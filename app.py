import streamlit as st
import pandas as pd
from datetime import datetime
from ui.styles.theme import inject_theme
from ui.layouts.hero import hero
from ui.layouts.tabs import grouped_nav
from ui.components.section import section_header
from core.loader import load_workbook
from core.dashboard_engine import build_dashboard


@st.cache_data(show_spinner=False, max_entries=12, ttl=1800)
def _cached_build_dashboard(df, profile):
    # build_dashboard es lo más pesado de la app (KPIs, hallazgos, anomalías,
    # estadísticas). Streamlit vuelve a ejecutar TODO el script en cada clic
    # (cambiar de pestaña, aplicar un filtro), así que sin este caché se
    # recalculaba desde cero cada vez, aunque los datos visibles no hubieran
    # cambiado. Streamlit reconoce cuándo df/profile son iguales a una
    # llamada anterior y reutiliza el resultado en vez de recalcular.
    return build_dashboard(df, profile)
from core.dataset_mode import detect_dataset_mode
from core.filter_engine import apply_filters, natural_filter, cascading_options
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
from ui.home import render_home
from ui.landing import render_landing
from ui.login import render_login
import core.auth_engine as auth_engine
from ui.mode_choice import render_mode_choice
from ui.practical import render_practical_page
from ui.tracking import render_tracking
from ui.multi_sheet import render_multi_sheet
from core.tracking_engine import ingest_file, sources_to_long, merge_long, read_consolidated
import core.db_engine as db_engine

if "view_mode" not in st.session_state:
    st.session_state.view_mode = "Ejecutivo"
if "app_started" not in st.session_state:
    st.session_state.app_started = False
if "theme_mode" not in st.session_state:
    st.session_state.theme_mode = "light"  # el jefe pidió blanco por defecto; oscuro es opcional, elegido por cada quien

st.set_page_config(
    page_title="Panel Analítico Universal", page_icon="📊", layout="wide",
    initial_sidebar_state="collapsed" if not st.session_state.app_started else "auto",
)

_DARK = st.session_state.theme_mode == "dark"

inject_theme(_DARK)

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

hero("📊 Panel Analítico Universal", "De Excel crudo a decisiones: qué pasó, dónde pasó, qué lo explica y qué conviene revisar.")

