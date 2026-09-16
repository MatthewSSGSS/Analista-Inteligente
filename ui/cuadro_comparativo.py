"""Pestaña "📊 Cuadro comparativo": varios elementos, la misma vara, un vistazo.

El cálculo vive en `core/cuadro_comparativo.py`; aquí solo se pinta. El orden
de la pantalla es el de la pregunta "¿cómo va cada uno?":

1. Qué se compara: por qué columna, con qué métrica y a quiénes.
1b. La base de la comparación en palabras: a quiénes, qué se mide, contra
   qué, en qué periodo, cómo se lee el color y con cuántos registros. Sin
   esto el ranking decía quién iba primero pero no "primero en qué".
2. Cuatro tarjetas: quién va primero, quién va último, la distancia entre
   ellos y cuántos están bien.
3. El gráfico de cómo va cada uno, con la meta o el promedio como línea de
   referencia, y su evolución mes a mes si el archivo tiene fechas.
4. El cuadro con todas las cifras y el veredicto de cada uno en palabras.
5. La lectura: las conclusiones con nombre y cifra.

Los colores dicen lo mismo que la columna Estado —verde bien, ámbar cerca,
rojo mal— para que se lea igual sin distinguir colores.
"""
from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.cuadro_comparativo import (MAX_ELEGIDOS, UMBRAL_PROMEDIO, base_de_comparacion, cuadro_comparativo,
                                     opciones_de_comparacion)
from core.diagnostics import METRICA_CONTEO, _fmt
from core.filter_engine import describir_regla
from ui.components.cards import kpi_card
from ui.components.charts import chart_card, empty_state
from ui.components.section import section_header
from visualization.charts import CATEGORY_PALETTE, _base, metric_candidates, realzar_barras

# Misma paleta de salud que la Estrategia por canal (ui/comercial.py).
COLOR_TONO = {"bueno": "#22A06B", "medio": "#F59E0B", "malo": "#E4002B"}
ICONO_TONO = {"bueno": "🟢", "medio": "🟡", "malo": "🔴"}
_ETIQUETA_CONTEO = "Cantidad de registros"
# Margen inferior de los gráficos. La caja .stPlotlyChart del tema suma
# relleno sobre la altura de la figura y, con el margen corto de _base, las
# etiquetas del eje de abajo quedaban cortadas a la mitad.
_MARGEN_EJE = 44


def _pct(v, signo=False) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:+.1f}%" if signo else f"{v:,.0f}%"


