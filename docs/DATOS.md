# Datos: propios y públicos

## Estado actual

| Fuente | Tipo | Uso | Estado |
|---|---|---|---|
| `datos/videos/prueba.mp4` | **Propio (principal)** | Grabación real en vía local (1920×1080, 30 FPS, 31,793 frames ≈ 17 min 39 s). Calibrado (`DISTANCIA_REAL_METROS = 3.5`, límite `30 km/h`), procesado (`prueba`) y usado en la demo y análisis técnico | **Grabado, calibrado y procesado** (177 cruces, 171 con velocidad, 25.4 km/h promedio, 45 excesos) |
| `datos/videos/Prueba1_optimizado.mp4` | **Propio (exploratorio)** | Prueba previa en vía lateral (1080p, 30 FPS, 32,102 frames, `4.7 m`) | Procesado en BD como `prueba1` |
| `datos/evaluacion/prueba.json` | **Propio (GT)** | Verdad de terreno opcional anotada manualmente con `python -m aforo anotar` | Auditoría de tracking y comparación de modelos registradas en `METRICAS_RESULTADOS.md` |
| `autopista_1.mp4` | Público | Desarrollo, calibración de referencia y casos de falla (538 frames, 4K, 25 FPS) | Descargado con `descargar_videos.py` |
| `autopista_2.mp4` | Público | Prueba de estrés en tráfico denso y casos de falla (1080p) | Descargado con `descargar_videos.py` |
| `carretera_3.mp4` | Público | Tráfico moderado y prueba de regresión (1,501 frames, 1080p, 25 FPS) | Descargado con `descargar_videos.py` |

El requisito 2 exige que **al menos una parte de los datos sea propia**: el equipo grabó `prueba.mp4` desde un punto fijo en vía local, midiendo la distancia real entre las líneas A y B (**3,5 m**) y calibrándola en `datos/calibraciones.json`.

## Fuentes y citas

| Recurso | Cita / URL | Licencia / condiciones |
|---|---|---|
| `prueba.mp4` (video propio principal) | Grabación propia del equipo en vía urbana local (1080p, 30 FPS): <https://drive.google.com/file/d/1uIu75rfCu8QMMPlDfBzAZOLBPvNdPInT/view?usp=sharing> | Uso académico; excluido de Git por tamaño (298 MB) y compartido en Google Drive para su descarga/revisión. |
| `autopista_1.mp4`, `autopista_2.mp4` | Roboflow, *supervision – video examples*. <https://media.roboflow.com/supervision/video-examples/vehicles.mp4> y `vehicles-2.mp4` | Videos de ejemplo distribuidos con la librería `supervision` (MIT). Se usan solo con fines académicos y **no se redistribuyen** (excluidos de Git). |
| `carretera_3.mp4` | Pexels, video nº 854671. <https://www.pexels.com/video/854671/> (`854671-hd_1920_1080_25fps.mp4`) | Licencia Pexels (uso libre, sin atribución obligatoria; se cita por buena práctica). |
| Pesos `yolov8s.pt`, `yolov8n.pt` | Jocher, G., Chaurasia, A., Qiu, J. (2023). *Ultralytics YOLOv8*. <https://github.com/ultralytics/ultralytics> | AGPL-3.0 (código y pesos de Ultralytics). Entrenados en COCO. |
| Dataset COCO (entrenamiento de YOLOv8) | Lin, T.-Y. et al. (2014). *Microsoft COCO: Common Objects in Context*. ECCV. | CC BY 4.0 (anotaciones). |
| ByteTrack | Zhang, Y. et al. (2022). *ByteTrack: Multi-Object Tracking by Associating Every Detection Box*. ECCV. | Implementación vía paquete `trackers` de Roboflow. |

> Los videos no se versionan en Git (`.gitignore`). Los videos públicos se obtienen con
> `python -m aforo descargar`; los pesos se descargan automáticamente en `datos/modelos/`.

## Protocolo aplicado en la grabación y anotación

1. **Cámara fija y encuadre estable:** 1920×1080 a 30 FPS desde punto fijo, sin movimiento de cámara (`prueba.mp4`).
2. **Calibración en campo / escena:** medición de referencia física del tramo entre `LINEA_VELOCIDAD_A` y `LINEA_VELOCIDAD_B` (**3,5 m**), límite urbano de **30 km/h** y tope `VELOCIDAD_MAX_KMH = 80.0` registrados en `datos/calibraciones.json`.
3. **Privacidad:** grabación en vía pública evitando primeros planos de rostros; el video se entrega mediante enlace privado para revisión académica.
4. **Verdad de terreno (paso final de evaluación):**
   ```bash
   python -m aforo anotar --video datos/videos/prueba.mp4 --camara prueba
   python -m aforo evaluar --camara prueba --informe
   ```

## Datos que NO se usan para entrenar

No se entrena ni se ajusta (*fine-tuning*) ningún modelo con los videos del proyecto: YOLOv8 se usa con los pesos preentrenados de COCO. Por eso **todos los videos del proyecto, propios o públicos, son datos que el modelo no vio en el entrenamiento** (requisito 6 del proyecto final).
