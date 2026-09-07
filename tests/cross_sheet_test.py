"""Regresión del cruce entre hojas (core/cross_sheet.py).

Verifica que encuentre la misma entidad en otras hojas aunque la columna se
llame distinto en cada una, y que NO empareje hojas sin relación.

PYTHONPATH=. python tests/cross_sheet_test.py
"""
import pandas as pd

from core.cross_sheet import encontrar_hojas_relacionadas, datos_de_entidad, resumir_filas
from core.profile import profile_sheet


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _libro(hojas: dict) -> dict:
    return {"sheets": {n: profile_sheet(d, {"sheet_name": n, "workbook_name": "x.xlsx"})
                       for n, d in hojas.items()}}


# ── Caso principal: el mismo código en 3 hojas, con 3 nombres de columna
# distintos (que es exactamente lo que pasa en archivos reales). ──
def test_cruce_con_nombres_distintos():
    ventas = pd.DataFrame({
        "Ref": ["D3243.00002"] * 3 + ["D3244.00013"] * 3 + ["D3251.00007"] * 2,
        "Periodo": [202606, 202607, 202608] * 2 + [202606, 202607],
        "Venta": [100, 340, 890, 120, 210, 430, 190, 300],
    })
    personal = pd.DataFrame({
        "Cod_Punto": ["D3243.00002", "D3244.00013", "D3251.00007"],
        "Responsable": ["Ana Gómez", "Luis Ruiz", "Marta Díaz"],
        "Cargo": ["Jefe", "Asesor", "Jefe"],
    })
    ubicaciones = pd.DataFrame({
        "Identificador": ["D3243.00002", "D3244.00013", "D3251.00007"],
        "Ciudad": ["Bogotá", "Cali", "Medellín"],
        "Direccion": ["Cra 15 #93-47", "Cll 80 #5-12", "Av 68 #22-04"],
    })
    libro = _libro({"VENTAS": ventas, "PERSONAL": personal, "UBICACIONES": ubicaciones})

    rel = encontrar_hojas_relacionadas(libro, "VENTAS", "Ref")
    hojas = {r["hoja"]: r["columna"] for r in rel}
    print("     relaciones:", [(r["hoja"], r["columna"], r["coincidencia"]) for r in rel])
    check("encuentra las 2 hojas relacionadas", set(hojas) == {"PERSONAL", "UBICACIONES"})
    check("empareja con la columna correcta pese al nombre distinto",
          hojas["PERSONAL"] == "Cod_Punto" and hojas["UBICACIONES"] == "Identificador")

    filas = datos_de_entidad(libro, rel[0], "D3243.00002")
    check("trae las filas del código en la otra hoja", len(filas) == 1)
    resumen = {r["Campo"]: r["Información encontrada"] for r in resumir_filas(filas, rel[0]["columna"])}
    print("     ficha:", resumen)
    check("la ficha trae los datos de esa hoja",
          "Ana Gómez" in str(resumen) or "Bogotá" in str(resumen))


# ── Control: dos hojas sin nada que ver no deben emparejarse. ──
def test_control_hojas_sin_relacion():
    ventas = pd.DataFrame({"Ref": ["D01.1", "D02.2", "D03.3"], "Venta": [1, 2, 3]})
    otra = pd.DataFrame({"Producto": ["Silla", "Mesa", "Lampara"], "Precio": [10, 20, 30]})
    libro = _libro({"VENTAS": ventas, "CATALOGO": otra})
    check("no inventa relación entre hojas ajenas",
          encontrar_hojas_relacionadas(libro, "VENTAS", "Ref") == [])


# ── Caso uno-a-muchos: la otra hoja tiene varias filas por código; la ficha
# debe resumir, no volcar todo. ──
def test_uno_a_muchos():
    maestro = pd.DataFrame({"Ref": ["D01.1", "D02.2"], "Local": ["Norte", "Sur"]})
    historico = pd.DataFrame({
        "Codigo": ["D01.1"] * 4 + ["D02.2"] * 2,
        "Estado": ["Activo", "Activo", "Suspendido", "Activo", "Activo", "Activo"],
        "Monto": [10, 20, 30, 40, 50, 60],
    })
    libro = _libro({"MAESTRO": maestro, "HISTORICO": historico})
    rel = encontrar_hojas_relacionadas(libro, "MAESTRO", "Ref")
    check("detecta la hoja de histórico", len(rel) == 1 and rel[0]["hoja"] == "HISTORICO")
    filas = datos_de_entidad(libro, rel[0], "D01.1")
    check("trae las 4 filas de ese código", len(filas) == 4)
    resumen = {r["Campo"]: r["Información encontrada"] for r in resumir_filas(filas, rel[0]["columna"])}
    print("     ficha uno-a-muchos:", resumen)
    check("resume el campo que varía", "min" in resumen.get("Monto", ""))
    check("lista los valores distintos del texto", "Suspendido" in resumen.get("Estado", ""))


# ── Caso: el código está como número en una hoja y como texto en otra. ──
def test_codigo_numerico_vs_texto():
    a = pd.DataFrame({"Punto": [4021, 4022, 4023], "Venta": [10, 20, 30]})
    b = pd.DataFrame({"Cod": ["4021", "4022", "4023"], "Zona": ["N", "S", "C"]})
    libro = _libro({"A": a, "B": b})
    rel = encontrar_hojas_relacionadas(libro, "A", "Punto")
    check("empareja código numérico con el mismo código en texto",
          len(rel) == 1 and rel[0]["columna"] == "Cod")


if __name__ == "__main__":
    test_cruce_con_nombres_distintos()
    test_control_hojas_sin_relacion()
    test_uno_a_muchos()
    test_codigo_numerico_vs_texto()
    print("\nCross-sheet test completado sin errores.")
