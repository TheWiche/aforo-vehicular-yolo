"""
dashboard.py
============
Panel web (Streamlit, modo oscuro) que consulta con SQL la base de datos SQLite
`db/database.db`, donde `main.py` guarda cada vehiculo que cruza la linea de conteo.

Ejecutar:
    streamlit run dashboard.py

Muestra:
  1) Tarjetas con el total de vehiculos contados por tipo.
  2) Grafico de barras con la velocidad PROMEDIO por tipo de vehiculo.
  3) Grafico de dispersion (scatter) de cada medicion de velocidad contra la hora
     del cruce, resaltando los picos.

Como se leen los datos
----------------------
No hay archivos intermedios: cada bloque del panel ejecuta un `SELECT` sobre la
tabla `cruces` (ver las constantes SQL_* mas abajo) y las agregaciones (conteos,
promedios) las calcula el motor SQL con `GROUP BY`, no Python. La conexion se
abre en modo solo-lectura logico (`PRAGMA query_only`), asi que el dashboard
jamas puede modificar los datos, y gracias al modo WAL de SQLite puede
consultarlos mientras `main.py` sigue escribiendo.

Decisiones de diseno de los graficos
------------------------------------
* El color identifica al TIPO de vehiculo y es el mismo que usa el video
  (COLORES_CLASE en config.py). Son tonos validados para fondo oscuro que no se
  confunden entre si ni con daltonismo.
* En el scatter el color NO codifica la clase (con 4 clases la separacion
  entre colores no seria fiable): el gris son las mediciones normales y el
  amarillo los picos; la clase aparece al pasar el mouse y en la tabla.
* Todo texto usa tonos de tinta (claro/gris), nunca el color de la serie.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from config import CLASES_VEHICULO, COLORES_CLASE, DB_RUTA, LIMITE_VELOCIDAD_KMH, RAIZ_PROYECTO

# ---------------------------------------------------------------------------
# Tokens de diseno (modo oscuro). Se definen una sola vez y se reutilizan en el
# CSS y en los graficos para que todo el panel se vea coherente.
# ---------------------------------------------------------------------------
PAGINA = "#0d0d0d"            # fondo de la pagina
SUPERFICIE = "#1a1a19"        # fondo de tarjetas y graficos
BORDE = "rgba(255,255,255,0.10)"
TINTA = "#f0efec"             # texto principal
TINTA_2 = "#c3c2b7"           # texto secundario
TINTA_SUAVE = "#898781"       # ejes, etiquetas discretas
REJILLA = "#2c2c2a"           # lineas de cuadricula (muy discretas)
EJE = "#383835"               # linea base de los ejes
PUNTO_NORMAL = "#898781"      # mediciones normales en el scatter
PUNTO_PICO = "#fab219"        # picos de velocidad (color de estado "alerta")
FUENTE = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Nombre de clase -> color, usando las mismas definiciones que el video.
COLOR_POR_CLASE: Dict[str, str] = {
    nombre: COLORES_CLASE.get(cid, TINTA_SUAVE) for cid, nombre in CLASES_VEHICULO.items()
}
ORDEN_CLASES: List[str] = list(CLASES_VEHICULO.values())

# ---------------------------------------------------------------------------
# Consultas SQL. El unico fragmento que se arma dinamicamente es la lista de
# marcadores `?` del filtro de camaras (su cantidad, nunca sus valores), por lo
# que no hay riesgo de inyeccion SQL: los valores siempre viajan como parametros.
# ---------------------------------------------------------------------------
SQL_CAMARAS = """
    SELECT camara, COUNT(*) AS cruces, MIN(momento) AS desde, MAX(momento) AS hasta
    FROM cruces
    GROUP BY camara
    ORDER BY camara
"""
SQL_TOTAL_POR_TIPO = """
    SELECT tipo, COUNT(*) AS total
    FROM cruces
    WHERE camara IN ({marcadores})
    GROUP BY tipo
