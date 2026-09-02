import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from ui.labels import pretty_technical
from ui.components.cards import kpi_card, insight_card
from ui.components.section import section_header, banner_header
from visualization.charts import chart_text_color
from core.comparison_engine import (
    common_dimension_map,
    dimension_filter_options,
    apply_dimension_filters,
    build_comparison,
    combined_records_table,
)


def _fmt(v):
    if v is None or pd.isna(v): return "—"
    x = float(v)
    ax = abs(x)
    if ax >= 1_000_000_000: return f"{x/1_000_000_000:,.2f} mil M"
    if ax >= 1_000_000: return f"{x/1_000_000:,.2f} M"
    if ax >= 1_000: return f"{x/1_000:,.1f} mil"
    return f"{x:,.2f}"


def _pct(v):
    if v is None or pd.isna(v): return "—"
    return f"{'+' if v > 0 else ''}{v:,.1f}%"


def _tone(v):
    if v is None or pd.isna(v) or abs(v) < 0.05: return "neutral"
    return "positive" if v > 0 else "negative"


def _render_filter_panel(key_prefix: str = "cmp"):
    """Filtro que se aplica a los N archivos comparados a la vez, usando la
    columna equivalente de cada uno aunque el nombre no sea idéntico entre
    archivos. Recalcula la comparación completa cuando cambia la selección.
    """
    raw_files = st.session_state.get("comparison_raw_files")
    if not raw_files:
        return
    dim_maps = common_dimension_map(raw_files)
    if not dim_maps:
        return
    active = st.session_state.get("comparison_filters") or {}
    with st.expander("🎚️ Filtrar todos los archivos a la vez", expanded=bool(active)):
        st.caption(
            "Se aplica a los "
            f"{len(raw_files)} archivos comparados usando la columna equivalente de cada uno, "
            "aunque se llame distinto (ej. 'Región' vs 'REGION_'). Los archivos que no tengan "
            "esa dimensión quedan sin filtrar en vez de vaciarse por error."
        )
        cols = st.columns(min(3, len(dim_maps)))
        picked = {}
        for i, (label, mapping) in enumerate(dim_maps.items()):
            options = dimension_filter_options(raw_files, mapping)
            with cols[i % len(cols)]:
                sel = st.multiselect(label, options, default=active.get(label, []), key=f"{key_prefix}_filter_{label}")
                if sel:
                    picked[label] = sel
        c1, c2 = st.columns([1, 1])
        if c1.button("Aplicar filtros", use_container_width=True, type="primary", key=f"{key_prefix}_apply_filters"):
            st.session_state.comparison_filters = picked
            filtered = apply_dimension_filters(raw_files, picked, dim_maps)
            try:
                st.session_state.comparison_result = build_comparison({"files": filtered})
            except Exception as exc:
                st.error(f"No se pudo recalcular la comparación con ese filtro: {exc}")
            st.rerun()
        if active and c2.button("Quitar filtros", use_container_width=True, key=f"{key_prefix}_clear_filters"):
            st.session_state.comparison_filters = {}
            st.session_state.comparison_result = build_comparison({"files": raw_files})
            st.rerun()
    if active:
        summary = " · ".join(f"{k}: {', '.join(v)}" for k, v in active.items())
        st.markdown(f'<div class="data-badge" style="display:inline-block;margin-bottom:8px;">Filtros activos en la comparativa: {summary}</div>', unsafe_allow_html=True)


