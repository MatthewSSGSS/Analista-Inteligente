"""El informe interactivo es un tablero de análisis, no solo filtros y un ranking.

Antes traía cuatro KPIs, una línea y dos tablas «mayores/menores» que con 11
elementos repetían casi lo mismo; no decía qué pasó ni qué hacer. Aquí se
exige que traiga las secciones de decisión (resumen, qué atacar, gráficos,
cómo va cada uno, alertas, registros) y el diagnóstico del archivo completo,
y que los datos viajen bien para que el navegador recalcule sin mentir:

- un faltante viaja como null, no como 0 (un mes sin reportar no es cero);
- la meta de una métrica viaja como dato, pero no se ofrece como métrica
  («Meta» contra «Meta» no dice nada);
- con una sola dimensión, esa dimensión es la del cuadro (antes se usaba
  solo para el buscador y el tablero quedaba sin distribución);
- un texto con «</script>» no rompe el archivo;
- una tabla ancha de meses se pasa a formato largo para tener tendencia.

PYTHONPATH=. python tests/informe_interactivo_test.py
"""
import json
import logging
import re
import warnings

import numpy as np
import pandas as pd

from core.profile import profile_sheet
from ui.interactive_report import build_interactive_html_report

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _html(df0, hoja="Hoja", archivo="a.xlsx"):
    item = profile_sheet(df0, {"sheet_name": hoja, "workbook_name": archivo})
    return build_interactive_html_report(item["processed"], item["profile"]["schema"], archivo, hoja)


def _datos(html):
    cfg = json.loads(re.search(r"window\.__CFG=(\{.*?\});window\.__DATA=", html, re.S).group(1))
    data = json.loads(re.search(r"window\.__DATA=(\{.*?\});</script>", html, re.S).group(1))
    return cfg, data


def _otts():
    """Como el archivo real: productos × meses, sin otra dimensión."""
    rng = np.random.default_rng(4)
    base = {"Netflix": 1560, "Win+": 1080, "Amazon Prime": 920, "Mcafee": 700, "Disney": 187, "Otros": 11}
    filas = []
    for mes in pd.date_range("2026-04-01", periods=5, freq="MS"):
        for p, b in base.items():
            filas.append({"Mes": mes, "Productos": p, "Altas": int(b * (1 + rng.normal(0, .08)))})
    filas[3]["Altas"] = None  # un mes sin reportar
    return pd.DataFrame(filas)


def _ventas():
    rng = np.random.default_rng(7)
    filas = []
    for mes in pd.date_range("2026-01-01", periods=6, freq="MS"):
        for region in ["Norte", "Sur", "Centro"]:
            for canal in ["Tienda", "Online"]:
                filas.append({"Fecha": mes, "Región": region, "Canal": canal,
                              "Ventas": int(rng.integers(800, 3000)) * 1000, "Meta": 2_000_000,
                              "Nota": "</script><script>alert(1)</script>" if region == "Sur" else "ok"})
    return pd.DataFrame(filas)


def test_secciones_de_decision():
    html = _html(_otts(), "CUMPLIMIENTO OTTS CALLE")
    for sid in ("resumen", "atacar", "graficos", "cada-uno", "alertas", "detalle"):
        check(f"trae la sección «{sid}»", f'id="{sid}"' in html)
    check("trae la ficha de cada elemento", 'id="fx"' in html)
    check("trae el diagnóstico del archivo completo", 'id="diagnostico"' in html and 'id="planes"' in html)
    check("rotula que el diagnóstico no cambia con los filtros", "No cambia con los filtros" in html)
    check("abre sin internet: ningún script externo y Plotly incrustado",
          "<script src=" not in html and len(html) > 1_000_000)


