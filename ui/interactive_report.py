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
from ui.report_base import documento

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
const METRIC_LABEL = {json.dumps(_label(schema, metric) if metric else "Registros")};
const SEARCH_LABEL = {json.dumps(_label(schema, search_col).lower() if search_col else "elementos")};
const NAME_LABEL = {json.dumps(_label(schema, search_col) if search_col else "Nombre")};

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
  let text = rows.length.toLocaleString("es-CO") + " registros con los filtros actuales";
  if (SEARCH_COL && uniqueSearch !== null) {{
    text += " (" + uniqueSearch.toLocaleString("es-CO") + " de " + SEARCH_LABEL + ")";
  }}
  text += " · " + (ADDITIVE ? "total" : "promedio") + " de " + METRIC_LABEL.toLowerCase() + ": " + fmtNumber(total) + ".";
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
  Plotly.react(box, [{{x: entries.map(function(e) {{ return e[1]; }}), y: entries.map(function(e) {{ return e[0]; }}), type: "bar", orientation: "h", marker: {{color: entries.map(function(e, i) {{ return i === 0 ? "#e4002b" : "#94a3b8"; }})}}}}], {{
    margin: {{l: 140, r: 20, t: 10, b: 40}}, height: 320, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: {{family: "Inter,Segoe UI,Arial,sans-serif", size: 12}}, xaxis: {{title: METRIC_LABEL}}, yaxis: {{autorange: "reversed"}}
  }}, {{displayModeBar: false, responsive: true}});
}}

