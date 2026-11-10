"""
Arma la respuesta JSON del panel a partir de las consultas SQL.

Aqui vive la unica logica que el SQL no resuelve: el percentil de las velocidades (SQLite no
trae una funcion de percentil), los porcentajes y la forma final de cada bloque. Todo lo demas
(conteos, promedios, orden) viene calculado por la base de datos.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import consultas

ESTADOS_DB = ("ok", "sin_bd", "sin_tablas", "vacia")


def percentil(valores: Sequence[float], p: float) -> Optional[float]:
    """Percentil `p` (0-100) con interpolacion lineal, igual que numpy/pandas por defecto."""
    if not valores:
        return None
    orden = sorted(valores)
    posicion = (len(orden) - 1) * p / 100.0
    inferior = int(posicion)
    superior = min(inferior + 1, len(orden) - 1)
    return orden[inferior] + (orden[superior] - orden[inferior]) * (posicion - inferior)


def abrir_solo_lectura(ruta: Path) -> sqlite3.Connection:
    """Conexion que no puede modificar nada (PRAGMA query_only)."""
    con = sqlite3.connect(str(ruta), timeout=10.0)
    con.execute("PRAGMA query_only = ON")
    return con


def _vacio(estado: str, mensaje: str, camaras: List[str], clases: List[Dict[str, Any]], limite: float) -> Dict[str, Any]:
    return {"estado": estado, "mensaje": mensaje, "camaras": camaras, "clases": clases, "limite_kmh": limite}


def construir_panel(
    ruta_db: Path,
    seleccion: Optional[Sequence[str]],
    pct: int,
    clases: List[Dict[str, Any]],
    limite_kmh: float,
    contexto: Optional[Callable[[str, Optional[Dict[str, Any]]], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Devuelve el panel completo. `estado` indica si hay algo que mostrar:
    ok | sin_bd (el archivo no existe) | sin_tablas (no es una base de este proyecto) | vacia.
    """
    if not ruta_db.is_file():
        return _vacio("sin_bd", f"Todavía no existe la base de datos ({ruta_db.name}).", [], clases, limite_kmh)
    con = abrir_solo_lectura(ruta_db)
    try:
        try:
            todas = consultas.camaras_disponibles(con)
        except sqlite3.OperationalError:
            return _vacio("sin_tablas", "La base de datos no tiene la tabla de cruces; se crea al procesar un video.", [], clases, limite_kmh)
        nombres = [c["camara"] for c in todas]
        if not nombres:
            return _vacio("vacia", "La base de datos existe, pero aún no tiene cruces.", [], clases, limite_kmh)

        elegidas = [c for c in (seleccion or nombres) if c in nombres] or nombres
        # Con UNA camara elegida se conoce su video y su calibracion (lineas, distancia y limite propio).
        ejecucion = consultas.ultima_ejecucion(con, elegidas[0]) if len(elegidas) == 1 else None
        camara_ctx = contexto(elegidas[0], ejecucion) if contexto and len(elegidas) == 1 else None
        if camara_ctx:
            limite_kmh = float(camara_ctx.get("limite_kmh", limite_kmh))
        duracion = None
        if ejecucion and ejecucion.get("fps") and ejecucion.get("frames"):
            duracion = round(float(ejecucion["frames"]) / float(ejecucion["fps"]), 1)
        totales = {f["tipo"]: f["total"] for f in consultas.total_por_tipo(con, elegidas)}
        total = sum(totales.values())
        por_tipo_vel = {f["tipo"]: f for f in consultas.velocidad_por_tipo(con, elegidas)}
        puntos = consultas.puntos_velocidad(con, elegidas)
        velocidades = [p["velocidad_kmh"] for p in puntos]
        ex = consultas.excesos(con, elegidas, limite_kmh)
        alertas = consultas.alertas(con, elegidas)
        lecturas = consultas.lecturas(con, elegidas)
        detenidos = sum(1 for a in alertas if a["tipo"] == "TRAFICO_DETENIDO")
        color = {c["nombre"]: c["color"] for c in clases}

        return {
            "estado": "ok",
            "mensaje": "",
            "generado": datetime.now().isoformat(timespec="seconds"),
            "camaras": nombres,
            "camaras_info": todas,
            "seleccion": elegidas,
            "camara": camara_ctx,
            "ejecucion": ({"video": ejecucion["video"], "inicio": ejecucion["inicio_video"],
                           "fps": ejecucion["fps"], "frames": ejecucion["frames"], "duracion_s": duracion}
                          if ejecucion else None),
            "por_minuto": [{"t": f["minuto"], "n": f["vehiculos"]} for f in consultas.aforo_por_minuto(con, elegidas)],
            "filtros": consultas.conteo_por_filtro(con, elegidas, limite_kmh),
            "clases": clases,
            "limite_kmh": limite_kmh,
            "total": total,
            "ultimo_cruce": consultas.ultimo_cruce(con, elegidas),
            "tipos": [
                {"nombre": c["nombre"], "color": c["color"], "total": totales.get(c["nombre"], 0),
                 "pct": round(100 * totales.get(c["nombre"], 0) / total) if total else 0}
                for c in clases
            ],
            "velocidad": {
                "promedio": round(sum(velocidades) / len(velocidades), 1) if velocidades else None,
                "mediciones": ex["medidos"],
                "excesos": ex["excesos"],
                "pct_excesos": round(100 * ex["excesos"] / ex["medidos"]) if ex["medidos"] else None,
            },
            "detenidos": detenidos,
            "estado_via": lecturas[-1]["estado"] if lecturas else None,
            "por_tipo": [
                {**por_tipo_vel[c["nombre"]], "color": c["color"]}
                for c in clases if c["nombre"] in por_tipo_vel
            ],
            "puntos": [
                {"t": p["momento"], "v": p["velocidad_kmh"], "tipo": p["tipo"], "id": p["track_id"]}
                for p in puntos
            ],
            "percentil": pct,
            "umbral_pico": percentil(velocidades, pct),
            "mas_rapidos": [
                {"t": f["momento"], "id": f["track_id"], "tipo": f["tipo"], "v": f["velocidad_kmh"],
                 "camara": f["camara"], "color": color.get(f["tipo"])}
                for f in consultas.mas_rapidos(con, elegidas)
            ],
            "lecturas": [
                {"t": f["momento"], "vehiculos": f["vehiculos_roi"], "movimiento": f["ratio_movimiento"],
                 "estado": f["estado"]}
                for f in lecturas
            ],
            "alertas": [
                {"t": a["momento"], "tipo": a["tipo"], "id": a["track_id"], "valor": a["valor"],
                 "detalle": a["descripcion"], "camara": a["camara"]}
                for a in alertas
            ],
            "cruces": [
                {"id": f["id"], "track": f["track_id"], "tipo": f["tipo"], "t": f["momento"],
                 "v": f["velocidad_kmh"], "camara": f["camara"], "color": color.get(f["tipo"])}
                for f in consultas.cruces_recientes(con, elegidas)
            ],
        }
    finally:
        con.close()
