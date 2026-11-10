"""
aforo procesar
=======
Punto de entrada del sistema de Aforo Vehicular y Estimacion de Velocidad.

Uso basico (toma todo de config.py):
    python -m aforo procesar

Con opciones (sobrescriben config.py solo para esta ejecucion):
    python -m aforo procesar --video datos/videos/autopista.mp4 --camara autopista --reemplazar --mostrar

Cada vehiculo que cruza la linea de conteo se guarda de inmediato en la tabla
`cruces` de la base de datos SQLite (datos/db/database.db). Visualiza los datos con:
    python -m aforo dashboard
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from aforo.config import AppConfig, ConfigError, cargar_configuracion

if TYPE_CHECKING:  # solo para el verificador de tipos; evita importar torch al arrancar
    from aforo.pipeline import PipelineSummary

logger = logging.getLogger("aforo")


def _parsear_argumentos(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Define la interfaz de linea de comandos (todas las opciones son opcionales)."""
    ap = argparse.ArgumentParser(
        description="Aforo vehicular y estimacion de velocidad con YOLOv8 + ByteTrack.",
    )
    ap.add_argument("--video", type=Path, help="Ruta del video de entrada (sobrescribe config.py).")
    ap.add_argument("--salida", type=Path, help="Ruta del video anotado de salida.")
    ap.add_argument("--modelo", type=Path, help="Pesos YOLO a usar, p. ej. datos/modelos/yolov8n.pt.")
    ap.add_argument("--dispositivo", type=str, help="'cpu', '0' (GPU CUDA) ... (por defecto: automatico).")
    ap.add_argument("--mostrar", action="store_true", help="Muestra una ventana en vivo (q para salir).")
    ap.add_argument("--tiempo-real", action="store_true",
                    help="Reproduce a la velocidad real del video saltando cuadros si hace falta "
                         "(abre la ventana y no guarda video; algo menos preciso).")
    ap.add_argument("--imgsz", type=int, help="Tamano de entrada de YOLO en px (menor = mas rapido, p. ej. 640).")
    ap.add_argument("--sin-video", action="store_true", help="No guarda el video anotado (mas rapido).")
    ap.add_argument("--camara", type=str, help="Nombre de la camara guardado en la BD (sobrescribe CAMARA de config.py).")
    ap.add_argument("--reemplazar", action="store_true",
                    help="Borra de la BD los cruces previos de esta camara antes de empezar (evita duplicados al repetir una prueba).")
    return ap.parse_args(argv)


def _aplicar_argumentos(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    """
    Devuelve una NUEVA configuracion con los argumentos de consola aplicados.
    Las dataclasses son inmutables (frozen), por eso se usa `dataclasses.replace`
    en lugar de modificar atributos: evita efectos secundarios inesperados.
    """
    io, det, vis = config.io, config.detector, config.visual
    if args.video:
        io = dataclasses.replace(io, video_entrada=args.video.resolve())
    if args.salida:
        io = dataclasses.replace(io, video_salida=args.salida.resolve())
    if args.camara:
        io = dataclasses.replace(io, camara=args.camara.strip())
    if args.sin_video:
        io = dataclasses.replace(io, video_salida=None)
    if args.imgsz:
        det = dataclasses.replace(det, tamano_imagen=args.imgsz)
    if args.modelo:
        det = dataclasses.replace(det, modelo=args.modelo.resolve())
    if args.dispositivo:
        det = dataclasses.replace(det, dispositivo=args.dispositivo)
    if args.mostrar or args.tiempo_real:
        vis = dataclasses.replace(vis, mostrar_ventana=True)
    if args.tiempo_real:
        vis = dataclasses.replace(vis, tiempo_real=True)
    nueva = dataclasses.replace(config, io=io, detector=det, visual=vis)
    nueva.validate()
    return nueva


def _imprimir_resumen(resumen: PipelineSummary) -> None:
    """Muestra en consola el resultado final del aforo y las velocidades."""
    linea = "=" * 52
    print(f"\n{linea}\n RESUMEN DE AFORO VEHICULAR\n{linea}")
    for clase, n in resumen.conteo_por_clase.items():
        print(f" {clase:<12} {n:>6}")
    print(f" {'-' * 20}\n {'TOTAL':<12} {resumen.total:>6}")
    for sentido, n in resumen.conteo_por_sentido.items():
        print(f"   {sentido}: {n}")

    if resumen.mediciones:
        velocidades = [m.speed_kmh for m in resumen.mediciones]
        print(
            f"\n Velocidades medidas: {len(velocidades)} vehiculos | "
            f"promedio {sum(velocidades) / len(velocidades):.1f} km/h | "
            f"min {min(velocidades):.1f} | max {max(velocidades):.1f}"
        )
    else:
        print("\n No se completo ninguna medicion de velocidad "
              "(revisa las lineas A/B de la ROI en config.py).")

    print(f"\n Alertas: {resumen.alertas_exceso} por exceso de velocidad, "
          f"{resumen.alertas_detenido} por trafico detenido")
    print(f" Frames: {resumen.frames_procesados} en {resumen.segundos_proceso:.1f} s")
    if resumen.frames_saltados:
        vistos = resumen.frames_procesados + resumen.frames_saltados
        print(f" Tiempo real: se analizo 1 de cada {vistos / max(resumen.frames_procesados, 1):.1f} cuadros "
              f"({resumen.frames_saltados} saltados para no atrasarse)")
    print(f" Video : {resumen.video_salida or '(no se guardo video: modo rapido)'}")
    print(f" BD    : {resumen.db_ruta}  ({resumen.filas_db} cruces insertados, camara '{resumen.camara}')")
    print(linea)


def main(argv: Optional[List[str]] = None) -> int:
    """Devuelve 0 si todo salio bien o un codigo distinto de 0 si hubo error."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    args = _parsear_argumentos(argv)

    try:
        config = _aplicar_argumentos(cargar_configuracion(), args)

        # Las importaciones pesadas (torch, ultralytics) se hacen aqui para que
        # `python -m aforo procesar --help` y los errores de configuracion respondan al instante.
        from aforo.pipeline import AforoPipeline

        resumen = AforoPipeline(config).run(reemplazar_camara=args.reemplazar)
    except ConfigError as exc:
        logger.error("Configuracion invalida: %s", exc)
        return 2
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 3
    except RuntimeError as exc:     # incluye ModeloError, VideoError y BaseDatosError
        logger.error("%s", exc)
        return 4

    _imprimir_resumen(resumen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
