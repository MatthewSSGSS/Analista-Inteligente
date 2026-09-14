"""Que las comparaciones entre grupos den datos acordes y digan contra qué se miden.

El caso de prueba tiene un desenlace conocido: R5 es la región más grande y la
que peor cumple su meta; R1 es la más pequeña y la que mejor cumple. Antes el
panel coronaba a R5 ("Líder · R5 · 180"), recomendaba copiar sus prácticas,
promediaba una columna de conteo ("Altas Eje") y llamaba "mayor retroceso" a
un -0,5% sin decir frente a qué periodo.

PYTHONPATH=. python tests/comparaciones_test.py
"""
import pandas as pd

from core.dashboard_engine import build_dashboard
from core.diagnostics import diagnosticar
from core.insights import generate
from core.profile import profile_sheet
from core.semantic_engine import interpret_dataframe
from core.universal_analysis import dynamic_kpis

# ventas y meta por fila: cumplimiento R1 150%, R2 110%, R3 95%, R4 80%, R5 60%
REGIONES = {"R1": (15, 10), "R2": (55, 50), "R3": (95, 100), "R4": (120, 150), "R5": (180, 300)}


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _archivo(con_meta=True):
    """En el último mes R4 cae 1,7% (una caída real) y R5 un 0,6% (ruido)."""
    filas = []
    for mes in range(1, 7):
        for region, (venta, meta) in REGIONES.items():
            for p in range(4):
                valor = venta
                if mes == 6 and region == "R4":
                    valor = 118
                if mes == 6 and region == "R5":
                    valor = 179
                fila = {"FECHA": f"2026-{mes:02d}-01", "REGION": region,
                        "NOMBREPUNTO": f"PDV {region}{p}", "Altas Eje": valor}
                if con_meta:
                    fila["Meta Altas Eje"] = meta
                filas.append(fila)
    item = profile_sheet(pd.DataFrame(filas), {"sheet_name": "Base", "workbook_name": "ventas.xlsx"})
    return item["processed"], item["profile"]


def _por_titulo(hallazgos, titulo):
    return next((h for h in hallazgos if h.get("title") == titulo), None)


def test_una_columna_de_conteo_se_suma():
    tipos = {c["column"]: c["semantic_type"] for c in interpret_dataframe(pd.DataFrame({
        "Altas Eje": [10, 20, 30], "Meta Altas Eje": [20, 20, 20], "Activaciones": [3, 4, 5],
        "Temperatura": [10.5, 20.1, 30.7], "Saldo": [-5, 3, 4],
    }))["columns"]}
    check("una métrica con meta que la nombra se suma", tipos["Altas Eje"] == "quantity")
    check("y su meta también", tipos["Meta Altas Eje"] == "quantity")
    check("un nombre de conteo se suma", tipos["Activaciones"] == "quantity")
    check("una columna cualquiera no se vuelve cantidad", tipos["Temperatura"] != "quantity")
    check("una columna con negativos no es un conteo", tipos["Saldo"] != "quantity")

    df, profile = _archivo()
    dashboard = build_dashboard(df, profile)
    principal = next(k for k in dynamic_kpis(df, profile["schema"], dashboard) if k["kind"] == "primary")
    check("el KPI principal de Altas Eje es el total, no el promedio", principal["label"] == "Total")
    check("y el total coincide con la suma", round(principal["value"]) == round(float(df["Altas Eje"].sum())))


def test_quien_va_primero_se_mide_contra_la_meta():
    df, profile = _archivo()
    dashboard = build_dashboard(df, profile)
    lider = next(k for k in dynamic_kpis(df, profile["schema"], dashboard) if k["kind"] == "leader")
    check("la tarjeta no corona a la región más grande", lider["value"] == "R1")
    check("dice contra qué se mide", "cumplimiento de meta" in lider["label"])
    check("y trae la cifra que lo sostiene, nombrando la meta", "de una meta de" in lider["detalle"])

    sin_meta, profile_sm = _archivo(con_meta=False)
    lider_sm = next(k for k in dynamic_kpis(sin_meta, profile_sm["schema"], build_dashboard(sin_meta, profile_sm))
                    if k["kind"] == "leader")
    check("sin meta la tarjeta dice que mide volumen", lider_sm["label"].startswith("Mayor volumen"))


def test_el_mas_grande_no_es_el_referente():
    df, profile = _archivo()
    hallazgo = _por_titulo(generate(df, profile["schema"], []), "Concentración por dimensión")
    check("el hallazgo de concentración aparece", hallazgo is not None)
    check("dice que R5 es el de mayor volumen", "R5 es el de mayor volumen" in hallazgo["finding"])
    check("y que contra su meta queda último", "5.º de 5" in hallazgo["finding"]
          and "cumplimiento de meta" in hallazgo["finding"])
    check("no recomienda copiar al más grande", "replic" not in hallazgo["action"].lower())
    check("señala al referente real", "R1" in hallazgo["action"])


