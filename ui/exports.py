import io, re
import pandas as pd
import streamlit as st
from core.dashboard_engine import build_dashboard
from ui.report_html import build_html_report, build_workbook_html_report


def _insight_text(item):
    """Obtiene el texto de un hallazgo sin asumir una única estructura."""
    if not isinstance(item, dict):
        return str(item) if item is not None else ""
    value = item.get("finding") or item.get("text") or item.get("message") or item.get("description") or item.get("title") or ""
    return re.sub(r"<[^>]+>", "", str(value))


def _insight_confidence(item):
    if not isinstance(item, dict):
        return "Media"
    return item.get("confidence") or item.get("confidence_label") or "Media"


def render_exports(df, dashboard, filename, sheet, full_df=None, schema=None, workbook=None):
    st.subheader("Centro de exportación")
    st.caption("Descarga los datos o genera un informe visual listo para compartir con dirección.")

    # Datos: mantienen el comportamiento anterior.
    csv=df.to_csv(index=False).encode("utf-8-sig")
    x=io.BytesIO()
    with pd.ExcelWriter(x,engine="openpyxl") as writer:
        df.to_excel(writer,index=False,sheet_name="Datos")
        if not dashboard["statistics"].empty:
            dashboard["statistics"].to_excel(writer,index=False,sheet_name="Estadistica")
        if dashboard["insights"]:
            pd.DataFrame([{
                "Hallazgo": _insight_text(i),
                "Confianza": _insight_confidence(i),
                "Tipo": i.get("kind", "info") if isinstance(i, dict) else "info",
                "Acción sugerida": (i.get("action", "") if isinstance(i, dict) else ""),
            } for i in dashboard["insights"]]).to_excel(writer,index=False,sheet_name="Insights")

    report=f"""EXCEL INTELLIGENCE — RESUMEN EJECUTIVO
Archivo: {filename}
Hoja: {sheet}
Registros analizados: {len(df):,}

{dashboard["summary"]}

HALLAZGOS
""" + "\n".join(f"- {_insight_text(i)}" for i in dashboard["insights"])

    a,b,c=st.columns(3)
    a.download_button("⬇ CSV",csv,"datos_filtrados.csv","text/csv",use_container_width=True)
    b.download_button("⬇ Excel",x.getvalue(),"reporte_excel_intelligence.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",use_container_width=True)
    c.download_button("⬇ Resumen ejecutivo",report.encode("utf-8"),"resumen_ejecutivo.txt","text/plain",use_container_width=True)

    # ─────────────────────────────────────────────────────────────────────
    # Informes HTML autocontenidos y compartibles.
    st.markdown("### 🌐 Informes HTML para compartir")
    st.caption(
        "Puedes sacar dos niveles de informe: uno general de todo el Excel o uno mucho más corto "
        "centrado en una sola hoja. Ambos ignoran los filtros del dashboard."
    )

    # Informe individual por hoja: permite sacar un reporte mucho más corto y
    # enfocado cuando el informe general del libro resulta demasiado extenso.
    sheet_reports = {}
    if workbook is not None:
        for sheet_name, item in (workbook.get("sheets", {}) or {}).items():
            if not isinstance(item, dict):
                continue
            frame = item.get("processed")
            profile = item.get("profile") or {}
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                continue
            sheet_reports[sheet_name] = (frame, profile)

    # Mantiene el nombre de la hoja que el usuario está viendo como selección inicial.
    available_sheets = list(sheet_reports.keys())
    default_index = available_sheets.index(sheet) if sheet in available_sheets else 0
    selected_report_sheet = None
    html_hoja = None
    if available_sheets:
        st.markdown("#### 📄 Informe individual por hoja")
        st.caption(
            "Si el informe general te parece demasiado largo, selecciona una sola hoja y descarga "
            "un HTML dedicado únicamente a esa parte del Excel. No depende de los filtros actuales."
        )
        selected_report_sheet = st.selectbox(
            "Selecciona la hoja que quieres convertir en informe",
            available_sheets,
            index=default_index,
            key="export_html_sheet_selector_v59",
        )
        selected_df, selected_profile = sheet_reports[selected_report_sheet]
        selected_schema = selected_profile.get("schema", {}) if isinstance(selected_profile, dict) else {}
        try:
            selected_dashboard = build_dashboard(selected_df, selected_profile)
            html_hoja = build_html_report(
                selected_df,
                selected_schema,
                selected_dashboard,
                filename,
                selected_report_sheet,
                "Hoja completa (sin filtros)",
            )
        except Exception as exc:
            st.error(f"No se pudo preparar el informe de la hoja seleccionada: {exc}")

    # Informe realmente general: recorre todas las hojas disponibles del libro.
    html_libro = None
    if workbook is not None:
        try:
            html_libro = build_workbook_html_report(workbook)
        except Exception as exc:
            st.error(f"No se pudo preparar el informe general del Excel: {exc}")
    elif html_hoja:
        # Compatibilidad con llamadas antiguas sin workbook.
        html_libro = html_hoja

    st.markdown("#### 📊 Informe general · todo el Excel")
    st.caption(
        "Una visión transversal del libro completo, con resumen ejecutivo y detalle adaptativo por hoja."
    )

    a, b = st.columns([1.35, 1])
    with a:
        if html_libro:
            st.download_button(
                "📊 Exportar informe general · TODO el Excel",
                html_libro.encode("utf-8"),
                "informe_general_todo_el_excel.html",
                "text/html",
                use_container_width=True,
                type="primary",
                help="Ignora filtros y analiza todas las hojas con datos del libro cargado.",
            )
    with b:
        if html_hoja and selected_report_sheet:
            safe_sheet = re.sub(r"[^A-Za-z0-9_-]+", "_", str(selected_report_sheet)).strip("_") or "hoja"
            st.download_button(
                f"📄 Exportar informe · {selected_report_sheet}",
                html_hoja.encode("utf-8"),
                f"informe_{safe_sheet}.html",
                "text/html",
                use_container_width=True,
                help="Genera un informe independiente únicamente de la hoja seleccionada, sin filtros.",
            )

    st.info(
        "💡 El informe general no es una captura del dashboard. Es un reporte independiente "
        "del Excel completo: al abrir el HTML en Chrome o Edge puedes recorrer el resumen, "
        "los hallazgos y los gráficos de cada hoja sin ejecutar Streamlit."
    )

