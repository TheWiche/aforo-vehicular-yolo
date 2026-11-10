# Guía de sustentación (cada integrante debe poder explicar cualquier parte)

La revisión incluye preguntas individuales. Esta guía resume, módulo por módulo, **qué hace,
por qué se hizo así, la idea o fórmula clave** y preguntas probables con respuesta corta.
Todo el código está comentado en español; lean el archivo mientras estudian su sección.

Flujo general (un frame):

```
video ─► detector.py ─► tracker.py ─► line_counter.py ──► db.py (INSERT en cruces)
          (YOLO)        (ByteTrack)    speed_estimator.py ┘      │
                                       movimiento.py ─► alertas.py ─► db.py (alertas, lecturas)
                                       visualizer.py ─► video anotado          │
                                                              dashboard.py ◄── SELECT
```

## `config.py` — configuración centralizada
- **Qué:** todos los datos que cambian de un video a otro (rutas, líneas, metros, umbrales) en
  una zona editable arriba; abajo, `dataclass` inmutables y `validate()`.
- **Por qué:** separar datos de lógica; recalibrar sin tocar algoritmos. `validate()` falla rápido
  con mensajes claros (p. ej. distancia ≤ 0, líneas A y B que se cruzan).
- **P:** ¿Por qué `dataclass(frozen=True)`? **R:** inmutables: nadie cambia la configuración a
  mitad de una ejecución sin darse cuenta; `dataclasses.replace` crea una copia modificada.

## `detector.py` — YOLO (CNN)
- **Qué:** carga `yolov8s.pt` una vez y, por frame, devuelve cajas, clase y confianza filtradas a
  car/motorcycle/bus/truck.
- **Clave:** detector de una etapa: toda la imagen entra a la red y sale la predicción en una
  pasada. `conf=0.25` descarta detecciones débiles; `iou=0.5` es la supresión de no-máximos
  (elimina cajas duplicadas del mismo objeto).
- **P:** ¿Entrenaron el modelo? **R:** No; pesos preentrenados en COCO. Por eso los videos del
  proyecto son datos no vistos. **P:** ¿Qué es una CNN? **R:** red con capas convolucionales
  (filtros aprendidos que detectan bordes, texturas, partes) apiladas.
- **Detalle técnico:** Ultralytics borra apóstrofes de las rutas; se carga por nombre desde la
  carpeta de los pesos (ver comentario en `_cargar_modelo`).

## `tracker.py` — ByteTrack y trayectorias
- **Qué:** asigna un ID persistente a cada vehículo; estabiliza la clase por votación; produce
  `Movement` (posición anterior → actual) para contar y medir.
- **Clave de ByteTrack:** filtro de Kalman predice dónde estará cada track; se empareja con las
  detecciones por IoU (asignación óptima); las detecciones de **baja confianza no se descartan**:
  se usan en una segunda ronda para recuperar tracks ocluidos.
- **P:** ¿Por qué hace falta tracker? **R:** YOLO trabaja frame a frame, no sabe que el auto del
  frame 10 es el del 11; sin identidad se contaría el mismo auto muchas veces y no se podría medir
  su tiempo en la ROI. **P:** ¿Y por qué votar la clase? **R:** YOLO alterna car/truck para el
  mismo vehículo; la clase más votada es más estable.
- **Auditoría:** `verificar_tracking.py` comprueba IDs únicos (invariantes) y estabilidad.

## `geometry.py` y `line_counter.py` — conteo por cruce de línea
- **Qué:** un vehículo se cuenta una vez cuando el **segmento** que une su posición anterior con la
  actual corta el segmento de la línea.
- **Fórmula:** con `r = p_fin − p_ini` y `s = q_fin − q_ini`:
  `t = ((q_ini − p_ini) × s) / (r × s)`, `u = ((q_ini − p_ini) × r) / (r × s)`; hay cruce si
  `0 ≤ t ≤ 1` y `0 ≤ u ≤ 1`. El producto cruz 2D es `a×b = ax·by − ay·bx`. El signo de `r×s`
  da el sentido (A/B). `t` también da el instante exacto del cruce entre dos frames.
- **P:** ¿Por qué no comparar "arriba/abajo de la línea"? **R:** un cruce es un evento puntual y
  bien definido; comparar posiciones obliga a decidir qué hacer con quien se queda sobre la línea
  o rebota por ruido. Además cada ID se cuenta una sola vez.

## `speed_estimator.py` — velocidad
- **Qué:** tiempo que tarda un ID en ir de la línea A a la B (distancia real conocida).
- **Fórmula:** `v [km/h] = (distancia_m / tiempo_s) × 3.6`, con `tiempo_s = frames / FPS`.
  - Se divide entre los FPS porque un video no tiene reloj, solo fotogramas numerados; los FPS
    convierten "frames" en "segundos".
  - El 3.6 sale de 1 m/s = (1/1000 km)/(1/3600 h) = 3.6 km/h.
  - Interpolación sub-frame: con `t` de la intersección se estima el instante entre frames;
    sin ella el error sería de hasta 1 frame (40 ms a 25 FPS = varios km/h).