"""
SQL_VELOCIDAD_POR_TIPO = """
    SELECT tipo,
           AVG(velocidad_kmh)   AS promedio,
           MIN(velocidad_kmh)   AS minimo,
           MAX(velocidad_kmh)   AS maximo,
           COUNT(velocidad_kmh) AS n
    FROM cruces
    WHERE velocidad_kmh IS NOT NULL AND camara IN ({marcadores})
    GROUP BY tipo
"""
SQL_PUNTOS_VELOCIDAD = """
    SELECT momento, velocidad_kmh, tipo, track_id, camara
    FROM cruces
    WHERE velocidad_kmh IS NOT NULL AND camara IN ({marcadores})
    ORDER BY momento
"""
SQL_MAS_RAPIDOS = """
    SELECT momento, track_id, tipo, velocidad_kmh, camara
    FROM cruces
    WHERE velocidad_kmh IS NOT NULL AND camara IN ({marcadores})
    ORDER BY velocidad_kmh DESC
    LIMIT 8
"""
SQL_TABLA_COMPLETA = """
    SELECT id, track_id, tipo, momento, velocidad_kmh, camara
    FROM cruces
    WHERE camara IN ({marcadores})
    ORDER BY momento
"""
SQL_ULTIMO_CRUCE = "SELECT MAX(momento) FROM cruces WHERE camara IN ({marcadores})"

# Resumen ejecutivo y alertas (el primer `?` es el limite de velocidad).
SQL_EXCESOS = """
    SELECT COUNT(velocidad_kmh)       AS medidos,
           COALESCE(SUM(velocidad_kmh > ?), 0) AS excesos
    FROM cruces
    WHERE camara IN ({marcadores})
"""
SQL_ALERTAS = """
    SELECT momento, tipo, track_id, valor, umbral, descripcion, camara
    FROM alertas
    WHERE camara IN ({marcadores})
    ORDER BY momento DESC
    LIMIT 100
"""
SQL_ALERTAS_POR_TIPO = """
    SELECT tipo, COUNT(*) AS total
    FROM alertas
    WHERE camara IN ({marcadores})
    GROUP BY tipo
"""
SQL_LECTURAS = """
    SELECT momento, vehiculos_roi, ratio_movimiento, estado
    FROM lecturas_trafico
    WHERE camara IN ({marcadores})
    ORDER BY momento
