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
# Estilo "terminal de datos" (pantalla de monitoreo para sesiones largas): tarjetas MAS
# OSCURAS que el fondo, bordes de 1 px, cifras tabulares, sin sombras ni gradientes, y el
# color reservado para los datos. Un solo acento (azul) y solo como linea de 1 px en lo
# que esta seleccionado.
PAGINA = "#171719"            # fondo de la pagina
SUPERFICIE = "#131217"        # tarjetas y paneles (mas oscuros que el fondo)
ELEVADO = "#212023"           # un escalon mas claro (hover, chips)
BORDE = "#222224"
REGLA = "#1b1a1f"             # divisores entre celdas
CONTROL = "#3a3a3e"           # borde de los controles
TINTA = "#ffffff"             # texto principal
TINTA_2 = "#bdbdc0"           # texto secundario
TINTA_SUAVE = "#8a8c92"       # etiquetas, ejes (>= 4.5:1 sobre la superficie)
REJILLA = "#2b2b2b"           # lineas de cuadricula (4-5, muy tenues)
EJE = "#3a3a3e"               # linea base de los ejes
ACENTO = "#4a8ad6"            # unico acento: seleccion de 1 px
SERIE = "#f2f2f3"             # serie neutra de los graficos
PUNTO_NORMAL = "#8a8c92"      # mediciones normales en el scatter
PUNTO_PICO = "#d9a441"        # picos de velocidad / alertas (color de estado)
FUENTE = '"Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif'

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
    """
    Estilos del panel (estilo "terminal de datos"). Reglas que se siguen:
      * cifras tabulares (los digitos no "bailan" al actualizarse);
      * tarjetas mas oscuras que el fondo, borde de 1 px, sin sombras ni degradados;
      * las franjas de KPI son UN contenedor dividido por lineas finas, no tarjetas sueltas;
      * movimiento solo como respuesta a una accion (hover/foco), con la escala de
        transiciones del curso: 250 ms y curva suave de salida.
    """
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600;700&display=swap');

        :root {{
            --duracion-rapida: 250ms;                          /* --duration-fast */
            --suave: cubic-bezier(0.22, 1, 0.36, 1);           /* --ease-smooth-out */
        }}
        /* La fuente se fija solo en .stApp (los hijos la heredan). No usar un selector
           comodin: pisaria la fuente de iconos de Streamlit y mostraria "_arrow_right". */
        .stApp {{
            background: {PAGINA}; color: {TINTA}; font-family: {FUENTE};
            font-variant-numeric: tabular-nums; font-size: 13px;
        }}
        header[data-testid="stHeader"] {{ background: transparent; }}
        footer, #MainMenu {{ visibility: hidden; }}
        .block-container {{ padding: 28px 32px 48px; max-width: 1320px; }}

        /* ---------- barra lateral: queda en segundo plano ---------- */
        section[data-testid="stSidebar"] {{
            background: {PAGINA}; border-right: 1px solid {BORDE};
        }}
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {{
            font-size: 12px; font-weight: 500; color: {TINTA_SUAVE}; margin: 22px 0 4px;
        }}
        .marca {{ display: flex; align-items: center; gap: 12px; padding: 4px 0 8px; }}
        .marca-nombre {{ font-size: 16px; font-weight: 600; line-height: 1.2; }}
        .marca-ambito {{ font-size: 12px; color: {TINTA_SUAVE}; }}

        /* Controles: borde de 1 px; la seleccion es una linea de 1 px del acento. */
        [data-baseweb="input"], [data-baseweb="select"] > div {{
            background: {SUPERFICIE}; border: 1px solid {CONTROL}; border-radius: 6px;
            transition: border-color var(--duracion-rapida) var(--suave);
        }}
        [data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within,
        [data-baseweb="input"]:hover, [data-baseweb="select"] > div:hover {{ border-color: {ACENTO}; }}
        [data-baseweb="tag"] {{
            background: {ELEVADO} !important; color: {TINTA} !important; border-radius: 999px;
            border: 1px solid {CONTROL};
        }}

        /* ---------- encabezado de pantalla ---------- */
        [data-testid="stMarkdownContainer"] p.titulo {{
            color: {TINTA}; font-size: 26px; font-weight: 600; margin: 0; line-height: 1.2;
            letter-spacing: -0.01em;
        }}
        [data-testid="stMarkdownContainer"] p.subtitulo {{
            color: {TINTA_SUAVE}; font-size: 14px; margin: 6px 0 22px; line-height: 1.5;
        }}
        p.subtitulo b {{ color: {TINTA}; font-weight: 500; }}

        /* ---------- franjas de KPI: un contenedor, celdas divididas por 1 px ---------- */
        .franja {{
            display: grid; background: {SUPERFICIE}; border: 1px solid {BORDE};
            border-radius: 6px; overflow: hidden; margin-bottom: 12px;
        }}
        .franja.f5 {{ grid-template-columns: 1.5fr repeat(4, 1fr); }}
        .franja.f4 {{ grid-template-columns: repeat(4, 1fr); }}
        .celda-kpi {{
            padding: 16px 20px; border-left: 1px solid {REGLA}; min-width: 0;
            transition: background var(--duracion-rapida) var(--suave);
        }}
        .celda-kpi:first-child {{ border-left: 0; }}
        .celda-kpi:hover {{ background: {ELEVADO}; }}
        .kpi-etiqueta {{ color: {TINTA_SUAVE}; font-size: 12px; display: flex; align-items: center; gap: 8px; }}
        .punto {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex: none; }}
        .kpi-valor {{ color: {TINTA}; font-size: 22px; font-weight: 400; line-height: 1.2; margin: 6px 0 2px; }}
        .celda-kpi.guia .kpi-valor {{ font-size: 34px; font-weight: 500; }}   /* la cifra que responde la pregunta */
        .kpi-unidad {{ color: {TINTA_SUAVE}; font-size: 13px; margin-left: 4px; }}
        .kpi-detalle {{ color: {TINTA_SUAVE}; font-size: 12px; }}

        /* ---------- paneles (cada grafico/tabla) ---------- */
        .st-key-panel_barras, .st-key-panel_picos, .st-key-panel_tabla,
        .st-key-panel_via, .st-key-panel_alertas {{
            background: {SUPERFICIE}; border: 1px solid {BORDE}; border-radius: 6px;
            padding: 18px 22px 16px;
        }}
        [data-testid="stMarkdownContainer"] p.panel-titulo {{
            color: {TINTA}; font-size: 16px; font-weight: 600; margin: 0;
        }}
        [data-testid="stMarkdownContainer"] p.panel-texto {{
            color: {TINTA_SUAVE}; font-size: 13px; margin: 4px 0 10px; line-height: 1.5;
        }}
        [data-testid="stExpander"] details {{ border: 1px solid {BORDE}; border-radius: 6px; background: {PAGINA}; }}
        [data-testid="stExpander"] summary {{ transition: background var(--duracion-rapida) var(--suave); }}
        [data-testid="stExpander"] summary:hover {{ background: {ELEVADO}; }}

        /* ---------- tira de estado de la via: lo que solo este producto tiene ---------- */
        .tira {{ display: flex; gap: 2px; height: 26px; margin: 4px 0 8px; }}
        .tira span {{ flex: 1; border-radius: 2px; min-width: 2px; }}
        .tira .libre {{ background: {ELEVADO}; }}
        .tira .fluido {{ background: #6b6e76; }}
        .tira .detenido {{ background: {PUNTO_PICO}; }}
        .tira-leyenda {{ display: flex; gap: 16px; color: {TINTA_SUAVE}; font-size: 12px; margin-bottom: 8px; }}
        .tira-leyenda i {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }}

        @media (max-width: 900px) {{
            .franja.f5, .franja.f4 {{ grid-template-columns: repeat(2, 1fr); }}
            .celda-kpi {{ border-top: 1px solid {REGLA}; }}
            .block-container {{ padding: 20px 16px 40px; }}
        }}
        @media (prefers-reduced-motion: reduce) {{
            .celda-kpi, [data-baseweb="input"], [data-baseweb="select"] > div,
            [data-testid="stExpander"] summary {{ transition: none; }}
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
def celda_kpi(etiqueta: str, valor: object, detalle: str, punto: str = "",
              unidad: str = "", guia: bool = False) -> str:
    """HTML de una celda de KPI: etiqueta, cifra (tinta clara, nunca coloreada) y detalle gris."""
    marca = f'<span class="punto" style="background:{punto}"></span>' if punto else ""
    sufijo = f'<span class="kpi-unidad">{unidad}</span>' if unidad else ""
    return (
        f'<div class="celda-kpi{" guia" if guia else ""}">'
        f'<div class="kpi-etiqueta">{marca}{etiqueta}</div>'
        f'<div class="kpi-valor">{valor}{sufijo}</div>'
        f'<div class="kpi-detalle">{detalle}</div></div>'
    )


def franja(celdas: Sequence[str], columnas: int) -> str:
    """Un solo contenedor con las celdas separadas por lineas finas (no tarjetas sueltas)."""
    return f'<div class="franja f{columnas}">{"".join(celdas)}</div>'


def tira_estado(lecturas: pd.DataFrame) -> str:
    """
    Elemento propio del producto: el estado de la via lectura a lectura. Cada celda es un
    intervalo (INTERVALO_LECTURA_S); ambar = trafico detenido. Se ve de un vistazo cuando
    y por cuanto tiempo la via estuvo parada.
    """
    celdas = []
    for fila in lecturas.itertuples():
        hora = pd.to_datetime(fila.momento).strftime("%H:%M:%S")
        estado = str(fila.estado)
        celdas.append(
            f'<span class="{estado.lower()}" title="{hora} · {estado.capitalize()} · '
            f'{fila.vehiculos_roi:.1f} vehiculos en la ROI"></span>'
        )
    leyenda = (
        f'<div class="tira-leyenda"><span><i style="background:{ELEVADO}"></i>Libre</span>'
        f'<span><i style="background:#6b6e76"></i>Fluido</span>'
        f'<span><i style="background:{PUNTO_PICO}"></i>Detenido</span></div>'
    )
    return f'<div class="tira">{"".join(celdas)}</div>{leyenda}'


def estilo_base(fig: go.Figure, alto: int) -> go.Figure:
    """Aplica el aspecto comun (oscuro, ejes discretos, tooltip legible)."""
    fig.update_layout(
        height=alto,
        margin=dict(l=8, r=8, t=28, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FUENTE, color=TINTA_SUAVE, size=12),
        hoverlabel=dict(bgcolor=SUPERFICIE, bordercolor=CONTROL,
                        font=dict(family=FUENTE, color=TINTA, size=13)),
    )
    # `automargin` hace que Plotly reserve espacio para las etiquetas de los ejes;
    # sin el, con margenes pequenos las etiquetas quedan recortadas.
    # Sin linea de eje Y, 4-5 lineas de cuadricula tenues y texto de ejes en gris legible.
    fig.update_xaxes(showgrid=False, linecolor=EJE, tickcolor=EJE, zeroline=False,
                     automargin=True, title_standoff=10)
    fig.update_yaxes(gridcolor=REJILLA, gridwidth=1, zeroline=False, showline=False,
                     automargin=True, title_standoff=10, nticks=5)
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
    fig.update_layout(showlegend=False, barcornerradius=2)
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
        line=dict(color=SERIE, width=2), marker=dict(size=6, color=SERIE, line=dict(color=SUPERFICIE, width=2)),
        customdata=lecturas[["hora", "estado"]].to_numpy(),
        hovertemplate="%{y:.1f} vehiculos<br>%{customdata[0]} · %{customdata[1]}<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=lecturas["x"], y=lecturas["movimiento_pct"], mode="lines+markers", name="Lectura", showlegend=False,
        line=dict(color=SERIE, width=2), marker=dict(size=6, color=SERIE, line=dict(color=SUPERFICIE, width=2)),
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

    estilo_base(fig, alto=320)
    fig.update_layout(
        showlegend=False,   # la leyenda esta en la tira de estado, encima
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

    # ---- Datos de las franjas y del hallazgo -------------------------------------
    por_clase = totales.set_index("tipo")["total"]
    medidos = int(excesos.iloc[0]["medidos"])
    n_excesos = int(excesos.iloc[0]["excesos"])
    n_detenido = int(alertas_tipo.set_index("tipo")["total"].get("TRAFICO_DETENIDO", 0)) if not alertas_tipo.empty else 0
    velocidad_prom = f"{puntos['velocidad_kmh'].mean():.1f}" if not puntos.empty else "-"
    estado_actual = str(lecturas.iloc[-1]["estado"]).capitalize() if not lecturas.empty else "-"

    # ---- Encabezado: el titulo es un sustantivo y la linea de abajo es EL HALLAZGO --------
    st.markdown('<p class="titulo">Aforo vehicular</p>', unsafe_allow_html=True)
    plural = lambda n, uno, varios: f"{n} {uno if n == 1 else varios}"  # noqa: E731
    st.markdown(
        f'<p class="subtitulo"><b>{plural(total, "vehiculo contado", "vehiculos contados")}</b> · '
        f'<b>{plural(n_excesos, "exceso", "excesos")}</b> de velocidad sobre {LIMITE_VELOCIDAD_KMH:g} km/h · '
        f'<b>{plural(n_detenido, "episodio", "episodios")}</b> de trafico detenido · '
        f'ultimo cruce {str(ultimo)[:19]} · {", ".join(camaras)}</p>',
        unsafe_allow_html=True,
    )

    # ---- Franja 1: aforo por tipo (SELECT ... GROUP BY tipo). La cifra total manda. -------
    celdas = [celda_kpi("Total", total, "vehiculos que cruzaron la linea", guia=True)]
    for nombre in ORDEN_CLASES:
        n = int(por_clase.get(nombre, 0))
        celdas.append(celda_kpi(nombre, n, f"{100 * n / total:.0f} % del total", punto=COLOR_POR_CLASE[nombre]))
    st.markdown(franja(celdas, 5), unsafe_allow_html=True)

    # ---- Franja 2: velocidad y estado de la via ------------------------------------------
    st.markdown(franja([
        celda_kpi("Velocidad promedio", velocidad_prom, f"{medidos} mediciones", unidad="km/h"),
        celda_kpi(f"Excesos sobre {LIMITE_VELOCIDAD_KMH:g} km/h", n_excesos,
                  f"{100 * n_excesos / medidos:.0f} % de las mediciones" if medidos else "sin mediciones"),
        celda_kpi("Trafico detenido", n_detenido, "episodios con alerta"),
        celda_kpi("Estado de la via", estado_actual, "ultima lectura del analisis de movimiento"),
    ], 4), unsafe_allow_html=True)

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
                    st.markdown(tira_estado(lecturas), unsafe_allow_html=True)
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
                    st.dataframe(tabla_alertas, hide_index=True, width="stretch", height=min(330, 38 + 35 * len(tabla_alertas)))

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
    # Marca del producto (dibujada para este producto): dos lineas, A y B, con un vehiculo
    # entre ellas, que es lo que mide el sistema (la ROI), mas el ambito de datos activo.
    st.sidebar.markdown(
        f"""
        <div class="marca">
          <svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true">
            <line x1="4" y1="8" x2="26" y2="8" stroke="{ACENTO}" stroke-width="2" stroke-linecap="round"/>
            <line x1="4" y1="22" x2="26" y2="22" stroke="{TINTA_SUAVE}" stroke-width="2" stroke-linecap="round"/>
            <rect x="11" y="12" width="8" height="6" rx="2" fill="{SERIE}"/>
          </svg>
          <div><div class="marca-nombre">Aforo vial</div>
          <div class="marca-ambito">Camara fija · conteo y velocidad</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
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
