# Métricas

Este documento describe **qué se mide, cómo y con qué datos**. Los números finales se generan
con `evaluar.py` y quedan en la tabla `metricas` de la base de datos y en
[`METRICAS_RESULTADOS.md`](METRICAS_RESULTADOS.md) (se regenera con `python evaluar.py --informe`).

> **Estado:** las métricas finales requieren (a) los videos propios del equipo y (b) su verdad de
> terreno anotada a mano. Mientras tanto, lo medido sobre videos públicos es **provisional** y
> se indica como tal. No se reportan cifras que no hayan sido medidas.

## Datos de evaluación (no vistos en entrenamiento)

El detector es YOLOv8 con pesos preentrenados en COCO y **no se ajusta con ningún video del
proyecto**; por lo tanto todos los videos (propios y públicos) son datos que el modelo no vio en
entrenamiento. Los parámetros del sistema (umbrales, líneas) se calibran con un video y se
evalúan con **otro distinto** cuando es posible (calibrar y evaluar sobre el mismo video infla
las métricas).

## Procedimiento

1. **Verdad de terreno (GT).** Una persona, sin mirar la salida del sistema, marca con
   `anotar_verdad_terreno.py` el instante y tipo de cada vehículo que cruza la línea de conteo
   (`evaluacion/<camara>.json`). Si hay velocidades de referencia (GPS, cronómetro), se agregan.
2. **Sistema.** `python main.py --video <video> --camara <camara> --reemplazar` guarda los cruces
   en la BD.
3. **Evaluación.** `python evaluar.py --camara <camara>` lee con `SELECT` los cruces y la GT,
   empareja eventos (1 a 1, ventana ±1 s, el más cercano primero) y calcula:

| Métrica | Definición | Qué responde |
|---|---|---|
| Precisión | TP / (TP + FP) | De los vehículos que contó, ¿cuántos eran reales? |
| Recall | TP / (TP + FN) | De los vehículos reales, ¿cuántos contó? |
| F1 | 2·P·R / (P + R) | Resumen de ambas. |
| Acierto de clasificación | TP con tipo correcto / TP | ¿Acierta auto/moto/bus/camión? |
| Error de aforo | \|N_sistema − N_real\| / N_real (total y por tipo) | ¿Qué tan exacto es el conteo? |
| MAE de velocidad | promedio de \|v_sistema − v_real\| (km/h) | Error típico de la velocidad. |
| RMSE de velocidad | √promedio((v_sistema − v_real)²) | Como MAE, penalizando errores grandes. |
| % dentro de ±5 km/h | mediciones con error ≤ 5 km/h | Tasa de acierto de la velocidad. |
| Recall / precisión de exceso | sobre cruces con velocidad real: ¿detecta v > límite? | Calidad de la alerta de exceso. |

TP = cruce del sistema con pareja en la GT; FP = cruce del sistema sin pareja (contó de más);
FN = cruce de la GT sin pareja (no lo contó).

**Por qué precisión y recall y no solo el total:** el total puede coincidir por casualidad si un
falso positivo compensa un falso negativo. Las pruebas de `tests/test_evaluar.py` verifican estos
cálculos con casos hechos a mano (incluido ese).

## Metas (ficha del cliente hipotético)

Ver [`CONTEXTO_CLIENTE.md`](CONTEXTO_CLIENTE.md): error de aforo ≤ 10 %, F1 ≥ 0.90, clasificación
≥ 85 %, MAE ≤ 5 km/h, recall de exceso ≥ 80 %.

## Métrica opcional: mAP del detector

Si el equipo etiqueta ~100 frames de sus videos en formato YOLO (por ejemplo con Roboflow o CVAT),
el mAP de YOLO sobre ellos se obtiene con:

```bash
yolo val model=models/yolov8s.pt data=mi_dataset.yaml imgsz=960 classes=2,3,5,7
```

Mide la calidad del **detector** aislada del tracker y de la línea de conteo; las métricas de
arriba miden el **sistema completo** (que es lo que le importa al cliente).

## Auditoría del tracking (complementaria)

`verificar_tracking.py` no necesita verdad de terreno: comprueba **invariantes** (ningún ID repetido
en un frame ni reutilizado tras caducar) y mide indicadores de estabilidad (saltos sospechosos,
IDs efímeros, cambios de clase). Resultados sobre los videos públicos:

| Video | Frames | IDs | Vida media de un ID | IDs efímeros (< 8 fr.) | Cambios de clase | Invariantes |
|---|---|---|---|---|---|---|
| `autopista_1` (4K, tráfico fluido) | 538 | 12 | 171 fr. | 0 | 6 | OK |
| `carretera_3` (1080p, moderado) | 300 | 12 | 128 fr. | 0 | 0 | OK |
| `autopista_2` (1080p, denso) | 400 | 410 | 28 fr. | 31 | 61 | OK |

En tráfico fluido cada vehículo conserva un único ID de entrada a salida; en tráfico denso los
IDs se fragmentan (ver [`CASOS_DE_FALLA.md`](CASOS_DE_FALLA.md)). Son mediciones reales con
`python verificar_tracking.py`.
