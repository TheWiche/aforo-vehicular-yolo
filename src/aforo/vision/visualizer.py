"""
visualizer.py
=============
Capa de VISUALIZACION: dibuja sobre cada frame todo lo que el sistema "piensa".

Elementos dibujados
-------------------
  * Cajas delimitadoras coloreadas por tipo de vehiculo.
  * Etiqueta por vehiculo:  #ID  Clase  |  velocidad (km/h)
  * Estela (trayectoria reciente) de cada vehiculo.
  * Linea de conteo con la flecha del "Sentido A".
  * ROI de velocidad (lineas A y B + distancia real).
  * Panel de aforo con el conteo por tipo, el total y los sentidos.

Se usa la libreria `supervision` para cajas, etiquetas y estelas (API limpia y
mantenida) y OpenCV directamente para el panel y las lineas, que requieren
control fino del dibujo.

Escalado por resolucion
-----------------------
Un grosor de 2 px se ve bien en 720p pero casi invisible en 4K. Todos los
tamaños se multiplican por un factor `k` proporcional a la altura del video
para que el resultado se vea igual de bien en cualquier resolucion.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import cv2
import numpy as np
import supervision as sv

from aforo.config import CounterConfig, SpeedConfig, VisualConfig
from aforo.analitica.geometry import Point, poligono_entre_lineas
from aforo.analitica.line_counter import CrossingEvent, LineCounter
from aforo.analitica.speed_estimator import SpeedEstimator

# Colores fijos en formato BGR (el que usa OpenCV).
_COLOR_LINEA_CONTEO: Tuple[int, int, int] = (0, 215, 255)     # amarillo-dorado
_COLOR_LINEA_FLASH: Tuple[int, int, int] = (255, 255, 255)    # blanco al contar
_COLOR_ROI: Tuple[int, int, int] = (255, 0, 200)              # magenta
_COLOR_PANEL: Tuple[int, int, int] = (28, 24, 22)
_COLOR_TEXTO: Tuple[int, int, int] = (245, 245, 245)
_COLOR_TEXTO_SUAVE: Tuple[int, int, int] = (170, 170, 170)
_COLOR_ACENTO: Tuple[int, int, int] = (0, 215, 255)
_COLOR_ALERTA: Tuple[int, int, int] = (25, 178, 250)          # ambar (BGR) para "trafico detenido"

_FUENTE: int = cv2.FONT_HERSHEY_DUPLEX
# Frames que la linea de conteo permanece "encendida" tras un cruce.
_FRAMES_FLASH: int = 6


class Visualizer:
    """Dibuja el estado del sistema sobre los frames de salida."""

    def __init__(
        self,
        visual: VisualConfig,
        counter_cfg: CounterConfig,
        speed_cfg: SpeedConfig,
        class_names: Dict[int, str],
        ancla: str,
        resolution_wh: Tuple[int, int],
        limite_kmh: float = 0.0,
    ) -> None:
        self._visual = visual
        self._counter_cfg = counter_cfg
        self._speed_cfg = speed_cfg
        self._class_names = class_names
        self._limite_kmh = limite_kmh           # 0 = no marcar excesos de velocidad
        self._flash_restante = 0

        ancho, alto = resolution_wh
        # Factor de escala respecto a un video de referencia de 1080 px de alto.
        self._k: float = max(alto / 1080.0, 0.6)

        # --- Paleta indexada por class_id (COCO usa ids 2,3,5,7: el resto
        #     de posiciones se rellenan con gris y nunca se usan).
        n = max(class_names) + 1
        self._colores_clase: Dict[int, sv.Color] = {
            cid: sv.Color.from_hex(visual.colores_clase.get(cid, "#95A5A6"))
            for cid in class_names
        }
        paleta = sv.ColorPalette(
            [self._colores_clase.get(i, sv.Color.from_hex("#95A5A6")) for i in range(n)]
        )

        grosor = max(2, int(round(2 * self._k)))
        escala_texto = sv.calculate_optimal_text_scale(resolution_wh) * 0.8
        self._box = sv.BoxAnnotator(color=paleta, thickness=grosor, color_lookup=sv.ColorLookup.CLASS)
        self._label = sv.LabelAnnotator(
            color=paleta,
            text_color=sv.Color.WHITE,
            text_scale=escala_texto,
            text_thickness=max(1, grosor - 1),
            text_padding=max(4, int(6 * self._k)),
            text_position=sv.Position.TOP_LEFT,
            color_lookup=sv.ColorLookup.CLASS,
        )
        self._trace = sv.TraceAnnotator(
            color=paleta,
            position=sv.Position(ancla),
            trace_length=visual.largo_estela,
            thickness=grosor,
            color_lookup=sv.ColorLookup.CLASS,
        )

        self._poligono_roi = self._construir_poligono_roi(speed_cfg)
        self._preparar_relleno_roi(ancho, alto)

    def _preparar_relleno_roi(self, ancho: int, alto: int) -> None:
        """
        Pre-calcula (una sola vez) la mascara y el color de relleno de la ROI.
        Hacerlo por frame en un video 4K desperdiciaria mucho tiempo de CPU.
        """
        x, y, w, h = cv2.boundingRect(self._poligono_roi)
        # Recorte al area visible del frame.
        x0, y0 = max(x, 0), max(y, 0)
        x1, y1 = min(x + w, ancho), min(y + h, alto)
        self._roi_rect: Tuple[int, int, int, int] = (x0, y0, x1, y1)

        mascara = np.zeros((alto, ancho), dtype=np.uint8)
        cv2.fillPoly(mascara, [self._poligono_roi], 255)
        recorte = mascara[y0:y1, x0:x1].astype(bool)
        self._roi_mascara = np.repeat(recorte[:, :, None], 3, axis=2)
        self._roi_color = np.full((max(y1 - y0, 0), max(x1 - x0, 0), 3), _COLOR_ROI, dtype=np.uint8)

    # ------------------------------------------------------------------ API
    def render(
        self,
        frame: np.ndarray,
        detections: sv.Detections,
        counter: LineCounter,
        speed: SpeedEstimator,
        eventos: Sequence[CrossingEvent],
        estado_trafico: str = "",
    ) -> np.ndarray:
        """
        Dibuja todo sobre `frame` (se modifica EN SITIO para ahorrar memoria:
        un frame 4K ocupa ~25 MB y copiarlo en cada iteracion es costoso).
        """
        if eventos:
            self._flash_restante = _FRAMES_FLASH

        self._dibujar_roi_velocidad(frame)
        self._dibujar_linea_conteo(frame)

        if len(detections) > 0 and detections.tracker_id is not None:
            if self._visual.dibujar_estela:
                frame = self._trace.annotate(frame, detections)
            frame = self._box.annotate(frame, detections)
            frame = self._label.annotate(frame, detections, labels=self._etiquetas(detections, speed))

        self._dibujar_panel(frame, counter, estado_trafico)

        if self._flash_restante > 0:
            self._flash_restante -= 1
        return frame

    # ------------------------------------------------------------ etiquetas
    def _etiquetas(self, detections: sv.Detections, speed: SpeedEstimator) -> List[str]:
        """Texto sobre cada vehiculo:  '#12 Auto | 54 km/h'."""
        etiquetas: List[str] = []
        for tid, cid in zip(detections.tracker_id, detections.class_id):
            tid, cid = int(tid), int(cid)
            texto = f"#{tid} {self._class_names.get(cid, '?')}"
            velocidad = speed.speed_of(tid)
            if velocidad is not None:
                texto += f" | {velocidad:.0f} km/h"
                if self._limite_kmh > 0 and velocidad > self._limite_kmh:
                    texto += " EXCESO"        # supera el limite configurado (genera alerta en la BD)
            elif speed.is_measuring(tid):
                texto += " | midiendo..."
            etiquetas.append(texto)
        return etiquetas

    # ------------------------------------------------------- lineas y zonas
    @staticmethod
    def _construir_poligono_roi(cfg: SpeedConfig) -> np.ndarray:
        """Cuadrilatero de la ROI (ver `geometry.poligono_entre_lineas`) como arreglo de enteros."""
        return np.array(poligono_entre_lineas(cfg.linea_a, cfg.linea_b), dtype=np.int32)

    def _dibujar_roi_velocidad(self, frame: np.ndarray) -> None:
        """Rellena la ROI en translucido y marca sus dos lineas."""
        k = self._k

        # Relleno translucido: se mezcla (alpha 0.12) SOLO el rectangulo que
        # contiene a la ROI y se copia unicamente donde la mascara es verdadera.
        x0, y0, x1, y1 = self._roi_rect
        sub = frame[y0:y1, x0:x1]
        if sub.size:
            mezcla = cv2.addWeighted(sub, 0.88, self._roi_color, 0.12, 0)
            np.copyto(sub, mezcla, where=self._roi_mascara)

        grosor = max(2, int(round(3 * k)))
        for nombre, (p, q) in (("A", self._speed_cfg.linea_a), ("B", self._speed_cfg.linea_b)):
            p_i, q_i = (int(p[0]), int(p[1])), (int(q[0]), int(q[1]))
            cv2.line(frame, p_i, q_i, _COLOR_ROI, grosor, cv2.LINE_AA)
            self._texto_con_fondo(frame, f"LINEA {nombre}", (p_i[0] + 8, p_i[1] - 8), 0.55 * k, _COLOR_ROI)

        # Etiqueta con la distancia real, pegada al borde izquierdo de la ROI
        # (punto medio entre los extremos izquierdos de A y B) para no tapar
        # la flecha de sentido que se dibuja en el centro de la via.
        borde = (self._poligono_roi[0] + self._poligono_roi[3]) / 2.0
        self._texto_con_fondo(
            frame, f"ROI {self._speed_cfg.distancia_metros:g} m",
            (int(borde[0]) + int(24 * k), int(borde[1])), 0.6 * k, _COLOR_ROI,
        )

    def _dibujar_linea_conteo(self, frame: np.ndarray) -> None:
        """Dibuja la linea de conteo y una flecha que indica el 'Sentido A'."""
        k = self._k
        p, q = self._counter_cfg.linea
        p_i, q_i = (int(p[0]), int(p[1])), (int(q[0]), int(q[1]))

        activa = self._flash_restante > 0
        color = _COLOR_LINEA_FLASH if activa else _COLOR_LINEA_CONTEO
        grosor = max(2, int(round((6 if activa else 4) * k)))

        cv2.line(frame, p_i, q_i, color, grosor, cv2.LINE_AA)
        cv2.circle(frame, p_i, int(7 * k), color, -1, cv2.LINE_AA)
        cv2.circle(frame, q_i, int(7 * k), color, -1, cv2.LINE_AA)
        self._texto_con_fondo(frame, "LINEA DE CONTEO", (p_i[0] + 10, p_i[1] - int(14 * k)), 0.6 * k, color)

        # Flecha del Sentido A. En la convencion de geometry.segment_intersection,
        # el sentido A es el que cruza de la mano derecha a la izquierda de la
        # linea orientada p -> q (vista en pantalla). Si d = q - p, el vector
        # hacia la izquierda en coordenadas de imagen (eje y hacia abajo) es
        # (dy, -dx).
        dx, dy = q[0] - p[0], q[1] - p[1]
        norma = max((dx * dx + dy * dy) ** 0.5, 1e-9)
        nx, ny = dy / norma, -dx / norma
        medio = ((p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0)
        largo = 70 * k
        inicio = (int(medio[0] - nx * largo / 2), int(medio[1] - ny * largo / 2))
        fin = (int(medio[0] + nx * largo / 2), int(medio[1] + ny * largo / 2))
        cv2.arrowedLine(frame, inicio, fin, color, max(2, int(3 * k)), cv2.LINE_AA, tipLength=0.35)
        self._texto_con_fondo(frame, "A", (fin[0] + int(8 * k), fin[1]), 0.6 * k, color)

    # ---------------------------------------------------------------- panel
    def _dibujar_panel(self, frame: np.ndarray, counter: LineCounter, estado_trafico: str = "") -> None:
        """Panel translucido (esquina superior izquierda) con el aforo."""
        k = self._k
        margen = int(20 * k)
        ancho = int(360 * k)
        alto_fila = int(38 * k)
        n_clases = len(self._class_names)
        alto = int((120 + 38 * n_clases + 70 + (30 if estado_trafico else 0)) * k)

        x0, y0 = margen, margen
        x1, y1 = x0 + ancho, y0 + alto

        # --- Fondo translucido: mezcla del color del panel con el contenido
        #     del frame (alpha 0.70) para que el video siga insinuandose detras.
        zona = frame[y0:y1, x0:x1]
        fondo = np.full_like(zona, _COLOR_PANEL)
        cv2.addWeighted(fondo, 0.70, zona, 0.30, 0, dst=zona)
        # Barra de acento a la izquierda.
        cv2.rectangle(frame, (x0, y0), (x0 + int(6 * k), y1), _COLOR_ACENTO, -1)

        pad = int(24 * k)
        x_texto = x0 + pad
        x_der = x1 - pad
        y = y0 + int(38 * k)

        # --- Titulo --------------------------------------------------------
        self._texto(frame, "AFORO VEHICULAR", (x_texto, y), 0.75 * k, _COLOR_TEXTO, max(1, int(2 * k)))
        y += int(16 * k)
        cv2.line(frame, (x_texto, y), (x_der, y), _COLOR_TEXTO_SUAVE, 1, cv2.LINE_AA)
        y += int(14 * k)

        # --- Una fila por tipo de vehiculo ---------------------------------
        for cid, nombre in self._class_names.items():
            y += alto_fila
            color = self._colores_clase[cid].as_bgr()
            lado = int(16 * k)
            cv2.rectangle(frame, (x_texto, y - lado), (x_texto + lado, y), color, -1)
            self._texto(frame, nombre, (x_texto + lado + int(14 * k), y), 0.65 * k, _COLOR_TEXTO, 1)
            self._texto(
                frame, str(counter.counts_by_class.get(cid, 0)), (x_der, y),
                0.75 * k, _COLOR_TEXTO, max(1, int(2 * k)), alinear_derecha=True,
            )

        # --- Total ----------------------------------------------------------
        y += int(16 * k)
        cv2.line(frame, (x_texto, y), (x_der, y), _COLOR_TEXTO_SUAVE, 1, cv2.LINE_AA)
        y += int(46 * k)
        self._texto(frame, "TOTAL", (x_texto, y), 0.85 * k, _COLOR_ACENTO, max(1, int(2 * k)))
        self._texto(
            frame, str(counter.total), (x_der, y), 1.3 * k, _COLOR_ACENTO,
            max(2, int(3 * k)), alinear_derecha=True,
        )

        # --- Sentidos de circulacion ---------------------------------------
        y += int(34 * k)
        resumen = (
            f"{self._counter_cfg.etiqueta_a}: {counter.counts_by_direction['A']}   "
            f"{self._counter_cfg.etiqueta_b}: {counter.counts_by_direction['B']}"
        )
        self._texto(frame, resumen, (x_texto, y), 0.5 * k, _COLOR_TEXTO_SUAVE, 1)

        # --- Estado del trafico (analisis de movimiento en la ROI) ----------
        if estado_trafico:
            y += int(30 * k)
            color = _COLOR_ALERTA if estado_trafico == "DETENIDO" else _COLOR_TEXTO
            self._texto(frame, f"Trafico: {estado_trafico}", (x_texto, y), 0.55 * k, color, 1)

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _texto(
        frame: np.ndarray, texto: str, origen: Tuple[int, int], escala: float,
        color: Tuple[int, int, int], grosor: int = 1, alinear_derecha: bool = False,
    ) -> None:
        """Escribe texto antialias; opcionalmente alineado a la derecha."""
        x, y = origen
        if alinear_derecha:
            (ancho, _), _ = cv2.getTextSize(texto, _FUENTE, escala, grosor)
            x -= ancho
        cv2.putText(frame, texto, (x, y), _FUENTE, escala, color, grosor, cv2.LINE_AA)

    @classmethod
    def _texto_con_fondo(
        cls, frame: np.ndarray, texto: str, origen: Point, escala: float,
        color: Tuple[int, int, int],
    ) -> None:
        """Texto con un recuadro oscuro detras para que se lea sobre cualquier fondo."""
        grosor = max(1, int(round(escala * 2)))
        (ancho, alto), base = cv2.getTextSize(texto, _FUENTE, escala, grosor)
        x, y = int(origen[0]), int(origen[1])
        pad = 4
        cv2.rectangle(frame, (x - pad, y - alto - pad), (x + ancho + pad, y + base + pad), _COLOR_PANEL, -1)
        cv2.putText(frame, texto, (x, y), _FUENTE, escala, color, grosor, cv2.LINE_AA)