"""


class BaseDatosNoDisponibleError(RuntimeError):
    """La base de datos no existe todavia, no tiene la tabla `cruces` o no se puede leer."""


# ===========================================================================
# Acceso a datos (SQL)
# ===========================================================================
def abrir_conexion(ruta: Path) -> sqlite3.Connection:
    """Abre la base de datos para CONSULTAR; falla con un mensaje claro si no existe."""
    if not ruta.is_file():
        raise BaseDatosNoDisponibleError(
            f"Todavia no existe la base de datos `{ruta}`.\n\n"
            "Genera datos primero con `python main.py` y recarga esta pagina."
        )
    try:
        con = sqlite3.connect(str(ruta), timeout=10.0)
        con.execute("PRAGMA query_only = ON")    # el dashboard solo lee, nunca escribe
        return con
    except sqlite3.Error as exc:
        raise BaseDatosNoDisponibleError(f"No se pudo abrir la base de datos: {exc}") from exc


def consultar(
    con: sqlite3.Connection, sql: str, camaras: Sequence[str], antes: Sequence[object] = ()
) -> pd.DataFrame:
    """
    Ejecuta un SELECT filtrado por camaras y devuelve el resultado como DataFrame.

    `{marcadores}` se reemplaza por '?, ?, ?' (uno por camara) y los nombres de
    camara se pasan como parametros enlazados. `antes` son parametros que aparecen
    ANTES del filtro de camaras en el SQL (p. ej. el limite de velocidad).
    """
    marcadores = ", ".join("?" for _ in camaras)
    try:
        return pd.read_sql_query(
            sql.format(marcadores=marcadores), con, params=list(antes) + list(camaras)
        )
    except (sqlite3.Error, pd.errors.DatabaseError) as exc:
        raise BaseDatosNoDisponibleError(
            f"Error al consultar la tabla `cruces`: {exc}\n\n"
            "Verifica que la base de datos la haya creado main.py."
        ) from exc


def _consulta_opcional(con: sqlite3.Connection, sql: str, camaras: Sequence[str]) -> pd.DataFrame:
    """Como `consultar`, pero devuelve un DataFrame vacio si la tabla aun no existe."""
    try:
        return consultar(con, sql, camaras)
    except BaseDatosNoDisponibleError:
        return pd.DataFrame()


ETIQUETA_ALERTA: Dict[str, str] = {
    "EXCESO_VELOCIDAD": "Exceso de velocidad",
    "TRAFICO_DETENIDO": "Trafico detenido",
}


# ===========================================================================
# Estilos (CSS)
# ===========================================================================
def inyectar_css() -> None:
    """Estilos de tarjetas y paneles; el resto lo resuelve el tema oscuro."""
    st.markdown(
        f"""
        <style>
        /* La fuente se fija solo en .stApp (los hijos la heredan). No usar un selector
           comodin: pisaria la fuente de iconos de Streamlit y mostraria texto como "_arrow_right". */
        .stApp {{ background: {PAGINA}; font-family: {FUENTE}; }}
        header[data-testid="stHeader"] {{ background: transparent; }}
        .block-container {{ padding-top: 2.2rem; max-width: 1400px; }}

        /* El prefijo [data-testid="stMarkdownContainer"] da mas especificidad que los
           estilos por defecto de Streamlit para <p>, que de otro modo ganarian. */
        [data-testid="stMarkdownContainer"] p.titulo {{
            color: {TINTA}; font-size: 2rem; font-weight: 650; margin: 0; line-height: 1.2;
        }}
        [data-testid="stMarkdownContainer"] p.subtitulo {{
            color: {TINTA_SUAVE}; font-size: .9rem; margin: .3rem 0 1.4rem 0;
        }}

        /* Tarjetas de total: la barra de color de la izquierda identifica el tipo. */
        .kpi {{
            position: relative; overflow: hidden; background: {SUPERFICIE};
            border: 1px solid {BORDE}; border-radius: 14px; padding: 18px 20px 16px 24px;
        }}
        .kpi::before {{
            content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 5px;
            background: var(--acento);
        }}
        .kpi-etiqueta {{
            color: {TINTA_2}; font-size: .8rem; font-weight: 600;
            letter-spacing: .08em; text-transform: uppercase;
        }}
        .kpi-valor {{ color: {TINTA}; font-size: 2.8rem; font-weight: 650; line-height: 1.1; margin: .3rem 0 .15rem; }}
        .kpi-detalle {{ color: {TINTA_SUAVE}; font-size: .85rem; }}

        /* Paneles que envuelven cada grafico (identificados por su `key`). */
        .st-key-panel_barras, .st-key-panel_picos, .st-key-panel_tabla,
        .st-key-panel_via, .st-key-panel_alertas {{
            background: {SUPERFICIE}; border: 1px solid {BORDE}; border-radius: 14px;
            padding: 1.1rem 1.3rem 1rem;
        }}
        [data-testid="stMarkdownContainer"] p.panel-titulo {{
            color: {TINTA}; font-size: 1.1rem; font-weight: 600; margin: 0;
        }}
        [data-testid="stMarkdownContainer"] p.panel-texto {{
            color: {TINTA_SUAVE}; font-size: .85rem; margin: .2rem 0 .6rem;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def titulo_panel(titulo: str, descripcion: str) -> None:
    """Encabezado de un panel: titulo + una frase que explica como leerlo."""
    st.markdown(
        f'<p class="panel-titulo">{titulo}</p><p class="panel-texto">{descripcion}</p>',
        unsafe_allow_html=True,
    )


# ===========================================================================
# Componentes visuales
# ===========================================================================
def tarjeta(etiqueta: str, valor: object, detalle: str, acento: str) -> str:
    """HTML de una tarjeta de total. El numero va en tinta clara, no en el color."""
    return (
        f'<div class="kpi" style="--acento:{acento}">'
        f'<div class="kpi-etiqueta">{etiqueta}</div>'
        f'<div class="kpi-valor">{valor}</div>'
        f'<div class="kpi-detalle">{detalle}</div></div>'
    )


def estilo_base(fig: go.Figure, alto: int) -> go.Figure:
    """Aplica el aspecto comun (oscuro, ejes discretos, tooltip legible)."""
    fig.update_layout(
        height=alto,
        margin=dict(l=8, r=8, t=28, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FUENTE, color=TINTA_2, size=13),
        hoverlabel=dict(bgcolor=PAGINA, bordercolor="rgba(255,255,255,0.25)",
                        font=dict(family=FUENTE, color=TINTA, size=13)),
    )
    # `automargin` hace que Plotly reserve espacio para las etiquetas de los ejes;
    # sin el, con margenes pequenos las etiquetas quedan recortadas.
    fig.update_xaxes(showgrid=False, linecolor=EJE, tickcolor=EJE, zeroline=False,
                     automargin=True, title_standoff=10)
    fig.update_yaxes(gridcolor=REJILLA, gridwidth=1, zeroline=False, showline=False,
                     automargin=True, title_standoff=10)
    return fig


def grafico_barras(resumen: pd.DataFrame, promedio_general: float) -> Optional[go.Figure]:
    """Barras con la velocidad promedio por tipo (el promedio ya viene calculado por SQL)."""
    resumen = resumen.set_index("tipo").reindex(
        [c for c in ORDEN_CLASES if c in set(resumen["tipo"])]
    )
    if resumen.empty:
        return None

    fig = go.Figure(
        go.Bar(
            x=resumen.index,
            y=resumen["promedio"],
            width=0.5,                       # barras delgadas
            marker=dict(
                color=[COLOR_POR_CLASE.get(c, TINTA_SUAVE) for c in resumen.index],
                line=dict(color=SUPERFICIE, width=2),
            ),
            text=[f"{v:.1f}" for v in resumen["promedio"]],
            textposition="outside",
            textfont=dict(color=TINTA, size=14),
            customdata=resumen[["n", "minimo", "maximo"]].to_numpy(),
            hovertemplate=(
                "<b>%{x}</b><br>Promedio: %{y:.1f} km/h<br>"
                "Mediciones: %{customdata[0]}<br>"
                "Min - Max: %{customdata[1]:.1f} - %{customdata[2]:.1f} km/h<extra></extra>"
            ),
        )
    )
    # Linea punteada del promedio general. Su valor se informa en el texto del panel
    # (no sobre el grafico) para que nunca tape la etiqueta de una barra.
    fig.add_hline(y=promedio_general, line_dash="dot", line_width=1, line_color=TINTA_SUAVE)
    estilo_base(fig, alto=380)
    fig.update_layout(showlegend=False, barcornerradius=4)
    fig.update_yaxes(title_text="km/h", range=[0, float(resumen["promedio"].max()) * 1.3])
    return fig


def grafico_dispersion(puntos: pd.DataFrame, umbral: float, percentil: int) -> go.Figure:
    """Scatter velocidad vs. hora del cruce, con los picos resaltados."""
    puntos = puntos.assign(x=pd.to_datetime(puntos["momento"]))
    puntos = puntos.assign(hora=puntos["x"].dt.strftime("%H:%M:%S"))
    # Si los datos abarcan mas de un dia, el eje incluye la fecha.
    abarca_dias = (puntos["x"].max() - puntos["x"].min()).days >= 1
    formato = "%d/%m %H:%M" if abarca_dias else "%H:%M:%S"

    es_pico = puntos["velocidad_kmh"] >= umbral

    def traza(datos: pd.DataFrame, nombre: str, color: str, tam: int) -> go.Scatter:
        return go.Scatter(
            x=datos["x"], y=datos["velocidad_kmh"], mode="markers", name=nombre,
            marker=dict(size=tam, color=color, line=dict(color=SUPERFICIE, width=2)),
            customdata=datos[["hora", "tipo", "track_id"]].to_numpy(),
            hovertemplate=(
                "<b>%{customdata[1]}</b> (ID %{customdata[2]})<br>"
                "%{y:.1f} km/h<br>Hora: %{customdata[0]}<extra></extra>"
            ),
        )

    fig = go.Figure()
    fig.add_trace(traza(puntos[~es_pico], "Medicion", PUNTO_NORMAL, 10))
    fig.add_trace(traza(puntos[es_pico], f"Pico (percentil {percentil} o mayor)", PUNTO_PICO, 14))

    fig.add_hline(
        y=umbral, line_dash="dash", line_width=1, line_color=TINTA_SUAVE,
        annotation_text=f"Umbral de pico {umbral:.1f} km/h",
        annotation_position="bottom right", annotation_font=dict(color=TINTA_2, size=12),
    )

    # Etiqueta directa solo para el punto mas rapido (no un numero por punto).
    top = puntos.loc[puntos["velocidad_kmh"].idxmax()]
    fig.add_annotation(
        x=top["x"], y=top["velocidad_kmh"], text=f"Max. {top['velocidad_kmh']:.1f} km/h · {top['hora']}",
        showarrow=True, arrowcolor=TINTA_SUAVE, arrowwidth=1, ax=0, ay=-42,
        font=dict(color=TINTA, size=13), bgcolor=SUPERFICIE, borderpad=3,
    )

    estilo_base(fig, alto=380)
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(color=TINTA_2, size=13)),
        margin=dict(l=8, r=8, t=44, b=8),
    )
    fig.update_xaxes(title_text="Hora del cruce", tickformat=formato)
    lo, hi = float(puntos["velocidad_kmh"].min()), float(puntos["velocidad_kmh"].max())
    fig.update_yaxes(title_text="km/h", range=[max(0.0, lo - 10), hi + 18])
    return fig


