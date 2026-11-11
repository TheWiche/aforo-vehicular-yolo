"""
perfiles.py
===========
Perfiles de calibracion por video: donde estan las lineas, cuantos metros hay entre A y B y cual es
el limite de velocidad. Se guardan en `datos/calibraciones.json`, una entrada por NOMBRE de video:

    {
      "Prueba1_optimizado.mp4": {
        "CAMARA": "prueba1",
        "LINEA_CONTEO": [[550, 580], [550, 920]],
        "LINEA_VELOCIDAD_A": [[200, 620], [200, 940]],
        "LINEA_VELOCIDAD_B": [[900, 560], [900, 900]],
        "DISTANCIA_REAL_METROS": 4.7,
        "LIMITE_VELOCIDAD_KMH": 30.0,
        "VELOCIDAD_MAX_KMH": 80.0
      }
    }

Es la fuente de verdad de la calibracion: el menu, el dashboard web (calibrador) y el comando
`procesar --perfil` leen y escriben aqui. Los valores de `config.py` quedan como valores por defecto
para todo lo que un perfil no define.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aforo.config import RAIZ_PROYECTO, AppConfig, ConfigError

ARCHIVO_PERFILES: Path = RAIZ_PROYECTO / "datos" / "calibraciones.json"

# Claves que definen la calibracion (las usa tambien el menu). El resto (nota, regla...) es informativo.
CLAVES_PERFIL = ("CAMARA", "LINEA_CONTEO", "LINEA_VELOCIDAD_A", "LINEA_VELOCIDAD_B",
                 "DISTANCIA_REAL_METROS", "LIMITE_VELOCIDAD_KMH", "VELOCIDAD_MAX_KMH")
CLAVES_EXTRA = ("nota", "REGLA", "FECHA_INICIO_VIDEO")
LINEAS = ("LINEA_CONTEO", "LINEA_VELOCIDAD_A", "LINEA_VELOCIDAD_B")
NOMBRES_LINEAS = {"LINEA_CONTEO": "La línea de conteo", "LINEA_VELOCIDAD_A": "La línea A", "LINEA_VELOCIDAD_B": "La línea B"}

_PATRON_CAMARA = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
_CANDADO = threading.Lock()


# ---------------------------------------------------------------------------------------------
# Lectura y escritura
# ---------------------------------------------------------------------------------------------
def cargar(ruta: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Todos los perfiles guardados ({nombre_de_video: perfil}); {} si el archivo no existe o esta danado."""
    try:
        datos = json.loads((ruta or ARCHIVO_PERFILES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in datos.items() if isinstance(k, str) and isinstance(v, dict)} if isinstance(datos, dict) else {}


def guardar(video: str, perfil: Dict[str, Any], ruta: Optional[Path] = None) -> None:
    """
    Guarda (mezclando con lo que ya hubiera) el perfil de un video. La escritura es atomica:
    se escribe un archivo temporal y se renombra, asi un corte a mitad no deja el JSON roto.
    """
    destino = ruta or ARCHIVO_PERFILES
    video = Path(video).name
    with _CANDADO:
        todos = cargar(destino)
        todos.setdefault(video, {}).update({k: v for k, v in perfil.items() if k in CLAVES_PERFIL + CLAVES_EXTRA})
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_suffix(".json.tmp")
        temporal.write_text(json.dumps(todos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporal, destino)


# ---------------------------------------------------------------------------------------------
# Validacion
# ---------------------------------------------------------------------------------------------
def _punto(valor: Any) -> Optional[Tuple[float, float]]:
    try:
        x, y = valor
        x, y = float(x), float(y)
    except (TypeError, ValueError):
        return None
    return (x, y) if math.isfinite(x) and math.isfinite(y) else None


def _linea(valor: Any) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    try:
        p, q = valor
    except (TypeError, ValueError):
        return None
    p, q = _punto(p), _punto(q)
    return (p, q) if p and q else None


def _punto_medio(linea: Tuple[Tuple[float, float], Tuple[float, float]]) -> Tuple[float, float]:
    return ((linea[0][0] + linea[1][0]) / 2, (linea[0][1] + linea[1][1]) / 2)


def validar(perfil: Dict[str, Any], ancho: Optional[int] = None, alto: Optional[int] = None) -> Tuple[List[str], List[str]]:
    """
    Revisa un perfil. Devuelve (errores, avisos): con errores no se puede guardar ni usar; los avisos
    son sospechas (p. ej. la linea de conteo fuera del tramo A-B) que el usuario puede ignorar.
    """
    errores: List[str] = []
    avisos: List[str] = []

    camara = perfil.get("CAMARA")
    if camara is not None and not _PATRON_CAMARA.match(str(camara)):
        errores.append("El nombre de la cámara solo puede tener letras, números, guion y guion bajo (hasta 40).")

    lineas: Dict[str, Any] = {}
    for clave in LINEAS:
        if clave not in perfil:
            errores.append(f"Falta {NOMBRES_LINEAS[clave].lower()}.")
            continue
        linea = _linea(perfil[clave])
        if linea is None:
            errores.append(f"{NOMBRES_LINEAS[clave]} debe tener dos puntos (x, y).")
            continue
        lineas[clave] = linea
        if math.dist(*linea) < 10:
            errores.append(f"{NOMBRES_LINEAS[clave]} es demasiado corta (menos de 10 píxeles).")
        if ancho and alto:
            for x, y in linea:
                if not (0 <= x <= ancho and 0 <= y <= alto):
                    errores.append(f"{NOMBRES_LINEAS[clave]} sale del video ({ancho}×{alto} px).")
                    break

    distancia = perfil.get("DISTANCIA_REAL_METROS")
    if distancia is not None:
        try:
            d = float(distancia)
            if not 0.5 <= d <= 1000:
                errores.append("La distancia real entre A y B debe estar entre 0,5 y 1000 metros.")
        except (TypeError, ValueError):
            errores.append("La distancia real entre A y B debe ser un número.")
    limite, maxima = perfil.get("LIMITE_VELOCIDAD_KMH"), perfil.get("VELOCIDAD_MAX_KMH")
    for nombre, valor in (("El límite de velocidad", limite), ("La velocidad máxima creíble", maxima)):
        if valor is not None:
            try:
                if not 1 <= float(valor) <= 400:
                    errores.append(f"{nombre} debe estar entre 1 y 400 km/h.")
            except (TypeError, ValueError):
                errores.append(f"{nombre} debe ser un número.")
    if not errores and limite is not None and maxima is not None and float(maxima) <= float(limite):
        errores.append("La velocidad máxima creíble debe ser mayor que el límite de velocidad.")

    # --- Avisos de coherencia geometrica ---------------------------------------------------
    if all(k in lineas for k in LINEAS):
        a, b, conteo = _punto_medio(lineas["LINEA_VELOCIDAD_A"]), _punto_medio(lineas["LINEA_VELOCIDAD_B"]), _punto_medio(lineas["LINEA_CONTEO"])
        eje = (b[0] - a[0], b[1] - a[1])
        largo2 = eje[0] ** 2 + eje[1] ** 2
        if largo2 < 20 ** 2:
            errores.append("Las líneas A y B están casi en el mismo sitio: sepáralas a lo largo de la calle.")
        else:
            t = ((conteo[0] - a[0]) * eje[0] + (conteo[1] - a[1]) * eje[1]) / largo2
            if not 0.0 <= t <= 1.0:
                avisos.append("La línea de conteo debería quedar entre A y B: así cada vehículo se cuenta dentro del tramo medido.")
    if distancia is not None and not errores:
        try:
            if float(distancia) == 4.7 and perfil.get("CAMARA") not in (None, "prueba1"):
                avisos.append("La distancia es 4,7 m, el valor de otro video: mídela en este.")
        except (TypeError, ValueError):
            pass

    if "FECHA_INICIO_VIDEO" in perfil and perfil["FECHA_INICIO_VIDEO"] not in (None, ""):
        try:
            datetime.fromisoformat(str(perfil["FECHA_INICIO_VIDEO"]))
        except ValueError:
            errores.append("La hora de inicio debe tener el formato AAAA-MM-DD HH:MM:SS.")
    return errores, avisos


# ---------------------------------------------------------------------------------------------
# Aplicar un perfil a la configuracion
# ---------------------------------------------------------------------------------------------
def _linea_entera(valor: Any) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    linea = _linea(valor)
    if linea is None:
        raise ConfigError("Una línea del perfil no tiene dos puntos (x, y).")
    (x1, y1), (x2, y2) = linea
    return (int(round(x1)), int(round(y1))), (int(round(x2)), int(round(y2)))


def aplicar_a_config(config: AppConfig, perfil: Dict[str, Any]) -> AppConfig:
    """Devuelve una copia de `config` con los valores que define el perfil (lo demas queda igual)."""
    io, counter, speed, alertas = config.io, config.counter, config.speed, config.alertas
    try:
        if perfil.get("CAMARA"):
            io = dataclasses.replace(io, camara=str(perfil["CAMARA"]))
        if perfil.get("FECHA_INICIO_VIDEO"):
            io = dataclasses.replace(io, fecha_inicio=datetime.fromisoformat(str(perfil["FECHA_INICIO_VIDEO"])))
        if "LINEA_CONTEO" in perfil:
            counter = dataclasses.replace(counter, linea=_linea_entera(perfil["LINEA_CONTEO"]))
        cambios: Dict[str, Any] = {}
        if "LINEA_VELOCIDAD_A" in perfil:
            cambios["linea_a"] = _linea_entera(perfil["LINEA_VELOCIDAD_A"])
        if "LINEA_VELOCIDAD_B" in perfil:
            cambios["linea_b"] = _linea_entera(perfil["LINEA_VELOCIDAD_B"])
        if "DISTANCIA_REAL_METROS" in perfil:
            cambios["distancia_metros"] = float(perfil["DISTANCIA_REAL_METROS"])
        if "VELOCIDAD_MAX_KMH" in perfil:
            cambios["velocidad_max_kmh"] = float(perfil["VELOCIDAD_MAX_KMH"])
        speed = dataclasses.replace(speed, **cambios)
        if "LIMITE_VELOCIDAD_KMH" in perfil:
            alertas = dataclasses.replace(alertas, limite_velocidad_kmh=float(perfil["LIMITE_VELOCIDAD_KMH"]))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"El perfil de calibración tiene un valor inválido: {exc}") from exc
    nueva = dataclasses.replace(config, io=io, counter=counter, speed=speed, alertas=alertas)
    nueva.validate()
    return nueva


def sugerir(ancho: int, alto: int) -> Dict[str, Any]:
    """
    Perfil de partida para un video sin calibrar: tres lineas horizontales repartidas por la zona
    central (A arriba, conteo en medio, B abajo). Es solo un punto de partida para arrastrar.
    """
    x1, x2 = round(ancho * 0.2), round(ancho * 0.8)
    def y(f: float) -> int:
        return round(alto * f)
    return {
        "LINEA_VELOCIDAD_A": [[x1, y(0.40)], [x2, y(0.40)]],
        "LINEA_CONTEO": [[x1, y(0.55)], [x2, y(0.55)]],
        "LINEA_VELOCIDAD_B": [[x1, y(0.70)], [x2, y(0.70)]],
        "DISTANCIA_REAL_METROS": 10.0,
        "LIMITE_VELOCIDAD_KMH": 50.0,
        "VELOCIDAD_MAX_KMH": 120.0,
    }
