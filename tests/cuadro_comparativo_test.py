"""Que el cuadro comparativo compare con la misma vara a todos los elegidos.

Lo que se prueba son las decisiones que hacen que el cuadro no mienta:

- con meta, el orden es por cumplimiento y no por volumen (el que más vende
  puede ir cuarto si su meta era mucho más alta);
- la tabla típica de una fila por vendedor funciona, sin exigir que los
  nombres se repitan;
- promedio, participación y posición se calculan entre los elegidos;
- en métricas donde subir es peor, el mejor es el que menos tiene;
- sin columnas numéricas, se compara cuántos registros tiene cada uno.

PYTHONPATH=. python tests/cuadro_comparativo_test.py
"""
import warnings

import pandas as pd

from core.cuadro_comparativo import base_de_comparacion, cuadro_comparativo, opciones_de_comparacion
from core.diagnostics import METRICA_CONTEO
from core.profile import profile_sheet

warnings.filterwarnings("ignore")


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _perfil(df):
    item = profile_sheet(df, {"sheet_name": "V", "workbook_name": "v.xlsx"})
    return item["processed"], item["profile"]["schema"]


def _seis_vendedores():
    """Una fila por vendedor. Pedro vende más que nadie, pero su meta era la más alta."""
    return _perfil(pd.DataFrame({
        "Vendedor": ["Ana", "Luis", "Marta", "Pedro", "Sofía", "Juan"],
        "Región": ["Norte", "Norte", "Sur", "Sur", "Centro", "Centro"],
        "Ventas": [120000, 95000, 80000, 150000, 60000, 99000],
        "Meta": [100000, 100000, 90000, 160000, 80000, 90000],
    }))


def _detalle_con_fechas():
    """Operaciones diarias de seis asesores durante cuatro meses; Pedro acelera en abril."""
    filas = []
    ritmo = {"Ana": 20, "Luis": 16, "Marta": 24, "Pedro": 8, "Sofía": 18, "Juan": 22}
    for mes in ("2026-01", "2026-02", "2026-03", "2026-04"):
        for asesor, n in ritmo.items():
            n = n * 2 if (asesor == "Pedro" and mes == "2026-04") else n
            for i in range(n):
                filas.append({"Fecha": f"{mes}-{(i % 27) + 1:02d}", "Asesor": asesor,
                              "Canal": ("Retail", "Digital")[i % 2], "Ventas": 1000})
    return _perfil(pd.DataFrame(filas))


def test_una_fila_por_vendedor_con_meta():
    df, schema = _seis_vendedores()
    opciones = opciones_de_comparacion(df, schema)
    check("se ofrece comparar por vendedor, y primero", opciones and opciones[0] == "Vendedor")
    check("la métrica no se ofrece como columna para comparar", "Ventas" not in opciones)

    cuadro = cuadro_comparativo(df, schema, "Vendedor", "Ventas")
    check("el cuadro se construye", cuadro is not None)
    check("los seis quedan en el cuadro", len(cuadro["filas"]) == 6)
    check("usa la meta del archivo como vara", cuadro["base"] == "meta" and cuadro["meta_col"] == "Meta")
    nombres = [f["nombre"] for f in cuadro["filas"]]
    check("va primero quien más cumple su meta, no quien más vende", nombres[0] == "Ana")
    check("el que más vende no encabeza por volumen", nombres.index("Pedro") > 0)
    check("va último quien menos cumple", nombres[-1] == "Sofía")
    check("las posiciones van de 1 a 6", [f["posicion"] for f in cuadro["filas"]] == list(range(1, 7)))
    ana = cuadro["filas"][0]
    check("el cumplimiento es resultado entre meta", abs(ana["cumplimiento"] - 120) < 0.01)
    check("quien supera su meta la cumple", ana["tono"] == "bueno")
    check("la lectura nombra al primero y al último",
          "Ana" in cuadro["lectura"][0] and "Sofía" in cuadro["lectura"][1])
    check("y dice cuántos cumplen", any("2 de 6" in f for f in cuadro["lectura"]))


