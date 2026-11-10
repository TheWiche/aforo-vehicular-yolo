"""
db.py
=====
Capa de PERSISTENCIA: almacenamiento final de los cruces en SQLite.

Por que SQLite
--------------
SQLite es una base de datos relacional completa guardada en UN solo archivo
(`datos/db/database.db`), sin servidor que instalar. A diferencia de un CSV:
  * garantiza integridad (tipos, claves primarias, transacciones ACID: si el
    programa se cierra a la mitad, nunca queda una fila a medio escribir);
  * se consulta con SQL (`SELECT ... GROUP BY ...`) en lugar de recorrer
    archivos de texto;
  * permite que el dashboard lea los datos MIENTRAS aforo procesar los escribe
    (modo WAL: un escritor y varios lectores a la vez).

Esquema de la tabla `cruces` (una fila por vehiculo contado):

    id             INTEGER PRIMARY KEY   identificador de la fila (autonumerico)
    track_id       INTEGER               ID unico que asigno el tracker (ByteTrack)
    tipo           TEXT                  Auto / Moto / Bus / Camion
    momento        TIMESTAMP             instante del cruce de la linea de conteo
    velocidad_kmh  REAL                  velocidad medida en la ROI (NULL si no hubo medicion)
    camara         TEXT                  nombre de la camara / fuente de video

Otras tablas (modelo completo documentado en docs/MODELO_DATOS.md):

    alertas           EXCESO_VELOCIDAD y TRAFICO_DETENIDO (ver alertas.py)
    lecturas_trafico  estado de la via cada N segundos (vehiculos, movimiento, estado)
    ejecuciones       que video / hora de inicio produjo los datos de cada camara
    metricas          resultados de evaluar.py (precision, recall, error de velocidad...)
    v_aforo_por_minuto  VISTA: conteo de vehiculos y velocidad promedio por minuto y tipo

Nota: `track_id` se reinicia en 0 en cada ejecucion del tracker. Dentro de una
misma ejecucion es unico; para identificar un vehiculo en toda la tabla usa la
combinacion (camara, momento, track_id) o la clave primaria `id`.

Seguridad: todas las consultas usan parametros (`?`) y nunca concatenan
valores en el texto SQL, lo que previene inyeccion SQL.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Dict, Optional, Type

logger = logging.getLogger(__name__)

TABLA: str = "cruces"

SQL_CREAR_TABLA: str = """
CREATE TABLE IF NOT EXISTS cruces (
    id             INTEGER PRIMARY KEY,
    track_id       INTEGER,
    tipo           TEXT,
    momento        TIMESTAMP,
    velocidad_kmh  REAL,
    camara         TEXT
)
"""

# Indice para acelerar las consultas del dashboard (filtran por camara y hora).
SQL_CREAR_INDICE: str = (
    "CREATE INDEX IF NOT EXISTS idx_cruces_camara_momento ON cruces (camara, momento)"
)

# Alertas de negocio (ver alertas.py): exceso de velocidad y trafico detenido.
SQL_CREAR_ALERTAS: str = """
CREATE TABLE IF NOT EXISTS alertas (
    id           INTEGER PRIMARY KEY,
    camara       TEXT      NOT NULL,
    momento      TIMESTAMP NOT NULL,
    tipo         TEXT      NOT NULL,     -- EXCESO_VELOCIDAD | TRAFICO_DETENIDO
    track_id     INTEGER,                -- vehiculo implicado (NULL si la alerta es de la via)
    valor        REAL,                   -- velocidad medida (km/h) o vehiculos detenidos
    umbral       REAL,                   -- limite que se supero
    descripcion  TEXT
)
"""
SQL_CREAR_INDICE_ALERTAS: str = (
    "CREATE INDEX IF NOT EXISTS idx_alertas_camara_momento ON alertas (camara, momento)"
)

# Lecturas periodicas del estado de la via (analisis de movimiento + YOLO).
SQL_CREAR_LECTURAS: str = """
CREATE TABLE IF NOT EXISTS lecturas_trafico (
    id                 INTEGER PRIMARY KEY,
    camara             TEXT      NOT NULL,
    momento            TIMESTAMP NOT NULL,
    vehiculos_roi      REAL,             -- promedio de vehiculos dentro de la ROI en el intervalo
    ratio_movimiento   REAL,             -- fraccion (0..1) de pixeles de la ROI en movimiento (promedio)
    estado             TEXT              -- LIBRE | FLUIDO | DETENIDO al cierre del intervalo
)
"""
SQL_CREAR_INDICE_LECTURAS: str = (
    "CREATE INDEX IF NOT EXISTS idx_lecturas_camara_momento ON lecturas_trafico (camara, momento)"
)

# Trazabilidad: que video y que hora de inicio produjeron los cruces de cada camara.
# evaluar.py la usa para convertir `momento` en "segundos desde el inicio del video".
SQL_CREAR_EJECUCIONES: str = """
CREATE TABLE IF NOT EXISTS ejecuciones (
    id            INTEGER PRIMARY KEY,
    camara        TEXT      NOT NULL,
    video         TEXT      NOT NULL,
    inicio_video  TIMESTAMP NOT NULL,   -- hora real asignada al primer frame
    fps           REAL,
    frames        INTEGER,
    procesado_en  TIMESTAMP NOT NULL    -- cuando se corrio aforo procesar
)
"""

# Resultados de la evaluacion de metricas (ver evaluar.py).
SQL_CREAR_METRICAS: str = """
CREATE TABLE IF NOT EXISTS metricas (
    id            INTEGER PRIMARY KEY,
    camara        TEXT      NOT NULL,
    evaluado_en   TIMESTAMP NOT NULL,
    metrica       TEXT      NOT NULL,     -- p. ej. precision, recall, f1, mae_velocidad_kmh
    valor         REAL,
    detalle       TEXT
)
"""

# Vista de conteos: vehiculos por minuto y tipo (la consulta de aforo mas usada).
SQL_CREAR_VISTA_AFORO: str = """
CREATE VIEW IF NOT EXISTS v_aforo_por_minuto AS
SELECT camara,
       strftime('%Y-%m-%d %H:%M', momento) AS minuto,
       tipo,
       COUNT(*)                            AS vehiculos,
       ROUND(AVG(velocidad_kmh), 1)        AS velocidad_promedio_kmh
