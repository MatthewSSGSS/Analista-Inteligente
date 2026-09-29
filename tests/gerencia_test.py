"""La lectura de un gerente: causa, palanca y qué vale atacar.

Un jefe de ventas no se conforma con "Barranquilla cayó". Pregunta dónde
nació el cambio (¿la región o el canal dentro de ella?), si fue por vender
menos veces o por vender más barato, y qué frente vale más plata. Aquí se
exige que el motor lo responda con los datos y que calle cuando no puede:

- La causa se encuentra aunque esté un nivel más abajo (región → canal).
- Volumen y ticket se separan bien, y no se inventa una palanca cuando las
  filas vienen agregadas (una por asesor y mes): ahí contar filas no mide
  operaciones.
- Las oportunidades salen con su cifra y en orden de valor.
- Los planes y las alertas heredan la causa y lo que vale atacarlas.
- Una métrica que no se suma (un porcentaje) no produce "causas" falsas.

PYTHONPATH=. python tests/gerencia_test.py
"""
import warnings

import numpy as np
import pandas as pd

from core.dashboard_engine import build_dashboard
from core.gerencia import analisis_gerencial
from core.planes import generar
from core.profile import profile_sheet

warnings.filterwarnings("ignore")


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _perfilar(filas, nombre="Ventas"):
    item = profile_sheet(pd.DataFrame(filas), {"sheet_name": nombre, "workbook_name": "v.xlsx"})
    df, perfil = item["processed"], item["profile"]
    return df, perfil["schema"], build_dashboard(df, perfil)


def _ventas(caida_en=("Barranquilla", "Tienda"), por="volumen"):
    """Transacciones individuales. En agosto, un solo canal de una sola región
    cae: por menos operaciones (volumen) o por menor valor (ticket)."""
    rng = np.random.default_rng(3)
    filas = []
    for mes, segundo in (("2026-07", False), ("2026-08", True)):
        for reg in ["Bogotá", "Medellín", "Barranquilla", "Cali", "Cartagena"]:
            for can in ["Tienda", "Online", "Distribuidor"]:
                n, precio = 40, 100000.0
                if segundo and (reg, can) == caida_en:
                    if por == "volumen":
                        n = 15
                    else:
                        precio = 55000.0
                for i in range(n):
                    filas.append({"Fecha": f"{mes}-{1 + i % 27:02d}", "Región": reg, "Canal": can,
                                  "Asesor": f"{reg[:3]}-{i % 4}", "Ventas": float(rng.normal(precio, precio * .03)),
                                  "Meta": 110000.0})
    return _perfilar(filas)


def test_encuentra_la_causa_un_nivel_abajo():
    df, schema, d = _ventas()
    g = analisis_gerencial(df, schema, d)
    check("hay lectura gerencial", g is not None and g["se_movio"] and g["delta"] < 0)
    c = g["causas"]
    n0 = c["nodos"][0]
    check("la causa principal es Barranquilla", n0["nombre"] == "Barranquilla")
    check("y explica casi todo el cambio", n0["peso"] is not None and n0["peso"] > 60)
    detalle = n0.get("detalle") or {}
    check("dentro de Barranquilla, el canal Tienda",
          detalle.get("segmentos") and detalle["segmentos"][0]["nombre"] == "Tienda")
    check("el titular nombra los dos meses", "agosto de 2026" in g["titular"] and "julio de 2026" in g["titular"])


def test_separa_volumen_de_ticket():
    df, schema, d = _ventas(por="volumen")
    g = analisis_gerencial(df, schema, d)
    check("menos operaciones → palanca de volumen", g["palanca"] and g["palanca"]["dominante"] == "volumen")
    check("y su acción es de actividad comercial", "actividad comercial" in (g["accion_palanca"] or ""))
    df, schema, d = _ventas(por="ticket")
    g = analisis_gerencial(df, schema, d)
    check("mismo volumen y menor precio → palanca de ticket", g["palanca"] and g["palanca"]["dominante"] == "ticket")
    check("y su acción es de precio y mezcla", "precio" in (g["accion_palanca"] or ""))


def test_no_inventa_palanca_con_filas_agregadas():
    """Una fila por asesor y mes: el conteo de filas no cambia y no mide operaciones."""
    filas = []
    for mes, factor in (("2026-07-01", 1.0), ("2026-08-01", 0.8)):
        for a in range(8):
            filas.append({"Fecha": mes, "Asesor": f"Asesor {a}", "Zona": "Norte" if a < 4 else "Sur",
                          "Ventas": 1000.0 * (factor if a < 2 else 1.0)})
    df, schema, d = _perfilar(filas)
    g = analisis_gerencial(df, schema, d)
    check("hay lectura", g is not None)
    check("pero sin palanca inventada", g["palanca"] is None)


def test_oportunidades_con_cifra_y_en_orden():
    df, schema, d = _ventas()
    g = analisis_gerencial(df, schema, d)
    montos = [o["monto"] for o in g["oportunidades"]]
    check("hay oportunidades con cifra", montos and all(m > 0 for m in montos))
    check("ordenadas de mayor a menor valor", montos == sorted(montos, reverse=True))
    claves = {o["clave"] for o in g["oportunidades"]}
    check("incluye recuperar lo perdido y la brecha de meta", {"recuperar", "meta"} <= claves)


def test_planes_y_alertas_heredan_causa_y_valor():
    df, schema, d = _ventas()
    r = generar(df, schema, d)
    caida = next(p for p in r["planes"] if p["titulo"] == "Dónde se concentra la caída")
    check("el plan de la caída dice cuánto vale", caida.get("impacto_txt", "").startswith("Vale "))
    check("y dónde entrar primero (con el segundo nivel)",
          any("Barranquilla" in paso and "Tienda" in paso for paso in caida["pasos"]))
    check("la primera alerta explica por qué bajó", d["alerts"][0]["title"].startswith("Por qué bajó"))
    check("con la causa como evidencia", d["alerts"][0]["evidence"][0]["nombre"] == "Barranquilla")


def test_calla_con_una_metrica_que_no_se_suma():
    filas = [{"Fecha": f"2026-0{m}-01", "Zona": z, "Cumplimiento %": v}
             for m, base in ((7, 90.0), (8, 80.0)) for z, v in (("N", base), ("S", base + 5), ("E", base - 5))]
    df, schema, d = _perfilar(filas, "Cumplimiento")
    check("un porcentaje no produce causas ni oportunidades falsas", analisis_gerencial(df, schema, d) is None)


if __name__ == "__main__":
    test_encuentra_la_causa_un_nivel_abajo()
    test_separa_volumen_de_ticket()
    test_no_inventa_palanca_con_filas_agregadas()
    test_oportunidades_con_cifra_y_en_orden()
    test_planes_y_alertas_heredan_causa_y_valor()
    test_calla_con_una_metrica_que_no_se_suma()
    print("\nGerencia test completado sin errores.")
