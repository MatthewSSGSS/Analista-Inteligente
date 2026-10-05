# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Streamlit app ("Panel Analítico Universal") that turns an uploaded Excel/CSV workbook into an
interactive analytics dashboard — KPIs, findings, alerts, comparisons, forecasting, georeferencing,
OCR of embedded images, executive reports — without assuming any fixed schema (sales, HR,
inventory, catalogs, etc. all work through the same engine). All code, comments and UI copy are in
Spanish; keep new code consistent with that.

There is deliberately **one single `app.py`** at the repo root. Do not create a second entry point.

## Running the app

```powershell
pip install -r requirements.txt
streamlit run app.py
```

`packages.txt` lists apt packages needed on Linux/Streamlit Cloud (`libgl1`, `libglib2.0-0`) for the
OCR dependency (`rapidocr_onnxruntime`) — irrelevant on Windows dev machines.

## Tests

There is no pytest/unittest runner — every file in `tests/` is a standalone script with a `main()`
that calls a local `check(label, condition)` helper (raises `AssertionError` on failure, prints `OK`
on success). Run one directly:

```powershell
python tests/smoke_test.py
python tests/filtros_test.py
```

or with explicit path setup (needed if imports fail):

```bash
PYTHONPATH=. python tests/smoke_test.py
```

To run everything, iterate over `tests/*_test.py` — there is no single aggregate command. Some
tests self-skip when an optional dependency is missing (e.g. `imagen_ocr_test.py` skips without
RapidOCR). `tests/smoke_test.py` is the broadest sanity check (load → profile → dashboard → charts
→ comparison). Each test file's module docstring documents the specific bug/regression it exists
to catch — read it before changing the code it covers, since these tests encode hard-won behavior
(zero-base growth, missing-vs-zero semantics, month-column ordering, etc.).

## Architecture

Three layers, strictly separated (see `DESIGN.md` for the full rationale):

```
core/            Data engine: load, profile, semantic schema detection, filters, KPIs,
                 insights, alerts, comparison, geography, forecasting, tracking, auth.
                 No Streamlit dependency except auth_engine.py/db_engine.py (st.secrets only).
visualization/   Plotly chart engine (charts.py) + chart type selector (chart_selector.py).
                 Reused by all of ui/. No business logic.
ui/              Presentation only, layered further (see below).
app.py           Orchestrator/router only: session bootstrap, login gate, sidebar
                 (upload + filters + tools), tab selection based on detected capabilities.
                 No business logic, minimal inline HTML/CSS.
```

Inside `ui/`:
- `ui/styles/theme.py` — the **only** source of injected `<style>`/theme tokens (light/dark). Never
  add a second theme system; a view-local `<style>` block may only *add* classes on top of these
  tokens, never redefine `:root` colors.
- `ui/components/` — pure, reusable render helpers (`cards.py`, `charts.py`, `section.py`, `descarga.py` →
  `preparar_y_descargar`, the two-step «Preparar → Descargar» used by Exportar and Territorial). No
  business logic, no reading `core/` directly, no reading business `session_state` keys.
- `ui/layouts/` — reusable page structures (`hero.py`, `tabs.py` → `barra_de_vistas`/`ir_a`, `columns.py`).
  Top-level navigation is `barra_de_vistas(principales, secundarias)`: a sticky bar with the daily views plus a
  «➕ Más» menu, and **only the active view is executed** (unlike `st.tabs`, which ran every tab on every
  rerun). Consequence: Streamlit drops the state of widgets that weren't drawn, so anything that must survive
  switching views has to be mirrored outside the widget (see `ui/planes.py::_pasos_guardados`).
- `ui/format.py` — the single `_fmt`/`_label`/`_compact_number` implementation; don't reintroduce
  local copies in a view.
- `ui/*.py` (the rest) — one file per screen/tab, combining `core/` + `visualization/` +
  `components/` + `layouts/`. `ui/dashboard.py` is the largest and most delicate (temporal chart
  comparison, executive panels, geo panel) and still mixes several concerns internally per
  `DESIGN.md` §5 Fase E — a documented, not-yet-executed follow-up.

Contract: `ui/*` views must not import private helpers from other `ui/*` views (import from
`core/`, `visualization/`, `ui/components/`, `ui/layouts/`, `ui/format.py` instead). `core/`
functions never receive Streamlit objects.

### Data flow (core/)

`core/loader.load_workbook` reads every sheet of the uploaded file (openpyxl/xlrd/pyxlsb depending
on extension) and calls `core/profile.profile_sheet` per sheet, which cleans the data
(`core/cleaner.py`) and calls `core/schema.detect_schema` to classify every column — dates,
metrics, categorical, text, geography, ids — including semantic typing
(`core/semantic_engine.interpret_dataframe`, e.g. `revenue` vs `quantity` vs `percentage`) and
identifier detection (`ID_RE`/`DOC_ID_RE` in `core/schema.py`, which keeps cédulas/NIT/SKU out of
numeric aggregation even when they repeat). `core/gerencia.analisis_gerencial` adds the sales-manager reading on top of the diagnostics: root cause of the
change across every groupable column (two levels, e.g. region → channel), volume-vs-ticket lever, and
opportunities valued in money. It is computed once inside `build_dashboard` (`dashboard["gerencia"]`) and
reused by the plans, alerts, Resumen, «🎯 Qué atacar» and the HTML reports; `tests/gerencia_test.py`.

