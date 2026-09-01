import streamlit as st
import pandas as pd
from datetime import datetime
from core.loader import load_workbook
from core.dashboard_engine import build_dashboard


@st.cache_data(show_spinner=False, max_entries=12, ttl=1800)
def _cached_build_dashboard(df, profile):
    # build_dashboard es lo más pesado de la app (KPIs, hallazgos, anomalías,
    # estadísticas). Streamlit vuelve a ejecutar TODO el script en cada clic
    # (cambiar de sección, aplicar un filtro), así que sin este caché se
    # recalculaba desde cero cada vez, aunque los datos visibles no hubieran
    # cambiado. Streamlit reconoce cuándo df/profile son iguales a una
    # llamada anterior y reutiliza el resultado en vez de recalcular.
    return build_dashboard(df, profile)


from core.dataset_mode import detect_dataset_mode
from core.filter_engine import apply_filters, natural_filter, cascading_options
from ui.theme import inject_theme
from ui.dashboard import render_dashboard
from ui.explorer import render_explorer
from ui.quality import render_quality
from ui.georeferencing import render_georeferencing
from core.geo_engine import supports_georeferencing
from ui.anomalies import render_anomalies
from ui.data_table import render_data_table
from ui.exports import render_exports
from ui.catalog import render_catalog
from ui.assistant import render_assistant
from core.comparison_engine import prepare_comparison, build_comparison
from ui.comparison import render_comparison
from ui.person_profile import render_person_profile
from ui.person_compare import render_person_compare
from ui.executive import render_executive
from ui.alerts import render_alerts
from ui.home import render_home
from ui.landing import render_landing
from ui.login import render_login
import core.auth_engine as auth_engine
from ui.mode_choice import render_mode_choice
from ui.practical import render_practical_page
from ui.tracking import render_tracking
from core.tracking_engine import ingest_file, sources_to_long, merge_long, read_consolidated
import core.db_engine as db_engine

# Íconos de la navegación por secciones — mismo orden que la Propuesta UX
# (Resumen · Explorar · Datos · Alertas · Personas · Mapa · Informes).
SECTION_ICONS = {
    "Resumen": "📈", "Explorar": "🔍", "Datos": "🗂️", "Alertas": "🚨",
    "Personas": "👤", "Mapa": "🗺️", "Informes": "📤",
}

if "app_started" not in st.session_state:
    st.session_state.app_started = False
if "active_section" not in st.session_state:
    st.session_state.active_section = "Resumen"

st.set_page_config(
    page_title="Panel Analítico Universal", page_icon="📊", layout="wide",
    initial_sidebar_state="collapsed" if not st.session_state.app_started else "auto",
)

inject_theme()

if "authenticated" not in st.session_state: st.session_state.authenticated=False
if "auth_user" not in st.session_state: st.session_state.auth_user=None

# El login solo se activa si hay base de datos configurada (ahí es donde se
# guardan los usuarios de forma persistente). Sin eso, no hay dónde guardar
# cuentas entre sesiones, así que la app sigue funcionando sin login, igual
# que antes.
if auth_engine.is_available() and not st.session_state.authenticated:
    render_login()
    st.stop()

if "workbook" not in st.session_state: st.session_state.workbook=None
if "filters" not in st.session_state: st.session_state.filters={}
if "comparison_result" not in st.session_state: st.session_state.comparison_result=None
if "comparison_error" not in st.session_state: st.session_state.comparison_error=None
if "comparison_raw_files" not in st.session_state: st.session_state.comparison_raw_files=None
if "comparison_filters" not in st.session_state: st.session_state.comparison_filters={}
if "tracking_data" not in st.session_state: st.session_state.tracking_data=None
if "practico_workbook" not in st.session_state: st.session_state.practico_workbook=None
if "practico_chat" not in st.session_state: st.session_state.practico_chat=[]
if "tracking_error" not in st.session_state: st.session_state.tracking_error=None

