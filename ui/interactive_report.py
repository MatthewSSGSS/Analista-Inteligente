"""Informe HTML interactivo: un tablero de análisis que funciona sin la app.

A diferencia de los otros informes (una foto fija de lo filtrado al
exportar), este lleva los datos adentro y TODO se recalcula en el navegador
cuando quien lo abre cambia un filtro: el veredicto del último mes, quién
explica el cambio, las oportunidades con su valor, las alertas, los gráficos
y el cuadro de «cómo va cada uno». Antes traía cuatro KPIs, una línea y dos
tablas que con pocos elementos repetían lo mismo; no decía qué pasó ni qué
hacer, así que había que sacar las conclusiones a mano.

Qué se decide aquí (Python) y qué en el navegador (JS):

- Python elige, con el mismo motor del panel, las columnas que importan
  (métricas, dimensiones, fecha, meta de cada métrica, si una métrica se suma
  o se promedia y si «menos es mejor») y empaqueta los datos por columnas y
  con diccionario, para que 60.000 filas no pesen lo que pesaría un JSON por
  fila. También arma, con `core/gerencia` y `core/planes`, el diagnóstico del
  archivo COMPLETO (por qué se movió y planes de mejora): esa parte es fija y
  así se rotula.
- El navegador repite, sobre lo filtrado, las reglas del proyecto:
  un faltante no es cero (una suma sin datos queda vacía, no en 0); las
  referencias —promedio, participación, posición, cumplimiento del grupo— se
  calculan sobre TODOS los elementos visibles con los filtros, nunca sobre
  una selección; si el último mes llega con menos días de lo habitual se
  comparan los dos anteriores; «recuperar» promete volver al promedio de
  sus 3 meses previos y «nivelar» la mitad del camino a la mediana.

Hacer clic en una barra, una celda del mapa de calor o una fila abre la
ficha de ese elemento (su posición entre todos, su evolución contra el
promedio del grupo y en qué se descompone); desde ahí se puede filtrar.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime

import numpy as np
import pandas as pd

from core.dates import a_datetime
from core.explorador import calculo_automatico, columna_fecha
from core.meses_largo import meses_a_filas
from core.numeric import numeric_valid
from core.universal_analysis import semantic_map
from ui.report_base import documento, esc, fecha_larga, mes, nav, seccion
from visualization.charts import _label, dimension_candidates, metric_candidates

MAX_ROWS = 60_000          # filas incrustadas (el archivo abre sin internet; más filas lo vuelven pesado)
MAX_DIMS = 8
MAX_METRICAS = 6
MAX_VALORES_DIM = 5_000    # una columna con más valores distintos es un código, no algo que comparar
CONTEO = "__conteo__"


def _plotly_js_bundle() -> str:
    """El bundle de Plotly.js, incrustado para que el archivo abra sin
    internet. to_html(include_plotlyjs='inline') genera varios <script>; la
    librería es el más grande."""
    import plotly.graph_objects as go
    snippet = go.Figure().to_html(full_html=False, include_plotlyjs="inline")
    blocks = re.findall(r"<script[^>]*>(.*?)</script>", snippet, re.S)
    return max(blocks, key=len) if blocks else ""


def _json(obj) -> str:
    """JSON seguro dentro de <script>: sin NaN (no es JSON válido) y sin que
    un texto con «</script>» cierre la etiqueta antes de tiempo."""
    return (json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            .replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _es_nulo(v) -> bool:
    """¿Celda vacía? Reconoce todos los vacíos de pandas: None, NaN, NaT y
    `pd.NA` (el de las columnas Int64/string con faltantes). Solo comparar con
    None y NaN dejaba pasar `pd.NA`: `float(pd.NA)` tumbaba el interactivo de
    un archivo real y `str(pd.NA)` creaba un grupo llamado «<NA>»."""
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False  # una lista u otro objeto: no es un vacío


def _numeros(serie: pd.Series) -> list:
    valores = numeric_valid(serie)
    salida = []
    for v in valores.tolist():
        if _es_nulo(v) or (isinstance(v, float) and not math.isfinite(v)):
            salida.append(None)
        else:
            f = float(v)
            if not math.isfinite(f):
                salida.append(None)
                continue
            salida.append(int(f) if f.is_integer() and abs(f) < 2**53 else round(f, 6))
    return salida


def _codificar(serie: pd.Series) -> dict:
    """Columna de texto por diccionario: los valores distintos una vez y un
    código por fila (-1 = vacío)."""
    texto = serie.astype(object).map(lambda v: None if _es_nulo(v) else str(v).strip())
    texto = texto.where(texto.astype(str).str.len() > 0)
    codigos, valores = pd.factorize(texto, sort=True)
    return {"v": [str(v) for v in valores.tolist()], "c": codigos.astype(int).tolist()}


def _es_porcentaje(df: pd.DataFrame, schema: dict, col) -> tuple[bool, bool]:
    """(es porcentaje, viene como fracción 0–1)."""
    sem = semantic_map(schema).get(col, "")
    nombre = str(col).lower()
    es_pct = sem == "percentage" or "%" in nombre or "porcentaje" in nombre or "particip" in nombre
    if not es_pct:
        return False, False
    v = numeric_valid(df[col]).dropna()
    return True, bool(len(v) and float(v.abs().max()) <= 1.5)


def _preparar(df: pd.DataFrame, schema: dict, primaria=None) -> tuple[dict, dict]:
    """Configuración del tablero y datos empaquetados por columna."""
    from core.cuadro_comparativo import opciones_de_comparacion
    from core.diagnostics import PEOR_SI_SUBE
    from core.performance import columna_meta

    fecha = columna_fecha(df, schema)
    metricas = [m for m in metric_candidates(df, schema) if m in df.columns]
    # La meta de cada métrica viaja como dato, no como métrica elegible:
    # «Meta» contra «Meta» no dice nada.
    metas = {}
    for m in metricas:
        try:
            meta = columna_meta(df, schema, m)
        except Exception:
            meta = None
        if meta is not None and meta in df.columns and meta != m:
            metas[m] = meta
    columnas_meta = set(metas.values())
    elegibles = [m for m in metricas if m not in columnas_meta][:MAX_METRICAS]
    if primaria in elegibles:
        elegibles.remove(primaria)
        elegibles.insert(0, primaria)

    dims = []
    try:
        preferidas = [d for d in opciones_de_comparacion(df, schema) if d in df.columns]
    except Exception:
        preferidas = []
    for d in preferidas + [d for d in dimension_candidates(df, schema) if d in df.columns]:
        if d in dims or d == fecha or d in metricas:
            continue
        distintos = df[d].nunique(dropna=True)
        if 2 <= distintos <= MAX_VALORES_DIM:
            dims.append(d)
        if len(dims) >= MAX_DIMS:
            break
    vista = dims[0] if dims else None

    datos_df = df.iloc[:MAX_ROWS]
    data = {"n": int(len(datos_df)), "fecha": None, "dims": {}, "met": {}}
    if fecha:
        fechas = a_datetime(datos_df[fecha], errors="coerce")
        data["fecha"] = _codificar(fechas.dt.strftime("%Y-%m-%d"))
    for d in dims:
        data["dims"][str(d)] = _codificar(datos_df[d])
    for m in list(dict.fromkeys(elegibles + list(columnas_meta))):
        data["met"][str(m)] = _numeros(datos_df[m])

    config_metricas = []
    for m in elegibles:
        es_pct, fraccion = _es_porcentaje(df, schema, m)
        try:
            calculo = calculo_automatico(df, schema, m)
        except Exception:
            calculo = "Suma"
        config_metricas.append({
            "col": str(m), "label": _label(schema, m), "agg": "mean" if calculo == "Promedio" else "sum",
            "menos": bool(PEOR_SI_SUBE.search(str(m))), "meta": str(metas[m]) if m in metas else None,
            "metaLabel": _label(schema, metas[m]) if m in metas else None,
            "pct": es_pct, "fraccion": fraccion,
        })
    config_metricas.append({"col": CONTEO, "label": "Cantidad de registros", "agg": "sum", "menos": False,
                            "meta": None, "metaLabel": None, "pct": False, "fraccion": False})

    desde = hasta = None
    if fecha:
        validas = a_datetime(df[fecha], errors="coerce").dropna()
        if not validas.empty:
            desde, hasta = validas.min(), validas.max()
    config = {
        "fechaLabel": _label(schema, fecha) if fecha else None,
        "dims": [{"col": str(d), "label": _label(schema, d)} for d in dims],
        "vista": str(vista) if vista is not None else None,
        "metricas": config_metricas,
        "principal": config_metricas[0]["col"],
        "totalFilas": int(len(df)),
        "incluidas": int(len(datos_df)),
        "periodo": (f"del {fecha_larga(desde)} al {fecha_larga(hasta)}" if desde is not None else "sin fechas"),
    }
    return config, data


def _diagnostico(df: pd.DataFrame, schema: dict, dashboard: dict | None, archivo: str, hoja: str) -> tuple[str, str]:
    """El «por qué» y los planes del archivo completo, con el mismo motor que
    los demás informes. Devuelve (html por qué, html planes); vacío si el
    archivo no da para ellos."""
    try:
        from core.dashboard_engine import build_dashboard
        from ui.report_secciones import bloque_gerencia, bloque_planes, calcular_planes
        if dashboard is None:
            dashboard = build_dashboard(df, {"schema": schema})
        plan = calcular_planes(df, schema, dashboard)
    except Exception:
        return "", ""

    def fuente(columnas: str = "") -> str:
        partes = [f"Hoja «{esc(hoja)}» de {esc(archivo)}"] + ([columnas] if columnas else [])
        partes.append(f"{len(df):,} registros · archivo completo al exportar, no cambia con los filtros")
        return " · ".join(partes)

    try:
        por_que = bloque_gerencia(plan.get("gerencia") or dashboard.get("gerencia"), fuente=fuente) or ""
    except Exception:
        por_que = ""
    try:
        planes = bloque_planes(df, schema, dashboard, plan, fuente=fuente) or ""
    except Exception:
        planes = ""
    return por_que, planes


def build_interactive_html_report(df: pd.DataFrame, schema: dict, filename: str, sheet: str,
                                  dashboard: dict | None = None) -> str:
    schema = schema or {}
    largo = None
    try:
        largo = meses_a_filas(df, schema, filename, sheet)
    except Exception:
        largo = None
    base_df, base_schema = largo if largo is not None else (df, schema)
    primaria = (dashboard or {}).get("primary_metric") if largo is None else "Valor"
    config, data = _preparar(base_df, base_schema, primaria)
    config.update({"archivo": str(filename), "hoja": str(sheet),
                   "generado": datetime.now().strftime("%d/%m/%Y %H:%M")})
    por_que, planes = _diagnostico(df, schema, dashboard, str(filename), str(sheet))

    vista_label = next((d["label"] for d in config["dims"] if d["col"] == config["vista"]), "elemento")
    recorte = (f" Por tamaño, se incluyen las primeras {config['incluidas']:,} de {config['totalFilas']:,} filas."
               if config["incluidas"] < config["totalFilas"] else "")

    filtros = f"""
<section class="ix-bar" id="filtros">
  <div class="ix-row">
    <label class="ix-field"><span>Métrica</span><select id="f_metrica"></select></label>
    <label class="ix-field" id="w_vista"><span>Ver por</span><select id="f_vista"></select></label>
    <label class="ix-field ix-date"><span>Desde</span><select id="f_desde"></select></label>
    <label class="ix-field ix-date"><span>Hasta</span><select id="f_hasta"></select></label>
    <label class="ix-field ix-grow"><span>Buscar</span><input id="f_texto" type="search" placeholder="Nombre, producto, región…"></label>
  </div>
  <div class="ix-row" id="f_dims"></div>
  <div class="ix-row ix-end">
    <div id="f_chips" class="ix-chips"></div>
    <span id="f_count" class="ix-count"></span>
    <button type="button" class="ix-btn ghost" id="f_limpiar">Limpiar filtros</button>
    <button type="button" class="ix-btn" id="f_csv">⬇ CSV filtrado</button>
  </div>