with st.sidebar:
    st.markdown('<div class="sidebar-logo"><div class="sidebar-logo-mark">📊</div><div class="sidebar-logo-text">Panel Analítico<small>Centro de control universal</small></div></div>', unsafe_allow_html=True)
    theme_choice = st.radio(
        "Tema", ["☀️ Claro", "🌙 Oscuro"], horizontal=True, label_visibility="collapsed",
        index=0 if st.session_state.theme_mode == "light" else 1, key="theme_mode_radio",
    )
    new_theme = "light" if theme_choice == "☀️ Claro" else "dark"
    if new_theme != st.session_state.theme_mode:
        st.session_state.theme_mode = new_theme
        st.rerun()
    if st.session_state.get("auth_user"):
        u = st.session_state.auth_user
        col_user, col_out = st.columns([3, 1])
        col_user.markdown(f'<p class="sidebar-section-label" style="margin:0;">👤 {u.get("display_name") or u.get("username")}</p>', unsafe_allow_html=True)
        if col_out.button("Salir", key="logout_btn", use_container_width=True):
            auth_engine.logout()
            st.rerun()

    st.markdown('<p class="sidebar-group-header">ARCHIVO</p>', unsafe_allow_html=True)
    if st.button("⚡ Cambiar a Análisis Práctico", use_container_width=True, key="switch_to_practico"):
        st.session_state.analysis_mode = "practico"
        st.rerun()
    # Una vez hay un archivo cargado, subir uno nuevo pasa a ser la acción
    # menos frecuente de esta sección (se hace una vez, luego se trabaja
    # sobre "Hoja activa" el resto de la sesión) — así que el cargador
    # completo (caja de arrastrar y soltar) se colapsa detrás de un resumen
    # de una línea con el nombre del archivo, en vez de ocupar ese espacio
    # siempre. Sigue expandido por defecto mientras no haya ningún archivo.
    _wb_before = st.session_state.workbook
    with st.expander(
        f'📄 {_wb_before["filename"]}' if _wb_before else "📤 Cargar Excel / CSV",
        expanded=(_wb_before is None),
    ):
        upload=st.file_uploader("Cargar Excel / CSV",type=["xlsx","xls","xlsb","xlsm","csv"], key="single_upload", label_visibility="collapsed")
        if upload and st.button("Analizar archivo",type="primary",use_container_width=True):
            with st.spinner("Analizando estructura, fechas, calidad y relaciones..."):
                try:
                    st.session_state.workbook=load_workbook(upload)
                    st.session_state.filters={}
                except Exception as e:
                    st.error(f"No pudimos procesar este archivo: {e}")
        if _wb_before:
            st.caption("¿Otro archivo? Súbelo aquí para reemplazar el actual.")

    wb=st.session_state.workbook
    if wb:
        st.markdown('<p class="sidebar-section-label" style="margin-top:10px;">Hoja activa</p>', unsafe_allow_html=True)
        sheet=st.selectbox("Hoja",list(wb["sheets"]), label_visibility="collapsed")
        item=wb["sheets"][sheet]
        st.session_state.active_sheet = sheet
        df=item["processed"]
        schema=item["profile"]["schema"]
        mode_info=detect_dataset_mode(df, schema)

        st.markdown('<p class="sidebar-group-header">VISTA</p>', unsafe_allow_html=True)
        st.session_state.view_mode = st.radio(
            "Nivel de detalle",
            ["Ejecutivo", "Analista"],
            horizontal=True,
            key="view_mode_radio",
            help="Ejecutivo prioriza conclusiones y visualizaciones. Analista muestra todas las herramientas y controles.",
            label_visibility="collapsed",
        )

        st.markdown('<p class="sidebar-group-header">FILTROS</p>', unsafe_allow_html=True)
        st.caption("Selecciona una persona o usa los filtros de contexto. Todo el dashboard se actualiza con la selección.")

        # ── Búsqueda principal de persona ────────────────────────────────
        # Si el archivo tiene Nombre + Apellidos, el usuario trabaja con una
        # sola identidad completa. No debe tener que combinar tres filtros.
        full_name = schema.get("full_name", {})
        full_name_col = full_name.get("column") if isinstance(full_name, dict) else None
        hidden_name_parts = set(full_name.get("parts", [])) if isinstance(full_name, dict) else set()

        if full_name_col and full_name_col in df.columns:
            names = (df[full_name_col].dropna().astype(str).str.strip())
            names = sorted([x for x in names.unique().tolist() if x], key=str.casefold)
            name_key = f"person_filter_{sheet}"
            # El selector es searchable: el usuario puede escribir unas letras
            # para encontrar el nombre, pero siempre selecciona un nombre real
            # existente en el Excel.
            current_name = st.session_state.get(name_key)
            if current_name not in names:
                current_name = None
            selected_name = st.selectbox(
                "Buscar persona",
                names,
                index=(names.index(current_name) if current_name in names else None),
                key=name_key,
                placeholder="Busca y selecciona un nombre completo…",
                help="Empieza a escribir para encontrar un nombre. Al seleccionarlo, todos los datos relacionados se filtran automáticamente.",
            )
            if selected_name:
                st.session_state.filters[full_name_col] = {"op":"in", "value":[selected_name]}
                st.success(f"Mostrando todo lo relacionado con **{selected_name}**")
            elif full_name_col in st.session_state.filters:
                st.session_state.filters.pop(full_name_col, None)

        # ── Periodo ───────────────────────────────────────────────────────
        # Antes vivía dentro de un expander que siempre arrancaba abierto
        # (expanded=True): un solo widget no necesita esa envoltura, solo
        # ocupaba espacio extra (icono, borde, padding) sin ofrecer un
        # colapso real. Un rótulo compacto cumple la misma función.
        if schema["dates"]:
            st.markdown('<p class="sidebar-section-label">📅 Periodo</p>', unsafe_allow_html=True)
            dc=schema["dates"][0]
            vals=df[dc].dropna()
            if len(vals):
                lo,hi=vals.min().date(),vals.max().date()
                dr=st.date_input("Periodo",value=(lo,hi),min_value=lo,max_value=hi, key=f"period_filter_{sheet}", label_visibility="collapsed")
                if isinstance(dr,tuple) and len(dr)==2:
                    # st.date_input devuelve fechas sin hora: pd.Timestamp(dr[1])
                    # cae a medianoche del día final. Si la columna tiene además
                    # una hora (p.ej. "2026-01-31 14:23:00"), comparar con <= esa
                    # medianoche excluía todo lo registrado después de las 00:00
                    # del último día — el día final quedaba prácticamente fuera
                    # del rango. Se extiende el límite superior al final de ese
                    # día (23:59:59.999999) para que el rango sea inclusivo de
                    # verdad, sin importar si la columna trae hora o no.
                    end_of_day = pd.Timestamp(dr[1]) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
                    st.session_state.filters["__date__"]={"column":dc,"start":pd.Timestamp(dr[0]),"end":end_of_day}

        # ── Filtros de contexto ──────────────────────────────────────────
        filter_columns=[x for x in schema.get("categorical", []) if x in df.columns and not str(x).startswith("__")]
        if full_name_col and full_name_col in df.columns:
            filter_columns=[x for x in filter_columns if x not in hidden_name_parts and x != full_name_col]
        # Evita una barra lateral interminable: muestra primero los campos más
        # útiles y deja el resto dentro de "Más filtros".
        preferred=[]
        sem_map={x.get("column"):x.get("semantic_type") for x in schema.get("semantic",{}).get("columns",[])}
        preferred_types={"region","department","state","zone","city","country","segment","category","product","brand","status","type","customer","employee"}
        for c in filter_columns:
            if sem_map.get(c) in preferred_types:
                preferred.append(c)
        preferred += [c for c in filter_columns if c not in preferred]
        visible_filters=preferred[:4]
        extra_filters=preferred[4:]

        # La fecha también participa en la cascada.
        filter_source=df
        date_rule=st.session_state.filters.get("__date__")
        if isinstance(date_rule,dict) and date_rule.get("column") in df.columns:
            try:
                dcol=date_rule["column"]
                filter_source=df[(df[dcol]>=date_rule["start"]) & (df[dcol]<=date_rule["end"])].copy()
            except Exception:
                filter_source=df

        all_filter_cols=([full_name_col] if full_name_col and full_name_col in df.columns else []) + preferred
        active_categorical={c:r for c,r in st.session_state.filters.items()
                            if not str(c).startswith("__") and isinstance(r,dict) and c in df.columns}
        options_by_col=cascading_options(filter_source, all_filter_cols, active_categorical, limit=2000)

        def render_context_filter(c):
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

        # "🎯 Segmentación" tampoco necesita expander: siempre arrancaba
        # abierto (mismo problema que "📅 Tiempo"). "Más filtros" sí se queda
        # como expander porque ese sí colapsa de verdad por defecto
        # (expanded=False) — es la única sección que realmente ahorra
        # espacio ocultando algo que no siempre hace falta ver.
        if visible_filters:
            st.markdown('<p class="sidebar-section-label">🎯 Segmentación</p>', unsafe_allow_html=True)
            for c in visible_filters:
                render_context_filter(c)
        if extra_filters:
            with st.expander(f"Más filtros · {len(extra_filters)} disponibles", expanded=False):
                for c in extra_filters:
                    render_context_filter(c)

        active_count=sum(1 for c in st.session_state.filters if not str(c).startswith("__")) + (1 if "__date__" in st.session_state.filters else 0)
        if active_count:
            if st.button("✕ Limpiar filtros", use_container_width=True, key=f"clear_filters_{sheet}"):
                # Limpia reglas y valores de widgets de la hoja actual.
                st.session_state.filters={}
                for k in list(st.session_state.keys()):
                    if str(k).startswith("filter_") or str(k).startswith("person_filter_") or str(k).startswith("period_filter_"):
                        st.session_state.pop(k, None)
                st.rerun()
            st.caption(f"{active_count} filtro(s) activo(s)")
        st.markdown(f'<div class="mode-banner"><span class="mode-banner-label">MODO DETECTADO</span><br><b>{mode_info["label"]}</b> <span class="mode-confidence">{mode_info["confidence"]*100:.0f}%</span></div>', unsafe_allow_html=True)

        with st.expander("🤖 Asistente IA", expanded=False):
            st.caption("Opcional: conecta una API key para habilitar conversación y análisis asistido.")
            st.session_state.assistant_api_key = st.text_input("OpenAI API key", value=st.session_state.get("assistant_api_key", ""), type="password", key="sidebar_assistant_key")
            st.session_state.assistant_model = st.text_input("Modelo", value=st.session_state.get("assistant_model", "gpt-5.5"), key="sidebar_assistant_model")
        st.divider()
        st.caption(f"{wb['filename']} · {wb['size_mb']:.2f} MB")
        st.caption(f"{len(df):,} registros · {len(df.columns)} columnas")


    with st.expander("🧰 Herramientas avanzadas", expanded=False):
        st.markdown('<p class="sidebar-section-label" style="margin-top:0;">⚖️ Comparar periodos o archivos</p>', unsafe_allow_html=True)
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
if not st.session_state.workbook:
    if st.session_state.comparison_result:
        render_comparison(st.session_state.comparison_result)
        st.stop()
    if st.session_state.tracking_data is not None and not st.session_state.tracking_data.empty:
        render_tracking(st.session_state.tracking_data)
        st.stop()
    st.info("Carga un archivo para comenzar, o selecciona varios archivos en la sección Comparar periodos o archivos, o usa Análisis de seguimiento en la barra lateral.")
    st.stop()

