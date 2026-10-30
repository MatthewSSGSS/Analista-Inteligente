"""Explorador analítico (pestaña "Analítica" del modo Analista).

A diferencia de Ejecutivo/Descripción (una lectura fija que el sistema
decide mostrar), aquí el usuario elige la pregunta. Cada "lente" responde una
distinta y trae siempre las mismas cuatro piezas, en este orden:

1. La base: qué métrica, calculada cómo, agrupada por qué, sobre cuántos
   registros y qué fechas. Sin esto un gráfico no se puede defender.
2. El gráfico de esa pregunta.
3. Qué dice: hallazgos con nombre y cifra, calculados en core/explorador.py.
4. La tabla completa, descargable.

Una lente solo aparece si el archivo tiene lo que necesita: sin fechas no
hay evolución; sin pares meta/ejecutado no hay cumplimiento. Todo se calcula
sobre los datos ya filtrados en el menú lateral.

Los nombres que se muestran son los de las columnas del Excel, nunca el
concepto genérico del motor semántico: con "Cantidad" en todas partes no se
sabía cuál de las seis columnas de altas se estaba viendo.
"""
from __future__ import annotations

import html

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from ui.components.escena import NO_DISPONIBLE, botones_ocultos, cabecera, disponible, escena

import core.explorador as ex
from core.diagnostics import _fmt
from core.performance import columna_meta
from ui.components.charts import chart_card, empty_state
from ui.components.section import banner_header
from visualization.charts import CATEGORY_PALETTE, _base, metric_candidates, realzar_barras

VERDE, AMBAR, ROJO, GRIS = "#22A06B", "#F59E0B", "#E4002B", "#94A3B8"
CONTEO = "(conteo de registros)"
SIN_AGRUPAR = "(sin agrupar)"
_MARGEN_EJE = 44

LENTES = {
    "ranking": ("🏆 Ranking", "¿Quién pesa más y cuántos explican el 80% del total?"),
    "evolucion": ("📈 Evolución", "¿Cómo se movió cada grupo en el tiempo?"),
    "periodos": ("⚖️ Periodo vs. periodo", "¿Qué cambió entre dos periodos y quién lo explica?"),
    "cruzada": ("🧮 Tabla cruzada", "¿Cómo se reparte una dimensión dentro de otra?"),
    "cumplimiento": ("🎯 Ejecutado vs. meta", "¿Cuánto se ejecutó de lo presupuestado y dónde falta?"),
    "relacion": ("🔗 Relación", "¿Dos métricas se mueven juntas? ¿Quién rinde más o menos de lo esperado?"),
    "distribucion": ("📦 Distribución", "¿Qué tan parejos son los registros dentro de cada grupo?"),
}


