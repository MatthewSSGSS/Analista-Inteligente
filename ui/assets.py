"""Imágenes locales (`assets/images/`) listas para usar en CSS.

Streamlit no expone una carpeta estática pública por defecto — no hay una
URL tipo `/assets/foo.jpg` que un `background-image:url(...)` pueda usar
directamente. La forma simple, sin tocar configuración del servidor, es
incrustar el archivo como `data:` URI dentro del propio HTML/CSS.
"""
from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "images"


@st.cache_data(show_spinner=False)
def image_data_uri(filename: str, mime: str = "image/jpeg") -> str:
    """Lee `assets/images/<filename>` y lo devuelve como `data:` URI.

    Cacheado: el archivo no cambia entre reruns de Streamlit, así que se
    lee y codifica en base64 una sola vez por sesión, no en cada clic.
    """
    data = (_ASSETS_DIR / filename).read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"
