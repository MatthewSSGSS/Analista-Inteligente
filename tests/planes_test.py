"""Que el análisis termine en algo que alguien pueda ejecutar.

Dos pestañas se prueban aquí:

- **Planes de mejora**: cada hallazgo tiene que salir convertido en pasos
  concretos que mencionen a los casos por su nombre. Un plan que dice
  "revisar los segmentos afectados" no es un plan, es el hallazgo otra vez.
- **Análisis de seguimiento**: las observaciones de UN caso tienen que estar
  comparadas contra algo —el grupo, la meta o su propio pasado—. "Vendió
  3.2M" no dice si va bien.

PYTHONPATH=. python tests/planes_test.py
"""
import pandas as pd

from core.dashboard_engine import build_dashboard
from core.planes import generar
from core.profile import profile_sheet
from core.seguimiento import observaciones
from ui.person_profile import has_entity, resolve_entity


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _archivo(con_problemas=True):
    """Seis meses por punto. Con problemas: RIOHACHA se hunde y MAICAO se va."""
    puntos = ("RIOHACHA", "CIENAGA", "SOLEDAD", "CARTAGENA", "MONTERIA", "MAICAO")
    filas = []
    for mes in range(1, 7):
        for punto in puntos:
            base = 900
            if con_problemas and punto == "RIOHACHA":
                base = max(0, 1200 - mes * 180)
            if con_problemas and punto == "MAICAO" and mes >= 5:
                base = 0
            for i in range(6):
                filas.append({"Fecha": f"2026-{mes:02d}-{(i * 4) + 2:02d}", "PUNTO": punto,
                              "Ventas": int(base * (0.9 + i * 0.04)), "Meta": 1000})
    item = profile_sheet(pd.DataFrame(filas), {"sheet_name": "V", "workbook_name": "v.xlsx"})
    return item["processed"], item["profile"]["schema"], build_dashboard(item["processed"], item["profile"])


def _texto_de(plan):
    return " ".join([plan["situacion"], plan["por_que"], plan["medir"]] + plan["pasos"])


def test_los_planes_nombran_a_los_casos():
    df, schema, dashboard = _archivo()
    resultado = generar(df, schema, dashboard)
    planes = resultado["planes"]
    check("el análisis produce planes", bool(planes))
    check("hay al menos un frente crítico", resultado["criticos"] >= 1)
    check("el resumen dice por dónde empezar", "atención" in resultado["resumen"].lower()
          or "crítico" in resultado["resumen"].lower())

    caida = next((p for p in planes if p["titulo"].startswith("Dónde se concentra")), None)
    check("la caída se convierte en plan", caida is not None)
    check("y el plan menciona al punto que cae", "RIOHACHA" in _texto_de(caida))
    check("con pasos en orden, no una sola frase", len(caida["pasos"]) >= 3)
    check("y con una forma de saber si funcionó", bool(caida["medir"]))
    check("lo crítico va primero", planes[0]["estado"] == "critico")

    # Ningún paso puede quedarse en la plantilla sin rellenar.
    for plan in planes:
        check(f"el plan '{plan['titulo'][:28]}' no deja huecos sin rellenar",
              "{nombres}" not in _texto_de(plan) and "{primero}" not in _texto_de(plan))


def test_si_todo_va_bien_propone_mejoras():
    """Una pestaña vacía es la forma más rápida de que nadie la vuelva a abrir."""
    filas = [{"Fecha": f"2026-{m:02d}-1{i}", "Zona": z, "Ventas": 400 + m * 20, "Meta": 300}
             for m in range(1, 7) for z in ("N", "S", "E", "O") for i in range(5)]
    item = profile_sheet(pd.DataFrame(filas), {"sheet_name": "V", "workbook_name": "v.xlsx"})
    df, schema = item["processed"], item["profile"]["schema"]
    resultado = generar(df, schema, build_dashboard(df, item["profile"]))
    check("sin problemas no se inventa ninguno", resultado["criticos"] == 0)
    check("pero igual se propone algo", bool(resultado["planes"]))
    check("y todo lo propuesto es una mejora",
          all(p["estado"] == "mejora" for p in resultado["planes"]))
    check("el resumen lo dice sin alarmar", "rojo" in resultado["resumen"])


def test_el_seguimiento_compara_contra_algo():
    df, schema, _ = _archivo()
    check("el archivo de puntos habilita el seguimiento", has_entity(df, schema))
    entidad = resolve_entity(df, schema)
    check("y se sigue por el punto de venta", entidad["column"] == "PUNTO")

    hallazgos = observaciones(df, schema, "PUNTO", "RIOHACHA", "Ventas")
    check("el seguimiento produce observaciones", bool(hallazgos))
    titulos = " ".join(h["title"] for h in hallazgos)

    posicion = next((h for h in hallazgos if h["title"].startswith("Posición")), None)
    check("dice en qué puesto está", posicion is not None)
    check("contra cuántos comparables", "de 6" in posicion["title"])
    check("y contra qué se le está midiendo", "meta" in posicion["implication"].lower())
    check("con la mediana del grupo como referencia",
          any("Mediana" in str(e["nombre"]) for e in posicion["evidence"]))
    check("y nombrando al mejor del grupo",
          any("CARTAGENA" in str(e["nombre"]) for e in posicion["evidence"]))

    check("detecta que viene cayendo", "cayendo" in titulos.lower())
    check("y dice cuánto pesa en el total", "peso" in titulos.lower())

    # Un caso sano no debe recibir las mismas alertas que uno que se hunde.
    sano = observaciones(df, schema, "PUNTO", "CARTAGENA", "Ventas")
    check("un caso sano no se marca como caído",
          not any("cayendo" in h["title"].lower() for h in sano))
    check("y su posición se reporta como favorable",
          any(h["kind"] == "positive" for h in sano))


def test_no_rompe_sin_datos():
    vacio = pd.DataFrame({"A": [], "B": []})
    check("sin filas no truena", observaciones(vacio, {}, "A", "x") == [])
    check("con una columna inexistente tampoco",
          observaciones(pd.DataFrame({"A": [1, 2]}), {}, "NoExiste", "x") == [])


if __name__ == "__main__":
    test_los_planes_nombran_a_los_casos()
    test_si_todo_va_bien_propone_mejoras()
    test_el_seguimiento_compara_contra_algo()
    test_no_rompe_sin_datos()
    print("\nPlanes test completado sin errores.")
