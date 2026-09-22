"""Regresión de la cascada del cambio (visualization/charts.cascada).

Responde "¿de dónde salió la caída?" partiendo del valor del periodo
anterior, sumando y restando los segmentos que más movieron la aguja hasta
llegar al valor actual.

Lo que se verifica aquí es, sobre todo, que la aritmética CIERRE: si el
gráfico parte de 55.163, muestra unos saltos y termina en un número que no
es el real, está mintiendo con forma de gráfico. Y que NO se dibuje cuando
los segmentos no suman el total (promedios y porcentajes), donde esa suma
no se cumple.

Se corre igual que tests/smoke_test.py: PYTHONPATH=. python tests/cascada_test.py
"""
import numpy as np
import pandas as pd

from core.executive import explain_change
from visualization.charts import cascada


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _datos(tipo_semantico="revenue", n=400, semilla=4):
    np.random.seed(semilla)
    df = pd.DataFrame({
        "Fecha": pd.to_datetime(np.random.choice(pd.date_range("2026-01-01", "2026-02-28"), n)),
        "Region": np.random.choice(["R1", "R2", "R3", "R4", "R5"], n),
        "Ingresos": np.random.randint(50, 500, n),
    })
    esquema = {"dates": ["Fecha"], "metrics": ["Ingresos"], "categorical": ["Region"], "ids": [],
               "semantic": {"columns": [{"column": "Ingresos", "semantic_type": tipo_semantico,
                                         "display_name": "Ingresos"},
                                        {"column": "Region", "semantic_type": "region"}]}}
    return df, esquema


# ── Lo que hace creíble a una cascada: que cierre. ──
def la_cascada_cuadra_con_el_valor_final():
    df, esquema = _datos()
    cambio = explain_change(df, esquema, "Ingresos")
    fig = cascada(cambio)
    check("la cascada se construye para una métrica que se suma", fig is not None)

    trazo = fig.data[0]
    check("empieza en el valor del periodo anterior",
          trazo.measure[0] == "absolute" and abs(trazo.y[0] - cambio["before"]) < 0.01)
    check("termina en el valor del periodo actual",
          trazo.measure[-1] == "total" and abs(trazo.y[-1] - cambio["after"]) < 0.01)

    pasos = sum(v for v, m in zip(trazo.y, trazo.measure) if m == "relative")
    check("el inicio más todos los pasos da exactamente el final",
          abs((trazo.y[0] + pasos) - trazo.y[-1]) < 0.01)


# ── La barra "Resto" es la que impide mentir por omisión: sin ella, mostrar
# solo los 5 mayores movimientos daría un final que no es el real. ──
def el_resto_recoge_lo_que_no_se_muestra():
    np.random.seed(9)
    n = 600
    df = pd.DataFrame({
        "Fecha": pd.to_datetime(np.random.choice(pd.date_range("2026-01-01", "2026-02-28"), n)),
        # Muchas categorías: es imposible que las 5 mayores expliquen todo.
        "Ciudad": np.random.choice([f"C{i:02d}" for i in range(30)], n),
        "Ingresos": np.random.randint(50, 500, n),
    })
    esquema = {"dates": ["Fecha"], "metrics": ["Ingresos"], "categorical": ["Ciudad"], "ids": [],
               "semantic": {"columns": [{"column": "Ingresos", "semantic_type": "revenue"},
                                        {"column": "Ciudad", "semantic_type": "city"}]}}
    cambio = explain_change(df, esquema, "Ingresos")
    fig = cascada(cambio)
    if fig is None:
        print("SKIP el resto: no hubo cambio analizable con estos datos")
        return
    trazo = fig.data[0]
    check("aparece la barra «Resto» cuando los segmentos mostrados no explican todo",
          "Resto" in list(trazo.x))
    pasos = sum(v for v, m in zip(trazo.y, trazo.measure) if m == "relative")
    check("y con ella la cascada sigue cerrando en el valor real",
          abs((trazo.y[0] + pasos) - trazo.y[-1]) < 0.01)


# ── El control que evita una mentira estadística: en un promedio, la media
# de las partes no es la media del todo, así que los segmentos NO suman el
# cambio total y una cascada afirmaría una aritmética que no se cumple. ──
def en_un_promedio_no_se_dibuja_cascada():
    df, esquema = _datos(tipo_semantico="percentage")
    cambio = explain_change(df, esquema, "Ingresos")
    check("el motor marca la métrica como no sumable", cambio["additive"] is False)
    check("y por eso no se dibuja cascada", cascada(cambio) is None)


# ── Nunca debe tronar con datos incompletos. ──
def sin_datos_no_truena():
    for etiqueta, cambio in [
        ("None", None),
        ("sin factores", {"additive": True, "factors": [], "before": 10, "after": 12, "delta": 2}),
        ("sin la marca additive", {"factors": [{"label": "R1", "delta": 5}], "before": 10, "after": 15, "delta": 5}),
        ("diccionario vacío", {}),
    ]:
        check(f"«{etiqueta}» devuelve None en vez de un gráfico roto", cascada(cambio) is None)


# ── Colores: la lectura es "verde empuja arriba, rojo empuja abajo". ──
def los_colores_dicen_la_direccion():
    df, esquema = _datos()
    fig = cascada(explain_change(df, esquema, "Ingresos"))
    trazo = fig.data[0]
    check("las subidas van en verde", trazo.increasing.marker.color == "#22A06B")
    check("las caídas van en el rojo de marca", trazo.decreasing.marker.color == "#E4002B")
    check("los totales van en gris, para no competir con los movimientos",
          trazo.totals.marker.color == "#64748B")


if __name__ == "__main__":
    la_cascada_cuadra_con_el_valor_final()
    el_resto_recoge_lo_que_no_se_muestra()
    en_un_promedio_no_se_dibuja_cascada()
    sin_datos_no_truena()
    los_colores_dicen_la_direccion()
    print("\nCascada test completado sin errores.")
