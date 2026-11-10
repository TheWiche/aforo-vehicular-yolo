# Datos: propios y públicos

## Estado actual

| Fuente | Tipo | Uso | Estado |
|---|---|---|---|
| Videos grabados por el equipo (`datos/videos/propios/`) | **Propios** | Calibración, verdad de terreno y métricas finales | **Pendiente de grabar** (ver protocolo abajo) |
| `autopista_1.mp4` | Público | Desarrollo y pruebas de regresión | Descargado con `descargar_videos.py` |
| `autopista_2.mp4` | Público | Prueba de estrés (tráfico denso) y casos de falla | Descargado con `descargar_videos.py` |
| `carretera_3.mp4` | Público | Tráfico moderado | Descargado con `descargar_videos.py` |

El requisito 2 exige que **al menos una parte de los datos sea propia**: los videos de
`datos/videos/propios/` deben grabarlos los integrantes. Hasta entonces, las métricas calculadas
sobre videos públicos son provisionales.

## Fuentes y citas

| Recurso | Cita / URL | Licencia / condiciones |
|---|---|---|
| `autopista_1.mp4`, `autopista_2.mp4` | Roboflow, *supervision – video examples*. <https://media.roboflow.com/supervision/video-examples/vehicles.mp4> y `vehicles-2.mp4` | Videos de ejemplo distribuidos con la librería `supervision` (MIT). El autor no especifica licencia propia para los videos: se usan solo con fines académicos y **no se redistribuyen** (excluidos de git). |
| `carretera_3.mp4` | Pexels, video nº 854671. <https://www.pexels.com/video/854671/> (archivo `854671-hd_1920_1080_25fps.mp4`) | Licencia Pexels (uso libre, sin atribución obligatoria; se cita por buena práctica). Consultar el autor en la página del video. |
| Pesos `yolov8s.pt` | Jocher, G., Chaurasia, A., Qiu, J. (2023). *Ultralytics YOLOv8*. <https://github.com/ultralytics/ultralytics> | AGPL-3.0 (código y pesos de Ultralytics). Entrenados en COCO. |
| Dataset COCO (entrenamiento de YOLOv8) | Lin, T.-Y. et al. (2014). *Microsoft COCO: Common Objects in Context*. ECCV. | CC BY 4.0 (anotaciones). |
| ByteTrack | Zhang, Y. et al. (2022). *ByteTrack: Multi-Object Tracking by Associating Every Detection Box*. ECCV. | Implementación vía paquete `trackers` de Roboflow. |

> Los videos públicos **no se suben al repositorio** (`.gitignore`) y se obtienen con
> `python -m aforo descargar`. Los pesos se descargan solos en `datos/modelos/`.

## Protocolo para grabar los videos propios

Objetivo: al menos **3 videos de 10–15 minutos** (idealmente en momentos distintos del día), de
modo que haya suficientes vehículos para contar y medir.

1. **Cámara fija** (trípode o soporte, sin movimiento) y encuadre **elevado y frontal o trasero**
   a la vía: desde un puente peatonal, un edificio o una loma. Resolución ≥ 1080p, 25–30 FPS,
   foco y exposición fijos. Evitar contraluz directo.
2. **Que se vea todo el ancho de la calzada** y un tramo recto de, idealmente, ≥ 20 m.
3. **Medir la distancia real** entre dos marcas de la vía (p. ej. dos líneas de cebra, dos postes
   o marcas de tiza) con cinta métrica o rueda medidora. Anotarla: es `DISTANCIA_REAL_METROS`.
   De este valor depende toda la precisión de la velocidad.
4. **Velocidad de referencia (para medir el error):** hacer **pasadas controladas** de un vehículo
   del equipo a velocidades conocidas (p. ej. 20, 30, 40, 50 km/h con el velocímetro verificado
   con GPS del celular) o cronometrar vehículos reales sobre la distancia medida
   (`v = d / t`). Registrar hora y velocidad de cada pasada.
5. **Guardar** los archivos en `datos/videos/propios/` con nombre descriptivo
   (`corredor_manana_01.mp4`). Anotar fecha, hora de inicio (se usa como `FECHA_INICIO_VIDEO`),
   clima y ubicación en una nota junto al video.
6. **Privacidad:** grabar en vía pública, sin enfocar rostros ni placas de cerca; no publicar los
   videos. Si el video se muestra en el informe, difuminar placas.
7. **Verdad de terreno:** con cada video correr
   `python -m aforo anotar --video datos/videos/propios/<video>.mp4 --camara <nombre>` y,
   si hay velocidades de referencia, agregarlas al JSON generado
   (`datos/evaluacion/<nombre>.json`). Luego `python -m aforo procesar ... --camara <nombre> --reemplazar` y
   `python -m aforo evaluar --camara <nombre>`.

## Datos que NO se usan para entrenar

No se entrena ni se ajusta (fine-tuning) ningún modelo con los videos del proyecto: YOLOv8 se usa
con los pesos preentrenados de COCO. Por eso **todos los videos del proyecto, propios o públicos,
son datos que el modelo no vio en el entrenamiento** (requisito 6).
