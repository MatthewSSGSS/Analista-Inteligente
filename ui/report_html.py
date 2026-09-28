"""Informes HTML descargables: el de la selección (o de una hoja), el de todo
el Excel y el comparativo entre archivos.

Estructura pensada para presentar a un equipo y decidir, no para leer de
corrido:

1. **Resumen**: el veredicto en una línea, el semáforo de frentes y las tres
   prioridades con su primer paso. Quien solo lee esto ya sabe qué hacer.
2. **Indicadores y gráficos principales**: las cifras y las dos vistas que
   explican el resultado.
3. **Decisión**: planes de mejora, estrategia por canal, cómo va cada uno y
   qué cambió entre periodos (ver `ui/report_secciones.py`).
4. **Contexto**: concentración del resultado y los hallazgos que no se
   convirtieron en plan.
5. **Anexo plegado**: estadística, atípicos, alertas restantes, otros
   gráficos y calidad del dato. Al imprimir se abre solo.

Cada hallazgo se dice una vez: si ya es un plan, no se repite como hallazgo
ni como alerta (antes el mismo "Dónde se concentra la caída" salía cuatro
veces en el mismo documento).
"""
from __future__ import annotations

import html
from datetime import datetime

import numpy as np
import pandas as pd

from core.quality import assess
from ui.labels import clean_display_text
from ui.report_base import (desplegable, documento, esc_limpio, nav, prioridades, seccion, semaforo)
from ui.report_secciones import (bloque_cambio_periodos, bloque_cuadro_comparativo, bloque_estrategia,
                                 bloque_planes, calcular_planes)
from core.dashboard_engine import build_dashboard
from core.geo_engine import geographic_summary, supports_georeferencing
from core.universal_analysis import semantic_map, ADDITIVE, drilldown_table
from visualization.charts import (
    adaptive_chart_specs,
    correlation,
    dimension_candidates,
    donut,
    geo_summary_map,
    histogram,
    rangos,
    cascada,
    metric_candidates,
    multi_trend,
    period_compare_bar,
    ranking,
    scatter,
    trend,
)

_TONO = {"positive": "pos", "negative": "neg", "warning": "warn"}


# ── Contexto: lo que el público de la presentación no sabe ────────────────
#
# Quien ve el informe proyectado no tiene el Excel ni la app al lado. Cada
# cifra tiene que poder responder "¿de dónde sale esto?" sin que el
# presentador lo explique de memoria: qué hoja, qué columna, qué periodo,
# cuántos registros y contra qué se compara. Todo eso se calcula una vez
# aquí y se reparte a las secciones.

def _contexto(df: pd.DataFrame, schema: dict, dashboard: dict, filename: str, sheet: str,
              scope_label: str = "") -> dict:
    from ui.report_base import fecha_larga, mes
    metrics = metric_candidates(df, schema)
    dims = dimension_candidates(df, schema)
    primary = dashboard.get("primary_metric") or (metrics[0] if metrics else None)
    sem = semantic_map(schema)
    suma = sem.get(primary) in ADDITIVE if primary else True
    ctx = {
        "archivo": str(filename), "hoja": str(sheet), "alcance": scope_label or "Hoja completa",
        "registros": len(df), "primary": primary, "suma": suma,
        "metrica": _label(schema, primary) if primary else None,
        "dim_col": dims[0] if dims else None,
        "dim": _label(schema, dims[0]) if dims else None,
        "n_dim": int(df[dims[0]].nunique(dropna=True)) if dims and dims[0] in df.columns else 0,
        "desde": None, "hasta": None, "mes_a": None, "mes_b": None, "fecha_col": None, "meta_col": None,
    }
    for col in schema.get("dates", []):
        if col not in df.columns:
            continue
        fechas = pd.to_datetime(df[col], errors="coerce")
        validas = fechas.dropna()
        if validas.empty:
            continue
        ctx["fecha_col"] = str(col)
        ctx["desde"], ctx["hasta"] = validas.min(), validas.max()
        # Los dos últimos meses con dato en la métrica: los mismos que usa
        # el veredicto (core/executive.py) para decir si subió o bajó.
        if primary and primary in df.columns:
            con_dato = fechas[pd.to_numeric(df[primary], errors="coerce").notna()].dropna()
        else:
            con_dato = validas
        meses = sorted(con_dato.dt.to_period("M").unique())
        if len(meses) >= 2:
            ctx["mes_a"], ctx["mes_b"] = mes(meses[-2].to_timestamp()), mes(meses[-1].to_timestamp())
        break
    if ctx["desde"] is not None:
        ctx["periodo"] = f"del {fecha_larga(ctx['desde'])} al {fecha_larga(ctx['hasta'])}"
        ctx["periodo_corto"] = f"{mes(ctx['desde'], True)} – {mes(ctx['hasta'], True)}"
    else:
        ctx["periodo"] = ctx["periodo_corto"] = "sin fechas en el archivo"
    try:
        from core.performance import columna_meta
        meta = columna_meta(df, schema, primary) if primary else None
        ctx["meta_col"] = str(meta) if meta is not None else None
    except Exception:
        pass
    return ctx


def _fuente(ctx: dict, columnas: str = "") -> str:
    """La línea «Fuente» de cada sección, siempre con los mismos datos."""
    partes = [f"Hoja «{_esc(ctx['hoja'])}» de {_esc(ctx['archivo'])}"]
    if columnas:
        partes.append(columnas)
    partes.append(f"{ctx['registros']:,} registros")
    if ctx.get("periodo_corto") and ctx.get("desde") is not None:
        partes.append(_esc(ctx["periodo_corto"]))
    if ctx.get("alcance") and "sin filtros" not in ctx["alcance"].lower():
        partes.append(_esc(ctx["alcance"]))
    return " · ".join(partes)


def _col(nombre) -> str:
    return f"columna «{_esc(nombre)}»"


def _comparacion_txt(ctx: dict) -> str:
    if ctx.get("mes_a") and ctx.get("mes_b"):
        return f"{ctx['mes_b']} frente a {ctx['mes_a']}"
    return "el último periodo frente al anterior"