def grafico_estado_via(lecturas: pd.DataFrame) -> go.Figure:
    """
    Dos graficos apilados con el mismo eje de tiempo (nunca dos escalas Y en un
    mismo grafico): vehiculos dentro de la ROI y porcentaje de movimiento.
    """
    lecturas = lecturas.assign(x=pd.to_datetime(lecturas["momento"]))
    lecturas = lecturas.assign(hora=lecturas["x"].dt.strftime("%H:%M:%S"),
                               movimiento_pct=lecturas["ratio_movimiento"] * 100.0)
    detenido = lecturas[lecturas["estado"] == "DETENIDO"]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.16,
                        subplot_titles=("Vehiculos en la ROI (promedio)", "Movimiento en la ROI (% de pixeles)"))
    fig.add_trace(go.Scatter(
        x=lecturas["x"], y=lecturas["vehiculos_roi"], mode="lines+markers", name="Lectura",
        line=dict(color=TINTA_2, width=2), marker=dict(size=8, color=TINTA_2, line=dict(color=SUPERFICIE, width=2)),
        customdata=lecturas[["hora", "estado"]].to_numpy(),
        hovertemplate="%{y:.1f} vehiculos<br>%{customdata[0]} · %{customdata[1]}<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=lecturas["x"], y=lecturas["movimiento_pct"], mode="lines+markers", name="Lectura", showlegend=False,
        line=dict(color=TINTA_2, width=2), marker=dict(size=8, color=TINTA_2, line=dict(color=SUPERFICIE, width=2)),
        customdata=lecturas[["hora", "estado"]].to_numpy(),
        hovertemplate="%{y:.1f} % en movimiento<br>%{customdata[0]} · %{customdata[1]}<extra></extra>",
    ), row=2, col=1)
    if not detenido.empty:
        for fila in (1, 2):
            fig.add_trace(go.Scatter(
                x=detenido["x"], y=detenido["vehiculos_roi" if fila == 1 else "movimiento_pct"],
                mode="markers", name="Trafico detenido", showlegend=(fila == 1),
                marker=dict(size=13, color=PUNTO_PICO, line=dict(color=SUPERFICIE, width=2)),
                hoverinfo="skip",
            ), row=fila, col=1)

    estilo_base(fig, alto=380)
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.08, xanchor="left", x=0,
                    font=dict(color=TINTA_2, size=13)),
        margin=dict(l=8, r=8, t=60, b=8),
    )
    fig.update_annotations(font=dict(color=TINTA_2, size=12), xanchor="left", x=0)
    fig.update_yaxes(rangemode="tozero")
    fig.update_xaxes(tickformat="%H:%M:%S")
    return fig