The resulting `{df, schema}` (called `item["processed"]`
/ `item["profile"]`) feeds `core/dashboard_engine.build_dashboard`, which is the expensive
aggregate step (KPIs, insights, alerts, anomalies, performance, growth) and is wrapped in
`st.cache_data` in `app.py` because Streamlit reruns the whole script on every interaction.

The mode-choice screen (`ui/mode_choice.py`) offers three routes: **Análisis Completo** (the main
panel above; `analysis_mode == "completo"`, the default path with no `if` of its own),
**Territorial** (`ui/territorial.py`, geography-first view: 3D pydeck map — columns per municipio,
extruded departments, hexagons, heatmap, points — colored by volume/variation/goal/penetration, laid out as a three-column console — layer panel ·
HUD + map · reading rail with selected zone, Top 10 and alerts — with zone detail on click (fly-to + highlight),
a green/amber/red traffic light by default and «why it rose/fell» per zone (`core/territorio.motivos`; a
half-loaded last month is compared against the previous month cut at the same day, `corte_dia`), downloadable
Excel/HTML reports (`ui/report_territorial.py`, both built from `core/territorio.informe`, the same dict the
on-screen traffic-light board uses), a «🎯 Plan de acción» turning the diagnosis into decisions
(`core/territorio_plan.plan`: per-zone strategy Rescatar/Recuperar/Desarrollar/Replicar/Sostener valued per month,
«las jugadas del mes» ranked by expected value, a playbook per sales agent when the file has an asesor/vendedor/agente
column, lost clients to visit, and «Dónde abrir» with the nearest base zone; also in the Excel/HTML reports),
numbered plan pins, expansion arcs, a rich hover tooltip on every pickable layer (Streamlit escapes tooltip field
values, so all HTML/styling lives in the `_tooltip` template and fields carry plain text/colors) and a «🎬 Modo
presentación» that flies through the plan's plays, timeline playback and «Dónde crecer»; the engine is
`core/territorio.py` over the bundled Colombia data in `assets/geo/`: DIVIPOLA's 1,122 municipios
with coordinates and DANE 2026 population, plus the 33 department polygons) and **Seguimiento de Logística**
(`ui/logistica.py`, `analysis_mode == "logistica"`; still a scaffold — upload + data preview — whose
analysis is being defined incrementally). Territorial and Logística run as standalone full-screen
pages, stopping the main script with `st.stop()`, each with its own file uploader and
`session_state` keys (`territorial_*`, `logistica_*`) so they don't collide with the main workbook
state. A former third route, **Práctico**
(quick summary + Q&A), was removed as redundant with the main panel's «Pregúntale al Excel» and
Asistente IA; `app.py` maps any stale `analysis_mode` value to `"completo"`.

### Filters

One filter engine only: `core/filter_engine.apply_filters`/`cascading_options`. It is shared by the
sidebar, the tracking/seguimiento cross-file matching, and export summaries — do not add a
parallel filtering path. `apply_filters` returns a single DataFrame (not a tuple); unpacking it as
`df, meta = apply_filters(...)` is a regression `tests/filtros_test.py` guards against.

### Domain rule: comparisons reference the full group

When comparing a subset of elements (e.g. 3 of 30 people, top-N of a ranking), any reference value
— average, participation %, rank/position, group compliance — must be computed over the **full
visible group** (all values of that dimension under the current sidebar filters), never over just
the selected subset. The selection only decides what's *displayed*; state the group size on screen
(e.g. "promedio de los 30", "5.º de 30"). This applies to `ui/cuadro_comparativo.py`,
`ui/person_compare.py`, ranking/top-N views, and any new comparison feature.

### Known gotchas worth knowing before touching related code

- `ui/login.py` has `BYPASS_AUTH_TEMPORARY = True` — login currently passes through without
  validating a real password against the DB, and signup is disabled while this flag is on. Don't
  "fix" this silently; it's a deliberate temporary product decision.
- `core/version.py` reads `.git/HEAD` directly (no `git` subprocess) to show which commit is
  actually deployed, because Streamlit Cloud deploys had silently served stale code before.
- Missing values in numeric columns are treated as 0 for normal sheets, but **not** for
  report-style tables read via `core/informe.py` (`faltantes_son_cero=False`) — there, a blank
  month means "not yet reported," not zero, otherwise variance calculations show false 100% drops.
- `FEATURES.md` is a regression checklist generated from an audit — each row names the file/function
  implementing a behavior and the specific real-world failure it prevents. Check it before
  refactoring anything it lists, especially items marked 🔴.
