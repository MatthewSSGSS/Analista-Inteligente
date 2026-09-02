"""Navegación por pestañas con acceso por nombre, y agrupación de vistas en
secciones lógicas.

`named_tabs()` reemplaza el patrón `tabs = st.tabs(names); tab_map = {name:
tabs[i] for i, name in enumerate(names)}` que estaba repetido tal cual tres
veces en app.py.

`grouped_nav()` es la navegación de nivel superior de la app: recibe las
vistas ya organizadas en grupos lógicos ("General", "Análisis", "Personas")
solo para que quien llama pueda seguir pensando en esos términos, pero las
aplana en una sola fila de pestañas (Inicio, Resumen ejecutivo/Descripción,
Comparar personas, Georeferenciación, Asistente IA, Datos, Calidad,
Analítica, Finanzas, Trabajo, Anomalías, Exportar, Comparativa, Análisis
Seguimiento — según el modo). Un grupo sin ninguna vista disponible no
aporta nada a esa fila (p. ej. "Personas" cuando el Excel no tiene
identidad ni seguimiento cargado) — ninguna vista deja de estar accesible,
solo cambia si hay que desplazarse horizontalmente para llegar a ella.
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
    """Navegación de nivel superior. `groups` es una lista de
    `(etiqueta_de_grupo, vistas)`, donde `vistas` es una lista de
    `(etiqueta_de_vista, función_sin_argumentos)` que renderiza esa vista
    al llamarla. Los grupos sin ninguna vista disponible se omiten
    automáticamente (p. ej. "Personas" cuando el Excel no tiene identidad
    ni seguimiento cargado) — no se muestra un grupo vacío.

    Todas las vistas de todos los grupos se muestran en UNA sola fila de
    pestañas (antes había una fila por "grupo" — 📋 General/📊 Análisis/👥
    Personas — y, al entrar a una, una SEGUNDA fila con sus vistas; dos
    filas de pestañas apiladas, con el mismo estilo visual, hacían difícil
    saber en qué nivel se estaba). El nombre del grupo ya no se usa como
    pestaña propia — solo ayuda a mantener juntas, en el orden de la lista,
    las vistas que pertenecen al mismo grupo. Si la fila crece mucho (modo
    Analista con muchas herramientas), se desplaza horizontalmente
    (`.stTabs [data-baseweb="tab-list"]{overflow-x:auto}`, ya existente)
    en vez de partirse en niveles.
    """
    groups = [(label, views) for label, views in groups if views]
    if not groups:
        return
    all_views = [v for _, views in groups for v in views]
    _render_views(all_views)


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
