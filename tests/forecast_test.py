"""Regresión del motor de pronóstico (core/forecast.py).

Lo que más se prueba aquí no es que acierte, sino que sea HONESTO: que se
niegue cuando no hay datos, que mida su propio error y que avise cuando el
indicador es demasiado volátil para tomarse en serio el valor central.

PYTHONPATH=. python tests/forecast_test.py
"""
import numpy as np
import pandas as pd

from core.forecast import pronosticar, explicar, diagnosticar, serie_periodica
from core.profile import profile_sheet


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _datos(valores, inicio="2025-01-01"):
    """Un archivo con una fila por periodo y su valor."""
    fechas = pd.date_range(inicio, periods=len(valores), freq="MS")
    df = pd.DataFrame({"Fecha": fechas, "Ingresos": valores})
    item = profile_sheet(df, {"sheet_name": "H", "workbook_name": "x.xlsx"})
    return item["processed"], item["profile"]["schema"]


# ── Se niega cuando no hay datos suficientes ──
def test_se_niega_con_poca_historia():
    df, sc = _datos([100, 120, 140])
    r = pronosticar(df, sc, "Ingresos")
    print("     ", explicar(r))
    check("con 3 periodos no pronostica", r["viable"] is False)
    check("y explica por qué", "periodo" in r["motivo"].lower())


def test_se_niega_si_no_varia():
    df, sc = _datos([100] * 8)
    r = pronosticar(df, sc, "Ingresos")
    print("     ", explicar(r))
    check("una serie plana no se pronostica", r["viable"] is False)


# ── Tendencia clara: debe acertar y declararse confiable ──
def test_tendencia_clara():
    df, sc = _datos([100, 110, 120, 130, 140, 150, 160, 170, 180, 190])
    r = pronosticar(df, sc, "Ingresos", horizonte=3)
    print("     ", explicar(r))
    print("     ", r["prediccion"].round(1).to_dict("records"))
    check("pronostica una serie creciente", r["viable"] is True)
    check("proyecta hacia arriba", r["prediccion"]["estimado"].iloc[0] > 190)
    check("el rango contiene al estimado",
          bool((r["prediccion"]["minimo"] <= r["prediccion"]["estimado"]).all()
               and (r["prediccion"]["estimado"] <= r["prediccion"]["maximo"]).all()))
    check("con una tendencia limpia se declara confiable", r["confianza"] in {"alta", "media"})
    check("mide su propio error", r["error_tipico"] is not None)


# ── Datos muy ruidosos: debe seguir dando rango pero avisar ──
def test_avisa_cuando_es_volatil():
    np.random.seed(3)
    valores = list(np.random.randint(50, 5000, 14))
    df, sc = _datos(valores)
    r = pronosticar(df, sc, "Ingresos")
    print("     ", explicar(r))
    check("con datos erráticos igual devuelve un rango", r["viable"] is True)
    check("pero declara confianza baja", r["confianza"] == "baja")
    check("y lo dice en el texto", "rango" in explicar(r).lower() or "alto" in explicar(r).lower())


# ── El rango se abre hacia el futuro ──
def test_incertidumbre_crece():
    df, sc = _datos([100, 105, 115, 118, 130, 138, 145, 155, 162, 170])
    r = pronosticar(df, sc, "Ingresos", horizonte=3)
    anchos = (r["prediccion"]["maximo"] - r["prediccion"]["minimo"]).tolist()
    print("     anchos del rango:", [round(a, 1) for a in anchos])
    check("el rango del mes 3 es más ancho que el del mes 1", anchos[2] > anchos[0])


# ── Nunca proyecta negativo un indicador que nunca lo fue ──
def test_no_proyecta_negativos():
    df, sc = _datos([500, 400, 300, 200, 120, 60, 30, 15])
    r = pronosticar(df, sc, "Ingresos", horizonte=4)
    p = r["prediccion"]
    print("     ", p.round(1).to_dict("records"))
    check("no proyecta valores negativos", bool((p["minimo"] >= 0).all()))
    # Esta comprobación es la que faltaba: con una serie en CAÍDA el
    # estimado puede ser negativo, y calcular el rango multiplicando por
    # (1±margen) invertía los extremos (mínimo 86 con máximo -116). Un
    # rango imposible que la prueba anterior no detectaba porque solo
    # miraba el mínimo.
    check("el rango nunca queda invertido (mínimo <= máximo)", bool((p["minimo"] <= p["maximo"]).all()))
    check("el estimado siempre cae dentro del rango",
          bool((p["minimo"] <= p["estimado"]).all() and (p["estimado"] <= p["maximo"]).all()))
    check("un pronóstico cercano a cero conserva un rango visible",
          bool((p["maximo"] - p["minimo"] > 0).all()))


# ── Con dos años de historia usa estacionalidad ──
def test_usa_estacionalidad_con_dos_anios():
    base = [100, 90, 110, 120, 130, 125, 140, 135, 150, 160, 200, 260]
    df, sc = _datos(base * 2 + base[:4])
    r = pronosticar(df, sc, "Ingresos", horizonte=3)
    print("     método:", r["metodo"], "|", explicar(r))
    check("con 28 periodos usa un método estacional o suavizado",
          r["metodo"] in {"estacional", "suavizado"})


if __name__ == "__main__":
    test_se_niega_con_poca_historia()
    test_se_niega_si_no_varia()
    test_tendencia_clara()
    test_avisa_cuando_es_volatil()
    test_incertidumbre_crece()
    test_no_proyecta_negativos()
    test_usa_estacionalidad_con_dos_anios()
    print("\nForecast test completado sin errores.")
