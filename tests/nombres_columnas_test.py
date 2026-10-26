"""Regresión: el mismo archivo se lee igual se llamen como se llamen sus columnas.

Un exporte de otro sistema trae VLR_NETO, Doc, Mpio, Obj, Und, Mg en vez de
Ventas, Cédula, Ciudad, Meta, Cantidad, Margen. La detección buscaba palabras
completas en el nombre, así que con esos encabezados:

- «Doc» (cédulas) quedaba como métrica: el panel sumaba cédulas;
- «Mpio» no era geografía: no había mapa, aunque los valores eran municipios;
- «Obj» no era la meta: no había cumplimiento;
- un número de serie de Excel en «Corte» o «F. Venta» quedaba como número,
  sin fecha el archivo caía en «📚 Vista principal».

Aquí se carga el mismo contenido con nombres claros y con abreviaturas, y se
exige que se lea igual. También que las abreviaturas ambiguas que se dejaron
fuera del diccionario (ver core/abreviaturas.py) no cambien nada.

Se corre igual que tests/smoke_test.py: PYTHONPATH=. python tests/nombres_columnas_test.py
"""
import numpy as np
import pandas as pd

from core.abreviaturas import nombre_legible
from core.performance import columna_meta
from core.schema import detect_schema


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _datos():
    rng = np.random.default_rng(1)
    n = 300
    venta = rng.integers(200_000, 5_000_000, n)
    return {
        "fecha": pd.date_range("2025-01-01", periods=n, freq="D"),
        "persona": rng.choice(["Ana Gómez", "Luis Díaz", "Juan Pérez", "Marta Ruiz", "Carlos Rojas"], n),
        "cedula": rng.choice([52111222, 79000111, 1020304050, 43555666, 80123456], n),
        "ciudad": rng.choice(["Bogotá", "Medellín", "Cali", "Barranquilla", "Cartagena"], n),
        "venta": venta,
        "meta": (venta * rng.uniform(.8, 1.3, n)).round(),
        "unidades": rng.integers(1, 40, n),
        "margen": rng.uniform(5, 45, n).round(1),
    }


CLAROS = {"fecha": "Fecha", "persona": "Vendedor", "cedula": "Cédula", "ciudad": "Ciudad",
          "venta": "Ventas", "meta": "Meta", "unidades": "Cantidad", "margen": "Margen %"}
ABREVIADOS = {"fecha": "Corte", "persona": "Responsable", "cedula": "Doc", "ciudad": "Mpio",
              "venta": "VLR_NETO", "meta": "Obj", "unidades": "Und", "margen": "Mg"}


def _leer(nombres):
    d = _datos()
    df = pd.DataFrame({nombres[k]: v for k, v in d.items()})
    schema = detect_schema(df.copy())
    rol = {}
    for k, c in nombres.items():
        if c in schema["dates"]:
            rol[k] = "fecha"
        elif c in schema["ids"]:
            rol[k] = "id"
        elif c in schema["geography"]:
            rol[k] = "geo"
        elif c in schema["metrics"]:
            rol[k] = "metrica:" + schema["types"][c]
        else:
            rol[k] = "otro"
    meta = columna_meta(df, schema)
    return rol, (meta and {v: k for k, v in nombres.items()}[meta])


def el_traductor_escribe_completo_lo_abreviado():
    check("VLR_NETO → valor NETO", nombre_legible("VLR_NETO") == "valor NETO")
    check("F. Venta → fecha Venta", nombre_legible("F. Venta") == "fecha Venta")
    check("Mpio → municipio", nombre_legible("Mpio") == "municipio")
    check("VlrNeto (camello) → valor Neto", nombre_legible("VlrNeto") == "valor Neto")
    check("Ppto2026 → presupuesto2026", nombre_legible("Ppto2026") == "presupuesto2026")
    check("un nombre normal no cambia", nombre_legible("Ventas Totales") == "Ventas Totales")
    # Partirlo sin traducir nada cambiaba la lectura: «Dias Mora» se tomaba
    # como fecha (por «día») y el panel se caía (tests/smoke_test.py).
    check("sin abreviaturas no se parte: DiasMora sigue igual", nombre_legible("DiasMora") == "DiasMora")
    check("ni se tocan sus separadores", nombre_legible("Ventas_2026") == "Ventas_2026")
    check("«F» sola no se vuelve fecha", nombre_legible("F") == "F")
    check("ambiguas fuera: Pto Venta no cambia", nombre_legible("Pto Venta") == "Pto Venta")
    check("ambiguas fuera: Desc no cambia", nombre_legible("Desc") == "Desc")


def abreviado_se_lee_igual_que_claro():
    claros, meta_c = _leer(CLAROS)
    abreviados, meta_a = _leer(ABREVIADOS)
    for k in ("fecha", "cedula", "ciudad"):
        check(f"{CLAROS[k]} y {ABREVIADOS[k]} cumplen el mismo papel ({claros[k]})", claros[k] == abreviados[k])
    check("Doc (cédulas) es identificador: no se suma", abreviados["cedula"] == "id")
    check("Mpio es geografía: hay mapa", abreviados["ciudad"] == "geo")
    check("VLR_NETO es dinero", abreviados["venta"] == "metrica:Moneda")
    check("Und es cantidad", abreviados["unidades"] == "metrica:Cantidad")
    check("Mg es porcentaje", abreviados["margen"] == "metrica:Porcentaje")
    check("la meta se encuentra con nombre claro", meta_c == "meta")
    check("Obj se encuentra como meta", meta_a == "meta")


