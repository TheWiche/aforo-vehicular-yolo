"""
anotar_verdad_terreno.py
========================
Herramienta para crear la VERDAD DE TERRENO: una persona mira el video y marca, con una
tecla, el instante exacto en que cada vehiculo cruza la linea de conteo. Con esas marcas
`evaluar.py` mide la precision del sistema.

Uso:
    python -m aforo anotar --video datos/videos/autopista_1.mp4 --camara autopista_1
    python -m aforo anotar --video datos/videos/autopista_1.mp4 --camara autopista_1 --velocidad 0.5

Teclas (la ventana debe tener el foco):
    a / m / b / c   marca un cruce de Auto / Moto / Bus / Camion en el instante actual
    ESPACIO         pausa / continua
    . y ,           (en pausa) avanza / retrocede un frame, para afinar el instante
    u               deshace la ultima marca
    q o ESC         guarda y sale

Consejos: anota con velocidad 0.5 y pausa cuando el vehiculo toque la linea. Si tienes la
velocidad real de algun vehiculo (GPS, radar, cronometro sobre distancia conocida),
agregala editando el JSON: "velocidad_kmh": 54.0 (por defecto es null).

Importante: la verdad de terreno debe hacerse SIN mirar la salida del sistema, para que
sea independiente. Se guarda en datos/evaluacion/<camara>.json (se versiona en git).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import cv2
import numpy as np

from aforo.config import CLASES_VEHICULO, LINEA_CONTEO, RAIZ_PROYECTO

TECLAS: Dict[int, str] = {ord("a"): "Auto", ord("m"): "Moto", ord("b"): "Bus", ord("c"): "Camion"}
ANCHO_VENTANA = 1280


def _dibujar(frame: np.ndarray, escala: float, marcas: List[dict], t: float, pausado: bool) -> np.ndarray:
    """Frame reducido con la linea de conteo y un resumen de las marcas."""
    vista = cv2.resize(frame, None, fx=escala, fy=escala) if escala != 1.0 else frame.copy()
    p, q = LINEA_CONTEO
    cv2.line(vista, (int(p[0] * escala), int(p[1] * escala)), (int(q[0] * escala), int(q[1] * escala)),
             (0, 215, 255), 2, cv2.LINE_AA)
    conteo = {nombre: sum(m["tipo"] == nombre for m in marcas) for nombre in CLASES_VEHICULO.values()}
    texto = f"t={t:6.2f}s  {'PAUSA' if pausado else 'REPRODUCIENDO'}  | " + "  ".join(f"{k}:{v}" for k, v in conteo.items())
    cv2.rectangle(vista, (0, 0), (vista.shape[1], 34), (20, 20, 20), -1)
    cv2.putText(vista, texto, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (240, 240, 240), 1, cv2.LINE_AA)
    return vista


def anotar(video: Path, velocidad: float) -> Optional[dict]:
    """Bucle interactivo. Devuelve el contenido del JSON o None si no se pudo abrir el video."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"No se pudo abrir el video: {video}", file=sys.stderr)
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    ancho = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    escala = min(1.0, ANCHO_VENTANA / ancho)
    espera_ms = max(1, int(1000 / fps / max(velocidad, 0.05)))

    marcas: List[dict] = []
    pausado, indice, frame = False, 0, None
    cv2.namedWindow("Verdad de terreno", cv2.WINDOW_AUTOSIZE)
    try:
        while True:
            if not pausado or frame is None:
                cap.set(cv2.CAP_PROP_POS_FRAMES, indice)
                ok, frame = cap.read()
                if not ok:
                    break                       # fin del video
            t = indice / fps
            cv2.imshow("Verdad de terreno", _dibujar(frame, escala, marcas, t, pausado))
            tecla = cv2.waitKey(espera_ms if not pausado else 30) & 0xFF

            if tecla in (ord("q"), 27):
                break
            if tecla == ord(" "):
                pausado = not pausado
            elif tecla in TECLAS:
                marcas.append({"segundo": round(t, 3), "tipo": TECLAS[tecla], "velocidad_kmh": None})
            elif tecla == ord("u") and marcas:
                marcas.pop()
            elif pausado and tecla == ord("."):
                indice = min(indice + 1, total - 1)
                frame = None
            elif pausado and tecla == ord(","):
                indice = max(indice - 1, 0)
                frame = None
            if not pausado:
                indice += 1
    finally:
        cap.release()
        cv2.destroyAllWindows()

    return {
        "camara": None,
        "video": video.name,
        "fps": fps,
        "linea_conteo": [list(LINEA_CONTEO[0]), list(LINEA_CONTEO[1])],
        "cruces": sorted(marcas, key=lambda m: m["segundo"]),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Anota a mano los cruces de la linea de conteo (verdad de terreno).")
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--camara", required=True, help="Nombre de camara; debe coincidir con aforo procesar --camara.")
    ap.add_argument("--velocidad", type=float, default=0.5, help="Factor de reproduccion (0.5 = mitad de velocidad).")
    args = ap.parse_args(argv)

    resultado = anotar(args.video, args.velocidad)
    if resultado is None:
        return 1
    resultado["camara"] = args.camara
    destino = RAIZ_PROYECTO / "datos" / "evaluacion" / f"{args.camara}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(resultado, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(resultado['cruces'])} cruces guardados en {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
