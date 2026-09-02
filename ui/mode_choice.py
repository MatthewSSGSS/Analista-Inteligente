"""Pantalla intermedia entre la bienvenida y el resto de la app: elegir entre
Análisis Práctico (subir, preguntar, listo) o Análisis Avanzado (el Panel
Analítico Universal completo que ya existía)."""
from __future__ import annotations
import streamlit as st
from ui.assets import image_data_uri


def render_mode_choice() -> str | None:
    """Muestra las 2 tarjetas. Devuelve 'practico' o 'avanzado' si el
    usuario eligió una, o None si sigue sin elegir."""
    # Foto de portada de cada tarjeta (assets/images/*.jpg, provistas por el
    # usuario). "Práctico" = circuito (procesamiento rápido); "Avanzado" =
    # mapa mundial (la propia tarjeta menciona georreferenciación).
    practico_cover = image_data_uri("circuito.jpg")
    avanzado_cover = image_data_uri("mapa.jpg")

    st.markdown(
        """
        <style>
        @keyframes fadeUp{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}
        .mode-hero{text-align:center;max-width:640px;margin:5vh auto 34px;padding:0 12px;animation:fadeUp .5s ease both}
        .mode-hero h1{font-size:26px;font-weight:850;letter-spacing:-.02em;margin:0 0 8px;color:var(--text)}
        .mode-hero p{font-size:13.5px;color:var(--muted)}
        .mode-cards{display:grid;grid-template-columns:1fr 1fr;gap:20px;max-width:920px;margin:0 auto;padding:0 12px}
        .mode-card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-lg);
          overflow:hidden;box-shadow:var(--shadow-md),var(--glow-ring);animation:fadeUp .55s ease both;
          transition:transform .18s ease,box-shadow .18s ease}
        .mode-card:hover{transform:translateY(-3px);box-shadow:var(--shadow-lg),var(--glow-ring)}
        .mode-card:nth-child(2){animation-delay:.08s}
        /* Foto de portada: bg-image a todo el ancho, con un degradado que se
           funde con var(--panel) hacia abajo para que el texto de la tarjeta
           (que sigue viviendo en .mode-card-body, sobre fondo sólido) nunca
           pierda contraste — la foto es decorativa, no el fondo del texto. */
        .mode-card-cover{height:132px;background-size:cover;background-position:center;position:relative}
        .mode-card-cover:after{content:"";position:absolute;inset:0;
          background:linear-gradient(to top,var(--panel) 0%,rgba(0,0,0,0) 75%)}
        .mode-card-body{padding:18px 24px 26px}
        .mode-card-icon{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:21px;margin:-38px 0 14px;position:relative;box-shadow:var(--shadow-md)}
        .mode-card.practico .mode-card-icon{background:var(--blue-soft);color:var(--blue-strong)}
        .mode-card.avanzado .mode-card-icon{background:var(--purple-soft);color:var(--purple)}
        .mode-card h3{margin:0 0 6px;font-size:17px;font-weight:800;font-family:'Sora','Inter',sans-serif}
        .mode-card p{margin:0 0 4px;font-size:13px;color:var(--muted);line-height:1.55;min-height:64px}
        .mode-card ul{margin:10px 0 0;padding-left:18px;font-size:12px;color:var(--muted)}
        .mode-card li{margin-bottom:3px}
        @media(max-width:760px){.mode-cards{grid-template-columns:1fr}}
        </style>
        <div class="mode-hero">
          <h1>¿Cómo quieres analizar tu Excel hoy?</h1>
          <p>Elige según lo que necesites — puedes cambiar de modo cuando quieras.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2, gap="large")
    choice = None

    with col1:
        st.markdown(
            f"""
            <div class="mode-card practico">
              <div class="mode-card-cover" style="background-image:url({practico_cover})"></div>
              <div class="mode-card-body">
                <div class="mode-card-icon">⚡</div>
                <h3>Análisis Práctico</h3>
                <p>Sube tu Excel, dale un vistazo rápido y pregúntale lo que quieras saber en tus propias
                palabras. Ideal para una respuesta rápida sin tener que navegar menús.</p>
                <ul>
                  <li>Resumen simple y directo</li>
                  <li>Pregúntale en lenguaje natural</li>
                  <li>Respuestas con datos reales, nunca inventadas</li>
                </ul>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("⚡ Empezar Análisis Práctico", type="primary", use_container_width=True, key="choose_practico"):
            choice = "practico"

    with col2:
        st.markdown(
            f"""
            <div class="mode-card avanzado">
              <div class="mode-card-cover" style="background-image:url({avanzado_cover})"></div>
              <div class="mode-card-body">
                <div class="mode-card-icon">🧭</div>
                <h3>Análisis Avanzado</h3>
                <p>El Panel Analítico Universal completo: filtros, comparaciones, seguimiento por
                funcionario, georreferenciación, exportación e informes HTML.</p>
                <ul>
                  <li>Todas las herramientas que ya conoces</li>
                  <li>Ideal para un análisis a fondo</li>
                  <li>Exportación e informes completos</li>
                </ul>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("🧭 Ir a Análisis Avanzado", use_container_width=True, key="choose_avanzado"):
            choice = "avanzado"

    return choice
