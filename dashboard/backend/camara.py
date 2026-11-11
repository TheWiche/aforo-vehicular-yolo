"""
Contexto de una camara: su calibracion (lineas, distancia, limite) y los cuadros de su video.

El dashboard muestra la evidencia junto a cada cifra: el cuadro del video en el instante en
que un vehiculo cruzo la linea de conteo, con las lineas de medicion dibujadas encima. Para
eso hacen falta dos cosas que no estan en la base de datos:

  * la calibracion de la camara -> `datos/calibraciones.json` (la escribe el menu) o, si la
    camara es la activa, las constantes de `aforo/config.py`;
  * el archivo de video          -> `datos/videos/<nombre>` (el nombre lo guarda la tabla
    `ejecuciones`).

Todo aqui es de solo lectura y tolera que falte cualquier pieza: sin video o sin OpenCV el
panel sigue funcionando, solo que sin imagen.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from aforo import config

ANCHO_MAXIMO = 1280            # los cuadros se reducen a este ancho antes de enviarlos
CALIDAD_JPEG = 82
_CANDADO_VIDEO = threading.Lock()   # OpenCV no comparte bien un mismo archivo entre hilos


def _perfiles(raiz: Path) -> Dict[str, Dict[str, Any]]:
    """Perfiles de calibracion guardados por el menu: {nombre_del_video: {...}}."""
    try:
        datos = json.loads((raiz / "datos" / "calibraciones.json").read_text(encoding="utf-8"))
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def _perfil_de(raiz: Path, camara: str, video: Optional[str]) -> Dict[str, Any]:
    """Calibracion de `camara`: primero el perfil guardado, luego config.py si es la camara activa."""
    perfiles = _perfiles(raiz)
    for nombre, perfil in perfiles.items():
        if isinstance(perfil, dict) and perfil.get("CAMARA") == camara:
            return {**perfil, "_video": nombre}
    if video and isinstance(perfiles.get(video), dict):
        return {**perfiles[video], "_video": video}
    if getattr(config, "CAMARA", None) == camara:
        return {
            "LINEA_CONTEO": config.LINEA_CONTEO,
            "LINEA_VELOCIDAD_A": config.LINEA_VELOCIDAD_A,
            "LINEA_VELOCIDAD_B": config.LINEA_VELOCIDAD_B,
            "DISTANCIA_REAL_METROS": config.DISTANCIA_REAL_METROS,
            "LIMITE_VELOCIDAD_KMH": config.LIMITE_VELOCIDAD_KMH,
            "_video": Path(str(config.VIDEO_ENTRADA)).name,
        }
    return {}


def _linea(valor: Any) -> Optional[list]:
    """Normaliza una linea a [[x1, y1], [x2, y2]] o None si no tiene esa forma."""
    try:
        (x1, y1), (x2, y2) = valor
        return [[float(x1), float(y1)], [float(x2), float(y2)]]
    except (TypeError, ValueError):
        return None


def ruta_video(raiz: Path, nombre: Optional[str]) -> Optional[Path]:
    """Ruta del video dentro de datos/videos/. Solo se acepta el NOMBRE (sin carpetas)."""
    if not nombre:
        return None
    candidato = raiz / "datos" / "videos" / Path(str(nombre)).name
    if candidato.is_file():
        return candidato
    activo = Path(str(config.VIDEO_ENTRADA))
    activo = activo if activo.is_absolute() else raiz / activo
    return activo if activo.name == Path(str(nombre)).name and activo.is_file() else None


@lru_cache(maxsize=16)
def _dimensiones(ruta: str, _mtime: float) -> Optional[Tuple[int, int]]:
    try:
        import cv2
    except ImportError:
        return None
    with _CANDADO_VIDEO:
        captura = cv2.VideoCapture(ruta)
        try:
            if not captura.isOpened():
                return None
            ancho = int(captura.get(cv2.CAP_PROP_FRAME_WIDTH))
            alto = int(captura.get(cv2.CAP_PROP_FRAME_HEIGHT))
        finally:
            captura.release()
    return (ancho, alto) if ancho > 0 and alto > 0 else None


def contexto_camara(raiz: Path, camara: str, ejecucion: Optional[Dict[str, Any]],
                    limite_defecto: float, limite_fijo: Optional[float] = None) -> Dict[str, Any]:
    """Todo lo que el panel necesita saber de la camara ademas de sus filas en la base."""
    video = (ejecucion or {}).get("video")
    perfil = _perfil_de(raiz, camara, video)
    video = video or perfil.get("_video")
    ruta = ruta_video(raiz, video)
    dimensiones = _dimensiones(str(ruta), ruta.stat().st_mtime) if ruta else None
    lineas = {
        "conteo": _linea(perfil.get("LINEA_CONTEO")),
        "a": _linea(perfil.get("LINEA_VELOCIDAD_A")),
        "b": _linea(perfil.get("LINEA_VELOCIDAD_B")),
    }
    limite = limite_fijo if limite_fijo is not None else float(perfil.get("LIMITE_VELOCIDAD_KMH", limite_defecto))
    distancia = perfil.get("DISTANCIA_REAL_METROS")
    return {
        "camara": camara,
        "video": video,
        "limite_kmh": limite,
        "distancia_m": float(distancia) if distancia is not None else None,
        "nota": perfil.get("nota"),
        "lineas": lineas if all(lineas.values()) else None,
        "ancho": dimensiones[0] if dimensiones else None,
        "alto": dimensiones[1] if dimensiones else None,
        "fotograma": dimensiones is not None,
    }


def indice_de_cuadro(ejecucion: Dict[str, Any], momento: Optional[str]) -> int:
    """Cuadro del video que corresponde a `momento` (hora del cruce guardada en la base)."""
    fps = float(ejecucion.get("fps") or 30.0)
    total = int(ejecucion.get("frames") or 0)
    if momento:
        segundos = (datetime.fromisoformat(momento) - datetime.fromisoformat(str(ejecucion["inicio_video"]))).total_seconds()
        indice = int(round(segundos * fps))
    else:
        indice = total // 2
    return max(0, min(indice, max(total - 1, 0)))


@lru_cache(maxsize=96)
def _cuadro_jpeg(ruta: str, _mtime: float, indice: int, ancho_maximo: int = ANCHO_MAXIMO) -> Optional[bytes]:
    try:
        import cv2
    except ImportError:
        return None
    with _CANDADO_VIDEO:
        captura = cv2.VideoCapture(ruta)
        try:
            if not captura.isOpened():
                return None
            captura.set(cv2.CAP_PROP_POS_FRAMES, indice)
            ok, cuadro = captura.read()
        finally:
            captura.release()
    if not ok or cuadro is None:
        return None
    alto, ancho = cuadro.shape[:2]
    if ancho > ancho_maximo:
        cuadro = cv2.resize(cuadro, (ancho_maximo, round(alto * ancho_maximo / ancho)), interpolation=cv2.INTER_AREA)
    ok, datos = cv2.imencode(".jpg", cuadro, [cv2.IMWRITE_JPEG_QUALITY, CALIDAD_JPEG])
    return datos.tobytes() if ok else None


def fotograma(raiz: Path, ejecucion: Optional[Dict[str, Any]], momento: Optional[str]) -> Optional[bytes]:
    """JPEG del cuadro del video en `momento`, o None si no hay video, ejecucion u OpenCV."""
    if not ejecucion:
        return None
    ruta = ruta_video(raiz, ejecucion.get("video"))
    if ruta is None:
        return None
    try:
        indice = indice_de_cuadro(ejecucion, momento)
    except (KeyError, ValueError):
        return None
    return _cuadro_jpeg(str(ruta), ruta.stat().st_mtime, indice)