- **P:** ¿Por qué dos líneas y no una homografía? **R:** el instante de cruce no depende de la
  perspectiva; solo hace falta la distancia real entre líneas. **P:** ¿Qué limita la precisión?
  **R:** error en la distancia medida, líneas no perpendiculares a la vía, FPS, y que es velocidad
  *media* del tramo.

## `movimiento.py` — operaciones aritméticas, umbralización y morfología
- **Qué:** máscara de movimiento en la ROI para saber si los vehículos se mueven.
- **Pasos y fórmulas:** (1) `D = |I − B|` (`absdiff`); (2) fondo `B ← (1−α)B + αI`
  (`accumulateWeighted`, α=0.02); (3) umbral `D > 25 → 255` (`threshold`); (4) apertura
  (erosión→dilatación) quita ruido; (5) cierre (dilatación→erosión) rellena huecos.
- **P:** ¿Por qué un vehículo detenido "desaparece" de la máscara? **R:** el promedio móvil lo
  absorbe en el fondo en ~1/α frames (2 s a 25 FPS): diferencia ≈ 0. **P:** ¿Qué hace la apertura?
  **R:** elimina manchas pequeñas aisladas sin encoger regiones grandes.
- **Limitación:** requiere cámara fija; los vehículos presentes en el primer frame dejan "fantasma"
  (por eso hay `CALENTAMIENTO_SEGUNDOS`).

## `alertas.py` — reglas de negocio
- **Exceso:** `velocidad > LIMITE_VELOCIDAD_KMH` → fila en `alertas`.
- **Tráfico detenido:** ≥ 3 vehículos en la ROI y < 12 % de sus píxeles en movimiento durante ≥ 4 s;
  se sale tras 2 s normales; **una alerta por episodio** (histéresis).
- **P:** ¿Por qué histéresis? **R:** sin ella, un parpadeo de un frame generaría cientos de alertas.

## `db.py` — SQLite
- **Qué:** crea `db/database.db` y las tablas al abrir; `INSERT` apenas el vehículo cruza;
  `UPDATE` si la velocidad llega después; consultas siempre parametrizadas.
- **P:** ¿Por qué SQLite y no CSV? **R:** integridad (tipos, PK, transacciones ACID), SQL para
  consultar y agregar, lectura concurrente (WAL) mientras se escribe, sin servidor. Un CSV no
  garantiza nada de eso. **P:** ¿Qué es una inyección SQL y cómo la evitan? **R:** que un valor
  se interprete como código; se evita enlazando parámetros (`?`) en vez de concatenar.
- **Modelo completo:** [`MODELO_DATOS.md`](MODELO_DATOS.md).

## `pipeline.py` / `main.py` — orquestación
- **Qué:** recorre el video y llama a cada etapa en orden; `main.py` es la línea de comandos.
- **Por qué:** cada etapa solo conoce la salida de la anterior (bajo acoplamiento), se puede
  cambiar una pieza sin tocar las demás.

## `visualizer.py` — video anotado
- Cajas, ID, clase, velocidad (con "EXCESO" sobre el límite), estelas, ROI, panel de conteo.
  Todo escala con la resolución (`k = alto/1080`).

## `dashboard.py` — Streamlit
- Cada bloque ejecuta un `SELECT` (agregaciones con `GROUP BY` en SQL, no en Python), conexión
  `PRAGMA query_only`. Resumen ejecutivo, alertas, estado de la vía, gráficos.

## `evaluar.py` — métricas
- **Precisión** = TP/(TP+FP); **recall** = TP/(TP+FN); **F1** = media armónica; **MAE** =
  promedio de |error|; **RMSE** penaliza más los errores grandes. Emparejamiento por cercanía
  temporal (±1 s). Ver [`METRICAS.md`](METRICAS.md).
- **P:** ¿Por qué precisión y recall y no solo "accuracy"? **R:** contar de más (FP) y contar de
  menos (FN) son errores distintos que pueden compensarse en el total; ambas métricas los separan.

## Preguntas transversales
1. **¿Qué pasa de noche o con lluvia?** YOLO pierde confianza y el fondo se vuelve ruidoso: ver
   [`CASOS_DE_FALLA.md`](CASOS_DE_FALLA.md); mitigación: reentrenar/ajustar con datos nocturnos propios.
2. **¿Cómo se calibra para otro video?** `seleccionar_puntos.py` → líneas en `config.py` + medir
   `DISTANCIA_REAL_METROS`.
3. **¿Por qué `track_id` se repite entre ejecuciones?** ByteTrack reinicia el contador; el vehículo
   se identifica por (`camara`, `momento`, `track_id`) o por `id`.
4. **¿Qué mejorarían?** Homografía para velocidad instantánea, re-identificación para tráfico
   denso, modelo ajustado a sus datos, cámara en vivo (RTSP).
5. **¿Qué parte es de ustedes y cuál de librerías?** Las librerías (Ultralytics, `trackers`,
   `supervision`, OpenCV, Streamlit) aportan detección, seguimiento y utilidades; el conteo
   por intersección, la velocidad, el análisis de movimiento, las alertas, la base de datos, el
   dashboard y la evaluación son código del proyecto.
