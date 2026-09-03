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
_ASSETS_ROOT = Path(__file__).resolve().parent.parent / "assets"


@st.cache_data(show_spinner=False)
def image_data_uri(filename: str, mime: str = "image/jpeg") -> str:
    """Lee `assets/images/<filename>` y lo devuelve como `data:` URI.

    Cacheado: el archivo no cambia entre reruns de Streamlit, así que se
    lee y codifica en base64 una sola vez por sesión, no en cada clic.
    """
    data = (_ASSETS_DIR / filename).read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


@st.cache_data(show_spinner=False)
def background_data_uri(filename: str, mime: str = "image/jpeg") -> str:
    """Igual que `image_data_uri`, pero lee directo de `assets/<filename>`
    (no de `assets/images/`) — función nueva, separada a propósito, para
    no tocar `image_data_uri` ni las rutas que ya dependen de ella
    (mode_choice.py, landing.py, banner_header, el fondo del hero de
    Inicio...). Usa `open()+base64.b64encode()` igual que el fondo general
    de la app pidió explícitamente, solo que con ruta resuelta desde la
    ubicación real del proyecto (no desde el directorio de trabajo actual)
    y cacheada, para no releer/recodificar el archivo en cada rerun."""
    data = (_ASSETS_ROOT / filename).read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"
