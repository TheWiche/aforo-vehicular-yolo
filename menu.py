"""
menu.py
=======
Menu interactivo en la terminal para PROBAR y CONFIGURAR todo el proyecto sin editar
archivos a mano:

    python menu.py

Que hace
--------
  * DIAGNOSTICO: revisa que dependencias, pesos, videos, calibracion y base de datos
    existen, y dice exactamente que falta y como arreglarlo.
  * CONFIGURACION (tipo CRUD sobre config.py): ver y modificar cada parametro con
    validacion de tipo y rango; si el cambio dejaria la configuracion invalida, se revierte.
  * VIDEOS: descargar los publicos, elegir cual procesar, calibrar las lineas haciendo clic.
  * PROCESAR, DASHBOARD, EVALUACION, PRUEBAS: cada accion comprueba primero sus requisitos y
    ofrece resolverlos (instalar, descargar, calibrar) antes de continuar.
  * BASE DE DATOS: resumen, ultimos cruces, alertas y borrado de una camara.

Este archivo usa SOLO la biblioteca estandar de Python, para que funcione incluso cuando
todavia no se han instalado las dependencias del proyecto (opencv, torch, etc.).

Como edita config.py
--------------------
Con el modulo `ast` se localiza la posicion EXACTA del valor de cada constante
(`NOMBRE: tipo = valor  # comentario`) y se reemplaza solo ese fragmento: los comentarios y
el resto del archivo quedan intactos. Despues se valida con `cargar_configuracion()` en un
proceso aparte; si falla, se restaura el texto anterior.
"""

from __future__ import annotations

import ast
import json
import importlib.util
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

RAIZ = Path(__file__).resolve().parent
CONFIG_PY = RAIZ / "config.py"
PY = sys.executable

EXTENSIONES_VIDEO = (".mp4", ".avi", ".mov", ".mkv")

# Dependencias: modulo importable -> (paquete pip, para que sirve)
DEPENDENCIAS_NUCLEO: Dict[str, Tuple[str, str]] = {
    "numpy": ("numpy", "calculo numerico"),
    "cv2": ("opencv-python", "lectura de video e imagen"),
    "torch": ("torch", "red neuronal de YOLO"),
    "ultralytics": ("ultralytics", "YOLOv8 (deteccion)"),
    "supervision": ("supervision", "anotaciones y video"),
    "trackers": ("trackers", "ByteTrack (seguimiento)"),
    "scipy": ("scipy", "asignacion del tracker"),
    "tqdm": ("tqdm", "barra de progreso"),
}
DEPENDENCIAS_DASHBOARD: Dict[str, Tuple[str, str]] = {
    "streamlit": ("streamlit", "dashboard web"),
    "plotly": ("plotly", "graficos del dashboard"),
    "pandas": ("pandas", "tablas del dashboard"),
}

# Calibracion de ejemplo por defecto de config.py (pensada para 1280x720, sin medir nada).
VALORES_EJEMPLO: Dict[str, Any] = {
    "LINEA_CONTEO": ((0, 400), (1280, 400)),
    "LINEA_VELOCIDAD_A": ((200, 300), (1100, 300)),
    "LINEA_VELOCIDAD_B": ((100, 550), (1200, 550)),
    "DISTANCIA_REAL_METROS": 20.0,
}

# Calibraciones ya probadas de punta a punta con los videos publicos. La distancia es una
# SUPOSICION: sirve para ver el sistema funcionando, no para medir velocidades reales.
PRESETS: Dict[str, Dict[str, Any]] = {
    "autopista_1.mp4": {
        "LINEA_CONTEO": ((900, 1350), (3150, 1350)),
        "LINEA_VELOCIDAD_A": ((990, 990), (3000, 990)),
        "LINEA_VELOCIDAD_B": ((600, 1680), (3570, 1680)),
        "DISTANCIA_REAL_METROS": 50.0,
    },
}


# =============================================================================
# Utilidades de consola
# =============================================================================
def configurar_consola() -> None:
    """Evita errores de codificacion en consolas de Windows."""
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def titulo(texto: str) -> None:
    print(f"\n{'=' * 64}\n {texto}\n{'=' * 64}")


def pedir(texto: str, defecto: Optional[str] = None) -> str:
    """Pide una linea. Ctrl+C / Ctrl+D lanzan KeyboardInterrupt hacia el menu."""
    sufijo = f" [{defecto}]" if defecto not in (None, "") else ""
    try:
        respuesta = input(f"{texto}{sufijo}: ").strip()
    except EOFError:
        raise KeyboardInterrupt from None
    return respuesta if respuesta else (defecto or "")


def confirmar(texto: str, defecto: bool = False) -> bool:
    marca = "S/n" if defecto else "s/N"
    r = pedir(f"{texto} ({marca})").lower()
    if not r:
        return defecto
    return r in ("s", "si", "sí", "y", "yes", "1", "true")


def pausa() -> None:
    try:
        input("\nEnter para continuar...")
    except EOFError:
        pass


def elegir(opciones: Sequence[str], texto: str = "Opcion", con_volver: bool = True,
           etiqueta_cero: str = "Volver") -> Optional[int]:
    """Muestra una lista numerada y devuelve el indice elegido (None = volver)."""
    for i, o in enumerate(opciones, 1):
        print(f"  {i:>2}) {o}")
    if con_volver:
        print(f"   0) {etiqueta_cero}")
    while True:
        r = pedir(texto)
        if r in ("", "0") and con_volver:
            return None
        if r.isdigit() and 1 <= int(r) <= len(opciones):
            return int(r) - 1
        print("  Opcion no valida.")


# =============================================================================
# Lectura y escritura de config.py (CRUD de parametros)
# =============================================================================
@dataclass(frozen=True)
class Constante:
    """Una constante editable de config.py y donde esta su valor dentro del texto."""
    nombre: str
    valor: Any
    linea: int          # 1-based
    col_ini: int        # posicion en BYTES (utf-8) del inicio del valor dentro de la linea
    col_fin: int


def _lineas(texto: str) -> List[str]:
    """Divide en lineas conservando el salto (solo '\\n', igual que el modulo ast)."""
    return re.split(r"(?<=\n)", texto)


