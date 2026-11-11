"""
Arranca el dashboard:   python -m aforo dashboard   (o python -m dashboard)

    --puerto 8501   --host 127.0.0.1   --db ruta/a/otra.db   --no-abrir
"""

from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path
from typing import List, Optional

import uvicorn

from aforo.config import DB_RUTA, RAIZ_PROYECTO

from .backend.app import crear_app


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Dashboard web de aforo vehicular.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--puerto", type=int, default=8501)
    ap.add_argument("--db", type=Path, default=RAIZ_PROYECTO / DB_RUTA, help="Base de datos SQLite a consultar.")
    ap.add_argument("--no-abrir", action="store_true", help="No abrir el navegador automaticamente.")
    args = ap.parse_args(argv)

    # Cargar torch para saber si hay GPU tarda unos segundos: se hace ya, en segundo plano, y la pagina
    # "Procesar" muestra los modos adecuados al abrirse sin esperar.
    from .backend import sistema
    threading.Thread(target=sistema.estado_gpu, daemon=True).start()

    url = f"http://{args.host}:{args.puerto}"
    print(f"Dashboard en {url}  (base de datos: {args.db})\nCtrl+C para detenerlo.")
    if not args.no_abrir:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(crear_app(args.db), host=args.host, port=args.puerto, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
