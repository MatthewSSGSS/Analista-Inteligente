from __future__ import annotations

import html
from datetime import datetime
from typing import Iterable

import numpy as np
import pandas as pd

from core.quality import assess
from ui.labels import clean_display_text
from core.dashboard_engine import build_dashboard
from core.geo_engine import geographic_summary, supports_georeferencing
from visualization.charts import (
    adaptive_chart_specs,
    correlation,
    dimension_candidates,
    donut,
    geo_summary_map,
    grouped_trend,
    histogram,
    metric_candidates,
    multi_trend,
    period_compare_bar,
    ranking,
    scatter,
    trend,
)


def _esc(value) -> str:
    return html.escape(str(value))


def _slug(text: str) -> str:
    """Convierte un nombre de hoja en un id de HTML válido para anclas."""
    import re as _re
    import unicodedata as _ud
    s = _ud.normalize("NFKD", str(text))
    s = "".join(c for c in s if not _ud.combining(c))
    s = _re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "hoja"


def _fmt(value) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "—"
    try:
        v = float(value)
    except Exception:
        return _esc(value)
    a = abs(v)
    if a >= 1_000_000_000:
        return f"{v/1_000_000_000:.1f}B"
    if a >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if a >= 1_000:
        return f"{v/1_000:.1f}K"
    return f"{v:,.0f}"


def _kpi_value(k: dict) -> str:
    """Formatea el valor de una tarjeta KPI para el HTML exportado.

    Los KPI dinámicos guardan el número crudo en 'value' (no un string ya
    formateado), así que sin este paso un cambio porcentual como -2.4784...
    se mostraba con todos sus decimales en vez de '-2.5%'.
    """
    value = k.get("value")
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        if k.get("kind") == "growth":
            return f"{value:+.1f}%"
        return _fmt(value)
    return str(value) if value is not None else "—"


def _label(schema: dict, column: str) -> str:
    for item in schema.get("semantic", {}).get("columns", []):
        if item.get("column") == column:
            return item.get("display_name") or str(column)
    return str(column)


def _insight_text(item: dict) -> tuple[str, str, str, str]:
    title = item.get("title") or item.get("label") or "Hallazgo"
    finding = item.get("finding") or item.get("message") or item.get("text") or item.get("description") or ""
    action = item.get("action") or ""
    implication = item.get("implication") or ""
    return (clean_display_text(title), clean_display_text(finding), clean_display_text(action), clean_display_text(implication))


def _date_range(df: pd.DataFrame, schema: dict) -> str:
    for col in schema.get("dates", []):
        if col not in df.columns:
            continue
        dates = pd.to_datetime(df[col], errors="coerce").dropna()
        if len(dates):
            lo, hi = dates.min(), dates.max()
            return f"{lo.strftime('%d/%m/%Y')} — {hi.strftime('%d/%m/%Y')}"
    return "Sin periodo temporal detectado"


def _quality_cards(df: pd.DataFrame, schema: dict) -> list[tuple[str, str, str]]:
    q = assess(df, schema)
    return [
        ("Calidad global", f"{q['score']:.0f}/100", "Lectura de completitud, consistencia y validez"),
        ("Completitud", f"{q['completeness']:.1f}%", "Campos con información disponible"),
        ("Duplicados", f"{q['duplicate_rows']:,}", "Filas duplicadas detectadas"),
        ("Columnas", f"{len(df.columns):,}", "Campos incluidos en el análisis"),
    ]


def _chart_block(title: str, subtitle: str, fig, chart_number: int, include_js: bool) -> str:
    if fig is None:
        return ""
    # Plotly's inline bundle makes the exported file self-contained: the boss can
    # open the HTML locally without needing Streamlit or an internet connection.
    plot = fig.to_html(
        full_html=False,
        include_plotlyjs="inline" if include_js else False,
        config={"displaylogo": False, "responsive": True, "modeBarButtonsToRemove": ["lasso2d", "select2d"]},
    )
    return f"""
    <section class="chart-card">
      <div class="chart-head"><span>VISUAL {chart_number:02d}</span><h3>{_esc(title)}</h3><p>{_esc(subtitle)}</p></div>
      {plot}
    </section>
    """


def _build_charts(df: pd.DataFrame, schema: dict, dashboard: dict, include_geo: bool = True) -> list[str]:
    metrics = metric_candidates(df, schema)
    dims = dimension_candidates(df, schema)
    primary = dashboard.get("primary_metric") or (metrics[0] if metrics else None)
    charts: list[tuple[str, str, object]] = []

    # The report is intentionally adaptive. We ask the same universal chart
    # engine used by the dashboard what is meaningful for this workbook, then
    # add complementary visuals when the dataset supports them.
    for title, subtitle, kind in adaptive_chart_specs(df, schema):
        fig = None
        if kind == "trend":
            fig = trend(df, schema, primary, "Mes", "Suma", False)
        elif kind == "multi_trend":
            fig = multi_trend(df, schema, metrics[:3], "Mes", "Suma")
        elif kind == "ranking" and dims:
            fig = ranking(df, schema, primary, dims[0], 10, "Suma")
        elif kind == "donut" and dims:
            fig = donut(df, schema, primary, dims[0], 7)
        elif kind == "scatter" and len(metrics) >= 2:
            fig = scatter(df, schema, metrics[0], metrics[1])
        elif kind == "histogram":
            fig = histogram(df, schema, primary, 24)
        if fig is not None:
            charts.append((title, subtitle, fig))

    # Add a second ranking/trend by another dimension where possible.
    if primary and len(dims) >= 2:
        fig = ranking(df, schema, primary, dims[1], 10, "Suma")
        if fig is not None:
            charts.append((f"Ranking por {_label(schema, dims[1])}", "Otra vista para detectar concentración y rezagos.", fig))

    if primary and dims:
        fig = period_compare_bar(df, schema, primary, dims[0], "Mes", "Suma", 8)
        if fig is not None:
            charts.append(("Comparación por periodo", "Compara el resultado entre categorías y periodos disponibles.", fig))

    if len(metrics) >= 3:
        fig = correlation(df, schema, metrics[:8])
        if fig is not None:
            charts.append(("Relación entre indicadores", "Qué variables tienden a moverse juntas o en sentidos opuestos.", fig))

    # Deduplicate by title and keep a practical report length.
    seen = set()
    unique = []
    for item in charts:
        if item[0] in seen:
            continue
        seen.add(item[0])
        unique.append(item)
    charts = unique[:10]

    if include_geo:
        try:
            enabled, _ = supports_georeferencing(df, schema)
            if enabled:
                geo_data = geographic_summary(df, schema)
                fig = geo_summary_map(geo_data)
                if fig is not None:
                    charts.append(("Mapa de desempeño", "Distribución geográfica del indicador principal. El mapa solo aparece cuando el Excel tiene datos geográficos utilizables.", fig))
        except Exception:
            # Export must never fail just because geocoding/map support is unavailable.
            pass

    blocks = []
    for i, (title, subtitle, fig) in enumerate(charts, 1):
        blocks.append(_chart_block(title, subtitle, fig, i, include_js=(i == 1)))
    return blocks


