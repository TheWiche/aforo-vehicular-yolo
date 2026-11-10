"""
pipeline.py
===========
ORQUESTADOR: conecta todas las etapas en el orden correcto y recorre el video.

Flujo de datos por cada frame
-----------------------------

    frame --> [VehicleDetector] --> detecciones (cajas, clase, confianza)
          --> [VehicleTracker]  --> detecciones con ID + lista de Movement
          --> [LineCounter]     --> cruces de la linea de conteo (aforo)
          --> [SpeedEstimator]  --> mediciones de velocidad (km/h)
          --> [DetectorMovimiento + MonitorTrafico] --> estado de la via y alertas
          --> [RegistradorCruces] --> INSERT en SQLite (datos/db/database.db)
          --> [Visualizer]      --> frame anotado --> archivo de video

Cada etapa solo conoce la salida de la anterior (bajo acoplamiento), por lo
que se puede reemplazar una pieza (p. ej. cambiar YOLOv8 por otro detector)
sin tocar las demas.
"""

from __future__ import annotations

import logging
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import cv2
import numpy as np
import supervision as sv
from tqdm import tqdm

from aforo.analitica.alertas import (
    TIPO_EXCESO_VELOCIDAD,
    TIPO_TRAFICO_DETENIDO,
    EstadoTrafico,
    MonitorTrafico,
    supera_limite,
)
from aforo.config import AppConfig
from aforo.persistencia.db import CrucesDB, RegistradorCruces
from aforo.vision.detector import VehicleDetector
from aforo.analitica.geometry import Point, poligono_entre_lineas
from aforo.analitica.line_counter import LineCounter
from aforo.vision.movimiento import DetectorMovimiento
from aforo.analitica.speed_estimator import SpeedEstimator, SpeedMeasurement
from aforo.vision.tracker import VehicleTracker
from aforo.vision.visualizer import Visualizer

logger = logging.getLogger(__name__)

# FPS de respaldo si el contenedor de video no reporta un valor valido.
_FPS_POR_DEFECTO: float = 30.0


class VideoError(RuntimeError):
    """Se lanza si el video de entrada no se puede abrir o leer."""


@dataclass
class PipelineSummary:
    """Resumen final de la ejecucion (lo imprime aforo procesar)."""
    frames_procesados: int = 0
    frames_saltados: int = 0   # solo en tiempo real: cuadros que no se analizaron para no atrasarse
    segundos_proceso: float = 0.0
    conteo_por_clase: Dict[str, int] = field(default_factory=dict)
    conteo_por_sentido: Dict[str, int] = field(default_factory=dict)
    total: int = 0
    mediciones: List[SpeedMeasurement] = field(default_factory=list)
    video_salida: Optional[Path] = None
    db_ruta: Optional[Path] = None
    camara: str = ""
    filas_db: int = 0          # cruces insertados en la base de datos en esta ejecucion
    alertas_exceso: int = 0    # alertas EXCESO_VELOCIDAD registradas
    alertas_detenido: int = 0  # alertas TRAFICO_DETENIDO registradas