def test_seleccion_y_promedio_entre_los_elegidos():
    df, schema = _seis_vendedores()
    cuadro = cuadro_comparativo(df, schema, "Vendedor", "Ventas", seleccion=["Pedro", "Sofía", "Ana"])
    check("solo entran los elegidos", {f["nombre"] for f in cuadro["filas"]} == {"Pedro", "Sofía", "Ana"})
    check("el promedio es el de los elegidos", abs(cuadro["promedio"] - (150000 + 60000 + 120000) / 3) < 0.01)
    check("la participación suma 100 entre ellos",
          abs(sum(f["participacion"] for f in cuadro["filas"]) - 100) < 0.01)
    check("la lista para elegir sigue ofreciendo a los seis", len(cuadro["opciones"]) == 6)
    check("con un solo elegido no hay cuadro",
          cuadro_comparativo(df, schema, "Vendedor", "Ventas", seleccion=["Ana"]) is None)


def test_detalle_con_fechas_trae_movimiento():
    df, schema = _detalle_con_fechas()
    check("se ofrece comparar por asesor", opciones_de_comparacion(df, schema)[0] == "Asesor")
    cuadro = cuadro_comparativo(df, schema, "Asesor", "Ventas")
    check("sin meta, la vara es el resultado", cuadro["base"] == "valor")
    check("hay cuatro meses para la evolución", len(cuadro["periodos"]) == 4)
    pedro = next(f for f in cuadro["filas"] if f["nombre"] == "Pedro")
    check("la variación del último mes es real", abs(pedro["variacion"] - 100) < 0.01)
    check("cada uno trae su serie mensual", all(len(f["serie"]) == 4 for f in cuadro["filas"]))
    check("la lectura dice quién más subió", any("Pedro" in f and "subió" in f for f in cuadro["lectura"]))
    check("va primero quien más vendió", cuadro["filas"][0]["nombre"] == "Marta")
    check("con carteras de tamaño muy distinto se avisa", cuadro["aviso"] is not None)


def test_menos_es_mejor():
    df, schema = _perfil(pd.DataFrame({
        "Asesor": ["Ana", "Luis", "Marta", "Pedro"] * 3,
        "Quejas": [1, 5, 2, 9] * 3,
    }))
    cuadro = cuadro_comparativo(df, schema, "Asesor", "Quejas")
    check("en quejas el mejor es el que menos tiene", cuadro["menos_es_mejor"] and cuadro["filas"][0]["nombre"] == "Ana")
    check("y el que más tiene va último", cuadro["filas"][-1]["nombre"] == "Pedro")
    check("tener más quejas que el promedio no es bueno", cuadro["filas"][-1]["tono"] == "malo")


def test_sin_columnas_numericas_cuenta_registros():
    df, schema = _perfil(pd.DataFrame({
        "Responsable": ["Ana"] * 8 + ["Luis"] * 5 + ["Marta"] * 3,
        "Estado": ["Cerrado", "Abierto"] * 8,
    }))
    cuadro = cuadro_comparativo(df, schema, "Responsable", METRICA_CONTEO)
    check("se compara contando registros", cuadro["conteo"])
    check("con la cantidad correcta", [f["valor"] for f in cuadro["filas"]] == [8, 5, 3])


