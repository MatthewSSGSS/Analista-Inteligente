"""Regresión del gráfico «Cómo se reparten» (visualization/charts.rangos).

Sustituye al histograma en el análisis automático. El histograma era
correcto pero no se entendía sin saber leerlo: pedía interpretar una forma
y sus intervalos los elegía el algoritmo, así que salían rótulos como
"100 - 109" que no significan nada para quien dirige.

Lo que se verifica aquí es lo que hace que sí se entienda: grupos con
nombre en español, cantidad y porcentaje a la vista, y el corte en la meta
cuando la métrica es un cumplimiento.

Se corre igual que tests/smoke_test.py: PYTHONPATH=. python tests/rangos_test.py
"""
import numpy as np
import pandas as pd

from core.chart_explainer import explain_chart
from core.universal_analysis import smart_chart_questions
from visualization.charts import rangos


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _esquema(columna, tipo, dims=()):
    return {"metrics": [columna], "dates": [], "ids": [], "categorical": list(dims),
            "semantic": {"columns": [{"column": columna, "semantic_type": tipo,
                                      "display_name": columna}]}}


def _grupos(fig):
    trazo = fig.data[0]
    return list(zip(trazo.y, trazo.x))


# ── Un cumplimiento se parte por la META, no por cuartiles: la pregunta de
# la reunión es quién llegó al 100% y quién no. ──
def un_cumplimiento_se_parte_por_la_meta():
    valores = ([70] * 20 + [90] * 30 + [105] * 40 + [130] * 10)
    df = pd.DataFrame({"Cumplimiento": valores})
    fig = rangos(df, _esquema("Cumplimiento", "percentage"), "Cumplimiento")
    check("el gráfico se construye", fig is not None)
    grupos = dict(_grupos(fig))
    check("los grupos son los de la conversación real, no intervalos calculados",
          list(grupos) == ["Por debajo de 80%", "Entre 80% y 99%",
                           "Cumplió: 100% a 119%", "Superó: 120% o más"])
    check("cada grupo tiene su cuenta correcta",
          [grupos[k] for k in grupos] == [20, 30, 40, 10])
    textos = fig.data[0].text
    check("cada barra muestra cantidad y porcentaje", "(20%)" in textos[0] and "40" in textos[2])


# ── El corte del 100% es el que importa: un caso justo en 100 CUMPLE. ──
def el_cien_por_ciento_cuenta_como_cumplido():
    df = pd.DataFrame({"Cumplimiento": [99.9] * 5 + [100.0] * 5 + [100.1] * 5})
    fig = rangos(df, _esquema("Cumplimiento", "percentage"), "Cumplimiento")
    grupos = dict(_grupos(fig))
    check("los que están en 100 exactos cuentan como cumplidos",
          grupos.get("Cumplió: 100% a 119%") == 10)
    check("y los de 99.9 no", grupos.get("Entre 80% y 99%") == 5)


# ── Una métrica normal no tiene meta, así que se parte en cuartiles y cada
# grupo se rotula con sus cifras reales. Cuartiles y no anchos iguales: con
# anchos iguales un solo valor extremo deja tres grupos vacíos y uno con
# todo, que es justo lo que hacía ilegible el histograma. ──
def una_metrica_normal_se_parte_en_grupos_del_mismo_tamano():
    np.random.seed(3)
    df = pd.DataFrame({"Ventas": np.random.lognormal(8, 1, 400).round(0)})
    fig = rangos(df, _esquema("Ventas", "revenue"), "Ventas")
    grupos = _grupos(fig)
    check("salen cuatro grupos", len(grupos) == 4)
    cuentas = [c for _, c in grupos]
    check("con aproximadamente la misma cantidad de registros cada uno",
          max(cuentas) - min(cuentas) <= 2)
    check("y cada rótulo dice el rango real, no un intervalo anónimo",
          all(" a " in str(nombre) for nombre, _ in grupos))
    check("un valor extremo no deja los demás grupos vacíos", min(cuentas) > 0)


# ── Un porcentaje que NO es un cumplimiento (participación de 0 a 5%) no
# debe partirse por una meta de 100 que no existe: saldría todo en un solo
# grupo y no diría nada. ──
def un_porcentaje_que_no_es_cumplimiento_no_usa_la_meta():
    np.random.seed(5)
    df = pd.DataFrame({"% Participación": np.random.uniform(0, 5, 200).round(2)})
    fig = rangos(df, _esquema("% Participación", "percentage"), "% Participación")
    nombres = [n for n, _ in _grupos(fig)]
    check("no se usan los grupos de meta", "Cumplió: 100% a 119%" not in nombres)
    check("se usan rangos con sus cifras", all(" a " in str(n) for n in nombres))


# ── Casos en los que no hay nada que dibujar: nunca deben tronar. ──
def casos_sin_datos_no_truenan():
    for etiqueta, valores in [("columna vacía", []),
                              ("un solo valor repetido", [5] * 20),
                              ("todo nulo", [None] * 10)]:
        df = pd.DataFrame({"Valor": valores})
        fig = rangos(df, _esquema("Valor", "unknown"), "Valor")
        check(f"«{etiqueta}» devuelve None en vez de un gráfico roto", fig is None)


