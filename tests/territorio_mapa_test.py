"""Mapa territorial: la ficha flotante y lo que se dibuja encima.

Qué se protege:

- Toda capa que se puede señalar con el cursor trae TODOS los campos de la
  ficha flotante (`_CAMPOS_TT`), también las columnas 3D, los pines del plan
  y los arcos: si falta uno, deck.gl muestra «{campo}» tal cual.
- Ningún campo lleva HTML: Streamlit escapa el valor de cada campo y un
  trozo de HTML salía como texto crudo en la ficha (los estilos van en la
  plantilla de `_tooltip`).
- La ficha dice lo que dice el plan de esa zona (estrategia, valor, responsable).
- En 3D, los nombres van ENCIMA de su columna: en el suelo, las columnas los
  tapaban y no se veía ningún nombre.
- Los pines llevan el número de la jugada y abren su zona al hacer clic.

PYTHONPATH=. python tests/territorio_mapa_test.py
"""
import logging
import warnings

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

import pandas as pd  # noqa: E402

from core import territorio as T  # noqa: E402
from core import territorio_plan as P  # noqa: E402
from ui import territorial as V  # noqa: E402

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


def _mapa(capas_on):
    _, ub, z, agente, cuenta, pl = TP._plan()
    zd = T.zonas(ub, "Ventas", "Suma", "departamento", "Fecha", None)
    deck, _ = V._construir_mapa(capas_on, z["tabla"], zd["tabla"], pd.DataFrame(), pd.DataFrame(), T.donde_crecer(z),
                                "variacion", "Rojo intenso", "Claro", 1.0, 8.0, "Ventas", plan=pl)
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
        faltan = {k for f in filas for k in ("nombre", *V._CAMPOS_TT) if k not in f}
        check(f"«{capa.id}»: cada objeto trae todos los campos de la ficha", filas and not faltan)
        con_html = [f[k] for f in filas for k in V._CAMPOS_TT if isinstance(f.get(k), str) and "<" in f[k]]
        check(f"«{capa.id}»: sin HTML dentro de los campos (Streamlit lo escapa)", not con_html)
    plantilla = V._tooltip(False)["html"]
    check("la plantilla usa todos los campos", all("{" + k + "}" in plantilla for k in V._CAMPOS_TT))


def test_la_ficha_dice_el_plan():
    deck, z, pl = _mapa({"columnas": True})
    columnas = next(c for c in deck.layers if c.id == "zonas")
    baq = next(f for f in _datos(columnas) if f["nombre"] == "Barranquilla")
    check("Barranquilla: «Plan: Rescatar», cuánto vale y la responsable",
          "Rescatar" in baq["plan_tit"] and "al mes" in baq["plan_tit"] and baq["plan_resp"] == "👤 Ana")
    check("y el chip del semáforo en rojo", baq["var_bg"] == V._CHIP_TT["bajo"][0] and "-50%" in baq["var_txt"])


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


def main():
    test_campos_de_la_ficha()
    test_la_ficha_dice_el_plan()
    test_nombres_encima_de_las_columnas()
    test_pines_del_plan()


if __name__ == "__main__":
    main()
