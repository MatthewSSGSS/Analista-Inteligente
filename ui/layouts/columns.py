"""Columnas de contenido principal y grillas de tarjetas.

`two_column()` es el patrón "contenido principal + panel lateral de
lectura" que ya usan Resumen ejecutivo, Georeferenciación y (con su propia
proporción) el detalle de desempeño del dashboard — antes cada vista
elegía sus propios números de `st.columns([...])` sin que quedara claro
que son la misma idea de layout.

`kpi_grid()` es la cuadrícula de tarjetas en filas de N columnas con
relleno de la fila incompleta (para que la última fila no se vea más
angosta que las demás), antes duplicada a mano en `ui/dashboard.py`.
"""
from __future__ import annotations

import streamlit as st


def two_column(main: float = 2.15, side: float = 1, gap: str = "small"):
    """Layout de dos columnas: contenido principal (ancho `main`) y panel
    lateral (ancho `side`). Devuelve `(col_principal, col_lateral)`, igual
    que `st.columns(...)` — se sigue usando con `with`."""
    return st.columns([main, side], gap=gap)


def kpi_grid(items: list, render, per_row: int = 4) -> None:
    """Cuadrícula de tarjetas: `per_row` columnas por fila, la fila final
    se rellena con columnas vacías para que no quede más angosta que el
    resto. `render(item)` debe devolver el HTML de una tarjeta (p. ej.
    `kpi_card(...)` de `ui.components.cards`); esta función solo decide la
    disposición, no el contenido de cada tarjeta."""
    for row_start in range(0, len(items), per_row):
        row = items[row_start:row_start + per_row]
        cols = st.columns(per_row)
        for i, item in enumerate(row):
            with cols[i]:
                st.markdown(render(item), unsafe_allow_html=True)
        for j in range(len(row), per_row):
            cols[j].empty()
