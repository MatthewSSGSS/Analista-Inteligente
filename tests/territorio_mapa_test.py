"""Mapa territorial: la ficha flotante y lo que se dibuja encima.

Qué se protege:

- Toda capa que se puede señalar con el cursor trae TODOS los campos de la
  ficha flotante (`CAMPOS_TT` de visualization/mapa_territorial), también las columnas 3D, los pines del plan
  y los arcos: si falta uno, deck.gl muestra «{campo}» tal cual.
- Ningún campo lleva HTML: Streamlit escapa el valor de cada campo y un
  trozo de HTML salía como texto crudo en la ficha (los estilos van en la
  plantilla de `_tooltip`).
- La ficha dice lo que dice el plan de esa zona (estrategia, valor, responsable).
- En 3D, los nombres van ENCIMA de su columna: en el suelo, las columnas los
  tapaban y no se veía ningún nombre.
- Los pines llevan el número de la jugada y abren su zona al hacer clic.
- Relieve, satélite y edificios (contexto para cualquier archivo): con
  «Montañas 3D» cada dato sube a la altitud de su lugar —una columna de
  Bogotá nacía a nivel del mar, enterrada bajo la cordillera— y lo plano se
  pega al relieve; los edificios y el mapa de calor, que no pueden subir, no
  se dibujan ahí. Las URLs y «auto» van entre comillas: sin ellas pydeck las
  convierte en fórmulas de deck.gl y la capa no dibuja nada (así fue como los
  nombres terminaron sin tildes).

PYTHONPATH=. python tests/territorio_mapa_test.py
"""
import logging
import warnings

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

import pandas as pd  # noqa: E402

from core import territorio as T  # noqa: E402
from core import territorio_plan as P  # noqa: E402
from visualization import mapa_territorial as V  # noqa: E402

import territorio_plan_test as TP  # noqa: E402


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _datos(capa):
    d = capa.data
    if isinstance(d, pd.DataFrame):
        return d.to_dict("records")
    if isinstance(d, dict) and "features" in d:
        return d["features"]
    return list(d) if d is not None else []


def _mapa(capas_on, fondo="Claro"):
    _, ub, z, agente, cuenta, pl = TP._plan()
    zd = T.zonas(ub, "Ventas", "Suma", "departamento", "Fecha", None)
    deck, _ = V.construir_mapa(capas_on, z["tabla"], zd["tabla"], pd.DataFrame(), pd.DataFrame(), T.donde_crecer(z),
                                "variacion", "Rojo intenso", fondo, 1.0, 8.0, "Ventas", plan=pl)
    return deck, z, pl


def test_campos_de_la_ficha():
    capas_on = {"mpios": True, "columnas": True, "deptos": False, "blancos": True, "jugadas": True, "rutas": True,
                "etiquetas": True, "focos": True}
    deck, _, _ = _mapa(capas_on)
    señalables = [c for c in deck.layers if getattr(c, "pickable", False)]
    ids = {c.id for c in señalables}
    check("se pueden señalar las columnas, los municipios, los pines y los arcos",
          {"zonas", "mpios", "jugadas_pin", "rutas"} <= ids)
    for capa in señalables:
        filas = _datos(capa)
        faltan = {k for f in filas for k in ("nombre", *V.CAMPOS_TT) if k not in f}
        check(f"«{capa.id}»: cada objeto trae todos los campos de la ficha", filas and not faltan)
        con_html = [f[k] for f in filas for k in V.CAMPOS_TT if isinstance(f.get(k), str) and "<" in f[k]]
        check(f"«{capa.id}»: sin HTML dentro de los campos (Streamlit lo escapa)", not con_html)
    plantilla = V.tooltip(False)["html"]
    check("la plantilla usa todos los campos", all("{" + k + "}" in plantilla for k in V.CAMPOS_TT))


def test_la_ficha_dice_el_plan():
    deck, z, pl = _mapa({"columnas": True})
    columnas = next(c for c in deck.layers if c.id == "zonas")
    baq = next(f for f in _datos(columnas) if f["nombre"] == "Barranquilla")
    check("Barranquilla: «Plan: Rescatar», cuánto vale y la responsable",
          "Rescatar" in baq["plan_tit"] and "al mes" in baq["plan_tit"] and baq["plan_resp"] == "👤 Ana")
    check("y el chip del semáforo en rojo", baq["var_bg"] == V.CHIP_TT["bajo"][0] and "-50%" in baq["var_txt"])


def test_nombres_encima_de_las_columnas():
    deck, z, _ = _mapa({"columnas": True, "etiquetas": True})
    etiquetas = next(c for c in deck.layers if c.id == "etiquetas")
    check("con columnas 3D, los nombres van en el aire (z > 0)", all(f["z"] > 0 for f in _datos(etiquetas)))
    # pydeck guarda la lista como expresión: «@@=[lon, lat, z]».
    check("y la posición usa la altura", str(etiquetas.get_position).replace(" ", "").endswith("[lon,lat,z]"))
    deck, _, _ = _mapa({"mpios": True, "etiquetas": True})
    etiquetas = next(c for c in deck.layers if c.id == "etiquetas")
    check("en plano, en el suelo", all(f["z"] == 0 for f in _datos(etiquetas)))