def leer_constantes(texto: str) -> Dict[str, Constante]:
    """Constantes de nivel superior con valor literal en UNA sola linea (las unicas editables)."""
    encontradas: Dict[str, Constante] = {}
    for nodo in ast.parse(texto).body:
        if isinstance(nodo, ast.AnnAssign) and isinstance(nodo.target, ast.Name) and nodo.value is not None:
            nombre, valor_nodo = nodo.target.id, nodo.value
        elif isinstance(nodo, ast.Assign) and len(nodo.targets) == 1 and isinstance(nodo.targets[0], ast.Name):
            nombre, valor_nodo = nodo.targets[0].id, nodo.value
        else:
            continue
        if not nombre.isupper() or valor_nodo.lineno != valor_nodo.end_lineno:
            continue
        try:
            valor = ast.literal_eval(valor_nodo)
        except (ValueError, SyntaxError):
            continue            # p. ej. Path(...): no es un literal
        encontradas[nombre] = Constante(nombre, valor, valor_nodo.lineno,
                                        valor_nodo.col_offset, valor_nodo.end_col_offset)
    return encontradas


def formatear_valor(valor: Any) -> str:
    """Texto Python valido para un valor (cadenas con comillas dobles, como el resto del archivo)."""
    if isinstance(valor, str):
        return json.dumps(valor, ensure_ascii=False)
    return repr(valor)


def reemplazar_constante(texto: str, nombre: str, valor: Any) -> str:
    """Devuelve `texto` con el valor de `nombre` cambiado; comentarios y demas lineas intactos."""
    constante = leer_constantes(texto).get(nombre)
    if constante is None:
        raise KeyError(f"{nombre} no es una constante editable de config.py")
    lineas = _lineas(texto)
    cruda = lineas[constante.linea - 1].encode("utf-8")
    nueva = cruda[: constante.col_ini] + formatear_valor(valor).encode("utf-8") + cruda[constante.col_fin:]
    lineas[constante.linea - 1] = nueva.decode("utf-8")
    return "".join(lineas)


def validar_config_en_subproceso() -> Optional[str]:
    """Carga y valida config.py en un proceso limpio. Devuelve None si esta bien, o el error."""
    # Se ejecuta el TEXTO de config.py sin pasar por la cache de bytecode (.pyc): Python la
    # invalida por fecha (en segundos) y tamano, y dos versiones del archivo editadas en el
    # mismo segundo con igual tamano (p. ej. 20.0 -> -5.0) podrian validarse con la vieja.
    codigo = (
        "import sys, types; sys.path.insert(0, '.'); "
        "import os; m = types.ModuleType('config'); m.__file__ = os.path.abspath('config.py'); "
        "sys.modules['config'] = m; "
        "exec(compile(open('config.py', encoding='utf-8').read(), 'config.py', 'exec'), m.__dict__); "
        "m.cargar_configuracion()"
    )
    r = subprocess.run([PY, "-c", codigo], cwd=RAIZ, capture_output=True, text=True)
    if r.returncode == 0:
        return None
    ultima = [l for l in r.stderr.strip().splitlines() if l.strip()]
    return ultima[-1] if ultima else "error desconocido"


def aplicar_cambios(cambios: Dict[str, Any]) -> Optional[str]:
    """
    Escribe uno o varios valores en config.py y valida el resultado. Si queda invalido,
    restaura el archivo original y devuelve el mensaje de error (None = todo bien).
    """
    original = CONFIG_PY.read_text(encoding="utf-8")
    nuevo = original
    for nombre, valor in cambios.items():
        nuevo = reemplazar_constante(nuevo, nombre, valor)
    CONFIG_PY.write_text(nuevo, encoding="utf-8", newline="")
    error = validar_config_en_subproceso()
    if error is not None:
        CONFIG_PY.write_text(original, encoding="utf-8", newline="")
    return error


def valores_actuales() -> Dict[str, Any]:
    return {n: c.valor for n, c in leer_constantes(CONFIG_PY.read_text(encoding="utf-8")).items()}


# --- Catalogo de parametros: (nombre, tipo, ayuda, extra) ---------------------------------
@dataclass(frozen=True)
class Parametro:
    nombre: str
    tipo: str            # ruta | texto | float | int | bool | fecha | dispositivo | ancla | linea
    ayuda: str
    minimo: Optional[float] = None
    maximo: Optional[float] = None


ANCLAS = ["BOTTOM_CENTER", "CENTER", "TOP_CENTER", "CENTER_LEFT", "CENTER_RIGHT",
          "BOTTOM_LEFT", "BOTTOM_RIGHT", "TOP_LEFT", "TOP_RIGHT"]

