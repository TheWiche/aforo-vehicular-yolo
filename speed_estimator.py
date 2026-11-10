"""
speed_estimator.py
==================
Capa de VELOCIDAD: estima los km/h de cada vehiculo midiendo cuanto tarda en
recorrer una ROI (region de interes) cuya longitud REAL en metros es conocida.

Fundamento fisico
-----------------
Velocidad media = distancia / tiempo.

  * distancia : la define el usuario en config.py (DISTANCIA_REAL_METROS) entre
                dos lineas virtuales A y B pintadas sobre la via.
  * tiempo    : se mide con el propio video. Un video NO tiene reloj, solo
                fotogramas numerados; pero sabemos que se graba a `fps`
                fotogramas POR SEGUNDO, por lo tanto:

                        tiempo [s] = numero_de_frames / fps

                Dividir entre los FPS convierte "frames" (unidad de la
                camara) en "segundos" (unidad del mundo real).

  * conversion: el resultado sale en m/s; para km/h se multiplica por 3.6
                porque 1 m/s = (1/1000 km) / (1/3600 h) = 3.6 km/h.

Por que dos lineas y no un poligono
-----------------------------------
Medir el cruce de dos lineas es independiente de la perspectiva: en la imagen
los pixeles NO equivalen a metros constantes (lo lejano se ve mas pequeño), pero
el INSTANTE en que el vehiculo toca cada linea si es una medida fiable. Asi
evitamos tener que convertir pixeles a metros (homografia); solo necesitamos
que la distancia real entre ambas lineas este bien medida.

Precision sub-frame
-------------------
El vehiculo casi nunca esta exactamente sobre la linea en un frame. Si solo
usaramos el frame en que "ya la paso", el error de tiempo seria de hasta 1
frame (40 ms a 25 FPS => varios km/h de error). Por eso se interpola: el
parametro `t` de la interseccion indica en que fraccion del trayecto entre dos
frames ocurrio el cruce, y se usa para refinar el instante.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from config import SpeedConfig
from geometry import segment_intersection
from tracker import Movement

logger = logging.getLogger(__name__)

# Factor de conversion m/s -> km/h (ver explicacion en el docstring del modulo).
_MS_A_KMH: float = 3.6


@dataclass(frozen=True)
class SpeedMeasurement:
    """Resultado de una medicion de velocidad completada."""
    track_id: int
    class_id: int
    speed_kmh: float
    elapsed_s: float        # tiempo que tardo en recorrer la ROI
    entry_line: str         # "A" o "B": por cual linea entro
    frame: int              # frame en que se completo la medicion


class SpeedEstimator:
    """
    Estimador de velocidad por tiempo de transito entre dos lineas.

    Maquina de estados por vehiculo:

        (sin datos) --cruza 1ra linea--> (midiendo) --cruza 2da linea--> (medido)

    El sistema reconoce automaticamente cual linea es la de entrada: la que el
    vehiculo cruce primero. Por eso funciona para ambos sentidos de circulacion.
    """

    def __init__(self, config: SpeedConfig, fps: float) -> None:
        if fps <= 0:
            raise ValueError("Los FPS del video deben ser positivos para medir tiempos.")
        self._config = config
        self._fps = fps

        self._lineas: Dict[str, Tuple[Tuple[float, float], Tuple[float, float]]] = {
            "A": config.linea_a,
            "B": config.linea_b,
        }
        # track_id -> (linea de entrada, instante de entrada en segundos)
        self._entradas: Dict[int, Tuple[str, float]] = {}
        # track_id -> km/h ya calculados y validos
        self._velocidades: Dict[int, float] = {}
        # IDs cuya medicion fue descartada por inverosimil (no se reintenta)
        self._descartados: Set[int] = set()

    # ------------------------------------------------------------------ API
    def update(self, movimientos: Sequence[Movement]) -> List[SpeedMeasurement]:
        """Procesa los desplazamientos de un frame y devuelve mediciones nuevas."""
        nuevas: List[SpeedMeasurement] = []

        for mov in movimientos:
            if mov.track_id in self._velocidades or mov.track_id in self._descartados:
                continue    # este vehiculo ya fue medido

            for linea, tiempo_s in self._cruces_ordenados(mov):
                medicion = self._registrar_cruce(mov, linea, tiempo_s)
                if medicion is not None:
                    nuevas.append(medicion)
                    break
        return nuevas

    def speed_of(self, track_id: int) -> Optional[float]:
        """Velocidad (km/h) ya medida para el ID, o None si aun no existe."""
        return self._velocidades.get(track_id)

    def is_measuring(self, track_id: int) -> bool:
        """True si el vehiculo ya entro a la ROI pero aun no la ha completado."""
        return (
            track_id in self._entradas
            and track_id not in self._velocidades
            and track_id not in self._descartados
        )

    # -------------------------------------------------------------- interno
    def _cruces_ordenados(self, mov: Movement) -> List[Tuple[str, float]]:
        """
        Devuelve [(nombre_linea, instante_en_segundos)] de las lineas que el
        vehiculo cruzo en este desplazamiento, ordenadas cronologicamente.

        Se ordenan por `t` porque un vehiculo rapido (o con frames omitidos)
        podria cruzar A y B entre dos observaciones; sin ordenar, no sabriamos
        cual fue la entrada y cual la salida.
        """
        cruces: List[Tuple[float, str]] = []
        for nombre, (p, q) in self._lineas.items():
            res = segment_intersection(mov.prev_point, mov.curr_point, p, q)
            if res is not None:
                cruces.append((res[0], nombre))
        cruces.sort()

        resultado: List[Tuple[str, float]] = []
        saltos = mov.curr_frame - mov.prev_frame   # normalmente 1; mayor si hubo oclusion
        for t, nombre in cruces:
            # Interpolacion lineal del frame exacto del cruce:
            #   frame_cruce = frame_previo + t * (frames transcurridos)
            frame_cruce = mov.prev_frame + t * saltos
            # Division entre FPS: frames -> segundos.
            resultado.append((nombre, frame_cruce / self._fps))
        return resultado

    def _registrar_cruce(
        self, mov: Movement, linea: str, tiempo_s: float
    ) -> Optional[SpeedMeasurement]:
        """Avanza la maquina de estados del vehiculo con un nuevo cruce."""
        previo = self._entradas.get(mov.track_id)

        if previo is None or previo[0] == linea:
            # Primer cruce (o repeticion de la misma linea por jitter/retroceso):
            # nos quedamos con el cruce MAS RECIENTE de la linea de entrada.
            self._entradas[mov.track_id] = (linea, tiempo_s)
            return None

        linea_entrada, tiempo_entrada = previo
        transcurrido = tiempo_s - tiempo_entrada
        if transcurrido <= 0:
            return None     # no deberia ocurrir, pero evita dividir entre cero

        # v = d / t  [m/s]   y luego * 3.6 para pasar a km/h.
        velocidad_kmh = (self._config.distancia_metros / transcurrido) * _MS_A_KMH

        if not (self._config.velocidad_min_kmh <= velocidad_kmh <= self._config.velocidad_max_kmh):
            # Un valor absurdo casi siempre indica un cambio de ID del tracker
            # (otro vehiculo "heredo" el ID) y no una velocidad real.
            logger.debug("Velocidad descartada ID %d: %.1f km/h", mov.track_id, velocidad_kmh)
            self._descartados.add(mov.track_id)
            return None

        self._velocidades[mov.track_id] = velocidad_kmh
        return SpeedMeasurement(
            track_id=mov.track_id,
            class_id=mov.class_id,
            speed_kmh=velocidad_kmh,
            elapsed_s=transcurrido,
            entry_line=linea_entrada,
            frame=mov.curr_frame,
        )