# ===========================================================================
# Pantalla principal
# ===========================================================================
def mostrar_dashboard(ruta: str, camaras: List[str], percentil: int) -> None:
    """Dibuja todo el contenido. Se separa para poder auto-refrescarlo (st.fragment)."""
    archivo = Path(ruta)
    if not archivo.is_absolute():
        archivo = RAIZ_PROYECTO / archivo

    if not camaras:
        st.info("Elige al menos una camara en la barra lateral.")
        return

    try:
        # `closing` cierra la conexion al terminar el bloque, haya o no errores.
        with closing(abrir_conexion(archivo)) as con:
            totales = consultar(con, SQL_TOTAL_POR_TIPO, camaras)
            velocidades = consultar(con, SQL_VELOCIDAD_POR_TIPO, camaras)
            puntos = consultar(con, SQL_PUNTOS_VELOCIDAD, camaras)
            rapidos = consultar(con, SQL_MAS_RAPIDOS, camaras)
            ultimo = consultar(con, SQL_ULTIMO_CRUCE, camaras).iloc[0, 0]
            tabla_completa = consultar(con, SQL_TABLA_COMPLETA, camaras)
            excesos = consultar(con, SQL_EXCESOS, camaras, antes=[LIMITE_VELOCIDAD_KMH])
            # Tablas nuevas: una base creada con una version anterior no las tiene.
            # En ese caso se muestran vacias en lugar de bloquear todo el panel.
            alertas = _consulta_opcional(con, SQL_ALERTAS, camaras)
            alertas_tipo = _consulta_opcional(con, SQL_ALERTAS_POR_TIPO, camaras)
            lecturas = _consulta_opcional(con, SQL_LECTURAS, camaras)
    except BaseDatosNoDisponibleError as exc:
        st.warning(str(exc))
        return

    total = int(totales["total"].sum()) if not totales.empty else 0
    if total == 0:
        st.info("La tabla `cruces` no tiene registros para las camaras elegidas. "
                "Ejecuta `python main.py` sobre un video.")
        return

    st.markdown('<p class="titulo">Aforo vehicular</p>', unsafe_allow_html=True)
    st.markdown(
        f'<p class="subtitulo">{archivo.name} · tabla cruces · {total} registros · '
        f'ultimo cruce {str(ultimo)[:19]}</p>',     # sin milisegundos
        unsafe_allow_html=True,
    )

    # ---- Tarjetas: total por tipo (resultado de SELECT ... GROUP BY tipo) ---
    por_clase = totales.set_index("tipo")["total"]
    columnas = st.columns(1 + len(ORDEN_CLASES))
    columnas[0].markdown(tarjeta("Total", total, "vehiculos contados", TINTA_2), unsafe_allow_html=True)
    for col, nombre in zip(columnas[1:], ORDEN_CLASES):
        n = int(por_clase.get(nombre, 0))
        col.markdown(
            tarjeta(nombre, n, f"{100 * n / total:.0f} % del total", COLOR_POR_CLASE[nombre]),
            unsafe_allow_html=True,
        )

    # ---- Resumen ejecutivo: los indicadores que le importan al cliente ------
    medidos = int(excesos.iloc[0]["medidos"])
    n_excesos = int(excesos.iloc[0]["excesos"])
    n_detenido = int(alertas_tipo.set_index("tipo")["total"].get("TRAFICO_DETENIDO", 0)) if not alertas_tipo.empty else 0
    velocidad_prom = f"{puntos['velocidad_kmh'].mean():.1f}" if not puntos.empty else "-"
    estado_actual = str(lecturas.iloc[-1]["estado"]) if not lecturas.empty else "-"
    resumen = st.columns(4)
    resumen[0].markdown(tarjeta("Velocidad promedio", velocidad_prom, f"km/h · {medidos} mediciones", TINTA_2),
                        unsafe_allow_html=True)
    resumen[1].markdown(
        tarjeta(f"Excesos (> {LIMITE_VELOCIDAD_KMH:g} km/h)", n_excesos,
                f"{100 * n_excesos / medidos:.0f} % de las mediciones" if medidos else "sin mediciones",
                PUNTO_PICO),
        unsafe_allow_html=True)
    resumen[2].markdown(
        tarjeta("Trafico detenido", n_detenido, "episodios con alerta", PUNTO_PICO), unsafe_allow_html=True)
    resumen[3].markdown(
        tarjeta("Estado de la via", estado_actual, "ultima lectura", TINTA_2), unsafe_allow_html=True)

    st.write("")

    # ---- Graficos de velocidad ---------------------------------------------
    if puntos.empty:
        st.info(
            "Ningun cruce tiene velocidad medida. Revisa que la linea de conteo quede dentro del "
            "tramo entre las lineas A y B (LINEA_VELOCIDAD_A / LINEA_VELOCIDAD_B en config.py)."
        )
    else:
        promedio_general = float(puntos["velocidad_kmh"].mean())
        col_barras, col_picos = st.columns([4, 8])

        with col_barras:
            with st.container(key="panel_barras"):
                titulo_panel(
                    "Velocidad promedio por tipo",
                    f"{len(puntos)} mediciones. La linea punteada es el promedio general: "
                    f"{promedio_general:.1f} km/h.",
                )
                figura = grafico_barras(velocidades, promedio_general)
                if figura is not None:
                    st.plotly_chart(figura, width="stretch", theme=None, config={"displayModeBar": False})
                sin_datos = [c for c in ORDEN_CLASES if c not in set(velocidades["tipo"])]
                if sin_datos:
                    st.caption("Sin mediciones: " + ", ".join(sin_datos))

        with col_picos:
            with st.container(key="panel_picos"):
                titulo_panel("Picos de velocidad en el tiempo",
                             "Cada punto es un vehiculo medido. Los amarillos superan el umbral de pico.")
                # SQLite no trae una funcion de percentil: el umbral se calcula con pandas.
                umbral = float(puntos["velocidad_kmh"].quantile(percentil / 100))
                st.plotly_chart(
                    grafico_dispersion(puntos, umbral, percentil),
                    width="stretch", theme=None, config={"displayModeBar": False},
                )

        # ---- Estado de la via y alertas ---------------------------------------
        st.write("")
        col_via, col_alertas = st.columns([6, 6])
        with col_via:
            with st.container(key="panel_via"):
                titulo_panel("Estado de la via en el tiempo",
                             "Lecturas periodicas del analisis de movimiento (resta de fondo, umbral y morfologia) "
                             "combinado con YOLO. Los puntos amarillos son lecturas con trafico detenido.")
                if lecturas.empty:
                    st.info("Aun no hay lecturas: se guardan cada pocos segundos de video (INTERVALO_LECTURA_S).")
                else:
                    st.plotly_chart(grafico_estado_via(lecturas), width="stretch", theme=None,
                                    config={"displayModeBar": False})
        with col_alertas:
            with st.container(key="panel_alertas"):
                titulo_panel("Alertas recientes",
                             "Exceso de velocidad y trafico detenido, de la mas reciente a la mas antigua.")
                if alertas.empty:
                    st.info("No se han registrado alertas con los umbrales actuales.")
                else:
                    tabla_alertas = pd.DataFrame({
                        "Hora": pd.to_datetime(alertas["momento"]).dt.strftime("%H:%M:%S"),
                        "Tipo": alertas["tipo"].map(ETIQUETA_ALERTA).fillna(alertas["tipo"]),
                        "Detalle": alertas["descripcion"],
                    })
                    st.dataframe(tabla_alertas, hide_index=True, width="stretch", height=330)

        # ---- Tabla de picos y datos completos -------------------------------
        st.write("")
        with st.container(key="panel_tabla"):
            titulo_panel("Mayores velocidades registradas",
                         "Los vehiculos mas rapidos y la hora en que cruzaron.")
            tabla = pd.DataFrame({
                "Hora": pd.to_datetime(rapidos["momento"]).dt.strftime("%H:%M:%S"),
                "ID de seguimiento": rapidos["track_id"],
                "Tipo": rapidos["tipo"],
                "Velocidad": rapidos["velocidad_kmh"],
                "Camara": rapidos["camara"],
            })
            st.dataframe(
                tabla, hide_index=True, width="stretch",
                column_config={"Velocidad": st.column_config.NumberColumn(format="%.1f km/h")},
            )
            with st.expander("Ver la tabla `cruces` completa"):
                st.dataframe(tabla_completa, hide_index=True, width="stretch")


