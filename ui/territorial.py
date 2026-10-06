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
- **🎯 Plan de acción** (`core/territorio_plan`): lo que se hace con todo lo
  anterior. Las jugadas del mes (qué hacer, dónde, quién, plazo y cuánto
  vale al mes), la estrategia de cada zona, el plan de cada agente comercial
  y dónde abrir. Va también en el Excel y el HTML descargables.
"""
from __future__ import annotations

import html
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

from core import territorio as T
from core import territorio_plan as P
from core.filter_engine import apply_filters
from core.loader import load_workbook
from ui.components.descarga import preparar_y_descargar
from ui.report_territorial import build_territorial_excel, build_territorial_html, nombre_archivo
from visualization.mapa_territorial import (
    CSS_MAPA,
    cabecera_mapa as _cabecera_mapa,
    COLORES as _COLORES,
    ESTADO_ICONO as _ESTADO_ICONO,
    MAPAS as _MAPAS,
    PALETAS as _PALETAS,
    clasificar as _clasificar,
    construir_mapa as _construir_mapa,
    hud as _hud,
    leyenda_linea as _leyenda_linea,
    ley_html as _ley_html,
    sin_mes_a_medias as _sin_mes_a_medias,
    sparkline as _sparkline,
)

# Claves de sesión propias: el archivo que se analiza aquí no tiene por qué
# ser el mismo que el del panel completo, y compartir la clave haría que
# cargar uno pisara al otro.
_CLAVE_LIBRO = "territorial_workbook"
_CLAVE_HOJA = "territorial_sheet"
_CONTEO = "__conteo__"

_ALTO_MAPA = 900   # px; el panel y el riel se desplazan por dentro para no pasarse de esto
# En «Mapa grande» el alto lo pone el CSS (lo que deja libre la ventana); este
# es el de partida, antes de que el navegador mida la pantalla.
_ALTO_MAPA_GRANDE = 820
# La capa cuya leyenda va debajo del mapa grande (el panel con las leyendas
# queda dentro de un menú desplegable): la primera prendida de estas.
_CAPAS_CON_LEYENDA = ("mpios", "columnas", "deptos", "hex", "calor", "puntos", "poblacion")


def _oscuro() -> bool:
    return st.session_state.get("theme_mode") == "dark"


def _inject_css():
    # Lo que comparte con la pestaña «Georreferenciación» (indicadores,
    # cabecera del mapa, semáforo, jugadas) vive en visualization/mapa_territorial.
    st.markdown(
        "<style>" + CSS_MAPA + """
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


        /* Barra del mapa (ir a una zona · ver todo · inclinar · mapa grande).
           Sus columnas NO son las de la consola: sin esto heredaban los 320 px
           fijos del panel y los 360 del riel. */
        .st-key-terr_consola .st-key-terr_nav div[data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important}
        .st-key-terr_consola .st-key-terr_nav div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]:nth-child(n){
          flex:1 1 0!important;min-width:0!important;max-width:none!important;width:auto!important}
        .st-key-terr_consola .st-key-terr_nav div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]:first-child{
          flex:2.6 1 0!important}
        .st-key-terr_nav{margin:2px 0 6px}
        /* El tema muestra TODAS las etiquetas (display:inline-block), también
           las marcadas como ocultas: la del buscador se quita aquí. */
        .st-key-terr_nav [data-testid="stWidgetLabel"]{display:none!important}

        /* «Mapa grande»: una sola tarjeta con la fila de menús arriba y el
           mapa a todo el ancho; el alto es lo que deja libre la ventana. */
        .st-key-terr_grande{background:var(--panel-2);border:1px solid var(--line);border-radius:20px;padding:14px 16px 16px;
          box-shadow:var(--shadow-md);margin-top:6px}
        /* También su envoltorio: si no, guarda el alto de partida y la leyenda
           de abajo se monta sobre el borde del mapa. */
        .st-key-terr_mapa_grande [data-testid="stElementContainer"]:has([data-testid="stDeckGlJsonChart"]),
        .st-key-terr_mapa_grande [data-testid="stDeckGlJsonChart"],
        .st-key-terr_mapa_grande [data-testid="stDeckGlJsonChart"]>div{height:max(560px,calc(100vh - 150px))!important}
        .st-key-terr_mapa_grande [data-testid="stDeckGlJsonChart"]{border-radius:16px;overflow:hidden}
        /* Los menús de la fila: anchos para que quepan las capas con su explicación. */
        div[data-testid="stPopoverBody"]{min-width:380px;max-height:78vh;overflow-y:auto}
        /* Debajo del mapa grande, el riel en tarjetas lado a lado. */
        .st-key-terr_riel_abajo .st-key-terr_riel{display:block!important;columns:3 320px;column-gap:16px;margin-top:14px}
        .st-key-terr_riel_abajo .st-key-terr_riel>div{break-inside:avoid;margin-bottom:14px}

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

        /* Modo presentación */
        @keyframes tourIn{from{opacity:0;transform:translateY(-8px) scale(.98)}to{opacity:1;transform:none}}
        .terr-tour{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-bottom:10px;
          padding:18px 22px;border-radius:18px;border:1px solid var(--line);border-left:7px solid var(--muted);
          background:linear-gradient(120deg,var(--panel) 60%,var(--panel-2));box-shadow:var(--shadow-md);animation:tourIn .5s ease both}
        .terr-tour.bajo{border-left-color:#ef4444}.terr-tour.estable{border-left-color:#eab308}
        .terr-tour.subio{border-left-color:#22c55e}.terr-tour.oport{border-left-color:#a855f7}
        .terr-tour .izq{display:flex;gap:16px;align-items:flex-start;min-width:0}
        .terr-tour .n{flex:0 0 54px;height:54px;border-radius:14px;display:grid;place-items:center;font-size:26px;font-weight:900;
          background:var(--text);color:var(--panel)}
        .terr-tour h3{margin:6px 0 4px!important;padding:0!important;border:0!important;background:none!important;box-shadow:none!important;
          display:block!important;font-size:30px;font-family:'Sora','Inter',sans-serif;color:var(--text);letter-spacing:-.02em}
        .terr-tour h3 small{font-size:15px;color:var(--muted);font-weight:500;font-family:'Inter',sans-serif}
        .terr-tour p{margin:0;font-size:15.5px;line-height:1.5;color:var(--text)}
        .terr-tour .der{text-align:right;flex:0 0 auto}
        .terr-tour .valor{font-size:16px;color:var(--muted)}.terr-tour .valor b{font-size:28px;color:var(--text);font-family:'Sora','Inter',sans-serif}
        .terr-tour .resp{font-size:14px;color:var(--muted);margin-top:4px}
        .terr-tour .puntos{display:flex;gap:5px;justify-content:flex-end;margin-top:10px}
        .terr-tour .puntos i{width:9px;height:9px;border-radius:50%;background:var(--line)}
        .terr-tour .puntos i.on{background:var(--teal);box-shadow:0 0 8px var(--teal)}
        .terr-tour small{font-size:12px;color:var(--muted)}

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
        /* Plan de acción */
        .terr-brief{background:var(--panel);border:1px solid var(--line);border-left:5px solid var(--teal);border-radius:18px;
          padding:18px 22px;box-shadow:var(--shadow-sm);margin-bottom:12px}
        .terr-brief ul{margin:12px 0 0;padding-left:20px}.terr-brief li{font-size:15px;line-height:1.55;margin-bottom:5px;color:var(--text)}
        .terr-bolsa{display:grid;grid-template-columns:200px 1fr;gap:20px;align-items:center}
        .terr-bolsa .tot small{display:block;font-size:11.5px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
        .terr-bolsa .tot b{font-size:34px;font-family:'Sora','Inter',sans-serif;color:var(--text)}
        .terr-bolsa .barra{display:flex;height:16px;border-radius:99px;overflow:hidden;gap:3px;background:var(--panel-2)}
        .terr-bolsa .barra i{display:block}
        .terr-bolsa .ley{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:8px;font-size:13px;color:var(--muted)}
        .terr-bolsa .ley b{color:var(--text)}
        .terr-bolsa i.rescatar{background:#dc2626}.terr-bolsa i.recuperar{background:#f87171}
        .terr-bolsa i.desarrollar{background:#eab308}.terr-bolsa i.abrir{background:#a855f7}
        @media(max-width:900px){.terr-bolsa{grid-template-columns:1fr}}
        .terr-estrs{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:12px}
        .terr-estr{background:var(--panel);border:1px solid var(--line);border-top:4px solid var(--muted);border-radius:14px;padding:12px 14px}
        .terr-estr.bajo{border-top-color:#ef4444}.terr-estr.estable{border-top-color:#eab308}.terr-estr.subio{border-top-color:#22c55e}
        .terr-estr span{display:block;font-size:13px;font-weight:800;color:var(--text)}
        .terr-estr b{display:block;font-size:28px;font-family:'Sora','Inter',sans-serif;color:var(--text)}
        .terr-estr small{font-size:12px;color:var(--muted);line-height:1.35}
        .terr-agente{background:var(--panel);border:1px solid var(--line);border-top:5px solid var(--muted);border-radius:18px;
          padding:18px 22px;box-shadow:var(--shadow-sm);margin-top:8px}
        .terr-agente.bajo{border-top-color:#ef4444}.terr-agente.subio{border-top-color:#22c55e}.terr-agente.estable{border-top-color:#eab308}
        .terr-agente .cab{display:flex;justify-content:space-between;gap:16px;align-items:center}
        .terr-agente h4{margin:8px 0 2px;padding:0;border:0;background:none;font-size:26px;font-family:'Sora','Inter',sans-serif;color:var(--text)}
        .terr-agente .cab small{font-size:13px;color:var(--muted)}
        .terr-mini.seis{grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}
        .terr-agente .bloques{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:14px 0 4px}
        .terr-agente .bloques>div{background:var(--panel-2);border-radius:12px;padding:12px 14px}
        .terr-agente h5{margin:0 0 6px;font-size:11.5px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
        .terr-agente>h5{margin-top:14px}
        .terr-agente p{margin:3px 0;font-size:14px;color:var(--text)}
        .terr-agente p.mov.bajo{color:var(--red)}.terr-agente p.mov.subio{color:var(--green)}
        .terr-agente p b{color:var(--text)}

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


@st.cache_data(show_spinner="Armando el plan de acción…", max_entries=8, ttl=1800)
def _plan_cacheado(ub, metrica, calculo, fecha_col, z, dims, etiquetas, agente, cuenta):
    return P.plan(ub, metrica, calculo, fecha_col, z, list(dims), etiquetas, agente=agente, cuenta=cuenta)


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
    for capa in ("jugadas_pin", "rutas", "mpios", "zonas", "deptos", "blancos", "poblacion"):
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


def _estado_y_hud(meta, origen, z, zm, ub, metrica_calc, calculo, fecha_col, metrica_label, cob) -> None:
    """Cuántos registros se ubicaron y los indicadores de arriba del mapa."""
    st.markdown(f'<div class="terr-estado">📍 Ubicados <b>{meta["ubicadas"]:,} de {meta["total"]:,}</b> registros '
                f'a partir de {html.escape(origen)}.</div>', unsafe_allow_html=True)
    st.markdown(_hud(z if not z["tabla"].empty else zm, T.serie_total(ub, metrica_calc, calculo, fecha_col),
                     metrica_label, cob), unsafe_allow_html=True)


def _ver_todo() -> None:
    """Vuelve a encuadrar todas las zonas: cierra la zona abierta y obliga al
    mapa a recentrarse aunque se haya movido a mano (si la vista que se le
    manda es idéntica a la anterior, deck.gl deja la cámara donde estaba)."""
    st.session_state.pop("territorial_zona_sel", None)
    st.session_state["_territorial_firma"] = _firma_mapa()
    st.session_state["territorial_vista_n"] = st.session_state.get("territorial_vista_n", 0) + 1


def _alternar_grande() -> None:
    st.session_state["territorial_grande"] = not st.session_state.get("territorial_grande", False)


def _alternar_inclinada() -> None:
    st.session_state["territorial_inclinada"] = not st.session_state.get("territorial_inclinada", False)


def _navegacion(z: dict, nivel_mpio: str, grande: bool) -> bool:
    """La barra pegada al mapa: ir a una zona, ver todo, inclinar y cambiar a
    «Mapa grande». Devuelve si el mapa va inclinado."""
    c = st.columns([3.2, 1.2, 1.15, 1.45], gap="small", vertical_alignment="center")
    tabla = z["tabla"]
    with c[0]:
        if not tabla.empty:
            nivel_t = "departamento" if z.get("nivel") == "departamento" else nivel_mpio
            opciones = {f"{int(r.posicion)}. {r.nombre}": {"zona": str(r.zona), "nivel": nivel_t}
                        for r in tabla.head(300).itertuples()}
            lista = ["🔎 Ir a una zona…"] + list(opciones)
            if st.session_state.get("territorial_ir_a") not in lista:
                st.session_state.pop("territorial_ir_a", None)
            # Sin «?» de ayuda: lo vuelve más alto que los botones y la barra queda dispareja.
            st.selectbox("Ir a una zona", lista, key="territorial_ir_a", on_change=_ir_a, args=(opciones,),
                         label_visibility="collapsed")
    c[1].button("🧭 Ver todo", key="territorial_ver_todo", on_click=_ver_todo, use_container_width=True,
                help="Vuelve a encuadrar todas tus zonas y cierra la que esté abierta.")
    # Botón y no interruptor, por la misma razón: todo en la barra mide lo mismo.
    inclinada = bool(st.session_state.get("territorial_inclinada", False))
    c[2].button("▭ Plano" if inclinada else "⟋ Inclinar", key="territorial_inclinar_btn", on_click=_alternar_inclinada,
                use_container_width=True, help="Inclina el mapa aunque las capas sean planas: da profundidad.")
    c[3].button("↙ Vista normal" if grande else "⛶ Mapa grande", key="territorial_grande_btn",
                on_click=_alternar_grande, use_container_width=True, type="secondary" if grande else "primary",
                help="El mapa a todo el ancho y alto de la pantalla; los controles pasan a menús arriba y el "
                     "resto, debajo del mapa." if not grande else "Vuelve al panel, el mapa y el riel lado a lado.")
    return inclinada


def _riel(z: dict, colores: list, seleccion: Optional[dict], zm: dict, zd: dict, ub, metrica, calculo, fecha_col,
          crecer: dict, nivel_mpio: str, dims_neg: list, etiquetas: dict):
    """El riel derecho: zona abierta, Top 10 y alertas («Ir a una zona» está en la barra del mapa)."""
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

    # 2) Top 10 con barras del mismo color que el mapa.
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

    # 3) Alertas del territorio.
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
               serie_total: pd.DataFrame, mapa, plan_accion: Optional[dict] = None) -> None:
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
            lambda: build_territorial_excel(_informe(), ctx, serie_total, plan=plan_accion, mensual=T.mes_a_mes(
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
            lambda: build_territorial_html(_informe(), ctx, serie_total, mapa(), plan=plan_accion),
            nombre_archivo(hoja or archivo, "html"), "text/html",
            preparar="⚙️ Preparar informe HTML", descargar="⬇️ Descargar informe HTML",
            ayuda="Incluye el mapa con las capas, el color y el fondo que tienes puestos.")


def _ver_en_mapa(clave: str, nivel: str) -> None:
    st.session_state["territorial_zona_sel"] = {"zona": str(clave), "nivel": nivel}


def _pasos_html(pasos: list) -> str:
    return "<ol>" + "".join(f"<li>{_negritas(x)}</li>" for x in pasos) + "</ol>"


def _bolsa_html(bolsa: dict) -> str:
    """Barra apilada de lo que hay en juego al mes, por estrategia."""
    partes = [(e, bolsa[e]["valor"], bolsa[e]["n"]) for e in ("rescatar", "recuperar", "desarrollar", "abrir")
              if bolsa.get(e, {}).get("valor", 0) > 0]
    total = sum(v for _, v, _ in partes)
    if not total:
        return ""
    barra = "".join(f'<i class="{e}" style="width:{v / total * 100:.1f}%" title="{P.ESTRATEGIAS[e]["titulo"]}"></i>'
                    for e, v, _ in partes)
    leyenda = "".join(f'<span class="{e}"><b>{P.ESTRATEGIAS[e]["icono"]} {P.ESTRATEGIAS[e]["titulo"]}</b> '
                      f'{T.cifra(v)} · {n} {"zona" if n == 1 else "zonas"}</span>' for e, v, n in partes)
    return (f'<div class="terr-bolsa"><div class="tot"><small>En juego al mes</small><b>{T.cifra(total)}</b></div>'
            f'<div class="cuerpo"><div class="barra">{barra}</div><div class="ley">{leyenda}</div></div></div>')


def _plan_accion(pl: dict, metrica_label: str, nivel_plan: str) -> None:
    """🎯 Plan de acción: lo que el gerente reparte el lunes."""
    if not pl:
        return
    st.markdown('<div class="terr-label">🎯 Plan de acción · qué hacer, dónde, quién y cuánto vale</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="terr-brief">' + _bolsa_html(pl["bolsa"]) + '<ul>'
                + "".join(f"<li>{_negritas(f)}</li>" for f in pl["resumen"]) + "</ul></div>", unsafe_allow_html=True)
    n_ag = len(pl["agentes"])
    pestañas = st.tabs([f"🎯 Las jugadas del mes ({len(pl['jugadas'])})", "🗺️ Plan por zona",
                        f"👥 Agentes comerciales ({n_ag})" if n_ag else "👥 Agentes comerciales",
                        f"📍 Dónde abrir ({len(pl['aperturas'])})"])

    # 1) Las jugadas, ordenadas por lo que valen.
    with pestañas[0]:
        if not pl["jugadas"]:
            st.info("No hay caídas ni brechas que valga la pena atacar con este periodo: el territorio está sano.")
        for fila in range(0, len(pl["jugadas"]), 2):
            columnas = st.columns(2, gap="medium")
            for col, j in zip(columnas, pl["jugadas"][fila:fila + 2]):
                with col:
                    valor = (f"vale ≈ <b>{T.cifra(j['valor'])}</b> al mes" if j["valor"] else
                             f"ganó <b>{T.cifra_signo(j.get('ganancia', 0))}</b> · buena práctica")
                    pie = [f"👤 {html.escape(j['responsable'])}" if j["responsable"] else "", f"⏱ {html.escape(j['plazo'])}",
                           f"📏 {html.escape(j['kpi'])}"]
                    st.markdown(
                        f'<div class="terr-jugada {j["tono"]}"><div class="cab"><span class="n">{j["n"]}</span>'
                        f'<span class="tchip {j["tono"]}">{j["icono"]} {html.escape(j["titulo"])}</span>'
                        f'<span class="valor">{valor}</span></div><h4>{html.escape(j["zona"])}'
                        f'<small>{html.escape(j["departamento"])}</small></h4><p class="que">{html.escape(j["que"])}</p>'
                        f'{_pasos_html(j["pasos"])}<div class="pie">' + "".join(f"<span>{x}</span>" for x in pie if x)
                        + "</div></div>", unsafe_allow_html=True)
                    nivel = "municipio" if j["estrategia"] == "abrir" else nivel_plan
                    st.button("🗺️ Ver en el mapa", key=f"terr_jug_{j['n']}", on_click=_ver_en_mapa,
                              args=(j["clave_zona"], nivel))

    # 2) Todas las zonas con su estrategia.
    with pestañas[1]:
        zonas = pl["zonas"]
        cuenta = zonas["estrategia"].value_counts()
        tarjetas = "".join(
            f'<div class="terr-estr {e["tono"]}"><span>{e["icono"]} {e["titulo"]}</span><b>{int(cuenta.get(k, 0))}</b>'
            f'<small>{html.escape(e["que"])}</small></div>' for k, e in P.ESTRATEGIAS.items()
            if k != "abrir" and cuenta.get(k, 0))
        st.markdown(f'<div class="terr-estrs">{tarjetas}</div>', unsafe_allow_html=True)
        opciones = [k for k in P.ESTRATEGIAS if k != "abrir" and cuenta.get(k, 0)]
        elegidas = st.multiselect("Ver estrategias", opciones, default=[o for o in opciones if o != "sostener"],
                                  format_func=lambda k: f"{P.ESTRATEGIAS[k]['icono']} {P.ESTRATEGIAS[k]['titulo']}",
                                  key="territorial_plan_estr")
        vista = zonas[zonas["estrategia"].isin(elegidas)].copy()
        vista["_orden"] = vista["estrategia"].map(lambda e: P.ESTRATEGIAS[e]["orden"])
        vista = vista.sort_values(["_orden", "valor_mes"], ascending=[True, False])
        tabla = pd.DataFrame({
            "Estrategia": vista["estrategia"].map(lambda e: f"{P.ESTRATEGIAS[e]['icono']} {P.ESTRATEGIAS[e]['titulo']}"),
            "Zona": vista["nombre"], "Departamento": vista.get("departamento", ""),
            "Ritmo al mes": vista["ritmo"].round(0), "Meta al mes": vista["meta_mes"].round(0),
            "Vale al mes": vista["valor_mes"].round(0), "Responsable": vista["responsable"],
            "Plazo": vista["plazo"], "Primer paso": vista["pasos"].map(lambda x: x[0].replace("**", "") if x else ""),
        })
        st.dataframe(tabla, hide_index=True, use_container_width=True, height=min(520, 40 + 35 * len(tabla)),
                     column_config={c: st.column_config.NumberColumn(format="localized")
                                    for c in ("Ritmo al mes", "Meta al mes", "Vale al mes")}
                     | {"Primer paso": st.column_config.TextColumn(width="large")})

    # 3) Agentes comerciales.
    with pestañas[2]:
        _plan_agentes(pl)

    # 4) Dónde abrir.
    with pestañas[3]:
        ap = pl["aperturas"]
        if ap is None or ap.empty:
            st.info("No hay municipios grandes sin presencia en los departamentos donde operas"
                    if pl["nivel"] == "municipio" else "«Dónde abrir» necesita ubicación por municipio.")
        else:
            st.caption(f"Municipios de 20.000+ habitantes sin presencia, en los departamentos donde ya operas. Potencial = la "
                       f"mitad de la penetración típica de tu red ({T.cifra(pl['tipica'])} por cada 10.000 habitantes al mes). "
                       "El modelo de entrada depende de la distancia a tu zona activa más cercana.")
            for fila in range(0, min(len(ap), 6), 3):
                columnas = st.columns(3, gap="small")
                for col, (_, r) in zip(columnas, ap.iloc[fila:fila + 3].iterrows()):
                    with col:
                        st.markdown(
                            f'<div class="terr-jugada oport"><div class="cab"><span class="tchip oport">🎯 Abrir</span>'
                            f'<span class="valor">≈ <b>{T.cifra(r["potencial_mes"])}</b> al mes</span></div>'
                            f'<h4>{html.escape(str(r["municipio"]))}<small>{html.escape(str(r["departamento"]))}</small></h4>'
                            f'{_pasos_html(r["pasos"])}</div>', unsafe_allow_html=True)
            tabla = pd.DataFrame({
                "Municipio": ap["municipio"], "Departamento": ap["departamento"], "Población": ap["poblacion"],
                "Urbana": ap["poblacion_cabecera"], "Crec. 2030": ap["crecimiento_2030"] * 100,
                "Atender desde": ap["base"], "Km": ap["distancia_km"].round(0),
                "Agente sugerido": ap["agente_sugerido"], "Potencial al mes": ap["potencial_mes"].round(0),
                "Modelo de entrada": ap["modelo"]})
            st.dataframe(tabla, hide_index=True, use_container_width=True, column_config={
                "Población": st.column_config.NumberColumn(format="localized"),
                "Urbana": st.column_config.NumberColumn(format="localized"),
                "Crec. 2030": st.column_config.NumberColumn(format="%+.1f%%"),
                "Potencial al mes": st.column_config.NumberColumn(format="localized"),
                "Modelo de entrada": st.column_config.TextColumn(width="large")})


def _plan_agentes(pl: dict) -> None:
    agentes = pl["agentes"]
    if not agentes:
        st.info("Para el plan por agente, el archivo necesita una columna de asesor, vendedor, agente, ejecutivo o "
                "promotor. Con ella, cada uno recibe su ruta, sus clientes perdidos, su meta y su estrategia.")
        return
    n = len(agentes)
    perfiles = pd.Series([a["perfil"] for a in agentes]).value_counts()
    st.markdown('<div class="terr-estrs">' + "".join(
        f'<div class="terr-estr {P.PERFILES[k]["tono"]}"><span>{P.PERFILES[k]["icono"]} {P.PERFILES[k]["titulo"]}</span>'
        f'<b>{int(perfiles.get(k, 0))}</b><small>de {n} agentes</small></div>'
        for k in ("caida", "desarrollo", "solido", "referente")) + "</div>", unsafe_allow_html=True)
    tabla = pd.DataFrame({
        "#": [a["posicion"] for a in agentes], "Agente": [a["nombre"] for a in agentes],
        "Perfil": [f"{a['perfil_icono']} {a['perfil_titulo']}" for a in agentes],
        "Ritmo al mes": [round(a["ritmo"]) for a in agentes],
        "Variación": [None if a["var"] is None else a["var"] * 100 for a in agentes],
        f"vs mediana de {n}": [None if a["vs_mediana"] is None else a["vs_mediana"] * 100 for a in agentes],
        "Meta sugerida": [round(a["meta"]) for a in agentes], "Zonas": [a["zonas"] for a in agentes],
        "Dónde perdió": [", ".join(p["zona"] for p in a["perdio"]) for a in agentes],
    })
    st.dataframe(tabla, hide_index=True, use_container_width=True, height=min(420, 40 + 35 * n), column_config={
        "Ritmo al mes": st.column_config.NumberColumn(format="localized"),
        "Meta sugerida": st.column_config.NumberColumn(format="localized"),
        "Variación": st.column_config.NumberColumn(format="%+.0f%%"),
        f"vs mediana de {n}": st.column_config.NumberColumn(format="%+.0f%%")})
    nombres = [a["nombre"] for a in agentes]
    # Por defecto, el que más cae: es la conversación más urgente.
    orden = sorted(agentes, key=lambda a: (a["perfil"] != "caida", a["delta"]))
    if st.session_state.get("territorial_plan_agente") not in nombres:
        st.session_state["territorial_plan_agente"] = orden[0]["nombre"]
    elegido = st.selectbox("Plan del agente", nombres, key="territorial_plan_agente")
    a = next(x for x in agentes if x["nombre"] == elegido)
    datos = [("Ritmo al mes", T.cifra(a["ritmo"])), ("Posición", f"{a['posicion']}.º de {n}"),
             ("Vs mes anterior", "—" if a["var"] is None else f"{a['var']:+.0%}"),
             (f"Vs mediana de {n}", "—" if a["vs_mediana"] is None else f"{a['vs_mediana']:+.0%}"),
             ("Meta sugerida", T.cifra(a["meta"])), ("Zonas", str(a["zonas"]))]
    bloques = []
    if a["perdio"] or a["gano"]:
        bloques.append("<div><h5>Dónde se movió</h5>" + "".join(
            f'<p class="mov bajo">▼ <b>{html.escape(x["zona"])}</b> {T.cifra_signo(x["delta"])}</p>' for x in a["perdio"])
            + "".join(f'<p class="mov subio">▲ <b>{html.escape(x["zona"])}</b> {T.cifra_signo(x["delta"])}</p>' for x in a["gano"])
            + "</div>")
    if a["cuentas_perdidas"]:
        bloques.append("<div><h5>Clientes que dejaron de comprar</h5>" + "".join(
            f'<p>• <b>{html.escape(c["nombre"])}</b> (compraba {T.cifra(c["antes"])})</p>' for c in a["cuentas_perdidas"])
            + "</div>")
    if a["ruta"]:
        bloques.append("<div><h5>Ruta sugerida</h5>" + "".join(
            f'<p>{k}. {P.ESTRATEGIAS[r["estrategia"]]["icono"]} <b>{html.escape(r["zona"])}</b>'
            + (f' · vale ≈ {T.cifra(r["valor"])}' if r["valor"] else "") + "</p>" for k, r in enumerate(a["ruta"], start=1))
            + "</div>")
    st.markdown(
        f'<div class="terr-agente {a["perfil_tono"]}"><div class="cab"><div><span class="tchip {a["perfil_tono"]}">'
        f'{a["perfil_icono"]} {a["perfil_titulo"]}</span><h4>{html.escape(a["nombre"])}</h4>'
        f'<small>{"Principales zonas: " + html.escape(", ".join(a["principales"])) if a["principales"] else ""}</small></div>'
        f'{_sparkline(a["historia"], ancho=220, alto=54) if len(a["historia"]) >= 2 else ""}</div>'
        '<div class="terr-mini seis">' + "".join(f"<div><span>{html.escape(x)}</span><b>{html.escape(y)}</b></div>" for x, y in datos)
        + f'</div><div class="bloques">{"".join(bloques)}</div><h5>Estrategia</h5>{_pasos_html(a["estrategia"])}</div>',
        unsafe_allow_html=True)


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
    ("jugadas", "Jugadas del plan", "Pines numerados con las jugadas del mes: el mismo número de las tarjetas del plan.",
     "Plan de acción", "oport"),
    ("rutas", "Rutas de expansión", "Arcos desde tu zona más cercana a cada municipio por abrir.", "Plan de acción", "oport"),
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

    # Dos formas de ver la consola. Normal: panel · mapa · riel. «Mapa grande»:
    # el mapa a todo el ancho y alto de la pantalla, el panel convertido en
    # menús desplegables en una sola fila y el riel debajo. Los widgets son los
    # mismos (mismas claves), así que cambiar de modo no pierde nada.
    grande = bool(st.session_state.get("territorial_grande"))
    if grande:
        with st.container(key="terr_grande"):
            barra = st.columns([1, 1, 1, 1, 5.2], gap="small", vertical_alignment="bottom")
            caja_datos = barra[0].popover("📂 Datos", use_container_width=True)
            caja_periodo = barra[1].popover("📅 Periodo", use_container_width=True)
            caja_capas = barra[2].popover("🗂️ Capas", use_container_width=True)
            caja_estilo = barra[3].popover("🎨 Estilo", use_container_width=True)
            caja_nav = barra[4].container()
            principal = st.container(key="terr_mapa_grande")
        riel = st.container()
    else:
        with st.container(key="terr_consola"):
            panel, principal, riel = st.columns([320, 1100, 360], gap="medium")
        caja_datos = panel
        caja_nav = None

    with caja_datos, st.container(key="terr_panel"):
        st.markdown('<div class="terr-sec">Datos</div>', unsafe_allow_html=True)
        hojas = list(libro["sheets"].keys())
        if len(hojas) > 1:
            elegida = st.selectbox("Hoja", hojas, index=hojas.index(hoja), key="territorial_hoja_sel")
            if elegida != hoja:
                st.session_state[_CLAVE_HOJA] = elegida
                st.session_state.pop("territorial_zona_sel", None)
                st.rerun()
        # La pestaña Georreferenciación puede mandar una métrica: si no existe en esta hoja, se descarta.
        if st.session_state.get("territorial_metrica") not in metricas + [_CONTEO]:
            st.session_state.pop("territorial_metrica", None)
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
                   "focos": (por_municipio or con_coordenadas) and len(meses) >= 2, "etiquetas": True,
                   "jugadas": en_colombia, "rutas": por_municipio}
    por_defecto = ({"hex", "jugadas", "rutas", "etiquetas"} if con_coordenadas else
                   {"mpios", "jugadas", "rutas", "etiquetas"} if por_municipio else {"deptos", "jugadas", "etiquetas"})

    if not grande:
        # Se crea aquí y no arriba: el orden en que se crean es el orden en pantalla (Datos va primero).
        caja_periodo = caja_capas = caja_estilo = panel.container(key="terr_panel_2")
    with caja_periodo:
        periodo, jugar, tour = None, False, False
        if len(meses) >= 2:
            opciones_mes = ["Todo"] + meses
            if st.session_state.get("territorial_mes") not in opciones_mes:
                st.session_state["territorial_mes"] = "Todo"
            periodo = st.select_slider("Periodo", opciones_mes, key="territorial_mes",
                                       format_func=lambda m: "Todo el periodo" if m == "Todo" else T.etiqueta_mes(m, True))
            periodo = None if periodo == "Todo" else periodo
            jugar = st.toggle("▶ Reproducir mes a mes", key="territorial_play",
                              help="Recorre los meses en el mapa, uno cada segundo y medio.")
        tour = st.toggle("🎬 Modo presentación", key="territorial_tour",
                         help="Recorre las jugadas del plan una por una: el mapa vuela a cada zona y muestra qué hacer. "
                              "Para proyectar en una reunión.")

    with caja_capas:
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

    with caja_estilo:
        st.markdown('<div class="terr-sec">Estilo</div>', unsafe_allow_html=True)
        # El semáforo va primero: es la lectura que pide un gerente.
        colores = (["variacion"] if len(meses) >= 2 else []) + (["meta"] if meta_col else []) + ["volumen"] \
            + (["penetracion"] if en_colombia and calculo in {"Suma", "Conteo"} else [])
        if st.session_state.get("territorial_color") not in colores:
            st.session_state.pop("territorial_color", None)
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

    # 🎯 El plan: siempre por municipio si se puede (también con coordenadas,
    # que se asignan al municipio más cercano), si no por departamento.
    if nivel_mpio == "municipio":
        z_plan, nivel_plan = zm, "municipio"
    elif por_municipio:
        z_plan, nivel_plan = T.zonas(ub, metrica_calc, calculo, "municipio", fecha_col, periodo, meta_col), "municipio"
    else:
        z_plan, nivel_plan = zd, "departamento"
    # Con coordenadas el mapa va por punto, pero el plan abre municipios: la
    # tarjeta y la ficha de un municipio elegido desde el plan leen la tabla
    # por municipio (si no, lo mostraban como «sin actividad»).
    z_mpio_sel, nivel_sel = zm, nivel_mpio
    if seleccion and seleccion.get("nivel") == "municipio" and nivel_mpio == "punto":
        z_mpio_sel, nivel_sel = z_plan, "municipio"

    columnas_texto = [c for c in df.columns if c not in set(metricas) | set(schema.get("dates", []))]
    agente_col = P.columna_agente(df, columnas_texto)
    cuenta_col = P.columna_cuenta(df, columnas_texto, excluir=(agente_col,))
    dims_plan = dims_neg + ([agente_col] if agente_col and agente_col not in dims_neg else [])
    pl = _plan_cacheado(ub, metrica_calc, calculo, fecha_col, z_plan, tuple(dims_plan), etiquetas, agente_col, cuenta_col)

    def _dibujar(mes, clave_evento: Optional[str], leyendas_panel: bool = True, forzar: Optional[dict] = None):
        zm_m, zd_m = (zm, zd) if mes == periodo else _calcular(mes)
        hex_t = T.hexagonos(ub, metrica_calc, calculo, radio_km, fecha_col, mes) if capas_on.get("hex") else pd.DataFrame()
        deck, leyendas = _construir_mapa(capas_on, zm_m["tabla"], zd_m["tabla"], hex_t,
                                         _puntos(mes) if (capas_on.get("calor") or capas_on.get("puntos")) else pd.DataFrame(),
                                         crecer, color, paleta, fondo, escala, radio_km, metrica_label,
                                         seleccion=forzar or (seleccion if clave_evento else None),
                                         inclinada=inclinada or bool(forzar), plan=pl)
        # Desde la animación (un fragmento) no se puede escribir en el panel,
        # que está fuera de él: las leyendas se quedan como estaban.
        if leyendas_panel:
            for clave, hueco in huecos.items():
                hueco.markdown(_ley_html(leyendas.get(clave, [])) if capas_on.get(clave) else "", unsafe_allow_html=True)
        etiqueta = T.etiqueta_mes(mes) if mes else (
            f"Todo el periodo · {T.etiqueta_mes(meses[0], True)} – {T.etiqueta_mes(meses[-1], True)}" if meses else "Todos los registros")
        z_m = zd_m if solo_departamento else zm_m
        st.markdown(_cabecera_mapa(metrica_label, color, z_m, etiqueta, capas_on, pl,
                                   [tit for c, tit, *_ in _CAPAS if capas_on.get(c)]), unsafe_allow_html=True)
        if deck is None:
            st.info("Prende al menos una capa en " + ("el menú «🗂️ Capas»." if grande else "el panel de la izquierda."))
            return None
        # «🧭 Ver todo»: una vista apenas distinta a la anterior hace que el mapa se recentre.
        vueltas = st.session_state.get("territorial_vista_n", 0)
        if vueltas and not forzar and deck.initial_view_state is not None:
            deck.initial_view_state.zoom = float(deck.initial_view_state.zoom) + vueltas * 1e-6
        alto = _ALTO_MAPA_GRANDE if grande else _ALTO_MAPA
        evento = None
        if clave_evento:
            evento = st.pydeck_chart(deck, height=alto, use_container_width=True, on_select="rerun",
                                     selection_mode="single-object", key=clave_evento)
        else:
            st.pydeck_chart(deck, height=alto, use_container_width=True)
        if grande:
            capa = next((c for c in _CAPAS_CON_LEYENDA if capas_on.get(c) and leyendas.get(c)), None)
            if capa:
                st.markdown(_leyenda_linea(leyendas[capa]), unsafe_allow_html=True)
        return evento

    with principal:
        origen = {"coordenadas": f"las coordenadas ({meta['columna']})", "municipio": f"la columna «{meta['columna']}»",
                  "departamento": f"la columna «{meta['columna']}» (nivel departamento)",
                  "texto": f"el municipio escrito en «{meta['columna']}»"}.get(meta["origen"], "")
        # En «Mapa grande» los indicadores van DEBAJO del mapa: arriba
        # ocupaban ~300 px y el mapa no cabía entero en la pantalla.
        if not grande:
            _estado_y_hud(meta, origen, z, zm, ub, metrica_calc, calculo, fecha_col, metrica_label, cob)
        with (caja_nav if grande else st.container()), st.container(key="terr_nav"):
            inclinada = _navegacion(z, nivel_mpio, grande)
        jugadas_tour = [j for j in (pl.get("jugadas") if pl else None) or [] if j.get("lat") is not None]
        if tour and jugadas_tour:
            # Modo presentación: un fragmento que cada 6 s pasa a la jugada
            # siguiente; el mapa vuela a la zona y la tarjeta dice qué hacer.
            @st.fragment(run_every=6)
            def _presentacion():
                i = st.session_state.get("territorial_tour_i", 0) % len(jugadas_tour)
                j = jugadas_tour[i]
                vale = (f"vale ≈ <b>{T.cifra(j['valor'])}</b> al mes" if j["valor"] else
                        f"ganó <b>{T.cifra_signo(j.get('ganancia', 0))}</b> · buena práctica")
                puntos = "".join(f'<i class="{"on" if k == i else ""}"></i>' for k in range(len(jugadas_tour)))
                st.markdown(
                    f'<div class="terr-tour {j["tono"]}"><div class="izq"><span class="n">{j["n"]}</span><div>'
                    f'<span class="tchip {j["tono"]}">{j["icono"]} {html.escape(j["titulo"])}</span>'
                    f'<h3>{html.escape(j["zona"])} <small>{html.escape(j["departamento"])}</small></h3>'
                    f'<p>{_negritas(j["pasos"][0]) if j["pasos"] else ""}</p></div></div>'
                    f'<div class="der"><div class="valor">{vale}</div>'
                    + (f'<div class="resp">👤 {html.escape(j["responsable"])} · ⏱ {html.escape(j["plazo"])}</div>' if j["responsable"]
                       else f'<div class="resp">⏱ {html.escape(j["plazo"])}</div>')
                    + f'<div class="puntos">{puntos}</div><small>Jugada {i + 1} de {len(jugadas_tour)}</small></div></div>',
                    unsafe_allow_html=True)
                nivel_j = "municipio" if j["estrategia"] == "abrir" else (pl.get("nivel") or "municipio")
                _dibujar(periodo, None, leyendas_panel=False, forzar={"zona": j["clave_zona"], "nivel": nivel_j})
                st.session_state["territorial_tour_i"] = i + 1
            _presentacion()
        elif jugar and len(meses) >= 2:
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
        if grande:
            _estado_y_hud(meta, origen, z, zm, ub, metrica_calc, calculo, fecha_col, metrica_label, cob)
        if meta.get("no_ubicados"):
            with st.expander(f"{meta['total'] - meta['ubicadas']:,} registros sin ubicar"):
                st.caption("Valores que no se reconocieron como un municipio de Colombia: " +
                           ", ".join(f"«{html.escape(str(k))}» ({v})" for k, v in meta["no_ubicados"].items()))

    # Riel derecho: zona abierta, ir a una zona, Top 10 y alertas.
    with riel, st.container(key="terr_riel_abajo" if grande else "terr_riel_lado"), st.container(key="terr_riel"):
        colores_top, _ = _clasificar(z["tabla"], color, paleta, fondo.startswith("Oscuro")) if not z["tabla"].empty else ([], [])
        _riel(z, colores_top, seleccion, z_mpio_sel, zd, ub, metrica, calculo, fecha_col, crecer, nivel_sel, dims_neg,
              etiquetas)

    def _mapa_para_informe() -> Optional[str]:
        """El mapa como se ve ahora (mismas capas, color, paleta y fondo), en HTML para el informe."""
        try:
            hex_t = T.hexagonos(ub, metrica_calc, calculo, radio_km, fecha_col, periodo) if capas_on.get("hex") else pd.DataFrame()
            deck, _ = _construir_mapa(capas_on, zm["tabla"], zd["tabla"], hex_t,
                                      _puntos(periodo) if (capas_on.get("calor") or capas_on.get("puntos")) else pd.DataFrame(),
                                      crecer, color, paleta, fondo, escala, radio_km, metrica_label, inclinada=inclinada,
                                      ligero=True, plan=pl)
            return deck.to_html(as_string=True, notebook_display=False) if deck is not None else None
        except Exception:
            return None  # sin mapa, el informe sale igual

    if seleccion:
        _ficha(ub, seleccion, zd if seleccion["nivel"] == "departamento" else z_mpio_sel, crecer, metrica, metrica_label,
               calculo, fecha_col, dims, dims_neg, etiquetas)

    _plan_accion(pl, metrica_label, nivel_plan)

    # Pocas razones en pantalla (se ven 3 por columna); el informe descargable pide muchas más.
    inf = T.informe(ub, metrica_calc, calculo, fecha_col, z, zd, dims_neg, etiquetas, crecer, cob, metrica_label,
                    max_razones=3, max_deptos=8)
    _tablero_semaforo(inf)

    _descargas(ub, metrica_calc, calculo, fecha_col, z, zd, dims_neg, etiquetas, crecer, cob, metrica_label,
               libro["filename"], hoja, filtros, len(df), T.serie_total(ub, metrica_calc, calculo, fecha_col),
               _mapa_para_informe, pl)

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
