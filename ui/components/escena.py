"""Pantallas hechas en HTML/CSS/JavaScript dentro de Streamlit.

Python decide qué se muestra y qué pasa con cada clic; JavaScript solo dibuja
(animaciones, tarjetas, efectos) y avisa del clic con
`setTriggerValue("accion", ...)`. Se montan con `st.components.v2`: el HTML va
directo en la página (no en un iframe), así que hereda los tokens del tema
(`var(--text)`, `var(--panel)`…) y se ve bien en claro y en oscuro.

Los archivos viven en `ui/web/`: `comun.css`/`comun.js` (base y utilidades
compartidas) más un `.css`/`.js` por pantalla. El `.js` de cada pantalla
exporta por defecto la función que recibe el componente.

Si `st.components.v2` no existe (Streamlit viejo) o el montaje falla,
`escena` devuelve `NO_DISPONIBLE` y la vista dibuja su versión clásica en
Streamlit puro: nunca queda una pantalla en blanco sin botones.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

_WEB = Path(__file__).resolve().parent.parent / "web"
_registradas: dict = {}

NO_DISPONIBLE = object()


def _leer(nombre: str) -> str:
    ruta = _WEB / nombre
    return ruta.read_text(encoding="utf-8") if ruta.exists() else ""


def disponible() -> bool:
    try:
        from streamlit.components import v2
    except Exception:
        return False
    return hasattr(v2, "component")


def _componente(nombre: str):
    # Se registra una vez por proceso: registrar en cada rerun haría que
    # Streamlit avisara de nombres repetidos y remontara la pantalla.
    if nombre not in _registradas:
        from streamlit.components import v2
        _registradas[nombre] = v2.component(
            f"escena_{nombre}",
            css=_leer("comun.css") + "\n" + _leer(f"{nombre}.css"),
            js=_leer("comun.js") + "\n" + _leer(f"{nombre}.js"),
        )
    return _registradas[nombre]


def escena(nombre: str, datos: dict, clave: str):
    """Monta la pantalla `ui/web/<nombre>.*` con `datos`.

    Devuelve la acción que eligió el usuario en este rerun (texto), None si
    no eligió nada, o `NO_DISPONIBLE` si hay que usar la versión clásica."""
    if not disponible():
        return NO_DISPONIBLE
    try:
        resultado = _componente(nombre)(data=datos, key=clave, on_accion_change=lambda: None)
    except Exception:
        return NO_DISPONIBLE
    return getattr(resultado, "accion", None)