def test_la_base_dice_en_que_se_basa():
    """Cada frase de la base tiene que coincidir con lo que el cuadro calculó."""
    df, schema = _seis_vendedores()
    base = {b["titulo"]: b["texto"] for b in base_de_comparacion(cuadro_comparativo(df, schema, "Vendedor", "Ventas"))}
    check("responde las seis preguntas", set(base) == {"A quiénes se compara", "Qué se mide", "Contra qué",
                                                       "Periodo", "Cómo se lee el color", "Datos usados"})
    check("nombra la columna comparada", "«Vendedor»" in base["A quiénes se compara"])
    check("dice que la métrica se suma", "«Ventas» sumada" in base["Qué se mide"])
    check("dice contra qué meta y cómo se calcula", "«Meta»" in base["Contra qué"] and "resultado ÷ meta" in base["Contra qué"])
    check("sin fechas lo dice en vez de inventar un periodo", "no tiene fechas" in base["Periodo"])
    check("explica los umbrales del color", "90%" in base["Cómo se lee el color"])
    check("cuenta los registros usados", "6 registros" in base["Datos usados"])
    check("y los filtros activos cuando hay",
          "Región: Norte" in base_de_comparacion(cuadro_comparativo(df, schema, "Vendedor", "Ventas"),
                                                 ["Región: Norte"])[5]["texto"])

    manual = cuadro_comparativo(df, schema, "Vendedor", "Ventas", seleccion=["Ana", "Luis"])
    check("una selección propia se reconoce como tal",
          "elegidos por ti" in base_de_comparacion(manual)[0]["texto"])

    df2, schema2 = _detalle_con_fechas()
    cuadro2 = cuadro_comparativo(df2, schema2, "Asesor", "Ventas")
    base2 = {b["titulo"]: b["texto"] for b in base_de_comparacion(cuadro2)}
    check("sin meta, se compara contra el promedio de los elegidos, con su cifra",
          "promedio de los 6" in base2["Contra qué"] and "no trae una columna de meta" in base2["Contra qué"])
    check("el periodo trae fechas reales y la columna",
          "1 de enero de 2026" in base2["Periodo"] and "«Fecha»" in base2["Periodo"])
    check("y qué meses compara la variación", "abril de 2026 contra marzo de 2026" in base2["Periodo"])
    check("los registros usados son los de los elegidos", cuadro2["registros_usados"] == len(df2))


def test_la_pestana_se_dibuja():
    """La vista completa corre sin una app Streamlit viva, igual que en smoke_test."""
    from ui.cuadro_comparativo import figura_evolucion, figura_meta, figura_ranking, render_cuadro_comparativo, tabla_cuadro
    df, schema = _seis_vendedores()
    render_cuadro_comparativo(df, schema)
    cuadro = cuadro_comparativo(df, schema, "Vendedor", "Ventas")
    check("el ranking tiene una barra por vendedor", len(figura_ranking(cuadro).data[0].y) == 6)
    check("el ranking marca la meta del 100%", any(s.x0 == 100 for s in figura_ranking(cuadro).layout.shapes))
    check("con meta hay gráfico de resultado contra meta", figura_meta(cuadro) is not None)
    check("sin fechas no se inventa una evolución", figura_evolucion(cuadro) is None)
    tabla = tabla_cuadro(cuadro)
    check("el cuadro trae cumplimiento y estado", {"Cumplimiento", "Estado"} <= set(tabla.columns))

    df2, schema2 = _detalle_con_fechas()
    render_cuadro_comparativo(df2, schema2)
    cuadro2 = cuadro_comparativo(df2, schema2, "Asesor", "Ventas")
    check("con fechas hay una línea por asesor", len(figura_evolucion(cuadro2).data) == 6)
    check("sin meta no hay gráfico de meta", figura_meta(cuadro2) is None)
    check("el cuadro trae la variación del último mes", any(c.startswith("Variación") for c in tabla_cuadro(cuadro2).columns))


if __name__ == "__main__":
    test_una_fila_por_vendedor_con_meta()
    test_seleccion_y_promedio_entre_los_elegidos()
    test_detalle_con_fechas_trae_movimiento()
    test_menos_es_mejor()
    test_sin_columnas_numericas_cuenta_registros()
    test_la_base_dice_en_que_se_basa()
    test_la_pestana_se_dibuja()
    print("\nCuadro comparativo test completado sin errores.")
