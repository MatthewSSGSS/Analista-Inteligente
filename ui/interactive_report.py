"""Informe HTML "interactivo": a diferencia de los otros 3 tipos (que son una
foto fija de lo que estaba filtrado al momento de exportar), este lleva los
datos completos metidos adentro y los filtros funcionan de verdad dentro del
archivo ya abierto — sin necesitar la app ni internet.

Sigue el mismo principio universal del resto del proyecto: qué métrica,
dimensiones y columna de nombre usar se decide analizando el esquema
semántico de cada archivo, nunca column names hardcodeados.
"""
from __future__ import annotations

import html
import json
from datetime import datetime

import numpy as np
import pandas as pd

from core.universal_analysis import ADDITIVE, semantic_map, choose_metric
from visualization.charts import metric_candidates, dimension_candidates, _label

MAX_ROWS = 20000


def _esc(value) -> str:
    return html.escape(str(value))


def _slug(text: str) -> str:
    import re as _re
    return _re.sub(r"[^a-zA-Z0-9]+", "_", str(text)).strip("_").lower() or "col"


def _pick_search_column(df: pd.DataFrame, schema: dict, dims: list[str]) -> str | None:
    full_name = (schema.get("full_name") or {}).get("column")
    if full_name and full_name in df.columns:
        return full_name
    sem = semantic_map(schema)
    for c in dims:
        if sem.get(c) in {"name", "customer", "employee"}:
            return c
    # Si no hay ninguna columna claramente "de persona", usa la dimensión de
    # mayor cardinalidad (la más parecida a un identificador individual).
    if dims:
        return max(dims, key=lambda c: df[c].nunique(dropna=True))
    return None


def _plotly_js_bundle() -> str:
    """Extrae el bundle de Plotly.js para incrustarlo dentro del HTML, igual
    que el resto de informes del proyecto — así este archivo también abre
    sin internet, sin depender de un CDN externo. to_html() con
    include_plotlyjs='inline' genera VARIOS bloques <script> (config, la
    librería completa, el render del gráfico); se necesita el más grande
    (la librería), no el primero que aparezca.
    """
    import re
    import plotly.graph_objects as go
    snippet = go.Figure().to_html(full_html=False, include_plotlyjs="inline")
    blocks = re.findall(r"<script[^>]*>(.*?)</script>", snippet, re.S)
    return max(blocks, key=len) if blocks else ""