def build_html_report(df: pd.DataFrame, schema: dict, dashboard: dict, filename: str, sheet: str, scope_label: str = "Selección actual") -> str:
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")
    metrics = metric_candidates(df, schema)
    dims = dimension_candidates(df, schema)
    primary = dashboard.get("primary_metric") or (metrics[0] if metrics else None)
    quality = _quality_cards(df, schema)

    kpis = dashboard.get("kpis") or []
    kpi_html = []
    for k in kpis[:8]:
        kpi_html.append(f"<div class='kpi'><div class='kpi-label'>{_esc(k.get('label','Indicador'))}</div><div class='kpi-value'>{_esc(_kpi_value(k))}</div></div>")

    insights = dashboard.get("insights") or []
    insight_html = []
    for item in insights[:8]:
        title, finding, action, implication = _insight_text(item if isinstance(item, dict) else {})
        kind = item.get("kind", "info") if isinstance(item, dict) else "info"
        insight_html.append(
            f"<article class='insight {kind}'><div class='insight-tag'>{_esc(kind.upper())}</div><h3>{_esc(title)}</h3>"
            f"<p>{_esc(finding)}</p>"
            f"{('<div class=\"action\"><b>Qué revisar:</b> '+_esc(action)+'</div>') if action else ''}"
            f"{('<div class=\"implication\"><b>Implicación:</b> '+_esc(implication)+'</div>') if implication else ''}</article>"
        )

    alerts = dashboard.get("alerts") or []
    alert_html = []
    for a in alerts[:8]:
        if not isinstance(a, dict):
            continue
        alert_html.append(
            f"<tr><td><span class='severity'>{_esc(clean_display_text(a.get('severity','')))}</span></td><td><b>{_esc(clean_display_text(a.get('title','Hallazgo')))}</b><br><span class='muted'>{_esc(clean_display_text(a.get('text','')))}</span></td>"
            f"<td>{_esc(clean_display_text(a.get('action','')))}</td></tr>"
        )

    change = dashboard.get("change_analysis") or {}
    change_html = ""
    if change:
        pct = change.get("pct")
        direction = "mejoró" if (pct or 0) > 0 else "empeoró" if (pct or 0) < 0 else "se mantuvo estable"
        change_html = f"""
        <section class="change-box">
          <div><span>CAMBIO PRINCIPAL</span><h2>{_esc(change.get('metric_label', 'Indicador'))}</h2></div>
          <div class="change-value">{('+' if (pct or 0) > 0 else '') + f'{pct:.1f}%' if pct is not None else '—'}</div>
          <p>Entre { _esc(change.get('period_before','')) } y { _esc(change.get('period_after','')) }, el indicador {direction}. Antes: <b>{_fmt(change.get('before'))}</b> · Después: <b>{_fmt(change.get('after'))}</b>.</p>
        </section>
        """

    # Small analytical table: strongest groups for the first usable dimension.
    ranking_html = ""
    if primary and dims and dims[0] in df.columns:
        try:
            x = df[[dims[0], primary]].copy()
            x[primary] = pd.to_numeric(x[primary], errors="coerce")
            x = x.dropna(subset=[primary])
            x[dims[0]] = x[dims[0]].fillna("Sin dato").astype(str)
            grouped = x.groupby(dims[0])[primary].sum().sort_values(ascending=False).head(10)
            rows = "".join(f"<tr><td>{_esc(k)}</td><td>{_fmt(v)}</td></tr>" for k, v in grouped.items())
            ranking_html = f"<section class='table-card'><h2>Principales categorías</h2><p class='muted'>Top 10 por {_esc(_label(schema, primary))}.</p><table><thead><tr><th>{_esc(_label(schema, dims[0]))}</th><th>{_esc(_label(schema, primary))}</th></tr></thead><tbody>{rows}</tbody></table></section>"
        except Exception:
            pass

    quality_rows = "".join(f"<tr><td>{_esc(c)}</td><td>{_esc(v)}</td><td>{_esc(s)}</td></tr>" for c,v,s in quality)

    # El gráfico más representativo (evolución si hay fecha+métrica; si no,
    # ranking o distribución) se muestra grande e inmediatamente después del
    # resumen ejecutivo. El resto de gráficos queda como material de apoyo
    # más abajo, en vez de competir todos por la misma atención.
    chart_blocks = _build_charts(df, schema, dashboard, include_geo=True)
    if chart_blocks:
        featured_chart_html = chart_blocks[0]
        secondary_chart_blocks = chart_blocks[1:]
    else:
        featured_chart_html = "<div class='empty'>No hubo suficientes variables para construir gráficos universales con significado.</div>"
        secondary_chart_blocks = []
    secondary_chart_html = "".join(secondary_chart_blocks)

    schema_summary = f"""
    <section class="table-card" id="motor">
      <h2>Qué encontró el motor</h2>
      <div class="meta-grid">
        <div><b>{len(metrics)}</b><span>Métricas</span></div>
        <div><b>{len(schema.get('dates', []))}</b><span>Fechas</span></div>
        <div><b>{len(dims)}</b><span>Dimensiones</span></div>
        <div><b>{len(schema.get('ids', []))}</b><span>Identificadores</span></div>
      </div>
      <p class="muted">El informe no presupone una estructura fija: los gráficos y secciones se activan según lo que realmente contiene este Excel.</p>
    </section>
    """

    # Menú de navegación lateral: solo enlaza a secciones que realmente
    # existen en este informe, para no dejar enlaces muertos.
    nav_items = [("resumen", "Resumen rápido"), ("vista-principal", "Vista principal")]
    if change_html:
        nav_items.append(("cambio", "Cambio principal"))
    nav_items.append(("lectura", "Lectura analítica"))
    nav_items.append(("alertas", "Alertas"))
    nav_items.append(("motor", "Qué encontró el motor"))
    if secondary_chart_html:
        nav_items.append(("graficos", "Otros gráficos"))
    if ranking_html:
        nav_items.append(("categorias", "Principales categorías"))
    nav_items.append(("calidad", "Calidad del dato"))
    nav_html = "".join(f'<a href="#{sid}">{_esc(label)}</a>' for sid, label in nav_items)

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Resumen analítico — {_esc(filename)}</title>
<style>
:root{{--bg:#f5f7fb;--card:#fff;--text:#172033;--muted:#667085;--line:#e1e6ef;--blue:#e4002b;--teal:#10b9a6;--green:#22a06b;--amber:#f59e0b;--red:#e05252;--shadow:0 5px 18px rgba(23,32,51,.06)}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif;line-height:1.45;scroll-behavior:smooth}}
.report-shell{{display:flex;align-items:flex-start;gap:24px;max-width:1500px;margin:0 auto;padding:32px 24px 60px}}
.side-nav{{width:206px;flex:0 0 206px;position:sticky;top:22px;align-self:flex-start;max-height:calc(100vh - 44px);overflow-y:auto;background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px 14px;box-shadow:var(--shadow)}}
.side-nav .nav-title{{font-size:10px;font-weight:800;letter-spacing:.1em;color:var(--muted);text-transform:uppercase;margin:0 0 10px}}
.side-nav a{{display:block;padding:7px 9px;border-radius:8px;font-size:12.5px;color:var(--text);text-decoration:none;margin-bottom:2px;border-left:3px solid transparent;transition:background .12s ease,color .12s ease}}
.side-nav a:hover{{background:#f7f9fc;color:var(--blue)}}
.side-nav a.active{{background:#fde8ea;color:var(--blue);border-left-color:var(--blue);font-weight:700}}
.wrap{{flex:1;min-width:0}}
.header{{background:#fff;border:1px solid var(--line);border-top:5px solid #e4002b;border-radius:16px;padding:28px 30px;box-shadow:var(--shadow)}}
.kicker{{font-size:11px;font-weight:800;letter-spacing:.13em;color:#e4002b;text-transform:uppercase}}h1{{margin:6px 0 5px;font-size:30px;letter-spacing:-.03em}}.subtitle{{color:var(--muted);font-size:14px}}.meta{{display:flex;flex-wrap:wrap;gap:8px;margin-top:17px}}.meta span{{background:#f7f9fc;border:1px solid var(--line);border-radius:999px;padding:7px 10px;font-size:11px;color:var(--muted)}}
.section{{margin-top:28px;scroll-margin-top:20px}}.section>h2,.table-card h2{{font-size:20px;margin:0 0 6px;letter-spacing:-.02em}}.section>p,.table-card>p{{margin:0 0 14px;color:var(--muted);font-size:13px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}.kpi{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;box-shadow:var(--shadow)}}.kpi-label{{font-size:11px;color:var(--muted);font-weight:700}}.kpi-value{{font-size:24px;font-weight:800;margin-top:8px}}
.change-box{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:13px;padding:18px 20px;box-shadow:var(--shadow);display:grid;grid-template-columns:1fr auto;gap:4px 18px;scroll-margin-top:20px}}.change-box span{{font-size:10px;font-weight:800;letter-spacing:.12em;color:var(--blue)}}.change-box h2{{margin:3px 0 0;font-size:19px}}.change-value{{font-size:30px;font-weight:900;align-self:center;color:var(--blue)}}.change-box p{{grid-column:1/-1;color:var(--muted);margin:6px 0 0}}
.insights{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}}.insight{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:12px;padding:15px;box-shadow:var(--shadow)}}.insight.warning{{border-left-color:var(--amber)}}.insight.positive{{border-left-color:var(--green)}}.insight-tag{{font-size:9px;letter-spacing:.11em;font-weight:800;color:var(--muted)}}.insight h3{{margin:5px 0 6px;font-size:14px}}.insight p{{margin:0;font-size:13px}}.action,.implication{{margin-top:9px;background:#f7f9fc;border:1px solid var(--line);border-radius:8px;padding:8px;font-size:12px}}
.grid2{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}.chart-card,.table-card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:15px 17px;box-shadow:var(--shadow);margin-top:14px;scroll-margin-top:20px}}.chart-head span{{font-size:9px;color:var(--blue);font-weight:800;letter-spacing:.13em}}.chart-head h3{{margin:4px 0 2px;font-size:15px}}.chart-head p{{margin:0 0 5px;color:var(--muted);font-size:11px}}.table-card table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:9px 8px;border-bottom:1px solid var(--line);text-align:left}}th{{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.06em}}.muted{{color:var(--muted)}}.severity{{font-size:10px;font-weight:800;padding:4px 7px;border-radius:999px;background:#fff3dc;color:#a86000}}.empty{{padding:24px;background:#fff;border:1px dashed var(--line);border-radius:12px;color:var(--muted)}}.meta-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:15px 0}}.meta-grid div{{background:#f7f9fc;border:1px solid var(--line);border-radius:10px;padding:13px}}.meta-grid b{{display:block;font-size:20px}}.meta-grid span{{color:var(--muted);font-size:11px}}.footer{{margin-top:35px;color:#7a8495;font-size:11px;text-align:center}}
@media(max-width:1000px){{.side-nav{{display:none}}}}
@media(max-width:850px){{.report-shell{{padding:18px 12px}}h1{{font-size:24px}}.grid2{{grid-template-columns:1fr}}.meta-grid{{grid-template-columns:repeat(2,1fr)}}}}
@media print{{.side-nav{{display:none}}.report-shell{{padding:0;display:block}}}}
</style>
</head>
<body>
<div class="report-shell">
<nav class="side-nav"><div class="nav-title">En este informe</div>{nav_html}</nav>
<main class="wrap">
<header class="header"><div class="kicker">Excel Intelligence · Informe ejecutivo</div><h1>Resumen analítico del Excel</h1><div class="subtitle">Una lectura lista para compartir: qué pasó, dónde se concentra, qué cambió y qué conviene revisar.</div><div class="meta"><span>Archivo: {_esc(filename)}</span><span>Hoja: {_esc(sheet)}</span><span>Alcance: {_esc(scope_label)}</span><span>Periodo: {_esc(_date_range(df, schema))}</span><span>Generado: {_esc(generated)}</span><span>Registros: {len(df):,}</span></div></header>
<section class="section" id="resumen"><h2>Resumen rápido</h2><p>Indicadores principales calculados sobre el conjunto que se está reportando.</p><div class="kpis">{''.join(kpi_html) or '<div class="empty">No se detectaron KPIs universales.</div>'}</div></section>
<section class="section" id="vista-principal"><h2>Vista principal</h2><p>El indicador más representativo detectado para esta hoja.</p>{featured_chart_html}</section>
{change_html.replace('<section class="change-box">', '<section class="change-box" id="cambio">', 1)}
<section class="section" id="lectura"><h2>Lectura analítica</h2><p>Hallazgos priorizados por el motor universal, con contexto y acción cuando existe.</p><div class="insights">{''.join(insight_html) or '<div class="empty">No se detectaron hallazgos suficientes para esta selección.</div>'}</div></section>
<section class="section" id="alertas"><h2>Alertas y puntos de atención</h2><div class="table-card"><table><thead><tr><th>Nivel</th><th>Hallazgo</th><th>Qué hacer</th></tr></thead><tbody>{''.join(alert_html) or '<tr><td colspan="3">No hay alertas relevantes.</td></tr>'}</tbody></table></div></section>
{schema_summary}
{f'<section class="section" id="graficos"><h2>Otros gráficos disponibles</h2><p>Visualizaciones adicionales que complementan la vista principal.</p><div class="grid2">{secondary_chart_html}</div></section>' if secondary_chart_html else ''}
{ranking_html.replace("<section class='table-card'>", "<section class='table-card' id='categorias'>", 1)}
<section class="section" id="calidad"><div class="table-card"><h2>Calidad del dato</h2><p>Indicadores básicos para saber si el análisis merece confianza antes de tomar decisiones.</p><table><thead><tr><th>Indicador</th><th>Valor</th><th>Interpretación</th></tr></thead><tbody>{quality_rows}</tbody></table></div></section>
<footer class="footer">Generado automáticamente por Panel Analítico Universal · El contenido se adapta a la estructura real del Excel.</footer>
</main>
</div>
<script>
(function(){{
  var links = Array.prototype.slice.call(document.querySelectorAll('.side-nav a[href^="#"]'));
  var sections = links.map(function(a){{ return document.getElementById(a.getAttribute('href').slice(1)); }}).filter(Boolean);
  function onScroll(){{
    var pos = window.scrollY + 130;
    var current = sections[0];
    sections.forEach(function(s){{ if (s.offsetTop <= pos) current = s; }});
    links.forEach(function(a){{ a.classList.remove('active'); }});
    if (current) {{
      var active = document.querySelector('.side-nav a[href="#' + current.id + '"]');
      if (active) active.classList.add('active');
    }}
  }}
  window.addEventListener('scroll', onScroll, {{passive:true}});
  onScroll();
}})();
</script>
</body></html>"""



def _workbook_sheet_summary(sheet_name: str, df: pd.DataFrame, profile: dict) -> dict:
    schema = profile.get("schema", {}) if isinstance(profile, dict) else {}
    dashboard = build_dashboard(df, profile)
    metrics = metric_candidates(df, schema)
    dims = dimension_candidates(df, schema)
    quality = _quality_cards(df, schema)
    primary = dashboard.get("primary_metric") or (metrics[0] if metrics else None)
    total_value = None
    if primary and primary in df.columns:
        vals = pd.to_numeric(df[primary], errors="coerce")
        if vals.notna().any():
            total_value = vals.sum()
    return {
        "sheet": sheet_name,
        "df": df,
        "profile": profile,
        "schema": schema,
        "dashboard": dashboard,
        "metrics": metrics,
        "dims": dims,
        "quality": quality,
        "primary": primary,
        "total_value": total_value,
    }


def build_workbook_html_report(workbook: dict) -> str:
    """Build a report of the entire workbook, independent of current filters.

    Each non-empty sheet gets its own adaptive section. The opening pages are
    workbook-level: sheet count, total records, data quality, detected date
    ranges, main metrics and the most important findings across sheets.
    """
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")
    filename = workbook.get("filename", "Excel")
    sheets = workbook.get("sheets", {}) or {}
    reports = []
    for sheet_name, item in sheets.items():
        if not isinstance(item, dict):
            continue
        frame = item.get("processed")
        profile = item.get("profile") or {}
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            continue
        try:
            reports.append(_workbook_sheet_summary(sheet_name, frame, profile))
        except Exception:
            # One malformed sheet must not prevent the rest of the workbook report.
            continue

    total_rows = sum(len(r["df"]) for r in reports)
    total_columns = sum(len(r["df"].columns) for r in reports)
    total_cells = sum(r["df"].shape[0] * r["df"].shape[1] for r in reports)

    # Workbook-level quality is presented as a weighted view of all usable sheets.
    if reports:
        weighted_quality = sum(r["quality"][0][1].split("/")[0] and float(r["quality"][0][1].split("/")[0]) * len(r["df"]) for r in reports) / max(total_rows, 1)
        avg_complete = sum(float(r["quality"][1][1].replace("%", "")) * len(r["df"]) for r in reports) / max(total_rows, 1)
        duplicates = sum(int(r["quality"][2][1].replace(",", "")) for r in reports)
    else:
        weighted_quality, avg_complete, duplicates = 0.0, 0.0, 0

    # Cross-sheet index: useful even when sheets have completely different schemas.
    index_rows = []
    global_findings = []
    for r in reports:
        d = r["dashboard"]
        insights = d.get("insights") or []
        first = insights[0] if insights else {}
        if isinstance(first, dict):
            title = clean_display_text(first.get("title") or first.get("label") or "Hallazgo")
            finding = clean_display_text(first.get("finding") or first.get("message") or first.get("text") or first.get("description") or "")
            # Hojas sin un hallazgo real (por ejemplo una portada/título sin datos
            # analizables) no deben producir una tarjeta vacía en el resumen.
            if finding:
                global_findings.append((r["sheet"], title, finding))
        index_rows.append(
            f"<tr><td><b>{_esc(r['sheet'])}</b></td><td>{len(r['df']):,}</td><td>{len(r['df'].columns):,}</td>"
            f"<td>{_esc(_date_range(r['df'], r['schema']))}</td><td>{_fmt(r['total_value']) if r['total_value'] is not None else '—'}</td>"
            f"<td>{_esc(r['primary'] and _label(r['schema'], r['primary']) or 'No detectada')}</td></tr>"
        )

    findings_html = "".join(
        f"<article class='finding-mini'><div class='finding-sheet'>{_esc(sheet)}</div><b>{_esc(title)}</b><p>{_esc(finding)}</p></article>"
        for sheet, title, finding in global_findings[:10]
    )

    sheet_sections = []
    chart_counter = 0
    used_slugs: dict = {}
    for r in reports:
        d = r["dashboard"]
        schema = r["schema"]
        df = r["df"]

        # Id único por hoja para el ancla del menú, incluso si dos hojas
        # comparten un nombre muy parecido tras normalizarlo.
        base_slug = _slug(r["sheet"])
        used_slugs[base_slug] = used_slugs.get(base_slug, 0) + 1
        sheet_id = base_slug if used_slugs[base_slug] == 1 else f"{base_slug}-{used_slugs[base_slug]}"
        r["_anchor"] = sheet_id

        kpis = d.get("kpis") or []
        kpi_html = "".join(
            f"<div class='kpi'><div class='kpi-label'>{_esc(k.get('label','Indicador'))}</div><div class='kpi-value'>{_esc(_kpi_value(k))}</div></div>"
            for k in kpis[:6]
        )
        if not kpi_html:
            kpi_html = f"<div class='kpi'><div class='kpi-label'>Registros</div><div class='kpi-value'>{len(df):,}</div></div>"

        insights = d.get("insights") or []
        insight_html = "".join(
            f"<article class='insight {('positive' if (i.get('kind') == 'positive') else 'warning' if i.get('kind') in {'warning','negative'} else 'info') if isinstance(i,dict) else 'info'}'>"
            f"<div class='insight-tag'>{_esc((i.get('kind','info') if isinstance(i,dict) else 'info').upper())}</div>"
            f"<h3>{_esc((i.get('title') or i.get('label') or 'Hallazgo') if isinstance(i,dict) else 'Hallazgo')}</h3>"
            f"<p>{_esc(clean_display_text((i.get('finding') or i.get('message') or i.get('text') or i.get('description') or '') if isinstance(i,dict) else str(i)))}</p></article>"
            for i in insights[:6]
        )
        if not insight_html:
            insight_html = "<div class='empty'>No se detectaron hallazgos suficientes en esta hoja.</div>"

        charts = _build_charts(df, schema, d, include_geo=True)
        numbered_blocks = []
        for block in charts[:8]:
            chart_counter += 1
            # Renumber the visible label without rebuilding Plotly HTML.
            numbered_blocks.append(block.replace("VISUAL 01", f"VISUAL {chart_counter:02d}", 1).replace("VISUAL 02", f"VISUAL {chart_counter:02d}", 1))
        # El primer gráfico (el más representativo: evolución si hay fecha,
        # si no ranking/distribución) se muestra grande justo después de los
        # KPIs, igual que en el informe individual. El resto queda como
        # material de apoyo más abajo.
        if numbered_blocks:
            featured_chart_html = numbered_blocks[0]
            secondary_charts_html = "".join(numbered_blocks[1:])
        else:
            featured_chart_html = "<div class='empty'>Esta hoja no tiene suficientes variables para construir visualizaciones con significado.</div>"
            secondary_charts_html = ""

        qrows = "".join(f"<tr><td>{_esc(c)}</td><td>{_esc(v)}</td><td>{_esc(s)}</td></tr>" for c,v,s in r["quality"])
        sheet_sections.append(f"""
        <section class='sheet-section' id='{sheet_id}'>
          <div class='sheet-heading'><div><span class='kicker'>HOJA</span><h2>{_esc(r['sheet'])}</h2><p>{len(df):,} registros · {len(df.columns):,} columnas · {_esc(_date_range(df, schema))}</p></div><span class='sheet-primary'>{_esc(r['primary'] and _label(schema, r['primary']) or 'Sin métrica principal')}</span></div>
          <div class='kpis'>{kpi_html}</div>
          {featured_chart_html}
          <div class='sheet-grid'><div><h3>Lectura de esta hoja</h3><div class='insights'>{insight_html}</div></div><div class='table-card'><h3>Calidad</h3><table><tbody>{qrows}</tbody></table></div></div>
          {f"<div class='grid2'>{secondary_charts_html}</div>" if secondary_charts_html else ""}
        </section>
        """)

    # Menú de navegación lateral: secciones generales del libro + un enlace
    # por cada hoja analizada, para saltar directo sin scrollear todo.
    nav_top = [("resumen-libro", "Resumen ejecutivo")]
    if findings_html:
        nav_top.append(("hallazgos", "Qué está pasando"))
    nav_top.append(("mapa", "Mapa del contenido"))
    nav_top_html = "".join(f'<a href="#{sid}">{_esc(label)}</a>' for sid, label in nav_top)
    nav_sheets_html = "".join(f'<a href="#{r["_anchor"]}">{_esc(r["sheet"])}</a>' for r in reports)
    nav_html = (
        nav_top_html
        + (f'<div class="nav-title nav-group">Hojas</div>{nav_sheets_html}' if nav_sheets_html else "")
    )

    return f"""<!doctype html>
<html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Informe general del Excel — {_esc(filename)}</title>
<style>
:root{{--bg:#f4f6fa;--card:#fff;--text:#172033;--muted:#667085;--line:#dfe4ec;--blue:#e4002b;--teal:#10b9a6;--green:#1b9a67;--amber:#d88708;--red:#c52a3d;--shadow:0 5px 18px rgba(23,32,51,.06)}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif;line-height:1.45;scroll-behavior:smooth}}
.report-shell{{display:flex;align-items:flex-start;gap:22px;max-width:1560px;margin:0 auto;padding:30px 22px 60px}}
.side-nav{{width:216px;flex:0 0 216px;position:sticky;top:20px;align-self:flex-start;max-height:calc(100vh - 40px);overflow-y:auto;background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px 14px;box-shadow:var(--shadow)}}
.side-nav .nav-title{{font-size:10px;font-weight:800;letter-spacing:.1em;color:var(--muted);text-transform:uppercase;margin:0 0 10px}}
.side-nav .nav-group{{margin-top:14px;padding-top:12px;border-top:1px solid var(--line)}}
.side-nav a{{display:block;padding:7px 9px;border-radius:8px;font-size:12.5px;color:var(--text);text-decoration:none;margin-bottom:2px;border-left:3px solid transparent;transition:background .12s ease,color .12s ease;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.side-nav a:hover{{background:#f7f9fc;color:var(--blue)}}
.side-nav a.active{{background:#fde8ea;color:var(--blue);border-left-color:var(--blue);font-weight:700}}
.wrap{{flex:1;min-width:0}}
.header{{background:#fff;border:1px solid var(--line);border-top:6px solid #e4002b;border-radius:17px;padding:28px 30px;box-shadow:var(--shadow)}}.kicker{{font-size:10px;font-weight:900;letter-spacing:.13em;color:#e4002b;text-transform:uppercase}}h1{{margin:6px 0 6px;font-size:31px;letter-spacing:-.03em}}.subtitle{{color:var(--muted);font-size:14px;max-width:900px}}.meta{{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}}.meta span{{background:#f7f9fc;border:1px solid var(--line);border-radius:999px;padding:7px 10px;font-size:11px;color:var(--muted)}}
.section{{margin-top:28px;scroll-margin-top:20px}}.section>h2{{font-size:21px;margin:0 0 5px}}.section>p{{margin:0 0 14px;color:var(--muted);font-size:13px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:11px}}.kpi{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;box-shadow:var(--shadow)}}.kpi-label{{font-size:10px;color:var(--muted);font-weight:800}}.kpi-value{{font-size:23px;font-weight:900;margin-top:7px}}
.table-card{{background:#fff;border:1px solid var(--line);border-radius:13px;padding:15px;box-shadow:var(--shadow);margin-top:10px}}.table-card h3{{margin:0 0 9px;font-size:15px}}.table-card table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:8px;border-bottom:1px solid var(--line);text-align:left}}th{{font-size:10px;color:var(--muted);text-transform:uppercase}}.muted{{color:var(--muted)}}
.findings{{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:11px}}.finding-mini{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:12px;padding:13px;box-shadow:var(--shadow)}}.finding-sheet{{font-size:9px;font-weight:900;letter-spacing:.1em;color:var(--blue);text-transform:uppercase;margin-bottom:5px}}.finding-mini b{{font-size:13px}}.finding-mini p{{font-size:12px;color:var(--muted);margin:6px 0 0}}
.sheet-section{{margin-top:34px;padding-top:22px;border-top:2px solid #e4e8ef;scroll-margin-top:20px}}.sheet-heading{{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:12px}}.sheet-heading h2{{margin:3px 0;font-size:23px}}.sheet-heading p{{margin:0;color:var(--muted);font-size:12px}}.sheet-primary{{padding:7px 10px;border-radius:999px;background:#fde8ea;color:var(--blue);font-size:10px;font-weight:800}}
.sheet-grid{{display:grid;grid-template-columns:1.6fr .8fr;gap:14px;margin-top:14px}}.sheet-grid h3{{font-size:15px;margin:0 0 8px}}.insights{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}}.insight{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:12px;padding:13px;box-shadow:var(--shadow)}}.insight.warning{{border-left-color:var(--amber)}}.insight.positive{{border-left-color:var(--green)}}.insight-tag{{font-size:9px;letter-spacing:.1em;font-weight:900;color:var(--muted)}}.insight h3{{font-size:13px;margin:5px 0}}.insight p{{font-size:12px;margin:0}}
.grid2{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:14px}}.chart-card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:13px 15px;box-shadow:var(--shadow);overflow:hidden;scroll-margin-top:20px}}.chart-head span{{font-size:9px;color:var(--blue);font-weight:900;letter-spacing:.12em}}.chart-head h3{{margin:4px 0 2px;font-size:15px}}.chart-head p{{margin:0;color:var(--muted);font-size:11px}}.empty{{padding:18px;background:#fff;border:1px dashed var(--line);border-radius:11px;color:var(--muted);font-size:12px}}.footer{{margin-top:40px;color:#7a8495;font-size:11px;text-align:center}}
@media(max-width:1050px){{.side-nav{{display:none}}}}
@media(max-width:900px){{.grid2,.sheet-grid,.insights{{grid-template-columns:1fr}}.report-shell{{padding:18px 11px}}.sheet-heading{{flex-direction:column}}}}
@media print{{.side-nav{{display:none}}.report-shell{{padding:0;display:block}}}}
</style></head><body>
<div class="report-shell">
<nav class="side-nav"><div class="nav-title">En este informe</div>{nav_html}</nav>
<main class='wrap'>
<header class='header'><div class='kicker'>Panel Analítico Universal · Informe para compartir</div><h1>Resumen general de todo el Excel</h1><div class='subtitle'>Lectura completa del libro: no depende de los filtros que estén activos en Streamlit. Resume las hojas disponibles, sus principales indicadores, hallazgos, calidad y gráficos que realmente tienen sentido para cada estructura.</div><div class='meta'><span>Archivo: {_esc(filename)}</span><span>Hojas analizadas: {len(reports):,}</span><span>Registros totales: {total_rows:,}</span><span>Celdas analizadas: {total_cells:,}</span><span>Generado: {_esc(generated)}</span></div></header>
<section class='section' id='resumen-libro'><h2>Resumen ejecutivo del libro</h2><p>Primero una visión general para dirección; después el detalle de cada hoja.</p><div class='kpis'><div class='kpi'><div class='kpi-label'>Hojas con datos</div><div class='kpi-value'>{len(reports):,}</div></div><div class='kpi'><div class='kpi-label'>Registros totales</div><div class='kpi-value'>{total_rows:,}</div></div><div class='kpi'><div class='kpi-label'>Columnas analizadas</div><div class='kpi-value'>{total_columns:,}</div></div><div class='kpi'><div class='kpi-label'>Calidad ponderada</div><div class='kpi-value'>{weighted_quality:.0f}/100</div></div><div class='kpi'><div class='kpi-label'>Completitud ponderada</div><div class='kpi-value'>{avg_complete:.1f}%</div></div><div class='kpi'><div class='kpi-label'>Duplicados detectados</div><div class='kpi-value'>{duplicates:,}</div></div></div></section>
{f'''<section class='section' id='hallazgos'><h2>Qué está pasando en el Excel</h2><p>Hallazgos destacados de las hojas con información útil para el análisis.</p><div class='findings'>{findings_html}</div></section>''' if findings_html else ''}
<section class='section' id='mapa'><div class='table-card'><h2>Mapa del contenido del libro</h2><p class='muted'>Esta tabla permite entender rápidamente qué contiene cada hoja y cuál es su indicador principal.</p><table><thead><tr><th>Hoja</th><th>Registros</th><th>Columnas</th><th>Periodo</th><th>Total principal</th><th>Métrica principal</th></tr></thead><tbody>{''.join(index_rows) or '<tr><td colspan="6">No se encontraron hojas analizables.</td></tr>'}</tbody></table></div></section>
{''.join(sheet_sections) or '<section class="section"><div class="empty">No se encontraron hojas con datos analizables.</div></section>'}
<footer class='footer'>Informe generado automáticamente por Panel Analítico Universal · Resumen general del libro completo · Los gráficos y análisis se adaptan a cada hoja.</footer>
</main>
</div>
<script>
(function(){{
  var links = Array.prototype.slice.call(document.querySelectorAll('.side-nav a[href^="#"]'));
  var sections = links.map(function(a){{ return document.getElementById(a.getAttribute('href').slice(1)); }}).filter(Boolean);
  function onScroll(){{
    var pos = window.scrollY + 130;
    var current = sections[0];
    sections.forEach(function(s){{ if (s.offsetTop <= pos) current = s; }});
    links.forEach(function(a){{ a.classList.remove('active'); }});
    if (current) {{
      var active = document.querySelector('.side-nav a[href="#' + current.id + '"]');
      if (active) active.classList.add('active');
    }}
  }}
  window.addEventListener('scroll', onScroll, {{passive:true}});
  onScroll();
}})();
</script>
</body></html>"""


def build_comparison_html_report(comparison: dict, filters_summary: str = "Sin filtros aplicados") -> str:
    """Informe HTML de la vista "Comparativa": qué cambió entre N archivos,
    con los mismos filtros que el usuario tenga aplicados en pantalla. No es
    una foto del dashboard: se reconstruye de forma independiente, igual que
    los otros informes.
    """
    import plotly.express as px
    from core.comparison_engine import combined_records_table

    files = comparison.get("files", [])
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")
    file_list = "".join(
        f"<li><b>{i+1}.</b> {_esc(f['label'])} <span class='muted'>({_esc(f['filename'])} · {len(f['df']):,} registros)</span></li>"
        for i, f in enumerate(files)
    )

    kpi_cards = []
    for m in comparison.get("recent_metrics", []):
        cp = m["cambio_pct"]
        cp_txt = "—" if cp is None else f"{cp:+.1f}%"
        tone = "up" if (cp or 0) > 0 else ("down" if (cp or 0) < 0 else "")
        kpi_cards.append(
            f"<div class='kpi'><div class='kpi-label'>{_esc(m['nombre'])}</div>"
            f"<div class='kpi-value'>{_fmt(m['actual'])}</div>"
            f"<div class='kpi-delta {tone}'>{cp_txt} vs. periodo anterior</div></div>"
        )
    kpi_html = "".join(kpi_cards)

    signals_html = "".join(
        f"<article class='finding-mini'><div class='finding-sheet'>{'↑ MEJORA' if s['tipo']=='positive' else '↓ ATENCIÓN' if s['tipo']=='warning' else 'CONTEXTO'}</div><p>{_esc(clean_display_text(s['texto']))}</p></article>"
        for s in comparison.get("signals", [])
    )

    dim_tables = []
    for dr in comparison.get("dimension_results", [])[:4]:
        t = dr["table"]
        up = t.sort_values("cambio", ascending=False).head(5)
        down = t.sort_values("cambio", ascending=True).head(5)
        def _rows(sub):
            out = []
            for _, r in sub.iterrows():
                cp_txt = "—" if pd.isna(r["cambio_pct"]) else f"{r['cambio_pct']:+.1f}%"
                out.append(
                    f"<tr><td>{_esc(r['categoria'])}</td><td>{_fmt(r['anterior'])}</td><td>{_fmt(r['actual'])}</td>"
                    f"<td>{cp_txt}</td></tr>"
                )
            return "".join(out)
        dim_tables.append(f"""
        <div class='table-card'>
          <h3>{_esc(dr['dimension'])} · usando {_esc(dr['metric'])}</h3>
          <div class='dim-grid'>
            <div><p class='muted'>Mayor mejora</p><table><thead><tr><th>Categoría</th><th>Antes</th><th>Ahora</th><th>Variación</th></tr></thead><tbody>{_rows(up)}</tbody></table></div>
            <div><p class='muted'>Mayor caída</p><table><thead><tr><th>Categoría</th><th>Antes</th><th>Ahora</th><th>Variación</th></tr></thead><tbody>{_rows(down)}</tbody></table></div>
          </div>
        </div>
        """)

    chart_blocks = []
    for i, h in enumerate(comparison.get("history", [])[:6]):
        series = h["serie"]
        fig = px.line(series, x="periodo", y="valor", markers=True)
        fig.update_layout(
            height=340, margin=dict(l=20, r=20, t=20, b=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            xaxis_title="Periodo", yaxis_title=h["operacion"], font=dict(family="Inter,Segoe UI,Arial,sans-serif", size=12),
        )
        fig.update_traces(line_color="#e4002b", marker_color="#e4002b")
        chart_blocks.append(_chart_block(f"Evolución · {h['metrica']}", f"{h['operacion']} por archivo comparado", fig, i + 1, include_js=(i == 0)))

    matches = comparison.get("matches", [])
    match_rows = "".join(
        f"<tr><td>{_esc(m['a'])}</td><td>{_esc(m['b'])}</td><td>{m['score']*100:.0f}%</td><td>{_esc(_pretty_technical_safe(m.get('concept','')))}</td></tr>"
        for m in matches
    )

    records = combined_records_table(files, max_rows=300)
    records_section = ""
    if not records.empty:
        total_real = sum(len(f["df"]) for f in files)
        head_cols = "".join(f"<th>{_esc(c)}</th>" for c in records.columns)
        body_rows = "".join(
            "<tr>" + "".join(f"<td>{_esc(v) if pd.notna(v) else '—'}</td>" for v in row) + "</tr>"
            for row in records.itertuples(index=False)
        )
        note = f"Mostrando los primeros {len(records):,} de {total_real:,} registros totales." if total_real > len(records) else f"{len(records):,} registros."
        records_section = f"""
        <section class='section'><div class='table-card'>
          <h3>Registros detallados</h3>
          <p class='muted'>{note} Descarga el CSV completo desde la app si necesitas todo el detalle.</p>
          <div style='overflow-x:auto'><table><thead><tr>{head_cols}</tr></thead><tbody>{body_rows}</tbody></table></div>
        </div></section>
        """

    return f"""<!doctype html>
<html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Informe comparativo — {len(files)} archivos</title>
<style>
:root{{--bg:#f4f6fa;--card:#fff;--text:#172033;--muted:#667085;--line:#dfe4ec;--blue:#e4002b;--green:#1b9a67;--amber:#d88708;--shadow:0 5px 18px rgba(23,32,51,.06)}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif;line-height:1.45}}
.wrap{{max-width:1200px;margin:0 auto;padding:30px 22px 60px}}
.header{{background:#fff;border:1px solid var(--line);border-top:6px solid var(--blue);border-radius:17px;padding:26px 28px;box-shadow:var(--shadow)}}
.kicker{{font-size:10px;font-weight:900;letter-spacing:.13em;color:var(--blue);text-transform:uppercase}}
h1{{margin:6px 0 8px;font-size:28px;letter-spacing:-.03em}}
.subtitle{{color:var(--muted);font-size:13.5px}}
.filelist{{list-style:none;padding:0;margin:14px 0 0;display:flex;flex-wrap:wrap;gap:8px}}
.filelist li{{background:#f7f9fc;border:1px solid var(--line);border-radius:999px;padding:6px 12px;font-size:12px}}
.badge{{display:inline-block;margin-top:12px;background:#fde8ea;color:var(--blue);border-radius:999px;padding:6px 12px;font-size:12px;font-weight:700}}
.section{{margin-top:26px}}.section h2{{font-size:19px;margin:0 0 12px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}
.kpi{{background:#fff;border:1px solid var(--line);border-radius:13px;padding:15px;box-shadow:var(--shadow)}}
.kpi-label{{font-size:11px;color:var(--muted);font-weight:700}}.kpi-value{{font-size:22px;font-weight:800;margin-top:6px}}
.kpi-delta{{font-size:11.5px;font-weight:700;margin-top:6px;color:var(--muted)}}.kpi-delta.up{{color:var(--green)}}.kpi-delta.down{{color:var(--blue)}}
.findings{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:11px}}
.finding-mini{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:12px;padding:13px;box-shadow:var(--shadow)}}
.finding-sheet{{font-size:9px;font-weight:900;letter-spacing:.1em;color:var(--blue);margin-bottom:5px}}
.table-card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:var(--shadow);margin-top:14px}}
.table-card h3{{margin:0 0 10px;font-size:15px}}.dim-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}
th{{color:var(--muted);font-size:10px;text-transform:uppercase}}.muted{{color:var(--muted);font-size:11.5px;margin:0 0 6px}}
.chart-card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px 16px;box-shadow:var(--shadow);margin-top:14px}}
.chart-head span{{font-size:9px;color:var(--blue);font-weight:900;letter-spacing:.12em}}.chart-head h3{{margin:4px 0 2px;font-size:15px}}.chart-head p{{margin:0;color:var(--muted);font-size:11px}}
.footer{{margin-top:35px;color:#7a8495;font-size:11px;text-align:center}}
@media(max-width:800px){{.dim-grid{{grid-template-columns:1fr}}}}
</style></head><body><main class='wrap'>
<header class='header'>
  <div class='kicker'>Panel Analítico Universal · Informe comparativo</div>
  <h1>Qué cambió entre {len(files)} archivos</h1>
  <div class='subtitle'>Comparación calculada automáticamente cruzando variables equivalentes entre archivos, con los mismos filtros que tenías activos. Generado: {_esc(generated)}.</div>
  <ul class='filelist'>{file_list}</ul>
  <div class='badge'>Filtros aplicados: {_esc(filters_summary)}</div>
</header>

<section class='section'><h2>Resumen de cambios</h2><div class='kpis'>{kpi_html or '<div class="finding-mini">No se encontraron métricas comparables entre los archivos.</div>'}</div></section>

{f'<section class="section"><h2>Lectura ejecutiva</h2><div class="findings">{signals_html}</div></section>' if signals_html else ''}

{f'<section class="section"><h2>Cambios por categoría</h2>{"".join(dim_tables)}</section>' if dim_tables else ''}

{f'<section class="section"><h2>Evolución a través de los archivos</h2>{"".join(chart_blocks)}</section>' if chart_blocks else ''}

{records_section}

<section class='section'><div class='table-card'><h3>Variables que se cruzaron entre archivos</h3><table><thead><tr><th>Columna (primer archivo)</th><th>Columna equivalente (último)</th><th>Coincidencia</th><th>Tipo</th></tr></thead><tbody>{match_rows or '<tr><td colspan="4">No se encontraron variables equivalentes.</td></tr>'}</tbody></table></div></section>

<footer class='footer'>Informe generado automáticamente por Panel Analítico Universal · Refleja los filtros que tenías activos al momento de exportar.</footer>
</main></body></html>"""


def _pretty_technical_safe(value: str) -> str:
    try:
        from ui.labels import pretty_technical
        return pretty_technical(value)
    except Exception:
        return str(value)
