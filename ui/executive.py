from __future__ import annotations
import pandas as pd
import streamlit as st
from core.universal_analysis import dynamic_kpis, smart_chart_questions, period_series
from core.tracking_engine import project_metric
from core.dates import format_month_year
from visualization.charts import trend, ranking, period_compare_bar, donut, histogram, scatter, metric_candidates, dimension_candidates, _label
from ui.labels import clean_display_text
from ui.dashboard import _fmt, _chart_insight, _display_kpi_value, _kpi_style
from ui.components.cards import kpi_card, insight_card, executive_headline, executive_signals
from ui.components.charts import chart_card
from ui.components.section import section_header, banner_header
from ui.layouts.columns import two_column, kpi_grid
from ui.person_profile import has_entity


def render_executive(df, schema, dashboard):
    st.markdown(banner_header("Resumen ejecutivo", "Vista ejecutiva · lectura compacta para decidir rápido. El contenido se adapta al tipo de Excel detectado.", "ciudad_red.jpg"), unsafe_allow_html=True)

    # ── Veredicto ejecutivo: lo primero que se lee, antes que cualquier KPI
    # o gráfico. dashboard["executive"] ya lo calcula core/executive.py
    # específicamente para esta vista, pero antes esta pantalla no lo
    # mostraba — solo ui/dashboard.py lo usaba. Es la pieza que más
    # protagonismo merece aquí.
    if isinstance(dashboard, dict) and dashboard.get("executive"):
        executive_headline(dashboard)

    # El análisis de seguimiento ya no vive aquí dentro: tiene pestaña propia
    # ("🔎 Análisis de seguimiento"). Enterrado a media página, con un botón
    # que había que descubrir, era de las herramientas menos usadas del panel
    # pese a responder una de las preguntas más frecuentes.
    if has_entity(df, schema):
        st.caption("¿Quieres ver un punto, asesor o código en concreto? Está en la pestaña "
                   "**🔎 Análisis de seguimiento**, con sus alertas y su comparación contra el grupo.")

    # ── Layout de dos columnas: a la izquierda los KPIs y los gráficos
    # principales (lo que ocupa más espacio de lectura), a la derecha la
    # Lectura Analítica en un panel angosto — igual que el resto de la app
    # ya usa (comparación de layouts en Georeferenciación, Comparativa).
    main_col, side_col = two_column(gap="medium")

    def _render_kpi(k):
        label, tone, icon = _kpi_style(k, schema)
        # En la tarjeta de quién va primero, la cifra que lo sostiene
        # ("541 de una meta de 360") va debajo: sin ella no se sabe contra qué.
        delta = k.get("detalle") if k.get("kind") == "leader" else None
        # Un nombre largo ("COMMUTE SAS SOLEDAD ATLANTICO") con la letra de una
        # cifra ocupaba tres renglones enormes: se muestra en tamaño de texto.
        return kpi_card(label, _display_kpi_value(k), delta=delta, tone=tone, icon=icon,
                        small_value=k.get("kind") == "leader")

    with main_col:
        kpis=dynamic_kpis(df,schema,dashboard)[:6]
        if kpis:
            kpi_grid(kpis, render=_render_kpi, per_row=3)

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

        # ── Proyección: "a este ritmo, ¿a cuánto llegarías?" ────────────────
        # Reutiliza project_metric() (regresión lineal simple), que ya existía
        # pero solo se usaba en Análisis de Seguimiento — nunca en el
        # Resumen ejecutivo normal, que es donde la mayoría de la gente
        # primero se pregunta esto. Nada de cálculo nuevo: solo se le da a
        # period_series() (ya usada en toda esta vista) la forma de columnas
        # que project_metric() espera ("period"/"_num").
        if m and schema.get("dates"):
            ps = period_series(df, schema, m, "Mes", "Automático")
            if len(ps) >= 3:
                timeline = ps.rename(columns={m: "_num"})
                last_period = pd.to_datetime(ps["period"]).max()
                target = last_period + pd.DateOffset(months=3)
                proj = project_metric(timeline, target)
                if proj.get("status") == "ok":
                    r2 = proj.get("r2", 0) or 0
                    # Se informa la confianza en vez de mostrar el número
                    # pelado: un r² bajo significa que la tendencia es
                    # ruidosa, y presentarlo con el mismo peso que una
                    # proyección confiable sería engañoso.
                    confidence = "alta" if r2 >= 0.6 else "media" if r2 >= 0.3 else "baja"
                    trend_word = {"creciente": "creciente", "decreciente": "decreciente", "estable": "estable"}.get(proj.get("trend"), "reciente")
                    st.markdown(section_header("Proyección", compact=True), unsafe_allow_html=True)
                    metric_label = _label(schema, m)
                    text = (
                        f"Si la tendencia {trend_word} de los últimos {proj['points']} periodos se mantiene, "
                        f"<b>{metric_label}</b> llegaría a aproximadamente "
                        f"<b>{_fmt(proj['projected'])}</b> para {format_month_year(target, full=True)} "
                        f"(confianza {confidence}, basada en {proj['points']} periodos de historia)."
                    )
                    st.markdown(insight_card(text, title="A este ritmo...", kind="info"), unsafe_allow_html=True)

        insights=dashboard.get("insights",[]) if isinstance(dashboard,dict) else []
        if insights:
            st.markdown(section_header("Lectura analítica", compact=True), unsafe_allow_html=True)
            for x in insights[:4]:
                title=clean_display_text(x.get("title") or x.get("label") or "Hallazgo")
                finding=clean_display_text(x.get("finding") or x.get("message") or x.get("text") or x.get("description") or "Sin detalle disponible.")
                action=clean_display_text(x.get("action")) if x.get("action") else None
                st.markdown(insight_card(finding, title=title, kind="info", action=action, action_label="Qué revisar"),unsafe_allow_html=True)

    st.caption(f"{len(df):,} registros visibles · los indicadores se recalculan con la selección actual.")
