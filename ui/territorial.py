"""Análisis Territorial: una consola de mapas por capas, clara u oscura.

Una de las rutas de la app, al mismo nivel que Análisis Completo y
Seguimiento de Logística: `render_territorial_page()` dibuja la pantalla
completa, con su propio CSS, su propio cargador y sus propias claves de
sesión (`territorial_*`). El cálculo vive en `core/territorio.py`; aquí solo
se dibuja.

La pantalla es una consola tipo SIG:

- **Panel de capas** a la izquierda: cada capa se prende o se apaga, lleva
  la etiqueta de su fuente (tu archivo, DANE, oportunidad) y su leyenda por
  rangos cuando está activa. Se pueden combinar.
- **Capas**: municipios coloreados (con opción de levantarlos en 3D),
  columnas 3D, departamentos 3D, hexágonos 3D (con coordenadas), mapa de
  calor, puntos, población DANE 2026 como contexto, blancos de expansión
  resaltados y nombres de las zonas principales.
- **Color con sentido**: el valor se reparte en 5 rangos (quintiles) con la
  paleta elegida; la variación usa rojo ↔ gris ↔ verde y la meta un
  semáforo. Cada paleta tiene su versión para fondo oscuro (de oscuro a
  brillante) y para fondo claro (de claro a intenso): así siempre contrasta.
- **Consola clara u oscura**: sigue el tema de la app (`theme_mode`) y se
  puede cambiar aquí mismo; el fondo del mapa acompaña y se puede elegir.
- Línea de tiempo con «▶ Reproducir», indicadores, clic → ficha de la zona,
  ranking sobre TODAS las zonas, lectura y «Dónde crecer».
"""
from __future__ import annotations

import html
import math
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

from core import territorio as T
from core.filter_engine import apply_filters
from core.loader import load_workbook

# Claves de sesión propias: el archivo que se analiza aquí no tiene por qué
# ser el mismo que el del panel completo, y compartir la clave haría que
# cargar uno pisara al otro.
_CLAVE_LIBRO = "territorial_workbook"
_CLAVE_HOJA = "territorial_sheet"
_CONTEO = "__conteo__"

# ── Paletas ───────────────────────────────────────────────────────────────
# Secuenciales de 5 pasos (un solo recorrido de tono, del valor bajo al
# alto). Cada una en dos versiones: sobre fondo oscuro va de oscuro a
# brillante; sobre fondo claro, de claro a intenso.
_PALETAS = {
    "Rojo intenso": ([(60, 18, 28), (112, 26, 40), (168, 34, 52), (220, 56, 64), (255, 107, 107)],
                     [(254, 224, 224), (252, 170, 165), (244, 108, 100), (214, 48, 49), (150, 15, 30)]),
    "Fuego": ([(52, 16, 92), (120, 28, 109), (189, 55, 84), (240, 112, 39), (252, 206, 72)],
              [(255, 237, 160), (254, 178, 76), (240, 110, 50), (190, 40, 60), (110, 15, 80)]),
    "Océano": ([(14, 36, 72), (20, 72, 128), (26, 120, 180), (48, 170, 220), (120, 220, 250)],
               [(222, 235, 247), (158, 202, 225), (90, 160, 210), (40, 110, 180), (10, 60, 130)]),
    "Esmeralda": ([(10, 48, 40), (14, 90, 66), (22, 138, 92), (46, 190, 120), (140, 235, 170)],
                  [(220, 245, 230), (150, 220, 180), (80, 180, 130), (30, 130, 90), (5, 80, 55)]),
    "Neón": ([(40, 20, 90), (100, 30, 150), (180, 40, 170), (240, 70, 160), (255, 150, 200)],
             [(250, 225, 240), (240, 160, 210), (220, 90, 180), (160, 40, 160), (90, 20, 120)]),
    "Ámbar": ([(58, 36, 10), (110, 68, 12), (170, 108, 16), (226, 152, 30), (255, 206, 90)],
              [(255, 240, 200), (250, 210, 120), (235, 165, 50), (190, 115, 20), (120, 70, 10)]),
}
# Contexto (población): gris violeta, para no confundirse con tus datos.
_PIZARRA = ([(30, 30, 46), (52, 50, 80), (80, 74, 120), (115, 105, 165), (160, 150, 210)],
            [(240, 238, 248), (212, 206, 236), (176, 166, 218), (134, 120, 190), (90, 76, 150)])
# Variación: rojo ↔ gris ↔ verde (sin tono en el centro).
_DIVERGENTE = ([(229, 57, 70), (240, 130, 130), (100, 110, 125), (110, 200, 150), (36, 189, 122)],
               [(200, 30, 45), (240, 150, 150), (190, 195, 205), (130, 205, 160), (20, 150, 95)])
_CORTES_VARIACION = [-0.20, -0.05, 0.05, 0.20]
_SEMAFORO = [(229, 57, 70), (240, 128, 60), (245, 180, 40), (36, 189, 122)]
_CORTES_META = [0.80, 0.90, 1.00]
_MAPAS = {"Oscuro": "CARTO_DARK", "Oscuro sin nombres": "CARTO_DARK_NO_LABELS",
          "Claro": "CARTO_LIGHT", "Claro sin nombres": "CARTO_LIGHT_NO_LABELS", "Calles": "CARTO_ROAD"}
_COLORES = {"volumen": "Volumen", "variacion": "Variación vs mes anterior",
            "meta": "Cumplimiento de meta", "penetracion": "Penetración por habitante"}


def _oscuro() -> bool:
    return st.session_state.get("theme_mode") == "dark"


