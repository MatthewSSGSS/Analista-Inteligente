"""Sección "Alertas": el motor ya construye una lectura evidencia →
significado → acción (`core.executive.build_alerts`, corrido dentro de
`core.dashboard_engine.build_dashboard`) y `ui/dashboard.py` ya sabe
dibujarla (`_alerts_panel`) — hasta ahora enterrada dentro de la pestaña
"Descripción" → sub-pestaña "Diagnóstico", donde no tenía sección propia.

Este módulo no añade ningún cálculo nuevo: reutiliza `_executive_headline` y
`_alerts_panel` tal cual existen, y solo añade un aviso de cuántas anomalías
de fila (`dashboard["anomalies"]`) hay, con el detalle completo remitido a
Explorar → Anomalías (`ui/anomalies.py`) para no duplicar la tabla.
"""
from __future__ import annotations
import pandas as pd
import streamlit as st
from ui.dashboard import _executive_headline, _alerts_panel


def render_alerts(df, dashboard: dict) -> None:
    st.markdown(
        '<div class="section-intro"><div><span class="eyebrow">DÓNDE HAY UN PROBLEMA</span>'
        '<h2>Alertas</h2><div class="chart-subtitle">Evidencia, significado y qué conviene revisar primero — ya calculado por el motor de análisis.</div></div></div>',
        unsafe_allow_html=True,
    )

    _executive_headline(dashboard)
    _alerts_panel(df, dashboard)

    anomalies = dashboard.get("anomalies") if isinstance(dashboard, dict) else None
    if isinstance(anomalies, pd.DataFrame) and not anomalies.empty:
        st.caption(f"Además, {len(anomalies):,} valores atípicos detectados · ver detalle en Explorar → Anomalías.")
