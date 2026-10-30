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
# Pantallas que reutilizan los estilos de otra (el resumen usa las tarjetas
# y el recuadro oscuro del parte del día).
_CSS_EXTRA = {"resumen": ["parte"], "atacar": ["parte"], "cuadro": ["parte"], "canales": ["parte"], "proyeccion": ["parte"], "caso": ["parte"], "calidad": ["parte"], "anomalias": ["parte"], "finanzas": ["parte"], "duelo": ["parte"], "analitica": ["parte"]}

NO_DISPONIBLE = object()
_MARCA = {"portada", "modos", "acceso"}


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
            css="\n".join(_leer(f"{n}.css") for n in ["comun", *_CSS_EXTRA.get(nombre, []), nombre]),
            js=_leer("comun.js") + "\n" + _leer(f"{nombre}.js"),
        )
    return _registradas[nombre]


def botones_ocultos(botones: dict[str, str], al_pulsar: dict | None = None) -> str | None:
    """Botones normales de Streamlit, invisibles, uno por acción
    ({acción: clave del botón}). Devuelve la acción cuyo botón se pulsó.
    `al_pulsar` = {acción: (función, args)} corre como `on_click`, antes del
    rerun (lo que necesita `ir_a` para cambiar de vista).

    Son el camino principal del clic: el JavaScript de la pantalla busca el
    botón por su clave (`.st-key-<clave> button`) y lo pulsa. Es el mismo
    mecanismo de cualquier botón de la app, así que funciona igual en todas
    las versiones y despliegues; el aviso por `setTriggerValue` queda solo
    de respaldo. En Streamlit Cloud la portada se quedaba «pegada» en
    «Comenzar» aunque en local avanzaba."""
    css = ",".join(f".st-key-{clave}" for clave in botones.values())
    st.markdown(f"<style>{css}{{position:fixed!important;left:-10000px!important;top:0!important;"
                "width:1px!important;height:1px!important;overflow:hidden!important;opacity:0!important}</style>",
                unsafe_allow_html=True)
    elegida = None
    for accion, clave in botones.items():
        fn, args = (al_pulsar or {}).get(accion, (None, ()))
        if st.button(accion, key=clave, on_click=fn, args=args):
            elegida = accion
    return elegida


def cabecera(titulo: str, subtitulo: str = "", ceja: str = "", icono: str = "📊",
             cifras: list | None = None, clave: str = "cabecera_js", respaldo_html: str | None = None) -> None:
    """Cabecera animada de una vista (ui/web/cabecera.*): recuadro oscuro con la
    red de datos, ícono, título, subtítulo y hasta cuatro cifras que cuentan
    (`cifras` = [(valor, etiqueta)]). Sin JavaScript se dibuja `respaldo_html`
    (la cabecera de siempre de esa vista) o, si no lo hay, un título simple."""
    datos = {"titulo": str(titulo), "subtitulo": str(subtitulo or ""), "ceja": str(ceja or ""), "icono": str(icono or ""),
             "cifras": [{"v": str(v), "l": str(l)} for v, l in (cifras or [])[:4]]}
    if escena("cabecera", datos, clave=clave) is NO_DISPONIBLE:
        if respaldo_html is None:
            import html as _html
            respaldo_html = (f'<div class="section-intro"><div><span class="eyebrow">{_html.escape(ceja or "")}</span>'
                             f'<h2>{_html.escape(str(titulo))}</h2><p>{_html.escape(str(subtitulo or ""))}</p></div></div>')
        st.markdown(respaldo_html, unsafe_allow_html=True)


def escena(nombre: str, datos: dict, clave: str):
    """Monta la pantalla `ui/web/<nombre>.*` con `datos`.

    Devuelve la acción que eligió el usuario en este rerun (texto), None si
    no eligió nada, o `NO_DISPONIBLE` si hay que usar la versión clásica."""
    if not disponible():
        return NO_DISPONIBLE
    # El color de la sección abierta (ui/components/colores.py); la portada,
    # los modos y el acceso llevan el de la marca.
    if nombre not in _MARCA and isinstance(datos, dict) and "acento" not in datos:
        from ui.components.colores import color_activo
        datos = {**datos, "acento": color_activo()}
    try:
        resultado = _componente(nombre)(data=datos, key=clave, on_accion_change=lambda: None)
    except Exception:
        return NO_DISPONIBLE
    return getattr(resultado, "accion", None)
