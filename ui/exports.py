import html as _html
import re
import pandas as pd
import streamlit as st
from core.dashboard_engine import build_dashboard
from ui.components.section import section_header
from ui.report_excel import build_excel_report, nombre_archivo as nombre_archivo_excel
from ui.report_html import build_html_report, build_workbook_html_report
from ui.interactive_report import build_interactive_html_report


def _active_filters_summary(schema=None):
    """Texto legible de los filtros realmente activos en este momento, para
    que el informe deje constancia exacta de qué recorte de datos muestra.
    Usa la misma descripción que el menú lateral, así que entiende también
    los rangos numéricos, los de fechas y el texto contenido."""
    from core.filter_engine import describir_regla

    filters = st.session_state.get("filters") or {}
    partes = [describir_regla(col, regla) for col, regla in filters.items() if not str(col).startswith("__")]
    partes = [p for p in partes if p]
    return " · ".join(partes) if partes else "Sin filtros aplicados (vista completa)"


# Solo agrega clases sobre los tokens del tema (ui/styles/theme.py); no
# redefine colores. Las tarjetas son contenedores con `key`, que Streamlit
# expone como la clase `.st-key-<key>`.
_CSS = """
<style>
.st-key-exp_destacado,.st-key-exp_libro,.st-key-exp_hoja,.st-key-exp_interactivo,.st-key-exp_datos{
  background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-lg);
  padding:18px 20px;box-shadow:var(--shadow-sm);gap:.6rem}
.st-key-exp_destacado{border-left:5px solid var(--blue);
  background:linear-gradient(120deg,var(--blue-soft) 0%,var(--panel) 55%);padding:22px 24px}
.exp-eyebrow{font-size:10.5px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--blue)}
.exp-head{display:flex;gap:12px;align-items:flex-start}
.exp-icon{font-size:22px;line-height:1;width:40px;height:40px;flex:0 0 40px;display:flex;align-items:center;
  justify-content:center;border-radius:12px;background:var(--panel-2);border:1px solid var(--line-soft)}
.exp-title{font-size:16px;font-weight:800;color:var(--text);line-height:1.25}
.st-key-exp_destacado .exp-title{font-size:21px;margin-top:4px}
.exp-desc{font-size:13px;color:var(--muted);line-height:1.5;margin-top:3px}
.st-key-exp_libro .exp-desc,.st-key-exp_hoja .exp-desc,.st-key-exp_interactivo .exp-desc{min-height:40px}
.exp-head{margin-bottom:8px}
/* Las tres tarjetas del medio, del mismo alto y con el botón abajo. */
.st-key-exp_libro,.st-key-exp_hoja,.st-key-exp_interactivo{min-height:278px}
.st-key-exp_libro [data-testid="stElementContainer"]:has([data-testid="stDownloadButton"]),
.st-key-exp_hoja [data-testid="stElementContainer"]:has([data-testid="stSelectbox"]),
.st-key-exp_interactivo [data-testid="stElementContainer"]:has([data-testid="stDownloadButton"]){margin-top:auto}
/* El tema muestra siempre las etiquetas de los widgets; aquí el selector se explica solo. */
.st-key-exp_hoja [data-testid="stWidgetLabel"]{display:none}
.exp-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.exp-chip{font-size:11px;font-weight:600;color:var(--muted);background:var(--panel-2);
  border:1px solid var(--line-soft);border-radius:999px;padding:3px 10px;max-width:100%;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.exp-chip.on{color:var(--blue-strong);background:var(--blue-soft);border-color:transparent}
.exp-size{font-size:11.5px;color:var(--soft);text-align:center;margin-top:-2px}
.exp-subhead{font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;
  color:var(--muted);margin:14px 0 2px}
.exp-tip{font-size:12.5px;color:var(--muted);padding:10px 14px;border-radius:var(--radius-md);
  background:var(--panel-2);border:1px dashed var(--line)}
.exp-tip b{color:var(--text)}
</style>
"""


def _mb(contenido: bytes) -> str:
    return f"{len(contenido) / 1_000_000:.1f} MB"


def _cabecera(icono: str, titulo: str, descripcion: str, chips: list = (), eyebrow: str = "") -> str:
    chips_html = "".join(
        f'<span class="exp-chip{" on" if activo else ""}" title="{_html.escape(str(texto))}">{_html.escape(str(texto))}</span>'
        for texto, activo in chips
    )
    return (
        f'<div class="exp-head"><div class="exp-icon">{icono}</div><div style="min-width:0">'
        + (f'<div class="exp-eyebrow">{eyebrow}</div>' if eyebrow else "")
        + f'<div class="exp-title">{titulo}</div><div class="exp-desc">{descripcion}</div>'
        + (f'<div class="exp-chips">{chips_html}</div>' if chips_html else "")
        + "</div></div>"
    )


