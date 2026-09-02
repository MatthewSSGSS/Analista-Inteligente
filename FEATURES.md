# FEATURES.md — Inventario de funcionalidades (checklist de regresión)

> Generado en la auditoría del rediseño. Cada ítem: qué hace, qué archivo/función lo implementa,
> de qué depende, y el riesgo concreto de romperlo. **Nada de esto debe desaparecer ni cambiar de
> comportamiento** al tocar solo CSS/estructura visual.

Leyenda de riesgo: 🔴 alto (lógica de datos entrelazada con presentación) · 🟡 medio · 🟢 bajo (solo presentación).

---

## 0. Flujo de arranque y navegación global

| # | Funcionalidad | Implementación | Depende de | Riesgo |
|---|---|---|---|---|
| 0.1 | Landing/bienvenida antes de pedir el Excel | `ui/landing.py:render_landing` · gate en `app.py:437-442` (`session_state.app_started`) | — | 🟢 |
| 0.2 | Selección de modo Práctico / Avanzado | `ui/mode_choice.py:render_mode_choice` · gate en `app.py:444-452` (`session_state.analysis_mode`) | — | 🟢 |
| 0.3 | Modo "Análisis Práctico" (subir → resumen → preguntar) | `ui/practical.py:render_practical_page` · `app.py:454-456` | `core/loader`, `core/dashboard_engine`, `core/dataset_mode`, `core/query_engine`, `core/assistant_engine`, `visualization/charts` | 🟡 |
| 0.4 | Botón "Cambiar a Análisis Práctico" desde el modo avanzado | `app.py:479-481` (sidebar) | `session_state.analysis_mode` | 🟢 |
| 0.5 | Login (usuario/contraseña) | `ui/login.py:render_login` · gate `app.py:408-410` (`auth_engine.is_available()`) | `core/auth_engine`, `core/db_engine` | 🔴 — **login está con `BYPASS_AUTH_TEMPORARY = True`** ([ui/login.py:17](ui/login.py#L17)): hoy deja pasar sin validar contraseña real contra BD. Si se reactiva sin probar, puede romper el acceso o dejarlo abierto sin querer. |
| 0.6 | Alta de cuenta ("Crear cuenta") | `ui/login.py` (tab `signup`) → `core/auth_engine.create_user` | `core/db_engine` (requiere BD configurada) | 🔴 — deshabilitado mientras dure el bypass (`disabled=BYPASS_AUTH_TEMPORARY`). |
| 0.7 | Cierre de sesión | `app.py:474-476` (botón "Salir") → `auth_engine.logout()` | `session_state.authenticated/auth_user` | 🟢 |
| 0.8 | Tema Claro/Oscuro (toggle) | `app.py:44-49,56-103,460-469` (`session_state.theme_mode`, radio en sidebar) | CSS inline de `app.py` (variables `--bg`,`--text`, etc.) | 🔴 — **único sistema de tema realmente activo**; ver hallazgo de auditoría sobre `assets/style.css.css` y `ui/theme.py` huérfanos. Cualquier cambio visual debe hacerse aquí, no crear un cuarto sistema. |
| 0.9 | Carga de Excel/CSV único (sidebar) | `app.py:483-490` → `core/loader.load_workbook` | `openpyxl/xlrd/pyxlsb/pandas`, `core/profile.profile_sheet` | 🔴 — parsing central; cualquier hoja de la app depende de esto. |
| 0.10 | Selector de hoja activa | `app.py:495-499` (`st.selectbox("Hoja", ...)`) | `wb["sheets"]` de `load_workbook` | 🟡 |
| 0.11 | Detección de modo/tipo de dataset y banner "Modo detectado" | `core/dataset_mode.detect_dataset_mode` + `core/dataset_classifier.classify_dataset` · render en `app.py:500-511,622,772-787` | `schema` de `core/schema.py` | 🔴 — decide qué tabs/tools se muestran (catálogo vs. dashboard normal, ejecutivo vs. analista). |
| 0.12 | Selector de vista Ejecutivo/Analista | `app.py:504-511` (`session_state.view_mode`) | — | 🟢 — solo decide qué tabs se arman en `app.py:819-882`. |
| 0.13 | Tabs dinámicos según modo/capacidades | `app.py:798-882` | `mode_info`, `geo_enabled`, `profile_enabled`, `comparison_result`, `tracking_data` | 🔴 — lógica condicional compleja; quitar una condición puede ocultar una pestaña entera. |

## 1. Filtros y segmentación (sidebar)

| # | Funcionalidad | Implementación | Depende de | Riesgo |
|---|---|---|---|---|
| 1.1 | Búsqueda/filtro por persona (nombre completo, searchable) | `app.py:517-546` | `schema["full_name"]` (de `core/schema._find_name_parts`) | 🔴 |
| 1.2 | Filtro de periodo (rango de fechas) | `app.py:549-557` | `schema["dates"]`, `session_state.filters["__date__"]` | 🔴 |
| 1.3 | Filtros de contexto (categóricos, cascada) | `app.py:560-610` → `core/filter_engine.cascading_options` | `schema["categorical"]`, `schema["semantic"]` | 🔴 — las opciones de cada filtro dependen de los demás filtros activos (cascada real). |
| 1.4 | "Más filtros" colapsable (columnas no prioritarias) | `app.py:571-610` | igual que 1.3 | 🟢 |
| 1.5 | Botón "Limpiar filtros" | `app.py:613-621` | limpia `session_state.filters` + claves `filter_*`, `person_filter_*`, `period_filter_*` | 🟡 |
| 1.6 | Aplicación efectiva de filtros al `df` mostrado | `app.py:734-763` (in/equals/contains/gt/gte/lt/lte) → `core/filter_engine.apply_filters` | tolera columnas eliminadas al cambiar de hoja (limpieza defensiva) | 🔴 |
| 1.7 | Búsqueda en lenguaje natural ("Pregúntale al Excel") | `app.py:767-770` → `core/filter_engine.natural_filter` | `schema` | 🟡 |
| 1.8 | Contador de filtros activos / registros visibles | `app.py:612,765` | — | 🟢 |

## 2. Resumen ejecutivo / dashboard principal

| # | Funcionalidad | Implementación | Depende de | Riesgo |
|---|---|---|---|---|
| 2.1 | KPIs dinámicos (universales, se adaptan al Excel) | `core/universal_analysis.dynamic_kpis` · render `ui/dashboard._universal_kpi_grid`, `ui/executive.py:39-47` | `core/numeric.safe_*` | 🔴 |
| 2.2 | Headline ejecutivo (situación favorable/estable/negativa) | `core/executive.build_executive` · render `ui/dashboard._executive_headline` | `core/dashboard_engine.build_dashboard` | 🔴 |
| 2.3 | Señales positivas / puntos a vigilar | `core/executive.build_executive` · render `ui/dashboard._executive_signals` | igual | 🟡 |
| 2.4 | Alertas inteligentes con severidad, evidencia y acción | `core/executive.build_alerts` · render `ui/dashboard._alerts_panel` | igual | 🔴 |
| 2.5 | Botón "Ver análisis" en una alerta (enfoca dimensión/metric/filtro) | `ui/dashboard.py:671-679` | `session_state.focus_dimension/focus_metric/focus_view`, `session_state.filters` | 🟡 |
| 2.6 | "¿Por qué cambió?" (explicación de variación entre periodos) | `core/executive.explain_change` · render `ui/dashboard._why_changed` | requiere fecha detectada | 🔴 |
| 2.7 | Hallazgos / líneas de acción (insights) | `core/insights.generate` · render `ui/dashboard._insights_panel` | `core/anomalies.detect` | 🟡 |
| 2.8 | Mejor/peor desempeño por dimensión (con selector) | `core/performance.analyze` · render `ui/dashboard._performance_panel` | requiere 2-40 categorías válidas | 🔴 |
| 2.9 | Drill-down "Del total al detalle" | `core/universal_analysis.drilldown_table/drilldown_options` · render `ui/dashboard._drilldown_panel` | — | 🟡 |
| 2.10 | Perfil del archivo ("qué entendió el sistema" + interpretación de columnas) | `ui/dashboard._profile_panel` + `schema["semantic"]["columns"]` | `core/semantic_engine.interpret_dataframe` | 🟢 |
| 2.11 | Recomendaciones automáticas ("qué conviene revisar") | `ui/dashboard._recommendations_panel` | `dashboard["executive"/"change_analysis"/"alerts"]` | 🟢 |
| 2.12 | Gráfico especial Enero–Diciembre (columnas de meses anchas) | `visualization/charts.wide_month_chart` · render en `ui/dashboard.py:914-924` | solo aparece si `schema["dates"]` está vacío y hay columnas mensuales | 🔴 — lógica muy específica (evita falsos KPIs); no debe perderse al tocar el layout. |
| 2.13 | Controles de visualización (métrica/dimensión/periodo/cálculo/top-N/comparación/%) | `ui/dashboard._visual_controls` | limpia selección obsoleta al cambiar de hoja (líneas 616-623) | 🔴 |
| 2.14 | Selector de tipo de gráfico principal (línea/barra/área/ranking/periodo/dona/histograma/dispersión) | `ui/dashboard._available_chart_types` + `_render_selected_chart` | `visualization/charts.*` | 🔴 |
| 2.15 | Comparación individual (multi-persona/categoría, hasta 6, 9 tipos de gráfico) | `ui/dashboard._individual_trend` (líneas, área, barras agrupadas/apiladas/100%, radar, variación %, heatmap) | reconstruye "Nombre completo" si el perfil no lo trae (líneas 977-991) | 🔴 — lógica de reconstrucción de nombre + reglas de cuándo usar líneas vs. barras (mínimo 2 periodos reales). |
| 2.16 | Ficha de persona embebida tras comparar 1 sola persona | `ui/dashboard._person_profile` (línea 458, **implementación separada** de 2.20) | ver duplicación en auditoría | 🔴 |
| 2.17 | Comparación temporal últimos periodos | `visualization/charts.comparison` · render línea 1116 | requiere fecha + métrica | 🟡 |
| 2.18 | Diagnóstico: ranking de contribución + anterior vs. actual | `visualization/charts.ranking/period_compare_bar` · render líneas 1121-1147 | evita repetir el tipo ya elegido como principal | 🟡 |
| 2.19 | "Gráficos inteligentes" (preguntas que el Excel puede responder) | `core/universal_analysis.smart_chart_questions` · render líneas 1151-1171 | evita duplicar gráfico ya mostrado | 🟡 |
| 2.20 | Inteligencia geográfica embebida en el dashboard (KPIs + mapa + ranking) | `core/geo_engine.geographic_summary` + `visualization/charts.geo_summary_map` · render líneas 1173-1202 | ver sección 6 (georreferenciación) | 🔴 |
| 2.21 | Relación entre métricas (dispersión) + mapa de correlaciones | `visualization/charts.scatter/correlation` · render líneas 1205-1214 | requiere ≥2 y ≥3 métricas respectivamente | 🟡 |
| 2.22 | Tabla de detalle por dimensión (Total/Promedio/Registros) | `ui/dashboard.py:1216+` (`df.groupby(...).agg(...)`) | — | 🟢 |
| 2.23 | Botón "Analizar perfil individual" embebido en el dashboard/ejecutivo | `ui/dashboard.py:830-843`, `ui/executive.py:16-30` → abre `ui/person_profile.render_person_profile` inline (sin `st.switch_page`) | `session_state.show_profile_inline` | 🟡 |
| 2.24 | "3 gráficos que importan" (vista ejecutiva compacta) | `ui/executive.py:49-70` | `core/universal_analysis.smart_chart_questions` | 🟡 |
| 2.25 | Lectura analítica lateral (panel derecho, vista ejecutiva) | `ui/executive.py:72-80` | `dashboard["insights"]` | 🟢 |
| 2.26 | Vista "Descripción" (modo Analista) — dashboard completo sin recorte ejecutivo | `ui/dashboard.render_dashboard` vía `app.py:855` | igual que toda la sección 2 | 🔴 |
| 2.27 | Vista "Trabajo y decisiones" (modo Analista) | `app.py:865-873` (lista simple de insights) | `dashboard["insights"]` | 🟢 |
| 2.28 | Vista "Finanzas" (modo Analista, tabla de estadísticas) | `app.py:861-864` → `dashboard["statistics"]` (`core/statistics.describe`) | — | 🟢 |

## 3. Catálogo (modo "catalog"/"reference")

| # | Funcionalidad | Implementación | Depende de | Riesgo |
|---|---|---|---|---|
| 3.1 | Detección automática de catálogo/tabla de referencia | `core/dataset_classifier.classify_dataset` → `mode_info["mode"] in {"catalog","reference"}` | cambia el set de tabs en `app.py:798-818` | 🔴 |
| 3.2 | Búsqueda libre + filtros por categoría (hasta 6) | `ui/catalog.render_catalog` líneas 70-90 | `schema["categorical"]` | 🟡 |
| 3.3 | Tarjetas de producto/plan (título, subtítulo, precio, bullets) | `ui/catalog.py:52-136` (`_pick_title/_pick_price/_text_columns/_split_points`) | heurísticas por nombre de columna y tipo semántico | 🟡 |
| 3.4 | Métricas rápidas (elementos disponibles, precio min/max) | `ui/catalog.py:92-100` | — | 🟢 |
| 3.5 | Visualización rápida (ranking o histograma) si hay métrica | `ui/catalog.py:143-154` | `visualization/charts.ranking/histogram` | 🟢 |
| 3.6 | Tabla completa expandible | `ui/catalog.py:156-157` | — | 🟢 |

## 4. Perfil individual dedicado

| # | Funcionalidad | Implementación | Depende de | Riesgo |
|---|---|---|---|---|
| 4.1 | Selección de persona (detecta columna de identidad con heurística amplia) | `ui/person_profile._person_col` | `schema["full_name"]`, `semantic_map`, alias de nombre de columna | 🔴 |
| 4.2 | Aplica los filtros globales activos (fecha + categóricos) antes de listar personas | `ui/person_profile._apply_current_filters` | `session_state.filters` | 🔴 |
| 4.3 | KPIs de la persona (registros, total/promedio, máximo) | `ui/person_profile.py:117-128` | `core/numeric.numeric_series`, `core/universal_analysis.ADDITIVE` | 🟡 |
| 4.4 | Evolución temporal de la persona + lectura ("mejoró/empeoró X%") | `ui/person_profile.py:130-147` | `core/universal_analysis.period_series` | 🔴 |
| 4.5 | Desglose por dimensión que más explica el resultado | `ui/person_profile.py:149-172` | prioridad semántica (product > category > channel...) | 🟡 |
| 4.6 | Persona vs. promedio visible (benchmark) | `ui/person_profile.py:174-186` | — | 🟢 |
| 4.7 | Tabla "todo lo relacionado con la persona" (metadatos por columna) | `ui/person_profile.py:188-207` | distingue fechas/métricas/categóricas | 🟢 |
| 4.8 | Registros originales de la persona (expandible, hasta 500) | `ui/person_profile.py:209-213` | — | 🟢 |
| 4.9 | Acceso: botón dentro de Ejecutivo (`ui/executive.py`) y dentro de Descripción/Dashboard (`ui/dashboard.py`) | ver 2.23 | — | — |

## 5. Comparar personas (A vs. B) — pestaña "⚔️ Comparar personas"

| # | Funcionalidad | Implementación | Depende de | Riesgo |
|---|---|---|---|---|
| 5.1 | Solo aparece si hay identidad detectable (`profile_enabled`) | `app.py:792-794,823,833,846,857` | `schema["full_name"]` | 🔴 |
| 5.2 | Selección de métrica preferida + persona A / persona B | `ui/person_compare.py:31-38` | `core/universal_analysis.semantic_map` | 🟡 |
| 5.3 | KPIs A, B, diferencia, "mejor resultado" | `ui/person_compare.py:45-46` | `core/numeric.numeric_series` | 🟡 |
| 5.4 | 5 tipos de gráfico comparativo (barras, líneas, apiladas, 100%, radar) | `ui/person_compare.py:48-79` | requiere fecha para líneas/radar por periodo | 🔴 |
| 5.5 | "Qué explica la diferencia" (tabla por dimensión, top 5 cada uno) | `ui/person_compare.py:82-98` | prioridad de tipos semánticos (product/category/channel/brand/segment/city/region) | 🟡 |

## 6. Georreferenciación (condicional)

| # | Funcionalidad | Implementación | Depende de | Riesgo |
|---|---|---|---|---|
| 6.1 | Habilitación condicional (solo si hay geografía utilizable) | `core/geo_engine.supports_georeferencing` → `geo_enabled` en `app.py:775`, controla tab en 801,809,824,834,847,858 | coordenadas válidas o ciudad/región/país | 🔴 |
| 6.2 | Mapa interactivo con clic en punto (detalle de ubicación) | `ui/georeferencing.py:66-338` (`_map_figure`, `_map_figure_3d`, `_selection_label`) | `plotly` `customdata` para recuperar la ubicación correcta al hacer clic | 🔴 — bug histórico ya corregido (V40/V44); no perder el uso de `customdata`. |
| 6.3 | Geocodificación de ciudad/región/país con respaldos sin conexión | `core/geo_engine.geocode_place/_known_region_location/_fallback_place` | `geopy` (opcional/online) + tabla de respaldo local | 🔴 |
| 6.4 | Límite de ubicaciones nuevas a geocodificar (evita bloqueos) | `core/geo_engine.enrich_geography(max_places=40)` | — | 🟡 |
| 6.5 | Escala visual por nivel de desempeño (alto/medio/bajo) | `ui/georeferencing._performance_class` | — | 🟢 |
| 6.6 | Detalle de ubicación: zona vs. promedio de otras zonas, evolución temporal, ranking de agentes, composición por categoría | `ui/georeferencing._detail_panel` (línea 376-533) | `core/numeric`, `core/universal_analysis` | 🔴 |
| 6.7 | Comparar dos zonas directamente | `ui/georeferencing.render_georeferencing` (usa `_detail_panel` con selección doble) | — | 🟡 |
| 6.8 | Registros originales de la ubicación (auditoría) | dentro de `_detail_panel` | — | 🟢 |
| 6.9 | Mini-mapa + KPIs embebidos dentro del dashboard principal | ver 2.20 | — | 🔴 |
| 6.10 | Mapa por país cuando solo hay país (sin ciudad) | `core/geo_engine.geographic_summary` (mode `country_geocoding`) | — | 🟡 |

## 7. Asistente IA

| # | Funcionalidad | Implementación | Depende de | Riesgo |
|---|---|---|---|---|
| 7.1 | Chat con historial por sesión, se reinicia al cambiar de hoja/archivo | `ui/assistant.py:14-21` | `session_state.assistant_messages`, `assistant_context_key` | 🟡 |
| 7.2 | Preguntas sugeridas (3 botones) | `ui/assistant.py:27-35` | — | 🟢 |
| 7.3 | Respuesta con IA (OpenAI, opcional) o modo local limitado sin API key | `core/assistant_engine.ask_assistant` (+ `_fallback`, `execute_tool`) | `openai` (opcional), API key en `session_state.assistant_api_key` | 🔴 — degradación explícita a modo local si no hay key; no debe quedar sin ese fallback. |
| 7.4 | Configuración de API key y modelo (sidebar Y dentro de la pestaña) | `app.py:624-628`, `ui/assistant.py:55-61` | `session_state.assistant_api_key/assistant_model` (duplicado en dos lugares — mismo estado, no hay conflicto pero sí redundancia de UI) | 🟢 |
| 7.5 | Limpiar conversación | `ui/assistant.py:59-61` | — | 🟢 |
| 7.6 | Modo Práctico: preguntas sugeridas + respuesta directa (`core/query_engine`) | `ui/practical.py` → `core/query_engine.answer_question/suggest_questions` | motor de reglas independiente del asistente IA (no usa OpenAI por defecto) | 🟡 |

## 8. Datos, calidad y anomalías

| # | Funcionalidad | Implementación | Depende de | Riesgo |
|---|---|---|---|---|
| 8.1 | Tabla de datos visibles (hasta 10.000 filas) | `ui/data_table.render_data_table` | — | 🟢 |
| 8.2 | Calidad de datos (score, completitud, consistencia, duplicados) | `core/quality.assess` · render `ui/quality.render_quality` | — | 🟡 |
| 8.3 | Log de limpieza automática ("cambios realizados") | `core/cleaner.clean` → `profile["cleaning_log"]` · render `ui/quality.py:22-24` | — | 🟢 |
| 8.4 | Relaciones detectadas entre hojas | `core/relationships.detect_relationships` · render `ui/quality.py:25-27` | — | 🟡 |
| 8.5 | Anomalías (valores atípicos) | `core/anomalies.detect` · render `ui/anomalies.render_anomalies` | — | 🟡 |
| 8.6 | Explorador libre (dimensión X / métrica Y, agregados sum/mean/count) | `ui/explorer.render_explorer` | — | 🟢 |

## 9. Comparación de archivos/periodos

| # | Funcionalidad | Implementación | Depende de | Riesgo |
|---|---|---|---|---|
| 9.1 | Carga de 2+ archivos a comparar (sidebar → Herramientas avanzadas) | `app.py:637-663` | `core/comparison_engine.prepare_comparison/build_comparison` | 🔴 |
| 9.2 | Emparejamiento automático de columnas equivalentes entre archivos | `core/comparison_engine._match_columns` (usa `difflib.SequenceMatcher` + heurística semántica) | — | 🔴 |
| 9.3 | Orden cronológico automático cuando todos los archivos tienen fecha | `core/comparison_engine._period_label` / `prepare_comparison` | — | 🟡 |
| 9.4 | KPIs de cambio (actual, variación %, dirección) | `ui/comparison.py:86-92` | protegido contra base cero (`_pct_change`) | 🔴 |
| 9.5 | Lectura ejecutiva de señales comparativas | `core/comparison_engine.build_comparison` (`signals`) · render `ui/comparison.py:94-98` | — | 🟡 |
| 9.6 | Tabs: Resumen / Ganadores y caídas / Evolución / Registros / Variables comparables | `ui/comparison.render_comparison:100-163` | — | 🟡 |
| 9.7 | Filtro conjunto sobre todos los archivos comparados (por dimensión equivalente) | `ui/comparison._render_filter_panel` → `core/comparison_engine.dimension_filter_options/apply_dimension_filters` | recalcula `build_comparison` al aplicar | 🔴 |
| 9.8 | Descarga de registros combinados (CSV) | `ui/comparison.py:143-156` → `core/comparison_engine.combined_records_table` | — | 🟢 |
| 9.9 | Informe HTML de la comparación | `ui/comparison.py:166-182` → `ui/report_html.build_comparison_html_report` | — | 🟡 |
| 9.10 | Vista de bienvenida cuando no hay Excel principal pero sí comparación lista | `app.py:716-719` | — | 🟢 |

## 10. Análisis de seguimiento (multi-Excel por funcionario)

| # | Funcionalidad | Implementación | Depende de | Riesgo |
|---|---|---|---|---|
| 10.1 | Ingesta de archivos nuevos + cruce por ID o nombre | `app.py:671-710` → `core/tracking_engine.ingest_file/sources_to_long/merge_long` | detecta columna de ID/nombre; omite archivos sin columna reconocible (con warning) | 🔴 |
| 10.2 | Persistencia opcional en base de datos compartida (todo el equipo ve lo mismo) | `core/db_engine.is_configured/load_from_db/save_to_db` | requiere `SQLAlchemy`+`psycopg2` y conexión configurada; si no, cae a modo manual (subir consolidado) | 🔴 |
| 10.3 | Historial consolidado descargable/reutilizable (modo sin BD) | `core/tracking_engine.export_consolidated/read_consolidated` · `ui/tracking._download_consolidated_button` | — | 🟡 |
| 10.4 | Vista Empleado: perfil consolidado por funcionario, ubicaciones, métricas, proyección | `ui/tracking._render_employee_view` → `core/tracking_engine.person_profile/project_metric` | badge de confianza del cruce (ID vs. nombre) | 🔴 |
| 10.5 | Proyección de desempeño a una fecha objetivo (regresión simple, con confianza) | `core/tracking_engine.project_metric` | requiere ≥3 puntos para proyección con confianza | 🟡 |
| 10.6 | Vista Supervisor: equipo a cargo + detalle de un funcionario del equipo | `ui/tracking._render_supervisor_view` → `core/tracking_engine.supervisor_directory/team_roster` | — | 🟡 |
| 10.7 | Registros originales por persona (auditoría) | `ui/tracking.py:128-132` | — | 🟢 |
| 10.8 | Vista de bienvenida cuando no hay Excel principal pero sí seguimiento cargado | `app.py:720-722` | — | 🟢 |

## 11. Exportación / Informes HTML

| # | Funcionalidad | Implementación | Depende de | Riesgo |
|---|---|---|---|---|
| 11.1 | Descarga CSV de los datos filtrados | `ui/exports.py:54,79` | — | 🟢 |
| 11.2 | Descarga Excel (datos + estadística + insights) | `ui/exports.py:55-66,80` | `openpyxl` | 🟢 |
| 11.3 | Descarga resumen ejecutivo en texto plano | `ui/exports.py:68-81` | — | 🟢 |
| 11.4 | Informe HTML "según tus filtros actuales" | `ui/exports.py:93-123` → `ui/report_html.build_html_report` | refleja exactamente `session_state.filters` | 🔴 |
| 11.5 | Informe HTML interactivo (filtros funcionan dentro del HTML, sin la app) | `ui/exports.py:129-147` → `ui/interactive_report.build_interactive_html_report` | incrusta hasta 20.000 filas + Plotly bundle | 🔴 |
| 11.6 | Informe HTML individual por hoja (selector de hoja, sin filtros) | `ui/exports.py:149-192` → `ui/report_html.build_html_report` | recorre `workbook["sheets"]` | 🟡 |
| 11.7 | Informe HTML general de todo el Excel (todas las hojas) | `ui/exports.py:194-221` → `ui/report_html.build_workbook_html_report` | `core/geo_engine`, `core/quality`, etc. por cada hoja | 🔴 |
| 11.8 | Resumen de filtros activos incrustado en cada informe | `ui/exports._active_filters_summary` | — | 🟢 |

## 12. Estado de sesión (Streamlit) — mapa de claves relevantes

Inicializadas en `app.py:44-49,401-435` salvo que se indique otra cosa:
`view_mode`, `app_started`, `theme_mode`, `authenticated`, `auth_user`, `workbook`, `filters`,
`comparison_result`, `comparison_error`, `comparison_raw_files`, `comparison_filters`,
`tracking_data`, `tracking_error`, `practico_workbook`, `practico_chat`, `analysis_mode`,
`focus_dimension`, `focus_metric`, `focus_view`, `active_sheet`, `assistant_messages`,
`assistant_context_key`, `assistant_api_key`, `assistant_model`, `show_profile_inline`,
`show_individual_comparison_v47`. Riesgo 🔴 transversal: están dispersas por todo `app.py` en vez
de un solo inicializador — fácil olvidar una al tocar el flujo de arranque (ver auditoría, punto 4
de la propuesta de refactor).

## 13. Light Mode / Dark Mode — checklist específico

- El toggle (`ui/theme.py` NO se usa; el real es `app.py:44-49,56-103,460-469`) debe seguir
  cambiando `session_state.theme_mode` y disparando `st.rerun()`.
- Todo color debe seguir viniendo de las variables CSS (`--bg`, `--text`, `--panel`, etc.)
  definidas en ese bloque — **no** hardcodear colores nuevos en `ui/*.py` fuera de esas variables,
  eso rompería el modo oscuro silenciosamente.
- `ui/login.py` y `ui/landing.py` y `ui/mode_choice.py` inyectan `<style>` propios que **asumen**
  las variables ya definidas por `app.py` (se cargan antes del gate de login/landing). Si se
  reordena el flujo de arranque, verificar que el CSS de `app.py` se siga inyectando primero.
- `assets/style.css.css` es 100% oscuro y con `!important` — **no conectarlo** sin antes adaptarlo
  a variables de tema, o Light Mode se rompe apenas se cargue.

---

## Puntos de regresión más probables al rediseñar

1. **Claves de `session_state` sin renombrar**: muchas funciones de `ui/*.py` referencian claves
   por nombre literal (`show_profile_inline`, `individual_compare_*_v47`, `filters`, etc.). Un
   rediseño que reestructure componentes debe conservar estos nombres o actualizar todas las
   referencias a la vez.
2. **Gating por capacidades** (`geo_enabled`, `profile_enabled`, `mode_info["mode"]`,
   `classification`) decide qué pestañas existen. Si el rediseño cambia cómo se arma `tab_names`
   en `app.py`, hay que preservar exactamente esas condiciones.
3. **`_person_profile` (dashboard.py) vs. `render_person_profile` (person_profile.py)**: dos
   caminos para lo "mismo"; un rediseño de uno solo puede dejar al otro con estilo/comportamiento
   inconsistente.
4. **Helpers de formato duplicados** (`_fmt`, `_label`, ~10 copias): si el rediseño cambia el
   formato numérico en un archivo, hay que replicarlo manualmente en el resto o quedan
   inconsistentes.
5. **`assets/style.css.css` y `ui/theme.py`**: no conectarlos como "atajo" de estilos nuevos sin
   fusionarlos primero con el sistema real de `app.py` — repetido aquí porque es la causa más
   probable de romper Light/Dark Mode.
6. **`BYPASS_AUTH_TEMPORARY`**: si el rediseño toca `ui/login.py`, no eliminar el flag sin
   coordinarlo — hoy es la única razón por la que el login no está roto por la conexión de BD caída.

---

## 14. Actualización — QA final (Tarea 20)

Cierre del rediseño (tareas 00–19). Lo que cambió respecto a esta auditoría original y sigue
vigente hoy:

- **Sistema de tema centralizado**: el bloque `<style>` que antes vivía inline en `app.py` (punto
  0.8 y sección 13 arriba) ahora es `ui/styles/theme.py:inject_theme(dark)`, llamado una sola vez
  desde `app.py`. Los huérfanos que esta auditoría marcaba como riesgo — `ui/theme.py` y
  `assets/style.css.css` — **ya no existen** (eliminados en la tarea 03); no hay ni hubo un
  "cuarto sistema" de estilos.
- **Componentes y layouts extraídos**: `ui/components/{cards,charts,section}.py` (tarjetas KPI,
  insight, chart_card, section_header) y `ui/layouts/{columns,hero,tabs}.py` (`two_column`,
  `kpi_grid`, `hero`, `grouped_nav`/`named_tabs`) son ahora la forma estándar de construir
  presentación en toda la app; los números de línea citados en las secciones 0–11 de arriba
  corresponden a la auditoría original y ya no son exactos tras la extracción — la descripción
  funcional y el módulo donde vive cada pieza sí se mantienen vigentes.
- **`ui/alerts.py` eliminado** (tarea 20): módulo huérfano ya señalado en la auditoría original
  (nunca se importaba desde ningún otro archivo) y con un import roto (`from ui.components import
  card_kpi, section_header` — `card_kpi` nunca existió con ese nombre; el equivalente real es
  `kpi_card` en `ui/components/cards.py`). Confirmado sin referencias en todo el proyecto antes de
  borrarlo.
- **CSS muerto eliminado** (tarea 20): `.smart-grid` en `ui/styles/theme.py` no tenía ningún
  consumidor en `ui/*.py` (confirmado dos veces, en la auditoría original y de nuevo aquí).
- **2 inconsistencias de Dark Mode encontradas y corregidas** (tarea 20, no detectadas por el
  barrido de la tarea 04): `ui/tracking.py:_confidence_badge` traía los colores del badge de
  confianza (`#189a63`/`#e7f7ef`, `#c8790a`/`#fdf2e2`) escritos como hex literal en vez de
  `var(--green)`/`var(--green-soft)` y `var(--amber)`/`var(--amber-soft)` — visualmente idéntico en
  Light Mode, pero se quedaba fijo en colores claros dentro de un panel oscuro en Dark Mode.
  `ui/mode_choice.py`'s `.mode-card.avanzado .mode-card-icon` tenía el mismo problema
  (`#eef1fb`/`#3b4a8f` fijos, mientras su tarjeta hermana `.practico` ya usaba
  `var(--blue-soft)`/`var(--blue)`) — corregido con `var(--purple-soft)`/`var(--purple)` (tokens ya
  definidos en `_theme_vars()` pero sin ningún uso hasta ahora).
- **`ui/login.py` fuerza un fondo crema fijo con `!important`** sobre `body`/`stAppViewContainer`,
  ignorando `theme_mode` — revisado y confirmado **intencional**, no un bug: sus propios textos
  (`.login-hero h1/p`) usan grises fijos coherentes con ese mismo fondo fijo, nunca `var(--text)`;
  es una pantalla de splash con identidad de marca propia, igual que el panel `.landing-how` (fondo
  `#0d1119` fijo, literal, deliberadamente desacoplado de cualquier token de tema — ver el punto
  siguiente). El toggle de tema solo es visible dentro de la app ya autenticada, así que esta
  pantalla nunca necesita reaccionar a él.
- **El sidebar ya no es "siempre oscuro"** (corrección posterior a esta misma tarea de QA, a
  pedido explícito del usuario): `--sidebar-bg/--sidebar-panel/--sidebar-line/--sidebar-text/
  --sidebar-muted` pasaron de ser valores fijos a variar con `dark` igual que el resto de la
  paleta (nuevo helper `_sidebar_vars(dark)` en `ui/styles/theme.py`, más un token nuevo
  `--sidebar-text-strong` para los pocos elementos —encabezados, inputs— que antes usaban blanco
  fijo). Efecto colateral detectado y corregido en el mismo cambio: `ui/landing.py`'s
  `.landing-how` reutilizaba `var(--sidebar-bg)` únicamente porque era un valor oscuro fijo
  conveniente, con hijos de texto blanco fijo — al volverse `--sidebar-bg` reactivo al tema, ese
  panel se habría vuelto ilegible en Light Mode; se desacopló dándole su propio literal
  `#0d1119`, preservando su apariencia exacta en ambos modos (siempre fue, y sigue siendo, un
  panel oscuro fijo, ahora ya no accidentalmente atado al sidebar).
- **`BYPASS_AUTH_TEMPORARY` sigue en `True`** ([ui/login.py:17](ui/login.py#L17)) — sin cambios,
  fuera de alcance de esta tarea, tal como advierte el punto 6 de arriba.
- **Barrido de claves de widget (`key=`) en todo el proyecto**: sin colisiones reales. Las dos
  únicas claves repetidas textualmente (`explorer_trend`, `explorer_ranking` en
  `ui/explorer.py`) están en ramas `if/elif` mutuamente excluyentes — nunca se instancian dos veces
  en la misma ejecución.
- **CSS "duplicado" entre `ui/styles/theme.py` y `ui/report_html.py`/`ui/interactive_report.py`**
  (mismos nombres de clase: `.kpi-card`, `.chart-card`, `.hero`, etc.): no es duplicación real —
  son dos documentos HTML independientes (la app viva vs. los informes HTML descargables,
  explícitamente fuera de alcance) que nunca comparten DOM.