def _contexto_block(ctx: dict, agenda: list[tuple[str, str]], extra_mide: list[str] = (),
                    datos: list[tuple[str, str]] = None, sid: str = "contexto") -> str:
    """Diapositiva «Sobre este informe»: de dónde salen los datos, qué se mide
    y cómo leer los colores. Es la que responde las preguntas que el público
    haría antes de creerle a cualquier cifra."""
    if datos is None:
        datos = [("Archivo", ctx["archivo"]), ("Hoja", ctx["hoja"]),
                 ("Registros", f"{ctx['registros']:,}"), ("Periodo", ctx["periodo"]),
                 ("Filtros", ctx["alcance"])]
    dl = "".join(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>" for k, v in datos if v)

    mide = []
    if ctx.get("metrica"):
        como = "sumando todos los registros" if ctx["suma"] else "como promedio de los registros"
        mide.append(f"El indicador principal es <b>{_esc(ctx['metrica'])}</b>, calculado {como}.")
    if ctx.get("mes_a"):
        mide.append(f"Para ver si mejora o empeora se compara el último mes con datos, <b>{_esc(ctx['mes_b'])}</b>, "
                    f"contra <b>{_esc(ctx['mes_a'])}</b>.")
    if ctx.get("dim"):
        mide.append(f"Los grupos se comparan por <b>{_esc(ctx['dim'])}</b> ({ctx['n_dim']:,} valores distintos).")
    if ctx.get("meta_col"):
        mide.append(f"El archivo trae meta (<b>{_esc(ctx['meta_col'])}</b>): cumplimiento = resultado ÷ meta; "
                    "100% significa meta cumplida.")
    mide += list(extra_mide)
    mide_html = "".join(f"<p>{m}</p>" for m in mide) or "<p>El archivo no tiene una métrica numérica principal.</p>"

    leyenda = (
        "<ul class='leyenda'>"
        "<li><span class='pill neg'>Crítico</span><span>Ya está afectando el resultado: requiere acción ahora.</span></li>"
        "<li><span class='pill warn'>En observación</span><span>Se está desviando: revisarlo antes de que crezca.</span></li>"
        "<li><span class='pill pos'>Oportunidad</span><span>Margen de mejora que los datos permiten ver.</span></li>"
        "</ul><p class='note'>En las cifras, <b style='color:var(--pos)'>verde</b> es una mejora y "
        "<b style='color:var(--neg)'>rojo</b> un deterioro.</p>"
    )
    agenda_html = "".join(f"<li><div><b>{_esc(t)}</b><span>{_esc(d)}</span></div></li>" for t, d in agenda)
    cuerpo = (
        "<div class='ctx-grid'>"
        f"<div class='ctx-card'><h3>📁 De dónde salen los datos</h3><dl>{dl}</dl></div>"
        f"<div class='ctx-card'><h3>📏 Qué se mide</h3>{mide_html}</div>"
        f"<div class='ctx-card'><h3>🚦 Cómo leer los colores</h3>{leyenda}</div>"
        "</div>"
        + (f"<p class='subhead' style='margin-top:20px'>Qué contiene este informe</p><ol class='agenda'>{agenda_html}</ol>"
           if agenda_html else "")
    )
    return seccion(sid, "Sobre este informe", "Qué datos se usaron, cómo se midieron y cómo leer lo que sigue.", cuerpo)


def _titular(ex: dict, ctx: dict) -> tuple[str, str]:
    """El veredicto con los meses nombrados. «Retrocedió 2.8% frente al
    periodo anterior» obliga a preguntar «¿qué periodo?»; aquí se dice."""
    titular = clean_display_text(ex.get("headline", ""))
    detalle = clean_display_text(ex.get("detail", ""))
    if ctx.get("mes_a") and ctx.get("mes_b"):
        titular = titular.replace("frente al periodo anterior", f"en {ctx['mes_b']} frente a {ctx['mes_a']}")
        if ex.get("previous") is not None and ex.get("current_period") is not None:
            que = "el total" if ctx.get("suma") else "el promedio"
            detalle = (f"{ctx.get('metrica') or 'El indicador'} pasó de {_fmt(ex['previous'])} en {ctx['mes_a']} "
                       f"a {_fmt(ex['current_period'])} en {ctx['mes_b']} ({que} de cada mes).")
            if ex.get("status") not in {"positive", "negative"} and ex.get("change") is not None:
                detalle += " La variación es pequeña: menos del umbral que se considera un cambio real."
        else:
            detalle = detalle.replace("el periodo anterior", ctx["mes_a"])
    elif ex.get("change") is None and ctx.get("metrica") and titular.startswith(f"{ctx['metrica']}:"):
        # Sin comparación posible, «Salario: 3.6M» no dice si es un total o
        # un promedio, ni por qué no se compara con nada.
        como = "total" if ctx.get("suma") else "promedio"
        titular = titular.replace(f"{ctx['metrica']}:", f"{ctx['metrica']} ({como}):", 1)
        detalle = (f"Resultado de los {ctx.get('registros', 0):,} registros. "
                   + ("El archivo no tiene fechas, así que no hay un periodo anterior contra el cual comparar."
                      if ctx.get("desde") is None else
                      "Hay menos de dos meses con datos, así que todavía no hay contra qué comparar."))
    return titular, detalle


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


def _kpi_explicacion(k: dict, schema: dict, n_registros: int | None) -> str:
    """Una línea bajo cada KPI que dice cómo se calculó: «37.7M» solo no dice
    si es un total, un promedio o un caso aislado."""
    kind = k.get("kind")
    metrica = _label(schema, k["metric"]) if k.get("metric") else "el indicador"
    registros = f" de los {n_registros:,} registros" if n_registros else ""
    if kind == "primary":
        return (f"Suma de «{metrica}»{registros}" if k.get("label") == "Total"
                else f"Promedio de «{metrica}»{registros}")
    if kind == "median":
        return "Valor del caso típico: la mitad de los registros está por encima y la mitad por debajo"
    if kind == "max":
        return "El registro individual más alto de todo el periodo"
    if kind == "leader":
        partes = [p for p in (k.get("texto"), k.get("detalle")) if p]
        return " · ".join(str(clean_display_text(p)) for p in partes) or (_fmt(k.get("raw")) if k.get("raw") is not None else "")
    return ""


def _kpi_card(k: dict, schema: dict, n_registros: int | None = None) -> str:
    """Tarjeta KPI con su explicación debajo. El líder se parte en dos
    líneas —nombre grande y su cifra debajo— porque "Bogotá · 106" en una
    sola línea no decía que 106 era un %."""
    sub = _kpi_explicacion(k, schema, n_registros)
    sub_html = f"<div class='kpi-sub'>{_esc(sub)}</div>" if sub else ""
    valor = clean_display_text(k.get("value", "—")) if k.get("kind") == "leader" else _kpi_value(k)
    return (f"<div class='kpi'><div class='kpi-label'>{_esc(_kpi_label(k, schema))}</div>"
            f"<div class='kpi-value'>{_esc(valor)}</div>{sub_html}</div>")


def _kpis_html(kpis: list, schema: dict, maximo: int = 6, n_registros: int | None = None) -> str:
    """Los KPI sin los que ya están en la portada y el veredicto (el conteo de
    registros y el cambio reciente): repetirlos era ruido."""
    tarjetas = [_kpi_card(k, schema, n_registros) for k in (kpis or [])
                if isinstance(k, dict) and k.get("kind") not in {"count", "growth"}][:maximo]
    return "".join(tarjetas)


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
    sub = f"<p>{_esc(subtitle)}</p>" if subtitle else ""
    return (f'<section class="chart-card" data-n="{chart_number}"><div class="chart-head">'
            f'<h3>{_esc(title)}</h3>{sub}</div>{plot}</section>')


# Orden en que se muestran los gráficos universales: los dos primeros van
# arriba (la evolución y quién pesa más); el resto queda en el anexo.
_PRIORIDAD_GRAFICO = {"trend": 0, "ranking": 1, "cascada": 2, "periodo": 3, "donut": 4,
                      "multi_trend": 5, "ranking2": 6, "rangos": 7, "histogram": 8,
                      "scatter": 9, "correlacion": 10, "mapa": 11}


def _build_charts(df: pd.DataFrame, schema: dict, dashboard: dict, include_geo: bool = True,
                  incluir_motor: bool = True) -> list[str]:
    metrics = metric_candidates(df, schema)
    dims = dimension_candidates(df, schema)
    primary = dashboard.get("primary_metric") or (metrics[0] if metrics else None)
    charts: list[tuple[str, str, str, object]] = []

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
        elif kind == "rangos":
            fig = rangos(df, schema, primary)
        elif kind == "histogram":
            fig = histogram(df, schema, primary, 24)
        if fig is not None:
            charts.append((kind, title, subtitle, fig))

    # La cascada del cambio: de dónde salió la subida o la caída, paso a
    # paso. Responde el "¿por qué?" que deja abierto el titular del informe.
    # Se dibuja sola solo cuando los segmentos suman el total (ver
    # visualization/charts.cascada); si no, devuelve None y no aparece.
    fig_cascada = cascada(dashboard.get("change_analysis"))
    if fig_cascada is not None:
        cambio = dashboard.get("change_analysis") or {}
        charts.append((
            "cascada", "De dónde salió el cambio",
            f"De {cambio.get('period_before','')} a {cambio.get('period_after','')}, segmento por segmento",
            fig_cascada,
        ))

    # Add a second ranking/trend by another dimension where possible.
    if primary and len(dims) >= 2:
        fig = ranking(df, schema, primary, dims[1], 10, "Suma")
        if fig is not None:
            charts.append(("ranking2", f"Ranking por {_label(schema, dims[1])}", "Concentración y rezagos en otra dimensión.", fig))

    if primary and dims:
        fig = period_compare_bar(df, schema, primary, dims[0], "Mes", "Suma", 8)
        if fig is not None:
            charts.append(("periodo", "Comparación por periodo", "Cada categoría en el periodo actual y el anterior.", fig))

    if len(metrics) >= 3:
        fig = correlation(df, schema, metrics[:8])
        if fig is not None:
            charts.append(("correlacion", "Relación entre indicadores", "Qué variables se mueven juntas o en sentidos opuestos.", fig))

    # Deduplicate by title and keep a practical report length.
    seen = set()
    unique = []
    for item in charts:
        if item[1] in seen:
            continue
        seen.add(item[1])
        unique.append(item)
    # La dona y el ranking por la misma dimensión cuentan lo mismo; con el
    # ranking y la tabla de concentración, la dona sobra.
    kinds = {k for k, *_ in unique}
    if "ranking" in kinds:
        unique = [c for c in unique if c[0] != "donut"]
    charts = sorted(unique, key=lambda c: _PRIORIDAD_GRAFICO.get(c[0], 20))[:10]

    if include_geo:
        try:
            enabled, _ = supports_georeferencing(df, schema)
            if enabled:
                geo_data = geographic_summary(df, schema)
                fig = geo_summary_map(geo_data)
                if fig is not None:
                    charts.append(("mapa", "Mapa de desempeño", "Distribución geográfica del indicador principal.", fig))
        except Exception:
            # Export must never fail just because geocoding/map support is unavailable.
            pass

    # El motor de Plotly (~3.5 MB) va incrustado UNA sola vez por documento:
    # en el informe de todo el Excel cada hoja llamaba aquí y metía su propia
    # copia, y el archivo llegaba a 58 MB —imposible de enviar por correo—
    # cuando con una sola copia pesa una fracción de eso.
    blocks = []
    for i, (kind, title, subtitle, fig) in enumerate(charts, 1):
        title, subtitle = _titulo_grafico(kind, title, subtitle, schema, dashboard, metrics, dims, primary)
        blocks.append(_chart_block(title, subtitle, fig, i, include_js=(incluir_motor and i == 1)))
    return blocks


def _titulo_grafico(kind, title, subtitle, schema, dashboard, metrics, dims, primary) -> tuple[str, str]:
    """Título y bajada que dicen QUÉ muestra el gráfico y cómo leerlo.

    El motor universal nombra los gráficos de forma genérica ("Evolución del
    indicador", "Ranking de resultados") porque no conoce el archivo. En una
    presentación eso obliga a adivinar; aquí se nombran con las columnas
    reales."""
    from ui.report_base import mes
    m = _label(schema, primary) if primary else "el indicador"
    d = _label(schema, dims[0]) if dims else "categoría"
    if kind == "trend":
        return (f"{m} mes a mes",
                "Cada punto es el resultado de un mes. La etiqueta del último punto es su variación frente al mes anterior.")
    if kind == "multi_trend":
        nombres = " y ".join(_label(schema, x) for x in metrics[:3])
        return (f"{nombres} mes a mes", "Una línea por indicador, para ver si se mueven juntos o por separado.")
    if kind == "ranking":
        return (f"{m} por {d}",
                f"Cada barra es un valor de «{d}», de mayor a menor. La línea punteada marca la mediana del grupo.")
    if kind == "ranking2" and len(dims) >= 2:
        d2 = _label(schema, dims[1])
        return (f"{m} por {d2}",
                f"Cada barra es un valor de «{d2}», de mayor a menor. La línea punteada marca la mediana del grupo.")
    if kind == "donut":
        return (f"Participación de cada {d} en {m}", f"Qué parte del total de «{m}» aporta cada valor de «{d}».")
    if kind == "scatter" and len(metrics) >= 2:
        a, b = _label(schema, metrics[0]), _label(schema, metrics[1])
        return (f"Relación entre {a} y {b}",
                "Cada punto es un registro. Si forman una línea, los dos indicadores suben y bajan juntos.")
    if kind == "histogram":
        return (f"Cómo se reparten los valores de {m}",
                "Cada barra agrupa registros con valores parecidos; la más alta es el rango más frecuente.")
    if kind == "rangos":
        return (f"{m} por rango de valores", "Cuántos registros caen en cada tramo de valores.")
    if kind == "cascada":
        cambio = dashboard.get("change_analysis") or {}
        try:
            a = mes(pd.Timestamp(cambio.get("period_before")))
            b = mes(pd.Timestamp(cambio.get("period_after")))
        except Exception:
            a, b = cambio.get("period_before", ""), cambio.get("period_after", "")
        return (f"Qué explica el cambio de {m}", f"De {a} a {b}: cuánto sumó o restó cada parte.")
    if kind == "periodo":
        return (f"{m} por {d}: último mes y anterior",
                f"Cada columna es un valor de «{d}»; los colores separan el último mes del anterior.")
    if kind == "correlacion":
        return ("Qué indicadores se mueven juntos",
                "Cerca de 1: suben y bajan a la vez. Cerca de −1: cuando uno sube, el otro baja. Cerca de 0: no se relacionan.")
    if kind == "mapa":
        return (f"{m} por ubicación", "Cada punto es una ubicación del archivo; el tamaño indica cuánto pesa.")
    return title, subtitle


def _narrative_summary(df: pd.DataFrame, schema: dict, dashboard: dict, primary, dims) -> str:
    """Frase ejecutiva de una línea combinando lo que el archivo realmente
    tiene — nunca inventa una métrica o dimensión que no exista.
    """
    n = len(df)
    parts = [f"{n:,} registros analizados"]
    if primary and primary in df.columns:
        sem = semantic_map(schema).get(primary, "")
        s = pd.to_numeric(df[primary], errors="coerce").dropna()
        if len(s):
            value = float(s.sum()) if sem in ADDITIVE else float(s.mean())
            verb = "con un total de" if sem in ADDITIVE else "con un promedio de"
            parts.append(f"{verb} {_label(schema, primary).lower()} de {_fmt(value)}")
    if dims:
        first_dim = dims[0]
        if first_dim in df.columns:
            unique_n = df[first_dim].nunique(dropna=True)
            if unique_n:
                parts.append(f"repartidos en {unique_n:,} valores de {_label(schema, first_dim).lower()}")
    return ", ".join(parts) + "."


def _status(dashboard: dict) -> str:
    ex = dashboard.get("executive") or {}
    return _TONO.get(ex.get("status", ""), "")


def _delta_html(dashboard: dict, clase: str = "delta") -> str:
    ex = dashboard.get("executive") or {}
    if ex.get("change") is None:
        return ""
    pct = float(ex["change"])
    arrow = "▲" if pct > 0 else "▼" if pct < 0 else "="
    return f"<div class='{clase} {_status(dashboard)}'>{arrow} {abs(pct):.1f}%</div>"


def _resumen_block(dashboard: dict, plan: dict, sid: str = "lectura-ejecutiva",
                   titulo: str = "Resumen para decidir", enlace_planes: str = "planes",
                   ctx: dict | None = None) -> str:
    """El veredicto, el semáforo y las tres prioridades con su primer paso.

    Es lo único que muchos van a leer: tiene que decir cómo va el negocio y
    qué hacer primero sin necesidad de bajar al detalle.
    """
    ex = dashboard.get("executive") or {}
    planes = (plan or {}).get("planes") or []
    veredicto = ""
    if ex.get("headline"):
        titular, detalle_txt = _titular(ex, ctx or {})
        detalle = f"<p>{_esc(detalle_txt)}</p>" if detalle_txt else ""
        veredicto = (f"<div class='verdict {_status(dashboard)}'><div><h3>{_esc(titular)}</h3>"
                     f"{detalle}</div>{_delta_html(dashboard)}</div>")

    izquierda = ""
    if planes:
        izquierda = ("<p class='subhead'>Qué atender primero</p>"
                     + prioridades(planes, 3, enlace=enlace_planes if len(planes) > 3 else ""))
    else:
        watch = [w for w in (ex.get("watch") or []) if w][:4]
        if watch:
            items = "".join(f"<li>{esc_limpio(w)}</li>" for w in watch)
            izquierda = f"<p class='subhead'>Requiere atención</p><ul class='bullets'>{items}</ul>"

    positivos = [p for p in (ex.get("positive") or []) if p][:3]
    a_favor = ""
    if positivos:
        a_favor = ("<div class='a-favor'><b>A favor</b><ul>"
                   + "".join(f"<li>{esc_limpio(p)}</li>" for p in positivos) + "</ul></div>")
    derecha = ""
    if planes or a_favor:
        derecha = (f"<div>{'<p class=subhead>Semáforo de frentes</p>' + semaforo(plan) if planes else ''}"
                   f"{a_favor}</div>")

    if not (veredicto or izquierda or derecha):
        return ""
    grid = (f"<div class='resumen-grid'><div>{izquierda}</div>{derecha}</div>" if (izquierda or derecha) else "")
    ctx = ctx or {}
    leer = ""
    if planes:
        leer = ("Arriba, cómo cerró el indicador principal"
                + (f" en {_esc(ctx['mes_b'])} comparado con {_esc(ctx['mes_a'])}" if ctx.get("mes_a") else "")
                + ". Debajo, los tres frentes más urgentes que detectó el análisis: cada uno trae el dato "
                  "que lo originó y el primer paso para atenderlo. El semáforo cuenta cuántos frentes hay de cada tipo.")
    fuente = _fuente(ctx, _col(ctx["metrica"])) if ctx.get("hoja") and ctx.get("metrica") else ""
    return seccion(sid, titulo, "La conclusión primero: cómo va el resultado y qué conviene hacer.",
                   veredicto + grid, leer=leer, fuente=fuente)


def _concentration_block(dashboard: dict, schema: dict, df: pd.DataFrame | None = None,
                         primary=None, dims=None, ctx: dict | None = None) -> str:
    """Concentración: cuánto pesa cada grupo sobre el total, y cuánto se
    acumula en los primeros. Responde la pregunta que sigue siempre a un
    total ("¿de dónde sale?") y detecta dependencia excesiva de un solo
    grupo, que es un riesgo de negocio real.

    Se apoya en dashboard["performance"], que el motor ya calculaba. Si hay
    más grupos de los que caben, los extremos (top y bottom 10) quedan
    plegados debajo; con pocos grupos la propia tabla ya los muestra todos.
    """
    perf = dashboard.get("performance") or {}
    top = perf.get("top") or []
    total = perf.get("total")
    if not top or not total:
        return ""
    dim_label = _label(schema, perf.get("dimension", ""))
    metric_label = _label(schema, perf.get("metric", ""))
    rows, acumulado = [], 0.0
    mayor = max(float(v) for _, v in top[:10]) or 1.0
    for name, value in top[:10]:
        share = (float(value) / float(total) * 100) if total else 0.0
        acumulado += share
        rows.append(
            f"<tr><td><b>{_esc(clean_display_text(name))}</b></td><td class='num'>{_fmt(value)}</td>"
            f"<td class='num'>{share:.1f}%</td><td class='num muted'>{acumulado:.1f}%</td>"
            f"<td class='barcell'><span class='bar' style='width:{max(float(value) / mayor * 100, 1):.1f}%'></span></td></tr>"
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
        tono = "neg"
        veredicto = (f"<b>Alta concentración:</b> {_esc(clean_display_text(str(lider)))} concentra el "
                     f"{lider_share:.1f}% del total sobre {universo}. Una caída ahí arrastra el resultado completo.")
    elif top3 >= 70:
        tono = "warn"
        veredicto = (f"<b>Concentración moderada-alta:</b> los 3 primeros suman el {top3:.1f}% del total, "
                     f"sobre {universo}.")
    else:
        tono = "pos"
        veredicto = (f"<b>Distribución repartida:</b> los 3 primeros suman el {top3:.1f}% del total "
                     f"sobre {universo}, sin dependencia de un solo grupo.")

    extremos = ""
    if df is not None and primary and dims and groups > 10:
        top_df = drilldown_table(df, schema, primary, dims[0], limit=10, ascending=False)
        bottom_df = drilldown_table(df, schema, primary, dims[0], limit=10, ascending=True)

        def _tb_rows(t):
            return "".join(f"<tr><td class='num muted'>{i+1}</td><td>{_esc(r[dims[0]])}</td>"
                           f"<td class='num'>{_fmt(r['Valor'])}</td></tr>" for i, r in t.iterrows())
        if not top_df.empty:
            cab = (f"<thead><tr><th class='num'>#</th><th>{_esc(_label(schema, dims[0]))}</th>"
                   f"<th class='num'>{_esc(_label(schema, primary))}</th></tr></thead>")
            extremos = desplegable(
                "Top 10 y Bottom 10",
                f"<div class='grid2'><div class='table-card'><p class='subhead'>Mayor {_esc(_label(schema, primary).lower())}</p>"
                f"<table>{cab}<tbody>{_tb_rows(top_df)}</tbody></table></div>"
                f"<div class='table-card'><p class='subhead'>Menor {_esc(_label(schema, primary).lower())}</p>"
                f"<table>{cab}<tbody>{_tb_rows(bottom_df)}</tbody></table></div></div>",
                f"por {_label(schema, dims[0]).lower()}", sid="top-bottom")

    return seccion(
        "concentracion", "De dónde sale el resultado",
        f"Peso de cada {dim_label.lower()} sobre el total de {metric_label.lower()}.",
        f"<div class='callout {tono}'>{veredicto}</div>"
        f"<div class='table-card'><table><thead><tr><th>{_esc(dim_label)}</th><th class='num'>{_esc(metric_label)}</th>"
        f"<th class='num'>% del total</th><th class='num'>Acumulado</th><th>Peso</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>{extremos}",
        leer=(f"Cada fila es un valor de «{_esc(dim_label)}». «% del total» es la parte de {_esc(metric_label.lower())} "
              f"que aporta; «Acumulado» va sumando las filas anteriores y muestra cuántos concentran la mayor parte. "
              f"Depender de pocos es un riesgo: si uno cae, arrastra el total."),
        fuente=_fuente(ctx, f"{_col(metric_label)} por «{_esc(dim_label)}»") if ctx else "",
    )


def _statistics_table(dashboard: dict, schema: dict) -> str:
    """Estadística descriptiva por métrica: promedio, mediana, dispersión y
    extremos. Dice si un promedio representa al conjunto o lo distorsiona
    un puñado de valores extremos."""
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
                    lectura = "<span class='pill warn'>Usar mediana</span>"
                elif sesgo < -25:
                    lectura = "<span class='pill warn'>Cola baja</span>"
                else:
                    lectura = "<span class='pill pos'>Promedio fiable</span>"
        except (TypeError, ValueError):
            lectura = ""
        rows.append(
            f"<tr><td><b>{_esc(_label(schema, col))}</b></td><td class='num'>{_fmt(r.get('Media'))}</td>"
            f"<td class='num'>{_fmt(r.get('Mediana'))}</td><td class='num'>{_fmt(r.get('Std'))}</td>"
            f"<td class='num'>{_fmt(r.get('Min'))}</td><td class='num'>{_fmt(r.get('Max'))}</td>"
            f"<td>{lectura}</td></tr>"
        )
    return (
        f"<div class='table-card'><div class='table-scroll'><table><thead><tr><th>Métrica</th><th class='num'>Promedio</th>"
        f"<th class='num'>Mediana</th><th class='num'>Desviación</th><th class='num'>Mínimo</th>"
        f"<th class='num'>Máximo</th><th>Lectura</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        f"<p class='note'>«Usar mediana»: el promedio está inflado por valores altos y no representa el caso típico.</p></div>"
    )


def _anomalies_table(dashboard: dict, schema: dict) -> tuple[str, int]:
    """Valores atípicos detectados. Se muestran los primeros y se dice
    cuántos hay en total: importa el orden de magnitud, no la lista entera."""
    anomalies = dashboard.get("anomalies")
    if anomalies is None or not hasattr(anomalies, "empty") or anomalies.empty:
        return "", 0
    total = len(anomalies)
    rows = []
    for _, r in anomalies.head(12).iterrows():
        rows.append(
            f"<tr><td class='num muted'>{_esc(r.get('fila', ''))}</td>"
            f"<td><b>{_esc(_label(schema, r.get('columna', '')))}</b></td>"
            f"<td class='num'>{_fmt(r.get('valor'))}</td>"
            f"<td><span class='pill'>{_esc(clean_display_text(str(r.get('tipo', ''))))}</span></td></tr>"
        )
    extra = f"<p class='note'>Se muestran 12 de {total:,}.</p>" if total > 12 else ""
    return (
        f"<div class='table-card'><p class='note' style='margin:0 0 8px'>No son errores por definición, pero conviene "
        f"confirmarlos antes de dar el dato por bueno.</p><table><thead><tr><th class='num'>Fila</th><th>Columna</th>"
        f"<th class='num'>Valor</th><th>Tipo</th></tr></thead><tbody>{''.join(rows)}</tbody></table>{extra}</div>",
        total,
    )


def _ya_cubiertos(plan: dict) -> set[str]:
    """Títulos que ya son un plan: no se repiten como hallazgo ni alerta."""
    return {str(p.get("titulo", "")).strip().lower() for p in (plan or {}).get("planes") or []}


# Hallazgos que solo repiten lo que ya dicen las tarjetas KPI y el veredicto
# del resumen: en una presentación, decir dos veces el total resta atención.
_REDUNDANTES = {"nivel de actividad", "evolución reciente"}


def _findings_html(items: list, cubiertos: set[str], maximo: int = 6, ctx: dict | None = None) -> str:
    """Hallazgos que no se convirtieron en plan: una fila por hallazgo, con el
    dato, sus nombres y qué revisar. La "implicación" larga queda fuera: en
    una presentación se lee el dato y la acción.

    Los títulos que se muestran se agregan a `cubiertos`, para que las
    alertas del anexo no los repitan."""
    filas = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title, finding, action, _ = _insight_text(item)
        if not finding or title.strip().lower() in cubiertos or title.strip().lower() in _REDUNDANTES:
            continue
        if ctx and ctx.get("mes_a"):
            finding = finding.replace("frente al periodo anterior", f"en {ctx['mes_b']} frente a {ctx['mes_a']}")
        tono = {"positive": "pos", "warning": "warn", "negative": "neg"}.get(item.get("kind"), "")
        accion = f"<p class='action'><b>→</b> {_esc(action)}</p>" if action else ""
        cubiertos.add(title.strip().lower())
        filas.append(f"<article class='finding {tono}'><span class='dot'></span><div><h3>{_esc(title)}</h3>"
                     f"<p>{_esc(finding)}</p>{_evidence_html(item)}{accion}</div></article>")
        if len(filas) >= maximo:
            break
    return f"<div class='findings'>{''.join(filas)}</div>" if filas else ""


def _alerts_table(alerts: list, cubiertos: set[str]) -> str:
    filas = []
    for a in alerts[:10]:
        if not isinstance(a, dict):
            continue
        if str(clean_display_text(a.get("title", ""))).strip().lower() in cubiertos:
            continue
        filas.append(
            f"<tr><td><span class='pill warn'>{_esc(clean_display_text(a.get('severity','')))}</span></td>"
            f"<td><b>{_esc(clean_display_text(a.get('title','Hallazgo')))}</b><br>"
            f"<span class='muted'>{_esc(clean_display_text(a.get('text','')))}</span>{_evidence_html(a)}</td>"
            f"<td>{_esc(clean_display_text(a.get('action','')))}</td></tr>"
        )
    if not filas:
        return ""
    return ("<div class='table-card'><table><thead><tr><th>Nivel</th><th>Alerta</th><th>Qué hacer</th></tr></thead>"
            f"<tbody>{''.join(filas)}</tbody></table></div>")


def _quality_html(df, schema, quality, metrics, dims) -> str:
    kpis = "".join(f"<div class='kpi'><div class='kpi-label'>{_esc(c)}</div><div class='kpi-value'>{_esc(v)}</div>"
                   f"<div class='kpi-sub'>{_esc(s)}</div></div>" for c, v, s in quality)
    return (f"<div class='kpis'>{kpis}</div>"
            f"<p class='note'>El motor reconoció {len(metrics)} métrica(s), {len(schema.get('dates', []))} fecha(s), "
            f"{len(dims)} dimensión(es) y {len(schema.get('ids', []))} identificador(es). El informe no presupone una "
            f"estructura fija: cada sección aparece solo si el archivo da para ella.</p>")


def _cover(kicker: str, titulo: str, lead: str, stats: list[tuple[str, str, str]], meta: list[tuple[str, str]]) -> str:
    stats_html = "".join(f"<div class='cover-stat {tono}'><b>{_esc(v)}</b><span>{_esc(l)}</span></div>"
                         for v, l, tono in stats if v not in (None, ""))
    meta_html = "".join(f"<span>{_esc(l)}: <b>{_esc(v)}</b></span>" for l, v in meta if v)
    return (f"<header class='cover'><div class='cover-kicker'>{_esc(kicker)}</div><h1>{_esc(titulo)}</h1>"
            f"<p class='lead'>{_esc(lead)}</p><div class='cover-stats'>{stats_html}</div>"
            f"<div class='cover-meta'>{meta_html}</div></header>")


def _primary_kpi(kpis: list, schema: dict):
    for k in kpis or []:
        if isinstance(k, dict) and k.get("kind") == "primary":
            return _kpi_value(k), _kpi_label(k, schema)
    return None, None


def build_html_report(df: pd.DataFrame, schema: dict, dashboard: dict, filename: str, sheet: str, scope_label: str = "Selección actual") -> str:
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")
    metrics = metric_candidates(df, schema)
    dims = dimension_candidates(df, schema)
    primary = dashboard.get("primary_metric") or (metrics[0] if metrics else None)
    quality = _quality_cards(df, schema)
    narrative = _narrative_summary(df, schema, dashboard, primary, dims)
    plan = calcular_planes(df, schema, dashboard)
    cubiertos = _ya_cubiertos(plan)

    # ── Gráficos universales: los dos primeros arriba, el resto al anexo ──
    chart_blocks = _build_charts(df, schema, dashboard, include_geo=True)

    # ── Secciones de decisión (mismas que las pestañas del panel) ──────────
    # Si el informe no tuviera ningún gráfico universal, el primero de estos
    # carga el motor de Plotly: sin él, los demás quedarían en blanco.
    estado_js = {"pendiente": not chart_blocks, "n": len(chart_blocks)}

    def _numerar() -> int:
        estado_js["n"] += 1
        return estado_js["n"]

    def _bloque(titulo, subtitulo, fig, numero) -> str:
        incluir = estado_js["pendiente"]
        estado_js["pendiente"] = False
        return _chart_block(titulo, subtitulo, fig, numero, include_js=incluir)

    def _seguro(fn) -> str:
        try:
            return fn() or ""
        except Exception:
            return ""

    ctx = _contexto(df, schema, dashboard, filename, sheet, scope_label)

    def _fuente_de(columnas: str = "") -> str:
        return _fuente(ctx, columnas)

    planes_html = _seguro(lambda: bloque_planes(df, schema, dashboard, plan, fuente=_fuente_de))
    estrategia_html = _seguro(lambda: bloque_estrategia(df, schema, fuente=_fuente_de))
    cuadro_html = _seguro(lambda: bloque_cuadro_comparativo(df, schema, primary, _bloque, _numerar, fuente=_fuente_de))
    cambio_html = _seguro(lambda: bloque_cambio_periodos(df, schema, primary, _bloque, _numerar, fuente=_fuente_de))

    resumen_html = _resumen_block(dashboard, plan, ctx=ctx)
    kpis = dashboard.get("kpis") or []
    kpi_cards = _kpis_html(kpis, schema, n_registros=len(df))
    indicadores_html = seccion(
        "resumen", "Indicadores clave",
        (f"Las cifras generales de {ctx['metrica'].lower()} en todo el periodo analizado ({ctx['periodo_corto']})."
         if ctx.get("metrica") else "Las cifras generales del periodo analizado."),
        (f"<div class='kpis'>{kpi_cards}</div>" if kpi_cards else "")
        + (f"<div class='grid2' id='vista-principal' style='margin-top:14px'>{''.join(chart_blocks[:2])}</div>"
           if chart_blocks else ""),
        leer="Cada tarjeta dice debajo cómo se calculó su cifra. Los gráficos muestran la evolución mes a mes "
             "y cómo se reparte el resultado entre los grupos.",
        fuente=_fuente(ctx, _col(ctx["metrica"]) if ctx.get("metrica") else ""),
    )
    concentracion_html = _concentration_block(dashboard, schema, df, primary, dims, ctx=ctx)
    hallazgos = _findings_html(dashboard.get("insights") or [], cubiertos, ctx=ctx)
    hallazgos_html = (seccion(
        "lectura", "Otros hallazgos", "Patrones que detectó el análisis y que no necesitan un plan propio.", hallazgos,
        leer="El punto de color indica el tipo: verde es favorable, ámbar pide atención y gris es informativo. "
             "Bajo cada hallazgo, los nombres y cifras que lo sustentan y, tras la flecha, qué revisar.",
        fuente=_fuente(ctx) + " · Hallazgos generados por el análisis automático de la hoja.",
    ) if hallazgos else "")

    # ── Anexo plegado ──
    stats_html = _statistics_table(dashboard, schema)
    anomalies_html, n_atipicos = _anomalies_table(dashboard, schema)
    alerts_html = _alerts_table(dashboard.get("alerts") or [], cubiertos)
    otros = "".join(chart_blocks[2:])
    anexo_items = [
        ("estadistica", "Estadística descriptiva", stats_html, "valor típico, dispersión y extremos de cada columna numérica"),
        ("atipicos", "Valores atípicos", anomalies_html, f"{n_atipicos:,} registros fuera de lo normal" if n_atipicos else ""),
        ("alertas", "Otras alertas", alerts_html, ""),
        ("graficos", "Otros gráficos", f"<div class='grid2'>{otros}</div>" if otros else "", f"{len(chart_blocks[2:])} vistas adicionales"),
        ("calidad", "Calidad del dato", _quality_html(df, schema, quality, metrics, dims), f"puntaje {quality[0][1]}"),
    ]
    anexo_items = [a for a in anexo_items if a[2]]
    anexo_html = seccion(
        "anexo", "Anexo técnico", "Material de soporte para quien quiera verificar las cifras.",
        "".join(desplegable(t, c, d, sid=sid) for sid, t, c, d in anexo_items),
        leer="Cada bloque se abre con un clic. Al imprimir o guardar en PDF salen todos desplegados.",
        fuente=_fuente(ctx),
    )

    # ── Orden del documento = orden del menú ──
    # (grupo, id, etiqueta del menú, qué dice en la agenda, html)
    cuerpo_secciones = [
        ("Resumen", "lectura-ejecutiva", "Resumen para decidir", "Cómo cerró el resultado y los tres frentes más urgentes.", resumen_html),
        ("Resumen", "resumen", "Indicadores clave", "Las cifras generales y su evolución mes a mes.", indicadores_html),
        ("Decisión", "planes", "Planes de mejora", "Qué hacer, en orden de urgencia, con pasos concretos.", planes_html),
        ("Decisión", "estrategia", "Estrategia por canal", "Cuánto pesa cada canal, hacia dónde va y qué jugada le toca.", estrategia_html),
        ("Decisión", "cuadro-comparativo", "Cómo va cada uno", "Cada uno contra su meta o contra el promedio del grupo.", cuadro_html),
        ("Decisión", "cambio-periodos", "Qué cambió y quién lo explica", "Quién sumó y quién restó entre los dos últimos meses.", cambio_html),
        ("Contexto", "concentracion", "De dónde sale el resultado", "Cuánto depende el total de unos pocos.", concentracion_html),
        ("Contexto", "lectura", "Otros hallazgos", "Patrones adicionales que detectó el análisis.", hallazgos_html),
        ("Anexo", "anexo", "Anexo técnico", "Estadística, atípicos, alertas y calidad del dato.", anexo_html),
    ]
    agenda = [(etiqueta, desc) for _, _, etiqueta, desc, contenido in cuerpo_secciones if contenido]
    contexto_html = _contexto_block(ctx, agenda)
    cuerpo_secciones.insert(0, ("Resumen", "contexto", "Sobre este informe", "", contexto_html))

    grupos: dict[str, list] = {}
    for grupo, sid, etiqueta, _, contenido in cuerpo_secciones:
        if contenido:
            grupos.setdefault(grupo, []).append((sid, etiqueta))
    nav_html = nav(list(grupos.items()), "Informe analítico", sheet)

    valor, etiqueta_valor = _primary_kpi(kpis, schema)
    ex = dashboard.get("executive") or {}
    cambio = ex.get("change")
    criticos = sum(1 for p in plan.get("planes") or [] if p.get("estado") == "critico")
    stats = [
        (valor, f"{etiqueta_valor or 'Indicador principal'} del periodo", ""),
        ((f"{'▲' if cambio > 0 else '▼' if cambio < 0 else '='} {abs(cambio):.1f}%" if cambio is not None else None),
         f"{ctx['mes_b']} vs {ctx['mes_a']}" if ctx.get("mes_a") else "vs periodo anterior", _status(dashboard)),
        (f"{len(df):,}", "Registros analizados", ""),
        (str(criticos) if plan.get("planes") else None,
         "Frentes críticos" if criticos != 1 else "Frente crítico", "neg" if criticos else "pos"),
    ]
    cover = _cover("Panel Analítico Universal · Informe ejecutivo", sheet, narrative, stats,
                   [("Archivo", filename), ("Alcance", scope_label), ("Periodo", ctx["periodo"]),
                    ("Generado", generated)])
    cuerpo = (cover + "".join(c for *_, c in cuerpo_secciones if c)
              + "<footer class='footer'>Generado por Panel Analítico Universal · El contenido se adapta a la estructura real del Excel.</footer>")
    return documento(f"Informe ejecutivo — {sheet} · {filename}", cuerpo, nav_html)


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
        "plan": calcular_planes(df, schema, dashboard),
    }


def build_workbook_html_report(workbook: dict) -> str:
    """Informe de todo el libro, independiente de los filtros activos.

    Abre con un tablero de una fila por hoja (cómo va, cuánto cambió, cuántos
    frentes críticos tiene) y las prioridades de todo el libro. Después, cada
    hoja muestra sus cifras, sus dos gráficos principales y qué hacer; el
    análisis completo de cada hoja queda plegado debajo.
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

    # Workbook-level quality is presented as a weighted view of all usable sheets.
    if reports:
        weighted_quality = sum(r["quality"][0][1].split("/")[0] and float(r["quality"][0][1].split("/")[0]) * len(r["df"]) for r in reports) / max(total_rows, 1)
    else:
        weighted_quality = 0.0

    used_slugs: dict = {}
    for r in reports:
        # Id único por hoja para el ancla del menú, incluso si dos hojas
        # comparten un nombre muy parecido tras normalizarlo.
        base_slug = _slug(r["sheet"])
        used_slugs[base_slug] = used_slugs.get(base_slug, 0) + 1
        r["_anchor"] = base_slug if used_slugs[base_slug] == 1 else f"{base_slug}-{used_slugs[base_slug]}"

    # ── Tablero por hoja: una fila por hoja, lo que un director mira primero ──
    board_rows = []
    todas_prioridades = []
    for r in reports:
        d, schema = r["dashboard"], r["schema"]
        ex = d.get("executive") or {}
        r["_ctx"] = _contexto(r["df"], schema, d, filename, r["sheet"], "Hoja completa (sin filtros)")
        planes = (r["plan"] or {}).get("planes") or []
        criticos = sum(1 for p in planes if p.get("estado") == "critico")
        atencion = sum(1 for p in planes if p.get("estado") == "atencion")
        for p in planes:
            if p.get("estado") in {"critico", "atencion"}:
                todas_prioridades.append({**p, "_hoja": r["sheet"]})
        cambio = ex.get("change")
        cambio_html = (f"<span class='kpi-delta {_status(d)}'>{'▲' if cambio > 0 else '▼' if cambio < 0 else '='} "
                       f"{abs(cambio):.1f}%</span>" if cambio is not None else "<span class='muted'>—</span>")
        frentes = []
        if criticos:
            frentes.append(f"<span class='pill neg'>{criticos} crítico{'s' if criticos != 1 else ''}</span>")
        if atencion:
            frentes.append(f"<span class='pill warn'>{atencion} en observación</span>")
        if not frentes:
            frentes.append("<span class='pill pos'>Sin alertas</span>")
        metrica = _label(schema, r["primary"]) if r["primary"] else "Sin métrica principal"
        board_rows.append(
            f"<tr><td><b>{_esc(r['sheet'])}</b><br><span class='muted'>{len(r['df']):,} registros · {_esc(metrica)}</span></td>"
            f"<td>{_esc(_titular(ex, r['_ctx'])[0] or '—')}</td>"
            f"<td class='num'>{_fmt(r['total_value']) if r['total_value'] is not None else '—'}</td>"
            f"<td class='num'>{cambio_html}</td><td>{' '.join(frentes)}</td>"
            f"<td><a class='go' href='#{r['_anchor']}'>Ver →</a></td></tr>"
        )
    orden = {"critico": 0, "atencion": 1}
    todas_prioridades.sort(key=lambda p: orden.get(p.get("estado"), 2))

    tablero_html = seccion(
        "resumen-libro", "Tablero por hoja", "Cómo va cada hoja del libro y cuántos frentes abiertos tiene.",
        "<div class='table-card'><div class='table-scroll'><table><thead><tr><th>Hoja</th><th>Lectura</th>"
        "<th class='num'>Total principal</th><th class='num'>Cambio</th><th>Frentes</th><th></th></tr></thead>"
        f"<tbody>{''.join(board_rows) or '<tr><td colspan=6>No se encontraron hojas analizables.</td></tr>'}</tbody>"
        "</table></div></div>",
        leer="Una fila por hoja. «Lectura» es el veredicto de su indicador principal, «Cambio» compara su último "
             "mes con datos contra el anterior y «Frentes» cuenta los asuntos críticos o en observación que "
             "encontró el análisis. «Ver →» lleva al detalle de la hoja.",
        fuente=f"{_esc(filename)} · {len(reports):,} hoja(s) con datos · {total_rows:,} registros · sin filtros",
    )
    prioridades_html = ""
    if todas_prioridades:
        prioridades_html = seccion(
            "hallazgos", "Prioridades del libro", "Los frentes críticos y en observación de todas las hojas, en orden de atención.",
            prioridades(todas_prioridades, 6, con_hoja=True)
            + (f"<p class='note'>Y {len(todas_prioridades) - 6} frente(s) más en el detalle de cada hoja.</p>"
               if len(todas_prioridades) > 6 else ""),
            leer="Cada fila es un frente de trabajo; la etiqueta roja indica la hoja de donde sale. Debajo del "
                 "título, el dato que lo originó y el primer paso para atenderlo.",
            fuente=f"{_esc(filename)} · frentes generados por el análisis automático de cada hoja",
        )

    # ── Detalle por hoja ──
    sheet_sections = []
    chart_counter = 0
    # El motor de Plotly viaja en el PRIMER gráfico que se dibuje en todo el
    # documento, sea de la hoja que sea: si la primera hoja no tiene gráficos,
    # lo lleva el primero de la siguiente sección que sí los tenga.
    motor = {"pendiente": True}
    for r in reports:
        d = r["dashboard"]
        schema = r["schema"]
        df = r["df"]
        sheet_id = r["_anchor"]
        plan = r["plan"] or {}
        cubiertos = _ya_cubiertos(plan)
        ctx_h = r["_ctx"]

        def _fuente_hoja(columnas: str = "", _c=ctx_h) -> str:
            return _fuente(_c, columnas)

        kpi_html = _kpis_html(d.get("kpis") or [], schema, 4, n_registros=len(df))
        if not kpi_html:
            kpi_html = f"<div class='kpi'><div class='kpi-label'>Registros</div><div class='kpi-value'>{len(df):,}</div></div>"

        charts = _build_charts(df, schema, d, include_geo=True, incluir_motor=motor["pendiente"])
        if charts:
            motor["pendiente"] = False
        chart_counter += len(charts)
        primary_charts_html = "".join(charts[:2])
        secondary_charts_html = "".join(charts[2:8])

        # Mismas secciones de decisión que el informe individual, una por hoja.
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
            lambda: bloque_planes(df, schema, d, plan, fuente=_fuente_hoja),
            lambda: bloque_estrategia(df, schema, fuente=_fuente_hoja),
            lambda: bloque_cuadro_comparativo(df, schema, r["primary"], _bloque_hoja, _numerar_hoja, fuente=_fuente_hoja),
            lambda: bloque_cambio_periodos(df, schema, r["primary"], _bloque_hoja, _numerar_hoja, fuente=_fuente_hoja),
            lambda: _concentration_block(d, schema, df, r["primary"], r["dims"], ctx=ctx_h),
        ):
            try:
                bloque = constructor()
            except Exception:
                bloque = ""
            if bloque:
                # El ancla ya la usa la sección del informe individual; en el
                # libro hay una por hoja, así que se hace única.
                bloque = bloque.replace('<section class="section" id="', f'<section class="section" id="{sheet_id}-', 1)
                bloque = bloque.replace('id="top-bottom"', f'id="{sheet_id}-top-bottom"')
                secciones_hoja.append(bloque)
        hallazgos = _findings_html(d.get("insights") or [], cubiertos, 4, ctx=ctx_h)
        if hallazgos:
            secciones_hoja.append(seccion(f"{sheet_id}-lectura", "Otros hallazgos",
                                          "Patrones que detectó el análisis y que no necesitan un plan propio.", hallazgos,
                                          fuente=_fuente(ctx_h)))
        if secondary_charts_html:
            secciones_hoja.append(seccion(f"{sheet_id}-graficos", "Otros gráficos", "",
                                          f"<div class='grid2'>{secondary_charts_html}</div>"))
        secciones_hoja.append(seccion(f"{sheet_id}-calidad", "Calidad del dato", "",
                                      _quality_html(df, schema, r["quality"], r["metrics"], r["dims"])))

        ex = d.get("executive") or {}
        titular, detalle = _titular(ex, ctx_h)
        que_hacer = prioridades((plan.get("planes") or []), 3)
        status_pill = {"pos": "<span class='pill pos'>Mejora</span>", "neg": "<span class='pill neg'>Declive</span>"}.get(_status(d), "")
        sheet_sections.append(
            f"<section class='sheet-section' id='{sheet_id}'>"
            f"<div class='sheet-heading'><div><span class='kicker'>Hoja</span><h2>{_esc(r['sheet'])}</h2>"
            f"<p>{len(df):,} registros · {len(df.columns):,} columnas · {_esc(ctx_h['periodo'])}"
            + (f" · indicador principal: «{_esc(ctx_h['metrica'])}»" if ctx_h.get("metrica") else "")
            + f"</p></div>{status_pill}</div>"
            + (f"<div class='verdict {_status(d)}'><div><h3>{_esc(titular)}</h3>"
               f"<p>{_esc(detalle)}</p></div>{_delta_html(d)}</div>" if ex.get("headline") else "")
            + f"<div class='kpis' style='margin-top:12px'>{kpi_html}</div>"
            + (f"<div class='grid2' style='margin-top:12px'>{primary_charts_html}</div>" if primary_charts_html else "")
            + (f"<div style='margin-top:16px'><p class='subhead'>Qué hacer en esta hoja</p>{que_hacer}</div>" if que_hacer else "")
            + desplegable("Análisis completo de esta hoja", "".join(secciones_hoja),
                          "plan, comparativos, cambios, hallazgos y calidad", sid=f"{sheet_id}-detalle")
            + f"<p class='fuente'><b>Fuente</b> {_fuente(ctx_h)}</p>"
            + "</section>"
        )

    hojas_txt = ", ".join(r["sheet"] for r in reports[:6]) + (f" y {len(reports) - 6} más" if len(reports) > 6 else "")
    ctx_libro = {"archivo": filename, "hoja": "", "registros": total_rows, "periodo": "", "alcance": "",
                 "metrica": None, "dim": None, "mes_a": None, "meta_col": None, "suma": True}
    agenda = ([("Tablero por hoja", "Cómo va cada hoja, en una fila, con sus frentes abiertos.")]
              + ([("Prioridades del libro", "Los frentes más urgentes de todas las hojas juntas.")] if prioridades_html else [])
              + [(f"Hoja «{r['sheet']}»", "Veredicto, cifras, gráficos y qué hacer; el análisis completo va plegado.")
                 for r in reports])
    contexto_html = _contexto_block(
        ctx_libro, agenda,
        extra_mide=["Cada hoja se analiza por separado, con su propio indicador principal (el que aparece en el tablero).",
                    "En cada hoja se compara su último mes con datos contra el mes anterior; el veredicto de cada una "
                    "nombra los meses que compara.",
                    "Este informe no usa los filtros de la app: cada hoja se analiza completa."],
        datos=[("Archivo", filename), ("Hojas", hojas_txt), ("Registros", f"{total_rows:,} en total"),
               ("Filtros", "Ninguno: cada hoja completa")],
    )
    nav_html = nav(
        [("Libro", [("contexto", "Sobre este informe"), ("resumen-libro", "Tablero por hoja")]
          + ([("hallazgos", "Prioridades del libro")] if prioridades_html else [])),
         ("Hojas", [(r["_anchor"], r["sheet"]) for r in reports])],
        "Informe del libro", filename,
    )
    criticos_total = sum(1 for r in reports for p in (r["plan"] or {}).get("planes") or [] if p.get("estado") == "critico")
    cover = _cover(
        "Panel Analítico Universal · Informe general",
        "Resumen de todo el Excel",
        "Lectura completa del libro, sin depender de los filtros activos: cómo va cada hoja, qué atender primero y el detalle de cada una.",
        [(f"{len(reports):,}", "Hojas con datos", ""), (f"{total_rows:,}", "Registros", ""),
         (str(criticos_total), "Frentes críticos", "neg" if criticos_total else "pos"),
         (f"{weighted_quality:.0f}/100", "Calidad del dato", "")],
        [("Archivo", filename), ("Generado", generated)],
    )
    cuerpo = (cover + contexto_html + tablero_html + prioridades_html
              + ("".join(sheet_sections) or '<section class="section"><div class="empty">No se encontraron hojas con datos analizables.</div></section>')
              + "<footer class='footer'>Generado por Panel Analítico Universal · Resumen del libro completo · Los análisis se adaptan a cada hoja.</footer>")
    return documento(f"Informe general del Excel — {filename}", cuerpo, nav_html)


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

    kpi_cards = []
    subieron = bajaron = 0
    for m in comparison.get("recent_metrics", []):
        cp = m["cambio_pct"]
        cp_txt = "—" if cp is None else f"{'▲' if cp > 0 else '▼' if cp < 0 else '='} {abs(cp):.1f}%"
        tone = "pos" if (cp or 0) > 0 else ("neg" if (cp or 0) < 0 else "")
        subieron += (cp or 0) > 0
        bajaron += (cp or 0) < 0
        kpi_cards.append(
            f"<div class='kpi'><div class='kpi-label'>{_esc(m['nombre'])}</div>"
            f"<div class='kpi-value'>{_fmt(m['actual'])}</div>"
            f"<div class='kpi-delta {tone}'>{cp_txt} vs. anterior</div></div>"
        )

    tonos = {"positive": "pos", "warning": "warn"}
    signals = comparison.get("signals", [])
    signals_html = "".join(
        f"<article class='finding {tonos.get(s['tipo'], '')}'><span class='dot'></span><div>"
        f"<p>{_esc(clean_display_text(s['texto']))}</p></div></article>"
        for s in signals[:6]
    )
    if len(signals) > 6:
        signals_html += desplegable(f"{len(signals) - 6} lectura(s) más", "".join(
            f"<article class='finding {tonos.get(s['tipo'], '')}'><span class='dot'></span><div>"
            f"<p>{_esc(clean_display_text(s['texto']))}</p></div></article>" for s in signals[6:]))

    dim_tables = []
    for dr in comparison.get("dimension_results", [])[:4]:
        t = dr["table"]
        # Se separa por signo: con pocas categorías, "las 5 que más bajaron"
        # incluía algunas que en realidad subieron.
        up = t[t["cambio"] > 0].sort_values("cambio", ascending=False).head(5)
        down = t[t["cambio"] < 0].sort_values("cambio", ascending=True).head(5)

        def _rows(sub):
            if sub.empty:
                return "<tr><td colspan=4 class='muted'>Ninguna.</td></tr>"
            out = []
            for _, r in sub.iterrows():
                cp = r["cambio_pct"]
                cp_txt = "—" if pd.isna(cp) else f"{cp:+.1f}%"
                tono = "" if pd.isna(cp) else ("pos" if cp > 0 else "neg" if cp < 0 else "")
                out.append(
                    f"<tr><td>{_esc(r['categoria'])}</td><td class='num'>{_fmt(r['anterior'])}</td>"
                    f"<td class='num'>{_fmt(r['actual'])}</td><td class='num'><span class='kpi-delta {tono}'>{cp_txt}</span></td></tr>"
                )
            return "".join(out)
        cab = "<thead><tr><th>Categoría</th><th class='num'>Antes</th><th class='num'>Ahora</th><th class='num'>Variación</th></tr></thead>"
        dim_tables.append(
            f"<div class='table-card'><h3 style='margin:0 0 10px;font-size:14.5px'>{_esc(dr['dimension'])} · {_esc(dr['metric'])}</h3>"
            f"<div class='grid2'><div><p class='subhead'>Mayor mejora</p><table>{cab}<tbody>{_rows(up)}</tbody></table></div>"
            f"<div><p class='subhead'>Mayor caída</p><table>{cab}<tbody>{_rows(down)}</tbody></table></div></div></div>"
        )

    chart_blocks = []
    for i, h in enumerate(comparison.get("history", [])[:6]):
        series = h["serie"]
        fig = px.line(series, x="periodo", y="valor", markers=True)
        fig.update_layout(
            height=300, margin=dict(l=10, r=20, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            xaxis_title=None, yaxis_title=None, font=dict(family="Inter,Segoe UI,Arial,sans-serif", size=12),
        )
        fig.update_yaxes(automargin=True, tickformat="~s", gridcolor="#eef2f7")
        fig.update_xaxes(automargin=True, showgrid=False)
        fig.update_traces(line_color="#e4002b", marker_color="#e4002b")
        chart_blocks.append(_chart_block(f"Evolución · {h['metrica']}", f"{h['operacion']} por archivo comparado", fig, i + 1, include_js=(i == 0)))

    matches = comparison.get("matches", [])
    match_rows = "".join(
        f"<tr><td>{_esc(m['a'])}</td><td>{_esc(m['b'])}</td><td class='num'>{m['score']*100:.0f}%</td><td>{_esc(_pretty_technical_safe(m.get('concept','')))}</td></tr>"
        for m in matches
    )

    records = combined_records_table(files, max_rows=300)
    records_html = ""
    if not records.empty:
        total_real = sum(len(f["df"]) for f in files)
        head_cols = "".join(f"<th>{_esc(c)}</th>" for c in records.columns)
        body_rows = "".join(
            "<tr>" + "".join(f"<td>{_esc(v) if pd.notna(v) else '—'}</td>" for v in row) + "</tr>"
            for row in records.itertuples(index=False)
        )
        note = (f"Primeros {len(records):,} de {total_real:,} registros. El CSV completo se descarga desde la app."
                if total_real > len(records) else f"{len(records):,} registros.")
        records_html = (f"<div class='table-card'><p class='note' style='margin:0 0 8px'>{note}</p>"
                        f"<div class='table-scroll'><table><thead><tr>{head_cols}</tr></thead><tbody>{body_rows}</tbody></table></div></div>")

    secciones = [
        seccion("resumen", "Resumen de cambios", "Cada métrica comparable, en el último archivo frente al anterior.",
                f"<div class='kpis'>{''.join(kpi_cards)}</div>" if kpi_cards
                else "<div class='empty'>No se encontraron métricas comparables entre los archivos.</div>"),
        seccion("lectura", "Qué cambió", "Lo que más se movió entre archivos.", f"<div class='findings'>{signals_html}</div>") if signals_html else "",
        seccion("categorias", "Quién mejoró y quién cayó", "Hasta cinco categorías que subieron y cinco que bajaron, por dimensión.",
                "".join(dim_tables)) if dim_tables else "",
        seccion("evolucion", "Evolución a través de los archivos", "",
                f"<div class='grid2'>{''.join(chart_blocks)}</div>") if chart_blocks else "",
        seccion("anexo", "Anexo", "",
                desplegable("Registros detallados", records_html, "")
                + desplegable("Variables que se cruzaron entre archivos",
                              "<div class='table-card'><table><thead><tr><th>Columna (primer archivo)</th><th>Equivalente (último)</th>"
                              f"<th class='num'>Coincidencia</th><th>Tipo</th></tr></thead><tbody>"
                              f"{match_rows or '<tr><td colspan=4>No se encontraron variables equivalentes.</td></tr>'}</tbody></table></div>",
                              f"{len(matches)} variables")),
    ]
    cover = _cover(
        "Panel Analítico Universal · Informe comparativo",
        f"Qué cambió entre {len(files)} archivos",
        " → ".join(clean_display_text(f["label"]) for f in files) or "Comparación de archivos",
        [(str(len(files)), "Archivos", ""), (str(subieron), "Métricas al alza", "pos" if subieron else ""),
         (str(bajaron), "Métricas a la baja", "neg" if bajaron else "")],
        [("Filtros", filters_summary), ("Generado", generated)],
    )
    cuerpo = (cover + "".join(secciones)
              + "<footer class='footer'>Generado por Panel Analítico Universal · Refleja los filtros activos al exportar.</footer>")
    return documento(f"Informe comparativo — {len(files)} archivos", cuerpo)


def _pretty_technical_safe(value: str) -> str:
    try:
        from ui.labels import pretty_technical
        return pretty_technical(value)
    except Exception:
        return str(value)
