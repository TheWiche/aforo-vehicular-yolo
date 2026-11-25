# Contexto empresarial

> Caso de estudio aplicado a la región (Riohacha, La Guajira), alineado con las necesidades de gestión vial urbana y las capacidades del sistema implementado.

## 1. Ficha del cliente

| Campo | Detalle |
|---|---|
| **Nombre de la entidad** | **Secretaría de Tránsito y Movilidad Distrital de Riohacha** |
| **Sector** | Sector público — Gestión de movilidad urbana, tránsito y seguridad vial |
| **A qué se dedica** | Regulación del tránsito, estudios de flujo vehicular, control de velocidades en corredores urbanos y prevención de siniestros viales en el distrito de Riohacha, La Guajira. |
| **Quién usaría el sistema** | **1) Ingeniero(a) / Analista de Movilidad:** revisa aforos por tipo vehicular y por minuto, distribución de velocidades y percentil $V_{85}$ para planificar señalización o reductores de velocidad.<br>**2) Operador del Centro de Gestión Vial:** calibra cámaras, ejecuta análisis de grabaciones y atiende alertas de exceso de velocidad y tráfico detenido. |

## 2. Problema de negocio

Actualmente la Secretaría realiza sus diagnósticos de tráfico mediante **aforos manuales esporádicos** (personal en campo con planillas y contadores durante jornadas cortas de 2 a 4 horas). No disponer de un sistema automatizado le cuesta a la entidad:

- **En tiempo:** Hasta **12 horas hombre por estudio puntual** (~8 horas de observación en vía divididas en turnos + ~4 horas de digitación y consolidación en hojas de cálculo), retrasando varios días la toma de decisiones.
- **En dinero:** Gasto operativo recurrente de **COP \$1.200.000 a \$1.800.000 por punto monitoreado al mes** en viáticos, turnos de personal y consolidación manual, sin generar una base de datos histórica reutilizable.
- **En riesgo:** **Ausencia total de medición de velocidad** (no se conoce qué porcentaje de conductores supera los 30–50 km/h en vías urbanas o zonas escolares, ni en qué franjas horarias) y detección tardía de embotellamientos o incidentes, lo que eleva el riesgo de siniestros viales (especialmente de motociclistas, que representan el mayor volumen en la muestra local).

## 3. Indicador de éxito

| # | Indicador | Línea base (sin sistema) | Meta con el sistema | Cómo se verifica |
|---|---|---|---|---|
| 1 | **Tiempo de análisis por jornada** | ~12 horas hombre (campo + digitación) | **< 15 minutos** de procesamiento y consulta (**ahorro > 95 %**) | Tiempo de `procesar` + consulta en dashboard |
| 2 | **Exactitud del aforo total** | Conteo manual sin auditoría ni evidencia | **Error de aforo $\le 10\,\%$** | `aforo_error_pct` en `evaluar.py` |
| 3 | **Detección de cruces** | Sin registro de cuadro ni trazabilidad | **$F_1 \ge 0.90$** (precisión y recall equilibrados) | `eventos_f1` en `evaluar.py` |
| 4 | **Clasificación por tipo** | Anotación manual propensa a omisiones | **$\ge 85\,\%$ de aciertos** (`Auto`, `Moto`, `Bus`, `Camion`) | `clasificacion_acierto` |
| 5 | **Error de velocidad** | **0 % de cobertura** (no se mide velocidad) | **MAE $\le 5\text{ km/h}$** frente a referencia real | `velocidad_mae_kmh` |
| 6 | **Detección de excesos** | No medido | **Recall $\ge 80\,\%$** de los excesos reales | `exceso_recall` |

## 4. Requisitos del cliente

- **Qué debe hacer el sistema:**
  1. Procesar video de cámara fija sobre un corredor vial, detectando y clasificando vehículos (`Auto`, `Moto`, `Bus`, `Camion`).
  2. Asignar un identificador único por vehículo (seguimiento entre cuadros) para evitar conteos repetidos y cruzar una línea virtual de aforo.
  3. Estimar la velocidad media (km/h) en un tramo calibrado con distancia real en metros y emitir alertas de `EXCESO_VELOCIDAD` al superar el límite configurado.
  4. Vigilar la dinámica de movimiento en la zona de interés para detectar y alertar episodios de `TRAFICO_DETENIDO`.
  5. Guardar cada cruce, lectura de tráfico y alerta en una base de datos relacional (`SQLite`) y ofrecer un **dashboard web propio** para calibrar líneas arrastrando sobre el video, ejecutar el procesamiento en vivo, visualizar estadísticas y auditar cada cruce con su fotograma de evidencia.
- **Dónde se instala:** En un computador de escritorio o estación de trabajo local dentro de la sede técnica de la Secretaría de Tránsito y Movilidad (Windows/Linux con Python 3.12 y GPU NVIDIA recomendada para análisis en tiempo real; corre 100 % local fuera de Google Colab, sin subir grabaciones a servidores externos).
- **Quién lo opera:** Un técnico o analista de movilidad sin conocimientos de programación: usa el navegador web (`http://localhost:8501`) lanzado mediante `python iniciar.py` para cargar el video, calibrar las tres líneas y consultar los resultados.

## 5. Análisis de costos y beneficio estimado (Punto de alcance)

| Concepto | Estimación (COP) | Detalle |
|---|---|---|
| **Software y licencia de visión** | \$0 | Stack open-source (`YOLOv8` AGPL-3.0, `OpenCV`, `FastAPI`, `SQLite`) y desarrollo propio del equipo. |
| **Estación de cómputo (hardware)** | \$4.500.000 (única vez) | PC existente de oficina o equipo con GPU NVIDIA de gama media (ej. RTX 3060 / 2070) para procesar a ~20 FPS. *(Si se aprovecha un equipo institucional existente, costo adicional = \$0).* |
| **Cámara fija / soporte en punto piloto** | \$450.000 – \$900.000 | Cámara 1080p @ 30 FPS en punto elevado existente (poste o puente peatonal) o uso de grabaciones de cámaras municipales ya instaladas. |
| **Ahorro operativo mensual** | ~\$1.400.000 / mes por punto | Sustituye campañas manuales periódicas (~12 h hombre por estudio × varios puntos al mes) y elimina la digitación manual. |
| **Retorno de inversión (ROI)** | **~3 a 4 meses** | Asumiendo compra de cámara + equipo dedicado; **inmediato (< 1 mes)** si se ejecuta sobre hardware y cámaras existentes de la Secretaría. |

## 6. Alcance técnico y límites de operación

- Requiere cámara **fija** en posición elevada, enfocando un tramo recto de la calzada cuya distancia real entre las líneas A y B haya sido medida en campo.
- Mide **velocidad media en el tramo A–B**, no velocidad instantánea; funciona como herramienta de diagnóstico, planeación y priorización operativa (no como cinemómetro metrológico sancionatorio).
- El rendimiento se degrada en congestión extrema con oclusiones severas o baja iluminación sin calibración nocturna (ver [`CASOS_DE_FALLA.md`](CASOS_DE_FALLA.md)).
