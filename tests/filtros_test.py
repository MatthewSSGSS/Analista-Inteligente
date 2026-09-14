"""Que se pueda filtrar por cualquier columna, y que ningún filtro se escape.

Tres cosas se prueban aquí, y las tres fallaban antes:

- **Alcance**: toda columna con datos tiene un filtro en algún lugar del menú,
  no solo las que el esquema clasificó como categoría.
- **Un solo motor**: el panel, el seguimiento y las opciones en cascada
  entienden las mismas reglas. Antes el seguimiento ignoraba en silencio los
  filtros que no fueran de lista.
- **Nada se escapa**: las celdas vacías se pueden elegir o excluir, y los
  rangos incluyen sus extremos.

PYTHONPATH=. python tests/filtros_test.py
"""
import ast
import io

import pandas as pd

from core.filter_engine import (VACIO, apply_filters, cascading_options, columnas_filtrables,
                                describir_regla)
from core.profile import profile_sheet


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _archivo():
    filas = []
    for i in range(60):
        filas.append({
            "Fecha": f"2026-{(i % 6) + 1:02d}-{(i % 27) + 1:02d}",
            "Region": ["Caribe", "Andina", "Pacifica"][i % 3],
            "Canal": ["Retail", "Digital"][i % 2],
            "Punto": f"PDV {i:03d}",
            "Codigo": f"C-{i:05d}",
            "Ventas": None if i % 11 == 0 else 100 + i * 10,
            "Observacion": None if i % 4 == 0 else ("Pendiente" if i % 2 else "Ok"),
        })
    item = profile_sheet(pd.DataFrame(filas), {"sheet_name": "H", "workbook_name": "h.xlsx"})
    return item["processed"], item["profile"]["schema"]


def test_toda_columna_tiene_su_filtro():
    df, schema = _archivo()
    columnas = columnas_filtrables(df, schema)
    nombres = {c["columna"] for c in columnas}
    reales = {c for c in df.columns if not str(c).startswith("__")}
    check("todas las columnas con datos se pueden filtrar", reales <= nombres)
    tipos = {c["columna"]: c["tipo"] for c in columnas}
    check("una métrica se filtra por rango", tipos["Ventas"] == "numero")
    check("una categoría, por lista", tipos["Region"] == "opciones")
    check("una fecha, por rango de fechas", tipos["Fecha"] == "fecha")
    check("una columna con muchos valores sigue teniendo lista si cabe", tipos["Punto"] == "opciones")

    muchos = pd.DataFrame({"Codigo": [f"X{i:05d}" for i in range(2500)], "Valor": range(2500)})
    tipos_muchos = {c["columna"]: c["tipo"] for c in columnas_filtrables(muchos, {})}
    check("con demasiados valores para una lista, se filtra por texto", tipos_muchos["Codigo"] == "texto")

    vacia = pd.DataFrame({"A": [1, 2, 3], "Nada": [None, None, None]})
    check("una columna sin ningún dato no ofrece filtro",
          "Nada" not in {c["columna"] for c in columnas_filtrables(vacia, {})})


