"""Análisis Territorial: ubicar, resumir por zona, hexágonos y dónde crecer.

Qué se protege:

- Los datos de Colombia incluidos (`assets/geo/`) están completos: 1.122
  municipios del DIVIPOLA con coordenadas y población DANE 2026, y los 33
  departamentos con contorno, cruzados por código.
- `ubicar` reconoce las cuatro formas en que llega un lugar: coordenadas,
  columna de municipio (escrito a mano: «BOGOTA D.C.», «CUCUTA», «Medellin»),
  columna de departamento y municipio dentro de otro texto («MC MULTICELL
  SAS CIENEGA CENTRO»). Un valor vacío como pista de departamento no debe
  impedir el cruce (NaN != NaN: antes no se ubicaba nada).
- `zonas` da la posición y la participación sobre TODAS las zonas visibles
  (regla del dominio) y la variación frente al mes anterior.
- `hexagonos` reparte cada punto en un solo hexágono: la suma de los
  hexágonos es la suma de los datos.
- `donde_crecer` valora la mitad del camino a la penetración típica.

PYTHONPATH=. python tests/territorio_test.py
"""
import json
import logging
import warnings

import numpy as np
import pandas as pd

from core import territorio as T
from core.profile import profile_sheet

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

CIUDADES = ["BARRANQUILLA", "SOLEDAD", "MALAMBO", "CARTAGENA", "SANTA MARTA", "Ciénaga", "VALLEDUPAR", "MONTERIA",
            "SINCELEJO", "RIOHACHA", "MAICAO", "BOGOTA D.C.", "CUCUTA", "Medellin", "Lorica", "Sahagún"]


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _perfil(df0):
    item = profile_sheet(df0, {"sheet_name": "x", "workbook_name": "x.xlsx"})
    return item["processed"], item["profile"]["schema"]


def _ventas():
    # Valor fijo por ciudad (sin azar): Montería cae a la mitad en el último mes.
    meses = pd.date_range("2026-06-01", periods=3, freq="MS")
    return pd.DataFrame([{"Fecha": m, "Ciudad": c, "Ventas": float(20 + 10 * i) * 1000
                          * (0.5 if c == "MONTERIA" and m == meses[-1] else 1.0), "Meta": 120_000}
                         for m in meses for i, c in enumerate(CIUDADES) for _ in range(2)])


def test_datos_de_colombia():
    m = T.municipios()
    check("1.122 municipios del DIVIPOLA", len(m) == 1122 and m["cod_mpio"].is_unique)
    check("todos con coordenadas y población", m[["lat", "lon", "poblacion"]].notna().all().all())
    check("la población 2026 del país es razonable (50–56 millones)", 50e6 < m["poblacion"].sum() < 56e6)
    deptos = T.departamentos_geojson()["features"]
    check("33 departamentos con contorno", len(deptos) == 33)
    check("y todos cruzan por código con el DIVIPOLA",
          {f["properties"]["cod_dpto"] for f in deptos} == set(m["cod_dpto"]))
    mpios = T.municipios_geojson()["features"]
    con_indice = [f for f in mpios if f["properties"]["idx"] >= 0]
    check("contornos de 1.122 municipios (DANE MGN), 1.121 cruzados con el DIVIPOLA",
          len(mpios) == 1122 and len(con_indice) == 1121)
    check("con área para la densidad de población", m["area_km2"].notna().sum() >= 1120)


