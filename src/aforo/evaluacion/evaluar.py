"""
evaluar.py
==========
Mide la CALIDAD del sistema comparando lo que guardo en la base de datos contra la
VERDAD DE TERRENO (conteo y velocidades reales anotados por una persona).

Uso:
    python -m aforo anotar --video datos/videos/mi_video.mp4 --camara mi_camara   # una vez
    python -m aforo procesar --video datos/videos/mi_video.mp4 --camara mi_camara --reemplazar
    python -m aforo evaluar --camara mi_camara

Metricas (todas calculadas sobre video que el modelo NO vio en entrenamiento: YOLOv8
viene preentrenado en COCO y los videos del proyecto no forman parte de ese dataset)
----------------------------------------------------------------------------------
Se parte de dos listas de eventos "un vehiculo cruzo la linea": los de la verdad de
terreno (GT) y los que el sistema inserto en la tabla `cruces`.

  Emparejamiento: cada evento del sistema se asocia como maximo con UN evento GT
  cuya hora difiera menos de `--ventana` segundos (1 s por defecto, que cubre la
  demora humana al anotar). Se asigna primero la pareja mas cercana en el tiempo.

    TP (verdadero positivo) : evento del sistema con pareja en GT.
    FP (falso positivo)     : evento del sistema SIN pareja (vehiculo contado de mas).
    FN (falso negativo)     : evento GT SIN pareja (vehiculo que el sistema no conto).

    precision = TP / (TP + FP)       "de lo que conto, cuanto era real"
    recall    = TP / (TP + FN)       "de lo real, cuanto conto"
    F1        = 2 * P * R / (P + R)  media armonica de ambas

  Clasificacion  : de los TP, fraccion donde el TIPO (auto/moto/bus/camion) coincide.
  Aforo          : error relativo del conteo total y por tipo, |N_sistema - N_gt| / N_gt.
  Velocidad      : sobre los TP que tienen velocidad real en GT y velocidad medida:
                   MAE  = promedio de |v_sistema - v_real|        (km/h)
                   RMSE = raiz del promedio de (v_sistema - v_real)^2  (castiga mas los errores grandes)
                   % de mediciones con error <= 5 km/h.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from aforo.config import RAIZ_PROYECTO, cargar_configuracion
from aforo.persistencia.db import CrucesDB, formatear_momento

TOLERANCIA_VELOCIDAD_KMH: float = 5.0


@dataclass(frozen=True)
class Evento:
    """Un vehiculo cruzando la linea: instante (s desde el inicio del video), tipo y velocidad."""
    t: float
    tipo: str
    velocidad_kmh: Optional[float] = None


@dataclass
class Resultado:
    """Metricas calculadas."""
    tp: int = 0
    fp: int = 0
    fn: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    clasificacion_acierto: Optional[float] = None      # None si no hubo TP
    total_gt: int = 0
    total_sistema: int = 0
    aforo_error_pct: Optional[float] = None
    aforo_por_tipo: Dict[str, Tuple[int, int]] = field(default_factory=dict)    # tipo -> (gt, sistema)
    velocidad_n: int = 0
    velocidad_mae: Optional[float] = None
    velocidad_rmse: Optional[float] = None
    velocidad_dentro_tolerancia_pct: Optional[float] = None
    exceso_n_real: int = 0                              # vehiculos que en la verdad de terreno superan el limite
    exceso_recall: Optional[float] = None               # de los excesos reales, cuantos detecto el sistema
    exceso_precision: Optional[float] = None            # de los excesos que alerto el sistema, cuantos eran reales
    confusion: Dict[Tuple[str, str], int] = field(default_factory=dict)         # (tipo_gt, tipo_sistema) -> n


# ===========================================================================
# Nucleo (funciones puras: se prueban sin base de datos ni video)
# ===========================================================================
def emparejar(gt: Sequence[Evento], sistema: Sequence[Evento], ventana_s: float) -> List[Tuple[int, int]]:
    """
    Empareja eventos GT y del sistema de forma uno-a-uno, por cercania temporal.

    Se generan todos los pares con |dt| <= ventana, se ordenan de menor a mayor |dt| y
    se aceptan siempre que ni el evento GT ni el del sistema esten ya usados (asignacion
    voraz). Devuelve [(indice_gt, indice_sistema), ...].
    """
    candidatos = [
        (abs(g.t - s.t), i, j)
        for i, g in enumerate(gt)
        for j, s in enumerate(sistema)
        if abs(g.t - s.t) <= ventana_s
    ]
    candidatos.sort()
    usados_gt, usados_sis, pares = set(), set(), []
    for _, i, j in candidatos:
        if i not in usados_gt and j not in usados_sis:
            usados_gt.add(i)
            usados_sis.add(j)
            pares.append((i, j))
    return pares


def calcular_metricas(
    gt: Sequence[Evento],
    sistema: Sequence[Evento],
    ventana_s: float = 1.0,
    limite_kmh: Optional[float] = None,
) -> Resultado:
    """
    Calcula todas las metricas descritas en la cabecera del modulo.

    Si se indica `limite_kmh`, ademas mide la ALERTA de exceso de velocidad: sobre los
    cruces con velocidad real y medida, un "exceso real" es v_real > limite y un "exceso
    alertado" es v_sistema > limite (recall y precision de esa decision).
    """
    pares = emparejar(gt, sistema, ventana_s)
    r = Resultado()
    r.tp = len(pares)
    r.fp = len(sistema) - r.tp
    r.fn = len(gt) - r.tp
    r.precision = r.tp / (r.tp + r.fp) if (r.tp + r.fp) else 0.0
    r.recall = r.tp / (r.tp + r.fn) if (r.tp + r.fn) else 0.0
    r.f1 = 2 * r.precision * r.recall / (r.precision + r.recall) if (r.precision + r.recall) else 0.0

    # --- Clasificacion de tipo sobre los TP -----------------------------------
    aciertos = 0
    for i, j in pares:
        r.confusion[(gt[i].tipo, sistema[j].tipo)] = r.confusion.get((gt[i].tipo, sistema[j].tipo), 0) + 1
        aciertos += gt[i].tipo == sistema[j].tipo
    r.clasificacion_acierto = aciertos / r.tp if r.tp else None

    # --- Aforo (conteos) -------------------------------------------------------
    r.total_gt, r.total_sistema = len(gt), len(sistema)
    r.aforo_error_pct = 100.0 * abs(len(sistema) - len(gt)) / len(gt) if gt else None
    for tipo in sorted({e.tipo for e in gt} | {e.tipo for e in sistema}):
        r.aforo_por_tipo[tipo] = (sum(e.tipo == tipo for e in gt), sum(e.tipo == tipo for e in sistema))

    # --- Velocidad --------------------------------------------------------------
    errores = [
        sistema[j].velocidad_kmh - gt[i].velocidad_kmh
        for i, j in pares
        if gt[i].velocidad_kmh is not None and sistema[j].velocidad_kmh is not None
    ]
    r.velocidad_n = len(errores)
    if errores:
        r.velocidad_mae = sum(abs(e) for e in errores) / len(errores)
        r.velocidad_rmse = math.sqrt(sum(e * e for e in errores) / len(errores))
        r.velocidad_dentro_tolerancia_pct = (
            100.0 * sum(abs(e) <= TOLERANCIA_VELOCIDAD_KMH for e in errores) / len(errores)
        )

    # --- Alerta de exceso de velocidad (decision binaria sobre el limite) -----
    if limite_kmh is not None:
        reales = alertados = ambos = 0
        for i, j in pares:
            v_real, v_sis = gt[i].velocidad_kmh, sistema[j].velocidad_kmh
            if v_real is None or v_sis is None:
                continue
            es_real, es_alerta = v_real > limite_kmh, v_sis > limite_kmh
            reales += es_real
            alertados += es_alerta
            ambos += es_real and es_alerta
        r.exceso_n_real = reales
        r.exceso_recall = ambos / reales if reales else None
        r.exceso_precision = ambos / alertados if alertados else None
    return r


# ===========================================================================
# Entrada / salida
# ===========================================================================
def cargar_verdad_terreno(ruta: Path) -> List[Evento]:
    """Lee el JSON generado por anotar_verdad_terreno.py."""
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        return sorted(
            (Evento(float(c["segundo"]), str(c["tipo"]), c.get("velocidad_kmh")) for c in datos["cruces"]),
            key=lambda e: e.t,
        )
    except FileNotFoundError:
        raise FileNotFoundError(
            f"No existe la verdad de terreno: {ruta}\nGenerala con: python -m aforo anotar --video <video> --camara <camara>"
        ) from None
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError(f"Formato invalido en {ruta}: {exc}") from exc


def cargar_eventos_sistema(ruta_db: Path, camara: str) -> Tuple[List[Evento], datetime]:
    """
    Lee de la BD (SELECT) los cruces de la ultima ejecucion de la camara, con su hora
    convertida a segundos desde el inicio del video.
    """
    if not ruta_db.is_file():
        raise FileNotFoundError(f"No existe la base de datos {ruta_db}. Ejecuta primero aforo procesar.")
    con = sqlite3.connect(str(ruta_db))
    try:
        ejecucion = con.execute(
            "SELECT inicio_video, fps, frames FROM ejecuciones WHERE camara = ? ORDER BY id DESC LIMIT 1",
            (camara,),
        ).fetchone()
        if ejecucion is None:
            raise ValueError(f"No hay ejecuciones registradas para la camara '{camara}'. Corre aforo procesar con --camara {camara}.")
        inicio = datetime.fromisoformat(ejecucion[0])
        duracion = timedelta(seconds=ejecucion[2] / ejecucion[1]) if ejecucion[1] and ejecucion[2] else timedelta(days=1)
        filas = con.execute(
            "SELECT momento, tipo, velocidad_kmh FROM cruces "
            "WHERE camara = ? AND momento >= ? AND momento <= ? ORDER BY momento",
            (camara, formatear_momento(inicio), formatear_momento(inicio + duracion + timedelta(seconds=1))),
        ).fetchall()
    finally:
        con.close()
    eventos = [
        Evento((datetime.fromisoformat(m) - inicio).total_seconds(), tipo, vel) for m, tipo, vel in filas
    ]
    return eventos, inicio


def guardar_metricas(ruta_db: Path, camara: str, r: Resultado, ventana_s: float) -> None:
    """Guarda cada metrica como una fila de la tabla `metricas`."""
    ahora = datetime.now()
    filas: List[Tuple[str, Optional[float], str]] = [
        ("eventos_precision", r.precision, f"TP={r.tp} FP={r.fp} ventana={ventana_s:g}s"),
        ("eventos_recall", r.recall, f"TP={r.tp} FN={r.fn} ventana={ventana_s:g}s"),
        ("eventos_f1", r.f1, ""),
        ("clasificacion_acierto", r.clasificacion_acierto, f"sobre {r.tp} cruces emparejados"),
        ("aforo_error_pct", r.aforo_error_pct, f"gt={r.total_gt} sistema={r.total_sistema}"),
        ("velocidad_mae_kmh", r.velocidad_mae, f"n={r.velocidad_n}"),
        ("velocidad_rmse_kmh", r.velocidad_rmse, f"n={r.velocidad_n}"),
        ("velocidad_dentro_5kmh_pct", r.velocidad_dentro_tolerancia_pct, f"n={r.velocidad_n}"),
        ("exceso_recall", r.exceso_recall, f"excesos reales={r.exceso_n_real}"),
        ("exceso_precision", r.exceso_precision, f"excesos reales={r.exceso_n_real}"),
    ]
    for tipo, (n_gt, n_sis) in r.aforo_por_tipo.items():
        error = 100.0 * abs(n_sis - n_gt) / n_gt if n_gt else None
        filas.append((f"aforo_error_pct_{tipo}", error, f"gt={n_gt} sistema={n_sis}"))
    with CrucesDB(ruta_db) as db:
        for nombre, valor, detalle in filas:
            db.insertar_metrica(camara, ahora, nombre, valor, detalle)


def escribir_informe(ruta_db: Path, destino: Path) -> None:
    """Regenera un informe Markdown con la ULTIMA evaluacion de cada camara (SELECT sobre `metricas`)."""
    con = sqlite3.connect(str(ruta_db))
    try:
        filas = con.execute(
            "SELECT m.camara, m.evaluado_en, m.metrica, m.valor, m.detalle FROM metricas m "
            "WHERE m.evaluado_en = (SELECT MAX(evaluado_en) FROM metricas WHERE camara = m.camara) "
            "ORDER BY m.camara, m.id"
        ).fetchall()
    finally:
        con.close()
    lineas = ["# Resultados de metricas", "",
              "Generado por `python -m aforo evaluar --informe`. Cada tabla es la ultima evaluacion de la camara "
              "(tabla `metricas` de `datos/db/database.db`).", ""]
    camara_actual = None
    for camara, cuando, metrica, valor, detalle in filas:
        if camara != camara_actual:
            lineas += ["", f"## Camara `{camara}` (evaluada {cuando[:19]})", "",
                       "| Metrica | Valor | Detalle |", "|---|---|---|"]
            camara_actual = camara
        texto = "n/a" if valor is None else (f"{valor:.3f}" if abs(valor) <= 1.0 and not metrica.endswith(("pct", "kmh")) else f"{valor:.2f}")
        lineas.append(f"| {metrica} | {texto} | {detalle} |")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def imprimir(r: Resultado, camara: str, ventana_s: float, limite_kmh: float = 0.0) -> None:
    """Resumen legible en consola."""
    pct = lambda v: "n/a" if v is None else f"{v:.1f} %"  # noqa: E731
    num = lambda v: "n/a" if v is None else f"{v:.2f}"  # noqa: E731
    print(f"\n{'=' * 60}\n METRICAS - camara '{camara}' (ventana de emparejamiento {ventana_s:g} s)\n{'=' * 60}")
    print(f" Cruces en la verdad de terreno : {r.total_gt}")
    print(f" Cruces contados por el sistema : {r.total_sistema}")
    print(f"\n Deteccion de cruces:   TP={r.tp}  FP={r.fp}  FN={r.fn}")
    print(f"   precision {r.precision:.3f} | recall {r.recall:.3f} | F1 {r.f1:.3f}")
    print(f"\n Clasificacion de tipo (sobre TP): {pct(None if r.clasificacion_acierto is None else 100 * r.clasificacion_acierto)}")
    print(f" Error del aforo total           : {pct(r.aforo_error_pct)}")
    for tipo, (g, s) in r.aforo_por_tipo.items():
        print(f"   {tipo:<8} real {g:>3} | sistema {s:>3}")
    print(f"\n Velocidad (n={r.velocidad_n}): MAE {num(r.velocidad_mae)} km/h | RMSE {num(r.velocidad_rmse)} km/h | "
          f"dentro de +-{TOLERANCIA_VELOCIDAD_KMH:g} km/h: {pct(r.velocidad_dentro_tolerancia_pct)}")
    if r.velocidad_n == 0:
        print("   (sin velocidades reales en la verdad de terreno: agrega 'velocidad_kmh' a los cruces del JSON)")
    else:
        print(f" Alerta de exceso de velocidad (limite {limite_kmh:g} km/h): excesos reales {r.exceso_n_real} | "
              f"recall {pct(None if r.exceso_recall is None else 100 * r.exceso_recall)} | "
              f"precision {pct(None if r.exceso_precision is None else 100 * r.exceso_precision)}")
    print("=" * 60)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Calcula precision, recall, F1, error de aforo y error de velocidad.")
    ap.add_argument("--camara", help="Camara a evaluar (la usada en aforo procesar --camara).")
    ap.add_argument("--gt", type=Path, help="JSON de verdad de terreno (por defecto datos/evaluacion/<camara>.json).")
    ap.add_argument("--db", type=Path, help="Base de datos (por defecto DB_RUTA de config.py).")
    ap.add_argument("--ventana", type=float, default=1.0, help="Tolerancia de emparejamiento en segundos.")
    ap.add_argument("--sin-guardar", action="store_true", help="No guardar las metricas en la BD.")
    ap.add_argument("--informe", type=Path, nargs="?", const=Path("docs/METRICAS_RESULTADOS.md"),
                    help="Regenera el informe Markdown a partir de la tabla `metricas`.")
    args = ap.parse_args(argv)

    cfg = cargar_configuracion()
    ruta_db = (args.db or cfg.io.db_ruta).resolve()
    try:
        if args.camara:
            gt_ruta = args.gt or RAIZ_PROYECTO / "datos" / "evaluacion" / f"{args.camara}.json"
            gt = cargar_verdad_terreno(gt_ruta)
            sistema, _ = cargar_eventos_sistema(ruta_db, args.camara)
            limite = cfg.alertas.limite_velocidad_kmh
            r = calcular_metricas(gt, sistema, args.ventana, limite_kmh=limite)
            imprimir(r, args.camara, args.ventana, limite)
            if not args.sin_guardar:
                guardar_metricas(ruta_db, args.camara, r, args.ventana)
        elif not args.informe:
            ap.error("indica --camara <nombre> y/o --informe")
        if args.informe:
            destino = args.informe if args.informe.is_absolute() else RAIZ_PROYECTO / args.informe
            escribir_informe(ruta_db, destino)
            print(f"Informe escrito en {destino}")
    except (FileNotFoundError, ValueError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
