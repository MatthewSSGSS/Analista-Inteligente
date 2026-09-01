from __future__ import annotations
import pandas as pd
import streamlit as st
from core.universal_analysis import dynamic_kpis, smart_chart_questions
from visualization.charts import trend, ranking, period_compare_bar, donut, histogram, scatter, metric_candidates, dimension_candidates, _label
from ui.labels import clean_display_text
from ui.dashboard import _fmt, _card, _chart_card, _chart_insight, _display_kpi_value
from ui.person_profile import render_person_profile


def render_executive(df, schema, dashboard):
    st.markdown('<div class="section-intro"><div><span class="eyebrow">DIRECCIÓN</span><h2>Resumen ejecutivo</h2><div class="chart-subtitle">Lectura compacta para decidir rápido. El contenido se adapta al tipo de Excel detectado.</div></div><span class="data-badge">Vista ejecutiva</span></div>', unsafe_allow_html=True)
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
    main_col, side_col = st.columns([2.15, 1], gap="medium")

    with main_col:
        kpis=dynamic_kpis(df,schema,dashboard)[:6]
        if kpis:
            cols=st.columns(min(3,len(kpis)))
            for i,k in enumerate(kpis[:3]):
                with cols[i]: st.markdown(_card(k.get("label","Indicador"), _display_kpi_value(k)),unsafe_allow_html=True)
            if len(kpis)>3:
                cols=st.columns(min(3,len(kpis)-3))
                for i,k in enumerate(kpis[3:6]):
                    with cols[i]: st.markdown(_card(k.get("label","Indicador"), _display_kpi_value(k)),unsafe_allow_html=True)

        metrics=metric_candidates(df,schema); dims=dimension_candidates(df,schema)
        m=metrics[0] if metrics else None; d=dims[0] if dims else None
        if m:
            specs=smart_chart_questions(df,schema,m,d)
            st.markdown("### 3 gráficos que importan")
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
                cols=st.columns(2)
                for i,(title,q,fig,kind,idx) in enumerate(chart_items):
                    with cols[i%2]:
                        _chart_card(title,q,fig,key=f"executive_{kind}_{idx}")

    with side_col:
        insights=dashboard.get("insights",[]) if isinstance(dashboard,dict) else []
        if insights:
            st.markdown('<p class="sidebar-section-label" style="color:var(--muted)!important;">Lectura analítica</p>', unsafe_allow_html=True)
            for x in insights[:4]:
                title=clean_display_text(x.get("title") or x.get("label") or "Hallazgo")
                finding=clean_display_text(x.get("finding") or x.get("message") or x.get("text") or x.get("description") or "Sin detalle disponible.")
                action=clean_display_text(x.get("action")) if x.get("action") else None
                st.markdown(f'<div class="insight-card info"><div class="insight-body"><div class="insight-title">{title}</div><div class="insight-text">{finding}</div>{f"<div class=\"insight-action\"><b>Qué revisar:</b> {action}</div>" if action else ""}</div></div>',unsafe_allow_html=True)

    st.caption(f"{len(df):,} registros visibles · los indicadores se recalculan con la selección actual.")
