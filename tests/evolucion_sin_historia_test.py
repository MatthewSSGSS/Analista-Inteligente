"""Sin historia no se dibuja una «Evolución»: se muestra otro análisis.

Bastaba con que el archivo tuviera una columna de fecha para pedir el
gráfico de evolución. Un corte mensual (todas las filas con la misma fecha)
abría el Resumen con «Evolución · ¿Está mejorando o empeorando?» y un punto
suelto en medio de un eje vacío: no responde la pregunta que hace. Ahora:

- dos meses o más con dato → evolución mes a mes, como siempre;
- un solo mes con varios días → evolución día a día dentro de ese mes;
- un único corte → sin evolución ni «anterior vs actual»; entra la
  concentración («3 de 10 hacen el 80%») junto al ranking y la participación.

La regla vale para el Resumen, el panel completo y los informes HTML.

PYTHONPATH=. python tests/evolucion_sin_historia_test.py
"""
import logging
import warnings

import numpy as np
import pandas as pd

from core.profile import profile_sheet
from core.universal_analysis import cobertura_temporal, smart_chart_questions
from visualization.charts import adaptive_chart_specs, concentracion

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

PESOS = {"Netflix": 420, "Win+": 260, "Amazon Prime": 180, "Mcafee": 90, "Disney": 40,
         "HBO Max": 35, "Win Play": 20, "Claro Espert": 12, "T-Resuelve": 9, "Otros": 4}


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _hoja(fechas):
    filas = [{"Fecha": f, "Producto": p, "Ingresos": v * 1_000_000} for f in fechas for p, v in PESOS.items()]
    item = profile_sheet(pd.DataFrame(filas), {"sheet_name": "x", "workbook_name": "x.xlsx"})
    return item["processed"], item["profile"]["schema"]


def _tipos(df, schema):
    return [k for _, _, k in smart_chart_questions(df, schema, "Ingresos", "Producto")]


def test_un_solo_corte():
    df, schema = _hoja([pd.Timestamp("2026-09-30")])
    cob = cobertura_temporal(df, schema, "Ingresos")
    check("un corte tiene un mes y un día", cob["meses"] == 1 and cob["dias"] == 1)
    tipos = _tipos(df, schema)
    check("no pide la evolución", "trend" not in tipos and "trend_dia" not in tipos)
    check("ni «anterior vs actual»", "period_compare" not in tipos)
    check("pide la concentración", "concentracion" in tipos)
    check("y el primero (el gráfico grande del Resumen) es el ranking", tipos[0] == "ranking")
    informes = [k for _, _, k in adaptive_chart_specs(df, schema)]
    check("los informes HTML tampoco la piden", "trend" not in informes and "multi_trend" not in informes)


def test_un_mes_con_varios_dias():
    df, schema = _hoja(list(pd.date_range("2026-09-01", periods=20, freq="D")))
    specs = smart_chart_questions(df, schema, "Ingresos", "Producto")
    tipos = [k for _, _, k in specs]
    check("pide la evolución día a día", tipos[0] == "trend_dia")
    titulo, pregunta, _ = specs[0]
    check("y nombra el mes", "septiembre de 2026" in pregunta)
    check("los informes HTML también la piden", "trend_dia" in [k for _, _, k in adaptive_chart_specs(df, schema)])


def test_varios_meses_sigue_igual():
    df, schema = _hoja(list(pd.date_range("2026-04-01", periods=6, freq="MS")))
    tipos = _tipos(df, schema)
    check("con historia, evolución mes a mes primero", tipos[:2] == ["trend", "period_compare"])
    check("y sin la concentración en lugar de la evolución", "concentracion" not in tipos)


def test_concentracion():
    df, schema = _hoja([pd.Timestamp("2026-09-30")])
    fig = concentracion(df, schema, "Ingresos", "Producto")
    check("dibuja la curva", fig is not None)
    check("dice cuántos hacen el 80%", "3 de 10" in fig.layout.annotations[0].text)
    acumulado = list(fig.data[0].y)
    check("la curva sube hasta el 100%", abs(acumulado[-1] - 100) < 1e-9 and acumulado == sorted(acumulado))

    con_negativos = df.copy()
    con_negativos.loc[0, "Ingresos"] = -5
    check("con negativos no se dibuja (no se lee como parte del total)",
          concentracion(con_negativos, schema, "Ingresos", "Producto") is None)
    dos = df[df["Producto"].isin(["Netflix", "Win+"])]
    check("con menos de tres grupos no se dibuja", concentracion(dos, schema, "Ingresos", "Producto") is None)


def test_selector_del_panel():
    from ui.dashboard import _available_chart_types
    df, schema = _hoja([pd.Timestamp("2026-09-30")])
    sin = [k for _, k in _available_chart_types(df, schema, "Ingresos", "Producto", False)]
    check("sin historia el selector no ofrece línea ni «anterior vs actual»",
          not {"line", "bar", "area", "period_compare"} & set(sin))
    con = [k for _, k in _available_chart_types(df, schema, "Ingresos", "Producto", True)]
    check("con historia sí", {"line", "period_compare"} <= set(con))


def main():
    test_un_solo_corte()
    test_un_mes_con_varios_dias()
    test_varios_meses_sigue_igual()
    test_concentracion()
    test_selector_del_panel()


if __name__ == "__main__":
    main()
