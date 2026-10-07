"""Regresión de la presentación para gerentes (lo que se ve y cómo se lee).

Cada comprobación viene de algo que se vio mal en el panel con un archivo de
ventas real de 19 meses:

- Las cifras salían en formato internacional: «15.4B» (en español «B» se lee
  como billones) y ejes con «1G», «1.5G»; los meses, en inglés («Jan 2025»).
- El Resumen decía «Ingresos mejoró 17.1%» y, al lado, «No se detectaron
  mejoras»: las señales solo miraban los 4 primeros hallazgos.
- Las tarjetas mostraban registros, total de 19 meses, mediana y máximo: nada
  de cómo cerró el mes, contra el año pasado, el acumulado, el margen o la meta.
  Con esas cifras se ve lo que el «+17% vs junio» escondía: el año iba −4%.
- «Cambio por segmento» apilaba julio sobre junio como si se sumaran; el
  ranking pintaba al líder de rojo (alarma) y al último de coral.
- Canales decía «pesan poco» de un canal con el 20% del negocio cayendo 13%.
- Inicio abría con «Bienvenido», qué archivo se cargó y un tutorial; el
  parte del día (titular, cifras, qué hacer) no estaba.

PYTHONPATH=. python tests/presentacion_test.py
"""
import logging
import warnings

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from core.dashboard_engine import build_dashboard  # noqa: E402
from core.executive import build_executive, indicadores_gerente  # noqa: E402
from core.profile import profile_sheet  # noqa: E402
from visualization import charts as C  # noqa: E402


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _ventas():
    """19 meses de ventas por región con utilidad y meta: julio sube frente a
    junio, pero el año va por debajo del anterior."""
    rng = np.random.default_rng(4)
    filas = []
    for mes in pd.date_range("2025-01-01", "2026-07-01", freq="MS"):
        factor = 0.85 if mes.year == 2026 else 1.0
        if mes == pd.Timestamp("2026-06-01"):
            factor = 0.7
        for region, base in (("Caribe", 300e6), ("Centro", 250e6), ("Andina", 150e6), ("Sur", 100e6)):
            for dia in (5, 15, 25):
                ingreso = base * factor / 3 * rng.uniform(0.95, 1.05)
                filas.append({"Fecha": mes + pd.Timedelta(days=dia - 1), "Region": region, "Ingresos": ingreso,
                              "Utilidad": ingreso * 0.25, "Meta": base / 3})
    df = pd.DataFrame(filas)
    item = profile_sheet(df, context={"sheet_name": "Ventas", "workbook_name": "ventas.xlsx"})
    return item["processed"], item["profile"]


def test_cifras_y_meses_en_espanol():
    check("mil millones como «mil M», no «B»", C.cifra_eje(1.5e9) == "1.5 mil M")
    check("millones como «M» y miles como «mil»", C.cifra_eje(880e6) == "880 M" and C.cifra_eje(250e3) == "250 mil")
    check("el cero es cero", C.cifra_eje(0) == "0")
    df, perfil = _ventas()
    fig = C.en_espanol(C.trend(df, perfil["schema"], "Ingresos", "Mes", "Automático", False))
    textos = list(fig.layout.yaxis.ticktext or []) + list(fig.layout.xaxis.ticktext or [])
    check("el eje de cifras no usa «G» ni «B»", textos and not any(t.endswith(("G", "B")) for t in textos))
    check("el eje de fechas dice los meses en español", any(t.startswith("ene ") for t in fig.layout.xaxis.ticktext))
    check("en_espanol nunca rompe una figura vacía", C.en_espanol(None) is None)


def test_barras_que_se_leen():
    df, perfil = _ventas()
    fig = C.period_compare_bar(df, perfil["schema"], "Ingresos", "Region", "Mes", "Automático", 8)
    check("los dos meses van lado a lado, no apilados", fig.layout.barmode == "group")
    rank = C.ranking(df, perfil["schema"], "Ingresos", "Region", 8, "Automático")
    colores = set(rank.data[0].marker.color)
    check("el ranking es una sola serie de un solo color", len(colores) == 1)


