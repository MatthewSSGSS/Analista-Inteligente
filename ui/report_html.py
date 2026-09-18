from __future__ import annotations

import html
from datetime import datetime
from typing import Iterable

import numpy as np
import pandas as pd

from core.quality import assess
from ui.labels import clean_display_text
from ui.report_secciones import (CSS as CSS_SECCIONES, bloque_cambio_periodos,
                                 bloque_cuadro_comparativo, bloque_estrategia, bloque_planes)
from core.dashboard_engine import build_dashboard
from core.geo_engine import geographic_summary, supports_georeferencing
from core.universal_analysis import semantic_map, ADDITIVE, drilldown_table
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
    if k.get("kind") == "leader":
        # Para "Líder · X" el 'value' es el NOMBRE (ej. "Bogotá"), no un
        # número — antes se mostraba solo ese nombre, sin el "· 61.7M" que
        # sí llevaba la versión en pantalla: el informe exportado se veía
        # con menos información que la propia app, no solo distinta.
        raw = k.get("raw")
        if isinstance(raw, (int, float, np.integer, np.floating)) and not isinstance(raw, bool):
            return f"{value} · {_fmt(raw)}"
        return str(value) if value is not None else "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        if k.get("kind") == "growth":
            return f"{value:+.1f}%"
        return _fmt(value)
    return str(value) if value is not None else "—"


def _kpi_label(k: dict, schema: dict) -> str:
    """Etiqueta de una tarjeta KPI — "Líder · Ciudad" no decía de qué
    métrica (¿ingresos? ¿unidades?); se agrega el nombre de la métrica,
    igual criterio que la versión en pantalla (`ui/dashboard.py::_kpi_style`)."""
    label = k.get("label", "Indicador")
    if k.get("kind") == "leader" and k.get("metric"):
        label = f"{label} · {_label(schema, k['metric'])}"
    return label


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