st.session_state.active_sheet = sheet
item=wb["sheets"][sheet]
df=item["processed"].copy()
schema=item["profile"]["schema"]

# Apply filters globally and defensively.
# A filter must never be able to crash the dashboard if its column
# no longer exists (for example after changing sheets).
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
        # Remove stale filters from previous sheets/files.
        st.session_state.filters.pop(c, None)

if "__date__" in valid_filters:
    f=valid_filters["__date__"]
    date_col=f["column"]
    df=df[(df[date_col]>=f["start"]) & (df[date_col]<=f["end"])]

# Categorical/numeric filters are applied only when their source column exists.
for c,r in valid_filters.items():
    if c.startswith("__"): continue
    op=r.get("op")
    if op=="in":
        df=df[df[c].astype(str).isin([str(v) for v in r.get("value",[])])]
    elif op in {"equals","contains","gt","gte","lt","lte"}:
        df,_meta=apply_filters(df,{c:r})

st.markdown(f"**{len(df):,} registros visibles** · Todos los indicadores y gráficos se recalculan sobre la selección actual.")

query=st.text_input("🔎 Pregúntale al Excel",placeholder="Ej.: mayores a 100000, Bogotá, producto X...",key="natural_query_search")
if query:
    df,_=natural_filter(df,query,schema)
    st.caption(f"Resultado de la consulta: {len(df):,} registros")