</section>"""

    resumen = seccion(
        "resumen", "Resumen para decidir",
        "Se recalcula con cada filtro: cómo cerró el último mes, qué lo explica y qué tan concentrado está el resultado.",
        '<div id="r_verdict"></div><div class="kpis ix-kpis" id="r_kpis"></div><ul class="bullets" id="r_bullets"></ul>',
        leer="El veredicto compara los dos últimos meses con datos. Si el último llega con menos días de lo "
             "habitual, se comparan los dos anteriores y se avisa. Promedio, participación y posición se "
             "calculan sobre todos los elementos visibles con los filtros, no sobre una selección.",
    )
    atacar = seccion(
        "atacar", "Qué atacar primero",
        "Oportunidades en orden de valor, calculadas con lo que ves ahora.",
        '<div class="gx-opps" id="a_lista"></div>',
        leer="«Recuperar» = volver al promedio de sus 3 meses anteriores. «Llevar a la meta» = cerrar la brecha "
             "del último mes. «Nivelar» = que los que están bajo la mediana recorran la mitad del camino. "
             "El botón de cada tarjeta filtra el tablero a esos casos. Puede diferir un poco del diagnóstico del "
             "archivo completo (más abajo), que además exige que la caída de cada caso esté fuera de su variación normal.",
    )
    graficos = seccion(
        "graficos", "Gráficos",
        "Clic en una barra, un punto o una celda para ver la ficha de ese elemento (o, en la tendencia, para "
        "quedarte con ese mes).",
        """<div class="grid2">
  <div class="chart-card" id="c_trend_card"><div class="chart-head"><h3 id="c_trend_t">Evolución mes a mes</h3><p id="c_trend_s"></p></div><div id="c_trend"></div></div>
  <div class="chart-card" id="c_rank_card"><div class="chart-head"><h3 id="c_rank_t">Ranking</h3><p id="c_rank_s"></p></div><div id="c_rank"></div></div>
  <div class="chart-card" id="c_delta_card"><div class="chart-head"><h3 id="c_delta_t">Quién sumó y quién restó</h3><p id="c_delta_s"></p></div><div id="c_delta"></div></div>
  <div class="chart-card" id="c_part_card"><div class="chart-head"><h3 id="c_part_t">Participación</h3><p id="c_part_s"></p></div><div id="c_part"></div></div>
</div>
<div class="chart-card" id="c_heat_card"><div class="chart-head"><h3 id="c_heat_t">Mapa de calor</h3><p id="c_heat_s"></p></div><div id="c_heat"></div></div>""",
    )
    cada_uno = seccion(
        "cada-uno", f"Cómo va cada uno · {vista_label}",
        "Todos los elementos, con su posición, participación, meta, movimiento y estado. Clic en un encabezado "
        "para ordenar y en una fila para abrir su ficha.",
        """<div class="table-card"><div class="ix-tools"><input id="t_buscar" type="search" placeholder="Buscar en el cuadro…">
<span id="t_ref" class="muted"></span></div><div class="table-scroll" id="t_tabla"></div>
<button type="button" class="ix-btn ghost" id="t_mas" style="margin-top:10px">Mostrar todos</button></div>""",
        leer="Estado: con meta, «Cumple» es 100% o más y «Cerca» de 90% a 99%; sin meta, se compara contra el "
             "promedio de todos (±5%). La línea pequeña es su evolución mes a mes.",
    )
    alertas = seccion(
        "alertas", "Alertas",
        "Lo que se movió fuera de lo normal con los filtros actuales.",
        '<div class="findings" id="al_lista"></div>',
    )
    diagnostico_intro = (
        '<section class="section" id="diagnostico"><div class="sec-head"><span class="sec-num"></span><div>'
        "<h2>Diagnóstico del archivo completo</h2><p>Calculado al exportar sobre todos los datos de la hoja, con el "
        "mismo motor del panel. No cambia con los filtros de arriba.</p></div></div>"
        '<div class="callout warn">Esta parte es una foto fija: úsala como plan de trabajo general. '
        "Para ver cómo cambia en un grupo, usa los filtros y las secciones de arriba.</div></section>"
        if (por_que or planes) else "")
    detalle = seccion(
        "detalle", "Registros",
        "Los registros que quedan con los filtros. Clic en un encabezado para ordenar.",
        '<div class="table-card"><div class="table-scroll" id="d_tabla"></div><div class="ix-pager" id="d_pager"></div></div>',
        fuente=esc(f"Hoja «{sheet}» de {filename}.{recorte}"),
    )

    grupos = [("Análisis en vivo", [("resumen", "Resumen para decidir"), ("atacar", "Qué atacar"),
                                   ("graficos", "Gráficos"), ("cada-uno", "Cómo va cada uno"),
                                   ("alertas", "Alertas")])]
    fijo = ([("diagnostico", "Sobre el diagnóstico")] + ([("por-que", "Por qué y qué atacar")] if por_que else [])
            + ([("planes", "Planes de mejora")] if planes else []))
    if len(fijo) > 1:
        grupos.append(("Archivo completo", fijo))
    grupos.append(("Datos", [("detalle", "Registros")]))
    nav_html = nav(grupos, "Informe interactivo", sheet)

    cover = f"""
<header class="cover">
  <div class="cover-kicker">Panel Analítico Universal · Informe interactivo</div>
  <h1>{esc(sheet)}</h1>
  <p class="lead" id="cv_lead">Cargando…</p>
  <div class="cover-stats" id="cv_stats"></div>
  <div class="cover-meta"><span>Archivo: <b>{esc(filename)}</b></span><span>Periodo: <b>{esc(config['periodo'])}</b></span>
  <span>Generado: <b>{esc(config['generado'])}</b></span><span>Todo se recalcula dentro de este archivo, sin la app ni internet.</span></div>
</header>"""

    ficha = """
<div class="ix-modal" id="fx" hidden><div class="ix-modal-box" role="dialog" aria-modal="true" aria-labelledby="fx_t">
  <div class="ix-modal-head"><div><div class="cover-kicker" id="fx_k"></div><h2 id="fx_t"></h2><p id="fx_s" class="muted"></p></div>
  <button type="button" class="ix-x" id="fx_cerrar" aria-label="Cerrar">✕</button></div>
  <div class="kpis ix-kpis" id="fx_kpis"></div>
  <div class="chart-card"><div class="chart-head"><h3>Evolución frente al promedio del grupo</h3><p id="fx_cs"></p></div><div id="fx_chart"></div></div>
  <div class="grid2" id="fx_desc" style="margin-top:12px"></div>
  <div class="ix-modal-foot"><button type="button" class="ix-btn" id="fx_filtrar">Filtrar solo este</button>
  <button type="button" class="ix-btn ghost" id="fx_cerrar2">Cerrar</button></div>