function escHtml(v) {{
  return String(v === null || v === undefined ? "" : v).replace(/[&<>"']/g, function(c) {{
    return {{"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}}[c];
  }});
}}

function renderTables(rows) {{
  if (!SEARCH_COL || !METRIC) {{ document.getElementById("tables_row").style.display = "none"; return; }}
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
  const total = entries.length;
  // Posición y promedio sobre TODOS los visibles con los filtros, no solo
  // sobre los 10 que se muestran.
  const avg = total ? entries.reduce(function(a, e) {{ return a + e[1]; }}, 0) / total : 0;
  const maxAbs = entries.reduce(function(m, e) {{ return Math.max(m, Math.abs(e[1])); }}, 0) || 1;
  const extraCols = FILTER_COLS.slice(0, 2);
  function renderTable(el, list, startRank, step) {{
    const headHtml = "<tr><th class='num'>#</th><th>" + escHtml(NAME_LABEL) + "</th>" + extraCols.map(function(c) {{ return "<th>"+escHtml(c)+"</th>"; }}).join("") + "<th class='num'>" + escHtml(METRIC_LABEL) + "</th><th>vs. promedio</th></tr>";
    const bodyHtml = list.map(function(e, i) {{
      const diff = avg ? (e[1] - avg) / Math.abs(avg) * 100 : 0;
      const tone = diff >= 0 ? "pos" : "neg";
      const width = Math.max(Math.abs(e[1]) / maxAbs * 110, 2).toFixed(0);
      return "<tr><td class='num muted'>" + (startRank + step * i) + "</td><td><b>" + escHtml(e[0]) + "</b></td>" +
        extraCols.map(function(c) {{ return "<td>" + (e[2][c] !== undefined ? escHtml(e[2][c]) : "—") + "</td>"; }}).join("") +
        "<td class='num'>" + fmtNumber(e[1]) + "</td><td class='barcell'><span class='bar" + (e[1] < avg ? " soft" : "") +
        "' style='width:" + width + "px'></span><span class='kpi-delta " + tone + "'>" + (diff >= 0 ? "+" : "") + diff.toFixed(0) + "%</span></td></tr>";
    }}).join("");
    el.innerHTML = list.length ? "<table><thead>" + headHtml + "</thead><tbody>" + bodyHtml + "</tbody></table>"
                               : "<div class='empty'>Sin datos con estos filtros.</div>";
  }}
  document.getElementById("top_title").textContent = total > 10 ? "Los 10 con mayor " + METRIC_LABEL.toLowerCase() : "Ranking completo";
  document.getElementById("ref_note").textContent = total ? "Posición y promedio calculados sobre los " + total.toLocaleString("es-CO") + " visibles con estos filtros." : "";
  renderTable(document.getElementById("table_top"), entries.slice(0, 10), 1, 1);
  const bottomCard = document.getElementById("bottom_card");
  if (total > 10) {{
    bottomCard.style.display = "";
    renderTable(document.getElementById("table_bottom"), entries.slice(-10).reverse(), total, -1);
  }} else {{
    bottomCard.style.display = "none";
  }}
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
    nombre = _esc(_label(schema, search_col)) if search_col else "Elementos"
    nota_truncado = (f" · archivo recortado a {MAX_ROWS:,} filas para mantenerlo liviano" if truncated else "")

    cuerpo = f"""
<header class="cover">
  <div class="cover-kicker">Panel Analítico Universal · Informe interactivo</div>
  <h1>{_esc(sheet)}</h1>
  <p class="lead" id="narrative_text">Cargando resumen…</p>
  <div class="cover-meta"><span>Archivo: <b>{_esc(filename)}</b></span><span>Generado: <b>{_esc(generated)}</b></span>
  <span>Los filtros funcionan dentro de este archivo, sin la app ni internet.</span></div>
</header>

<section class="filters">
  {search_html}
  {filter_selects}
  <div class="filters-end"><span id="result_count"></span><button class="export-btn" id="export_btn" type="button">⬇ Descargar CSV filtrado</button></div>
</section>

<section class="kpis" {kpi_extra} style="margin-top:16px">
  <div class="kpi"><div class="kpi-label">Registros</div><div class="kpi-value" id="kpi_count">—</div></div>
  <div class="kpi"><div class="kpi-label" id="kpi_metric_label">{metric_label}</div><div class="kpi-value" id="kpi_metric">—</div></div>
  <div class="kpi"><div class="kpi-label">{nombre} únicos</div><div class="kpi-value" id="kpi_unique">—</div></div>
  <div class="kpi"><div class="kpi-label">Promedio por {nombre.lower()}</div><div class="kpi-value" id="kpi_avg">—</div></div>
</section>

<section class="grid2" style="margin-top:14px">
  <div class="chart-card"><div class="chart-head"><h3>Evolución{f' · {metric_label}' if metric else ''}</h3><p>Por mes, con los filtros aplicados</p></div><div id="chart_trend"></div></div>
  <div class="chart-card"><div class="chart-head"><h3>Distribución{f' por {dist_label}' if dist_dim else ''}</h3><p>Los 10 de mayor valor; el primero resaltado</p></div><div id="chart_dist"></div></div>
</section>

<section class="grid2" id="tables_row" style="margin-top:14px">
  <div class="table-card"><div class="chart-head"><h3 id="top_title">Los 10 con mayor {metric_label.lower()}</h3><p id="ref_note"></p></div><div class="table-scroll" id="table_top"></div></div>
  <div class="table-card" id="bottom_card"><div class="chart-head"><h3>Los 10 con menor {metric_label.lower()}</h3><p>Donde más margen de mejora hay</p></div><div class="table-scroll" id="table_bottom"></div></div>
</section>

<footer class="footer">{len(payload_df):,} registros incluidos{nota_truncado}.</footer>
<script>{js}</script>
"""
    return documento(f"Informe interactivo — {sheet} · {filename}", cuerpo,
                     css_extra=_CSS_EXTRA, head_extra=f"<script>{plotly_js}</script>\n",
                     # Aquí se filtra en vivo: pasar de a una sección esconde los filtros.
                     presentar=False)


_CSS_EXTRA = """
.filters{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:12px 16px;margin-top:16px;box-shadow:var(--shadow)}
.filter-field{display:flex;flex-direction:column;gap:4px;font-size:10.5px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.05em}
.filter-field select,.filter-field input{border:1px solid var(--line);border-radius:9px;padding:7px 10px;font-size:13px;color:var(--text);min-width:150px;background:#fff;font-family:inherit;text-transform:none;letter-spacing:0}
.filter-field.search input{min-width:210px}
.filters-end{margin-left:auto;display:flex;align-items:center;gap:12px}
#result_count{font-size:12px;color:var(--muted)}
.export-btn{background:var(--brand);color:#fff;border:none;border-radius:9px;padding:9px 16px;font-weight:700;font-size:12.5px;cursor:pointer;font-family:inherit}
.export-btn:hover{background:var(--brand-dark)}
td.barcell{white-space:nowrap;width:auto}
td.barcell .bar{display:inline-block;vertical-align:middle;margin-right:8px}
td.barcell .kpi-delta{display:inline;margin:0}
@media(max-width:860px){.filters{position:static;flex-direction:column;align-items:stretch}.filters-end{margin-left:0;justify-content:space-between}}
@media print{.filters{position:static}.export-btn{display:none}}
"""
