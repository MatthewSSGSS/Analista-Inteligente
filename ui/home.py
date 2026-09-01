"""Pestaña de Inicio: una introducción breve antes de entrar al dashboard.

No repite el análisis de las demás pestañas; da contexto (qué hace la
herramienta, qué se cargó, cómo moverse) y usa clases de estilo ya definidas
en app.py para no introducir CSS adicional.
"""
from __future__ import annotations
import streamlit as st


def _step(number: str, title: str, text: str) -> str:
    return (
        f'<div class="drilldown-card" style="display:flex;gap:14px;align-items:flex-start;padding:16px;">'
        f'<div class="action-number" style="flex:0 0 30px;width:30px;height:30px;border-radius:50%;'
        f'background:radial-gradient(circle at 32% 28%,#ff4d4d,#e4002b 55%,#a80e1f 100%);color:#fff;'
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
    st.markdown(
        '<div class="hero" style="border-bottom:none;padding-bottom:4px;">'
        '<div style="display:flex;align-items:center;gap:14px;">'
        '<div style="width:46px;height:46px;border-radius:50%;flex:0 0 46px;'
        'background:radial-gradient(circle at 32% 28%,#ff4d4d,#e4002b 55%,#a80e1f 100%);'
        'box-shadow:inset 0 -3px 6px rgba(0,0,0,.22),inset 0 2px 3px rgba(255,255,255,.35);"></div>'
        '<div><h1 style="margin:0;">Bienvenido al Panel Analítico Universal</h1>'
        '<p style="margin:4px 0 0;">Sube cualquier Excel o CSV y obtén, en segundos, KPIs, hallazgos, '
        'alertas, comparaciones y un informe listo para compartir — sin depender de una estructura fija.</p></div>'
        '</div></div>',
        unsafe_allow_html=True,
    )

    # ── Snapshot del archivo cargado ───────────────────────────────────────
    st.markdown(
        '<div class="section-intro compact"><div><span class="eyebrow">ARCHIVO ACTUAL</span>'
        '<h2>Qué se cargó</h2></div></div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div class="kpi-card"><span class="kpi-label">Archivo</span><div class="kpi-value" style="font-size:15px;">{wb.get("filename","—")}</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card"><span class="kpi-label">Hojas con datos</span><div class="kpi-value">{len(sheets):,}</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card"><span class="kpi-label">Registros totales</span><div class="kpi-value">{total_records:,}</div></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card"><span class="kpi-label">Hoja activa</span><div class="kpi-value" style="font-size:15px;">{sheet}</div></div>', unsafe_allow_html=True)

    if classification:
        cap_labels = {"evolucion": "evolución", "comparacion_periodos": "comparación de periodos", "ranking": "rankings", "distribucion": "distribuciones", "relaciones": "relaciones entre métricas", "estadisticas": "estadísticas", "grafico_distribucion": "gráficos de distribución", "geografia": "geografía", "catalogo": "consulta de catálogo", "estados": "seguimiento de estados"}
        caps = classification.get("capabilities", [])
        readable = ", ".join(cap_labels.get(x, x) for x in caps[:6]) or "lectura y tabla"
        st.markdown(
            f'<div class="decision-strip"><span class="decision-dot"></span>'
            f'<b>Tipo detectado en "{sheet}":</b> {classification.get("label","Datos generales")} '
            f'· confianza {classification.get("confidence",0)*100:.0f}% · Herramientas activadas: {readable}.</div>',
            unsafe_allow_html=True,
        )

    # ── Cómo moverse por la herramienta ────────────────────────────────────
    st.markdown(
        '<div class="section-intro compact"><div><span class="eyebrow">CÓMO EMPEZAR</span>'
        '<h2>Recorrido rápido</h2></div></div>',
        unsafe_allow_html=True,
    )
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