</div></div>"""

    cuerpo = (cover + filtros + resumen + atacar + graficos + cada_uno + alertas + diagnostico_intro
              + por_que + planes + detalle + ficha
              + f"<footer class='footer'>{config['incluidas']:,} registros incluidos.{esc(recorte)} "
                "Generado por Panel Analítico Universal.</footer>"
              + f"<script>window.__CFG={_json(config)};window.__DATA={_json(data)};</script>"
              + f"<script>{_JS_APP}</script>")
    return documento(f"Informe interactivo — {sheet} · {filename}", cuerpo, nav_html,
                     css_extra=_CSS_EXTRA, head_extra=f"<script>{_plotly_js_bundle()}</script>\n",
                     # Aquí se filtra en vivo: pasar de a una sección esconde los filtros.
                     presentar=False)


_CSS_EXTRA = """
.ix-bar{position:sticky;top:0;z-index:20;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:12px 16px;margin-top:16px;box-shadow:0 6px 20px rgba(15,23,42,.08);display:grid;gap:10px}
.ix-row{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end}
.ix-row:empty{display:none}
.ix-field{display:flex;flex-direction:column;gap:4px;font-size:10px;color:var(--muted);font-weight:800;text-transform:uppercase;letter-spacing:.07em}
.ix-field select,.ix-field input,.ms-btn,.ix-tools input{border:1px solid var(--line);border-radius:9px;padding:7px 10px;font-size:13px;color:var(--ink);background:#fff;font-family:inherit;min-width:140px;text-transform:none;letter-spacing:0;font-weight:500}
.ix-grow{flex:1 1 220px}.ix-grow input{width:100%}
.ms{position:relative}
.ms-btn{cursor:pointer;display:flex;align-items:center;gap:8px;justify-content:space-between;max-width:230px}
.ms-btn span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ms-btn.on{border-color:var(--brand);background:var(--brand-soft);color:var(--brand-dark);font-weight:700}
.ms-btn:after{content:"";width:6px;height:6px;border-right:2px solid currentColor;border-bottom:2px solid currentColor;transform:rotate(45deg);margin-top:-3px;flex:0 0 auto}
.ms-panel{position:absolute;top:calc(100% + 6px);left:0;z-index:30;width:290px;max-height:360px;display:flex;flex-direction:column;background:#fff;border:1px solid var(--line);border-radius:12px;box-shadow:0 12px 32px rgba(15,23,42,.18);padding:10px}
.ms-panel input{border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:12.5px;margin-bottom:6px;font-family:inherit}
.ms-acts{display:flex;gap:10px;font-size:11.5px;margin-bottom:6px}
.ms-acts a{color:var(--brand);cursor:pointer;font-weight:700}
.ms-list{overflow:auto;display:grid;gap:1px}
.ms-list label{display:flex;gap:8px;align-items:center;font-size:12.5px;padding:4px 6px;border-radius:6px;cursor:pointer;text-transform:none;letter-spacing:0;font-weight:500;color:var(--ink)}
.ms-list label:hover{background:var(--line-soft)}
.ms-list label.cero{color:var(--soft)}
.ms-list label small{margin-left:auto;color:var(--muted);font-variant-numeric:tabular-nums}
.ix-end{align-items:center}
.ix-chips{display:flex;flex-wrap:wrap;gap:6px;flex:1}
.ix-chip{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;background:var(--brand-soft);color:var(--brand-dark);border-radius:99px;padding:3px 6px 3px 10px;font-weight:700;max-width:340px}
.ix-chip span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ix-chip button{border:0;background:rgba(228,0,43,.12);color:var(--brand-dark);border-radius:99px;width:18px;height:18px;cursor:pointer;font-size:11px;line-height:1}
.ix-count{font-size:12px;color:var(--muted);white-space:nowrap}
.ix-btn{background:var(--brand);color:#fff;border:1px solid var(--brand);border-radius:9px;padding:8px 14px;font-weight:700;font-size:12.5px;cursor:pointer;font-family:inherit;white-space:nowrap}
.ix-btn:hover{background:var(--brand-dark)}
.ix-btn.ghost{background:#fff;color:var(--brand-dark);border-color:var(--line)}
.ix-btn.ghost:hover{border-color:var(--brand)}
.ix-btn.mini{padding:5px 10px;font-size:11.5px}
.ix-kpis{margin-top:14px}
.kpi-delta.warn{color:var(--warn)}
.gx-opp .ix-btn{margin-top:8px}
.gx-opp{grid-template-columns:34px minmax(0,1fr) 170px}
.ix-tools{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.ix-tools input{min-width:240px}
.ix-tools span{font-size:12px}
#t_tabla table,#d_tabla table{font-size:12.5px}
th.sort{cursor:pointer;user-select:none;white-space:nowrap}
th.sort:hover{color:var(--brand)}
th.sort.on{color:var(--brand-dark)}
th.sort.on:after{content:" ▾"}th.sort.on.asc:after{content:" ▴"}
tr.click{cursor:pointer}tr.click:hover td{background:var(--brand-soft)}
td.pos{color:var(--pos);font-weight:700}td.neg{color:var(--neg);font-weight:700}
.spark{display:block}
.ix-pager{display:flex;gap:8px;align-items:center;justify-content:flex-end;margin-top:10px;font-size:12px;color:var(--muted)}
.ix-modal{position:fixed;inset:0;z-index:80;background:rgba(15,23,42,.55);display:flex;align-items:flex-start;justify-content:center;padding:32px 16px;overflow:auto}
.ix-modal[hidden]{display:none}
.ix-modal-box{background:var(--bg);border-radius:18px;max-width:1040px;width:100%;padding:22px 24px;box-shadow:0 30px 80px rgba(15,23,42,.35)}
.ix-modal-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}
.ix-modal-head .cover-kicker{color:var(--brand)}
.ix-modal-head h2{margin:4px 0 2px;font-size:24px;color:var(--ink);letter-spacing:-.02em}
.ix-x{border:0;background:var(--card);border-radius:10px;width:36px;height:36px;font-size:16px;cursor:pointer;box-shadow:var(--shadow)}
.ix-modal-foot{display:flex;gap:10px;justify-content:flex-end;margin-top:16px}
.fx-bars{display:grid;gap:8px;margin-top:6px}
.fx-bar{display:grid;grid-template-columns:minmax(0,1fr) 90px;gap:4px 10px;font-size:12.5px;align-items:center}
.fx-bar i{grid-column:1/-1;display:block;height:7px;border-radius:99px;background:var(--line-soft);overflow:hidden}
.fx-bar i b{display:block;height:100%;background:#2a78d6;border-radius:99px}
.fx-bar span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fx-bar em{font-style:normal;text-align:right;font-weight:700;font-variant-numeric:tabular-nums}
@media(max-width:860px){.ix-bar{position:static}.ms-panel{width:250px}.ix-modal{padding:10px}.ix-modal-box{padding:16px}}
@media print{.ix-bar,.ix-modal,#t_mas,.ix-pager,.gx-opp .ix-btn{display:none!important}}
"""

# El tablero en el navegador. Es un string normal (no f-string): las llaves
# de JavaScript van tal cual y los datos llegan por window.__CFG/__DATA.
_JS_APP = r"""
(function(){
"use strict";
var C = window.__CFG, D = window.__DATA, N = D.n;
var AZUL = "#2a78d6", GRIS = "#9aa4b2", POS = "#0f8a5f", NEG = "#be123c", MARCA = "#e4002b";
var CATEG = ["#2a78d6","#eb6834","#1baf7a","#eda100","#e87ba4","#008300","#4a3aa7"];
var MES_C = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];
var MES_L = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"];
var UMBRAL_PROMEDIO = 0.05, CERCA_META = 0.90;
function $(id){ return document.getElementById(id); }
function esc(v){ return String(v === null || v === undefined ? "" : v).replace(/[&<>"']/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
function mesC(k){ if(!k) return ""; var p = k.split("-"); return MES_C[+p[1]-1] + " " + p[0]; }
function mesL(k){ if(!k) return ""; var p = k.split("-"); return MES_L[+p[1]-1] + " de " + p[0]; }
function mediana(a){ var b = a.filter(function(x){ return x !== null && isFinite(x); }).sort(function(x,y){ return x-y; }); if(!b.length) return null; var m = Math.floor(b.length/2); return b.length % 2 ? b[m] : (b[m-1]+b[m])/2; }
function media(a){ var b = a.filter(function(x){ return x !== null && isFinite(x); }); return b.length ? b.reduce(function(s,x){ return s+x; },0)/b.length : null; }

// ── Formato ─────────────────────────────────────────────────────────────
var LOC = "es-CO";
function num(v, dec){ return Number(v).toLocaleString(LOC, {maximumFractionDigits: dec === undefined ? 0 : dec, minimumFractionDigits: 0}); }
function compacto(v){
  if(v === null || v === undefined || !isFinite(v)) return "—";
  var a = Math.abs(v);
  if(a >= 1e9) return num(v/1e9, 1) + "B";
  if(a >= 1e6) return num(v/1e6, 1) + "M";
  if(a >= 1e4) return num(v/1e3, 1) + "K";
  return num(v, a < 10 ? 2 : a < 100 ? 1 : 0);
}
function fmtM(v, m){
  if(v === null || v === undefined || !isFinite(v)) return "—";
  if(m && m.pct) return num(m.fraccion ? v*100 : v, 1) + "%";
  return compacto(v);
}
function fmtPct(f, signo){ if(f === null || f === undefined || !isFinite(f)) return "—"; var t = num(f*100, Math.abs(f) < 0.1 ? 1 : 0) + "%"; return (signo && f > 0 ? "+" : "") + t; }
function fmtDelta(v, m){ if(v === null || !isFinite(v)) return "—"; return (v > 0 ? "+" : v < 0 ? "−" : "") + fmtM(Math.abs(v), m); }

// ── Datos ───────────────────────────────────────────────────────────────
var FM = null, FD = null, MESES_TODOS = [];
if(D.fecha){
  FM = new Array(N); FD = new Int8Array(N); var vis = {};
  for(var i = 0; i < N; i++){
    var c = D.fecha.c[i];
    if(c < 0){ FM[i] = null; continue; }
    var s = D.fecha.v[c]; FM[i] = s.slice(0,7); FD[i] = +s.slice(8,10); vis[FM[i]] = 1;
  }
  MESES_TODOS = Object.keys(vis).sort();
}
var DIMS = C.dims, METRICAS = {}; C.metricas.forEach(function(m){ METRICAS[m.col] = m; });
function codigo(col, i){ return D.dims[col].c[i]; }
function nombre(col, cod){ return cod < 0 ? "(vacío)" : D.dims[col].v[cod]; }
function valor(col, i){ if(col === "__conteo__") return 1; var a = D.met[col]; return a ? a[i] : null; }
function dimLabel(col){ for(var k = 0; k < DIMS.length; k++) if(DIMS[k].col === col) return DIMS[k].label; return col; }

var S = {metrica: C.principal, vista: C.vista, filtros: {}, desde: "", hasta: "", texto: "",
         orden: {k: "pos", asc: true}, todos: false, pagina: 0, ordenDet: null, buscarTabla: ""};

// ── Filtros ─────────────────────────────────────────────────────────────
function filas(excluir){
  var out = [], txt = S.texto.trim().toLowerCase(), marcas = null;
  if(txt){
    marcas = {};
    DIMS.forEach(function(d){ var vs = D.dims[d.col].v, arr = new Uint8Array(vs.length);
      for(var k = 0; k < vs.length; k++) if(String(vs[k]).toLowerCase().indexOf(txt) >= 0) arr[k] = 1; marcas[d.col] = arr; });
  }
  var activos = Object.keys(S.filtros).filter(function(c){ return c !== excluir && S.filtros[c] && S.filtros[c].size; });
  for(var i = 0; i < N; i++){
    var ok = true;
    for(var a = 0; a < activos.length; a++){ if(!S.filtros[activos[a]].has(codigo(activos[a], i))){ ok = false; break; } }
    if(!ok) continue;
    if(FM && (S.desde || S.hasta)){ var mk = FM[i]; if(!mk || (S.desde && mk < S.desde) || (S.hasta && mk > S.hasta)) continue; }
    if(marcas){ var hit = false;
      for(var d = 0; d < DIMS.length; d++){ var cc = codigo(DIMS[d].col, i); if(cc >= 0 && marcas[DIMS[d].col][cc]){ hit = true; break; } }
      if(!hit) continue; }
    out.push(i);
  }
  return out;
}

// ── Agregación (un faltante no es cero) ─────────────────────────────────
function acc(){ return {s: 0, n: 0}; }
function sumar(a, v){ if(v === null || v === undefined || !isFinite(v)) return; a.s += v; a.n += 1; }
function res(a, agg){ if(!a || !a.n) return null; return agg === "mean" ? a.s / a.n : a.s; }

function analizar(rows){
  var m = METRICAS[S.metrica], agg = m.agg, mc = m.col, meta = m.meta, vista = S.vista;
  var tot = acc(), totMeta = acc(), porMes = {}, metaMes = {}, dias = {}, G = {};
  for(var r = 0; r < rows.length; r++){
    var i = rows[r], v = valor(mc, i), mk = FM ? FM[i] : null, mv = meta ? valor(meta, i) : null;
    sumar(tot, v); if(meta) sumar(totMeta, mv);
    if(mk){ (porMes[mk] || (porMes[mk] = acc())); sumar(porMes[mk], v);
      if(meta){ (metaMes[mk] || (metaMes[mk] = acc())); sumar(metaMes[mk], mv); }
      if(v !== null && FD[i] > (dias[mk] || 0)) dias[mk] = FD[i]; }
    if(vista){
      var g = codigo(vista, i); if(g < 0) continue;
      var e = G[g] || (G[g] = {cod: g, a: acc(), m: acc(), meses: {}, metaMeses: {}, filas: 0});
      e.filas++; sumar(e.a, v);
      if(mk){ (e.meses[mk] || (e.meses[mk] = acc())); sumar(e.meses[mk], v); }
      if(meta){ sumar(e.m, mv); if(mk){ (e.metaMeses[mk] || (e.metaMeses[mk] = acc())); sumar(e.metaMeses[mk], mv); } }
    }
  }
  var meses = Object.keys(porMes).filter(function(k){ return porMes[k].n > 0; }).sort();
  var serie = meses.map(function(k){ return res(porMes[k], agg); });
  var serieMeta = meta ? meses.map(function(k){ return res(metaMes[k], agg === "mean" ? "mean" : "sum"); }) : null;
  // El último mes a medias hace parecer que todo se desplomó.
  var parcial = false, parcialVol = false;
  if(meses.length >= 3){
    var tip = mediana(meses.slice(0, -1).map(function(k){ return dias[k] || 0; })), ult = dias[meses[meses.length-1]] || 0;
    if(tip >= 20 && ult < tip * 0.7) parcial = true;
    if(!parcial && agg === "sum"){ var prev = mediana(serie.slice(0, -1)); if(prev > 0 && serie[serie.length-1] < prev * 0.5) parcialVol = true; }
  }
  var comp = parcial ? meses.slice(0, -1) : meses;
  var mesA = comp.length >= 2 ? comp[comp.length-2] : null, mesB = comp.length >= 1 ? comp[comp.length-1] : null;
  var vA = mesA ? res(porMes[mesA], agg) : null, vB = mesB ? res(porMes[mesB], agg) : null;
  var sumable = agg === "sum";

  var grupos = Object.keys(G).map(function(k){
    var e = G[k], val = res(e.a, agg), mt = meta ? res(e.m, agg === "mean" ? "mean" : "sum") : null;
    var a = mesA ? res(e.meses[mesA], agg) : null, b = mesB ? res(e.meses[mesB], agg) : null;
    return {cod: e.cod, nombre: nombre(vista, e.cod), valor: val, filas: e.filas, meta: mt,
            cumpl: (mt !== null && mt > 0 && val !== null) ? val / mt : null,
            va: a, vb: b, variacion: (a !== null && a !== 0 && b !== null) ? (b - a) / Math.abs(a) : null,
            // Para el aporte al cambio, en una suma, no aparecer un mes es no aportar.
            delta: sumable && mesA ? (b || 0) - (a || 0) : null,
            serie: meses.map(function(mk){ return res(e.meses[mk], agg); }),
            metaB: (meta && mesB) ? res(e.metaMeses[mesB], agg === "mean" ? "mean" : "sum") : null, _e: e};
  }).filter(function(g){ return g.valor !== null; });
  var valores = grupos.map(function(g){ return g.valor; });
  var promedio = media(valores), totalGrupos = sumable ? valores.reduce(function(s,x){ return s+x; }, 0) : null;
  var usaMeta = grupos.filter(function(g){ return g.cumpl !== null; }).length >= 2;
  var menos = m.menos;
  grupos.forEach(function(g){
    g.part = (sumable && totalGrupos > 0) ? g.valor / totalGrupos : null;
    g.vsProm = promedio ? (g.valor - promedio) / Math.abs(promedio) : null;
    if(usaMeta && g.cumpl !== null){
      if(menos){ g.estado = g.cumpl <= 1 ? "Dentro de la meta" : g.cumpl <= 1.1 ? "Cerca de la meta" : "Por encima de la meta"; g.tono = g.cumpl <= 1 ? "pos" : g.cumpl <= 1.1 ? "warn" : "neg"; }
      else { g.estado = g.cumpl >= 1 ? "Cumple la meta" : g.cumpl >= CERCA_META ? "Cerca de la meta" : "Por debajo de la meta"; g.tono = g.cumpl >= 1 ? "pos" : g.cumpl >= CERCA_META ? "warn" : "neg"; }
    } else if(g.vsProm === null || Math.abs(g.vsProm) < UMBRAL_PROMEDIO){ g.estado = "En el promedio"; g.tono = "warn"; }
    else { var arriba = g.vsProm > 0; g.estado = arriba ? "Sobre el promedio" : "Bajo el promedio"; g.tono = (arriba !== menos) ? "pos" : "neg"; }
  });
  var clave = usaMeta ? "cumpl" : "valor";
  var orden = grupos.slice().sort(function(x, y){
    var a = x[clave], b = y[clave]; if(a === null) return 1; if(b === null) return -1; return menos ? a - b : b - a; });
  orden.forEach(function(g, k){ g.pos = k + 1; });
  var cumplGrupo = null;
  if(usaMeta){ var conMeta = grupos.filter(function(g){ return g.meta > 0; });
    cumplGrupo = sumable ? conMeta.reduce(function(s,g){ return s+g.valor; },0) / conMeta.reduce(function(s,g){ return s+g.meta; },0)
                         : media(conMeta.map(function(g){ return g.cumpl; })); }
  return {m: m, rows: rows, total: res(tot, agg), totalMeta: meta ? res(totMeta, agg === "mean" ? "mean" : "sum") : null,
          meses: meses, serie: serie, serieMeta: serieMeta, parcial: parcial, parcialVol: parcialVol,
          mesA: mesA, mesB: mesB, vA: vA, vB: vB, sumable: sumable, grupos: orden, n: orden.length,
          promedio: promedio, mediana: mediana(valores), usaMeta: usaMeta, cumplGrupo: cumplGrupo, menos: menos,
          totalGrupos: totalGrupos};
}

// Segundo nivel: dentro de un elemento, qué segmento de otra dimensión explica su cambio.
function segundoNivel(A, g){
  if(!A.mesA || !A.sumable) return null;
  var otras = DIMS.filter(function(d){ return d.col !== S.vista; });
  for(var k = 0; k < otras.length; k++){
    var col = otras[k].col, seg = {};
    A.rows.forEach(function(i){
      if(codigo(S.vista, i) !== g.cod) return;
      var mk = FM[i]; if(mk !== A.mesA && mk !== A.mesB) return;
      var v = valor(A.m.col, i); if(v === null || !isFinite(v)) return;
      var c = codigo(col, i); seg[c] = (seg[c] || 0) + (mk === A.mesB ? v : -v);
    });
    var lista = Object.keys(seg).map(function(c){ return {n: nombre(col, +c), d: seg[c]}; });
    if(lista.length < 2) continue;
    lista.sort(function(a, b){ return g.delta < 0 ? a.d - b.d : b.d - a.d; });
    if((g.delta < 0 && lista[0].d < 0) || (g.delta > 0 && lista[0].d > 0))
      return {dim: otras[k].label, nombre: lista[0].n, delta: lista[0].d, peso: g.delta ? lista[0].d / g.delta : null};
  }
  return null;
}

// ── Oportunidades con su valor ──────────────────────────────────────────
function oportunidades(A){
  var ops = [], m = A.m;
  if(!A.sumable || !A.mesB || !A.grupos.length) return ops;
  var iB = A.meses.indexOf(A.mesB), ml = mesL(A.mesB);
  // 1) Recuperar lo perdido: volver al promedio de sus 3 meses anteriores.
  var rec = [];
  A.grupos.forEach(function(g){
    var prev = g.serie.slice(Math.max(0, iB-3), iB).filter(function(x){ return x !== null; });
    if(prev.length < 2) return;
    var base = media(prev), b = g.vb || 0;
    if(base > 0 && ((A.menos && b > base * 1.1) || (!A.menos && b < base * 0.9)))
      rec.push({g: g, monto: Math.abs(base - b), base: base, b: b});
  });
  if(rec.length){ rec.sort(function(a,b){ return b.monto - a.monto; });
    ops.push({titulo: "Recuperar lo perdido", monto: rec.reduce(function(s,x){ return s+x.monto; },0), casos: rec,
      texto: rec.length + " de " + A.n + " quedaron en " + ml + " lejos de su nivel habitual (su promedio de los 3 meses anteriores).",
      accion: "Revisar con cada uno qué cambió en " + ml + ": clientes, visitas, precio, disponibilidad.",
      det: function(x){ return "de " + fmtM(x.base, m) + " a " + fmtM(x.b, m); }}); }
  // 2) Llevar a la meta en el último mes.
  if(A.usaMeta){
    var bajo = [];
    A.grupos.forEach(function(g){ if(g.metaB !== null && g.metaB > 0){ var b = g.vb || 0;
      if((!A.menos && b < g.metaB) || (A.menos && b > g.metaB)) bajo.push({g: g, monto: Math.abs(g.metaB - b), meta: g.metaB, b: b}); } });
    if(bajo.length){ bajo.sort(function(a,b){ return b.monto - a.monto; });
      ops.push({titulo: "Llevar a la meta", monto: bajo.reduce(function(s,x){ return s+x.monto; },0), casos: bajo,
        texto: bajo.length + " de " + A.n + " no llegaron a su meta en " + ml + ".",
        accion: "Fijar con cada uno la brecha semanal y revisarla cada viernes.",
        det: function(x){ return fmtM(x.b, m) + " de " + fmtM(x.meta, m); }}); }
  }
  // 3) Nivelar a los rezagados: la mitad del camino a la mediana, no todo.
  var bs = A.grupos.map(function(g){ return g.vb; }).filter(function(x){ return x !== null; });
  if(bs.length >= 4 && !A.menos){
    var med = mediana(bs), rez = [];
    A.grupos.forEach(function(g){ if(g.vb !== null && g.vb < med) rez.push({g: g, monto: (med - g.vb) / 2, b: g.vb}); });
    if(rez.length){ rez.sort(function(a,b){ return b.monto - a.monto; });
      ops.push({titulo: "Nivelar a los rezagados", monto: rez.reduce(function(s,x){ return s+x.monto; },0), casos: rez,
        texto: rez.length + " de " + A.n + " están bajo la mediana (" + fmtM(med, m) + ") en " + ml + ". Recorrer la mitad del camino vale esto.",
        accion: "Acompañar a los que más lejos están y replicar lo que hacen los de arriba.",
        det: function(x){ return fmtM(x.b, m); }}); }
  }
  ops.sort(function(a,b){ return b.monto - a.monto; });
  return ops;
}

// ── Alertas ─────────────────────────────────────────────────────────────
function alertas(A){
  var out = [], m = A.m;
  if(A.parcial) out.push({t: "warn", h: "El último mes está incompleto", p: mesL(A.meses[A.meses.length-1]) + " trae datos de menos días que los anteriores. Las comparaciones usan " + mesL(A.mesB) + " frente a " + mesL(A.mesA) + "."});
  else if(A.parcialVol) out.push({t: "warn", h: "¿El último mes está completo?", p: mesL(A.mesB) + " vale menos de la mitad de lo habitual. Si todavía no cierra, no lo leas como una caída."});
  if(A.mesA && A.grupos.length){
    var totA = A.grupos.reduce(function(s,g){ return s + (g.va || 0); }, 0);
    var caidas = A.grupos.filter(function(g){ return g.variacion !== null && (A.menos ? g.variacion >= 0.2 : g.variacion <= -0.2) && (!A.sumable || !totA || (g.va || 0) / totA >= 0.03); });
    caidas.sort(function(a,b){ return A.menos ? b.variacion - a.variacion : a.variacion - b.variacion; });
    caidas.slice(0, 5).forEach(function(g){ out.push({t: "neg", h: g.nombre + ": " + fmtPct(g.variacion, true) + " en " + mesC(A.mesB), p: "Pasó de " + fmtM(g.va, m) + " a " + fmtM(g.vb, m) + " frente a " + mesL(A.mesA) + ".", cod: g.cod}); });
    var idx = A.meses.indexOf(A.mesB);
    A.grupos.forEach(function(g){
      if(idx < 3) return; var s = g.serie.slice(idx-3, idx+1); if(s.some(function(x){ return x === null; })) return;
      var baja = s[1] < s[0] && s[2] < s[1] && s[3] < s[2], sube = s[1] > s[0] && s[2] > s[1] && s[3] > s[2];
      if(A.menos ? sube : baja) out.push({t: "warn", h: g.nombre + ": 3 meses seguidos empeorando", p: "De " + fmtM(s[0], m) + " en " + mesC(A.meses[idx-3]) + " a " + fmtM(s[3], m) + " en " + mesC(A.mesB) + ". No es un mes malo: es una tendencia.", cod: g.cod});
    });
    if(A.sumable){
      var fuera = A.grupos.filter(function(g){ return (g.va || 0) > 0 && g.vb === null; });
      if(fuera.length) out.push({t: "warn", h: fuera.length + " sin registros en " + mesC(A.mesB), p: fuera.slice(0,6).map(function(g){ return g.nombre; }).join(", ") + (fuera.length > 6 ? " y otros" : "") + " tenían actividad en " + mesL(A.mesA) + " y ninguna en " + mesL(A.mesB) + "."});
      var nuevos = A.grupos.filter(function(g){ return g.va === null && (g.vb || 0) > 0; });
      if(nuevos.length) out.push({t: "pos", h: nuevos.length + " nuevos en " + mesC(A.mesB), p: nuevos.slice(0,6).map(function(g){ return g.nombre; }).join(", ") + (nuevos.length > 6 ? " y otros" : "") + " no tenían actividad en " + mesL(A.mesA) + "."});
    }
  }
  if(A.usaMeta){
    var lejos = A.grupos.filter(function(g){ return g.cumpl !== null && (A.menos ? g.cumpl > 1.1 : g.cumpl < CERCA_META); });
    if(lejos.length) out.push({t: "neg", h: lejos.length + " de " + A.n + " lejos de su meta", p: lejos.slice(0,6).map(function(g){ return g.nombre + " (" + fmtPct(g.cumpl) + ")"; }).join(", ") + (lejos.length > 6 ? " y otros" : "") + "."});
  }
  return out;
}

// ── Pintar ──────────────────────────────────────────────────────────────
function kpi(label, valorTxt, sub, delta, tono){
  return "<div class='kpi'><div class='kpi-label'>" + esc(label) + "</div><div class='kpi-value'>" + esc(valorTxt) + "</div>" +
    (delta ? "<div class='kpi-delta " + (tono || "") + "'>" + esc(delta) + "</div>" : "") +
    (sub ? "<div class='kpi-sub'>" + esc(sub) + "</div>" : "") + "</div>";
}
function tonoCambio(f, menos){ if(f === null || Math.abs(f) < 0.005) return ""; return (f > 0) !== menos ? "pos" : "neg"; }

function pintarResumen(A){
  var m = A.m, vl = dimLabel(S.vista), cambio = (A.vA !== null && A.vA !== 0 && A.vB !== null) ? (A.vB - A.vA) / Math.abs(A.vA) : null;
  var tono = tonoCambio(cambio, A.menos), lead;
  // Portada
  lead = A.rows.length.toLocaleString(LOC) + " registros con los filtros actuales" +
    (A.total !== null ? " · " + (m.agg === "mean" ? "promedio" : "total") + " de " + m.label.toLowerCase() + ": " + fmtM(A.total, m) : "") +
    (S.vista ? " · " + A.n.toLocaleString(LOC) + " valores de «" + vl + "»" : "") + ".";
  $("cv_lead").textContent = lead;
  var stats = [[fmtM(A.total, m), (m.agg === "mean" ? "Promedio · " : "Total · ") + m.label, ""]];
  if(cambio !== null) stats.push([(cambio > 0 ? "▲ " : cambio < 0 ? "▼ " : "= ") + fmtPct(Math.abs(cambio)), mesC(A.mesB) + " vs " + mesC(A.mesA), tono]);
  if(A.usaMeta) stats.push([fmtPct(A.cumplGrupo), "Cumplimiento de meta", A.cumplGrupo >= 1 ? "pos" : A.cumplGrupo >= CERCA_META ? "warn" : "neg"]);
  stats.push([A.rows.length.toLocaleString(LOC), "Registros", ""]);
  $("cv_stats").innerHTML = stats.map(function(s){ return "<div class='cover-stat " + s[2] + "'><b>" + esc(s[0]) + "</b><span>" + esc(s[1]) + "</span></div>"; }).join("");

  // Veredicto
  var h, p;
  if(cambio !== null){
    var verbo = Math.abs(cambio) < 0.005 ? "se mantuvo" : cambio > 0 ? "subió " + fmtPct(Math.abs(cambio)) : "bajó " + fmtPct(Math.abs(cambio));
    h = m.label + " " + verbo + " en " + mesL(A.mesB) + " frente a " + mesL(A.mesA) + (A.sumable ? ": " + fmtDelta(A.vB - A.vA, m) + "." : ".");
    p = "El último mes con datos cerró en " + fmtM(A.vB, m) + ", frente a " + fmtM(A.vA, m) + " el mes anterior." + (A.parcial ? " El último mes del archivo está incompleto y se dejó fuera de la comparación." : "");
  } else if(A.total !== null){
    h = (m.agg === "mean" ? "Promedio" : "Total") + " de " + m.label.toLowerCase() + ": " + fmtM(A.total, m) + ".";
    p = A.meses.length === 1 ? "Solo hay un mes con datos (" + mesL(A.meses[0]) + "): no hay contra qué comparar." : "El archivo no trae fechas para comparar meses.";
  } else { h = "Sin datos con estos filtros."; p = "Quita algún filtro para ver resultados."; }
  $("r_verdict").innerHTML = "<div class='verdict " + tono + "'><div><h3>" + esc(h) + "</h3><p>" + esc(p) + "</p></div>" +
    (cambio !== null ? "<div class='delta " + tono + "'>" + (cambio > 0 ? "▲ " : cambio < 0 ? "▼ " : "") + fmtPct(Math.abs(cambio)) + "</div>" : "") + "</div>";

  // KPIs
  var ks = [kpi((m.agg === "mean" ? "Promedio · " : "Total · ") + m.label, fmtM(A.total, m), (m.agg === "mean" ? "Promedio" : "Suma") + " de los " + A.rows.length.toLocaleString(LOC) + " registros")];
  if(A.mesB) ks.push(kpi("Último mes · " + mesC(A.mesB), fmtM(A.vB, m), A.mesA ? "Antes: " + fmtM(A.vA, m) + " en " + mesC(A.mesA) : "", cambio !== null ? fmtPct(cambio, true) + " vs " + mesC(A.mesA) : "", tono));
  if(A.usaMeta) ks.push(kpi("Cumplimiento de meta", fmtPct(A.cumplGrupo), fmtM(A.total, m) + " de " + fmtM(A.totalMeta, m), A.grupos.filter(function(g){ return g.tono === "pos"; }).length + " de " + A.n + " cumplen", A.cumplGrupo >= 1 ? "pos" : "neg"));
  if(S.vista){
    ks.push(kpi(vl + " con datos", A.n.toLocaleString(LOC), "Promedio de cada uno: " + fmtM(A.promedio, m)));
    if(A.grupos.length){ var l = A.grupos[0], u = A.grupos[A.grupos.length-1];
      ks.push(kpi("Va primero", l.nombre, A.usaMeta ? fmtPct(l.cumpl) + " de su meta" : fmtM(l.valor, m) + (l.part !== null ? " · " + fmtPct(l.part) + " del total" : "")));
      if(A.grupos.length > 1) ks.push(kpi("Va último", u.nombre, A.usaMeta ? fmtPct(u.cumpl) + " de su meta" : fmtM(u.valor, m) + (u.vsProm !== null ? " · " + fmtPct(u.vsProm, true) + " vs promedio" : ""))); }
  }
  $("r_kpis").innerHTML = ks.join("");

  // Lecturas
  var b = [];
  if(cambio !== null && A.sumable && A.grupos.length > 1){
    var dT = A.vB - A.vA, dir = dT < 0 ? -1 : 1;
    var expl = A.grupos.filter(function(g){ return g.delta * dir > 0; }).sort(function(a,b){ return (b.delta - a.delta) * dir; });
    var contra = A.grupos.filter(function(g){ return g.delta * dir < 0; }).sort(function(a,b){ return (a.delta - b.delta) * dir; });
    if(expl.length && dT !== 0){
      var top = expl.slice(0, 3).map(function(g){ return "<b>" + esc(g.nombre) + "</b> (" + esc(fmtDelta(g.delta, m)) + ")"; }).join(", ");
      // Sobre lo que se movió en esa dirección, no sobre el neto: si otros
      // compensaron, «135% del cambio» no se entiende.
      var mismo = expl.reduce(function(s,g){ return s + g.delta; }, 0);
      var peso = mismo ? expl.slice(0, 3).reduce(function(s,g){ return s + g.delta; }, 0) / mismo : 0;
      var sn = segundoNivel(A, expl[0]);
      b.push("Lo que más explica " + (dir < 0 ? "la caída" : "la subida") + ": " + top + (expl.length > 3 && peso > 0 ? " — " + fmtPct(peso) + " de todo lo que " + (dir < 0 ? "bajó" : "subió") : "") + "." +
        (sn ? " En " + esc(expl[0].nombre) + ", sobre todo " + esc(sn.dim.toLowerCase()) + " <b>" + esc(sn.nombre) + "</b> (" + esc(fmtDelta(sn.delta, m)) + ")." : ""));
    }
    if(contra.length) b.push("En sentido contrario, " + contra.slice(0, 2).map(function(g){ return "<b>" + esc(g.nombre) + "</b> (" + esc(fmtDelta(g.delta, m)) + ")"; }).join(" y ") + (dir < 0 ? " amortiguaron la caída." : " frenaron la subida."));
  }
  if(A.sumable && A.grupos.length >= 3 && A.totalGrupos > 0){
    var ord = A.grupos.slice().sort(function(a,b){ return b.valor - a.valor; }), acum = 0, k80 = 0;
    for(var k = 0; k < ord.length; k++){ acum += ord[k].valor; if(acum / A.totalGrupos >= 0.8){ k80 = k + 1; break; } }
    var t3 = ord.slice(0, 3).reduce(function(s,g){ return s + g.valor; }, 0) / A.totalGrupos;
    b.push("Concentración: los 3 primeros suman el " + fmtPct(t3) + " del total" + (k80 ? " y " + k80 + " de " + A.n + " hacen el 80%" : "") + "." + (t3 >= 0.6 && A.n >= 8 ? " El resultado depende de pocos: cuidar a esos es prioridad." : ""));
  }
  if(A.usaMeta){
    var cumplen = A.grupos.filter(function(g){ return g.tono === "pos"; }).length;
    b.push(cumplen + " de " + A.n + " cumplen su meta; el grupo completo va al " + fmtPct(A.cumplGrupo) + ".");
  } else if(A.grupos.length >= 3 && A.promedio){
    var bajo = A.grupos.filter(function(g){ return g.tono === "neg"; }).length;
    b.push(bajo + " de " + A.n + " están por " + (A.menos ? "encima" : "debajo") + " del promedio del grupo (" + fmtM(A.promedio, m) + ") en más de 5%.");
  }
  if(A.serie.length >= 4){
    var s = A.serie.slice(-4);
    if(s.every(function(x){ return x !== null; })){
      if(s[3] < s[2] && s[2] < s[1] && s[1] < s[0]) b.push("El total lleva 3 meses seguidos bajando: no es un mes malo, es una tendencia.");
      else if(s[3] > s[2] && s[2] > s[1] && s[1] > s[0]) b.push("El total lleva 3 meses seguidos subiendo.");
    }
  }
  $("r_bullets").innerHTML = b.map(function(x){ return "<li>" + x + "</li>"; }).join("");
}

function pintarAtacar(A){
  var ops = oportunidades(A), el = $("a_lista"), m = A.m;
  $("atacar").style.display = "";
  if(!ops.length){
    el.innerHTML = "<div class='empty'>" + (A.sumable ? (A.mesB ? "Con estos filtros no hay brechas que valga la pena atacar: todos están en su nivel habitual." : "Hace falta una fecha para comparar meses y calcular oportunidades.") : m.label + " se promedia (no se suma): las oportunidades en valor se calculan con métricas que se suman.") + "</div>";
    return;
  }
  var base = A.vB || 0;
  el.innerHTML = ops.map(function(o, k){
    var quienes = o.casos.slice(0, 4).map(function(x){ return "<b>" + esc(x.g.nombre) + "</b> " + esc(o.det(x)); }).join(" · ") + (o.casos.length > 4 ? " · y " + (o.casos.length - 4) + " más" : "");
    return "<div class='gx-opp'><div class='gx-num'>" + (k+1) + "</div><div><b class='gx-opp-t'>" + esc(o.titulo) + "</b><p>" + esc(o.texto) + "</p>" +
      "<p class='gx-quien'>" + quienes + "</p><p>→ " + esc(o.accion) + "</p>" +
      "<button type='button' class='ix-btn mini ghost' data-op='" + k + "'>Filtrar a estos " + o.casos.length + "</button></div>" +
      "<div class='gx-monto'><b>" + esc(fmtM(o.monto, m)) + "</b><small>al mes" + (base > 0 ? " · " + fmtPct(o.monto / base) + " de " + mesC(A.mesB) : "") + "</small></div></div>";
  }).join("");
  el.querySelectorAll("[data-op]").forEach(function(btn){ btn.addEventListener("click", function(){
    var o = ops[+btn.getAttribute("data-op")]; S.filtros[S.vista] = new Set(o.casos.map(function(x){ return x.g.cod; })); render(); pintarDims();
    $("resumen").scrollIntoView({behavior: "smooth"}); }); });
}

// ── Gráficos ────────────────────────────────────────────────────────────
function base(h){
  return {height: h || 320, margin: {l: 64, r: 18, t: 10, b: 46}, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: {family: "Inter,Segoe UI,Arial,sans-serif", size: 12, color: "#1e293b"}, showlegend: false,
    xaxis: {gridcolor: "#eef1f5", zeroline: false, automargin: true}, yaxis: {gridcolor: "#eef1f5", zeroline: false, automargin: true},
    hoverlabel: {bgcolor: "#fff", bordercolor: "#e2e8f0", font: {color: "#0f172a"}}};
}
var CFG_P = {displayModeBar: false, responsive: true};
function pintar(id, trazas, layout, alClic){
  var el = $(id); Plotly.react(el, trazas, layout, CFG_P);
  if(alClic && !el.__clic){ el.__clic = true; el.on("plotly_click", function(ev){ if(ev && ev.points && ev.points[0]) el.__fn(ev.points[0]); }); }
  el.__fn = alClic;
}
function tarjeta(id, visible){ $(id).style.display = visible ? "" : "none"; }
// Rango del eje con aire a ambos lados: la etiqueta de una barra negativa
// quedaba encima del nombre de la categoría.
function rango(vals){ var v = vals.filter(function(x){ return x !== null && isFinite(x); }); if(!v.length) return undefined;
  var mn = Math.min(0, Math.min.apply(null, v)), mx = Math.max(0, Math.max.apply(null, v)), pad = (mx - mn) * 0.22 || 1;
  return [mn < 0 ? mn - pad : 0, mx > 0 ? mx + pad : 0]; }
function tickFmt(m){ return m.pct ? (m.fraccion ? ".0%" : "") : "~s"; }

function pintarGraficos(A){
  var m = A.m, vl = dimLabel(S.vista);
  // Tendencia
  tarjeta("c_trend_card", A.meses.length >= 2);
  if(A.meses.length >= 2){
    $("c_trend_t").textContent = m.label + " mes a mes";
    $("c_trend_s").textContent = (m.agg === "mean" ? "Promedio" : "Suma") + " por mes" + (A.serieMeta ? " · gris = meta" : "") + " · clic en un mes para quedarte solo con él";
    var x = A.meses.map(mesC), tr = [{x: x, y: A.serie, type: "scatter", mode: "lines+markers", name: m.label, line: {color: AZUL, width: 2.5}, marker: {size: 8, color: AZUL},
      customdata: A.meses, text: A.serie.map(function(v){ return fmtM(v, m); }), hovertemplate: "%{x}: <b>%{text}</b><extra></extra>"}];
    if(A.serieMeta) tr.push({x: x, y: A.serieMeta, type: "scatter", mode: "lines", name: m.metaLabel || "Meta", line: {color: GRIS, width: 2, dash: "dash"},
      text: A.serieMeta.map(function(v){ return fmtM(v, m); }), hovertemplate: "Meta %{x}: %{text}<extra></extra>"});
    // Una línea no necesita arrancar en cero: con el cero, una caída de 5% se ve plana.
    var L = base(320); L.yaxis.tickformat = tickFmt(m);
    if(A.serieMeta){ L.showlegend = true; L.legend = {orientation: "h", y: 1.12, x: 0}; }
    pintar("c_trend", tr, L, function(p){ if(p.customdata){ S.desde = S.hasta = p.customdata; sincronizarFechas(); render(); } });
  }
  // Ranking
  tarjeta("c_rank_card", A.grupos.length >= 2);
  if(A.grupos.length >= 2){
    var top = A.grupos.slice(0, 15), porMeta = A.usaMeta;
    $("c_rank_t").textContent = (porMeta ? "Cumplimiento de meta por " : m.label + " por ") + vl.toLowerCase();
    $("c_rank_s").textContent = (A.n > 15 ? "Los 15 primeros de " + A.n : "Los " + A.n) + " · la línea marca " + (porMeta ? "el 100%" : "el promedio de los " + A.n);
    var ys = top.map(function(g){ return porMeta ? g.cumpl : g.valor; });
    var L2 = base(Math.max(260, top.length * 26 + 70)); L2.margin.l = 10; L2.yaxis.autorange = "reversed"; L2.xaxis.tickformat = porMeta ? ".0%" : tickFmt(m);
    L2.xaxis.range = rango(ys.concat([porMeta ? 1 : A.promedio]));
    L2.shapes = [{type: "line", xref: "x", yref: "paper", x0: porMeta ? 1 : A.promedio, x1: porMeta ? 1 : A.promedio, y0: 0, y1: 1, line: {color: "#64748b", width: 1.5, dash: "dot"}}];
    pintar("c_rank", [{type: "bar", orientation: "h", x: ys, y: top.map(function(g){ return g.pos + ". " + g.nombre; }), customdata: top.map(function(g){ return g.cod; }),
      marker: {color: top.map(function(g){ return g.tono === "neg" ? "#9fc0ea" : AZUL; })},
      text: top.map(function(g){ return porMeta ? fmtPct(g.cumpl) : fmtM(g.valor, m); }), textposition: "outside", cliponaxis: false,
      hovertemplate: "%{y}: <b>%{text}</b><extra></extra>"}], L2, function(p){ abrirFicha(p.customdata); });
  }
  // Aporte al cambio
  var conDelta = A.grupos.filter(function(g){ return g.delta !== null && g.delta !== 0; });
  tarjeta("c_delta_card", A.sumable && !!A.mesA && conDelta.length >= 2);
  if(A.sumable && A.mesA && conDelta.length >= 2){
    var sel = conDelta.slice().sort(function(a,b){ return Math.abs(b.delta) - Math.abs(a.delta); }).slice(0, 12).sort(function(a,b){ return a.delta - b.delta; });
    $("c_delta_t").textContent = "Quién sumó y quién restó";
    $("c_delta_s").textContent = vl + " · cambio de cada uno de " + mesC(A.mesA) + " a " + mesC(A.mesB) + (conDelta.length > 12 ? " · los 12 que más movieron" : "");
    var L3 = base(Math.max(260, sel.length * 26 + 70)); L3.margin.l = 10; L3.xaxis.tickformat = tickFmt(m);
    L3.xaxis.range = rango(sel.map(function(g){ return g.delta; })); L3.xaxis.zeroline = true; L3.xaxis.zerolinecolor = "#94a3b8";
    pintar("c_delta", [{type: "bar", orientation: "h", x: sel.map(function(g){ return g.delta; }), y: sel.map(function(g){ return g.nombre; }), customdata: sel.map(function(g){ return g.cod; }),
      marker: {color: sel.map(function(g){ return (g.delta > 0) !== A.menos ? POS : NEG; })},
      text: sel.map(function(g){ return fmtDelta(g.delta, m); }), textposition: "outside", cliponaxis: false,
      hovertemplate: "%{y}: <b>%{text}</b><extra></extra>"}], L3, function(p){ abrirFicha(p.customdata); });
  }
  // Participación
  var positivos = A.grupos.filter(function(g){ return g.valor > 0; });
  tarjeta("c_part_card", A.sumable && positivos.length >= 2 && positivos.length === A.grupos.length);
  if(A.sumable && positivos.length >= 2 && positivos.length === A.grupos.length){
    var ordP = positivos.slice().sort(function(a,b){ return b.valor - a.valor; }), top6 = ordP.slice(0, 6), resto = ordP.slice(6).reduce(function(s,g){ return s + g.valor; }, 0);
    var labs = top6.map(function(g){ return g.nombre; }), vals = top6.map(function(g){ return g.valor; }), cods = top6.map(function(g){ return g.cod; });
    if(resto > 0){ labs.push("Otros (" + (ordP.length - 6) + ")"); vals.push(resto); cods.push(null); }
    $("c_part_t").textContent = "Participación en el total";
    $("c_part_s").textContent = vl + " · cuánto aporta cada uno al total de " + m.label.toLowerCase();
    var L4 = base(320); L4.margin = {l: 10, r: 10, t: 10, b: 10}; L4.showlegend = true; L4.legend = {orientation: "v", x: 1, y: 0.5};
    pintar("c_part", [{type: "pie", hole: 0.55, labels: labs, values: vals, customdata: cods, sort: false, direction: "clockwise",
      marker: {colors: labs.map(function(_, k){ return (resto > 0 && k === labs.length - 1) ? GRIS : CATEG[k % CATEG.length]; }), line: {color: "#fff", width: 2}},
      textinfo: "percent", hovertemplate: "%{label}: <b>%{percent}</b><extra></extra>"}], L4, function(p){ if(p.customdata !== null && p.customdata !== undefined) abrirFicha(p.customdata); });
  }
  // Mapa de calor
  tarjeta("c_heat_card", A.meses.length >= 2 && A.grupos.length >= 2);
  if(A.meses.length >= 2 && A.grupos.length >= 2){
    var hs = A.grupos.slice().sort(function(a,b){ return b.valor - a.valor; }).slice(0, 20);
    $("c_heat_t").textContent = vl + " × mes";
    $("c_heat_s").textContent = m.label + " de cada uno por mes" + (A.n > 20 ? " · los 20 de mayor valor" : "") + " · más intenso = más alto; en blanco, sin datos";
    var L5 = base(Math.max(240, hs.length * 24 + 80)); L5.margin.l = 10; L5.yaxis.autorange = "reversed"; L5.xaxis.side = "top";
    pintar("c_heat", [{type: "heatmap", x: A.meses.map(mesC), y: hs.map(function(g){ return g.nombre; }), z: hs.map(function(g){ return g.serie; }),
      customdata: hs.map(function(g){ return A.meses.map(function(){ return g.cod; }); }),
      text: hs.map(function(g){ return g.serie.map(function(v){ return fmtM(v, m); }); }), texttemplate: hs.length * A.meses.length <= 160 ? "%{text}" : "",
      colorscale: [[0, "#f1f6fd"], [1, "#2a78d6"]], showscale: false, xgap: 2, ygap: 2,
      hovertemplate: "%{y} · %{x}: <b>%{text}</b><extra></extra>"}], L5, function(p){ abrirFicha(p.customdata); });
  }
}

// ── Cuadro «cómo va cada uno» ───────────────────────────────────────────
function spark(serie){
  var pts = [], vs = serie.filter(function(v){ return v !== null; }); if(vs.length < 2) return "";
  var mn = Math.min.apply(null, vs), mx = Math.max.apply(null, vs), w = 84, h = 22, n = serie.length;
  serie.forEach(function(v, k){ if(v === null) return; var x = n > 1 ? k / (n - 1) * (w - 4) + 2 : w / 2, y = mx === mn ? h / 2 : h - 3 - (v - mn) / (mx - mn) * (h - 6); pts.push(x.toFixed(1) + "," + y.toFixed(1)); });
  var ult = pts[pts.length - 1].split(",");
  return "<svg class='spark' width='" + w + "' height='" + h + "' viewBox='0 0 " + w + " " + h + "'><polyline fill='none' stroke='" + AZUL + "' stroke-width='1.6' points='" + pts.join(" ") + "'/><circle cx='" + ult[0] + "' cy='" + ult[1] + "' r='2.6' fill='" + AZUL + "'/></svg>";
}
function pintarTabla(A){
  var m = A.m, el = $("t_tabla"), vl = dimLabel(S.vista);
  $("cada-uno").style.display = S.vista ? "" : "none"; if(!S.vista) return;
  $("cada-uno").querySelector("h2").textContent = "Cómo va cada uno · " + vl;
  $("t_ref").textContent = A.n ? "Referencia: promedio de los " + A.n + " = " + fmtM(A.promedio, m) + (A.usaMeta ? " · el grupo va al " + fmtPct(A.cumplGrupo) + " de su meta" : "") : "";
  var cols = [{k: "pos", t: "#", num: true, f: function(g){ return g.pos + ".º"; }},
              {k: "nombre", t: vl, f: function(g){ return "<b>" + esc(g.nombre) + "</b>"; }},
              {k: "valor", t: m.label, num: true, f: function(g){ return esc(fmtM(g.valor, m)); }}];
  if(A.usaMeta){ cols.push({k: "meta", t: m.metaLabel || "Meta", num: true, f: function(g){ return esc(fmtM(g.meta, m)); }});
                 cols.push({k: "cumpl", t: "Cumplimiento", num: true, f: function(g){ return esc(fmtPct(g.cumpl)); }, cls: function(g){ return g.cumpl === null ? "" : (A.menos ? g.cumpl <= 1 : g.cumpl >= 1) ? "pos" : "neg"; }}); }
  if(A.sumable) cols.push({k: "part", t: "Participación", num: true, f: function(g){ return esc(fmtPct(g.part)); }});
  cols.push({k: "vsProm", t: "vs promedio de los " + A.n, num: true, f: function(g){ return esc(fmtPct(g.vsProm, true)); }, cls: function(g){ return g.vsProm === null || Math.abs(g.vsProm) < UMBRAL_PROMEDIO ? "" : (g.vsProm > 0) !== A.menos ? "pos" : "neg"; }});
  if(A.mesA){ cols.push({k: "va", t: mesC(A.mesA), num: true, f: function(g){ return esc(fmtM(g.va, m)); }});
              cols.push({k: "vb", t: mesC(A.mesB), num: true, f: function(g){ return esc(fmtM(g.vb, m)); }});
              cols.push({k: "variacion", t: "Variación", num: true, f: function(g){ return esc(fmtPct(g.variacion, true)); }, cls: function(g){ return g.variacion === null || Math.abs(g.variacion) < 0.005 ? "" : (g.variacion > 0) !== A.menos ? "pos" : "neg"; }}); }
  if(A.meses.length >= 2) cols.push({k: null, t: "Tendencia", f: function(g){ return spark(g.serie); }});
  cols.push({k: "filas", t: "Registros", num: true, f: function(g){ return g.filas.toLocaleString(LOC); }});
  cols.push({k: "estado", t: "Estado", f: function(g){ return "<span class='pill " + g.tono + "'>" + esc(g.estado) + "</span>"; }});
  var lista = A.grupos.slice(), q = S.buscarTabla.trim().toLowerCase();
  if(q) lista = lista.filter(function(g){ return String(g.nombre).toLowerCase().indexOf(q) >= 0; });
  var o = S.orden, k = o.k;
  if(!cols.some(function(c){ return c.k === k; })) { k = o.k = "pos"; o.asc = true; }
  lista.sort(function(a, b){ var x = a[k], y = b[k]; if(x === null || x === undefined) return 1; if(y === null || y === undefined) return -1;
    var r = typeof x === "string" ? x.localeCompare(y, "es") : x - y; return o.asc ? r : -r; });
  var total = lista.length, vis = S.todos ? lista : lista.slice(0, 30);
  el.innerHTML = total ? "<table><thead><tr>" + cols.map(function(c){ return "<th class='" + (c.num ? "num " : "") + (c.k ? "sort" + (c.k === o.k ? " on" + (o.asc ? " asc" : "") : "") : "") + "'" + (c.k ? " data-k='" + c.k + "'" : "") + ">" + esc(c.t) + "</th>"; }).join("") +
    "</tr></thead><tbody>" + vis.map(function(g){ return "<tr class='click' data-cod='" + g.cod + "'>" + cols.map(function(c){ return "<td class='" + (c.num ? "num " : "") + (c.cls ? c.cls(g) : "") + "'>" + c.f(g) + "</td>"; }).join("") + "</tr>"; }).join("") + "</tbody></table>"
    : "<div class='empty'>Sin elementos con estos filtros.</div>";
  var mas = $("t_mas"); mas.style.display = total > 30 ? "" : "none"; mas.textContent = S.todos ? "Mostrar solo 30" : "Mostrar los " + total;
  el.querySelectorAll("th.sort").forEach(function(th){ th.addEventListener("click", function(){ var kk = th.getAttribute("data-k");
    if(S.orden.k === kk) S.orden.asc = !S.orden.asc; else { S.orden.k = kk; S.orden.asc = kk === "pos" || kk === "nombre"; } pintarTabla(ULTIMO); }); });
  el.querySelectorAll("tr.click").forEach(function(tr){ tr.addEventListener("click", function(){ abrirFicha(+tr.getAttribute("data-cod")); }); });
}

function pintarAlertas(A){
  var al = alertas(A), el = $("al_lista");
  el.innerHTML = al.length ? al.slice(0, 14).map(function(a){
    return "<div class='finding " + a.t + "'><span class='dot'></span><div><h3>" + esc(a.h) + "</h3><p>" + esc(a.p) + "</p>" +
      (a.cod !== undefined ? "<p class='action'><a href='#' data-cod='" + a.cod + "'>Ver ficha →</a></p>" : "") + "</div></div>"; }).join("") +
    (al.length > 14 ? "<p class='note'>Y " + (al.length - 14) + " alertas más: usa los filtros para acotar.</p>" : "")
    : "<div class='empty'>Sin alertas con estos filtros: nada se movió fuera de lo normal.</div>";
  el.querySelectorAll("a[data-cod]").forEach(function(a){ a.addEventListener("click", function(e){ e.preventDefault(); abrirFicha(+a.getAttribute("data-cod")); }); });
}

// ── Registros ───────────────────────────────────────────────────────────
var POR_PAGINA = 50;
function columnasDetalle(){
  var cols = [];
  if(FM) cols.push({t: C.fechaLabel || "Fecha", v: function(i){ var c = D.fecha.c[i]; return c < 0 ? "" : D.fecha.v[c]; }});
  DIMS.forEach(function(d){ cols.push({t: d.label, v: function(i){ var c = codigo(d.col, i); return c < 0 ? "" : D.dims[d.col].v[c]; }}); });
  Object.keys(D.met).forEach(function(mc){ var mm = METRICAS[mc]; cols.push({t: mm ? mm.label : mc, num: true, v: function(i){ return D.met[mc][i]; }, m: mm}); });
  return cols;
}
var COLS_DET = null;
function pintarDetalle(A){
  COLS_DET = COLS_DET || columnasDetalle();
  var rows = A.rows.slice(), o = S.ordenDet;
  if(o){ var col = COLS_DET[o.i]; rows.sort(function(a, b){ var x = col.v(a), y = col.v(b); if(x === null || x === "") return 1; if(y === null || y === "") return -1;
    var r = typeof x === "number" ? x - y : String(x).localeCompare(String(y), "es"); return o.asc ? r : -r; }); }
  var paginas = Math.max(1, Math.ceil(rows.length / POR_PAGINA)); if(S.pagina >= paginas) S.pagina = paginas - 1;
  var vis = rows.slice(S.pagina * POR_PAGINA, (S.pagina + 1) * POR_PAGINA);
  $("d_tabla").innerHTML = rows.length ? "<table><thead><tr>" + COLS_DET.map(function(c, k){ return "<th class='sort" + (c.num ? " num" : "") + (o && o.i === k ? " on" + (o.asc ? " asc" : "") : "") + "' data-i='" + k + "'>" + esc(c.t) + "</th>"; }).join("") + "</tr></thead><tbody>" +
    vis.map(function(i){ return "<tr>" + COLS_DET.map(function(c){ var v = c.v(i); return "<td" + (c.num ? " class='num'" : "") + ">" + (c.num ? esc(v === null || v === undefined ? "—" : (c.m && c.m.pct ? fmtM(v, c.m) : Number(v).toLocaleString(LOC, {maximumFractionDigits: 2}))) : esc(v)) + "</td>"; }).join("") + "</tr>"; }).join("") + "</tbody></table>"
    : "<div class='empty'>Sin registros con estos filtros.</div>";
  $("d_pager").innerHTML = rows.length > POR_PAGINA ? "<span>" + (S.pagina * POR_PAGINA + 1).toLocaleString(LOC) + "–" + Math.min(rows.length, (S.pagina + 1) * POR_PAGINA).toLocaleString(LOC) + " de " + rows.length.toLocaleString(LOC) + "</span>" +
    "<button type='button' class='ix-btn mini ghost' data-p='-1'" + (S.pagina ? "" : " disabled") + ">‹ Anterior</button><button type='button' class='ix-btn mini ghost' data-p='1'" + (S.pagina < paginas - 1 ? "" : " disabled") + ">Siguiente ›</button>" : "";
  $("d_pager").querySelectorAll("[data-p]").forEach(function(b){ b.addEventListener("click", function(){ S.pagina += +b.getAttribute("data-p"); pintarDetalle(ULTIMO); }); });
  $("d_tabla").querySelectorAll("th.sort").forEach(function(th){ th.addEventListener("click", function(){ var i = +th.getAttribute("data-i");
    S.ordenDet = (S.ordenDet && S.ordenDet.i === i) ? {i: i, asc: !S.ordenDet.asc} : {i: i, asc: !COLS_DET[i].num}; S.pagina = 0; pintarDetalle(ULTIMO); }); });
}
function exportarCsv(){
  COLS_DET = COLS_DET || columnasDetalle();
  var rows = ULTIMO ? ULTIMO.rows : filas(); if(!rows.length) return;
  var q = function(v){ v = v === null || v === undefined ? "" : String(v); return /[",;\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  var lineas = [COLS_DET.map(function(c){ return q(c.t); }).join(",")].concat(rows.map(function(i){ return COLS_DET.map(function(c){ return q(c.v(i)); }).join(","); }));
  var blob = new Blob(["\ufeff" + lineas.join("\n")], {type: "text/csv;charset=utf-8;"}), a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "datos_filtrados.csv"; document.body.appendChild(a); a.click(); a.remove();
}

// ── Ficha de un elemento ────────────────────────────────────────────────
var FICHA = null;
function abrirFicha(cod){
  if(cod === null || cod === undefined || !ULTIMO) return;
  var A = ULTIMO, m = A.m, g = null; A.grupos.forEach(function(x){ if(x.cod === cod) g = x; }); if(!g) return;
  FICHA = cod; var vl = dimLabel(S.vista);
  $("fx_k").textContent = vl; $("fx_t").textContent = g.nombre;
  $("fx_s").textContent = g.pos + ".º de " + A.n + (A.usaMeta ? " por cumplimiento de meta" : " por " + m.label.toLowerCase()) + " · " + g.filas.toLocaleString(LOC) + " registros · con los filtros actuales";
  var ks = [kpi(m.label, fmtM(g.valor, m), m.agg === "mean" ? "Promedio de sus registros" : "Suma de sus registros")];
  if(g.part !== null) ks.push(kpi("Participación", fmtPct(g.part), "del total de los " + A.n));
  ks.push(kpi("vs promedio del grupo", fmtPct(g.vsProm, true), "Promedio de los " + A.n + ": " + fmtM(A.promedio, m), "", tonoCambio(g.vsProm, A.menos)));
  if(g.cumpl !== null) ks.push(kpi("Cumplimiento de meta", fmtPct(g.cumpl), fmtM(g.valor, m) + " de " + fmtM(g.meta, m), g.estado, g.tono));
  if(A.mesA) ks.push(kpi("Último mes · " + mesC(A.mesB), fmtM(g.vb, m), "Antes: " + fmtM(g.va, m), g.variacion !== null ? fmtPct(g.variacion, true) + " vs " + mesC(A.mesA) : "", tonoCambio(g.variacion, A.menos)));
  $("fx_kpis").innerHTML = ks.join("");
  var sn = g.delta ? segundoNivel(A, g) : null;
  $("fx_cs").textContent = "Azul = " + g.nombre + " · gris = promedio de los " + A.n + " cada mes" + (sn ? " · su cambio viene sobre todo de " + sn.dim.toLowerCase() + " " + sn.nombre + " (" + fmtDelta(sn.delta, m) + ")" : "");
  $("fx").hidden = false; document.body.style.overflow = "hidden";
  if(A.meses.length >= 2){
    $("fx_chart").parentNode.style.display = "";
    var prom = A.meses.map(function(_, k){ return media(A.grupos.map(function(x){ return x.serie[k]; })); });
    var L = base(300); L.showlegend = true; L.legend = {orientation: "h", y: 1.12, x: 0}; L.yaxis.tickformat = tickFmt(m); if(A.sumable) L.yaxis.rangemode = "tozero";
    Plotly.react($("fx_chart"), [
      {x: A.meses.map(mesC), y: g.serie, type: "scatter", mode: "lines+markers", name: g.nombre, line: {color: AZUL, width: 2.5}, marker: {size: 8}, text: g.serie.map(function(v){ return fmtM(v, m); }), hovertemplate: "%{x}: <b>%{text}</b><extra></extra>"},
      {x: A.meses.map(mesC), y: prom, type: "scatter", mode: "lines", name: "Promedio de los " + A.n, line: {color: GRIS, width: 2, dash: "dash"}, text: prom.map(function(v){ return fmtM(v, m); }), hovertemplate: "Promedio %{x}: %{text}<extra></extra>"}
    ], L, CFG_P);
  } else { $("fx_chart").parentNode.style.display = "none"; }
  // En qué se descompone, por las otras dimensiones.
  var otras = DIMS.filter(function(d){ return d.col !== S.vista; }).slice(0, 4), html = "";
  otras.forEach(function(d){
    var seg = {}, t = acc();
    A.rows.forEach(function(i){ if(codigo(S.vista, i) !== cod) return; var c = codigo(d.col, i); (seg[c] || (seg[c] = acc())); var v = valor(m.col, i); sumar(seg[c], v); sumar(t, v); });
    var lista = Object.keys(seg).map(function(c){ return {n: nombre(d.col, +c), v: res(seg[c], m.agg)}; }).filter(function(x){ return x.v !== null; });
    if(lista.length < 2) return;
    lista.sort(function(a,b){ return b.v - a.v; }); var mx = Math.max.apply(null, lista.map(function(x){ return Math.abs(x.v); })) || 1;
    html += "<div class='table-card'><div class='chart-head'><h3>Por " + esc(d.label.toLowerCase()) + "</h3><p>" + (lista.length > 8 ? "Los 8 de mayor valor de " + lista.length : lista.length + " valores") + "</p></div><div class='fx-bars'>" +
      lista.slice(0, 8).map(function(x){ return "<div class='fx-bar'><span>" + esc(x.n) + "</span><em>" + esc(fmtM(x.v, m)) + "</em><i><b style='width:" + Math.max(2, Math.abs(x.v) / mx * 100).toFixed(1) + "%'></b></i></div>"; }).join("") + "</div></div>";
  });
  $("fx_desc").innerHTML = html; $("fx_desc").style.display = html ? "" : "none";
  $("fx_filtrar").textContent = "Filtrar solo " + g.nombre;
}
function cerrarFicha(){ $("fx").hidden = true; document.body.style.overflow = ""; FICHA = null; }

// ── Barra de filtros ────────────────────────────────────────────────────
function opciones(sel, lista, actual){ sel.innerHTML = lista.map(function(o){ return "<option value='" + esc(o[0]) + "'" + (o[0] === actual ? " selected" : "") + ">" + esc(o[1]) + "</option>"; }).join(""); }
function sincronizarFechas(){ if(!FM) return; $("f_desde").value = S.desde; $("f_hasta").value = S.hasta; }
var ABIERTO = null;
function pintarDims(){
  var cont = $("f_dims");
  cont.innerHTML = DIMS.map(function(d){
    var sel = S.filtros[d.col], n = sel ? sel.size : 0, txt = n === 0 ? "Todos" : n === 1 ? nombre(d.col, sel.values().next().value) : n + " seleccionados";
    return "<div class='ix-field ms' data-col='" + esc(d.col) + "'><span>" + esc(d.label) + "</span><button type='button' class='ms-btn" + (n ? " on" : "") + "'><span>" + esc(txt) + "</span></button></div>";
  }).join("");
  cont.querySelectorAll(".ms").forEach(function(box){ box.querySelector(".ms-btn").addEventListener("click", function(e){ e.stopPropagation(); abrirPanel(box); }); });
  pintarChips();
}
function abrirPanel(box){
  cerrarPanel(); var col = box.getAttribute("data-col"), vals = D.dims[col].v, sel = S.filtros[col] || new Set();
  // Conteos con los DEMÁS filtros: así se ve qué opciones quedan con datos.
  var cuenta = new Int32Array(vals.length); filas(col).forEach(function(i){ var c = codigo(col, i); if(c >= 0) cuenta[c]++; });
  var orden = vals.map(function(v, k){ return k; }).sort(function(a, b){ return (cuenta[b] > 0) - (cuenta[a] > 0) || String(vals[a]).localeCompare(String(vals[b]), "es", {numeric: true}); });
  var p = document.createElement("div"); p.className = "ms-panel";
  p.innerHTML = "<input type='search' placeholder='Buscar…'><div class='ms-acts'><a data-a='todos'>Marcar visibles</a><a data-a='ninguno'>Quitar filtro</a></div><div class='ms-list'>" +
    orden.map(function(k){ return "<label class='" + (cuenta[k] ? "" : "cero") + "' data-t='" + esc(String(vals[k]).toLowerCase()) + "'><input type='checkbox' value='" + k + "'" + (sel.has(k) ? " checked" : "") + "> <span>" + esc(vals[k]) + "</span><small>" + cuenta[k].toLocaleString(LOC) + "</small></label>"; }).join("") + "</div>";
  p.addEventListener("click", function(e){ e.stopPropagation(); });
  box.appendChild(p); ABIERTO = box;
  var buscar = p.querySelector("input[type=search]"); buscar.focus();
  buscar.addEventListener("input", function(){ var q = buscar.value.trim().toLowerCase(); p.querySelectorAll(".ms-list label").forEach(function(l){ l.style.display = !q || l.getAttribute("data-t").indexOf(q) >= 0 ? "" : "none"; }); });
  function aplicar(){ var s = new Set(); p.querySelectorAll(".ms-list input:checked").forEach(function(c){ s.add(+c.value); });
    if(s.size && s.size < vals.length) S.filtros[col] = s; else delete S.filtros[col];
    var btn = box.querySelector(".ms-btn"), n = s.size < vals.length ? s.size : 0; btn.classList.toggle("on", !!n);
    btn.querySelector("span").textContent = n === 0 ? "Todos" : n === 1 ? nombre(col, s.values().next().value) : n + " seleccionados";
    S.pagina = 0; render(); pintarChips(); }
  p.querySelectorAll(".ms-list input").forEach(function(c){ c.addEventListener("change", aplicar); });
  p.querySelector("[data-a=todos]").addEventListener("click", function(){ p.querySelectorAll(".ms-list label").forEach(function(l){ if(l.style.display !== "none") l.querySelector("input").checked = true; }); aplicar(); });
  p.querySelector("[data-a=ninguno]").addEventListener("click", function(){ p.querySelectorAll(".ms-list input").forEach(function(c){ c.checked = false; }); aplicar(); });
}
function cerrarPanel(){ if(ABIERTO){ var p = ABIERTO.querySelector(".ms-panel"); if(p) p.remove(); ABIERTO = null; } }
function pintarChips(){
  var chips = [];
  Object.keys(S.filtros).forEach(function(col){ var s = S.filtros[col]; if(!s || !s.size) return;
    var ns = Array.from(s).slice(0, 3).map(function(c){ return nombre(col, c); }); chips.push([dimLabel(col) + ": " + ns.join(", ") + (s.size > 3 ? " +" + (s.size - 3) : ""), "d", col]); });
  if(S.desde || S.hasta) chips.push([(C.fechaLabel || "Fecha") + ": " + (S.desde === S.hasta ? mesC(S.desde) : (S.desde ? mesC(S.desde) : "inicio") + " – " + (S.hasta ? mesC(S.hasta) : "fin")), "f", ""]);
  if(S.texto.trim()) chips.push(["Contiene «" + S.texto.trim() + "»", "t", ""]);
  $("f_chips").innerHTML = chips.map(function(c, k){ return "<span class='ix-chip'><span>" + esc(c[0]) + "</span><button type='button' data-k='" + k + "' title='Quitar'>✕</button></span>"; }).join("");
  $("f_chips").querySelectorAll("button").forEach(function(b){ b.addEventListener("click", function(){ var c = chips[+b.getAttribute("data-k")];
    if(c[1] === "d") delete S.filtros[c[2]]; else if(c[1] === "f"){ S.desde = S.hasta = ""; sincronizarFechas(); } else { S.texto = ""; $("f_texto").value = ""; }
    render(); pintarDims(); }); });
  $("f_limpiar").style.display = chips.length ? "" : "none";
}

// ── Orquestación ────────────────────────────────────────────────────────
var ULTIMO = null;
function render(){
  var rows = filas(), A = analizar(rows); ULTIMO = A;
  $("f_count").textContent = rows.length.toLocaleString(LOC) + " de " + N.toLocaleString(LOC) + " registros";
  pintarResumen(A); pintarAtacar(A); pintarGraficos(A); pintarTabla(A); pintarAlertas(A); pintarDetalle(A);
  if(FICHA !== null && !$("fx").hidden) abrirFicha(FICHA);
}

document.addEventListener("DOMContentLoaded", function(){
  opciones($("f_metrica"), C.metricas.map(function(m){ return [m.col, m.label]; }), S.metrica);
  if(DIMS.length) opciones($("f_vista"), DIMS.map(function(d){ return [d.col, d.label]; }), S.vista); else $("w_vista").style.display = "none";
  if(FM && MESES_TODOS.length > 1){
    opciones($("f_desde"), [["", "Inicio"]].concat(MESES_TODOS.map(function(k){ return [k, mesC(k)]; })), "");
    opciones($("f_hasta"), [["", "Fin"]].concat(MESES_TODOS.map(function(k){ return [k, mesC(k)]; })), "");
  } else document.querySelectorAll(".ix-date").forEach(function(e){ e.style.display = "none"; });
  $("f_metrica").addEventListener("change", function(){ S.metrica = this.value; render(); });
  $("f_vista").addEventListener("change", function(){ S.vista = this.value; S.orden = {k: "pos", asc: true}; S.todos = false; render(); });
  $("f_desde").addEventListener("change", function(){ S.desde = this.value; if(S.hasta && S.desde > S.hasta){ S.hasta = S.desde; sincronizarFechas(); } render(); pintarChips(); });
  $("f_hasta").addEventListener("change", function(){ S.hasta = this.value; if(S.desde && S.hasta < S.desde){ S.desde = S.hasta; sincronizarFechas(); } render(); pintarChips(); });
  var t = null; $("f_texto").addEventListener("input", function(){ var v = this.value; clearTimeout(t); t = setTimeout(function(){ S.texto = v; S.pagina = 0; render(); pintarChips(); }, 220); });
  $("f_limpiar").addEventListener("click", function(){ S.filtros = {}; S.desde = S.hasta = S.texto = ""; $("f_texto").value = ""; sincronizarFechas(); render(); pintarDims(); });
  $("f_csv").addEventListener("click", exportarCsv);
  $("t_buscar").addEventListener("input", function(){ S.buscarTabla = this.value; pintarTabla(ULTIMO); });
  $("t_mas").addEventListener("click", function(){ S.todos = !S.todos; pintarTabla(ULTIMO); });
  $("fx_cerrar").addEventListener("click", cerrarFicha); $("fx_cerrar2").addEventListener("click", cerrarFicha);
  $("fx").addEventListener("click", function(e){ if(e.target === $("fx")) cerrarFicha(); });
  $("fx_filtrar").addEventListener("click", function(){ if(FICHA === null) return; S.filtros[S.vista] = new Set([FICHA]); cerrarFicha(); render(); pintarDims(); });
  document.addEventListener("click", cerrarPanel);
  document.addEventListener("keydown", function(e){ if(e.key === "Escape"){ cerrarPanel(); if(!$("fx").hidden) cerrarFicha(); } });
  pintarDims(); render();
});
})();
"""
