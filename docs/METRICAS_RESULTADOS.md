# Resultados de métricas y pruebas medidas

## 1. Resultados registrados en SQLite (`datos/db/database.db`)

| Cámara / Video | Cruces totales | Con velocidad | Vel. promedio (km/h) | Desglose por tipo | Alertas `EXCESO_VELOCIDAD` |
|---|---|---|---|---|---|
| `prueba` (`prueba.mp4`, 17.6 min) | **177** | 171 (96.6 %) | **25.4** | Moto: 132 (27.2 km/h), Auto: 40 (19.6 km/h), Camión: 5 (21.3 km/h) | **45** (30.1 – 41.1 km/h; límite 30) |
| `prueba1` (`Prueba1_optimizado.mp4`, 17.8 min) | **179** | 171 | **29.2** | Moto: 136 (31.6 km/h), Auto: 42 (21.8 km/h), Camión: 1 (16.6 km/h) | **83** (30.1 – 47.5 km/h; límite 30) |
| `autopista_1` (538 fr.) | **10** | 6 | **52.5** | Auto: 8 (55.2 km/h), Camión: 2 (39.0 km/h) | **1** (68.1 km/h; límite 60) |
| `carretera_3` (1,501 fr.) | **30** | 25 | **18.0** | Auto: 28, Moto: 1, Camión: 1 | **0** (límite 50) |

## 2. Auditoría de invariantes de tracking (`python -m aforo auditar`)

| Video | Frames | IDs | Vida media de un ID | IDs efímeros (< 8 fr.) | Cambios de clase | Invariantes |
|---|---|---|---|---|---|---|
| `prueba.mp4` (1080p, propio) | 3,000 | 7 | 47.3 fr. | 0 | 0 | OK |
| `autopista_1` (4K, fluido) | 538 | 12 | 171 fr. | 0 | 6 | OK |
| `carretera_3` (1080p, moderado) | 300 | 12 | 128 fr. | 0 | 0 | OK |
| `autopista_2` (1080p, denso) | 400 | 410 | 28 fr. | 31 | 61 | OK |

## 3. Comparación de modelos (`yolov8n.pt` vs. `yolov8s.pt`)

Evaluación en `carretera_3.mp4` (1,501 frames @ 960 px en GPU RTX 2070 SUPER):

| Modelo | Tiempo (s) | Velocidad (FPS) | Cruces totales | Desglose por tipo | Velocidad media (rango) |
|---|---|---|---|---|---|
| `yolov8n.pt` (Nano) | 42.4 s | **35.40 FPS** | 31 | Auto: 28, Moto: 1, Camión: 2 | **18.0 km/h** (13.7 – 22.1) |
| `yolov8s.pt` (Small) | 51.4 s | 29.24 FPS | 30 | Auto: 28, Moto: 1, Camión: 1 | **18.0 km/h** (13.7 – 22.2) |

*(Nota: la tabla de precisión, recall, $F_1$ y MAE contra verdad de terreno se regenera automáticamente en este archivo al ejecutar `python -m aforo evaluar --camara <nombre> --informe` tras anotar `datos/evaluacion/<nombre>.json`.)*
