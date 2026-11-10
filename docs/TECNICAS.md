# Técnicas del curso utilizadas

El sistema usa **tres técnicas del curso** claramente separadas (cada una con su archivo y su
función), más una cuarta de apoyo:

| # | Técnica | Dónde | Para qué |
|---|---|---|---|
| 1 | **YOLO (red neuronal convolucional)** | [`detector.py`](../detector.py) | Detectar vehículos y su clase en cada frame. |
| 2 | **Operaciones aritméticas entre imágenes** | [`movimiento.py`](../movimiento.py) | Modelar el fondo y medir qué cambió. |
| 3 | **Umbralización + morfología matemática** | [`movimiento.py`](../movimiento.py) | Convertir "qué cambió" en una máscara limpia de movimiento. |
| 4 | Aritmética de tiempo/espacio (apoyo) | [`speed_estimator.py`](../speed_estimator.py), [`geometry.py`](../geometry.py) | Velocidad = distancia ÷ tiempo; cruce de línea con producto cruz. |

## 1. YOLO / CNN — detección

- **Qué es:** YOLOv8 (`yolov8s.pt`), un detector de **una etapa** basado en una **red neuronal
  convolucional**: la imagen completa entra a la red y en una sola pasada predice cajas, clase y
  confianza. Los pesos están preentrenados en COCO (80 clases); no se entrena nada, se filtran
  las clases `car`, `motorcycle`, `bus` y `truck`.
- **Dónde:** `VehicleDetector.detect()` en `detector.py` (`classes=[2,3,5,7]`, `conf=0.25`,
  `iou=0.5` para la supresión de no-máximos).
- **Por qué esta:** es el estado del arte práctico para detección en tiempo casi real y no exige
  un dataset de entrenamiento propio.
- **Complemento — seguimiento:** ByteTrack (`tracker.py`) asocia las detecciones entre frames
  con filtro de Kalman + IoU para dar un ID estable a cada vehículo (se audita con
  `verificar_tracking.py`).

## 2. Operaciones aritméticas — modelo de fondo y diferencia

En `DetectorMovimiento.actualizar()` (`movimiento.py`):

- **Resta absoluta** `D = |I − B|` con `cv2.absdiff`: cuánto difiere cada píxel del frame actual
  `I` respecto del fondo `B`.
- **Promedio móvil** `B ← (1 − α)·B + α·I` con `cv2.accumulateWeighted` (α = 0.02): el fondo se
  actualiza lentamente con una suma ponderada de imágenes.
- **Por qué:** un vehículo que pasa produce una diferencia grande; uno que se detiene es
  "absorbido" por el fondo en ≈ 1/α frames y su diferencia tiende a 0. Esa es la señal de
  "hay vehículos pero no se mueven".
- También hay aritmética de imágenes en la mezcla translúcida del panel (`cv2.addWeighted`,
  `visualizer.py`), pero es solo visual; la técnica con función real es la de movimiento.

## 3. Umbralización y morfología — máscara de movimiento

Tras la resta, también en `actualizar()`:

1. **Umbralización** `cv2.threshold(D, 25, 255, THRESH_BINARY)`: cada píxel pasa a 255
   (movimiento) si su diferencia supera el umbral, o a 0. El umbral (`MOV_UMBRAL_DIFERENCIA`)
   separa el cambio real del ruido del sensor y de la iluminación.
2. **Apertura morfológica** (erosión → dilatación) con elemento estructurante elíptico 3×3:
   elimina manchas aisladas de 1–2 píxeles (ruido) sin encoger los objetos grandes.
3. **Cierre morfológico** (dilatación → erosión) 7×7: rellena huecos dentro de un vehículo
   (reflejos, ventanas) para que sea una región compacta.

Con la máscara se calcula `ratio_roi` (fracción de la ROI en movimiento) y `ratio_en_vehiculos`
(fracción de los píxeles de las cajas YOLO que se mueven). `MonitorTrafico` (`alertas.py`) usa el
segundo para decidir si el tráfico está **detenido**. Las pruebas
`tests/test_movimiento.py` verifican que la apertura elimina ruido puntual y que el cierre
rellena huecos.

> **Nota sobre "umbral":** los umbrales de **confianza** (0.25 del detector, 0.4/0.5 de ByteTrack)
> son un concepto distinto (umbralización de una *puntuación*, no de una imagen). La
> umbralización de imágenes del curso es la de `cv2.threshold` del punto 3.

## Cómo se combinan

```
frame ─► YOLO (CNN) ─► cajas y clases ─► ByteTrack ─► IDs ─► cruce de línea ─► BD (cruces)
   │                                          │
   └─► |I−B| ─► umbral ─► apertura/cierre ─► máscara ──┴─► ¿vehículos que no se mueven? ─► alerta
```
