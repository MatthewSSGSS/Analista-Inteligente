"""Explorador analítico (pestaña "Analítica" del modo Analista).

A diferencia de Ejecutivo/Descripción (una lectura fija que el sistema
decide mostrar), Explorer es una herramienta interactiva: el usuario elige
qué cruzar y el resultado — tabla, filtro de valores y gráfico — se
actualiza al instante para esa elección concreta. No hay tarjetas de KPI ni
un veredicto ejecutivo aquí; esa identidad ya la cubre Ejecutivo/Descripción.

Reutiliza trend()/ranking()/heatmap() de visualization/charts.py, los
mismos que usa el resto de la app; no hay cálculo nuevo en core/.
"""
import streamlit as st
import pandas as pd
from ui.labels import agg_label
from ui.components.charts import chart_card
from ui.components.section import section_header, banner_header
from visualization.charts import trend, ranking, heatmap, _label


def render_explorer(df, schema):
    st.markdown(
        banner_header(
            "Explorador analítico",
            "Elige qué cruzar; la tabla y el gráfico se actualizan al instante.",
            "ciudad_red.jpg",
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
        bar_col = "Registros"
    else:
        result = scope.groupby(x, dropna=False)[y].agg(["sum", "mean", "count"]).reset_index()
        sum_label, mean_label, count_label = agg_label("sum"), agg_label("mean"), agg_label("count")
        result.columns = [x, sum_label, mean_label, count_label]
        metric_col = y
        bar_col = sum_label

    if value_filter and scope.empty:
        st.info(f"Ningún valor de {x_label} coincide con «{value_filter}». Ajusta el filtro para ver resultados.")
        return

    st.caption(f"{len(result):,} valores distintos de {x_label} · {len(scope):,} registros analizados.")

    # ── Visualización ────────────────────────────────────────────────────
    # Un solo gráfico a la vez, elegido por el usuario cuando hay más de una
    # lectura posible — así los controles secundarios (el selector de vista)
    # no compiten en tamaño con el resultado, y explorar se siente como
    # cambiar de lente, no como desplazarse por una página larga. La lista
    # de vistas disponibles se arma dinámicamente en vez de un árbol de
    # if/elif — agregar "Mapa de calor" como tercera opción no obligó a
    # reescribir la combinatoria de las otras dos.
    dates = schema.get("dates", [])
    n_unique = scope[x].dropna().astype(str).nunique()
    has_evolution = bool(metric_col and dates)
    has_segmentation = bool(metric_col and 2 <= n_unique <= 50)
    # El mapa de calor cruza X contra el tiempo — necesita fecha Y una
    # dimensión con un número de categorías legible (mismo tope que
    # Segmentación: con más de 50 filas, ni una barra ni un mapa de calor
    # se leen bien).
    has_heatmap = bool(metric_col and dates and 2 <= n_unique <= 50)

    views = []
    if has_evolution:
        views.append(("Evolución", lambda: chart_card(
            "Evolución", f"{_label(schema, metric_col)} a lo largo del tiempo",
            trend(scope, schema, metric_col), key="explorer_trend",
        )))
    if has_segmentation:
        views.append(("Segmentación", lambda: chart_card(
            "Segmentación", f"{_label(schema, metric_col)} por {x_label}",
            ranking(scope, schema, metric_col, x, top_n=15), key="explorer_ranking",
        )))
    if has_heatmap:
        views.append(("Mapa de calor", lambda: chart_card(
            "Mapa de calor", f"{_label(schema, metric_col)} por {x_label}, mes a mes",
            heatmap(scope, schema, metric_col, x), key="explorer_heatmap",
        )))

    if len(views) > 1:
        labels = [v[0] for v in views]
        view = st.radio("Vista", labels, horizontal=True, label_visibility="collapsed", key="explore_view")
        dict(views)[view]()
    elif len(views) == 1:
        views[0][1]()

    # ── Detalle ──────────────────────────────────────────────────────────
    st.markdown(section_header("Detalle", compact=True), unsafe_allow_html=True)
    # "Barritas" (data bars): una lectura visual inmediata de qué fila pesa
    # más, directamente en la tabla — sin abrir el gráfico. Solo se activa
    # sobre la columna del agregado principal (o "Registros" si no se
    # eligió métrica) y solo cuando hay variación real que mostrar.
    column_config = {}
    if not result.empty and bar_col in result.columns:
        numeric_bar_col = pd.to_numeric(result[bar_col], errors="coerce")
        raw_min, raw_max = numeric_bar_col.min(), numeric_bar_col.max()
        # "NaN or 0" evaluaría a NaN (NaN es verdadero en Python) en vez de
        # 0 — se usa pd.isna() explícito, no el atajo "or", para el caso
        # borde de una columna sin ningún valor numérico válido.
        col_min = 0.0 if pd.isna(raw_min) else float(raw_min)
        col_max = 0.0 if pd.isna(raw_max) else float(raw_max)
        if col_max > col_min:
            column_config[bar_col] = st.column_config.ProgressColumn(
                bar_col,
                help=f"Barra proporcional al valor de {bar_col.lower()} en esta fila, frente al resto de la tabla.",
                min_value=min(0.0, col_min), max_value=col_max, format="%.0f",
            )
    st.dataframe(result, use_container_width=True, column_config=column_config)
