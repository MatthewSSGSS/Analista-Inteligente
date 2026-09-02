"""Pantalla de bienvenida (landing) que se muestra ANTES de pedir el Excel.

Se activa cuando `st.session_state.app_started` es False. Al hacer clic en
"Comenzar" se pone en True y la app pasa al flujo normal (sidebar +
uploader). Reutiliza las clases de estilo definidas en app.py.
"""
from __future__ import annotations
import streamlit as st
from ui.assets import image_data_uri

# Foto de portada de cada tarjeta (assets/images/*.jpg, provistas por el
# usuario): circuito → procesamiento/detección, red de nodos → relaciones
# entre segmentos, barras 3D → visualización, mapa mundial → alcance/compartir.
_CAPABILITIES = [
    ("01", "Detecta", "Reconoce automáticamente el tipo de Excel y adapta la lectura a ventas, catálogos, personas, operaciones, finanzas, listas y otros contextos.", "circuito.jpg"),
    ("02", "Explica", "Prioriza qué cambió, dónde está la diferencia, qué segmentos pesan más y qué conviene revisar.", "datos1.jpg"),
    ("03", "Visualiza", "Construye gráficos solo cuando la estructura del archivo permite responder una pregunta con sentido.", "barras.jpg"),
    ("04", "Comparte", "Exporta una lectura ejecutiva en HTML lista para enviar, sin entregar toda la base de datos.", "mapa.jpg"),
]

# Las mismas 4 fotos de _CAPABILITIES, reutilizadas — no hace falta una
# imagen distinta por tarjeta, y así todo "Cómo usarlo" queda consistente
# con "Qué hace" de arriba en vez de sentirse una sección aparte.
_STEPS = [
    ("1", "Carga el Excel", "Desde la barra lateral, en cualquier momento.", "circuito.jpg"),
    ("2", "Revisa el resumen", "Empieza por la lectura ejecutiva: qué pasó y qué conviene mirar primero.", "barras.jpg"),
    ("3", "Profundiza", "Usa filtros, gráficos, personas o geografía cuando existan en tu archivo.", "mapa.jpg"),
    ("4", "Exporta", "Genera un informe listo para compartir, en un link o en un HTML autocontenido.", "datos1.jpg"),
]


def _capability_card(number: str, title: str, text: str, image: str) -> str:
    cover = image_data_uri(image)
    return (
        '<div class="landing-cap-card">'
        f'<div class="landing-cap-cover" style="background-image:url({cover})"></div>'
        '<div class="landing-cap-body">'
        f'<span class="landing-cap-number">{number}</span>'
        f'<h3>{title}</h3>'
        f'<p>{text}</p>'
        '</div>'
        '</div>'
    )


def _how_step(number: str, title: str, text: str, image: str) -> str:
    cover = image_data_uri(image)
    return (
        '<div class="landing-step">'
        f'<div class="landing-step-cover" style="background-image:url({cover})"></div>'
        '<div class="landing-step-body">'
        f'<span class="landing-step-number">{number}</span>'
        f'<div><b>{title}</b><p>{text}</p></div>'
        '</div>'
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
          overflow:hidden;box-shadow:var(--shadow-sm),var(--glow-ring);transition:transform .18s ease,box-shadow .18s ease}
        .landing-cap-card:hover{transform:translateY(-3px);box-shadow:var(--shadow-md),var(--glow-ring)}
        /* Foto de portada, igual criterio que en mode_choice.py: la imagen
           es decorativa y se funde con var(--panel) hacia abajo — el texto
           vive en .landing-cap-body, siempre sobre fondo sólido, nunca
           sobre la foto directamente. */
        .landing-cap-cover{height:76px;background-size:cover;background-position:center;position:relative}
        .landing-cap-cover:after{content:"";position:absolute;inset:0;
          background:linear-gradient(to top,var(--panel) 0%,rgba(0,0,0,0) 80%)}
        .landing-cap-body{padding:0 18px 20px}
        .landing-cap-number{display:inline-block;font-size:11px;font-weight:800;color:var(--blue-strong);
          background:var(--blue-soft);border-radius:999px;padding:3px 9px;margin:-14px 0 12px;position:relative;box-shadow:var(--shadow-sm)}
        .landing-cap-card h3{margin:0 0 6px;font-size:15.5px;font-weight:800;color:var(--text)}
        .landing-cap-card p{margin:0;font-size:12.5px;color:var(--muted);line-height:1.5}
        .landing-how{max-width:1180px;margin:22px auto 0;background:#0d1119;border-radius:var(--radius-lg);
          padding:26px 28px 22px;box-shadow:var(--shadow-lg)}
        .landing-how-eyebrow{font-size:10.5px;font-weight:800;letter-spacing:.12em;color:#ff5b6c;text-transform:uppercase}
        .landing-how h2{margin:6px 0 18px;font-size:19px;font-weight:800;color:#fff}
        .landing-steps{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
        .landing-step{background:rgba(255,255,255,.04);
          border:1px solid rgba(255,255,255,.08);border-radius:var(--radius-md);overflow:hidden}
        /* .landing-how es un panel siempre oscuro (fondo #0d1119 fijo, no
           sigue el tema — ver comentario junto a esa clase), así que el
           degradado de esta portada se funde con ese mismo oscuro fijo, no
           con var(--panel) como en las tarjetas de arriba. */
        .landing-step-cover{height:64px;background-size:cover;background-position:center;position:relative}
        .landing-step-cover:after{content:"";position:absolute;inset:0;
          background:linear-gradient(to top,#0d1119 0%,rgba(0,0,0,0) 85%)}
        .landing-step-body{display:flex;gap:10px;padding:12px 14px 14px}
        .landing-step-number{width:24px;height:24px;border-radius:7px;background:#e4002b;color:#fff;
          font-weight:800;font-size:12px;display:flex;align-items:center;justify-content:center;flex:0 0 24px;
          margin-top:-24px;position:relative;box-shadow:0 2px 8px rgba(0,0,0,.35)}
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