def test_las_reglas_no_dejan_escapar_nada():
    df, _ = _archivo()
    total = len(df)
    sin_ventas = int(pd.to_numeric(df["Ventas"], errors="coerce").isna().sum())
    sin_observacion = int(df["Observacion"].isna().sum())

    solo_ok = apply_filters(df, {"Observacion": {"op": "in", "value": ["Ok"]}})
    check("una lista deja solo los valores elegidos", set(solo_ok["Observacion"].astype(str)) == {"Ok"})
    con_vacias = apply_filters(df, {"Observacion": {"op": "in", "value": ["Ok", VACIO]}})
    check("elegir «(Vacío)» suma las filas sin dato",
          len(con_vacias) == len(solo_ok) + sin_observacion)

    ventas = pd.to_numeric(df["Ventas"], errors="coerce")
    desde, hasta = float(ventas.min()), 300.0
    en_rango = int(((ventas >= desde) & (ventas <= hasta)).sum())
    incluye = apply_filters(df, {"Ventas": {"op": "between", "value": [desde, hasta], "incluir_vacios": True}})
    excluye = apply_filters(df, {"Ventas": {"op": "between", "value": [desde, hasta], "incluir_vacios": False}})
    check("un rango incluye sus dos extremos", len(excluye) == en_rango)
    check("y puede conservar las filas vacías", len(incluye) == en_rango + sin_ventas)

    fechas = pd.to_datetime(df["Fecha"], errors="coerce")
    ultimo_dia = fechas.max().normalize()
    fin_del_dia = ultimo_dia + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    rango = apply_filters(df, {"Fecha": {"op": "date_between", "value": [ultimo_dia, fin_del_dia]}})
    check("un rango de fechas incluye todo el último día", len(rango) == int((fechas >= ultimo_dia).sum()))

    check("contiene no distingue mayúsculas",
          len(apply_filters(df, {"Punto": {"op": "contains", "value": "pdv 00"}})) == 10)
    check("una columna que ya no existe se ignora",
          len(apply_filters(df, {"NoExiste": {"op": "in", "value": ["x"]}})) == total)
    check("una regla mal formada no tumba el panel",
          len(apply_filters(df, {"Ventas": {"op": "between", "value": ["abc", None]}})) == total)
    check("apply_filters devuelve una sola tabla", isinstance(apply_filters(df, {}), pd.DataFrame))


def test_la_cascada_entiende_los_mismos_filtros():
    df, _ = _archivo()
    regla = {"Ventas": {"op": "between", "value": [100, 200], "incluir_vacios": False}}
    opciones = cascading_options(df, ["Punto", "Observacion"], regla, limit=2000)
    ventas = pd.to_numeric(df["Ventas"], errors="coerce")
    esperados = set(df.loc[(ventas >= 100) & (ventas <= 200), "Punto"].astype(str))
    check("un rango numérico también acota las opciones de las listas",
          set(opciones["Punto"]) - {VACIO} == esperados)
    todas = cascading_options(df, ["Observacion"], {}, limit=2000)["Observacion"]
    check("si hay celdas vacías, «(Vacío)» aparece primero", todas[0] == VACIO)


