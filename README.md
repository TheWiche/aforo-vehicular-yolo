# Aforo Vehicular y Estimación de Velocidad (YOLOv8 + ByteTrack + SQLite)

Detecta **auto, moto, bus y camión** en video, les asigna un ID único, los **cuenta** al cruzar una
línea virtual, estima su **velocidad (km/h)**, vigila el **estado del tráfico** y genera **alertas**
(exceso de velocidad y tráfico detenido). Todo se guarda en una base de datos **SQLite** y se
consulta en un dashboard Streamlit.

Informe y documentación en [`docs/`](docs/): contexto del cliente, datos, técnicas del curso,
modelo de datos, métricas, casos de falla y guía de sustentación (ver [Documentación](#documentación)).

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
```

> Probado con Python 3.12. Para usar GPU NVIDIA instala antes la build CUDA de PyTorch
> (ver pytorch.org) y luego el resto de `requirements.txt`.

## Menú interactivo (la forma más fácil de probar)

```bash
python menu.py
```

Menú en la terminal que **revisa primero qué tienes y qué te falta** (dependencias, pesos, videos,
calibración, base de datos, verdad de terreno) y, antes de cada acción, comprueba sus requisitos y
ofrece resolverlos (instalar dependencias, descargar videos, calibrar). Permite:

- **Prueba rápida guiada:** descarga `autopista_1`, aplica su calibración probada, procesa y abre el dashboard.
- **Configuración (tipo CRUD sobre `config.py`):** ver y editar cada parámetro con validación de tipo y
  rango; si un cambio dejaría la configuración inválida, se revierte solo.
- **Videos:** descargar, elegir el video activo y calibrar las líneas haciendo clic sobre un frame.
- **Procesar, dashboard, base de datos** (resumen, cruces, alertas, borrar una cámara), **evaluación** y
  **pruebas unitarias**.

## Ejecutar (flujo completo, sin menú)

```bash
python descargar_videos.py                                                        # 1. videos de prueba -> videos/
python main.py --video videos/autopista_1.mp4 --camara autopista_1 --reemplazar   # 2. procesa y guarda en la BD
streamlit run dashboard.py                                                        # 3. dashboard (lee la BD con SELECT)
```

Con tu propio video: cópialo a `videos/entrada.mp4` (o cambia `VIDEO_ENTRADA` en `config.py`) y
ejecuta `python main.py`. **Antes de interpretar velocidades hay que calibrar** las líneas y la
distancia real (siguiente sección): con valores de ejemplo los resultados no tienen sentido.

Opciones de `main.py` (sobrescriben `config.py` solo en esa ejecución): `--video`, `--salida`,
`--modelo`, `--dispositivo`, `--mostrar`, `--camara NOMBRE`, `--reemplazar`
(borra de la BD los datos previos de esa cámara para repetir una prueba sin duplicar filas).

Resultados: `output/salida.mp4` (video anotado) y las tablas de `db/database.db`. Los pesos de
YOLO se descargan solos en `models/` la primera vez.

## Calibrar para tu video → `config.py` (PARTE 1)

| Qué | Constante |
|---|---|
| Ruta del video | `VIDEO_ENTRADA` |
| Base de datos, nombre de cámara, hora de inicio del video | `DB_RUTA`, `CAMARA`, `FECHA_INICIO_VIDEO` |
| Línea de conteo (2 puntos `(x, y)` en píxeles) | `LINEA_CONTEO` |
| ROI de velocidad (línea de entrada y de salida) | `LINEA_VELOCIDAD_A`, `LINEA_VELOCIDAD_B` |
| **Distancia real en metros entre A y B (medirla en el sitio)** | `DISTANCIA_REAL_METROS` |
| Límite de velocidad que dispara la alerta | `LIMITE_VELOCIDAD_KMH` |
| Umbrales de "tráfico detenido" y del análisis de movimiento | `DETENIDO_*`, `MOV_*` |

**Coordenadas:** `python seleccionar_puntos.py --video videos/autopista_1.mp4` → haz clic sobre el
frame (2 puntos por línea: conteo, A, B) y pega lo que imprime. Deben corresponder a la
**resolución real** del video (`autopista_1` mide 3840x2160; `autopista_2` y `carretera_3`,
1920x1080). Coloca la línea de conteo **dentro** del tramo A–B (o a su salida).

## Base de datos

`db.py` crea `db/database.db` y las tablas al iniciar (si no existen). Un `INSERT` en `cruces`
ocurre en el instante en que el vehículo cruza la línea de conteo:

| Campo de `cruces` | Tipo | Contenido |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | autonumérico |
| `track_id` | INTEGER | ID único que asignó ByteTrack al vehículo |
| `tipo` | TEXT | Auto / Moto / Bus / Camion |
| `momento` | TIMESTAMP | hora real del cruce = `FECHA_INICIO_VIDEO` + segundos del video |
| `velocidad_kmh` | REAL | velocidad medida en la ROI (`NULL` si no se completó) |
| `camara` | TEXT | nombre de la cámara / fuente (`CAMARA` o `--camara`) |

Otras tablas: `alertas`, `lecturas_trafico`, `ejecuciones`, `metricas` y la vista
`v_aforo_por_minuto`. Modelo ER, DDL y diccionario: [`docs/MODELO_DATOS.md`](docs/MODELO_DATOS.md).

Consulta rápida desde la terminal:
`python -c "import sqlite3; print(sqlite3.connect('db/database.db').execute('SELECT tipo, COUNT(*), AVG(velocidad_kmh) FROM cruces GROUP BY tipo').fetchall())"`.

## Evaluación (métricas)

```bash
python anotar_verdad_terreno.py --video videos/mi_video.mp4 --camara mi_camara    # 1. marcar cruces a mano
python main.py --video videos/mi_video.mp4 --camara mi_camara --reemplazar         # 2. correr el sistema
python evaluar.py --camara mi_camara --informe                                     # 3. precisión, recall, F1, MAE...
```

Detalle y definiciones en [`docs/METRICAS.md`](docs/METRICAS.md). La verdad de terreno se guarda
en `evaluacion/<camara>.json`. Para auditar solo el tracking (sin verdad de terreno):
`python verificar_tracking.py --video videos/carretera_3.mp4 --max-frames 300`.

## Pruebas unitarias

```bash
python -m unittest discover -s tests -v
```

## Documentación

| Documento | Contenido |
|---|---|
| [`docs/INFORME.md`](docs/INFORME.md) | Borrador del informe (enlaza todo lo demás) |
| [`docs/CONTEXTO_CLIENTE.md`](docs/CONTEXTO_CLIENTE.md) | Cliente, problema de negocio e indicadores de éxito |
| [`docs/DATOS.md`](docs/DATOS.md) | Datos propios y públicos (citas, licencias), protocolo de grabación |
| [`docs/TECNICAS.md`](docs/TECNICAS.md) | Técnicas del curso usadas y dónde |
| [`docs/MODELO_DATOS.md`](docs/MODELO_DATOS.md) | Modelo relacional, DDL, diccionario |
| [`docs/METRICAS.md`](docs/METRICAS.md) | Cómo se miden precisión, recall, error de velocidad |
| [`docs/CASOS_DE_FALLA.md`](docs/CASOS_DE_FALLA.md) | 5 casos de falla con evidencia |
| [`docs/GUIA_SUSTENTACION.md`](docs/GUIA_SUSTENTACION.md) | Qué hace cada módulo y preguntas probables |

## Estructura

```
config.py              Configuración centralizada (rutas, BD, líneas, metros, umbrales)
main.py                Punto de entrada y argumentos de consola
pipeline.py            Orquesta detección → tracking → conteo/velocidad/movimiento → BD → video
db.py                  SQLite: tablas, INSERT/UPDATE
detector.py            YOLOv8 filtrado a vehículos
tracker.py             ByteTrack + votación de clase + historial de posiciones
line_counter.py        Aforo por intersección de segmentos
speed_estimator.py     Velocidad = distancia / tiempo (frames ÷ FPS)
movimiento.py          Resta de fondo + umbralización + morfología (movimiento en la ROI)
alertas.py             Reglas: exceso de velocidad y tráfico detenido (con histéresis)
visualizer.py          Cajas, etiquetas, estelas, ROI y panel de conteo
geometry.py            Producto cruz, intersección de segmentos, polígono de la ROI
menu.py                Menú interactivo: diagnóstico, configuración, videos, procesar, BD, evaluación
dashboard.py           Panel Streamlit (modo oscuro) con consultas SQL
evaluar.py             Métricas contra verdad de terreno
anotar_verdad_terreno.py  Herramienta para marcar cruces a mano
verificar_tracking.py  Auditoría de unicidad y estabilidad de IDs
descargar_videos.py    Descarga videos de tráfico de prueba a videos/
capturar_fallas.py, generar_evidencia_fallas.py   Evidencia visual de casos de falla
seleccionar_puntos.py  Obtiene coordenadas con el mouse
tests/                 Pruebas unitarias
docs/                  Informe y documentación
```

## Notas

- El **Sentido A** (flecha "A" en el video) es el de los vehículos que cruzan la línea de derecha
  a izquierda según la orientación `punto1 → punto2` tal como se ve en pantalla. Los sentidos se
  cuentan en el panel del video pero no se guardan en la BD.
- La velocidad es **media** en el tramo A–B, no instantánea; depende directamente de la distancia
  medida (ver caso 5 en [`docs/CASOS_DE_FALLA.md`](docs/CASOS_DE_FALLA.md)).
- Los videos, pesos y la base de datos no se versionan (`.gitignore`); se regeneran con los
  comandos de arriba.
