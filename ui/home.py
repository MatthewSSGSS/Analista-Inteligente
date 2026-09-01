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


def render_home_universal(summary_data: dict):
    """
    Renderiza la portada dinámica utilizando el diccionario summary_data.
    """
    # 1. Extracción de variables dinámicas del dataset
    filename = summary_data.get("filename", "Archivo.xlsx")
    sheets_count = summary_data.get("sheets_count", 0)
    total_rows = summary_data.get("total_rows", 0)
    active_sheet = summary_data.get("active_sheet", "Principal")
    confidence = summary_data.get("confidence", "90%")
    detected_type = summary_data.get("detected_type", "General")
    tools = summary_data.get("tools", "Analítica general activada")

    # 2. HERO BANNER
    st.markdown("""
    <div style="
        background: linear-gradient(135deg, rgba(22, 27, 34, 0.95) 0%, rgba(255, 42, 95, 0.12) 100%);
        border: 1px solid rgba(255, 42, 95, 0.35);
        border-radius: 12px;
        padding: 20px 24px;
        display: flex;
        align-items: center;
        gap: 16px;
        box-shadow: 0 0 20px rgba(255, 42, 95, 0.15);
        margin-bottom: 24px;
    ">
        <div style="
            background: #FF2A5F;
            width: 44px;
            height: 44px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 0 12px rgba(255, 42, 95, 0.6);
            font-size: 20px;
            flex-shrink: 0;
        ">⚡</div>
        <div>
            <h2 style="margin: 0; font-size: 1.35rem; font-weight: 800; color: #FFFFFF; border: none; padding: 0;">Panel Analítico Universal</h2>
            <p style="margin: 4px 0 0 0; color: #8B949E; font-size: 0.88rem;">De Excel crudo a decisiones: qué pasó, dónde pasó, qué lo explica y qué conviene revisar.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 3. SECCIÓN QUÉ SE CARGÓ (Grid Unificado)
    st.markdown("### 📂 Qué se cargó")

    st.markdown(f"""
    <div style="
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 12px;
        margin-bottom: 20px;
    ">
        <div style="background: #161B22; border: 1px solid #21262D; border-radius: 10px; padding: 14px; min-width: 0;">
            <span style="color: #8B949E; font-size: 0.7rem; font-weight: 700; letter-spacing: 0.05em; display: block;">ARCHIVO</span>
            <p style="margin: 6px 0 0 0; font-size: 0.88rem; font-weight: 700; color: #F0F6FC; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="{filename}">
                📄 {filename}
            </p>
        </div>
        
        <div style="background: #161B22; border: 1px solid #21262D; border-radius: 10px; padding: 14px;">
            <span style="color: #8B949E; font-size: 0.7rem; font-weight: 700; letter-spacing: 0.05em; display: block;">HOJAS CON DATOS</span>
            <p style="margin: 6px 0 0 0; font-size: 1.2rem; font-weight: 800; color: #FFFFFF;">{sheets_count}</p>
        </div>
        
        <div style="background: #161B22; border: 1px solid #21262D; border-radius: 10px; padding: 14px;">
            <span style="color: #8B949E; font-size: 0.7rem; font-weight: 700; letter-spacing: 0.05em; display: block;">REGISTROS TOTALES</span>
            <p style="margin: 6px 0 0 0; font-size: 1.2rem; font-weight: 800; color: #FFFFFF;">{total_rows:,}</p>
        </div>
        
        <div style="background: rgba(255, 42, 95, 0.05); border: 1px solid #FF2A5F; border-radius: 10px; padding: 14px; box-shadow: 0 0 10px rgba(255, 42, 95, 0.2); min-width: 0;">
            <span style="color: #FF2A5F; font-size: 0.7rem; font-weight: 800; letter-spacing: 0.05em; display: block;">HOJA ACTIVA</span>
            <p style="margin: 6px 0 0 0; font-size: 1.1rem; font-weight: 800; color: #FFFFFF; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                📌 {active_sheet}
            </p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 4. BANNER DE DETECCIÓN INTELIGENTE
    st.markdown(f"""
    <div style="
        background: #161B22;
        border: 1px solid #21262D;
        border-left: 4px solid #00E676;
        border-radius: 8px;
        padding: 12px 16px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 12px;
        margin-bottom: 24px;
    ">
        <div style="display: flex; align-items: center; gap: 12px;">
            <span style="
                background: rgba(0, 230, 118, 0.15);
                color: #00E676;
                border: 1px solid #00E676;
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 0.72rem;
                font-weight: 800;
                letter-spacing: 0.05em;
            ">CONFIANZA {confidence}</span>
            <span style="font-size: 0.9rem; color: #F0F6FC;">
                <b>Tipo detectado en "{active_sheet}":</b> {detected_type}
            </span>
        </div>
        <span style="font-size: 0.82rem; color: #8B949E;">
            Herramientas activadas: {tools}
        </span>
    </div>
    """, unsafe_allow_html=True)

    # 5. CÓMO MOVERSE POR LA HERRAMIENTA
    st.markdown("### 🗺️ Recorrido rápido")

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
        '<div style="margin-top:20px; padding:12px; background:rgba(255,255,255,0.03); border-radius:8px; border:1px solid #21262D; font-size:0.85rem; color:#8B949E;">'
        '<b style="color:#F0F6FC;">Tip:</b> Cada pestaña recalcula sus indicadores en tiempo real según los filtros activos en la barra lateral.</div>',
        unsafe_allow_html=True,
    )