def _evidence_html(item: dict) -> str:
    """Los nombres y cifras que sostienen el hallazgo, dentro del informe.

    El informe es lo que se comparte y se lee sin la app al lado, así que es
    justo donde más falta hace que el hallazgo diga QUIÉN va mal y cuánto, y
    no solo que algo va mal.
    """
    evidencia = item.get("evidence") if isinstance(item, dict) else None
    if not evidencia:
        return ""
    filas = []
    for e in list(evidencia)[:4]:
        nombre = _esc(clean_display_text(e.get("nombre", "")))
        valor = _esc(clean_display_text(e.get("valor", "")))
        detalle = _esc(clean_display_text(e.get("detalle", "")))
        filas.append(f"<li><span class='ev-name'>{nombre}</span><span class='ev-value'>{valor}</span>"
                     f"<span class='ev-detail'>{detalle}</span></li>")
    return f"<ul class='evidence'>{''.join(filas)}</ul>"


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
    # Antes solo se mostraban 4 de las 6 métricas que `assess()` ya calcula
    # — consistencia y validez se computaban pero nunca llegaban al informe.
    # Se agregan aquí sin ningún cálculo nuevo, solo mostrando lo que ya
    # existía — AL FINAL de la lista, no intercaladas: build_workbook_html_report
    # lee `quality[0]`/`[1]`/`[2]` por posición (Calidad global/Completitud/
    # Duplicados) para su cálculo ponderado; insertarlas en medio corría esos
    # índices y hacía que "Duplicados" leyera el valor de "Consistencia".
    return [
        ("Calidad global", f"{q['score']:.0f}/100", "Lectura de completitud, consistencia y validez"),
        ("Completitud", f"{q['completeness']:.1f}%", "Campos con información disponible"),
        ("Duplicados", f"{q['duplicate_rows']:,}", "Filas duplicadas detectadas"),
        ("Columnas", f"{len(df.columns):,}", "Campos incluidos en el análisis"),
        ("Consistencia", f"{q['consistency']:.1f}%", "Qué tan libres de duplicados están los registros"),
        ("Validez", f"{q['validity']:.1f}%", "Formato de los datos dentro de lo esperado"),
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


def _build_charts(df: pd.DataFrame, schema: dict, dashboard: dict, include_geo: bool = True,
                  incluir_motor: bool = True) -> list[str]:
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

    # El motor de Plotly (~3.5 MB) va incrustado UNA sola vez por documento:
    # en el informe de todo el Excel cada hoja llamaba aquí y metía su propia
    # copia, y el archivo llegaba a 58 MB —imposible de enviar por correo—
    # cuando con una sola copia pesa una fracción de eso.
    blocks = []
    for i, (title, subtitle, fig) in enumerate(charts, 1):
        blocks.append(_chart_block(title, subtitle, fig, i, include_js=(incluir_motor and i == 1)))
    return blocks


def _narrative_summary(df: pd.DataFrame, schema: dict, dashboard: dict, primary, dims) -> str:
    """Frase ejecutiva de una línea combinando lo que el archivo realmente
    tiene — nunca inventa una métrica o dimensión que no exista.
    """
    n = len(df)
    parts = [f"El análisis de la selección actual recorre {n:,} registros"]
    if primary and primary in df.columns:
        sem = semantic_map(schema).get(primary, "")
        s = pd.to_numeric(df[primary], errors="coerce").dropna()
        if len(s):
            value = float(s.sum()) if sem in ADDITIVE else float(s.mean())
            verb = "con un total de" if sem in ADDITIVE else "con un promedio de"
            parts.append(f"{verb} {_esc(_label(schema, primary)).lower()} de {_fmt(value)}")
    if dims:
        first_dim = dims[0]
        if first_dim in df.columns:
            unique_n = df[first_dim].nunique(dropna=True)
            if unique_n:
                parts.append(f"distribuidos en {unique_n:,} valores distintos de {_esc(_label(schema, first_dim)).lower()}")
    change = dashboard.get("change_analysis") or {}
    if change and change.get("pct") is not None:
        pct = change["pct"]
        direction = "mejoró" if pct > 0 else "empeoró" if pct < 0 else "se mantuvo estable"
        parts.append(f"el indicador principal {direction} {abs(pct):.1f}% frente al periodo anterior")
    return ", ".join(parts) + "."


def _executive_block(dashboard: dict) -> str:
    """Lectura ejecutiva: el titular, su explicación y las dos listas que el
    motor ya separa (señales a favor y puntos de atención).

    Todo esto ya se calculaba en core/executive.py y se mostraba en la app,
    pero el informe exportado —el que de verdad se presenta— lo ignoraba por
    completo. Es la sección que más rinde en una presentación: dice en dos
    líneas cómo va el negocio antes de que nadie mire un gráfico.
    """
    ex = dashboard.get("executive") or {}
    if not ex or not ex.get("headline"):
        return ""
    status = ex.get("status", "neutral")
    positive = [p for p in (ex.get("positive") or []) if p]
    watch = [w for w in (ex.get("watch") or []) if w]
    chips = ""
    if ex.get("change") is not None:
        pct = float(ex["change"])
        arrow = "▲" if pct > 0 else "▼" if pct < 0 else "="
        chips = f"<div class='exec-delta {status}'>{arrow} {abs(pct):.1f}%</div>"
    lists = ""
    if positive:
        items = "".join(f"<li>{_esc(clean_display_text(p))}</li>" for p in positive[:5])
        lists += f"<div class='signal positive'><h4>A favor</h4><ul>{items}</ul></div>"
    if watch:
        items = "".join(f"<li>{_esc(clean_display_text(w))}</li>" for w in watch[:5])
        lists += f"<div class='signal watch'><h4>Requiere atención</h4><ul>{items}</ul></div>"
    return (
        f"<section class='section' id='lectura-ejecutiva'>"
        f"<div class='sec-head'><span class='sec-num'>01</span><div><h2>Lectura ejecutiva</h2>"
        f"<p>La conclusión primero: cómo cerró el indicador principal y qué lo explica.</p></div></div>"
        f"<div class='exec-card {status}'>"
        f"<div class='exec-main'><h3>{_esc(clean_display_text(ex.get('headline', '')))}</h3>"
        f"<p>{_esc(clean_display_text(ex.get('detail', '')))}</p></div>{chips}</div>"
        f"{f'<div class=chartrow>{lists}</div>' if lists else ''}</section>"
    )


def _concentration_block(dashboard: dict, schema: dict) -> str:
    """Concentración: cuánto pesa cada grupo sobre el total, y cuánto se
    acumula en los primeros. Responde la pregunta que sigue siempre a un
    total ("¿de dónde sale?") y detecta dependencia excesiva de un solo
    grupo, que es un riesgo de negocio real.

    Se apoya en dashboard["performance"], que el motor ya calculaba y el
    informe tampoco usaba.
    """
    perf = dashboard.get("performance") or {}
    top = perf.get("top") or []
    total = perf.get("total")
    if not top or not total:
        return ""
    dim_label = _label(schema, perf.get("dimension", ""))
    metric_label = _label(schema, perf.get("metric", ""))
    rows, acumulado = [], 0.0
    for name, value in top[:10]:
        share = (float(value) / float(total) * 100) if total else 0.0
        acumulado += share
        rows.append(
            f"<tr><td><b>{_esc(clean_display_text(name))}</b></td><td class='num'>{_fmt(value)}</td>"
            f"<td class='num'>{share:.1f}%</td><td class='num muted'>{acumulado:.1f}%</td>"
            f"<td class='barcell'><span class='bar' style='width:{min(share, 100):.1f}%'></span></td></tr>"
        )
    lider, lider_val = top[0]
    lider_share = (float(lider_val) / float(total) * 100) if total else 0.0
    top3 = sum(float(v) for _, v in top[:3]) / float(total) * 100 if total else 0.0
    groups = perf.get("groups") or len(top)
    # "sobre N valores de X" y no "N Xs": el nombre de la dimensión lo pone
    # el archivo del usuario (Ciudad, Local, Canal...) y pluralizarlo a mano
    # produce cosas como "5 ciudads". Esta forma funciona con cualquier
    # nombre, venga como venga escrito.
    universo = f"{groups:,} valores de {_esc(dim_label.lower())}"
    if lider_share >= 50:
        veredicto = (f"Alta concentración: <b>{_esc(clean_display_text(str(lider)))}</b> concentra el "
                     f"{lider_share:.1f}% del total sobre {universo}. Una caída ahí arrastra el resultado completo.")
    elif top3 >= 70:
        veredicto = (f"Concentración moderada-alta: los 3 primeros suman el {top3:.1f}% del total, "
                     f"sobre {universo}.")
    else:
        veredicto = (f"Distribución repartida: los 3 primeros suman el {top3:.1f}% del total "
                     f"sobre {universo}, sin dependencia de un solo grupo.")
    return (
        f"<section class='section' id='concentracion'>"
        f"<div class='sec-head'><span class='sec-num'>04</span><div><h2>Concentración del resultado</h2>"
        f"<p>De dónde sale {_esc(metric_label.lower())}: peso de cada {_esc(dim_label.lower())} sobre el total.</p></div></div>"
        f"<div class='callout'>{veredicto}</div>"
        f"<div class='table-card'><table><thead><tr><th>{_esc(dim_label)}</th><th class='num'>{_esc(metric_label)}</th>"
        f"<th class='num'>% del total</th><th class='num'>Acumulado</th><th>Peso</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div></section>"
    )


def _statistics_block(dashboard: dict, schema: dict) -> str:
    """Estadística descriptiva por métrica: promedio, mediana, dispersión y
    cuartiles. Es lo que permite decir si un promedio representa al conjunto
    o lo distorsiona un puñado de valores extremos."""
    stats = dashboard.get("statistics")
    if stats is None or not hasattr(stats, "empty") or stats.empty:
        return ""
    rows = []
    for _, r in stats.head(12).iterrows():
        col = r.get("Columna", "")
        media, mediana = r.get("Media"), r.get("Mediana")
        lectura = ""
        try:
            if pd.notna(media) and pd.notna(mediana) and float(mediana) != 0:
                sesgo = (float(media) - float(mediana)) / abs(float(mediana)) * 100
                if sesgo > 25:
                    lectura = "Promedio inflado por valores altos: la mediana representa mejor el caso típico."
                elif sesgo < -25:
                    lectura = "Promedio arrastrado por valores bajos: revisar la cola inferior."
                else:
                    lectura = "Promedio y mediana cercanos: el promedio es representativo."
        except (TypeError, ValueError):
            lectura = ""
        rows.append(
            f"<tr><td><b>{_esc(_label(schema, col))}</b></td><td class='num'>{_fmt(r.get('Media'))}</td>"
            f"<td class='num'>{_fmt(r.get('Mediana'))}</td><td class='num'>{_fmt(r.get('Std'))}</td>"
            f"<td class='num'>{_fmt(r.get('Min'))}</td><td class='num'>{_fmt(r.get('Max'))}</td>"
            f"<td class='muted'>{_esc(lectura)}</td></tr>"
        )
    return (
        f"<section class='section' id='estadistica'>"
        f"<div class='sec-head'><span class='sec-num'>07</span><div><h2>Estadística descriptiva</h2>"
        f"<p>Cómo se comporta cada métrica: valor típico, dispersión y extremos.</p></div></div>"
        f"<div class='table-card'><table><thead><tr><th>Métrica</th><th class='num'>Promedio</th>"
        f"<th class='num'>Mediana</th><th class='num'>Desviación</th><th class='num'>Mínimo</th>"
        f"<th class='num'>Máximo</th><th>Lectura</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>"
    )


def _anomalies_block(dashboard: dict, schema: dict) -> str:
    """Valores atípicos detectados. Se muestran los primeros y se dice
    cuántos hay en total: en una presentación importa el orden de magnitud
    ("hay 27 que revisar"), no la lista completa."""
    anomalies = dashboard.get("anomalies")
    if anomalies is None or not hasattr(anomalies, "empty") or anomalies.empty:
        return ""
    total = len(anomalies)
    rows = []
    for _, r in anomalies.head(12).iterrows():
        rows.append(
            f"<tr><td class='num muted'>{_esc(r.get('fila', ''))}</td>"
            f"<td><b>{_esc(_label(schema, r.get('columna', '')))}</b></td>"
            f"<td class='num'>{_fmt(r.get('valor'))}</td>"
            f"<td><span class='pill'>{_esc(clean_display_text(str(r.get('tipo', ''))))}</span></td></tr>"
        )
    extra = (f"<p class='muted' style='margin-top:10px'>Se muestran 12 de {total:,} valores atípicos detectados.</p>"
             if total > 12 else "")
    return (
        f"<section class='section' id='atipicos'>"
        f"<div class='sec-head'><span class='sec-num'>08</span><div><h2>Valores atípicos</h2>"
        f"<p>Registros que se salen del comportamiento normal del conjunto. No son errores por definición, "
        f"pero conviene confirmarlos antes de dar el dato por bueno.</p></div></div>"
        f"<div class='callout warn'><b>{total:,}</b> registro(s) fuera de rango esperado.</div>"
        f"<div class='table-card'><table><thead><tr><th class='num'>Fila</th><th>Columna</th>"
        f"<th class='num'>Valor</th><th>Tipo</th></tr></thead><tbody>{''.join(rows)}</tbody></table>{extra}</div></section>"
    )


def build_html_report(df: pd.DataFrame, schema: dict, dashboard: dict, filename: str, sheet: str, scope_label: str = "Selección actual") -> str:
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")
    metrics = metric_candidates(df, schema)
    dims = dimension_candidates(df, schema)
    primary = dashboard.get("primary_metric") or (metrics[0] if metrics else None)
    quality = _quality_cards(df, schema)
    narrative = _narrative_summary(df, schema, dashboard, primary, dims)

    kpis = dashboard.get("kpis") or []
    kpi_html_all = []
    for k in kpis[:8]:
        kpi_html_all.append(f"<div class='kpi'><div class='kpi-label'>{_esc(_kpi_label(k, schema))}</div><div class='kpi-value'>{_esc(_kpi_value(k))}</div></div>")
    kpi_html_top4 = "".join(kpi_html_all[:4])
    # La portada ya destaca el indicador principal y el cambio, así que la
    # sección de KPIs puede mostrarlos todos sin resultar repetitiva (antes
    # se recortaba a 4 porque era lo primero que se veía del informe).
    kpi_html_all_html = "".join(kpi_html_all)

    insights = dashboard.get("insights") or []
    insight_html = []
    for item in insights[:8]:
        title, finding, action, implication = _insight_text(item if isinstance(item, dict) else {})
        kind = item.get("kind", "info") if isinstance(item, dict) else "info"
        # Estos dos bloques se arman fuera del f-string a propósito. Antes iban
        # dentro de las llaves con comillas escapadas (\"), y una barra
        # invertida dentro de la expresión de un f-string es un error de
        # sintaxis en Python 3.11: el informe entero no llegaba a importarse.
        accion_html = f"<div class='action'><b>Qué revisar:</b> {_esc(action)}</div>" if action else ""
        implicacion_html = (f"<div class='implication'><b>Implicación:</b> {_esc(implication)}</div>"
                            if implication else "")
        insight_html.append(
            f"<article class='insight {kind}'><div class='insight-tag'>{_esc(kind.upper())}</div><h3>{_esc(title)}</h3>"
            f"<p>{_esc(finding)}</p>{_evidence_html(item if isinstance(item, dict) else {})}"
            f"{accion_html}{implicacion_html}</article>"
        )

    alerts = dashboard.get("alerts") or []
    alert_html = []
    for a in alerts[:8]:
        if not isinstance(a, dict):
            continue
        alert_html.append(
            f"<tr><td><span class='severity'>{_esc(clean_display_text(a.get('severity','')))}</span></td><td><b>{_esc(clean_display_text(a.get('title','Hallazgo')))}</b><br><span class='muted'>{_esc(clean_display_text(a.get('text','')))}</span>{_evidence_html(a)}</td>"
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

    # Top 10 / Bottom 10 por la primera dimensión disponible — el mismo par
    # de tablas que se ve arriba de todo en el informe, lado a lado.
    top_bottom_html = ""
    if primary and dims:
        top_df = drilldown_table(df, schema, primary, dims[0], limit=10, ascending=False)
        bottom_df = drilldown_table(df, schema, primary, dims[0], limit=10, ascending=True)
        def _tb_rows(t):
            return "".join(f"<tr><td>{i+1}</td><td>{_esc(r[dims[0]])}</td><td>{_fmt(r['Valor'])}</td></tr>" for i, r in t.iterrows())
        if not top_df.empty:
            top_bottom_html = f"""
            <div class="table-card"><h3>🏆 Top 10 · mayor {_esc(_label(schema, primary)).lower()}</h3>
            <table><thead><tr><th>#</th><th>{_esc(_label(schema, dims[0]))}</th><th>{_esc(_label(schema, primary))}</th></tr></thead><tbody>{_tb_rows(top_df)}</tbody></table></div>
            <div class="table-card"><h3>🔻 Bottom 10 · menor {_esc(_label(schema, primary)).lower()}</h3>
            <table><thead><tr><th>#</th><th>{_esc(_label(schema, dims[0]))}</th><th>{_esc(_label(schema, primary))}</th></tr></thead><tbody>{_tb_rows(bottom_df)}</tbody></table></div>
            """

    quality_rows = "".join(f"<tr><td>{_esc(c)}</td><td>{_esc(v)}</td><td>{_esc(s)}</td></tr>" for c,v,s in quality)

    # Los primeros DOS gráficos (evolución + distribución, cuando existen)
    # se muestran grandes y lado a lado justo después del resumen — igual
    # que el resto de gráficos, se adaptan a lo que el archivo realmente
    # tiene. El resto queda como material de apoyo más abajo.
    chart_blocks = _build_charts(df, schema, dashboard, include_geo=True)

    # ── Secciones de decisión (mismas que las pestañas del panel) ──────────
    # Los gráficos siguen la numeración de los de arriba, y si el informe no
    # tuviera ningún gráfico universal, el primero de estos carga el motor de
    # Plotly: sin él, los demás quedarían en blanco al abrir el archivo.
    estado_js = {"pendiente": not chart_blocks, "n": len(chart_blocks)}

    def _numerar() -> int:
        estado_js["n"] += 1
        return estado_js["n"]

    def _bloque(titulo, subtitulo, fig, numero) -> str:
        incluir = estado_js["pendiente"]
        estado_js["pendiente"] = False
        return _chart_block(titulo, subtitulo, fig, numero, include_js=incluir)

    try:
        cuadro_html = bloque_cuadro_comparativo(df, schema, primary, _bloque, _numerar)
    except Exception:
        cuadro_html = ""
    try:
        cambio_periodos_html = bloque_cambio_periodos(df, schema, primary, _bloque, _numerar)
    except Exception:
        cambio_periodos_html = ""
    try:
        estrategia_html = bloque_estrategia(df, schema)
    except Exception:
        estrategia_html = ""
    try:
        planes_html = bloque_planes(df, schema, dashboard)
    except Exception:
        planes_html = ""

    primary_charts_html = "".join(chart_blocks[:2])
    secondary_chart_blocks = chart_blocks[2:]
    if not chart_blocks:
        primary_charts_html = "<div class='empty'>No hubo suficientes variables para construir gráficos universales con significado.</div>"
    secondary_chart_html = "".join(secondary_chart_blocks)

    schema_summary = f"""
    <section class="table-card" id="motor">
      <div class="sec-head"><span class="sec-num">11</span><div><h2>Cómo se interpretó el archivo</h2><p>Qué reconoció el motor en esta hoja.</p></div></div>
      <div class="meta-grid">
        <div><b>{len(metrics)}</b><span>Métricas</span></div>
        <div><b>{len(schema.get('dates', []))}</b><span>Fechas</span></div>
        <div><b>{len(dims)}</b><span>Dimensiones</span></div>
        <div><b>{len(schema.get('ids', []))}</b><span>Identificadores</span></div>
      </div>
      <p class="muted">El informe no presupone una estructura fija: los gráficos y secciones se activan según lo que realmente contiene este Excel.</p>
    </section>
    """

    # ── Secciones de análisis que el motor ya calculaba y este informe no
    # mostraba (lectura ejecutiva, concentración, estadística y atípicos).
    # Cada una se autodescarta si el archivo no da para ella. ──
    executive_html = _executive_block(dashboard)
    concentration_html = _concentration_block(dashboard, schema)
    statistics_html = _statistics_block(dashboard, schema)
    anomalies_html = _anomalies_block(dashboard, schema)

    # ── Portada: los números que abren la presentación ──
    growth = dashboard.get("growth")
    growth_stat = ""
    if growth is not None:
        tone = "up" if growth > 0 else "down" if growth < 0 else ""
        arrow = "▲" if growth > 0 else "▼" if growth < 0 else "="
        growth_stat = (f"<div class='cover-stat {tone}'><b>{arrow} {abs(growth):.1f}%</b>"
                       f"<span>vs periodo anterior</span></div>")
    headline_kpi = ""
    for k in kpis:
        if isinstance(k, dict) and k.get("kind") == "primary":
            headline_kpi = (f"<div class='cover-stat'><b>{_esc(_kpi_value(k))}</b>"
                            f"<span>{_esc(_kpi_label(k, schema))}</span></div>")
            break
    cover_stats = (
        f"<div class='cover-stat'><b>{len(df):,}</b><span>Registros analizados</span></div>"
        f"{headline_kpi}{growth_stat}"
        f"<div class='cover-stat'><b>{len(dims):,}</b><span>Dimensiones</span></div>"
    )

    # ── Menú lateral: agrupado por bloques y numerado. Solo enlaza a
    # secciones que de verdad existen en este informe, para no dejar
    # enlaces muertos cuando el archivo no da para alguna. ──
    nav_groups = [("Resumen", []), ("Análisis", []), ("Detalle y soporte", [])]
    if executive_html:
        nav_groups[0][1].append(("lectura-ejecutiva", "Lectura ejecutiva"))
    nav_groups[0][1].append(("resumen", "Indicadores clave"))
    nav_groups[1][1].append(("vista-principal", "Gráficos principales"))
    if concentration_html:
        nav_groups[1][1].append(("concentracion", "Concentración"))
    if top_bottom_html:
        nav_groups[1][1].append(("top-bottom", "Top y Bottom 10"))
    if change_html:
        nav_groups[1][1].append(("cambio", "Cambio principal"))
    if cuadro_html:
        nav_groups[1][1].append(("cuadro-comparativo", "Cómo va cada uno"))
    if cambio_periodos_html:
        nav_groups[1][1].append(("cambio-periodos", "Qué cambió y quién lo explica"))
    if estrategia_html:
        nav_groups[1][1].append(("estrategia", "Estrategia por canal"))
    if planes_html:
        nav_groups[1][1].append(("planes", "Planes de mejora"))
    nav_groups[1][1].append(("lectura", "Lectura analítica"))
    if statistics_html:
        nav_groups[2][1].append(("estadistica", "Estadística"))
    if anomalies_html:
        nav_groups[2][1].append(("atipicos", "Valores atípicos"))
    nav_groups[2][1].append(("alertas", "Alertas"))
    if secondary_chart_html:
        nav_groups[2][1].append(("graficos", "Otros gráficos"))
    nav_groups[2][1].append(("motor", "Cómo se interpretó"))
    nav_groups[2][1].append(("calidad", "Calidad del dato"))

    nav_parts, counter = [], 0
    for group_label, items in nav_groups:
        if not items:
            continue
        nav_parts.append(f'<div class="nav-group">{_esc(group_label)}</div>')
        for sid, label in items:
            counter += 1
            nav_parts.append(f'<a href="#{sid}"><i>{counter:02d}</i>{_esc(label)}</a>')
    nav_html = "".join(nav_parts)

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Resumen analítico — {_esc(filename)}</title>
<style>
/* ===== Paleta del informe =====
   Antes el token de marca se llamaba --blue pero valía rojo, y el rojo
   "negativo" era casi el mismo tono: en una tabla no se distinguía un dato
   de marca de una alerta. Ahora la marca es --brand y los colores de estado
   (bien / atención / mal) son familias aparte, para que el color signifique
   algo. La tinta del texto sube de contraste (#0f172a) porque este
   documento se proyecta y se imprime, no solo se lee en pantalla. */
:root{{--bg:#eef1f7;--card:#fff;--ink:#0f172a;--text:#1e293b;--muted:#64748b;--soft:#94a3b8;
--line:#e2e8f0;--line-soft:#eef2f7;--brand:#e4002b;--brand-dark:#b00020;--brand-soft:#fff1f3;
--pos:#0f8a5f;--pos-soft:#e8f7f0;--warn:#b45309;--warn-soft:#fef6e7;--neg:#be123c;--neg-soft:#fff1f3;
--shadow:0 1px 2px rgba(15,23,42,.04),0 6px 20px rgba(15,23,42,.06);
--shadow-lg:0 2px 4px rgba(15,23,42,.04),0 16px 40px rgba(15,23,42,.10)}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif;line-height:1.5;scroll-behavior:smooth;-webkit-font-smoothing:antialiased}}
.report-shell{{display:flex;align-items:flex-start;gap:26px;max-width:1560px;margin:0 auto;padding:26px 24px 70px}}
.wrap{{flex:1;min-width:0}}

/* ===== Menú: agrupado por bloques y numerado. Antes era una lista plana de
   10 enlaces sin jerarquía; con el informe más largo hace falta saber en qué
   parte del documento se está parado. ===== */
.side-nav{{width:232px;flex:0 0 232px;position:sticky;top:20px;align-self:flex-start;max-height:calc(100vh - 40px);overflow-y:auto;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px 14px;box-shadow:var(--shadow)}}
.side-nav .nav-brand{{display:flex;align-items:center;gap:9px;padding:0 6px 14px;border-bottom:1px solid var(--line-soft);margin-bottom:12px}}
.side-nav .nav-dot{{width:26px;height:26px;border-radius:50%;background:radial-gradient(circle at 32% 28%,#ff4d5f,var(--brand) 60%,var(--brand-dark));flex:0 0 26px}}
.side-nav .nav-brand b{{font-size:12.5px;letter-spacing:-.01em;color:var(--ink);line-height:1.2;display:block}}
.side-nav .nav-brand small{{font-size:10px;color:var(--soft)}}
.nav-group{{font-size:9.5px;font-weight:800;letter-spacing:.12em;color:var(--soft);text-transform:uppercase;margin:14px 8px 6px}}
.nav-group:first-of-type{{margin-top:2px}}
.side-nav a{{display:flex;align-items:center;gap:9px;padding:7px 9px;border-radius:9px;font-size:12.5px;color:var(--text);text-decoration:none;margin-bottom:1px;border-left:3px solid transparent;transition:background .12s ease,color .12s ease}}
.side-nav a i{{font-style:normal;font-size:9.5px;font-weight:800;color:var(--soft);min-width:15px}}
.side-nav a:hover{{background:var(--line-soft);color:var(--brand)}}
.side-nav a.active{{background:var(--brand-soft);color:var(--brand-dark);border-left-color:var(--brand);font-weight:700}}
.side-nav a.active i{{color:var(--brand)}}

/* ===== Portada ===== */
.cover{{background:linear-gradient(135deg,#12172b 0%,#1e2440 55%,#3a1020 100%);border-radius:18px;padding:30px 34px;color:#fff;box-shadow:var(--shadow-lg);position:relative;overflow:hidden}}
.cover:before{{content:"";position:absolute;right:-90px;top:-90px;width:320px;height:320px;border-radius:50%;background:radial-gradient(circle,rgba(228,0,43,.42),transparent 68%)}}
.cover-kicker{{font-size:10.5px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:#ff8095;position:relative}}
.cover h1{{margin:9px 0 8px;font-size:31px;letter-spacing:-.03em;line-height:1.12;position:relative}}
.cover .lead{{color:#c7cede;font-size:14px;max-width:640px;position:relative;margin:0}}
.cover-stats{{display:flex;flex-wrap:wrap;gap:26px;margin-top:22px;padding-top:19px;border-top:1px solid rgba(255,255,255,.14);position:relative}}
.cover-stat b{{display:block;font-size:23px;font-weight:800;letter-spacing:-.02em}}
.cover-stat span{{font-size:10.5px;color:#9aa3bb;text-transform:uppercase;letter-spacing:.08em;font-weight:700}}
.cover-stat.up b{{color:#5ee0a4}}
.cover-stat.down b{{color:#ff8095}}
.meta{{display:flex;flex-wrap:wrap;gap:7px;margin-top:16px}}
.meta span{{background:var(--card);border:1px solid var(--line);border-radius:999px;padding:6px 11px;font-size:11px;color:var(--muted)}}

/* ===== Secciones ===== */
.section{{margin-top:34px;scroll-margin-top:18px}}
.sec-head{{display:flex;gap:13px;align-items:flex-start;margin-bottom:14px;padding-bottom:11px;border-bottom:2px solid var(--line)}}
.sec-num{{font-size:11px;font-weight:800;color:var(--brand);background:var(--brand-soft);border-radius:7px;padding:5px 8px;letter-spacing:.04em;flex:0 0 auto;margin-top:2px}}
.sec-head h2,.section>h2,.table-card h2{{font-size:20px;margin:0;letter-spacing:-.022em;color:var(--ink)}}
.sec-head p,.section>p,.table-card>p{{margin:4px 0 0;color:var(--muted);font-size:12.5px;max-width:78ch}}
.section>h2{{margin-bottom:5px}}

/* ===== KPIs ===== */
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(178px,1fr));gap:12px}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:16px 17px;box-shadow:var(--shadow);position:relative;overflow:hidden}}
.kpi:before{{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--brand)}}
.kpi-label{{font-size:10.5px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.05em}}
.kpi-value{{font-size:26px;font-weight:800;margin-top:7px;letter-spacing:-.025em;color:var(--ink)}}
.narrative{{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--brand);border-radius:12px;padding:15px 17px;font-size:13.5px;margin:0 0 15px;box-shadow:var(--shadow)}}

/* ===== Lectura ejecutiva ===== */
.exec-card{{display:grid;grid-template-columns:1fr auto;gap:20px;align-items:center;background:var(--card);border:1px solid var(--line);border-left:5px solid var(--muted);border-radius:14px;padding:20px 22px;box-shadow:var(--shadow)}}
.exec-card.positive{{border-left-color:var(--pos)}}
.exec-card.negative{{border-left-color:var(--neg)}}
.exec-card.warning{{border-left-color:var(--warn)}}
.exec-main h3{{margin:0 0 6px;font-size:19px;letter-spacing:-.02em;color:var(--ink);line-height:1.3}}
.exec-main p{{margin:0;color:var(--muted);font-size:13px}}
.exec-delta{{font-size:27px;font-weight:800;letter-spacing:-.02em;white-space:nowrap;padding:9px 15px;border-radius:12px;background:var(--line-soft);color:var(--muted)}}
.exec-delta.positive{{background:var(--pos-soft);color:var(--pos)}}
.exec-delta.negative{{background:var(--neg-soft);color:var(--neg)}}
.exec-delta.warning{{background:var(--warn-soft);color:var(--warn)}}
.chartrow{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:13px;margin-top:13px}}
.signal{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;box-shadow:var(--shadow)}}
.signal h4{{margin:0 0 8px;font-size:11px;letter-spacing:.09em;text-transform:uppercase}}
.signal.positive h4{{color:var(--pos)}}
.signal.watch h4{{color:var(--warn)}}
.signal ul{{margin:0;padding-left:17px;font-size:13px}}
.signal li{{margin-bottom:4px}}

/* ===== Avisos y píldoras ===== */
.callout{{background:var(--brand-soft);border:1px solid rgba(228,0,43,.18);border-radius:11px;padding:12px 15px;font-size:13px;margin-bottom:13px;color:var(--ink)}}
.callout.warn{{background:var(--warn-soft);border-color:rgba(180,83,9,.2)}}
.pill{{font-size:10px;font-weight:700;padding:3px 8px;border-radius:999px;background:var(--line-soft);color:var(--muted)}}
.severity{{font-size:10px;font-weight:800;padding:4px 8px;border-radius:999px;background:var(--warn-soft);color:var(--warn)}}

.change-box{{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--brand);border-radius:14px;padding:19px 21px;box-shadow:var(--shadow);display:grid;grid-template-columns:1fr auto;gap:4px 18px;scroll-margin-top:18px}}
.change-box span{{font-size:10px;font-weight:800;letter-spacing:.12em;color:var(--brand)}}
.change-box h2{{margin:3px 0 0;font-size:19px}}
.change-value{{font-size:31px;font-weight:800;align-self:center;color:var(--brand);letter-spacing:-.02em}}
.change-box p{{grid-column:1/-1;color:var(--muted);margin:7px 0 0}}

/* ===== Hallazgos ===== */
.insights{{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:13px}}
.evidence{{list-style:none;margin:9px 0 0;padding:8px 10px;background:#f6f8fb;border:1px solid var(--line);border-radius:9px}}
.evidence li{{display:flex;align-items:baseline;gap:8px;font-size:11.5px;line-height:1.4;padding:1px 0}}
.evidence .ev-name{{font-weight:700;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.evidence .ev-value{{font-weight:700;white-space:nowrap;font-variant-numeric:tabular-nums}}
.evidence .ev-detail{{color:var(--muted);white-space:nowrap}}
.insight{{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--brand);border-radius:12px;padding:16px 17px;box-shadow:var(--shadow)}}
.insight.warning{{border-left-color:var(--warn)}}
.insight.positive{{border-left-color:var(--pos)}}
.insight-tag{{font-size:9px;letter-spacing:.12em;font-weight:800;color:var(--soft)}}
.insight h3{{margin:6px 0 7px;font-size:14.5px;color:var(--ink)}}
.insight p{{margin:0;font-size:13px}}
.action,.implication{{margin-top:9px;background:var(--line-soft);border-radius:8px;padding:9px 10px;font-size:12px}}

/* ===== Tarjetas, tablas y barras ===== */
.grid2{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
.chart-card,.table-card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;box-shadow:var(--shadow);margin-top:13px;scroll-margin-top:18px}}
.chart-head span{{font-size:9px;color:var(--brand);font-weight:800;letter-spacing:.13em}}
.chart-head h3{{margin:4px 0 2px;font-size:15px;color:var(--ink)}}
.chart-head p{{margin:0 0 6px;color:var(--muted);font-size:11.5px}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}}
th,td{{padding:10px 9px;border-bottom:1px solid var(--line-soft);text-align:left;vertical-align:middle}}
thead th{{color:var(--soft);font-size:9.5px;text-transform:uppercase;letter-spacing:.08em;border-bottom:1.5px solid var(--line)}}
tbody tr:hover{{background:var(--line-soft)}}
td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums}}
.barcell{{width:110px}}
.bar{{display:block;height:7px;border-radius:4px;background:linear-gradient(90deg,var(--brand),#ff5b73);min-width:2px}}
.muted{{color:var(--muted)}}
.empty{{padding:26px;background:var(--card);border:1px dashed var(--line);border-radius:12px;color:var(--muted)}}
.meta-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:11px;margin:15px 0}}
.meta-grid div{{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:14px}}
.meta-grid b{{display:block;font-size:20px;color:var(--ink)}}
.meta-grid span{{color:var(--muted);font-size:11px}}
.footer{{margin-top:40px;padding-top:16px;border-top:1px solid var(--line);color:var(--soft);font-size:11px;text-align:center}}

@media(max-width:1080px){{.side-nav{{display:none}}}}
{CSS_SECCIONES}
@media(max-width:850px){{.report-shell{{padding:16px 12px}}.cover{{padding:22px 20px}}.cover h1{{font-size:24px}}.grid2,.exec-card{{grid-template-columns:1fr}}.meta-grid{{grid-template-columns:repeat(2,1fr)}}.cover-stats{{gap:16px}}}}

/* ===== Impresión / PDF =====
   Es un documento para presentar, así que las secciones grandes arrancan en
   página nueva y ninguna tarjeta se parte por la mitad. */
@media print{{
  @page{{margin:14mm}}
  .side-nav{{display:none}}
  .report-shell{{padding:0;display:block;max-width:none}}
  body{{background:#fff}}
  .cover{{background:#12172b!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
  .section{{margin-top:24px}}
  #concentracion,#estadistica,#atipicos,#calidad{{break-before:page;page-break-before:always}}
  .kpi,.insight,.chart-card,.table-card,.exec-card,.signal,.change-box{{box-shadow:none!important;break-inside:avoid;page-break-inside:avoid}}
  a[href^="#"]{{text-decoration:none;color:inherit}}
}}
</style>
</head>
<body>
<div class="report-shell">
<nav class="side-nav">
  <div class="nav-brand"><div class="nav-dot"></div><div><b>Informe analítico</b><small>{_esc(sheet)}</small></div></div>
  {nav_html}
</nav>
<main class="wrap">
<header class="cover">
  <div class="cover-kicker">Panel Analítico Universal · Informe ejecutivo</div>
  <h1>{_esc(sheet)}</h1>
  <p class="lead">Qué pasó, dónde se concentra el resultado, qué cambió frente al periodo anterior y qué conviene revisar antes de decidir.</p>
  <div class="cover-stats">{cover_stats}</div>
</header>
<div class="meta"><span>Archivo: {_esc(filename)}</span><span>Hoja: {_esc(sheet)}</span><span>Alcance: {_esc(scope_label)}</span><span>Periodo: {_esc(_date_range(df, schema))}</span><span>Generado: {_esc(generated)}</span></div>
{executive_html}
<section class="section" id="resumen">
  <div class="sec-head"><span class="sec-num">02</span><div><h2>Indicadores clave</h2><p>Las cifras que resumen la selección analizada.</p></div></div>
  <p class="narrative">{_esc(narrative)}</p>
  <div class="kpis">{kpi_html_all_html or '<div class="empty">No se detectaron KPIs universales.</div>'}</div>
</section>
<section class="section" id="vista-principal"><div class="sec-head"><span class="sec-num">03</span><div><h2>Gráficos principales</h2><p>Los indicadores más representativos detectados para esta hoja.</p></div></div><div class="grid2">{primary_charts_html}</div></section>
{concentration_html}
{f'<section class="section" id="top-bottom"><div class="sec-head"><span class="sec-num">05</span><div><h2>Top y Bottom 10</h2><p>Extremos por {_esc(_label(schema, primary))}, usando {_esc(_label(schema, dims[0]))} como categoría.</p></div></div><div class="grid2">{top_bottom_html}</div></section>' if top_bottom_html else ''}
{change_html.replace('<section class="change-box">', '<section class="change-box" id="cambio">', 1)}
{cuadro_html}
{cambio_periodos_html}
{estrategia_html}
{planes_html}
<section class="section" id="lectura"><div class="sec-head"><span class="sec-num">06</span><div><h2>Lectura analítica</h2><p>Hallazgos priorizados por el motor universal, con contexto y acción cuando existe.</p></div></div><div class="insights">{''.join(insight_html) or '<div class="empty">No se detectaron hallazgos suficientes para esta selección.</div>'}</div></section>
{statistics_html}
{anomalies_html}
<section class="section" id="alertas"><div class="sec-head"><span class="sec-num">09</span><div><h2>Alertas y puntos de atención</h2><p>Lo que el motor marca como revisable, con la acción sugerida.</p></div></div><div class="table-card"><table><thead><tr><th>Nivel</th><th>Hallazgo</th><th>Qué hacer</th></tr></thead><tbody>{''.join(alert_html) or '<tr><td colspan="3">No hay alertas relevantes.</td></tr>'}</tbody></table></div></section>
{schema_summary}
{f'<section class="section" id="graficos"><div class="sec-head"><span class="sec-num">10</span><div><h2>Otros gráficos disponibles</h2><p>Visualizaciones adicionales que complementan la vista principal.</p></div></div><div class="grid2">{secondary_chart_html}</div></section>' if secondary_chart_html else ''}
<section class="section" id="calidad"><div class="sec-head"><span class="sec-num">12</span><div><h2>Calidad del dato</h2><p>Indicadores básicos para saber si el análisis merece confianza antes de tomar decisiones.</p></div></div><div class="table-card"><table><thead><tr><th>Indicador</th><th>Valor</th><th>Interpretación</th></tr></thead><tbody>{quality_rows}</tbody></table></div></section>
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
    # El motor de Plotly viaja en el PRIMER gráfico que se dibuje en todo el
    # documento, sea de la hoja que sea: si la primera hoja no tiene gráficos,
    # lo lleva el primero de la siguiente sección que sí los tenga.
    motor = {"pendiente": True}
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
        kpi_html_all = [
            f"<div class='kpi'><div class='kpi-label'>{_esc(_kpi_label(k, schema))}</div><div class='kpi-value'>{_esc(_kpi_value(k))}</div></div>"
            for k in kpis[:6]
        ]
        kpi_html = "".join(kpi_html_all[:4])
        if not kpi_html:
            kpi_html = f"<div class='kpi'><div class='kpi-label'>Registros</div><div class='kpi-value'>{len(df):,}</div></div>"

        sheet_dims = dimension_candidates(df, schema)
        narrative = _narrative_summary(df, schema, d, r["primary"], sheet_dims)

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

        charts = _build_charts(df, schema, d, include_geo=True, incluir_motor=motor["pendiente"])
        if charts:
            motor["pendiente"] = False
        numbered_blocks = []
        for block in charts[:8]:
            chart_counter += 1
            # Renumber the visible label without rebuilding Plotly HTML.
            numbered_blocks.append(block.replace("VISUAL 01", f"VISUAL {chart_counter:02d}", 1).replace("VISUAL 02", f"VISUAL {chart_counter:02d}", 1))
        # Los primeros DOS gráficos (evolución + distribución, cuando
        # existen) se muestran grandes y lado a lado justo después de los
        # KPIs, igual que en el informe individual. El resto queda como
        # material de apoyo más abajo.
        if numbered_blocks:
            primary_charts_html = "".join(numbered_blocks[:2])
            secondary_charts_html = "".join(numbered_blocks[2:])
        else:
            primary_charts_html = "<div class='empty'>Esta hoja no tiene suficientes variables para construir visualizaciones con significado.</div>"
            secondary_charts_html = ""

        top_bottom_html = ""
        if r["primary"] and sheet_dims:
            top_df = drilldown_table(df, schema, r["primary"], sheet_dims[0], limit=10, ascending=False)
            bottom_df = drilldown_table(df, schema, r["primary"], sheet_dims[0], limit=10, ascending=True)
            def _tb_rows(t):
                return "".join(f"<tr><td>{i+1}</td><td>{_esc(row[sheet_dims[0]])}</td><td>{_fmt(row['Valor'])}</td></tr>" for i, row in t.iterrows())
            if not top_df.empty:
                top_bottom_html = f"""
                <div class="table-card"><h3>🏆 Top 10 · mayor {_esc(_label(schema, r['primary'])).lower()}</h3>
                <table><thead><tr><th>#</th><th>{_esc(_label(schema, sheet_dims[0]))}</th><th>{_esc(_label(schema, r['primary']))}</th></tr></thead><tbody>{_tb_rows(top_df)}</tbody></table></div>
                <div class="table-card"><h3>🔻 Bottom 10 · menor {_esc(_label(schema, r['primary'])).lower()}</h3>
                <table><thead><tr><th>#</th><th>{_esc(_label(schema, sheet_dims[0]))}</th><th>{_esc(_label(schema, r['primary']))}</th></tr></thead><tbody>{_tb_rows(bottom_df)}</tbody></table></div>
                """

        # Mismas secciones de decisión que el informe individual, una por hoja.
        # El motor de Plotly ya viene en el primer gráfico del libro; estos
        # solo agregan sus figuras.
        def _bloque_hoja(titulo, subtitulo, fig, numero):
            incluir = motor["pendiente"]
            motor["pendiente"] = False
            return _chart_block(titulo, subtitulo, fig, numero, include_js=incluir)

        def _numerar_hoja():
            nonlocal chart_counter
            chart_counter += 1
            return chart_counter

        secciones_hoja = []
        for constructor in (
            lambda: bloque_cuadro_comparativo(df, schema, r["primary"], _bloque_hoja, _numerar_hoja),
            lambda: bloque_cambio_periodos(df, schema, r["primary"], _bloque_hoja, _numerar_hoja),
            lambda: bloque_estrategia(df, schema),
            lambda: bloque_planes(df, schema, d),
        ):
            try:
                bloque = constructor()
            except Exception:
                bloque = ""
            if bloque:
                # El ancla ya la usa la sección del informe individual; en el
                # libro hay una por hoja, así que se hace única.
                secciones_hoja.append(bloque.replace('<section class="section" id="', f'<section class="section" id="{sheet_id}-', 1))
        secciones_hoja_html = "".join(secciones_hoja)

        qrows = "".join(f"<tr><td>{_esc(c)}</td><td>{_esc(v)}</td><td>{_esc(s)}</td></tr>" for c,v,s in r["quality"])
        sheet_sections.append(f"""
        <section class='sheet-section' id='{sheet_id}'>
          <div class='sheet-heading'><div><span class='kicker'>HOJA</span><h2>{_esc(r['sheet'])}</h2><p>{len(df):,} registros · {len(df.columns):,} columnas · {_esc(_date_range(df, schema))}</p></div><span class='sheet-primary'>{_esc(r['primary'] and _label(schema, r['primary']) or 'Sin métrica principal')}</span></div>
          <p class='narrative'>{_esc(narrative)}</p>
          <div class='kpis'>{kpi_html}</div>
          <div class='grid2'>{primary_charts_html}</div>
          {f"<div class='grid2'>{top_bottom_html}</div>" if top_bottom_html else ""}
          {secciones_hoja_html}
          <div class='sheet-detail-divider'>Detalle adicional de esta hoja</div>
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
:root{{--bg:#f4f6fa;--card:#fff;--text:#172033;--muted:#667085;--line:#dfe4ec;--line-soft:#eef1f6;--ink:#0f172a;--soft:#94a3b8;--brand:#e4002b;--brand-dark:#a80e1f;--blue:#e4002b;--teal:#10b9a6;--green:#1b9a67;--amber:#d88708;--red:#c52a3d;--shadow:0 5px 18px rgba(23,32,51,.06);--glow:0 0 0 1px rgba(228,0,43,.08),0 10px 24px rgba(228,0,43,.06)}}
{CSS_SECCIONES}
*{{box-sizing:border-box}}body{{margin:0;background:
    radial-gradient(ellipse 900px 480px at 100% 0%,rgba(228,0,43,.05),transparent 60%),
    radial-gradient(ellipse 900px 480px at 0% 100%,rgba(228,0,43,.035),transparent 60%),
    var(--bg);color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif;line-height:1.45;scroll-behavior:smooth}}
.report-shell{{display:flex;align-items:flex-start;gap:22px;max-width:1560px;margin:0 auto;padding:30px 22px 60px}}
.side-nav{{width:216px;flex:0 0 216px;position:sticky;top:20px;align-self:flex-start;max-height:calc(100vh - 40px);overflow-y:auto;background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px 14px;box-shadow:var(--shadow)}}
.side-nav .nav-title{{font-size:10px;font-weight:800;letter-spacing:.1em;color:var(--muted);text-transform:uppercase;margin:0 0 10px}}
.side-nav .nav-group{{margin-top:14px;padding-top:12px;border-top:1px solid var(--line)}}
.side-nav a{{display:block;padding:7px 9px;border-radius:8px;font-size:12.5px;color:var(--text);text-decoration:none;margin-bottom:2px;border-left:3px solid transparent;transition:background .12s ease,color .12s ease;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.side-nav a:hover{{background:#f7f9fc;color:var(--blue)}}
.side-nav a.active{{background:#fde8ea;color:var(--blue);border-left-color:var(--blue);font-weight:700}}
.wrap{{flex:1;min-width:0}}
.header{{background:#fff;border:1px solid var(--line);border-top:6px solid #e4002b;border-radius:17px;padding:28px 30px;box-shadow:var(--shadow),var(--glow)}}.kicker{{font-size:10px;font-weight:900;letter-spacing:.13em;color:#e4002b;text-transform:uppercase}}h1{{margin:6px 0 6px;font-size:31px;letter-spacing:-.03em}}.subtitle{{color:var(--muted);font-size:14px;max-width:900px}}.meta{{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}}.meta span{{background:#f7f9fc;border:1px solid var(--line);border-radius:999px;padding:7px 10px;font-size:11px;color:var(--muted)}}
.section{{margin-top:28px;scroll-margin-top:20px}}.section>h2{{font-size:21px;margin:0 0 5px}}.section>p{{margin:0 0 14px;color:var(--muted);font-size:13px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:11px}}.kpi{{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--blue);border-radius:12px;padding:14px;box-shadow:var(--shadow),var(--glow)}}.kpi-label{{font-size:10px;color:var(--muted);font-weight:800}}.kpi-value{{font-size:23px;font-weight:900;margin-top:7px}}
.table-card{{background:#fff;border:1px solid var(--line);border-radius:13px;padding:15px;box-shadow:var(--shadow),var(--glow);margin-top:10px}}.table-card h3{{margin:0 0 9px;font-size:15px}}.table-card table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:8px;border-bottom:1px solid var(--line);text-align:left}}th{{font-size:10px;color:var(--muted);text-transform:uppercase}}.muted{{color:var(--muted)}}
.findings{{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:11px}}.finding-mini{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:12px;padding:13px;box-shadow:var(--shadow),var(--glow)}}.finding-sheet{{font-size:9px;font-weight:900;letter-spacing:.1em;color:var(--blue);text-transform:uppercase;margin-bottom:5px}}.finding-mini b{{font-size:13px}}.finding-mini p{{font-size:12px;color:var(--muted);margin:6px 0 0}}
.sheet-section{{margin-top:34px;padding-top:22px;border-top:2px solid #e4e8ef;scroll-margin-top:20px}}.sheet-heading{{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:12px}}.sheet-heading h2{{margin:3px 0;font-size:23px}}.sheet-heading p{{margin:0;color:var(--muted);font-size:12px}}.sheet-primary{{padding:7px 10px;border-radius:999px;background:#fde8ea;color:var(--blue);font-size:10px;font-weight:800}}
.sheet-grid{{display:grid;grid-template-columns:1.6fr .8fr;gap:14px;margin-top:14px}}.sheet-grid h3{{font-size:15px;margin:0 0 8px}}.insights{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}}.insight{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:12px;padding:13px;box-shadow:var(--shadow)}}.insight.warning{{border-left-color:var(--amber)}}.insight.positive{{border-left-color:var(--green)}}.insight-tag{{font-size:9px;letter-spacing:.1em;font-weight:900;color:var(--muted)}}.insight h3{{font-size:13px;margin:5px 0}}.insight p{{font-size:12px;margin:0}}
.narrative{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:12px;padding:13px 15px;font-size:13px;color:var(--text);margin:10px 0 14px;box-shadow:var(--shadow)}}
.sheet-detail-divider{{font-size:10.5px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);border-top:1px solid var(--line);padding-top:16px;margin-top:20px}}
.grid2{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:14px}}.chart-card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:13px 15px;box-shadow:var(--shadow),var(--glow);overflow:hidden;scroll-margin-top:20px}}.chart-head span{{font-size:9px;color:var(--blue);font-weight:900;letter-spacing:.12em}}.chart-head h3{{margin:4px 0 2px;font-size:15px}}.chart-head p{{margin:0;color:var(--muted);font-size:11px}}.empty{{padding:18px;background:#fff;border:1px dashed var(--line);border-radius:11px;color:var(--muted);font-size:12px}}.footer{{margin-top:40px;color:#7a8495;font-size:11px;text-align:center}}
@media(max-width:1050px){{.side-nav{{display:none}}}}
@media(max-width:900px){{.grid2,.sheet-grid,.insights{{grid-template-columns:1fr}}.report-shell{{padding:18px 11px}}.sheet-heading{{flex-direction:column}}}}
@media print{{.side-nav{{display:none}}.report-shell{{padding:0;display:block}}body{{background:#fff}}.header,.kpi,.finding-mini,.narrative,.chart-card,.table-card{{box-shadow:none!important}}}}
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
