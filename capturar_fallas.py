"""
capturar_fallas.py
==================
Extrae frames puntuales de un video (normalmente el video anotado de `output/`) para
documentar casos de falla con evidencia visual en `docs/fallas/`.

Uso:
    python capturar_fallas.py --video output/salida.mp4 --frames 12 75 300 --prefijo denso
    python capturar_fallas.py --video output/salida.mp4 --frames 120 --recorte 600 800 1500 1080 --prefijo zoom

Cada frame se guarda como docs/fallas/<prefijo>_f<frame>.jpg reducido a `--ancho` px.
Para saber QUE frames mirar, ayudan `verificar_tracking.py` (saltos, IDs efimeros) y las
filas con `velocidad_kmh` nula de la tabla `cruces`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

import cv2

from config import RAIZ_PROYECTO

CARPETA_SALIDA: Path = RAIZ_PROYECTO / "docs" / "fallas"


def capturar(video: Path, frames: Sequence[int], prefijo: str, ancho: int,
             recorte: Optional[Sequence[int]] = None) -> int:
    """Guarda los frames pedidos. Devuelve cuantos se guardaron."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"No se pudo abrir {video}", file=sys.stderr)
        return 0
    CARPETA_SALIDA.mkdir(parents=True, exist_ok=True)
    guardados = 0
    try:
        for n in frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, n)
            ok, frame = cap.read()
            if not ok:
                print(f"Frame {n}: fuera de rango, se omite.", file=sys.stderr)
                continue
            if recorte:
                x1, y1, x2, y2 = recorte
                frame = frame[y1:y2, x1:x2]
            if frame.shape[1] > ancho:
                frame = cv2.resize(frame, (ancho, int(frame.shape[0] * ancho / frame.shape[1])),
                                   interpolation=cv2.INTER_AREA)
            destino = CARPETA_SALIDA / f"{prefijo}_f{n}.jpg"
            cv2.imwrite(str(destino), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            print(f"Guardado {destino.relative_to(RAIZ_PROYECTO)}")
            guardados += 1
    finally:
        cap.release()
    return guardados


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Guarda frames de un video para documentar casos de falla.")
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--frames", type=int, nargs="+", required=True, help="Indices de frame (desde 0).")
    ap.add_argument("--prefijo", required=True, help="Prefijo del nombre de archivo (p. ej. 'denso').")
    ap.add_argument("--ancho", type=int, default=1280, help="Ancho maximo de la imagen guardada.")
    ap.add_argument("--recorte", type=int, nargs=4, metavar=("X1", "Y1", "X2", "Y2"),
                    help="Recorta (en pixeles del video) antes de reducir, para hacer zoom.")
    args = ap.parse_args(argv)
    return 0 if capturar(args.video, args.frames, args.prefijo, args.ancho, args.recorte) else 1


if __name__ == "__main__":
    sys.exit(main())