FROM cruces
GROUP BY camara, minuto, tipo
"""

# Todo lo que se ejecuta al abrir la base de datos (todas son idempotentes).
SENTENCIAS_ESQUEMA = (
    SQL_CREAR_TABLA, SQL_CREAR_INDICE,
    SQL_CREAR_ALERTAS, SQL_CREAR_INDICE_ALERTAS,
    SQL_CREAR_LECTURAS, SQL_CREAR_INDICE_LECTURAS,
    SQL_CREAR_EJECUCIONES, SQL_CREAR_METRICAS, SQL_CREAR_VISTA_AFORO,
)


class BaseDatosError(RuntimeError):
    """Se lanza cuando la base de datos no se puede abrir, crear o escribir."""


def formatear_momento(momento: datetime) -> str:
    """
    Convierte un datetime al texto 'AAAA-MM-DD HH:MM:SS.mmm'.

    SQLite no tiene un tipo fecha propio: guarda los TIMESTAMP como texto ISO-8601,
    que ademas se ordena cronologicamente al ordenarlo como texto. Se convierte de
    forma explicita (en vez de depender del adaptador automatico de `sqlite3`, que
    esta obsoleto desde Python 3.12).
    """
    return momento.isoformat(sep=" ", timespec="milliseconds")


class CrucesDB:
    """Conexion a la base de datos y operaciones de escritura sobre `cruces`."""

    def __init__(self, ruta: Path) -> None:
        self._ruta = ruta
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            self._con = sqlite3.connect(str(ruta), timeout=10.0)
            # WAL (Write-Ahead Logging): el dashboard puede leer mientras se escribe.
            self._con.execute("PRAGMA journal_mode=WAL")
            for sentencia in SENTENCIAS_ESQUEMA:      # "IF NOT EXISTS": no borra datos existentes
                self._con.execute(sentencia)
            self._con.commit()
        except (sqlite3.Error, OSError) as exc:
            raise BaseDatosError(f"No se pudo abrir/crear la base de datos '{ruta}': {exc}") from exc
        logger.info("Base de datos lista: %s", ruta)

    # ------------------------------------------------------------ escritura
    def insertar_cruce(
        self,
        track_id: int,
        tipo: str,
        momento: datetime,
        velocidad_kmh: Optional[float],
        camara: str,
    ) -> int:
        """
        Inserta un cruce y devuelve el `id` de la fila creada.

        Se hace `commit()` en cada insercion: asi el dato queda guardado de forma
        durable en cuanto el vehiculo cruza (aunque el programa se interrumpa
        despues) y el dashboard lo ve de inmediato.
        """
        try:
            cursor = self._con.execute(
                "INSERT INTO cruces (track_id, tipo, momento, velocidad_kmh, camara) "
                "VALUES (?, ?, ?, ?, ?)",
                (int(track_id), tipo, formatear_momento(momento),
                 None if velocidad_kmh is None else float(velocidad_kmh), camara),
            )
            self._con.commit()
        except sqlite3.Error as exc:
            self._con.rollback()
            raise BaseDatosError(f"No se pudo insertar el cruce del track {track_id}: {exc}") from exc
        return int(cursor.lastrowid)

    def actualizar_velocidad(self, fila_id: int, velocidad_kmh: float) -> None:
        """Completa la velocidad de un cruce ya insertado (medicion que llego despues)."""
        try:
            self._con.execute(
                "UPDATE cruces SET velocidad_kmh = ? WHERE id = ?", (float(velocidad_kmh), fila_id)
            )
            self._con.commit()
        except sqlite3.Error as exc:
            self._con.rollback()
            raise BaseDatosError(f"No se pudo actualizar la fila {fila_id}: {exc}") from exc

    def insertar_alerta(
        self,
        camara: str,
        momento: datetime,
        tipo: str,
        track_id: Optional[int],
        valor: Optional[float],
        umbral: Optional[float],
        descripcion: str,
    ) -> int:
        """Inserta una alerta (exceso de velocidad o trafico detenido). Devuelve su `id`."""
        try:
            cursor = self._con.execute(
                "INSERT INTO alertas (camara, momento, tipo, track_id, valor, umbral, descripcion) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (camara, formatear_momento(momento), tipo,
                 None if track_id is None else int(track_id), valor, umbral, descripcion),
            )
            self._con.commit()
        except sqlite3.Error as exc:
            self._con.rollback()
            raise BaseDatosError(f"No se pudo insertar la alerta '{tipo}': {exc}") from exc
        return int(cursor.lastrowid)

    def insertar_lectura(
        self,
        camara: str,
        momento: datetime,
        vehiculos_roi: float,
        ratio_movimiento: float,
        estado: str,
    ) -> int:
        """Inserta una lectura periodica del estado de la via. Devuelve su `id`."""
        try:
            cursor = self._con.execute(
                "INSERT INTO lecturas_trafico (camara, momento, vehiculos_roi, ratio_movimiento, estado) "
                "VALUES (?, ?, ?, ?, ?)",
                (camara, formatear_momento(momento), round(vehiculos_roi, 2), round(ratio_movimiento, 4), estado),
            )
            self._con.commit()
        except sqlite3.Error as exc:
            self._con.rollback()
            raise BaseDatosError(f"No se pudo insertar la lectura: {exc}") from exc
        return int(cursor.lastrowid)

    def registrar_ejecucion(
        self, camara: str, video: str, inicio_video: datetime, fps: float, frames: Optional[int]
    ) -> int:
        """Anota que se proceso `video` para `camara` con esa hora de inicio. Devuelve su `id`."""
        try:
            cursor = self._con.execute(
                "INSERT INTO ejecuciones (camara, video, inicio_video, fps, frames, procesado_en) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (camara, video, formatear_momento(inicio_video), float(fps),
                 None if frames is None else int(frames), formatear_momento(datetime.now())),
            )
            self._con.commit()
        except sqlite3.Error as exc:
            self._con.rollback()
            raise BaseDatosError(f"No se pudo registrar la ejecucion: {exc}") from exc
        return int(cursor.lastrowid)

    def insertar_metrica(
        self, camara: str, evaluado_en: datetime, metrica: str, valor: Optional[float], detalle: str = ""
    ) -> int:
        """Guarda el resultado de una metrica de evaluacion. Devuelve su `id`."""
        try:
            cursor = self._con.execute(
                "INSERT INTO metricas (camara, evaluado_en, metrica, valor, detalle) VALUES (?, ?, ?, ?, ?)",
                (camara, formatear_momento(evaluado_en), metrica, valor, detalle),
            )
            self._con.commit()
        except sqlite3.Error as exc:
            self._con.rollback()
            raise BaseDatosError(f"No se pudo guardar la metrica '{metrica}': {exc}") from exc
        return int(cursor.lastrowid)

    def eliminar_camara(self, camara: str) -> int:
        """
        Borra los datos de una camara (cruces, alertas, lecturas y ejecuciones) para repetir una
        prueba sin duplicados. Devuelve cuantos CRUCES se borraron. Las metricas
        se conservan: son el historial de evaluaciones.
        """
        try:
            cursor = self._con.execute("DELETE FROM cruces WHERE camara = ?", (camara,))
            self._con.execute("DELETE FROM alertas WHERE camara = ?", (camara,))
            self._con.execute("DELETE FROM lecturas_trafico WHERE camara = ?", (camara,))
            self._con.execute("DELETE FROM ejecuciones WHERE camara = ?", (camara,))
            self._con.commit()
        except sqlite3.Error as exc:
            self._con.rollback()
            raise BaseDatosError(f"No se pudieron borrar los cruces de '{camara}': {exc}") from exc
        return cursor.rowcount

    # ------------------------------------------------------------- consulta
    def contar(self, camara: Optional[str] = None) -> int:
        """Numero de filas (opcionalmente de una sola camara)."""
        if camara is None:
            fila = self._con.execute("SELECT COUNT(*) FROM cruces").fetchone()
        else:
            fila = self._con.execute(
                "SELECT COUNT(*) FROM cruces WHERE camara = ?", (camara,)
            ).fetchone()
        return int(fila[0])

    # ------------------------------------------------------------- ciclo de vida
    @property
    def ruta(self) -> Path:
        return self._ruta

    def cerrar(self) -> None:
        """Cierra la conexion (un `with` lo hace automaticamente)."""
        self._con.close()

    def __enter__(self) -> "CrucesDB":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.cerrar()


class RegistradorCruces:
    """
    Traduce los eventos del sistema en filas de la base de datos.

    Dos eventos independientes alimentan la tabla y pueden ocurrir en cualquier
    orden para un mismo vehiculo:

      * cruce de la linea de conteo  -> crea la fila (INSERT) apenas ocurre.
      * medicion de velocidad (ROI)  -> completa `velocidad_kmh`.

    Casos segun el orden en que lleguen:
      - velocidad DESPUES del cruce : la fila ya existe -> UPDATE.
      - velocidad ANTES del cruce   : se guarda en memoria y se incluye en el
                                      INSERT cuando el vehiculo cruce la linea.
    Un vehiculo que nunca cruza la linea de conteo no se registra: la tabla
    refleja exactamente los vehiculos contados en el aforo.
    """

    def __init__(self, db: CrucesDB, camara: str) -> None:
        self._db = db
        self._camara = camara
        self._filas: Dict[int, int] = {}                # track_id -> id de la fila insertada
        self._velocidades_pendientes: Dict[int, float] = {}
        self.insertados: int = 0

    def registrar_cruce(self, track_id: int, tipo: str, momento: datetime) -> Optional[int]:
        """INSERT del cruce. Devuelve el id de la fila (o None si el track ya estaba registrado)."""
        if track_id in self._filas:
            return None     # defensa: un vehiculo (ID) se registra una sola vez
        velocidad = self._velocidades_pendientes.pop(track_id, None)   # ya redondeada
        fila_id = self._db.insertar_cruce(track_id, tipo, momento, velocidad, self._camara)
        self._filas[track_id] = fila_id
        self.insertados += 1
        return fila_id

    def registrar_velocidad(self, track_id: int, velocidad_kmh: float) -> None:
        """Asocia la velocidad al vehiculo: UPDATE si ya cruzo, o espera su cruce."""
        # Un decimal basta: la precision real de la medicion (un frame de ~40 ms sobre
        # unos segundos de recorrido) no justifica guardar 15 decimales.
        velocidad_kmh = round(velocidad_kmh, 1)
        fila_id = self._filas.get(track_id)
        if fila_id is None:
            self._velocidades_pendientes[track_id] = velocidad_kmh
        else:
            self._db.actualizar_velocidad(fila_id, velocidad_kmh)
