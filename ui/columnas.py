"""«🔎 Columnas»: cómo leyó el panel cada columna, y corregirlo.

La lectura y la corrección viven en core/columnas.py; aquí solo se dibujan.
La corrección se guarda en la propia hoja del libro cargado (item), así que
sobrevive a cambiar de vista y la usan todas: filtros, KPIs, mapa, informes.
"""
import pandas as pd
import streamlit as st

from core.columnas import PAPELES, aplicar_papeles, lectura
from core.quality import assess
from ui.components.escena import cabecera


def render_columnas(item: dict, hoja: str) -> None:
    df, schema = item["processed"], item["profile"]["schema"]
    filas = lectura(df, schema)
    por_revisar = sum(1 for f in filas if f["revisar"])
    corregidas = len(schema.get("papeles_usuario") or {})
    cabecera("Así entendí tus columnas",
             "Qué es cada columna para el panel. Si algo no cuadra, corrígelo y todo se recalcula.",
             ceja="Columnas", icono="🔎",
             cifras=[(str(len(filas)), "columnas"), (str(por_revisar), "para revisar"),
                     (str(corregidas), "corregidas por ti")],
             clave="cab_columnas", respaldo_html="<h3>🔎 Así entendí tus columnas</h3>")

    if not schema.get("dates"):
        st.warning("No encontré ninguna columna de fecha, por eso el panel no muestra tendencias ni "
                   "proyección. Si alguna columna sí es una fecha, márcala como «Fecha».")
    if por_revisar:
        st.info(f"{por_revisar} columna(s) tienen un nombre que no dice qué son: van primero. "
                "Una cifra sin nombre puede ser la venta, la meta o el costo; solo tú sabes cuál.")

    filas.sort(key=lambda f: not f["revisar"])  # las dudosas arriba, el resto en su orden
    tabla = pd.DataFrame([{"Revisar": "⚠️" if f["revisar"] else "", "Columna": str(f["columna"]),
                           "Es": f["papel"], "Por qué": f["motivo"], "Ejemplos": f["ejemplos"]}
                          for f in filas])
    # El editor guarda sus ediciones por POSICIÓN de fila, y al aplicar las
    # filas se reordenan: con la misma clave, la edición vieja quedaba
    # apuntando a otra columna. Cada aplicar/volver estrena editor.
    version = item.get("version_columnas", 0)
    editada = st.data_editor(
        tabla, hide_index=True, width="stretch", key=f"editor_columnas_{hoja}_{version}",
        disabled=["Revisar", "Columna", "Por qué", "Ejemplos"],
        column_config={
            "Revisar": st.column_config.TextColumn("", width="small"),
            "Es": st.column_config.SelectboxColumn("Es", options=PAPELES, required=True,
                                                   help="Qué representa la columna para el análisis."),
        },
    )
    nombres = {str(f["columna"]): f["columna"] for f in filas}
    antes = dict(zip(tabla["Columna"], tabla["Es"]))
    cambios = {nombres[c]: p for c, p in zip(editada["Columna"], editada["Es"]) if p != antes.get(c)}

    a, b = st.columns([1, 1])
    if a.button(f"Aplicar {len(cambios)} cambio(s)" if cambios else "Aplicar cambios", type="primary",
                disabled=not cambios, key=f"aplicar_columnas_{hoja}", width="stretch"):
        try:
            nuevo_df, nuevo_schema = aplicar_papeles(df, schema, cambios)
        except ValueError as e:
            st.error(str(e))
            return
        # Se guarda una sola vez cómo estaba al cargar, para poder volver.
        item.setdefault("antes_de_corregir", (df, schema, item["profile"].get("quality")))
        item["processed"] = nuevo_df
        item["profile"] = {**item["profile"], "schema": nuevo_schema, "quality": assess(nuevo_df, nuevo_schema)}
        item["version_columnas"] = version + 1
        st.rerun()
    if "antes_de_corregir" in item and b.button("Volver a como lo leí al principio",
                                                 key=f"restablecer_columnas_{hoja}", width="stretch"):
        df0, schema0, calidad0 = item.pop("antes_de_corregir")
        item["processed"] = df0
        item["profile"] = {**item["profile"], "schema": schema0, "quality": calidad0}
        item["version_columnas"] = version + 1
        st.rerun()
    st.caption("Las correcciones valen mientras este archivo siga abierto.")
