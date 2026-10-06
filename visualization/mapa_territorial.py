"""El mapa territorial (pydeck): capas, colores, ficha flotante e indicadores.

Lo usan la consola de Análisis Territorial (`ui/territorial.py`) y la
pestaña «🗺️ Georreferenciación» del Análisis Completo (`ui/georeferencing.py`):
un solo mapa para las dos pantallas, para que digan exactamente lo mismo
(mismo semáforo, mismos cortes, misma ficha al pasar el cursor, mismos pines
del plan). Vive aquí y no en `ui/territorial.py` porque una vista no importa
cosas de otra vista (CLAUDE.md).

Sin lógica de negocio: los números salen de `core/territorio` y
`core/territorio_plan`; aquí solo se decide cómo se dibujan.
"""
from __future__ import annotations

import html
import math
from typing import Optional

import numpy as np
import pandas as pd

from core import territorio as T
from core import territorio_plan as P

# ── Paletas ───────────────────────────────────────────────────────────────
# Secuenciales de 5 pasos (un solo recorrido de tono, del valor bajo al
# alto). Cada una en dos versiones: sobre fondo oscuro va de oscuro a
# brillante; sobre fondo claro, de claro a intenso.
PALETAS = {
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
PIZARRA = ([(30, 30, 46), (52, 50, 80), (80, 74, 120), (115, 105, 165), (160, 150, 210)],
            [(240, 238, 248), (212, 206, 236), (176, 166, 218), (134, 120, 190), (90, 76, 150)])
# Semáforo de la variación: rojo (bajó) · amarillo (estable, ±5%) · verde
# (subió), con dos intensidades a cada lado. Sobre fondo oscuro, tonos
# brillantes; sobre fondo claro, más hondos para que contrasten.
SEMAFORO_VAR = ([(239, 68, 68), (248, 145, 120), (250, 204, 21), (120, 222, 160), (34, 197, 94)],
                 [(200, 30, 45), (240, 135, 120), (234, 179, 8), (115, 200, 145), (22, 150, 75)])
CORTES_VARIACION = [-0.20, -T.UMBRAL_ESTABLE, T.UMBRAL_ESTABLE, 0.20]
# Semáforo de la meta: rojo < 90% · amarillo 90–100% · verde ≥ 100%.
SEMAFORO = ([(239, 68, 68), (250, 204, 21), (34, 197, 94)], [(214, 40, 50), (234, 179, 8), (22, 163, 74)])
CORTES_META = [0.90, 1.00]
# Los mismos tres estados para bordes de etiquetas, anillos y tarjetas.
ESTADO_RGB = {"bajo": (239, 68, 68), "estable": (250, 204, 21), "subio": (34, 197, 94)}
ESTADO_ICONO = {"bajo": "🔴", "estable": "🟡", "subio": "🟢"}
MAPAS = {"Oscuro": "CARTO_DARK", "Oscuro sin nombres": "CARTO_DARK_NO_LABELS",
          "Claro": "CARTO_LIGHT", "Claro sin nombres": "CARTO_LIGHT_NO_LABELS", "Calles": "CARTO_ROAD",
          # La foto satelital se dibuja como capa (ver `_raster`); debajo, el oscuro.
          "Satélite": "CARTO_DARK_NO_LABELS"}

# ── Relieve, satélite y edificios ─────────────────────────────────────────
# Capas de CONTEXTO: sirven para cualquier archivo (ventas, personal,
# inventario…), porque no dependen de qué se mide sino de dónde. Todas son
# gratuitas y sin clave; las baja el navegador por cuadros, así que se ven
# nítidas a cualquier zoom (igual que el fondo del mapa, necesitan internet).
# - Relieve sombreado y satélite: ESRI World Hillshade / World Imagery.
# - Altura del terreno: Terrain Tiles de AWS (formato terrarium, de SRTM).
# - Edificios: OpenStreetMap servido por OpenFreeMap, con su altura real
#   (`render_height`) cuando OSM la tiene; si no, una casa de 8 m.
SOMBRA_URL = {True: "https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade_Dark/MapServer/tile/{z}/{y}/{x}",
              False: "https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}"}
SATELITE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
_ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/{}/MapServer/tile/{{z}}/{{y}}/{{x}}"
# Con relieve, el mapa base se dibuja aquí (y no lo pone el visor) para poder
# MULTIPLICARLE las sombras: (base, nombres) según el fondo elegido. Los de
# CARTO no sirven por cuadros: sin clave salen con una marca de agua.
BASE_RELIEVE = {
    "Oscuro": (_ESRI.format("Canvas/World_Dark_Gray_Base"), _ESRI.format("Canvas/World_Dark_Gray_Reference")),
    "Oscuro sin nombres": (_ESRI.format("Canvas/World_Dark_Gray_Base"), None),
    "Claro": (_ESRI.format("Canvas/World_Light_Gray_Base"), _ESRI.format("Canvas/World_Light_Gray_Reference")),
    "Claro sin nombres": (_ESRI.format("Canvas/World_Light_Gray_Base"), None),
    "Calles": (_ESRI.format("World_Street_Map"), None),  # trae sus nombres pegados
}
NOMBRES_SATELITE = _ESRI.format("Reference/World_Boundaries_and_Places")
ALTURA_URL = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png"
EDIFICIOS_URL = "https://tiles.openfreemap.org/planet"
# Cuánto se exageran las montañas en «Montañas 3D»: a escala real (×1) la
# cordillera casi no se nota vista desde el país entero.
EXAGERACION = 3.0
# Los datos van un poco por encima del terreno para no «parpadear» con él.
_SOBRE_TERRENO_M = 250


def fondo_oscuro(fondo: str) -> bool:
    """Si el fondo es oscuro (los colores y la ficha se ajustan a eso). La foto satelital cuenta como oscura."""
    return fondo.startswith("Oscuro") or fondo == "Satélite"


def _lit(texto: str) -> str:
    """Un texto que pydeck debe pasar tal cual. Sin comillas, pydeck convierte
    cualquier texto en una fórmula de deck.gl: una URL o la palabra «auto»
    terminaban evaluadas como código (y fallaban sin avisar)."""
    return f"'{texto}'"


# Una imagen plana se muestra con sus colores tal cual: luz ambiente plena y
# sin luz direccional. `material=False` NO apaga la luz de la capa de terreno
# (medido: la imagen salía al 65 % de su brillo y el mapa entero, gris).
_SIN_LUZ = {"ambient": 1.0, "diffuse": 0.0, "shininess": 0, "specularColor": [0, 0, 0]}
# Mezcla «multiplicar»: el color de abajo × el de la capa. Con el relieve
# sombreado (blanco en lo plano) solo oscurece las laderas en sombra, sin
# lavar el mapa ni el mar como hace la transparencia.
_MULTIPLICAR = {"blend": True, "blendColorOperation": "add", "blendColorSrcFactor": "dst",
                "blendColorDstFactor": "zero", "blendAlphaOperation": "add", "blendAlphaSrcFactor": "zero",
                "blendAlphaDstFactor": "one"}


def _raster(pdk, id_capa: str, url: str, opacidad: float = 1.0, k: float = 0.0, nivel: float = -80,
            mezcla: Optional[dict] = None):
    """Una capa de cuadros de imagen (satélite, relieve sombreado), con o sin montañas.

    Se usa la capa de terreno de deck.gl porque es la única de imágenes por
    cuadros que se puede describir sin escribir código JavaScript (la de
    cuadros normal pide una función para dibujar cada uno). Con `k = 0` el
    terreno es plano (un poco por debajo del suelo, para no tapar los datos):
    queda una imagen nítida a cualquier zoom. Con `k > 0` se levanta con la
    altura real del terreno, exagerada `k` veces, y la imagen lo cubre (ahí sí
    con luz: es la que da volumen a las laderas). Varias imágenes planas se
    apilan con `nivel` distinto (más alto = encima) y `mezcla` (ver `_MULTIPLICAR`)."""
    if k:
        decodificador = {"rScaler": 256 * k, "gScaler": k, "bScaler": k / 256, "offset": -32768 * k}
        return pdk.Layer("TerrainLayer", id=id_capa, elevation_data=_lit(ALTURA_URL), texture=_lit(url),
                         elevation_decoder=decodificador, max_zoom=14, mesh_max_error=4, opacity=opacidad,
                         pickable=False)
    decodificador = {"rScaler": 0, "gScaler": 0, "bScaler": 0, "offset": nivel}
    return pdk.Layer("TerrainLayer", id=id_capa, elevation_data=_lit(url), texture=_lit(url),
                     elevation_decoder=decodificador, max_zoom=17, mesh_max_error=40, opacity=opacidad,
                     material=_SIN_LUZ, parameters=mezcla, pickable=False)


_DRAPEADOS: dict = {}


def _drapear(geom: dict, k: float, alza: float = _SOBRE_TERRENO_M) -> dict:
    """La geometría con la altura del terreno en cada vértice, para que un
    municipio o un contorno se «pegue» a las montañas en vez de quedar en el
    suelo, enterrado bajo la cordillera."""
    def _anillo(anillo):
        a = np.asarray(anillo, dtype=float)[:, :2]
        z = T.altitudes(a[:, 1], a[:, 0]) * k + alza
        return np.column_stack([a, z]).round(5).tolist()
    if geom["type"] == "Polygon":
        return {"type": "Polygon", "coordinates": [_anillo(r) for r in geom["coordinates"]]}
    if geom["type"] == "MultiPolygon":
        return {"type": "MultiPolygon", "coordinates": [[_anillo(r) for r in p] for p in geom["coordinates"]]}
    return geom


def _geojson_drapeado(nombre: str, k: float) -> list:
    """Las geometrías de `T.municipios_geojson()` o `T.departamentos_geojson()`
    ya pegadas al relieve, en el mismo orden. Se calculan una vez por exageración."""
    llave = (nombre, round(k, 2))
    if llave not in _DRAPEADOS:
        fuente = T.municipios_geojson() if nombre == "municipios" else T.departamentos_geojson()
        _DRAPEADOS[llave] = [_drapear(f["geometry"], k) for f in fuente["features"]]
    return _DRAPEADOS[llave]


# Sobre las montañas, una capa plana se dibuja SIEMPRE encima (no la tapa una
# ladera): con los vértices ya a la altura del terreno, queda pegada a él.
_ENCIMA = {"depthCompare": "always"}
# Material de las columnas: con luz y reflejo se leen como cilindros, no como
# rectángulos planos de color.
_BRILLO = {"ambient": 0.45, "diffuse": 0.6, "shininess": 72, "specularColor": [255, 255, 255]}
COLORES = {"variacion": "🚦 Semáforo: subió · estable · bajó", "meta": "🚦 Semáforo de meta",
            "volumen": "Volumen", "penetracion": "Penetración por habitante"}


# ── Color por rangos ──────────────────────────────────────────────────────

def rampa_de(paleta: str, fondo_oscuro: bool) -> list:
    oscura, clara = PALETAS.get(paleta, PALETAS["Rojo intenso"])
    return oscura if fondo_oscuro else clara


def cortes_quintiles(valores) -> list:
    v = pd.Series(valores, dtype=float)
    v = v[np.isfinite(v)]
    if v.empty:
        return []
    cortes = sorted(set(np.quantile(v, [0.2, 0.4, 0.6, 0.8]).round(10)))
    return [c for c in cortes if v.min() < c < v.max()] or []


def clase(v, cortes) -> int:
    if v is None or not np.isfinite(v):
        return -1
    return int(np.searchsorted(cortes, v, side="right"))


def clasificar(tabla: pd.DataFrame, modo: str, paleta: str, fondo_oscuro: bool) -> tuple[list, list]:
    """Color de cada zona y la leyenda por rangos [(color, texto)]."""
    if tabla.empty:
        return [], []
    if modo == "variacion" and ("tendencia" in tabla.columns or "variacion" in tabla.columns):
        # `tendencia` = variación, o ±100% si la zona apareció o desapareció.
        colores = SEMAFORO_VAR[0 if fondo_oscuro else 1]
        columna = "tendencia" if "tendencia" in tabla.columns else "variacion"
        cls = [clase(v, CORTES_VARIACION) for v in pd.to_numeric(tabla[columna], errors="coerce")]
        cuenta = pd.Series(cls).value_counts()
        textos = ["Bajó más de 20%", "Bajó 5% a 20%", "Estable (±5%)", "Subió 5% a 20%", "Subió más de 20%"]
        leyenda = [(colores[i], f"{textos[i]} · {int(cuenta.get(i, 0))}") for i in range(5)]
        return [colores[c] if c >= 0 else None for c in cls], leyenda[::-1]
    if modo == "meta" and "cumplimiento" in tabla.columns:
        colores = SEMAFORO[0 if fondo_oscuro else 1]
        cls = [clase(v, CORTES_META) for v in pd.to_numeric(tabla["cumplimiento"], errors="coerce")]
        cuenta = pd.Series(cls).value_counts()
        textos = ["Menos de 90% de la meta", "90% a 100%", "Cumple (100% o más)"]
        leyenda = [(colores[i], f"{textos[i]} · {int(cuenta.get(i, 0))}") for i in range(3)]
        return [colores[c] if c >= 0 else None for c in cls], leyenda[::-1]
    columna = "por_10k" if modo == "penetracion" and "por_10k" in tabla.columns else "valor"
    valores = pd.to_numeric(tabla[columna], errors="coerce")
    rampa = rampa_de(paleta, fondo_oscuro)
    cortes = cortes_quintiles(valores)
    # Con pocos valores distintos hay menos rangos: se usan los tonos del extremo alto.
    paso = rampa[len(rampa) - len(cortes) - 1:]
    cls = [clase(v, cortes) for v in valores]
    limites = [valores.min()] + cortes + [valores.max()]
    sufijo = " por 10.000 hab." if columna == "por_10k" else ""
    leyenda = [(paso[i], f"{T.cifra(limites[i])} – {T.cifra(limites[i + 1])}{sufijo}") for i in range(len(paso))]
    return [paso[c] if c >= 0 else None for c in cls], leyenda[::-1]


def ley_html(leyenda: list) -> str:
    if not leyenda:
        return ""
    return '<div class="terr-ley">' + "".join(
        f'<div><i style="background:rgb{tuple(c)}"></i>{html.escape(t)}</div>' for c, t in leyenda) + "</div>"


# Ficha flotante (al pasar el cursor): cada capa que se puede señalar trae
# TODOS estos campos, aunque vayan vacíos; si falta uno, deck.gl muestra el
# «{campo}» tal cual. Streamlit ESCAPA el valor de cada campo (un trozo de
# HTML salía como texto crudo), así que la estructura y los estilos viven en
# la plantilla de `tooltip` y los campos solo traen texto o colores: el
# chip del semáforo (`var_*`) y el bloque del plan (`plan_*`) se «apagan»
# con fondo transparente y relleno 0 cuando no aplican.
CAMPOS_TT = ("valor_txt", "pos_txt", "part_txt", "var_txt", "var_bg", "var_fg", "var_pad", "cump_txt", "pob_txt",
              "pen_txt", "unidad", "plan_tit", "plan_resp", "plan_paso", "plan_borde", "plan_bg", "plan_pad", "hint")
CHIP_TT = {"bajo": ("#fee2e2", "#b91c1c"), "estable": ("#fef9c3", "#a16207"), "subio": ("#dcfce7", "#15803d"),
            "oport": ("#f3e8ff", "#7e22ce")}
TONO_HEX = {"bajo": "#ef4444", "estable": "#eab308", "subio": "#22c55e", "oport": "#a855f7"}
TONO_RGB = {"bajo": [239, 68, 68], "estable": [234, 179, 8], "subio": [34, 197, 94], "oport": [168, 85, 247]}
HINT = "👆 Clic para abrir su ficha"
SIN_CHIP = {"var_txt": "", "var_bg": "transparent", "var_fg": "inherit", "var_pad": "0"}
SIN_PLAN = {"plan_tit": "", "plan_resp": "", "plan_paso": "", "plan_borde": "transparent", "plan_bg": "transparent",
             "plan_pad": "0"}


def clave(z) -> str:
    """La misma clave para una zona venga como 125, 125.0 o "125"; los códigos de departamento quedan como texto."""
    try:
        return str(int(float(z))) if not (isinstance(z, str) and z.startswith("0")) else z
    except (TypeError, ValueError):
        return str(z)


def chip(texto: str, estado) -> dict:
    """Campos del chip de color de la ficha flotante."""
    if not texto:
        return dict(SIN_CHIP)
    fondo, color = CHIP_TT.get(estado, ("rgba(148,163,184,.22)", "inherit"))
    return {"var_txt": texto, "var_bg": fondo, "var_fg": color, "var_pad": "3px 10px"}


def bloque_plan(titulo: str, resp: str, paso: str, tono: str) -> dict:
    """Campos del bloque del plan de la ficha flotante."""
    paso = (paso or "").replace("**", "")
    paso = paso if len(paso) <= 130 else paso[:127] + "…"
    return {"plan_tit": titulo, "plan_resp": f"👤 {resp}" if resp else "", "plan_paso": f"→ {paso}" if paso else "",
            "plan_borde": TONO_HEX.get(tono, "#94a3b8"), "plan_bg": "rgba(148,163,184,.14)", "plan_pad": "8px 10px"}


def plan_tooltip(pl: Optional[dict]) -> dict:
    """Lo que dice el plan de cada zona, para la ficha flotante: {clave: campos plan_*}."""
    if not pl or pl.get("zonas") is None or pl["zonas"].empty:
        return {}
    salida = {}
    for _, r in pl["zonas"].iterrows():
        e = P.ESTRATEGIAS[r["estrategia"]]
        vale = f" · vale ≈ {T.cifra(r['valor_mes'])} al mes" if r["valor_mes"] > 0 else ""
        salida[clave(r["zona"])] = bloque_plan(f"{e['icono']} Plan: {e['titulo']}{vale}", str(r["responsable"] or ""),
                                                 r["pasos"][0] if r["pasos"] else "", e["tono"])
    return salida


def textos(tabla: pd.DataFrame, n: int, unidad: str, plan_info: Optional[dict] = None, hint: str = HINT) -> pd.DataFrame:
    t = tabla.copy()
    t["valor_txt"] = t["valor"].map(T.cifra)
    t["pos_txt"] = t["posicion"].map(lambda p: f"· {int(p)}.º de {n}")
    t["part_txt"] = t["participacion"].map(lambda x: f"{x:.1%} del total" if pd.notna(x) else "") \
        if "participacion" in t.columns else ""
    if "variacion" in t.columns:
        tend = t["tendencia"] if "tendencia" in t.columns else pd.Series(np.nan, index=t.index)
        estado = t["estado"] if "estado" in t.columns else pd.Series(None, index=t.index)

        def _var(x, td, e):
            icono = ESTADO_ICONO.get(e, "")
            if pd.notna(x):
                return f"{icono} {x:+.0%} vs mes anterior".strip()
            if td == 1:
                return f"{icono} empezó a tener actividad".strip()
            if td == -1:
                return f"{icono} sin actividad en el último mes".strip()
            return "sin dato del mes anterior"
        chips = [chip(_var(x, td, e), e) for x, td, e in zip(t["variacion"], tend, estado)]
    else:
        chips = [dict(SIN_CHIP)] * len(t)
    for k in SIN_CHIP:
        t[k] = [c[k] for c in chips]
    t["cump_txt"] = t["cumplimiento"].map(lambda x: f"{x:.0%} de la meta" if pd.notna(x) else "") \
        if "cumplimiento" in t.columns else ""
    t["pob_txt"] = t["poblacion"].map(lambda x: f"{T.cifra(x)} habitantes" if pd.notna(x) and x > 0 else "") \
        if "poblacion" in t.columns else ""
    t["pen_txt"] = t["por_10k"].map(lambda x: f"{T.cifra(x)} por cada 10.000 hab." if pd.notna(x) else "") \
        if "por_10k" in t.columns else ""
    t["unidad"] = unidad
    bloques = [(plan_info or {}).get(clave(z), SIN_PLAN) for z in t["zona"]]
    for k in SIN_PLAN:
        t[k] = [b[k] for b in bloques]
    t["hint"] = hint
    return t


def campos(r) -> dict:
    """Los campos de la ficha flotante de una fila de `textos`."""
    return {k: getattr(r, k, "") for k in CAMPOS_TT}


def tooltip(fondo_oscuro: bool) -> dict:
    """La ficha flotante: nombre grande, valor, semáforo, lo que dice el plan y la pista del clic."""
    fondo, texto, suave, acento = (("rgba(12,17,26,.96)", "#eef2f7", "#9aa4b2", "#5ee0d4") if fondo_oscuro
                                   else ("rgba(255,255,255,.98)", "#131826", "#5b6473", "#0f8a85"))
    return {
        "html": ("<div style='font-family:Inter,Segoe UI,sans-serif;min-width:230px;max-width:330px'>"
                 "<div style='font-size:17px;font-weight:800;letter-spacing:-.01em;line-height:1.2'>{nombre}</div>"
                 f"<div style='font-size:12px;color:{suave};margin-top:2px'>{{departamento}} {{pos_txt}}</div>"
                 f"<div style='font-size:24px;font-weight:800;color:{acento};margin-top:7px;line-height:1.1'>{{valor_txt}} "
                 f"<span style='font-size:11.5px;color:{suave};font-weight:600'>{{unidad}}</span></div>"
                 "<div><span style='display:inline-block;margin-top:7px;background:{var_bg};color:{var_fg};padding:{var_pad};"
                 "border-radius:99px;font-size:12px;font-weight:800'>{var_txt}</span></div>"
                 "<div style='font-size:12.5px;margin-top:5px;font-weight:600'>{cump_txt}</div>"
                 f"<div style='font-size:12px;color:{suave};margin-top:4px;line-height:1.45'>{{part_txt}}<br>{{pob_txt}}<br>{{pen_txt}}</div>"
                 "<div style='margin-top:9px;padding:{plan_pad};border-radius:9px;border-left:4px solid {plan_borde};"
                 "background:{plan_bg};white-space:normal'><div style='font-size:12.5px;font-weight:800'>{plan_tit}</div>"
                 "<div style='font-size:12px;margin-top:2px'>{plan_resp}</div>"
                 "<div style='font-size:12px;margin-top:2px;opacity:.85'>{plan_paso}</div></div>"
                 f"<div style='font-size:11.5px;color:{acento};margin-top:8px;font-weight:700'>{{hint}}</div></div>"),
        "style": {"backgroundColor": fondo, "color": texto, "border": "1px solid #2a313d" if fondo_oscuro else "1px solid #d8dce6",
                  "borderRadius": "14px", "padding": "12px 14px", "boxShadow": "0 14px 40px rgba(0,0,0,.35)",
                  "backdropFilter": "blur(6px)"},
    }


def vista_inicial(lat, lon, inclinacion: float):
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


VACIO = {"valor_txt": "Sin actividad", "pos_txt": "", "part_txt": "", "cump_txt": "", "pob_txt": "",
          "pen_txt": "", "unidad": "", "hint": HINT, **SIN_CHIP, **SIN_PLAN}


def feature(geom, props) -> dict:
    # Los campos también arriba: el tooltip de deck.gl lee el objeto elegido,
    # que en un GeoJSON es el feature, no sus propiedades.
    return {"type": "Feature", "geometry": geom, "properties": props, **props}


def etiquetas_sin_choque(tabla: pd.DataFrame, maximo: int = 10) -> pd.DataFrame:
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


def construir_mapa(capas_on: dict, zm: pd.DataFrame, zd: pd.DataFrame, hex_t: pd.DataFrame, puntos: pd.DataFrame,
                    crecer: dict, color: str, paleta: str, fondo: str, escala: float, radio_km: float, unidad: str,
                    seleccion: Optional[dict] = None, inclinada: bool = False, ligero: bool = False,
                    plan: Optional[dict] = None, exageracion: float = EXAGERACION, rumbo: Optional[float] = None):
    """El objeto pydeck y las leyendas de cada capa activa.

    `seleccion` = la zona abierta en la ficha: se resalta con un borde neón y
    la vista vuela hacia ella. `inclinada` inclina también las capas planas.
    `ligero` = para el informe HTML: sin los municipios que no tienen dato
    (con todos, el archivo pasa de ~1 a ~5 MB). `plan` = `core/territorio_plan.plan`:
    su estrategia va en la ficha flotante de cada zona y sus jugadas y
    aperturas se dibujan como pines numerados y arcos de expansión.

    Contexto (cualquier archivo): `capas_on["relieve"]` sombrea las montañas
    debajo de los datos; `capas_on["montanas"]` las levanta en 3D (exageradas
    `exageracion` veces) y sube cada dato a su altitud; `capas_on["edificios"]`
    muestra los edificios en 3D al acercarse a una ciudad (zoom 13+). El fondo
    «Satélite» pone la foto satelital. `rumbo` = hacia dónde mira la cámara al
    volar a la zona elegida (el modo presentación lo va girando)."""
    import pydeck as pdk
    oscuro = fondo_oscuro(fondo)
    capas, leyendas = [], {}
    mpios = T.municipios()
    # Montañas 3D: cada dato se sube a la altitud de su lugar (×exageración).
    montanas = bool(capas_on.get("montanas"))
    relieve_x = float(exageracion) if montanas else 0.0

    def suelo(lat, lon) -> np.ndarray:
        """Altura del suelo bajo cada dato: 0 en el mapa plano; la del terreno con montañas."""
        if not montanas:
            return np.zeros(len(np.atleast_1d(lat)))
        return T.altitudes(lat, lon) * relieve_x + _SOBRE_TERRENO_M

    def geometrias(nombre: str) -> list:
        fuente = T.municipios_geojson() if nombre == "municipios" else T.departamentos_geojson()
        return _geojson_drapeado(nombre, relieve_x) if montanas else [f["geometry"] for f in fuente["features"]]

    encima = _ENCIMA if montanas else None

    # 0) Fondo: foto satelital, relieve (plano sombreado o montañas en 3D).
    satelite = fondo == "Satélite"
    if montanas:
        capas.append(_raster(pdk, "montanas", SATELITE_URL if satelite else SOMBRA_URL[oscuro], 1.0, relieve_x))
    elif satelite:
        # Híbrido: la foto con los nombres de lugares encima. Ya trae sus
        # sombras: ponerle además el relieve la ensuciaría.
        capas.append(_raster(pdk, "satelite", SATELITE_URL, nivel=-120))
        capas.append(_raster(pdk, "satelite_nombres", NOMBRES_SATELITE, nivel=-60))
    elif capas_on.get("relieve"):
        # Mapa base + sombras multiplicadas + nombres encima. Las sombras se
        # aplican 3 veces sobre fondo oscuro (si no, casi no se notan) y 2 sobre claro.
        base, nombres = BASE_RELIEVE.get(fondo, BASE_RELIEVE["Oscuro" if oscuro else "Claro"])
        capas.append(_raster(pdk, "relieve_base", base, nivel=-140))
        for i in range(3 if oscuro else 2):
            capas.append(_raster(pdk, f"relieve{'' if i == 0 else i + 1}", SOMBRA_URL[False], nivel=-120 + 10 * i,
                                 mezcla=_MULTIPLICAR))
        if nombres:
            capas.append(_raster(pdk, "relieve_nombres", nombres, nivel=-60))
    # Bordes finos y claros entre municipios con dato; los que no tienen
    # dato casi desaparecen (antes, 1.122 contornos de color armaban una
    # malla que tapaba el mapa).
    linea = [255, 255, 255, 55] if oscuro else [255, 255, 255, 210]
    linea_vacia = [150, 165, 190, 22] if oscuro else [110, 120, 140, 40]
    sin_dato = [70, 80, 100, 40] if oscuro else [205, 210, 220, 70]
    vistas_lat, vistas_lon = [], []
    inclinacion = 0
    info_plan = plan_tooltip(plan)
    plan_mpio = info_plan if plan and plan.get("nivel") == "municipio" else None
    plan_depto = info_plan if plan and plan.get("nivel") == "departamento" else None
    # Altura de cada zona cuando está levantada en 3D: los nombres y los pines
    # se ponen ENCIMA de la columna (en el suelo, las columnas los tapaban).
    tope_m = float(zm["valor"].clip(lower=0).max()) if not zm.empty else 1.0
    tope_m = tope_m or 1.0
    factor_m = 320_000 if capas_on.get("columnas") else 260_000 if (capas_on.get("mpios") and capas_on.get("mpios3d")) else 0
    alto_mpio = ({clave(z): max(float(v), 0) / tope_m * factor_m * escala for z, v in zip(zm["zona"], zm["valor"])}
                 if factor_m and not zm.empty else {})

    # 1) Contexto: población DANE (abajo de todo).
    if capas_on.get("poblacion"):
        dens = mpios["poblacion"] / mpios["area_km2"].replace(0, np.nan)
        cortes = cortes_quintiles(np.log10(dens.clip(lower=0.1)))
        rampa = PIZARRA[0] if oscuro else PIZARRA[1]
        feats = []
        for f, geom in zip(T.municipios_geojson()["features"], geometrias("municipios")):
            i = f["properties"]["idx"]
            if i < 0:
                continue
            d = dens.iloc[i]
            c = clase(np.log10(max(d, 0.1)) if np.isfinite(d) else np.nan, cortes)
            r = mpios.iloc[i]
            feats.append(feature(geom, {
                "color": list(rampa[c]) + [200] if c >= 0 else sin_dato, "nombre": r["municipio"],
                "departamento": r["departamento"], "zona": str(i), "nivel": "municipio",
                **VACIO, "valor_txt": f"{T.cifra(r['poblacion'])} hab.", "pob_txt": f"{d:,.0f} hab/km²" if np.isfinite(d) else "",
                "unidad": "", "hint": ""}))
        capas.append(pdk.Layer("GeoJsonLayer", data={"type": "FeatureCollection", "features": feats}, id="poblacion",
                               filled=True, stroked=True, get_fill_color="properties.color", get_line_color=linea_vacia,
                               line_width_min_pixels=0.3, pickable=not capas_on.get("mpios"), parameters=encima))
        limites = [10 ** x for x in ([np.log10(max(dens.min(), 0.1))] + cortes + [np.log10(dens.max())])]
        leyendas["poblacion"] = [(rampa[i], f"{T.cifra(limites[i])} – {T.cifra(limites[i + 1])} hab/km²")
                                 for i in range(len(cortes) + 1)][::-1]

    # Con relieve, satélite o edificios debajo, el color de las zonas se deja
    # ver a través: de lejos se transparenta la cordillera y de cerca se ven
    # las calles y los edificios (opaco, una ciudad entera quedaba de un solo
    # color). deck.gl no deja cambiar la transparencia según el zoom.
    alfa_zona = 185 if (capas_on.get("relieve") or capas_on.get("edificios") or satelite or montanas) else 235

    # 2) Municipios coloreados (y levantados en 3D si se pide).
    if capas_on.get("mpios") and not zm.empty and "cod_mpio" in zm.columns:
        t = textos(zm, len(zm), unidad, plan_mpio)
        colores, leyendas["mpios"] = clasificar(t, color, paleta, oscuro)
        tope = float(t["valor"].clip(lower=0).max()) or 1.0
        por_idx = {int(z): (r, c) for z, r, c in zip(t["zona"], t.itertuples(), colores)}
        feats = []
        for f, geom in zip(T.municipios_geojson()["features"], geometrias("municipios")):
            i = f["properties"]["idx"]
            dato = por_idx.get(i)
            if dato is None:
                if not capas_on.get("poblacion") and not ligero:
                    r = mpios.iloc[i] if i >= 0 else None
                    feats.append(feature(geom, {
                        "color": sin_dato, "linea": linea_vacia, "altura": 0, "nombre": r["municipio"] if r is not None else "",
                        "departamento": r["departamento"] if r is not None else "", "zona": str(i), "nivel": "municipio",
                        **VACIO, "pob_txt": f"{T.cifra(r['poblacion'])} habitantes" if r is not None else "",
                        **(plan_mpio or {}).get(str(i), SIN_PLAN)}))
                continue
            r, c = dato
            feats.append(feature(geom, {
                "color": list(c) + [alfa_zona] if c else sin_dato, "linea": linea, "altura": max(r.valor, 0) / tope * 260_000 * escala,
                "nombre": r.nombre, "departamento": r.departamento, "zona": str(i), "nivel": "municipio", **campos(r)}))
        # Sobre las montañas no se levantan: el relieve ya es el 3D y un bloque
        # levantado desde una ladera quedaría a medio enterrar.
        en3d = bool(capas_on.get("mpios3d")) and not montanas
        capas.append(pdk.Layer("GeoJsonLayer", data={"type": "FeatureCollection", "features": feats}, id="mpios",
                               filled=True, stroked=True, extruded=en3d, wireframe=False,
                               get_elevation="properties.altura", get_fill_color="properties.color",
                               get_line_color="properties.linea", line_width_min_pixels=0.6, pickable=True, auto_highlight=True,
                               highlight_color=[94, 224, 212, 220], parameters=encima))
        vistas_lat += list(t["lat"]); vistas_lon += list(t["lon"])
        inclinacion = max(inclinacion, 50 if en3d else 0)

    # 3) Departamentos levantados en 3D.
    if capas_on.get("deptos") and not zd.empty:
        t = textos(zd, len(zd), unidad, plan_depto)
        colores, leyendas["deptos"] = clasificar(t, color, paleta, oscuro)
        tope = float(t["valor"].clip(lower=0).max()) or 1.0
        por_cod = {str(z): (r, c) for z, r, c in zip(t["zona"], t.itertuples(), colores)}
        feats = []
        for f, geom in zip(T.departamentos_geojson()["features"], geometrias("departamentos")):
            cod = f["properties"]["cod_dpto"]
            dato = por_cod.get(cod)
            base = {"nombre": f["properties"]["departamento"], "departamento": "Departamento", "zona": cod, "nivel": "departamento"}
            if dato:
                r, c = dato
                base.update(altura=max(float(r.valor), 0) / tope * 320_000 * escala, color=list(c) + [215] if c else sin_dato,
                            **campos(r))
            else:
                base.update(altura=0, color=sin_dato, **VACIO)
            feats.append(feature(geom, base))
        # Con montañas, el departamento se pinta sobre el relieve en vez de
        # levantarse como un bloque (que taparía la cordillera entera).
        capas.append(pdk.Layer("GeoJsonLayer", data={"type": "FeatureCollection", "features": feats}, id="deptos",
                               extruded=not montanas, wireframe=False, get_elevation="properties.altura",
                               get_fill_color="properties.color", get_line_color=linea, line_width_min_pixels=1,
                               pickable=True, auto_highlight=True, highlight_color=[94, 224, 212, 200],
                               parameters=encima))
        vistas_lat += list(t["lat"]); vistas_lon += list(t["lon"])
        inclinacion = max(inclinacion, 48)
    else:
        # Contornos de departamento siempre, con brillo: una línea ancha y
        # transparente debajo de una fina y nítida. Con montañas, siguen el relieve.
        contornos = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": g, "properties": {}} for g in geometrias("departamentos")]}
        capas.append(pdk.Layer("GeoJsonLayer", data=contornos, id="contornos_brillo", stroked=True,
                               filled=False, get_line_color=linea[:3] + [40 if oscuro else 30],
                               line_width_min_pixels=6, pickable=False, parameters=encima))
        capas.append(pdk.Layer("GeoJsonLayer", data=contornos, id="contornos", stroked=True,
                               filled=False, get_line_color=([140, 255, 240, 200] if oscuro else [15, 110, 105, 170]),
                               line_width_min_pixels=1.1, pickable=False, parameters=encima))

    # 3b) Edificios 3D al acercarse a una ciudad. Solo cargan desde el zoom 13
    # (un barrio): a la escala del país no se verían y serían millones. Con
    # montañas no: los edificios no saben la altitud y quedarían enterrados.
    if capas_on.get("edificios") and not montanas:
        capas.append(pdk.Layer(
            "MVTLayer", data=EDIFICIOS_URL, id="edificios", load_options={"mvt": {"layers": ["building"]}},
            min_zoom=13, max_zoom=14, extruded=True, get_elevation="properties.render_height || 8",
            # Más claros cuanto más altos, para que las torres se lean como torres.
            get_fill_color=("properties.render_height > 60 ? [196, 205, 228, 245] : properties.render_height > 20 "
                            "? [150, 162, 192, 240] : [104, 116, 146, 235]") if oscuro else
                           ("properties.render_height > 60 ? [148, 163, 184, 245] : properties.render_height > 20 "
                            "? [190, 200, 214, 240] : [222, 227, 235, 235]"),
            material={"ambient": 0.4, "diffuse": 0.65, "shininess": 24, "specularColor": [190, 205, 235]},
            pickable=False))

    # 4) Columnas 3D por municipio.
    if capas_on.get("columnas") and not zm.empty:
        t = textos(zm, len(zm), unidad, plan_mpio)
        colores, ley = clasificar(t, color, paleta, oscuro)
        leyendas.setdefault("columnas", ley)
        tope = float(t["valor"].clip(lower=0).max()) or 1.0
        t["altura"] = t["valor"].clip(lower=0) / tope * 320_000 * escala
        t["color"] = [list(c) + [240] if c else sin_dato for c in colores]
        t["zona"] = t["zona"].astype(str)
        # Solo las columnas que usa la capa: un DataFrame con listas, fechas o
        # NaN en otras columnas puede dejar la capa sin ficha flotante.
        cols = ["lon", "lat", "altura", "color", "zona", "nombre", "departamento", *CAMPOS_TT]
        datos_col = t[cols].copy()
        datos_col["nivel"] = "municipio"
        datos_col["suelo"] = suelo(datos_col["lat"], datos_col["lon"])
        # Un disco ancho y bajo debajo de cada columna: marca dónde está aunque
        # la columna sea baja, y da el brillo de «base» de los mapas tipo kepler.
        capas.append(pdk.Layer("ScatterplotLayer", data=datos_col[["lon", "lat", "suelo", "color"]], id="zonas_base",
                               get_position=["lon", "lat", "suelo"], get_radius=14_000, radius_min_pixels=4,
                               get_fill_color="color", opacity=0.22, pickable=False))
        # Cilindros lisos con brillo: la luz da volumen y se lee el redondeo.
        capas.append(pdk.Layer("ColumnLayer", data=datos_col, id="zonas", get_position=["lon", "lat", "suelo"],
                               get_elevation="altura", elevation_scale=1, radius=10_000, disk_resolution=32,
                               extruded=True, coverage=0.92, get_fill_color="color", pickable=True, auto_highlight=True,
                               highlight_color=[255, 255, 255, 230], material=_BRILLO))
        vistas_lat += list(t["lat"]); vistas_lon += list(t["lon"])
        inclinacion = max(inclinacion, 52)

    # 5) Hexágonos 3D (ya agregados en core/territorio.hexagonos).
    if capas_on.get("hex") and not hex_t.empty:
        t = textos(hex_t, len(hex_t), unidad, hint="")
        colores, leyendas["hex"] = clasificar(t, "volumen", paleta, oscuro)
        tope = float(t["valor"].clip(lower=0).max()) or 1.0
        t["altura"] = t["valor"].clip(lower=0) / tope * 300_000 * escala
        t["color"] = [list(c) + [240] if c else sin_dato for c in colores]
        t = t[["lon", "lat", "altura", "color", "zona", "nombre", "departamento", *CAMPOS_TT]].copy()
        t["suelo"] = suelo(t["lat"], t["lon"])
        capas.append(pdk.Layer("ColumnLayer", data=t, id="hexagonos", get_position=["lon", "lat", "suelo"],
                               get_elevation="altura", elevation_scale=1, radius=radio_km * 1000 * 0.94, disk_resolution=6,
                               angle=90, extruded=True, get_fill_color="color", pickable=True, auto_highlight=True,
                               highlight_color=[94, 224, 212, 255], material=_BRILLO))
        vistas_lat += list(t["lat"]); vistas_lon += list(t["lon"])
        inclinacion = max(inclinacion, 50)

    # 6) Mapa de calor. Se pinta sobre el suelo plano: con montañas quedaría
    # debajo de la cordillera, así que ahí no se dibuja (la consola lo avisa).
    if capas_on.get("calor") and not montanas:
        base = puntos if not puntos.empty else (zm.rename(columns={"valor": "w"})[["lat", "lon", "w"]] if not zm.empty else pd.DataFrame())
        if not base.empty:
            rampa = rampa_de(paleta, True)
            capas.append(pdk.Layer("HeatmapLayer", data=base, id="calor", get_position=["lon", "lat"], get_weight="w",
                                   radius_pixels=55, intensity=1.1, threshold=0.04, aggregation="SUM",
                                   color_range=[list(c) for c in rampa] + [[255, 255, 230]]))
            leyendas["calor"] = [(rampa[-1], "alta concentración"), (rampa[1], "baja concentración")]
            vistas_lat += list(base["lat"]); vistas_lon += list(base["lon"])

    # 7) Puntos.
    if capas_on.get("puntos") and not puntos.empty:
        p = puntos.copy()
        tope = float(p["w"].clip(lower=0).max()) or 1.0
        rampa = rampa_de(paleta, oscuro)
        p["r"] = 300 + np.sqrt(p["w"].clip(lower=0) / tope) * 6000
        p["color"] = [list(rampa[min(4, int(math.sqrt(max(w, 0) / tope) * 5))]) + [220] for w in p["w"]]
        p["suelo"] = suelo(p["lat"], p["lon"])
        capas.append(pdk.Layer("ScatterplotLayer", data=p, id="puntos", get_position=["lon", "lat", "suelo"], get_radius="r",
                               get_fill_color="color", radius_min_pixels=2, radius_max_pixels=30, opacity=0.9,
                               stroked=True, get_line_color=[255, 255, 255, 90] if oscuro else [0, 0, 0, 60],
                               line_width_min_pixels=0.5))
        vistas_lat += list(p["lat"]); vistas_lon += list(p["lon"])

    # 8) Blancos de expansión: municipios grandes sin presencia, resaltados.
    blancos = crecer.get("blancos") if crecer else None
    if capas_on.get("blancos") and blancos is not None and len(blancos):
        codigos = {c: r for c, r in zip(blancos["cod_mpio"], blancos.itertuples())}
        feats = []
        for f, geom in zip(T.municipios_geojson()["features"], geometrias("municipios")):
            r = codigos.get(f["properties"]["cod_mpio"])
            if r is None:
                continue
            feats.append(feature(geom, {
                "nombre": r.municipio, "departamento": f"{r.departamento} · sin presencia", "zona": str(f["properties"]["idx"]),
                "nivel": "blanco", **VACIO, "valor_txt": f"Potencial {T.cifra(r.potencial)}", "pos_txt": "· oportunidad",
                "pob_txt": f"{T.cifra(r.poblacion)} habitantes", **chip("🎯 Sin presencia: para abrir", "oport")}))
        # Violeta: el amarillo es «estable» en el semáforo y se confundían.
        neon = [147, 51, 234] if not oscuro else [192, 132, 252]
        capas.append(pdk.Layer("GeoJsonLayer", data={"type": "FeatureCollection", "features": feats}, id="blancos",
                               filled=True, stroked=True, get_fill_color=neon + [55], get_line_color=neon + [255],
                               line_width_min_pixels=2.5, pickable=True, auto_highlight=True, parameters=encima))
        leyendas["blancos"] = [(tuple(neon), f"{len(feats)} municipios grandes sin presencia")]

    # 9) Nombres de las zonas principales.
    if capas_on.get("etiquetas"):
        fuente = zd if (capas_on.get("deptos") and not zd.empty and zm.empty) else zm
        if fuente is not None and not fuente.empty:
            top = etiquetas_sin_choque(fuente, maximo=8 if alto_mpio else 10).copy()
            # Con tildes y eñes: `character_set="auto"` hace que deck.gl arme la
            # fuente con las letras que traen los nombres. Antes salía «auto»
            # sin comillas, pydeck lo convertía en una fórmula y no dibujaba
            # nada, así que los nombres iban sin tildes («Medellin»). Ver `_lit`.
            def _var(r):
                v, td = r.get("variacion", np.nan), r.get("tendencia", np.nan)
                if pd.notna(v):
                    return f"  {v:+.0%}"
                return "  nuevo" if td == 1 else "  sin venta" if td == -1 else ""
            top["texto"] = (top["nombre"].astype(str) + "  " + top["valor"].map(T.cifra)
                            + top.apply(_var, axis=1))
            # Píldoras con el borde del color del semáforo de la zona.
            neutro = [94, 224, 212, 210] if oscuro else [15, 120, 115, 200]
            estados = top["estado"] if "estado" in top.columns else pd.Series(None, index=top.index)
            top["borde"] = [list(ESTADO_RGB[e]) + [255] if e in ESTADO_RGB else neutro for e in estados]
            # En 3D, el nombre va encima de su columna; en plano, en el suelo.
            if fuente is zm:
                top["z"] = [alto_mpio.get(clave(z), 0.0) + (4_000 if alto_mpio else 0) for z in top["zona"]]
            else:
                tope_d = float(zd["valor"].clip(lower=0).max()) or 1.0
                # Con montañas el departamento va plano sobre el relieve: el nombre, a ras.
                top["z"] = 0.0 if montanas else top["valor"].clip(lower=0) / tope_d * 320_000 * escala + 4_000
            top["z"] = top["z"] + suelo(top["lat"], top["lon"])
            capas.append(pdk.Layer("TextLayer", data=top[["lon", "lat", "z", "texto", "borde"]], id="etiquetas",
                                   get_position=["lon", "lat", "z"], get_text="texto", character_set=_lit("auto"),
                                   get_size=14, get_color=[236, 241, 246] if oscuro else [19, 24, 38],
                                   # Con pines del plan, el nombre sube un poco más para no quedar debajo del pin.
                                   get_pixel_offset=[0, -34 if capas_on.get("jugadas") else -18], billboard=True, background=True,
                                   get_background_color=[13, 18, 28, 230] if oscuro else [255, 255, 255, 240],
                                   background_padding=[8, 4, 8, 4], get_border_color="borde",
                                   get_border_width=2))

    # 10) Focos del mes: anillos sobre las 3 mayores caídas (rojo) y subidas (verde).
    if capas_on.get("focos") and not zm.empty and "cambio" in zm.columns:
        caidas = zm[zm["cambio"] < 0].sort_values("cambio").head(3)
        subidas = zm[zm["cambio"] > 0].sort_values("cambio", ascending=False).head(3)
        focos = pd.concat([caidas.assign(borde=[list(ESTADO_RGB["bajo"]) + [255]] * len(caidas)),
                           subidas.assign(borde=[list(ESTADO_RGB["subio"]) + [255]] * len(subidas))])
        if len(focos):
            focos = focos[["lon", "lat", "borde"]].copy()
            focos["brillo"] = [b[:3] + [60] for b in focos["borde"]]
            focos["suelo"] = suelo(focos["lat"], focos["lon"])
            capas.append(pdk.Layer("ScatterplotLayer", data=focos, id="focos_brillo", get_position=["lon", "lat", "suelo"],
                                   get_radius=16_000, radius_min_pixels=20, radius_max_pixels=46, filled=False,
                                   stroked=True, get_line_color="brillo", line_width_min_pixels=8, pickable=False))
            capas.append(pdk.Layer("ScatterplotLayer", data=focos, id="focos", get_position=["lon", "lat", "suelo"],
                                   get_radius=16_000, radius_min_pixels=20, radius_max_pixels=46, filled=False,
                                   stroked=True, get_line_color="borde", line_width_min_pixels=2.5, pickable=False))
            leyendas["focos"] = [(ESTADO_RGB["subio"], f"{len(subidas)} mayores subidas"),
                                 (ESTADO_RGB["bajo"], f"{len(caidas)} mayores caídas")]

    # 11) Rutas de expansión: un arco desde la zona más cercana de la red a cada municipio por abrir.
    aperturas = plan.get("aperturas") if plan else None
    if capas_on.get("rutas") and aperturas is not None and len(aperturas) and "base_lat" in aperturas.columns:
        a = aperturas.copy()
        idx_m = {c: i for i, c in zip(mpios.index, mpios["cod_mpio"])}
        arcos = pd.DataFrame({
            "base_lon": a["base_lon"], "base_lat": a["base_lat"], "lon": a["lon"].astype(float), "lat": a["lat"].astype(float),
            "nombre": "Abrir " + a["municipio"].astype(str), "departamento": a["departamento"].astype(str),
            "zona": [str(idx_m.get(c, -1)) for c in a["cod_mpio"]], "nivel": "blanco",
            **{k: "" for k in CAMPOS_TT},
        })
        arcos["valor_txt"] = ["≈ " + T.cifra(v) for v in a["potencial_mes"]]
        arcos["unidad"] = "al mes de potencial"
        arcos["pos_txt"] = [f"· desde {b} ({k:.0f} km)" for b, k in zip(a["base"], a["distancia_km"])]
        arcos["pob_txt"] = [f"{T.cifra(p)} habitantes · {T.cifra(u)} urbanos" for p, u in zip(a["poblacion"], a["poblacion_cabecera"])]
        for k, v in chip("🎯 Dónde abrir", "oport").items():
            arcos[k] = v
        bloques = [bloque_plan("🎯 Plan: Abrir · 90 días", str(ag or ""), m, "oport")
                   for m, ag in zip(a["modelo"], a["agente_sugerido"])]
        for k in SIN_PLAN:
            arcos[k] = [b[k] for b in bloques]
        arcos["hint"] = HINT
        arcos["base_z"] = suelo(arcos["base_lat"], arcos["base_lon"])
        arcos["suelo"] = suelo(arcos["lat"], arcos["lon"])
        capas.append(pdk.Layer("ArcLayer", data=arcos, id="rutas", get_source_position=["base_lon", "base_lat", "base_z"],
                               get_target_position=["lon", "lat", "suelo"], get_source_color=[45, 212, 191, 230],
                               get_target_color=[192, 132, 252, 255], get_width=5, width_min_pixels=3,
                               get_height=0.8, pickable=True, auto_highlight=True, highlight_color=[255, 255, 255, 255]))
        capas.append(pdk.Layer("ScatterplotLayer", data=arcos[["lon", "lat", "suelo"]], id="rutas_destino",
                               get_position=["lon", "lat", "suelo"],
                               get_radius=6_000, radius_min_pixels=7, radius_max_pixels=16, filled=True, stroked=True,
                               get_fill_color=[192, 132, 252, 90], get_line_color=[192, 132, 252, 255],
                               line_width_min_pixels=2, pickable=False))
        leyendas["rutas"] = [((45, 212, 191), "sale de tu zona más cercana"), ((192, 132, 252), f"llega a {len(a)} municipios por abrir")]

    # 12) Las jugadas del plan: pines numerados, el mismo número de las tarjetas.
    jugadas = plan.get("jugadas") if plan else None
    if capas_on.get("jugadas") and jugadas:
        pines = pd.DataFrame([{
            "lon": j["lon"], "lat": j["lat"], "n": str(j["n"]), "tono": j["tono"],
            "z": alto_mpio.get(clave(j["clave_zona"]), 0.0) + (9_000 if alto_mpio else 0),
            "nombre": f"{j['n']}. {j['icono']} {j['titulo']} {j['zona']}", "departamento": j["departamento"],
            "zona": j["clave_zona"], "nivel": "blanco" if j["estrategia"] == "abrir" else (plan.get("nivel") or "municipio"),
            **{k: "" for k in CAMPOS_TT},
            "valor_txt": (f"≈ {T.cifra(j['valor'])}" if j["valor"] else T.cifra_signo(j.get("ganancia", 0))),
            "unidad": "al mes" if j["valor"] else "ganó este mes",
            "pos_txt": f"· {j['plazo']}",
            **chip(f"Jugada {j['n']} del plan", j["tono"]),
            **bloque_plan(f"{j['icono']} {j['titulo']} · {j['kpi']}", j["responsable"], j["pasos"][0] if j["pasos"] else "",
                           j["tono"]),
            "hint": HINT} for j in jugadas if j.get("lat") is not None])
        if len(pines):
            # Pin oscuro con anillo del color de la estrategia: el número blanco
            # se lee igual sobre rojo, amarillo, verde o violeta.
            pines["color"] = [TONO_RGB[x] + [255] for x in pines["tono"]]
            pines["z"] = pines["z"] + suelo(pines["lat"], pines["lon"])
            pines["halo"] = [TONO_RGB[x] + [90] for x in pines["tono"]]
            capas.append(pdk.Layer("ScatterplotLayer", data=pines[["lon", "lat", "z", "halo"]], id="jugadas_halo",
                                   get_position=["lon", "lat", "z"], get_radius=1, radius_min_pixels=22, radius_max_pixels=22,
                                   get_fill_color="halo", pickable=False))
            capas.append(pdk.Layer("ScatterplotLayer", data=pines.drop(columns=["halo"]), id="jugadas_pin",
                                   get_position=["lon", "lat", "z"], get_radius=1, radius_min_pixels=15, radius_max_pixels=15,
                                   get_fill_color=[17, 24, 39, 245], stroked=True, get_line_color="color",
                                   line_width_min_pixels=3.5, pickable=True, auto_highlight=True,
                                   highlight_color=[255, 255, 255, 120]))
            capas.append(pdk.Layer("TextLayer", data=pines[["lon", "lat", "z", "n"]], id="jugadas_num",
                                   get_position=["lon", "lat", "z"], get_text="n", get_size=17,
                                   get_color=[255, 255, 255, 255], billboard=True))
            tonos = list(dict.fromkeys(j["tono"] for j in jugadas))
            nombres = {"bajo": "rescatar / recuperar", "estable": "desarrollar", "oport": "abrir", "subio": "replicar"}
            leyendas["jugadas"] = [(tuple(TONO_RGB[x]), nombres[x]) for x in tonos]

    # 13) La zona abierta en la ficha: borde neón con brillo y la vista va hacia ella.
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
            if montanas:
                geom = _drapear(geom, relieve_x, _SOBRE_TERRENO_M + 150)
            sel = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": geom, "properties": {}}]}
            capas.append(pdk.Layer("GeoJsonLayer", data=sel, id="seleccion_brillo", stroked=True, filled=False,
                                   get_line_color=[94, 224, 212, 70], line_width_min_pixels=12, pickable=False,
                                   parameters=encima))
            capas.append(pdk.Layer("GeoJsonLayer", data=sel, id="seleccion", stroked=True, filled=True,
                                   get_fill_color=[94, 224, 212, 35], get_line_color=[94, 255, 236, 255],
                                   line_width_min_pixels=2.5, pickable=False, parameters=encima))

    if len(capas) <= 1 and not any(capas_on.values()):
        return None, leyendas
    if inclinada and inclinacion == 0:
        inclinacion = 40
    if montanas:
        # Las montañas solo se ven de lado: vista de dron, girada.
        inclinacion = max(inclinacion, 58)
    vista = vista_inicial(vistas_lat, vistas_lon, inclinacion)
    if montanas:
        vista.bearing = -22
    if foco:
        giro = rumbo if rumbo is not None else (-22 if montanas else -12 if inclinacion else 0)
        vista = pdk.ViewState(latitude=foco[0], longitude=foco[1], zoom=foco[2], pitch=inclinacion,
                              bearing=giro, transition_duration=1400 if rumbo is not None else 900)
    deck = pdk.Deck(layers=capas, initial_view_state=vista,
                    map_style=getattr(pdk.map_styles, MAPAS.get(fondo, "CARTO_DARK")), map_provider="carto",
                    tooltip=tooltip(oscuro))
    return deck, leyendas


# ── Piezas de la pantalla ─────────────────────────────────────────────────

def sin_mes_a_medias(serie: pd.DataFrame, z: dict) -> pd.DataFrame:
    """La serie sin el último mes si va a medias: en un mini-gráfico, el
    día 7 contra un mes completo se ve como un desplome que no existe."""
    if serie is None or serie.empty or not z.get("corte_dia"):
        return serie
    return serie[serie["mes"] != z.get("mes_b")]


def sparkline(valores, color: str = "#0fa8a0", ancho: int = 170, alto: int = 46) -> str:
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


def anillo(fraccion, color: str = "#0fa8a0", tam: int = 60) -> str:
    """Anillo de progreso con el porcentaje en el centro."""
    f = max(0.0, min(1.0, float(fraccion or 0)))
    r = tam / 2 - 5
    largo = 2 * math.pi * r
    return (f'<svg width="{tam}" height="{tam}" viewBox="0 0 {tam} {tam}" class="terr-anillo">'
            f'<circle cx="{tam / 2}" cy="{tam / 2}" r="{r}" fill="none" stroke="var(--line)" stroke-width="5"/>'
            f'<circle cx="{tam / 2}" cy="{tam / 2}" r="{r}" fill="none" stroke="{color}" stroke-width="5" stroke-linecap="round" '
            f'stroke-dasharray="{largo * f:.1f} {largo:.1f}" transform="rotate(-90 {tam / 2} {tam / 2})"/>'
            f'<text x="50%" y="54%" text-anchor="middle" font-size="14" font-weight="800" fill="var(--text)">{f:.0%}</text></svg>')


def barra_semaforo(sem: dict) -> str:
    """Barra apilada rojo · amarillo · verde con la proporción de zonas."""
    total = sum(sem[k]["n"] for k in ("bajo", "estable", "subio")) or 1
    return '<div class="terr-sem-barra">' + "".join(
        f'<i class="{k}" style="width:{sem[k]["n"] / total * 100:.1f}%"></i>'
        for k in ("bajo", "estable", "subio") if sem[k]["n"]) + "</div>"


def cuando(z: dict) -> str:
    """«sep 2026» o «sep 2026 al día 7» si el mes va a medias."""
    return T.etiqueta_mes(z.get("mes_b"), True) + (f" al día {z['corte_dia']}" if z.get("corte_dia") else "")


def hud(z: dict, serie: pd.DataFrame, metrica_label: str, cob: dict) -> str:
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
                 f'{abs(cambio):.1%} <small>{html.escape(cuando(z))}</small></span>')
    tiles.append(("principal", f"{'Total' if z.get('sumable') else 'Promedio'} · {metrica_label}", T.cifra(z["total"]),
                  delta, sparkline(sin_mes_a_medias(serie, z)["valor"], ancho=124, alto=42) if len(serie) >= 3 else ""))
    sem = T.semaforo(z)
    if sem:
        cuerpo = (f'<div class="terr-sem-cuenta"><span class="subio">▲ {sem["subio"]["n"]}</span>'
                  f'<span class="estable">● {sem["estable"]["n"]}</span><span class="bajo">▼ {sem["bajo"]["n"]}</span></div>'
                  + barra_semaforo(sem))
        tiles.append(("sem", f"Semáforo · {cuando(z)}", cuerpo, f"subieron · estables · bajaron, de {z['n']:,} zonas", ""))
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
            tiles.append(("mov", f"Mayores movimientos · {cuando(z)}", "".join(lineas), "", ""))
    if cob and cob.get("pct_deptos") is not None:
        tiles.append(("anillo", "Cobertura de población", anillo(cob["pct_deptos"]),
                      "de la gente de tus departamentos vive donde ya estás", ""))
    partes = []
    for clase, etiqueta, valor, sub, extra in tiles:
        crudo = clase in {"anillo", "sem", "mov"}
        cuerpo = valor if crudo else f'<b title="{html.escape(valor)}">{html.escape(valor)}</b>'
        sub_html = sub if sub.startswith("<span") else (f"<small>{html.escape(sub)}</small>" if sub else "")
        partes.append(f'<div class="terr-hud-tile {clase}"><span>{html.escape(etiqueta)}</span>'
                      f'<div class="fila">{cuerpo}{extra}</div>{sub_html}</div>')
    return '<div class="terr-hud">' + "".join(partes) + "</div>"



