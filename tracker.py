"""
tracker.py
==========
Capa de SEGUIMIENTO (tracking): asigna un ID unico y persistente a cada
vehiculo a lo largo del video y construye su trayectoria.

Por que hace falta un tracker
-----------------------------
YOLO procesa cada frame de forma INDEPENDIENTE: no sabe que el "auto" del
frame 10 es el mismo "auto" del frame 11. Sin identidad no se puede:
  * contar un vehiculo una sola vez (si no, se contaria en cada frame),
  * medir cuanto tiempo tarda un mismo vehiculo en recorrer la ROI.

ByteTrack en pocas palabras
---------------------------
1. Un filtro de Kalman PREDICE donde deberia estar cada track en el frame actual
   (modelo de movimiento).
2. Se EMPAREJAN predicciones con detecciones usando IoU (solapamiento de cajas)
   y el algoritmo hungaro/Jonker-Volgenant (asignacion optima).
3. Lo distintivo de ByteTrack: las detecciones de BAJA confianza NO se tiran;
   se usan en una segunda ronda para rescatar tracks ocluidos (p. ej. un auto
   parcialmente tapado por un camion). Eso reduce los cambios de ID.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np
import supervision as sv
from trackers import ByteTrackTracker

from config import TrackerConfig
from geometry import Point

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Movement:
    """
    Desplazamiento de un vehiculo entre dos observaciones consecutivas.

    Es el "contrato" entre el tracker y los modulos de conteo y velocidad:
    ellos no necesitan saber nada de YOLO ni de ByteTrack, solo reciben
    "el vehiculo X paso del punto P al punto Q entre el frame i y el frame j".

    `prev_frame` puede ser anterior a `curr_frame - 1` si el vehiculo estuvo
    ocluido unos frames y ByteTrack lo recupero con el mismo ID.
    """
    track_id: int
    class_id: int
    prev_point: Point
    curr_point: Point
    prev_frame: int
    curr_frame: int


@dataclass
class _TrackState:
    """Memoria interna por vehiculo (ultima posicion y votos de clase)."""
    last_point: Point
    last_frame: int
    class_votes: Counter = field(default_factory=Counter)


class VehicleTracker:
    """
    Envuelve ByteTrack y le agrega tres responsabilidades propias:

    1. Descartar detecciones aun no confirmadas (tracker_id = -1).
    2. Estabilizar la CLASE de cada ID por votacion mayoritaria.
    3. Recordar la posicion previa de cada ID para producir objetos `Movement`.
    """

    def __init__(self, config: TrackerConfig, fps: float) -> None:
        self._config = config
        self._fps = fps
        self._anchor = sv.Position(config.ancla)

        # `frame_rate` permite a ByteTrack convertir `track_buffer` (expresado
        # en "frames a 30 FPS") a la cantidad real de frames para este video:
        #     frames_maximos_perdido = fps / 30 * track_buffer
        self._bytetrack = self._crear_bytetrack()

        # Un ID que lleva mas frames que este limite sin aparecer ya no puede
        # ser recuperado por ByteTrack: se libera su memoria (evita fugas).
        self._max_frames_sin_ver = int(config.track_buffer * max(fps, 1.0) / 30.0) + 2
        self._estados: Dict[int, _TrackState] = {}

    def _crear_bytetrack(self) -> ByteTrackTracker:
        return ByteTrackTracker(
            lost_track_buffer=self._config.track_buffer,
            frame_rate=self._fps,
            track_activation_threshold=self._config.umbral_activacion,
            minimum_consecutive_frames=self._config.frames_consecutivos,
            minimum_iou_threshold=self._config.umbral_iou,
            high_conf_det_threshold=self._config.umbral_alta_confianza,
        )

    def reset(self) -> None:
        """Reinicia IDs y memoria (util al procesar otro video)."""
        self._bytetrack = self._crear_bytetrack()
        self._estados.clear()

    def update(
        self, detections: sv.Detections, frame_idx: int
    ) -> Tuple[sv.Detections, List[Movement]]:
        """
        Procesa las detecciones de un frame.

        Returns
        -------
        (tracked, movimientos)
            tracked     : `sv.Detections` con `tracker_id` valido y `class_id`
                          estabilizado (listo para dibujar).
            movimientos : un `Movement` por cada vehiculo que ya tenia
                          historial (los recien aparecidos no tienen "previo").
        """
        tracked = self._bytetrack.update(detections)

        # ByteTrack asigna tracker_id = -1 a objetos aun no confirmados: se
        # excluyen para no contar falsos positivos de un solo frame.
        if len(tracked) == 0 or tracked.tracker_id is None:
            self._limpiar_estados(frame_idx)
            return sv.Detections.empty(), []
        tracked = tracked[tracked.tracker_id != -1]
        if len(tracked) == 0:
            self._limpiar_estados(frame_idx)
            return tracked, []

        puntos = tracked.get_anchors_coordinates(self._anchor)
        clases_estables = np.empty(len(tracked), dtype=int)
        movimientos: List[Movement] = []

        for i, (tid, cid, pt) in enumerate(
            zip(tracked.tracker_id, tracked.class_id, puntos)
        ):
            tid, cid = int(tid), int(cid)
            punto: Point = (float(pt[0]), float(pt[1]))

            estado = self._estados.get(tid)
            if estado is None:
                estado = _TrackState(last_point=punto, last_frame=frame_idx)
                self._estados[tid] = estado
                estado.class_votes[cid] += 1
                clases_estables[i] = cid
                continue

            # --- Votacion de clase ------------------------------------------
            # YOLO puede alternar entre "car" y "truck" para el mismo vehiculo
            # en frames distintos. Si contaramos con la clase instantanea, un
            # mismo auto podria sumar a dos categorias. La clase mas votada a
            # lo largo de la vida del ID es mucho mas estable.
            estado.class_votes[cid] += 1
            clase_final = estado.class_votes.most_common(1)[0][0]
            clases_estables[i] = clase_final

            movimientos.append(
                Movement(
                    track_id=tid,
                    class_id=clase_final,
                    prev_point=estado.last_point,
                    curr_point=punto,
                    prev_frame=estado.last_frame,
                    curr_frame=frame_idx,
                )
            )
            estado.last_point = punto
            estado.last_frame = frame_idx

        tracked.class_id = clases_estables
        self._limpiar_estados(frame_idx)
        return tracked, movimientos

    def _limpiar_estados(self, frame_idx: int) -> None:
        """Elimina la memoria de IDs que ya no volveran a aparecer."""
        caducados = [
            tid for tid, e in self._estados.items()
            if frame_idx - e.last_frame > self._max_frames_sin_ver
        ]
        for tid in caducados:
            del self._estados[tid]
