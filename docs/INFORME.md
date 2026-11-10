# Informe: Aforo vehicular y estimación de velocidad con YOLOv8

> Borrador consolidado. Cada sección resume y enlaza el documento de detalle. Las partes
> marcadas **[PENDIENTE]** dependen de datos que solo el equipo puede aportar (videos propios,
> verdad de terreno, ficha real del cliente). Integrantes: **[PENDIENTE: nombres]**.

## 1. Contexto empresarial
Cliente (hipotético hasta recibir la ficha): Secretaría de Movilidad de una ciudad intermedia.
Problema: decide con conteos manuales esporádicos, sin velocidad ni alertas. Indicadores de éxito:
error de aforo ≤ 10 %, F1 de cruces ≥ 0.90, error de velocidad (MAE) ≤ 5 km/h y recall de excesos
≥ 80 %. Detalle: [`CONTEXTO_CLIENTE.md`](CONTEXTO_CLIENTE.md).

## 2. Datos
Videos propios **[PENDIENTE: grabar según el protocolo]** más tres videos públicos citados
(Roboflow `supervision`, Pexels) y los pesos de YOLOv8 preentrenados en COCO. Detalle y
licencias: [`DATOS.md`](DATOS.md).

## 3. Técnicas del curso
1. **YOLO / CNN** (`detector.py`): detección de vehículos.
2. **Operaciones aritméticas** (`movimiento.py`): resta absoluta contra un fondo de promedio móvil.
3. **Umbralización y morfología** (`movimiento.py`): máscara binaria limpia por apertura y cierre.

Detalle con fórmulas y archivos: [`TECNICAS.md`](TECNICAS.md).

## 4. Base de datos
SQLite (`datos/db/database.db`) con tablas `cruces`, `alertas`, `lecturas_trafico`, `ejecuciones`,
`metricas` y la vista `v_aforo_por_minuto`; modelo ER, DDL y diccionario en
[`MODELO_DATOS.md`](MODELO_DATOS.md). No hay CSV como almacenamiento.

## 5. Sistema de punta a punta
```
video ─► YOLOv8 ─► ByteTrack ─► cruce de línea ─► INSERT cruces ───────────┐
            │                └► tiempo A→B ─► velocidad ─► alerta de exceso ┤
            └► resta de fondo ─► umbral ─► morfología ─► ¿detenido? ─► alerta ┤
                                                                            ▼
                                                           SQLite ─► dashboard web (FastAPI + interfaz propia)
```
Entrada: video (archivo). Salida útil para el cliente: **aforo por tipo y por minuto, velocidad
media por vehículo, alertas de exceso y de tráfico detenido, estado de la vía**, consultables en el
dashboard y por SQL; además, un video anotado. Arquitectura por módulos:
[`GUIA_SUSTENTACION.md`](GUIA_SUSTENTACION.md).

Demostración sobre `autopista_1` (sin verdad de terreno, por lo que **no es una métrica**): 10 vehículos
contados (8 autos, 2 camiones), 6 velocidades entre 38.6 y 66.9 km/h y 1 alerta de exceso (66.9 km/h
con límite de 60 km/h).

## 6. Métricas
Precisión, recall, F1 de cruces, acierto de clasificación, error de aforo, MAE/RMSE de velocidad
y recall/precisión del exceso, medidos contra verdad de terreno anotada a mano sobre videos que el
modelo no vio. **[PENDIENTE: resultados finales con videos propios]**. Método y definiciones:
[`METRICAS.md`](METRICAS.md); auditoría del tracking ya medida en los tres videos públicos
(IDs únicos en todos; fragmentación solo en tráfico denso).

## 7. Casos de falla
Cinco casos observados con evidencia: conteo inflado en tráfico denso, velocidad `NULL` al inicio,
cambios de clase de un mismo vehículo, máscara de movimiento inflada por sombras y calibración de
distancia incorrecta. Detalle: [`CASOS_DE_FALLA.md`](CASOS_DE_FALLA.md).

## 8. Reproducibilidad
Repositorio ordenado, `requirements.txt` con versiones exactas, pruebas unitarias (109) y flujo
completo en el [`README`](../README.md): `pip install -r requirements.txt` →
`python -m aforo descargar` → `python -m aforo procesar ...` → `python -m aforo dashboard` →
`python -m aforo evaluar ...`.

## 9. Trabajo propio
Se usaron librerías (Ultralytics, `trackers`, `supervision`, OpenCV, FastAPI) y asistencia
de IA como apoyo. El conteo por intersección de segmentos, la velocidad, el análisis de movimiento,
las alertas, la base de datos, el dashboard y la evaluación son código del proyecto y están
comentados en español; [`GUIA_SUSTENTACION.md`](GUIA_SUSTENTACION.md) resume qué hace cada parte y
por qué, para que cada integrante pueda explicarla.
