"""Bases donde la meta y el resultado son FILAS, no columnas.

Se reproduce la forma de la base real («Inf ventas - R1.xlsb», Hoja1): una
columna «Registro» con Presupuesto / Ejecución / Digitadas, la cifra repartida
entre dos columnas —`Activaciones` trae lo ejecutado y `Pry` trae tanto la
proyección como el presupuesto— y las dimensiones repetidas en cada fila.

Lo que esto evita, verificado contra ese archivo:

- sumar «Activaciones» mezclaba presupuesto y ejecución en una sola cifra;
- el motor buscaba la meta en una COLUMNA y no la encontraba, así que el panel
  decía «el archivo no trae una meta» con 2.710 filas de presupuesto dentro,
  y comparaba los canales por volumen en vez de por cumplimiento;
- la métrica principal salía por orden semántico («Ingresos · Digitadas») en
  lugar de la única medida comparable contra su presupuesto.

Y lo que NO debe pasar: la fecha no se puede sumar como si fuera una cifra
(colapsaba las 64.646 filas a 11, un mes entero en una sola fila), y una tabla
que ya viene ancha, o con una columna de categorías cualquiera, no se toca.

PYTHONPATH=. python tests/registro_largo_test.py
"""
import pandas as pd

from core.dashboard_engine import build_dashboard
from core.cuadro_comparativo import cuadro_comparativo
from core.performance import columna_meta
from core.profile import profile_sheet


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


CANALES = {"CAV": (100, 120), "DIGITAL": (60, 60), "TAT": (30, 90)}   # (ejecutado, presupuesto) por día


def _base():
    """Tres canales × tres días × tres tipos de registro, como la base real."""
    filas = []
    for dia in range(1, 4):
        for canal, (eje, ppto) in CANALES.items():
            filas.append({"Canal": canal, "Producto": "CHIPS", "Fecha": f"2026-09-0{dia}",
                          "Registro": "Ejecución", "Activaciones": eje, "Pry": eje * 1.5, "Ingresos": eje * 1000})
            filas.append({"Canal": canal, "Producto": "CHIPS", "Fecha": f"2026-09-0{dia}",
                          "Registro": "Digitadas", "Activaciones": eje // 2, "Pry": eje, "Ingresos": eje * 500})
            # El presupuesto no trae Activaciones: su cifra viaja en «Pry».
            filas.append({"Canal": canal, "Producto": "CHIPS", "Fecha": f"2026-09-0{dia}",
                          "Registro": "Presupuesto", "Activaciones": 0, "Pry": ppto, "Ingresos": 0})
    return pd.DataFrame(filas)


def _perfilar(df, hoja="Hoja1"):
    return profile_sheet(df, {"sheet_name": hoja, "workbook_name": "ventas.xlsx"})


def test_la_tabla_se_gira_y_las_cifras_cuadran():
    item = _perfilar(_base())
    df = item["processed"]
    check("una fila por combinación real, no una por tipo de registro", len(df) == 9)
    check("cada cruce medida × tipo es su propia columna",
          {"Activaciones · Ejecución", "Pry · Ejecución", "Pry · Presupuesto"} <= set(df.columns))
    check("un cruce sin ninguna cifra no ensucia la tabla (Activaciones del Presupuesto)",
          "Activaciones · Presupuesto" not in df.columns)
    check("el presupuesto ya no se mezcla con lo ejecutado",
          float(df["Activaciones · Ejecución"].sum()) == sum(e for e, _ in CANALES.values()) * 3)
    check("y el presupuesto queda completo",
          float(df["Pry · Presupuesto"].sum()) == sum(p for _, p in CANALES.values()) * 3)
    check("se deja dicho en el registro de carga",
          any("se giró" in l for l in item["profile"]["cleaning_log"]))


def test_la_fecha_no_se_suma_como_una_cifra():
    item = _perfilar(_base())
    df, schema = item["processed"], item["profile"]["schema"]
    check("la fecha sigue siendo una fecha, no una columna sumada", "Fecha" in schema["dates"])
    check("y los tres días siguen separados", pd.to_datetime(df["Fecha"]).dt.day.nunique() == 3)
    check("sin ninguna columna «Fecha · algo»", not any("Fecha ·" in str(c) for c in df.columns))


def test_ahora_hay_meta_y_se_compara_contra_ella():
    item = _perfilar(_base())
    df, schema = item["processed"], item["profile"]["schema"]
    check("«Pry · Presupuesto» es la meta de «Pry · Ejecución»",
          columna_meta(df, schema, "Pry · Ejecución") == "Pry · Presupuesto")
    tablero = build_dashboard(df, item["profile"])
    check("la métrica principal es la que tiene meta, no la de mayor tipo semántico",
          tablero["primary_metric"] == "Pry · Ejecución")
    check("y se deja dicho en el registro de carga",
          any("trae su propia meta" in l for l in item["profile"]["cleaning_log"]))
    check("los canales se comparan contra su meta, no por volumen",
          tablero["performance"]["base"]["clave"] == "meta")
    cuadro = cuadro_comparativo(df, schema, "Canal", "Pry · Ejecución")
    check("el cuadro usa el presupuesto como meta", cuadro["meta_col"] == "Pry · Presupuesto")
    check("la referencia es el grupo completo", cuadro["total_grupo"] == len(CANALES))
    por_canal = {f["nombre"]: round(f["cumplimiento"]) for f in cuadro["filas"]}
    # CAV 150/120 = 125 %, DIGITAL 90/60 = 150 %, TAT 45/90 = 50 %.
    check("gana quien más cumple su meta, no quien más vende (DIGITAL sobre CAV)",
          por_canal == {"CAV": 125, "DIGITAL": 150, "TAT": 50} and cuadro["filas"][0]["nombre"] == "DIGITAL")


def test_una_tabla_que_no_es_asi_no_se_toca():
    ancha = pd.DataFrame({"Canal": ["CAV", "DIGITAL", "TAT"] * 3,
                          "Fecha": ["2026-09-01"] * 3 + ["2026-09-02"] * 3 + ["2026-09-03"] * 3,
                          "Ventas": [10, 20, 30] * 3, "Presupuesto": [12, 18, 40] * 3})
    df = _perfilar(ancha, "Ancha")["processed"]
    check("una tabla que ya trae la meta en columna se deja igual",
          list(df.columns) == ["Canal", "Fecha", "Ventas", "Presupuesto"] and len(df) == 9)

    # Una columna de categorías sin ninguna meta entre sus valores: no es este caso.
    categorias = ancha.assign(Segmento=["Hogar", "Empresa", "Masivo"] * 3)
    df = _perfilar(categorias, "Categorias")["processed"]
    check("una categoría cualquiera no dispara el giro", "Segmento" in df.columns and len(df) == 9)

    # Con meta entre los valores pero sin filas que juntar, girar solo dejaría huecos.
    suelto = pd.DataFrame({"Canal": list("ABCDEFGH"), "Tipo": ["Presupuesto", "Real"] * 4,
                           "Valor": [1, 2, 3, 4, 5, 6, 7, 8]})
    df = _perfilar(suelto, "Suelto")["processed"]
    check("si al girar no se junta ninguna fila, la tabla se deja igual",
          "Tipo" in df.columns and len(df) == 8)


if __name__ == "__main__":
    test_la_tabla_se_gira_y_las_cifras_cuadran()
    test_la_fecha_no_se_suma_como_una_cifra()
    test_ahora_hay_meta_y_se_compara_contra_ella()
    test_una_tabla_que_no_es_asi_no_se_toca()
    print("\nRegistro largo test completado sin errores.")
