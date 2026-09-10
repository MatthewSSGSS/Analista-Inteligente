"""Regresión del motor de pronóstico (core/forecast.py).

Lo que más se prueba aquí no es que acierte, sino que sea HONESTO: que se
niegue cuando no hay datos, que mida su propio error y que avise cuando el
indicador es demasiado volátil para tomarse en serio el valor central.

PYTHONPATH=. python tests/forecast_test.py
"""
import numpy as np
import pandas as pd

from core.forecast import (pronosticar, explicar, diagnosticar, serie_periodica,
                           atribuir, explicar_atribucion)
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


# ── La prueba más importante: que la confianza NO mienta ──
def test_la_confianza_no_miente():
    """Se le piden meses que YA sabemos qué pasó, y se comprueba que la
    realidad caiga dentro del rango que prometió.

    Nace de un fallo real: con una serie de fuerte estacionalidad y sin dos
    años de historia, declaraba *confianza alta* con 6% de error y luego se
    desviaba un 42%, fuera del rango las tres veces. Dos causas: medía su
    error a UN periodo aunque mostrara pronósticos a tres, y probaba en tan
    pocos puntos de corte que nunca se enfrentaba al pico de fin de año.
    """
    escenarios = {
        "tendencia estable": [100, 108, 115, 124, 131, 140, 148, 157, 165, 174, 182, 190, 199, 207, 216],
        "estacional sin dos años": ([100, 95, 110, 120, 130, 125, 140, 135, 150, 160, 200, 260] * 2)[:27],
        "errático": [412, 1890, 230, 3100, 780, 2450, 190, 3980, 1120, 640, 2870, 350, 1560, 920, 2210],
    }
    for nombre, valores in escenarios.items():
        conocidos, ocultos = valores[:-3], valores[-3:]
        df, sc = _datos(conocidos)
        r = pronosticar(df, sc, "Ingresos", horizonte=3)
        dentro = sum(1 for i, real in enumerate(ocultos)
                     if r["prediccion"]["minimo"].iloc[i] <= real <= r["prediccion"]["maximo"].iloc[i])
        print(f"      {nombre:<26} confianza={r['confianza']:<6} aciertos en rango={dentro}/3")
        check(f"el rango contiene la realidad: {nombre}", dentro == 3)
        # Y si acertó poco, jamás debe haberse declarado confiable.
        if dentro < 3:
            check(f"no se declara confiable si falla: {nombre}", r["confianza"] != "alta")

    # Caso puntual del fallo original: con saltos y menos de dos años, nunca
    # puede declararse confianza alta — no ha visto un diciembre repetido.
    df, sc = _datos(([100, 95, 110, 120, 130, 125, 140, 135, 150, 160, 200, 260] * 2)[:21])
    r = pronosticar(df, sc, "Ingresos", horizonte=3)
    check("sin dos años de historia y con saltos, no declara confianza alta", r["confianza"] != "alta")
    check("y avisa de la posible estacionalidad", "temporada" in explicar(r).lower())


def _archivo_con_culpables():
    """Doce meses y tres puntos que caen por motivos DISTINTOS.

    La distinción es el punto de la prueba: RIOHACHA atiende menos
    operaciones, CIENAGA cobra menos por cada una y MAICAO dejó de registrar.
    Son tres problemas que se corrigen de tres formas, y un pronóstico que
    solo dice "va a bajar" los mete a todos en la misma bolsa.
    """
    filas = []
    for mes in range(1, 13):
        for punto in ("RIOHACHA", "CIENAGA", "SOLEDAD", "CARTAGENA", "MONTERIA", "MAICAO"):
            if punto == "RIOHACHA":
                operaciones, ticket = max(2, 30 - mes * 2), 1000
            elif punto == "CIENAGA":
                operaciones, ticket = 25, max(200, 1000 - mes * 60)
            elif punto == "MAICAO":
                operaciones, ticket = (20 if mes <= 9 else 0), 900
            else:
                operaciones, ticket = 25, 1000
            for i in range(operaciones):
                filas.append({"Fecha": f"2026-{mes:02d}-{(i % 28) + 1:02d}",
                              "PUNTO": punto, "Ventas": ticket + (i % 5) * 10})
    item = profile_sheet(pd.DataFrame(filas), {"sheet_name": "V", "workbook_name": "v.xlsx"})
    return item["processed"], item["profile"]["schema"]


def _impulsor(atribucion, nombre):
    return next((i for i in atribucion["impulsores"] if i["nombre"] == nombre), None)


