"""
config.py
=========
Configuracion CENTRALIZADA del sistema de aforo vehicular y estimacion de velocidad.

Este archivo esta dividido en dos partes:

    PARTE 1 - "ZONA DEL USUARIO": constantes simples que debes editar para tu
              video (ruta, lineas virtuales, distancia real en metros, etc.).
    PARTE 2 - Clases `dataclass` con validacion + objeto `CONFIG`. No es necesario
              tocarlas: solo agrupan las constantes de la parte 1 en estructuras
              tipadas e inmutables que consumen el resto de los modulos.

Por que centralizar la configuracion
------------------------------------
Separar "datos" (rutas, coordenadas, umbrales) de "logica" (deteccion, tracking,
conteo) permite recalibrar el sistema para otro video o camara SIN modificar ni
una sola linea de los algoritmos (principio de responsabilidad unica).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from geometry import Point, euclidean_distance, segment_intersection

# Carpeta raiz del proyecto. Se calcula a partir de la ubicacion de este archivo
# para que las rutas relativas funcionen sin importar desde donde se ejecute Python.
RAIZ_PROYECTO: Path = Path(__file__).resolve().parent

# =============================================================================
# PARTE 1 - ZONA DEL USUARIO (edita aqui)
# =============================================================================

# ---------------------------------------------------------------------------
# 1.1 Rutas de entrada / salida (relativas a la carpeta del proyecto)
# ---------------------------------------------------------------------------
VIDEO_ENTRADA: str = "videos/autopista_1.mp4"      # <- TU VIDEO
VIDEO_SALIDA: str = "output/salida.mp4"        # video anotado resultante

# Base de datos SQLite donde se guardan los cruces (almacenamiento final).
# Si el archivo no existe, db.py lo crea junto con la tabla `cruces`.
DB_RUTA: str = "db/database.db"

# Nombre de la camara / fuente de video: se guarda en la columna `camara` de cada
# cruce para distinguir fuentes cuando varias comparten la misma base de datos.
CAMARA: str = "autopista_1"

# Fecha y hora REAL en que empieza el video, formato "AAAA-MM-DD HH:MM:SS".
# El `momento` de cada cruce se calcula como: inicio + segundos transcurridos del
# video (frame / FPS). None = usar la hora actual al arrancar la ejecucion
# (equivale a una camara en vivo).
FECHA_INICIO_VIDEO: Optional[str] = None

# ---------------------------------------------------------------------------
# 1.2 Linea virtual de CONTEO (aforo)
# ---------------------------------------------------------------------------
# Dos puntos (x, y) en PIXELES del video original; el origen (0, 0) es la
# esquina superior izquierda. Usa `python seleccionar_puntos.py` para obtener
# las coordenadas haciendo clic sobre un frame de tu video.
# La linea debe atravesar TODA la calzada para que ningun vehiculo la esquive.
# Colocala DENTRO del tramo entre LINEA_VELOCIDAD_A y LINEA_VELOCIDAD_B (o a su
# salida): cada cruce se guarda en la base de datos junto con la velocidad del
# mismo vehiculo, que solo se conoce tras recorrer la ROI.
LINEA_CONTEO: Tuple[Point, Point] = ((900, 1350), (3150, 1350))

# Nombre de cada sentido de circulacion (ver README: el sentido "A" es el de
# los vehiculos que cruzan la linea con el producto cruz positivo).
ETIQUETA_SENTIDO_A: str = "Sentido A"
ETIQUETA_SENTIDO_B: str = "Sentido B"

# ---------------------------------------------------------------------------
# 1.3 Zona de VELOCIDAD (ROI delimitada por dos lineas)
# ---------------------------------------------------------------------------
# La ROI es el tramo de via entre la LINEA A (entrada) y la LINEA B (salida).
# Se mide cuanto tarda un vehiculo en recorrer ese tramo.
# Ambas lineas deben ser (aprox.) perpendiculares al sentido de la via y
# no cortarse entre si. El sistema detecta automaticamente cual cruza primero,
# asi que funciona en ambos sentidos de circulacion.
LINEA_VELOCIDAD_A: Tuple[Point, Point] = ((990, 990), (3000, 990))
LINEA_VELOCIDAD_B: Tuple[Point, Point] = ((600, 1680), (3570, 1680))

# DISTANCIA REAL en metros entre la linea A y la linea B medida sobre la via
# (por ejemplo con cinta metrica, Google Maps o marcas viales de longitud
# conocida). De este valor depende TODA la precision de la velocidad.
DISTANCIA_REAL_METROS: float = 50.0

# Velocidades fuera de este rango se descartan por considerarse errores de
# tracking (cambio de ID, oclusiones, etc.).
VELOCIDAD_MIN_KMH: float = 2.0
VELOCIDAD_MAX_KMH: float = 200.0

# ---------------------------------------------------------------------------
# 1.4 Modelo de deteccion (YOLOv8)
# ---------------------------------------------------------------------------
# Si el archivo no existe, Ultralytics lo descarga automaticamente.
# Opciones (de mas rapido a mas preciso): yolov8n, yolov8s, yolov8m, yolov8l, yolov8x
MODELO: str = "models/yolov8s.pt"
CONFIANZA_MINIMA: float = 0.25   # descarta detecciones con score menor
IOU_NMS: float = 0.5             # umbral de la supresion de no-maximos
TAMANO_IMAGEN: int = 960         # lado mayor de entrada a la red (px); mas = mejor para autos lejanos
DISPOSITIVO: Optional[str] = None  # None = automatico | "cpu" | "0" (primera GPU CUDA)

# Clases COCO a conservar y su nombre en pantalla.
# (Sin tildes: las fuentes de OpenCV no dibujan caracteres como "ó".)
CLASES_VEHICULO: Dict[int, str] = {
    2: "Auto",
    3: "Moto",
    5: "Bus",
    7: "Camion",
}

# Color (hex) de cada clase, usado en el video de salida Y en dashboard.py para
# que cada tipo de vehiculo tenga el mismo color en todas partes. Son tonos
# pensados para fondo oscuro y validados para que no se confundan entre si
# (incluso con daltonismo); evita poner juntos rojo y verde.
COLORES_CLASE: Dict[int, str] = {
    2: "#3987e5",   # azul     (Auto)
    3: "#d95926",   # naranja  (Moto)
    5: "#199e70",   # turquesa (Bus)
    7: "#9085e9",   # violeta  (Camion)
}

# ---------------------------------------------------------------------------
# 1.5 Tracker (ByteTrack)
# ---------------------------------------------------------------------------
# Punto del cuadro que representa la posicion del vehiculo en el suelo.
# BOTTOM_CENTER (centro del borde inferior) toca el pavimento, por lo que
# es mas estable que el centro del cuadro cuando la camara esta inclinada.
ANCLA_VEHICULO: str = "BOTTOM_CENTER"
TRACK_BUFFER_FRAMES: int = 30        # frames (a 30 FPS) que se recuerda un ID perdido
UMBRAL_ACTIVACION_TRACK: float = 0.4  # confianza minima para crear un track nuevo
UMBRAL_ALTA_CONFIANZA: float = 0.5   # separa detecciones "fuertes" de "debiles" (ByteTrack)
UMBRAL_IOU_ASOCIACION: float = 0.1   # IoU minimo para emparejar deteccion <-> track
FRAMES_CONSECUTIVOS_MIN: int = 3     # apariciones seguidas para confirmar un ID

# ---------------------------------------------------------------------------
# 1.6 Alertas (reglas de negocio para el cliente)
# ---------------------------------------------------------------------------
# ALERTA "EXCESO_VELOCIDAD": se registra en la tabla `alertas` cuando la velocidad
# medida de un vehiculo supera este limite (ajustalo al limite legal de la via).
LIMITE_VELOCIDAD_KMH: float = 60.0

# ALERTA "TRAFICO_DETENIDO": hay al menos N vehiculos en la ROI y casi nada de
# movimiento dentro de ellos de forma sostenida (posible congestion o accidente).
DETENIDO_MIN_VEHICULOS: int = 3          # vehiculos minimos dentro de la ROI
DETENIDO_RATIO_MAX: float = 0.12         # fraccion de pixeles de los vehiculos en movimiento por debajo de la cual "no se mueven"
DETENIDO_SEGUNDOS: float = 4.0           # cuanto debe sostenerse la condicion para alertar
SALIDA_DETENIDO_SEGUNDOS: float = 2.0    # cuanto debe dejar de cumplirse para dar el episodio por terminado
CALENTAMIENTO_SEGUNDOS: float = 3.0      # al inicio el modelo de fondo aun no es fiable: no se alerta

# Cada cuantos segundos se guarda una lectura del estado de la via (tabla `lecturas_trafico`).
INTERVALO_LECTURA_S: float = 5.0

# ---------------------------------------------------------------------------
# 1.7 Analisis de movimiento (resta de fondo + umbral + morfologia)
# ---------------------------------------------------------------------------
MOV_ESCALA: float = 0.25               # se procesa el frame reducido a esta fraccion (mas rapido)
MOV_ALFA_FONDO: float = 0.02           # peso del frame nuevo en el promedio movil del fondo (0..1)
MOV_UMBRAL_DIFERENCIA: int = 25        # diferencia de gris (0-255) a partir de la cual un pixel "cambio"
MOV_KERNEL_APERTURA: int = 3           # tamano (impar) del elemento estructurante que elimina ruido
MOV_KERNEL_CIERRE: int = 7             # tamano (impar) del elemento estructurante que rellena huecos

# ---------------------------------------------------------------------------
# 1.8 Visualizacion
# ---------------------------------------------------------------------------
MOSTRAR_VENTANA: bool = False   # True = abre ventana en vivo (tecla 'q' para salir)
DIBUJAR_ESTELA: bool = True     # dibuja la trayectoria reciente de cada vehiculo
LARGO_ESTELA: int = 40          # numero de frames de la estela


# =============================================================================
# PARTE 2 - ESTRUCTURAS TIPADAS (no es necesario modificar)
# =============================================================================

class ConfigError(ValueError):
    """Se lanza cuando algun valor de configuracion es invalido."""


def _resolver_ruta(ruta: str) -> Path:
    """Convierte una ruta relativa al proyecto en una ruta absoluta."""
    p = Path(ruta)
    return p if p.is_absolute() else RAIZ_PROYECTO / p


@dataclass(frozen=True)
class IOConfig:
    """Rutas de video, base de datos y datos de la camara."""
    video_entrada: Path
    video_salida: Path
    db_ruta: Path
    camara: str
    fecha_inicio: Optional[datetime]    # None = hora actual al iniciar la ejecucion


@dataclass(frozen=True)
class DetectorConfig:
    """Parametros del detector YOLOv8."""
    modelo: Path
    confianza: float
    iou_nms: float
    tamano_imagen: int
    dispositivo: Optional[str]
    clases: Dict[int, str]


@dataclass(frozen=True)
class TrackerConfig:
    """Parametros de ByteTrack y del punto de anclaje."""
    ancla: str
    track_buffer: int
    umbral_activacion: float
    umbral_alta_confianza: float
    umbral_iou: float
    frames_consecutivos: int


@dataclass(frozen=True)
class CounterConfig:
    """Linea virtual de conteo."""
    linea: Tuple[Point, Point]
    etiqueta_a: str
    etiqueta_b: str


@dataclass(frozen=True)
class SpeedConfig:
    """ROI de velocidad: dos lineas y la distancia real entre ellas."""
    linea_a: Tuple[Point, Point]
    linea_b: Tuple[Point, Point]
    distancia_metros: float
    velocidad_min_kmh: float
    velocidad_max_kmh: float


@dataclass(frozen=True)
class AlertasConfig:
    """Umbrales de las alertas y frecuencia de las lecturas."""
    limite_velocidad_kmh: float
    detenido_min_vehiculos: int
    detenido_ratio_max: float
    detenido_segundos: float
    salida_segundos: float
    calentamiento_s: float
    intervalo_lectura_s: float


@dataclass(frozen=True)
class MovimientoConfig:
    """Parametros del analisis de movimiento (fondo, umbral, morfologia)."""
    escala: float
    alfa_fondo: float
    umbral_diferencia: int
    kernel_apertura: int
    kernel_cierre: int


@dataclass(frozen=True)
class VisualConfig:
    """Opciones de dibujo."""
    mostrar_ventana: bool
    dibujar_estela: bool
    largo_estela: int
    colores_clase: Dict[int, str]


@dataclass(frozen=True)
class AppConfig:
    """Configuracion completa de la aplicacion (agrupa todas las secciones)."""
    io: IOConfig
    detector: DetectorConfig
    tracker: TrackerConfig
    counter: CounterConfig
    speed: SpeedConfig
    alertas: AlertasConfig
    movimiento: MovimientoConfig
    visual: VisualConfig

    def validate(self) -> None:
        """
        Verifica la coherencia de los valores. Falla rapido (fail-fast) con un
        mensaje claro, en lugar de producir resultados absurdos horas despues.
        """
        # --- Base de datos --------------------------------------------------
        if not self.io.camara.strip():
            raise ConfigError("CAMARA no puede estar vacia.")

        # --- Detector -------------------------------------------------------
        if not 0.0 < self.detector.confianza <= 1.0:
            raise ConfigError("CONFIANZA_MINIMA debe estar en el rango (0, 1].")
        if not 0.0 < self.detector.iou_nms <= 1.0:
            raise ConfigError("IOU_NMS debe estar en el rango (0, 1].")
        if not self.detector.clases:
            raise ConfigError("CLASES_VEHICULO no puede estar vacio.")
        if self.detector.tamano_imagen < 32:
            raise ConfigError("TAMANO_IMAGEN debe ser >= 32.")

        # --- Tracker --------------------------------------------------------
        anclas_validas = {"CENTER", "BOTTOM_CENTER", "TOP_CENTER", "CENTER_LEFT",
                          "CENTER_RIGHT", "BOTTOM_LEFT", "BOTTOM_RIGHT",
                          "TOP_LEFT", "TOP_RIGHT"}
        if self.tracker.ancla not in anclas_validas:
            raise ConfigError(f"ANCLA_VEHICULO invalida. Opciones: {sorted(anclas_validas)}")

        # --- Linea de conteo ------------------------------------------------
        self._validar_linea(self.counter.linea, "LINEA_CONTEO")

        # --- Zona de velocidad ---------------------------------------------
        self._validar_linea(self.speed.linea_a, "LINEA_VELOCIDAD_A")
        self._validar_linea(self.speed.linea_b, "LINEA_VELOCIDAD_B")
        if self.speed.distancia_metros <= 0:
            raise ConfigError("DISTANCIA_REAL_METROS debe ser mayor que 0.")
        if self.speed.velocidad_min_kmh >= self.speed.velocidad_max_kmh:
            raise ConfigError("VELOCIDAD_MIN_KMH debe ser menor que VELOCIDAD_MAX_KMH.")
        # Si las lineas A y B se cortaran, "antes" y "despues" perderian sentido.
        if segment_intersection(*self.speed.linea_a, *self.speed.linea_b) is not None:
            raise ConfigError("LINEA_VELOCIDAD_A y LINEA_VELOCIDAD_B no deben cruzarse entre si.")

        # --- Alertas ---------------------------------------------------------
        a = self.alertas
        if a.limite_velocidad_kmh <= 0:
            raise ConfigError("LIMITE_VELOCIDAD_KMH debe ser mayor que 0.")
        if a.detenido_min_vehiculos < 1:
            raise ConfigError("DETENIDO_MIN_VEHICULOS debe ser >= 1.")
        if not 0.0 < a.detenido_ratio_max <= 1.0:
            raise ConfigError("DETENIDO_RATIO_MAX debe estar en el rango (0, 1].")
        if min(a.detenido_segundos, a.salida_segundos, a.intervalo_lectura_s) <= 0 or a.calentamiento_s < 0:
            raise ConfigError("Los tiempos de las alertas deben ser positivos (CALENTAMIENTO_SEGUNDOS puede ser 0).")

        # --- Movimiento ------------------------------------------------------
        m = self.movimiento
        if not 0.0 < m.escala <= 1.0:
            raise ConfigError("MOV_ESCALA debe estar en el rango (0, 1].")
        if not 0.0 < m.alfa_fondo <= 1.0:
            raise ConfigError("MOV_ALFA_FONDO debe estar en el rango (0, 1].")
        if not 0 <= m.umbral_diferencia <= 255:
            raise ConfigError("MOV_UMBRAL_DIFERENCIA debe estar entre 0 y 255.")
        for nombre, k in (("MOV_KERNEL_APERTURA", m.kernel_apertura), ("MOV_KERNEL_CIERRE", m.kernel_cierre)):
            if k < 1 or k % 2 == 0:
                raise ConfigError(f"{nombre} debe ser un entero impar >= 1.")

    @staticmethod
    def _validar_linea(linea: Tuple[Point, Point], nombre: str) -> None:
        """Una linea valida tiene dos puntos distintos (longitud > 0)."""
        if len(linea) != 2 or euclidean_distance(linea[0], linea[1]) < 1.0:
            raise ConfigError(f"{nombre} debe tener dos puntos (x, y) distintos.")


def _parsear_fecha(texto: Optional[str]) -> Optional[datetime]:
    """Convierte 'AAAA-MM-DD HH:MM:SS' en datetime (None se conserva como None)."""
    if texto is None:
        return None
    try:
        return datetime.fromisoformat(texto)
    except ValueError as exc:
        raise ConfigError(
            f"FECHA_INICIO_VIDEO='{texto}' no es valida. Usa el formato 'AAAA-MM-DD HH:MM:SS'."
        ) from exc


def cargar_configuracion() -> AppConfig:
    """Construye el `AppConfig` a partir de las constantes de la PARTE 1."""
    config = AppConfig(
        io=IOConfig(
            video_entrada=_resolver_ruta(VIDEO_ENTRADA),
            video_salida=_resolver_ruta(VIDEO_SALIDA),
            db_ruta=_resolver_ruta(DB_RUTA),
            camara=CAMARA,
            fecha_inicio=_parsear_fecha(FECHA_INICIO_VIDEO),
        ),
        detector=DetectorConfig(
            modelo=_resolver_ruta(MODELO),
            confianza=CONFIANZA_MINIMA,
            iou_nms=IOU_NMS,
            tamano_imagen=TAMANO_IMAGEN,
            dispositivo=DISPOSITIVO,
            clases=dict(CLASES_VEHICULO),
        ),
        tracker=TrackerConfig(
            ancla=ANCLA_VEHICULO,
            track_buffer=TRACK_BUFFER_FRAMES,
            umbral_activacion=UMBRAL_ACTIVACION_TRACK,
            umbral_alta_confianza=UMBRAL_ALTA_CONFIANZA,
            umbral_iou=UMBRAL_IOU_ASOCIACION,
            frames_consecutivos=FRAMES_CONSECUTIVOS_MIN,
        ),
        counter=CounterConfig(
            linea=LINEA_CONTEO,
            etiqueta_a=ETIQUETA_SENTIDO_A,
            etiqueta_b=ETIQUETA_SENTIDO_B,
        ),
        speed=SpeedConfig(
            linea_a=LINEA_VELOCIDAD_A,
            linea_b=LINEA_VELOCIDAD_B,
            distancia_metros=DISTANCIA_REAL_METROS,
            velocidad_min_kmh=VELOCIDAD_MIN_KMH,
            velocidad_max_kmh=VELOCIDAD_MAX_KMH,
        ),
        alertas=AlertasConfig(
            limite_velocidad_kmh=LIMITE_VELOCIDAD_KMH,
            detenido_min_vehiculos=DETENIDO_MIN_VEHICULOS,
            detenido_ratio_max=DETENIDO_RATIO_MAX,
            detenido_segundos=DETENIDO_SEGUNDOS,
            salida_segundos=SALIDA_DETENIDO_SEGUNDOS,
            calentamiento_s=CALENTAMIENTO_SEGUNDOS,
            intervalo_lectura_s=INTERVALO_LECTURA_S,
        ),
        movimiento=MovimientoConfig(
            escala=MOV_ESCALA,
            alfa_fondo=MOV_ALFA_FONDO,
            umbral_diferencia=MOV_UMBRAL_DIFERENCIA,
            kernel_apertura=MOV_KERNEL_APERTURA,
            kernel_cierre=MOV_KERNEL_CIERRE,
        ),
        visual=VisualConfig(
            mostrar_ventana=MOSTRAR_VENTANA,
            dibujar_estela=DIBUJAR_ESTELA,
            largo_estela=LARGO_ESTELA,
            colores_clase=dict(COLORES_CLASE),
        ),
    )
    config.validate()
    return config
