"""Pantalla de bienvenida (landing) que se muestra ANTES de pedir el Excel.

Se activa cuando `st.session_state.app_started` es False. Al hacer clic en
"Comenzar" se pone en True y la app pasa al flujo normal (sidebar +
uploader). Reutiliza las clases de estilo definidas en app.py.
"""
from __future__ import annotations
import streamlit as st

_CAPABILITIES = [
    ("01", "Detecta", "Reconoce automáticamente el tipo de Excel y adapta la lectura a ventas, catálogos, personas, operaciones, finanzas, listas y otros contextos."),
    ("02", "Explica", "Prioriza qué cambió, dónde está la diferencia, qué segmentos pesan más y qué conviene revisar."),
    ("03", "Visualiza", "Construye gráficos solo cuando la estructura del archivo permite responder una pregunta con sentido."),
    ("04", "Comparte", "Exporta una lectura ejecutiva en HTML lista para enviar, sin entregar toda la base de datos."),
]

_STEPS = [
    ("1", "Carga el Excel", "Desde la barra lateral, en cualquier momento."),
    ("2", "Revisa el resumen", "Empieza por la lectura ejecutiva: qué pasó y qué conviene mirar primero."),
    ("3", "Profundiza", "Usa filtros, gráficos, personas o geografía cuando existan en tu archivo."),
    ("4", "Exporta", "Genera un informe listo para compartir, en un link o en un HTML autocontenido."),
]


def _capability_card(number: str, title: str, text: str) -> str:
    return (
        '<div class="landing-cap-card">'
        f'<span class="landing-cap-number">{number}</span>'
        f'<h3>{title}</h3>'
        f'<p>{text}</p>'
        '</div>'
    )


def _how_step(number: str, title: str, text: str) -> str:
    return (
        '<div class="landing-step">'
        f'<span class="landing-step-number">{number}</span>'
        f'<div><b>{title}</b><p>{text}</p></div>'
        '</div>'
    )


def render_landing() -> bool:
    """Dibuja la bienvenida. Devuelve True si el usuario ya le dio a "Comenzar"."""
    st.markdown(
        """
        <style>
        .landing-hero{text-align:center;max-width:720px;margin:6vh auto 8px;padding:0 12px}
        .landing-mark{width:64px;height:64px;border-radius:50%;margin:0 auto 20px;
          background:var(--brand-orb);
          box-shadow:inset 0 -4px 8px rgba(0,0,0,.22),inset 0 3px 4px rgba(255,255,255,.35),0 10px 24px rgba(228,0,43,.22)}
        .landing-hero h1{font-size:32px;font-weight:850;letter-spacing:-.02em;margin:0 0 10px;color:var(--text)}
        .landing-hero p{font-size:14.5px;color:var(--muted);line-height:1.55;margin:0 auto}
        .landing-caps{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;max-width:1180px;margin:34px auto 0}
        .landing-cap-card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-lg);
          padding:18px 18px 20px;box-shadow:var(--shadow-sm)}
        .landing-cap-number{display:inline-block;font-size:11px;font-weight:800;color:var(--blue);
          background:var(--blue-soft);border-radius:999px;padding:3px 9px;margin-bottom:12px}
        .landing-cap-card h3{margin:0 0 6px;font-size:15.5px;font-weight:800;color:var(--text)}
        .landing-cap-card p{margin:0;font-size:12.5px;color:var(--muted);line-height:1.5}
        .landing-how{max-width:1180px;margin:22px auto 0;background:var(--sidebar-bg);border-radius:var(--radius-lg);
          padding:26px 28px 22px;box-shadow:var(--shadow-lg)}
        .landing-how-eyebrow{font-size:10.5px;font-weight:800;letter-spacing:.12em;color:#ff5b6c;text-transform:uppercase}
        .landing-how h2{margin:6px 0 18px;font-size:19px;font-weight:800;color:#fff}
        .landing-steps{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
        .landing-step{display:flex;flex-direction:column;gap:10px;background:rgba(255,255,255,.04);
          border:1px solid rgba(255,255,255,.08);border-radius:var(--radius-md);padding:14px}
        .landing-step-number{width:24px;height:24px;border-radius:7px;background:#e4002b;color:#fff;
          font-weight:800;font-size:12px;display:flex;align-items:center;justify-content:center}
        .landing-step b{color:#fff;font-size:13px}
        .landing-step p{margin:3px 0 0;color:#9aa2b8;font-size:11.5px;line-height:1.5}
        .landing-cta{max-width:1180px;margin:0 auto;padding-top:2px}
        @media(max-width:900px){.landing-caps,.landing-steps{grid-template-columns:repeat(2,1fr)}}
        @media(max-width:560px){.landing-caps,.landing-steps{grid-template-columns:1fr}}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="landing-hero"><div class="landing-mark"></div>'
        '<h1>Panel Analítico Universal</h1>'
        '<p>Sube cualquier Excel o CSV y obtén, en segundos, KPIs, hallazgos, alertas, comparaciones '
        'y un informe listo para compartir con dirección — sin depender de una estructura fija.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    _, mid, _ = st.columns([1, 1, 1])
    with mid:
        start = st.button("Comenzar →", type="primary", use_container_width=True, key="landing_start_btn")

    st.markdown(
        '<div class="landing-caps">' + "".join(_capability_card(*c) for c in _CAPABILITIES) + '</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="landing-how"><span class="landing-how-eyebrow">Cómo usarlo</span><h2>Un flujo sencillo</h2>'
        '<div class="landing-steps">' + "".join(_how_step(*s) for s in _STEPS) + '</div></div>',
        unsafe_allow_html=True,
    )

    st.write("")
    st.write("")
    return start