def cabecera_mapa(metrica_label: str, color: str, z_m: dict, etiqueta: str, capas_on: dict,
                  plan: Optional[dict] = None, capas_titulos=()) -> str:
    """La cabecera del mapa: qué se ve, el periodo, el semáforo (o las capas
    activas), el aviso del mes a medias y «cómo leer este mapa»."""
    sem = T.semaforo(z_m)
    if sem:
        derecha = (f'<span class="terr-sem-chip subio">▲ {sem["subio"]["n"]} subieron</span>'
                   f'<span class="terr-sem-chip estable">● {sem["estable"]["n"]} estables</span>'
                   f'<span class="terr-sem-chip bajo">▼ {sem["bajo"]["n"]} bajaron</span>')
    else:
        derecha = "".join(f'<span class="terr-chip dato">{html.escape(x)}</span>' for x in capas_titulos)
    corte = ""
    if z_m.get("corte_dia"):
        corte = (f'<span class="corte">⏱ {html.escape(T.etiqueta_mes(z_m["mes_b"]).capitalize())} va hasta el día '
                 f'{z_m["corte_dia"]}: se compara con {html.escape(T.etiqueta_mes(z_m["mes_a"]))} hasta ese mismo día.</span>')
    elif sem:
        corte = (f'<span class="corte suave">Semáforo: {html.escape(T.etiqueta_mes(z_m["mes_b"], True))} frente a '
                 f'{html.escape(T.etiqueta_mes(z_m["mes_a"], True))}</span>')
    leer = [f"🎨 Color: {COLORES[color].replace('🚦 ', '')}"]
    if capas_on.get("columnas") or capas_on.get("mpios3d") or capas_on.get("deptos") or capas_on.get("hex"):
        leer.append(f"📏 Altura: {metrica_label.lower()}")
    if capas_on.get("jugadas") and plan and plan.get("jugadas"):
        leer.append("🔢 Pines: jugadas del plan")
    if capas_on.get("rutas") and plan is not None and len(plan.get("aperturas", [])):
        leer.append("🟣 Arcos: dónde abrir")
    leer += ["🔍 Pasa el cursor: detalle", "👆 Clic: ficha"]
    return (f'<div class="terr-mapa-head"><div><b>{html.escape(metrica_label)} · {html.escape(COLORES[color])}</b><br>'
            f'<span class="per">{html.escape(etiqueta)}</span>{corte}</div><div class="capas">{derecha}</div>'
            '<div class="terr-leer">' + "".join(f"<span>{html.escape(x)}</span>" for x in leer) + "</div></div>")


