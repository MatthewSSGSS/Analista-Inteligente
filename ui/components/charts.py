"""Tarjeta de gráfico (`.chart-card.pbi-visual`): encabezado + `st.plotly_chart`
+ lectura/explicación opcionales + estado vacío.

Antes existían tres copias casi idénticas de esto: `ui/dashboard.py::_chart_card`
(con lectura y botón "Explicar gráfico"), `ui/georeferencing.py::_geo_card` y
`ui/person_profile.py::_chart` (ambas más simples, sin esos dos extras).
`chart_card()` cubre los tres casos con los mismos parámetros por defecto que
ya tenía `_chart_card`, así que las vistas más simples solo necesitan pasar
`visual_type`/`badge_text` para reproducir su texto exacto.

A diferencia de las tarjetas en `cards.py`, esta función renderiza
directamente (no devuelve HTML): intercala `st.plotly_chart` entre el
encabezado y el cierre del `<div>`, igual que hacían las tres funciones que
reemplaza.
"""
from __future__ import annotations

import re
import streamlit as st


def chart_card(
    title,
    subtitle,
    fig,
    empty: str = "No hay datos suficientes para este análisis.",
    insight=None,
    explain=None,
    key: str | None = None,
    visual_type: str = "VISUAL",
    badge_text: str = "Datos actuales",
) -> None:
    st.markdown(
        f'<div class="chart-card pbi-visual"><div class="chart-head"><div class="chart-head-main">'
        f'<span class="visual-type">{visual_type}</span>'
        f'<div class="chart-title">{title}</div><div class="chart-subtitle">{subtitle}</div></div>'
        f'<span class="data-badge visual-badge">{badge_text}</span></div>',
        unsafe_allow_html=True,
    )
    if fig is not None:
        # Streamlit exige claves únicas por elemento; el gráfico y su botón
        # de explicación son dos elementos distintos y nunca deben compartir
        # clave.
        safe_key = key or "chart_" + re.sub(r"[^a-zA-Z0-9_]+", "_", f"{title}_{subtitle}")[:80]
        chart_key = f"{safe_key}__chart"
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "responsive": True}, key=chart_key)
        if insight:
            st.markdown(f'<div class="chart-reading"><b>Lectura:</b> {insight}</div>', unsafe_allow_html=True)
        if explain:
            button_key = f"{safe_key}__explain"
            if st.button("💡 Explicar gráfico", key=button_key, use_container_width=False):
                st.markdown(f'<div class="chart-reading"><b>Interpretación:</b> {explain}</div>', unsafe_allow_html=True)
    else:
        st.info(empty)
    st.markdown('</div>', unsafe_allow_html=True)


def empty_state(message: str = "No hay datos suficientes para este análisis.") -> None:
    """Estado vacío de una sola línea, para usar fuera de una tarjeta de
    gráfico (chart_card ya incluye el suyo cuando `fig` es None)."""
    st.info(message)
