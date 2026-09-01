"""Este módulo no añade ningún cálculo nuevo: reutiliza `_executive_headline` y
`_alerts_panel` tal cual existen, y solo añade un aviso de cuántas anomalías
de fila (`dashboard["anomalies"]`) hay, con el detalle completo remitido a
Explorar -> Anomalías (`ui/anomalies.py`) para no duplicar la tabla.
"""

from __future__ import annotations
import pandas as pd
import streamlit as st
from ui.dashboard import _executive_headline, _alerts_panel
from ui.components import card_kpi, section_header
from visualization.charts import apply_dashboard_theme


def render_alerts(df, dashboard: dict) -> None:
    # 1. ENCABEZADO UNIFICADO
    section_header(
        "🔔 Alertas e Indicadores Prioritarios",
        "Evidencia, significado y qué conviene revisar primero — ya calculado por el motor."
    )

    # 2. RESUMEN DE ALERTAS EN COLUMNAS (Evita que quede apilado)
    col_main, col_sidebar_info = st.columns([2.2, 1])

    with col_main:
        # Aquí renderizas las alertas principales calculadas
        _alerts_panel(df, dashboard)

    with col_sidebar_info:
        # Columna derecha: Headline/Resumen en tarjeta glassmorphic
        st.markdown('<div class="neon-card">', unsafe_allow_html=True)
        _executive_headline(dashboard)
        st.markdown('</div>', unsafe_allow_html=True)

    # 3. BANNER DE ANOMALÍAS DETECTADAS (En tarjeta de advertencia neón)
    anomalies = dashboard.get("anomalies") if isinstance(dashboard, dict) else None
    if isinstance(anomalies, pd.DataFrame) and not anomalies.empty:
        st.markdown(f"""
        <div style="
            background: rgba(255, 171, 0, 0.08);
            border: 1px solid rgba(255, 171, 0, 0.3);
            border-left: 4px solid #FFD600;
            border-radius: 8px;
            padding: 12px 16px;
            margin-top: 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        ">
            <span style="color: #FFD600; font-weight: 700; font-size: 0.88rem;">
                ⚠️ Además, se detectaron <b>{len(anomalies):,}</b> valores atípicos.
            </span>
            <span style="color: #8B949E; font-size: 0.8rem;">
                Ver detalle completo en <b>Explorar ➔ Anomalías</b>
            </span>
        </div>
        """, unsafe_allow_html=True)