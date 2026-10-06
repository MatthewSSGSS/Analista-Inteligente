"""Regresión de la Estructura comercial (core/estructura.py).

El caso real: un jefe recibe cuatro archivos —estructura (región › jefe ›
supervisor › agente), puntos de venta con su código, metas y ventas del
día— y los cruza a mano con BUSCARV. Aquí se arman esos cuatro archivos con
los problemas que los vuelven difíciles de cruzar y que un BUSCARV no avisa:

- el código del punto viene como número en un archivo («123») y como texto
  con ceros a la izquierda en otro («00123»), y la columna se llama distinto
  en cada uno (`Código M.`, `Cod PDV`, `Código`);
- el nombre del agente viene con y sin tildes / mayúsculas;
- un agente (Pedro) está con dos supervisores de dos jefes distintos;
- un punto vende pero no está en la estructura (huérfano) y otro está en la
  estructura pero no vendió;
- la meta de un supervisor no cuadra con la suma de la de sus puntos.

Lo que no debe pasar nunca: que el cruce duplique ventas (la suma de la
tabla unificada debe ser exactamente la de los archivos), que la meta se
repita en cada fila de ventas, o que un punto sin ventas desaparezca.

Se corre igual que tests/smoke_test.py: PYTHONPATH=. python tests/estructura_test.py
"""
import io

import pandas as pd

from core.loader import load_workbook
from core import estructura as E


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print(f"OK   {label}")


def _subida(nombre, hojas: dict):
    b = io.BytesIO()
    if nombre.endswith(".csv"):
        next(iter(hojas.values())).to_csv(b, index=False)
    else:
        with pd.ExcelWriter(b) as w:
            for hoja, df in hojas.items():
                df.to_excel(w, index=False, sheet_name=hoja)
    datos = b.getvalue()
    return type("Upload", (), {"getvalue": lambda self: datos, "name": nombre})()


def _archivos():
    estructura = pd.DataFrame({
        "Región": ["Norte", "Norte", "Norte", "Sur", "Sur"],
        "Jefe de zona": ["Ana Gómez", "Ana Gómez", "Ana Gómez", "Luis Mora", "Luis Mora"],
        "Supervisor": ["Sofía Ruiz", "Sofía Ruiz", "Carlos Díaz", "Marta León", "Marta León"],
        "Asesor": ["José Pérez", "Pedro Ríos", "Laura Gil", "Pedro Ríos", "Nina Paz"],
        "Cédula asesor": [1001, 1002, 1003, 1002, 1005],
    })
    puntos = pd.DataFrame({
        "Código M.": [123, 124, 125, 126, 127, 128],
        "Nombre del punto": ["Tienda La 14", "Mini Sur", "Don Pepe", "La Esquina", "El Sol", "Tienda Nueva"],
        # Sin tildes y en mayúsculas: el mismo agente que en la estructura.
        "Asesor": ["JOSE PEREZ", "Pedro Rios", "Laura Gil", "Laura Gil", "Nina Paz", "Nina Paz"],
        "Ciudad": ["Barranquilla", "Soledad", "Cartagena", "Cartagena", "Neiva", "Neiva"],
    })
    metas_pdv = pd.DataFrame({
        "Cod PDV": [123, 124, 125, 126, 127, 128],
        "Meta": [1000, 800, 600, 400, 500, 300],
        "Presupuesto": [100, 80, 60, 40, 50, 30],
    })
    metas_sup = pd.DataFrame({
        "Supervisor": ["Sofía Ruiz", "Carlos Díaz", "Marta León"],
        # Sofía: 1000+800 = 1800 ✓ · Carlos: 600+400 = 1000, pero dice 1500 ✗
        # Marta: Pedro (800, compartido) + Nina (500+300) = 1600 ✓
        "Meta": [1800, 1500, 1600],
    })
    ventas = pd.DataFrame({
        "Fecha": ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-03", "2026-09-05", "2026-09-06", "2026-09-06"],
        # Texto con ceros a la izquierda; 999 no está en la estructura; 128 no vendió.
        "Código": ["00123", "00123", "00124", "00125", "00126", "00127", "00999"],
        "Ventas": [150.0, 200.0, 90.0, 120.0, 60.0, 75.0, 40.0],
    })
    return [
        load_workbook(_subida("estructura.xlsx", {"Equipo": estructura})),
        load_workbook(_subida("puntos.xlsx", {"Puntos": puntos})),
        load_workbook(_subida("metas.xlsx", {"Metas PDV": metas_pdv, "Metas supervisores": metas_sup})),
        load_workbook(_subida("ventas.csv", {"CSV": ventas})),
    ], ventas


