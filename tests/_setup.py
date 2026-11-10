"""Hace importable el paquete `aforo` (src/) y el `dashboard` (raiz) al correr las pruebas sin instalar."""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
for ruta in (RAIZ / "src", RAIZ):
    if str(ruta) not in sys.path:
        sys.path.insert(0, str(ruta))
