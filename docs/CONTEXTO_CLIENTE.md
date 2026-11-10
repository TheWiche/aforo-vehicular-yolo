# Contexto empresarial

> **Nota:** el equipo aún no tiene la ficha oficial del cliente. Este documento propone un
> cliente hipotético coherente con lo que el sistema mide. **Reemplazar las secciones 1–3 por
> la ficha real** cuando la entreguen; los indicadores de la sección 4 se ajustan a los suyos.

## 1. Cliente

**Secretaría de Movilidad de una ciudad intermedia** (cliente ficticio), responsable de la
seguridad vial y la planeación del tránsito en un corredor arterial de doble calzada.

## 2. Problema de negocio

La Secretaría toma decisiones (dónde instalar fotodetección, qué límite de velocidad fijar,
cuándo reforzar presencia policial, cómo sincronizar semáforos) con **conteos manuales
esporádicos**: una persona con un contador durante unas pocas horas. Ese método:

- no distingue por tipo de vehículo (auto, moto, bus, camión) más allá de lo que alcanza a anotar;
- no mide velocidad, así que **no sabe cuántos vehículos exceden el límite** ni en qué horas;
- no detecta **tráfico detenido** (congestión, accidente, falla) hasta que alguien llama;
- es caro, discontinuo y no deja un registro consultable.

## 3. Solución

Un sistema de visión por computador que procesa el video de una cámara fija sobre el corredor y
produce, sin intervención humana:

| Pregunta del cliente | Respuesta del sistema |
|---|---|
| ¿Cuántos vehículos pasan, de qué tipo y a qué hora? | Aforo por tipo y por minuto (tabla `cruces`, vista `v_aforo_por_minuto`). |
| ¿A qué velocidad circulan? | Velocidad media en un tramo de longitud conocida por vehículo. |
| ¿Cuántos y quiénes exceden el límite? | Alerta `EXCESO_VELOCIDAD` por vehículo, con hora y valor. |
| ¿Hay tráfico detenido ahora? | Alerta `TRAFICO_DETENIDO` y estado de la vía (libre / fluido / detenido). |
| ¿Dónde veo todo esto? | Dashboard web con resumen ejecutivo, alertas y gráficos (`streamlit run dashboard.py`). |

Entrada: video (archivo o grabación de la cámara). Salida: base de datos relacional + dashboard.

## 4. Indicadores de éxito (medibles con `evaluar.py`)

| # | Indicador | Meta propuesta | Cómo se mide |
|---|---|---|---|
| 1 | Exactitud del aforo | error del total ≤ 10 % frente a conteo manual | `aforo_error_pct` |
| 2 | Detección de cruces | F1 ≥ 0.90 | `eventos_f1` (precisión y recall) |
| 3 | Clasificación de tipo | ≥ 85 % de aciertos | `clasificacion_acierto` |
| 4 | Error de velocidad | MAE ≤ 5 km/h frente a una referencia | `velocidad_mae_kmh` |
| 5 | Alertas de exceso | recall ≥ 80 % de los excesos reales | `exceso_recall` |
| 6 | Disponibilidad de la información | resultados consultables minutos después de procesar el video | dashboard / tabla `cruces` |

Las metas son una propuesta del equipo; las cifras **medidas** están en
[`METRICAS.md`](METRICAS.md) (se completan con los videos propios y su verdad de terreno).

## 5. Alcance y límites

- Cámara fija, vista elevada y frontal/trasera de los vehículos, tráfico en el sentido de la vía.
- Se mide **velocidad media en un tramo**, no velocidad instantánea; no es un instrumento
  certificado para sancionar, sino una herramienta de diagnóstico y planeación.
- Rendimiento degradado en tráfico muy denso, oclusiones y baja luz: ver
  [`CASOS_DE_FALLA.md`](CASOS_DE_FALLA.md).
- Los videos pueden contener placas y personas: ver las notas de privacidad en [`DATOS.md`](DATOS.md).