def main():
    libros, ventas = _archivos()
    res = E.cruzar(libros)
    t = res["tabla"]
    print(t.to_string())

    # ── Qué se entendió de cada columna ──
    roles = {(m["archivo"], c["columna"]): c["rol"] for m in res["mapeo"] for c in m["columnas"]}
    check("«Jefe de zona» es el jefe, no la región", roles[("estructura.xlsx", "Jefe de zona")] == "nivel:jefe:nombre")
    check("«Cédula asesor» es el código del agente", roles[("estructura.xlsx", "Cédula asesor")] == "nivel:agente:codigo")
    check("«Código M.» es el código del PDV", roles[("puntos.xlsx", "Código M.")] == "nivel:pdv:codigo")
    check("«Cod PDV» es el código del PDV", roles[("metas.xlsx", "Cod PDV")] == "nivel:pdv:codigo")
    check("«Código» a secas en ventas termina como código del PDV", roles[("ventas.csv", "Código")] == "nivel:pdv:codigo")
    check("«Ventas» es el resultado", roles[("ventas.csv", "Ventas")] == "real")
    check("«Meta» y «Presupuesto» se reconocen", roles[("metas.xlsx", "Meta")] == "meta"
          and roles[("metas.xlsx", "Presupuesto")] == "presupuesto")

    # ── El cruce no inventa ni pierde ventas ──
    check("la suma de ventas es exactamente la de los archivos",
          abs(t["Ventas"].sum() - ventas["Ventas"].sum()) < 1e-9)
    check("la meta va UNA vez por punto (suma = suma de metas de PDV)", abs(t["Meta"].sum() - 3600) < 1e-9)
    check("el presupuesto también", abs(t["Presupuesto"].sum() - 360) < 1e-9)
    check("el punto sin ventas aparece con cero", (t.loc[t["PDV"] == "Tienda Nueva", "Ventas"].fillna(0) == 0).all()
          and (t["PDV"] == "Tienda Nueva").any())

    # ── Códigos y nombres distintos entre archivos ──
    fila_123 = t[t["Código PDV"] == "123"]
    check("«00123» de ventas cruzó con 123 de la estructura", len(fila_123) >= 2
          and (fila_123["PDV"] == "Tienda La 14").all())
    check("«JOSE PEREZ» es «José Pérez»", set(fila_123["Agente"]) == {"José Pérez"})
    check("y hereda su supervisor, jefe y región", set(fila_123["Supervisor"]) == {"Sofía Ruiz"}
          and set(fila_123["Jefe"]) == {"Ana Gómez"} and set(fila_123["Región"]) == {"Norte"})
    check("la ciudad del punto viaja a sus ventas", set(fila_123["Ciudad"]) == {"Barranquilla"})

    # ── Agente con dos superiores ──
    pedro = t[t["Agente"] == "Pedro Ríos"]
    check("Pedro queda compartido entre sus dos supervisores", set(pedro["Supervisor"]) == {"Marta León / Sofía Ruiz"})
    check("y entre sus dos jefes", set(pedro["Jefe"]) == {"Ana Gómez / Luis Mora"})
    rutas = E.rutas(res["red"], "agente", "Pedro Ríos")
    check("la ficha de Pedro muestra sus dos cadenas de mando", len(rutas) == 2)

    # ── Lo que no cruzó ──
    textos = " | ".join(a["texto"] for a in res["avisos"])
    huerfano = next((a for a in res["avisos"] if a["tipo"] == "error" and "pdv" in a["texto"].lower()), None)
    check("el PDV que vende sin estar en la estructura se avisa", huerfano is not None and "999" in huerfano["ejemplos"])
    check("el punto sin ventas se avisa", "no tienen ningún resultado" in textos)
    check("la meta de Carlos que no cuadra se avisa",
          any("Carlos Díaz" in e for a in res["avisos"] for e in a["ejemplos"]))
    check("Sofía, que sí cuadra, no aparece en el descuadre",
          not any(e.startswith("Sofía Ruiz:") for a in res["avisos"] for e in a["ejemplos"]))

    # ── Navegación: cómo va cada uno ──
    medida = E.medida_principal(res)
    check("la medida principal es Ventas", medida == "Ventas")
    jefes = E.resumen_por_nivel(t, res, "jefe", medida).set_index("Jefe")
    check("la meta del jefe sale de sumar la de sus supervisores", jefes.at["Ana Gómez", "Meta"] == 1800 + 1500
          and jefes.at["Ana Gómez", "Origen meta"] == "suma de supervisores")
    # Ana: José 350 + Pedro 90 (compartido) + Laura 180 = 620
    check("el real del jefe incluye lo compartido completo", jefes.at["Ana Gómez", "Real"] == 620)
    check("y dice cuánto de eso es compartido", jefes.at["Ana Gómez", "Compartido"] == 90)
    c = E.corte(t, res, medida)
    check("el corte es el último día con ventas (6 de septiembre)", c and c["dia"] == 6 and c["dias_mes"] == 30)
    check("al día 6 de 30 se espera el 20 %", abs(c["esperado"] - 0.2) < 1e-9)
    check("la posición se cuenta sobre todos los jefes", set(jefes["De"]) == {2})

    ana = E.ficha(t, res, "jefe", "Ana Gómez", medida)
    check("debajo de Ana solo están sus supervisores (no Marta, aunque comparta a Pedro)",
          set(ana["debajo"]["Supervisor"]) == {"Sofía Ruiz", "Carlos Díaz"})
    check("y el puesto se cuenta entre esos dos", set(ana["debajo"]["De"]) == {2})

    f = E.ficha(t, res, "supervisor", "Carlos Díaz", medida)
    check("la ficha de Carlos marca el descuadre de su meta", f["descuadre"] == {"declarada": 1500.0, "suma": 1000.0})
    check("y lista sus agentes debajo", list(f["debajo"]["Agente"]) == ["Laura Gil"])
    pdv = E.ficha(t, res, "pdv", "Don Pepe", medida)
    check("la ficha de un PDV trae su código y su ciudad", pdv["codigo"] == "125" and pdv["datos"].get("Ciudad") == "Cartagena")
    check("y su ruta completa hasta la región", pdv["rutas"][0][0] == ("region", "Norte"))

    # ── Corrección manual de una columna ──
    ajustado = E.cruzar(libros, {("puntos.xlsx", "Puntos", "Ciudad"): "ignorar"})
    check("una columna marcada «No usar» sale de la tabla", "Ciudad" not in ajustado["tabla"].columns)

    # ── Nombres con números ──
    # «Agente 7» o «Tienda 12» NO son números: `numeric_valid` les quita las
    # letras y los leía como 7 y 12, y entonces la columna de nombres pasaba
    # por la de códigos y nada cruzaba (encontrado con 5.000 PDV).
    agentes = pd.DataFrame({"Supervisor": ["Sup 1", "Sup 1", "Sup 2"],
                            "Asesor": ["Agente 1", "Agente 2", "Agente 3"], "Cédula asesor": [11, 12, 13]})
    puntos = pd.DataFrame({"Código M.": [501, 502, 503], "Nombre PDV": ["Tienda 1", "Tienda 2", "Tienda 3"],
                           "Cédula asesor": [11, 12, 13]})
    ventas2 = pd.DataFrame({"Código": ["501", "503", "503"], "Ventas": [5, 7, 8]})
    r2 = E.cruzar([load_workbook(_subida("agentes.csv", {"CSV": agentes})),
                   load_workbook(_subida("pdv.csv", {"CSV": puntos})),
                   load_workbook(_subida("ventas2.csv", {"CSV": ventas2}))])
    roles2 = {(m["archivo"], c["columna"]): c["rol"] for m in r2["mapeo"] for c in m["columnas"]}
    check("«Asesor» con valores «Agente 1» es el nombre del agente", roles2[("agentes.csv", "Asesor")] == "nivel:agente:nombre")
    check("«Nombre PDV» con «Tienda 1» es el nombre del PDV", roles2[("pdv.csv", "Nombre PDV")] == "nivel:pdv:nombre")
    check("y «Código M.» sigue siendo el código", roles2[("pdv.csv", "Código M.")] == "nivel:pdv:codigo")
    t2 = r2["tabla"]
    check("las ventas llegan hasta el supervisor", t2.loc[t2["PDV"] == "Tienda 3", "Supervisor"].eq("Sup 2").all()
          and t2.loc[t2["PDV"] == "Tienda 3", "Ventas"].sum() == 15)

    print("\nEstructura comercial: todo en orden.")


if __name__ == "__main__":
    main()
