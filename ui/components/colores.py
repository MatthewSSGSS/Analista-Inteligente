"""El color de cada sección del panel.

Cada vista tiene su color: la pestaña activa de la barra, los acentos de la
página (cejas de sección, franja de la tarjeta «Analizando», bordes de los
gráficos) y las pantallas animadas se tiñen con él, así se sabe dónde se
está de un vistazo. Verde y rojo NO se usan como color de sección: quedan
reservados para «va bien» y «va mal».
"""
from __future__ import annotations

import re

# (palabra clave de la etiqueta, color). Se busca por palabra clave porque
# las etiquetas llevan emoji («📋 Resumen») y algunas cambian con el modo.
_COLORES = (
    ("inicio", "#E4002B"),          # rojo de marca: la portada del panel
    ("resumen", "#2563EB"),         # azul
    ("descripci", "#2563EB"),
    ("qué atacar", "#EA580C"),      # naranja: acción
    ("cómo va", "#7C3AED"),         # morado
    ("analítica", "#7C3AED"),
    ("canales", "#0D9488"),         # verde azulado
    ("proyecci", "#4F46E5"),        # índigo
    ("georref", "#0891B2"),         # cian
    ("seguimiento", "#0284C7"),     # azul cielo
    ("asistente", "#C026D3"),       # fucsia
    ("exportar", "#475569"),        # pizarra
    ("estructura", "#B45309"),      # ámbar oscuro
    ("comparar personas", "#DB2777"),
    ("comparar archivos", "#0E7490"),
    ("varias hojas", "#D97706"),
    ("datos", "#475569"),
    ("calidad", "#0F766E"),
    ("anomal", "#BE123C"),
    ("finanzas", "#047857"),
    ("vista principal", "#2563EB"),
)
POR_DEFECTO = "#E4002B"


def color_de(etiqueta: str | None) -> str:
    t = str(etiqueta or "").lower()
    return next((c for clave, c in _COLORES if clave in t), POR_DEFECTO)


def slug(etiqueta: str) -> str:
    """Clave estable y válida para CSS a partir de la etiqueta («📋 Resumen» → «resumen»)."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(etiqueta)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_") or "vista"


def color_activo() -> str:
    """El color de la vista que se está mirando (para las pantallas y cabeceras)."""
    try:
        import streamlit as st
        return color_de(st.session_state.get("nav_vista"))
    except Exception:
        return POR_DEFECTO
