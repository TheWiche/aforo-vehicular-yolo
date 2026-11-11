"""
Control del procesamiento desde la web.

El analisis corre en un PROCESO APARTE (`python -m aforo procesar ...`), no dentro del servidor: asi
un analisis largo no bloquea la interfaz, cerrar la pestana no lo mata y si el modelo falla el
servidor sigue vivo. La comunicacion es por archivos (ver `aforo/reporte.py`):

    datos/salidas/web/estado.json   progreso (lo escribe el analisis, lo lee la web)
    datos/salidas/web/cuadro.jpg    ultimo cuadro anotado (video en vivo)
    datos/salidas/web/parar         si existe, el analisis termina de forma ordenada
    datos/salidas/web/proceso.log   salida del proceso (para diagnosticar errores)

Solo puede haber un analisis a la vez.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

MODOS = ("vivo", "completo", "rapido")
SUFIJO_VIVO = "_vivo"
_TERMINALES = ("terminado", "detenido", "error")


class ErrorProceso(RuntimeError):
    """No se pudo iniciar o detener el analisis (el mensaje se muestra al usuario)."""


class GestorProceso:
    """Lanza, vigila y detiene el analisis de un video."""

    def __init__(self, raiz: Path, ruta_db: Path, python: Optional[str] = None) -> None:
        self._raiz = raiz
        self._db = ruta_db
        self._python = python or sys.executable
        self.carpeta = raiz / "datos" / "salidas" / "web"
        self.ruta_estado = self.carpeta / "estado.json"
        self.ruta_cuadro = self.carpeta / "cuadro.jpg"
        self.ruta_parar = self.carpeta / "parar"
        self.ruta_log = self.carpeta / "proceso.log"
        self._proceso: Optional[subprocess.Popen] = None
        self._log = None
        self._candado = threading.Lock()
        self._lanzado: Dict[str, Any] = {}

    # ------------------------------------------------------------------ comando
    def construir_comando(self, video: Path, modo: str, camara: str, gpu: bool,
                          reemplazar: bool, guardar_video: bool) -> List[str]:
        """
        Argumentos de `python -m aforo procesar` para cada modo:

          vivo      velocidad normal: salta cuadros si no alcanza; datos parciales -> camara aparte
          completo  todos los cuadros, con vista previa (el mas preciso)
          rapido    todos los cuadros, modelo liviano y sin vista previa (lo mas rapido en CPU)
        """
        if modo not in MODOS:
            raise ErrorProceso(f"Modo desconocido: {modo}")
        cmd = [self._python, "-m", "aforo", "procesar", "--video", str(video), "--perfil", "--db", str(self._db),
               "--estado", str(self.ruta_estado), "--parar", str(self.ruta_parar)]
        if modo != "rapido":
            cmd += ["--cuadro-vivo", str(self.ruta_cuadro)]
        liviano = ["--modelo", "datos/modelos/yolov8n.pt", "--imgsz", "640"]
        if modo == "vivo":
            cmd += ["--tiempo-real", "--sin-ventana", "--camara", camara + SUFIJO_VIVO, "--reemplazar", "--sin-video"]
            if not gpu:
                cmd += liviano
            return cmd
        if modo == "rapido":
            cmd += liviano
        if reemplazar:
            cmd.append("--reemplazar")
        if not (guardar_video and modo == "completo"):
            cmd.append("--sin-video")
        return cmd

    # ------------------------------------------------------------------ control
    def corriendo(self) -> bool:
        return self._proceso is not None and self._proceso.poll() is None

    def iniciar(self, video: Path, modo: str, camara: str, gpu: bool, reemplazar: bool, guardar_video: bool) -> None:
        with self._candado:
            if self.corriendo():
                raise ErrorProceso("Ya hay un análisis en marcha. Detenlo o espera a que termine.")
            comando = self.construir_comando(video, modo, camara, gpu, reemplazar, guardar_video)
            self.carpeta.mkdir(parents=True, exist_ok=True)
            for ruta in (self.ruta_estado, self.ruta_cuadro, self.ruta_parar):
                ruta.unlink(missing_ok=True)
            self._cerrar_log()
            self._log = open(self.ruta_log, "wb")
            entorno = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
                       "PYTHONPATH": str(self._raiz / "src") + os.pathsep + str(self._raiz)}
            opciones: Dict[str, Any] = {}
            if sys.platform == "win32":
                opciones["creationflags"] = subprocess.CREATE_NO_WINDOW
            try:
                self._proceso = subprocess.Popen(comando, cwd=self._raiz, env=entorno, stdout=self._log,
                                                 stderr=subprocess.STDOUT, **opciones)
            except OSError as exc:
                self._cerrar_log()
                raise ErrorProceso(f"No se pudo iniciar el análisis: {exc}") from exc
            self._lanzado = {"video": video.name, "camara": camara + SUFIJO_VIVO if modo == "vivo" else camara,
                             "modo": modo, "inicio": time.time()}

    def detener(self) -> None:
        """Pide parar de forma ordenada; si el proceso no responde en 15 s, se termina a la fuerza."""
        with self._candado:
            if not self.corriendo():
                return
            self.carpeta.mkdir(parents=True, exist_ok=True)
            self.ruta_parar.write_text("parar", encoding="utf-8")
            proceso = self._proceso

        def _vigilar() -> None:
            try:
                proceso.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proceso.kill()
        threading.Thread(target=_vigilar, daemon=True).start()

    def _cerrar_log(self) -> None:
        if self._log is not None:
            try:
                self._log.close()
            except OSError:
                pass
            self._log = None

    # ------------------------------------------------------------------ estado
    def _leer_estado(self) -> Dict[str, Any]:
        try:
            datos = json.loads(self.ruta_estado.read_text(encoding="utf-8"))
            return datos if isinstance(datos, dict) else {}
        except (OSError, ValueError):
            return {}

    def cola_del_registro(self, lineas: int = 12) -> List[str]:
        """Ultimas lineas del registro del proceso (sin las barras de progreso de tqdm)."""
        try:
            texto = self.ruta_log.read_bytes()[-6000:].decode("utf-8", errors="replace")
        except OSError:
            return []
        limpias = [re.sub(r"\x1b\[[0-9;]*m", "", ln).strip() for ln in re.split(r"[\r\n]+", texto)]
        return [ln for ln in limpias if ln and "frame/s" not in ln and "it/s" not in ln][-lineas:]

    def estado(self) -> Dict[str, Any]:
        """Estado actual: libre | iniciando | corriendo | terminado | detenido | error, mas el progreso."""
        publicado = self._leer_estado()
        if not publicado and not self.corriendo() and self._proceso is None:
            return {"estado": "libre"}
        datos = {**self._lanzado, **publicado}
        estado = datos.get("estado")
        if self.corriendo():
            # Entre el arranque y la primera publicacion el proceso esta cargando el modelo.
            datos["estado"] = "corriendo" if publicado.get("actualizado") else "iniciando"
        elif estado not in _TERMINALES:
            # El proceso ya no existe pero no dejo un estado final: se cerro inesperadamente.
            datos["estado"] = "error"
            cola = self.cola_del_registro(4)
            datos["mensaje"] = cola[-1] if cola else "El análisis se interrumpió antes de terminar."
        datos["registro"] = self.cola_del_registro()
        total, frame = datos.get("total_frames"), datos.get("frame")
        if total and frame is not None:
            datos["progreso"] = round(min(1.0, frame / total), 4)
            restante = max(0, total - frame)
            if datos.get("modo") == "tiempo_real" and datos.get("fps_video"):
                datos["restante_s"] = round(restante / datos["fps_video"])      # avanza con el reloj
            elif datos.get("cuadros_por_s"):
                datos["restante_s"] = round(restante / datos["cuadros_por_s"])
        return datos

    def cuadro(self) -> Optional[bytes]:
        try:
            return self.ruta_cuadro.read_bytes()
        except OSError:
            return None

    def cuadro_mtime(self) -> float:
        try:
            return self.ruta_cuadro.stat().st_mtime
        except OSError:
            return 0.0
