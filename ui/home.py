"""Pestaña de Inicio: una introducción breve antes de entrar al dashboard.

No repite el análisis de las demás pestañas; da contexto (qué hace la
herramienta, qué se cargó, cómo moverse) y usa clases de estilo ya definidas
en app.py para no introducir CSS adicional.
"""
from __future__ import annotations
import streamlit as st

from ui.components.cards import kpi_card
from ui.components.section import section_header, decision_strip
from ui.layouts.hero import hero


def _step(number: str, title: str, text: str) -> str:
    return (
        f'<div class="drilldown-card" style="display:flex;gap:14px;align-items:flex-start;padding:16px;">'
        f'<div class="action-number" style="flex:0 0 30px;width:30px;height:30px;border-radius:50%;'
        f'background:var(--brand-orb);color:#fff;'
        f'display:flex;align-items:center;justify-content:center;font-weight:800;font-size:13px;">{number}</div>'
        f'<div><b style="font-size:13.5px;">{title}</b>'
        f'<div style="color:var(--muted);font-size:12.5px;margin-top:3px;line-height:1.45;">{text}</div></div>'
        f'</div>'
    )


def render_home(wb: dict, sheet: str, mode_info: dict, dashboard: dict) -> None:
    sheets = wb.get("sheets", {}) or {}
    total_records = sum(len(it.get("processed", [])) for it in sheets.values() if isinstance(it, dict))
    classification = (mode_info or {}).get("classification", {}) or {}

    # ── Hero de bienvenida, con el círculo rojo como acento de marca ──────
    hero(
        "Bienvenido al Panel Analítico Universal",
        "Sube cualquier Excel o CSV y obtén, en segundos, KPIs, hallazgos, "
        "alertas, comparaciones y un informe listo para compartir — sin depender de una estructura fija.",
        icon=True, tight=True,
    )

    # ── Snapshot del archivo cargado ───────────────────────────────────────
    st.markdown(section_header("Qué se cargó", eyebrow="ARCHIVO ACTUAL", compact=True), unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(kpi_card("Archivo", wb.get("filename", "—"), small_value=True), unsafe_allow_html=True)
    c2.markdown(kpi_card("Hojas con datos", f"{len(sheets):,}"), unsafe_allow_html=True)
    c3.markdown(kpi_card("Registros totales", f"{total_records:,}"), unsafe_allow_html=True)
    c4.markdown(kpi_card("Hoja activa", sheet, small_value=True), unsafe_allow_html=True)

    if classification:
        cap_labels = {"evolucion": "evolución", "comparacion_periodos": "comparación de periodos", "ranking": "rankings", "distribucion": "distribuciones", "relaciones": "relaciones entre métricas", "estadisticas": "estadísticas", "grafico_distribucion": "gráficos de distribución", "geografia": "geografía", "catalogo": "consulta de catálogo", "estados": "seguimiento de estados"}
        caps = classification.get("capabilities", [])
        readable = ", ".join(cap_labels.get(x, x) for x in caps[:6]) or "lectura y tabla"
        text = (
            f'<b>Tipo detectado en "{sheet}":</b> {classification.get("label","Datos generales")} '
            f'· confianza {classification.get("confidence",0)*100:.0f}% · Herramientas activadas: {readable}.'
        )
        st.markdown(decision_strip(text, dot=True), unsafe_allow_html=True)
        reason = classification.get("reason")
        if reason:
            with st.expander("¿Por qué este tipo?", expanded=False):
                st.caption(reason)

    # ── Cómo moverse por la herramienta ────────────────────────────────────
    st.markdown(section_header("Recorrido rápido", eyebrow="CÓMO EMPEZAR", compact=True), unsafe_allow_html=True)
    s1, s2 = st.columns(2)
    with s1:
        st.markdown(_step("1", "Resumen ejecutivo", "KPIs, tendencia, hallazgos y alertas calculados automáticamente sobre tus datos."), unsafe_allow_html=True)
        st.write("")
        st.markdown(_step("2", "Filtros y segmentación", "Usa la barra lateral para acotar por persona, categoría, región o periodo. Todo el panel se recalcula solo."), unsafe_allow_html=True)
    with s2:
        st.markdown(_step("3", "Asistente IA y comparaciones", "Pregunta directamente sobre tus datos, compara personas o compara archivos/periodos completos."), unsafe_allow_html=True)
        st.write("")
        st.markdown(_step("4", "Exportar", "Descarga un informe HTML autocontenido (una hoja o el Excel completo) listo para compartir por correo."), unsafe_allow_html=True)

    st.markdown(
        '<div class="chart-reading" style="margin-top:18px;"><b>Tip:</b> cada pestaña recalcula sus '
        'indicadores en tiempo real según los filtros activos en la barra lateral.</div>',
        unsafe_allow_html=True,
    )