def test_senales_coherentes_con_el_titular():
    df, perfil = _ventas()
    # La mejora llega en el quinto hallazgo: antes quedaba fuera de las señales.
    hallazgos = [{"kind": "warning", "title": f"Aviso {i}"} for i in range(4)] + [{"kind": "positive", "title": "Evolución reciente"}]
    ex = build_executive(df, perfil["schema"], hallazgos)
    check("el veredicto es de mejora", ex["status"] == "positive")
    check("y la mejora aparece en las señales positivas", ex["positive"] and "Evolución reciente" in ex["positive"])
    check("el titular mismo es la primera señal", ex["positive"][0] == ex["headline"])


def test_indicadores_del_gerente():
    df, perfil = _ventas()
    db = build_dashboard(df, perfil)
    ind = {i["clave"]: i for i in indicadores_gerente(df, perfil["schema"], db["gerencia"], "Ingresos")}
    check("el mes contra el anterior", "mes" in ind and "vs junio de 2026" in ind["mes"]["detalle"])
    check("julio sube frente a junio", ind["mes"]["tono"] == "positive")
    check("el mismo mes del año pasado", "anual" in ind and "julio 2025" in ind["anual"]["etiqueta"])
    check("el acumulado del año muestra lo que el mes esconde (va por debajo)",
          "acumulado" in ind and ind["acumulado"]["tono"] == "negative")
    check("el margen, con la utilidad del archivo", "margen" in ind and ind["margen"]["valor"].startswith("25"))
    check("y el cumplimiento de la meta del mes", "meta" in ind and ind["meta"]["valor"].endswith("%"))
    check("sin análisis gerencial no se inventa nada", indicadores_gerente(df, perfil["schema"], None, "Ingresos") == [])


def test_canales_no_minimiza_un_canal_grande():
    from core.comercial import _titular
    filas = [{"canal": "Corporativo", "participacion": 20.2, "crecimiento": -13.2},
             {"canal": "Online", "participacion": 30.0, "crecimiento": 8.0},
             {"canal": "Tienda", "participacion": 27.0, "crecimiento": 6.0},
             {"canal": "Mayorista", "participacion": 22.8, "crecimiento": 4.0}]
    texto = _titular(filas, [], [filas[0]], 3.0)
    check("un canal con el 20% cayendo no «pesa poco»", "pesan poco" not in texto and "20%" in texto)
    pequeño = [{"canal": "Kiosco", "participacion": 3.0, "crecimiento": -9.0}] + filas[1:]
    check("uno de verdad pequeño sí se dice como continuidad",
          "continuidad" in _titular(pequeño, [], [pequeño[0]], 3.0))


def test_inicio_es_el_parte_del_dia():
    import streamlit as st
    from streamlit.delta_generator import DeltaGenerator
    from ui.home import render_home

    df, perfil = _ventas()
    db = build_dashboard(df, perfil)
    wb = {"filename": "ventas.xlsx", "sheets": {"Ventas": {"processed": df, "profile": perfil}}}
    textos = []
    original_st, original_dg = st.markdown, DeltaGenerator.markdown
    st.markdown = lambda body, *a, **k: textos.append(str(body))
    DeltaGenerator.markdown = lambda self, body, *a, **k: textos.append(str(body))
    try:
        render_home(wb, "Ventas", {}, db, df=df, schema=perfil["schema"])
    finally:
        st.markdown, DeltaGenerator.markdown = original_st, original_dg
    todo = " ".join(textos)
    check("abre con lo que hay que saber", "Lo que tienes que saber" in todo)
    check("con el titular del mes", db["gerencia"]["titular"].split(":")[0] in todo)
    check("puesto en perspectiva contra el año", "En perspectiva" in todo)
    check("y qué hacer, con lo que vale", "Qué hacer ahora" in todo and "al mes" in todo)
    check("ya no abre con «Bienvenido»", "Bienvenido" not in todo)


def main():
    test_cifras_y_meses_en_espanol()
    test_barras_que_se_leen()
    test_senales_coherentes_con_el_titular()
    test_indicadores_del_gerente()
    test_canales_no_minimiza_un_canal_grande()
    test_inicio_es_el_parte_del_dia()
    print("\nPresentación test completado sin errores.")


if __name__ == "__main__":
    main()
