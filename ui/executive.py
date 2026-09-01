from __future__ import annotations
import pandas as pd
import streamlit as st
from core.universal_analysis import dynamic_kpis, smart_chart_questions
from visualization.charts import trend, ranking, period_compare_bar, donut, histogram, scatter, metric_candidates, dimension_candidates, _label
from ui.labels import clean_display_text
from ui.dashboard import _fmt, _chart_insight, _display_kpi_value
from ui.components.cards import kpi_card, insight_card, executive_headline, executive_signals
from ui.components.charts import chart_card
from ui.components.section import section_header
from ui.layouts.columns import two_column, kpi_grid
from ui.person_profile import render_person_profile


def render_executive(df, schema, dashboard):
    st.markdown(section_header("Resumen ejecutivo", eyebrow="DIRECCIÓN", subtitle="Lectura compacta para decidir rápido. El contenido se adapta al tipo de Excel detectado.", badge="Vista ejecutiva"), unsafe_allow_html=True)

    # ── Veredicto ejecutivo: lo primero que se lee, antes que cualquier KPI
    # o gráfico. dashboard["executive"] ya lo calcula core/executive.py
    # específicamente para esta vista, pero antes esta pantalla no lo
    # mostraba — solo ui/dashboard.py lo usaba. Es la pieza que más
    # protagonismo merece aquí.
    if isinstance(dashboard, dict) and dashboard.get("executive"):
        executive_headline(dashboard)

    # Acción rápida: el perfil individual se abre DENTRO del dashboard.
    # No usamos st.switch_page: así evitamos depender de una página física
    # dentro de /pages y mantenemos el perfil como una herramienta del mismo panel.
    full_name = schema.get("full_name", {}) if isinstance(schema.get("full_name"), dict) else {}
    if full_name.get("column") in df.columns:
        cta1, cta2 = st.columns([1.35, 4])
        with cta1:
            if st.button("👤 Analizar perfil individual", type="primary", use_container_width=True, key="executive_open_profile_v53"):
                st.session_state["show_profile_inline"] = True
        with cta2:
            st.caption("Abre el análisis completo de una persona sin salir del dashboard.")

        if st.session_state.get("show_profile_inline", False):
            st.markdown('<div class="decision-panel"><div class="decision-panel-title">Perfil individual</div><div class="decision-panel-subtitle">Todo el análisis disponible para la persona seleccionada, respetando los filtros actuales.</div></div>', unsafe_allow_html=True)
            if st.button("✕ Cerrar perfil", key="executive_close_profile_v53"):
                st.session_state["show_profile_inline"] = False
                st.rerun()
            render_person_profile(df, schema, dashboard)

    # ── Layout de dos columnas: a la izquierda los KPIs y los gráficos
    # principales (lo que ocupa más espacio de lectura), a la derecha la
    # Lectura Analítica en un panel angosto — igual que el resto de la app
    # ya usa (comparación de layouts en Georeferenciación, Comparativa).
    main_col, side_col = two_column(gap="medium")

    with main_col:
        kpis=dynamic_kpis(df,schema,dashboard)[:6]
        if kpis:
            kpi_grid(kpis, render=lambda k: kpi_card(k.get("label","Indicador"), _display_kpi_value(k)), per_row=3)

        metrics=metric_candidates(df,schema); dims=dimension_candidates(df,schema)
        m=metrics[0] if metrics else None; d=dims[0] if dims else None
        if m:
            specs=smart_chart_questions(df,schema,m,d)
            rendered=0
            chart_items=[]
            for title,q,kind in specs:
                if rendered>=3: break
                if kind=="trend": fig=trend(df,schema,m,"Mes","Automático",False)
                elif kind=="ranking" and d: fig=ranking(df,schema,m,d,8,"Automático")
                elif kind=="period_compare" and d: fig=period_compare_bar(df,schema,m,d,"Mes","Automático",8)
                elif kind=="donut" and d: fig=donut(df,schema,m,d,8)
                elif kind=="histogram": fig=histogram(df,schema,m)
                else: continue
                if fig is not None:
                    chart_items.append((title,q,fig,kind,rendered)); rendered+=1
            if chart_items:
                st.markdown(section_header("Gráficos que importan", eyebrow="ANÁLISIS", compact=True), unsafe_allow_html=True)
                # El primero es el gráfico principal: a todo el ancho de la
                # columna, para que sea lo primero que se lea. Los que
                # siguen son análisis secundarios, uno al lado del otro.
                main_title,main_q,main_fig,main_kind,main_idx = chart_items[0]
                chart_card(main_title,main_q,main_fig,key=f"executive_{main_kind}_{main_idx}")
                secondary=chart_items[1:3]
                if secondary:
                    cols=st.columns(len(secondary))
                    for i,(title,q,fig,kind,idx) in enumerate(secondary):
                        with cols[i]:
                            chart_card(title,q,fig,key=f"executive_{kind}_{idx}")

    with side_col:
        ex=dashboard.get("executive",{}) if isinstance(dashboard,dict) else {}
        if ex.get("positive") or ex.get("watch"):
            st.markdown(section_header("Señales", compact=True), unsafe_allow_html=True)
            executive_signals(dashboard)

        insights=dashboard.get("insights",[]) if isinstance(dashboard,dict) else []
        if insights:
            st.markdown(section_header("Lectura analítica", compact=True), unsafe_allow_html=True)
            for x in insights[:4]:
                title=clean_display_text(x.get("title") or x.get("label") or "Hallazgo")
                finding=clean_display_text(x.get("finding") or x.get("message") or x.get("text") or x.get("description") or "Sin detalle disponible.")
                action=clean_display_text(x.get("action")) if x.get("action") else None
                st.markdown(insight_card(finding, title=title, kind="info", action=action, action_label="Qué revisar"),unsafe_allow_html=True)

    st.caption(f"{len(df):,} registros visibles · los indicadores se recalculan con la selección actual.")
