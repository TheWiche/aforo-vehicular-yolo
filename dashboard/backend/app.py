"""
API del dashboard (FastAPI) y servidor de la interfaz.

Datos (solo lectura sobre la base SQLite):
    GET  /api/panel?camaras=a&percentil=85     el resumen de una camara, en un solo JSON
    GET  /api/cruces?camara=a&filtro=excesos   una pagina del registro de vehiculos
    GET  /api/fotograma?camara=a&t=<momento>   el cuadro del video en el instante de un cruce (JPEG)

Videos y calibracion:
    GET  /api/videos                           videos disponibles, su calibracion y cruces guardados
    GET  /api/videos/cuadro?video=&t=&ancho=   un cuadro del video en el segundo `t` (JPEG)
    POST /api/videos/agregar                   registra un video por su ruta completa
    PUT  /api/videos/subir?nombre=             sube un video (el cuerpo es el archivo)
    GET  /api/calibracion?video=               perfil guardado + propiedades del video + sugerencia
    PUT  /api/calibracion                      valida y guarda el perfil (datos/calibraciones.json)

Procesamiento y sistema:
    GET  /api/proceso                          estado y progreso del analisis en curso
    POST /api/proceso/iniciar | /detener       lanza o detiene el analisis (proceso aparte)
    GET  /api/proceso/video                    vista en vivo del analisis (MJPEG)
    GET  /api/sistema                          diagnostico: Python, paquetes, GPU, pesos, base de datos

    GET  /                                      la interfaz (carpeta dashboard/frontend/)

La base de datos solo se LEE desde aqui (cada peticion abre su conexion de solo lectura). Lo unico
que el servidor escribe es la calibracion y los videos subidos; el analisis, que si escribe en la
base, corre en un proceso aparte (ver proceso.py).
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from aforo import perfiles
from aforo.config import (CLASES_VEHICULO, COLORES_CLASE, DB_RUTA, LIMITE_VELOCIDAD_KMH, RAIZ_PROYECTO,
                          ConfigError, cargar_configuracion)

from . import camara as camara_ctx
from . import consultas, sistema, videos
from .panel import abrir_solo_lectura, construir_panel
from .proceso import MODOS, ErrorProceso, GestorProceso

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


def clases_configuradas() -> List[Dict[str, Any]]:
    """Tipos de vehiculo y su color, tal como los define config.py (los mismos del video)."""
    return [
        {"nombre": nombre, "color": COLORES_CLASE.get(cid, "#8a8c92")}
        for cid, nombre in CLASES_VEHICULO.items()
    ]


# --------------------------------------------------------------------------- cuerpos de peticiones
Linea = List[List[float]]


class PerfilEntrada(BaseModel):
    """Calibracion que envia el calibrador de la web."""
    video: str = Field(min_length=1, max_length=260)
    camara: str = Field(min_length=1, max_length=40)
    linea_conteo: Linea
    linea_a: Linea
    linea_b: Linea
    distancia_m: float
    limite_kmh: float
    velocidad_max_kmh: float = 120.0
    nota: Optional[str] = Field(None, max_length=500)
    regla: Optional[Dict[str, Any]] = None
    fecha_inicio: Optional[str] = Field(None, max_length=19)


class RutaEntrada(BaseModel):
    ruta: str = Field(min_length=1, max_length=1024)


class IniciarEntrada(BaseModel):
    video: str = Field(min_length=1, max_length=260)
    modo: str
    reemplazar: bool = False
    guardar_video: bool = False


def crear_app(ruta_db: Optional[Path] = None, limite_kmh: Optional[float] = None,
              raiz: Optional[Path] = None, gestor: Optional[GestorProceso] = None) -> FastAPI:
    """
    Fabrica de la aplicacion (permite probarla con una base de datos temporal).

    `limite_kmh` fija el limite para todas las camaras; sin el, cada camara usa el de su
    calibracion guardada y, si no tiene, el de config.py. `raiz` es la carpeta donde estan
    `datos/videos/` y `datos/calibraciones.json`. `gestor` permite inyectar uno falso en las pruebas.
    """
    ruta = ruta_db or (RAIZ_PROYECTO / DB_RUTA)
    raiz_datos = raiz or RAIZ_PROYECTO
    limite = LIMITE_VELOCIDAD_KMH if limite_kmh is None else limite_kmh
    archivo_perfiles = raiz_datos / "datos" / "calibraciones.json"
    gestor = gestor or GestorProceso(raiz_datos, ruta)

    def contexto(nombre: str, ejecucion: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return camara_ctx.contexto_camara(raiz_datos, nombre, ejecucion, limite, limite_kmh)

    def conexion() -> sqlite3.Connection:
        if not ruta.is_file():
            raise HTTPException(404, "Todavia no existe la base de datos.")
        return abrir_solo_lectura(ruta)

    def cruces_por_camara() -> Dict[str, int]:
        if not ruta.is_file():
            return {}
        con = abrir_solo_lectura(ruta)
        try:
            return {c["camara"]: c["cruces"] for c in consultas.camaras_disponibles(con)}
        except sqlite3.OperationalError:
            return {}
        finally:
            con.close()

    def video_o_404(nombre: str) -> Path:
        encontrado = videos.resolver(raiz_datos, nombre)
        if encontrado is None:
            raise HTTPException(404, f"No encuentro el video «{Path(nombre).name}».")
        return encontrado

    app = FastAPI(title="Aforo vial - dashboard", docs_url=None, redoc_url=None)

    # ------------------------------------------------------------------ datos
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

    # ------------------------------------------------------------------ videos
    @app.get("/api/videos")
    def listar_videos() -> Dict[str, Any]:
        return {"videos": videos.listar(raiz_datos, cruces_por_camara(), archivo_perfiles)}

    @app.get("/api/videos/cuadro")
    def cuadro_de_video(
        video: str = Query(..., min_length=1, max_length=260),
        t: float = Query(0.0, ge=0, le=86400 * 7, description="Segundo del video"),
        ancho: int = Query(1280, ge=160, le=1920),
    ) -> Response:
        video_o_404(video)
        datos = videos.cuadro(raiz_datos, video, t, ancho)
        if datos is None:
            raise HTTPException(404, "No se pudo leer ese cuadro del video.")
        return Response(datos, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    @app.post("/api/videos/agregar")
    def agregar_video(cuerpo: RutaEntrada) -> Dict[str, Any]:
        try:
            return {"nombre": videos.registrar_externo(raiz_datos, cuerpo.ruta)}
        except videos.ErrorVideo as exc:
            raise HTTPException(422, str(exc))

    @app.put("/api/videos/subir")
    async def subir_video(request: Request, nombre: str = Query(..., min_length=1, max_length=260)) -> Dict[str, Any]:
        try:
            limpio, destino = videos.ruta_para_subida(raiz_datos, nombre)
        except videos.ErrorVideo as exc:
            raise HTTPException(422, str(exc))
        parcial = destino.with_name(destino.name + ".part")
        recibido = 0
        try:
            with open(parcial, "wb") as f:
                async for trozo in request.stream():
                    recibido += len(trozo)
                    if recibido > videos.TAMANO_MAXIMO_SUBIDA:
                        raise HTTPException(413, "El archivo supera el máximo de 8 GB.")
                    f.write(trozo)
            if recibido == 0:
                raise HTTPException(422, "El archivo está vacío.")
            parcial.replace(destino)
        except BaseException:
            parcial.unlink(missing_ok=True)
            raise
        if not videos.propiedades(destino):
            destino.unlink(missing_ok=True)
            raise HTTPException(422, "OpenCV no puede abrir ese archivo (¿está dañado o en un formato no soportado?).")
        return {"nombre": limpio, "bytes": recibido}

    # ------------------------------------------------------------------ calibracion
    @app.get("/api/calibracion")
    def leer_calibracion(video: str = Query(..., min_length=1, max_length=260)) -> Dict[str, Any]:
        ruta_video = video_o_404(video)
        props = videos.propiedades(ruta_video)
        if not props:
            raise HTTPException(422, "OpenCV no puede abrir ese video.")
        nombre = ruta_video.name
        perfil = perfiles.cargar(archivo_perfiles).get(nombre)
        return {
            "video": nombre, **props, "calibrado": perfil is not None, "perfil": perfil,
            "sugerido": perfiles.sugerir(props["ancho"], props["alto"]),
            "camara_sugerida": re.sub(r"[^\w\-]+", "_", Path(nombre).stem).strip("_")[:40] or "camara_01",
        }

    @app.put("/api/calibracion")
    def guardar_calibracion(cuerpo: PerfilEntrada) -> Dict[str, Any]:
        ruta_video = video_o_404(cuerpo.video)
        props = videos.propiedades(ruta_video)
        if not props:
            raise HTTPException(422, "OpenCV no puede abrir ese video.")
        perfil: Dict[str, Any] = {
            "CAMARA": cuerpo.camara.strip(),
            "LINEA_CONTEO": cuerpo.linea_conteo, "LINEA_VELOCIDAD_A": cuerpo.linea_a, "LINEA_VELOCIDAD_B": cuerpo.linea_b,
            "DISTANCIA_REAL_METROS": cuerpo.distancia_m, "LIMITE_VELOCIDAD_KMH": cuerpo.limite_kmh,
            "VELOCIDAD_MAX_KMH": cuerpo.velocidad_max_kmh,
        }
        if cuerpo.nota is not None:
            perfil["nota"] = cuerpo.nota
        if cuerpo.regla is not None:
            perfil["REGLA"] = cuerpo.regla
        if cuerpo.fecha_inicio:
            perfil["FECHA_INICIO_VIDEO"] = cuerpo.fecha_inicio
        errores, avisos = perfiles.validar(perfil, props["ancho"], props["alto"])
        if not errores:
            try:                                      # la misma comprobacion que hara el analisis
                perfiles.aplicar_a_config(cargar_configuracion(), perfil)
            except ConfigError as exc:
                errores.append(str(exc))
        if errores:
            raise HTTPException(422, detail={"errores": errores})
        perfiles.guardar(ruta_video.name, perfil, archivo_perfiles)
        return {"ok": True, "video": ruta_video.name, "avisos": avisos}

    # ------------------------------------------------------------------ sistema
    @app.get("/api/sistema")
    def diagnostico() -> Dict[str, Any]:
        return sistema.diagnostico(raiz_datos, ruta, cruces_por_camara())

    # ------------------------------------------------------------------ procesamiento
    @app.get("/api/proceso")
    def estado_proceso() -> Dict[str, Any]:
        return gestor.estado()

    @app.post("/api/proceso/iniciar")
    def iniciar_proceso(cuerpo: IniciarEntrada) -> Dict[str, Any]:
        if cuerpo.modo not in MODOS:
            raise HTTPException(422, f"Modo desconocido: {cuerpo.modo}")
        ruta_video = video_o_404(cuerpo.video)
        perfil = perfiles.cargar(archivo_perfiles).get(ruta_video.name)
        if perfil is None:
            raise HTTPException(409, "Este video aún no está calibrado. Calibra las líneas antes de procesarlo.")
        props = videos.propiedades(ruta_video) or {}
        errores, _ = perfiles.validar(perfil, props.get("ancho"), props.get("alto"))
        if errores:
            raise HTTPException(409, "La calibración guardada tiene problemas: " + " ".join(errores))
        try:
            gestor.iniciar(ruta_video, cuerpo.modo, str(perfil.get("CAMARA") or "camara_01"),
                           sistema.estado_gpu()["modo"] == "gpu", cuerpo.reemplazar, cuerpo.guardar_video)
        except ErrorProceso as exc:
            raise HTTPException(409, str(exc))
        return gestor.estado()

    @app.post("/api/proceso/detener")
    def detener_proceso() -> Dict[str, Any]:
        gestor.detener()
        return gestor.estado()

    @app.get("/api/proceso/video")
    async def vista_en_vivo(request: Request) -> StreamingResponse:
        """El cuadro anotado del analisis como MJPEG: el navegador lo muestra en una etiqueta <img>."""
        async def generador():
            ultimo, inactivo = 0.0, 0
            while not await request.is_disconnected():
                momento = gestor.cuadro_mtime()
                if momento and momento != ultimo:
                    datos = gestor.cuadro()
                    if datos:
                        ultimo, inactivo = momento, 0
                        yield (b"--cuadro\r\nContent-Type: image/jpeg\r\nContent-Length: "
                               + str(len(datos)).encode() + b"\r\n\r\n" + datos + b"\r\n")
                else:
                    inactivo += 1
                    if not gestor.corriendo() and inactivo > 12:      # termino y ya se envio el ultimo cuadro
                        break
                await asyncio.sleep(0.05)
        return StreamingResponse(generador(), media_type="multipart/x-mixed-replace; boundary=cuadro",
                                 headers={"Cache-Control": "no-store"})

    @app.get("/api/proceso/cuadro")
    def ultimo_cuadro() -> Response:
        datos = gestor.cuadro()
        if datos is None:
            raise HTTPException(404, "Todavía no hay cuadros.")
        return Response(datos, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    # ------------------------------------------------------------------ interfaz
    @app.get("/")
    def indice() -> FileResponse:
        return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})

    # Hojas de estilo, scripts y demas archivos estaticos de la interfaz.
    app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")
    return app


app = crear_app()
