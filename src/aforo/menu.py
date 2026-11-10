"""
menu.py
=======
Menu interactivo en la terminal para PROBAR y CONFIGURAR todo el proyecto sin editar
archivos a mano:

    python -m aforo

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
import os
import re
import shutil
import importlib.util
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

RAIZ = Path(__file__).resolve().parents[2]               # <raiz>/src/aforo/menu.py
CONFIG_PY = RAIZ / "src" / "aforo" / "config.py"
PY = sys.executable
# Los procesos hijos ven el paquete `aforo` aunque no se haya hecho `pip install -e .`.
ENTORNO = {**os.environ, "PYTHONPATH": os.pathsep.join([str(RAIZ / "src"), str(RAIZ)] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))}

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
    "fastapi": ("fastapi", "API del dashboard"),
    "uvicorn": ("uvicorn", "servidor web del dashboard"),
}

# Calibracion de ejemplo por defecto de config.py (pensada para 1280x720, sin medir nada).
VALORES_EJEMPLO: Dict[str, Any] = {
    "LINEA_CONTEO": ((0, 400), (1280, 400)),
    "LINEA_VELOCIDAD_A": ((200, 300), (1100, 300)),
    "LINEA_VELOCIDAD_B": ((100, 550), (1200, 550)),
    "DISTANCIA_REAL_METROS": 20.0,
}

# Perfiles de calibracion POR VIDEO (datos/calibraciones.json): lineas, distancia real, camara y
# limites. Al elegir un video en el menu se aplica su perfil; al calibrar o editar esos valores
# se guarda de nuevo. Asi cambiar de video no obliga a recalibrar.
ARCHIVO_PERFILES = RAIZ / "datos" / "calibraciones.json"
CLAVES_PERFIL = ("CAMARA", "LINEA_CONTEO", "LINEA_VELOCIDAD_A", "LINEA_VELOCIDAD_B",
                 "DISTANCIA_REAL_METROS", "LIMITE_VELOCIDAD_KMH", "VELOCIDAD_MAX_KMH")


def _a_tuplas(valor: Any) -> Any:
    """JSON guarda las lineas como listas; config.py las espera como tuplas ((x, y), (x, y))."""
    return tuple(_a_tuplas(v) for v in valor) if isinstance(valor, list) else valor


def cargar_perfiles() -> Dict[str, Dict[str, Any]]:
    try:
        crudo = json.loads(ARCHIVO_PERFILES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {video: {k: _a_tuplas(v) for k, v in perfil.items()} for video, perfil in crudo.items()}


def guardar_perfil(video: str, valores: Dict[str, Any]) -> None:
    """Crea o actualiza el perfil de un video con los valores indicados (el resto se conserva)."""
    try:
        crudo = json.loads(ARCHIVO_PERFILES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        crudo = {}
    crudo.setdefault(video, {}).update({k: v for k, v in valores.items() if k in CLAVES_PERFIL})
    ARCHIVO_PERFILES.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVO_PERFILES.write_text(json.dumps(crudo, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


PRESETS: Dict[str, Dict[str, Any]] = cargar_perfiles()


# =============================================================================
# Utilidades de consola
# =============================================================================
def configurar_consola() -> None:
    """Evita errores de codificacion y activa los colores ANSI en la consola de Windows."""
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    if os.name == "nt":
        os.system("")          # habilita las secuencias ANSI en conhost/Windows Terminal


# Colores: solo si la salida es una terminal y el usuario no los desactivo (NO_COLOR).
COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ
_CODIGOS = {"tenue": "2", "negrita": "1", "ok": "32", "aviso": "33", "error": "31", "info": "36", "acento": "1;36"}


def est(texto: str, estilo: str) -> str:
    """Envuelve `texto` con el estilo ANSI indicado (o lo deja intacto sin colores)."""
    return f"[{_CODIGOS[estilo]}m{texto}[0m" if COLOR else texto


def titulo(texto: str, detalle: str = "") -> None:
    """Cabecera de seccion: linea fina, titulo en acento y una frase que explica para que sirve."""
    print(f"\n{est('─' * 66, 'tenue')}\n {est(texto, 'acento')}")
    if detalle:
        print(f" {est(detalle, 'tenue')}")
    print(est('─' * 66, 'tenue'))


def marca(nivel: str) -> str:
    """Indicador de estado: ✔ correcto, ! aviso, ✘ error."""
    return {"ok": est("✔", "ok"), "aviso": est("!", "aviso"), "error": est("✘", "error")}[nivel]


def limpiar_pantalla() -> None:
    if sys.stdout.isatty():
        os.system("cls" if os.name == "nt" else "clear")


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
        print(f"  {est(f'{i:>2}', 'info')}  {o}")
    if con_volver:
        print(f"  {est(' 0', 'tenue')}  {est(etiqueta_cero, 'tenue')}")
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
        "import sys, types, os; m = types.ModuleType('aforo.config'); m.__package__ = 'aforo'; "
        "m.__file__ = os.path.abspath('src/aforo/config.py'); sys.modules['aforo.config'] = m; "
        "exec(compile(open('src/aforo/config.py', encoding='utf-8').read(), 'config.py', 'exec'), m.__dict__); "
        "m.cargar_configuracion()"
    )
    r = subprocess.run([PY, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, env=ENTORNO)
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


def estado_gpu() -> Tuple[str, str]:
    """
    Que hardware usara YOLO: ("gpu", nombre) | ("cpu_con_gpu", nombre) | ("cpu", "").

    "cpu_con_gpu" = hay una tarjeta NVIDIA pero PyTorch esta instalado sin CUDA (el caso mas
    comun: `pip install torch` en Windows trae la version solo-CPU). Se consulta en un
    subproceso para no cargar torch en el menu.
    """
    if modulo_instalado("torch"):
        try:
            r = subprocess.run([PY, "-c", "import torch; print(torch.cuda.is_available()); "
                                "print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"],
                               capture_output=True, text=True, timeout=120)
            lineas = r.stdout.strip().splitlines()
            if len(lineas) >= 2 and lineas[0] == "True":
                return "gpu", lineas[1]
        except (subprocess.SubprocessError, OSError):
            pass
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            return "cpu_con_gpu", r.stdout.strip().splitlines()[0]
    except (subprocess.SubprocessError, OSError):
        pass
    return "cpu", ""


COMANDO_TORCH_CUDA = "pip install --force-reinstall --no-deps torch==2.14.1+cu130 torchvision==0.29.1+cu130 --index-url https://download.pytorch.org/whl/cu130"


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
    carpeta = RAIZ / "datos" / "videos"
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

    # --- GPU ------------------------------------------------------------------------------
    if not falta_n:
        modo_gpu, nombre_gpu = estado_gpu()
        estado["gpu"] = modo_gpu == "gpu"
        if modo_gpu == "gpu":
            print(f"[OK] GPU: {nombre_gpu} (CUDA). YOLO la usa solo.")
        elif modo_gpu == "cpu_con_gpu":
            print(f"[! ] Tienes una {nombre_gpu}, pero PyTorch esta instalado sin CUDA: YOLO corre en CPU (varias veces mas lento).")
            print(f"      -> {COMANDO_TORCH_CUDA}")
        else:
            print("[! ] Sin GPU NVIDIA: YOLO corre en CPU (usa el modo rapido para ver el sistema moverse).")

    # --- Configuracion ------------------------------------------------------------------
    error = validar_config_en_subproceso()
    estado["config_valida"] = error is None
    print(f"[{'OK' if error is None else 'X '}] config.py " + ("valida" if error is None else f"INVALIDA: {error}"))

    # --- Pesos --------------------------------------------------------------------------
    pesos = ruta_absoluta(str(vals.get("MODELO", "datos/modelos/yolov8s.pt")))
    estado["pesos"] = pesos.is_file()
    print(f"[{'OK' if pesos.is_file() else '! '}] Pesos YOLO {pesos.name}: "
          + ("presentes" if pesos.is_file() else "faltan (se descargan solos en la primera ejecucion; requiere internet)"))

    # --- Videos -------------------------------------------------------------------------
    videos = listar_videos()
    estado["hay_videos"] = bool(videos)
    print(f"[{'OK' if videos else 'X '}] Videos en datos/videos/: " + (f"{len(videos)}" if videos else "ninguno"))
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
    ruta_db = ruta_absoluta(str(vals.get("DB_RUTA", "datos/db/database.db")))
    filas = resumen_bd(ruta_db)
    estado["bd_con_datos"] = bool(filas)
    if filas is None:
        print(f"[! ] Base de datos {vals.get('DB_RUTA')}: aun no existe (se crea al procesar un video)")
    elif not filas:
        print(f"[! ] Base de datos {vals.get('DB_RUTA')}: existe pero sin cruces")
    else:
        print(f"[OK] Base de datos {vals.get('DB_RUTA')}: " + "; ".join(f"{c}: {n} cruces" for c, n, *_ in filas))

    # --- Verdad de terreno ---------------------------------------------------------------------
    gts = sorted((RAIZ / "datos" / "evaluacion").glob("*.json")) if (RAIZ / "datos" / "evaluacion").is_dir() else []
    estado["hay_gt"] = bool(gts)
    print(f"[{'OK' if gts else '! '}] Verdad de terreno (datos/evaluacion/*.json): "
          + (", ".join(g.stem for g in gts) if gts else "ninguna (necesaria para las metricas)"))
    return estado


# =============================================================================
# Acciones (cada una comprueba sus requisitos primero)
# =============================================================================
def ejecutar(comando: Sequence[str], descripcion: str) -> int:
    """Ejecuta un comando mostrando su salida en vivo. Ctrl+C lo detiene y vuelve al menu."""
    print(f"\n> {descripcion}\n  $ {' '.join(str(c) for c in comando)}\n")
    try:
        return subprocess.run(list(comando), cwd=RAIZ, env=ENTORNO).returncode
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
              "(.venv\\Scripts\\activate) y vuelve a abrir `python -m aforo`.")
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
    titulo("Descargar videos de prueba", "Tres videos públicos de tráfico para probar el sistema sin depender del video final.")
    if not modulo_instalado("tqdm") or not modulo_instalado("cv2"):
        print(f"{marca('error')} La descarga necesita tqdm y opencv-python.")
        if not asegurar_dependencias(False):
            return
    ejecutar([PY, "-m", "aforo", "descargar"], "Descargando (los que ya existen se omiten)")


# ---------------------------------------------------------------------------
# Perfiles por video: cambiar de video no obliga a recalibrar
# ---------------------------------------------------------------------------
def video_activo() -> Path:
    return ruta_absoluta(str(valores_actuales().get("VIDEO_ENTRADA", "")))


def nombre_camara_valido(texto: str) -> str:
    """Nombre de camara seguro para la base de datos (letras, numeros, guion y guion bajo)."""
    limpio = re.sub(r"[^\w\-]+", "_", texto, flags=re.UNICODE).strip("_")
    return limpio or "camara_01"


def sincronizar_perfil() -> None:
    """Guarda en el perfil del video activo los valores de calibracion que hay ahora en config.py."""
    vals = valores_actuales()
    nombre = Path(str(vals.get("VIDEO_ENTRADA", ""))).name
    if nombre:
        guardar_perfil(nombre, {k: vals[k] for k in CLAVES_PERFIL if k in vals})
        PRESETS.clear()
        PRESETS.update(cargar_perfiles())


def aplicar_perfil(nombre_video: str) -> bool:
    """Aplica a config.py el perfil guardado de un video. False si no hay o falla."""
    perfil = {k: v for k, v in PRESETS.get(nombre_video, {}).items() if k in CLAVES_PERFIL}
    if not perfil:
        return False
    error = aplicar_cambios(perfil)
    if error:
        print(f"{marca('error')} No se pudo aplicar el perfil: {error}")
        return False
    return True


def aplicar_preset(nombre_video: str) -> bool:
    """Compatibilidad: aplica el perfil guardado de un video e informa al usuario."""
    if not aplicar_perfil(nombre_video):
        return False
    nota = PRESETS.get(nombre_video, {}).get("nota")
    print(f"{marca('ok')} Calibración de «{nombre_video}» aplicada." + (f"\n  {est(str(nota), 'tenue')}" if nota else ""))
    return True


def activar_video(ruta: Path) -> bool:
    """Deja `ruta` como video activo: actualiza config.py y aplica su perfil si existe."""
    try:
        relativa = ruta.resolve().relative_to(RAIZ)
        texto_ruta = relativa.as_posix()
    except ValueError:
        texto_ruta = ruta.resolve().as_posix()           # fuera del proyecto: ruta absoluta
    camara = PRESETS.get(ruta.name, {}).get("CAMARA") or nombre_camara_valido(ruta.stem)
    error = aplicar_cambios({"VIDEO_ENTRADA": texto_ruta, "CAMARA": camara})
    if error:
        print(f"{marca('error')} No se pudo actualizar config.py: {error}")
        return False
    print(f"\n{marca('ok')} Video activo: {est(ruta.name, 'negrita')}   cámara: {camara}")
    if aplicar_perfil(ruta.name):
        nota = PRESETS[ruta.name].get("nota")
        print(f"{marca('ok')} Se aplicó la calibración guardada de este video (líneas, distancia y límites)."
              + (f"\n  {est(str(nota), 'tenue')}" if nota else ""))
    else:
        print(f"{marca('aviso')} Este video aún no está calibrado. Usa «Calibrar» para marcar las líneas "
              "y la distancia real; el menú las recordará.")
    return True


def _fila_video(v: Path, activo: Path, camaras_con_datos: Dict[str, int]) -> str:
    info = info_video(v)
    res = f"{info[0]}x{info[1]}" if info else "?"
    dur = f"{int(info[3] / info[2] // 60)}:{int(info[3] / info[2] % 60):02d}" if info and info[2] else "?"
    mb = f"{v.stat().st_size / 1e6:,.0f} MB"
    perfil = PRESETS.get(v.name)
    calibrado = est("calibrado", "ok") if perfil else est("sin calibrar", "aviso")
    cam = (perfil or {}).get("CAMARA") or nombre_camara_valido(v.stem)
    datos = camaras_con_datos.get(cam)
    procesado = est(f"{datos} cruces", "info") if datos else est("sin procesar", "tenue")
    es_activo = v.resolve() == activo.resolve()
    nombre = f"{v.name[:30]:<30}"
    return (f"{est('● ', 'ok') if es_activo else '  '}{est(nombre, 'negrita') if es_activo else nombre} "
            f"{res:>10} {dur:>6} {mb:>9}   {calibrado}  ·  {procesado}")


def elegir_video() -> Optional[Path]:
    """Gestor de videos: lista con estado, elegir uno, agregar por ruta o descargar los de prueba."""
    while True:
        vals = valores_actuales()
        activo = ruta_absoluta(str(vals.get("VIDEO_ENTRADA", "")))
        videos = listar_videos()
        filas = resumen_bd(ruta_absoluta(str(vals.get("DB_RUTA", "datos/db/database.db")))) or []
        con_datos = {c: n for c, n, *_ in filas}
        titulo("Videos", "Elige el video a analizar. Cada video recuerda su calibración (líneas y distancia).")
        if not videos:
            print(f"  {marca('aviso')} No hay videos en datos/videos/.\n")
        else:
            print(est(f"  {'':2}{'Video':<30} {'Resolución':>10} {'Dur.':>6} {'Tamaño':>9}   Estado", "tenue"))
            for i, v in enumerate(videos, 1):
                print(f"{est(f'{i:>2}', 'info')} {_fila_video(v, activo, con_datos)}")
        print(f"\n  {est(' A', 'info')}  Agregar un video desde otra carpeta (ruta completa)"
              f"\n  {est(' D', 'info')}  Descargar los videos de prueba"
              f"\n  {est(' 0', 'tenue')}  {est('Volver', 'tenue')}")
        r = pedir("\nNúmero de video, A, D o 0").strip().lower()
        if r in ("", "0"):
            return activo if activo.is_file() else None
        if r == "d":
            descargar_videos()
            continue
        if r == "a":
            ruta = pedir("Ruta completa del video (.mp4/.avi/.mov/.mkv)").strip().strip('"')
            candidato = Path(ruta)
            if not candidato.is_file() or candidato.suffix.lower() not in EXTENSIONES_VIDEO:
                print(f"{marca('error')} No encuentro un video válido en esa ruta.")
                continue
            if info_video(candidato) is None and modulo_instalado("cv2"):
                print(f"{marca('error')} OpenCV no puede abrir ese archivo.")
                continue
            destino = RAIZ / "datos" / "videos" / candidato.name
            if candidato.resolve().parent != destino.parent.resolve() and confirmar(
                    f"¿Copiarlo a datos/videos/ ({candidato.stat().st_size / 1e6:,.0f} MB)? (No = usarlo desde donde está)", False):
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidato, destino)
                candidato = destino
            activar_video(candidato)
            continue
        if r.isdigit() and 1 <= int(r) <= len(videos):
            if activar_video(videos[int(r) - 1]) and not PRESETS.get(videos[int(r) - 1].name) \
                    and confirmar("¿Calibrarlo ahora?", True):
                calibrar()
            continue
        print(f"  {marca('aviso')} Opción no válida.")


def calibrar() -> None:
    titulo("Calibrar", "Marca dónde cuentan los vehículos (línea de conteo), el tramo A–B donde se mide la velocidad y su distancia REAL en metros.")
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
        opciones.append("Restaurar la calibración guardada de este video")
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
        r = subprocess.run([PY, "-m", "aforo", "calibrar", "--video", str(activo), "--frame", frame],
                           cwd=RAIZ, capture_output=True, text=True, env=ENTORNO)
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
    sincronizar_perfil()          # recuerda esta calibracion para este video
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
    if error:
        print(f"{marca('error')} No se guardó, config.py quedaría inválida: {error}")
        return
    print(f"{marca('ok')} Guardado: {p.nombre} = {valor!r}")
    if p.nombre in CLAVES_PERFIL:
        sincronizar_perfil()


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
    """Valida todo y ejecuta aforo procesar. Devuelve True si el procesamiento termino bien."""
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

    print(f"""
  {est('Cómo quieres procesarlo', 'negrita')}
   {est('1', 'info')}  En vivo a velocidad normal   se ve como un video; salta cuadros y pierde vehículos (demo)
   {est('2', 'info')}  En vivo, todos los cuadros   preciso, pero en CPU se ve en cámara lenta
   {est('3', 'info')}  Sin ventana                  solo la barra de progreso; lo más rápido para llenar la base""")
    modo = pedir("Opción (q en la ventana para detenerla)", "1").strip()
    con_gpu = estado_gpu()[0] == "gpu"
    camara = str(vals.get("CAMARA", ""))
    comando = [PY, "-m", "aforo", "procesar"]
    if modo == "1":
        # Datos parciales: van a una camara aparte para no borrar ni mezclar los completos.
        camara = f"{camara}_vivo"
        comando += ["--camara", camara, "--tiempo-real"]
        if con_gpu:
            print(f"[!] En vivo se salta algún cuadro si el equipo no alcanza. Se guarda como «{camara}»,")
            print("    aparte de tus datos completos. Para datos definitivos usa la opción 2 o 3.")
        else:
            print(f"[!] Sin GPU, en vivo se analiza 1 de cada ~5 cuadros: se pierden vehículos. Se guarda como «{camara}»,")
            print("    aparte de tus datos completos. Para datos confiables usa la opción 2 o 3.")
            comando += ["--modelo", "datos/modelos/yolov8n.pt", "--imgsz", "640"]
    else:
        if modo == "2":
            comando.append("--mostrar")
        if confirmar("Modo rápido: YOLOv8n a 640 px y sin guardar el video (~3 veces más rápido, algo menos preciso)", modo == "3"):
            comando += ["--modelo", "datos/modelos/yolov8n.pt", "--imgsz", "640", "--sin-video"]
    filas = resumen_bd(ruta_absoluta(str(vals.get("DB_RUTA", "datos/db/database.db")))) or []
    previos = next((n for c, n, *_ in filas if c == camara), 0)
    if previos:
        print(f"[!] La camara '{camara}' ya tiene {previos} cruces en la base de datos.")
        if forzar_pregunta_reemplazo and confirmar("Borrarlos antes de procesar (evita duplicados)", True):
            comando.append("--reemplazar")
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
    filas = resumen_bd(ruta_absoluta(str(vals.get("DB_RUTA", "datos/db/database.db"))))
    if not filas:
        print("[!] La base de datos no tiene cruces todavia: el dashboard mostrara un aviso.")
        if not confirmar("Abrirlo de todos modos", False):
            return
    print("Se abrira en http://localhost:8501. Ctrl+C en esta terminal lo cierra y vuelve al menu.")
    ejecutar([PY, "-m", "aforo", "dashboard"], "Iniciando el dashboard")


def menu_videos() -> None:
    """Compatibilidad: el gestor de videos ahora es `elegir_video`."""
    elegir_video()


def menu_bd() -> None:
    while True:
        titulo("BASE DE DATOS")
        vals = valores_actuales()
        ruta_db = ruta_absoluta(str(vals.get("DB_RUTA", "datos/db/database.db")))
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
                            from aforo.persistencia.db import CrucesDB  # solo usa la biblioteca estandar
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
        gt = RAIZ / "datos" / "evaluacion" / f"{camara}.json"
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
                ejecutar([PY, "-m", "aforo", "anotar", "--video", str(activo), "--camara", camara],
                         "Anotando (a/m/b/c marcan, espacio pausa, q guarda)")
        elif idx == 1:
            filas = resumen_bd(ruta_absoluta(str(vals.get("DB_RUTA", "datos/db/database.db")))) or []
            if not gt.is_file():
                print(f"[X] Falta la verdad de terreno datos/evaluacion/{camara}.json -> opcion 1 de este menu.")
            elif camara not in [c for c, *_ in filas]:
                print(f"[X] La camara '{camara}' no tiene datos en la BD.")
                if confirmar("Procesar el video activo ahora", True):
                    procesar_video(ofrecer_dashboard=False)
            else:
                ejecutar([PY, "-m", "aforo", "evaluar", "--camara", camara, "--informe"], "Calculando metricas")
        elif idx == 2:
            if not asegurar_dependencias(False):
                continue
            if not activo.is_file():
                print("[X] El video activo no existe (menu 'Videos').")
            else:
                n = pedir("Frames a analizar (vacio = todos)", "300")
                ejecutar([PY, "-m", "aforo", "auditar", "--video", str(activo)] + (["--max-frames", n] if n else []),
                         "Auditando tracking")
        elif idx == 3:
            ejecutar([PY, "-m", "aforo", "evaluar", "--informe"], "Regenerando docs/METRICAS_RESULTADOS.md")
        pausa()


def correr_pruebas() -> None:
    titulo("PRUEBAS UNITARIAS")
    if not asegurar_dependencias(False):
        return
    ejecutar([PY, "-m", "unittest", "discover", "-s", "tests", "-v"], "Ejecutando pruebas")


def prueba_rapida() -> None:
    """Flujo guiado: entorno -> video de ejemplo -> su calibracion guardada -> procesar -> dashboard."""
    titulo("Prueba rápida", "Todo el flujo con un video de ejemplo: verifica, descarga si falta, calibra, procesa y abre el panel.")
    if not asegurar_dependencias(True):
        print("No se puede continuar sin las dependencias.")
        return
    video = RAIZ / "datos" / "videos" / "autopista_1.mp4"
    if not video.is_file():
        print(f"{marca('aviso')} Falta datos/videos/autopista_1.mp4.")
        if not confirmar("Descargar los videos de prueba", True):
            return
        descargar_videos()
        if not video.is_file():
            print(f"{marca('error')} No se pudo descargar autopista_1.mp4 (revisa tu conexión).")
            return
    if not activar_video(video):
        return
    procesar_video()


# =============================================================================
# Panel de estado, siguiente paso recomendado y ayuda
# =============================================================================
def estado_resumido() -> Dict[str, Any]:
    """Foto rapida del proyecto para el panel del menu (sin subprocesos: es barata)."""
    vals = valores_actuales()
    activo = ruta_absoluta(str(vals.get("VIDEO_ENTRADA", "")))
    info = info_video(activo) if activo.is_file() else None
    lineas_ok = bool(info) and not lineas_fuera_de_cuadro(vals, info[0], info[1]) and not es_calibracion_de_ejemplo(vals)
    camara = str(vals.get("CAMARA", ""))
    filas = resumen_bd(ruta_absoluta(str(vals.get("DB_RUTA", "datos/db/database.db")))) or []
    return {
        "deps": not dependencias_faltantes(False), "deps_dash": not dependencias_faltantes(True),
        "video": activo, "video_existe": activo.is_file(), "info": info, "calibrado": lineas_ok,
        "camara": camara, "cruces": next((n for c, n, *_ in filas if c == camara), 0),
        "camaras": len(filas), "videos": len(listar_videos()),
    }


def siguiente_paso(e: Dict[str, Any]) -> Tuple[str, str]:
    """Que hacer ahora, segun el estado: (texto, numero de opcion del menu)."""
    if not e["deps"]:
        return "Instalar las dependencias (faltan paquetes).", "11"
    if not e["video_existe"]:
        return "Elegir o descargar un video para analizar.", "1"
    if not e["calibrado"]:
        return "Calibrar el video: marcar las líneas y la distancia real.", "2"
    if e["cruces"] == 0:
        return "Procesar el video: contar vehículos y medir velocidades.", "4"
    if not e["deps_dash"]:
        return "Instalar las dependencias del dashboard.", "11"
    return "Ver los resultados en el dashboard.", "5"


def panel_estado(e: Dict[str, Any]) -> None:
    """Resumen de una pantalla: video activo, calibracion, datos y el siguiente paso."""
    def linea(nivel: str, etiqueta: str, valor: str) -> None:
        print(f"  {marca(nivel)} {est(f'{etiqueta:<13}', 'tenue')} {valor}")

    nombre = e["video"].name if e["video_existe"] else "ninguno"
    if e["info"]:
        i = e["info"]
        nombre += est(f"  {i[0]}x{i[1]} · {int(i[3] / max(i[2], 1) // 60)} min", "tenue")
    linea("ok" if e["video_existe"] else "error", "Video activo", nombre)
    linea("ok" if e["calibrado"] else "aviso", "Calibración", "lista" if e["calibrado"] else "pendiente (líneas y distancia real)")
    linea("ok" if e["cruces"] else "aviso", "Datos", f"{e['cruces']} cruces de «{e['camara']}»" if e["cruces"] else f"sin procesar «{e['camara']}»")
    linea("ok" if e["deps"] else "error", "Dependencias", "instaladas" if e["deps"] else "faltan paquetes")
    texto, opcion = siguiente_paso(e)
    print(f"\n  {est('Siguiente paso', 'acento')}  {texto}  {est(f'→ opción {opcion}', 'info')}")


def ayuda() -> None:
    titulo("Ayuda", "Cómo funciona el sistema, en cuatro pasos.")
    print(f"""
  {est('1  Elegir el video', 'negrita')}       Cada video recuerda su calibración. Puedes agregar el tuyo.
  {est('2  Calibrar', 'negrita')}              Tres cosas sobre el video:
        · {est('línea de conteo', 'info')}: cada vehículo que la cruza se cuenta una vez.
        · {est('tramo A–B', 'info')}: dos líneas entre las que se mide el tiempo de cada vehículo.
        · {est('distancia real', 'info')} entre A y B en metros (mídela en el sitio: de ella depende
          toda la velocidad). Velocidad = distancia ÷ tiempo.
  {est('3  Procesar', 'negrita')}             YOLO detecta, ByteTrack sigue, y todo se guarda en SQLite.
        Tip: en CPU usa el «modo rápido» para ver el sistema moverse (menos preciso).
  {est('4  Dashboard', 'negrita')}            Panel web con aforo, velocidades, alertas y estado de la vía.

  {est('Dónde está cada cosa', 'negrita')}
        datos/videos        tus videos             datos/db        la base de datos
        datos/modelos       pesos de YOLO          src/aforo       el código
        datos/calibraciones.json   calibración de cada video

  {est('Sin menú', 'negrita')}   python -m aforo procesar | dashboard | calibrar | evaluar ...  (python -m aforo --help)