def la_fecha_en_numero_de_serie_se_reconoce_con_otros_nombres():
    dias = pd.date_range("2025-01-05", periods=40, freq="7D")
    serie = (dias - pd.Timestamp("1899-12-30")).days.astype(int)
    periodo = dias.strftime("%Y%m").astype(int)
    for nombre in ("Corte", "Emisión", "F. Venta", "F_Pago", "Fec Ingreso", "Vencimiento"):
        for etiqueta, valores in (("serie de Excel", serie), ("periodo AAAAMM", periodo)):
            df = pd.DataFrame({nombre: valores, "Vendedor": ["A", "B", "C", "D"] * 10, "Valor": range(40)})
            check(f"«{nombre}» como {etiqueta} es fecha", nombre in detect_schema(df)["dates"])
    # Una cantidad con nombre de cantidad NO se vuelve fecha por estar en el
    # rango de un número de serie: eso lo tienen que probar los valores.
    df = pd.DataFrame({"Activaciones": serie, "Vendedor": ["A", "B", "C", "D"] * 10})
    check("«Activaciones» en rango de serie sigue siendo cantidad", "Activaciones" not in detect_schema(df)["dates"])


def sin_nombre_se_reconoce_por_los_valores():
    """Col1…Col8: el nombre no dice nada y los valores sí (core/por_valores.py)."""
    d = _datos()
    personas = ["Ana Gómez", "Luis Díaz", "Juan Pérez", "Marta Ruiz", "Carlos Rojas"]
    cedulas = dict(zip(personas, [52111222, 79000111, 1020304050, 43555666, 80123456]))
    d["cedula"] = pd.Series(d["persona"]).map(cedulas).to_numpy()   # cada cédula, siempre la misma persona
    d["fecha"] = (d["fecha"] - pd.Timestamp("1899-12-30")).days.astype(int)  # serie de Excel
    df = pd.DataFrame({f"Col{i}": v for i, v in enumerate(d.values(), 1)})
    schema = detect_schema(df)
    sem = {x["column"]: x.get("semantic_type") for x in schema["semantic"]["columns"]}
    check("Col1 (número de serie) es fecha: no cae en «Vista principal»", schema["dates"] == ["Col1"])
    check("Col2 son personas", sem["Col2"] == "name")
    check("Col3 (cédulas 1 a 1 con la persona) es identificador", "Col3" in schema["ids"])
    check("Col3 no se suma", "Col3" not in schema["metrics"] and "Col3" not in schema["semantic"]["metrics"])
    check("Col4 (municipios) es geografía", "Col4" in schema["geography"])
    check("y queda explicado por qué", set(schema.get("por_valores", {})) == {"Col1", "Col2", "Col3", "Col4"})
    check("Col5…Col8 siguen siendo métricas (meta/porcentaje se confirman a mano)",
          {"Col5", "Col6", "Col7", "Col8"} <= set(schema["metrics"]))


def los_valores_no_inventan_papeles():
    n = 60
    # Productos y zonas: dos palabras con mayúscula, pero sin nombres de pila.
    df = pd.DataFrame({"Campo": ["Plan Oro", "Zona Norte", "Tarjeta Clásica", "Plan Plata"] * 15,
                       "Valor": range(n)})
    sem = {x["column"]: x.get("semantic_type") for x in detect_schema(df)["semantic"]["columns"]}
    check("«Plan Oro», «Zona Norte» no son personas", sem["Campo"] != "name")
    # Apellidos que son lugares: es una persona, nunca un lugar.
    df = pd.DataFrame({"Campo": ["Juan Córdoba Gómez", "María Pereira López", "Ana Santander Ruiz",
                                 "Luis Bolívar Díaz"] * 15, "Valor": range(n)})
    schema = detect_schema(df)
    check("«Juan Córdoba Gómez» no es un lugar", "Campo" not in schema["geography"])
    # Tabla resumen, una fila por persona: la venta va 1 a 1 con el nombre,
    # pero no se repite, así que sigue siendo una métrica.
    df = pd.DataFrame({"Campo": ["Ana Gómez", "Luis Díaz", "Juan Pérez", "Marta Ruiz"],
                       "Total": [1200, 3400, 560, 7800]})
    schema = detect_schema(df)
    check("una venta por persona en un resumen sigue siendo métrica", "Total" in schema["metrics"])
    # La meta fija de cada región, mes a mes, va 1 a 1 con la región igual que
    # una cédula con su persona; es redonda y no es un documento.
    df = pd.DataFrame({"Region": ["R1", "R2", "R3", "R4"] * 6, "Ventas": range(24),
                       "Campo": [4_000_000, 2_500_000, 3_200_000, 1_800_000] * 6})
    check("una meta fija por región no se toma por código", "Campo" not in detect_schema(df)["ids"])
    # Precios redondos dentro del rango de las fechas de Excel: no son fechas.
    df = pd.DataFrame({"Item": list("ABCDEFGHIJ") * 4,
                       "Campo": [35000, 42000, 39900, 45500, 50000, 38000, 41000, 47000, 36500, 44000] * 4})
    check("precios redondos en rango de serie no son fecha", detect_schema(df)["dates"] == [])
    # Con una fecha de verdad en la hoja, otro entero en rango no se toca.
    dias = pd.date_range("2025-01-05", periods=40, freq="7D")
    df = pd.DataFrame({"Fecha": dias, "Campo": (dias - pd.Timestamp("1899-12-30")).days + 3})
    check("si ya hay fecha, no se busca otra en los números", detect_schema(df)["dates"] == ["Fecha"])


if __name__ == "__main__":
    el_traductor_escribe_completo_lo_abreviado()
    abreviado_se_lee_igual_que_claro()
    la_fecha_en_numero_de_serie_se_reconoce_con_otros_nombres()
    sin_nombre_se_reconoce_por_los_valores()
    los_valores_no_inventan_papeles()
    print("\nNombres de columnas test completado sin errores.")
