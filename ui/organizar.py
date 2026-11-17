"""«🧹 Ordenar y corregir»: dejar el archivo en orden antes de analizarlo.

Qué se revisa y con qué criterio vive en core/organizar.py; aquí solo se
muestra cada propuesta con su motivo y se aplica lo que la persona aprueba.
Como «🔎 Columnas», la corrección se guarda en la propia hoja del libro
cargado (item): sobrevive a cambiar de vista y la usan todas. Las dos vistas
comparten «Volver a como lo leí al principio» (item["antes_de_corregir"]).
"""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from core.organizar import a_excel, aplicar, revisar, volver_a_leer
from ui.components.descarga import preparar_y_descargar
from ui.components.escena import cabecera

_MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _revision(item: dict) -> dict:
    """La revisión de la hoja, calculada una vez por versión de los datos."""
    guardada = item.get("_revision_organizar")
    if guardada and guardada[0] is item["processed"]:
        return guardada[1]
    resultado = revisar(item["processed"], item["profile"]["schema"])
    item["_revision_organizar"] = (item["processed"], resultado)
    return resultado


def _titulo(numero: int, texto: str, cuantos: int | None = None) -> None:
    extra = f" · {cuantos}" if cuantos else ""
    st.markdown(f"#### {numero} · {texto}{extra}")