class _ControlVia:
    """
    Vigila el estado de la via dentro de la ROI en cada frame.

    Combina YOLO (cuantos vehiculos hay en la ROI) con el analisis de movimiento
    (`DetectorMovimiento`: cuanto cambia la imagen dentro de ellos) y guarda en la
    base de datos las lecturas periodicas y las alertas de trafico detenido.
    """

    def __init__(
        self,
        cfg: AppConfig,
        db: CrucesDB,
        resolucion_wh: Tuple[int, int],
        inicio_video: datetime,
    ) -> None:
        self._cfg = cfg
        self._db = db
        self._inicio = inicio_video
        roi = np.array(poligono_entre_lineas(cfg.speed.linea_a, cfg.speed.linea_b), dtype=np.int32)
        self._movimiento = DetectorMovimiento(cfg.movimiento, roi, resolucion_wh)
        self._monitor = MonitorTrafico(cfg.alertas)
        self._ancla = sv.Position(cfg.tracker.ancla)
        self.alertas_detenido = 0

        # Acumuladores de la lectura periodica (promedio de lo ocurrido en el intervalo).
        self._proxima_lectura_s = cfg.alertas.intervalo_lectura_s
        self._suma_vehiculos = 0.0
        self._suma_ratio = 0.0
        self._muestras = 0

    def procesar(self, frame: np.ndarray, seguidos: sv.Detections, idx: int, fps: float) -> EstadoTrafico:
        """Procesa un frame y devuelve el estado actual de la via."""
        hay = len(seguidos) > 0
        movimiento = self._movimiento.actualizar(frame, seguidos.xyxy if hay else None)
        anclas = seguidos.get_anchors_coordinates(self._ancla) if hay else np.empty((0, 2))
        vehiculos = self._movimiento.contar_vehiculos_en_roi(anclas)

        t_s = idx / fps
        momento = self._inicio + timedelta(seconds=t_s)
        act = self._monitor.actualizar(t_s, vehiculos, movimiento.ratio_en_vehiculos)

        if act.alerta_nueva:
            cfg = self._cfg.alertas
            self._db.insertar_alerta(
                camara=self._cfg.io.camara, momento=momento, tipo=TIPO_TRAFICO_DETENIDO, track_id=None,
                valor=float(vehiculos), umbral=float(cfg.detenido_min_vehiculos),
                descripcion=(f"{vehiculos} vehiculos en la ROI sin movimiento durante "
                             f"{cfg.detenido_segundos:g} s"),
            )
            self.alertas_detenido += 1

        self._suma_vehiculos += vehiculos
        self._suma_ratio += movimiento.ratio_roi
        self._muestras += 1
        if t_s >= self._proxima_lectura_s:
            self._db.insertar_lectura(
                self._cfg.io.camara, momento,
                self._suma_vehiculos / self._muestras, self._suma_ratio / self._muestras,
                act.estado.value,
            )
            self._suma_vehiculos = self._suma_ratio = 0.0
            self._muestras = 0
            self._proxima_lectura_s += self._cfg.alertas.intervalo_lectura_s
        return act.estado


