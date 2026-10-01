"""Seguimiento de Logística: tercera ruta de la app.

Al mismo nivel que Análisis Completo y Análisis Territorial, y construida con
el mismo patrón que Territorial: una función `render_logistica_page()` que se
llama desde `app.py` y dibuja la pantalla completa, con su propio CSS, su
propio cargador y sus propias claves de sesión (`logistica_*`), para que
cargar un archivo aquí no pise el del panel completo ni el del territorial.

Esta primera versión deja montada la sección —tarjeta en la pantalla de
inicio, ruta, navegación, carga del archivo y vista previa de los datos—; el
análisis propio de logística se irá definiendo y agregando aquí.

Acento: ámbar (`--amber`), distinto del rojo de Completo y del turquesa de
Territorial, con las mismas variables de tema que el resto de la app.
"""
from __future__ import annotations

import html

import streamlit as st

from core.loader import load_workbook
from ui.assets import image_data_uri

# Claves de sesión propias: el archivo de logística no tiene por qué ser el
# mismo del panel completo, y compartir la clave haría que uno pisara al otro.
_CLAVE_LIBRO = "logistica_workbook"
_CLAVE_HOJA = "logistica_sheet"


def _inject_css():
    portada = image_data_uri("datos1.jpg")
    st.markdown(
        f"""
        <style>
        @keyframes fadeUp{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:translateY(0)}}}}
        .logistica-hero{{position:relative;overflow:hidden;border-radius:var(--radius-lg);
          border:1px solid var(--line);box-shadow:var(--shadow-md);padding:22px 26px;
          background-image:linear-gradient(100deg,var(--panel) 40%,rgba(200,121,10,.12) 100%),
            url({portada});background-size:cover;background-position:center;animation:fadeUp .4s ease both}}
        .logistica-hero .eyebrow{{font-size:11px;font-weight:800;letter-spacing:.11em;
          color:var(--amber-strong);text-transform:uppercase;display:inline-flex;align-items:center;gap:6px}}
        .logistica-hero h1{{margin:6px 0 4px;font-size:25px;font-family:'Sora','Inter',sans-serif;
          letter-spacing:-.02em;color:var(--text)}}
        .logistica-hero p{{color:var(--muted);font-size:13px;margin:0;max-width:640px}}
        .logistica-label{{font-size:10.5px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;
          color:var(--muted);margin:16px 0 8px}}
        .logistica-resumen{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;
          margin:4px 0 14px;animation:fadeUp .45s ease both}}
        .logistica-dato{{background:var(--panel);border:1px solid var(--line);border-top:3px solid var(--amber);
          border-radius:var(--radius-md);padding:12px 14px;box-shadow:var(--shadow-sm)}}
        .logistica-dato span{{display:block;font-size:10.5px;font-weight:800;letter-spacing:.07em;
          text-transform:uppercase;color:var(--muted)}}
        .logistica-dato b{{display:block;font-size:20px;font-family:'Sora','Inter',sans-serif;color:var(--text);
          margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
        .logistica-pronto{{background:var(--panel);border:1px dashed var(--line);border-radius:var(--radius-lg);
          padding:28px 24px;text-align:center;animation:fadeUp .5s ease both;
          background-image:repeating-linear-gradient(45deg,var(--panel-2),var(--panel-2) 14px,transparent 14px,transparent 28px)}}
        .logistica-pronto .icono{{font-size:38px;line-height:1;opacity:.7}}
        .logistica-pronto b{{display:block;font-size:17px;font-family:'Sora','Inter',sans-serif;color:var(--text);margin:8px 0 4px}}
        .logistica-pronto p{{font-size:12.5px;color:var(--muted);margin:0 auto;max-width:520px;line-height:1.5}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _cabecera():
    izq, der = st.columns([5, 1.6])
    with izq:
        st.markdown(
            '<div class="logistica-hero"><span class="eyebrow">🚚 SEGUIMIENTO DE LOGÍSTICA</span>'
            '<h1>Seguimiento de logística</h1>'
            '<p>Tu operación logística en un solo lugar: carga el archivo de seguimiento y revisa cómo va.</p></div>',
            unsafe_allow_html=True,
        )
    with der:
        st.write("")
        if st.button("🧭 Ir a Análisis Completo", use_container_width=True, key="logistica_a_completo"):
            st.session_state.analysis_mode = "completo"
            st.rerun()
        if st.button("🗺️ Ir a Análisis Territorial", use_container_width=True, key="logistica_a_territorial"):
            st.session_state.analysis_mode = "territorial"
            st.rerun()


def _cargador():
    """Cargar el archivo, o reutilizar el que ya esté abierto en el panel."""
    subida = st.file_uploader(
        "Cargar Excel / CSV", type=["xlsx", "xls", "xlsb", "xlsm", "csv"],
        key="logistica_upload", label_visibility="collapsed",
    )
    columnas = st.columns([1, 1])
    with columnas[0]:
        if subida and st.button("Analizar archivo", type="primary", use_container_width=True,
                                key="logistica_analizar"):
            with st.spinner("Leyendo el archivo..."):
                try:
                    st.session_state[_CLAVE_LIBRO] = load_workbook(subida)
                    st.session_state[_CLAVE_HOJA] = list(st.session_state[_CLAVE_LIBRO]["sheets"].keys())[0]
                except Exception as exc:
                    st.error(f"No pudimos procesar este archivo: {exc}")
    with columnas[1]:
        # Si ya hay un archivo abierto en el panel completo, no tiene sentido
        # obligar a subirlo otra vez.
        otro = st.session_state.get("workbook")
        if otro and not st.session_state.get(_CLAVE_LIBRO):
            if st.button(f'📄 Usar el archivo abierto ({otro["filename"]})',
                         use_container_width=True, key="logistica_reusar"):
                st.session_state[_CLAVE_LIBRO] = otro
                st.session_state[_CLAVE_HOJA] = list(otro["sheets"].keys())[0]
                st.rerun()


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


def render_logistica_page():
    """Pantalla completa de Seguimiento de Logística."""
    _inject_css()
    _cabecera()

    st.markdown('<div class="logistica-label">Archivo</div>', unsafe_allow_html=True)
    _cargador()

    libro, hoja = _hoja_activa()
    if not libro:
        st.info("Sube el Excel o CSV de seguimiento logístico, o usa el archivo que ya tengas abierto en el panel.")
        return

    hojas = list(libro["sheets"].keys())
    if len(hojas) > 1:
        hoja = st.selectbox("Hoja", hojas, index=hojas.index(hoja), key="logistica_selector_hoja")
        st.session_state[_CLAVE_HOJA] = hoja

    item = libro["sheets"][hoja]
    df = item["processed"]
    schema = item["profile"]["schema"]
    fechas = [c for c in schema.get("dates", []) if c in df.columns]
    datos = [("Registros", f"{len(df):,}"), ("Columnas", f"{len(df.columns)}"),
             ("Fecha detectada", str(fechas[0]) if fechas else "—"), ("Hoja", str(hoja))]
    st.markdown('<div class="logistica-resumen">' + "".join(
        f'<div class="logistica-dato"><span>{etiqueta}</span><b title="{html.escape(valor)}">{html.escape(valor)}</b></div>'
        for etiqueta, valor in datos) + "</div>", unsafe_allow_html=True)

    # Aquí irá el análisis de logística, a medida que se defina.
    st.markdown(
        '<div class="logistica-pronto"><div class="icono">🚚</div><b>El análisis de logística está en construcción</b>'
        '<p>El archivo ya quedó cargado y listo. Las vistas de seguimiento se irán agregando en esta sección.</p></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="logistica-label">Vista previa de los datos</div>', unsafe_allow_html=True)
    st.dataframe(df.head(200), use_container_width=True, hide_index=True)
    st.caption(f"{libro['filename']} · hoja {hoja} · {len(df):,} registros · {len(df.columns)} columnas"
               + (" · se muestran los primeros 200" if len(df) > 200 else ""))