""")


# =============================================================================
# Menu principal
# =============================================================================
BANNER = """
   ╭─────────────────────────────────────────────────────╮
   │   AFORO VIAL   ·   conteo y velocidad de vehículos  │
   │   YOLOv8 · ByteTrack · SQLite                       │
   ╰─────────────────────────────────────────────────────╯"""


def menu_principal() -> None:
    grupos: List[Tuple[str, List[Tuple[str, str, str, Callable[[], Any], bool]]]] = [
        ("PREPARAR", [
            ("1", "Videos", "elegir, agregar o descargar el video a analizar", menu_videos, False),
            ("2", "Calibrar", "marcar líneas y distancia real del video activo", calibrar, True),
            ("3", "Configuración", "ver y editar cualquier parámetro", menu_configuracion, False),
        ]),
        ("EJECUTAR", [
            ("4", "Procesar", "analizar el video activo → base de datos", procesar_video, True),
            ("5", "Dashboard", "abrir el panel web con los resultados", abrir_dashboard, True),
            ("6", "Prueba rápida", "flujo guiado completo con un video de ejemplo", prueba_rapida, True),
        ]),
        ("ANALIZAR", [
            ("7", "Base de datos", "resumen, cruces, alertas, borrar una cámara", menu_bd, False),
            ("8", "Evaluación", "verdad de terreno, métricas y auditoría del tracking", menu_evaluacion, False),
        ]),
        ("SISTEMA", [
            ("9", "Diagnóstico", "revisión completa del entorno", diagnostico, True),
            ("10", "Pruebas", "ejecutar las pruebas unitarias", correr_pruebas, True),
            ("11", "Instalar", "dependencias del proyecto", instalar_dependencias, True),
            ("12", "Ayuda", "cómo funciona, paso a paso", ayuda, True),
        ]),
    ]
    mapa = {num: (accion, pausar) for _, items in grupos for num, _, _, accion, pausar in items}
    while True:
        limpiar_pantalla()
        print(est(BANNER, "acento"))
        print()
        panel_estado(estado_resumido())
        for nombre_grupo, items in grupos:
            print(f"\n  {est(nombre_grupo, 'tenue')}")
            for num, nombre, detalle, _, _ in items:
                print(f"   {est(f'{num:>2}', 'info')}  {est(f'{nombre:<14}', 'negrita')} {est(detalle, 'tenue')}")
        print(f"\n   {est(' 0', 'tenue')}  {est('Salir', 'tenue')}")
        try:
            r = pedir("\n  Opción").strip().lower()
        except KeyboardInterrupt:
            r = "0"
        if r in ("0", "q", "salir"):
            print(f"\n  {est('Hasta luego.', 'tenue')}\n")
            return
        if r not in mapa:
            print(f"  {marca('aviso')} Opción no válida.")
            pausa()
            continue
        accion, pausar = mapa[r]
        try:
            accion()
        except KeyboardInterrupt:
            print("\n  (Cancelado)")
        if pausar:
            pausa()


def main(argv: Optional[Sequence[str]] = None) -> int:
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