def _css() -> None:
    # Solo variables del tema: así el bloque se ve bien en Claro y en Oscuro.
    st.markdown(
        """
        <style>
        .cuadro-base{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-md);
          padding:14px 16px 12px;margin:6px 0 14px;box-shadow:var(--shadow-sm)}
        .cuadro-base-titulo{font-size:10.5px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;
          color:var(--muted);margin-bottom:10px}
        /* Tres columnas: las seis preguntas quedan en dos filas parejas. */
        .cuadro-base-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px 22px}
        @media (max-width:900px){.cuadro-base-grid{grid-template-columns:1fr}}
        .cuadro-base-item{display:flex;gap:9px;align-items:flex-start}
        .cuadro-base-icono{font-size:16px;line-height:1.3}
        .cuadro-base-item b{display:block;font-size:12px;color:var(--text);margin-bottom:3px}
        .cuadro-base-item .cuadro-base-texto{display:block;font-size:12.5px;line-height:1.5 !important;
          color:var(--muted);margin:0}
        /* Los nombres de punto de venta ocupan dos líneas y la regla general
           de .kpi-card (altura al 100% de la fila) cortaba la cifra de abajo.
           Solo en esta pestaña, las tarjetas crecen con su texto. */
        .st-key-cuadro_kpis .kpi-card{height:auto !important;min-height:100%}
        .st-key-cuadro_kpis{padding-bottom:22px}
        .st-key-cuadro_kpis [data-testid="stElementContainer"]:has(.kpi-card) > div,
        .st-key-cuadro_kpis [data-testid="stElementContainer"]:has(.kpi-card) > div > div,
        .st-key-cuadro_kpis [data-testid="stElementContainer"]:has(.kpi-card) > div > div > div{height:auto !important}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _filtros_activos() -> list[str]:
    """Los filtros del menú lateral en frases, igual que bajo el contador de filtros."""
    try:
        reglas = st.session_state.get("filters", {}) or {}
    except Exception:
        return []
    frases = [describir_regla(c, r) for c, r in reglas.items() if not str(c).startswith("__")]
    return [f for f in frases if f]


def _base_de_comparacion(cuadro: dict) -> None:
    items = "".join(
        f'<div class="cuadro-base-item"><span class="cuadro-base-icono">{b["icono"]}</span>'
        f'<div><b>{html.escape(b["titulo"])}</b><div class="cuadro-base-texto">{html.escape(b["texto"])}</div></div></div>'
        for b in base_de_comparacion(cuadro, _filtros_activos())
    )
    st.markdown(f'<div class="cuadro-base"><div class="cuadro-base-titulo">Base de la comparación</div>'
                f'<div class="cuadro-base-grid">{items}</div></div>', unsafe_allow_html=True)


def _controles(df: pd.DataFrame, schema: dict):
    """Por qué columna, con qué métrica y a quiénes.

    Devuelve (dimensión, métrica, elegidos, manual). `manual` dice si la
    lista la armó el usuario o sigue siendo la sugerida, para que la base de
    la comparación explique por qué están esos y no otros.
    """
    hoja = st.session_state.get("active_sheet", "")
    opciones = opciones_de_comparacion(df, schema)
    if not opciones:
        return None, None, None, False
    metricas = [m for m in metric_candidates(df, schema) if m in df.columns] + [METRICA_CONTEO]

    a, b = st.columns(2)
    with a:
        dimension = st.selectbox(
            "Comparar por", opciones, key=f"cuadro_dim_{hoja}",
            help="La columna que nombra a quienes se comparan: vendedores, asesores, regiones, puntos…",
        )
    with b:
        # La clave incluye la métrica elegida en el menú lateral: si se cambia
        # allí, esta pestaña la sigue en vez de quedarse con la anterior.
        metrica = st.selectbox(
            "Métrica", metricas, key=f"cuadro_met_{hoja}_{schema.get('metrica_preferida')}",
            format_func=lambda m: _ETIQUETA_CONTEO if m == METRICA_CONTEO else str(m),
        )

    # Primero se calcula con la sugerencia, solo para conocer el orden de
    # todos los elementos y ofrecerlos en ese orden en la lista.
    previo = cuadro_comparativo(df, schema, dimension, metrica)
    if previo is None:
        return dimension, metrica, None, False

    clave_sel = f"cuadro_sel_{hoja}_{dimension}"
    # Los filtros pueden dejar fuera a alguien que estaba elegido: Streamlit
    # falla si el valor guardado no está entre las opciones, así que se limpia
    # antes de dibujar la lista. Solo se toca si de verdad sobra alguien: si
    # fue el usuario quien dejó uno solo, se respeta y se le pide otro.
    if clave_sel in st.session_state:
        guardados = list(st.session_state[clave_sel])
        vigentes = [n for n in guardados if n in previo["opciones"]]
        if len(vigentes) != len(guardados):
            if len(vigentes) < 2:
                st.session_state.pop(clave_sel)
            else:
                st.session_state[clave_sel] = vigentes
    elegidos = st.multiselect(
        f"Elementos a comparar · {previo['total_opciones']} disponibles",
        previo["opciones"],
        default=previo["sugeridos"] if clave_sel not in st.session_state else None,
        key=clave_sel,
        max_selections=MAX_ELEGIDOS,
        placeholder="Elige al menos dos…",
        help=f"Hasta {MAX_ELEGIDOS}. La lista va ordenada de mejor a peor resultado.",
    )
    return dimension, metrica, elegidos, sorted(elegidos) != sorted(previo["sugeridos"])


def _kpis(cuadro: dict) -> None:
    filas = cuadro["filas"]
    primero, ultimo = filas[0], filas[-1]
    n = len(filas)
    # Cada cifra dice contra qué se mide: "492.5K" solo no dice si es mucho.
    if cuadro["base"] == "meta":
        cifra = lambda f: (f"{_pct(f['cumplimiento'])} de su meta · {_fmt(f['valor'])} de {_fmt(f['meta'])}"
                           if f["cumplimiento"] is not None else f"{_fmt(f['valor'])} · sin meta en el archivo")
        # Quien no tiene meta queda al final del orden: la distancia se mide
        # entre los que sí la tienen.
        con_meta = [f for f in filas if f["cumplimiento"] is not None]
        brecha = f"{abs(con_meta[0]['cumplimiento'] - con_meta[-1]['cumplimiento']):,.0f} pts"
        brecha_detalle = f"de cumplimiento: {_pct(con_meta[0]['cumplimiento'])} contra {_pct(con_meta[-1]['cumplimiento'])}"
        bien = sum(1 for f in filas if f["tono"] == "bueno")
        cuarta = ("Dentro de su meta", f"{bien} de {n}", "bueno" if bien == n else "malo" if bien == 0 else "medio",
                  "con 100% o más de cumplimiento")
    else:
        def cifra(f):
            if f["vs_promedio"] is None:
                return _fmt(f["valor"])
            lado = "sobre" if f["vs_promedio"] >= 0 else "bajo"
            return f"{_fmt(f['valor'])} · {abs(f['vs_promedio']):.0f}% {lado} el promedio"
        brecha = _fmt(abs(primero["valor"] - ultimo["valor"]))
        # Corto a propósito: la tarjeta tiene alto fijo y un texto largo se cortaba.
        proporcion = (f" · último = {ultimo['valor'] / primero['valor'] * 100:.0f}% del 1.º"
                      if primero["valor"] > 0 and not cuadro["menos_es_mejor"] else "")
        brecha_detalle = f"{_fmt(primero['valor'])} vs. {_fmt(ultimo['valor'])}{proporcion}"
        bien = sum(1 for f in filas if f["tono"] != "malo")
        cuarta = ("En o sobre el promedio" if not cuadro["menos_es_mejor"] else "En o bajo el promedio",
                  f"{bien} de {n}", "bueno" if bien == n else "medio",
                  f"promedio de los {n}: {_fmt(cuadro['promedio'])} (margen ±{UMBRAL_PROMEDIO:.0f}%)")
    tono_kpi = {"bueno": "positive", "medio": "neutral", "malo": "negative"}
    # El key da la clase .st-key-cuadro_kpis que usa el CSS de _css().
    with st.container(key="cuadro_kpis"):
        c1, c2, c3, c4 = st.columns(4)
    c1.markdown(kpi_card("🥇 Va primero", html.escape(primero["nombre"]), delta=cifra(primero),
                         tone="positive", small_value=True), unsafe_allow_html=True)
    c2.markdown(kpi_card("Va último", html.escape(ultimo["nombre"]), delta=cifra(ultimo),
                         tone="negative", small_value=True), unsafe_allow_html=True)
    c3.markdown(kpi_card("Distancia primero–último", brecha, delta=brecha_detalle), unsafe_allow_html=True)
    c4.markdown(kpi_card(cuarta[0], cuarta[1], delta=cuarta[3], tone=tono_kpi[cuarta[2]]), unsafe_allow_html=True)


def figura_ranking(cuadro: dict):
    """Una barra por elemento, el mejor arriba, con la meta o el promedio como referencia."""
    filas = list(reversed(cuadro["filas"]))  # Plotly dibuja de abajo hacia arriba
    por_meta = cuadro["base"] == "meta"
    x = [f["cumplimiento"] if por_meta else f["valor"] for f in filas]
    # Junto a cada barra, la cifra Y contra qué se mide: sin la segunda parte
    # "492.5K" no dice si es mucho o poco.
    if por_meta:
        texto = [f"{_pct(f['cumplimiento'])} · {_fmt(f['valor'])} de {_fmt(f['meta'])}" if f["meta"] else "sin meta"
                 for f in filas]
    else:
        texto = [_fmt(f["valor"]) + (f" · {f['vs_promedio']:+.0f}% vs. prom." if f["vs_promedio"] is not None else "")
                 for f in filas]
    detalle = [f"{f['registros']:,} registros · {f['estado']}" for f in filas]
    fig = go.Figure(go.Bar(
        x=x, y=[f["nombre"] for f in filas], orientation="h",
        marker=dict(color=[COLOR_TONO[f["tono"]] for f in filas], line=dict(width=0)),
        text=texto, textposition="outside", cliponaxis=False, customdata=detalle,
        hovertemplate="<b>%{y}</b><br>%{text}<br>%{customdata}<extra></extra>",
    ))
    fig.update_layout(showlegend=False, bargap=.3)
    fig.update_xaxes(tickformat="~s" if not por_meta else None, ticksuffix="%" if por_meta else "")
    fig = _base(fig, max(300, 42 * len(filas) + 110), show_xgrid=True)
    # _base pone el hover unificado por eje, pensado para series en el
    # tiempo; en un ranking cada barra es su propio dato. Margen arriba para
    # el rótulo de la referencia.
    fig.update_layout(hovermode="closest", margin=dict(t=40, b=_MARGEN_EJE))
    # Espacio a la derecha para el texto de la barra más larga.
    validos = [v for v in x if v is not None and pd.notna(v)]
    if validos and min(validos) >= 0:
        fig.update_xaxes(range=[0, max(max(validos), cuadro["referencia"]) * 1.3])
    referencia = cuadro["referencia"]
    fig = realzar_barras(fig, referencia=referencia)
    # El rótulo de la línea va por encima del gráfico y no dentro: dentro
    # quedaba montado sobre la primera barra y no se leía.
    n = len(filas)
    texto_ref = "meta 100%" if por_meta else f"promedio de los {n}: {_fmt(referencia)}"
    fig.add_annotation(x=referencia, y=1, xref="x", yref="paper", yanchor="bottom", showarrow=False,
                       text=f"┆ {texto_ref}", font=dict(size=11, color="#64748B"))
    return fig


def figura_evolucion(cuadro: dict):
    """Una línea por elemento, mes a mes. None si hay menos de dos meses."""
    if len(cuadro["periodos"]) < 2:
        return None
    fig = go.Figure()
    for i, f in enumerate(cuadro["filas"]):
        if not f["serie"]:
            continue
        puntos = sorted(f["serie"].items())
        color = CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)]
        fig.add_trace(go.Scatter(
            x=[p for p, _ in puntos], y=[v for _, v in puntos], mode="lines+markers", name=f["nombre"],
            line=dict(color=color, width=2.8), marker=dict(size=6, color=color),
            hovertemplate=f"<b>{html.escape(f['nombre'])}</b>: %{{y:,.0f}}<extra></extra>",
        ))
    if not fig.data:
        return None
    # Una marca por mes: con pocos meses Plotly repetía la misma etiqueta.
    fig.update_xaxes(tickformat="%b %Y", dtick="M1")
    fig.update_yaxes(tickformat="~s", title=None)
    return _base(fig, 380).update_layout(margin=dict(b=_MARGEN_EJE))


def figura_meta(cuadro: dict):
    """Resultado contra meta, en barras pareadas. None si no hay meta."""
    filas = [f for f in cuadro["filas"] if f["meta"] is not None]
    if cuadro["base"] != "meta" or len(filas) < 2:
        return None
    nombres = [f["nombre"] for f in filas]
    fig = go.Figure([
        go.Bar(name="Resultado", x=nombres, y=[f["valor"] for f in filas],
               marker_color=[COLOR_TONO[f["tono"]] for f in filas],
               text=[_fmt(f["valor"]) for f in filas], textposition="outside", cliponaxis=False),
        go.Bar(name="Meta", x=nombres, y=[f["meta"] for f in filas], marker_color="#94A3B8",
               text=[_fmt(f["meta"]) for f in filas], textposition="outside", cliponaxis=False),
    ])
    fig.update_layout(barmode="group", bargap=.28, bargroupgap=.08)
    fig.update_yaxes(tickformat="~s", title=None)
    return realzar_barras(_base(fig, 380).update_layout(margin=dict(b=_MARGEN_EJE)), horizontal=False)


def tabla_cuadro(cuadro: dict) -> pd.DataFrame:
    """El cuadro como tabla, con las columnas que aplican a este archivo."""
    etiqueta = _ETIQUETA_CONTEO if cuadro["conteo"] else str(cuadro["metrica"])
    filas = []
    for f in cuadro["filas"]:
        fila = {"#": f["posicion"], str(cuadro["dimension"]): f["nombre"], etiqueta: _fmt(f["valor"])}
        if cuadro["base"] == "meta":
            fila["Meta"] = _fmt(f["meta"])
            fila["Cumplimiento"] = round(f["cumplimiento"], 1) if f["cumplimiento"] is not None else None
        if cuadro["aditiva"]:
            fila["Participación"] = round(f["participacion"], 1) if f["participacion"] is not None else None
        if not cuadro["conteo"]:
            fila["Registros"] = f["registros"]
            if cuadro["aviso"]:
                fila["Promedio por registro"] = _fmt(f["por_registro"])
        if cuadro["base"] != "meta":
            fila["Vs. promedio"] = _pct(f["vs_promedio"], signo=True)
        if cuadro["periodo_label"]:
            fila[f"Variación {cuadro['periodo_label']}"] = _pct(f["variacion"], signo=True)
        fila["Estado"] = f"{ICONO_TONO[f['tono']]} {f['estado']}"
        filas.append(fila)
    return pd.DataFrame(filas)


def render_cuadro_comparativo(df: pd.DataFrame, schema: dict) -> None:
    st.markdown(section_header(
        "Cuadro comparativo", eyebrow="COMPARACIÓN",
        subtitle="Elige a quiénes comparar y mira cómo va cada uno con la misma vara: su meta si el archivo la trae, "
                 "o el promedio del grupo si no.",
    ), unsafe_allow_html=True)

    _css()
    dimension, metrica, elegidos, manual = _controles(df, schema)
    if dimension is None:
        empty_state("Este archivo no tiene una columna con nombres o categorías para comparar entre sí.")
        return
    if elegidos is not None and len(elegidos) < 2:
        empty_state("Elige al menos dos elementos para armar el cuadro.")
        return
    # Si la lista sigue siendo la sugerida, se calcula como sugerida: así la
    # base de la comparación dice "los 8 con mejor resultado" y no "elegidos por ti".
    cuadro = cuadro_comparativo(df, schema, dimension, metrica, seleccion=elegidos if manual else None)
    if cuadro is None:
        empty_state("Con la selección y los filtros actuales no quedan al menos dos elementos con datos para comparar.")
        return

    _base_de_comparacion(cuadro)
    _kpis(cuadro)
    etiqueta = _ETIQUETA_CONTEO if cuadro["conteo"] else str(cuadro["metrica"])
    n = len(cuadro["filas"])
    como = "cantidad de registros" if cuadro["conteo"] else (
        f"{etiqueta} total (suma)" if cuadro["aditiva"] else f"{etiqueta} promedio")
    periodo = (f" · {cuadro['desde']:%d/%m/%Y}–{cuadro['hasta']:%d/%m/%Y}" if cuadro["desde"] is not None else "")

    orden = "de menor a mayor (aquí menos es mejor)" if cuadro["menos_es_mejor"] else "de mayor a menor"
    if cuadro["base"] == "meta":
        subtitulo = (f"Cumplimiento = {etiqueta} ÷ {cuadro['meta_col']}, {orden} · "
                     f"línea punteada = 100% de la meta{periodo}")
    else:
        subtitulo = (f"{como} por {dimension}, {orden} · línea punteada = promedio de los {n} "
                     f"({_fmt(cuadro['promedio'])}){periodo}")
    chart_card(f"Cómo va cada uno · {dimension}", subtitulo, figura_ranking(cuadro),
               key="cuadro_ranking", visual_type="COMPARACIÓN", badge_text=f"{n} elegidos")

    evolucion = figura_evolucion(cuadro)
    if evolucion is not None:
        suma_mes = "sumada" if cuadro["aditiva"] else "promediada"
        chart_card("Evolución mes a mes",
                   f"{etiqueta} {suma_mes} por mes · una línea por cada {dimension} elegido",
                   evolucion, key="cuadro_evolucion", visual_type="TENDENCIA",
                   badge_text=f"{len(cuadro['periodos'])} meses")
    meta = figura_meta(cuadro)
    if meta is not None:
        chart_card("Resultado frente a meta",
                   f"Barra de color = {etiqueta} logrado · barra gris = {cuadro['meta_col']} (lo que se esperaba)",
                   meta, key="cuadro_meta", visual_type="META", badge_text="Resultado vs. meta")

    st.markdown(section_header("El cuadro", compact=True), unsafe_allow_html=True)
    tabla = tabla_cuadro(cuadro)
    # Cada columna explica de dónde sale su cifra al pasar el cursor por el título.
    ayudas = {
        "#": "Posición en el orden del cuadro" + (" (por cumplimiento de meta)." if cuadro["base"] == "meta" else "."),
        etiqueta: ("Cuántos registros tiene cada uno." if cuadro["conteo"] else
                   f"{etiqueta} {'sumada de' if cuadro['aditiva'] else 'promedio de'} todos sus registros."),
        "Meta": f"{'Suma' if cuadro['aditiva'] else 'Promedio'} de la columna «{cuadro['meta_col']}» de cada uno.",
        "Registros": "Cuántas filas del archivo tiene cada uno.",
        "Promedio por registro": f"{etiqueta} dividido entre sus registros: descuenta el tamaño de la cartera.",
        "Vs. promedio": f"Diferencia contra el promedio de los {n} elegidos ({_fmt(cuadro['promedio'])}).",
        "Estado": "Veredicto según la meta o el promedio; ver «Cómo se lee el color» arriba.",
    }
    if cuadro["periodo_label"]:
        ayudas[f"Variación {cuadro['periodo_label']}"] = (
            f"Cambio de {cuadro['periodo_label']} contra {cuadro['periodo_anterior_label']}.")
    configuracion = {c: st.column_config.Column(c, help=t) for c, t in ayudas.items() if c in tabla}
    if "Cumplimiento" in tabla:
        tope = max(100.0, float(tabla["Cumplimiento"].max() or 0))
        configuracion["Cumplimiento"] = st.column_config.ProgressColumn(
            "Cumplimiento", format="%.0f%%", min_value=0, max_value=tope,
            help=f"{etiqueta} ÷ meta × 100. 100% = cumplió exactamente lo esperado.")
    if "Participación" in tabla:
        configuracion["Participación"] = st.column_config.ProgressColumn(
            "Participación", format="%.1f%%", min_value=0, max_value=100,
            help=f"Qué parte de lo que suman los {n} elegidos aporta cada uno.")
    st.dataframe(tabla, use_container_width=True, hide_index=True, column_config=configuracion)
    st.download_button("⬇️ Descargar cuadro (CSV)", tabla.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"cuadro_comparativo_{dimension}.csv", mime="text/csv", key="cuadro_descarga")

    st.markdown(section_header("Lectura", compact=True), unsafe_allow_html=True)
    for frase in cuadro["lectura"]:
        st.markdown(f"- {frase}")
    if cuadro["aviso"]:
        st.warning(cuadro["aviso"])
    if cuadro["parcial"]:
        st.caption("El último mes parece incompleto, así que la variación compara los dos meses anteriores.")
