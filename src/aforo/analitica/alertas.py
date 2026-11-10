"""
alertas.py
==========
Reglas de NEGOCIO que convierten mediciones en alertas utiles para el cliente.

El sistema produce dos tipos de alerta (tabla `alertas` de la base de datos):

  EXCESO_VELOCIDAD : un vehiculo supera el limite de velocidad configurado.
                     Regla simple: velocidad medida > LIMITE_VELOCIDAD_KMH.

  TRAFICO_DETENIDO : hay vehiculos en la ROI pero no se mueven (posible
                     congestion, accidente o falla). Se detecta combinando
                     YOLO (cuantos vehiculos hay) con el analisis de movimiento
                     (`movimiento.py`: cuanto cambia la imagen dentro de ellos).

Por que una maquina de estados con histeresis
---------------------------------------------
Si la alerta saltara en cuanto el movimiento cae por debajo del umbral en UN
frame, un parpadeo de la deteccion generaria cientos de alertas falsas. Por eso:
  * entrar a DETENIDO exige cumplir la condicion de forma SOSTENIDA durante
    `detenido_segundos`;
  * salir de DETENIDO exige que deje de cumplirse durante `salida_segundos`;
  * se emite UNA sola alerta por episodio, no una por frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from aforo.config import AlertasConfig

TIPO_EXCESO_VELOCIDAD = "EXCESO_VELOCIDAD"
TIPO_TRAFICO_DETENIDO = "TRAFICO_DETENIDO"


class EstadoTrafico(str, Enum):
    """Estado de la via dentro de la ROI."""
    LIBRE = "LIBRE"          # no hay vehiculos en la ROI
    FLUIDO = "FLUIDO"        # hay vehiculos y se mueven
    DETENIDO = "DETENIDO"    # hay vehiculos pero llevan un rato sin moverse


def supera_limite(velocidad_kmh: float, limite_kmh: float) -> bool:
    """Regla de la alerta de exceso de velocidad."""
    return velocidad_kmh > limite_kmh


@dataclass(frozen=True)
class ActualizacionTrafico:
    """Resultado de procesar un frame en el monitor de trafico."""
    estado: EstadoTrafico
    alerta_nueva: bool      # True solo en el frame en que comienza un episodio de DETENIDO


class MonitorTrafico:
    """Clasifica el estado del trafico con histeresis y avisa cuando empieza un episodio detenido."""

    def __init__(self, config: AlertasConfig) -> None:
        self._cfg = config
        self._estado = EstadoTrafico.LIBRE
        self._detenido_desde: Optional[float] = None    # inicio de la condicion "parece detenido"
        self._normal_desde: Optional[float] = None      # inicio de la condicion contraria (para salir)

    @property
    def estado(self) -> EstadoTrafico:
        return self._estado

    def actualizar(
        self, t_s: float, vehiculos: int, ratio_en_vehiculos: Optional[float]
    ) -> ActualizacionTrafico:
        """
        Parameters
        ----------
        t_s : segundos transcurridos desde el inicio del video (frame / FPS).
        vehiculos : vehiculos seguidos dentro de la ROI en este frame.
        ratio_en_vehiculos : fraccion (0..1) de los pixeles de esos vehiculos que se mueven.
        """
        cfg = self._cfg
        basico = EstadoTrafico.LIBRE if vehiculos == 0 else EstadoTrafico.FLUIDO

        # Durante el calentamiento el modelo de fondo aun no es fiable (vehiculos del
        # primer frame quedan "dentro" del fondo): no se evalua ni se alerta.
        if t_s < cfg.calentamiento_s:
            self._estado = basico
            return ActualizacionTrafico(self._estado, False)

        parece_detenido = (
            vehiculos >= cfg.detenido_min_vehiculos
            and ratio_en_vehiculos is not None
            and ratio_en_vehiculos < cfg.detenido_ratio_max
        )

        alerta = False
        if parece_detenido:
            self._normal_desde = None
            if self._detenido_desde is None:
                self._detenido_desde = t_s
            if self._estado != EstadoTrafico.DETENIDO and t_s - self._detenido_desde >= cfg.detenido_segundos:
                self._estado = EstadoTrafico.DETENIDO
                alerta = True                                   # una sola alerta por episodio
        else:
            self._detenido_desde = None
            if self._estado == EstadoTrafico.DETENIDO:
                if self._normal_desde is None:
                    self._normal_desde = t_s
                if t_s - self._normal_desde >= cfg.salida_segundos:
                    self._estado = basico                      # el episodio termino
                    self._normal_desde = None
            else:
                self._estado = basico
        return ActualizacionTrafico(self._estado, alerta)
