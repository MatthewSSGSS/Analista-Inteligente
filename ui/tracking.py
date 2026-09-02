"""Pestaña "Análisis Seguimiento": perfil consolidado por funcionario y por
supervisor, cruzando varios Excel de distinta estructura por ID/nombre.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from core.tracking_engine import (
    export_consolidated,
    person_directory,
    person_profile,
    project_metric,
    supervisor_directory,
    team_roster,
)


def _confidence_badge(level: str) -> str:
    if level == "alta":
        return '<span style="font-size:10.5px;font-weight:800;color:var(--green-strong);background:var(--green-soft);border-radius:999px;padding:3px 9px;">Cruce por ID · alta confianza</span>'
    return '<span style="font-size:10.5px;font-weight:800;color:var(--amber-strong);background:var(--amber-soft);border-radius:999px;padding:3px 9px;">Cruce por nombre · revisar</span>'


def _month_end(d: datetime) -> pd.Timestamp:
    ts = pd.Timestamp(d)
    return (ts + pd.offsets.MonthEnd(0))


def _download_consolidated_button(long_df: pd.DataFrame):
    data = export_consolidated(long_df)
    st.download_button(
        "⬇️ Descargar historial consolidado",
        data=data,
        file_name=f"historial_consolidado_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        key="tracking_download_consolidated",
    )
    st.caption("Guarda este archivo. La próxima vez que subas un Excel nuevo, súbelo junto con este consolidado para seguir acumulando el historial — sin él, la herramienta no recuerda lo que ya se procesó.")


def _render_metric_card(name: str, data: dict, target_date):
    timeline = data.get("timeline")
    has_series = timeline is not None and len(timeline) >= 2
    c1, c2, c3 = st.columns([1, 1, 1.4])
    c1.markdown(f'<div class="kpi-card"><span class="kpi-label">{name} · último valor</span><div class="kpi-value">{data["latest"]:,.0f}</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card"><span class="kpi-label">{name} · promedio</span><div class="kpi-value">{data["avg"]:,.0f}</div></div>', unsafe_allow_html=True)

    if has_series:
        proj = project_metric(timeline, target_date)
        if proj["status"] == "ok":
            trend_word = {"creciente": "↑ creciente", "decreciente": "↓ decreciente", "estable": "→ estable"}[proj["trend"]]
            confidence_note = "alta" if proj["r2"] >= 0.7 else ("media" if proj["r2"] >= 0.4 else "baja — pocos puntos o comportamiento irregular")
            c3.markdown(
                f'<div class="kpi-card"><span class="kpi-label">Proyección a {pd.Timestamp(target_date).strftime("%d/%m/%Y")}</span>'
                f'<div class="kpi-value" style="font-size:18px;">{proj["projected"]:,.0f}</div>'
                f'<div class="kpi-delta neutral">{trend_word} · confianza {confidence_note}</div></div>',
                unsafe_allow_html=True,
            )
        else:
            c3.markdown(f'<div class="kpi-card"><span class="kpi-label">Proyección</span><div class="kpi-value" style="font-size:13px;color:var(--muted);">Insuficientes datos ({proj["points"]} punto{"s" if proj["points"]!=1 else ""}, se necesitan al menos 3)</div></div>', unsafe_allow_html=True)
    else:
        c3.markdown('<div class="kpi-card"><span class="kpi-label">Proyección</span><div class="kpi-value" style="font-size:13px;color:var(--muted);">Se necesita historial en más de un periodo</div></div>', unsafe_allow_html=True)

    if has_series:
        chart_df = timeline.rename(columns={"period": "Periodo", "_num": name}).set_index("Periodo")
        st.line_chart(chart_df, use_container_width=True)


def _render_employee_view(long_df: pd.DataFrame):
    directory = person_directory(long_df)
    if directory.empty:
        st.info("No se detectaron personas identificables en los archivos procesados.")
        return

    labels = {row.person_key: f"{row.person_name} ({row.person_id})" if row.person_id else row.person_name for row in directory.itertuples()}
    low_conf = directory[directory["match_confidence"] != "alta"]
    if not low_conf.empty:
        st.warning(f"{len(low_conf)} persona(s) se identificaron solo por nombre (sin ID en ningún archivo) — el cruce entre archivos para ellas es menos confiable. Revísalas si algo se ve raro.")

    selected_key = st.selectbox(
        "Busca y selecciona un funcionario",
        options=list(labels.keys()),
        format_func=lambda k: labels.get(k, k),
        key="tracking_person_select",
    )
    if not selected_key:
        return

    profile = person_profile(long_df, selected_key)
    if not profile:
        st.info("No se encontró información para esta persona.")
        return

    identity = profile["identity"]
    st.markdown(
        f'<div class="hero" style="border-bottom:none;padding-bottom:6px;">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;">'
        f'<div><h1 style="margin:0;">{identity["name"]}</h1>'
        f'<p style="margin:4px 0 0;">ID: {identity["id"] or "—"} · Supervisor: {identity["supervisor"] or "No detectado"} · Fuentes: {", ".join(identity["sources"]) or "—"}</p></div>'
        f'{_confidence_badge(identity["match_confidence"])}'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    target = st.date_input("Proyectar desempeño hasta", value=_month_end(datetime.now()).date(), key="tracking_target_date")

    if profile["locations"]:
        st.markdown('<div class="section-intro compact"><div><span class="eyebrow">COBERTURA</span><h2>Puestos, puntos de venta y ubicaciones</h2></div></div>', unsafe_allow_html=True)
        for col, vals in profile["locations"].items():
            st.markdown(f'<div class="mini-list"><b>{col}</b> ({len(vals)}): {", ".join(vals)}</div>', unsafe_allow_html=True)
            st.write("")

    if profile["metrics"]:
        st.markdown('<div class="section-intro compact"><div><span class="eyebrow">DESEMPEÑO</span><h2>Indicadores y proyección</h2></div></div>', unsafe_allow_html=True)
        for name, data in profile["metrics"].items():
            _render_metric_card(name, data, target)
            st.write("")

    if profile["other"]:
        st.markdown('<div class="section-intro compact"><div><span class="eyebrow">CONTEXTO</span><h2>Otros datos encontrados</h2></div></div>', unsafe_allow_html=True)
        rows = [{"Campo": k, "Valores encontrados": ", ".join(v)} for k, v in profile["other"].items()]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with st.expander("🗂️ Ver todos los registros originales de esta persona", expanded=False):
        raw = profile["raw"][["source_file", "source_sheet", "period", "column", "value"]].copy()
        raw["value"] = raw["value"].astype(str)
        raw = raw.rename(columns={"source_file": "Archivo", "source_sheet": "Hoja", "period": "Periodo", "column": "Campo", "value": "Valor"})
        st.dataframe(raw, use_container_width=True, hide_index=True)


def _render_supervisor_view(long_df: pd.DataFrame):
    supervisors = supervisor_directory(long_df)
    if not supervisors:
        st.info("No se detectó ninguna columna de supervisor en los archivos procesados.")
        return

    selected_sup = st.selectbox("Busca y selecciona un supervisor", options=supervisors, key="tracking_supervisor_select")
    if not selected_sup:
        return

    roster = team_roster(long_df, selected_sup)
    if roster.empty:
        st.info("No se encontraron funcionarios a cargo de este supervisor.")
        return

    st.markdown(
        f'<div class="section-intro compact"><div><span class="eyebrow">EQUIPO</span>'
        f'<h2>{selected_sup} · {len(roster)} funcionario{"s" if len(roster)!=1 else ""} a cargo</h2></div></div>',
        unsafe_allow_html=True,
    )
    table = roster[["person_name", "person_id", "sources", "match_confidence"]].rename(
        columns={"person_name": "Nombre", "person_id": "ID", "sources": "Aparece en", "match_confidence": "Confianza del cruce"}
    )
    table["Aparece en"] = table["Aparece en"].apply(lambda x: ", ".join(x) if isinstance(x, list) else x)
    st.dataframe(table, use_container_width=True, hide_index=True)

    st.markdown('<div class="section-intro compact"><div><span class="eyebrow">DETALLE</span><h2>Perfil de un funcionario del equipo</h2></div></div>', unsafe_allow_html=True)
    labels = {row.person_key: f"{row.person_name} ({row.person_id})" if row.person_id else row.person_name for row in roster.itertuples()}
    pick = st.selectbox("Selecciona a quién revisar", options=list(labels.keys()), format_func=lambda k: labels.get(k, k), key="tracking_supervisor_pick_person")
    if pick:
        profile = person_profile(long_df, pick)
        if profile:
            identity = profile["identity"]
            st.markdown(f'**{identity["name"]}** · ID {identity["id"] or "—"}')
            target = st.date_input("Proyectar hasta", value=_month_end(datetime.now()).date(), key="tracking_supervisor_target_date")
            for name, data in profile["metrics"].items():
                _render_metric_card(name, data, target)
                st.write("")


def render_tracking(long_df: pd.DataFrame):
    st.markdown(
        '<div class="section-intro"><div><span class="eyebrow">ANÁLISIS SEGUIMIENTO</span>'
        '<h2>Seguimiento y proyección por funcionario</h2></div></div>',
        unsafe_allow_html=True,
    )
    if long_df is None or long_df.empty:
        st.info("Sube uno o más Excel en la sección \"📍 Análisis de seguimiento\" de la barra lateral para empezar.")
        return

    n_people = long_df["person_key"].nunique()
    n_sources = long_df["source_file"].nunique()
    c1, c2 = st.columns(2)
    c1.markdown(f'<div class="kpi-card"><span class="kpi-label">Funcionarios detectados</span><div class="kpi-value">{n_people:,}</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card"><span class="kpi-label">Archivos combinados</span><div class="kpi-value">{n_sources:,}</div></div>', unsafe_allow_html=True)
    st.write("")
    _download_consolidated_button(long_df)
    st.divider()

    tabs = st.tabs(["👤 Empleado", "🧑‍💼 Supervisor"])
    with tabs[0]:
        _render_employee_view(long_df)
    with tabs[1]:
        _render_supervisor_view(long_df)
