"""Tarjeta de gráfico (`.chart-card.pbi-visual`): encabezado + `st.plotly_chart`
+ lectura/explicación opcionales + estado vacío.

Antes existían tres copias casi idénticas de esto: `ui/dashboard.py::_chart_card`
(con lectura y botón "Explicar gráfico"), `ui/georeferencing.py::_geo_card` y
`ui/person_profile.py::_chart` (ambas más simples, sin esos dos extras).
`chart_card()` cubre los tres casos con los mismos parámetros por defecto que
ya tenía `_chart_card`, así que las vistas más simples solo necesitan pasar
`visual_type`/`badge_text` para reproducir su texto exacto.

A diferencia de las tarjetas en `cards.py`, esta función renderiza
directamente (no devuelve HTML): intercala `st.plotly_chart` entre el
encabezado y el cierre del `<div>`, igual que hacían las tres funciones que
reemplaza.
"""
from __future__ import annotations

import re
import streamlit as st
from visualization.charts import en_espanol


def _puntos_seleccionados(evento):
    """Los `customdata` de las barras en las que se hizo clic.

    Streamlit devuelve la selección a veces como objeto y a veces como
    diccionario según la versión, así que se prueban las dos formas — es el
    mismo cuidado que ya tenía `ui/georeferencing._selection_label`, que es
    donde este patrón se usó por primera vez.
    """
    try:
        seleccion = evento.selection
    except AttributeError:
        try:
            seleccion = evento.get("selection", {})
        except AttributeError:
            return []
    try:
        puntos = seleccion.points
    except AttributeError:
        puntos = seleccion.get("points", []) if hasattr(seleccion, "get") else []
    datos = []
    for punto in puntos or []:
        try:
            custom = punto.customdata
        except AttributeError:
            custom = punto.get("customdata") if hasattr(punto, "get") else None
        if custom is not None:
            datos.append(custom)
    return datos


def _tabla_detalle(titulo, tabla, key):
    """El bloque que se abre bajo el gráfico: qué se seleccionó, sus
    registros y la opción de llevárselos."""
    import pandas as pd  # local: este módulo no lo necesita para nada más

    if tabla is None or (hasattr(tabla, "empty") and tabla.empty):
        st.caption("No hay registros que mostrar para esa selección.")
        return
    st.markdown(
        f'<div class="chart-reading"><b>🔎 {titulo}</b> · {len(tabla):,} registro(s). '
        'Vuelve a hacer clic en la barra para cerrar.</div>',
        unsafe_allow_html=True,
    )
    st.dataframe(tabla.head(500), use_container_width=True, hide_index=True)
    if len(tabla) > 500:
        st.caption(f"Se muestran los primeros 500 de {len(tabla):,}. La descarga los trae todos.")
    st.download_button(
        "⬇️ Descargar estos registros (CSV)",
        tabla.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{re.sub(r'[^a-zA-Z0-9]+', '_', titulo)[:60]}.csv",
        mime="text/csv",
        key=f"{key}__descarga",
        use_container_width=False,
    )


def chart_card(
    title,
    subtitle,
    fig,
    empty: str = "No hay datos suficientes para este análisis.",
    insight=None,
    explain=None,
    key: str | None = None,
    visual_type: str = "VISUAL",
    badge_text: str = "Datos actuales",
    detalle=None,
) -> None:
    """Tarjeta de gráfico. Con `detalle`, además, el gráfico se vuelve
    clicable: al pinchar una barra se abre debajo la lista de registros que
    hay detrás de esa cifra.

    `detalle` es una función que recibe los `customdata` del punto pinchado
    y devuelve `(título, DataFrame)`, o None si esa barra no tiene detalle
    que mostrar. La función la pone cada vista, porque solo ella sabe qué
    significan los datos de su gráfico; aquí solo se dibuja el resultado.

    Por qué así y no con un botón aparte: el gráfico ya dice CUÁNTOS hay en
    cada grupo, y la pregunta que sigue siempre es QUIÉNES son. Tenerlo a un
    clic evita ir a otra pestaña a reconstruir a mano el mismo corte, que es
    donde se perdía el hilo entre ver el problema y actuar sobre él.
    """
    st.markdown(
        f'<div class="chart-card pbi-visual"><div class="chart-head"><div class="chart-head-main">'
        f'<span class="visual-type">{visual_type}</span>'
        f'<div class="chart-title">{title}</div><div class="chart-subtitle">{subtitle}</div></div>'
        f'<span class="data-badge visual-badge">{badge_text}</span></div>',
        unsafe_allow_html=True,
    )
    if fig is not None:
        # Cifras y meses de los ejes en español («1 mil M», «ene 2025») y no
        # como los escribe plotly («1G», «Jan 2025»). Ver visualization/charts.en_espanol.
        en_espanol(fig)
        # Streamlit exige claves únicas por elemento; el gráfico y su botón
        # de explicación son dos elementos distintos y nunca deben compartir
        # clave.
        safe_key = key or "chart_" + re.sub(r"[^a-zA-Z0-9_]+", "_", f"{title}_{subtitle}")[:80]
        chart_key = f"{safe_key}__chart"
        if detalle is None:
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "responsive": True}, key=chart_key)
        else:
            evento = st.plotly_chart(
                fig, use_container_width=True,
                config={"displayModeBar": False, "responsive": True},
                key=chart_key, on_select="rerun", selection_mode=["points"],
            )
            for custom in _puntos_seleccionados(evento):
                try:
                    resultado = detalle(custom)
                except Exception:
                    # Un detalle que falle no puede tumbar el gráfico: lo
                    # importante sigue siendo la cifra que ya se ve.
                    resultado = None
                if resultado:
                    _tabla_detalle(resultado[0], resultado[1], chart_key)
                break  # un clic, un detalle: dos tablas a la vez no se leen
        if insight:
            st.markdown(f'<div class="chart-reading"><b>Lectura:</b> {insight}</div>', unsafe_allow_html=True)
        if explain:
            button_key = f"{safe_key}__explain"
            if st.button("💡 Explicar gráfico", key=button_key, use_container_width=False):
                st.markdown(f'<div class="chart-reading"><b>Interpretación:</b> {explain}</div>', unsafe_allow_html=True)
    else:
        empty_state(empty)
    st.markdown('</div>', unsafe_allow_html=True)


def empty_state(message: str = "No hay datos suficientes para este análisis.", icon: str = "📭") -> None:
    """Estado vacío (`.empty-state`) — antes un `st.info()` genérico, la
    misma caja para cualquier mensaje informativo. Con borde punteado e
    ícono apagado se distingue de un aviso real: esto no es algo que
    pasó, es que sencillamente no hay nada que mostrar todavía.
    `chart_card()` ya lo usa cuando `fig` es None; también sirve suelto
    fuera de una tarjeta de gráfico."""
    st.markdown(f'<div class="empty-state"><span class="empty-icon">{icon}</span><span>{message}</span></div>', unsafe_allow_html=True)