def main() -> None:
    st.set_page_config(page_title="Aforo vehicular", layout="wide", initial_sidebar_state="auto")
    inyectar_css()

    # ---- Barra lateral: origen de datos y filtros ---------------------------
    st.sidebar.markdown("### Datos")
    ruta = st.sidebar.text_input("Base de datos SQLite", value=str(RAIZ_PROYECTO / DB_RUTA))
    auto = st.sidebar.toggle("Actualizar cada 5 s", value=False,
                             help="Vuelve a consultar la base de datos periodicamente "
                                  "(util mientras main.py esta procesando un video).")

    # Camaras disponibles: SELECT DISTINCT-like sobre la tabla.
    camaras_disponibles: List[str] = []
    archivo = Path(ruta) if Path(ruta).is_absolute() else RAIZ_PROYECTO / ruta
    try:
        with closing(abrir_conexion(archivo)) as con:
            camaras_disponibles = pd.read_sql_query(SQL_CAMARAS, con)["camara"].dropna().tolist()
    except (BaseDatosNoDisponibleError, pd.errors.DatabaseError, sqlite3.Error):
        pass    # mostrar_dashboard explica el problema con un mensaje claro

    st.sidebar.markdown("### Filtros")
    elegidas = st.sidebar.multiselect(
        "Camara", camaras_disponibles, default=camaras_disponibles,
        help="Fuente de video de los cruces (columna `camara`).",
    )
    percentil = st.sidebar.slider(
        "Umbral de pico (percentil)", 50, 99, 90,
        help="Una medicion es 'pico' si iguala o supera este percentil de las velocidades.",
    )

    if not camaras_disponibles:
        # Sin camaras no hay datos: mostrar el motivo (BD inexistente / tabla vacia).
        if auto:
            st.fragment(run_every="5s")(_mensaje_sin_datos)(str(archivo))
        else:
            _mensaje_sin_datos(str(archivo))
        return

    if auto:
        st.fragment(run_every="5s")(mostrar_dashboard)(ruta, elegidas, percentil)
    else:
        mostrar_dashboard(ruta, elegidas, percentil)


def _mensaje_sin_datos(ruta: str) -> None:
    """Explica por que no hay nada que mostrar (BD inexistente o tabla vacia)."""
    try:
        with closing(abrir_conexion(Path(ruta))):
            pass
    except BaseDatosNoDisponibleError as exc:
        st.warning(str(exc))
        return
    st.info("La base de datos existe pero la tabla `cruces` esta vacia o no existe. "
            "Ejecuta `python main.py` sobre un video.")


main()