GRUPOS: Dict[str, List[Parametro]] = {
    "Video, base de datos y camara": [
        Parametro("VIDEO_ENTRADA", "ruta", "Video que se procesa (ruta relativa al proyecto)"),
        Parametro("VIDEO_SALIDA", "ruta", "Video anotado resultante"),
        Parametro("DB_RUTA", "ruta", "Base de datos SQLite"),
        Parametro("CAMARA", "texto", "Nombre de la camara guardado en cada cruce"),
        Parametro("FECHA_INICIO_VIDEO", "fecha", "Hora real del primer frame 'AAAA-MM-DD HH:MM:SS' (vacio = ahora)"),
    ],
    "Lineas y distancia (calibracion)": [
        Parametro("LINEA_CONTEO", "linea", "Linea de conteo: x1,y1,x2,y2 en pixeles del video"),
        Parametro("LINEA_VELOCIDAD_A", "linea", "Linea A (entrada de la ROI): x1,y1,x2,y2"),
        Parametro("LINEA_VELOCIDAD_B", "linea", "Linea B (salida de la ROI): x1,y1,x2,y2"),
        Parametro("DISTANCIA_REAL_METROS", "float", "Distancia REAL en metros entre A y B (medirla en el sitio)", 0.1),
        Parametro("VELOCIDAD_MIN_KMH", "float", "Velocidades menores se descartan", 0),
        Parametro("VELOCIDAD_MAX_KMH", "float", "Velocidades mayores se descartan (error de tracking)", 1),
        Parametro("ETIQUETA_SENTIDO_A", "texto", "Nombre del sentido A en el video"),
        Parametro("ETIQUETA_SENTIDO_B", "texto", "Nombre del sentido B en el video"),
    ],
    "Alertas": [
        Parametro("LIMITE_VELOCIDAD_KMH", "float", "Limite de velocidad que dispara la alerta", 1),
        Parametro("DETENIDO_MIN_VEHICULOS", "int", "Vehiculos minimos en la ROI para considerar transito detenido", 1),
        Parametro("DETENIDO_RATIO_MAX", "float", "Fraccion de movimiento (0-1) bajo la cual 'no se mueven'", 0.001, 1),
        Parametro("DETENIDO_SEGUNDOS", "float", "Segundos sostenidos para alertar", 0.1),
        Parametro("SALIDA_DETENIDO_SEGUNDOS", "float", "Segundos normales para terminar el episodio", 0.1),
        Parametro("CALENTAMIENTO_SEGUNDOS", "float", "Segundos iniciales sin alertas de movimiento", 0),
        Parametro("INTERVALO_LECTURA_S", "float", "Cada cuantos segundos se guarda una lectura de la via", 0.1),
    ],
    "Analisis de movimiento": [
        Parametro("MOV_ESCALA", "float", "Escala de procesamiento (0-1]", 0.01, 1),
        Parametro("MOV_ALFA_FONDO", "float", "Peso del frame nuevo en el fondo (0-1]", 0.001, 1),
        Parametro("MOV_UMBRAL_DIFERENCIA", "int", "Umbral de diferencia de gris (0-255)", 0, 255),
        Parametro("MOV_KERNEL_APERTURA", "int", "Tamano impar del kernel de apertura", 1),
        Parametro("MOV_KERNEL_CIERRE", "int", "Tamano impar del kernel de cierre", 1),
    ],
    "Detector y tracker": [
        Parametro("MODELO", "ruta", "Pesos YOLO (yolov8n/s/m/l/x.pt)"),
        Parametro("CONFIANZA_MINIMA", "float", "Confianza minima de deteccion (0-1]", 0.01, 1),
        Parametro("IOU_NMS", "float", "Umbral IoU de la supresion de no-maximos (0-1]", 0.01, 1),
        Parametro("TAMANO_IMAGEN", "int", "Lado mayor de entrada a la red (px)", 32),
        Parametro("DISPOSITIVO", "dispositivo", "None = automatico | cpu | 0 (GPU)"),
        Parametro("ANCLA_VEHICULO", "ancla", "Punto del cuadro que representa al vehiculo"),
        Parametro("TRACK_BUFFER_FRAMES", "int", "Frames (a 30 FPS) que se recuerda un ID perdido", 1),
        Parametro("UMBRAL_ACTIVACION_TRACK", "float", "Confianza para crear un track (0-1)", 0, 1),
        Parametro("UMBRAL_ALTA_CONFIANZA", "float", "Separa detecciones fuertes de debiles (0-1)", 0, 1),
        Parametro("UMBRAL_IOU_ASOCIACION", "float", "IoU minimo deteccion<->track (0-1)", 0, 1),
        Parametro("FRAMES_CONSECUTIVOS_MIN", "int", "Apariciones seguidas para confirmar un ID", 1),
    ],
    "Visualizacion": [
        Parametro("MOSTRAR_VENTANA", "bool", "Abrir ventana en vivo al procesar"),
        Parametro("DIBUJAR_ESTELA", "bool", "Dibujar trayectoria reciente"),
        Parametro("LARGO_ESTELA", "int", "Frames de la estela", 1),
    ],
}


def parsear_valor(p: Parametro, texto: str) -> Any:
    """Convierte lo que escribio el usuario al valor Python correcto. Lanza ValueError si no sirve."""
    t = texto.strip()
    if p.tipo in ("ruta", "texto"):
        if not t:
            raise ValueError("no puede estar vacio")
        return t.replace("\\", "/") if p.tipo == "ruta" else t
    if p.tipo in ("float", "int"):
        try:
            numero = float(t.replace(",", ".")) if p.tipo == "float" else int(t)
        except ValueError:
            raise ValueError(f"se esperaba un numero {'decimal' if p.tipo == 'float' else 'entero'}") from None
        if p.minimo is not None and numero < p.minimo:
            raise ValueError(f"debe ser >= {p.minimo:g}")
        if p.maximo is not None and numero > p.maximo:
            raise ValueError(f"debe ser <= {p.maximo:g}")
        return numero
    if p.tipo == "bool":
        if t.lower() in ("s", "si", "sí", "true", "1", "y", "yes"):
            return True
        if t.lower() in ("n", "no", "false", "0"):
            return False
        raise ValueError("responde s o n")
    if p.tipo == "fecha":
        if t.lower() in ("", "none", "ninguna", "ahora"):
            return None
        try:
            datetime.fromisoformat(t)
        except ValueError:
            raise ValueError("usa el formato AAAA-MM-DD HH:MM:SS") from None
        return t
    if p.tipo == "dispositivo":
        return None if t.lower() in ("", "none", "auto") else t
    if p.tipo == "ancla":
        if t.upper() not in ANCLAS:
            raise ValueError(f"opciones: {', '.join(ANCLAS)}")
        return t.upper()
    if p.tipo == "linea":
        numeros = re.findall(r"-?\d+(?:\.\d+)?", t)      # la coma separa coordenadas, no decimales
        if len(numeros) != 4:
            raise ValueError("escribe 4 numeros: x1,y1,x2,y2")
        v = [float(n) for n in numeros]
        v = [int(x) if x == int(x) else x for x in v]
        return ((v[0], v[1]), (v[2], v[3]))
    raise ValueError(f"tipo desconocido: {p.tipo}")


def parsear_salida_seleccionar(texto: str) -> Dict[str, Any]:
    """Extrae `LINEA_X = ((x, y), (x, y))` de lo que imprime seleccionar_puntos.py."""
    resultado: Dict[str, Any] = {}
    for m in re.finditer(r"^(LINEA_\w+)\s*=\s*(\(\(.*\)\))\s*$", texto, flags=re.MULTILINE):
        try:
            resultado[m.group(1)] = ast.literal_eval(m.group(2))
        except (ValueError, SyntaxError):
            continue
    return resultado


