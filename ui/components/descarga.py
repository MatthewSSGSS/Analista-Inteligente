"""Descarga en dos pasos: «Preparar» arma el archivo a la vista y luego
«Descargar» entrega lo que ya está listo.

La usan Exportar (`ui/exports.py`) y Análisis Territorial
(`ui/territorial.py`). Sin lógica de negocio: recibe una función que arma
los bytes y una `firma` de los datos con que se armó.
"""
from __future__ import annotations

import traceback

import streamlit as st


def preparar_y_descargar(clave: str, firma: tuple, construir, nombre: str, mime: str, *,
                          preparar: str, descargar: str, ayuda: str, primario: bool = False, nota: str = "") -> None:
    """Un archivo pesado en dos pasos: «Preparar» lo arma aquí, a la vista, y
    después «Descargar» entrega lo que ya está listo.

    Antes se le pasaba a `st.download_button` una función que Streamlit
    ejecutaba en segundo plano al hacer clic. Si fallaba, Streamlit se tragaba
    el error (solo queda en el registro del servidor) y el navegador mostraba
    un genérico «Failed to generate file» o nada; además, el navegador deja de
    esperar a los 3 minutos. Con un Excel grande no había forma de saber por
    qué «no dejaba». Así se ve el progreso, el error real con su detalle, y no
    hay límite de espera.

    `firma` dice con qué datos se armó (archivo, hoja, filtros…): si cambia, lo
    preparado deja de servir y se vuelve a pedir «Preparar»."""
    # Lo preparado se guarda con otro nombre que el botón: Streamlit no deja
    # escribir en session_state la clave de un widget.
    almacen = f"_preparado__{clave}"
    guardado = st.session_state.get(almacen)
    if guardado and guardado.get("firma") == firma:
        st.download_button(descargar, guardado["datos"], nombre, mime, use_container_width=True,
                           type="primary" if primario else "secondary", key=clave, help=ayuda)
        st.markdown(f'<div class="exp-size" style="font-size:11.5px;opacity:.75;text-align:center">{nota}{" · " if nota else ""}{tamano_mb(guardado["datos"])} · listo</div>',
                    unsafe_allow_html=True)
        return
    if not st.button(preparar, use_container_width=True, type="primary" if primario else "secondary",
                     key=f"{clave}__preparar", help=ayuda):
        if nota:
            st.markdown(f'<div class="exp-size" style="font-size:11.5px;opacity:.75;text-align:center">{nota}</div>', unsafe_allow_html=True)
        return
    datos, error = None, None
    with st.spinner("Preparando el archivo… con archivos grandes puede tardar un minuto."):
        try:
            datos = construir()
        except Exception as exc:
            error = (exc, traceback.format_exc())
    if error is not None:
        st.error(f"No se pudo preparar: {error[0]}")
        with st.expander("Detalle técnico (cópialo si necesitas ayuda)"):
            st.code(error[1], language=None)
        return
    st.session_state[almacen] = {"firma": firma, "datos": datos}
    st.rerun()


def tamano_mb(contenido: bytes) -> str:
    return f"{len(contenido) / 1_000_000:.1f} MB"