mode_info=detect_dataset_mode(df, schema)
dashboard=_cached_build_dashboard(df,item["profile"])
geo_enabled, geo_meta = supports_georeferencing(df, schema)

# "Tipo detectado" ya no se repite aquí encima de cada pestaña: esta misma
# información (label + confianza + por qué + herramientas activadas), con
# el mismo `mode_info["classification"]`, ya la muestra 🏠 Inicio — que es
# donde alguien nuevo la ve primero, una sola vez, no arriba de Datos,
# Exportar, etc. donde no aporta nada. El resumen corto sigue siempre
# visible en la barra lateral ("MODO DETECTADO").

if st.session_state.get("focus_view"):
    st.info(f"Análisis enfocado: {st.session_state.focus_view}. Revisa los gráficos y filtros visibles para profundizar.")

# Capacidades individuales: solo aparecen si el Excel realmente contiene una identidad.
full_name_info = schema.get("full_name", {}) if isinstance(schema.get("full_name"), dict) else {}
profile_enabled = bool(full_name_info.get("column") and full_name_info.get("column") in df.columns)

# "Varias hojas" (buscar/combinar/comparar hojas del mismo Excel) solo
# aparece con 2+ hojas que de verdad tengan datos — con una sola hoja no
# hay nada que buscar en varias, combinar ni comparar.
usable_sheet_count = sum(
    1 for _s in wb["sheets"].values()
    if isinstance(_s, dict) and isinstance(_s.get("processed"), pd.DataFrame) and not _s["processed"].empty
)
multi_sheet_enabled = usable_sheet_count >= 2