def test_ubicar_las_cuatro_formas():
    df, schema = _perfil(_ventas())
    ub, meta = T.ubicar(df, schema)
    check("columna de municipio escrita a mano: ubica el 100%", meta["origen"] == "municipio" and meta["ubicadas"] == len(df))
    nombres = set(T.municipios().loc[ub["_t_idx"].unique(), "municipio"])
    check("reconoce «BOGOTA D.C.», «CUCUTA» y «Medellin»",
          {"Bogotá, D.C.", "San José de Cúcuta", "Medellín"} <= nombres)

    texto = pd.DataFrame({"Fecha": _ventas()["Fecha"], "Punto de venta": [f"MC MULTICELL SAS {c} CENTRO" for c in _ventas()["Ciudad"]],
                          "Ventas": _ventas()["Ventas"]})
    df, schema = _perfil(texto)
    _, meta = T.ubicar(df, schema)
    check("municipio dentro del nombre del punto", meta["origen"] == "texto" and meta["ubicadas"] == len(df))

    m = T.municipios().sample(30, random_state=1)
    coords = pd.DataFrame({"Latitud": m["lat"] + 0.001, "Longitud": m["lon"] - 0.001, "Ventas": 1.0})
    df, schema = _perfil(coords)
    ub, meta = T.ubicar(df, schema)
    check("coordenadas: cada punto con su municipio más cercano",
          meta["origen"] == "coordenadas" and list(T.municipios().loc[ub["_t_idx"], "cod_mpio"]) == list(m["cod_mpio"]))

    deptos = pd.DataFrame({"Departamento": ["ATLANTICO", "Bolívar", "La Guajira", "valle"], "Ventas": [1.0, 2.0, 3.0, 4.0]})
    df, schema = _perfil(deptos)
    ub, meta = T.ubicar(df, schema)
    check("solo departamento (con y sin tildes, «valle»)",
          meta["origen"] == "departamento" and list(ub["_t_cod_dpto"]) == ["08", "13", "44", "76"])


def test_zonas_sobre_el_grupo_completo():
    df, schema = _perfil(_ventas())
    ub, _ = T.ubicar(df, schema)
    z = T.zonas(ub, "Ventas", "Suma", "municipio", "Fecha", None, "Meta")
    t = z["tabla"]
    check("una zona por municipio", z["n"] == len(CIUDADES))
    check("posiciones 1..N sobre todas", list(t["posicion"]) == list(range(1, len(CIUDADES) + 1)))
    check("la participación suma 100%", abs(t["participacion"].sum() - 1) < 1e-9)
    check("compara el último mes con el anterior", (z["mes_b"], z["mes_a"]) == ("2026-08", "2026-07"))
    monteria = t[t["nombre"] == "Montería"].iloc[0]
    check("y la caída de Montería sale en su variación", monteria["variacion"] < -0.3)
    check("con población y penetración", monteria["poblacion"] > 400_000 and monteria["por_10k"] > 0)
    zd = T.zonas(ub, "Ventas", "Suma", "departamento", "Fecha", None)
    check("también por departamento", "Atlántico" in set(zd["tabla"]["nombre"]))


def test_hexagonos_y_donde_crecer():
    df, schema = _perfil(_ventas())
    ub, _ = T.ubicar(df, schema)
    hx = T.hexagonos(ub, "Ventas", "Suma", 12.0)
    check("la suma de los hexágonos es la suma de los datos", abs(hx["valor"].sum() - df["Ventas"].sum()) < 1e-6)
    check("cada hexágono dice cerca de qué municipio está", hx["nombre"].str.startswith("Cerca de ").all())
    z = T.zonas(ub, "Ventas", "Suma", "municipio", "Fecha", None)
    crecer = T.donde_crecer(z)
    blancos = crecer["blancos"]
    check("propone municipios sin presencia en los departamentos donde se opera",
          len(blancos) and not set(blancos["cod_mpio"]) & set(z["tabla"]["cod_mpio"]))
    fila = blancos.iloc[0]
    check("valorados en la mitad del camino a la penetración típica",
          abs(fila["potencial"] - crecer["penetracion_tipica"] * fila["poblacion"] / 10_000 * 0.5) < 1e-6)
    frases = T.lectura(z, crecer, T.cobertura(z), "Ventas")
    check("la lectura nombra la mayor caída", any("Montería" in f for f in frases))


def main():
    test_datos_de_colombia()
    test_ubicar_las_cuatro_formas()
    test_zonas_sobre_el_grupo_completo()
    test_hexagonos_y_donde_crecer()


if __name__ == "__main__":
    main()
