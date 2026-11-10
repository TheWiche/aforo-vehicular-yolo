"""
descargar_videos.py
===================
Descarga videos cortos y gratuitos de trafico vehicular a la carpeta `datos/videos/`
para poder probar el sistema sin depender del video final del proyecto.

Uso:
    python -m aforo descargar             # descarga los que falten
    python -m aforo descargar --forzar    # vuelve a descargarlos todos
    python -m aforo descargar --lista     # solo muestra el catalogo

Luego, por ejemplo:
    python -m aforo procesar --video datos/videos/autopista_1.mp4 --camara autopista_1 --reemplazar

Notas
-----
* Los videos se descargan de URLs publicas directas (.mp4). Cada uno puede tener
  varias URLs alternativas: si la primera falla se intenta la siguiente.
* La descarga es "atomica": se escribe en un archivo `.part` y solo se renombra al
  nombre final cuando termino completa y OpenCV logra abrirla, asi nunca queda un
  video corrupto a medias con el nombre definitivo.
* Para usar estos videos hay que calibrar las lineas de config.py a su resolucion
  (ver `python -m aforo calibrar --video datos/videos/<archivo>`): `autopista_1` es 4K y
  `autopista_2` / `carretera_3` son 1080p.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from tqdm import tqdm

from aforo.config import RAIZ_PROYECTO

logger = logging.getLogger("descarga")

CARPETA_VIDEOS: Path = RAIZ_PROYECTO / "datos" / "videos"
TAMANO_MINIMO_BYTES: int = 100_000        # menos de esto no puede ser un video valido
TIMEOUT_SEGUNDOS: int = 30
INTENTOS_POR_URL: int = 2
# Algunos servidores rechazan el "User-Agent" por defecto de Python.
CABECERAS = {"User-Agent": "Mozilla/5.0 (compatible; aforo-vehicular-demo/1.0)"}


@dataclass(frozen=True)
class VideoRemoto:
    """Un video del catalogo: nombre local, URLs de descarga y su procedencia."""
    archivo: str
    urls: Tuple[str, ...]
    descripcion: str
    fuente: str


CATALOGO: Tuple[VideoRemoto, ...] = (
    VideoRemoto(
        archivo="autopista_1.mp4",
        urls=("https://media.roboflow.com/supervision/video-examples/vehicles.mp4",),
        descripcion="Autopista de dos calzadas, camara fija elevada, trafico fluido (4K, ~21 s). "
                    "Ideal para calibrar aforo y velocidad.",
        fuente="Roboflow supervision - videos de ejemplo",
    ),
    VideoRemoto(
        archivo="autopista_2.mp4",
        urls=("https://media.roboflow.com/supervision/video-examples/vehicles-2.mp4",),
        descripcion="Autopista urbana con trafico DENSO (1080p, ~42 s): prueba de estres para el tracker.",
        fuente="Roboflow supervision - videos de ejemplo",
    ),
    VideoRemoto(
        archivo="carretera_3.mp4",
        urls=("https://videos.pexels.com/video-files/854671/854671-hd_1920_1080_25fps.mp4",),
        descripcion="Carretera de doble sentido con camara fija y trafico moderado (1080p, 60 s).",
        fuente="Pexels (licencia Pexels: uso libre) - video 854671",
    ),
)


class DescargaError(RuntimeError):
    """No se pudo descargar o validar un video."""


def _descargar_url(url: str, destino: Path) -> None:
    """Descarga `url` a `destino` mostrando una barra de progreso."""
    solicitud = urllib.request.Request(url, headers=CABECERAS)
    try:
        with urllib.request.urlopen(solicitud, timeout=TIMEOUT_SEGUNDOS) as respuesta:
            esperado = int(respuesta.headers.get("Content-Length") or 0)
            with destino.open("wb") as salida, tqdm(
                total=esperado or None, unit="B", unit_scale=True, desc=destino.name.removesuffix(".part")
            ) as barra:
                while True:
                    bloque = respuesta.read(1024 * 256)
                    if not bloque:
                        break
                    salida.write(bloque)
                    barra.update(len(bloque))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DescargaError(f"{url}: {exc}") from exc

    descargado = destino.stat().st_size
    if descargado < TAMANO_MINIMO_BYTES:
        raise DescargaError(f"{url}: archivo demasiado pequeno ({descargado} bytes)")
    if esperado and descargado != esperado:
        raise DescargaError(f"{url}: descarga incompleta ({descargado} de {esperado} bytes)")


def inspeccionar_video(ruta: Path) -> Tuple[int, int, float, int]:
    """Abre el video con OpenCV y devuelve (ancho, alto, fps, total_frames). Falla si no es legible."""
    import cv2   # importacion local: el resto del script no lo necesita

    cap = cv2.VideoCapture(str(ruta))
    try:
        if not cap.isOpened():
            raise DescargaError(f"OpenCV no pudo abrir {ruta.name}")
        ok, _ = cap.read()
        if not ok:
            raise DescargaError(f"{ruta.name} no contiene frames legibles")
        return (
            int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            float(cap.get(cv2.CAP_PROP_FPS)),
            int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        )
    finally:
        cap.release()


def obtener_video(video: VideoRemoto, forzar: bool) -> Path:
    """Garantiza que el video exista localmente (descargandolo si hace falta)."""
    CARPETA_VIDEOS.mkdir(parents=True, exist_ok=True)
    destino = CARPETA_VIDEOS / video.archivo

    if destino.is_file() and not forzar:
        try:
            inspeccionar_video(destino)
            logger.info("Ya existe (se omite): %s", destino.name)
            return destino
        except DescargaError:
            logger.warning("%s existe pero esta danado; se vuelve a descargar.", destino.name)

    temporal = destino.with_name(destino.name + ".part")
    errores: List[str] = []
    for url in video.urls:
        for intento in range(1, INTENTOS_POR_URL + 1):
            try:
                logger.info("Descargando %s (intento %d/%d)", video.archivo, intento, INTENTOS_POR_URL)
                _descargar_url(url, temporal)
                inspeccionar_video(temporal)      # valida antes de dar el archivo por bueno
                os.replace(temporal, destino)     # renombrado atomico al nombre final
                return destino
            except DescargaError as exc:
                errores.append(str(exc))
                logger.warning("Fallo: %s", exc)
            finally:
                temporal.unlink(missing_ok=True)  # nunca dejar un .part colgado
    raise DescargaError(f"No se pudo obtener {video.archivo}: " + " | ".join(errores))


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="Descarga videos de trafico de prueba a la carpeta datos/videos/.")
    ap.add_argument("--forzar", action="store_true", help="Descarga de nuevo aunque el archivo ya exista.")
    ap.add_argument("--lista", action="store_true", help="Muestra el catalogo sin descargar nada.")
    args = ap.parse_args(argv)

    if args.lista:
        for v in CATALOGO:
            print(f"- {v.archivo}: {v.descripcion}\n    fuente: {v.fuente}\n    url: {v.urls[0]}")
        return 0

    fallidos: List[str] = []
    resumen: List[str] = []
    for video in CATALOGO:
        try:
            ruta = obtener_video(video, args.forzar)
            ancho, alto, fps, frames = inspeccionar_video(ruta)
            duracion = frames / fps if fps > 0 else 0.0
            resumen.append(
                f"  OK  {ruta.name:<22} {ancho}x{alto} @ {fps:.1f} FPS, {duracion:.1f} s, "
                f"{ruta.stat().st_size / 1e6:.1f} MB"
            )
        except DescargaError as exc:
            fallidos.append(video.archivo)
            logger.error("%s", exc)
            resumen.append(f"  XX  {video.archivo:<22} no disponible")

    print("\nVideos en", CARPETA_VIDEOS)
    print("\n".join(resumen))
    if fallidos:
        print(f"\nNo se pudieron descargar: {', '.join(fallidos)} (revisa tu conexion a internet).")
        return 1
    print("\nListo. Prueba con:  python -m aforo procesar --video datos/videos/autopista_1.mp4 --camara autopista_1 --reemplazar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