# =============================================================================
# Diagnostico del entorno y del proyecto
# =============================================================================
def modulo_instalado(nombre: str) -> bool:
    try:
        return importlib.util.find_spec(nombre) is not None
    except (ImportError, ValueError):
        return False


def dependencias_faltantes(incluir_dashboard: bool = False) -> List[str]:
    """Nombres de paquetes pip que faltan."""
    grupos = [DEPENDENCIAS_NUCLEO] + ([DEPENDENCIAS_DASHBOARD] if incluir_dashboard else [])
    return [pip for g in grupos for mod, (pip, _) in g.items() if not modulo_instalado(mod)]


def en_entorno_virtual() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def info_video(ruta: Path) -> Optional[Tuple[int, int, float, int]]:
    """(ancho, alto, fps, frames) o None si OpenCV no esta o el video no se abre."""
    if not modulo_instalado("cv2"):
        return None
    import cv2  # importacion tardia: el menu debe arrancar sin OpenCV

    cap = cv2.VideoCapture(str(ruta))
    try:
        if not cap.isOpened():
            return None
        return (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                float(cap.get(cv2.CAP_PROP_FPS)), int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
    finally:
        cap.release()


def listar_videos() -> List[Path]:
    carpeta = RAIZ / "videos"
    if not carpeta.is_dir():
        return []
    return sorted(p for p in carpeta.iterdir() if p.suffix.lower() in EXTENSIONES_VIDEO)


def ruta_absoluta(ruta: str) -> Path:
    p = Path(ruta)
    return p if p.is_absolute() else RAIZ / p


def lineas_fuera_de_cuadro(vals: Dict[str, Any], ancho: int, alto: int) -> List[str]:
    """Nombres de las lineas con algun punto fuera del video."""
    malas = []
    for nombre in ("LINEA_CONTEO", "LINEA_VELOCIDAD_A", "LINEA_VELOCIDAD_B"):
        for x, y in vals.get(nombre, ()):
            if not (0 <= x <= ancho and 0 <= y <= alto):
                malas.append(nombre)
                break
    return malas


def es_calibracion_de_ejemplo(vals: Dict[str, Any]) -> bool:
    return all(vals.get(k) == v for k, v in VALORES_EJEMPLO.items())


def resumen_bd(ruta_db: Path) -> Optional[List[Tuple[str, int, int, int, int]]]:
    """[(camara, cruces, con_velocidad, alertas, ...)] o None si la BD/tabla no existe."""
    if not ruta_db.is_file():
        return None
    con = sqlite3.connect(str(ruta_db))
    try:
        filas = con.execute(
            "SELECT c.camara, COUNT(*), COUNT(c.velocidad_kmh), "
            "(SELECT COUNT(*) FROM alertas a WHERE a.camara = c.camara), 0 "
            "FROM cruces c GROUP BY c.camara ORDER BY c.camara"
        ).fetchall()
    except sqlite3.Error:
        try:    # BD creada con una version anterior (sin tabla alertas)
            filas = con.execute(
                "SELECT camara, COUNT(*), COUNT(velocidad_kmh), 0, 0 FROM cruces GROUP BY camara"
            ).fetchall()
        except sqlite3.Error:
            return None
    finally:
        con.close()
    return filas


def diagnostico(detallado: bool = True) -> Dict[str, bool]:
    """Imprime el estado del proyecto. Devuelve banderas que usan los demas menus."""
    vals = valores_actuales()
    estado: Dict[str, bool] = {}

    titulo("DIAGNOSTICO")
    # --- Python y entorno --------------------------------------------------------------
    ok_py = sys.version_info >= (3, 10)
    print(f"[{'OK' if ok_py else 'X '}] Python {sys.version.split()[0]} (se necesita >= 3.10)")
    print(f"[{'OK' if en_entorno_virtual() else '! '}] Entorno virtual: "
          f"{'activo' if en_entorno_virtual() else 'no activo (recomendado: python -m venv .venv)'}")

    # --- Dependencias -----------------------------------------------------------------
    falta_n = dependencias_faltantes(False)
    falta_d = [p for p in dependencias_faltantes(True) if p not in falta_n]
    estado["deps_nucleo"], estado["deps_dashboard"] = not falta_n, not falta_d
    print(f"[{'OK' if not falta_n else 'X '}] Dependencias para procesar video"
          + ("" if not falta_n else f": faltan {', '.join(falta_n)}"))
    print(f"[{'OK' if not falta_d else 'X '}] Dependencias del dashboard"
          + ("" if not falta_d else f": faltan {', '.join(falta_d)}"))
    if falta_n or falta_d:
        print("      -> Menu principal, opcion 'Instalar dependencias'.")

    # --- Configuracion ------------------------------------------------------------------
    error = validar_config_en_subproceso()
    estado["config_valida"] = error is None
    print(f"[{'OK' if error is None else 'X '}] config.py " + ("valida" if error is None else f"INVALIDA: {error}"))

    # --- Pesos --------------------------------------------------------------------------
    pesos = ruta_absoluta(str(vals.get("MODELO", "models/yolov8s.pt")))
    estado["pesos"] = pesos.is_file()
    print(f"[{'OK' if pesos.is_file() else '! '}] Pesos YOLO {pesos.name}: "
          + ("presentes" if pesos.is_file() else "faltan (se descargan solos en la primera ejecucion; requiere internet)"))

    # --- Videos -------------------------------------------------------------------------
    videos = listar_videos()
    estado["hay_videos"] = bool(videos)
    print(f"[{'OK' if videos else 'X '}] Videos en videos/: " + (f"{len(videos)}" if videos else "ninguno"))
    if videos and detallado:
        for v in videos:
            i = info_video(v)
            extra = f"{i[0]}x{i[1]} @ {i[2]:.0f} FPS, {i[3]} frames" if i else f"{v.stat().st_size / 1e6:.1f} MB"
            print(f"        - {v.name}  ({extra})")
    if not videos:
        print("      -> Menu 'Videos', opcion 'Descargar videos de prueba'.")

    # --- Video activo y calibracion ---------------------------------------------------------
    activo = ruta_absoluta(str(vals.get("VIDEO_ENTRADA", "")))
    estado["video_activo"] = activo.is_file()
    print(f"[{'OK' if activo.is_file() else 'X '}] Video activo (VIDEO_ENTRADA): {vals.get('VIDEO_ENTRADA')}"
          + ("" if activo.is_file() else "  -> no existe; elige uno en el menu 'Videos'"))
    estado["calibrado"] = False
    if activo.is_file():
        info = info_video(activo)
        if info is None:
            print("[! ] No se pudo leer el video activo (falta OpenCV o el archivo esta danado).")
        else:
            malas = lineas_fuera_de_cuadro(vals, info[0], info[1])
            if malas:
                print(f"[X ] Lineas fuera del video ({info[0]}x{info[1]}): {', '.join(malas)}  -> menu 'Calibrar'")
            elif es_calibracion_de_ejemplo(vals):
                print("[! ] Calibracion = valores de ejemplo de config.py; las velocidades no tendran sentido -> menu 'Calibrar'")
            else:
                estado["calibrado"] = True
                print(f"[OK] Lineas dentro del video ({info[0]}x{info[1]}), distancia {vals.get('DISTANCIA_REAL_METROS')} m")
                if activo.name in PRESETS and PRESETS[activo.name]["DISTANCIA_REAL_METROS"] == vals.get("DISTANCIA_REAL_METROS"):
                    print("      (distancia supuesta: sirve para probar, no para medir velocidades reales)")

    # --- Base de datos ------------------------------------------------------------------------
    ruta_db = ruta_absoluta(str(vals.get("DB_RUTA", "db/database.db")))
    filas = resumen_bd(ruta_db)
    estado["bd_con_datos"] = bool(filas)
    if filas is None:
        print(f"[! ] Base de datos {vals.get('DB_RUTA')}: aun no existe (se crea al procesar un video)")
    elif not filas:
        print(f"[! ] Base de datos {vals.get('DB_RUTA')}: existe pero sin cruces")
    else:
        print(f"[OK] Base de datos {vals.get('DB_RUTA')}: " + "; ".join(f"{c}: {n} cruces" for c, n, *_ in filas))

    # --- Verdad de terreno ---------------------------------------------------------------------
    gts = sorted((RAIZ / "evaluacion").glob("*.json")) if (RAIZ / "evaluacion").is_dir() else []
    estado["hay_gt"] = bool(gts)
    print(f"[{'OK' if gts else '! '}] Verdad de terreno (evaluacion/*.json): "
          + (", ".join(g.stem for g in gts) if gts else "ninguna (necesaria para las metricas)"))
    return estado


# =============================================================================
# Acciones (cada una comprueba sus requisitos primero)
# =============================================================================
def ejecutar(comando: Sequence[str], descripcion: str) -> int:
    """Ejecuta un comando mostrando su salida en vivo. Ctrl+C lo detiene y vuelve al menu."""
    print(f"\n> {descripcion}\n  $ {' '.join(str(c) for c in comando)}\n")
    try:
        return subprocess.run(list(comando), cwd=RAIZ).returncode
    except KeyboardInterrupt:
        print("\n(Detenido con Ctrl+C)")
        return 130
    except FileNotFoundError as exc:
        print(f"No se pudo ejecutar: {exc}")
        return 127


def instalar_dependencias() -> bool:
    titulo("INSTALAR DEPENDENCIAS")
    falta = dependencias_faltantes(True)
    if not falta:
        print("Todas las dependencias ya estan instaladas.")
        return True
    print(f"Faltan: {', '.join(falta)}")
    if not en_entorno_virtual():
        print("AVISO: no hay entorno virtual activo; se instalaria en el Python global.\n"
              "Recomendado: cierra el menu, ejecuta `python -m venv .venv`, activalo\n"
              "(.venv\\Scripts\\activate) y vuelve a abrir `python menu.py`.")
    if not (RAIZ / "requirements.txt").is_file():
        print("No se encuentra requirements.txt.")
        return False
    if not confirmar("Instalar con `pip install -r requirements.txt` (puede tardar varios minutos)", False):
        return False
    codigo = ejecutar([PY, "-m", "pip", "install", "-r", "requirements.txt"], "Instalando dependencias")
    ok = codigo == 0 and not dependencias_faltantes(True)
    print("\nInstalacion completada." if ok else "\nLa instalacion no termino bien (revisa los mensajes de arriba).")
    return ok


def asegurar_dependencias(incluir_dashboard: bool = False) -> bool:
    """True si se puede continuar; si faltan paquetes, ofrece instalarlos."""
    falta = dependencias_faltantes(incluir_dashboard)
    if not falta:
        return True
    print(f"\n[X] Faltan dependencias: {', '.join(falta)}")
    if confirmar("Instalarlas ahora", True):
        return instalar_dependencias() and not dependencias_faltantes(incluir_dashboard)
    return False


def asegurar_config_valida() -> bool:
    error = validar_config_en_subproceso()
    if error is None:
        return True
    print(f"\n[X] config.py es invalida: {error}\n    Corrigela en el menu 'Configuracion'.")
    return False


def descargar_videos() -> None:
    titulo("DESCARGAR VIDEOS DE PRUEBA")
    if not modulo_instalado("tqdm") or not modulo_instalado("cv2"):
        print("[X] descargar_videos.py necesita tqdm y opencv-python.")
        if not asegurar_dependencias(False):
            return
    ejecutar([PY, "descargar_videos.py"], "Descargando (los que ya existen se omiten)")


def elegir_video() -> Optional[Path]:
    """Elige el video activo; actualiza VIDEO_ENTRADA y CAMARA. Ofrece descargar si no hay."""
    videos = listar_videos()
    if not videos:
        print("\n[X] No hay videos en videos/.")
        if confirmar("Descargar los videos de prueba ahora", True):
            descargar_videos()
            videos = listar_videos()
        if not videos:
            print("Copia un video a videos/ o descarga los de prueba.")
            return None
    etiquetas = []
    for v in videos:
        i = info_video(v)
        etiquetas.append(f"{v.name}  ({i[0]}x{i[1]}, {i[3] / i[2]:.0f} s)" if i and i[2] else v.name)
    idx = elegir(etiquetas, "Video a usar")
    if idx is None:
        return None
    video = videos[idx]
    error = aplicar_cambios({"VIDEO_ENTRADA": f"videos/{video.name}", "CAMARA": video.stem})
    if error:
        print(f"[X] No se pudo actualizar config.py: {error}")
        return None
    print(f"\nVideo activo: videos/{video.name}   camara: {video.stem}")
    if video.name in PRESETS and confirmar("Hay una calibracion probada para este video. Aplicarla", True):
        aplicar_preset(video.name)
    return video


def aplicar_preset(nombre_video: str) -> bool:
    error = aplicar_cambios(dict(PRESETS[nombre_video]))
    if error:
        print(f"[X] No se pudo aplicar: {error}")
        return False
    print("Calibracion aplicada (la distancia de 50 m es una SUPOSICION: sirve para probar, no para medir).")
    return True


def calibrar() -> None:
    titulo("CALIBRAR LINEAS")
    vals = valores_actuales()
    activo = ruta_absoluta(str(vals.get("VIDEO_ENTRADA", "")))
    if not activo.is_file():
        print("[X] El video activo no existe.")
        if elegir_video() is None:
            return
        vals = valores_actuales()
        activo = ruta_absoluta(str(vals["VIDEO_ENTRADA"]))
    info = info_video(activo)
    if info:
        print(f"Video: {activo.name}  {info[0]}x{info[1]}")
    opciones = ["Hacer clic sobre un frame del video (ventana)", "Escribir las coordenadas a mano",
                "Medir/cambiar solo la distancia real entre A y B"]
    if activo.name in PRESETS:
        opciones.append("Aplicar la calibracion probada para este video")
    idx = elegir(opciones)
    if idx is None:
        return
    if idx == 0:
        if not asegurar_dependencias(False):
            return
        print("\nSe abrira una ventana. Orden de clics (2 por linea):\n"
              "  1-2 LINEA_CONTEO | 3-4 LINEA_VELOCIDAD_A | 5-6 LINEA_VELOCIDAD_B\n"
              "Teclas: u deshace, q termina.")
        frame = pedir("Indice del frame a mostrar", "0")
        r = subprocess.run([PY, "seleccionar_puntos.py", "--video", str(activo), "--frame", frame],
                           cwd=RAIZ, capture_output=True, text=True)
        lineas = parsear_salida_seleccionar(r.stdout)
        if r.returncode != 0 or not lineas:
            print(r.stderr.strip() or "No se marco ninguna linea completa.")
            return
        print("Lineas marcadas:", ", ".join(f"{k}={v}" for k, v in lineas.items()))
        if confirmar("Guardar en config.py", True):
            error = aplicar_cambios(lineas)
            print("[X] " + error if error else "Guardado.")
    elif idx == 1:
        for nombre in ("LINEA_CONTEO", "LINEA_VELOCIDAD_A", "LINEA_VELOCIDAD_B"):
            editar_parametro(_buscar_parametro(nombre))
    elif idx == 2:
        editar_parametro(_buscar_parametro("DISTANCIA_REAL_METROS"))
    elif idx == 3:
        aplicar_preset(activo.name)
    # Comprobacion final contra el tamano real del video
    if info:
        malas = lineas_fuera_de_cuadro(valores_actuales(), info[0], info[1])
        if malas:
            print(f"\n[!] Aun hay lineas fuera del video ({info[0]}x{info[1]}): {', '.join(malas)}")


def _buscar_parametro(nombre: str) -> Parametro:
    for lista in GRUPOS.values():
        for p in lista:
            if p.nombre == nombre:
                return p
    raise KeyError(nombre)


def editar_parametro(p: Parametro) -> None:
    """Pide un valor nuevo, lo valida (tipo y rango) y lo guarda; revierte si config queda invalida."""
    actual = valores_actuales().get(p.nombre, "?")
    print(f"\n{p.nombre} = {actual!r}\n  {p.ayuda}")
    while True:
        texto = pedir("Nuevo valor (Enter = no cambiar" + (", 'none' = sin valor" if p.tipo in ("fecha", "dispositivo") else "") + ")")
        if texto == "":
            print("Sin cambios.")
            return
        try:
            valor = parsear_valor(p, texto)
            break
        except ValueError as exc:
            print(f"  Valor no valido: {exc}")
    error = aplicar_cambios({p.nombre: valor})
    print(f"[X] No se guardo, config.py quedaria invalida: {error}" if error else f"Guardado: {p.nombre} = {valor!r}")


def menu_configuracion() -> None:
    while True:
        titulo("CONFIGURACION (config.py)")
        nombres = list(GRUPOS) + ["Ver TODOS los parametros", "Restaurar config.py desde git (descarta cambios)"]
        idx = elegir(nombres, "Grupo")
        if idx is None:
            return
        if idx == len(GRUPOS):
            vals = valores_actuales()
            for grupo, lista in GRUPOS.items():
                print(f"\n-- {grupo}")
                for p in lista:
                    print(f"   {p.nombre:<28} = {vals.get(p.nombre)!r}")
            pausa()
            continue
        if idx == len(GRUPOS) + 1:
            if confirmar("Esto descarta TODOS los cambios de config.py. Continuar", False):
                ejecutar(["git", "checkout", "--", "config.py"], "Restaurando config.py")
            continue
        lista = GRUPOS[nombres[idx]]
        while True:
            vals = valores_actuales()
            print(f"\n-- {nombres[idx]}")
            j = elegir([f"{p.nombre:<26} = {vals.get(p.nombre)!r}" for p in lista], "Parametro a editar")
            if j is None:
                break
            editar_parametro(lista[j])


def procesar_video(forzar_pregunta_reemplazo: bool = True, ofrecer_dashboard: bool = True) -> bool:
    """Valida todo y ejecuta main.py. Devuelve True si el procesamiento termino bien."""
    titulo("PROCESAR VIDEO")
    if not asegurar_dependencias(False) or not asegurar_config_valida():
        return False
    vals = valores_actuales()
    activo = ruta_absoluta(str(vals.get("VIDEO_ENTRADA", "")))
    if not activo.is_file():
        print(f"[X] No existe el video activo: {vals.get('VIDEO_ENTRADA')}")
        if elegir_video() is None:
            return False
        vals = valores_actuales()
        activo = ruta_absoluta(str(vals["VIDEO_ENTRADA"]))
    info = info_video(activo)
    if info is None:
        print("[X] OpenCV no puede abrir el video (archivo danado o formato no soportado).")
        return False
    malas = lineas_fuera_de_cuadro(vals, info[0], info[1])
    if malas:
        print(f"[X] Lineas fuera del video ({info[0]}x{info[1]}): {', '.join(malas)}")
        if activo.name in PRESETS and confirmar("Aplicar la calibracion probada de este video", True):
            aplicar_preset(activo.name)
        elif confirmar("Calibrar ahora", True):
            calibrar()
        if lineas_fuera_de_cuadro(valores_actuales(), info[0], info[1]):
            print("Siguen fuera del video: no se procesa.")
            return False
        vals = valores_actuales()
    if es_calibracion_de_ejemplo(vals):
        print("[!] La calibracion es la de ejemplo: el conteo puede ser incorrecto y las velocidades no tendran sentido.")
        if not confirmar("Continuar de todos modos", False):
            return False
    if not (ruta_absoluta(str(vals.get("MODELO", ""))).is_file()):
        print("[!] No estan los pesos de YOLO: se descargaran solos (necesita internet).")
        if not confirmar("Continuar", True):
            return False

    camara = str(vals.get("CAMARA", ""))
    filas = resumen_bd(ruta_absoluta(str(vals.get("DB_RUTA", "db/database.db")))) or []
    previos = next((n for c, n, *_ in filas if c == camara), 0)
    comando = [PY, "main.py"]
    if previos:
        print(f"[!] La camara '{camara}' ya tiene {previos} cruces en la base de datos.")
        if forzar_pregunta_reemplazo and confirmar("Borrarlos antes de procesar (evita duplicados)", True):
            comando.append("--reemplazar")
    if confirmar("Ver el modelo trabajando en vivo en una ventana (tecla q para detenerla)", True):
        comando.append("--mostrar")
    print("\nEn CPU, YOLOv8s a 960 px con video 4K va a ~3 cuadros/s (se ve a tirones).")
    if confirmar("Modo rapido: YOLOv8n a 640 px y sin guardar el video (~3 veces mas rapido, algo menos preciso)", False):
        comando += ["--modelo", "models/yolov8n.pt", "--imgsz", "640", "--sin-video"]
    estimado = info[3] / max(info[2], 1)
    print(f"\nVideo: {activo.name} {info[0]}x{info[1]}, {estimado:.0f} s ({info[3]} frames). "
          "En CPU puede tardar varios minutos.")
    if not confirmar("Procesar", True):
        return False
    ok = ejecutar(comando, f"Procesando {activo.name}") == 0
    if ok and ofrecer_dashboard and confirmar("\nAbrir el dashboard", True):
        abrir_dashboard()
    return ok


def abrir_dashboard() -> None:
    titulo("DASHBOARD")
    if not asegurar_dependencias(True):
        return
    vals = valores_actuales()
    filas = resumen_bd(ruta_absoluta(str(vals.get("DB_RUTA", "db/database.db"))))
    if not filas:
        print("[!] La base de datos no tiene cruces todavia: el dashboard mostrara un aviso.")
        if not confirmar("Abrirlo de todos modos", False):
            return
    print("Se abrira en http://localhost:8501. Ctrl+C en esta terminal lo cierra y vuelve al menu.")
    ejecutar([PY, "-m", "streamlit", "run", "dashboard.py"], "Iniciando Streamlit")


def menu_videos() -> None:
    while True:
        titulo("VIDEOS")
        idx = elegir(["Descargar videos de prueba", "Elegir el video a procesar (y su camara)",
                      "Calibrar lineas y distancia", "Listar videos locales"])
        if idx is None:
            return
        if idx == 0:
            descargar_videos()
        elif idx == 1:
            elegir_video()
        elif idx == 2:
            calibrar()
        elif idx == 3:
            for v in listar_videos() or []:
                i = info_video(v)
                print(f"  {v.name}  " + (f"{i[0]}x{i[1]} @ {i[2]:.0f} FPS, {i[3]} frames" if i else f"{v.stat().st_size / 1e6:.1f} MB"))
            if not listar_videos():
                print("  (no hay videos)")
        pausa()


def menu_bd() -> None:
    while True:
        titulo("BASE DE DATOS")
        vals = valores_actuales()
        ruta_db = ruta_absoluta(str(vals.get("DB_RUTA", "db/database.db")))
        if not ruta_db.is_file():
            print(f"[X] Aun no existe {ruta_db.name}. Se crea al procesar un video (menu principal).")
            pausa()
            return
        idx = elegir(["Resumen por camara", "Ultimos cruces", "Alertas", "Eliminar los datos de una camara"])
        if idx is None:
            return
        con = sqlite3.connect(str(ruta_db))
        try:
            if idx == 0:
                filas = resumen_bd(ruta_db)
                print(f"\n{'camara':<22}{'cruces':>8}{'con vel.':>10}{'alertas':>9}")
                for c, n, v, a, _ in filas or []:
                    print(f"{c:<22}{n:>8}{v:>10}{a:>9}")
                if not filas:
                    print("(sin datos)")
            elif idx == 1:
                n = int(pedir("Cuantos", "15") or 15)
                print(f"\n{'id':>5} {'track':>6} {'tipo':<8} {'momento':<24}{'km/h':>7}  camara")
                for f in con.execute("SELECT id, track_id, tipo, momento, velocidad_kmh, camara FROM cruces "
                                     "ORDER BY id DESC LIMIT ?", (n,)):
                    vel = "-" if f[4] is None else f"{f[4]:.1f}"
                    print(f"{f[0]:>5} {f[1]:>6} {f[2]:<8} {f[3]:<24}{vel:>7}  {f[5]}")
            elif idx == 2:
                try:
                    filas = con.execute("SELECT momento, tipo, valor, descripcion, camara FROM alertas "
                                        "ORDER BY id DESC LIMIT 20").fetchall()
                except sqlite3.Error:
                    filas = []
                    print("(esta base de datos no tiene la tabla alertas; procesa un video para actualizarla)")
                for f in filas:
                    print(f"  {f[0][:19]}  {f[1]:<17} {f[3]}  [{f[4]}]")
                if not filas:
                    print("  (sin alertas)")
            elif idx == 3:
                filas = resumen_bd(ruta_db) or []
                if not filas:
                    print("(no hay camaras)")
                else:
                    k = elegir([f"{c} ({n} cruces)" for c, n, *_ in filas], "Camara a eliminar")
                    if k is not None:
                        nombre = filas[k][0]
                        if pedir(f"Escribe el nombre '{nombre}' para confirmar") == nombre:
                            from db import CrucesDB  # solo usa la biblioteca estandar
                            with CrucesDB(ruta_db) as db:
                                print(f"Eliminados {db.eliminar_camara(nombre)} cruces (y sus alertas/lecturas).")
                        else:
                            print("Cancelado.")
        except sqlite3.Error as exc:
            print(f"Error de base de datos: {exc}")
        finally:
            con.close()
        pausa()


def menu_evaluacion() -> None:
    while True:
        titulo("EVALUACION")
        vals = valores_actuales()
        camara = str(vals.get("CAMARA", ""))
        gt = RAIZ / "evaluacion" / f"{camara}.json"
        print(f"Camara activa: {camara}   verdad de terreno: {'si' if gt.is_file() else 'NO'}")
        idx = elegir(["Marcar verdad de terreno a mano (ventana)", "Calcular metricas (evaluar.py)",
                      "Auditar el tracking del video activo", "Regenerar informe de metricas"])
        if idx is None:
            return
        activo = ruta_absoluta(str(vals.get("VIDEO_ENTRADA", "")))
        if idx == 0:
            if not asegurar_dependencias(False):
                continue
            if not activo.is_file():
                print("[X] El video activo no existe (menu 'Videos').")
            else:
                ejecutar([PY, "anotar_verdad_terreno.py", "--video", str(activo), "--camara", camara],
                         "Anotando (a/m/b/c marcan, espacio pausa, q guarda)")
        elif idx == 1:
            filas = resumen_bd(ruta_absoluta(str(vals.get("DB_RUTA", "db/database.db")))) or []
            if not gt.is_file():
                print(f"[X] Falta la verdad de terreno evaluacion/{camara}.json -> opcion 1 de este menu.")
            elif camara not in [c for c, *_ in filas]:
                print(f"[X] La camara '{camara}' no tiene datos en la BD.")
                if confirmar("Procesar el video activo ahora", True):
                    procesar_video(ofrecer_dashboard=False)
            else:
                ejecutar([PY, "evaluar.py", "--camara", camara, "--informe"], "Calculando metricas")
        elif idx == 2:
            if not asegurar_dependencias(False):
                continue
            if not activo.is_file():
                print("[X] El video activo no existe (menu 'Videos').")
            else:
                n = pedir("Frames a analizar (vacio = todos)", "300")
                ejecutar([PY, "verificar_tracking.py", "--video", str(activo)] + (["--max-frames", n] if n else []),
                         "Auditando tracking")
        elif idx == 3:
            ejecutar([PY, "evaluar.py", "--informe"], "Regenerando docs/METRICAS_RESULTADOS.md")
        pausa()


def correr_pruebas() -> None:
    titulo("PRUEBAS UNITARIAS")
    if not asegurar_dependencias(False):
        return
    ejecutar([PY, "-m", "unittest", "discover", "-s", "tests", "-v"], "Ejecutando pruebas")


def prueba_rapida() -> None:
    """Flujo guiado: entorno -> videos -> calibracion de ejemplo -> procesar -> dashboard."""
    titulo("PRUEBA RAPIDA (autopista_1)")
    print("Verifica el entorno, descarga el video si falta, aplica la calibracion probada,\n"
          "procesa el video y abre el dashboard.\n")
    if not asegurar_dependencias(True):
        print("No se puede continuar sin las dependencias.")
        return
    video = RAIZ / "videos" / "autopista_1.mp4"
    if not video.is_file():
        print("Falta videos/autopista_1.mp4.")
        if not confirmar("Descargar los videos de prueba", True):
            return
        descargar_videos()
        if not video.is_file():
            print("[X] No se pudo descargar autopista_1.mp4 (revisa tu conexion).")
            return
    error = aplicar_cambios({"VIDEO_ENTRADA": "videos/autopista_1.mp4", "CAMARA": "autopista_1",
                             **PRESETS["autopista_1.mp4"]})
    if error:
        print(f"[X] No se pudo preparar config.py: {error}")
        return
    print("Configuracion lista para autopista_1 (calibracion probada, distancia supuesta).")
    procesar_video()


# =============================================================================
# Menu principal
# =============================================================================
def menu_principal() -> None:
    estado = diagnostico()
    while True:
        titulo("MENU PRINCIPAL")
        acciones: List[Tuple[str, Callable[[], Any]]] = [
            ("Diagnostico (que tengo y que me falta)", lambda: diagnostico()),
            ("Prueba rapida guiada (autopista_1: todo de punta a punta)", prueba_rapida),
            ("Videos: descargar / elegir / calibrar", menu_videos),
            ("Configuracion: ver y editar parametros", menu_configuracion),
            ("Procesar el video activo", procesar_video),
            ("Dashboard", abrir_dashboard),
            ("Base de datos: resumen, cruces, alertas, borrar", menu_bd),
            ("Evaluacion: verdad de terreno, metricas, tracking", menu_evaluacion),
            ("Pruebas unitarias", correr_pruebas),
            ("Instalar dependencias", instalar_dependencias),
        ]
        idx = elegir([a[0] for a in acciones], "Opcion", etiqueta_cero="Salir")
        if idx is None:
            print("\nHasta luego.")
            return
        try:
            acciones[idx][1]()
        except KeyboardInterrupt:
            print("\n(Cancelado)")
        if idx in (0, 1, 4, 5, 8, 9):
            pausa()


def main() -> int:
    configurar_consola()
    if not CONFIG_PY.is_file():
        print(f"No se encuentra {CONFIG_PY}. Ejecuta el menu desde la carpeta del proyecto.")
        return 1
    try:
        menu_principal()
    except KeyboardInterrupt:
        print("\n\nHasta luego.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
