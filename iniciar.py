#!/usr/bin/env python3
"""
Aforo vial - lanzador unico.

    python iniciar.py

Hace, en orden, lo que hace falta para trabajar:

  1. comprueba Python y crea las carpetas de datos;
  2. comprueba las dependencias y, si faltan, ofrece instalarlas;
  3. detecta la GPU NVIDIA y, si PyTorch esta instalado sin CUDA, instala la version con CUDA (el
     analisis en CPU es muchas veces mas lento: solo se acepta si no hay tarjeta NVIDIA);
  4. valida la configuracion (config.py);
  5. levanta el dashboard web y abre el navegador. Desde ahi se hace todo: elegir y calibrar
     el video, procesarlo y ver los resultados.

Solo usa la biblioteca estandar de Python: puede ejecutarse aunque todavia no haya nada instalado.

Opciones:  --puerto 8501   --no-abrir   --si (responde "si" a todo)   --solo-revisar (no abre la web)
           --permitir-cpu (sigue aunque no se pueda activar la GPU)
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

RAIZ = Path(__file__).resolve().parent
PUERTO_INICIAL = 8501
PYTHON_MINIMO = (3, 10)

# modulo importable -> paquete pip
NUCLEO: Dict[str, str] = {
    "cv2": "opencv-python", "numpy": "numpy", "supervision": "supervision", "trackers": "trackers",
    "ultralytics": "ultralytics", "torch": "torch", "tqdm": "tqdm",
}
WEB: Dict[str, str] = {"fastapi": "fastapi", "uvicorn": "uvicorn"}

CARPETAS = ("datos/videos", "datos/modelos", "datos/db", "datos/salidas", "datos/evaluacion")
VERSION_TORCH, VERSION_TORCHVISION = "2.14.1", "0.29.1"


# --------------------------------------------------------------------------------- presentacion
def _color_activo() -> bool:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return False
    if os.name == "nt":
        os.system("")                    # activa las secuencias ANSI en la consola de Windows 10+
    return True


COLOR = _color_activo()


def _e(codigo: str, texto: str) -> str:
    return f"\033[{codigo}m{texto}\033[0m" if COLOR else texto


def ok(texto: str) -> None:
    print(f"  {_e('32', '✔')} {texto}")


def aviso(texto: str) -> None:
    print(f"  {_e('33', '!')} {texto}")


def fallo(texto: str) -> None:
    print(f"  {_e('31', '✖')} {texto}")


def paso(numero: int, titulo: str) -> None:
    print(f"\n{_e('1', f'{numero}. {titulo}')}")


def preguntar(texto: str, por_defecto: bool = True, automatico: bool = False) -> bool:
    """Pregunta si/no. En modo --si responde que si; sin terminal interactiva usa el valor por defecto."""
    if automatico:
        print(f"  ? {texto} -> sí (--si)")
        return True
    if not sys.stdin.isatty():
        return por_defecto
    marca = "S/n" if por_defecto else "s/N"
    try:
        r = input(f"  ? {texto} [{marca}] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return por_defecto if not r else r in ("s", "si", "sí", "y", "yes")


# --------------------------------------------------------------------------------- comprobaciones
def modulos_faltantes(modulos: Dict[str, str], existe=importlib.util.find_spec) -> List[str]:
    """Paquetes pip de los `modulos` que no se pueden importar."""
    faltan = []
    for modulo, paquete in modulos.items():
        try:
            if existe(modulo) is None:
                faltan.append(paquete)
        except (ImportError, ValueError):
            faltan.append(paquete)
    return faltan


def version_cuda_del_driver(salida_nvidia_smi: str) -> Optional[Tuple[int, int]]:
    """
    CUDA maxima que soporta el driver, leida de la cabecera de `nvidia-smi`. El texto cambia segun la
    version del driver: "CUDA Version: 12.4" (antiguo) o "CUDA UMD Version: 13.5" (nuevo).
    """
    m = re.search(r"CUDA\s+(?:UMD\s+)?Version\s*:\s*(\d+)\.(\d+)", salida_nvidia_smi)
    return (int(m.group(1)), int(m.group(2))) if m else None


def indices_de_torch(cuda: Optional[Tuple[int, int]]) -> List[str]:
    """
    Indices de ruedas de PyTorch (cu130, cu126) que sirven para esa version de CUDA, del mas nuevo al mas
    antiguo. Si no se pudo leer la version del driver se prueban los dos: es mejor intentar que rendirse.
    Lista vacia = el driver es demasiado antiguo (hace falta CUDA 12.6 o superior).
    """
    if cuda is None:
        return ["cu130", "cu126"]
    if cuda >= (13, 0):
        return ["cu130", "cu126"]
    if cuda >= (12, 6):
        return ["cu126"]
    return []


def comando_torch_cuda(indice: str, python: str = sys.executable) -> List[str]:
    return [python, "-m", "pip", "install", "--force-reinstall", "--no-deps",
            f"torch=={VERSION_TORCH}+{indice}", f"torchvision=={VERSION_TORCHVISION}+{indice}",
            "--index-url", f"https://download.pytorch.org/whl/{indice}"]


def instalar_torch_con_cuda() -> bool:
    """
    Reemplaza el PyTorch de este entorno por la version con CUDA que corresponda al driver y comprueba que
    la GPU quede visible. Prueba los indices compatibles en orden hasta que uno funcione.
    """
    cuda = version_cuda_del_driver(_nvidia_smi() or "")
    indices = indices_de_torch(cuda)
    if not indices:
        fallo(f"Tu driver NVIDIA solo soporta CUDA {cuda[0]}.{cuda[1]}; se necesita 12.6 o superior. Actualiza el driver desde nvidia.com.")
        return False
    if cuda:
        print(f"    Driver compatible con CUDA {cuda[0]}.{cuda[1]}")
    for indice in indices:
        print(f"    Instalando PyTorch con CUDA ({indice}); son ~3 GB, puede tardar unos minutos...")
        if _ejecutar(comando_torch_cuda(indice)) and _torch_ve_la_gpu()[0]:
            return True
        aviso(f"El indice {indice} no dejó la GPU activa; se prueba el siguiente." if indice != indices[-1] else f"El indice {indice} tampoco funcionó.")
    return False


def puerto_libre(inicial: int, intentos: int = 20, host: str = "127.0.0.1") -> Optional[int]:
    """Primer puerto libre a partir de `inicial`."""
    for puerto in range(inicial, inicial + intentos):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            try:
                s.bind((host, puerto))
                return puerto
            except OSError:
                continue
    return None


def _nvidia_smi() -> Optional[str]:
    try:
        r = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=20)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _nombre_gpu() -> str:
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip().splitlines()[0] if r.returncode == 0 and r.stdout.strip() else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _torch_ve_la_gpu() -> Tuple[bool, str]:
    """(torch usa CUDA, nombre) consultando en un subproceso (cargar torch aqui tardaria y bloquearia DLLs)."""
    try:
        r = subprocess.run([sys.executable, "-c", "import torch; print(torch.cuda.is_available()); "
                            "print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"],
                           capture_output=True, text=True, timeout=180)
        lineas = r.stdout.strip().splitlines()
        return (len(lineas) >= 2 and lineas[0] == "True"), (lineas[1] if len(lineas) >= 2 else "")
    except (OSError, subprocess.SubprocessError):
        return False, ""


def _entorno() -> Dict[str, str]:
    """Entorno de los subprocesos: ven el paquete `aforo` aunque no este instalado en modo editable."""
    previo = os.environ.get("PYTHONPATH")
    return {**os.environ, "PYTHONPATH": os.pathsep.join([str(RAIZ / "src"), str(RAIZ)] + ([previo] if previo else []))}


def _ejecutar(comando: Sequence[str]) -> bool:
    print(f"    $ {' '.join(comando)}")
    try:
        return subprocess.run(list(comando), cwd=RAIZ, env=_entorno()).returncode == 0
    except (OSError, KeyboardInterrupt):
        return False


# --------------------------------------------------------------------------------- pasos
def revisar_python() -> bool:
    version = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info < PYTHON_MINIMO:
        fallo(f"Python {version}: se necesita {PYTHON_MINIMO[0]}.{PYTHON_MINIMO[1]} o superior.")
        return False
    ok(f"Python {version}")
    for carpeta in CARPETAS:
        (RAIZ / carpeta).mkdir(parents=True, exist_ok=True)
    ok("Carpetas de datos listas (datos/videos, modelos, db, salidas)")
    return True


def revisar_dependencias(automatico: bool) -> bool:
    faltan = modulos_faltantes({**NUCLEO, **WEB})
    if not faltan:
        ok("Todas las dependencias están instaladas")
        return True
    aviso(f"Faltan paquetes: {', '.join(faltan)}")
    if not preguntar("¿Instalarlos ahora con pip? (descarga varios GB la primera vez)", True, automatico):
        fallo("Sin las dependencias no se puede continuar. Instálalas con:  pip install -r requirements.txt")
        return False
    # Con una tarjeta NVIDIA, torch se instala directamente con CUDA (evita bajar dos veces la version CPU).
    if "torch" in faltan and _nombre_gpu():
        print(f"    Se detectó una GPU NVIDIA ({_nombre_gpu()}): PyTorch se instalará con CUDA.")
        instalar_torch_con_cuda()
    if not _ejecutar([sys.executable, "-m", "pip", "install", "-r", str(RAIZ / "requirements.txt")]):
        fallo("La instalación falló. Revisa el mensaje de pip de arriba (¿hay conexión a internet?).")
        return False
    importlib.invalidate_caches()
    faltan = modulos_faltantes({**NUCLEO, **WEB})
    if faltan:
        fallo(f"Siguen faltando: {', '.join(faltan)}")
        return False
    ok("Dependencias instaladas")
    return True


def revisar_gpu(permitir_cpu: bool = False) -> bool:
    """
    Garantiza que el analisis use la GPU cuando hay una tarjeta NVIDIA. Si PyTorch esta instalado sin CUDA
    lo reemplaza solo (analizar en CPU es muchas veces mas lento). Devuelve False si hay tarjeta pero no se
    pudo activar y no se autorizo seguir en CPU (`--permitir-cpu`).
    """
    usa_gpu, nombre = _torch_ve_la_gpu()
    if usa_gpu:
        ok(f"GPU: {nombre} (CUDA). El análisis la usará automáticamente.")
        return True
    tarjeta = _nombre_gpu()
    if not tarjeta:
        aviso("No se detectó una GPU NVIDIA: el análisis usará la CPU. Funciona, pero es mucho más lento; "
              "para videos largos usa el modo «Rápido» del panel.")
        return True
    aviso(f"Tienes una {tarjeta}, pero PyTorch está instalado sin CUDA: el análisis correría en CPU, muy lento. Se corrige ahora.")
    if instalar_torch_con_cuda():
        ok(f"PyTorch con CUDA instalado: la GPU ({_torch_ve_la_gpu()[1] or tarjeta}) queda activa.")
        return True
    if permitir_cpu:
        aviso("No se pudo activar la GPU; se sigue con la CPU porque se indicó --permitir-cpu.")
        return True
    fallo("No se pudo activar la GPU, así que no se continúa (el análisis en CPU es demasiado lento). "
          "Revisa el mensaje de arriba; con --permitir-cpu se puede seguir igualmente.")
    return False


def revisar_configuracion() -> bool:
    r = subprocess.run([sys.executable, "-c",
                        "from aforo.config import cargar_configuracion; cargar_configuracion()"],
                       capture_output=True, text=True, cwd=RAIZ, env=_entorno())
    if r.returncode == 0:
        ok("Configuración (config.py) válida")
        return True
    detalle = (r.stderr.strip().splitlines() or ["error desconocido"])[-1]
    fallo(f"config.py tiene un problema: {detalle}")
    return False


def revisar_pesos() -> None:
    pesos = sorted(p.name for p in (RAIZ / "datos" / "modelos").glob("*.pt"))
    if pesos:
        ok(f"Pesos de YOLO: {', '.join(pesos)}")
    else:
        aviso("Aún no hay pesos de YOLO: se descargan solos al procesar por primera vez (necesita internet, ~22 MB).")


# --------------------------------------------------------------------------------- principal
def main(argv: Optional[List[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Revisa el entorno y abre el panel web de aforo vial.")
    ap.add_argument("--puerto", type=int, default=PUERTO_INICIAL, help=f"Puerto del panel (por defecto {PUERTO_INICIAL}).")
    ap.add_argument("--no-abrir", action="store_true", help="No abrir el navegador automáticamente.")
    ap.add_argument("--si", action="store_true", help="Responder «sí» a todas las preguntas (instalaciones incluidas).")
    ap.add_argument("--solo-revisar", action="store_true", help="Solo revisar el entorno; no abrir el panel.")
    ap.add_argument("--permitir-cpu", action="store_true", help="Seguir aunque no se pueda activar la GPU (solo para pruebas).")
    args = ap.parse_args(argv)

    print(_e("1", "\n  AFORO VIAL · conteo y velocidad de vehículos"))
    print("  Revisando que todo esté listo antes de abrir el panel...")

    paso(1, "Python y carpetas")
    if not revisar_python():
        return 1
    paso(2, "Dependencias")
    if not revisar_dependencias(args.si):
        return 1
    paso(3, "Aceleración por GPU")
    if not revisar_gpu(args.permitir_cpu):
        return 1
    paso(4, "Configuración")
    if not revisar_configuracion():
        return 1
    revisar_pesos()

    if args.solo_revisar:
        print("\n  Todo listo.")
        return 0

    puerto = puerto_libre(args.puerto)
    if puerto is None:
        fallo(f"No hay puertos libres desde el {args.puerto}. Usa --puerto con otro número.")
        return 1
    if puerto != args.puerto:
        aviso(f"El puerto {args.puerto} está ocupado; se usa el {puerto}.")

    paso(5, "Abriendo el panel")
    for ruta in (str(RAIZ / "src"), str(RAIZ)):
        if ruta not in sys.path:
            sys.path.insert(0, ruta)
    os.chdir(RAIZ)
    from dashboard.__main__ import main as abrir_panel
    return abrir_panel(["--puerto", str(puerto)] + (["--no-abrir"] if args.no_abrir else []))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n  Panel cerrado.")
        raise SystemExit(0)
