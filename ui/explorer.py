"""Explorador analítico (pestaña "Analítica" del modo Analista).

A diferencia de Ejecutivo/Descripción (una lectura fija que el sistema
decide mostrar), Explorer es una herramienta interactiva: el usuario elige
qué cruzar y el resultado — tabla, filtro de valores y gráfico — se
actualiza al instante para esa elección concreta. No hay tarjetas de KPI ni
un veredicto ejecutivo aquí; esa identidad ya la cubre Ejecutivo/Descripción.

Reutiliza trend()/ranking() de visualization/charts.py, los mismos que usa
el resto de la app; no hay cálculo nuevo en core/.
"""
import streamlit as st
import pandas as pd
from ui.labels import agg_label
from ui.components.charts import chart_card
from ui.components.section import section_header
from visualization.charts import trend, ranking, _label


def render_explorer(df, schema):
    st.markdown(
        section_header(
            "Explorador analítico", eyebrow="ANALÍTICA",
            subtitle="Elige qué cruzar; la tabla y el gráfico se actualizan al instante.",
        ),
        unsafe_allow_html=True,
    )

    # ── Selección ────────────────────────────────────────────────────────
    c1, c2 = st.columns(2)
    with c1:
        x = st.selectbox("Dimensión / X", list(df.columns), key="explore_x")
    with c2:
        y = st.selectbox("Métrica / Y", ["(conteo)"] + schema["metrics"], key="explore_y")
    x_label = _label(schema, x)

    # ── Filtros ──────────────────────────────────────────────────────────
    # Un filtro de texto sobre los valores de X, no sobre todo el dashboard
    # (eso ya lo hace la barra lateral): sirve para explorar un subconjunto
    # concreto ("solo las ciudades que contienen 'bog'") sin perder de vista
    # que es un filtro propio de esta herramienta, no global.
    scope = df
    unique_x = df[x].dropna().astype(str)
    value_filter = ""
    if unique_x.nunique() > 8:
        value_filter = st.text_input(
            f"Filtrar valores de {x_label}", placeholder="Escribe para acotar…",
            key="explore_value_filter",
        )
        if value_filter:
            scope = df[df[x].astype(str).str.contains(value_filter, case=False, na=False, regex=False)]

    if y == "(conteo)":
        result = scope[x].value_counts(dropna=False).head(100).rename("Registros").reset_index()
        result.columns = [x, "Registros"]
        metric_col = None
    else:
        result = scope.groupby(x, dropna=False)[y].agg(["sum", "mean", "count"]).reset_index()
        result.columns = [x, agg_label("sum"), agg_label("mean"), agg_label("count")]
        metric_col = y

    if value_filter and scope.empty:
        st.info(f"Ningún valor de {x_label} coincide con «{value_filter}». Ajusta el filtro para ver resultados.")
        return

    st.caption(f"{len(result):,} valores distintos de {x_label} · {len(scope):,} registros analizados.")

    # ── Visualización ────────────────────────────────────────────────────
    # Un solo gráfico a la vez, elegido por el usuario cuando hay más de una
    # lectura posible — así los controles secundarios (el selector de vista)
    # no compiten en tamaño con el resultado, y explorar se siente como
    # cambiar de lente, no como desplazarse por una página larga.
    dates = schema.get("dates", [])
    n_unique = scope[x].dropna().astype(str).nunique()
    has_evolution = bool(metric_col and dates)
    has_segmentation = bool(metric_col and 2 <= n_unique <= 50)

    if has_evolution and has_segmentation:
        view = st.radio(
            "Vista", ["Evolución", "Segmentación"], horizontal=True,
            label_visibility="collapsed", key="explore_view",
        )
        if view == "Evolución":
            chart_card("Evolución", f"{_label(schema, metric_col)} a lo largo del tiempo", trend(scope, schema, metric_col), key="explorer_trend")
        else:
            chart_card("Segmentación", f"{_label(schema, metric_col)} por {x_label}", ranking(scope, schema, metric_col, x, top_n=15), key="explorer_ranking")
    elif has_evolution:
        chart_card("Evolución", f"{_label(schema, metric_col)} a lo largo del tiempo", trend(scope, schema, metric_col), key="explorer_trend")
    elif has_segmentation:
        chart_card("Segmentación", f"{_label(schema, metric_col)} por {x_label}", ranking(scope, schema, metric_col, x, top_n=15), key="explorer_ranking")

    # ── Detalle ──────────────────────────────────────────────────────────
    st.markdown(section_header("Detalle", compact=True), unsafe_allow_html=True)
    st.dataframe(result, use_container_width=True)
