# Aforo Vehicular y Estimación de Velocidad (YOLOv8 + ByteTrack + SQLite)

Detecta **auto, moto, bus y camión** en video, les asigna un ID único, los **cuenta** al cruzar una
línea virtual, estima su **velocidad (km/h)**, vigila el **estado del tráfico** y genera **alertas**
(exceso de velocidad y tráfico detenido). Todo se guarda en **SQLite** y un **dashboard web propio**
(API FastAPI + interfaz HTML/CSS/JS) lo consulta con SQL.

Informe y documentación en [`docs/`](docs/) (contexto del cliente, datos, técnicas del curso,
modelo de datos, métricas, casos de falla y guía de sustentación).

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt   # instala las dependencias y el paquete `aforo` (modo editable)
```

> Probado con Python 3.12. Para usar GPU NVIDIA instala antes la build CUDA de PyTorch
> (ver pytorch.org) y luego el resto.

## Uso rápido: un solo archivo

```bash
python iniciar.py
```

`iniciar.py` revisa que todo esté listo y, solo entonces, abre el panel web en <http://localhost:8501>:

1. comprueba Python y crea las carpetas de datos;
2. comprueba las dependencias y, si faltan, **ofrece instalarlas** (`--si` responde "sí" a todo);
3. detecta tu **GPU NVIDIA** y, si PyTorch está instalado sin CUDA, **instala la versión con CUDA** automáticamente
   (analizar en CPU es muchas veces más lento, así que con tarjeta NVIDIA no se continúa sin GPU; `--permitir-cpu` lo evita);
4. valida `config.py`;
5. levanta el panel y abre el navegador.

Todo el trabajo se hace desde el panel, en este orden (el menú lateral lo sigue):

| Sección | Qué haces |
|---|---|
| **Videos** | Ves los videos con miniatura y estado ("calibrado · 181 cruces"). Agregas uno pegando su ruta (sin copiarlo) o subiéndolo. |
| **Calibrar** | Eliges un cuadro con la barra de tiempo y **arrastras las tres líneas** (conteo, A y B) sobre la imagen; o escribes sus coordenadas. Indicas los metros entre A y B (hay una regla de referencia para calcularlos), el límite de velocidad y el nombre de la cámara. Valida en vivo y explica cómo se obtiene la velocidad con tus números. |
| **Procesar** | Eliges el modo (en vivo a velocidad normal, todos los cuadros, o rápido) y pulsas Iniciar. Ves el video anotado **en vivo**, el avance, los vehículos contados y la velocidad de análisis. Puedes detenerlo. |
| **Resumen** y **Vehículos** | Los resultados: aforo, velocidades, excesos y, para cada vehículo, el cuadro del video en que cruzó. |
| **Sistema** | Estado del entorno: Python, paquetes, GPU y modelos. |

El análisis corre en un **proceso aparte**: cerrar la pestaña no lo detiene, y si falla el panel sigue vivo. La
calibración de cada video se guarda en `datos/calibraciones.json` (la misma que usa el menú de terminal).

Opciones del lanzador: `--puerto 8501`, `--no-abrir`, `--si`, `--solo-revisar` (revisa y sale), `--permitir-cpu`.

## Uso por terminal

Todo cuelga también de un solo comando, `python -m aforo`:

```bash
python -m aforo                       # menú interactivo (revisa qué tienes y qué te falta)
python -m aforo --help                # lista de comandos
```

| Comando | Qué hace |
|---|---|
| `python -m aforo` | **Menú interactivo**: diagnóstico, configuración, videos, procesar, base de datos, evaluación |
| `python -m aforo descargar` | Descarga videos de tráfico de prueba a `datos/videos/` |
| `python -m aforo calibrar` | Obtiene coordenadas de las líneas haciendo clic en un frame |
| `python -m aforo procesar` | Procesa un video → detección, conteo, velocidad, alertas → base de datos |
| `python -m aforo dashboard` | Abre el dashboard web (sin revisar el entorno; para eso usa `python iniciar.py`) |
| `python -m aforo anotar` / `evaluar` | Verdad de terreno a mano y métricas (precisión, recall, F1, MAE) |
| `python -m aforo auditar` | Audita la unicidad y estabilidad de los IDs del tracker |

Flujo completo sin menú:

```bash
python -m aforo descargar
python -m aforo procesar --video datos/videos/autopista_1.mp4 --camara autopista_1 --reemplazar
python -m aforo dashboard
```

Opciones de `procesar` (sobrescriben `config.py` solo en esa ejecución): `--video`, `--salida`, `--modelo`,
`--imgsz`, `--sin-video`, `--dispositivo`, `--mostrar` (ventana en vivo), `--camara NOMBRE`, `--reemplazar`
(borra de la BD los datos previos de esa cámara para repetir una prueba sin duplicar filas), `--perfil` (usa la
calibración guardada del video en `datos/calibraciones.json`), `--db RUTA` y `--tiempo-real`.
Las opciones `--estado`, `--cuadro-vivo` y `--parar` son el canal con el panel web (progreso, video en vivo y parada).

## Estructura del proyecto

```
.
├── iniciar.py                  Lanzador único: revisa el entorno y abre el panel web
├── src/aforo/                  Paquete Python con toda la lógica del sistema
│   ├── config.py               Configuración centralizada (rutas, líneas, metros, umbrales)  ← lo que editas
│   ├── cli.py · pipeline.py    Línea de comandos de `procesar` y orquestación del flujo
│   ├── perfiles.py · reporte.py  Calibración por video (JSON) y canal de progreso hacia la web
│   ├── menu.py · __main__.py   Menú interactivo y comando único `python -m aforo`
│   ├── vision/                 detector (YOLOv8) · tracker (ByteTrack) · movimiento · visualizer
│   ├── analitica/              geometry · line_counter · speed_estimator · alertas (reglas de negocio)
│   ├── persistencia/db.py      SQLite: tablas, INSERT/UPDATE
│   ├── evaluacion/             evaluar · anotar_verdad_terreno · verificar_tracking
│   └── herramientas/           descargar_videos · seleccionar_puntos · capturar_fallas · generar_evidencia_fallas
├── dashboard/                  Dashboard web, autocontenido
│   ├── backend/                API FastAPI: consultas.py (SQL) · panel.py (JSON del resumen) · camara.py (cuadros de evidencia) ·
│   │                           videos.py · proceso.py (lanza y vigila el análisis) · sistema.py · app.py
│   └── frontend/               index.html · css/ (tokens, base, marco, componentes, gráficos, movimiento) · js/ (vistas, componentes y gráficos SVG)
├── datos/                      Datos de ejecución (no se versionan, salvo la verdad de terreno)
│   ├── videos/  modelos/  db/  salidas/        videos, pesos YOLO, base de datos, video anotado
│   └── evaluacion/             verdad de terreno anotada a mano (JSON, sí se versiona)
├── tests/                      Pruebas unitarias
├── docs/                       Informe y documentación
├── requirements.txt · pyproject.toml
└── README.md
```

## Calibrar para tu video → `src/aforo/config.py` (PARTE 1)

| Qué | Constante |
|---|---|
| Ruta del video | `VIDEO_ENTRADA` |
| Base de datos, nombre de cámara, hora de inicio del video | `DB_RUTA`, `CAMARA`, `FECHA_INICIO_VIDEO` |
| Línea de conteo (2 puntos `(x, y)` en píxeles) | `LINEA_CONTEO` |
| ROI de velocidad (línea de entrada y de salida) | `LINEA_VELOCIDAD_A`, `LINEA_VELOCIDAD_B` |
| **Distancia real en metros entre A y B (medirla en el sitio)** | `DISTANCIA_REAL_METROS` |
| Límite de velocidad que dispara la alerta | `LIMITE_VELOCIDAD_KMH` |
| Umbrales de "tráfico detenido" y del análisis de movimiento | `DETENIDO_*`, `MOV_*` |

Más fácil: el **menú** (`python -m aforo` → Configuración / Videos → Calibrar) edita estos valores con
validación. Las coordenadas deben corresponder a la **resolución real** del video (`autopista_1` mide
3840x2160; `autopista_2` y `carretera_3`, 1920x1080). Coloca la línea de conteo **dentro** del tramo A–B.

## Base de datos

`aforo.persistencia.db` crea `datos/db/database.db` y las tablas al iniciar. Un `INSERT` en `cruces` ocurre
en el instante en que el vehículo cruza la línea de conteo:

| Campo de `cruces` | Tipo | Contenido |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | autonumérico |
| `track_id` | INTEGER | ID único que asignó ByteTrack al vehículo |
| `tipo` | TEXT | Auto / Moto / Bus / Camion |
| `momento` | TIMESTAMP | hora real del cruce = `FECHA_INICIO_VIDEO` + segundos del video |
| `velocidad_kmh` | REAL | velocidad medida en la ROI (`NULL` si no se completó) |
| `camara` | TEXT | nombre de la cámara / fuente |

Otras tablas: `alertas`, `lecturas_trafico`, `ejecuciones`, `metricas` y la vista `v_aforo_por_minuto`.
Modelo ER, DDL y diccionario: [`docs/MODELO_DATOS.md`](docs/MODELO_DATOS.md).

## Dashboard

`python iniciar.py` (o `python -m aforo dashboard`) levanta un servidor local (FastAPI + Uvicorn) que sirve la
interfaz y la API. Los resultados se leen de la base en **solo lectura** (`PRAGMA query_only`) y las agregaciones
se calculan con SQL (`GROUP BY`); lo único que el servidor escribe es la calibración y los videos subidos, y el
análisis (que sí escribe en la base) corre en un proceso aparte. El servidor escucha solo en `127.0.0.1`.

| Ruta | Qué devuelve |
|---|---|
| `/api/panel?camaras=a&percentil=85` | Resumen de una cámara: indicadores, puntos de velocidad, aforo por minuto, estado de la vía, calibración |
| `/api/cruces?camara=a&filtro=excesos` | Registro de vehículos paginado (filtros: `todos`, `excesos`, `sin_medir`; `tipo`, `track`, `orden`) |
| `/api/fotograma?camara=a&t=<momento>` | El cuadro del video en el instante del cruce (JPEG), leído con OpenCV de `datos/videos/` |
| `/api/videos` · `/api/videos/cuadro` · `/api/videos/agregar` · `/api/videos/subir` | Lista de videos, cuadros para el calibrador, alta por ruta o por subida |
| `/api/calibracion` (GET/PUT) | Perfil de calibración de un video: lee, valida y guarda |
| `/api/proceso` · `/iniciar` · `/detener` · `/video` | Control y seguimiento del análisis; `/video` es el flujo MJPEG en vivo |
| `/api/sistema` | Diagnóstico del entorno (solo lectura) |

La interfaz tiene dos vistas:

- **Resumen**: el hallazgo en una frase (cuántos vehículos superaron el límite), cuatro indicadores (aforo,
  velocidad media, percentil 85 o V85, porcentaje sobre el límite), la velocidad de cada vehículo contra el
  límite, el aforo por minuto con el estado de la vía, la distribución de velocidades y el desglose por tipo.
- **Vehículos**: el registro completo con filtros y búsqueda por ID. Al elegir un vehículo se ve **el cuadro
  del video en que cruzó la línea de conteo**, con las líneas A, B y de conteo dibujadas encima, y cómo se
  obtuvo su velocidad (distancia del tramo ÷ tiempo).

El límite de velocidad y las líneas de cada cámara salen de `datos/calibraciones.json`. Con el interruptor
"Actualizar cada 5 s" el panel se refresca mientras `procesar` sigue escribiendo. El diseño sigue el estilo
"hoja enmarcada" (tipografía IBM Plex Sans, color solo en los datos) y las transiciones de transitions.dev.

## Evaluación (métricas)

```bash
python -m aforo anotar --video datos/videos/mi_video.mp4 --camara mi_camara      # marcar cruces a mano
python -m aforo procesar --video datos/videos/mi_video.mp4 --camara mi_camara --reemplazar
python -m aforo evaluar --camara mi_camara --informe                              # precisión, recall, F1, MAE...
```

Detalle en [`docs/METRICAS.md`](docs/METRICAS.md). La verdad de terreno queda en `datos/evaluacion/<camara>.json`.

## Pruebas unitarias

```bash
python -m unittest discover -s tests -v
```

## Velocidad de procesamiento

En CPU, con YOLOv8s a 960 px y un video 4K el sistema procesa ~2.8 cuadros/s (medido), por eso la ventana
en vivo se ve a tirones; el cuello de botella es la red neuronal. Para ir más rápido:
`python -m aforo procesar --mostrar --sin-video --imgsz 640 --modelo datos/modelos/yolov8n.pt` (~8 cuadros/s
en el mismo video 4K), o usa una GPU NVIDIA, o un video de 1080p o menos. El menú ofrece este "modo rápido".

**Ver el video a velocidad normal:** `python -m aforo procesar --tiempo-real` reproduce el video con el reloj
(como un reproductor) y, si el modelo no alcanza, salta los cuadros que ya pasaron. Las horas y velocidades
siguen siendo correctas porque cada cuadro conserva su número real. Medido sobre 145 s de
`Prueba1_optimizado.mp4` contra el modo normal:

| Equipo | Cuadros analizados | Vehículos contados | Diferencia de velocidad |
|---|---|---|---|
| CPU, `yolov8n` a 640 px | 1 de cada ~5 | 7 de 14 | 2 mediciones de 13 (±0,2 km/h) |
| RTX 2070 SUPER, `yolov8s` a 960 px | 3 de cada 4 | 14 de 14 | 14 de 14, dentro de ±0,5 km/h |

Sin GPU sirve solo para demostrar; con GPU es fiable. El menú guarda la corrida en vivo en una cámara aparte
(`<cámara>_vivo`) para no mezclarla con los datos completos.

### Usar la GPU NVIDIA

`pip install torch` en Windows instala la versión **solo-CPU**, y YOLO corre varias veces más lento sin avisar.
`python iniciar.py` lo detecta y lo corrige solo (también el diagnóstico del menú, opción 9, y la sección Sistema del
panel). Para hacerlo a mano (driver con CUDA 13 o superior; con CUDA 12.6 a 12.9 cambia `cu130` por `cu126`):

```bash
pip install --force-reinstall --no-deps torch==2.14.1+cu130 torchvision==0.29.1+cu130 --index-url https://download.pytorch.org/whl/cu130
python -c "import torch; print(torch.cuda.is_available())"     # debe imprimir True
```

Con la GPU, `yolov8s` a 960 px procesa ~20 cuadros/s (en CPU, ~3). El límite pasa a ser el procesador
(decodificar el video, redimensionar y filtrar cajas); la media precisión (FP16) no mejoró la velocidad.

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

## Notas

- El **Sentido A** (flecha "A" en el video) es el de los vehículos que cruzan la línea de derecha a izquierda
  según la orientación `punto1 → punto2` tal como se ve en pantalla. Los sentidos se cuentan en el panel del
  video pero no se guardan en la BD.
- La velocidad es **media** en el tramo A–B, no instantánea; depende directamente de la distancia medida
  (ver caso 5 en [`docs/CASOS_DE_FALLA.md`](docs/CASOS_DE_FALLA.md)).
- Los videos, pesos y la base de datos no se versionan (`.gitignore`); se regeneran con los comandos de arriba.
