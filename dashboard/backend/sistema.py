"""
Diagnostico del entorno para la pagina "Sistema": Python, paquetes, GPU, pesos y archivos de datos.

Solo LEE: nunca instala nada desde la web (eso lo hace `iniciar.py`, que pregunta antes).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# modulo importable -> (paquete pip, para que sirve)
NUCLEO = {
    "cv2": ("opencv-python", "lee el video y dibuja"),
    "numpy": ("numpy", "cálculo numérico"),
    "supervision": ("supervision", "detecciones, líneas y anotaciones"),
    "trackers": ("trackers", "seguimiento ByteTrack"),
    "ultralytics": ("ultralytics", "modelo YOLOv8"),
    "torch": ("torch", "red neuronal"),
    "tqdm": ("tqdm", "barra de progreso"),
}
DASHBOARD = {
    "fastapi": ("fastapi", "servidor de esta página"),
    "uvicorn": ("uvicorn", "servidor web"),
}
COMANDO_TORCH_CUDA = ("pip install --force-reinstall --no-deps torch==2.14.1+cu130 torchvision==0.29.1+cu130 "
                      "--index-url https://download.pytorch.org/whl/cu130")

_cache_gpu: Tuple[float, Dict[str, Any]] = (0.0, {})
_TTL_GPU_S = 90.0


def _instalado(modulo: str) -> bool:
    try:
        return importlib.util.find_spec(modulo) is not None
    except (ImportError, ValueError):
        return False


def estado_gpu(python: Optional[str] = None) -> Dict[str, Any]:
    """
    {"modo": "gpu" | "cpu_con_gpu" | "cpu", "nombre": str}. Se consulta en un subproceso (torch tarda en
    cargar y no queremos bloquear el servidor ni cargar CUDA en el) y se recuerda 90 s.
    """
    global _cache_gpu
    if time.time() - _cache_gpu[0] < _TTL_GPU_S and _cache_gpu[1]:
        return _cache_gpu[1]
    resultado: Dict[str, Any] = {"modo": "cpu", "nombre": ""}
    if _instalado("torch"):
        try:
            r = subprocess.run([python or sys.executable, "-c",
                                "import torch; print(torch.cuda.is_available()); "
                                "print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"],
                               capture_output=True, text=True, timeout=120)
            lineas = r.stdout.strip().splitlines()
            if len(lineas) >= 2 and lineas[0] == "True":
                resultado = {"modo": "gpu", "nombre": lineas[1]}
        except (subprocess.SubprocessError, OSError):
            pass
    if resultado["modo"] == "cpu":
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                               capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                resultado = {"modo": "cpu_con_gpu", "nombre": r.stdout.strip().splitlines()[0]}
        except (subprocess.SubprocessError, OSError):
            pass
    _cache_gpu = (time.time(), resultado)
    return resultado


def diagnostico(raiz: Path, ruta_db: Path, cruces_por_camara: Dict[str, int], con_gpu: bool = True) -> Dict[str, Any]:
    """Foto del entorno lista para convertir a JSON."""
    paquetes: List[Dict[str, Any]] = [
        {"modulo": m, "paquete": pip, "para": para, "ok": _instalado(m), "grupo": grupo}
        for grupo, tabla in (("nucleo", NUCLEO), ("dashboard", DASHBOARD)) for m, (pip, para) in tabla.items()
    ]
    pesos = [{"nombre": p.name, "mb": round(p.stat().st_size / 1e6, 1)}
             for p in sorted((raiz / "datos" / "modelos").glob("*.pt"))] if (raiz / "datos" / "modelos").is_dir() else []
    gpu = estado_gpu() if con_gpu else {"modo": "desconocido", "nombre": ""}
    return {
        "python": sys.version.split()[0],
        "python_ok": sys.version_info >= (3, 10),
        "entorno_virtual": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
        "paquetes": paquetes,
        "gpu": {**gpu, "comando": COMANDO_TORCH_CUDA},
        "pesos": pesos,
        "base_de_datos": {
            "ruta": str(ruta_db), "existe": ruta_db.is_file(),
            "mb": round(ruta_db.stat().st_size / 1e6, 2) if ruta_db.is_file() else 0,
            "camaras": cruces_por_camara,
        },
    }