def render_exports(df, dashboard, filename, sheet, full_df=None, schema=None, workbook=None):
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(section_header(
        "Centro de exportación",
        subtitle="Informes listos para presentar al equipo y datos para seguir trabajando.",
    ), unsafe_allow_html=True)

    # ── Destacado: el informe con lo que se ve ahora en el panel ──────────
    filters_summary = _active_filters_summary(schema)
    has_active_filters = bool(st.session_state.get("filters"))
    try:
        html_filtrado = build_html_report(df, schema or {}, dashboard, filename, sheet, f"Filtrado · {filters_summary}")
    except Exception as exc:
        html_filtrado = None
        error_filtrado = exc
    with st.container(key="exp_destacado"):
        izquierda, derecha = st.columns([2.4, 1], vertical_alignment="center")
        with izquierda:
            st.markdown(_cabecera(
                "🎯", "Informe de lo que estás viendo",
                f"{len(df):,} registros de «{_html.escape(str(sheet))}» con tus filtros actuales. Abre con el resumen "
                "para decidir, sigue con el plan de acción y deja el detalle técnico al final.",
                [(f"Filtros: {filters_summary}", has_active_filters)],
                eyebrow="Recomendado para presentar",
            ), unsafe_allow_html=True)
        with derecha:
            if html_filtrado:
                contenido = html_filtrado.encode("utf-8")
                st.download_button(
                    "⬇ Descargar informe", contenido, "informe_filtrado.html", "text/html",
                    use_container_width=True, type="primary", key="exp_btn_filtrado",
                    help="Usa exactamente los datos que ves ahora mismo en el panel, con tus filtros aplicados.",
                )
                st.markdown(f'<div class="exp-size">HTML · {_mb(contenido)}</div>', unsafe_allow_html=True)
            else:
                st.error(f"No se pudo preparar: {error_filtrado}")

    # ── Otros informes ───────────────────────────────────────────────────
    st.markdown('<div class="exp-subhead">Otros informes</div>', unsafe_allow_html=True)

    sheet_reports = {}
    if workbook is not None:
        for sheet_name, item in (workbook.get("sheets", {}) or {}).items():
            if not isinstance(item, dict):
                continue
            frame = item.get("processed")
            profile = item.get("profile") or {}
            if isinstance(frame, pd.DataFrame) and not frame.empty:
                sheet_reports[sheet_name] = (frame, profile)
    available_sheets = list(sheet_reports.keys())

    col_libro, col_hoja, col_inter = st.columns(3)

    # Todo el Excel: recorre todas las hojas, sin filtros.
    with col_libro, st.container(key="exp_libro"):
        st.markdown(_cabecera(
            "📚", "Todo el Excel",
            "Un tablero con cómo va cada hoja y las prioridades de todo el libro.",
            [(f"{len(available_sheets) or 1} hoja(s)", False), ("Sin filtros", False)],
        ), unsafe_allow_html=True)
        html_libro = None
        if workbook is not None:
            try:
                html_libro = build_workbook_html_report(workbook)
            except Exception as exc:
                st.error(f"No se pudo preparar: {exc}")
        if html_libro:
            contenido = html_libro.encode("utf-8")
            st.download_button(
                "⬇ Descargar", contenido, "informe_general_todo_el_excel.html", "text/html",
                use_container_width=True, key="exp_btn_libro",
                help="Ignora filtros y analiza todas las hojas con datos del libro cargado.",
            )
            st.markdown(f'<div class="exp-size">HTML · {_mb(contenido)}</div>', unsafe_allow_html=True)

    # Una sola hoja: más corto y enfocado que el del libro completo.
    with col_hoja, st.container(key="exp_hoja"):
        st.markdown(_cabecera(
            "📄", "Una hoja",
            "Informe dedicado a una sola hoja, más corto que el del libro completo.",
            [("Sin filtros", False)],
        ), unsafe_allow_html=True)
        if available_sheets:
            default_index = available_sheets.index(sheet) if sheet in available_sheets else 0
            selected_report_sheet = st.selectbox(
                "Hoja", available_sheets, index=default_index,
                key="export_html_sheet_selector_v59", label_visibility="collapsed",
            )
            selected_df, selected_profile = sheet_reports[selected_report_sheet]
            selected_schema = selected_profile.get("schema", {}) if isinstance(selected_profile, dict) else {}
            try:
                html_hoja = build_html_report(
                    selected_df, selected_schema, build_dashboard(selected_df, selected_profile),
                    filename, selected_report_sheet, "Hoja completa (sin filtros)",
                )
                contenido = html_hoja.encode("utf-8")
                safe_sheet = re.sub(r"[^A-Za-z0-9_-]+", "_", str(selected_report_sheet)).strip("_") or "hoja"
                st.download_button(
                    "⬇ Descargar", contenido, f"informe_{safe_sheet}.html", "text/html",
                    use_container_width=True, key="exp_btn_hoja",
                    help="Genera un informe independiente únicamente de la hoja seleccionada, sin filtros.",
                )
                st.markdown(f'<div class="exp-size">HTML · {_mb(contenido)}</div>', unsafe_allow_html=True)
            except Exception as exc:
                st.error(f"No se pudo preparar: {exc}")
        else:
            st.caption("No hay hojas con datos para este informe.")

    # Interactivo: lleva los datos adentro y los filtros funcionan en el archivo.
    with col_inter, st.container(key="exp_interactivo"):
        st.markdown(_cabecera(
            "🧭", "Interactivo",
            "Quien lo abra filtra ahí mismo, sin la app ni internet: KPIs, gráficos y rankings se recalculan.",
            [("Hasta 20.000 filas", False)],
        ), unsafe_allow_html=True)
        try:
            html_interactivo = build_interactive_html_report(full_df if full_df is not None else df, schema or {}, filename, sheet)
            contenido = html_interactivo.encode("utf-8")
            st.download_button(
                "⬇ Descargar", contenido, "informe_interactivo.html", "text/html",
                use_container_width=True, key="exp_btn_interactivo",
                help="Incluye todos los datos de la hoja (hasta 20,000 filas) para que los filtros funcionen sin la app.",
            )
            st.markdown(f'<div class="exp-size">HTML · {_mb(contenido)} · pesa más porque lleva los datos</div>',
                        unsafe_allow_html=True)
        except Exception as exc:
            st.error(f"No se pudo preparar: {exc}")

    # ── Excel ejecutivo y CSV, con lo que se ve ahora ────────────────────
    # El Excel se arma al hacer clic (data=callable): con gráficos, planes y
    # tablas dinámicas es más pesado que un volcado, y armarlo en cada rerun
    # de la vista la haría lenta aunque nadie lo descargue.
    st.markdown('<div class="exp-subhead">Excel y datos</div>', unsafe_allow_html=True)
    with st.container(key="exp_datos"):
        izquierda, derecha = st.columns([2.4, 1], vertical_alignment="center")
        with izquierda:
            st.markdown(_cabecera(
                "📊", "Excel ejecutivo",
                f"Los {len(df):,} registros que ves ahora, en un libro listo para enviar: portada con indicadores y "
                "gráficos, plan de acción, evolución mes a mes, cómo va cada uno, matrices con mapa de calor y "
                "tablas dinámicas de Excel sobre los datos.",
                [("Gráficos", False), ("Tablas dinámicas", False), ("Plan de acción", False),
                 (f"Filtros: {filters_summary}", has_active_filters)],
            ), unsafe_allow_html=True)
        with derecha:
            st.download_button(
                "⬇ Descargar Excel",
                lambda: build_excel_report(df, schema or {}, dashboard, filename, sheet, filters_summary),
                nombre_archivo_excel(sheet), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True, type="primary", key="exp_btn_xlsx",
                help="Se arma al hacer clic, con tus filtros actuales. Las tablas dinámicas se actualizan al abrirlo.",
            )
            st.download_button(
                "CSV (solo datos)", lambda: df.to_csv(index=False).encode("utf-8-sig"), "datos_filtrados.csv",
                "text/csv", use_container_width=True, key="exp_btn_csv",
                help="Los datos planos, para cruzar con otras fuentes o cargarlos en otro sistema.",
            )

    st.markdown(
        '<div class="exp-tip">💡 Los informes se abren en Chrome o Edge sin internet. Dentro del archivo, '
        '<b>▶ Presentar</b> lo muestra sección por sección a pantalla completa (flechas para avanzar) y '
        '<b>Ctrl + P</b> lo guarda en PDF con todo desplegado.</div>',
        unsafe_allow_html=True,
    )
