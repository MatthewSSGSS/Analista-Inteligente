"""Regresión de «🔎 Columnas»: corregir a mano qué es cada columna.

Lo que no se puede adivinar (core/por_valores.py lo deja fuera a propósito)
lo indica la persona: cuál de «Col5» y «Col6» es la venta y cuál la meta, una
fecha guardada como número en una columna con nombre de cantidad, una columna
que no se quiere analizar. Aquí se comprueba que la corrección llega a todo el
panel —la meta al cumplimiento, la fecha a las tendencias— y que se puede
deshacer sin perder el dato original (una fecha leída de un número de serie
vuelve a ese mismo número).

Se corre igual que tests/smoke_test.py: PYTHONPATH=. python tests/columnas_test.py
"""
import numpy as np
import pandas as pd

from core.columnas import aplicar_papeles, lectura, papel_actual
from core.dashboard_engine import build_dashboard
from core.dataset_mode import detect_dataset_mode
from core.performance import columna_meta
from core.profile import profile_sheet


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _hoja_sin_nombres():
    rng = np.random.default_rng(3)
    n = 120
    venta = rng.integers(200_000, 5_000_000, n)
    df = pd.DataFrame({
        "Col1": pd.date_range("2025-01-01", periods=n, freq="3D"),
        "Col2": rng.choice(["Ana Gómez", "Luis Díaz", "Juan Pérez", "Marta Ruiz"], n),
        "Col5": venta,
        "Col6": (venta * rng.uniform(.8, 1.3, n)).round(),
        "Col8": rng.uniform(5, 45, n).round(1),
    })
    item = profile_sheet(df, {"sheet_name": "H", "workbook_name": "h.xlsx"})
    return item["processed"], item["profile"]["schema"], item["profile"]


def la_lectura_marca_lo_que_hay_que_revisar():
    df, schema, _ = _hoja_sin_nombres()
    filas = {f["columna"]: f for f in lectura(df, schema)}
    check("las cifras sin nombre quedan para revisar", all(filas[c]["revisar"] for c in ("Col5", "Col6", "Col8")))
    check("lo reconocido por valores no se marca y dice por qué",
          not filas["Col2"]["revisar"] and "nombres de persona" in filas["Col2"]["motivo"])
    check("cada fila trae ejemplos", bool(filas["Col5"]["ejemplos"]))


def la_meta_indicada_llega_al_cumplimiento():
    df, schema, profile = _hoja_sin_nombres()
    check("sin corregir, no hay meta", columna_meta(df, schema, "Col5") is None)
    df2, schema2 = aplicar_papeles(df, schema, {"Col5": "Dinero", "Col6": "Meta", "Col8": "Porcentaje"})
    check("con la corrección, Col6 es la meta de Col5", columna_meta(df2, schema2, "Col5") == "Col6")
    check("Col5 es dinero y Col8 porcentaje",
          schema2["types"]["Col5"] == "Moneda" and schema2["types"]["Col8"] == "Porcentaje")
    check("la pantalla muestra lo que indicó la persona",
          papel_actual("Col6", schema2) == "Meta" and "Lo indicaste" in
          next(f for f in lectura(df2, schema2) if f["columna"] == "Col6")["motivo"])
    check("el original no se tocó", "papeles_usuario" not in schema and "meta_declarada" not in schema)
    tablero = build_dashboard(df2, {**profile, "schema": schema2})
    check("el panel se arma con la corrección", tablero.get("primary_metric") != "Col6")


def una_fecha_que_no_se_reconocio_se_indica_y_se_deshace():
    dias = pd.date_range("2025-01-05", periods=40, freq="7D")
    serie = (dias - pd.Timestamp("1899-12-30")).days.astype(int)
    df = pd.DataFrame({"Activaciones": serie, "Vendedor": ["A", "B", "C", "D"] * 10,
                       "Producto": ["P1", "P2"] * 20, "Estado": ["Activo", "Inactivo"] * 20})
    item = profile_sheet(df, {"sheet_name": "H", "workbook_name": "h.xlsx"})
    df1, schema1 = item["processed"], item["profile"]["schema"]
    check("sin fecha de partida (por eso caía en «Vista principal»)",
          not schema1["dates"] and detect_dataset_mode(df1, schema1)["mode"] == "catalog")
    df2, schema2 = aplicar_papeles(df1, schema1, {"Activaciones": "Fecha"})
    check("marcada a mano, es fecha", schema2["dates"] == ["Activaciones"])
    check("y trae las fechas correctas", df2["Activaciones"].iloc[0] == pd.Timestamp("2025-01-05"))
    check("ya no es métrica", "Activaciones" not in schema2["metrics"])
    check("el archivo deja de leerse como catálogo: pasa al análisis completo",
          detect_dataset_mode(df2, schema2)["mode"] == "analytical")
    df3, schema3 = aplicar_papeles(df2, schema2, {"Activaciones": "Número"})
    check("volver a número devuelve el número de serie original",
          df3["Activaciones"].tolist() == list(serie))


def lo_imposible_se_explica_y_no_usar_quita_la_columna():
    df, schema, _ = _hoja_sin_nombres()
    try:
        aplicar_papeles(df, schema, {"Col2": "Fecha"})
        check("nombres como fecha deberían rechazarse", False)
    except ValueError as e:
        check("nombres como fecha se rechazan con un motivo", "no parece una fecha" in str(e))
    try:
        aplicar_papeles(df, schema, {"Col2": "Dinero"})
        check("nombres como dinero deberían rechazarse", False)
    except ValueError as e:
        check("nombres como dinero se rechazan con un motivo", "no trae números" in str(e))
    df2, schema2 = aplicar_papeles(df, schema, {"Col8": "No usar"})
    check("«No usar» quita la columna del análisis",
          "Col8" not in df2.columns and "Col8" not in schema2["metrics"]
          and "Col8" not in schema2["semantic"]["metrics"])
    df3, schema3 = aplicar_papeles(df, schema, {"Col5": "Identificador"})
    check("un identificador sale de las métricas",
          "Col5" in schema3["ids"] and "Col5" not in schema3["metrics"]
          and "Col5" not in schema3["semantic"]["metrics"])


if __name__ == "__main__":
    la_lectura_marca_lo_que_hay_que_revisar()
    la_meta_indicada_llega_al_cumplimiento()
    una_fecha_que_no_se_reconocio_se_indica_y_se_deshace()
    lo_imposible_se_explica_y_no_usar_quita_la_columna()
    print("\nColumnas test completado sin errores.")