def render_organizar(item: dict, hoja: str, nombre_archivo: str) -> None:
    df, schema = item["processed"], item["profile"]["schema"]
    rev = _revision(item)
    version = item.get("version_columnas", 0)
    k = f"{hoja}_{version}"   # cada aplicar estrena widgets (ver ui/columnas.py)

    sugeridos = [n for n in rev["nombres"] if n["sugerido"]]
    cabecera("Ordenar y corregir el archivo",
             "Reviso nombres de columnas, fechas que no se leían, palabras mal escritas, filas repetidas "
             "y el orden. Nada cambia hasta que lo apruebes.",
             ceja="Ordenar", icono="🧹",
             cifras=[(str(len(sugeridos)), "nombres"), (str(len(rev["fechas"])), "fechas"),
                     (str(len(rev["errores"])), "palabras"), (str(rev["repetidas"]), "filas repetidas")],
             clave="cab_organizar", respaldo_html="<h3>🧹 Ordenar y corregir el archivo</h3>")

    hecho = item.pop("_organizar_hecho", None)
    if hecho:
        st.success("Listo. " + " ".join(hecho) + " Todo el panel ya usa el archivo corregido.")

    hay_algo = sugeridos or rev["fechas"] or rev["errores"] or rev["repetidas"] or rev["orden"]["cambia"]
    if not hay_algo:
        st.success("No encontré nada que corregir: nombres, fechas y valores se leen bien.")

    # ── 1. Nombres de columna ─────────────────────────────────────────────
    _titulo(1, "Nombres de columnas", len(sugeridos) or None)
    st.caption("El nombre es lo primero que mira el panel: «Fceha» o «Unnamed: 3» no se reconocen. "
               "Puedes cambiar cualquier nombre, no solo los sugeridos.")
    filas = sorted(rev["nombres"], key=lambda f: not f["sugerido"])
    tabla_nombres = pd.DataFrame([{"Revisar": "⚠️" if f["sugerido"] else "", "Columna": str(f["columna"]),
                                   "Nombre nuevo": str(f["nuevo"]), "Por qué": f["motivo"],
                                   "Ejemplos": f["ejemplos"]} for f in filas])
    originales = {str(f["columna"]): f["columna"] for f in filas}
    editada = st.data_editor(
        tabla_nombres, hide_index=True, width="stretch", key=f"org_nombres_{k}",
        disabled=["Revisar", "Columna", "Por qué", "Ejemplos"],
        column_config={"Revisar": st.column_config.TextColumn("", width="small"),
                       "Nombre nuevo": st.column_config.TextColumn("Nombre nuevo", required=True)},
    ) if len(tabla_nombres) else tabla_nombres
    nombres = {originales[c]: str(n).strip() for c, n in zip(editada["Columna"], editada["Nombre nuevo"])
               if str(n).strip() and str(n).strip() != c} if len(editada) else {}

    # ── 2. Fechas ─────────────────────────────────────────────────────────
    fechas_elegidas = []
    if rev["fechas"]:
        _titulo(2, "Fechas que no estaba leyendo", len(rev["fechas"]))
        st.caption("Sin una fecha el panel no muestra tendencias, comparaciones ni proyección.")
        tabla_fechas = pd.DataFrame([{"Leer como fecha": True, "Columna": str(f["columna"]),
                                      "Por qué": f["motivo"], "Ejemplos": f["ejemplos"]} for f in rev["fechas"]])
        ed = st.data_editor(tabla_fechas, hide_index=True, width="stretch", key=f"org_fechas_{k}",
                            disabled=["Columna", "Por qué", "Ejemplos"])
        de_fecha = {str(f["columna"]): f["columna"] for f in rev["fechas"]}
        fechas_elegidas = [de_fecha[c] for c, si in zip(ed["Columna"], ed["Leer como fecha"]) if si]
    elif not schema.get("dates") and "__periodo_analisis__" not in df.columns:
        _titulo(2, "Fechas")
        st.info("No encontré ninguna columna con fechas. Si alguna lo es, cámbiale el nombre arriba a «Fecha» "
                "(o márcala como «Fecha» en «🔎 Columnas»).")

    # ── 3. Palabras mal escritas ──────────────────────────────────────────
    valores: dict = {}
    if rev["errores"]:
        _titulo(3, "Palabras mal escritas", len(rev["errores"]))
        st.caption("Cada variante rara se cuenta como otro municipio, cliente o vendedor y parte las cifras. "
                   "Las marcadas son casos claros; revisa las demás. Puedes cambiar a qué se corrige.")
        tabla_err = pd.DataFrame([{"Corregir": e["marcado"], "Columna": str(e["columna"]),
                                   "Escrito así": e["valor"], "Filas": e["filas"], "Pasa a ser": e["corregir_a"],
                                   "Por qué": e["motivo"]} for e in rev["errores"]])
        ed = st.data_editor(tabla_err, hide_index=True, width="stretch", key=f"org_errores_{k}",
                            disabled=["Columna", "Escrito así", "Filas", "Por qué"],
                            column_config={"Filas": st.column_config.NumberColumn("Filas", format="%d")})
        de_columna = {str(e["columna"]): e["columna"] for e in rev["errores"]}
        for _, f in ed.iterrows():
            destino = str(f["Pasa a ser"]).strip()
            if f["Corregir"] and destino and destino != f["Escrito así"]:
                valores.setdefault(de_columna[f["Columna"]], {})[f["Escrito así"]] = destino

    # ── 4. Filas repetidas ────────────────────────────────────────────────
    quitar = False
    if rev["repetidas"]:
        _titulo(4, "Filas repetidas", rev["repetidas"])
        quitar = st.checkbox(
            f"Quitar las {rev['repetidas']:,} filas que son copia exacta de otra", value=False,
            key=f"org_repetidas_{k}",
            help="Exactamente iguales en todas las columnas. A veces son reales (dos ventas iguales el mismo "
                 "día); si el archivo no tiene una columna que las distinga, revisa antes de quitarlas.")

    # ── 5. Orden ──────────────────────────────────────────────────────────
    ordenar = False
    if rev["orden"]["cambia"]:
        _titulo(5, "Orden")
        por = rev["orden"]["filas"]
        detalle = f"filas por «{por[0]}»" + (f" y «{por[1]}»" if len(por) > 1 else "") if por else ""
        ordenar = st.checkbox(
            "Ordenar columnas (fechas, luego datos, al final cifras)" + (f" y {detalle}" if detalle else ""),
            value=True, key=f"org_orden_{k}")

    # ── Aplicar ───────────────────────────────────────────────────────────
    n = len(nombres) + len(fechas_elegidas) + sum(len(v) for v in valores.values()) + int(quitar) + int(ordenar)
    st.divider()
    a, b = st.columns([1, 1])
    if a.button(f"🧹 Aplicar {n} cambio(s)" if n else "🧹 Aplicar cambios", type="primary", disabled=not n,
                key=f"org_aplicar_{hoja}", width="stretch"):
        with st.spinner("Corrigiendo y volviendo a leer el archivo…"):
            try:
                tabla, hecho = aplicar(df, schema, nombres=nombres, fechas=fechas_elegidas, valores=valores,
                                       quitar_repetidas=quitar, ordenar=ordenar)
                nuevo = volver_a_leer(tabla, item, {"sheet_name": hoja, "workbook_name": nombre_archivo},
                                      nombres, hecho)
            except ValueError as e:
                st.error(str(e))
                return
        # Se guarda una sola vez cómo estaba al cargar, para poder volver.
        item.setdefault("antes_de_corregir", (df, schema, item["profile"].get("quality")))
        item["processed"] = nuevo["processed"]
        log_viejo = list(item["profile"].get("cleaning_log") or [])
        item["profile"] = {**item["profile"], **nuevo["profile"],
                           "cleaning_log": log_viejo + [l for l in nuevo["profile"].get("cleaning_log", [])
                                                        if l not in log_viejo]}
        item["version_columnas"] = version + 1
        item["_organizar_hecho"] = hecho
        # Los filtros apuntaban a nombres y valores que ya no existen.
        st.session_state.filters = {}
        st.rerun()
    if "antes_de_corregir" in item and b.button("Volver a como lo leí al principio",
                                                 key=f"org_restablecer_{hoja}", width="stretch"):
        df0, schema0, calidad0 = item.pop("antes_de_corregir")
        item["processed"] = df0
        item["profile"] = {**item["profile"], "schema": schema0, "quality": calidad0}
        item["version_columnas"] = version + 1
        st.session_state.filters = {}
        st.rerun()
    st.caption("Las correcciones valen mientras este archivo siga abierto. Para conservarlas, descarga el "
               "archivo corregido.")

    # ── Descargar ─────────────────────────────────────────────────────────
    st.markdown("#### ⬇️ El archivo ordenado")
    base = re.sub(r"\.[^.]+$", "", str(nombre_archivo)) or "archivo"
    actual = item["processed"]
    preparar_y_descargar(
        f"org_descarga_{hoja}", (id(actual), len(actual), tuple(map(str, actual.columns))),
        lambda: a_excel(actual, hoja), f"{base}_ordenado.xlsx", _MIME_XLSX,
        preparar="📦 Preparar Excel", descargar="⬇️ Descargar Excel ordenado",
        ayuda="La hoja tal como la está usando el panel: con las correcciones aplicadas y sin filtros.",
        nota=f"{len(actual):,} filas · {len([c for c in actual.columns if not str(c).startswith('_')])} columnas")