# Si hay una base de datos compartida configurada (ver core/db_engine.py),
# cualquiera que abra la app ve automáticamente el historial más reciente
# que haya guardado cualquier otra persona del equipo — sin subir nada.
if db_engine.is_configured() and st.session_state.tracking_data is None:
    try:
        loaded = db_engine.load_from_db()
        if not loaded.empty:
            st.session_state.tracking_data = loaded
    except Exception as e:
        st.session_state.tracking_error = f"No se pudo conectar a la base de datos compartida: {e}"
if "focus_dimension" not in st.session_state: st.session_state.focus_dimension=None
if "focus_metric" not in st.session_state: st.session_state.focus_metric=None
if "focus_view" not in st.session_state: st.session_state.focus_view=None

if not st.session_state.app_started:
    started = render_landing()
    if started:
        st.session_state.app_started = True
        st.rerun()
    st.stop()

if "analysis_mode" not in st.session_state:
    st.session_state.analysis_mode = None

if st.session_state.analysis_mode is None:
    choice = render_mode_choice()
    if choice:
        st.session_state.analysis_mode = choice
        st.rerun()
    st.stop()

if st.session_state.analysis_mode == "practico":
    render_practical_page()
    st.stop()

st.markdown('<div class="hero"><h1>📊 Panel Analítico Universal</h1><p>De Excel crudo a decisiones: qué pasó, dónde pasó, qué lo explica y qué conviene revisar.</p></div>',unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────
# Sidebar = rail de navegación oscuro y angosto (marca, cuenta, secciones).
# Todo lo que no es "chrome" del producto (subir archivo, comparar/seguimiento)
# vive colapsado debajo, para que el rail visible coincida con el diseño.
# La lista de secciones depende del archivo/hoja activos, que todavía no se
# conocen aquí — se dibuja más abajo, dentro de `nav_slot` (un contenedor
# reservado ahora y rellenado después de calcular esa información).
# ─────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="sidebar-logo"><div class="sidebar-logo-mark">📊</div><div class="sidebar-logo-text">Excel Intelligence<small>UNIVERSAL</small></div></div>', unsafe_allow_html=True)
    if st.session_state.get("auth_user"):
        u = st.session_state.auth_user
        col_user, col_out = st.columns([3, 1])
        col_user.markdown(f'<p class="sidebar-section-label" style="margin:0;">👤 {u.get("display_name") or u.get("username")}</p>', unsafe_allow_html=True)
        if col_out.button("Salir", key="logout_btn", use_container_width=True):
            auth_engine.logout()
            st.rerun()
    if st.button("⚡ Cambiar a Análisis Práctico", use_container_width=True, key="switch_to_practico"):
        st.session_state.analysis_mode = "practico"
        st.rerun()

    nav_slot = st.container()

    with st.expander("📁 Archivo y herramientas", expanded=not bool(st.session_state.workbook)):
        st.markdown('<p class="sidebar-section-label" style="margin-top:0;">Tu archivo</p>', unsafe_allow_html=True)
        upload=st.file_uploader("Cargar Excel / CSV",type=["xlsx","xls","xlsb","xlsm","csv"], key="single_upload", label_visibility="collapsed")
        if upload and st.button("Analizar archivo",type="primary",use_container_width=True):
            with st.spinner("Analizando estructura, fechas, calidad y relaciones..."):
                try:
                    st.session_state.workbook=load_workbook(upload)
                    st.session_state.filters={}
                except Exception as e:
                    st.error(f"No pudimos procesar este archivo: {e}")

        st.divider()
        st.markdown('<p class="sidebar-section-label">⚖️ Comparar periodos o archivos</p>', unsafe_allow_html=True)
        compare_uploads=st.file_uploader(
            "Selecciona 2 o más archivos",
            type=["xlsx","xls","xlsb","xlsm","csv"],
            accept_multiple_files=True,
            key="compare_uploads",
            help="Ej.: Enero 2024, Enero 2025. También puedes cargar varios periodos."
        )
        if compare_uploads and st.button("Comparar archivos", use_container_width=True):
            if len(compare_uploads) < 2:
                st.warning("Selecciona al menos dos archivos para comparar.")
            else:
                with st.spinner("Buscando variables equivalentes y calculando cambios..."):
                    try:
                        workbooks=[load_workbook(f) for f in compare_uploads]
                        prepared=prepare_comparison(workbooks)
                        st.session_state.comparison_raw_files=prepared["files"]
                        st.session_state.comparison_filters={}
                        st.session_state.comparison_result=build_comparison(prepared)
                        st.session_state.comparison_error=None
                    except Exception as e:
                        st.session_state.comparison_result=None
                        st.session_state.comparison_error=str(e)
        if st.session_state.comparison_result:
            cr=st.session_state.comparison_result
            st.success(f"Comparativa lista · {len(cr['files'])} archivos")
        if st.session_state.comparison_error:
            st.error(f"No pudimos crear la comparativa: {st.session_state.comparison_error}")

        st.divider()
        st.markdown('<p class="sidebar-section-label">📍 Análisis de seguimiento</p>', unsafe_allow_html=True)
        if db_engine.is_configured():
            st.caption("🟢 Conectado a la base de datos compartida — todo el equipo ve la misma información con este link.")
        else:
            st.caption("🟡 Sin base de datos conectada todavía — modo manual: exporta el consolidado y vuelve a subirlo la próxima vez.")
        tracking_new_files = st.file_uploader(
            "Excel nuevos a procesar",
            type=["xlsx", "xls", "xlsb", "xlsm", "csv"],
            accept_multiple_files=True,
            key="tracking_new_uploads",
        )
        tracking_consolidated_file = None
        if not db_engine.is_configured():
            tracking_consolidated_file = st.file_uploader(
                "Historial consolidado (opcional, el que descargaste la vez anterior)",
                type=["xlsx"],
                accept_multiple_files=False,
                key="tracking_consolidated_upload",
                help="Si no lo subes, se parte de cero solo con los archivos nuevos.",
            )
        if tracking_new_files and st.button("Procesar seguimiento", use_container_width=True, key="tracking_process_btn"):
            with st.spinner("Cruzando funcionarios entre archivos..."):
                try:
                    if db_engine.is_configured():
                        existing = db_engine.load_from_db()
                    elif tracking_consolidated_file is not None:
                        existing = read_consolidated(tracking_consolidated_file)
                    else:
                        existing = None
                    batch_label = datetime.now().strftime("%Y-%m-%d %H:%M")
                    new_long_parts = []
                    for f in tracking_new_files:
                        sources = ingest_file(f, batch_label=batch_label)
                        if not sources:
                            st.warning(f"'{f.name}' no tiene una columna de ID o nombre reconocible; se omitió del cruce.")
                            continue
                        new_long_parts.append(sources_to_long(sources, upload_batch=batch_label))
                    new_long = pd.concat(new_long_parts, ignore_index=True) if new_long_parts else pd.DataFrame()
                    combined = merge_long(existing, new_long)
                    if db_engine.is_configured():
                        db_engine.save_to_db(combined)
                    st.session_state.tracking_data = combined
                    st.session_state.tracking_error = None
                except Exception as e:
                    st.session_state.tracking_error = str(e)
        if st.session_state.tracking_data is not None and not st.session_state.tracking_data.empty:
            td = st.session_state.tracking_data
            st.success(f"Seguimiento listo · {td['person_key'].nunique()} funcionarios · {td['source_file'].nunique()} archivos")
        if st.session_state.tracking_error:
            st.error(f"No pudimos procesar el seguimiento: {st.session_state.tracking_error}")

wb=st.session_state.workbook
if not wb:
    if st.session_state.comparison_result:
        render_comparison(st.session_state.comparison_result)
        st.stop()
    if st.session_state.tracking_data is not None and not st.session_state.tracking_data.empty:
        render_tracking(st.session_state.tracking_data)
        st.stop()
    st.info("Carga un archivo para comenzar, o selecciona varios archivos en la sección Comparar periodos o archivos, o usa Análisis de seguimiento en la barra lateral.")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────
# Barra de contexto persistente: archivo/hoja, buscar/preguntar, filtros
# como chips, exportar y asistente — visible sobre cualquier sección.
# ─────────────────────────────────────────────────────────────────────────
c_file, c_sheet, c_search, c_export, c_assist = st.columns([1.3, 1.15, 3.15, .95, .95])
with c_file:
    st.markdown(f'<div class="context-chip"><span class="mono">ARCHIVO</span>{wb["filename"]}</div>', unsafe_allow_html=True)
with c_sheet:
    sheet=st.selectbox("Hoja",list(wb["sheets"]), label_visibility="collapsed", key="topbar_sheet_select")
st.session_state.active_sheet = sheet
item=wb["sheets"][sheet]
raw_df=item["processed"]
schema=item["profile"]["schema"]

# ── Filtros: chips de lo activo + popover con los mismos controles de siempre ──
full_name = schema.get("full_name", {})
full_name_col = full_name.get("column") if isinstance(full_name, dict) else None
hidden_name_parts = set(full_name.get("parts", [])) if isinstance(full_name, dict) else set()

filter_columns=[x for x in schema.get("categorical", []) if x in raw_df.columns and not str(x).startswith("__")]
if full_name_col and full_name_col in raw_df.columns:
    filter_columns=[x for x in filter_columns if x not in hidden_name_parts and x != full_name_col]
preferred=[]
sem_map={x.get("column"):x.get("semantic_type") for x in schema.get("semantic",{}).get("columns",[])}
preferred_types={"region","department","state","zone","city","country","segment","category","product","brand","status","type","customer","employee"}
for c in filter_columns:
    if sem_map.get(c) in preferred_types:
        preferred.append(c)
preferred += [c for c in filter_columns if c not in preferred]
visible_filters=preferred[:4]
extra_filters=preferred[4:]

filter_source=raw_df
date_rule=st.session_state.filters.get("__date__")
if isinstance(date_rule,dict) and date_rule.get("column") in raw_df.columns:
    try:
        dcol=date_rule["column"]
        filter_source=raw_df[(raw_df[dcol]>=date_rule["start"]) & (raw_df[dcol]<=date_rule["end"])].copy()
    except Exception:
        filter_source=raw_df

all_filter_cols=([full_name_col] if full_name_col and full_name_col in raw_df.columns else []) + preferred
active_categorical={c:r for c,r in st.session_state.filters.items()
                    if not str(c).startswith("__") and isinstance(r,dict) and c in raw_df.columns}
options_by_col=cascading_options(filter_source, all_filter_cols, active_categorical, limit=2000)

def _render_context_filter(c):
    opts=options_by_col.get(c, [])
    widget_key=f"filter_{sheet}_{c}"
    current=st.session_state.get(widget_key, [])
    if not isinstance(current, list): current=list(current) if current else []
    valid_current=[v for v in current if str(v) in set(opts)]
    if valid_current != current: st.session_state[widget_key]=valid_current
    selected=st.multiselect(str(c),opts,key=widget_key,placeholder="Selecciona opciones…")
    if selected:
        st.session_state.filters[c]={"op":"in","value":selected}
    elif c in st.session_state.filters:
        st.session_state.filters.pop(c,None)

active_count=sum(1 for c in st.session_state.filters if not str(c).startswith("__")) + (1 if "__date__" in st.session_state.filters else 0)

chip_row = st.container()

with c_export:
    if st.button("⬇ Exportar", use_container_width=True, key="topbar_export_btn"):
        st.session_state.active_section = "Informes"
        st.rerun()

with c_search:
    query=st.text_input("Buscar", placeholder="🔎 Pregúntale al Excel — ej.: mayores a 100000, Bogotá, producto X...", label_visibility="collapsed", key="topbar_query")

has_person_search = bool(full_name_col and full_name_col in raw_df.columns)
has_date_filter = bool(schema["dates"])

with chip_row:
    ratios = [0.55] + ([1.3] if has_person_search else []) + ([0.75] if has_date_filter else []) + [0.85, 1.6]
    chip_cols = st.columns(ratios)
    ci = 0
    with chip_cols[ci]:
        st.caption("**Filtros:**")
    ci += 1

    if has_person_search:
        names = (raw_df[full_name_col].dropna().astype(str).str.strip())
        names = sorted([x for x in names.unique().tolist() if x], key=str.casefold)
        name_key = f"person_filter_{sheet}"
        current_name = st.session_state.get(name_key)
        if current_name not in names:
            current_name = None
        with chip_cols[ci]:
            selected_name = st.selectbox(
                "Buscar persona", names, index=(names.index(current_name) if current_name in names else None),
                key=name_key, placeholder="👤 Buscar persona…", label_visibility="collapsed",
                help="Empieza a escribir para encontrar un nombre. Al seleccionarlo, todos los datos relacionados se filtran automáticamente.",
            )
        ci += 1
        if selected_name:
            st.session_state.filters[full_name_col] = {"op":"in", "value":[selected_name]}
        elif full_name_col in st.session_state.filters:
            st.session_state.filters.pop(full_name_col, None)

    if has_date_filter:
        dc=schema["dates"][0]
        vals=raw_df[dc].dropna()
        with chip_cols[ci]:
            if len(vals):
                lo,hi=vals.min().date(),vals.max().date()
                with st.popover("📅 Periodo", use_container_width=True):
                    dr=st.date_input("Periodo",value=(lo,hi),min_value=lo,max_value=hi, key=f"period_filter_{sheet}")
                    if isinstance(dr,tuple) and len(dr)==2:
                        st.session_state.filters["__date__"]={"column":dc,"start":pd.Timestamp(dr[0]),"end":pd.Timestamp(dr[1])}
        ci += 1

    with chip_cols[ci]:
        with st.popover("+ Añadir filtro", use_container_width=True):
            st.caption("Selecciona una persona o usa los filtros de contexto. Todo el panel se actualiza con la selección.")
            if visible_filters:
                st.markdown("**🎯 Segmentación**")
                for c in visible_filters:
                    _render_context_filter(c)
            if extra_filters:
                with st.expander(f"Más filtros · {len(extra_filters)} disponibles", expanded=False):
                    for c in extra_filters:
                        _render_context_filter(c)
            if active_count:
                if st.button("✕ Limpiar filtros", use_container_width=True, key=f"clear_filters_{sheet}"):
                    st.session_state.filters={}
                    for k in list(st.session_state.keys()):
                        if str(k).startswith("filter_") or str(k).startswith("person_filter_") or str(k).startswith("period_filter_"):
                            st.session_state.pop(k, None)
                    st.rerun()
    ci += 1
    with chip_cols[ci]:
        st.caption(f"{active_count} filtro(s) activo(s) · {wb['size_mb']:.2f} MB · {len(raw_df):,} registros · {len(raw_df.columns)} columnas" if active_count else f"{wb['size_mb']:.2f} MB · {len(raw_df):,} registros · {len(raw_df.columns)} columnas")

# ─────────────────────────────────────────────────────────────────────────
# Aplicar filtros y la búsqueda, igual que antes, de forma defensiva: un
# filtro nunca debe poder tronar el panel si su columna ya no existe (por
# ejemplo, tras cambiar de hoja).
# ─────────────────────────────────────────────────────────────────────────
df=raw_df.copy()
valid_filters = {}
if "__date__" in st.session_state.filters:
    f=st.session_state.filters["__date__"]
    date_col=f.get("column")
    if date_col in df.columns:
        valid_filters["__date__"]=f
    else:
        st.session_state.filters.pop("__date__", None)

for c,r in list(st.session_state.filters.items()):
    if c.startswith("__"): continue
    if c in df.columns:
        valid_filters[c]=r
    else:
        st.session_state.filters.pop(c, None)

if "__date__" in valid_filters:
    f=valid_filters["__date__"]
    date_col=f["column"]
    df=df[(df[date_col]>=f["start"]) & (df[date_col]<=f["end"])]

for c,r in valid_filters.items():
    if c.startswith("__"): continue
    op=r.get("op")
    if op=="in":
        df=df[df[c].astype(str).isin([str(v) for v in r.get("value",[])])]
    elif op in {"equals","contains","gt","gte","lt","lte"}:
        df,_meta=apply_filters(df,{c:r})

st.markdown(f"**{len(df):,} registros visibles** · Todos los indicadores y gráficos se recalculan sobre la selección actual.")

if query:
    df,_=natural_filter(df,query,schema)
    st.caption(f"Resultado de la consulta: {len(df):,} registros")

mode_info=detect_dataset_mode(df, schema)
dashboard=_cached_build_dashboard(df,item["profile"])
classification = mode_info.get("classification", {})
geo_enabled, geo_meta = supports_georeferencing(df, schema)

with c_assist:
    if st.button("🤖 Asistente", use_container_width=True, key="topbar_assistant_btn"):
        st.session_state["show_assistant_inline"] = not st.session_state.get("show_assistant_inline", False)

if st.session_state.get("show_assistant_inline"):
    # `st.chat_input` no se puede anidar de forma confiable dentro de un
    # `st.popover`, así que el asistente se abre como panel inline (mismo
    # patrón que ya usa `ui/executive.py` para el perfil individual) en vez
    # de vivir dentro del botón de la barra de contexto.
    with st.container(border=True):
        if st.button("✕ Cerrar asistente", key="close_assistant_inline"):
            st.session_state["show_assistant_inline"] = False
            st.rerun()
        render_assistant(df, schema, item["profile"], mode_info, dashboard)

if classification:
    capabilities = classification.get("capabilities", [])
    cap_labels = {"evolucion":"evolución", "comparacion_periodos":"comparación de periodos", "ranking":"rankings", "distribucion":"distribuciones", "relaciones":"relaciones entre métricas", "estadisticas":"estadísticas", "grafico_distribucion":"gráficos de distribución", "geografia":"geografía", "catalogo":"consulta de catálogo", "estados":"seguimiento de estados"}
    readable_caps = ", ".join(cap_labels.get(x, x) for x in capabilities[:6]) or "lectura y tabla"
    st.markdown(
        f'<div class="mode-banner"><b>Tipo detectado:</b> {classification.get("label", "Datos generales")}'
        f'<span class="mode-confidence">confianza {classification.get("confidence",0)*100:.0f}%</span></div>',
        unsafe_allow_html=True,
    )
    with st.expander("¿Por qué este tipo? Ver detalle", expanded=False):
        st.caption(f'{classification.get("reason", "")} · Herramientas activadas: {readable_caps}.')

if st.session_state.get("focus_view"):
    st.info(f"Análisis enfocado: {st.session_state.focus_view}. Revisa los gráficos y filtros visibles para profundizar.")

# Capacidades individuales: solo aparecen si el Excel realmente contiene una identidad.
full_name_info = schema.get("full_name", {}) if isinstance(schema.get("full_name"), dict) else {}
profile_enabled = bool(full_name_info.get("column") and full_name_info.get("column") in df.columns)

is_catalog_mode = mode_info["mode"] in {"catalog", "reference"}
has_comparison = bool(st.session_state.comparison_result)
has_tracking = st.session_state.tracking_data is not None and not st.session_state.tracking_data.empty

# ─────────────────────────────────────────────────────────────────────────
# Secciones disponibles para este archivo/modo — se rellena el `nav_slot`
# reservado antes en el rail. En modo catálogo/referencia no se ofrecen
# Explorar/Alertas/Personas, igual que la app de hoy tampoco los ofrecía.
# ─────────────────────────────────────────────────────────────────────────
if is_catalog_mode:
    sections = ["Resumen", "Datos"]
    if geo_enabled: sections.append("Mapa")
    sections.append("Informes")
else:
    sections = ["Resumen", "Explorar", "Datos", "Alertas"]
    if profile_enabled: sections.append("Personas")
    if geo_enabled: sections.append("Mapa")
    sections.append("Informes")

if st.session_state.active_section not in sections:
    st.session_state.active_section = sections[0]

with nav_slot:
    st.markdown('<p class="sidebar-section-label">Navegación</p>', unsafe_allow_html=True)
    for sec in sections:
        active = st.session_state.active_section == sec
        if st.button(f"{SECTION_ICONS.get(sec,'•')}  {sec}", key=f"nav_{sec}", type="primary" if active else "secondary", use_container_width=True):
            st.session_state.active_section = sec
            st.rerun()
    hidden = [s for s in ("Personas", "Mapa") if s not in sections]
    note = "Personas y Mapa aparecen solo si el archivo los soporta." if hidden else "Personas y Mapa están activos para este archivo."
    st.markdown(f'<div class="nav-note"><span class="nav-note-label">MÓDULOS ACTIVOS</span><span class="nav-note-text">{note}</span></div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────
# Despacho unificado por sección (reemplaza las 3 combinaciones de pestañas
# de antes: catálogo/referencia, Ejecutivo y Analista). Cada sección llama
# exactamente a las mismas funciones de siempre.
# ─────────────────────────────────────────────────────────────────────────
section = st.session_state.active_section

if section == "Resumen":
    if is_catalog_mode:
        render_catalog(df, schema, mode_info)
    else:
        with st.expander("ℹ️ Sobre este archivo", expanded=False):
            render_home(wb, sheet, mode_info, dashboard)
        render_executive(df, schema, dashboard)

elif section == "Explorar":
    sub_names = ["Analítica", "Descripción", "Finanzas", "Trabajo", "Anomalías"]
    sub_tabs = st.tabs(sub_names)
    with sub_tabs[0]:
        render_explorer(df, schema)
    with sub_tabs[1]:
        render_dashboard(df, dashboard)
    with sub_tabs[2]:
        st.subheader("Lectura financiera")
        st.dataframe(dashboard["statistics"], use_container_width=True, hide_index=True)
        st.caption("Esta vista utiliza las métricas detectadas automáticamente; no presupone que el archivo sea de ventas.")
    with sub_tabs[3]:
        st.subheader("Trabajo y decisiones")
        for x in dashboard.get("insights", []):
            title = x.get("title") or x.get("label") or "Hallazgo"
            text = x.get("finding") or x.get("message") or x.get("text") or x.get("description") or "Sin detalle disponible."
            action = x.get("action")
            line = f"**{title}:** {text}"
            if action: line += f"  \n**Qué hacer:** {action}"
            st.markdown(line)
    with sub_tabs[4]:
        # `dashboard["anomalies"]` es lo que el motor realmente calculó — antes
        # esta pestaña recibía el `df` crudo en vez de este resultado.
        render_anomalies(dashboard["anomalies"], schema)

elif section == "Datos":
    render_quality(item["profile"])
    render_data_table(df)

elif section == "Alertas":
    render_alerts(df, dashboard)

elif section == "Personas" and profile_enabled:
    sub_tabs = st.tabs(["⚔️ Comparar", "👤 Perfil individual"])
    with sub_tabs[0]:
        render_person_compare(df, schema)
    with sub_tabs[1]:
        render_person_profile(df, schema, dashboard)

elif section == "Mapa" and geo_enabled:
    render_georeferencing(df, schema)

elif section == "Informes":
    extra = []
    if has_comparison: extra.append("⚖️ Comparativa")
    if has_tracking: extra.append("📍 Seguimiento")
    if extra:
        tab_names = ["Exportar"] + extra
        tabs = st.tabs(tab_names)
        with tabs[0]:
            render_exports(df, dashboard, wb["filename"], sheet, full_df=item["processed"], schema=schema, workbook=wb)
        idx = 1
        if has_comparison:
            with tabs[idx]:
                render_comparison(st.session_state.comparison_result)
            idx += 1
        if has_tracking:
            with tabs[idx]:
                render_tracking(st.session_state.tracking_data)
    else:
        render_exports(df, dashboard, wb["filename"], sheet, full_df=item["processed"], schema=schema, workbook=wb)
