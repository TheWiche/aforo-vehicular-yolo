"""
Consultas SQL del dashboard. Cada funcion recibe una conexion `sqlite3` abierta (solo
lectura) y la lista de camaras a incluir, ejecuta UN `SELECT` y devuelve filas ya como
diccionarios listos para convertir a JSON.

Las agregaciones (conteos, promedios, minimos y maximos) las calcula el motor SQL con
`GROUP BY`; Python solo da forma a los resultados. Los valores viajan siempre como
parametros enlazados (`?`): lo unico que se arma con texto es la LISTA de marcadores, nunca
los valores, asi que no hay inyeccion SQL posible.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Sequence


def _marcadores(camaras: Sequence[str]) -> str:
    """'?, ?, ?' con un marcador por camara."""
    return ", ".join("?" for _ in camaras)


def _filas(con: sqlite3.Connection, sql: str, parametros: Sequence[Any]) -> List[Dict[str, Any]]:
    cursor = con.execute(sql, list(parametros))
    columnas = [c[0] for c in cursor.description]
    return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]


def camaras_disponibles(con: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Camaras con datos, cuantos cruces tiene cada una y su rango de fechas."""
    return _filas(
        con,
        "SELECT camara, COUNT(*) AS cruces, MIN(momento) AS desde, MAX(momento) AS hasta "
        "FROM cruces GROUP BY camara ORDER BY camara",
        [],
    )


def total_por_tipo(con: sqlite3.Connection, camaras: Sequence[str]) -> List[Dict[str, Any]]:
    return _filas(
        con,
        f"SELECT tipo, COUNT(*) AS total FROM cruces WHERE camara IN ({_marcadores(camaras)}) GROUP BY tipo",
        camaras,
    )


def ultimo_cruce(con: sqlite3.Connection, camaras: Sequence[str]) -> Optional[str]:
    fila = con.execute(
        f"SELECT MAX(momento) FROM cruces WHERE camara IN ({_marcadores(camaras)})", list(camaras)
    ).fetchone()
    return fila[0] if fila else None


def velocidad_por_tipo(con: sqlite3.Connection, camaras: Sequence[str]) -> List[Dict[str, Any]]:
    return _filas(
        con,
        "SELECT tipo, AVG(velocidad_kmh) AS promedio, MIN(velocidad_kmh) AS minimo, "
        "MAX(velocidad_kmh) AS maximo, COUNT(velocidad_kmh) AS n FROM cruces "
        f"WHERE velocidad_kmh IS NOT NULL AND camara IN ({_marcadores(camaras)}) GROUP BY tipo",
        camaras,
    )


def puntos_velocidad(con: sqlite3.Connection, camaras: Sequence[str]) -> List[Dict[str, Any]]:
    """Cada medicion de velocidad con su hora (para el grafico de dispersion)."""
    return _filas(
        con,
        "SELECT momento, velocidad_kmh, tipo, track_id, camara FROM cruces "
        f"WHERE velocidad_kmh IS NOT NULL AND camara IN ({_marcadores(camaras)}) ORDER BY momento",
        camaras,
    )


def mas_rapidos(con: sqlite3.Connection, camaras: Sequence[str], limite: int = 8) -> List[Dict[str, Any]]:
    return _filas(
        con,
        "SELECT momento, track_id, tipo, velocidad_kmh, camara FROM cruces "
        f"WHERE velocidad_kmh IS NOT NULL AND camara IN ({_marcadores(camaras)}) "
        "ORDER BY velocidad_kmh DESC LIMIT ?",
        [*camaras, limite],
    )


def excesos(con: sqlite3.Connection, camaras: Sequence[str], limite_kmh: float) -> Dict[str, int]:
    """Cuantas mediciones hay y cuantas superan el limite de velocidad."""
    fila = _filas(
        con,
        "SELECT COUNT(velocidad_kmh) AS medidos, COALESCE(SUM(velocidad_kmh > ?), 0) AS excesos "
        f"FROM cruces WHERE camara IN ({_marcadores(camaras)})",
        [limite_kmh, *camaras],
    )[0]
    return {"medidos": int(fila["medidos"]), "excesos": int(fila["excesos"])}


def cruces_recientes(con: sqlite3.Connection, camaras: Sequence[str], limite: int = 100) -> List[Dict[str, Any]]:
    return _filas(
        con,
        "SELECT id, track_id, tipo, momento, velocidad_kmh, camara FROM cruces "
        f"WHERE camara IN ({_marcadores(camaras)}) ORDER BY momento DESC LIMIT ?",
        [*camaras, limite],
    )


# --- Tablas opcionales: una base creada por una version anterior puede no tenerlas -------------
def alertas(con: sqlite3.Connection, camaras: Sequence[str], limite: int = 100) -> List[Dict[str, Any]]:
    try:
        return _filas(
            con,
            "SELECT momento, tipo, track_id, valor, umbral, descripcion, camara FROM alertas "
            f"WHERE camara IN ({_marcadores(camaras)}) ORDER BY momento DESC LIMIT ?",
            [*camaras, limite],
        )
    except sqlite3.OperationalError:
        return []


def lecturas(con: sqlite3.Connection, camaras: Sequence[str]) -> List[Dict[str, Any]]:
    try:
        return _filas(
            con,
            "SELECT momento, vehiculos_roi, ratio_movimiento, estado FROM lecturas_trafico "
            f"WHERE camara IN ({_marcadores(camaras)}) ORDER BY momento",
            camaras,
        )
    except sqlite3.OperationalError:
        return []
