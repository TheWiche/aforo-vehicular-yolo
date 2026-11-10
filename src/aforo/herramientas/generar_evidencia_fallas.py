"""
generar_evidencia_fallas.py
===========================
Regenera las imagenes de evidencia de los casos 3 y 4 de docs/CASOS_DE_FALLA.md a partir de
los videos publicos (descargar_videos.py). Las imagenes de los casos 1 y 2 se obtienen con
`capturar_fallas.py` sobre los videos anotados que produce aforo procesar.

    python -m aforo evidencia            # ambas imagenes
    python -m aforo evidencia --caso 4   # solo la mascara de movimiento (rapido)

Caso 3: sigue al ID 153 de `autopista_2` (una pickup) y recorta sus frames mostrando como su
        clase oscila entre Camion y Auto. Ejecuta YOLO sobre ~200 frames (~1 min en CPU).
Caso 4: muestra frame y mascara de movimiento de `autopista_1` en t = 0.5, 1.5 y 3 s.

Los IDs dependen de las detecciones; si cambias el modelo o los umbrales, el ID 153 puede ser
otro: usa --id para elegir otro vehiculo (verificar_tracking.py ayuda a encontrarlos).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import cv2
import numpy as np
import supervision as sv

from aforo.config import CLASES_VEHICULO, RAIZ_PROYECTO, cargar_configuracion
from aforo.analitica.geometry import poligono_entre_lineas
from aforo.vision.movimiento import DetectorMovimiento

VIDEOS = RAIZ_PROYECTO / "datos" / "videos"
SALIDA = RAIZ_PROYECTO / "docs" / "fallas"


def caso_cambios_de_clase(id_objetivo: int, frames_totales: int = 200) -> Path:
    """Recortes del mismo ID en frames consecutivos con su clase estabilizada."""
    from aforo.vision.detector import VehicleDetector
    from aforo.vision.tracker import VehicleTracker

    cfg = cargar_configuracion()
    ruta = VIDEOS / "autopista_2.mp4"
    info = sv.VideoInfo.from_video_path(str(ruta))
    detector, tracker = VehicleDetector(cfg.detector), VehicleTracker(cfg.tracker, fps=info.fps)

    vistos: Dict[int, Tuple[np.ndarray, int]] = {}      # frame -> (caja, clase_id)
    miniaturas: Dict[int, np.ndarray] = {}
    for i, frame in enumerate(sv.get_video_frames_generator(str(ruta), end=frames_totales)):
        seguidos, _ = tracker.update(detector.detect(frame), frame_idx=i)
        for tid, cid, caja in zip(seguidos.tracker_id, seguidos.class_id, seguidos.xyxy):
            if int(tid) == id_objetivo:
                vistos[i] = (caja.copy(), int(cid))
                miniaturas[i] = frame.copy()

    # Frames donde la clase cambia respecto del anterior (y algunos vecinos).
    cambios = [f for f in sorted(vistos)[1:] if vistos[f][1] != vistos.get(f - 1, (None, -1))[1]]
    if not cambios:
        raise RuntimeError(f"El ID {id_objetivo} no cambia de clase en los primeros {frames_totales} frames.")
    elegidos = sorted({f for c in cambios[:4] for f in (c - 1, c) if f in vistos})[:7]

    tiras = []
    for n in elegidos:
        caja, cid = vistos[n]
        x1, y1, x2, y2 = (int(v) for v in caja)
        color = (0, 215, 255) if CLASES_VEHICULO[cid] == "Camion" else (255, 160, 60)
        img = miniaturas[n]
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        x0, y0 = max(cx - 130, 0), max(cy - 110, 0)
        rec = cv2.resize(img[y0:y0 + 220, x0:x0 + 260], (260, 220))
        cv2.rectangle(rec, (0, 0), (260, 30), (20, 20, 20), -1)
        cv2.putText(rec, f"f{n}  #{id_objetivo} {CLASES_VEHICULO[cid]}", (6, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
        tiras.append(rec)
    SALIDA.mkdir(parents=True, exist_ok=True)
    destino = SALIDA / f"cambios_de_clase_id{id_objetivo}.jpg"
    cv2.imwrite(str(destino), np.hstack(tiras), [cv2.IMWRITE_JPEG_QUALITY, 88])
    return destino


def caso_mascara_movimiento() -> Path:
    """Frame y mascara de movimiento de autopista_1 en tres instantes."""
    cfg = cargar_configuracion()
    k = 3   # las lineas de ejemplo se pensaron en 1280x720 y el video es 4K
    linea_a = tuple((x * k, y * k) for x, y in ((330, 330), (1000, 330)))
    linea_b = tuple((x * k, y * k) for x, y in ((200, 560), (1190, 560)))
    roi = np.array(poligono_entre_lineas(linea_a, linea_b), dtype=np.int32)

    cap = cv2.VideoCapture(str(VIDEOS / "autopista_1.mp4"))
    ancho, alto = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    detector = DetectorMovimiento(cfg.movimiento, roi, (ancho, alto))
    filas = []
    for i in range(75):
        ok, frame = cap.read()
        if not ok:
            break
        res = detector.actualizar(frame)
        if i in (12, 37, 74):
            vista = cv2.resize(frame, (640, 360))
            cv2.putText(vista, f"frame {i} (t={i / 25:.1f} s)", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            mascara = cv2.cvtColor(cv2.resize(res.mascara, (640, 360), interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)
            cv2.putText(mascara, f"movimiento en ROI: {res.ratio_roi * 100:.1f} %", (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            filas.append(np.hstack([vista, mascara]))
    cap.release()
    SALIDA.mkdir(parents=True, exist_ok=True)
    destino = SALIDA / "fantasma_fondo_autopista1.jpg"
    cv2.imwrite(str(destino), np.vstack(filas), [cv2.IMWRITE_JPEG_QUALITY, 85])
    return destino


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Regenera la evidencia visual de los casos de falla 3 y 4.")
    ap.add_argument("--caso", type=int, choices=(3, 4), help="Solo ese caso (por defecto ambos).")
    ap.add_argument("--id", type=int, default=153, help="ID del vehiculo para el caso 3.")
    args = ap.parse_args(argv)
    try:
        if args.caso in (None, 4):
            print("Guardado", caso_mascara_movimiento().relative_to(RAIZ_PROYECTO))
        if args.caso in (None, 3):
            print("Guardado", caso_cambios_de_clase(args.id).relative_to(RAIZ_PROYECTO))
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