# La comparativa vive en el mismo producto, pero separada del análisis individual.
# El perfil individual NO es una pestaña adicional: se abre con su botón dentro del dashboard.
general_views = [
    ("🏠 Inicio", lambda: render_home(wb, sheet, mode_info, dashboard)),
    ("Asistente IA", lambda: render_assistant(df, schema, item["profile"], mode_info, dashboard)),
    ("Datos", lambda: render_data_table(df)),
    ("Calidad", lambda: render_quality(item["profile"])),
    ("Exportar", lambda: render_exports(df,dashboard,wb["filename"],sheet,full_df=item["processed"],schema=schema,workbook=wb)),
]
if multi_sheet_enabled:
    general_views.append(("🗂️ Varias hojas", lambda: render_multi_sheet(wb)))
people_views = []
if profile_enabled:
    people_views.append(("⚔️ Comparar personas", lambda: render_person_compare(df, schema)))
if st.session_state.tracking_data is not None and not st.session_state.tracking_data.empty:
    people_views.append(("📍 Análisis Seguimiento", lambda: render_tracking(st.session_state.tracking_data)))

if mode_info["mode"] in {"catalog", "reference"}:
    st.markdown(f'<div class="mode-banner"><b>{mode_info["label"]}</b> · {mode_info["reason"]}</div>', unsafe_allow_html=True)
    # Vista principal reemplaza a Comparar personas en el modo catálogo: un
    # catálogo/lista de referencia no tiene "personas" que comparar, así que
    # Comparar personas nunca aparecía aquí (igual que antes de esta tarea).
    analysis_views = [("Vista principal", lambda: render_catalog(df, schema, mode_info))]
    if geo_enabled:
        analysis_views.append(("Georeferenciación", lambda: render_georeferencing(df, schema)))
    if st.session_state.comparison_result:
        analysis_views.append(("⚖️ Comparativa", lambda: render_comparison(st.session_state.comparison_result)))
    catalog_people_views = [v for v in people_views if v[0] != "⚔️ Comparar personas"]
    grouped_nav([
        ("📋 General", general_views),
        ("📊 Análisis", analysis_views),
        ("👥 Personas", catalog_people_views),
    ])
else:
    # Executive mode is deliberately compact; Analyst mode exposes every tool.
    if st.session_state.get("view_mode", "Ejecutivo") == "Ejecutivo":
        analysis_views = [("Resumen ejecutivo", lambda: render_executive(df, schema, dashboard))]
        if geo_enabled:
            analysis_views.append(("Georeferenciación", lambda: render_georeferencing(df, schema)))
        if st.session_state.comparison_result:
            analysis_views.append(("⚖️ Comparativa", lambda: render_comparison(st.session_state.comparison_result)))
        grouped_nav([
            ("📋 General", general_views),
            ("📊 Análisis", analysis_views),
            ("👥 Personas", people_views),
        ])
    else:
        def _render_finanzas():
            st.markdown(section_header("Lectura financiera", eyebrow="ANÁLISIS", compact=True), unsafe_allow_html=True)
            st.dataframe(dashboard["statistics"],use_container_width=True,hide_index=True)
            st.caption("Esta vista utiliza las métricas detectadas automáticamente; no presupone que el archivo sea de ventas.")

        def _render_trabajo():
            st.markdown(section_header("Trabajo y decisiones", eyebrow="ANÁLISIS", compact=True), unsafe_allow_html=True)
            for x in dashboard.get("insights", []):
                title = x.get("title") or x.get("label") or "Hallazgo"
                text = x.get("finding") or x.get("message") or x.get("text") or x.get("description") or "Sin detalle disponible."
                action = x.get("action")
                line = f"**{title}:** {text}"
                if action: line += f"  \n**Qué hacer:** {action}"
                st.markdown(line)

        analysis_views = [("Descripción", lambda: render_dashboard(df,dashboard))]
        if geo_enabled:
            analysis_views.append(("Georeferenciación", lambda: render_georeferencing(df, schema)))
        analysis_views += [
            ("Analítica", lambda: render_explorer(df,schema)),
            ("Finanzas", _render_finanzas),
            ("Trabajo", _render_trabajo),
            ("Anomalías", lambda: render_anomalies(df, schema)),
        ]
        if st.session_state.comparison_result:
            analysis_views.append(("⚖️ Comparativa", lambda: render_comparison(st.session_state.comparison_result)))
        grouped_nav([
            ("📋 General", general_views),
            ("📊 Análisis", analysis_views),
            ("👥 Personas", people_views),
        ])