def _inject_css():
    st.markdown(
        """
        <style>
        @keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
        @keyframes pulso{0%,100%{opacity:1}50%{opacity:.45}}
        .terr-hero{position:relative;overflow:hidden;border-radius:var(--radius-lg);border:1px solid var(--line);
          box-shadow:var(--shadow-md);padding:20px 24px;animation:fadeUp .4s ease both;
          background:radial-gradient(120% 160% at 100% 0%,rgba(15,168,160,.22) 0%,transparent 55%),
                     radial-gradient(90% 140% at 0% 100%,rgba(228,0,43,.14) 0%,transparent 60%),var(--panel)}
        .terr-hero:after{content:"";position:absolute;inset:0;pointer-events:none;opacity:.35;
          background-image:linear-gradient(var(--line-soft) 1px,transparent 1px),linear-gradient(90deg,var(--line-soft) 1px,transparent 1px);
          background-size:28px 28px;mask-image:linear-gradient(90deg,transparent,#000 60%)}
        .terr-hero>*{position:relative;z-index:1}
        .terr-hero .eyebrow{font-size:11px;font-weight:800;letter-spacing:.14em;color:var(--teal);text-transform:uppercase;
          display:inline-flex;align-items:center;gap:8px}
        .terr-hero .eyebrow i{width:8px;height:8px;border-radius:50%;background:var(--teal);box-shadow:0 0 10px var(--teal);
          animation:pulso 1.8s ease-in-out infinite}
        .terr-hero h1{margin:6px 0 4px;font-size:25px;font-family:'Sora','Inter',sans-serif;letter-spacing:-.02em;color:var(--text)}
        .terr-hero p{color:var(--muted);font-size:13px;margin:0;max-width:680px}
        .terr-hero .chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
        .terr-chip{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;font-weight:800;letter-spacing:.04em;
          padding:3px 9px;border-radius:999px;border:1px solid var(--line);color:var(--muted);background:var(--panel-2)}
        .terr-chip.dato{color:var(--teal);border-color:rgba(15,168,160,.45);background:rgba(15,168,160,.10)}
        .terr-chip.dane{color:var(--purple);border-color:rgba(106,91,216,.45);background:rgba(106,91,216,.10)}
        .terr-chip.oport{color:var(--amber-strong);border-color:rgba(200,121,10,.45);background:rgba(200,121,10,.10)}
        .terr-label{font-size:10.5px;font-weight:800;letter-spacing:.11em;text-transform:uppercase;color:var(--muted);margin:16px 0 8px}

        /* Consola: panel de 300px + mapa. Usa los colores del tema, así que
           se ve bien en claro y en oscuro. */
        .st-key-terr_consola{background:var(--panel-2);border:1px solid var(--line);border-radius:18px;padding:14px;
          box-shadow:var(--shadow-md);margin-top:6px}
        .st-key-terr_consola div[data-testid="stHorizontalBlock"]{align-items:flex-start}
        .st-key-terr_consola div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]:first-child{
          flex:0 0 300px;min-width:300px;max-width:300px;width:300px}
        .st-key-terr_consola div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]:last-child{flex:1 1 auto;min-width:0}
        @media(max-width:900px){.st-key-terr_consola div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]:first-child{
          flex:1 1 100%;min-width:0;max-width:none;width:auto}}
        .st-key-terr_panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px 12px 4px;
          gap:.45rem;max-height:860px;overflow-y:auto}
        .terr-sec{font-size:10px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--teal);
          margin:8px 0 2px;display:flex;align-items:center;gap:8px}
        .terr-sec:after{content:"";flex:1;height:1px;background:var(--line)}
        .terr-capa{font-size:11px;color:var(--muted);margin:-6px 0 6px 2px;line-height:1.45}
        .terr-ley{display:grid;gap:3px;margin:4px 0 2px}
        .terr-ley div{display:flex;align-items:center;gap:7px;font-size:11px;color:var(--text)}
        .terr-ley i{width:22px;height:10px;border-radius:3px;flex:0 0 22px;border:1px solid rgba(0,0,0,.08)}

        .terr-mapa-head{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;
          padding:10px 14px;background:var(--panel);border:1px solid var(--line);border-radius:14px 14px 0 0;margin-bottom:-1rem}
        .terr-mapa-head b{font-size:14px;font-family:'Sora','Inter',sans-serif;color:var(--text)}
        .terr-mapa-head .per{font-size:11.5px;font-weight:800;color:var(--teal);letter-spacing:.04em}
        .terr-mapa-head .capas{display:flex;flex-wrap:wrap;gap:5px}
        div[data-testid="stDeckGlJsonChart"]{border-radius:0 0 14px 14px;overflow:hidden;border:1px solid var(--line);border-top:0}

        .terr-estado{font-size:12px;color:var(--muted);margin:4px 2px 8px}
        .terr-estado b{color:var(--text)}
        .terr-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:12px}
        .terr-kpi{background:var(--panel);border:1px solid var(--line);border-top:3px solid var(--teal);border-radius:12px;
          padding:10px 13px;box-shadow:var(--shadow-sm);animation:fadeUp .4s ease both;min-width:0}
        .terr-kpi span{display:block;font-size:10px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}
        .terr-kpi b{display:block;font-size:19px;font-family:'Sora','Inter',sans-serif;color:var(--text);margin-top:3px;
          white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .terr-kpi small{display:block;font-size:11px;color:var(--muted);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .terr-kpi.neg{border-top-color:var(--red)} .terr-kpi.pos{border-top-color:var(--green)} .terr-kpi.oport{border-top-color:var(--amber)}
        .terr-kpi.neg small{color:var(--red)} .terr-kpi.pos small{color:var(--green)}

        .terr-lectura{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--teal);
          border-radius:12px;padding:12px 16px;box-shadow:var(--shadow-sm)}
        .terr-lectura ul{margin:0;padding-left:18px}
        .terr-lectura li{font-size:13px;line-height:1.55;margin-bottom:5px;color:var(--text)}
        .terr-ficha{background:var(--panel);border:1px solid var(--line);border-top:4px solid var(--teal);border-radius:16px;
          padding:14px 18px;box-shadow:var(--shadow-md);margin:12px 0;animation:fadeUp .35s ease both}
        .terr-ficha.oport{border-top-color:var(--amber)}
        .terr-ficha h3{margin:2px 0 2px;font-size:20px;font-family:'Sora','Inter',sans-serif;color:var(--text)}
        .terr-ficha .sub{font-size:12px;color:var(--muted)}
        .terr-ficha .eyebrow{font-size:10.5px;font-weight:800;letter-spacing:.1em;color:var(--teal);text-transform:uppercase}
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
            '<div class="terr-hero"><span class="eyebrow"><i></i>ANÁLISIS TERRITORIAL · COLOMBIA</span>'
            '<h1>Mapea tu red y encuentra dónde expandir</h1>'
            '<p>Tu operación por capas sobre el mapa de Colombia: dónde está, dónde se concentra, dónde cae y '
            'dónde vive la gente a la que todavía no llegas.</p>'
            '<div class="chips"><span class="terr-chip dane">DANE · 1.122 municipios</span>'
            '<span class="terr-chip dane">Población 2026</span><span class="terr-chip dato">Mapas 3D</span>'
            '<span class="terr-chip oport">Dónde crecer</span></div></div>',
            unsafe_allow_html=True,
        )
    with der:
        st.write("")
        if st.button("🧭 Ir a Análisis Completo", use_container_width=True, key="territorial_a_completo"):
            st.session_state.analysis_mode = "completo"
            st.rerun()
        if st.button("🚚 Ir a Logística", use_container_width=True, key="territorial_a_logistica"):
            st.session_state.analysis_mode = "logistica"
            st.rerun()
        # Si el tema se cambió en otra pantalla, el interruptor se pone al día
        # antes de dibujarse; si no, al compararlos devolvería el tema anterior.
        if st.session_state.get("_territorial_tema_ref") != _oscuro():
            st.session_state["territorial_tema"] = _oscuro()
            st.session_state["_territorial_tema_ref"] = _oscuro()
        oscuro = st.toggle("🌙 Consola oscura", key="territorial_tema",
                           help="Cambia el tema de toda la app entre claro y oscuro.")
        if oscuro != _oscuro():
            st.session_state.theme_mode = "dark" if oscuro else "light"
            st.session_state["_territorial_tema_ref"] = oscuro
            st.session_state.pop("territorial_mapa_fondo", None)  # el fondo acompaña al tema
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
                    st.session_state.pop("territorial_zona_sel", None)
                except Exception as exc:
                    st.error(f"No pudimos procesar este archivo: {exc}")
    with columnas[1]:
        otro = st.session_state.get("workbook")
        if otro and not st.session_state.get(_CLAVE_LIBRO):
            if st.button(f'📄 Usar el archivo abierto ({otro["filename"]})',
                         use_container_width=True, key="territorial_reusar"):
                st.session_state[_CLAVE_LIBRO] = otro
                st.session_state[_CLAVE_HOJA] = list(otro["sheets"].keys())[0]
                st.rerun()


# ── Datos (con caché: Streamlit vuelve a correr todo en cada clic) ─────────

@st.cache_data(show_spinner=False, max_entries=6, ttl=1800)
def _ubicar(df: pd.DataFrame, schema: dict):
    return T.ubicar(df, schema)


def _calculo(df, schema, metrica) -> str:
    if metrica == _CONTEO:
        return "Conteo"
    try:
        from core.explorador import calculo_automatico
        return calculo_automatico(df, schema, metrica)
    except Exception:
        return "Suma"


def _meta(df, schema, metrica):
    if metrica == _CONTEO:
        return None
    try:
        from core.performance import columna_meta
        meta = columna_meta(df, schema, metrica)
        return meta if meta in df.columns else None
    except Exception:
        return None


# ── Color por rangos ──────────────────────────────────────────────────────

def _rampa(paleta: str, fondo_oscuro: bool) -> list:
    oscura, clara = _PALETAS.get(paleta, _PALETAS["Rojo intenso"])
    return oscura if fondo_oscuro else clara


def _cortes_quintiles(valores) -> list:
    v = pd.Series(valores, dtype=float)
    v = v[np.isfinite(v)]
    if v.empty:
        return []
    cortes = sorted(set(np.quantile(v, [0.2, 0.4, 0.6, 0.8]).round(10)))
    return [c for c in cortes if v.min() < c < v.max()] or []


def _clase(v, cortes) -> int:
    if v is None or not np.isfinite(v):
        return -1
    return int(np.searchsorted(cortes, v, side="right"))


def _clasificar(tabla: pd.DataFrame, modo: str, paleta: str, fondo_oscuro: bool) -> tuple[list, list]:
    """Color de cada zona y la leyenda por rangos [(color, texto)]."""
    if tabla.empty:
        return [], []
    if modo == "variacion" and "variacion" in tabla.columns:
        colores = _DIVERGENTE[0] if fondo_oscuro else _DIVERGENTE[1]
        textos = ["cayó más de 20%", "cayó 5% a 20%", "estable (±5%)", "subió 5% a 20%", "subió más de 20%"]
        cls = [_clase(v, _CORTES_VARIACION) for v in tabla["variacion"]]
        return [colores[c] if c >= 0 else None for c in cls], list(zip(colores, textos))
    if modo == "meta" and "cumplimiento" in tabla.columns:
        textos = ["menos de 80%", "80% a 90%", "90% a 100%", "100% o más"]
        cls = [_clase(v, _CORTES_META) for v in tabla["cumplimiento"]]
        return [_SEMAFORO[c] if c >= 0 else None for c in cls], list(zip(_SEMAFORO, textos))
    columna = "por_10k" if modo == "penetracion" and "por_10k" in tabla.columns else "valor"
    valores = pd.to_numeric(tabla[columna], errors="coerce")
    rampa = _rampa(paleta, fondo_oscuro)
    cortes = _cortes_quintiles(valores)
    # Con pocos valores distintos hay menos rangos: se usan los tonos del extremo alto.
    paso = rampa[len(rampa) - len(cortes) - 1:]
    cls = [_clase(v, cortes) for v in valores]
    limites = [valores.min()] + cortes + [valores.max()]
    sufijo = " por 10.000 hab." if columna == "por_10k" else ""
    leyenda = [(paso[i], f"{T.cifra(limites[i])} – {T.cifra(limites[i + 1])}{sufijo}") for i in range(len(paso))]
    return [paso[c] if c >= 0 else None for c in cls], leyenda[::-1]


def _ley_html(leyenda: list) -> str:
    if not leyenda:
        return ""
    return '<div class="terr-ley">' + "".join(
        f'<div><i style="background:rgb{tuple(c)}"></i>{html.escape(t)}</div>' for c, t in leyenda) + "</div>"


def _textos(tabla: pd.DataFrame, n: int, unidad: str) -> pd.DataFrame:
    t = tabla.copy()
    t["valor_txt"] = t["valor"].map(T.cifra)
    t["pos_txt"] = t["posicion"].map(lambda p: f"{int(p)}.º de {n}")
    t["part_txt"] = t["participacion"].map(lambda x: f"{x:.1%} del total" if pd.notna(x) else "") \
        if "participacion" in t.columns else ""
    t["var_txt"] = t["variacion"].map(lambda x: f"{x:+.0%} vs mes anterior" if pd.notna(x) else "sin dato del mes anterior") \
        if "variacion" in t.columns else ""
    t["cump_txt"] = t["cumplimiento"].map(lambda x: f"{x:.0%} de la meta" if pd.notna(x) else "") \
        if "cumplimiento" in t.columns else ""
    t["pob_txt"] = t["poblacion"].map(lambda x: f"{T.cifra(x)} habitantes" if pd.notna(x) and x > 0 else "") \
        if "poblacion" in t.columns else ""
    t["pen_txt"] = t["por_10k"].map(lambda x: f"{T.cifra(x)} por cada 10.000 hab." if pd.notna(x) else "") \
        if "por_10k" in t.columns else ""
    t["unidad"] = unidad
    return t


def _tooltip(fondo_oscuro: bool) -> dict:
    fondo, texto, suave, acento = (("#11161f", "#e6e9ef", "#9aa4b2", "#5ee0d4") if fondo_oscuro
                                   else ("#ffffff", "#131826", "#5b6473", "#0f8a85"))
    return {
        "html": ("<div style='font-family:Inter,Segoe UI,sans-serif;min-width:200px'>"
                 "<div style='font-size:14px;font-weight:800'>{nombre}</div>"
                 f"<div style='font-size:11px;color:{suave};margin-bottom:6px'>{{departamento}} · {{pos_txt}}</div>"
                 f"<div style='font-size:18px;font-weight:800;color:{acento}'>{{valor_txt}} "
                 f"<span style='font-size:11px;color:{suave}'>{{unidad}}</span></div>"
                 "<div style='font-size:12px'>{var_txt}</div><div style='font-size:12px'>{cump_txt}</div>"
                 f"<div style='font-size:11px;color:{suave};margin-top:4px'>{{part_txt}}<br>{{pob_txt}}<br>{{pen_txt}}</div></div>"),
        "style": {"backgroundColor": fondo, "color": texto, "border": "1px solid #2a313d" if fondo_oscuro else "1px solid #d8dce6",
                  "borderRadius": "10px", "padding": "10px 12px", "boxShadow": "0 8px 24px rgba(0,0,0,.25)"},
    }


def _vista(lat, lon, inclinacion: float):
    import pydeck as pdk
    puntos = pd.DataFrame({"lon": lon, "lat": lat}).dropna()
    giro = -12 if inclinacion else 0
    if puntos.empty:
        return pdk.ViewState(latitude=4.6, longitude=-74.1, zoom=4.8, pitch=inclinacion, bearing=giro)
    # Con muy pocos puntos (un filtro que deja una sola zona), compute_view
    # recorta los extremos, se queda sin puntos y falla: se centra a mano.
    if len(puntos) < 5 or puntos[["lat", "lon"]].nunique().min() < 2:
        return pdk.ViewState(latitude=float(puntos["lat"].mean()), longitude=float(puntos["lon"].mean()),
                             zoom=7.2, pitch=inclinacion, bearing=giro)
    try:
        vista = pdk.data_utils.compute_view(puntos[["lon", "lat"]], view_proportion=0.95)
    except Exception:
        return pdk.ViewState(latitude=float(puntos["lat"].mean()), longitude=float(puntos["lon"].mean()),
                             zoom=5.5, pitch=inclinacion, bearing=giro)
    vista.pitch, vista.bearing = inclinacion, giro
    vista.zoom = min(max(float(vista.zoom) - 0.1, 4.4), 11.5)
    return vista


_VACIO = {"valor_txt": "Sin actividad", "pos_txt": "", "part_txt": "", "var_txt": "", "cump_txt": "", "pen_txt": "", "unidad": ""}


def _sin_tildes(texto) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto))
    return "".join(ch for ch in t if not unicodedata.combining(ch) and ord(ch) < 128)


def _feature(geom, props) -> dict:
    # Los campos también arriba: el tooltip de deck.gl lee el objeto elegido,
    # que en un GeoJSON es el feature, no sus propiedades.
    return {"type": "Feature", "geometry": geom, "properties": props, **props}


def _construir_mapa(capas_on: dict, zm: pd.DataFrame, zd: pd.DataFrame, hex_t: pd.DataFrame, puntos: pd.DataFrame,
                    crecer: dict, color: str, paleta: str, fondo: str, escala: float, radio_km: float, unidad: str):
    """El objeto pydeck y las leyendas de cada capa activa."""
    import pydeck as pdk
    oscuro = fondo.startswith("Oscuro")
    capas, leyendas = [], {}
    mpios = T.municipios()
    linea = [94, 224, 212, 80] if oscuro else [15, 120, 115, 110]
    sin_dato = [40, 46, 58, 150] if oscuro else [225, 228, 234, 170]
    vistas_lat, vistas_lon = [], []
    inclinacion = 0

    # 1) Contexto: población DANE (abajo de todo).
    if capas_on.get("poblacion"):
        dens = mpios["poblacion"] / mpios["area_km2"].replace(0, np.nan)
        cortes = _cortes_quintiles(np.log10(dens.clip(lower=0.1)))
        rampa = _PIZARRA[0] if oscuro else _PIZARRA[1]
        feats = []
        for f in T.municipios_geojson()["features"]:
            i = f["properties"]["idx"]
            if i < 0:
                continue
            d = dens.iloc[i]
            c = _clase(np.log10(max(d, 0.1)) if np.isfinite(d) else np.nan, cortes)
            r = mpios.iloc[i]
            feats.append(_feature(f["geometry"], {
                "color": list(rampa[c]) + [200] if c >= 0 else sin_dato, "nombre": r["municipio"],
                "departamento": r["departamento"], "zona": str(i), "nivel": "municipio",
                **_VACIO, "valor_txt": f"{T.cifra(r['poblacion'])} hab.", "pob_txt": f"{d:,.0f} hab/km²" if np.isfinite(d) else "",
                "unidad": ""}))
        capas.append(pdk.Layer("GeoJsonLayer", data={"type": "FeatureCollection", "features": feats}, id="poblacion",
                               filled=True, stroked=True, get_fill_color="properties.color", get_line_color=linea,
                               line_width_min_pixels=0.3, pickable=not capas_on.get("mpios")))
        limites = [10 ** x for x in ([np.log10(max(dens.min(), 0.1))] + cortes + [np.log10(dens.max())])]
        leyendas["poblacion"] = [(rampa[i], f"{T.cifra(limites[i])} – {T.cifra(limites[i + 1])} hab/km²")
                                 for i in range(len(cortes) + 1)][::-1]

    # 2) Municipios coloreados (y levantados en 3D si se pide).
    if capas_on.get("mpios") and not zm.empty and "cod_mpio" in zm.columns:
        t = _textos(zm, len(zm), unidad)
        colores, leyendas["mpios"] = _clasificar(t, color, paleta, oscuro)
        tope = float(t["valor"].clip(lower=0).max()) or 1.0
        por_idx = {int(z): (r, c) for z, r, c in zip(t["zona"], t.itertuples(), colores)}
        feats = []
        for f in T.municipios_geojson()["features"]:
            i = f["properties"]["idx"]
            dato = por_idx.get(i)
            if dato is None:
                if not capas_on.get("poblacion"):
                    r = mpios.iloc[i] if i >= 0 else None
                    feats.append(_feature(f["geometry"], {
                        "color": sin_dato, "altura": 0, "nombre": r["municipio"] if r is not None else "",
                        "departamento": r["departamento"] if r is not None else "", "zona": str(i), "nivel": "municipio",
                        **_VACIO, "pob_txt": f"{T.cifra(r['poblacion'])} habitantes" if r is not None else ""}))
                continue
            r, c = dato
            feats.append(_feature(f["geometry"], {
                "color": list(c) + [235] if c else sin_dato, "altura": max(r.valor, 0) / tope * 260_000 * escala,
                "nombre": r.nombre, "departamento": r.departamento, "zona": str(i), "nivel": "municipio",
                "valor_txt": r.valor_txt, "pos_txt": r.pos_txt, "part_txt": r.part_txt, "var_txt": r.var_txt,
                "cump_txt": r.cump_txt, "pob_txt": r.pob_txt, "pen_txt": r.pen_txt, "unidad": unidad}))
        en3d = bool(capas_on.get("mpios3d"))
        capas.append(pdk.Layer("GeoJsonLayer", data={"type": "FeatureCollection", "features": feats}, id="mpios",
                               filled=True, stroked=True, extruded=en3d, wireframe=en3d,
                               get_elevation="properties.altura", get_fill_color="properties.color",
                               get_line_color=linea, line_width_min_pixels=0.4, pickable=True, auto_highlight=True,
                               highlight_color=[94, 224, 212, 220]))
        vistas_lat += list(t["lat"]); vistas_lon += list(t["lon"])
        inclinacion = max(inclinacion, 50 if en3d else 0)

    # 3) Departamentos levantados en 3D.
    if capas_on.get("deptos") and not zd.empty:
        t = _textos(zd, len(zd), unidad)
        colores, leyendas["deptos"] = _clasificar(t, color, paleta, oscuro)
        tope = float(t["valor"].clip(lower=0).max()) or 1.0
        por_cod = {str(z): (r, c) for z, r, c in zip(t["zona"], t.itertuples(), colores)}
        feats = []
        for f in T.departamentos_geojson()["features"]:
            cod = f["properties"]["cod_dpto"]
            dato = por_cod.get(cod)
            base = {"nombre": f["properties"]["departamento"], "departamento": "Departamento", "zona": cod, "nivel": "departamento"}
            if dato:
                r, c = dato
                base.update(altura=max(float(r.valor), 0) / tope * 320_000 * escala, color=list(c) + [215] if c else sin_dato,
                            valor_txt=r.valor_txt, pos_txt=r.pos_txt, part_txt=r.part_txt, var_txt=r.var_txt,
                            cump_txt=r.cump_txt, pob_txt=r.pob_txt, pen_txt=r.pen_txt, unidad=unidad)
            else:
                base.update(altura=0, color=sin_dato, pob_txt="", **_VACIO)
            feats.append(_feature(f["geometry"], base))
        capas.append(pdk.Layer("GeoJsonLayer", data={"type": "FeatureCollection", "features": feats}, id="deptos",
                               extruded=True, wireframe=True, get_elevation="properties.altura",
                               get_fill_color="properties.color", get_line_color=linea, line_width_min_pixels=1,
                               pickable=True, auto_highlight=True, highlight_color=[94, 224, 212, 200]))
        vistas_lat += list(t["lat"]); vistas_lon += list(t["lon"])
        inclinacion = max(inclinacion, 48)
    else:
        # Contornos de departamento siempre, finos: dan contexto a cualquier capa.
        capas.append(pdk.Layer("GeoJsonLayer", data=T.departamentos_geojson(), id="contornos", stroked=True,
                               filled=False, get_line_color=linea[:3] + [130], line_width_min_pixels=1, pickable=False))

    # 4) Columnas 3D por municipio.
    if capas_on.get("columnas") and not zm.empty:
        t = _textos(zm, len(zm), unidad)
        colores, ley = _clasificar(t, color, paleta, oscuro)
        leyendas.setdefault("columnas", ley)
        tope = float(t["valor"].clip(lower=0).max()) or 1.0
        t["altura"] = t["valor"].clip(lower=0) / tope * 320_000 * escala
        t["color"] = [list(c) + [240] if c else sin_dato for c in colores]
        t["zona"] = t["zona"].astype(str)
        capas.append(pdk.Layer("ColumnLayer", data=t, id="zonas", get_position=["lon", "lat"], get_elevation="altura",
                               elevation_scale=1, radius=10_000, disk_resolution=24, extruded=True,
                               get_fill_color="color", pickable=True, auto_highlight=True,
                               highlight_color=[94, 224, 212, 255]))
        vistas_lat += list(t["lat"]); vistas_lon += list(t["lon"])
        inclinacion = max(inclinacion, 52)

    # 5) Hexágonos 3D (ya agregados en core/territorio.hexagonos).
    if capas_on.get("hex") and not hex_t.empty:
        t = _textos(hex_t, len(hex_t), unidad)
        colores, leyendas["hex"] = _clasificar(t, "volumen", paleta, oscuro)
        tope = float(t["valor"].clip(lower=0).max()) or 1.0
        t["altura"] = t["valor"].clip(lower=0) / tope * 300_000 * escala
        t["color"] = [list(c) + [240] if c else sin_dato for c in colores]
        capas.append(pdk.Layer("ColumnLayer", data=t, id="hexagonos", get_position=["lon", "lat"], get_elevation="altura",
                               elevation_scale=1, radius=radio_km * 1000 * 0.94, disk_resolution=6, angle=90,
                               extruded=True, get_fill_color="color", pickable=True, auto_highlight=True,
                               highlight_color=[94, 224, 212, 255]))
        vistas_lat += list(t["lat"]); vistas_lon += list(t["lon"])
        inclinacion = max(inclinacion, 50)

    # 6) Mapa de calor.
    if capas_on.get("calor"):
        base = puntos if not puntos.empty else (zm.rename(columns={"valor": "w"})[["lat", "lon", "w"]] if not zm.empty else pd.DataFrame())
        if not base.empty:
            rampa = _rampa(paleta, True)
            capas.append(pdk.Layer("HeatmapLayer", data=base, id="calor", get_position=["lon", "lat"], get_weight="w",
                                   radius_pixels=55, intensity=1.1, threshold=0.04, aggregation="SUM",
                                   color_range=[list(c) for c in rampa] + [[255, 255, 230]]))
            leyendas["calor"] = [(rampa[-1], "alta concentración"), (rampa[1], "baja concentración")]
            vistas_lat += list(base["lat"]); vistas_lon += list(base["lon"])

    # 7) Puntos.
    if capas_on.get("puntos") and not puntos.empty:
        p = puntos.copy()
        tope = float(p["w"].clip(lower=0).max()) or 1.0
        rampa = _rampa(paleta, oscuro)
        p["r"] = 300 + np.sqrt(p["w"].clip(lower=0) / tope) * 6000
        p["color"] = [list(rampa[min(4, int(math.sqrt(max(w, 0) / tope) * 5))]) + [220] for w in p["w"]]
        capas.append(pdk.Layer("ScatterplotLayer", data=p, id="puntos", get_position=["lon", "lat"], get_radius="r",
                               get_fill_color="color", radius_min_pixels=2, radius_max_pixels=30, opacity=0.9,
                               stroked=True, get_line_color=[255, 255, 255, 90] if oscuro else [0, 0, 0, 60],
                               line_width_min_pixels=0.5))
        vistas_lat += list(p["lat"]); vistas_lon += list(p["lon"])

    # 8) Blancos de expansión: municipios grandes sin presencia, resaltados.
    blancos = crecer.get("blancos") if crecer else None
    if capas_on.get("blancos") and blancos is not None and len(blancos):
        codigos = {c: r for c, r in zip(blancos["cod_mpio"], blancos.itertuples())}
        feats = []
        for f in T.municipios_geojson()["features"]:
            r = codigos.get(f["properties"]["cod_mpio"])
            if r is None:
                continue
            feats.append(_feature(f["geometry"], {
                "nombre": r.municipio, "departamento": f"{r.departamento} · sin presencia", "zona": str(f["properties"]["idx"]),
                "nivel": "blanco", "valor_txt": f"Potencial {T.cifra(r.potencial)}", "pos_txt": "oportunidad",
                "part_txt": "", "var_txt": "", "cump_txt": "", "pob_txt": f"{T.cifra(r.poblacion)} habitantes",
                "pen_txt": "", "unidad": ""}))
        neon = [255, 196, 0] if not oscuro else [255, 214, 10]
        capas.append(pdk.Layer("GeoJsonLayer", data={"type": "FeatureCollection", "features": feats}, id="blancos",
                               filled=True, stroked=True, get_fill_color=neon + [55], get_line_color=neon + [255],
                               line_width_min_pixels=2.5, pickable=True, auto_highlight=True))
        leyendas["blancos"] = [(tuple(neon), f"{len(feats)} municipios grandes sin presencia")]

    # 9) Nombres de las zonas principales.
    if capas_on.get("etiquetas"):
        fuente = zd if (capas_on.get("deptos") and not zd.empty and zm.empty) else zm
        if fuente is not None and not fuente.empty:
            top = fuente.head(12)[["nombre", "lat", "lon", "valor"]].copy()
            # Sin tildes a propósito: el TextLayer solo trae letras ASCII y
            # pydeck no deja ampliarlas (character_set="auto" no dibuja nada y
            # una lista o un texto de caracteres se interpretan como código).
            # Tooltips, ficha y ranking sí llevan los nombres completos.
            top["texto"] = top["nombre"].map(_sin_tildes) + "  " + top["valor"].map(T.cifra)
            capas.append(pdk.Layer("TextLayer", data=top, id="etiquetas", get_position=["lon", "lat"], get_text="texto",
                                   get_size=14, get_color=[235, 240, 245] if oscuro else [20, 24, 38],
                                   get_pixel_offset=[0, -12], billboard=True, font_settings={"sdf": True},
                                   outline_width=3, outline_color=[10, 14, 22, 230] if oscuro else [255, 255, 255, 235]))

    if len(capas) <= 1 and not any(capas_on.values()):
        return None, leyendas
    deck = pdk.Deck(layers=capas, initial_view_state=_vista(vistas_lat, vistas_lon, inclinacion),
                    map_style=getattr(pdk.map_styles, _MAPAS.get(fondo, "CARTO_DARK")), map_provider="carto",
                    tooltip=_tooltip(oscuro))
    return deck, leyendas


# ── Piezas de la pantalla ─────────────────────────────────────────────────

def _kpis(z: dict, cob: dict, crecer: dict, metrica_label: str) -> str:
    tabla = z["tabla"]
    tarjetas = [("", f"{'Total' if z.get('sumable') else 'Promedio'} · {metrica_label}", T.cifra(z["total"]),
                 f"{z['n']} zonas con actividad")]
    if len(tabla):
        lider = tabla.iloc[0]
        part = f" · {lider['participacion']:.0%} del total" if pd.notna(lider.get("participacion")) else ""
        tarjetas.append(("", "Zona líder", str(lider["nombre"]), f"{T.cifra(lider['valor'])}{part}"))
    if "cambio" in tabla.columns and z.get("mes_a"):
        caida = tabla.sort_values("cambio").iloc[0]
        if caida["cambio"] < 0:
            tarjetas.append(("neg", f"Mayor caída · {T.etiqueta_mes(z['mes_b'], True)}", str(caida["nombre"]),
                             f"{T.cifra(caida['cambio'])}" + (f" · {caida['variacion']:+.0%}" if pd.notna(caida['variacion']) else "")))
        subida = tabla.sort_values("cambio", ascending=False).iloc[0]
        if subida["cambio"] > 0:
            tarjetas.append(("pos", f"Mayor subida · {T.etiqueta_mes(z['mes_b'], True)}", str(subida["nombre"]),
                             f"+{T.cifra(subida['cambio'])}" + (f" · {subida['variacion']:+.0%}" if pd.notna(subida['variacion']) else "")))
    if cob:
        tarjetas.append(("", "Cobertura de población", f"{cob['pct_deptos']:.0%}" if cob.get("pct_deptos") else "—",
                         f"{cob['municipios']} de {cob['municipios_deptos']} municipios de tus departamentos"))
    blancos = crecer.get("blancos") if crecer else None
    if blancos is not None and len(blancos):
        tarjetas.append(("oport", "Mayor blanco sin presencia", str(blancos.iloc[0]["municipio"]),
                         f"{T.cifra(blancos.iloc[0]['poblacion'])} habitantes"))
    return '<div class="terr-kpis">' + "".join(
        f'<div class="terr-kpi {tono}"><span>{html.escape(et)}</span><b title="{html.escape(v)}">{html.escape(v)}</b>'
        f'<small title="{html.escape(s)}">{html.escape(s)}</small></div>' for tono, et, v, s in tarjetas) + "</div>"


def _negritas(texto: str) -> str:
    partes = html.escape(texto).split("**")
    return "".join(f"<b>{p}</b>" if i % 2 else p for i, p in enumerate(partes))


def _ranking(z: dict, metrica_label: str):
    tabla = z["tabla"]
    if tabla.empty:
        return
    n = z["n"]
    cols = {"posicion": "#", "nombre": "Zona", "departamento": "Departamento", "valor": metrica_label}
    if "participacion" in tabla.columns and tabla["participacion"].notna().any():
        cols["participacion"] = f"Participación (de {n})"
    if "variacion" in tabla.columns:
        cols["variacion"] = f"Var. {T.etiqueta_mes(z['mes_b'], True)} vs {T.etiqueta_mes(z['mes_a'], True)}"
    if "cumplimiento" in tabla.columns and tabla["cumplimiento"].notna().any():
        cols["cumplimiento"] = "Cumplimiento"
    if "por_10k" in tabla.columns and tabla["por_10k"].notna().any():
        cols["por_10k"] = "Por 10.000 hab."
    if "poblacion" in tabla.columns and tabla["poblacion"].notna().any():
        cols["poblacion"] = "Población"
    vista = tabla[list(cols)].rename(columns=cols).copy()
    for c in (f"Participación (de {n})", "Cumplimiento", cols.get("variacion")):
        if c and c in vista.columns:
            vista[c] = vista[c] * 100
    config = {"#": st.column_config.NumberColumn(width="small", format="%d"),
              metrica_label: st.column_config.NumberColumn(format="localized"),
              "Población": st.column_config.NumberColumn(format="localized"),
              "Por 10.000 hab.": st.column_config.NumberColumn(format="%.1f")}
    if f"Participación (de {n})" in vista.columns:
        config[f"Participación (de {n})"] = st.column_config.ProgressColumn(
            format="%.1f%%", min_value=0, max_value=float(max(vista[f"Participación (de {n})"].max(), 1)))
    if cols.get("variacion"):
        config[cols["variacion"]] = st.column_config.NumberColumn(format="%+.0f%%")
    if "Cumplimiento" in vista.columns:
        config["Cumplimiento"] = st.column_config.NumberColumn(format="%.0f%%")
    st.dataframe(vista, hide_index=True, use_container_width=True, height=min(420, 38 + 35 * len(vista)),
                 column_config=config)
    st.download_button("⬇️ Descargar zonas (CSV)", vista.to_csv(index=False).encode("utf-8-sig"),
                       "zonas_territorio.csv", "text/csv", key="territorial_csv_zonas")


def _ficha_blanco(idx: int, crecer: dict):
    """Ficha de un municipio sin actividad: la oportunidad, con datos DANE."""
    m = T.municipios()
    if idx < 0 or idx >= len(m):
        return
    r = m.iloc[idx]
    crec = (r["poblacion_2030"] / r["poblacion"] - 1) if r["poblacion"] else np.nan
    datos = [("Población 2026", T.cifra(r["poblacion"])), ("Urbana", T.cifra(r["poblacion_cabecera"])),
             ("Rural", T.cifra(r["poblacion_rural"])), ("Proyección 2030", f"{crec:+.1%}" if np.isfinite(crec) else "—")]
    if pd.notna(r.get("area_km2")) and r["area_km2"]:
        datos.append(("Densidad", f"{r['poblacion'] / r['area_km2']:,.0f} hab/km²"))
    blancos = crecer.get("blancos") if crecer else None
    if blancos is not None and r["cod_mpio"] in set(blancos["cod_mpio"]):
        pot = float(blancos.loc[blancos["cod_mpio"] == r["cod_mpio"], "potencial"].iloc[0])
        datos.append(("Potencial estimado", T.cifra(pot)))
    tarjetas = "".join(f'<div class="terr-kpi oport"><span>{html.escape(a)}</span><b>{html.escape(b)}</b></div>' for a, b in datos)
    st.markdown(
        f'<div class="terr-ficha oport"><div class="eyebrow">Municipio sin actividad · oportunidad</div>'
        f'<h3>{html.escape(str(r["municipio"]))}</h3><div class="sub">{html.escape(str(r["departamento"]))} · '
        f'datos DANE (proyecciones 2026)</div><div class="terr-kpis" style="margin-top:12px">{tarjetas}</div></div>',
        unsafe_allow_html=True)


def _ficha(ub, zona_sel: dict, z: dict, crecer: dict, metrica, metrica_label, calculo, fecha_col, dims):
    """Lo que se abre al hacer clic en una zona del mapa."""
    import plotly.graph_objects as go
    tabla = z["tabla"]
    nivel = zona_sel["nivel"]
    clave = zona_sel["zona"]
    # El clic entrega la zona como texto ("125" o "125.0"): se compara por
    # número cuando es un municipio y por texto cuando es un código.
    if nivel == "departamento":
        fila = tabla[tabla["zona"].astype(str) == str(clave)] if not tabla.empty else tabla
    else:
        fila = tabla[pd.to_numeric(tabla["zona"], errors="coerce") == pd.to_numeric(clave, errors="coerce")] if not tabla.empty else tabla
    if fila.empty:
        if nivel in {"municipio", "blanco"}:
            _ficha_blanco(int(float(clave)), crecer)
        else:
            st.info("Esa zona no tiene actividad con el periodo y los filtros actuales.")
    else:
        f = fila.iloc[0]
        datos = [("Valor", T.cifra(f["valor"])), ("Posición", f"{int(f['posicion'])}.º de {z['n']}")]
        if pd.notna(f.get("participacion", np.nan)):
            datos.append(("Participación", f"{f['participacion']:.1%}"))
        if pd.notna(f.get("variacion", np.nan)):
            datos.append((f"vs {T.etiqueta_mes(z['mes_a'], True)}", f"{f['variacion']:+.0%}"))
        if pd.notna(f.get("cumplimiento", np.nan)):
            datos.append(("Meta", f"{f['cumplimiento']:.0%}"))
        if pd.notna(f.get("poblacion", np.nan)) and f.get("poblacion", 0) > 0:
            datos.append(("Población", T.cifra(f["poblacion"])))
        if pd.notna(f.get("por_10k", np.nan)):
            datos.append(("Por 10.000 hab.", T.cifra(f["por_10k"])))
        tarjetas = "".join(f'<div class="terr-kpi"><span>{html.escape(a)}</span><b>{html.escape(b)}</b></div>' for a, b in datos)
        st.markdown(
            f'<div class="terr-ficha"><div class="eyebrow">{"Departamento" if nivel == "departamento" else "Municipio"}</div>'
            f'<h3>{html.escape(str(f["nombre"]))}</h3><div class="sub">{html.escape(str(f.get("departamento", "")))} · '
            f'{int(f["registros"]):,} registros con los filtros actuales</div>'
            f'<div class="terr-kpis" style="margin-top:12px">{tarjetas}</div></div>', unsafe_allow_html=True)
        izq, der = st.columns([1.5, 1])
        with izq:
            serie = T.serie_zona(ub, clave if nivel == "departamento" else int(float(clave)), nivel, metrica, calculo, fecha_col)
            if not serie.empty and len(serie) >= 2:
                fig = go.Figure()
                fig.add_scatter(x=[T.etiqueta_mes(m, True) for m in serie["mes"]], y=serie["zona"], mode="lines+markers",
                                name=str(f["nombre"]), line=dict(color="#0fa8a0", width=3), marker=dict(size=8))
                fig.add_scatter(x=[T.etiqueta_mes(m, True) for m in serie["mes"]], y=serie["promedio"], mode="lines",
                                name=f"Promedio de las {z['n']} zonas", line=dict(color="#9aa4b2", width=2, dash="dash"))
                fig.update_layout(height=280, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", y=1.15),
                                  title=dict(text="Evolución frente al promedio de todas las zonas", font=dict(size=13)),
                                  paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                fig.update_yaxes(tickformat="~s")
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key="territorial_ficha_serie")
            else:
                st.caption("Sin varios meses de datos para dibujar la evolución de esta zona.")
        with der:
            en_zona = ub[ub["_t_ok"]]
            en_zona = en_zona[(en_zona["_t_cod_dpto"] == clave) if nivel == "departamento"
                              else (en_zona["_t_idx"] == int(float(clave)))]
            for dim in dims[:2]:
                if dim not in en_zona.columns:
                    continue
                valores = en_zona.assign(_v=1.0 if metrica == _CONTEO else pd.to_numeric(en_zona[metrica], errors="coerce"))
                top = valores.groupby(dim)["_v"].sum().sort_values(ascending=False).head(6)
                if len(top) >= 2:
                    st.markdown(f"**Por {html.escape(str(dim)).lower()}**")
                    st.dataframe(top.rename(metrica_label).reset_index(), hide_index=True, use_container_width=True,
                                 column_config={metrica_label: st.column_config.ProgressColumn(
                                     format="%.0f", min_value=0, max_value=float(top.max()))})
    if st.button("✕ Cerrar ficha", key="territorial_cerrar_ficha"):
        st.session_state.pop("territorial_zona_sel", None)
        st.rerun()


def _donde_crecer(crecer: dict, metrica_label: str):
    blancos, rezagados = crecer.get("blancos"), crecer.get("rezagados")
    if (blancos is None or blancos.empty) and (rezagados is None or rezagados.empty):
        st.caption("«Dónde crecer» necesita una métrica que se sume, ubicación por municipio y al menos 5 municipios con actividad.")
        return
    tipica = crecer.get("penetracion_tipica")
    st.caption(f"Referencia: en un municipio típico de tu red hay **{T.cifra(tipica)}** de {metrica_label.lower()} por cada "
               "10.000 habitantes. El potencial es la **mitad** del camino hasta esa referencia: una meta exigente pero creíble.")
    a, b = st.columns(2)
    with a:
        st.markdown("**🎯 Municipios grandes sin presencia** (en los departamentos donde ya operas)")
        if blancos is not None and len(blancos):
            v = blancos[["municipio", "departamento", "poblacion", "poblacion_cabecera", "potencial"]].rename(columns={
                "municipio": "Municipio", "departamento": "Departamento", "poblacion": "Población",
                "poblacion_cabecera": "Urbana", "potencial": "Potencial estimado"})
            st.dataframe(v, hide_index=True, use_container_width=True, column_config={
                "Población": st.column_config.NumberColumn(format="localized"),
                "Urbana": st.column_config.NumberColumn(format="localized"),
                "Potencial estimado": st.column_config.NumberColumn(format="localized")})
    with b:
        st.markdown("**📉 Presentes pero por debajo de lo normal** (menos de la mitad de la penetración típica)")
        if rezagados is not None and len(rezagados):
            v = rezagados[["nombre", "departamento", "poblacion", "por_10k", "potencial"]].rename(columns={
                "nombre": "Municipio", "departamento": "Departamento", "poblacion": "Población",
                "por_10k": "Por 10.000 hab.", "potencial": "Potencial estimado"})
            st.dataframe(v, hide_index=True, use_container_width=True, column_config={
                "Población": st.column_config.NumberColumn(format="localized"),
                "Por 10.000 hab.": st.column_config.NumberColumn(format="%.1f"),
                "Potencial estimado": st.column_config.NumberColumn(format="localized")})
        else:
            st.caption("Ningún municipio con presencia está por debajo de la mitad de la penetración típica.")


# ── Pantalla ──────────────────────────────────────────────────────────────

# (clave, título, explicación, etiqueta de fuente, clase de la etiqueta)
_CAPAS = [
    ("mpios", "Municipios coloreados", "Cada municipio pintado según el valor, por rangos.", "Tu archivo · DANE MGN", "dato"),
    ("columnas", "Columnas 3D", "Una columna por municipio: altura = volumen.", "Tu archivo", "dato"),
    ("deptos", "Departamentos 3D", "Cada departamento levantado según su total.", "Tu archivo", "dato"),
    ("hex", "Hexágonos 3D", "Los puntos agrupados en hexágonos y levantados.", "Tus coordenadas", "dato"),
    ("calor", "Mapa de calor", "Manchas donde se concentra la actividad.", "Tu archivo", "dato"),
    ("puntos", "Puntos", "Cada registro en su coordenada.", "Tus coordenadas", "dato"),
    ("poblacion", "Población DANE 2026", "Densidad de población por municipio, como contexto.", "DANE · proyecciones", "dane"),
    ("blancos", "Blancos de expansión", "Municipios grandes donde aún no hay presencia.", "Oportunidad", "oport"),
    ("etiquetas", "Nombres de las zonas", "Las 12 zonas más fuertes, con su cifra.", "Tu archivo", "dato"),
]


def render_territorial_page():
    """Pantalla completa de Análisis Territorial."""
    _inject_css()
    _cabecera()

    st.markdown('<div class="terr-label">Archivo</div>', unsafe_allow_html=True)
    _cargador()

    libro, hoja = _hoja_activa()
    if not libro:
        st.info("Sube un Excel o CSV para mapear tu red, o usa el archivo que ya tengas abierto en el panel. "
                "Sirve si trae coordenadas, una columna de municipio o ciudad, de departamento, o el municipio "
                "escrito dentro de otro texto (por ejemplo, el nombre del punto de venta).")
        return

    item = libro["sheets"][hoja]
    df_hoja, schema = item["processed"], item["profile"]["schema"]
    from visualization.charts import _label, dimension_candidates, metric_candidates
    metricas = [m for m in metric_candidates(df_hoja, schema) if m in df_hoja.columns]

    with st.container(key="terr_consola"):
        panel, principal = st.columns([300, 720], gap="medium")

    with panel, st.container(key="terr_panel"):
        st.markdown('<div class="terr-sec">Datos</div>', unsafe_allow_html=True)
        hojas = list(libro["sheets"].keys())
        if len(hojas) > 1:
            elegida = st.selectbox("Hoja", hojas, index=hojas.index(hoja), key="territorial_hoja_sel")
            if elegida != hoja:
                st.session_state[_CLAVE_HOJA] = elegida
                st.session_state.pop("territorial_zona_sel", None)
                st.rerun()
        metrica = st.selectbox("Métrica", metricas + [_CONTEO], key="territorial_metrica",
                               format_func=lambda c: "Cantidad de registros" if c == _CONTEO else _label(schema, c))
        metrica_label = "Registros" if metrica == _CONTEO else _label(schema, metrica)
        dims = [d for d in dimension_candidates(df_hoja, schema) if d in df_hoja.columns][:5]
        filtros = {}
        with st.expander("Filtros", expanded=False):
            for dim in dims:
                valores = sorted(df_hoja[dim].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique())
                if 1 < len(valores) <= 200:
                    elegidos = st.multiselect(_label(schema, dim), valores, key=f"territorial_filtro_{dim}", placeholder="Todos")
                    if elegidos:
                        filtros[dim] = {"op": "in", "value": elegidos}
        # Un solo motor de filtros en toda la app (CLAUDE.md).
        df = apply_filters(df_hoja, filtros) if filtros else df_hoja

    with st.spinner("Ubicando cada registro en el mapa…"):
        ub, meta = _ubicar(df, schema)
    if not meta["ubicadas"]:
        with principal:
            st.warning("No se pudo ubicar ningún registro de esta hoja. El mapa necesita coordenadas, una columna de "
                       "municipio, ciudad o departamento de Colombia, o el municipio escrito dentro de otro texto.")
            if meta.get("no_ubicados"):
                st.caption("Ejemplos que no se reconocieron: " + ", ".join(f"«{k}»" for k in meta["no_ubicados"]))
        return

    calculo = _calculo(df, schema, metrica)
    meta_col = _meta(df, schema, metrica)
    fecha_col = next((c for c in schema.get("dates", []) if c in df.columns), None)
    meses = T.meses_disponibles(ub[ub["_t_ok"]], fecha_col)
    con_coordenadas = meta["origen"] == "coordenadas"
    en_colombia = bool(meta.get("en_colombia", True))
    solo_departamento = meta["origen"] == "departamento"
    por_municipio = en_colombia and not solo_departamento

    disponibles = {"mpios": por_municipio, "columnas": por_municipio, "deptos": en_colombia, "hex": con_coordenadas,
                   "calor": True, "puntos": con_coordenadas, "poblacion": True, "blancos": por_municipio,
                   "etiquetas": True}
    por_defecto = ({"hex", "etiquetas"} if con_coordenadas else {"mpios", "blancos", "etiquetas"} if por_municipio
                   else {"deptos", "etiquetas"})

    with panel, st.container(key="terr_panel_2"):
        periodo, jugar = None, False
        if len(meses) >= 2:
            opciones_mes = ["Todo"] + meses
            if st.session_state.get("territorial_mes") not in opciones_mes:
                st.session_state["territorial_mes"] = "Todo"
            periodo = st.select_slider("Periodo", opciones_mes, key="territorial_mes",
                                       format_func=lambda m: "Todo el periodo" if m == "Todo" else T.etiqueta_mes(m, True))
            periodo = None if periodo == "Todo" else periodo
            jugar = st.toggle("▶ Reproducir mes a mes", key="territorial_play",
                              help="Recorre los meses en el mapa, uno cada segundo y medio.")

        st.markdown('<div class="terr-sec">Capas</div>', unsafe_allow_html=True)
        capas_on, huecos = {}, {}
        for clave, titulo, explicacion, fuente, clase in _CAPAS:
            if not disponibles.get(clave):
                continue
            capas_on[clave] = st.toggle(titulo, value=clave in por_defecto, key=f"territorial_capa_{clave}")
            st.markdown(f'<div class="terr-capa">{html.escape(explicacion)} <span class="terr-chip {clase}">'
                        f'{html.escape(fuente)}</span></div>', unsafe_allow_html=True)
            if clave == "mpios" and capas_on[clave]:
                capas_on["mpios3d"] = st.checkbox("Levantar los municipios en 3D", key="territorial_mpios3d")
            huecos[clave] = st.empty()

        st.markdown('<div class="terr-sec">Estilo</div>', unsafe_allow_html=True)
        colores = ["volumen"] + (["variacion"] if len(meses) >= 2 else []) + (["meta"] if meta_col else []) \
            + (["penetracion"] if en_colombia and calculo in {"Suma", "Conteo"} else [])
        color = st.selectbox("Color según", colores, key="territorial_color", format_func=_COLORES.get,
                             help="La altura siempre es el volumen; el color dice su estado.")
        paleta = st.selectbox("Paleta", list(_PALETAS), key="territorial_paleta",
                              help="Cada paleta se ajusta sola al fondo: de oscuro a brillante sobre fondo oscuro, "
                                   "de claro a intenso sobre fondo claro.")
        opciones_fondo = list(_MAPAS)
        if st.session_state.get("territorial_mapa_fondo") not in opciones_fondo:
            st.session_state["territorial_mapa_fondo"] = "Oscuro" if _oscuro() else "Claro"
        fondo = st.selectbox("Fondo del mapa", opciones_fondo, key="territorial_mapa_fondo")
        escala = st.slider("Altura 3D", 0.3, 3.0, 1.0, 0.1, key="territorial_escala")
        radio_km = st.slider("Tamaño del hexágono (km)", 1.0, 40.0, 8.0, 1.0, key="territorial_radio") \
            if capas_on.get("hex") else 8.0

    # ── Cálculo por zona del periodo elegido ──
    metrica_calc = None if metrica == _CONTEO else metrica
    nivel_mpio = "municipio" if por_municipio else "punto"

    def _calcular(mes):
        zm = T.zonas(ub, metrica_calc, calculo, nivel_mpio, fecha_col, mes, meta_col)
        zd = T.zonas(ub, metrica_calc, calculo, "departamento", fecha_col, mes, meta_col) if en_colombia \
            else {"tabla": pd.DataFrame(), "n": 0}
        return zm, zd

    zm, zd = _calcular(periodo)
    z = zd if solo_departamento else zm
    crecer = T.donde_crecer(zm) if nivel_mpio == "municipio" else {}
    cob = T.cobertura(zm) if nivel_mpio == "municipio" else {}

    def _puntos(mes):
        datos = ub[ub["_t_ok"]]
        if mes and fecha_col:
            datos = datos[pd.to_datetime(datos[fecha_col], errors="coerce").dt.strftime("%Y-%m") == mes]
        w = 1.0 if metrica == _CONTEO else pd.to_numeric(datos[metrica], errors="coerce").fillna(0)
        return pd.DataFrame({"lat": datos["_t_lat"].astype(float), "lon": datos["_t_lon"].astype(float), "w": w})

    def _dibujar(mes, clave_evento: Optional[str], leyendas_panel: bool = True):
        zm_m, zd_m = (zm, zd) if mes == periodo else _calcular(mes)
        hex_t = T.hexagonos(ub, metrica_calc, calculo, radio_km, fecha_col, mes) if capas_on.get("hex") else pd.DataFrame()
        deck, leyendas = _construir_mapa(capas_on, zm_m["tabla"], zd_m["tabla"], hex_t,
                                         _puntos(mes) if (capas_on.get("calor") or capas_on.get("puntos")) else pd.DataFrame(),
                                         crecer, color, paleta, fondo, escala, radio_km, metrica_label)
        # Desde la animación (un fragmento) no se puede escribir en el panel,
        # que está fuera de él: las leyendas se quedan como estaban.
        if leyendas_panel:
            for clave, hueco in huecos.items():
                hueco.markdown(_ley_html(leyendas.get(clave, [])) if capas_on.get(clave) else "", unsafe_allow_html=True)
        etiqueta = T.etiqueta_mes(mes) if mes else (
            f"Todo el periodo · {T.etiqueta_mes(meses[0], True)} – {T.etiqueta_mes(meses[-1], True)}" if meses else "Todos los registros")
        activas = [t for c, t, *_ in _CAPAS if capas_on.get(c)]
        st.markdown(f'<div class="terr-mapa-head"><div><b>{html.escape(metrica_label)} · {html.escape(_COLORES[color])}</b><br>'
                    f'<span class="per">{html.escape(etiqueta)}</span></div><div class="capas">'
                    + "".join(f'<span class="terr-chip dato">{html.escape(a)}</span>' for a in activas) + "</div></div>",
                    unsafe_allow_html=True)
        if deck is None:
            st.info("Prende al menos una capa en el panel de la izquierda.")
            return None
        if clave_evento:
            return st.pydeck_chart(deck, height=680, use_container_width=True, on_select="rerun",
                                   selection_mode="single-object", key=clave_evento)
        st.pydeck_chart(deck, height=680, use_container_width=True)
        return None

    with principal:
        origen = {"coordenadas": f"las coordenadas ({meta['columna']})", "municipio": f"la columna «{meta['columna']}»",
                  "departamento": f"la columna «{meta['columna']}» (nivel departamento)",
                  "texto": f"el municipio escrito en «{meta['columna']}»"}.get(meta["origen"], "")
        st.markdown(f'<div class="terr-estado">📍 Ubicados <b>{meta["ubicadas"]:,} de {meta["total"]:,}</b> registros '
                    f'a partir de {html.escape(origen)}.</div>', unsafe_allow_html=True)
        if jugar and len(meses) >= 2:
            # La animación vive en un fragmento que se redibuja solo, sin
            # correr el resto de la pantalla.
            @st.fragment(run_every=1.5)
            def _animacion():
                i = st.session_state.get("territorial_play_i", 0) % len(meses)
                _dibujar(meses[i], None, leyendas_panel=False)
                st.session_state["territorial_play_i"] = i + 1
            _animacion()
            evento = None
        else:
            evento = _dibujar(periodo, "territorial_deck")
        st.markdown(_kpis(z if not z["tabla"].empty else zm, cob, crecer, metrica_label), unsafe_allow_html=True)
        if meta.get("no_ubicados"):
            with st.expander(f"{meta['total'] - meta['ubicadas']:,} registros sin ubicar"):
                st.caption("Valores que no se reconocieron como un municipio de Colombia: " +
                           ", ".join(f"«{html.escape(str(k))}» ({v})" for k, v in meta["no_ubicados"].items()))

    # Clic en una zona → su ficha.
    try:
        objetos = (evento.selection.get("objects") or {}) if evento is not None else {}
    except Exception:
        objetos = {}
    for capa in ("mpios", "zonas", "deptos", "blancos", "poblacion"):
        elegido = (objetos.get(capa) or [None])[0]
        if elegido:
            props = elegido.get("properties", elegido)
            st.session_state["territorial_zona_sel"] = {"zona": str(props.get("zona")), "nivel": props.get(
                "nivel", "departamento" if capa == "deptos" else nivel_mpio)}
    seleccion = st.session_state.get("territorial_zona_sel")
    if seleccion:
        _ficha(ub, seleccion, zd if seleccion["nivel"] == "departamento" else zm, crecer, metrica, metrica_label,
               calculo, fecha_col, dims)

    izq, der = st.columns([1.4, 1])
    with izq:
        st.markdown('<div class="terr-label">Ranking de zonas</div>', unsafe_allow_html=True)
        _ranking(z, metrica_label)
    with der:
        st.markdown('<div class="terr-label">Lectura del territorio</div>', unsafe_allow_html=True)
        frases = T.lectura(zm if nivel_mpio == "municipio" else z, crecer, cob, metrica_label)
        if frases:
            st.markdown('<div class="terr-lectura"><ul>' + "".join(f"<li>{_negritas(f)}</li>" for f in frases)
                        + "</ul></div>", unsafe_allow_html=True)
    if nivel_mpio == "municipio":
        st.markdown('<div class="terr-label">Dónde crecer</div>', unsafe_allow_html=True)
        _donde_crecer(crecer, metrica_label)

    st.caption(f"{libro['filename']} · hoja {hoja} · {len(df):,} registros"
               + (f" (con filtros, de {len(df_hoja):,})" if filtros else "")
               + " · Municipios, contornos y población: DANE (DIVIPOLA, Marco Geoestadístico Nacional y proyecciones 2026).")
