"""Regresión de «🧹 Ordenar y corregir» (core/organizar.py).

Lo que protege:
- Palabras mal escritas («Medelin», «Bogta», «Juan Peres», «Pérez Juan») se
  proponen hacia la forma frecuente; un municipio que solo aparece mal escrito
  se propone hacia su nombre oficial.
- NO se juntan valores distintos que se parecen: «María»/«Mario» (dos
  personas), «Carla»/«Laura», «Talla S»/«Talla M», «Zona 1»/«Zona 2», ni dos
  valores con un número de filas parecido (ambos son reales).
- Un encabezado mal escrito («Vendedro», «Cantida», «Fceha») se propone
  corregido, pero no una palabra derivada («Vendedora», «Regional»).
- Meses escritos en una columna sin nombre de mes → «Mes», y se leen como
  periodo al aplicar (con el año de la columna vecina).
- Una fecha con muchas celdas basura se puede leer igual (leer_como_fecha).
- Al volver a leer, una columna de fecha con celdas vacías sigue siendo fecha
  (detect_date medía la tasa contra todas las filas y la rechazaba).
- Lo que la persona indicó en «🔎 Columnas» sobrevive, con el nombre nuevo.

Se corre igual que tests/smoke_test.py: PYTHONPATH=. python tests/organizar_test.py
"""
import warnings

import numpy as np
import pandas as pd

from core.columnas import aplicar_papeles
from core.dates import detect_date, leer_como_fecha
from core.organizar import _palabra_corregida, a_excel, aplicar, revisar, volver_a_leer
from core.profile import profile_sheet

warnings.filterwarnings("ignore")
CTX = {"sheet_name": "H", "workbook_name": "h.xlsx"}


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _leer(raw):
    item = profile_sheet(raw, context=CTX)
    return item, item["processed"], item["profile"]["schema"]


def _ventas():
    rng = np.random.default_rng(1)
    n = 600
    ciudades = rng.choice(["Medellín", "Bogotá", "Cali", "Barranquilla"], n).astype(object)
    ciudades[5:9] = ["Medelin", "Medelin", "Barranqulla", "Bogta"]
    vend = rng.choice(["Juan Pérez", "María Gómez", "Mario Gómez", "Carla Ruiz", "Laura Ruiz"], n).astype(object)
    vend[10:12] = ["Juan Peres", "Perez Juan"]
    raw = pd.DataFrame({
        "Fecha": pd.date_range("2025-01-01", periods=n, freq="D"),
        "Ciudad": ciudades, "Vendedro": vend,
        "Talla": rng.choice(["Talla S", "Talla M"], n),
        "Zona": rng.choice(["Zona 1", "Zona 2"], n),
        "Cantida": rng.integers(1, 20, n),
    })
    return pd.concat([raw, raw.iloc[:7]], ignore_index=True)