def test_una_caida_dice_frente_a_que_y_respeta_el_umbral():
    df, profile = _archivo()
    caida = _por_titulo(diagnosticar(df, profile["schema"], None), "Dónde se concentra la caída")
    check("la caída de R4 aparece", caida is not None)
    nombres = [e["nombre"] for e in caida["evidence"]]
    check("R4 cayó más de 1% y se nombra", "R4" in nombres)
    check("R5 bajó menos de 1% y no se llama caída", "R5" not in nombres)
    check("con el total casi igual, no dice que el total subió",
          "subió" not in caida["finding"] and "estable" in caida["finding"])
    check("dice frente a qué periodo", "frente a mayo de 2026" in caida["finding"])
    check("y cada cifra también", all("frente a mayo de 2026" in e["detalle"] for e in caida["evidence"]))


def _dos_metricas():
    """ALTAS y Altas Eje en el mismo archivo, con la meta de una sola y un presupuesto de otra escala."""
    base = pd.DataFrame({
        "FECHA": [f"2026-{m:02d}-01" for m in range(1, 7) for _ in range(5)],
        "REGION": ["R1", "R2", "R3", "R4", "R5"] * 6,
        "ALTAS": [1000, 1100, 1200, 1300, 1400] * 6,
        "Altas Eje": [10, 20, 30, 40, 50] * 6,
        "Meta Altas Eje": [20] * 30,
        "Presupuesto": [5_000_000] * 30,
    })
    item = profile_sheet(base, {"sheet_name": "Base", "workbook_name": "altas.xlsx"})
    return item["processed"], item["profile"]


def test_la_meta_es_la_de_esa_metrica():
    from core.performance import columna_meta

    df, profile = _dos_metricas()
    schema = profile["schema"]
    check("la meta de «Altas Eje» no se usa para «ALTAS»", columna_meta(df, schema, "ALTAS") is None)
    check("un presupuesto mil veces el resultado no es su meta", columna_meta(df, schema, "ALTAS") != "Presupuesto")
    check("«Meta Altas Eje» sí es la meta de «Altas Eje»", columna_meta(df, schema, "Altas Eje") == "Meta Altas Eje")


def test_la_metrica_elegida_manda_en_todo_el_analisis():
    from core.executive import primary_metric
    from visualization.charts import metric_candidates

    df, profile = _dos_metricas()
    sin_eleccion = build_dashboard(df, profile)
    check("sin elegir, el motor toma la métrica de siempre", sin_eleccion["primary_metric"] != "Altas Eje")

    schema = {**profile["schema"], "metrica_preferida": "Altas Eje"}
    tablero = build_dashboard(df, {**profile, "schema": schema})
    check("elegida «Altas Eje», es la métrica principal", tablero["primary_metric"] == "Altas Eje")
    check("el veredicto habla de ella", "Altas Eje" in tablero["executive"]["headline"])
    check("los gráficos la ponen primero", metric_candidates(df, schema)[0] == "Altas Eje")
    check("el resumen ejecutivo también", primary_metric(df, schema) == "Altas Eje")
    check("la comparación entre regiones usa su meta", tablero["performance"]["base"]["clave"] == "meta")
    hallazgos = diagnosticar(df, schema, None)
    metricas = {h["target"].get("metric") for h in hallazgos if h.get("target", {}).get("metric")}
    check("los hallazgos se calculan sobre ella", metricas == {"Altas Eje"})


def test_agregar_una_metrica_como_filtro_la_elige():
    from ui.filtros import metrica_recien_elegida

    check("agregar una columna numérica la elige", metrica_recien_elegida(["REGION"], ["REGION", "Altas Eje"],
                                                                       ["ALTAS", "Altas Eje"]) == "Altas Eje")
    check("agregar una categoría no cambia la métrica", metrica_recien_elegida([], ["Canal"], ["ALTAS"]) is None)
    check("volver a dibujar sin cambios no la cambia",
          metrica_recien_elegida(["Altas Eje"], ["Altas Eje"], ["ALTAS", "Altas Eje"]) is None)


if __name__ == "__main__":
    test_la_meta_es_la_de_esa_metrica()
    test_la_metrica_elegida_manda_en_todo_el_analisis()
    test_agregar_una_metrica_como_filtro_la_elige()
    test_una_columna_de_conteo_se_suma()
    test_quien_va_primero_se_mide_contra_la_meta()
    test_el_mas_grande_no_es_el_referente()
    test_una_caida_dice_frente_a_que_y_respeta_el_umbral()
    print("\nComparaciones test completado sin errores.")
