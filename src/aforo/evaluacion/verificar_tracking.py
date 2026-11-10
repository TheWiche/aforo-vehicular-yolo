"""
verificar_tracking.py
=====================
Auditoria del TRACKER: comprueba que los IDs que asigna ByteTrack son unicos y
estables, porque ese ID (`track_id`) es el que se guarda en la base de datos y
el que evita contar dos veces al mismo vehiculo.

Uso:
    python -m aforo auditar --video datos/videos/autopista_2.mp4 --max-frames 400

Como no existe una "verdad de terreno" (alguien que etiquete cada vehiculo a
mano), la auditoria combina dos clases de pruebas:

  Invariantes (deben cumplirse SIEMPRE; si fallan hay un error de logica):
    1. Unicidad por frame : dos vehiculos distintos nunca comparten ID en un frame.
    2. Sin reutilizacion  : un ID que caduco (supero el buffer de tracks perdidos)
                            no vuelve a aparecer para otro vehiculo.

  Indicadores de estabilidad (heuristicas; miden la calidad del seguimiento):
    3. Saltos sospechosos : un mismo ID que se "teletransporta" mas de ~1.5 veces
                            el tamano de su caja entre dos frames consecutivos
                            suele indicar que el ID cambio de un vehiculo a otro.
    4. IDs efimeros       : tracks de muy pocos frames (fragmentos de un mismo
                            vehiculo que perdio su ID, o falsos positivos).
    5. Cambios de clase   : veces que la clase estabilizada de un ID cambia.
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np
import supervision as sv

from aforo.config import cargar_configuracion

logger = logging.getLogger("verificar_tracking")


@dataclass
class _Vida:
    """Historia de un ID a lo largo del video."""
    primer_frame: int
    ultimo_frame: int
    centro: tuple
    diagonal: float
    clase: int
    observaciones: int = 1


@dataclass
class InformeTracking:
    """Resultado de la auditoria."""
    frames: int = 0
    ids_totales: int = 0
    vida_media_frames: float = 0.0
    duplicados_en_frame: int = 0
    reapariciones_tardias: int = 0
    saltos_sospechosos: int = 0
    ids_efimeros: int = 0
    cambios_de_clase: int = 0
    detalles: List[str] = field(default_factory=list)

    @property
    def invariantes_ok(self) -> bool:
        """Las dos pruebas que NUNCA deben fallar."""
        return self.duplicados_en_frame == 0 and self.reapariciones_tardias == 0


class AuditorTracking:
    """
    Observa, frame a frame, la salida del tracker y acumula estadisticas.

    No depende de YOLO ni de ByteTrack (solo de `sv.Detections` con `tracker_id`),
    por lo que se puede probar con datos sinteticos.
    """

    def __init__(self, max_frames_sin_ver: int, factor_salto: float = 1.5, vida_minima: int = 8) -> None:
        self._max_hueco = max_frames_sin_ver
        self._factor_salto = factor_salto
        self._vida_minima = vida_minima
        self._vidas: Dict[int, _Vida] = {}
        self._informe = InformeTracking()

    def observar(self, frame_idx: int, tracked: sv.Detections) -> None:
        """Registra los vehiculos con ID presentes en un frame."""
        inf = self._informe
        inf.frames += 1
        if len(tracked) == 0 or tracked.tracker_id is None:
            return

        ids = [int(i) for i in tracked.tracker_id]
        inf.duplicados_en_frame += len(ids) - len(set(ids))        # prueba 1

        for tid, caja, clase in zip(ids, tracked.xyxy, tracked.class_id):
            x1, y1, x2, y2 = (float(v) for v in caja)
            centro = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
            diagonal = math.hypot(x2 - x1, y2 - y1)
            clase = int(clase)

            vida = self._vidas.get(tid)
            if vida is None:
                self._vidas[tid] = _Vida(frame_idx, frame_idx, centro, diagonal, clase)
                continue
            if vida.ultimo_frame == frame_idx:
                continue        # ID repetido en el mismo frame: ya contado como duplicado

            hueco = frame_idx - vida.ultimo_frame
            if hueco > self._max_hueco:                             # prueba 2
                inf.reapariciones_tardias += 1
                inf.detalles.append(
                    f"ID {tid} reaparecio en el frame {frame_idx} tras {hueco} frames sin verse "
                    f"(limite {self._max_hueco})"
                )
            elif hueco == 1:                                        # prueba 3 (solo frames consecutivos)
                distancia = math.dist(centro, vida.centro)
                if distancia > self._factor_salto * max(diagonal, vida.diagonal):
                    inf.saltos_sospechosos += 1
                    inf.detalles.append(
                        f"ID {tid} salto {distancia:.0f}px entre los frames {vida.ultimo_frame} y {frame_idx}"
                    )

            if clase != vida.clase:                                 # prueba 5
                inf.cambios_de_clase += 1
            vida.centro, vida.diagonal, vida.clase = centro, diagonal, clase
            vida.ultimo_frame = frame_idx
            vida.observaciones += 1

    def informe(self) -> InformeTracking:
        """Cierra la auditoria y calcula los agregados."""
        inf = self._informe
        inf.ids_totales = len(self._vidas)
        if self._vidas:
            inf.vida_media_frames = float(np.mean([v.observaciones for v in self._vidas.values()]))
            inf.ids_efimeros = sum(1 for v in self._vidas.values() if v.observaciones < self._vida_minima)
        return inf


def auditar_video(ruta: Path, max_frames: Optional[int], factor_salto: float) -> InformeTracking:
    """Ejecuta detector + tracker sobre el video y devuelve el informe."""
    # Importaciones pesadas aqui para que el modulo (y sus tests) carguen rapido.
    from aforo.vision.detector import VehicleDetector
    from aforo.vision.tracker import VehicleTracker

    if not ruta.is_file():
        raise FileNotFoundError(f"No se encontro el video: {ruta}")
    cfg = cargar_configuracion()
    info = sv.VideoInfo.from_video_path(str(ruta))
    detector = VehicleDetector(cfg.detector)
    tracker = VehicleTracker(cfg.tracker, fps=info.fps)
    # Mismo limite de "frames sin verse" que usa el tracker para liberar un ID.
    limite = int(cfg.tracker.track_buffer * max(info.fps, 1.0) / 30.0) + 2
    auditor = AuditorTracking(max_frames_sin_ver=limite, factor_salto=factor_salto)

    total = min(max_frames, info.total_frames) if max_frames and info.total_frames else info.total_frames
    logger.info("Auditando %s (%dx%d @ %.1f FPS, %s frames)", ruta.name, info.width, info.height,
                info.fps, total if total is not None else "?")
    from tqdm import tqdm
    gen = sv.get_video_frames_generator(str(ruta), end=max_frames)
    for idx, frame in enumerate(tqdm(gen, total=total, unit="frame", desc="Auditando")):
        seguidos, _ = tracker.update(detector.detect(frame), frame_idx=idx)
        auditor.observar(idx, seguidos)
    return auditor.informe()


def imprimir_informe(inf: InformeTracking, nombre: str) -> None:
    """Muestra el informe en consola con un veredicto claro."""
    ok = lambda b: "OK " if b else "FALLA"  # noqa: E731
    print(f"\n{'=' * 60}\n AUDITORIA DEL TRACKING - {nombre}\n{'=' * 60}")
    print(f" Frames analizados          : {inf.frames}")
    print(f" IDs distintos asignados    : {inf.ids_totales}")
    print(f" Vida media de un ID        : {inf.vida_media_frames:.1f} frames")
    print("\n Invariantes (deben ser 0):")
    print(f"   [{ok(inf.duplicados_en_frame == 0)}] IDs repetidos dentro de un frame : {inf.duplicados_en_frame}")
    print(f"   [{ok(inf.reapariciones_tardias == 0)}] IDs reutilizados tras caducar  : {inf.reapariciones_tardias}")
    print("\n Indicadores de estabilidad (cuanto menor, mejor):")
    print(f"   Saltos sospechosos de ID (posible cambio de vehiculo): {inf.saltos_sospechosos}")
    print(f"   IDs efimeros (< 8 frames, fragmentos o falsos positivos): {inf.ids_efimeros}")
    print(f"   Cambios de clase de un mismo ID                       : {inf.cambios_de_clase}")
    for linea in inf.detalles[:10]:
        print(f"     - {linea}")
    if len(inf.detalles) > 10:
        print(f"     ... y {len(inf.detalles) - 10} mas")
    veredicto = "IDs UNICOS Y CONSISTENTES" if inf.invariantes_ok else "HAY ERRORES DE UNICIDAD DE ID"
    print(f"\n Veredicto: {veredicto}\n{'=' * 60}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="Audita la unicidad y estabilidad de los IDs del tracker.")
    ap.add_argument("--video", type=Path, default=None, help="Video a analizar (por defecto VIDEO_ENTRADA).")
    ap.add_argument("--max-frames", type=int, default=None, help="Analiza solo los primeros N frames.")
    ap.add_argument("--salto-factor", type=float, default=1.5,
                    help="Un salto mayor a (factor x tamano de la caja) entre frames se marca como sospechoso.")
    args = ap.parse_args(argv)

    ruta = (args.video or cargar_configuracion().io.video_entrada).resolve()
    try:
        informe = auditar_video(ruta, args.max_frames, args.salto_factor)
    except (FileNotFoundError, RuntimeError) as exc:
        logger.error("%s", exc)
        return 2
    imprimir_informe(informe, ruta.name)
    return 0 if informe.invariantes_ok else 1


if __name__ == "__main__":
    sys.exit(main())
