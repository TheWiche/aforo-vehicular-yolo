"""
movimiento.py
=============
Analisis de MOVIMIENTO sobre la ROI con tecnicas clasicas de procesamiento de
imagenes. Es la segunda "pierna" del sistema: YOLO (una CNN) dice QUE hay y
DONDE; este modulo dice si lo que hay SE ESTA MOVIENDO, lo que permite detectar
trafico detenido o congestionado (alerta util para el cliente).

Tecnicas del curso que se usan aqui (identificadas tambien en docs/TECNICAS.md)
-------------------------------------------------------------------------------
1. OPERACIONES ARITMETICAS entre imagenes
     * resta absoluta  D = |I - B|      (cv2.absdiff)
     * promedio movil  B = (1-a)*B + a*I (cv2.accumulateWeighted)
   B es un "modelo del fondo": una imagen que se va actualizando lentamente con
   el promedio ponderado de los frames. Lo que difiere de B es lo que cambio.
2. UMBRALIZACION (cv2.threshold)
   D es una imagen en escala de grises con "cuanto cambio" cada pixel. Se
   binariza: pixel > umbral => 255 (en movimiento), si no => 0. El umbral
   separa el cambio real (un vehiculo) del ruido del sensor y de la luz.
3. MORFOLOGIA matematica (cv2.morphologyEx)
   * APERTURA = erosion seguida de dilatacion: elimina manchas pequenas
     aisladas (ruido de 1-2 pixeles) sin encoger las regiones grandes.
   * CIERRE   = dilatacion seguida de erosion: rellena huecos dentro de un
     vehiculo (reflejos, ventanas) para que sea una sola region compacta.

Por que el fondo es un promedio movil y no el primer frame
----------------------------------------------------------
Con a pequeno (0.02) el fondo "aprende" despacio: un vehiculo que PASA deja
poca huella en B y se detecta como cambio; un vehiculo que se DETIENE se va
absorbiendo en B (en unos ~1/a frames, 2 s a 25 FPS) y su diferencia tiende a 0.
Esa es justamente la senal que se busca: "hay vehiculos pero no hay cambio".

Limitaciones (ver docs/CASOS_DE_FALLA.md): requiere camara fija; los vehiculos
presentes en el primer frame quedan "dentro" del fondo y al irse dejan un
fantasma durante un par de segundos, por eso hay un periodo de calentamiento.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

from config import MovimientoConfig


@dataclass(frozen=True)
class ResultadoMovimiento:
    """Medidas de movimiento de un frame."""
    ratio_roi: float                        # fraccion de la ROI en movimiento (0..1)
    ratio_en_vehiculos: Optional[float]     # fraccion de las cajas (dentro de la ROI) en movimiento; None si no hay cajas
    mascara: np.ndarray                     # mascara binaria (reducida) tras umbral + morfologia


class DetectorMovimiento:
    """Mantiene el modelo de fondo y produce la mascara de movimiento de cada frame."""

    def __init__(
        self,
        config: MovimientoConfig,
        roi_poligono: np.ndarray,
        resolucion_wh: Tuple[int, int],
    ) -> None:
        self._cfg = config
        ancho, alto = resolucion_wh
        # Trabajar con una version reducida acelera todo (4K tiene 8 millones de
        # pixeles; a escala 0.25 de cada lado son ~0.5 millones) sin perder lo
        # esencial: solo interesa saber SI hay cambio, no su detalle fino.
        self._ancho_s = max(int(round(ancho * config.escala)), 8)
        self._alto_s = max(int(round(alto * config.escala)), 8)
        self._factor_x = self._ancho_s / ancho
        self._factor_y = self._alto_s / alto

        self._fondo: Optional[np.ndarray] = None      # modelo de fondo B (float32)
        self._nucleo_apertura = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (config.kernel_apertura, config.kernel_apertura)
        )
        self._nucleo_cierre = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (config.kernel_cierre, config.kernel_cierre)
        )

        # Mascara de la ROI en la escala reducida (se calcula una sola vez).
        poligono_s = (roi_poligono.astype(np.float64) * [self._factor_x, self._factor_y]).astype(np.int32)
        self._mascara_roi = np.zeros((self._alto_s, self._ancho_s), dtype=np.uint8)
        cv2.fillPoly(self._mascara_roi, [poligono_s], 255)
        self._area_roi = int(np.count_nonzero(self._mascara_roi))

    # ------------------------------------------------------------------ API
    def actualizar(self, frame_bgr: np.ndarray, cajas_xyxy: Optional[np.ndarray] = None) -> ResultadoMovimiento:
        """
        Procesa un frame: devuelve la mascara de movimiento y sus razones.

        Parameters
        ----------
        cajas_xyxy : cajas de los vehiculos seguidos (en pixeles del frame original),
            para medir cuanto movimiento hay DENTRO de los vehiculos.
        """
        pequeno = cv2.resize(frame_bgr, (self._ancho_s, self._alto_s), interpolation=cv2.INTER_AREA)
        gris = cv2.cvtColor(pequeno, cv2.COLOR_BGR2GRAY)

        if self._fondo is None:
            self._fondo = gris.astype(np.float32)     # el primer frame inicializa B

        # --- 1) Operaciones aritmeticas -------------------------------------
        # D = |I - B|. B es float32; se pasa a uint8 para poder restar con OpenCV.
        diferencia = cv2.absdiff(gris, cv2.convertScaleAbs(self._fondo))
        # B <- (1 - alfa) * B + alfa * I   (promedio movil exponencial del fondo)
        cv2.accumulateWeighted(gris, self._fondo, self._cfg.alfa_fondo)

        # --- 2) Umbralizacion -----------------------------------------------
        _, binaria = cv2.threshold(diferencia, self._cfg.umbral_diferencia, 255, cv2.THRESH_BINARY)

        # --- 3) Morfologia: apertura (quita ruido) y cierre (rellena huecos) -
        binaria = cv2.morphologyEx(binaria, cv2.MORPH_OPEN, self._nucleo_apertura)
        binaria = cv2.morphologyEx(binaria, cv2.MORPH_CLOSE, self._nucleo_cierre)

        # --- Razones de movimiento dentro de la ROI -------------------------
        en_roi = cv2.bitwise_and(binaria, self._mascara_roi)
        ratio_roi = float(np.count_nonzero(en_roi)) / self._area_roi if self._area_roi else 0.0

        ratio_vehiculos: Optional[float] = None
        if cajas_xyxy is not None and len(cajas_xyxy) > 0:
            cajas = np.zeros_like(binaria)
            for x1, y1, x2, y2 in cajas_xyxy:
                p1 = (int(x1 * self._factor_x), int(y1 * self._factor_y))
                p2 = (int(x2 * self._factor_x), int(y2 * self._factor_y))
                cv2.rectangle(cajas, p1, p2, 255, thickness=-1)
            cajas_en_roi = cv2.bitwise_and(cajas, self._mascara_roi)
            area_cajas = int(np.count_nonzero(cajas_en_roi))
            if area_cajas > 0:
                movimiento_en_cajas = cv2.bitwise_and(binaria, cajas_en_roi)
                ratio_vehiculos = float(np.count_nonzero(movimiento_en_cajas)) / area_cajas

        return ResultadoMovimiento(ratio_roi=ratio_roi, ratio_en_vehiculos=ratio_vehiculos, mascara=binaria)

    def contar_vehiculos_en_roi(self, puntos_xy: np.ndarray) -> int:
        """Cuantos de los puntos (anclas de vehiculos, en pixeles originales) caen dentro de la ROI."""
        dentro = 0
        for x, y in puntos_xy:
            xs, ys = int(x * self._factor_x), int(y * self._factor_y)
            if 0 <= xs < self._ancho_s and 0 <= ys < self._alto_s and self._mascara_roi[ys, xs] > 0:
                dentro += 1
        return dentro