def test_los_filtros_se_describen_en_palabras():
    check("lista", describir_regla("Region", {"op": "in", "value": ["Caribe", "Andina"]}) == "Region: Caribe, Andina")
    check("rango sin vacíos",
          describir_regla("Ventas", {"op": "between", "value": [100, 2500.5], "incluir_vacios": False})
          == "Ventas: de 100 a 2,500.50, sin vacíos")
    check("rango de fechas",
          describir_regla("Fecha", {"op": "date_between",
                                    "value": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-03-31")]})
          == "Fecha: del 01/01/2026 al 31/03/2026")
    check("texto contenido", describir_regla("Punto", {"op": "contains", "value": "pdv"}) == "Punto contiene «pdv»")


def test_el_panel_no_desempaqueta_la_tabla():
    """`df, _meta = apply_filters(...)` tumbaba la app con cualquier filtro que
    no fuera de lista: la función devuelve una sola tabla."""
    arbol = ast.parse(io.open("app.py", encoding="utf-8").read())
    desempaquetados = [
        nodo.lineno for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Assign) and isinstance(nodo.value, ast.Call)
        and isinstance(nodo.value.func, ast.Name) and nodo.value.func.id == "apply_filters"
        and any(isinstance(t, ast.Tuple) for t in nodo.targets)
    ]
    check("app.py no desempaqueta el resultado de apply_filters", not desempaquetados)


def test_el_seguimiento_respeta_todos_los_filtros():
    import streamlit as st

    from ui.person_profile import _apply_current_filters

    df, _ = _archivo()
    st.session_state["filters"] = {"Ventas": {"op": "between", "value": [100, 200], "incluir_vacios": False}}
    try:
        visto = _apply_current_filters(df)
    finally:
        st.session_state["filters"] = {}
    ventas = pd.to_numeric(df["Ventas"], errors="coerce")
    check("un rango numérico también se aplica en el seguimiento",
          len(visto) == int(((ventas >= 100) & (ventas <= 200)).sum()))


def test_el_menu_ofrece_todas_las_columnas():
    import streamlit as st

    from ui.filtros import render_filtros_por_columna

    df, schema = _archivo()
    capturas = {}
    original = st.multiselect

    def multiselect(label, opciones, **k):
        capturas[k.get("key")] = list(opciones)
        return st.session_state.get(k.get("key"), [])

    for clave in [k for k in st.session_state.keys() if str(k).startswith("filter_")]:
        del st.session_state[clave]
    st.session_state["filters"] = {}
    st.multiselect = multiselect
    try:
        visibles = render_filtros_por_columna(df, schema, "H")
    finally:
        st.multiselect = original
    selector = set(capturas.get("filter_H__columnas", []))
    periodo = schema["dates"][0]
    reales = {c for c in df.columns if not str(c).startswith("__")}
    check("cada columna se puede filtrar desde algún lugar del menú", reales <= selector | set(visibles) | {periodo})
    check("la segmentación visible no pasa de cuatro listas", len(visibles) <= 4)
    check("el periodo no se ofrece dos veces", periodo not in selector)

    # "Ver análisis" pone un filtro sin tocar el menú: no debe borrarse al redibujar.
    for clave in [k for k in st.session_state.keys() if str(k).startswith("filter_")]:
        del st.session_state[clave]
    st.session_state["filters"] = {"Canal": {"op": "in", "value": ["Digital"]}}
    st.multiselect = multiselect
    try:
        render_filtros_por_columna(df, schema, "H")
    finally:
        st.multiselect = original
    check("un filtro puesto desde «Ver análisis» sigue activo tras redibujar el menú",
          st.session_state["filters"].get("Canal", {}).get("value") == ["Digital"])
    st.session_state["filters"] = {}


def test_las_celdas_vacias_de_verdad():
    """Con celdas vacías reales, sin pasar por la limpieza del archivo.

    La limpieza convierte algunas celdas vacías antes de que lleguen al
    panel, así que probar los vacíos con un archivo procesado podía pasar sin
    probar nada. Aquí el motor recibe los vacíos tal cual.
    """
    crudo = pd.DataFrame({
        "Ventas": [100.0, None, 250.0, None, 400.0],
        "Estado": ["Ok", None, "", "Pendiente", "Ok"],
        "Alta": ["2026-01-05", None, "2026-02-10", "2026-03-15", None],
    })
    sin_vacios = apply_filters(crudo, {"Ventas": {"op": "between", "value": [100, 300], "incluir_vacios": False}})
    con_vacios = apply_filters(crudo, {"Ventas": {"op": "between", "value": [100, 300], "incluir_vacios": True}})
    check("un rango sin vacíos deja fuera las celdas vacías", len(sin_vacios) == 2)
    check("con vacíos, las conserva", len(con_vacios) == 4)
    vacias = apply_filters(crudo, {"Estado": {"op": "in", "value": [VACIO]}})
    check("«(Vacío)» toma tanto las celdas nulas como las de texto vacío", len(vacias) == 2)
    fechas = apply_filters(crudo, {"Alta": {"op": "date_between",
                                            "value": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-12-31")],
                                            "incluir_vacios": False}})
    check("un rango de fechas sin vacíos deja fuera las filas sin fecha", len(fechas) == 3)
    opciones = cascading_options(crudo, ["Estado"], {}, limit=100)["Estado"]
    check("la lista ofrece «(Vacío)» y no un valor en blanco", opciones[0] == VACIO and "" not in opciones)


if __name__ == "__main__":
    test_toda_columna_tiene_su_filtro()
    test_las_reglas_no_dejan_escapar_nada()
    test_las_celdas_vacias_de_verdad()
    test_la_cascada_entiende_los_mismos_filtros()
    test_los_filtros_se_describen_en_palabras()
    test_el_panel_no_desempaqueta_la_tabla()
    test_el_seguimiento_respeta_todos_los_filtros()
    test_el_menu_ofrece_todas_las_columnas()
    print("\nFiltros test completado sin errores.")