def _css() -> None:
    st.markdown(
        """
        <style>
        .analitica-pregunta{font-size:13px;color:var(--muted);margin:-4px 0 10px}
        .analitica-base{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--teal);
          border-radius:var(--radius-md);padding:10px 14px;margin:4px 0 12px;font-size:12.5px;line-height:1.55 !important;
          color:var(--muted)}
        .analitica-base b{color:var(--text)}
        .analitica-hallazgos{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-md);
          padding:12px 16px 6px;margin:8px 0 14px;box-shadow:var(--shadow-sm)}
        .analitica-hallazgos-titulo{font-size:10.5px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;
          color:var(--muted);margin-bottom:6px}
        .analitica-hallazgos ul{margin:0 0 6px 18px;padding:0}
        .analitica-hallazgos li{font-size:13px;line-height:1.55 !important;color:var(--text);margin-bottom:5px}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _markdown_a_html(texto: str) -> str:
    """Los hallazgos traen **negritas**; se escapa todo lo demás."""
    partes = html.escape(texto).split("**")
    return "".join(f"<b>{p}</b>" if i % 2 else p for i, p in enumerate(partes))


def _hallazgos(frases: list[str]) -> None:
    if not frases:
        return
    items = "".join(f"<li>{_markdown_a_html(f)}</li>" for f in frases)
    st.markdown(f'<div class="analitica-hallazgos"><div class="analitica-hallazgos-titulo">💡 Qué dice</div>'
                f'<ul>{items}</ul></div>', unsafe_allow_html=True)


def _base_texto(partes: list[str]) -> None:
    st.markdown(f'<div class="analitica-base">📐 {" · ".join(partes)}</div>', unsafe_allow_html=True)


def _formato_numero() -> str:
    """"localized" (separador de miles) existe desde Streamlit 1.42; antes, printf."""
    try:
        mayor, menor = (int(x) for x in st.__version__.split(".")[:2])
        return "localized" if (mayor, menor) >= (1, 42) else "%.2f"
    except Exception:
        return "%.2f"


def _tabla(df: pd.DataFrame, nombre: str, clave: str) -> None:
    from core.diagnostics import _fmt
    config = {}
    vista = df.copy()
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]):
            if "%" in str(c):
                config[c] = st.column_config.NumberColumn(c, format="%.1f%%")
            elif df[c].abs().max() >= 100_000:
                # Cifras grandes en la forma corta del panel («1.6 mil M»): con
                # todos los dígitos y decimales («1.613.564.697,544») no se leía
                # ninguna. El CSV de abajo conserva los números completos.
                vista[c] = df[c].map(lambda v: _fmt(v) if pd.notna(v) else "—")
            else:
                config[c] = st.column_config.NumberColumn(c, format=_formato_numero())
    st.dataframe(vista, use_container_width=True, hide_index=True, column_config=config)
    st.download_button("⬇️ Descargar tabla (CSV)", df.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"{nombre}.csv", mime="text/csv", key=f"{clave}_csv")


def _anotar_referencia(fig, x, texto, horizontal=True):
    """Rótulo de la línea de referencia por encima del gráfico, no sobre las barras."""
    if horizontal:
        fig.add_annotation(x=x, y=1, xref="x", yref="paper", yanchor="bottom", showarrow=False,
                           text=f"┆ {texto}", font=dict(size=11, color="#64748B"))
    return fig


def _tono(valor, referencia, arriba_es_bueno=True):
    if referencia is None or not np.isfinite(referencia) or referencia == 0:
        return GRIS
    d = (valor - referencia) / abs(referencia)
    if abs(d) < 0.10:
        return AMBAR
    return VERDE if (d > 0) == arriba_es_bueno else ROJO


# ── Lo que dibuja cada lente en JavaScript (ui/web/analitica.*) ─────────────
# Python calcula y da el texto ya formateado; el JS solo dibuja. Si la escena
# no está disponible, cada lente dibuja su versión clásica en Plotly.

_TONO = {VERDE: "pos", ROJO: "neg", AMBAR: "ambar", GRIS: "gris"}


def _en_js(lectura: dict, base: list[str], k: str) -> bool:
    """Monta la lectura de la lente (base, cifras, gráfico, qué dice). False:
    hay que dibujar la versión clásica (y su franja de base, si no salió ya)."""
    if not disponible():
        return False  # la base clásica ya se dibujó arriba
    if escena("analitica", {"modo": "lectura", "base": base, **lectura}, clave=f"{k}_js") is NO_DISPONIBLE:
        _base_texto([_markdown_a_html(p) for p in base])
        return False
    return True


def _g_barras(nombres, valores, textos, tonos, ref=None, ref_txt="", divergente=False, tope=None) -> dict:
    """Barras horizontales: `a` es el largo (0-100, o -100..100 si divergen)."""
    vals = [float(v) if pd.notna(v) else 0.0 for v in valores]
    divergente = divergente or (bool(vals) and min(vals) < 0)
    lim = tope or (max((abs(v) for v in vals), default=0) if divergente else max(max(vals, default=0), 0)) or 1.0
    filas = [{"n": str(n), "t": str(t), "a": round((v if divergente else max(v, 0)) / lim * 100, 1), "tono": tono}
             for n, v, t, tono in zip(nombres, vals, textos, tonos)]
    return {"tipo": "barras", "divergente": divergente, "filas": filas,
            "ref": ({"pos": round(float(ref) / lim * 100, 1), "t": ref_txt}
                    if ref is not None and not divergente and np.isfinite(ref) else None)}


def _kpi(clave, etiqueta, valor, detalle=None, tono="neutral") -> dict:
    return {"clave": clave, "etiqueta": str(etiqueta), "valor": str(valor), "detalle": detalle, "tono": tono}


# ── Lentes ─────────────────────────────────────────────────────────────────

def _lente_ranking(df, schema, dim, metrica, calculo, k, base):
    a, b = st.columns([3, 2])
    with a:
        top = st.slider("Cuántos mostrar en el gráfico", 5, 50, 15, key=f"{k}_top")
    with b:
        orden = st.radio("Orden", ["Mayores primero", "Menores primero"], horizontal=True, key=f"{k}_orden")
    r = ex.ranking(df, schema, dim, metrica, calculo, ascendente=(orden == "Menores primero"))
    if r is None:
        empty_state(f"No hay al menos dos valores de «{dim}» con datos para ordenar.")
        return
    t = r["tabla"].head(top).iloc[::-1]
    texto = [_fmt(v) + (f" · {p:.0f}%" if "Participación %" in t else "")
             for v, p in zip(t["Valor"], t.get("Participación %", t["Valor"]))]
    extra = f" · se muestran {len(t)} de {r['n']}" if r["n"] > len(t) else ""
    titulo = f"{metrica or 'Registros'} por {dim}"
    subtitulo = f"{r['calculo']} por grupo · verde: 10% o más sobre el promedio · rojo: 10% o más por debajo{extra}"
    leer = t.iloc[::-1]  # en pantalla, de arriba hacia abajo como se lee
    lectura = {"titulo": titulo, "subtitulo": subtitulo, "badge": f"{r['n']} grupos", "hallazgos": list(r["hallazgos"]),
               "grafico": _g_barras(leer[dim].astype(str), leer["Valor"], texto[::-1],
                                    [_TONO[_tono(v, r["promedio"])] for v in leer["Valor"]], ref=r["promedio"],
                                    ref_txt=f"promedio de los {r['n']}: {_fmt(r['promedio'])}")}
    if _en_js(lectura, base, k):
        _tabla(r["tabla"], f"ranking_{dim}", k)
        return
    fig = go.Figure(go.Bar(
        x=t["Valor"], y=t[dim].astype(str), orientation="h", text=texto, textposition="outside", cliponaxis=False,
        marker=dict(color=[_tono(v, r["promedio"]) for v in t["Valor"]]),
        hovertemplate="<b>%{y}</b><br>%{text}<extra></extra>",
    ))
    fig = _base(fig, max(320, 30 * len(t) + 110), show_xgrid=True)
    fig.update_layout(hovermode="closest", showlegend=False, bargap=.28, margin=dict(t=40, b=_MARGEN_EJE))
    if t["Valor"].min() >= 0:
        fig.update_xaxes(range=[0, float(t["Valor"].max()) * 1.25], tickformat="~s")
    fig = realzar_barras(fig, referencia=r["promedio"])
    _anotar_referencia(fig, r["promedio"], f"promedio de los {r['n']}: {_fmt(r['promedio'])}")
    chart_card(titulo, subtitulo, fig, key=f"{k}_fig", visual_type="RANKING", badge_text=f"{r['n']} grupos")
    _hallazgos(r["hallazgos"])
    _tabla(r["tabla"], f"ranking_{dim}", k)


def _selector_grano(etiqueta, grano_def, k):
    """Selector de grano que arranca en el que da al menos dos periodos."""
    return st.selectbox(etiqueta, ex.GRANOS, index=ex.GRANOS.index(grano_def or "Mes"), key=f"{k}_grano_{grano_def}")


def _serie_js(valores) -> tuple[list, list]:
    """(valores, textos) de una serie para el gráfico de líneas del JS."""
    v = [None if pd.isna(x) else float(x) for x in valores]
    return v, ["—" if x is None else _fmt(x) for x in v]


def _lente_evolucion(df, schema, dim, metrica, calculo, grano_def, k, base):
    a, b, c = st.columns([1, 2, 3])
    with a:
        grano = _selector_grano("Agrupar fechas por", grano_def, k)
    with b:
        modos = ["Valor", "Índice (inicio = 100)"]
        if ex.es_sumable(ex.resolver_calculo(df, schema, None if metrica == CONTEO else metrica, calculo)):
            modos.insert(1, "Acumulado")
        modo = st.radio("Mostrar", modos, horizontal=True, key=f"{k}_modo",
                        help="Índice: cada línea parte de 100, para comparar ritmos de grupos de tamaño muy distinto.")
    grupos = None
    if dim is not None:
        previo = ex.ranking(df, schema, dim, metrica, calculo)
        opciones = previo["tabla"][dim].astype(str).tolist() if previo else []
        with c:
            grupos = st.multiselect(f"Qué {dim} ver", opciones, default=opciones[:5],
                                    key=f"{k}_grupos_{dim}", placeholder="Los 5 más altos")
    r = ex.evolucion(df, schema, dim, metrica, calculo, grupos=grupos or None, grano=grano, modo=modo)
    if r is None:
        empty_state("Hacen falta al menos dos periodos con datos para ver una evolución.")
        return
    m = r["matriz"]
    con_promedio = (modo == "Valor" and r.get("promedio_grupo") is not None and r["total_grupo"] > len(m.columns))
    titulo = f"{metrica or 'Registros'} por {grano.lower()}" + (f" · {dim}" if dim else "")
    subtitulo = (f"{r['calculo']} de cada {grano.lower()} · {modo}"
                 + (f" · discontinua = promedio de los {r['total_grupo']}" if con_promedio else ""))
    series = []
    for i, g in enumerate(m.columns):
        v, t = _serie_js(m[g])
        series.append({"n": str(g), "color": CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)], "v": v, "t": t})
    promedio = None
    if con_promedio:
        v, t = _serie_js(r["promedio_grupo"].reindex(m.index))
        promedio = {"n": f"Promedio de los {r['total_grupo']}", "v": v, "t": t}
    lectura = {"titulo": titulo, "subtitulo": subtitulo, "badge": f"{len(m.index)} periodos",
               "hallazgos": list(r["hallazgos"]),
               "grafico": {"tipo": "lineas", "x": [ex.etiqueta_periodo(p, grano) for p in m.index], "series": series,
                           "prom": promedio, "parcial": bool(r["parcial"]), "base100": modo.startswith("Índice")}}
    tabla = m.copy()
    tabla.index = [ex.etiqueta_periodo(p, grano) for p in tabla.index]
    if _en_js(lectura, base, k):
        _tabla(tabla.reset_index().rename(columns={"index": "Periodo"}), f"evolucion_{dim or 'total'}", k)
        return
    fig = go.Figure()
    for i, g in enumerate(m.columns):
        color = CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)]
        fig.add_trace(go.Scatter(x=[ex.etiqueta_periodo(p, grano) for p in m.index], y=m[g], mode="lines+markers",
                                 name=str(g), line=dict(color=color, width=2.6), marker=dict(size=6, color=color),
                                 hovertemplate=f"<b>{html.escape(str(g))}</b> · %{{x}}: %{{y:,.0f}}<extra></extra>"))
    # Referencia del grupo completo, solo en «Valor»: acumulado o índice de un
    # promedio mezclarían dos lecturas distintas en la misma línea.
    if modo == "Valor" and r.get("promedio_grupo") is not None and r["total_grupo"] > len(m.columns):
        prom = r["promedio_grupo"]
        fig.add_trace(go.Scatter(x=[ex.etiqueta_periodo(p, grano) for p in prom.index], y=prom.values, mode="lines",
                                 name=f"Promedio de los {r['total_grupo']}",
                                 line=dict(color="#64748B", width=2.2, dash="dash"),
                                 hovertemplate=f"<b>Promedio de los {r['total_grupo']}</b> · %{{x}}: %{{y:,.0f}}<extra></extra>"))
    if r["parcial"]:
        fig.add_vrect(x0=len(m.index) - 1.5, x1=len(m.index) - 0.5, fillcolor="#94A3B8", opacity=.12, line_width=0,
                      annotation_text="incompleto", annotation_position="top left",
                      annotation_font=dict(size=10, color="#64748B"))
    if modo.startswith("Índice"):
        fig.add_hline(y=100, line_dash="dot", line_color="#94A3B8", line_width=1.2)
    fig.update_yaxes(tickformat="~s", title=None)
    fig = _base(fig, 400)
    fig.update_layout(margin=dict(b=_MARGEN_EJE))
    chart_card(titulo, subtitulo, fig, key=f"{k}_fig", visual_type="TENDENCIA", badge_text=f"{len(m.index)} periodos")
    _hallazgos(r["hallazgos"])
    _tabla(tabla.reset_index().rename(columns={"index": "Periodo"}), f"evolucion_{dim or 'total'}", k)


def _lente_periodos(df, schema, dim, metrica, calculo, grano_def, k, base):
    grano = _selector_grano("Agrupar fechas por", grano_def, k)
    periodos = ex.periodos_disponibles(df, schema, grano)
    if len(periodos) < 2:
        empty_state("Hacen falta al menos dos periodos para comparar.")
        return
    etiquetas = [ex.etiqueta_periodo(p, grano) for p in periodos]
    # Si el último periodo está a medias, se proponen los dos anteriores:
    # comparar un mes cerrado contra uno que va por la mitad siempre "cae".
    m_real = None if metrica == CONTEO else metrica
    incompleto = ex.ultimo_incompleto(df, schema, m_real, ex.resolver_calculo(df, schema, m_real, calculo), grano)
    ib = len(periodos) - 2 if incompleto and len(periodos) >= 3 else len(periodos) - 1
    a, b = st.columns(2)
    # La clave incluye la métrica y si el último está incompleto: si cambia
    # cualquiera de las dos, la sugerencia se recalcula en vez de quedarse
    # con la de antes (p. ej. un mes a medias elegido con otra métrica).
    sufijo = f"{grano}_{metrica}_{incompleto}"
    with a:
        pa = st.selectbox("Periodo A (antes)", etiquetas, index=max(ib - 1, 0), key=f"{k}_a_{sufijo}")
    with b:
        pb = st.selectbox("Periodo B (después)", etiquetas, index=ib, key=f"{k}_b_{sufijo}")
    if incompleto:
        st.caption(f"⚠️ {etiquetas[-1]} parece incompleto, por eso la comparación propuesta usa periodos cerrados.")
    if pa == pb:
        empty_state("Elige dos periodos distintos.")
        return
    r = ex.periodo_vs_periodo(df, schema, dim, metrica if metrica != CONTEO else None,
                              periodos[etiquetas.index(pa)], periodos[etiquetas.index(pb)], calculo, grano)
    if r is None:
        empty_state("No hay datos en esos periodos.")
        return
    cambio = r["total_b"] - r["total_a"]
    pct = cambio / abs(r["total_a"]) * 100 if r["total_a"] else None
    que = "Total" if r["sumable"] else "Promedio"
    titulo = f"Quién sumó y quién restó · {r['etiqueta_a']} → {r['etiqueta_b']}"
    subtitulo = (f"Diferencia de {metrica if metrica != CONTEO else 'registros'} ({r['calculo'].lower()}) por {dim} · "
                 "los 20 con más movimiento")
    tono = "neutral" if not cambio else ("positive" if cambio > 0 else "negative")
    leer = r["tabla"].head(20)
    lectura = {
        "titulo": titulo, "subtitulo": subtitulo, "badge": f"{len(r['tabla'])} grupos", "hallazgos": list(r["hallazgos"]),
        "kpis": [_kpi("antes", f"{que} {r['etiqueta_a']}", _fmt(r["total_a"])),
                 _kpi("despues", f"{que} {r['etiqueta_b']}", _fmt(r["total_b"]),
                      f"{pct:+.1f}% vs {r['etiqueta_a']}" if pct is not None else None, tono),
                 _kpi("diferencia", "Diferencia", ("+" if cambio >= 0 else "") + _fmt(cambio), None, tono)],
        "grafico": _g_barras(leer[dim].astype(str), leer["Diferencia"],
                             [("+" if v >= 0 else "") + _fmt(v) + (f" ({p:+.0f}%)" if pd.notna(p) else " (nuevo)")
                              for v, p in zip(leer["Diferencia"], leer["Variación %"])],
                             ["pos" if v >= 0 else "neg" for v in leer["Diferencia"]], divergente=True),
    }
    if _en_js(lectura, base, k):
        _tabla(r["tabla"], f"periodos_{dim}", k)
        return
    c1, c2, c3 = st.columns(3)
    c1.metric(f"{que} {r['etiqueta_a']}", _fmt(r["total_a"]))
    c2.metric(f"{que} {r['etiqueta_b']}", _fmt(r["total_b"]), delta=(f"{pct:+.1f}%" if pct is not None else None))
    c3.metric("Diferencia", ("+" if cambio >= 0 else "") + _fmt(cambio))

    t = r["tabla"].head(20).iloc[::-1]
    fig = go.Figure(go.Bar(
        x=t["Diferencia"], y=t[dim].astype(str), orientation="h",
        marker=dict(color=[VERDE if v >= 0 else ROJO for v in t["Diferencia"]]),
        text=[("+" if v >= 0 else "") + _fmt(v) + (f" ({p:+.0f}%)" if pd.notna(p) else " (nuevo)")
              for v, p in zip(t["Diferencia"], t["Variación %"])],
        textposition="outside", cliponaxis=False, hovertemplate="<b>%{y}</b><br>%{text}<extra></extra>",
    ))
    fig = _base(fig, max(320, 30 * len(t) + 110), show_xgrid=True)
    lim = float(t["Diferencia"].abs().max() or 1) * 1.35
    fig.update_xaxes(range=[-lim, lim], tickformat="~s", zeroline=True, zerolinecolor="#94A3B8")
    fig.update_layout(hovermode="closest", showlegend=False, bargap=.28, margin=dict(b=_MARGEN_EJE))
    fig = realzar_barras(fig)
    chart_card(titulo, subtitulo, fig, key=f"{k}_fig", visual_type="CAMBIO", badge_text=f"{len(r['tabla'])} grupos")
    _hallazgos(r["hallazgos"])
    _tabla(r["tabla"], f"periodos_{dim}", k)


def _lente_cruzada(df, schema, dim, metrica, calculo, dims, grano_def, k, base):
    # "Periodo" solo se ofrece si hay al menos dos periodos: con uno, la matriz
    # tendría una sola columna y no cruza nada.
    opciones = (["Periodo (fechas)"] if grano_def else []) + [d for d in dims if d != dim]
    if not opciones:
        empty_state("Hace falta una segunda columna para cruzar.")
        return
    a, b, c = st.columns([2, 1, 3])
    with a:
        columnas = st.selectbox("Columnas", opciones, key=f"{k}_cols")
    grano = grano_def or "Mes"
    if columnas == "Periodo (fechas)":
        with b:
            grano = _selector_grano("Fechas por", grano_def, k)
    with c:
        norm = st.radio("Mostrar", ex.NORMALIZACIONES, horizontal=True, key=f"{k}_norm",
                        help="% de la fila: cómo se reparte cada fila. % de la columna: qué fila pesa más en cada columna.")
    col = ex.PERIODO if columnas == "Periodo (fechas)" else columnas
    r = ex.tabla_cruzada(df, schema, dim, col, metrica if metrica != CONTEO else None, calculo, norm, grano)
    if r is None:
        empty_state("No hay suficientes combinaciones con datos para cruzar.")
        return
    v = r["valores"]
    es_pct = r["normalizar"] != "Valores"
    texto = v.map(lambda x: "" if pd.isna(x) else (f"{x:.0f}%" if es_pct else _fmt(x)))
    if r["normalizar"] != norm:
        st.caption(f"Los porcentajes solo tienen sentido sobre sumas o conteos; con {r['calculo'].lower()} se muestran valores.")
    titulo = f"{dim} × {columnas}"
    subtitulo = (f"{metrica if metrica != CONTEO else 'Registros'} · {r['calculo'].lower()} · "
                 f"{r['normalizar']} · más oscuro = más alto")
    tabla = v.round(2).reset_index().rename(columns={"_grupo": dim})
    tabla.columns = [str(c) + (" %" if es_pct and i else "") for i, c in enumerate(tabla.columns)]
    numeros = v.to_numpy(dtype=float)
    vmin, vmax = (float(np.nanmin(numeros)), float(np.nanmax(numeros))) if np.isfinite(numeros).any() else (0.0, 1.0)
    rango = (vmax - vmin) or 1.0
    lectura = {"titulo": titulo, "subtitulo": subtitulo, "badge": f"{v.shape[0]}×{v.shape[1]}",
               "hallazgos": list(r["hallazgos"]),
               "grafico": {"tipo": "calor", "cols": [str(c) for c in v.columns],
                           "filas": [{"n": str(fila), "c": [{"t": texto.iat[i, j],
                                                             "i": None if pd.isna(numeros[i, j])
                                                             else round((numeros[i, j] - vmin) / rango, 3)}
                                                            for j in range(v.shape[1])]}
                                     for i, fila in enumerate(v.index)]}}
    if _en_js(lectura, base, k):
        _tabla(tabla, f"cruzada_{dim}", k)
        return
    fig = go.Figure(go.Heatmap(
        z=v.values, x=[str(x) for x in v.columns], y=[str(x) for x in v.index], text=texto.values,
        texttemplate="%{text}", textfont=dict(size=10), colorscale=[[0, "#F1F5F9"], [0.5, "#5EC4B6"], [1, "#0F766E"]],
        hovertemplate="<b>%{y}</b> × %{x}<br>%{text}<extra></extra>", showscale=False, xgap=2, ygap=2,
    ))
    fig = _base(fig, max(320, 30 * len(v.index) + 130))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(side="top", showgrid=False)
    fig.update_layout(hovermode="closest", margin=dict(t=50, b=20))
    chart_card(titulo, subtitulo, fig, key=f"{k}_fig", visual_type="MATRIZ", badge_text=f"{v.shape[0]}×{v.shape[1]}")
    _hallazgos(r["hallazgos"])
    _tabla(tabla, f"cruzada_{dim}", k)


def _pares(df, schema, metrica):
    pares = ex.pares_meta_real(df, schema)
    if metrica and metrica != CONTEO:
        meta = columna_meta(df, schema, metrica)
        if meta and not any(p["real"] == metrica and p["meta"] == meta for p in pares):
            pares.insert(0, {"real": metrica, "meta": meta, "etiqueta": f"{metrica} vs. {meta}"})
    return pares


def _lente_cumplimiento(df, schema, dim, metrica, k, base):
    pares = _pares(df, schema, metrica)
    par = st.selectbox("Qué comparar", [p["etiqueta"] for p in pares], key=f"{k}_par",
                       help="Parejas detectadas por nombre: PPTO/Meta/Presupuesto contra EJEC/Real/Resultado de lo mismo.")
    p = next(x for x in pares if x["etiqueta"] == par)
    r = ex.cumplimiento(df, schema, dim, p["real"], p["meta"])
    if r is None:
        empty_state("La meta no tiene valores positivos con los filtros actuales.")
        return
    nombre = dim or "Grupo"
    titulo = f"Cumplimiento por {nombre}"
    subtitulo = f"{p['real']} ÷ {p['meta']} · verde ≥100% · ámbar 90–99% · rojo menos de 90%"
    leer = r["tabla"].head(40)
    total = r["total"]
    diferencia = r["total_real"] - r["total_meta"]
    tono = "neutral" if total is None else ("positive" if total >= 100 else "negative")
    lectura = {
        "titulo": titulo, "subtitulo": subtitulo, "badge": f"{len(r['tabla'])} grupos", "hallazgos": list(r["hallazgos"]),
        "kpis": [{**_kpi("meta", "Cumplimiento total", f"{total:.1f}%" if total is not None else "—", None, tono),
                  "pct": float(total) if total is not None else None},
                 _kpi("ejecutado", f"Ejecutado ({p['real']})", _fmt(r["total_real"])),
                 _kpi("objetivo", f"Meta ({p['meta']})", _fmt(r["total_meta"]),
                      ("+" if diferencia >= 0 else "") + _fmt(diferencia) + " frente a la meta",
                      "positive" if diferencia >= 0 else "negative")],
        "grafico": _g_barras(leer[nombre].astype(str), leer["Cumplimiento %"],
                             [f"{c:.0f}% · {_fmt(rv)} de {_fmt(mv)}"
                              for c, rv, mv in zip(leer["Cumplimiento %"], leer[p["real"]], leer[p["meta"]])],
                             ["pos" if c >= 100 else "ambar" if c >= 90 else "neg" for c in leer["Cumplimiento %"]],
                             ref=100, ref_txt="meta 100%",
                             tope=max(110.0, float(leer["Cumplimiento %"].max()))),
    }
    if _en_js(lectura, base, k):
        _tabla(r["tabla"], f"cumplimiento_{nombre}", k)
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Cumplimiento total", f"{r['total']:.1f}%" if r["total"] is not None else "—")
    c2.metric(f"Ejecutado ({p['real']})", _fmt(r["total_real"]))
    c3.metric(f"Meta ({p['meta']})", _fmt(r["total_meta"]),
              delta=("+" if r["total_real"] >= r["total_meta"] else "") + _fmt(r["total_real"] - r["total_meta"]))
    t = r["tabla"].head(40).iloc[::-1]
    colores = [VERDE if c >= 100 else AMBAR if c >= 90 else ROJO for c in t["Cumplimiento %"]]
    fig = go.Figure(go.Bar(
        x=t["Cumplimiento %"], y=t[nombre].astype(str), orientation="h", marker=dict(color=colores),
        text=[f"{c:.0f}% · {_fmt(rv)} de {_fmt(mv)}" for c, rv, mv in zip(t["Cumplimiento %"], t[p["real"]], t[p["meta"]])],
        textposition="outside", cliponaxis=False, hovertemplate="<b>%{y}</b><br>%{text}<extra></extra>",
    ))
    fig = _base(fig, max(300, 30 * len(t) + 110), show_xgrid=True)
    fig.update_xaxes(range=[0, max(110.0, float(t["Cumplimiento %"].max())) * 1.3], ticksuffix="%")
    fig.update_layout(hovermode="closest", showlegend=False, bargap=.28, margin=dict(t=40, b=_MARGEN_EJE))
    fig = realzar_barras(fig, referencia=100)
    _anotar_referencia(fig, 100, "meta 100%")
    chart_card(titulo, subtitulo, fig, key=f"{k}_fig", visual_type="META", badge_text=f"{len(r['tabla'])} grupos")
    _hallazgos(r["hallazgos"])
    _tabla(r["tabla"], f"cumplimiento_{nombre}", k)


_MAX_PUNTOS_JS = 2000


def _lente_relacion(df, schema, dim, metrica, calculo, metricas, k, base):
    opciones_y = [m for m in metricas if m != metrica]
    my = st.selectbox(f"Comparar «{metrica}» contra", opciones_y, key=f"{k}_y")
    r = ex.relacion(df, schema, dim, metrica, my, calculo)
    if r is None:
        empty_state("Hacen falta al menos 3 puntos con variación en las dos métricas.")
        return
    pts = r["puntos"]
    # Cuánto hay que apartarse de lo esperado para «rendir más» o «menos»: una
    # desviación de los residuos, pero nunca menos del 2% del valor típico.
    # Con una relación perfecta (r = 1) los residuos son ruido de redondeo
    # (−0,0000001) y, sin ese piso, todos los puntos salían en rojo.
    escala = max(float(pts["residuo"].std() or 0), abs(float(pts["y"].mean())) * 0.02) or 1.0
    colores = [VERDE if v > escala else ROJO if v < -escala else "#64748B" for v in pts["residuo"]]
    titulo = f"{metrica} contra {my}" + (f" · por {dim}" if dim else " · por registro")
    subtitulo = (f"r = {r['r']:.2f} · línea discontinua = lo esperado · verde rinde más de lo esperado, rojo menos · "
                 "punteadas = medianas")
    # Sin agrupar hay un punto por registro: se dibuja una muestra fija (la
    # recta y la r se calcularon con todos).
    dibujo = pts if len(pts) <= _MAX_PUNTOS_JS else pts.sample(_MAX_PUNTOS_JS, random_state=0)
    muestra = f" · se dibujan {len(dibujo):,} de {len(pts):,} puntos" if len(dibujo) < len(pts) else ""
    x0, x1 = float(pts["x"].min()), float(pts["x"].max())
    lectura = {
        "titulo": titulo, "subtitulo": subtitulo + muestra, "badge": f"{len(pts)} puntos",
        "hallazgos": list(r["hallazgos"]),
        "grafico": {"tipo": "puntos", "ex": str(metrica), "ey": str(my), "rotular": bool(dim) and len(pts) <= 25,
                    "p": [{"n": str(i) if dim else "", "x": float(f["x"]), "y": float(f["y"]),
                           "tx": _fmt(f["x"]), "ty": _fmt(f["y"]),
                           "tono": "pos" if f["residuo"] > escala else "neg" if f["residuo"] < -escala else "gris"}
                          for i, f in dibujo.iterrows()],
                    "recta": [[x0, r["pendiente"] * x0 + r["intercepto"]], [x1, r["pendiente"] * x1 + r["intercepto"]]],
                    "mx": float(r["mediana_x"]), "my": float(r["mediana_y"])},
    }
    pts_tabla = pts.assign(esperado=pts["esperado"].round(0), residuo=pts["residuo"].round(0))
    tabla = pts_tabla.rename(columns={"x": metrica, "y": my, "esperado": f"{my} esperado", "residuo": "Diferencia vs. esperado"})
    tabla = tabla.reset_index().rename(columns={"_grupo": dim or "Registro", "index": dim or "Registro"})
    tabla = tabla.sort_values("Diferencia vs. esperado", ascending=False)
    if _en_js(lectura, base, k):
        _tabla(tabla, f"relacion_{dim or 'registros'}", k)
        return
    nombres = [str(i) for i in pts.index] if dim else [""] * len(pts)
    fig = go.Figure(go.Scatter(
        x=pts["x"], y=pts["y"], mode="markers+text" if dim and len(pts) <= 25 else "markers",
        text=[n[:22] for n in nombres], textposition="top center", textfont=dict(size=9),
        marker=dict(size=10 if dim else 6, color=colores, opacity=.85, line=dict(width=1, color="#FFFFFF")),
        customdata=nombres, hovertemplate=f"<b>%{{customdata}}</b><br>{html.escape(metrica)}: %{{x:,.0f}}<br>"
                                          f"{html.escape(my)}: %{{y:,.0f}}<extra></extra>", showlegend=False,
    ))
    xs = np.linspace(float(pts["x"].min()), float(pts["x"].max()), 50)
    fig.add_trace(go.Scatter(x=xs, y=r["pendiente"] * xs + r["intercepto"], mode="lines", name="Lo esperado",
                             line=dict(color="#94A3B8", dash="dash", width=1.5), hoverinfo="skip"))
    fig.add_vline(x=r["mediana_x"], line_dash="dot", line_color="#CBD5E1", line_width=1)
    fig.add_hline(y=r["mediana_y"], line_dash="dot", line_color="#CBD5E1", line_width=1)
    fig = _base(fig, 460, show_xgrid=True)
    fig.update_xaxes(title=metrica, tickformat="~s")
    fig.update_yaxes(title=my, tickformat="~s")
    fig.update_layout(hovermode="closest", margin=dict(b=_MARGEN_EJE + 30))
    chart_card(titulo, subtitulo, fig, key=f"{k}_fig", visual_type="RELACIÓN", badge_text=f"{len(pts)} puntos")
    _hallazgos(r["hallazgos"])
    # Lo esperado sale de una recta: sus decimales no son un dato, son ruido
    # (por eso la tabla lleva «esperado» y «residuo» redondeados).
    _tabla(tabla, f"relacion_{dim or 'registros'}", k)


def _cajas_js(datos: pd.DataFrame, grupos: list) -> dict:
    """Una caja por grupo en una escala común 0-100: cuartiles, bigotes a 1,5
    veces la caja (como Plotly) y hasta 40 puntos fuera de lo habitual."""
    cajas = []
    for g in grupos:
        v = datos.loc[datos["_grupo"] == g, "_valor"].dropna().astype(float)
        if v.empty:
            continue
        q1, med, q3 = (float(x) for x in v.quantile([.25, .5, .75]))
        rango = q3 - q1
        dentro = v[(v >= q1 - 1.5 * rango) & (v <= q3 + 1.5 * rango)]
        lo, hi = float(dentro.min()), float(dentro.max())
        fuera = v[(v < lo) | (v > hi)]
        if len(fuera) > 40:
            fuera = fuera.sample(40, random_state=0)
        cajas.append({"n": str(g), "q1": q1, "med": med, "q3": q3, "lo": lo, "hi": hi,
                      "fuera": [float(x) for x in fuera], "cuenta": f"{len(v):,}",
                      "t": f"mediana {_fmt(med)} · la mitad central entre {_fmt(q1)} y {_fmt(q3)}"})
    if not cajas:
        return {"tipo": "cajas", "g": []}
    minimo = min([c["lo"] for c in cajas] + [x for c in cajas for x in c["fuera"]])
    maximo = max([c["hi"] for c in cajas] + [x for c in cajas for x in c["fuera"]])
    ancho = (maximo - minimo) or 1.0
    a_pct = lambda x: round((x - minimo) / ancho * 100, 2)  # noqa: E731
    for c in cajas:
        c.update(q1=a_pct(c["q1"]), med=a_pct(c["med"]), q3=a_pct(c["q3"]), lo=a_pct(c["lo"]), hi=a_pct(c["hi"]),
                 fuera=[a_pct(x) for x in c["fuera"]])
    return {"tipo": "cajas", "g": cajas, "min": _fmt(minimo), "max": _fmt(maximo)}


def _lente_distribucion(df, schema, dim, metrica, k, base):
    r = ex.distribucion(df, schema, dim, metrica)
    if r is None:
        empty_state("No hay valores para ver la distribución.")
        return
    titulo = f"Cómo se reparten los registros de {metrica}" + (f" · por {dim}" if dim else "")
    subtitulo = "Caja = mitad central de los registros · línea = mediana · puntos sueltos = fuera de lo habitual"
    lectura = {"titulo": titulo, "subtitulo": subtitulo, "badge": f"{len(r['datos']):,} registros",
               "hallazgos": list(r["hallazgos"]), "grafico": _cajas_js(r["datos"], list(r["grupos"]))}
    if _en_js(lectura, base, k):
        _tabla(r["tabla"], f"distribucion_{dim or 'todos'}", k)
        return
    fig = go.Figure()
    for i, g in enumerate(reversed(r["grupos"])):
        valores = r["datos"].loc[r["datos"]["_grupo"] == g, "_valor"]
        fig.add_trace(go.Box(x=valores, name=str(g)[:40], boxpoints="outliers", orientation="h",
                             marker=dict(color=CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)], size=4),
                             line=dict(width=1.5), hoverinfo="x+name"))
    fig = _base(fig, max(320, 42 * len(r["grupos"]) + 110), show_xgrid=True)
    fig.update_xaxes(tickformat="~s")
    fig.update_layout(showlegend=False, hovermode="closest", margin=dict(b=_MARGEN_EJE))
    chart_card(titulo, subtitulo, fig, key=f"{k}_fig", visual_type="DISTRIBUCIÓN", badge_text=f"{len(r['datos']):,} registros")
    _hallazgos(r["hallazgos"])
    _tabla(r["tabla"], f"distribucion_{dim or 'todos'}", k)


# ── Pantalla ───────────────────────────────────────────────────────────────

def _poner_lente(clave: str, lente: str) -> None:
    st.session_state[clave] = lente


def _elegir_lente(disponibles: list[str], k: str) -> str:
    """Las lentes como tarjetas en JavaScript (ícono, nombre y la pregunta que
    responde); el clic pulsa un botón oculto que guarda la elegida. Sin
    JavaScript, la fila de opciones de siempre."""
    clave = f"{k}_lente"
    actual = st.session_state.get(clave)
    if actual not in disponibles:
        actual = disponibles[0]
    if disponible():
        botones = {l: f"{k}_ir_{l}" for l in disponibles}
        lentes = [{"clave": l, "icono": LENTES[l][0].split(" ", 1)[0], "nombre": LENTES[l][0].split(" ", 1)[1],
                   "pregunta": LENTES[l][1], "activa": l == actual} for l in disponibles]
        if escena("analitica", {"modo": "lentes", "lentes": lentes, "botones": botones},
                  clave=f"{k}_lentes_js") is not NO_DISPONIBLE:
            botones_ocultos(botones, {l: (_poner_lente, (clave, l)) for l in disponibles})
            return actual
    if st.session_state.get(clave) not in disponibles:
        st.session_state.pop(clave, None)  # una lente que esta hoja no tiene
    lente = st.radio("Qué quieres analizar", disponibles, horizontal=True, key=clave,
                     format_func=lambda x: LENTES[x][0], label_visibility="collapsed")
    st.markdown(f'<div class="analitica-pregunta">{LENTES[lente][1]}</div>', unsafe_allow_html=True)
    return lente


def render_explorer(df, schema):
    cabecera("Explorador analítico",
             "Elige una pregunta, qué medir y cómo agrupar. Cada vista trae su gráfico, lo que dice y la tabla.",
             ceja="Analítica", icono="🔬", cifras=[(f"{len(df):,}", "registros")], clave="cab_explorador",
             respaldo_html=banner_header(
                 "Explorador analítico",
                 "Elige una pregunta, qué medir y cómo agrupar. Cada vista trae su gráfico, lo que dice y la tabla.",
                 "ciudad_red.jpg"))
    _css()
    hoja = st.session_state.get("active_sheet", "")
    k = f"an_{hoja}"

    dims = ex.dimensiones(df, schema)
    metricas = [m for m in metric_candidates(df, schema) if m in df.columns]
    fecha = ex.columna_fecha(df, schema)
    grano_def = ex.grano_sugerido(df, schema) if fecha else None

    disponibles = []
    if dims:
        disponibles.append("ranking")
    if grano_def:
        disponibles.append("evolucion")
        if dims:
            disponibles.append("periodos")
    if dims and (len(dims) >= 2 or grano_def):
        disponibles.append("cruzada")
    if metricas and _pares(df, schema, metricas[0]):
        disponibles.append("cumplimiento")
    if len(metricas) >= 2:
        disponibles.append("relacion")
    if metricas:
        disponibles.append("distribucion")
    if not disponibles:
        empty_state("Este archivo no tiene columnas para agrupar ni métricas numéricas que explorar.")
        return

    lente = _elegir_lente(disponibles, k)

    # ── Controles comunes ─────────────────────────────────────────────────
    usa_metrica = lente != "cumplimiento"
    admite_conteo = lente in {"ranking", "evolucion", "periodos", "cruzada"}
    admite_sin_agrupar = lente in {"evolucion", "cumplimiento", "relacion", "distribucion"}
    usa_calculo = lente in {"ranking", "evolucion", "periodos", "cruzada", "relacion"}

    columnas = st.columns(3)
    opciones_dim = ([SIN_AGRUPAR] if admite_sin_agrupar else []) + dims
    if not opciones_dim:
        empty_state("Esta vista necesita una columna para agrupar.")
        return
    with columnas[0]:
        dim_elegida = st.selectbox("Agrupar por", opciones_dim, key=f"{k}_dim_{lente}",
                                   index=opciones_dim.index(dims[0]) if dims else 0,
                                   help="Solo columnas de texto o categoría: agrupar por una métrica o un código no compara nada.")
    dim = None if dim_elegida == SIN_AGRUPAR else dim_elegida

    metrica = None
    if usa_metrica:
        opciones_m = metricas + ([CONTEO] if admite_conteo else [])
        if not opciones_m:
            empty_state("Esta vista necesita una métrica numérica.")
            return
        with columnas[1]:
            metrica = st.selectbox("Métrica", opciones_m, key=f"{k}_met_{schema.get('metrica_preferida')}")
    calculo = "Automático"
    if usa_calculo and metrica != CONTEO:
        with columnas[2]:
            calculo = st.selectbox("Cálculo", ex.CALCULOS, key=f"{k}_calc",
                                   help="Automático suma conteos y montos, y promedia tasas, precios y ARPU.")

    # ── Base del análisis ─────────────────────────────────────────────────
    # En texto plano con **negritas**: la pantalla en JavaScript la dibuja
    # junto al gráfico; la versión clásica la convierte a HTML aquí mismo.
    m_real = None if metrica in (None, CONTEO) else metrica
    real = ex.resolver_calculo(df, schema, m_real, "Conteo" if metrica == CONTEO else calculo)
    partes = []
    if lente != "cumplimiento":
        que = "registros contados" if metrica == CONTEO else f"**{metrica}**"
        if usa_calculo and metrica != CONTEO:
            que += f" ({real.lower()}{', elegido automáticamente' if calculo == 'Automático' else ''})"
        partes.append(que)
    partes.append(f"por **{dim}**" if dim else "sin agrupar")
    partes.append(f"{len(df):,} registros visibles")
    if fecha:
        f = pd.to_datetime(df[fecha], errors="coerce").dropna()
        if len(f):
            partes.append(f"{ex.etiqueta_periodo(f.min())} a {ex.etiqueta_periodo(f.max())} (columna «{fecha}»)")
    partes.append("con los filtros del menú lateral")
    if not disponible():
        _base_texto([_markdown_a_html(p) for p in partes])

    k2 = f"{k}_{lente}"
    if lente == "ranking":
        _lente_ranking(df, schema, dim, None if metrica == CONTEO else metrica,
                       "Conteo" if metrica == CONTEO else calculo, k2, partes)
    elif lente == "evolucion":
        _lente_evolucion(df, schema, dim, None if metrica == CONTEO else metrica,
                         "Conteo" if metrica == CONTEO else calculo, grano_def, k2, partes)
    elif lente == "periodos":
        _lente_periodos(df, schema, dim, metrica, "Conteo" if metrica == CONTEO else calculo, grano_def, k2, partes)
    elif lente == "cruzada":
        _lente_cruzada(df, schema, dim, metrica, "Conteo" if metrica == CONTEO else calculo, dims, grano_def, k2, partes)
    elif lente == "cumplimiento":
        _lente_cumplimiento(df, schema, dim, metricas[0] if metricas else None, k2, partes)
    elif lente == "relacion":
        _lente_relacion(df, schema, dim, metrica, calculo, metricas, k2, partes)
    elif lente == "distribucion":
        _lente_distribucion(df, schema, dim, metrica, k2, partes)