def test_pines_del_plan():
    deck, _, pl = _mapa({"mpios": True, "jugadas": True})
    pines = _datos(next(c for c in deck.layers if c.id == "jugadas_pin"))
    numeros = _datos(next(c for c in deck.layers if c.id == "jugadas_num"))
    check("un pin por jugada, con su número", len(pines) == len(pl["jugadas"])
          and [n["n"] for n in numeros] == [str(j["n"]) for j in pl["jugadas"]])
    check("cada pin abre su zona al hacer clic", all(p["zona"] == j["clave_zona"] for p, j in zip(pines, pl["jugadas"])))


def _capa(deck, id_capa):
    return next((c for c in deck.layers if c.id == id_capa), None)


def test_altitudes():
    m = T.municipios().set_index("municipio")
    alto = lambda n: float(T.altitudes(m.at[n, "lat"], m.at[n, "lon"]))
    check("Bogotá queda en la cordillera (más de 2.000 m)", alto("Bogotá, D.C.") > 2000)
    check("Barranquilla, en la costa (menos de 300 m)", alto("Barranquilla") < 300)
    check("fuera de la grilla o sin dato: 0, sin error", list(T.altitudes([60.0, float("nan")], [10.0, -74.0])) == [0.0, 0.0])


def test_relieve_y_edificios_en_plano():
    deck, z, _ = _mapa({"mpios": True, "etiquetas": True, "relieve": True, "edificios": True})
    relieve, edificios = _capa(deck, "relieve"), _capa(deck, "edificios")
    check("con relieve, el mapa base va debajo de todo y las sombras encima",
          [c.id for c in deck.layers[:3]] == ["relieve_base", "relieve", "relieve2"])
    check("plano: su terreno no sube", relieve.elevation_decoder["rScaler"] == 0 and relieve.elevation_decoder["offset"] < 0)
    check("la URL va como texto, no como fórmula", str(relieve.texture).startswith("http"))
    # La transparencia lavaba el mapa (mar y tierra del mismo gris); multiplicar solo oscurece las laderas.
    check("las sombras se MULTIPLICAN sobre el mapa base, no se superponen con transparencia",
          relieve.parameters["blendColorSrcFactor"] == "dst" and relieve.parameters["blendColorDstFactor"] == "zero")
    # material=False no apaga la luz del terreno: la imagen salía al 65 % de su brillo.
    check("las imágenes planas, sin luz (sus colores tal cual)",
          relieve.material["ambient"] == 1.0 and relieve.material["diffuse"] == 0.0)
    check("y los nombres del mapa encima de las sombras", _capa(deck, "relieve_nombres") is not None
          and _capa(deck, "relieve_nombres").elevation_decoder["offset"] > relieve.elevation_decoder["offset"])
    check("los edificios cargan solo al acercarse a una ciudad", edificios is not None and edificios.min_zoom >= 13)
    etiquetas = _capa(deck, "etiquetas")
    check("los nombres llevan tildes (fuente armada con sus letras)", etiquetas.character_set == "auto")
    nombres = set(z["tabla"]["nombre"].astype(str))
    check("y cada nombre va tal cual está en el archivo, sin quitarle las tildes",
          all(f["texto"].split("  ")[0] in nombres for f in _datos(etiquetas)))
    mpios = _capa(deck, "mpios")
    check("en plano, los municipios siguen en el suelo (sin altura en los vértices)",
          all(len(p) == 2 for p in _vertices(mpios)))


def _vertices(capa):
    feat = next(f for f in _datos(capa) if f["geometry"]["type"] in ("Polygon", "MultiPolygon"))
    g = feat["geometry"]
    return g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]


def test_montanas_3d():
    deck, z, _ = _mapa({"mpios": True, "columnas": True, "etiquetas": True, "jugadas": True, "rutas": True,
                        "calor": True, "montanas": True, "edificios": True})
    terreno = deck.layers[0]
    check("las montañas son la primera capa y suben (×3)", terreno.id == "montanas"
          and terreno.elevation_decoder["rScaler"] == 256 * V.EXAGERACION)
    check("los edificios no se dibujan sobre las montañas", _capa(deck, "edificios") is None)
    check("el mapa de calor tampoco (quedaría bajo la cordillera)", _capa(deck, "calor") is None)
    columnas = _datos(_capa(deck, "zonas"))
    check("cada columna nace a la altitud de su lugar", all(c["suelo"] > 0 for c in columnas)
          and str(_capa(deck, "zonas").get_position).replace(" ", "").endswith("[lon,lat,suelo]"))
    mpios = _capa(deck, "mpios")
    check("los municipios se pegan al relieve: cada vértice trae su altura", all(len(p) == 3 for p in _vertices(mpios)))
    check("y se dibujan encima de las laderas", mpios.parameters == {"depthCompare": "always"} and not mpios.extruded)
    check("la vista se inclina para que se vean", deck.initial_view_state.pitch >= 55)


def test_satelite():
    deck, _, _ = _mapa({"mpios": True, "relieve": True}, fondo="Satélite")
    check("con fondo satelital, la foto va debajo de todo", deck.layers[0].id == "satelite"
          and "World_Imagery" in deck.layers[0].texture)
    check("con los nombres de lugares encima (híbrido)", deck.layers[1].id == "satelite_nombres")
    check("y no se le pone el relieve sombreado encima", _capa(deck, "relieve") is None)
    check("el satélite cuenta como fondo oscuro (colores y ficha)", V.fondo_oscuro("Satélite"))


def main():
    test_campos_de_la_ficha()
    test_la_ficha_dice_el_plan()
    test_nombres_encima_de_las_columnas()
    test_pines_del_plan()
    test_altitudes()
    test_relieve_y_edificios_en_plano()
    test_montanas_3d()
    test_satelite()


if __name__ == "__main__":
    main()