def leyenda_linea(leyenda: list) -> str:
    """La leyenda de colores en una sola línea, para poner bajo el mapa."""
    if not leyenda:
        return ""
    return '<div class="terr-ley-linea">' + "".join(
        f'<span><i style="background:rgb{tuple(c)}"></i>{html.escape(t)}</span>' for c, t in leyenda) + "</div>"

# CSS de las piezas compartidas: indicadores, cabecera del mapa, semáforo y jugadas.
CSS_MAPA = """
.terr-ley-linea{display:flex;flex-wrap:wrap;gap:6px 16px;margin:8px 2px 0;font-size:12.5px;color:var(--muted)}
.terr-ley-linea span{display:inline-flex;align-items:center;gap:6px}
.terr-ley-linea i{width:22px;height:11px;border-radius:3px;border:1px solid rgba(0,0,0,.08)}
@keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.terr-chip{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;font-weight:800;letter-spacing:.04em;
  padding:3px 9px;border-radius:999px;border:1px solid var(--line);color:var(--muted);background:var(--panel-2)}
.terr-chip.dato{color:var(--teal);border-color:rgba(15,168,160,.45);background:rgba(15,168,160,.10)}
.terr-chip.dane{color:var(--purple);border-color:rgba(106,91,216,.45);background:rgba(106,91,216,.10)}
.terr-chip.oport{color:#a855f7;border-color:rgba(168,85,247,.45);background:rgba(168,85,247,.10)}
.terr-label{font-size:12px;font-weight:800;letter-spacing:.11em;text-transform:uppercase;color:var(--muted);margin:16px 0 8px}
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
.terr-mapa-head{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;
  padding:14px 18px 26px;background:var(--panel);border:1px solid var(--line);border-radius:16px 16px 0 0;margin-bottom:-1rem}
.terr-mapa-head b{font-size:17px;font-family:'Sora','Inter',sans-serif;color:var(--text)}
.terr-mapa-head .per{font-size:13px;font-weight:800;color:var(--teal);letter-spacing:.04em}
.terr-mapa-head .capas{display:flex;flex-wrap:wrap;gap:5px}
.terr-leer{flex:1 1 100%;display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:8px;padding-top:8px;
  border-top:1px dashed var(--line);font-size:12.5px;color:var(--muted)}
.terr-leer span{white-space:nowrap}
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
.terr-jugada{background:var(--panel);border:1px solid var(--line);border-left:5px solid var(--muted);border-radius:16px;
  padding:16px 18px;box-shadow:var(--shadow-sm);margin-bottom:6px;animation:fadeUp .35s ease both}
.terr-jugada.bajo{border-left-color:#ef4444}.terr-jugada.estable{border-left-color:#eab308}
.terr-jugada.subio{border-left-color:#22c55e}.terr-jugada.oport{border-left-color:#a855f7}
.terr-jugada .cab{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.terr-jugada .cab .n{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;font-weight:900;font-size:15px;
  background:var(--text);color:var(--panel)}
.terr-jugada .cab .valor{margin-left:auto;font-size:14px;color:var(--muted)}.terr-jugada .cab .valor b{color:var(--text);font-size:17px}
.terr-jugada h4,.terr-agente h4,.terr-rail-card h4,.terr-ficha h3{display:block!important;box-shadow:none!important;border:0!important;background:none!important;padding:0!important;width:auto!important}
.terr-jugada h4{margin:10px 0 2px;padding:0;border:0;background:none;font-size:22px;font-family:'Sora','Inter',sans-serif;color:var(--text)}
.terr-jugada h4 small{font-size:13px;color:var(--muted);font-weight:500;margin-left:8px;font-family:'Inter',sans-serif}
.terr-jugada .que{font-size:13px;color:var(--muted);margin:2px 0 8px}
.terr-jugada ol,.terr-agente ol{margin:0;padding-left:20px}
.terr-jugada li,.terr-agente li{font-size:14.5px;line-height:1.5;margin-bottom:5px;color:var(--text)}
.terr-jugada .pie{display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:10px;padding-top:9px;border-top:1px dashed var(--line);
  font-size:13px;color:var(--muted)}
.tchip{display:inline-flex;align-items:center;gap:5px;font-size:12.5px;font-weight:800;padding:3px 11px;border-radius:99px}
.tchip.bajo{color:var(--red);background:var(--red-soft)}.tchip.subio{color:var(--green);background:var(--green-soft)}
.tchip.estable{color:var(--amber-strong);background:var(--amber-soft)}
.tchip.oport{color:#a855f7;background:rgba(168,85,247,.12)}
.terr-estado{font-size:13.5px;color:var(--muted);margin:4px 2px 8px}
.terr-estado b{color:var(--text)}
"""
