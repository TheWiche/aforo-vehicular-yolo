"""
Videos disponibles para analizar: los de `datos/videos/` y los registrados desde otra carpeta.

El navegador no puede abrir archivos arbitrarios del disco, asi que el dashboard maneja los videos
desde el servidor: los lista, extrae cuadros (para el calibrador y las miniaturas), recibe subidas y
registra rutas externas en `datos/videos_externos.json` (sin copiar archivos de varios cientos de MB).

Seguridad: el servidor solo escucha en 127.0.0.1; aun asi, de los nombres que llegan por la API solo se
usa la parte final (sin carpetas) y solo se abren extensiones de video.
"""

from __future__ import annotations

import json
import os
import re
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aforo import perfiles

from . import camara as camara_ctx

EXTENSIONES = (".mp4", ".avi", ".mov", ".mkv")
TAMANO_MAXIMO_SUBIDA = 8 * 1024 ** 3        # 8 GB
_CANDADO = threading.Lock()


class ErrorVideo(ValueError):
    """Un video no existe, no es valido o no se pudo guardar (el mensaje se muestra al usuario)."""


def _carpeta(raiz: Path) -> Path:
    return raiz / "datos" / "videos"


def _archivo_externos(raiz: Path) -> Path:
    return raiz / "datos" / "videos_externos.json"


def _externos(raiz: Path) -> Dict[str, str]:
    try:
        datos = json.loads(_archivo_externos(raiz).read_text(encoding="utf-8"))
        return {k: v for k, v in datos.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def nombre_valido(nombre: str) -> str:
    """Nombre de archivo seguro: sin carpetas, con extension de video y sin caracteres raros."""
    limpio = Path(str(nombre).strip()).name
    limpio = re.sub(r"[^\w.\- ()]", "_", limpio, flags=re.UNICODE).strip(". ")
    if not limpio or Path(limpio).suffix.lower() not in EXTENSIONES:
        raise ErrorVideo(f"El archivo debe ser un video ({', '.join(EXTENSIONES)}).")
    return limpio


def resolver(raiz: Path, nombre: Optional[str]) -> Optional[Path]:
    """Ruta real de un video por su nombre, o None si no existe."""
    if not nombre:
        return None
    base = Path(str(nombre)).name
    local = _carpeta(raiz) / base
    if local.is_file():
        return local
    externo = _externos(raiz).get(base)
    return Path(externo) if externo and Path(externo).is_file() else None


@lru_cache(maxsize=32)
def _propiedades(ruta: str, _mtime: float) -> Optional[Dict[str, Any]]:
    try:
        import cv2
    except ImportError:
        return None
    captura = cv2.VideoCapture(ruta)
    try:
        if not captura.isOpened():
            return None
        ancho, alto = int(captura.get(cv2.CAP_PROP_FRAME_WIDTH)), int(captura.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(captura.get(cv2.CAP_PROP_FPS)) or 30.0
        cuadros = int(captura.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        captura.release()
    if ancho <= 0 or alto <= 0:
        return None
    return {"ancho": ancho, "alto": alto, "fps": round(fps, 3), "cuadros": cuadros,
            "duracion_s": round(cuadros / fps, 1) if fps > 0 and cuadros > 0 else None}


def propiedades(ruta: Path) -> Optional[Dict[str, Any]]:
    return _propiedades(str(ruta), ruta.stat().st_mtime)


def listar(raiz: Path, camaras_con_datos: Dict[str, int], archivo_perfiles: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Todos los videos con su resolucion, duracion, estado de calibracion y cruces ya guardados."""
    carpeta = _carpeta(raiz)
    encontrados: Dict[str, Tuple[Path, bool]] = {}
    if carpeta.is_dir():
        for ruta in sorted(carpeta.iterdir(), key=lambda r: r.name.lower()):
            if ruta.is_file() and ruta.suffix.lower() in EXTENSIONES:
                encontrados[ruta.name] = (ruta, False)
    for nombre, destino in _externos(raiz).items():
        if nombre not in encontrados and Path(destino).is_file():
            encontrados[nombre] = (Path(destino), True)

    guardados = perfiles.cargar(archivo_perfiles)
    filas = []
    for nombre, (ruta, externo) in encontrados.items():
        perfil = guardados.get(nombre)
        camara = (perfil or {}).get("CAMARA") or re.sub(r"[^\w\-]+", "_", Path(nombre).stem).strip("_")
        props = propiedades(ruta) or {}
        filas.append({
            "nombre": nombre, "externo": externo, "ruta": str(ruta) if externo else None,
            "bytes": ruta.stat().st_size, **{k: props.get(k) for k in ("ancho", "alto", "fps", "cuadros", "duracion_s")},
            "legible": bool(props), "calibrado": perfil is not None, "camara": camara,
            "cruces": camaras_con_datos.get(camara, 0),
        })
    return filas


def cuadro(raiz: Path, nombre: str, segundo: float, ancho_maximo: int) -> Optional[bytes]:
    """JPEG del video en el instante `segundo` (se acota al rango del video)."""
    ruta = resolver(raiz, nombre)
    if ruta is None:
        return None
    props = propiedades(ruta)
    if not props:
        return None
    indice = int(round(max(0.0, segundo) * props["fps"]))
    if props["cuadros"] > 0:
        indice = min(indice, props["cuadros"] - 1)
    return camara_ctx._cuadro_jpeg(str(ruta), ruta.stat().st_mtime, indice, max(160, min(ancho_maximo, 1920)))


def registrar_externo(raiz: Path, ruta_texto: str) -> str:
    """Registra un video que esta en otra carpeta. Devuelve el nombre con el que aparece en la lista."""
    ruta = Path(str(ruta_texto).strip().strip('"').strip("'"))
    if not ruta.is_absolute():
        raise ErrorVideo("Escribe la ruta completa del archivo (por ejemplo C:\\Videos\\calle.mp4).")
    if not ruta.is_file():
        raise ErrorVideo("No encuentro ese archivo. Revisa la ruta.")
    if ruta.suffix.lower() not in EXTENSIONES:
        raise ErrorVideo(f"El archivo debe ser un video ({', '.join(EXTENSIONES)}).")
    nombre = nombre_valido(ruta.name)
    if (_carpeta(raiz) / nombre).is_file():
        raise ErrorVideo(f"Ya hay un video llamado «{nombre}» en datos/videos.")
    if not propiedades(ruta):
        raise ErrorVideo("OpenCV no puede abrir ese archivo (¿está dañado o en un formato no soportado?).")
    with _CANDADO:
        registro = _externos(raiz)
        registro[nombre] = str(ruta.resolve())
        destino = _archivo_externos(raiz)
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_suffix(".json.tmp")
        temporal.write_text(json.dumps(registro, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporal, destino)
    return nombre


def ruta_para_subida(raiz: Path, nombre: str) -> Tuple[str, Path]:
    """Nombre limpio y ruta de destino para una subida; error si ya existe un video con ese nombre."""
    limpio = nombre_valido(nombre)
    destino = _carpeta(raiz) / limpio
    if destino.exists() or limpio in _externos(raiz):
        raise ErrorVideo(f"Ya hay un video llamado «{limpio}». Cambia el nombre del archivo.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    return limpio, destino