def main():
    item, df, sc = _leer(_ventas())
    rev = revisar(df, sc)
    errores = {(e["columna"], e["valor"]): e for e in rev["errores"]}
    check("«Medelin» → «Medellín», marcado", errores.get(("Ciudad", "Medelin"), {}).get("corregir_a") == "Medellín"
          and errores[("Ciudad", "Medelin")]["marcado"])
    check("«Bogta» → «Bogotá»", errores.get(("Ciudad", "Bogta"), {}).get("corregir_a") == "Bogotá")
    check("«Juan Peres» y «Perez Juan» → «Juan Pérez»",
          errores.get(("Vendedro", "Juan Peres"), {}).get("corregir_a") == "Juan Pérez"
          and errores.get(("Vendedro", "Perez Juan"), {}).get("corregir_a") == "Juan Pérez")
    valores = {e["valor"] for e in rev["errores"]}
    check("María/Mario, Carla/Laura, Talla S/M y Zona 1/2 no se juntan",
          not valores & {"María Gómez", "Mario Gómez", "Carla Ruiz", "Laura Ruiz", "Talla S", "Talla M",
                         "Zona 1", "Zona 2"})
    nombres = {n["columna"]: n["nuevo"] for n in rev["nombres"] if n["sugerido"]}
    check("encabezados mal escritos se proponen corregidos",
          nombres.get("Vendedro") == "Vendedor" and nombres.get("Cantida") == "Cantidad")
    check("«Fceha» → «Fecha»; derivadas no", _palabra_corregida("Fceha") == "Fecha"
          and _palabra_corregida("Vendedora") is None and _palabra_corregida("Regional") is None
          and _palabra_corregida("Ventas") is None)
    check("filas repetidas contadas", rev["repetidas"] == 7)

    # Una tabla sin errores no inventa propuestas.
    limpio = pd.DataFrame({"Fecha": pd.date_range("2025-01-01", periods=200),
                           "Vendedor": np.resize(["Ana Gómez", "Luis Díaz", "Marta Ruiz"], 200),
                           "Ventas": np.arange(200) * 1000})
    _, dfl, scl = _leer(limpio)
    rl = revisar(dfl, scl)
    check("tabla limpia: sin propuestas", not rl["errores"] and not rl["fechas"] and rl["repetidas"] == 0
          and not any(n["sugerido"] for n in rl["nombres"]))

    # Aplicar: corrige, renombra, quita repetidas, ordena y vuelve a leer.
    valores = {}
    for e in rev["errores"]:
        if e["marcado"]:
            valores.setdefault(e["columna"], {})[e["valor"]] = e["corregir_a"]
    tabla, hecho = aplicar(df, sc, nombres=nombres, valores=valores, quitar_repetidas=True, ordenar=True)
    check("aplicar: sin variantes mal escritas", not tabla["Ciudad"].isin(["Medelin", "Bogta", "Barranqulla"]).any()
          and not tabla["Vendedor"].isin(["Juan Peres", "Perez Juan"]).any())
    check("aplicar: sin repetidas y con nombres nuevos", len(tabla) == 600 and "Cantidad" in tabla.columns)
    check("aplicar: cuenta lo que hizo", any("repetida" in h for h in hecho) and any("renombradas" in h for h in hecho))
    nuevo = volver_a_leer(tabla, item, CTX, nombres, hecho)
    check("al volver a leer, la fecha sigue siendo fecha", nuevo["profile"]["schema"]["dates"] == ["Fecha"])
    check("revisar después: nada pendiente marcado",
          not [e for e in revisar(nuevo["processed"], nuevo["profile"]["schema"])["errores"] if e["marcado"]])

    # Dos nombres con un número de filas parecido son dos valores reales.
    parejos = pd.DataFrame({"Fecha": pd.date_range("2025-01-01", periods=100),
                            "Cliente": ["Tienda Rosales"] * 55 + ["Tienda Rosale"] * 45, "Ventas": range(100)})
    _, dfp, scp = _leer(parejos)
    check("variantes parejas no se proponen", not revisar(dfp, scp)["errores"])

    # Un municipio que solo aparece mal escrito → su nombre oficial.
    solo_mal = pd.DataFrame({"Fecha": pd.date_range("2025-01-01", periods=60),
                             "Municipio": np.resize(["Barranqulla", "Medellín", "Cali"], 60), "Ventas": range(60)})
    _, dfm, scm = _leer(solo_mal)
    em = {e["valor"]: e for e in revisar(dfm, scm)["errores"]}
    check("municipio mal escrito → nombre oficial", em.get("Barranqulla", {}).get("corregir_a") == "Barranquilla")

    # Meses escritos sin nombre de mes, y el año en otra columna.
    rng = np.random.default_rng(4)
    meses = pd.DataFrame({"Columna": rng.choice(["Enero", "Febrero", "Marzo"], 90),
                          "Vigencia": rng.choice([2024, 2025], 90), "Ventas": rng.integers(1, 100, 90)})
    itm, dfm2, scm2 = _leer(meses)
    nm = {n["columna"]: n["nuevo"] for n in revisar(dfm2, scm2)["nombres"] if n["sugerido"]}
    check("meses sin nombre → «Mes», y el año → «Año»", nm.get("Columna") == "Mes" and nm.get("Vigencia") == "Año")
    tabla, hecho = aplicar(dfm2, scm2, nombres=nm)
    leido = volver_a_leer(tabla, itm, CTX, nm, hecho)
    check("con «Mes» y «Año» se arma el periodo", "__periodo_analisis__" in leido["processed"].columns
          and set(leido["processed"]["__periodo_analisis__"].dt.year) == {2024, 2025})

    # Fecha con muchas celdas basura: la carga no la acepta; leer_como_fecha sí.
    f = pd.date_range("2024-01-01", periods=60, freq="D").strftime("%d/%m/%Y").tolist()
    for i in range(0, 60, 4):
        f[i] = "pendiente"
    serie = pd.Series(f)
    check("detect_date no la acepta al cargar", (detect_date(serie, "Entrega")[1] or 0) < 0.9)
    fechas, tasa, _ = leer_como_fecha(serie)
    check("leer_como_fecha la lee y deja vacía la basura", fechas is not None and fechas.isna().sum() == 15
          and abs(tasa - 0.75) < 0.01)
    raw = pd.DataFrame({"Entrega": f, "Ventas": range(60)})
    ite, dfe, sce = _leer(raw)
    if "Entrega" not in sce["dates"]:
        re_ = revisar(dfe, sce)
        check("fecha con basura se propone", [x["columna"] for x in re_["fechas"]] == ["Entrega"])
        tabla, hecho = aplicar(dfe, sce, fechas=["Entrega"])
        check("y al aplicar queda como fecha", "Entrega" in volver_a_leer(tabla, ite, CTX, {}, hecho)
              ["profile"]["schema"]["dates"])

    # Fecha real con celdas vacías: sigue siendo fecha al volver a leer.
    con_vacias = pd.Series(pd.date_range("2025-01-01", periods=50)).where(lambda s: s.index % 4 != 0)
    check("datetime con 25 % vacías es fecha", detect_date(con_vacias, "Entrega")[1] == 1.0)

    # Lo que se corrigió en «🔎 Columnas» sobrevive con el nombre nuevo.
    base = pd.DataFrame({"Fecha": pd.date_range("2025-01-01", periods=80), "Col5": np.arange(80) * 1000 + 7,
                         "Col6": np.arange(80) * 1100 + 3})
    itc, dfc, scc = _leer(base)
    dfc, scc = aplicar_papeles(dfc, scc, {"Col6": "Meta"})
    itc = {**itc, "processed": dfc, "profile": {**itc["profile"], "schema": scc}}
    tabla, hecho = aplicar(dfc, scc, nombres={"Col5": "Ventas", "Col6": "Objetivo mes"})
    leido = volver_a_leer(tabla, itc, CTX, {"Col5": "Ventas", "Col6": "Objetivo mes"}, hecho)
    check("la meta indicada a mano sigue siendo la meta", leido["profile"]["schema"].get("meta_declarada") == "Objetivo mes")

    # Nombres repetidos: error claro, no una tabla rota.
    try:
        aplicar(dfc, scc, nombres={"Col5": "Fecha"})
        check("dos columnas con el mismo nombre se rechazan", False)
    except ValueError:
        check("dos columnas con el mismo nombre se rechazan", True)

    check("el Excel ordenado se arma", a_excel(nuevo["processed"])[:2] == b"PK")


if __name__ == "__main__":
    main()