# ── El análisis automático tiene que pedir este gráfico, no el histograma. ──
def el_analisis_automatico_pide_este_grafico():
    df = pd.DataFrame({"Region": ["R1", "R2"] * 50,
                       "Cumplimiento": list(np.linspace(60, 140, 100))})
    specs = smart_chart_questions(df, _esquema("Cumplimiento", "percentage", ["Region"]),
                                  "Cumplimiento", "Region")
    kinds = [k for _, _, k in specs]
    check("el análisis pide «rangos»", "rangos" in kinds)
    check("y ya no pide el histograma", "histogram" not in kinds)
    titulo, pregunta, _ = next(s for s in specs if s[2] == "rangos")
    check("con una pregunta que se entiende sin saber estadística",
          pregunta == "¿Cuántos casos hay en cada rango?")


# ── El texto que acompaña al gráfico debe decir el dato accionable. ──
def la_explicacion_dice_cuantos_llegan_a_la_meta():
    df = pd.DataFrame({"Cumplimiento": [70] * 25 + [105] * 75})
    texto = explain_chart(df, _esquema("Cumplimiento", "percentage"), "rangos", "Cumplimiento")
    check("dice cuántos llegan al 100%", "75 de cada 100" in texto)
    check("y avisa de los que están muy por debajo", "25%" in texto and "80%" in texto)

    normal = pd.DataFrame({"Ventas": list(range(1, 101))})
    texto2 = explain_chart(normal, _esquema("Ventas", "revenue"), "rangos", "Ventas")
    check("en una métrica normal habla de la mitad de los registros",
          "mitad de los registros" in texto2)


# ── Clic en una barra → los registros que hay detrás. Lo que se verifica
# aquí no es que se abra una tabla, sino que esa tabla traiga EXACTAMENTE
# los mismos registros que contó la barra: si el gráfico dice 67 y la lista
# muestra 65, la cifra deja de servir para decidir. ──
def el_clic_en_una_barra_trae_sus_registros():
    import numpy as np
    from ui.dashboard import _detalle_de_grafico
    from visualization.charts import ranking

    np.random.seed(11)
    df = pd.DataFrame({
        "Asesor": [f"A{i:03d}" for i in range(300)],
        "Region": np.random.choice(["R1", "R2", "R3", "R4", "R5"], 300),
        "Cumplimiento": np.clip(np.random.normal(95, 22, 300), 30, 190).round(0),
    })
    esquema = _esquema("Cumplimiento", "percentage", ["Region", "Asesor"])

    fig = rangos(df, esquema, "Cumplimiento")
    resolver = _detalle_de_grafico(df, esquema, "rangos")
    check("el gráfico de rangos ofrece detalle al hacer clic", resolver is not None)
    for rotulo, cuenta, custom in zip(fig.data[0].y, fig.data[0].x, fig.data[0].customdata):
        titulo, tabla = resolver(list(custom))
        check(f"«{rotulo}»: la lista trae los mismos {cuenta} registros que la barra",
              len(tabla) == cuenta)
        check(f"«{rotulo}»: el detalle se titula igual que la barra", str(rotulo) in titulo)

    fig2 = ranking(df, esquema, "Cumplimiento", "Region", 5)
    resolver2 = _detalle_de_grafico(df, esquema, "ranking")
    check("el ranking también ofrece detalle", resolver2 is not None)
    for custom in fig2.data[0].customdata:
        _, tabla = resolver2(list(custom))
        real = int((df["Region"].astype(str) == str(custom[1])).sum())
        check(f"la barra «{custom[1]}» trae sus {real} registros", len(tabla) == real)

    # Un gráfico sin detalle con sentido no debe inventarse uno.
    check("una evolución temporal no ofrece detalle por clic",
          _detalle_de_grafico(df, esquema, "line") is None)


def un_clic_con_datos_raros_no_truena():
    """El detalle nunca puede tumbar el gráfico: si algo no cuadra, se queda
    sin detalle y la cifra sigue a la vista."""
    from ui.dashboard import _detalle_de_grafico

    df = pd.DataFrame({"Cumplimiento": [50, 100, 150]})
    resolver = _detalle_de_grafico(df, _esquema("Cumplimiento", "percentage"), "rangos")
    for etiqueta, entrada in [("vacío", []), ("incompleto", ["Cumplimiento"]),
                              ("columna que no existe", ["NoExiste", 0, 10]), ("nulo", None)]:
        check(f"clic con datos {etiqueta}: devuelve None en vez de tronar",
              resolver(entrada) is None)


if __name__ == "__main__":
    un_cumplimiento_se_parte_por_la_meta()
    el_cien_por_ciento_cuenta_como_cumplido()
    una_metrica_normal_se_parte_en_grupos_del_mismo_tamano()
    un_porcentaje_que_no_es_cumplimiento_no_usa_la_meta()
    casos_sin_datos_no_truenan()
    el_analisis_automatico_pide_este_grafico()
    la_explicacion_dice_cuantos_llegan_a_la_meta()
    el_clic_en_una_barra_trae_sus_registros()
    un_clic_con_datos_raros_no_truena()
    print("\nRangos test completado sin errores.")
