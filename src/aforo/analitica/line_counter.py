"""
line_counter.py
===============
Capa de CONTEO (aforo): cuenta cuantos vehiculos de cada tipo cruzan una linea
virtual y en que sentido.

Como se detecta un cruce
------------------------
Cada vehiculo llega como un `Movement` (posicion anterior -> posicion actual).
Hay cruce si ese segmento de trayectoria CORTA el segmento de la linea virtual
(ver `geometry.segment_intersection`).

Por que NO basta con comparar "esta por encima / por debajo de la linea"
------------------------------------------------------------------------
Comparar la posicion con la linea en cada frame obligaria a decidir cuando
"cuenta" un vehiculo que permanece sobre ella o que oscila por el ruido del
detector. Con la interseccion de segmentos el cruce es un EVENTO puntual y
bien definido; ademas, la regla "contar cada ID una sola vez" evita duplicados.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Set

from aforo.config import CounterConfig
from aforo.analitica.geometry import segment_intersection
from aforo.vision.tracker import Movement


@dataclass(frozen=True)
class CrossingEvent:
    """Registro de un vehiculo que acaba de cruzar la linea de conteo."""
    track_id: int
    class_id: int
    frame: int
    direction: str      # "A" o "B"


class LineCounter:
    """
    Contador de aforo por linea virtual.

    Mantiene:
      * `counts_by_class`     : total acumulado por tipo de vehiculo.
      * `counts_by_direction` : total acumulado por sentido de circulacion.
    """

    def __init__(self, config: CounterConfig, class_names: Dict[int, str]) -> None:
        self._config = config
        self._class_names = class_names

        # Inicializamos todas las clases en 0 para que el panel muestre
        # "Moto: 0" desde el primer frame, en lugar de omitirla.
        self.counts_by_class: Dict[int, int] = {cid: 0 for cid in class_names}
        self.counts_by_direction: Dict[str, int] = {"A": 0, "B": 0}

        # IDs ya contados: garantiza que cada vehiculo sume UNA sola vez,
        # aunque el ruido de deteccion lo haga "rebotar" sobre la linea.
        self._ids_contados: Set[int] = set()

    @property
    def total(self) -> int:
        """Total de vehiculos contados (suma de todas las clases)."""
        return sum(self.counts_by_class.values())

    def update(self, movimientos: Sequence[Movement]) -> List[CrossingEvent]:
        """
        Evalua los desplazamientos de un frame y devuelve los cruces nuevos.
        """
        eventos: List[CrossingEvent] = []
        p, q = self._config.linea

        for mov in movimientos:
            if mov.track_id in self._ids_contados:
                continue

            cruce = segment_intersection(mov.prev_point, mov.curr_point, p, q)
            if cruce is None:
                continue

            _, signo = cruce
            direccion = "A" if signo > 0 else "B"

            self._ids_contados.add(mov.track_id)
            self.counts_by_class[mov.class_id] = self.counts_by_class.get(mov.class_id, 0) + 1
            self.counts_by_direction[direccion] += 1
            eventos.append(
                CrossingEvent(
                    track_id=mov.track_id,
                    class_id=mov.class_id,
                    frame=mov.curr_frame,
                    direction=direccion,
                )
            )
        return eventos

    def direction_label(self, direccion: str) -> str:
        """Nombre legible del sentido ("A" o "B") definido en config.py."""
        return self._config.etiqueta_a if direccion == "A" else self._config.etiqueta_b