def test_una_sola_dimension_es_la_del_cuadro():
    cfg, data = _datos(_html(_otts(), "OTTS"))
    check("la única dimensión es la vista del cuadro", cfg["vista"] == "Productos")
    check("y también es filtro", [d["col"] for d in cfg["dims"]] == ["Productos"])
    check("la métrica principal es Altas", cfg["principal"] == "Altas")
    check("siempre se puede analizar la cantidad de registros",
          any(m["col"] == "__conteo__" for m in cfg["metricas"]))
    check("las fechas viajan por diccionario", data["fecha"] and len(data["fecha"]["v"]) == 5)

    # En una hoja normal la limpieza ya convirtió el faltante en 0 (regla del
    # proyecto); en un informe tipo tabla (core/informe, faltantes_son_cero=False)
    # llega vacío, y el interactivo no debe volverlo cero.
    item = profile_sheet(_otts(), {"sheet_name": "OTTS", "workbook_name": "a.xlsx"})
    df = item["processed"].copy()
    df["Altas"] = df["Altas"].astype("float")
    df.loc[3, "Altas"] = np.nan
    _, data = _datos(build_interactive_html_report(df, item["profile"]["schema"], "a.xlsx", "OTTS"))
    check("un mes sin reportar viaja como null, no como 0", data["met"]["Altas"][3] is None)


def test_meta_como_dato_y_texto_seguro():
    html = _html(_ventas(), "Ventas")
    cfg, data = _datos(html)
    ventas = next(m for m in cfg["metricas"] if m["col"] == "Ventas")
    check("la métrica sabe cuál es su meta", ventas["meta"] == "Meta")
    check("la meta no se ofrece como métrica", all(m["col"] != "Meta" for m in cfg["metricas"]))
    check("pero sus valores viajan", "Meta" in data["met"])
    check("Ventas se suma", ventas["agg"] == "sum")
    check("un texto con </script> no cierra la etiqueta", "</script><script>alert(1)" not in html)


def test_tabla_ancha_de_meses():
    ancha = pd.DataFrame({"Región": ["Antioquia", "Valle", "Atlántico"],
                          **{m: [100 + i * 10, 80 + i * 7, 60 - i * 3]
                             for i, m in enumerate(["Enero", "Febrero", "Marzo", "Abril"])}})
    cfg, data = _datos(_html(ancha, "Resumen 2026", "resumen_2026.xlsx"))
    check("la tabla ancha trae fechas para la tendencia", data["fecha"] is not None)
    check("con los 4 meses del año del archivo", data["fecha"]["v"][0] == "2026-01-01" and len(data["fecha"]["v"]) == 4)
    check("una fila por región y mes", data["n"] == 12)


def test_vacios_de_pandas():
    """Un archivo real tumbaba el interactivo: la métrica llegaba como Int64
    con `pd.NA` y `float(pd.NA)` lanza TypeError. Y un texto con `pd.NA` se
    volvía el grupo «<NA>»."""
    item = profile_sheet(_otts(), {"sheet_name": "OTTS", "workbook_name": "a.xlsx"})
    df = item["processed"].copy()
    df["Altas"] = df["Altas"].astype("Int64")
    df.loc[[2, 7], "Altas"] = pd.NA
    df["Productos"] = df["Productos"].astype("string")
    df.loc[5, "Productos"] = pd.NA
    _, data = _datos(build_interactive_html_report(df, item["profile"]["schema"], "a.xlsx", "OTTS"))
    check("una métrica Int64 con pd.NA no tumba el interactivo y viaja vacía",
          data["met"]["Altas"][2] is None and data["met"]["Altas"][7] is None)
    check("un texto con pd.NA queda vacío, no como el grupo «<NA>»",
          "<NA>" not in data["dims"]["Productos"]["v"] and data["dims"]["Productos"]["c"][5] == -1)


def main():
    test_vacios_de_pandas()
    test_secciones_de_decision()
    test_una_sola_dimension_es_la_del_cuadro()
    test_meta_como_dato_y_texto_seguro()
    test_tabla_ancha_de_meses()


if __name__ == "__main__":
    main()