def test_la_prediccion_dice_de_quien_es():
    df, sc = _archivo_con_culpables()
    resultado = pronosticar(df, sc, "Ventas", horizonte=3)
    check("el archivo de puntos sí se puede pronosticar", resultado["viable"])

    a = atribuir(df, sc, resultado)
    check("la predicción viene con su atribución", a is not None)
    check("abierta por la columna que nombra al punto", a["dimension"] == "PUNTO")
    check("y sabe que la tendencia va a la baja", a["direccion"] == "baja")

    nombres = [i["nombre"] for i in a["impulsores"]]
    check("nombra a los puntos que construimos cayendo",
          {"RIOHACHA", "CIENAGA", "MAICAO"} <= set(nombres))
    check("y dice cuánto aporta cada uno", all(i["peso"] > 0 for i in a["impulsores"]))
    check("el descenso queda explicado por esos pocos", a["concentracion"] >= 50)
    check("y no se declara disperso", not a["disperso"])

    # El POR QUÉ, que es lo que se pidió: no basta con el nombre.
    riohacha = _impulsor(a, "RIOHACHA")
    check("de quien atiende menos, dice que hace menos operaciones",
          "menos operaciones" in (riohacha["motivo"] or ""))
    cienaga = _impulsor(a, "CIENAGA")
    check("de quien cobra menos, dice que cada operación vale menos",
          "vale" in (cienaga["motivo"] or ""))
    maicao = _impulsor(a, "MAICAO")
    check("y de quien desapareció, que dejó de registrar",
          "no registra" in (maicao["motivo"] or ""))
    check("el que desapareció se marca como inactivo", maicao["inactivo"])

    check("hay una frase que resume el porqué", bool(explicar_atribucion(a)))
    check("y se sabe si el reparto usa el mismo método del gráfico",
          "metodo_lineal" in a)


def test_no_señala_culpables_cuando_la_caida_es_general():
    """Si baja todo el mundo, nombrar a tres es mandar a revisar lo que no es."""
    filas = []
    for mes in range(1, 13):
        for i in range(40):
            filas.append({"Fecha": f"2026-{mes:02d}-10", "Punto": f"P{i:02d}",
                          "Ventas": max(0, 1000 - mes * 40 + (i % 7) * 15)})
    item = profile_sheet(pd.DataFrame(filas), {"sheet_name": "V", "workbook_name": "v.xlsx"})
    df, sc = item["processed"], item["profile"]["schema"]
    a = atribuir(df, sc, pronosticar(df, sc, "Ventas", horizonte=3))
    check("una caída pareja se marca como dispersa", a is not None and a["disperso"])
    check("y el texto dice que la causa es común",
          "proceso" in explicar_atribucion(a))


def test_prefiere_la_agrupacion_que_explica():
    """Si el descenso es de toda una ciudad, se abre por ciudad y no por punto."""
    filas = []
    for mes in range(1, 13):
        for i in range(90):
            ciudad = "Barranquilla" if i < 30 else ("Cali" if i < 60 else "Medellín")
            base = 900 - (mes * 60 if ciudad == "Barranquilla" else 0)
            filas.append({"Fecha": f"2026-{mes:02d}-10", "Punto": f"P{i:02d}",
                          "Ciudad": ciudad, "Ventas": max(0, base + (i % 5) * 10)})
    item = profile_sheet(pd.DataFrame(filas), {"sheet_name": "V", "workbook_name": "v.xlsx"})
    df, sc = item["processed"], item["profile"]["schema"]
    a = atribuir(df, sc, pronosticar(df, sc, "Ventas", horizonte=3))
    check("se elige la agrupación que concentra el descenso", a["dimension"] == "Ciudad")
    check("y señala la ciudad que cae", a["impulsores"][0]["nombre"] == "Barranquilla")


def test_sin_dimension_no_inventa_atribucion():
    df, sc = _datos([100, 95, 90, 85, 80, 75, 70, 65])
    a = atribuir(df, sc, pronosticar(df, sc, "Ingresos", horizonte=3))
    check("sin una columna con la que nombrar a nadie, no se atribuye nada", a is None)


if __name__ == "__main__":
    test_se_niega_con_poca_historia()
    test_se_niega_si_no_varia()
    test_tendencia_clara()
    test_avisa_cuando_es_volatil()
    test_incertidumbre_crece()
    test_no_proyecta_negativos()
    test_usa_estacionalidad_con_dos_anios()
    test_la_confianza_no_miente()
    test_la_prediccion_dice_de_quien_es()
    test_no_señala_culpables_cuando_la_caida_es_general()
    test_prefiere_la_agrupacion_que_explica()
    test_sin_dimension_no_inventa_atribucion()
    print("\nForecast test completado sin errores.")
