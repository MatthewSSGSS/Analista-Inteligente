"""Pestaña "📊 Cuadro comparativo": varios elementos, la misma vara, un vistazo.

El cálculo vive en `core/cuadro_comparativo.py`; aquí solo se pinta. El orden
de la pantalla es el de la pregunta "¿cómo va cada uno?":

1. Qué se compara: por qué columna, con qué métrica y a quiénes.
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

from core.cuadro_comparativo import MAX_ELEGIDOS, cuadro_comparativo, opciones_de_comparacion
from core.diagnostics import METRICA_CONTEO, _fmt
from ui.components.cards import kpi_card
from ui.components.charts import chart_card, empty_state
from ui.components.section import section_header
from visualization.charts import CATEGORY_PALETTE, _base, metric_candidates, realzar_barras

# Misma paleta de salud que la Estrategia por canal (ui/comercial.py).
COLOR_TONO = {"bueno": "#22A06B", "medio": "#F59E0B", "malo": "#E4002B"}
ICONO_TONO = {"bueno": "🟢", "medio": "🟡", "malo": "🔴"}
_ETIQUETA_CONTEO = "Cantidad de registros"


def _pct(v, signo=False) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:+.1f}%" if signo else f"{v:,.0f}%"


def _controles(df: pd.DataFrame, schema: dict):
    """Por qué columna, con qué métrica y a quiénes. Devuelve (dimensión, métrica, elegidos)."""
    hoja = st.session_state.get("active_sheet", "")
    opciones = opciones_de_comparacion(df, schema)
    if not opciones:
        return None, None, None
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
        return dimension, metrica, None

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
    return dimension, metrica, elegidos


def _kpis(cuadro: dict) -> None:
    filas = cuadro["filas"]
    primero, ultimo = filas[0], filas[-1]
    n = len(filas)
    if cuadro["base"] == "meta":
        cifra = lambda f: _pct(f["cumplimiento"]) + " de su meta"
        # Quien no tiene meta queda al final del orden: la distancia se mide
        # entre los que sí la tienen.
        con_meta = [f for f in filas if f["cumplimiento"] is not None]
        brecha = f"{abs(con_meta[0]['cumplimiento'] - con_meta[-1]['cumplimiento']):,.0f} pts"
        brecha_detalle = "de cumplimiento"
        bien = sum(1 for f in filas if f["tono"] == "bueno")
        cuarta = ("Dentro de su meta", f"{bien} de {n}", "bueno" if bien == n else "malo" if bien == 0 else "medio")
    else:
        cifra = lambda f: _fmt(f["valor"])
        brecha = _fmt(abs(primero["valor"] - ultimo["valor"]))
        brecha_detalle = f"promedio {_fmt(cuadro['promedio'])}"
        bien = sum(1 for f in filas if f["tono"] != "malo")
        cuarta = ("En o sobre el promedio" if not cuadro["menos_es_mejor"] else "En o bajo el promedio",
                  f"{bien} de {n}", "bueno" if bien == n else "medio")
    tono_kpi = {"bueno": "positive", "medio": "neutral", "malo": "negative"}
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(kpi_card("🥇 Va primero", html.escape(primero["nombre"]), delta=cifra(primero),
                         tone="positive", small_value=True), unsafe_allow_html=True)
    c2.markdown(kpi_card("Va último", html.escape(ultimo["nombre"]), delta=cifra(ultimo),
                         tone="negative", small_value=True), unsafe_allow_html=True)
    c3.markdown(kpi_card("Distancia primero–último", brecha, delta=brecha_detalle), unsafe_allow_html=True)
    c4.markdown(kpi_card(cuarta[0], cuarta[1], tone=tono_kpi[cuarta[2]]), unsafe_allow_html=True)


def figura_ranking(cuadro: dict):
    """Una barra por elemento, el mejor arriba, con la meta o el promedio como referencia."""
    filas = list(reversed(cuadro["filas"]))  # Plotly dibuja de abajo hacia arriba
    por_meta = cuadro["base"] == "meta"
    x = [f["cumplimiento"] if por_meta else f["valor"] for f in filas]
    texto = [_pct(f["cumplimiento"]) if por_meta else _fmt(f["valor"]) for f in filas]
    detalle = [f"{_fmt(f['valor'])} de {_fmt(f['meta'])}" if por_meta and f["meta"] else f"{f['registros']:,} registros"
               for f in filas]
    fig = go.Figure(go.Bar(
        x=x, y=[f["nombre"] for f in filas], orientation="h",
        marker=dict(color=[COLOR_TONO[f["tono"]] for f in filas], line=dict(width=0)),
        text=texto, textposition="outside", cliponaxis=False, customdata=detalle,
        hovertemplate="<b>%{y}</b><br>%{text} · %{customdata}<extra></extra>",
    ))
    fig.update_layout(showlegend=False, bargap=.3)
    fig.update_xaxes(tickformat="~s" if not por_meta else None, ticksuffix="%" if por_meta else "")
    fig = _base(fig, max(300, 42 * len(filas) + 90), show_xgrid=True)
    # _base pone el hover unificado por eje, pensado para series en el
    # tiempo; en un ranking cada barra es su propio dato.
    fig.update_layout(hovermode="closest")
    referencia = cuadro["referencia"]
    texto_ref = "meta 100%" if por_meta else f"promedio {_fmt(referencia)}"
    return realzar_barras(fig, referencia=referencia, referencia_texto=texto_ref)


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
    fig.update_xaxes(tickformat="%b %Y")
    fig.update_yaxes(tickformat="~s", title=None)
    return _base(fig, 380)


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
    return realzar_barras(_base(fig, 380), horizontal=False)


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

    dimension, metrica, elegidos = _controles(df, schema)
    if dimension is None:
        empty_state("Este archivo no tiene una columna con nombres o categorías para comparar entre sí.")
        return
    if elegidos is not None and len(elegidos) < 2:
        empty_state("Elige al menos dos elementos para armar el cuadro.")
        return
    cuadro = cuadro_comparativo(df, schema, dimension, metrica, seleccion=elegidos)
    if cuadro is None:
        empty_state("Con la selección y los filtros actuales no quedan al menos dos elementos con datos para comparar.")
        return

    _kpis(cuadro)
    etiqueta = _ETIQUETA_CONTEO if cuadro["conteo"] else str(cuadro["metrica"])
    n = len(cuadro["filas"])

    if cuadro["base"] == "meta":
        subtitulo = f"Cumplimiento de meta ({cuadro['meta_col']}) · la línea marca el 100%"
    elif cuadro["menos_es_mejor"]:
        subtitulo = f"{etiqueta} · aquí menos es mejor · la línea marca el promedio de los {n}"
    else:
        subtitulo = f"{etiqueta} · la línea marca el promedio de los {n}"
    chart_card(f"Cómo va cada uno · {dimension}", subtitulo, figura_ranking(cuadro),
               key="cuadro_ranking", visual_type="COMPARACIÓN", badge_text=f"{n} elegidos")

    evolucion = figura_evolucion(cuadro)
    if evolucion is not None:
        chart_card("Evolución mes a mes", f"{etiqueta} por mes de cada uno", evolucion,
                   key="cuadro_evolucion", visual_type="TENDENCIA", badge_text=f"{len(cuadro['periodos'])} meses")
    meta = figura_meta(cuadro)
    if meta is not None:
        chart_card("Resultado frente a meta", f"{etiqueta} contra {cuadro['meta_col']}", meta,
                   key="cuadro_meta", visual_type="META", badge_text="Resultado vs. meta")

    st.markdown(section_header("El cuadro", compact=True), unsafe_allow_html=True)
    tabla = tabla_cuadro(cuadro)
    configuracion = {}
    if "Cumplimiento" in tabla:
        tope = max(100.0, float(tabla["Cumplimiento"].max() or 0))
        configuracion["Cumplimiento"] = st.column_config.ProgressColumn(
            "Cumplimiento", format="%.0f%%", min_value=0, max_value=tope)
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
    notas = ["Todo se calcula sobre los elementos elegidos y con los filtros activos del menú lateral."]
    if cuadro["parcial"]:
        notas.append("El último mes parece incompleto, así que la variación compara los dos meses anteriores.")
    st.caption(" ".join(notas))