class AforoPipeline:
    """Ejecuta el sistema completo de aforo y velocidad sobre un video."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    # ------------------------------------------------------------------ API
    def run(self, reemplazar_camara: bool = False) -> PipelineSummary:
        """
        Procesa el video completo.

        Parameters
        ----------
        reemplazar_camara : bool
            Si es True, borra antes de empezar los cruces previos de esta camara en
            la base de datos (util para repetir una prueba sin duplicar filas).
        """
        cfg = self._config
        info = self._leer_info_video(cfg.io.video_entrada)
        self._advertir_coordenadas_fuera_de_cuadro(info)

        # --- Construccion de las etapas (se hace una vez, no por frame) ----
        detector = VehicleDetector(cfg.detector)
        tracker = VehicleTracker(cfg.tracker, fps=info.fps)
        counter = LineCounter(cfg.counter, detector.class_names)
        speed = SpeedEstimator(cfg.speed, fps=info.fps)
        visualizer = Visualizer(
            visual=cfg.visual,
            counter_cfg=cfg.counter,
            speed_cfg=cfg.speed,
            class_names=detector.class_names,
            ancla=cfg.tracker.ancla,
            resolution_wh=(info.width, info.height),
            limite_kmh=cfg.alertas.limite_velocidad_kmh,
        )

        if cfg.io.video_salida is not None:
            cfg.io.video_salida.parent.mkdir(parents=True, exist_ok=True)
        mediciones: List[SpeedMeasurement] = []
        registrador: Optional[RegistradorCruces] = None
        control_via: Optional[_ControlVia] = None
        alertas_exceso = 0
        frames = 0
        ultimo_idx = -1
        tiempo_real = cfg.visual.tiempo_real
        t_inicio = time.perf_counter()

        # Hora real del primer frame: el `momento` de cada cruce se calcula a partir de ella.
        inicio_video = cfg.io.fecha_inicio or datetime.now()

        logger.info(
            "Procesando '%s' [camara: %s] (%dx%d @ %.2f FPS, %s frames)",
            cfg.io.video_entrada.name, cfg.io.camara, info.width, info.height, info.fps,
            info.total_frames if info.total_frames is not None else "?",
        )

        try:
            # `with CrucesDB(...)` garantiza que la conexion se cierre aunque ocurra un error.
            with CrucesDB(cfg.io.db_ruta) as db:
                if reemplazar_camara:
                    borradas = db.eliminar_camara(cfg.io.camara)
                    logger.info("Se borraron %d cruces previos de la camara '%s'.", borradas, cfg.io.camara)
                registrador = RegistradorCruces(db, cfg.io.camara)
                db.registrar_ejecucion(cfg.io.camara, cfg.io.video_entrada.name, inicio_video,
                                       info.fps, info.total_frames)
                control_via =_ControlVia(cfg, db, (info.width, info.height), inicio_video)

                # Con video_salida=None (modo rapido) no se escribe ni se codifica video: en 4K
                # eso es una parte grande del tiempo por frame.
                # En tiempo real tampoco: al saltar cuadros el archivo quedaria acelerado.
                guardar_video = cfg.io.video_salida is not None and not tiempo_real
                if tiempo_real and cfg.io.video_salida is not None:
                    logger.warning("En tiempo real no se guarda el video anotado (se saltan cuadros).")
                destino = sv.VideoSink(str(cfg.io.video_salida), info) if guardar_video else nullcontext()
                with destino as sink, \
                        tqdm(total=info.total_frames, unit="frame", desc="Procesando") as barra:
                    for idx, frame in self._cuadros(cfg.io.video_entrada, info.fps, tiempo_real):
                        # 1) Deteccion  2) Tracking  3) Conteo  4) Velocidad
                        detecciones = detector.detect(frame)
                        seguidos, movimientos = tracker.update(detecciones, frame_idx=idx)
                        nuevos_cruces = counter.update(movimientos)
                        nuevas_medidas = speed.update(movimientos)
                        mediciones.extend(nuevas_medidas)

                        # 5) Persistencia: INSERT apenas el vehiculo cruza la linea.
                        # Las velocidades se procesan primero: si el vehiculo cruza en este
                        # mismo frame, la fila nace completa con un solo INSERT.
                        for med in nuevas_medidas:
                            registrador.registrar_velocidad(med.track_id, med.speed_kmh)
                            # ALERTA de negocio: exceso de velocidad (ver alertas.py).
                            limite = cfg.alertas.limite_velocidad_kmh
                            if supera_limite(med.speed_kmh, limite):
                                tipo = detector.class_names[med.class_id]
                                db.insertar_alerta(
                                    camara=cfg.io.camara,
                                    momento=inicio_video + timedelta(seconds=med.frame / info.fps),
                                    tipo=TIPO_EXCESO_VELOCIDAD,
                                    track_id=med.track_id,
                                    valor=round(med.speed_kmh, 1),
                                    umbral=limite,
                                    descripcion=f"{tipo} a {med.speed_kmh:.1f} km/h (limite {limite:g} km/h)",
                                )
                                alertas_exceso += 1
                        for cruce in nuevos_cruces:
                            # Hora real del cruce = inicio del video + (frame / FPS) segundos.
                            momento = inicio_video + timedelta(seconds=cruce.frame / info.fps)
                            registrador.registrar_cruce(
                                track_id=cruce.track_id,     # ID que asigno ByteTrack
                                tipo=detector.class_names[cruce.class_id],
                                momento=momento,
                            )

                        # 6) Analisis de movimiento en la ROI: estado del trafico, alerta de
                        #    trafico detenido y lecturas periodicas (ver movimiento.py y alertas.py).
                        estado = control_via.procesar(frame, seguidos, idx, info.fps)

                        # 7) Dibujo y escritura del video anotado
                        # (sin video y sin ventana no hay nada que dibujar: se ahorra el trabajo)
                        anotado = frame
                        if sink is not None or cfg.visual.mostrar_ventana:
                            anotado = visualizer.render(
                                frame, seguidos, counter, speed, nuevos_cruces, estado_trafico=estado.value
                            )
                        if sink is not None:
                            sink.write_frame(anotado)
                        frames += 1
                        barra.set_postfix(total=counter.total, refresh=False)
                        barra.update(idx - ultimo_idx)      # incluye los cuadros saltados
                        ultimo_idx = idx

                        if cfg.visual.mostrar_ventana and not self._mostrar(anotado):
                            logger.info("Interrumpido por el usuario (tecla 'q').")
                            break
        except KeyboardInterrupt:
            logger.warning("Interrumpido con Ctrl+C: lo registrado hasta ahora ya esta en la base de datos.")
        finally:
            if cfg.visual.mostrar_ventana:
                cv2.destroyAllWindows()

        filas_db = registrador.insertados if registrador is not None else 0
        alertas_detenido = control_via.alertas_detenido if control_via is not None else 0

        return PipelineSummary(
            frames_procesados=frames,
            frames_saltados=max(0, ultimo_idx + 1 - frames),
            segundos_proceso=time.perf_counter() - t_inicio,
            conteo_por_clase={detector.class_names[c]: n for c, n in counter.counts_by_class.items()},
            conteo_por_sentido={
                counter.direction_label(d): n for d, n in counter.counts_by_direction.items()
            },
            total=counter.total,
            mediciones=mediciones,
            video_salida=None if tiempo_real else cfg.io.video_salida,
            db_ruta=cfg.io.db_ruta,
            camara=cfg.io.camara,
            filas_db=filas_db,
            alertas_exceso=alertas_exceso,
            alertas_detenido=alertas_detenido,
        )

    # -------------------------------------------------------------- interno
    @staticmethod
    def _cuadros(ruta: Path, fps: float, tiempo_real: bool) -> Iterator[Tuple[int, np.ndarray]]:
        """
        Entrega (indice, cuadro) del video.

        Modo normal: todos los cuadros, uno tras otro (lo mas preciso; tarda lo que tarde).

        Modo tiempo real: el video avanza con el reloj, como en un reproductor. Si analizar un
        cuadro tomo mas que 1/FPS, los cuadros que "ya pasaron" se saltan sin analizarlos
        (`grab()` los decodifica pero no los entrega); si la maquina va sobrada, se espera.
        El indice que se entrega es SIEMPRE el del video original, asi que las horas de los
        cruces y las velocidades (distancia / tiempo entre lineas) siguen siendo correctas:
        solo se pierde resolucion temporal, no se distorsiona el tiempo.
        """
        if not tiempo_real:
            yield from enumerate(sv.get_video_frames_generator(str(ruta)))
            return
        captura = cv2.VideoCapture(str(ruta))
        if not captura.isOpened():
            raise VideoError(f"No se pudo abrir el video '{ruta}'.")
        try:
            idx = -1
            inicio = time.perf_counter()
            while True:
                # Cuadro que un reproductor estaria mostrando en este instante.
                objetivo = int((time.perf_counter() - inicio) * fps)
                while idx + 1 < objetivo:              # atrasados: saltar hasta alcanzar al reloj
                    if not captura.grab():
                        return
                    idx += 1
                espera = (idx + 1) / fps - (time.perf_counter() - inicio)
                if espera > 0:                         # adelantados: esperar al siguiente cuadro
                    time.sleep(espera)
                ok, frame = captura.read()
                if not ok:
                    return
                idx += 1
                yield idx, frame
        finally:
            captura.release()

    @staticmethod
    def _leer_info_video(ruta: Path) -> sv.VideoInfo:
        """Valida que el video exista y lee su resolucion, FPS y numero de frames."""
        if not ruta.is_file():
            raise FileNotFoundError(
                f"No se encontro el video de entrada: {ruta}\n"
                "Edita VIDEO_ENTRADA en config.py o usa la opcion --video."
            )
        try:
            info = sv.VideoInfo.from_video_path(str(ruta))
        except Exception as exc:
            raise VideoError(f"No se pudo abrir el video '{ruta}': {exc}") from exc

        if info.fps is None or info.fps <= 0:
            # Sin FPS no se puede convertir frames a segundos => velocidad invalida.
            logger.warning("El video no reporta FPS; se asumen %.0f FPS.", _FPS_POR_DEFECTO)
            info = sv.VideoInfo(info.width, info.height, _FPS_POR_DEFECTO, info.total_frames)
        return info

    def _advertir_coordenadas_fuera_de_cuadro(self, info: sv.VideoInfo) -> None:
        """
        Avisa si alguna linea tiene puntos fuera del video: suele indicar que
        las coordenadas se tomaron de otra resolucion.
        """
        cfg = self._config
        grupos = {
            "LINEA_CONTEO": cfg.counter.linea,
            "LINEA_VELOCIDAD_A": cfg.speed.linea_a,
            "LINEA_VELOCIDAD_B": cfg.speed.linea_b,
        }
        for nombre, linea in grupos.items():
            for punto in linea:
                if not self._dentro(punto, info):
                    logger.warning(
                        "%s tiene el punto %s fuera del video (%dx%d). "
                        "Revisa que las coordenadas correspondan a esta resolucion.",
                        nombre, punto, info.width, info.height,
                    )
                    break

    @staticmethod
    def _dentro(punto: Point, info: sv.VideoInfo) -> bool:
        return 0 <= punto[0] <= info.width and 0 <= punto[1] <= info.height

    @staticmethod
    def _mostrar(frame) -> bool:
        """Muestra el frame en una ventana (reducido a 1280 px de ancho). False si se pulso 'q'."""
        alto, ancho = frame.shape[:2]
        if ancho > 1280:
            frame = cv2.resize(frame, (1280, int(alto * 1280 / ancho)))
        cv2.imshow("Aforo vehicular (q = salir)", frame)
        return (cv2.waitKey(1) & 0xFF) != ord("q")
