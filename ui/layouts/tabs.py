"""Navegación entre vistas.

`barra_de_vistas()` es la navegación de nivel superior de la app. Antes era
una sola fila de `st.tabs` con 11 a 16 pestañas, y tenía dos problemas:

- **Lenta**: `st.tabs` ejecuta TODAS las pestañas en cada interacción, se
  vean o no. Cambiar un filtro recalculaba las predicciones, armaba los
  cuatro informes HTML de Exportar, etc., aunque se estuviera mirando el
  Inicio.
- **Incómoda**: con tantas pestañas la fila se desplazaba de lado, lo usado
  todos los días quedaba mezclado con herramientas ocasionales y, al bajar
  por una vista larga, había que volver arriba para cambiar.

Ahora las vistas importantes van en una barra que queda fija arriba —la
activa, en píldora roja— y las herramientas ocasionales en «➕ Más». Solo
se dibuja la vista activa.

Como Streamlit borra el estado de los widgets que no se dibujan, lo que
tenga que sobrevivir al cambio de vista (por ejemplo, los pasos marcados de
un plan) debe guardarse fuera del widget; ver `ui/planes.py`.

`named_tabs()` sigue sirviendo para pestañas DENTRO de una vista.
"""
from __future__ import annotations

from typing import Callable

import streamlit as st

Vista = tuple[str, Callable[[], None]]

_CLAVE = "nav_vista"

# Nombres de las vistas a las que otras vistas pueden mandar con `ir_a()`.
# Viven aquí para que el botón y la barra usen exactamente el mismo texto.
VISTA_RESUMEN = "📋 Resumen"
VISTA_ATACAR = "🎯 Qué atacar"
VISTA_SEGUIMIENTO = "🔎 Seguimiento de un caso"
VISTA_ESTRUCTURA = "🏢 Estructura"


def named_tabs(names: list[str]) -> dict:
    """`st.tabs(names)` + acceso por nombre. Devuelve `{nombre: tab}` en
    vez de la lista posicional que da Streamlit."""
    tabs = st.tabs(names)
    return {name: tabs[i] for i, name in enumerate(names)}


def ir_a(vista: str) -> None:
    """Pide abrir una vista en la próxima ejecución (para botones del tipo
    «Ver qué atacar →» dentro de otra vista). Úsese en un `on_click`."""
    st.session_state[_CLAVE] = vista


def vista_activa() -> str | None:
    return st.session_state.get(_CLAVE)


def barra_de_vistas(principales: list[Vista], secundarias: list[Vista] | None = None) -> None:
    """Dibuja la barra y la vista activa (solo esa).

    `principales` van siempre a la vista; `secundarias`, dentro de «➕ Más».
    Si la vista guardada ya no existe (se cambió de modo o de hoja), se abre
    la primera principal.

    Cada vista es un botón, y la activa es un botón primario: la píldora roja
    de siempre. Se hizo así y no con `st.segmented_control` porque la marca de
    "seleccionado" de ese control cambia entre versiones de Streamlit, y en la
    versión de Streamlit Cloud la pestaña activa quedaba sin indicador; el
    botón primario se ve igual en todas.
    """
    secundarias = [v for v in (secundarias or []) if v[0] not in {p[0] for p in principales}]
    if not principales:
        return
    etiquetas_p = [v[0] for v in principales]
    todas = dict(principales + secundarias)

    activa = st.session_state.get(_CLAVE)
    if activa not in todas:
        activa = etiquetas_p[0]
        st.session_state[_CLAVE] = activa

    def _elegir(etiqueta: str):
        st.session_state[_CLAVE] = etiqueta

    with st.container(key="nav_barra", horizontal=True, gap="small", vertical_alignment="center"):
        for i, etiqueta in enumerate(etiquetas_p):
            st.button(etiqueta, key=f"nav_btn_{i}", type="primary" if etiqueta == activa else "secondary",
                      on_click=_elegir, args=(etiqueta,))
        if secundarias:
            activa_mas = activa if activa not in etiquetas_p else None
            with st.popover(f"➕ {activa_mas}" if activa_mas else "➕ Más"):
                for etiqueta, _ in secundarias:
                    st.button(etiqueta, key=f"nav_mas_{etiqueta}", use_container_width=True,
                              type="primary" if etiqueta == activa else "secondary",
                              on_click=_elegir, args=(etiqueta,))

    todas[activa]()
