"""Encabezado principal de página (`.hero`).

Cubre el caso simple (título + subtítulo, usado por app.py para el
encabezado de toda la app) y la variante con el isotipo de marca a la
izquierda (usada por la pantalla de Inicio). `ui/tracking.py` tiene una
tercera variante (identidad de una persona + badge de confianza a la
derecha) lo bastante distinta — contenido específico de esa pantalla, no
solo título/subtítulo — que no se fuerza aquí; ver notas de la tarea 06.
"""
from __future__ import annotations

import streamlit as st


def hero(title: str, subtitle: str | None = None, icon: bool = False, tight: bool = False, band: bool = False) -> None:
    """Renderiza el bloque `.hero`. `icon=True` antepone el isotipo de
    marca (círculo `var(--brand-orb)`); `tight=True` reduce el aire debajo
    del título, como ya hacía la variante con icono.

    `band=True` añade la clase `hero-band`: es SOLO para el único hero de
    nivel superior de toda la app (el de app.py, antes de las pestañas) —
    ese es el que en ui/styles/theme.py se pinta encima de la franja de foto
    (`.block-container:before`, la misma foto ciudad_red.jpg que usan los
    banners de cada vista) y por eso necesita texto blanco fijo. Los otros
    dos usos de `hero()` (ui/home.py, ui/tracking.py) viven DENTRO del
    contenido de una pestaña, muy por debajo de esa franja, sobre fondo
    normal — nunca deben heredar el texto blanco, por eso es opt-in y no el
    comportamiento por defecto de `.hero`."""
    classes = "hero hero-band" if band else "hero"
    style = ' style="border-bottom:none;padding-bottom:4px;"' if tight else ""
    subtitle_html = f"<p>{subtitle}</p>" if subtitle else ""
    if icon:
        st.markdown(
            f'<div class="{classes}"{style}>'
            f'<div style="display:flex;align-items:center;gap:14px;">'
            f'<div style="width:46px;height:46px;border-radius:50%;flex:0 0 46px;'
            f'background:var(--brand-orb);'
            f'box-shadow:inset 0 -3px 6px rgba(0,0,0,.22),inset 0 2px 3px rgba(255,255,255,.35);"></div>'
            f'<div><h1>{title}</h1>{subtitle_html}</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(f'<div class="{classes}"{style}><h1>{title}</h1>{subtitle_html}</div>', unsafe_allow_html=True)
