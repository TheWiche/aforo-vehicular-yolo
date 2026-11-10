"""
seleccionar_puntos.py
=====================
Herramienta auxiliar para CALIBRAR: muestra un frame de tu video y te deja
hacer clic para obtener las coordenadas en pixeles de las lineas, listas para
pegar en config.py.

Uso:
    python seleccionar_puntos.py                     # usa VIDEO_ENTRADA de config.py
    python seleccionar_puntos.py --video mi.mp4 --frame 120

Teclas:   clic izquierdo = agregar punto | u = deshacer | q o ESC = terminar
Orden sugerido (2 puntos por linea): 1-2 LINEA_CONTEO, 3-4 LINEA_VELOCIDAD_A,
5-6 LINEA_VELOCIDAD_B.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

import config

_ANCHO_MAX_VENTANA = 1280    # si el video es mas grande se reduce solo para mostrarlo
_NOMBRES = ["LINEA_CONTEO", "LINEA_VELOCIDAD_A", "LINEA_VELOCIDAD_B"]
_COLORES = [(0, 215, 255), (255, 0, 200), (255, 0, 200)]


def _leer_frame(ruta: Path, indice: int) -> np.ndarray:
    """Lee el frame `indice` del video (con manejo de errores explicito)."""
    if not ruta.is_file():
        raise FileNotFoundError(f"No se encontro el video: {ruta}")
    cap = cv2.VideoCapture(str(ruta))
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(indice, 0))
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok:
        raise RuntimeError(f"No se pudo leer el frame {indice} de {ruta}")
    return frame


def _dibujar(base: np.ndarray, puntos: List[Tuple[int, int]], escala: float) -> np.ndarray:
    """Dibuja los puntos y lineas elegidos hasta ahora sobre una copia reducida."""
    vista = cv2.resize(base, None, fx=escala, fy=escala) if escala != 1.0 else base.copy()
    for i, (x, y) in enumerate(puntos):
        color = _COLORES[min(i // 2, len(_COLORES) - 1)]
        centro = (int(x * escala), int(y * escala))
        cv2.circle(vista, centro, 6, color, -1, cv2.LINE_AA)
        cv2.putText(vista, f"{i + 1}:({x},{y})", (centro[0] + 8, centro[1] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
        if i % 2 == 1:
            previo = puntos[i - 1]
            cv2.line(vista, (int(previo[0] * escala), int(previo[1] * escala)), centro, color, 2, cv2.LINE_AA)
    return vista


def _imprimir_resultado(puntos: List[Tuple[int, int]]) -> None:
    """Imprime los puntos con el formato exacto que espera config.py."""
    print("\nPega esto en config.py:\n")
    for i, nombre in enumerate(_NOMBRES):
        par = puntos[2 * i: 2 * i + 2]
        if len(par) == 2:
            print(f"{nombre} = (({par[0][0]}, {par[0][1]}), ({par[1][0]}, {par[1][1]}))")
    sobrantes = len(puntos) % 2
    if sobrantes:
        print(f"# Aviso: el ultimo punto {puntos[-1]} no tiene pareja.")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Obtiene coordenadas haciendo clic sobre un frame.")
    ap.add_argument("--video", type=Path, default=config.RAIZ_PROYECTO / config.VIDEO_ENTRADA)
    ap.add_argument("--frame", type=int, default=0, help="Indice del frame a mostrar.")
    args = ap.parse_args(argv)

    try:
        base = _leer_frame(args.video, args.frame)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    alto, ancho = base.shape[:2]
    escala = min(1.0, _ANCHO_MAX_VENTANA / ancho)
    print(f"Resolucion del video: {ancho}x{alto}. Las coordenadas se dan en esa resolucion.")

    puntos: List[Tuple[int, int]] = []

    def _al_hacer_clic(evento: int, x: int, y: int, *_: object) -> None:
        if evento == cv2.EVENT_LBUTTONDOWN:
            # Se convierte de la vista reducida a pixeles del video original.
            puntos.append((int(round(x / escala)), int(round(y / escala))))

    ventana = "Selecciona puntos (u=deshacer, q=terminar)"
    cv2.namedWindow(ventana)
    cv2.setMouseCallback(ventana, _al_hacer_clic)

    while True:
        cv2.imshow(ventana, _dibujar(base, puntos, escala))
        tecla = cv2.waitKey(30) & 0xFF
        if tecla in (ord("q"), 27):
            break
        if tecla == ord("u") and puntos:
            puntos.pop()
    cv2.destroyAllWindows()

    _imprimir_resultado(puntos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