def build_interactive_html_report(df: pd.DataFrame, schema: dict, filename: str, sheet: str) -> str:
    metrics = metric_candidates(df, schema)
    dims = dimension_candidates(df, schema)
    dates = [d for d in schema.get("dates", []) if d in df.columns]
    sem = semantic_map(schema)

    metric = choose_metric(df, schema)
    additive = sem.get(metric) in ADDITIVE if metric else True
    date_col = dates[0] if dates else None
    search_col = _pick_search_column(df, schema, dims)
    filter_dims = [d for d in dims if d != search_col][:4]
    dist_dim = filter_dims[0] if filter_dims else (dims[0] if dims and dims[0] != search_col else None)

    # Columnas realmente necesarias en el HTML: no se exporta el archivo
    # completo con columnas irrelevantes, solo lo que el informe usa.
    needed_cols = list(dict.fromkeys(
        ([search_col] if search_col else [])
        + filter_dims
        + ([date_col] if date_col else [])
        + ([metric] if metric else [])
    ))
    payload_df = df[needed_cols].copy() if needed_cols else df.copy()
    truncated = len(payload_df) > MAX_ROWS
    if truncated:
        payload_df = payload_df.head(MAX_ROWS)
    if date_col and date_col in payload_df.columns:
        payload_df[date_col] = pd.to_datetime(payload_df[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
    if metric and metric in payload_df.columns:
        payload_df[metric] = pd.to_numeric(payload_df[metric], errors="coerce")
    records_json = payload_df.to_json(orient="records", force_ascii=False)

    filter_selects = "".join(
        f"""<div class="filter-field"><label>{_esc(_label(schema, d))}</label>
        <select id="filter_{_slug(d)}" data-col="{_esc(d)}"><option value="__all__">Todos</option></select></div>"""
        for d in filter_dims
    )
    search_html = (
        f'<div class="filter-field search"><label>Buscar</label>'
        f'<input id="search_box" type="text" placeholder="Buscar {_esc(_label(schema, search_col)).lower()}..."></div>'
        if search_col else ""
    )

    metric_label = _esc(_label(schema, metric)) if metric else "Registros"
    dist_label = _esc(_label(schema, dist_dim)) if dist_dim else ""
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")

    js = f"""
const RAW = {records_json};
const METRIC = {json.dumps(metric)};
const ADDITIVE = {json.dumps(bool(additive))};
const DATE_COL = {json.dumps(date_col)};
const SEARCH_COL = {json.dumps(search_col)};
const DIST_COL = {json.dumps(dist_dim)};
const FILTER_COLS = {json.dumps(filter_dims)};
const METRIC_LABEL = {json.dumps(metric_label)};
const SEARCH_LABEL = {json.dumps(_esc(_label(schema, search_col)).lower() if search_col else "elementos")};

function fmtNumber(v) {{
  if (v === null || v === undefined || isNaN(v)) return "—";
  const x = Number(v);
  const ax = Math.abs(x);
  if (ax >= 1e9) return (x/1e9).toFixed(1) + "B";
  if (ax >= 1e6) return (x/1e6).toFixed(1) + "M";
  if (ax >= 1e3) return (x/1e3).toFixed(1) + "K";
  return x.toLocaleString("es-CO", {{maximumFractionDigits: 0}});
}}

function populateFilterOptions() {{
  FILTER_COLS.forEach(function(col) {{
    const sel = document.getElementById("filter_" + col.toLowerCase().replace(/[^a-z0-9]+/g, "_"));
    if (!sel) return;
    const values = Array.from(new Set(RAW.map(function(r) {{ return r[col]; }}).filter(function(v) {{ return v !== null && v !== undefined && v !== ""; }})));
    values.sort(function(a, b) {{ return String(a).localeCompare(String(b), "es"); }});
    values.forEach(function(v) {{
      const opt = document.createElement("option");
      opt.value = String(v);
      opt.textContent = String(v);
      sel.appendChild(opt);
    }});
  }});
}}

function currentFilters() {{
  const active = {{}};
  FILTER_COLS.forEach(function(col) {{
    const sel = document.getElementById("filter_" + col.toLowerCase().replace(/[^a-z0-9]+/g, "_"));
    if (sel && sel.value !== "__all__") active[col] = sel.value;
  }});
  const search = (document.getElementById("search_box") ? document.getElementById("search_box").value : "").trim().toLowerCase();
  return {{active: active, search: search}};
}}

function applyFilters() {{
  const {{active, search}} = currentFilters();
  return RAW.filter(function(row) {{
    for (const col in active) {{ if (String(row[col]) !== active[col]) return false; }}
    if (search && SEARCH_COL) {{
      const v = row[SEARCH_COL];
      if (!v || String(v).toLowerCase().indexOf(search) === -1) return false;
    }}
    return true;
  }});
}}

function aggregate(rows) {{
  if (!METRIC) return null;
  const vals = rows.map(function(r) {{ return Number(r[METRIC]); }}).filter(function(v) {{ return !isNaN(v); }});
  if (!vals.length) return 0;
  if (ADDITIVE) return vals.reduce(function(a,b) {{ return a+b; }}, 0);
  return vals.reduce(function(a,b) {{ return a+b; }}, 0) / vals.length;
}}

function renderKPIs(rows) {{
  document.getElementById("kpi_count").textContent = rows.length.toLocaleString("es-CO");
  if (METRIC) {{
    const total = aggregate(rows);
    document.getElementById("kpi_metric_label").textContent = (ADDITIVE ? "Total " : "Promedio ") + METRIC_LABEL;
    document.getElementById("kpi_metric").textContent = fmtNumber(total);
    const uniqueSearch = SEARCH_COL ? new Set(rows.map(function(r) {{ return r[SEARCH_COL]; }})).size : rows.length;
    document.getElementById("kpi_unique").textContent = uniqueSearch.toLocaleString("es-CO");
    const perUnit = uniqueSearch ? (aggregate(rows) / uniqueSearch) : 0;
    document.getElementById("kpi_avg").textContent = fmtNumber(perUnit);
  }}
}}

function renderNarrative(rows) {{
  const el = document.getElementById("narrative_text");
  if (!el) return;
  if (!METRIC) {{
    el.textContent = "La selección actual muestra " + rows.length.toLocaleString("es-CO") + " registros con los filtros aplicados.";
    return;
  }}
  const total = aggregate(rows);
  const uniqueSearch = SEARCH_COL ? new Set(rows.map(function(r) {{ return r[SEARCH_COL]; }})).size : null;
  let text = "Con los filtros actuales se analizan " + rows.length.toLocaleString("es-CO") + " registros";
  if (SEARCH_COL && uniqueSearch !== null) {{
    text += " (" + uniqueSearch.toLocaleString("es-CO") + " valores distintos de " + SEARCH_LABEL + ")";
  }}
  text += ", con un " + (ADDITIVE ? "total" : "promedio") + " de " + METRIC_LABEL.toLowerCase() + " de " + fmtNumber(total) + ".";
  el.textContent = text;
}}

function renderTrend(rows) {{
  const box = document.getElementById("chart_trend");
  if (!box) return;
  if (!DATE_COL || !METRIC) {{ box.closest(".chart-card").style.display = "none"; return; }}
  const byPeriod = {{}};
  rows.forEach(function(r) {{
    const d = r[DATE_COL];
    if (!d) return;
    const period = String(d).slice(0, 7);
    const v = Number(r[METRIC]);
    if (isNaN(v)) return;
    if (!byPeriod[period]) byPeriod[period] = {{sum: 0, count: 0}};
    byPeriod[period].sum += v;
    byPeriod[period].count += 1;
  }});
  const periods = Object.keys(byPeriod).sort();
  const values = periods.map(function(p) {{ return ADDITIVE ? byPeriod[p].sum : byPeriod[p].sum / byPeriod[p].count; }});
  Plotly.react(box, [{{x: periods, y: values, type: "scatter", mode: "lines+markers", line: {{color: "#e4002b", width: 3}}, marker: {{color: "#e4002b", size: 7}}}}], {{
    margin: {{l: 50, r: 20, t: 10, b: 40}}, height: 320, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: {{family: "Inter,Segoe UI,Arial,sans-serif", size: 12}}, yaxis: {{title: METRIC_LABEL}}
  }}, {{displayModeBar: false, responsive: true}});
}}

function renderDistribution(rows) {{
  const box = document.getElementById("chart_dist");
  if (!box) return;
  if (!DIST_COL || !METRIC) {{ box.closest(".chart-card").style.display = "none"; return; }}
  const byGroup = {{}};
  rows.forEach(function(r) {{
    const g = r[DIST_COL];
    if (g === null || g === undefined || g === "") return;
    const v = Number(r[METRIC]);
    if (isNaN(v)) return;
    if (!byGroup[g]) byGroup[g] = {{sum: 0, count: 0}};
    byGroup[g].sum += v;
    byGroup[g].count += 1;
  }});
  let entries = Object.keys(byGroup).map(function(g) {{ return [g, ADDITIVE ? byGroup[g].sum : byGroup[g].sum / byGroup[g].count]; }});
  entries.sort(function(a,b) {{ return b[1]-a[1]; }});
  entries = entries.slice(0, 10);
  Plotly.react(box, [{{x: entries.map(function(e) {{ return e[1]; }}), y: entries.map(function(e) {{ return e[0]; }}), type: "bar", orientation: "h", marker: {{color: "#172033"}}}}], {{
    margin: {{l: 140, r: 20, t: 10, b: 40}}, height: 320, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: {{family: "Inter,Segoe UI,Arial,sans-serif", size: 12}}, xaxis: {{title: METRIC_LABEL}}, yaxis: {{autorange: "reversed"}}
  }}, {{displayModeBar: false, responsive: true}});
}}

function renderTables(rows) {{
  if (!SEARCH_COL || !METRIC) return;
  const byName = {{}};
  rows.forEach(function(r) {{
    const n = r[SEARCH_COL];
    if (n === null || n === undefined || n === "") return;
    const v = Number(r[METRIC]);
    if (isNaN(v)) return;
    if (!byName[n]) byName[n] = {{sum: 0, count: 0, extra: {{}}}};
    byName[n].sum += v;
    byName[n].count += 1;
    FILTER_COLS.forEach(function(c) {{ if (r[c] !== undefined) byName[n].extra[c] = r[c]; }});
  }});
  let entries = Object.keys(byName).map(function(n) {{ return [n, ADDITIVE ? byName[n].sum : byName[n].sum/byName[n].count, byName[n].extra]; }});
  entries.sort(function(a,b) {{ return b[1]-a[1]; }});
  const extraCols = FILTER_COLS.slice(0, 2);
  function renderTable(el, list) {{
    let headHtml = "<tr><th>#</th><th>{_esc(_label(schema, search_col)) if search_col else "Nombre"}</th>" + extraCols.map(function(c) {{ return "<th>"+c+"</th>"; }}).join("") + "<th>" + METRIC_LABEL + "</th></tr>";
    let bodyHtml = list.map(function(e, i) {{
      return "<tr><td>"+(i+1)+"</td><td>"+e[0]+"</td>" + extraCols.map(function(c) {{ return "<td>"+(e[2][c]!==undefined?e[2][c]:"—")+"</td>"; }}).join("") + "<td>"+fmtNumber(e[1])+"</td></tr>";
    }}).join("");
    el.innerHTML = "<table><thead>"+headHtml+"</thead><tbody>"+bodyHtml+"</tbody></table>";
  }}
  renderTable(document.getElementById("table_top"), entries.slice(0, 10));
  renderTable(document.getElementById("table_bottom"), entries.slice(-10).reverse());
}}

function exportCsv() {{
  const rows = applyFilters();
  if (!rows.length) return;
  const cols = Object.keys(rows[0]);
  const lines = [cols.join(",")].concat(rows.map(function(r) {{
    return cols.map(function(c) {{ let v = r[c]; if (v === null || v === undefined) v = ""; v = String(v).replace(/"/g,'""'); return /[,"\\n]/.test(v) ? '"'+v+'"' : v; }}).join(",");
  }}));
  const blob = new Blob([lines.join("\\n")], {{type: "text/csv;charset=utf-8;"}});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "dataset_filtrado.csv";
  a.click();
}}

function renderAll() {{
  const rows = applyFilters();
  document.getElementById("result_count").textContent = rows.length.toLocaleString("es-CO") + " de " + RAW.length.toLocaleString("es-CO") + " registros";
  renderKPIs(rows);
  renderNarrative(rows);
  renderTrend(rows);
  renderDistribution(rows);
  renderTables(rows);
}}

document.addEventListener("DOMContentLoaded", function() {{
  populateFilterOptions();
  FILTER_COLS.forEach(function(col) {{
    const sel = document.getElementById("filter_" + col.toLowerCase().replace(/[^a-z0-9]+/g, "_"));
    if (sel) sel.addEventListener("change", renderAll);
  }});
  const search = document.getElementById("search_box");
  if (search) search.addEventListener("input", renderAll);
  const exportBtn = document.getElementById("export_btn");
  if (exportBtn) exportBtn.addEventListener("click", exportCsv);
  renderAll();
}});
"""

    kpi_extra = "" if metric else "style='display:none'"
    plotly_js = _plotly_js_bundle()

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Informe interactivo — {_esc(filename)}</title>
<script>{plotly_js}</script>
<style>
:root{{--bg:#f4f6fa;--card:#fff;--text:#172033;--muted:#667085;--line:#dfe4ec;--blue:#e4002b;--shadow:0 5px 18px rgba(23,32,51,.06)}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif;line-height:1.45}}
.wrap{{max-width:1280px;margin:0 auto;padding:28px 20px 60px}}
.header{{background:#fff;border:1px solid var(--line);border-top:6px solid var(--blue);border-radius:16px;padding:20px 24px;box-shadow:var(--shadow)}}
.kicker{{font-size:10px;font-weight:900;letter-spacing:.13em;color:var(--blue);text-transform:uppercase;display:flex;align-items:center;gap:8px}}
h1{{margin:6px 0 6px;font-size:22px}}
.narrative{{color:var(--muted);font-size:13px;max-width:900px}}
.filters{{display:flex;flex-wrap:wrap;align-items:end;gap:12px;background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-top:16px;box-shadow:var(--shadow)}}
.filter-field{{display:flex;flex-direction:column;gap:4px;font-size:11px;color:var(--muted);font-weight:700}}
.filter-field select,.filter-field input{{border:1px solid var(--line);border-radius:9px;padding:7px 10px;font-size:12.5px;color:var(--text);min-width:150px}}
.filter-field.search input{{min-width:200px}}
.export-btn{{margin-left:auto;background:var(--blue);color:#fff;border:none;border-radius:9px;padding:9px 16px;font-weight:700;font-size:12.5px;cursor:pointer}}
.export-btn:hover{{background:#c8001f}}
#result_count{{font-size:11px;color:var(--muted);margin-top:8px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:18px}}
.kpi{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:12px;padding:15px;box-shadow:var(--shadow)}}
.kpi-label{{font-size:10.5px;color:var(--muted);font-weight:700;text-transform:uppercase}}
.kpi-value{{font-size:22px;font-weight:800;margin-top:6px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px}}
.chart-card,.table-card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:var(--shadow)}}
.chart-card h3,.table-card h3{{margin:0 0 10px;font-size:14px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th,td{{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left}}
th{{color:var(--muted);font-size:10px;text-transform:uppercase}}
.footer{{margin-top:30px;color:#8792a3;font-size:11px;text-align:center}}
@media(max-width:900px){{.grid2{{grid-template-columns:1fr}}.filters{{flex-direction:column;align-items:stretch}}.export-btn{{margin-left:0}}}}
</style></head>
<body><div class="wrap">
<header class="header">
  <div class="kicker">🔎 Panel Analítico Universal · Informe interactivo</div>
  <h1>{_esc(filename)} · {_esc(sheet)}</h1>
  <p class="narrative" id="narrative_text">Cargando resumen…</p>
</header>

<section class="filters">
  {search_html}
  {filter_selects}
  <button class="export-btn" id="export_btn">⬇ Exportar Dataset</button>
</section>
<div id="result_count"></div>

<section class="kpis" {kpi_extra}>
  <div class="kpi"><div class="kpi-label">Registros</div><div class="kpi-value" id="kpi_count">—</div></div>
  <div class="kpi"><div class="kpi-label" id="kpi_metric_label">{metric_label}</div><div class="kpi-value" id="kpi_metric">—</div></div>
  <div class="kpi"><div class="kpi-label">{_esc(_label(schema, search_col)) if search_col else "Elementos"} únicos</div><div class="kpi-value" id="kpi_unique">—</div></div>
  <div class="kpi"><div class="kpi-label">Promedio por {(_esc(_label(schema, search_col)) if search_col else "elemento").lower()}</div><div class="kpi-value" id="kpi_avg">—</div></div>
</section>

<section class="grid2">
  <div class="chart-card"><h3>📈 Tendencia{f' · {metric_label}' if metric else ''}</h3><div id="chart_trend"></div></div>
  <div class="chart-card"><h3>📊 Distribución{f' por {dist_label}' if dist_dim else ''}</h3><div id="chart_dist"></div></div>
</section>

<section class="grid2">
  <div class="table-card"><h3>🏆 Top 10 (mayor {metric_label.lower()})</h3><div id="table_top"></div></div>
  <div class="table-card"><h3>🔻 Bottom 10 (menor {metric_label.lower()})</h3><div id="table_bottom"></div></div>
</section>

<footer class="footer">
  Generado: {_esc(generated)} · {len(payload_df):,} registros incluidos{' (archivo truncado a ' + f'{MAX_ROWS:,}' + ' filas para mantener el archivo liviano)' if truncated else ''}.
  Los filtros de arriba funcionan dentro de este archivo, sin necesitar la app.
</footer>
</div>
<script>{js}</script>
</body></html>"""
