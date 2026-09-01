"""Tarjetas de datos: KPI, insight/hallazgo, y el veredicto ejecutivo.

`kpi_card`/`insight_card` devuelven HTML (no renderizan por sí mismas)
porque casi siempre se combinan varias en una fila de `st.columns(...)`;
quien las use decide dónde y con qué `st.markdown(html, unsafe_allow_html=True)`.
`executive_headline`/`executive_signals` sí renderizan directamente, igual
que `chart_card` en `ui/components/charts.py`.
"""
from __future__ import annotations

import streamlit as st


def kpi_card(label, value, delta=None, tone: str = "neutral", icon=None, small_value: bool = False) -> str:
    """Tarjeta `.kpi-card`. Antes duplicada como `_card()` en
    `ui/dashboard.py` y `ui/person_profile.py`, y reescrita a mano en
    `ui/home.py` (snapshot del archivo) y `ui/comparison.py` (con icono de
    tendencia). `icon` reproduce esa variante con flecha; `small_value`
    reproduce el valor en texto (nombre de archivo/hoja) más pequeño que un
    número, tal como ya hacía `ui/home.py`.
    """
    label_html = (
        f'<div class="kpi-top"><span class="kpi-icon">{icon}</span><span class="kpi-label">{label}</span></div>'
        if icon is not None else f'<span class="kpi-label">{label}</span>'
    )
    value_style = ' style="font-size:15px;"' if small_value else ""
    delta_html = f'<div class="kpi-delta {tone}">{delta}</div>' if delta else ""
    return (
        f'<div class="kpi-card {tone}">{label_html}'
        f'<div class="kpi-value"{value_style}>{value}</div>{delta_html}</div>'
    )


def insight_card(
    text,
    title=None,
    label=None,
    kind: str = "info",
    icon=None,
    action=None,
    action_label: str = "Qué hacer",
    compact: bool = False,
) -> str:
    """Tarjeta `.insight-card`. Antes escrita a mano de tres formas
    distintas en `ui/executive.py` (sin icono, con acción "Qué revisar"),
    `ui/dashboard.py::_insights_panel` (con icono, `compact`, acción "Qué
    hacer") y `ui/comparison.py` (con icono, encabezado fijo en vez de
    título por tarjeta).

    - `title`: encabezado dinámico por tarjeta (`.insight-title`).
    - `label`: encabezado fijo tipo eyebrow (`.insight-label`) — se usa
      cuando la tarjeta no tiene un título propio, solo una categoría fija
      (p. ej. "HALLAZGO COMPARATIVO"). Se usa uno u otro, no ambos.
    """
    classes = f"insight-card{' compact' if compact else ''} {kind}"
    icon_html = f'<div class="insight-icon">{icon}</div>' if icon is not None else ""
    if label is not None:
        header_html = f'<div class="insight-label">{label}</div>'
    elif title is not None:
        header_html = f'<div class="insight-title">{title}</div>'
    else:
        header_html = ""
    action_html = f'<div class="insight-action"><b>{action_label}:</b> {action}</div>' if action else ""
    return (
        f'<div class="{classes}">{icon_html}<div class="insight-body">'
        f'{header_html}<div class="insight-text">{text}</div>{action_html}</div></div>'
    )


def executive_headline(dashboard: dict) -> None:
    """Veredicto ejecutivo (`.executive-card`): estado + titular + detalle,
    calculado por `core/executive.py::build_executive` y expuesto en
    `dashboard["executive"]`. Antes solo lo pintaba
    `ui/dashboard.py::_executive_headline`; ahora también lo usa
    `ui/executive.py`, con el mismo HTML exacto."""
    ex = dashboard.get("executive", {}) if isinstance(dashboard, dict) else {}
    cls = ex.get("status", "neutral")
    status_label = "Situación favorable" if cls == "positive" else "Requiere atención" if cls == "negative" else "Situación estable"
    st.markdown(
        f'<div class="executive-card {cls}"><div class="executive-status">{status_label}</div>'
        f'<div class="executive-headline">{ex.get("headline","")}</div>'
        f'<div class="executive-detail">{ex.get("detail","")}</div></div>',
        unsafe_allow_html=True,
    )


def executive_signals(dashboard: dict) -> None:
    """Señales positivas / puntos a vigilar (`ex["positive"]`/`ex["watch"]`),
    en dos columnas. Antes solo `ui/dashboard.py::_executive_signals`."""
    ex = dashboard.get("executive", {}) if isinstance(dashboard, dict) else {}
    a, b = st.columns(2)
    with a:
        st.markdown('<div class="mini-list"><b>Señales positivas</b></div>', unsafe_allow_html=True)
        for x in ex.get("positive", [])[:3]:
            st.markdown(f'<div class="mini-positive">✓ {x}</div>', unsafe_allow_html=True)
        if not ex.get("positive"):
            st.caption("No se detectaron mejoras destacadas automáticamente.")
    with b:
        st.markdown('<div class="mini-list"><b>Puntos a vigilar</b></div>', unsafe_allow_html=True)
        for x in ex.get("watch", [])[:3]:
            st.markdown(f'<div class="mini-warning">! {x}</div>', unsafe_allow_html=True)
        if not ex.get("watch"):
            st.caption("No se detectaron alertas prioritarias.")
