"""Regresión: el mes a medio cargar no «cae 100 %», y los meses sin año no son del 2000.

Caso real: un archivo de un agente con MES = ENERO…SEPTIEMBRE, sin año en
ninguna parte, y septiembre todavía sin TOTAL_INGRESOS (las celdas en blanco).
El panel decía «TOTAL_INGRESOS bajó 100 % en septiembre de 2000 frente a
agosto de 2000»: el vacío se volvía cero (core/cleaner) y el año faltante se
rellenaba con 2000 (core/dates.month_year_series).

Ahora el último mes entero en blanco queda «sin reportar» (core/cleaner.
meses_sin_reportar) y el año es el más reciente que cuadra con los meses
(core/dates.anio_probable), avisándolo en la limpieza.

Se corre igual que tests/smoke_test.py: PYTHONPATH=. python tests/mes_sin_reportar_test.py
"""
import pandas as pd

from core.dashboard_engine import build_dashboard
from core.dates import anio_probable
from core.profile import profile_sheet

MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE"]
INGRESOS = [624908063, 555596845, 530538614, 582798333, 557771909, 539932152, 515024976, 493971413]


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _hoja(ingresos, archivo="INFO BASICA AGENTE.xlsx"):
    df = pd.DataFrame({"AGENTE": ["INVERSIONES ARAUJO"] * 9, "MES": MESES,
                       "TOTAL_INGRESOS": ingresos, "TERMINALES": range(700, 709)})
    item = profile_sheet(df, {"sheet_name": "Hoja1", "workbook_name": archivo})
    return item["processed"], item["profile"]


def el_mes_a_medio_cargar_no_cae_100():
    df, perfil = _hoja(INGRESOS + [None])
    check("septiembre queda sin reportar, no en cero", pd.isna(df["TOTAL_INGRESOS"].iloc[-1]))
    check("las otras columnas de septiembre siguen", df["TERMINALES"].iloc[-1] == 708)
    titular = build_dashboard(df, perfil)["executive"]["headline"]
    check("el titular compara agosto contra julio (-4.1 %), no -100 %", "4.1%" in titular and "100" not in titular)
    check("la limpieza lo explica", any("sin reportar" in x for x in perfil["cleaning_log"]))


def un_vacio_que_no_es_el_ultimo_mes_sigue_en_cero():
    con_hueco = INGRESOS[:4] + [None] + INGRESOS[5:] + [480000000]
    df, _ = _hoja(con_hueco)
    check("un mes en blanco a mitad de la serie sigue en cero", df["TOTAL_INGRESOS"].iloc[4] == 0)


def los_meses_sin_ano_toman_el_mas_reciente():
    check("ene-sep en octubre de 2026 → 2026", anio_probable(pd.Series(MESES), hoy="2026-10-27") == 2026)
    check("hasta diciembre en octubre de 2026 → 2025",
          anio_probable(pd.Series(MESES + ["OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]), hoy="2026-10-27") == 2025)
    df, perfil = _hoja(INGRESOS + [None])
    fechas = pd.to_datetime(df["__periodo_analisis__"])
    check("nunca más «septiembre de 2000»", fechas.dt.year.min() > 2000)
    check("y se avisa que el año es supuesto", any("no dice de qué año" in x for x in perfil["cleaning_log"]))
    df, perfil = _hoja(INGRESOS + [None], archivo="INFO AGENTE 2025.xlsx")
    check("si el nombre del archivo trae el año, manda ese",
          set(pd.to_datetime(df["__periodo_analisis__"]).dt.year) == {2025}
          and not any("no dice de qué año" in x for x in perfil["cleaning_log"]))


if __name__ == "__main__":
    el_mes_a_medio_cargar_no_cae_100()
    un_vacio_que_no_es_el_ultimo_mes_sigue_en_cero()
    los_meses_sin_ano_toman_el_mas_reciente()
    print("\nMes sin reportar test completado sin errores.")
