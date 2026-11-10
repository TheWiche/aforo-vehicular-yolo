"""
API del dashboard (FastAPI) y servidor de la interfaz.

    GET /api/panel?camaras=a&percentil=85     el resumen de una camara, en un solo JSON
    GET /api/cruces?camara=a&filtro=excesos   una pagina del registro de vehiculos
    GET /api/fotograma?camara=a&t=<momento>   el cuadro del video en ese instante (JPEG)
    GET /                                      la interfaz (carpeta dashboard/frontend/)

La API solo LEE la base de datos SQLite; nunca escribe. Cada peticion abre su propia
conexion (las conexiones de sqlite3 no se comparten entre hilos) y la cierra al terminar.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import sqlite3

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from aforo.config import CLASES_VEHICULO, COLORES_CLASE, DB_RUTA, LIMITE_VELOCIDAD_KMH, RAIZ_PROYECTO

from . import camara as camara_ctx
from . import consultas
from .panel import abrir_solo_lectura, construir_panel

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


def clases_configuradas() -> List[Dict[str, Any]]:
    """Tipos de vehiculo y su color, tal como los define config.py (los mismos del video)."""
    return [
        {"nombre": nombre, "color": COLORES_CLASE.get(cid, "#8a8c92")}
        for cid, nombre in CLASES_VEHICULO.items()
    ]


def crear_app(ruta_db: Optional[Path] = None, limite_kmh: Optional[float] = None,
              raiz: Optional[Path] = None) -> FastAPI:
    """
    Fabrica de la aplicacion (permite probarla con una base de datos temporal).

    `limite_kmh` fija el limite para todas las camaras; sin el, cada camara usa el de su
    calibracion guardada y, si no tiene, el de config.py. `raiz` es la carpeta donde estan
    `datos/videos/` y `datos/calibraciones.json`.
    """
    ruta = ruta_db or (RAIZ_PROYECTO / DB_RUTA)
    raiz_datos = raiz or RAIZ_PROYECTO
    limite = LIMITE_VELOCIDAD_KMH if limite_kmh is None else limite_kmh

    def contexto(nombre: str, ejecucion: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return camara_ctx.contexto_camara(raiz_datos, nombre, ejecucion, limite, limite_kmh)

    def conexion() -> sqlite3.Connection:
        if not ruta.is_file():
            raise HTTPException(404, "Todavia no existe la base de datos.")
        return abrir_solo_lectura(ruta)
    app = FastAPI(title="Aforo vial - dashboard", docs_url=None, redoc_url=None)

    @app.get("/api/panel")
    def panel(
        camaras: Optional[str] = Query(None, description="Camaras separadas por coma (vacio = todas)"),
        percentil: int = Query(90, ge=50, le=99),
    ) -> Dict[str, Any]:
        seleccion = [c for c in camaras.split(",") if c] if camaras else None
        return construir_panel(ruta, seleccion, percentil, clases_configuradas(), limite, contexto)

    @app.get("/api/cruces")
    def cruces(
        camara: str = Query(..., min_length=1, max_length=120),
        filtro: str = Query("todos", pattern="^(todos|excesos|sin_medir)$"),
        tipo: Optional[str] = Query(None, max_length=40),
        track: Optional[int] = Query(None, ge=0, description="ID del vehiculo (track_id)"),
        orden: str = Query("hora", pattern="^(hora|velocidad)$"),
        cuantos: int = Query(50, ge=1, le=500),
        desde: int = Query(0, ge=0),
    ) -> Dict[str, Any]:
        """Registro de vehiculos de una camara, paginado y filtrado (solo lectura)."""
        con = conexion()
        try:
            try:
                ctx = contexto(camara, consultas.ultima_ejecucion(con, camara))
                pagina = consultas.cruces_filtrados(con, [camara], ctx["limite_kmh"], filtro, tipo or None,
                                                    track, orden, cuantos, desde)
            except sqlite3.OperationalError:
                raise HTTPException(404, "La base de datos no tiene la tabla `cruces`.")
        finally:
            con.close()
        return {
            "total": pagina["total"], "desde": desde, "limite_kmh": ctx["limite_kmh"],
            "filas": [{"id": f["id"], "track": f["track_id"], "tipo": f["tipo"], "t": f["momento"],
                       "v": f["velocidad_kmh"]} for f in pagina["filas"]],
        }

    @app.get("/api/fotograma")
    def fotograma(
        camara: str = Query(..., min_length=1, max_length=120),
        t: Optional[str] = Query(None, max_length=40, description="Momento del cruce (vacio = mitad del video)"),
    ) -> Response:
        """Cuadro del video de la camara en el instante `t`, para ver el vehiculo sobre las lineas."""
        con = conexion()
        try:
            ejecucion = consultas.ultima_ejecucion(con, camara)
        finally:
            con.close()
        datos = camara_ctx.fotograma(raiz_datos, ejecucion, t)
        if datos is None:
            raise HTTPException(404, "No hay un cuadro disponible para esa camara (falta el video o su ejecucion).")
        return Response(datos, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/")
    def indice() -> FileResponse:
        return FileResponse(FRONTEND / "index.html")

    # Hojas de estilo, scripts y demas archivos estaticos de la interfaz.
    app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")
    return app


app = crear_app()
