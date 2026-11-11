"""
reporte.py
==========
Canal de comunicacion entre el proceso que analiza el video y quien lo observa (el dashboard web).

El proceso de analisis (`python -m aforo procesar ...`) no sabe nada de la web. Si se le pasan las
opciones `--estado`, `--cuadro-vivo` y `--parar`, usa un `Reportero` que:

  * escribe periodicamente un JSON con el progreso (cuadro actual, conteos, cuadros/s, estado);
  * guarda el ultimo cuadro anotado como JPEG (la web lo muestra como video en vivo);
  * vigila un archivo "parar": si aparece, el analisis termina de forma ordenada.

Todo pasa por archivos con escritura atomica (se escribe uno temporal y se renombra), asi quien lee
nunca ve un archivo a medias. Si el lector tiene el archivo abierto justo en ese instante (Windows no
deja reemplazarlo), esa actualizacion se omite: la siguiente llega en una fracción de segundo.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import cv2
import numpy as np

ANCHO_VISTA_PREVIA = 960      # el cuadro en vivo se reduce a este ancho (menos bytes, menos CPU)
CALIDAD_JPEG = 72


def _escribir_atomico(ruta: Path, datos: bytes) -> bool:
    """Escribe `datos` en `ruta` de forma atomica. False si el destino estaba ocupado (se reintenta luego)."""
    temporal = ruta.with_name(ruta.name + ".tmp")
    try:
        temporal.write_bytes(datos)
        os.replace(temporal, ruta)
        return True
    except OSError:
        return False


class Reportero:
    """Publica el progreso de un analisis y atiende la peticion de parada."""

    def __init__(
        self,
        ruta_estado: Optional[Path],
        ruta_cuadro: Optional[Path] = None,
        ruta_parada: Optional[Path] = None,
        meta: Optional[Dict[str, Any]] = None,
        intervalo_estado_s: float = 0.5,
        intervalo_cuadro_s: float = 0.066,
    ) -> None:
        self._estado = ruta_estado
        self._cuadro = ruta_cuadro
        self._parada = ruta_parada
        self._meta = dict(meta or {})
        self._intervalo_estado = intervalo_estado_s
        self._intervalo_cuadro = intervalo_cuadro_s
        self._ultimo_estado = 0.0
        self._ultimo_cuadro = 0.0
        self._inicio = time.time()
        for ruta in (ruta_estado, ruta_cuadro, ruta_parada):
            if ruta is not None:
                ruta.parent.mkdir(parents=True, exist_ok=True)
        # Una parada pedida antes de empezar (o de una corrida anterior) no debe afectar a esta.
        if ruta_parada is not None and ruta_parada.exists():
            ruta_parada.unlink(missing_ok=True)

    # ---------------------------------------------------------------- cuadro en vivo
    @property
    def quiere_cuadro(self) -> bool:
        """True si hay destino para el cuadro en vivo."""
        return self._cuadro is not None

    def cuadro_vencido(self) -> bool:
        """True si ya toca publicar un cuadro (para dibujar solo cuando hace falta)."""
        return self._cuadro is not None and time.perf_counter() - self._ultimo_cuadro >= self._intervalo_cuadro

    def publicar_cuadro(self, anotado: np.ndarray) -> None:
        """Guarda el cuadro anotado como JPEG reducido."""
        if self._cuadro is None:
            return
        alto, ancho = anotado.shape[:2]
        if ancho > ANCHO_VISTA_PREVIA:
            anotado = cv2.resize(anotado, (ANCHO_VISTA_PREVIA, round(alto * ANCHO_VISTA_PREVIA / ancho)),
                                 interpolation=cv2.INTER_AREA)
        ok, datos = cv2.imencode(".jpg", anotado, [cv2.IMWRITE_JPEG_QUALITY, CALIDAD_JPEG])
        if ok:
            _escribir_atomico(self._cuadro, datos.tobytes())
        self._ultimo_cuadro = time.perf_counter()

    # ---------------------------------------------------------------- estado
    def estado_vencido(self) -> bool:
        return self._estado is not None and time.perf_counter() - self._ultimo_estado >= self._intervalo_estado

    def publicar_estado(self, estado: str, **datos: Any) -> None:
        """Escribe el JSON de progreso. `estado`: corriendo | terminado | detenido | error."""
        if self._estado is None:
            return
        carga = {**self._meta, "estado": estado, "actualizado": time.time(),
                 "segundos": round(time.time() - self._inicio, 1), **datos}
        _escribir_atomico(self._estado, json.dumps(carga, ensure_ascii=False).encode("utf-8"))
        self._ultimo_estado = time.perf_counter()

    def finalizar(self, estado: str, **datos: Any) -> None:
        """Ultima escritura: siempre se publica (aunque el destino estuviera ocupado, se reintenta)."""
        for _ in range(20):
            self.publicar_estado(estado, **datos)
            if self._estado is None or self._leer_estado_actual() == estado:
                return
            time.sleep(0.05)

    def _leer_estado_actual(self) -> Optional[str]:
        try:
            return json.loads(self._estado.read_text(encoding="utf-8")).get("estado")  # type: ignore[union-attr]
        except (OSError, ValueError):
            return None

    # ---------------------------------------------------------------- parada
    def debe_parar(self) -> bool:
        """True si alguien pidio detener el analisis (existe el archivo "parar")."""
        return self._parada is not None and self._parada.exists()
