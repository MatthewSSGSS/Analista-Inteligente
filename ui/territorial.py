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
- **Color con sentido**: por defecto, el semáforo 🚦 (verde subió más de
  5%, amarillo estable, rojo bajó más de 5%, con dos intensidades); también
  semáforo de meta, o el valor en 5 rangos (quintiles) con la paleta
  elegida. El mismo color llega al Top 10, al borde de las etiquetas y a
  los anillos de «Focos del mes».
- **Por qué subió o bajó**: el tablero del semáforo, la tarjeta de la zona
  y la ficha dicen qué lo movió (`core/territorio.motivos`): el canal,
  asesor o producto en un municipio; los municipios en un departamento. Cada paleta tiene su versión para fondo oscuro (de oscuro a
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
from ui.components.descarga import preparar_y_descargar
from ui.report_territorial import build_territorial_excel, build_territorial_html, nombre_archivo

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
# Semáforo de la variación: rojo (bajó) · amarillo (estable, ±5%) · verde
# (subió), con dos intensidades a cada lado. Sobre fondo oscuro, tonos
# brillantes; sobre fondo claro, más hondos para que contrasten.
_SEMAFORO_VAR = ([(239, 68, 68), (248, 145, 120), (250, 204, 21), (120, 222, 160), (34, 197, 94)],
                 [(200, 30, 45), (240, 135, 120), (234, 179, 8), (115, 200, 145), (22, 150, 75)])
_CORTES_VARIACION = [-0.20, -T.UMBRAL_ESTABLE, T.UMBRAL_ESTABLE, 0.20]
# Semáforo de la meta: rojo < 90% · amarillo 90–100% · verde ≥ 100%.
_SEMAFORO = ([(239, 68, 68), (250, 204, 21), (34, 197, 94)], [(214, 40, 50), (234, 179, 8), (22, 163, 74)])
_CORTES_META = [0.90, 1.00]
# Los mismos tres estados para bordes de etiquetas, anillos y tarjetas.
_ESTADO_RGB = {"bajo": (239, 68, 68), "estable": (250, 204, 21), "subio": (34, 197, 94)}
_ESTADO_ICONO = {"bajo": "🔴", "estable": "🟡", "subio": "🟢"}
_ALTO_MAPA = 900   # px; el panel y el riel se desplazan por dentro para no pasarse de esto
_MAPAS = {"Oscuro": "CARTO_DARK", "Oscuro sin nombres": "CARTO_DARK_NO_LABELS",
          "Claro": "CARTO_LIGHT", "Claro sin nombres": "CARTO_LIGHT_NO_LABELS", "Calles": "CARTO_ROAD"}
_COLORES = {"variacion": "🚦 Semáforo: subió · estable · bajó", "meta": "🚦 Semáforo de meta",
            "volumen": "Volumen", "penetracion": "Penetración por habitante"}


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
        .terr-chip.oport{color:#a855f7;border-color:rgba(168,85,247,.45);background:rgba(168,85,247,.10)}
        .terr-label{font-size:12px;font-weight:800;letter-spacing:.11em;text-transform:uppercase;color:var(--muted);margin:16px 0 8px}

        /* Consola: panel 320 px · mapa · riel 360 px. Usa los colores del
           tema, así que se ve bien en claro y en oscuro.

           Los anchos llevan !important y el mapa min-width:0 porque Streamlit
           le da a cada columna un ancho mínimo proporcional (el mapa pedía
           ~62% de la fila): sumado a los 680 px fijos de los lados no cabía y
           el riel se caía SOLO a la fila de abajo, pegado a la izquierda.
           Los cortes se miden sobre la propia consola (consultas de
           contenedor), no sobre la ventana: así el zoom del navegador y la
           barra lateral no los engañan. */
        .st-key-terr_consola{background:var(--panel-2);border:1px solid var(--line);border-radius:20px;padding:16px;
          box-shadow:var(--shadow-md);margin-top:6px;container-type:inline-size;container-name:consola}
        .st-key-terr_consola div[data-testid="stHorizontalBlock"]{align-items:flex-start;flex-wrap:nowrap!important}
        .st-key-terr_consola div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]:first-child{
          flex:0 0 320px!important;min-width:320px!important;max-width:320px!important;width:320px!important}
        .st-key-terr_consola div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]:nth-child(2){
          flex:1 1 0!important;min-width:0!important;max-width:none!important;width:auto!important}
        .st-key-terr_consola div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]:nth-child(3){
          flex:0 0 360px!important;min-width:360px!important;max-width:360px!important;width:360px!important}
        /* Sin espacio para las tres: el riel baja, pero a TODO el ancho y con
           sus tarjetas repartidas en columnas (zona elegida, Top 10,
           alertas lado a lado), no como una tira angosta sola a la izquierda. */
        @container consola (max-width:1320px){
          .st-key-terr_consola div[data-testid="stHorizontalBlock"]{flex-wrap:wrap!important;row-gap:16px}
          .st-key-terr_consola div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]:nth-child(2){
            flex:1 1 calc(100% - 352px)!important}
          .st-key-terr_consola div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]:nth-child(3){
            flex:1 1 100%!important;min-width:0!important;max-width:none!important;width:100%!important}
          .st-key-terr_riel{display:block!important;columns:3 300px;column-gap:16px}
          .st-key-terr_riel>div{break-inside:avoid;margin-bottom:14px}}
        @container consola (max-width:860px){
          .st-key-terr_consola div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]{
            flex:1 1 100%!important;min-width:0!important;max-width:none!important;width:100%!important}}

        /* Barra de indicadores sobre el mapa */
        .terr-hud{display:grid;grid-template-columns:minmax(280px,1.5fr) repeat(4,minmax(0,1fr));gap:12px;margin-bottom:14px}
        .terr-hud-tile{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 18px;min-width:0;
          box-shadow:var(--shadow-sm);position:relative;overflow:hidden;animation:fadeUp .35s ease both}
        .terr-hud-tile:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--teal)}
        .terr-hud-tile.neg:before{background:var(--red)} .terr-hud-tile.anillo:before{background:var(--purple)}
        .terr-hud-tile.principal{background:linear-gradient(135deg,rgba(15,168,160,.13),transparent 70%),var(--panel)}
        .terr-hud-tile>span{display:block;font-size:11px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:var(--muted)}
        .terr-hud-tile .fila{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:5px}
        .terr-hud-tile b{font-size:25px;font-family:'Sora','Inter',sans-serif;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .terr-hud-tile.principal b{font-size:32px;overflow:visible;flex:0 0 auto}
        .terr-hud-tile.principal .fila{flex-wrap:wrap;row-gap:2px}
        .terr-hud-tile small{display:block;font-size:12.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .terr-hud-tile.neg small{color:var(--red)}
        .terr-hud-tile.anillo .fila{justify-content:flex-start}
        .terr-hud-tile.anillo small{white-space:normal;line-height:1.3}
        .terr-delta{display:inline-flex;align-items:center;gap:4px;font-size:12.5px;font-weight:800;padding:2px 9px;margin-top:4px;border-radius:99px}
        .terr-delta.pos{color:var(--green);background:var(--green-soft)} .terr-delta.neg{color:var(--red);background:var(--red-soft)}
        .terr-delta small{display:inline;color:inherit;opacity:.8;font-weight:600}
        .terr-spark{flex:0 0 auto}
        @media(max-width:1750px){.terr-hud{grid-template-columns:repeat(3,minmax(0,1fr))}}

        /* Riel derecho */
        .st-key-terr_riel{gap:.8rem}
        .terr-rail-card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px 18px;box-shadow:var(--shadow-sm);
          animation:fadeUp .35s ease both}
        .terr-rail-card .eyebrow{display:block;font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--teal);margin-bottom:6px}
        .terr-rail-card.sel{border:1px solid rgba(15,168,160,.55);box-shadow:0 0 0 3px rgba(15,168,160,.12),var(--shadow-sm)}
        .terr-rail-card.oport{border-color:rgba(168,85,247,.55);box-shadow:0 0 0 3px rgba(168,85,247,.14)}
        .terr-rail-card.oport .eyebrow{color:#a855f7}
        .terr-rail-card h4{margin:0;padding:0;border:0;background:none;box-shadow:none;font-size:23px;font-family:'Sora','Inter',sans-serif;color:var(--text);letter-spacing:-.01em}
        .terr-rail-card .sub{font-size:13px;color:var(--muted);margin-bottom:6px}
        .terr-rail-card .pista{font-size:12px;color:var(--muted);margin-top:8px}
        .terr-mini{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}
        .terr-mini div{background:var(--panel-2);border-radius:10px;padding:8px 11px}
        .terr-mini span{display:block;font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;font-weight:700}
        .terr-mini b{font-size:18px;color:var(--text)}
        .terr-top-fila{display:flex;gap:11px;align-items:center;padding:8px 0;border-bottom:1px dashed var(--line-soft)}
        .terr-top-fila:last-child{border-bottom:0}
        .terr-top-fila .num{flex:0 0 28px;height:28px;border-radius:8px;display:grid;place-items:center;font-size:13px;font-weight:800;
          background:var(--panel-2);color:var(--muted)}
        .terr-top-fila:nth-child(2) .num{background:var(--teal);color:#fff}
        .terr-top-fila .cuerpo{flex:1;min-width:0}
        .terr-top-fila .nom{display:flex;align-items:baseline;gap:8px;font-size:14.5px}
        .terr-top-fila .nom b{flex:1;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .terr-top-fila .nom i{font-style:normal;font-weight:700;color:var(--text);font-variant-numeric:tabular-nums}
        .terr-top-fila .nom em{font-style:normal;font-size:12px;font-weight:800}
        .terr-top-fila em.pos{color:var(--green)} .terr-top-fila em.neg{color:var(--red)}
        .terr-top-fila .barra{height:7px;border-radius:99px;background:var(--panel-2);margin-top:4px;overflow:hidden}
        .terr-top-fila .barra u{display:block;height:100%;border-radius:99px;text-decoration:none}
        .terr-alerta{border-left:4px solid var(--muted);padding:9px 12px;margin:8px 0;border-radius:0 8px 8px 0;background:var(--panel-2)}
        .terr-alerta b{display:block;font-size:14px;color:var(--text)}
        .terr-alerta small{font-size:12.5px;color:var(--muted)}
        .terr-alerta.neg{border-left-color:var(--red)} .terr-alerta.warn{border-left-color:var(--amber)}
        .terr-alerta.oport{border-left-color:#a855f7}
        .st-key-terr_panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px 12px 4px;
          gap:.5rem;max-height:1140px;overflow-y:auto}
        /* Periodo, capas y estilo se desplazan dentro del panel: así el panel
           no se estira más que el mapa y no deja un hueco debajo. */
        .st-key-terr_panel_2{max-height:900px;overflow-y:auto;padding-right:4px;scrollbar-width:thin}
        .terr-sec{font-size:10px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--teal);
          margin:8px 0 2px;display:flex;align-items:center;gap:8px}
        .terr-sec:after{content:"";flex:1;height:1px;background:var(--line)}
        .terr-capa{font-size:12px;color:var(--muted);margin:-6px 0 6px 2px;line-height:1.45}
        .terr-ley{display:grid;gap:3px;margin:4px 0 2px}
        .terr-ley div{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--text)}
        .terr-ley i{width:26px;height:12px;border-radius:3px;flex:0 0 22px;border:1px solid rgba(0,0,0,.08)}

        .terr-mapa-head{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;
          padding:14px 18px 26px;background:var(--panel);border:1px solid var(--line);border-radius:16px 16px 0 0;margin-bottom:-1rem}
        .terr-mapa-head b{font-size:17px;font-family:'Sora','Inter',sans-serif;color:var(--text)}
        .terr-mapa-head .per{font-size:13px;font-weight:800;color:var(--teal);letter-spacing:.04em}
        .terr-mapa-head .capas{display:flex;flex-wrap:wrap;gap:5px}
        div[data-testid="stDeckGlJsonChart"]{border-radius:0 0 16px 16px;overflow:hidden;border:1px solid var(--line);border-top:0}

        /* Semáforo: rojo · amarillo · verde con los tonos del tema */
        .terr-mapa-head .corte{display:block;font-size:12.5px;font-weight:700;color:var(--amber-strong);margin-top:2px}
        .terr-mapa-head .corte.suave{color:var(--muted);font-weight:600}
        .terr-sem-chip{display:inline-flex;align-items:center;gap:5px;font-size:13px;font-weight:800;padding:5px 13px;
          border-radius:999px;border:1px solid}
        .terr-sem-chip.subio{color:var(--green);background:var(--green-soft);border-color:color-mix(in srgb,var(--green) 40%,transparent)}
        .terr-sem-chip.estable{color:var(--amber-strong);background:var(--amber-soft);border-color:color-mix(in srgb,var(--amber) 45%,transparent)}
        .terr-sem-chip.bajo{color:var(--red);background:var(--red-soft);border-color:color-mix(in srgb,var(--red) 40%,transparent)}
        .terr-hud-tile.sem:before{background:linear-gradient(180deg,#22c55e,#eab308,#ef4444)}
        .terr-hud-tile.sem .fila,.terr-hud-tile.mov .fila{display:block}
        .terr-sem-cuenta{display:flex;gap:14px;white-space:nowrap;font-family:'Sora','Inter',sans-serif;font-size:24px;font-weight:800;margin:2px 0 7px}
        .terr-sem-cuenta .subio{color:var(--green)} .terr-sem-cuenta .estable{color:var(--amber)} .terr-sem-cuenta .bajo{color:var(--red)}
        .terr-sem-barra{display:flex;height:11px;border-radius:99px;overflow:hidden;background:var(--panel-2);gap:2px}
        .terr-sem-barra i{display:block;height:100%}
        .terr-sem-barra i.subio{background:#22c55e} .terr-sem-barra i.estable{background:#eab308} .terr-sem-barra i.bajo{background:#ef4444}
        .terr-hud-tile.mov:before{background:linear-gradient(180deg,#22c55e,#ef4444)}
        .terr-mov{display:flex;align-items:baseline;gap:8px;font-size:14.5px;margin-top:5px;min-width:0}
        .terr-mov em{font-style:normal;font-weight:900;font-size:11px}
        .terr-mov b{flex:1;min-width:0;font-size:16px!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .terr-mov i{font-style:normal;font-weight:800;font-variant-numeric:tabular-nums}
        .terr-mov.subio em,.terr-mov.subio i{color:var(--green)} .terr-mov.bajo em,.terr-mov.bajo i{color:var(--red)}
        .terr-rail-card.sel.subio{border-color:color-mix(in srgb,var(--green) 60%,transparent);box-shadow:0 0 0 3px color-mix(in srgb,var(--green) 14%,transparent)}
        .terr-rail-card.sel.bajo{border-color:color-mix(in srgb,var(--red) 60%,transparent);box-shadow:0 0 0 3px color-mix(in srgb,var(--red) 14%,transparent)}
        .terr-rail-card.sel.estable{border-color:color-mix(in srgb,var(--amber) 60%,transparent);box-shadow:0 0 0 3px color-mix(in srgb,var(--amber) 14%,transparent)}
        .terr-porque-mini{margin-top:10px;padding:10px 12px;border-radius:10px;font-size:13.5px;line-height:1.45;color:var(--text)}
        .terr-porque-mini span{display:block;font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;margin-bottom:2px}
        .terr-porque-mini.subio{background:var(--green-soft)} .terr-porque-mini.subio span{color:var(--green)}
        .terr-porque-mini.bajo{background:var(--red-soft)} .terr-porque-mini.bajo span{color:var(--red)}
        .terr-porque{font-size:14.5px;line-height:1.5;padding:9px 12px;border-radius:10px;margin:6px 0 4px;color:var(--text)}
        .terr-porque.subio{background:var(--green-soft);border-left:4px solid var(--green)}
        .terr-porque.bajo{background:var(--red-soft);border-left:4px solid var(--red)}
        .terr-total{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:20px 24px;margin:4px 0 12px;
          box-shadow:var(--shadow-sm);display:grid;grid-template-columns:minmax(220px,.8fr) 1.6fr 1.6fr;gap:18px;align-items:center;
          animation:fadeUp .35s ease both}
        .terr-total .cab{display:flex;gap:12px;align-items:center}
        .terr-total .cab>span{width:56px;height:56px;border-radius:14px;display:grid;place-items:center;font-size:26px;font-weight:900;color:#fff}
        .terr-total.subio .cab>span{background:linear-gradient(135deg,#22c55e,#15803d)}
        .terr-total.bajo .cab>span{background:linear-gradient(135deg,#ef4444,#b91c1c)}
        .terr-total .cab b{display:block;font-size:27px;font-family:'Sora','Inter',sans-serif;color:var(--text)}
        .terr-total .cab small{display:block;font-size:12.5px;color:var(--muted)}
        .terr-total .razon span{display:block;font-size:11.5px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
        .terr-total .razon p{margin:4px 0 0;font-size:15px;line-height:1.5;color:var(--text)}
        @media(max-width:1100px){.terr-total{grid-template-columns:1fr}}
        .terr-sem-col{background:var(--panel);border:1px solid var(--line);border-top:5px solid;border-radius:16px;padding:16px 18px;
          box-shadow:var(--shadow-sm);animation:fadeUp .35s ease both;min-height:120px}
        .terr-sem-col.bajo{border-top-color:#ef4444} .terr-sem-col.estable{border-top-color:#eab308} .terr-sem-col.subio{border-top-color:#22c55e}
        .terr-sem-col .cab{display:flex;justify-content:space-between;align-items:center}
        .terr-sem-col .cab span{font-size:14px;font-weight:800;letter-spacing:.04em;color:var(--text)}
        .terr-sem-col .cab b{font-size:32px;font-family:'Sora','Inter',sans-serif}
        .terr-sem-col.bajo .cab b{color:var(--red)} .terr-sem-col.estable .cab b{color:var(--amber)} .terr-sem-col.subio .cab b{color:var(--green)}
        .terr-sem-col .suma{font-size:12.5px;color:var(--muted);margin:-2px 0 6px}
        .terr-sem-col .vacio,.terr-sem-col .mas{font-size:12.5px;color:var(--muted);margin-top:6px}
        .terr-sem-fila{padding:9px 0;border-top:1px dashed var(--line-soft)}
        .terr-sem-fila .l1{display:flex;align-items:baseline;gap:9px;font-size:15px}
        .terr-sem-fila .l1 b{flex:1;min-width:0;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .terr-sem-fila .l1 i{font-style:normal;font-weight:800;font-variant-numeric:tabular-nums;color:var(--text)}
        .terr-sem-fila .l1 em{font-style:normal;font-size:12px;font-weight:800;padding:2px 8px;border-radius:99px}
        .terr-sem-col.bajo em{color:var(--red);background:var(--red-soft)} .terr-sem-col.subio em{color:var(--green);background:var(--green-soft)}
        .terr-sem-col.estable em{color:var(--amber-strong);background:var(--amber-soft)}
        .terr-sem-fila small{display:block;font-size:13px;line-height:1.45;color:var(--muted);margin-top:2px}
        .terr-sem-fila small b{color:var(--text)}
        .terr-deps{margin-top:12px}
        .terr-dep-fila{display:grid;grid-template-columns:14px minmax(140px,1.1fr) 110px 80px 3fr;gap:12px;align-items:center;
          padding:10px 0;border-top:1px dashed var(--line-soft);font-size:15px}
        .terr-dep-fila>i{width:12px;height:12px;border-radius:50%;background:var(--muted)}
        .terr-dep-fila.subio>i{background:#22c55e;box-shadow:0 0 8px #22c55e} .terr-dep-fila.bajo>i{background:#ef4444;box-shadow:0 0 8px #ef4444}
        .terr-dep-fila.estable>i{background:#eab308;box-shadow:0 0 8px #eab308}
        .terr-dep-fila b{color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .terr-dep-fila .cifra{font-weight:800;font-variant-numeric:tabular-nums;text-align:right;color:var(--text)}
        .terr-dep-fila em{font-style:normal;font-size:12px;font-weight:800;text-align:center;padding:1px 6px;border-radius:99px}
        .terr-dep-fila.subio em{color:var(--green);background:var(--green-soft)} .terr-dep-fila.bajo em{color:var(--red);background:var(--red-soft)}
        .terr-dep-fila.estable em{color:var(--amber-strong);background:var(--amber-soft)}
        .terr-dep-fila small{font-size:13.5px;color:var(--muted);line-height:1.4} .terr-dep-fila small b{color:var(--text)}
        @media(max-width:900px){.terr-dep-fila{grid-template-columns:12px 1fr 80px 60px}.terr-dep-fila small{grid-column:2/-1}}

        .terr-desc{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px 18px;margin-bottom:10px;
          box-shadow:var(--shadow-sm)}
        .terr-desc b{display:block;font-size:17px;font-family:'Sora','Inter',sans-serif;color:var(--text);margin-bottom:4px}
        .terr-desc span{font-size:13.5px;color:var(--muted);line-height:1.5}
        .terr-estado{font-size:13.5px;color:var(--muted);margin:4px 2px 8px}
        .terr-estado b{color:var(--text)}
        .terr-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:12px}
        .terr-kpi{background:var(--panel);border:1px solid var(--line);border-top:3px solid var(--teal);border-radius:12px;
          padding:10px 13px;box-shadow:var(--shadow-sm);animation:fadeUp .4s ease both;min-width:0}
        .terr-kpi span{display:block;font-size:10px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}
        .terr-kpi b{display:block;font-size:19px;font-family:'Sora','Inter',sans-serif;color:var(--text);margin-top:3px;
          white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .terr-kpi small{display:block;font-size:11px;color:var(--muted);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .terr-kpi.neg{border-top-color:var(--red)} .terr-kpi.pos{border-top-color:var(--green)} .terr-kpi.oport{border-top-color:#a855f7}
        .terr-kpi.neg small{color:var(--red)} .terr-kpi.pos small{color:var(--green)}

        .terr-lectura{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--teal);
          border-radius:12px;padding:12px 16px;box-shadow:var(--shadow-sm)}
        .terr-lectura ul{margin:0;padding-left:18px}
        .terr-lectura li{font-size:13px;line-height:1.55;margin-bottom:5px;color:var(--text)}
        .terr-ficha{background:var(--panel);border:1px solid var(--line);border-top:4px solid var(--teal);border-radius:16px;
          padding:14px 18px;box-shadow:var(--shadow-md);margin:12px 0;animation:fadeUp .35s ease both}
        .terr-ficha.oport{border-top-color:#a855f7}
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
    if modo == "variacion" and ("tendencia" in tabla.columns or "variacion" in tabla.columns):
        # `tendencia` = variación, o ±100% si la zona apareció o desapareció.
        colores = _SEMAFORO_VAR[0 if fondo_oscuro else 1]
        columna = "tendencia" if "tendencia" in tabla.columns else "variacion"
        cls = [_clase(v, _CORTES_VARIACION) for v in pd.to_numeric(tabla[columna], errors="coerce")]
        cuenta = pd.Series(cls).value_counts()
        textos = ["Bajó más de 20%", "Bajó 5% a 20%", "Estable (±5%)", "Subió 5% a 20%", "Subió más de 20%"]
        leyenda = [(colores[i], f"{textos[i]} · {int(cuenta.get(i, 0))}") for i in range(5)]
        return [colores[c] if c >= 0 else None for c in cls], leyenda[::-1]
    if modo == "meta" and "cumplimiento" in tabla.columns:
        colores = _SEMAFORO[0 if fondo_oscuro else 1]
        cls = [_clase(v, _CORTES_META) for v in pd.to_numeric(tabla["cumplimiento"], errors="coerce")]
        cuenta = pd.Series(cls).value_counts()
        textos = ["Menos de 90% de la meta", "90% a 100%", "Cumple (100% o más)"]
        leyenda = [(colores[i], f"{textos[i]} · {int(cuenta.get(i, 0))}") for i in range(3)]
        return [colores[c] if c >= 0 else None for c in cls], leyenda[::-1]
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
    if "variacion" in t.columns:
        tend = t["tendencia"] if "tendencia" in t.columns else pd.Series(np.nan, index=t.index)
        estado = t["estado"] if "estado" in t.columns else pd.Series(None, index=t.index)

        def _var(x, td, e):
            icono = _ESTADO_ICONO.get(e, "")
            if pd.notna(x):
                return f"{icono} {x:+.0%} vs mes anterior".strip()
            if td == 1:
                return f"{icono} empezó a tener actividad".strip()
            if td == -1:
                return f"{icono} sin actividad en el último mes".strip()
            return "sin dato del mes anterior"
        t["var_txt"] = [_var(x, td, e) for x, td, e in zip(t["variacion"], tend, estado)]
    else:
        t["var_txt"] = ""
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
                 "<div style='font-size:12.5px;font-weight:700;margin-top:2px'>{var_txt}</div>"
                 "<div style='font-size:12px'>{cump_txt}</div>"
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
    # compute_view encuadra para un lienzo chico; el mapa mide ~1100×900 px: se acerca un poco más.
    vista.zoom = min(max(float(vista.zoom) + 0.8, 4.6), 11.5)
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


def _etiquetas_sin_choque(tabla: pd.DataFrame, maximo: int = 10) -> pd.DataFrame:
    """Las zonas que llevan nombre en el mapa, sin que una etiqueta tape a otra.

    Primero las 5 más fuertes y las 3 que más bajaron y más subieron; luego
    el resto por valor. Se descarta la que cae encima de una ya puesta: la
    distancia mínima es una fracción del área que ocupa la red (las
    etiquetas son anchas, así que se pide más separación de este a oeste).
    """
    if tabla.empty:
        return tabla
    orden = list(tabla.head(5).index)
    if "cambio" in tabla.columns:
        orden += list(tabla[tabla["cambio"] < 0].sort_values("cambio").head(3).index)
        orden += list(tabla[tabla["cambio"] > 0].sort_values("cambio", ascending=False).head(3).index)
    orden += list(tabla.head(40).index)
    orden = list(dict.fromkeys(orden))
    # La red ocupa ~600 px del mapa; una etiqueta mide ~26 px de alto y
    # ~170 px de ancho: esa es la distancia mínima, pasada a grados.
    alto = max(float(tabla["lat"].max() - tabla["lat"].min()), float(tabla["lon"].max() - tabla["lon"].min()), 0.6)
    d_lat, d_lon = alto * 26 / 600, alto * 170 / 600
    puestos = {}
    for i in orden:
        la, lo = float(tabla.at[i, "lat"]), float(tabla.at[i, "lon"])
        if all(abs(la - a) > d_lat or abs(lo - b) > d_lon for a, b in puestos.values()):
            puestos[i] = (la, lo)
            if len(puestos) >= maximo:
                break
    return tabla.loc[list(puestos)]


def _construir_mapa(capas_on: dict, zm: pd.DataFrame, zd: pd.DataFrame, hex_t: pd.DataFrame, puntos: pd.DataFrame,
                    crecer: dict, color: str, paleta: str, fondo: str, escala: float, radio_km: float, unidad: str,
                    seleccion: Optional[dict] = None, inclinada: bool = False, ligero: bool = False):
    """El objeto pydeck y las leyendas de cada capa activa.

    `seleccion` = la zona abierta en la ficha: se resalta con un borde neón y
    la vista vuela hacia ella. `inclinada` inclina también las capas planas.
    `ligero` = para el informe HTML: sin los municipios que no tienen dato
    (con todos, el archivo pasa de ~1 a ~5 MB)."""
    import pydeck as pdk
    oscuro = fondo.startswith("Oscuro")
    capas, leyendas = [], {}
    mpios = T.municipios()
    # Bordes finos y claros entre municipios con dato; los que no tienen
    # dato casi desaparecen (antes, 1.122 contornos de color armaban una
    # malla que tapaba el mapa).
    linea = [255, 255, 255, 55] if oscuro else [255, 255, 255, 210]
    linea_vacia = [150, 165, 190, 22] if oscuro else [110, 120, 140, 40]
    sin_dato = [70, 80, 100, 40] if oscuro else [205, 210, 220, 70]
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
                               filled=True, stroked=True, get_fill_color="properties.color", get_line_color=linea_vacia,
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
                if not capas_on.get("poblacion") and not ligero:
                    r = mpios.iloc[i] if i >= 0 else None
                    feats.append(_feature(f["geometry"], {
                        "color": sin_dato, "linea": linea_vacia, "altura": 0, "nombre": r["municipio"] if r is not None else "",
                        "departamento": r["departamento"] if r is not None else "", "zona": str(i), "nivel": "municipio",
                        **_VACIO, "pob_txt": f"{T.cifra(r['poblacion'])} habitantes" if r is not None else ""}))
                continue
            r, c = dato
            feats.append(_feature(f["geometry"], {
                "color": list(c) + [235] if c else sin_dato, "linea": linea, "altura": max(r.valor, 0) / tope * 260_000 * escala,
                "nombre": r.nombre, "departamento": r.departamento, "zona": str(i), "nivel": "municipio",
                "valor_txt": r.valor_txt, "pos_txt": r.pos_txt, "part_txt": r.part_txt, "var_txt": r.var_txt,
                "cump_txt": r.cump_txt, "pob_txt": r.pob_txt, "pen_txt": r.pen_txt, "unidad": unidad}))
        en3d = bool(capas_on.get("mpios3d"))
        capas.append(pdk.Layer("GeoJsonLayer", data={"type": "FeatureCollection", "features": feats}, id="mpios",
                               filled=True, stroked=True, extruded=en3d, wireframe=False,
                               get_elevation="properties.altura", get_fill_color="properties.color",
                               get_line_color="properties.linea", line_width_min_pixels=0.6, pickable=True, auto_highlight=True,
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
                               extruded=True, wireframe=False, get_elevation="properties.altura",
                               get_fill_color="properties.color", get_line_color=linea, line_width_min_pixels=1,
                               pickable=True, auto_highlight=True, highlight_color=[94, 224, 212, 200]))
        vistas_lat += list(t["lat"]); vistas_lon += list(t["lon"])
        inclinacion = max(inclinacion, 48)
    else:
        # Contornos de departamento siempre, con brillo: una línea ancha y
        # transparente debajo de una fina y nítida.
        capas.append(pdk.Layer("GeoJsonLayer", data=T.departamentos_geojson(), id="contornos_brillo", stroked=True,
                               filled=False, get_line_color=linea[:3] + [40 if oscuro else 30],
                               line_width_min_pixels=6, pickable=False))
        capas.append(pdk.Layer("GeoJsonLayer", data=T.departamentos_geojson(), id="contornos", stroked=True,
                               filled=False, get_line_color=([140, 255, 240, 200] if oscuro else [15, 110, 105, 170]),
                               line_width_min_pixels=1.1, pickable=False))

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
        # Violeta: el amarillo es «estable» en el semáforo y se confundían.
        neon = [147, 51, 234] if not oscuro else [192, 132, 252]
        capas.append(pdk.Layer("GeoJsonLayer", data={"type": "FeatureCollection", "features": feats}, id="blancos",
                               filled=True, stroked=True, get_fill_color=neon + [55], get_line_color=neon + [255],
                               line_width_min_pixels=2.5, pickable=True, auto_highlight=True))
        leyendas["blancos"] = [(tuple(neon), f"{len(feats)} municipios grandes sin presencia")]

    # 9) Nombres de las zonas principales.
    if capas_on.get("etiquetas"):
        fuente = zd if (capas_on.get("deptos") and not zd.empty and zm.empty) else zm
        if fuente is not None and not fuente.empty:
            top = _etiquetas_sin_choque(fuente).copy()
            # Sin tildes a propósito: el TextLayer solo trae letras ASCII y
            # pydeck no deja ampliarlas (character_set="auto" no dibuja nada y
            # una lista o un texto de caracteres se interpretan como código).
            # Tooltips, ficha y ranking sí llevan los nombres completos.
            def _var(r):
                v, td = r.get("variacion", np.nan), r.get("tendencia", np.nan)
                if pd.notna(v):
                    return f"  {v:+.0%}"
                return "  nuevo" if td == 1 else "  sin venta" if td == -1 else ""
            top["texto"] = (top["nombre"].map(_sin_tildes) + "  " + top["valor"].map(T.cifra)
                            + top.apply(_var, axis=1))
            # Píldoras con el borde del color del semáforo de la zona.
            neutro = [94, 224, 212, 210] if oscuro else [15, 120, 115, 200]
            estados = top["estado"] if "estado" in top.columns else pd.Series(None, index=top.index)
            top["borde"] = [list(_ESTADO_RGB[e]) + [255] if e in _ESTADO_RGB else neutro for e in estados]
            capas.append(pdk.Layer("TextLayer", data=top[["lon", "lat", "texto", "borde"]], id="etiquetas",
                                   get_position=["lon", "lat"], get_text="texto",
                                   get_size=14, get_color=[236, 241, 246] if oscuro else [19, 24, 38],
                                   get_pixel_offset=[0, -18], billboard=True, background=True,
                                   get_background_color=[13, 18, 28, 230] if oscuro else [255, 255, 255, 240],
                                   background_padding=[8, 4, 8, 4], get_border_color="borde",
                                   get_border_width=2))

    # 10) Focos del mes: anillos sobre las 3 mayores caídas (rojo) y subidas (verde).
    if capas_on.get("focos") and not zm.empty and "cambio" in zm.columns:
        caidas = zm[zm["cambio"] < 0].sort_values("cambio").head(3)
        subidas = zm[zm["cambio"] > 0].sort_values("cambio", ascending=False).head(3)
        focos = pd.concat([caidas.assign(borde=[list(_ESTADO_RGB["bajo"]) + [255]] * len(caidas)),
                           subidas.assign(borde=[list(_ESTADO_RGB["subio"]) + [255]] * len(subidas))])
        if len(focos):
            focos = focos[["lon", "lat", "borde"]].copy()
            focos["brillo"] = [b[:3] + [60] for b in focos["borde"]]
            capas.append(pdk.Layer("ScatterplotLayer", data=focos, id="focos_brillo", get_position=["lon", "lat"],
                                   get_radius=16_000, radius_min_pixels=20, radius_max_pixels=46, filled=False,
                                   stroked=True, get_line_color="brillo", line_width_min_pixels=8, pickable=False))
            capas.append(pdk.Layer("ScatterplotLayer", data=focos, id="focos", get_position=["lon", "lat"],
                                   get_radius=16_000, radius_min_pixels=20, radius_max_pixels=46, filled=False,
                                   stroked=True, get_line_color="borde", line_width_min_pixels=2.5, pickable=False))
            leyendas["focos"] = [(_ESTADO_RGB["subio"], f"{len(subidas)} mayores subidas"),
                                 (_ESTADO_RGB["bajo"], f"{len(caidas)} mayores caídas")]

    # 11) La zona abierta en la ficha: borde neón con brillo y la vista va hacia ella.
    foco = None
    if seleccion:
        geom, nivel_sel = None, seleccion.get("nivel")
        if nivel_sel == "departamento":
            geom = next((f["geometry"] for f in T.departamentos_geojson()["features"]
                         if f["properties"]["cod_dpto"] == str(seleccion.get("zona"))), None)
            d = T.departamentos().set_index("cod_dpto")
            if str(seleccion.get("zona")) in d.index:
                foco = (float(d.loc[str(seleccion["zona"]), "lat"]), float(d.loc[str(seleccion["zona"]), "lon"]), 6.6)
        else:
            try:
                idx = int(float(seleccion.get("zona")))
            except (TypeError, ValueError):
                idx = -1
            geom = next((f["geometry"] for f in T.municipios_geojson()["features"] if f["properties"]["idx"] == idx), None)
            if 0 <= idx < len(mpios):
                foco = (float(mpios.iloc[idx]["lat"]), float(mpios.iloc[idx]["lon"]), 8.4)
        if geom:
            sel = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": geom, "properties": {}}]}
            capas.append(pdk.Layer("GeoJsonLayer", data=sel, id="seleccion_brillo", stroked=True, filled=False,
                                   get_line_color=[94, 224, 212, 70], line_width_min_pixels=12, pickable=False))
            capas.append(pdk.Layer("GeoJsonLayer", data=sel, id="seleccion", stroked=True, filled=True,
                                   get_fill_color=[94, 224, 212, 35], get_line_color=[94, 255, 236, 255],
                                   line_width_min_pixels=2.5, pickable=False))

    if len(capas) <= 1 and not any(capas_on.values()):
        return None, leyendas
    if inclinada and inclinacion == 0:
        inclinacion = 40
    vista = _vista(vistas_lat, vistas_lon, inclinacion)
    if foco:
        vista = pdk.ViewState(latitude=foco[0], longitude=foco[1], zoom=foco[2], pitch=inclinacion,
                              bearing=-12 if inclinacion else 0, transition_duration=900)
    deck = pdk.Deck(layers=capas, initial_view_state=vista,
                    map_style=getattr(pdk.map_styles, _MAPAS.get(fondo, "CARTO_DARK")), map_provider="carto",
                    tooltip=_tooltip(oscuro))
    return deck, leyendas


# ── Piezas de la pantalla ─────────────────────────────────────────────────

def _sin_mes_a_medias(serie: pd.DataFrame, z: dict) -> pd.DataFrame:
    """La serie sin el último mes si va a medias: en un mini-gráfico, el
    día 7 contra un mes completo se ve como un desplome que no existe."""
    if serie is None or serie.empty or not z.get("corte_dia"):
        return serie
    return serie[serie["mes"] != z.get("mes_b")]


def _sparkline(valores, color: str = "#0fa8a0", ancho: int = 170, alto: int = 46) -> str:
    """Mini-gráfico de tendencia en SVG (línea con área degradada y punto final)."""
    v = [float(x) for x in valores if x is not None and np.isfinite(x)]
    if len(v) < 2:
        return ""
    mn, mx = min(v), max(v)
    rango = (mx - mn) or 1.0
    pts = [(2 + i / (len(v) - 1) * (ancho - 6), alto - 4 - (x - mn) / rango * (alto - 10)) for i, x in enumerate(v)]
    linea = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    gid = "sp" + str(abs(hash((tuple(v), color))) % 10 ** 8)
    return (f'<svg class="terr-spark" width="{ancho}" height="{alto}" viewBox="0 0 {ancho} {alto}">'
            f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{color}" stop-opacity=".35"/>'
            f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
            f'<polygon points="2,{alto} {linea} {ancho - 4},{alto}" fill="url(#{gid})"/>'
            f'<polyline points="{linea}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>'
            f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="3.2" fill="{color}"/></svg>')


def _anillo(fraccion, color: str = "#0fa8a0", tam: int = 60) -> str:
    """Anillo de progreso con el porcentaje en el centro."""
    f = max(0.0, min(1.0, float(fraccion or 0)))
    r = tam / 2 - 5
    largo = 2 * math.pi * r
    return (f'<svg width="{tam}" height="{tam}" viewBox="0 0 {tam} {tam}" class="terr-anillo">'
            f'<circle cx="{tam / 2}" cy="{tam / 2}" r="{r}" fill="none" stroke="var(--line)" stroke-width="5"/>'
            f'<circle cx="{tam / 2}" cy="{tam / 2}" r="{r}" fill="none" stroke="{color}" stroke-width="5" stroke-linecap="round" '
            f'stroke-dasharray="{largo * f:.1f} {largo:.1f}" transform="rotate(-90 {tam / 2} {tam / 2})"/>'
            f'<text x="50%" y="54%" text-anchor="middle" font-size="14" font-weight="800" fill="var(--text)">{f:.0%}</text></svg>')


def _barra_semaforo(sem: dict) -> str:
    """Barra apilada rojo · amarillo · verde con la proporción de zonas."""
    total = sum(sem[k]["n"] for k in ("bajo", "estable", "subio")) or 1
    return '<div class="terr-sem-barra">' + "".join(
        f'<i class="{k}" style="width:{sem[k]["n"] / total * 100:.1f}%"></i>'
        for k in ("bajo", "estable", "subio") if sem[k]["n"]) + "</div>"


def _cuando(z: dict) -> str:
    """«sep 2026» o «sep 2026 al día 7» si el mes va a medias."""
    return T.etiqueta_mes(z.get("mes_b"), True) + (f" al día {z['corte_dia']}" if z.get("corte_dia") else "")


def _hud(z: dict, serie: pd.DataFrame, metrica_label: str, cob: dict) -> str:
    """La barra de indicadores sobre el mapa."""
    tabla = z["tabla"]
    tiles = []
    delta = ""
    ta, tb = z.get("total_a"), z.get("total_b")
    if ta and tb is not None and np.isfinite(ta) and np.isfinite(tb):
        # Los dos totales salen de `zonas`, con el mismo corte de día: un mes
        # a medias no se muestra como una caída.
        cambio = (tb - ta) / abs(ta)
        delta = (f'<span class="terr-delta {"pos" if cambio >= 0 else "neg"}">{"▲" if cambio >= 0 else "▼"} '
                 f'{abs(cambio):.1%} <small>{html.escape(_cuando(z))}</small></span>')
    tiles.append(("principal", f"{'Total' if z.get('sumable') else 'Promedio'} · {metrica_label}", T.cifra(z["total"]),
                  delta, _sparkline(_sin_mes_a_medias(serie, z)["valor"], ancho=124, alto=42) if len(serie) >= 3 else ""))
    sem = T.semaforo(z)
    if sem:
        cuerpo = (f'<div class="terr-sem-cuenta"><span class="subio">▲ {sem["subio"]["n"]}</span>'
                  f'<span class="estable">● {sem["estable"]["n"]}</span><span class="bajo">▼ {sem["bajo"]["n"]}</span></div>'
                  + _barra_semaforo(sem))
        tiles.append(("sem", f"Semáforo · {_cuando(z)}", cuerpo, f"subieron · estables · bajaron, de {z['n']:,} zonas", ""))
    else:
        tiles.append(("", "Zonas con actividad", f"{z['n']:,}",
                      f"de {cob['municipios_deptos']:,} municipios de tus departamentos" if cob else "", ""))
    if len(tabla):
        lider = tabla.iloc[0]
        part = f"{lider['participacion']:.0%} del total" if pd.notna(lider.get("participacion")) else T.cifra(lider["valor"])
        tiles.append(("", "Zona líder", str(lider["nombre"]), part, ""))
    if "cambio" in tabla.columns and z.get("mes_a"):
        lineas = []
        sube = tabla[tabla["cambio"] > 0].sort_values("cambio", ascending=False).head(1)
        baja = tabla[tabla["cambio"] < 0].sort_values("cambio").head(1)
        for clase, flecha, fila in (("subio", "▲", sube), ("bajo", "▼", baja)):
            if len(fila):
                r = fila.iloc[0]
                lineas.append(f'<div class="terr-mov {clase}"><em>{flecha}</em><b title="{html.escape(str(r["nombre"]))}">'
                              f'{html.escape(str(r["nombre"]))}</b><i>{T.cifra_signo(r["cambio"])}</i></div>')
        if lineas:
            tiles.append(("mov", f"Mayores movimientos · {_cuando(z)}", "".join(lineas), "", ""))
    if cob and cob.get("pct_deptos") is not None:
        tiles.append(("anillo", "Cobertura de población", _anillo(cob["pct_deptos"]),
                      "de la gente de tus departamentos vive donde ya estás", ""))
    partes = []
    for clase, etiqueta, valor, sub, extra in tiles:
        crudo = clase in {"anillo", "sem", "mov"}
        cuerpo = valor if crudo else f'<b title="{html.escape(valor)}">{html.escape(valor)}</b>'
        sub_html = sub if sub.startswith("<span") else (f"<small>{html.escape(sub)}</small>" if sub else "")
        partes.append(f'<div class="terr-hud-tile {clase}"><span>{html.escape(etiqueta)}</span>'
                      f'<div class="fila">{cuerpo}{extra}</div>{sub_html}</div>')
    return '<div class="terr-hud">' + "".join(partes) + "</div>"


def _firma_mapa() -> Optional[tuple]:
    """(capa, zona, nivel) del objeto elegido hoy en el mapa, o None."""
    estado = st.session_state.get("territorial_deck")
    seleccion = getattr(estado, "selection", None)
    if seleccion is None and isinstance(estado, dict):
        seleccion = estado.get("selection")
    try:
        objetos = (seleccion.get("objects") if seleccion else None) or {}
    except Exception:
        return None
    for capa in ("mpios", "zonas", "deptos", "blancos", "poblacion"):
        elegido = (objetos.get(capa) or [None])[0]
        if elegido:
            props = elegido.get("properties", elegido)
            return capa, str(props.get("zona")), props.get("nivel")
    return None


def _leer_clic(nivel_mpio: str) -> None:
    """Toma el clic del mapa ANTES de dibujarlo, para que el resaltado y el
    vuelo a la zona salgan en esa misma vuelta. Un clic ya atendido (la
    selección queda guardada en el widget) no se vuelve a aplicar: si no,
    cerrar la ficha la reabría en el acto."""
    firma = _firma_mapa()
    if firma and st.session_state.get("_territorial_firma") != firma:
        st.session_state["_territorial_firma"] = firma
        capa, zona, nivel = firma
        st.session_state["territorial_zona_sel"] = {"zona": zona, "nivel": nivel or (
            "departamento" if capa == "deptos" else nivel_mpio)}


def _cerrar_seleccion() -> None:
    st.session_state.pop("territorial_zona_sel", None)
    st.session_state["_territorial_firma"] = _firma_mapa()


def _ir_a(opciones: dict) -> None:
    elegido = st.session_state.get("territorial_ir_a")
    if elegido in opciones:
        st.session_state["territorial_zona_sel"] = opciones[elegido]


def _riel(z: dict, colores: list, seleccion: Optional[dict], zm: dict, zd: dict, ub, metrica, calculo, fecha_col,
          crecer: dict, nivel_mpio: str, dims_neg: list, etiquetas: dict):
    """El riel derecho: zona abierta, ir a una zona, Top 10 y alertas."""
    tabla = z["tabla"]
    # 1) La zona abierta, en corto.
    if seleccion:
        z_sel = zd if seleccion.get("nivel") == "departamento" else zm
        t = z_sel["tabla"]
        fila = pd.DataFrame()
        if not t.empty:
            if seleccion.get("nivel") == "departamento":
                fila = t[t["zona"].astype(str) == str(seleccion["zona"])]
            else:
                fila = t[pd.to_numeric(t["zona"], errors="coerce") == pd.to_numeric(seleccion["zona"], errors="coerce")]
        if len(fila):
            f = fila.iloc[0]
            es_depto = seleccion.get("nivel") == "departamento"
            clave = seleccion["zona"] if es_depto else int(float(seleccion["zona"]))
            serie = T.serie_zona(ub, clave, "departamento" if es_depto else nivel_mpio,
                                 None if metrica == _CONTEO else metrica, calculo, fecha_col)
            datos = [("Valor", T.cifra(f["valor"])), ("Posición", f"{int(f['posicion'])}.º de {z_sel['n']}")]
            if pd.notna(f.get("variacion", np.nan)):
                datos.append(("Vs mes anterior", f"{f['variacion']:+.0%}"))
            if pd.notna(f.get("cumplimiento", np.nan)):
                datos.append(("Meta", f"{f['cumplimiento']:.0%}"))
            if pd.notna(f.get("por_10k", np.nan)):
                datos.append(("Por 10.000 hab.", T.cifra(f["por_10k"])))
            mot = T.motivos(ub, None if metrica == _CONTEO else metrica, calculo, fecha_col, z_sel, dims_neg,
                            zona=clave, nivel="departamento" if es_depto else nivel_mpio, geografia=es_depto)
            porque = ""
            if mot:
                sube = mot["delta"] > 0
                porque = (f'<div class="terr-porque-mini {"subio" if sube else "bajo"}"><span>¿Por qué '
                          f'{"subió" if sube else "bajó"}? {T.cifra_signo(mot["delta"])}</span>'
                          f'{_negritas(T.frase_motivo(mot, etiquetas.get(mot["dimension"], mot["dimension"]), corta=True))}</div>')
            estado = f.get("estado") if f.get("estado") in _ESTADO_ICONO else None
            st.markdown(
                f'<div class="terr-rail-card sel {estado or ""}"><span class="eyebrow">Zona seleccionada'
                + (f' · {_ESTADO_ICONO[estado]} {dict(subio="subió", estable="estable", bajo="bajó")[estado]}' if estado in _ESTADO_ICONO else "")
                + f'</span><h4>{html.escape(str(f["nombre"]))}</h4><div class="sub">{html.escape(str(f.get("departamento", "")))}</div>'
                + (_sparkline(_sin_mes_a_medias(serie, z_sel)["zona"], ancho=320, alto=60) if len(serie) >= 3 else "")
                + '<div class="terr-mini">' + "".join(f"<div><span>{html.escape(a)}</span><b>{html.escape(b)}</b></div>"
                                                      for a, b in datos)
                + "</div>" + porque + '<div class="pista">La ficha completa está debajo del mapa ↓</div></div>',
                unsafe_allow_html=True)
        else:
            m = T.municipios()
            try:
                r = m.iloc[int(float(seleccion["zona"]))]
                st.markdown(
                    f'<div class="terr-rail-card sel oport"><span class="eyebrow">Sin actividad · oportunidad</span>'
                    f'<h4>{html.escape(str(r["municipio"]))}</h4><div class="sub">{html.escape(str(r["departamento"]))}</div>'
                    f'<div class="terr-mini"><div><span>Población</span><b>{T.cifra(r["poblacion"])}</b></div>'
                    f'<div><span>Urbana</span><b>{T.cifra(r["poblacion_cabecera"])}</b></div></div></div>',
                    unsafe_allow_html=True)
            except Exception:
                pass
        st.button("✕ Cerrar selección", key="territorial_cerrar_riel", on_click=_cerrar_seleccion,
                  use_container_width=True)

    # 2) Abrir cualquier zona sin buscarla en el mapa.
    if not tabla.empty:
        nivel_t = "departamento" if z.get("nivel") == "departamento" else nivel_mpio
        opciones = {f"{int(r.posicion)}. {r.nombre}": {"zona": str(r.zona), "nivel": nivel_t}
                    for r in tabla.head(300).itertuples()}
        st.selectbox("Ir a una zona", ["—"] + list(opciones), key="territorial_ir_a", on_change=_ir_a, args=(opciones,),
                     help="Abre la ficha de una zona y el mapa vuela hacia ella.")

    # 3) Top 10 con barras del mismo color que el mapa.
    if not tabla.empty:
        top = tabla.head(10)
        tope = float(top["valor"].abs().max()) or 1.0
        filas = []
        for k, r in enumerate(top.itertuples()):
            c = colores[k] if k < len(colores) and colores[k] else (15, 168, 160)
            var = ""
            if "variacion" in tabla.columns and pd.notna(getattr(r, "variacion", np.nan)):
                var = (f'<em class="{"pos" if r.variacion >= 0 else "neg"}">{"▲" if r.variacion >= 0 else "▼"}'
                       f'{abs(r.variacion):.0%}</em>')
            filas.append(f'<div class="terr-top-fila"><span class="num">{int(r.posicion)}</span>'
                         f'<div class="cuerpo"><div class="nom"><b>{html.escape(str(r.nombre))}</b><i>{T.cifra(r.valor)}</i>{var}</div>'
                         f'<div class="barra"><u style="width:{max(abs(r.valor) / tope * 100, 3):.1f}%;'
                         f'background:rgb{tuple(c)}"></u></div></div></div>')
        st.markdown(f'<div class="terr-rail-card"><span class="eyebrow">Top 10 de {z["n"]}</span>'
                    + "".join(filas) + "</div>", unsafe_allow_html=True)

    # 4) Alertas del territorio.
    alertas = []
    if "cambio" in tabla.columns and z.get("mes_a"):
        for r in tabla[(tabla["variacion"] <= -0.2)].sort_values("cambio").head(2).itertuples():
            alertas.append(("neg", f"{r.nombre} cayó {abs(r.variacion):.0%}",
                            f"{T.cifra(r.cambio)} en {T.etiqueta_mes(z['mes_b'])}"))
    if "cumplimiento" in tabla.columns and tabla["cumplimiento"].notna().sum() >= 2:
        bajo = tabla[tabla["cumplimiento"] < 0.9]
        if len(bajo):
            alertas.append(("warn", f"{len(bajo)} de {int(tabla['cumplimiento'].notna().sum())} bajo el 90% de su meta",
                            ", ".join(bajo.sort_values("cumplimiento")["nombre"].astype(str).head(3))))
    blancos = crecer.get("blancos") if crecer else None
    if blancos is not None and len(blancos):
        b = blancos.iloc[0]
        alertas.append(("oport", f"{b['municipio']} sin presencia",
                        f"{T.cifra(b['poblacion'])} habitantes · potencial {T.cifra(b['potencial'])}"))
    if alertas:
        st.markdown('<div class="terr-rail-card"><span class="eyebrow">Alertas del territorio</span>' + "".join(
            f'<div class="terr-alerta {t}"><b>{html.escape(a)}</b><small>{html.escape(d)}</small></div>'
            for t, a, d in alertas) + "</div>", unsafe_allow_html=True)


def _negritas(texto: str) -> str:
    partes = html.escape(texto).split("**")
    return "".join(f"<b>{p}</b>" if i % 2 else p for i, p in enumerate(partes))


def _var_txt(v, td) -> str:
    """+12% · «nuevo» si empezó a tener actividad · «sin actividad» si dejó de tenerla."""
    if v is not None and pd.notna(v):
        return f"{v:+.0%}"
    return "nuevo" if td == 1 else "sin actividad" if td == -1 else ""


def _var_corta(r) -> str:
    return _var_txt(getattr(r, "variacion", np.nan), getattr(r, "tendencia", np.nan))


def _tablero_semaforo(inf: dict) -> None:
    """🚦 Qué pasó en el territorio: el total, quién subió, quién bajó y por qué.

    Todo sale de `core/territorio.informe` (lo mismo que llevan el Excel y
    el HTML): en cada zona, la columna que concentra el movimiento (canal,
    asesor, producto… o el municipio, dentro de un departamento)."""
    sem = inf["semaforo"]
    if not sem:
        return
    nivel_z = inf["nivel"]
    zona_txt = "departamentos" if nivel_z == "departamento" else "municipios" if nivel_z == "municipio" else "zonas"
    st.markdown(f'<div class="terr-label">🚦 Semáforo del territorio · qué subió, qué bajó y por qué</div>'
                f'<div class="terr-estado">{html.escape(inf["comparacion"])}. Verde: subió más de 5% · amarillo: se mantuvo '
                f'(±5%) · rojo: bajó más de 5%.</div>', unsafe_allow_html=True)

    # 1) El total, por dónde y por qué.
    ct = inf["cambio_total"]
    if ct and inf["sumable"]:
        sube = ct["delta"] >= 0
        pct = f" ({ct['pct']:+.1%})" if ct["pct"] is not None else ""
        puntos = [(t, inf[c]["frase"]) for t, c in (("📍 Por dónde", "por_donde"), ("🔎 Por qué", "por_que")) if inf.get(c)]
        st.markdown(
            f'<div class="terr-total {"subio" if sube else "bajo"}"><div class="cab"><span>{"▲" if sube else "▼"}</span>'
            f'<div><small>Total de {html.escape(inf["metrica"].lower())}</small><b>{"Subió" if sube else "Bajó"} '
            f'{T.cifra(abs(ct["delta"]))}{pct}</b><small>{T.cifra(ct["antes"])} → {T.cifra(ct["ahora"])}</small></div></div>'
            + "".join(f'<div class="razon"><span>{a}</span><p>{_negritas(b)}</p></div>' for a, b in puntos)
            + "</div>", unsafe_allow_html=True)

    # 2) Rojo · amarillo · verde, con la razón de los que más se movieron.
    columnas = st.columns(3, gap="small")
    for col, clave, titulo in zip(columnas, ("bajo", "estable", "subio"), ("Bajaron", "Se mantuvieron (±5%)", "Subieron")):
        parte = sem[clave]
        filas = []
        for r in parte["tabla"].head(6).itertuples():
            razon = inf["razones"].get(str(r.zona), {}).get("frase", "") if clave != "estable" else ""
            filas.append(f'<div class="terr-sem-fila"><div class="l1"><b title="{html.escape(str(r.nombre))}">'
                         f'{html.escape(str(r.nombre))}</b><i>{T.cifra_signo(getattr(r, "cambio", np.nan))}</i>'
                         f'<em>{_var_corta(r)}</em></div>' + (f"<small>{_negritas(razon)}</small>" if razon else "") + "</div>")
        resto = parte["n"] - len(filas)
        with col:
            st.markdown(
                f'<div class="terr-sem-col {clave}"><div class="cab"><span>{_ESTADO_ICONO[clave]} {titulo}</span>'
                f'<b>{parte["n"]}</b></div><div class="suma">{T.cifra_signo(parte["cambio"])} entre los {parte["n"]} '
                f'{zona_txt}</div>'
                + ("".join(filas) if filas else '<div class="vacio">Ninguna zona en este grupo.</div>')
                + (f'<div class="mas">y {resto} más en el ranking ↓</div>' if resto > 0 else "") + "</div>",
                unsafe_allow_html=True)

    # 3) Por departamento: qué municipios lo empujaron.
    if inf["departamentos"]:
        filas = [f'<div class="terr-dep-fila {d["estado"] or ""}"><i></i><b>{html.escape(d["nombre"])}</b>'
                 f'<span class="cifra">{T.cifra_signo(d["cambio"])}</span>'
                 f'<em>{_var_txt(d["variacion"], d["tendencia"])}</em>'
                 f'<small>{_negritas(d["frase"]) if d["frase"] else "&nbsp;"}</small></div>' for d in inf["departamentos"]]
        st.markdown(f'<div class="terr-rail-card terr-deps"><span class="eyebrow">Por departamento · qué municipios '
                    f'lo empujaron (de {inf.get("n_departamentos", len(filas))} departamentos)</span>' + "".join(filas)
                    + "</div>", unsafe_allow_html=True)


def _descargas(ub, metrica, calculo, fecha_col, z: dict, zd: dict, dims_neg: list, etiquetas: dict, crecer: dict,
               cob: dict, metrica_label: str, archivo: str, hoja: str, filtros: dict, registros: int,
               serie_total: pd.DataFrame, mapa) -> None:
    """📥 El análisis para enviar: Excel ejecutivo y HTML con el mapa.

    Se arman a pedido (dos pasos, `ui/components/descarga`): el informe
    calcula la razón de muchas zonas y el HTML lleva el mapa entero, así que
    no se hace en cada clic de la pantalla. Llevan los filtros, el periodo y
    las capas que estén puestos al momento de prepararlos."""
    filtros_txt = "; ".join(f"{etiquetas.get(k, k)}: {', '.join(map(str, v.get('value', [])))}" for k, v in filtros.items())
    firma = (archivo, hoja, metrica_label, calculo, z.get("mes_b"), z.get("n"), round(float(z.get("total") or 0), 4),
             filtros_txt, tuple(dims_neg))
    ctx = {"archivo": archivo, "hoja": hoja, "registros": registros, "filtros": filtros_txt}

    def _informe():
        # Para el archivo, la razón de hasta 150 subidas y 150 caídas y todos los departamentos.
        return T.informe(ub, metrica, calculo, fecha_col, z, zd, dims_neg, etiquetas, crecer, cob, metrica_label,
                         max_razones=150)

    st.markdown('<div class="terr-label">📥 Descargar el análisis para enviarlo</div>', unsafe_allow_html=True)
    a, b = st.columns(2, gap="medium")
    with a:
        st.markdown('<div class="terr-desc"><b>📊 Excel ejecutivo</b><span>Resumen con indicadores, semáforo, por qué subió o '
                    'bajó y gráficos · todas las zonas con su razón (con filtros) · departamentos · mes a mes · dónde '
                    'crecer · notas de cálculo.</span></div>', unsafe_allow_html=True)
        preparar_y_descargar(
            "territorial_desc_xlsx", firma,
            lambda: build_territorial_excel(_informe(), ctx, serie_total, T.mes_a_mes(
                ub, metrica, calculo, fecha_col, "departamento" if z.get("nivel") == "departamento" else z.get("nivel", "municipio"))),
            nombre_archivo(hoja or archivo, "xlsx"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            preparar="⚙️ Preparar Excel", descargar="⬇️ Descargar Excel", primario=True,
            ayuda="Arma el libro con los filtros y el periodo actuales.")
    with b:
        st.markdown('<div class="terr-desc"><b>🌐 Informe HTML con mapa</b><span>Una página que se abre en cualquier navegador '
                    'y se puede reenviar o imprimir a PDF: el mapa interactivo como lo ves ahora, el semáforo, las razones, '
                    'la tabla completa con buscador y la evolución.</span></div>', unsafe_allow_html=True)
        preparar_y_descargar(
            "territorial_desc_html", firma + (str(st.session_state.get("territorial_color")),
                                             str(st.session_state.get("territorial_paleta")),
                                             str(st.session_state.get("territorial_mapa_fondo"))),
            lambda: build_territorial_html(_informe(), ctx, serie_total, mapa()),
            nombre_archivo(hoja or archivo, "html"), "text/html",
            preparar="⚙️ Preparar informe HTML", descargar="⬇️ Descargar informe HTML",
            ayuda="Incluye el mapa con las capas, el color y el fondo que tienes puestos.")


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


def _ficha(ub, zona_sel: dict, z: dict, crecer: dict, metrica, metrica_label, calculo, fecha_col, dims,
          dims_neg: list = (), etiquetas: Optional[dict] = None):
    """Lo que se abre al hacer clic en una zona del mapa."""
    import plotly.graph_objects as go
    from visualization.charts import chart_muted_color, chart_text_color
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
                x = [T.etiqueta_mes(m, True) for m in serie["mes"]]
                medias = bool(z.get("corte_dia")) and serie["mes"].iloc[-1] == z.get("mes_b")
                completos = slice(None, -1) if medias else slice(None)
                fig.add_scatter(x=x[completos], y=serie["zona"].iloc[completos], mode="lines+markers",
                                name=str(f["nombre"]), line=dict(color="#0fa8a0", width=3), marker=dict(size=8))
                fig.add_scatter(x=x[completos], y=serie["promedio"].iloc[completos], mode="lines",
                                name=f"Promedio de las {z['n']} zonas", line=dict(color="#9aa4b2", width=2, dash="dash"))
                if medias:
                    # El mes en curso va aparte, punteado y rotulado: hasta el día N
                    # no es comparable con un mes completo.
                    fig.add_scatter(x=x[-2:], y=serie["zona"].iloc[-2:], mode="lines+markers", showlegend=False,
                                    line=dict(color="#0fa8a0", width=2, dash="dot"),
                                    marker=dict(size=[0, 9], symbol="circle-open", line=dict(width=2)), hoverinfo="skip")
                    fig.add_annotation(x=x[-1], y=float(serie["zona"].iloc[-1]), text=f"al día {z['corte_dia']}",
                                       showarrow=False, yshift=14, font=dict(size=11, color="#f0a63e"))
                fig.update_layout(height=310, margin=dict(l=10, r=10, t=58, b=48), legend=dict(orientation="h", y=1.02, yanchor="bottom"),
                                  title=dict(text="Evolución frente al promedio de todas las zonas",
                                             font=dict(size=13, color=chart_text_color())),
                                  paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                  font=dict(color=chart_text_color()), legend_font_color=chart_muted_color())
                fig.update_xaxes(tickfont=dict(color=chart_muted_color()))
                fig.update_yaxes(tickformat="~s", tickfont=dict(color=chart_muted_color()))
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key="territorial_ficha_serie")
            else:
                st.caption("Sin varios meses de datos para dibujar la evolución de esta zona.")
        with der:
            mot = T.motivos(ub, None if metrica == _CONTEO else metrica, calculo, fecha_col, z, list(dims_neg),
                            zona=clave, nivel=nivel, geografia=nivel == "departamento")
            if mot:
                etiqueta = (etiquetas or {}).get(mot["dimension"], mot["dimension"])
                sube = mot["delta"] > 0
                mov = mot["movimiento"]
                mov = mov.loc[mov["delta"].abs().sort_values(ascending=False).head(8).index].sort_values("delta")
                st.markdown(f'<div class="terr-porque {"subio" if sube else "bajo"}"><b>¿Por qué {"subió" if sube else "bajó"} '
                            f'{T.cifra_signo(mot["delta"])}?</b> {_negritas(T.frase_motivo(mot, etiqueta))}.</div>',
                            unsafe_allow_html=True)
                fig = go.Figure(go.Bar(
                    x=mov["delta"], y=[str(i) for i in mov.index], orientation="h",
                    marker_color=["#22c55e" if d > 0 else "#ef4444" for d in mov["delta"]],
                    text=[T.cifra_signo(d) for d in mov["delta"]], textposition="outside", cliponaxis=False,
                    hovertemplate="%{y}: %{x:,.0f}<extra></extra>"))
                fig.update_layout(height=110 + 30 * len(mov), margin=dict(l=10, r=10, t=34, b=48), showlegend=False,
                                  title=dict(text=f"Cambio por {etiqueta.lower()} · {T.etiqueta_mes(z['mes_b'], True)} vs "
                                                  f"{T.etiqueta_mes(z['mes_a'], True)}",
                                             font=dict(size=13, color=chart_text_color())),
                                  paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                  font=dict(color=chart_text_color()))
                fig.update_yaxes(tickfont=dict(color=chart_text_color()))
                # Aire a los dos lados para que la cifra de cada barra no pise los nombres.
                lo, hi = min(float(mov["delta"].min()), 0.0), max(float(mov["delta"].max()), 0.0)
                pad = (hi - lo) * 0.3 or 1.0
                fig.update_xaxes(tickformat="~s", zeroline=True, zerolinecolor="#9aa4b2", tickfont=dict(color=chart_muted_color()),
                                 range=[lo - (pad if lo < 0 else 0), hi + (pad if hi > 0 else 0)])
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key="territorial_ficha_porque")
            en_zona = ub[ub["_t_ok"]]
            en_zona = en_zona[(en_zona["_t_cod_dpto"] == clave) if nivel == "departamento"
                              else (en_zona["_t_idx"] == int(float(clave)))]
            for dim in list(dims_neg or dims)[:1 if mot else 2]:
                if dim not in en_zona.columns:
                    continue
                valores = en_zona.assign(_v=1.0 if metrica == _CONTEO else pd.to_numeric(en_zona[metrica], errors="coerce"))
                top = valores.groupby(dim)["_v"].sum().sort_values(ascending=False).head(6)
                if len(top) >= 2:
                    st.markdown(f"**Por {html.escape(str(dim)).lower()}**")
                    st.dataframe(top.rename(metrica_label).reset_index(), hide_index=True, use_container_width=True,
                                 column_config={metrica_label: st.column_config.ProgressColumn(
                                     format="%.0f", min_value=0, max_value=float(top.max()))})
    st.button("✕ Cerrar ficha", key="territorial_cerrar_ficha", on_click=_cerrar_seleccion)


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
    ("focos", "Focos del mes", "Anillos sobre las 3 zonas que más subieron (verde) y más bajaron (rojo).", "Tu archivo", "dato"),
    ("etiquetas", "Nombres de las zonas", "Las zonas clave con su cifra y su variación; el borde lleva el color del semáforo.",
     "Tu archivo", "dato"),
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
        panel, principal, riel = st.columns([320, 1100, 360], gap="medium")

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
        etiquetas = {d: _label(schema, d) for d in dims}
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

    # Las razones de cada subida o caída se buscan en las columnas de negocio
    # (canal, asesor, producto…), no en la del lugar: dentro de un municipio
    # la columna «Ciudad» vale lo mismo en todas las filas.
    import re
    dims_neg = [d for d in dims if d != meta.get("columna")
                and not re.search(r"depart|municip|ciudad|latit|longit|coord", str(d), re.I)]

    disponibles = {"mpios": por_municipio, "columnas": por_municipio, "deptos": en_colombia, "hex": con_coordenadas,
                   "calor": True, "puntos": con_coordenadas, "poblacion": True, "blancos": por_municipio,
                   "focos": (por_municipio or con_coordenadas) and len(meses) >= 2, "etiquetas": True}
    por_defecto = ({"hex", "focos", "etiquetas"} if con_coordenadas else {"mpios", "blancos", "focos", "etiquetas"}
                   if por_municipio else {"deptos", "etiquetas"})

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
        # El semáforo va primero: es la lectura que pide un gerente.
        colores = (["variacion"] if len(meses) >= 2 else []) + (["meta"] if meta_col else []) + ["volumen"] \
            + (["penetracion"] if en_colombia and calculo in {"Suma", "Conteo"} else [])
        color = st.selectbox("Color según", colores, key="territorial_color", format_func=_COLORES.get,
                             help="La altura siempre es el volumen; el color dice su estado. Semáforo: verde subió "
                                  "más de 5%, amarillo se mantuvo (±5%), rojo bajó más de 5%.")
        paleta = st.selectbox("Paleta", list(_PALETAS), key="territorial_paleta",
                              help="Cada paleta se ajusta sola al fondo: de oscuro a brillante sobre fondo oscuro, "
                                   "de claro a intenso sobre fondo claro.")
        opciones_fondo = list(_MAPAS)
        if st.session_state.get("territorial_mapa_fondo") not in opciones_fondo:
            st.session_state["territorial_mapa_fondo"] = "Oscuro" if _oscuro() else "Claro"
        fondo = st.selectbox("Fondo del mapa", opciones_fondo, key="territorial_mapa_fondo")
        inclinada = st.toggle("Vista inclinada", key="territorial_inclinada",
                              help="Inclina el mapa aunque las capas sean planas: da profundidad.")
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

    # El clic se atiende antes de dibujar: así el mapa ya sale resaltado y
    # centrado en la zona elegida.
    _leer_clic(nivel_mpio)
    seleccion = st.session_state.get("territorial_zona_sel")

    def _dibujar(mes, clave_evento: Optional[str], leyendas_panel: bool = True):
        zm_m, zd_m = (zm, zd) if mes == periodo else _calcular(mes)
        hex_t = T.hexagonos(ub, metrica_calc, calculo, radio_km, fecha_col, mes) if capas_on.get("hex") else pd.DataFrame()
        deck, leyendas = _construir_mapa(capas_on, zm_m["tabla"], zd_m["tabla"], hex_t,
                                         _puntos(mes) if (capas_on.get("calor") or capas_on.get("puntos")) else pd.DataFrame(),
                                         crecer, color, paleta, fondo, escala, radio_km, metrica_label,
                                         seleccion=seleccion if clave_evento else None, inclinada=inclinada)
        # Desde la animación (un fragmento) no se puede escribir en el panel,
        # que está fuera de él: las leyendas se quedan como estaban.
        if leyendas_panel:
            for clave, hueco in huecos.items():
                hueco.markdown(_ley_html(leyendas.get(clave, [])) if capas_on.get(clave) else "", unsafe_allow_html=True)
        etiqueta = T.etiqueta_mes(mes) if mes else (
            f"Todo el periodo · {T.etiqueta_mes(meses[0], True)} – {T.etiqueta_mes(meses[-1], True)}" if meses else "Todos los registros")
        z_m = zd_m if solo_departamento else zm_m
        sem = T.semaforo(z_m)
        if sem:
            derecha = (f'<span class="terr-sem-chip subio">▲ {sem["subio"]["n"]} subieron</span>'
                       f'<span class="terr-sem-chip estable">● {sem["estable"]["n"]} estables</span>'
                       f'<span class="terr-sem-chip bajo">▼ {sem["bajo"]["n"]} bajaron</span>')
        else:
            derecha = "".join(f'<span class="terr-chip dato">{html.escape(t)}</span>'
                              for c, t, *_ in _CAPAS if capas_on.get(c))
        corte = ""
        if z_m.get("corte_dia"):
            corte = (f'<span class="corte">⏱ {html.escape(T.etiqueta_mes(z_m["mes_b"]).capitalize())} va hasta el día '
                     f'{z_m["corte_dia"]}: se compara con {html.escape(T.etiqueta_mes(z_m["mes_a"]))} hasta ese mismo día.</span>')
        elif sem:
            corte = (f'<span class="corte suave">Semáforo: {html.escape(T.etiqueta_mes(z_m["mes_b"], True))} frente a '
                     f'{html.escape(T.etiqueta_mes(z_m["mes_a"], True))}</span>')
        st.markdown(f'<div class="terr-mapa-head"><div><b>{html.escape(metrica_label)} · {html.escape(_COLORES[color])}</b><br>'
                    f'<span class="per">{html.escape(etiqueta)}</span>{corte}</div><div class="capas">{derecha}</div></div>',
                    unsafe_allow_html=True)
        if deck is None:
            st.info("Prende al menos una capa en el panel de la izquierda.")
            return None
        if clave_evento:
            return st.pydeck_chart(deck, height=_ALTO_MAPA, use_container_width=True, on_select="rerun",
                                   selection_mode="single-object", key=clave_evento)
        st.pydeck_chart(deck, height=_ALTO_MAPA, use_container_width=True)
        return None

    with principal:
        origen = {"coordenadas": f"las coordenadas ({meta['columna']})", "municipio": f"la columna «{meta['columna']}»",
                  "departamento": f"la columna «{meta['columna']}» (nivel departamento)",
                  "texto": f"el municipio escrito en «{meta['columna']}»"}.get(meta["origen"], "")
        st.markdown(f'<div class="terr-estado">📍 Ubicados <b>{meta["ubicadas"]:,} de {meta["total"]:,}</b> registros '
                    f'a partir de {html.escape(origen)}.</div>', unsafe_allow_html=True)
        st.markdown(_hud(z if not z["tabla"].empty else zm, T.serie_total(ub, metrica_calc, calculo, fecha_col),
                         metrica_label, cob), unsafe_allow_html=True)
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
            _dibujar(periodo, "territorial_deck")
        if meta.get("no_ubicados"):
            with st.expander(f"{meta['total'] - meta['ubicadas']:,} registros sin ubicar"):
                st.caption("Valores que no se reconocieron como un municipio de Colombia: " +
                           ", ".join(f"«{html.escape(str(k))}» ({v})" for k, v in meta["no_ubicados"].items()))

    # Riel derecho: zona abierta, ir a una zona, Top 10 y alertas.
    with riel, st.container(key="terr_riel"):
        colores_top, _ = _clasificar(z["tabla"], color, paleta, fondo.startswith("Oscuro")) if not z["tabla"].empty else ([], [])
        _riel(z, colores_top, seleccion, zm, zd, ub, metrica, calculo, fecha_col, crecer, nivel_mpio, dims_neg, etiquetas)

    def _mapa_para_informe() -> Optional[str]:
        """El mapa como se ve ahora (mismas capas, color, paleta y fondo), en HTML para el informe."""
        try:
            hex_t = T.hexagonos(ub, metrica_calc, calculo, radio_km, fecha_col, periodo) if capas_on.get("hex") else pd.DataFrame()
            deck, _ = _construir_mapa(capas_on, zm["tabla"], zd["tabla"], hex_t,
                                      _puntos(periodo) if (capas_on.get("calor") or capas_on.get("puntos")) else pd.DataFrame(),
                                      crecer, color, paleta, fondo, escala, radio_km, metrica_label, inclinada=inclinada,
                                      ligero=True)
            return deck.to_html(as_string=True, notebook_display=False) if deck is not None else None
        except Exception:
            return None  # sin mapa, el informe sale igual

    _descargas(ub, metrica_calc, calculo, fecha_col, z, zd, dims_neg, etiquetas, crecer, cob, metrica_label,
               libro["filename"], hoja, filtros, len(df), T.serie_total(ub, metrica_calc, calculo, fecha_col),
               _mapa_para_informe)

    if seleccion:
        _ficha(ub, seleccion, zd if seleccion["nivel"] == "departamento" else zm, crecer, metrica, metrica_label,
               calculo, fecha_col, dims, dims_neg, etiquetas)

    # Pocas razones en pantalla (se ven 3 por columna); el informe descargable pide muchas más.
    inf = T.informe(ub, metrica_calc, calculo, fecha_col, z, zd, dims_neg, etiquetas, crecer, cob, metrica_label,
                    max_razones=3, max_deptos=8)
    _tablero_semaforo(inf)

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
