"""Navegación por pestañas con acceso por nombre, y agrupación de vistas en
secciones lógicas.

`named_tabs()` reemplaza el patrón `tabs = st.tabs(names); tab_map = {name:
tabs[i] for i, name in enumerate(names)}` que estaba repetido tal cual tres
veces en app.py.

`grouped_nav()` es la navegación de nivel superior de la app (tarea 07):
en vez de una sola barra de pestañas plana con hasta 14 elementos (Inicio,
Resumen ejecutivo/Descripción, Comparar personas, Georeferenciación,
Asistente IA, Datos, Calidad, Analítica, Finanzas, Trabajo, Anomalías,
Exportar, Comparativa, Análisis Seguimiento — según el modo), agrupa las
vistas en "General", "Análisis" y "Personas". Ningún grupo aparece si no
tiene ninguna vista disponible, y ninguna vista deja de estar accesible:
solo cambia cuántos clics/qué ruta hace falta para llegar a ella.
"""
from __future__ import annotations

from typing import Callable

import streamlit as st


def named_tabs(names: list[str]) -> dict:
    """`st.tabs(names)` + acceso por nombre. Devuelve `{nombre: tab}` en
    vez de la lista posicional que da Streamlit."""
    tabs = st.tabs(names)
    return {name: tabs[i] for i, name in enumerate(names)}


def grouped_nav(groups: list[tuple[str, list[tuple[str, Callable[[], None]]]]]) -> None:
    """Navegación por grupos lógicos. `groups` es una lista de
    `(etiqueta_de_grupo, vistas)`, donde `vistas` es una lista de
    `(etiqueta_de_vista, función_sin_argumentos)` que renderiza esa vista
    al llamarla. Los grupos sin ninguna vista disponible se omiten
    automáticamente (p. ej. "Personas" cuando el Excel no tiene identidad
    ni seguimiento cargado) — no se muestra un grupo vacío.

    Dentro de cada grupo:
    - 1 sola vista: se renderiza directo, sin barra de navegación propia
      (una pestaña de un solo elemento no aporta nada).
    - 2 vistas: un selector de dos opciones (`st.radio` horizontal) en vez
      de una barra de pestañas completa — reduce la dependencia de
      `st.tabs()` donde una elección binaria no la necesita.
    - 3 o más vistas: pestañas anidadas (`named_tabs`), apropiadas para un
      grupo con varias vistas relacionadas entre sí.
    """
    groups = [(label, views) for label, views in groups if views]
    if not groups:
        return
    if len(groups) == 1:
        _render_views(groups[0][1])
        return
    group_map = named_tabs([label for label, _ in groups])
    for label, views in groups:
        with group_map[label]:
            _render_views(views)


def _render_views(views: list[tuple[str, Callable[[], None]]]) -> None:
    if len(views) == 1:
        views[0][1]()
        return
    if len(views) == 2:
        labels = [v[0] for v in views]
        choice = st.radio(
            "Vista", labels, horizontal=True, label_visibility="collapsed",
            key="nav_pair_" + "_".join(labels),
        )
        dict(views)[choice]()
        return
    view_map = named_tabs([v[0] for v in views])
    for label, render in views:
        with view_map[label]:
            render()
