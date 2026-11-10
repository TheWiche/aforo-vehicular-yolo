"""
API del dashboard (FastAPI) y servidor de la interfaz.

    GET /api/panel?camaras=a,b&percentil=90   todo lo que pinta la pantalla, en un solo JSON
    GET /                                      la interfaz (carpeta dashboard/frontend/)

La API solo LEE la base de datos SQLite; nunca escribe. Cada peticion abre su propia
conexion (las conexiones de sqlite3 no se comparten entre hilos) y la cierra al terminar.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from aforo.config import CLASES_VEHICULO, COLORES_CLASE, DB_RUTA, LIMITE_VELOCIDAD_KMH, RAIZ_PROYECTO

from .panel import construir_panel

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


def clases_configuradas() -> List[Dict[str, Any]]:
    """Tipos de vehiculo y su color, tal como los define config.py (los mismos del video)."""
    return [
        {"nombre": nombre, "color": COLORES_CLASE.get(cid, "#8a8c92")}
        for cid, nombre in CLASES_VEHICULO.items()
    ]


def crear_app(ruta_db: Optional[Path] = None, limite_kmh: Optional[float] = None) -> FastAPI:
    """Fabrica de la aplicacion (permite probarla con una base de datos temporal)."""
    ruta = ruta_db or (RAIZ_PROYECTO / DB_RUTA)
    limite = LIMITE_VELOCIDAD_KMH if limite_kmh is None else limite_kmh
    app = FastAPI(title="Aforo vial - dashboard", docs_url=None, redoc_url=None)

    @app.get("/api/panel")
    def panel(
        camaras: Optional[str] = Query(None, description="Camaras separadas por coma (vacio = todas)"),
        percentil: int = Query(90, ge=50, le=99),
    ) -> Dict[str, Any]:
        seleccion = [c for c in camaras.split(",") if c] if camaras else None
        return construir_panel(ruta, seleccion, percentil, clases_configuradas(), limite)

    @app.get("/")
    def indice() -> FileResponse:
        return FileResponse(FRONTEND / "index.html")

    # Hojas de estilo, scripts y demas archivos estaticos de la interfaz.
    app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")
    return app


app = crear_app()
