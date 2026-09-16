"""Que la pestaña Analítica compare bien y diga lo que ve sin engañar.

Se prueban las decisiones que corrigen fallos vistos con un archivo real:

- solo se agrupa por columnas de texto o categoría, nunca por una métrica;
- una tasa (ARPU, participación) se promedia aunque el motor la llame
  "cantidad", y un conteo sin clasificar se suma;
- la meta y la ejecución se emparejan por nombre (PPTO X ↔ EJEC X);
- un último mes a medias se detecta aunque venga fechado el día 1, y no se
  lee como una caída;
- "el que más creció" nunca se dice de alguien que bajó;
- los aportes a un cambio suman 100% tanto si el total sube como si baja.

PYTHONPATH=. python tests/explorador_test.py
"""
import warnings

import numpy as np
import pandas as pd

import core.explorador as ex
from core.profile import profile_sheet

warnings.filterwarnings("ignore")


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _perfil(df):
    item = profile_sheet(df, {"sheet_name": "D", "workbook_name": "d.xlsx"})
    return item["processed"], item["profile"]["schema"]


def _cortes_mensuales(incompleto=True):
    """Seis puntos en tres regiones, un corte por mes fechado el día 1 (como los reportes reales).

    Norte crece, Sur cae, Centro estable. Si `incompleto`, junio trae solo
    una quinta parte de las altas: el mes todavía no cerró.
    """
    puntos = {"Punto A": "Norte", "Punto B": "Norte", "Punto C": "Sur", "Punto D": "Sur",
              "Punto E": "Centro", "Punto F": "Centro"}
    ritmo = {"Norte": 1.05, "Sur": 0.95, "Centro": 1.0}
    filas = []
    for i, mes in enumerate(["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]):
        for p, region in puntos.items():
            base = 1000 * ritmo[region] ** i * (3 if p in {"Punto A", "Punto C"} else 1)
            factor = 0.2 if (incompleto and mes == "2026-06") else 1
            filas.append({
                "periodo": f"{mes}-01", "REGION": region, "NOMBREPUNTO": p,
                "ALTAS": int(base * factor), "Inducidas": int(base * factor * 0.4),
                "ARPU EJEC RECMES0": 10000 + i * 50.5,
                "PPTO RECMES0": int(base * 1.1), "EJEC RECMES0": int(base * factor),
            })
    return _perfil(pd.DataFrame(filas))


def test_opciones_y_calculo_automatico():
    df, schema = _cortes_mensuales()
    dims = ex.dimensiones(df, schema)
    check("se agrupa por región y por punto", {"REGION", "NOMBREPUNTO"} <= set(dims))
    check("nunca por una métrica", not ({"ALTAS", "Inducidas", "PPTO RECMES0"} & set(dims)))
    check("las altas se suman", ex.calculo_automatico(df, schema, "ALTAS") == "Suma")
    check("un ARPU se promedia", ex.calculo_automatico(df, schema, "ARPU EJEC RECMES0") == "Promedio")
    check("elegir un cálculo a mano manda sobre el automático",
          ex.resolver_calculo(df, schema, "ALTAS", "Máximo") == "Máximo")


def test_ranking_y_concentracion():
    df, schema = _cortes_mensuales(incompleto=False)
    r = ex.ranking(df, schema, "NOMBREPUNTO", "ALTAS")
    t = r["tabla"]
    check("hay un grupo por punto", r["n"] == 6)
    check("va primero el punto más grande", t.iloc[0]["NOMBREPUNTO"] in {"Punto A", "Punto C"})
    check("la participación suma 100", abs(t["Participación %"].sum() - 100) < 0.01)
    check("el acumulado termina en 100", abs(t["Acumulado %"].max() - 100) < 0.01)
    check("dice cuántos explican el 80%", any("explican el 80%" in h for h in r["hallazgos"]))
    menores = ex.ranking(df, schema, "NOMBREPUNTO", "ALTAS", ascendente=True)
    check("el orden inverso pone primero al más bajo", menores["tabla"].iloc[0]["Valor"] == t["Valor"].min())
    promedio = ex.ranking(df, schema, "REGION", "ARPU EJEC RECMES0")
    check("con un promedio no se inventa participación", "Participación %" not in promedio["tabla"])


def test_ultimo_mes_incompleto():
    df, schema = _cortes_mensuales(incompleto=True)
    check("un mes a medias fechado el día 1 se detecta", ex.ultimo_incompleto(df, schema, "ALTAS", "Suma"))
    check("uno completo no", not ex.ultimo_incompleto(*_cortes_mensuales(incompleto=False), "ALTAS", "Suma"))
    check("un promedio no se juzga por volumen", not ex.ultimo_incompleto(df, schema, "ARPU EJEC RECMES0", "Promedio"))
    r = ex.evolucion(df, schema, "REGION", "ALTAS")
    check("la evolución lo marca", r["parcial"] and "incompleto" in r["hallazgos"][0])
    check("y lo deja fuera: Norte crece", "Norte" in r["hallazgos"][1] and "creció" in r["hallazgos"][1])
    periodos = ex.periodos_disponibles(df, schema)
    pvp = ex.periodo_vs_periodo(df, schema, "REGION", "ALTAS", periodos[-2], periodos[-1])
    check("comparar contra el mes a medias avisa antes de todo", "incompleto" in pvp["hallazgos"][0])


def test_nunca_dice_que_crecio_quien_bajo():
    frase = ex._frase_extremos({"R4": -77.0, "R3": -81.0}, "Entre ene y sep")
    check("con todos bajando lo dice así", "todos bajaron" in frase and "creció" not in frase)
    frase = ex._frase_extremos({"R4": 5.0, "R3": 2.0}, "Entre ene y sep")
    check("con todos subiendo también", "todos subieron" in frase)


def test_periodo_contra_periodo():
    df, schema = _cortes_mensuales(incompleto=False)
    periodos = ex.periodos_disponibles(df, schema)
    r = ex.periodo_vs_periodo(df, schema, "REGION", "ALTAS", periodos[0], periodos[-1])
    t = r["tabla"].set_index("REGION")
    check("Norte sumó", t.loc["Norte", "Diferencia"] > 0)
    check("Sur restó", t.loc["Sur", "Diferencia"] < 0)
    check("los aportes suman 100% del cambio", abs(r["tabla"]["Aporte al cambio %"].sum() - 100) < 0.01)
    check("los totales cuadran con la tabla",
          abs(r["total_b"] - r["total_a"] - r["tabla"]["Diferencia"].sum()) < 0.01)
    check("nombra quién más sumó", any("Más sumaron" in h and "Norte" in h for h in r["hallazgos"]))


def test_tabla_cruzada():
    df, schema = _cortes_mensuales(incompleto=False)
    r = ex.tabla_cruzada(df, schema, "REGION", ex.PERIODO, "ALTAS")
    check("una fila por región y una columna por mes", r["matriz"].shape == (3, 6))
    check("las columnas se leen como meses", list(r["matriz"].columns)[0] == "ene 2026")
    fila = ex.tabla_cruzada(df, schema, "REGION", "NOMBREPUNTO", "ALTAS", normalizar="% de la fila")
    check("% de la fila suma 100 en cada fila", np.allclose(fila["valores"].sum(axis=1), 100))
    check("cada región depende de sus propios puntos", any("Dependen" in h for h in fila["hallazgos"]))
    prom = ex.tabla_cruzada(df, schema, "REGION", ex.PERIODO, "ARPU EJEC RECMES0", normalizar="% de la fila")
    check("sobre un promedio no se calculan porcentajes", prom["normalizar"] == "Valores")


def test_meta_contra_ejecutado():
    df, schema = _cortes_mensuales(incompleto=False)
    pares = ex.pares_meta_real(df, schema)
    check("PPTO y EJEC del mismo concepto se emparejan",
          any(p["real"] == "EJEC RECMES0" and p["meta"] == "PPTO RECMES0" for p in pares))
    check("un ARPU no se empareja como meta", not any("ARPU" in p["real"] for p in pares))
    r = ex.cumplimiento(df, schema, "REGION", "EJEC RECMES0", "PPTO RECMES0")
    check("el cumplimiento total es ejecutado ÷ meta", abs(r["total"] - r["total_real"] / r["total_meta"] * 100) < 0.01)
    check("ninguna región llega (la meta es 10% más alta)", any("0 de 3" in h for h in r["hallazgos"]))
    check("dice dónde falta más", any("Donde más falta" in h for h in r["hallazgos"]))


def test_relacion_y_distribucion():
    df, schema = _cortes_mensuales(incompleto=False)
    r = ex.relacion(df, schema, "NOMBREPUNTO", "Inducidas", "ALTAS")
    check("inducidas y altas van juntas", r["r"] > 0.9 and "fuerte" in r["hallazgos"][0])
    check("no se compara una métrica consigo misma", ex.relacion(df, schema, None, "ALTAS", "ALTAS") is None)
    d = ex.distribucion(df, schema, "REGION", "ALTAS")
    check("una fila de estadísticas por región", len(d["tabla"]) == 3)
    check("la mediana está entre P25 y P75", ((d["tabla"]["P25"] <= d["tabla"]["Mediana"])
                                              & (d["tabla"]["Mediana"] <= d["tabla"]["P75"])).all())


def test_granos_cortos():
    filas = [{"Fecha": f"2026-09-{d:02d}", "Canal": c, "Valor": d * (2 if c == "PDV" else 1)}
             for d in range(1, 29) for c in ("PDV", "TAT")]
    df, schema = _perfil(pd.DataFrame(filas))
    check("con un solo mes se propone ver por semana", ex.grano_sugerido(df, schema) == "Semana")
    check("y hay varias semanas", len(ex.periodos_disponibles(df, schema, "Semana")) >= 4)
    check("un día flojo no se toma por periodo incompleto",
          not ex.ultimo_incompleto(df, schema, "Valor", "Suma", "Día"))


def test_la_pestana_se_dibuja():
    from ui.explorer import render_explorer
    df, schema = _cortes_mensuales()
    render_explorer(df, schema)
    check("la pestaña se dibuja sin una app viva", True)


if __name__ == "__main__":
    test_opciones_y_calculo_automatico()
    test_ranking_y_concentracion()
    test_ultimo_mes_incompleto()
    test_nunca_dice_que_crecio_quien_bajo()
    test_periodo_contra_periodo()
    test_tabla_cruzada()
    test_meta_contra_ejecutado()
    test_relacion_y_distribucion()
    test_granos_cortos()
    test_la_pestana_se_dibuja()
    print("\nExplorador test completado sin errores.")
