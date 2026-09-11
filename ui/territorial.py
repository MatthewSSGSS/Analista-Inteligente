"""Análisis Territorial: la red sobre el mapa.

Tercera ruta de la app, al mismo nivel que Análisis Práctico y Análisis
Avanzado, y construida con el mismo patrón que ellas: una función
`render_*_page()` que se llama desde `app.py` y dibuja la pantalla completa,
con su propio CSS, su propio cargador y sus propias claves de sesión.

Sigue el lenguaje visual de la tarjeta que lleva aquí (`ui/mode_choice.py`):
acento turquesa (`--teal`), tipografía Sora en los títulos y las mismas
variables de tema que el resto de la app, para que cambiar de modo no se
sienta como cambiar de producto.

El layout es el que pidió esta pantalla: panel de filtros fijo a 280px a la
izquierda y el mapa ocupando todo lo demás a la derecha. Los 280px son
literales, no una proporción: `st.columns` solo reparte porcentajes, así que
el ancho se fija por CSS sobre la clase `st-key-*` que Streamlit le pone al
contenedor con `key`.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.geo_engine import supports_georeferencing
from core.loader import load_workbook
from ui.assets import image_data_uri

# Claves de sesión propias, igual que `practico_*` en ui/practical.py: el
# archivo que se analiza aquí no tiene por qué ser el mismo que el del panel
# avanzado, y compartir la clave haría que cargar uno pisara al otro.
_CLAVE_LIBRO = "territorial_workbook"
_CLAVE_HOJA = "territorial_sheet"


def _inject_css():
    portada = image_data_uri("ciudad_red.jpg")
    st.markdown(
        f"""
        <style>
        @keyframes fadeUp{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:translateY(0)}}}}

        /* Hero: misma estructura que .practico-hero, con el acento turquesa
           de la tarjeta de Territorial en vez del rojo de Práctico. */
        .territorial-hero{{position:relative;overflow:hidden;border-radius:var(--radius-lg);
          border:1px solid var(--line);box-shadow:var(--shadow-md);padding:22px 26px;
          background-image:linear-gradient(100deg,var(--panel) 38%,rgba(15,168,160,.10) 100%),
            url({portada});background-size:cover;background-position:center;animation:fadeUp .4s ease both}}
        .territorial-hero .eyebrow{{font-size:11px;font-weight:800;letter-spacing:.11em;
          color:var(--teal);text-transform:uppercase;display:inline-flex;align-items:center;gap:6px}}
        .territorial-hero h1{{margin:6px 0 4px;font-size:25px;font-family:'Sora','Inter',sans-serif;
          letter-spacing:-.02em;color:var(--text)}}
        .territorial-hero p{{color:var(--muted);font-size:13px;margin:0;max-width:640px}}

        .territorial-label{{font-size:10.5px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;
          color:var(--muted);margin:16px 0 8px}}

        /* Panel de filtros: 280px exactos. st.columns solo reparte
           proporciones, así que el ancho real se fija aquí, sobre la clase
           que Streamlit genera a partir de key="territorial_layout". */
        .st-key-territorial_layout div[data-testid="stHorizontalBlock"]{{align-items:flex-start}}
        .st-key-territorial_layout div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]:first-child{{
          flex:0 0 280px;min-width:280px;max-width:280px;width:280px}}
        .st-key-territorial_layout div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]:last-child{{
          flex:1 1 auto;min-width:0}}
        @media(max-width:900px){{
          .st-key-territorial_layout div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]:first-child{{
            flex:1 1 100%;min-width:0;max-width:none;width:auto}}}}

        .territorial-panel{{background:var(--panel);border:1px solid var(--line);
          border-radius:var(--radius-lg);padding:16px 16px 6px;box-shadow:var(--shadow-sm);
          animation:fadeUp .45s ease both}}
        .territorial-panel-title{{font-size:13px;font-weight:800;font-family:'Sora','Inter',sans-serif;
          color:var(--text);display:flex;align-items:center;gap:7px;margin-bottom:2px}}
        .territorial-panel-sub{{font-size:11.5px;color:var(--muted);line-height:1.45;margin-bottom:12px}}

        /* Marco del mapa. El placeholder ocupa exactamente el sitio que va a
           ocupar el mapa, para que al reemplazarlo no se mueva nada de la
           pantalla. */
        .territorial-mapa{{background:var(--panel);border:1px solid var(--line);
          border-radius:var(--radius-lg);box-shadow:var(--shadow-sm);overflow:hidden;
          animation:fadeUp .5s ease both}}
        .territorial-mapa-head{{padding:14px 18px;border-bottom:1px solid var(--line);
          display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}}
        .territorial-mapa-head b{{font-size:14px;font-family:'Sora','Inter',sans-serif;color:var(--text)}}
        .territorial-mapa-head span{{font-size:11.5px;color:var(--muted)}}
        .territorial-mapa-cuerpo{{height:520px;display:flex;flex-direction:column;align-items:center;
          justify-content:center;gap:10px;text-align:center;padding:24px;
          background:repeating-linear-gradient(45deg,var(--panel-2),var(--panel-2) 14px,transparent 14px,transparent 28px)}}
        .territorial-mapa-cuerpo .icono{{font-size:40px;opacity:.55;line-height:1}}
        .territorial-mapa-cuerpo b{{font-size:17px;font-family:'Sora','Inter',sans-serif;color:var(--text)}}
        .territorial-mapa-cuerpo p{{font-size:12.5px;color:var(--muted);margin:0;max-width:420px;line-height:1.5}}
        @media(max-width:900px){{.territorial-mapa-cuerpo{{height:360px}}}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _hoja_activa():
    """El libro y la hoja con la que se está trabajando, o (None, None)."""
    libro = st.session_state.get(_CLAVE_LIBRO)
    if not libro:
        return None, None
    hojas = list(libro["sheets"].keys())
    hoja = st.session_state.get(_CLAVE_HOJA)
    if hoja not in hojas:
        hoja = hojas[0]
        st.session_state[_CLAVE_HOJA] = hoja
    return libro, hoja


def _cabecera():
    izq, der = st.columns([5, 1.6])
    with izq:
        st.markdown(
            '<div class="territorial-hero"><span class="eyebrow">🗺️ ANÁLISIS TERRITORIAL</span>'
            '<h1>Mapea tu red y encuentra dónde expandir</h1>'
            '<p>Tu operación sobre el mapa: dónde está, dónde se concentra y dónde queda territorio '
            'sin cubrir.</p></div>',
            unsafe_allow_html=True,
        )
    with der:
        st.write("")
        if st.button("⚡ Ir a Práctico", use_container_width=True, key="territorial_a_practico"):
            st.session_state.analysis_mode = "practico"
            st.rerun()
        if st.button("🧭 Ir a Avanzado", use_container_width=True, key="territorial_a_avanzado"):
            st.session_state.analysis_mode = "avanzado"
            st.rerun()


def _cargador():
    """Cargar el archivo, o reutilizar el que ya esté abierto en el panel."""
    subida = st.file_uploader(
        "Cargar Excel / CSV", type=["xlsx", "xls", "xlsb", "xlsm", "csv"],
        key="territorial_upload", label_visibility="collapsed",
    )
    columnas = st.columns([1, 1])
    with columnas[0]:
        if subida and st.button("Analizar archivo", type="primary", use_container_width=True,
                                key="territorial_analizar"):
            with st.spinner("Leyendo el archivo y detectando ubicaciones..."):
                try:
                    st.session_state[_CLAVE_LIBRO] = load_workbook(subida)
                    st.session_state[_CLAVE_HOJA] = list(st.session_state[_CLAVE_LIBRO]["sheets"].keys())[0]
                except Exception as exc:
                    st.error(f"No pudimos procesar este archivo: {exc}")
    with columnas[1]:
        # Si ya hay un archivo abierto en el panel avanzado, no tiene sentido
        # obligar a subirlo otra vez para verlo en el mapa.
        otro = st.session_state.get("workbook")
        if otro and not st.session_state.get(_CLAVE_LIBRO):
            if st.button(f'📄 Usar el archivo abierto ({otro["filename"]})',
                         use_container_width=True, key="territorial_reusar"):
                st.session_state[_CLAVE_LIBRO] = otro
                st.session_state[_CLAVE_HOJA] = list(otro["sheets"].keys())[0]
                st.rerun()


def _panel_filtros(df, schema, libro, hoja):
    """Panel izquierdo: de dónde salen los puntos y qué se muestra."""
    st.markdown('<div class="territorial-panel">', unsafe_allow_html=True)
    st.markdown(
        '<div class="territorial-panel-title">🧭 Filtros</div>'
        '<div class="territorial-panel-sub">Acotan qué parte de la red se dibuja en el mapa.</div>',
        unsafe_allow_html=True,
    )
    hojas = list(libro["sheets"].keys())
    if len(hojas) > 1:
        elegida = st.selectbox("Hoja", hojas, index=hojas.index(hoja), key="territorial_hoja_sel")
        if elegida != hoja:
            st.session_state[_CLAVE_HOJA] = elegida
            st.rerun()

    from visualization.charts import dimension_candidates, metric_candidates, _label

    metricas = [m for m in metric_candidates(df, schema) if m in df.columns]
    if metricas:
        st.selectbox("Métrica del mapa", metricas, key="territorial_metrica",
                     format_func=lambda c: _label(schema, c))
    dimensiones = [d for d in dimension_candidates(df, schema) if d in df.columns][:4]
    for dim in dimensiones:
        valores = sorted(df[dim].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique())
        if 1 < len(valores) <= 60:
            st.multiselect(_label(schema, dim), valores, key=f"territorial_filtro_{dim}",
                           placeholder="Todos")
    if not metricas and not dimensiones:
        st.caption("Este archivo no tiene columnas con las que filtrar el mapa.")
    st.markdown("</div>", unsafe_allow_html=True)


def _placeholder_mapa(df, schema):
    """Área principal: el sitio exacto que va a ocupar el mapa."""
    geo_ok, geo_meta = supports_georeferencing(df, schema)
    if geo_ok:
        modo = geo_meta.get("mode", "")
        origen = {
            "coordinates": "coordenadas en el archivo",
            "city": "una columna de ciudad",
            "region": "una columna de región",
            "country": "una columna de país",
            "embedded": "el lugar escrito dentro del texto",
        }.get(modo, "los datos del archivo")
        estado = f"Ubicaciones detectadas a partir de {origen}."
    else:
        estado = ("Este archivo todavía no tiene una ubicación que el motor pueda mapear: sirve una "
                  "columna de ciudad, región o país, coordenadas, o el lugar escrito dentro de otro texto.")

    st.markdown(
        f"""
        <div class="territorial-mapa">
          <div class="territorial-mapa-head">
            <b>Mapa de la red</b><span>{estado}</span>
          </div>
          <div class="territorial-mapa-cuerpo">
            <div class="icono">🗺️</div>
            <b>Mapa próximamente</b>
            <p>Aquí va a ir el mapa de la red con los filtros de la izquierda aplicados.
            El espacio está reservado para que al conectarlo no se mueva nada de esta pantalla.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_territorial_page():
    """Pantalla completa de Análisis Territorial."""
    _inject_css()
    _cabecera()

    st.markdown('<div class="territorial-label">Archivo</div>', unsafe_allow_html=True)
    _cargador()

    libro, hoja = _hoja_activa()
    if not libro:
        st.info("Sube un Excel o CSV para mapear tu red, o usa el archivo que ya tengas abierto en el panel.")
        return

    item = libro["sheets"][hoja]
    df = item["processed"]
    schema = item["profile"]["schema"]

    # El layout de dos columnas va dentro de un contenedor con `key` para
    # poder fijarle los 280px por CSS (ver _inject_css).
    with st.container(key="territorial_layout"):
        panel, mapa = st.columns([280, 720], gap="large")
        with panel:
            _panel_filtros(df, schema, libro, hoja)
        with mapa:
            _placeholder_mapa(df, schema)

    st.caption(f"{libro['filename']} · hoja {hoja} · {len(df):,} registros · {len(df.columns)} columnas")