def _direct_comparison_chart(metrics, first_label, last_label):
    """Barras agrupadas horizontales: primero vs. último por indicador, en
    la misma escala visual — la forma más directa de ver de un vistazo
    dónde hay una diferencia grande y dónde los archivos se parecen."""
    if not metrics:
        return None
    rows = []
    for m in metrics:
        anterior, actual = m.get("anterior"), m.get("actual")
        if pd.isna(anterior) and pd.isna(actual):
            continue
        rows.append({"Indicador": m["nombre"], "Periodo": first_label, "Valor": 0 if pd.isna(anterior) else anterior})
        rows.append({"Indicador": m["nombre"], "Periodo": last_label, "Valor": 0 if pd.isna(actual) else actual})
    if not rows:
        return None
    long_df = pd.DataFrame(rows)
    fig = px.bar(
        long_df, x="Valor", y="Indicador", color="Periodo", orientation="h",
        barmode="group", text_auto=".3s",
        color_discrete_sequence=["#7D8794", "#E4002B"],
    )
    fig.update_traces(marker_line_width=0)
    fig.update_layout(
        height=max(240, 70 * long_df["Indicador"].nunique() + 80),
        margin=dict(l=10, r=20, t=20, b=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=1.05, x=0),
        font=dict(color=chart_text_color()),
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(96,112,132,.16)", title=None)
    fig.update_yaxes(title=None)
    return fig


def render_comparison(result, show_filter_panel: bool = True, key_prefix: str = "cmp"):
    """`show_filter_panel=False` y `key_prefix` distinto de "cmp" los usa
    `ui/multi_sheet.py` (comparar 2 hojas de un mismo Excel):

    - `_render_filter_panel()` lee y escribe
      `st.session_state.comparison_raw_files/comparison_result` — las
      mismas claves globales que usa "Comparar archivos" en el sidebar. Si
      alguien ya había comparado archivos en esa sesión y luego usa
      "Comparar hojas", mostrar ese panel aquí filtraría con los archivos
      equivocados y sobrescribiría el resultado de la otra comparación.
    - La navegación principal ahora es una sola fila de pestañas
      (`grouped_nav`), y Streamlit calcula el contenido de TODAS las
      pestañas en cada rerun, no solo la visible — así que si hay una
      comparación de archivos activa Y esta vista también está en la
      misma fila, `render_comparison()` se llama dos veces en el mismo
      ciclo. Sin un prefijo distinto, los `key=` fijos (`cmp_selected_metrics`,
      etc.) chocarían y Streamlit tronaría con un ID de widget duplicado.

    Los 4 llamados existentes (comparación de archivos) no pasan ninguno
    de los dos argumentos, así que siguen exactamente igual que antes."""
    st.markdown(banner_header("Qué cambió entre los archivos", "Último vs. anterior · primero vs. último.", "datos1.jpg"), unsafe_allow_html=True)
    files = result["files"]
    st.caption(" · ".join(f"{i+1}. {f['label']}" for i, f in enumerate(files)))
    if show_filter_panel:
        _render_filter_panel(key_prefix)

    # ── Selección de elementos: por defecto se destacan los primeros 5
    # indicadores comparables (mismo comportamiento que antes), pero ahora
    # el usuario puede elegir exactamente cuáles quiere ver en las tarjetas
    # y en el gráfico de abajo.
    all_names = [m["nombre"] for m in result["metrics"]]
    selected_names = st.multiselect(
        "Métricas a comparar", all_names, default=all_names[:5],
        key=f"{key_prefix}_selected_metrics",
        help="Elige qué indicadores destacar en las tarjetas y el gráfico. El resto de las pestañas de abajo siguen mostrando la comparación completa.",
    ) if all_names else []

    recent_metrics = [m for m in result["recent_metrics"] if not selected_names or m["nombre"] in selected_names]
    span_metrics = [m for m in result["metrics"] if not selected_names or m["nombre"] in selected_names]

    if all_names and not selected_names:
        st.info("Selecciona al menos una métrica para ver las tarjetas y el gráfico de comparación directa.")
    else:
        if recent_metrics:
            cols = st.columns(min(5, len(recent_metrics)))
            for col, m in zip(cols, recent_metrics[:5]):
                tone = _tone(m["cambio_pct"])
                arrow = "↑" if tone == "positive" else "↓" if tone == "negative" else "→"
                delta_text = f"{_pct(m['cambio_pct'])} · {m['etiqueta_operacion']}"
                col.markdown(kpi_card(m['nombre'], _fmt(m['actual']), delta=delta_text, tone=tone, icon=arrow), unsafe_allow_html=True)

        # ── Comparación visual directa: primero vs. último, mismos
        # indicadores seleccionados arriba.
        direct_fig = _direct_comparison_chart(span_metrics, result["first"]["label"], result["last"]["label"])
        if direct_fig is not None:
            st.markdown(section_header("Comparación directa", compact=True), unsafe_allow_html=True)
            st.plotly_chart(direct_fig, use_container_width=True, key=f"{key_prefix}_direct_chart")

    if result["signals"]:
        st.markdown('<div class="decision-panel"><div class="decision-panel-title">Lectura ejecutiva</div><div class="decision-panel-subtitle">Cambios detectados automáticamente a partir de variables comparables.</div></div>', unsafe_allow_html=True)
        for s in result["signals"][:5]:
            icon = "↑" if s["tipo"] == "positive" else "↓" if s["tipo"] == "warning" else "i"
            st.markdown(insight_card(s["texto"], label="HALLAZGO COMPARATIVO", kind=s["tipo"], icon=icon), unsafe_allow_html=True)

    tabs = st.tabs(["Resumen", "Ganadores y caídas", "Evolución", "📋 Registros", "Variables comparables"])
    with tabs[0]:
        rows=[]
        for m in result["metrics"]:
            rows.append({"Indicador": m["nombre"], result["first"]["label"]: _fmt(m["anterior"]), result["last"]["label"]: _fmt(m["actual"]), "Cambio": _pct(m["cambio_pct"])})
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.warning("No se encontraron métricas compatibles para comparar.")

        if result["dimension_results"]:
            st.markdown("### Cambios por dimensión")
            for dr in result["dimension_results"][:4]:
                st.markdown(f"**{dr['dimension']}** · usando **{dr['metric']}**")
                t=dr["table"].copy()
                t["Cambio"] = t["cambio"].map(lambda x: f"{'+' if x>0 else ''}{x:,.2f}")
                t["Variación"] = t["cambio_pct"].map(_pct)
                show=t.rename(columns={"categoria":"Categoría","anterior":"Periodo anterior","actual":"Periodo actual"})[["Categoría","Periodo anterior","Periodo actual","Cambio","Variación"]].head(10)
                st.dataframe(show, use_container_width=True, hide_index=True)
    with tabs[1]:
        for dr in result["dimension_results"][:4]:
            t=dr["table"]
            up=t.sort_values("cambio", ascending=False).head(5).copy()
            down=t.sort_values("cambio", ascending=True).head(5).copy()
            c1,c2=st.columns(2)
            with c1:
                st.markdown(f"#### 🟢 Mayor mejora · {dr['dimension']}")
                st.dataframe(up[["categoria","cambio","cambio_pct"]].rename(columns={"categoria":"Categoría","cambio":"Cambio","cambio_pct":"Variación"}).style.format({"Cambio":"{:,.2f}","Variación":"{:+.1f}%"}), use_container_width=True, hide_index=True)
            with c2:
                st.markdown(f"#### 🔴 Mayor caída · {dr['dimension']}")
                st.dataframe(down[["categoria","cambio","cambio_pct"]].rename(columns={"categoria":"Categoría","cambio":"Cambio","cambio_pct":"Variación"}).style.format({"Cambio":"{:,.2f}","Variación":"{:+.1f}%"}), use_container_width=True, hide_index=True)
    with tabs[2]:
        for history_index, h in enumerate(result["history"]):
            series=h["serie"]
            fig=px.line(series,x="periodo",y="valor",markers=True,title=f"{h['metrica']} · {h['operacion']}")
            fig.update_layout(height=360,margin=dict(l=20,r=20,t=50,b=20),paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",xaxis_title="Periodo",yaxis_title="Valor",font=dict(color=chart_text_color()))
            st.plotly_chart(fig,use_container_width=True,key=f"{key_prefix}_history_{history_index}")
    with tabs[3]:
        st.caption(
            "Cada fila real de los archivos comparados (ya con tus filtros aplicados), no un "
            "agregado. Las columnas que coinciden entre archivos (como una dimensión o una "
            "métrica compartida) quedan bajo un mismo nombre; el resto conserva su nombre original."
        )
        records = combined_records_table(files)
        if records.empty:
            st.info("No hay registros para mostrar con la selección actual.")
        else:
            st.dataframe(records, use_container_width=True, hide_index=True)
            st.caption(f"{len(records):,} registros mostrados (de los {sum(len(f['df']) for f in files):,} totales en los archivos comparados).")
            st.download_button(
                "⬇️ Descargar estos registros en CSV",
                records.to_csv(index=False).encode("utf-8-sig"),
                "registros_comparados.csv",
                "text/csv",
                use_container_width=True,
                key=f"{key_prefix}_records_csv",
            )
    with tabs[4]:
        matches=result["matches"]
        if matches:
            table=pd.DataFrame([{"Archivo base":"Primero","Columna":""+m["a"],"Archivo final":"Último","Columna equivalente":m["b"],"Coincidencia":f"{m['score']*100:.0f}%","Tipo":pretty_technical(m["concept"])} for m in matches])
            st.dataframe(table,use_container_width=True,hide_index=True)
        else:
            st.info("No se encontraron variables equivalentes.")

    st.divider()
    st.markdown("#### 🌐 Informe HTML de esta comparación")
    active_filters = st.session_state.get("comparison_filters") or {}
    filters_summary = " · ".join(f"{k}: {', '.join(v)}" for k, v in active_filters.items()) or "Sin filtros aplicados"
    st.caption(f"Genera un HTML listo para compartir con exactamente lo que ves aquí — {len(files)} archivos, filtros: {filters_summary}.")
    try:
        from ui.report_html import build_comparison_html_report
        html_comparativo = build_comparison_html_report(result, filters_summary)
        st.download_button(
            "🌐 Exportar informe comparativo",
            html_comparativo.encode("utf-8"),
            "informe_comparativo.html",
            "text/html",
            use_container_width=True,
            type="primary",
        )
    except Exception as exc:
        st.error(f"No se pudo preparar el informe comparativo: {exc}")
