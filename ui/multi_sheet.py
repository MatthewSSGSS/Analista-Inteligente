"""Herramientas para trabajar con VARIAS hojas del mismo Excel a la vez —
sin tener que cambiar "Hoja activa" en el sidebar una por una:

- Buscar algo (un cliente, un producto, un ID) en todas las hojas.
- Combinar hojas parecidas en una nueva hoja que funciona con TODAS las
  herramientas ya existentes (KPIs, gráficos, filtros).
- Comparar 2 hojas directamente (qué cambió entre una y otra).

No todas las hojas de un Excel son necesariamente comparables entre sí —
algunas pueden traer información extra sin relación con las demás. Por eso
`recommend_multi_sheet_tool()` explica su recomendación en vez de forzar
una sola herramienta: la persona sigue eligiendo.
"""
from __future__ import annotations

import streamlit as st

from core.comparison_engine import (
    recommend_multi_sheet_tool,
    prepare_sheet_comparison,
    build_comparison,
    combined_records_table,
)
from core.filter_engine import search_across_sheets
from core.profile import profile_sheet
from ui.components.section import section_header, decision_strip, banner_header
from ui.comparison import render_comparison

_TOOLS = [
    ("buscar", "🔎 Buscar en todas"),
    ("combinar", "🔗 Combinar hojas"),
    ("comparar", "⚖️ Comparar 2 hojas"),
]


def render_multi_sheet(workbook: dict) -> None:
    rec = recommend_multi_sheet_tool(workbook)
    names = rec["sheet_names"]
    st.markdown(
        banner_header("Varias hojas", "Busca, combina o compara información repartida en distintas hojas del mismo Excel.", "ciudad_red.jpg"),
        unsafe_allow_html=True,
    )
    if len(names) < 2:
        st.info("Necesitas al menos 2 hojas con datos utilizables para usar estas herramientas.")
        return

    labels = {key: label for key, label in _TOOLS}
    st.markdown(
        decision_strip(f"<b>Recomendado: {labels[rec['tool']]}.</b> {rec['reason']}", dot=True),
        unsafe_allow_html=True,
    )
    default_index = [k for k, _ in _TOOLS].index(rec["tool"])
    choice_label = st.radio(
        "Herramienta", [label for _, label in _TOOLS], horizontal=True,
        label_visibility="collapsed", index=default_index, key="multi_sheet_tool",
    )
    choice = {label: key for key, label in _TOOLS}[choice_label]

    if choice == "buscar":
        _render_search(workbook, names)
    elif choice == "combinar":
        _render_combine(workbook, names)
    else:
        _render_compare(workbook, names)


def _render_search(workbook: dict, names: list[str]) -> None:
    st.markdown(section_header("Buscar en todas las hojas", compact=True), unsafe_allow_html=True)
    query = st.text_input(
        "Buscar", placeholder="Ej.: nombre de cliente, producto, ID...",
        label_visibility="collapsed", key="multi_sheet_search_query",
    )
    if not query:
        st.caption(f"Escribe algo para buscarlo en las {len(names)} hojas a la vez.")
        return
    results = search_across_sheets(workbook, query)
    if not results:
        st.info(f"«{query}» no aparece en ninguna de las {len(names)} hojas con datos.")
        return
    total = sum(len(df) for df in results.values())
    st.caption(f"{total:,} fila(s) coinciden, repartidas en {len(results)} de {len(names)} hoja(s).")
    for name, matches in results.items():
        with st.expander(f"📄 {name} · {len(matches):,} coincidencia(s)", expanded=len(results) == 1):
            st.dataframe(matches, use_container_width=True, hide_index=True)


def _render_combine(workbook: dict, names: list[str]) -> None:
    st.markdown(section_header("Combinar hojas en una sola vista", compact=True), unsafe_allow_html=True)
    st.caption(
        "Apila las hojas elegidas en una hoja nueva y la analiza desde cero — queda disponible "
        "en \"Hoja activa\" (barra lateral), con sus propios KPIs, gráficos y filtros, igual que "
        "cualquier otra hoja. Las columnas que se reconocen como equivalentes entre hojas (misma "
        "fecha, categoría o métrica, aunque el nombre varíe) quedan unificadas; el resto conserva "
        "su nombre original."
    )
    selected = st.multiselect("Hojas a combinar", names, default=names, key="multi_sheet_combine_pick")
    if len(selected) < 2:
        st.info("Elige al menos 2 hojas para combinar.")
        return
    if st.button("🔗 Combinar estas hojas", type="primary", key="multi_sheet_combine_btn"):
        new_name = _combine_sheets(workbook, selected)
        st.session_state["_multi_sheet_combined_name"] = new_name
        st.rerun()

    combined_flag = st.session_state.pop("_multi_sheet_combined_name", None)
    if combined_flag:
        st.success(
            f"Listo — se creó la hoja **'{combined_flag}'**. Selecciónala en \"Hoja activa\" "
            f"(barra lateral) para verla con KPIs, gráficos y filtros, igual que cualquier otra hoja."
        )


def _combine_sheets(workbook: dict, sheet_names: list[str]) -> str:
    """Combina las hojas elegidas en una nueva hoja DENTRO del mismo
    workbook (no un archivo aparte), reutilizando `profile_sheet()` — el
    mismo perfilado que corre al cargar cualquier Excel — para que la hoja
    combinada tenga su propio schema/calidad válidos y funcione con todas
    las herramientas existentes sin código de análisis nuevo.
    """
    # combined_records_table() necesita también "label" por archivo (lo usa
    # para la columna "Periodo" del resultado) — se usa el nombre de la
    # hoja tal cual, igual que ya hace prepare_sheet_comparison() más abajo.
    files = [
        {"filename": n, "df": workbook["sheets"][n]["processed"], "schema": workbook["sheets"][n]["profile"]["schema"], "label": n}
        for n in sheet_names
    ]
    combined_df = combined_records_table(files, max_rows=20000)
    new_name = "🔗 Combinado: " + " + ".join(sheet_names)
    workbook["sheets"][new_name] = profile_sheet(combined_df)
    return new_name


def _render_compare(workbook: dict, names: list[str]) -> None:
    st.markdown(section_header("Comparar 2 hojas", compact=True), unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        sheet_a = st.selectbox("Hoja A", names, key="multi_sheet_compare_a")
    with c2:
        candidates_b = [n for n in names if n != sheet_a]
        sheet_b = st.selectbox("Hoja B", candidates_b or names, key="multi_sheet_compare_b")
    if st.button("⚖️ Comparar estas 2 hojas", type="primary", key="multi_sheet_compare_btn"):
        prepared = prepare_sheet_comparison(workbook, [sheet_a, sheet_b])
        if len(prepared["files"]) < 2:
            st.error("No se pudo preparar la comparación con esas 2 hojas.")
        else:
            st.session_state["_multi_sheet_comparison_result"] = build_comparison(prepared)

    result = st.session_state.get("_multi_sheet_comparison_result")
    if result:
        # show_filter_panel=False y un key_prefix propio: esta comparación
        # NO debe leer/escribir las claves de sesión de "Comparar archivos"
        # (sidebar) ni chocar con sus widgets si ambas vistas están activas
        # a la vez — ver el docstring de render_comparison() para el detalle.
        render_comparison(result, show_filter_panel=False, key_prefix="cmp_sheet")
