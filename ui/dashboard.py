import streamlit as st
import pandas as pd
import numpy as np
import re
from ui.labels import clean_display_text
from visualization.charts import (
    trend, grouped_trend, multi_trend, ranking, donut, histogram, scatter, correlation, geo, geo_summary_map, comparison, period_compare_bar,
    metric_candidates, dimension_candidates, _label, adaptive_chart_specs, wide_month_chart, _base, CATEGORY_PALETTE, chart_muted_color
)
from core.geo_engine import geographic_summary
from core.chart_explainer import explain_chart
from core.performance import choose_dimension
from core.numeric import numeric_series
from core.dates import format_month_year
from core.universal_analysis import dynamic_kpis, drilldown_options, drilldown_table, person_stats, smart_chart_questions
import plotly.graph_objects as go
import plotly.express as px
from ui.person_profile import render_person_profile
from ui.components.cards import kpi_card, insight_card, executive_headline as _shared_executive_headline, executive_signals as _shared_executive_signals
from ui.components.charts import chart_card as _shared_chart_card
from ui.components.section import banner_header
from ui.layouts.columns import kpi_grid as _kpi_grid_layout, two_column
from ui.layouts.tabs import named_tabs


def _card(label, value, delta=None, tone="neutral", icon=""):
    return kpi_card(label, value, delta=delta, tone=tone, icon=icon or None)


def _kpi_grid(kpis, growth=None, per_row=4):
    """Cuadrícula de tarjetas KPI, 4 por fila (con salto de línea automático),
    como en un panel tipo Power BI: sin iconos, solo etiqueta/valor/variación."""
    def render(entry):
        global_i, k = entry
        delta = None; tone = "neutral"
        if global_i == 1 and growth is not None:
            delta = f"{'▲' if growth >= 0 else '▼'} {abs(growth):.1f}% vs. periodo anterior"
            tone = "positive" if growth >= 0 else "negative"
        return _card(k["label"], k["value"], delta, tone)
    _kpi_grid_layout(list(enumerate(kpis)), render, per_row=per_row)


def _display_kpi_value(k):
    value=k.get("value")
    if k.get("kind")=="leader":
        # "Líder · Asesor" debe leerse completo de un vistazo: el nombre Y
        # cuánto vendió/logró, no solo el nombre suelto.
        raw=k.get("raw")
        if isinstance(raw,(int,float,np.integer,np.floating)) and not isinstance(raw,bool):
            return f"{value} · {_fmt(raw)}"
        return str(value)
    if isinstance(value,(int,float,np.integer,np.floating)) and not isinstance(value,bool):
        if k.get("kind")=="growth": return f"{value:+.1f}%"
        return _fmt(value)
    return str(value)


def _kpi_style(k, schema=None):
    """(etiqueta, tono, ícono) para una tarjeta KPI. Antes "Líder · Ciudad"
    con valor "Bogotá · 61.7M" no decía de qué eran esos 61.7M — ingresos,
    unidades, lo que fuera — y se veía exactamente igual (mismo borde rojo,
    mismo texto) que cualquier total o promedio, aunque es un tipo de dato
    distinto (quién encabeza, no cuánto suma todo). Con el schema a mano se
    agrega el nombre de la métrica a la etiqueta, y se le da un color/ícono
    propios (morado + 🏆) para que se reconozca de un vistazo."""
    label = k.get("label", "Indicador")
    if k.get("kind") == "leader":
        if schema is not None and k.get("metric"):
            label = f"{label} · {_label(schema, k['metric'])}"
        return label, "leader", "🏆"
    if k.get("kind") == "growth":
        tone = "positive" if (k.get("value") or 0) >= 0 else "negative"
        return label, tone, None
    return label, "neutral", None


def _universal_kpi_grid(df, schema, dashboard):
    kpis=dynamic_kpis(df,schema,dashboard)
    if not kpis: return
    cols=st.columns(min(4,len(kpis)))
    for i,k in enumerate(kpis[:4]):
        with cols[i]:
            delta=None
            label,tone,icon=_kpi_style(k,schema)
            if k.get("kind")=="growth":
                delta="Mejora reciente" if k["value"]>=0 else "Caída reciente"
            st.markdown(_card(label,_display_kpi_value(k),delta,tone,icon),unsafe_allow_html=True)
    if len(kpis)>4:
        cols=st.columns(min(4,len(kpis)-4))
        for i,k in enumerate(kpis[4:8]):
            with cols[i]:
                label,tone,icon=_kpi_style(k,schema)
                st.markdown(_card(label,_display_kpi_value(k),None,tone,icon),unsafe_allow_html=True)


def _drilldown_panel(df,schema,metric,dimension):
    dims=drilldown_options(df,schema)
    if not metric or len(dims)<1: return
    st.markdown('<div class="section-intro compact"><div><span class="eyebrow">PROFUNDIZAR</span><h2>Del total al detalle</h2></div><span class="data-badge">Explora el resultado paso a paso</span></div>',unsafe_allow_html=True)
    c1,c2=st.columns([1,2])
    with c1:
        drill_dim=st.selectbox("Bajar a",dims,index=dims.index(dimension) if dimension in dims else 0,format_func=lambda c:_label(schema,c),key="drilldown_dimension_v51")
    table=drilldown_table(df,schema,metric,drill_dim,12)
    if table.empty:
        st.info("No hay suficiente información para profundizar en esta dimensión.")
        return
    with c2:
        selected=st.selectbox("Selecciona un elemento",table[drill_dim].astype(str).tolist(),key="drilldown_value_v51")
    row=table[table[drill_dim].astype(str)==str(selected)]
    value=float(row.iloc[0]["Valor"]) if not row.empty else 0
    share=float(row.iloc[0]["Participación"]) if not row.empty else 0
    a,b,c=st.columns(3)
    a.metric("Resultado",_fmt(value)); b.metric("Participación",f"{share:.1f}%"); c.metric("Posición",f"#{int(table.index[table[drill_dim].astype(str)==str(selected)][0])+1}" if not row.empty else "—")
    st.dataframe(table.rename(columns={drill_dim:_label(schema,drill_dim)}),use_container_width=True,hide_index=True)


def _chart_card(title, subtitle, fig, empty="No hay datos suficientes para este análisis.", insight=None, explain=None, key=None):
    _shared_chart_card(title, subtitle, fig, empty=empty, insight=insight, explain=explain, key=key)


def _fmt(v):
    if pd.isna(v): return "—"
    v = float(v)
    if abs(v) >= 1e9: return f"{v/1e9:.1f}B"
    if abs(v) >= 1e6: return f"{v/1e6:.1f}M"
    if abs(v) >= 1e3: return f"{v/1e3:.1f}K"
    return f"{v:,.0f}"


def _fmt_number(v):
    return _fmt(v)


def _chart_insight(df, schema, metric, dimension=None):
    if metric not in df.columns: return None
    s = pd.to_numeric(df[metric], errors="coerce").dropna()
    if s.empty: return None
    base = f"{_label(schema, metric)} acumula {_fmt(s.sum())} en los datos visibles."
    if dimension and dimension in df.columns:
        x = df[[dimension, metric]].copy(); x[metric] = pd.to_numeric(x[metric], errors="coerce"); x = x.dropna()
        if not x.empty:
            x = x.groupby(dimension)[metric].sum().sort_values(ascending=False)
            if len(x) >= 2 and x.iloc[0] != 0:
                share = x.iloc[0] / x.sum() * 100
                base += f" {_clean_text(x.index[0])} lidera con {share:.1f}% del total."
    return base


def _concept_for(schema, col):
    for item in schema.get("semantic", {}).get("columns", []):
        if item.get("column") == col:
            return item.get("semantic_type", "")
    return ""


def _clean_text(v):
    return "Sin categoría" if pd.isna(v) or str(v).strip() == "" else str(v)


def _available_chart_types(df, schema, metric, dimension, has_date):
    """Only expose chart types that answer a distinct question for the data."""
    options=[]
    if has_date and metric:
        options += [("Línea", "line"), ("Barras", "bar"), ("Área", "area")]
    if metric and dimension:
        options += [("Barras por categoría", "ranking"), ("Barras: anterior vs actual", "period_compare"), ("Dona", "donut")]
    if metric and not has_date and not dimension:
        options += [("Histograma", "histogram")]
    metrics=metric_candidates(df,schema)
    if len(metrics)>=2:
        options.append(("Dispersión", "scatter"))
    # Preserve order and remove duplicates.
    seen=set(); out=[]
    for label,kind in options:
        if kind not in seen:
            seen.add(kind); out.append((label,kind))
    return out


def _render_selected_chart(df, schema, controls, chart_kind):
    m,d=controls["metric"],controls["dimension"]
    if chart_kind=="line":
        return trend(df,schema,m,controls["grain"],controls["agg"],controls["comparison"])
    if chart_kind=="bar":
        # A temporal bar chart answers period-to-period comparison, unlike the line.
        return ranking(df,schema,m,"__period_analisis_dummy__",controls["top_n"],controls["agg"]) if False else _temporal_bar(df,schema,m,controls["grain"],controls["agg"])
    if chart_kind=="area":
        return _temporal_area(df,schema,m,controls["grain"],controls["agg"])
    if chart_kind=="ranking":
        return ranking(df,schema,m,d,controls["top_n"],controls["agg"])
    if chart_kind=="period_compare":
        return period_compare_bar(df,schema,m,d,controls["grain"],controls["agg"],controls["top_n"])
    if chart_kind=="donut":
        return donut(df,schema,m,d,controls["top_n"])
    if chart_kind=="histogram":
        return histogram(df,schema,m)
    if chart_kind=="scatter":
        mm=metric_candidates(df,schema)
        return scatter(df,schema,mm[0],mm[1]) if len(mm)>=2 else None
    return None


def _temporal_bar(df,schema,metric,grain,agg):
    dates=[d for d in schema.get("dates",[]) if d in df.columns]
    if not dates or metric not in df.columns: return None
    d=dates[0]; x=df[[d,metric]].copy(); x[d]=pd.to_datetime(x[d],errors="coerce"); x[metric]=pd.to_numeric(x[metric],errors="coerce"); x=x.dropna()
    if x.empty: return None
    p=x[[d]].copy();
    if grain=="Día": p["_period"]=p[d].dt.floor("D")
    elif grain=="Semana": p["_period"]=p[d].dt.to_period("W").dt.start_time
    elif grain=="Trimestre": p["_period"]=p[d].dt.to_period("Q").dt.start_time
    elif grain=="Año": p["_period"]=p[d].dt.to_period("Y").dt.start_time
    else: p["_period"]=p[d].dt.to_period("M").dt.start_time
    x["_period"]=p["_period"]
    g=x.groupby("_period")[metric]
    y={"Promedio":g.mean(),"Máximo":g.max(),"Mínimo":g.min()}.get(agg,g.sum()).sort_index()
    import plotly.graph_objects as go
    fig=go.Figure(go.Bar(x=y.index,y=y.values,name=_label(schema,metric),marker_line_width=0,hovertemplate="<b>%{x|%b %Y}</b><br>"+_label(schema,metric)+": <b>%{y:,.0f}</b><extra></extra>"))
    return __import__('visualization.charts',fromlist=['_base'])._base(fig,360,show_xgrid=False)


def _temporal_area(df,schema,metric,grain,agg):
    dates=[d for d in schema.get("dates",[]) if d in df.columns]
    if not dates or metric not in df.columns: return None
    # Reuse the clean temporal aggregation from trend, then change the visual encoding.
    fig=trend(df,schema,metric,grain,agg,False)
    if fig is None: return None
    for tr in fig.data:
        tr.update(fill="tozeroy",fillcolor="rgba(47,128,237,0.18)",mode="lines")
    return fig


def _individual_trend(df, schema, metric, dimension, selected_groups, grain="Mes", agg="Suma", chart_type="Automático"):
    """Comparación individual robusta.

    Regla visual:
    - 2+ periodos por cada seleccionado -> líneas comparables.
    - Datos escasos -> barras comparativas (nunca puntos sueltos que parezcan
      una tendencia).
    - Si existe historia suficiente, se añade una referencia general discreta.
    """
    dates = [d for d in schema.get("dates", []) if d in df.columns]
    if metric not in df.columns or dimension not in df.columns or not selected_groups:
        return None, ""

    d = dates[0] if dates else None
    cols = [metric, dimension] + ([d] if d else [])
    x = df[cols].copy()
    x[metric] = numeric_series(x[metric])
    x[dimension] = x[dimension].fillna("Sin dato").astype(str).str.strip()
    selected = [str(v).strip() for v in selected_groups]
    x = x[x[dimension].isin(selected)].dropna(subset=[metric])
    if x.empty:
        return None, ""

    sem = next((z.get("semantic_type") for z in schema.get("semantic", {}).get("columns", []) if z.get("column") == metric), "")
    reducer = "sum" if agg == "Suma" else "mean" if agg == "Promedio" else "max" if agg == "Máximo" else "min"

    # Sin fecha: siempre una comparación directa clara.
    if not d:
        g = x.groupby(dimension)[metric].agg(reducer).reindex(selected).dropna().reset_index()
        g["Resultado"] = g[metric]
        fig = px.bar(
            g.sort_values("Resultado"), x="Resultado", y=dimension, orientation="h",
            text_auto=".3s", labels={"Resultado": _label(schema, metric), dimension: _label(schema, dimension)},
        )
        fig.update_traces(marker_color="#E4002B", marker_line_width=0)
        fig.update_layout(height=max(360, 54 * len(g) + 110), showlegend=False,
                          margin=dict(l=10, r=30, t=25, b=25))
        return _base(fig, max(360, 54 * len(g) + 110), show_xgrid=False), \
            f"Comparación directa de {_label(schema, metric).lower()}"

    x[d] = pd.to_datetime(x[d], errors="coerce")
    x = x.dropna(subset=[d])
    if x.empty:
        return None, ""

    if grain == "Día":
        x["_period"] = x[d].dt.floor("D")
    elif grain == "Semana":
        x["_period"] = x[d].dt.to_period("W").dt.start_time
    elif grain == "Trimestre":
        x["_period"] = x[d].dt.to_period("Q").dt.start_time
    elif grain == "Año":
        x["_period"] = x[d].dt.to_period("Y").dt.start_time
    else:
        x["_period"] = x[d].dt.to_period("M").dt.start_time

    grouped = (x.groupby(["_period", dimension], as_index=False)[metric]
                 .agg(reducer).sort_values("_period"))
    counts = grouped.groupby(dimension)["_period"].nunique().reindex(selected).fillna(0)
    periods = grouped["_period"].nunique()

    # Una línea solo existe cuando hay al menos dos periodos reales por serie.
    # La elección explícita de "Líneas" nunca se cambia silenciosamente por barras.
    chart_type = chart_type or "Automático"
    enough_for_lines = len(selected) >= 1 and bool((counts >= 2).all()) and periods >= 2
    if not enough_for_lines and chart_type in {None, "", "Automático"}:
        chart_type = "Barras agrupadas"

    # Historia suficiente: el usuario puede cambiar el tipo de comparación.
    # Todos los visuales parten de la MISMA serie agregada para no cambiar la
    # métrica al cambiar de visual.
    if chart_type == "Automático":
        chart_type = "Líneas"

    if chart_type == "Líneas":
        fig = go.Figure()
        for i, name in enumerate(selected):
            z = grouped[grouped[dimension].eq(name)].sort_values("_period")
            if z.empty:
                continue
            color = CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)]
            fig.add_trace(go.Scatter(
                x=z["_period"], y=z[metric], mode="lines+markers", name=name,
                line=dict(color=color, width=3.2, shape="linear"),
                marker=dict(size=8, color=color, line=dict(width=1.5, color="#FFFFFF")),
                connectgaps=False,
                hovertemplate=(f"<b>%{{x|%b %Y}}</b><br><b>{name}</b><br>"
                               f"{_label(schema, metric)}: <b>%{{y:,.0f}}</b><extra></extra>"),
            ))
        overall = grouped.groupby("_period")[metric].agg(reducer).sort_index()
        if len(overall) >= 3:
            fig.add_trace(go.Scatter(
                x=overall.index, y=overall.values, mode="lines", name="Referencia general",
                line=dict(color="#64748B", width=2, dash="dash"), opacity=.65,
                hovertemplate="<b>%{x|%b %Y}</b><br>Referencia general: <b>%{y:,.0f}</b><extra></extra>",
            ))
        subtitle = (
            f"Evolución de {_label(schema, metric).lower()} · una línea por persona"
            if enough_for_lines
            else "Líneas · solo se muestran los periodos reales disponibles; no se inventan tendencias"
        )
        height = 440

    elif chart_type in {"Barras agrupadas", "Barras apiladas"}:
        fig = go.Figure()
        for i, name in enumerate(selected):
            z = grouped[grouped[dimension].eq(name)].sort_values("_period")
            if z.empty:
                continue
            color = CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)]
            fig.add_trace(go.Bar(
                x=z["_period"], y=z[metric], name=name, marker_color=color,
                hovertemplate=(f"<b>%{{x|%b %Y}}</b><br><b>{name}</b><br>"
                               f"{_label(schema, metric)}: <b>%{{y:,.0f}}</b><extra></extra>"),
            ))
        fig.update_layout(barmode="group" if chart_type == "Barras agrupadas" else "stack")
        subtitle = ("Comparación por periodo · barras lado a lado" if chart_type == "Barras agrupadas"
                    else "Participación de cada persona dentro del total de cada periodo")
        height = 430

    elif chart_type == "Área":
        fig = go.Figure()
        for i, name in enumerate(selected):
            z = grouped[grouped[dimension].eq(name)].sort_values("_period")
            if z.empty:
                continue
            color = CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)]
            fig.add_trace(go.Scatter(
                x=z["_period"], y=z[metric], mode="lines", name=name,
                line=dict(color=color, width=2.6),
                fill="tozeroy",
                hovertemplate=f"<b>%{{x|%b %Y}}</b><br><b>{name}</b><br>{_label(schema, metric)}: <b>%{{y:,.0f}}</b><extra></extra>",
            ))
        subtitle = "Área comparativa · volumen y evolución de cada seleccionado"
        height = 430

    elif chart_type == "Barras 100%":
        pivot = grouped.pivot(index="_period", columns=dimension, values=metric).reindex(columns=selected).fillna(0)
        denom = pivot.sum(axis=1).replace(0, np.nan)
        pct = pivot.div(denom, axis=0).fillna(0) * 100
        fig = go.Figure()
        for i, name in enumerate(selected):
            fig.add_trace(go.Bar(
                x=pct.index, y=pct[name], name=name,
                marker_color=CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)],
                hovertemplate=f"<b>%{{x|%b %Y}}</b><br><b>{name}</b><br>Participación: <b>%{{y:.1f}}%</b><extra></extra>",
            ))
        fig.update_layout(barmode="stack")
        subtitle = "Participación relativa · qué porcentaje del total aporta cada seleccionado"
        height = 430

    elif chart_type == "Radar":
        pivot = grouped.pivot(index="_period", columns=dimension, values=metric).reindex(columns=selected).fillna(0)
        categories = [str(p)[:10] for p in pivot.index]
        fig = go.Figure()
        maxv = float(pivot.to_numpy().max()) if pivot.size else 0
        if maxv > 0 and categories:
            theta = categories + [categories[0]]
            for i, name in enumerate(selected):
                vals = (pivot[name] / maxv * 100).tolist()
                r = vals + [vals[0]]
                fig.add_trace(go.Scatterpolar(
                    r=r, theta=theta, fill="toself", name=name,
                    line=dict(color=CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)], width=2)
                ))
        fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0,100], ticksuffix="%")))
        subtitle = "Perfil relativo por periodo · escala normalizada al mejor valor observado"
        height = 460

    elif chart_type == "Variación %":
        rows = []
        for i, name in enumerate(selected):
            z = grouped[grouped[dimension].eq(name)].sort_values("_period").copy()
            if len(z) < 2:
                continue
            z["Variación"] = z[metric].pct_change().replace([np.inf, -np.inf], np.nan) * 100
            z = z.dropna(subset=["Variación"])
            if not z.empty:
                rows.append(z[["_period", dimension, "Variación"]])
        if not rows:
            return None, ""
        changes = pd.concat(rows, ignore_index=True)
        fig = go.Figure()
        for i, name in enumerate(selected):
            z = changes[changes[dimension].eq(name)]
            if z.empty:
                continue
            color = CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)]
            fig.add_trace(go.Bar(
                x=z["_period"], y=z["Variación"], name=name, marker_color=color,
                hovertemplate=f"<b>%{{x|%b %Y}}</b><br><b>{name}</b><br>Variación: <b>%{{y:+.1f}}%</b><extra></extra>",
            ))
        fig.add_hline(y=0, line_width=1, line_color="#AAB7C7")
        fig.update_layout(barmode="group")
        subtitle = "Cambio porcentual de un periodo al siguiente · mejoró o empeoró"
        height = 430

    elif chart_type == "Heatmap":
        pivot = grouped.pivot(index="_period", columns=dimension, values=metric).reindex(columns=selected)
        fig = go.Figure(go.Heatmap(
            z=pivot.values, x=pivot.columns.tolist(), y=pivot.index,
            colorscale=[[0, "#fbe4e7"], [0.5, "#e4002b"], [1, "#4b0712"]],
            colorbar=dict(title=_label(schema, metric)),
            hovertemplate="<b>%{y|%b %Y}</b><br>%{x}<br>" + _label(schema, metric) + ": <b>%{z:,.0f}</b><extra></extra>",
        ))
        subtitle = "Mapa de intensidad · permite detectar rápidamente quién domina cada periodo"
        height = max(390, 34 * len(pivot) + 120)

    else:
        return _individual_trend(df, schema, metric, dimension, selected_groups, grain, agg, "Líneas")

    fig.update_xaxes(tickformat="%Y" if grain == "Año" else "%b %Y", showgrid=False)
    fig.update_yaxes(tickformat="~s", title=_label(schema, metric), showgrid=True,
                     gridcolor="rgba(96,112,132,.16)")
    fig.update_layout(height=height, margin=dict(l=10, r=18, t=30, b=30), hovermode="x unified")
    if chart_type == "Heatmap":
        fig.update_yaxes(title="Periodo")
        fig.update_xaxes(title="Seleccionado", showgrid=False)
    if chart_type == "Variación %":
        fig.update_yaxes(title="Variación (%)", ticksuffix="%", tickformat="+.0f")
    return _base(fig, height, show_xgrid=False), \
        subtitle


def _person_profile(df, schema, person_col, person_name, metric, date_col=None):
    """Ficha analítica de una persona: resultado, evolución y qué lo explica."""
    if not person_col or person_col not in df.columns or not person_name:
        return
    rows = df[df[person_col].astype(str).str.strip().eq(str(person_name).strip())].copy()
    if rows.empty:
        st.info("No hay registros visibles para esta persona con los filtros actuales.")
        return

    semcols = schema.get("semantic", {}).get("columns", [])
    sem_metric = next((x.get("semantic_type", "") for x in semcols if x.get("column") == metric), "")
    additive = sem_metric in {"revenue", "profit", "cost", "quantity", "discount", "tax"}

    vals = numeric_series(rows[metric]).dropna() if metric and metric in rows.columns else pd.Series(dtype=float)
    total_or_avg = float(vals.sum()) if additive else float(vals.mean()) if len(vals) else None

    # --- Scorecard ---
    st.markdown(f"### 👤 {person_name}")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Registros", f"{len(rows):,}")
    c2.metric(_label(schema, metric) if metric else "Resultado", _fmt_number(total_or_avg) if total_or_avg is not None else "—")

    dates = pd.Series(dtype="datetime64[ns]")
    if date_col and date_col in rows.columns:
        dates = pd.to_datetime(rows[date_col], errors="coerce").dropna()
    c3.metric("Periodo inicial", format_month_year(dates.min()) if len(dates) else "—")
    c4.metric("Periodo final", format_month_year(dates.max()) if len(dates) else "—")

    # --- Build temporal series once; every visual uses the same aggregation ---
    y = None
    if metric and metric in rows.columns and date_col and date_col in rows.columns:
        tmp = rows[[date_col, metric]].copy()
        tmp[date_col] = pd.to_datetime(tmp[date_col], errors="coerce")
        tmp[metric] = numeric_series(tmp[metric])
        tmp = tmp.dropna().sort_values(date_col)
        if not tmp.empty:
            tmp["_period"] = tmp[date_col].dt.to_period("M").dt.start_time
            y = (tmp.groupby("_period", as_index=False)[metric].sum() if additive
                 else tmp.groupby("_period", as_index=False)[metric].mean()).sort_values("_period")

    # --- Main performance visual ---
    if y is not None and not y.empty:
        if len(y) >= 2:
            a,b = st.columns([1.7,1])
            with a:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=y["_period"], y=y[metric], mode="lines+markers", name=person_name,
                    line=dict(width=3.4, color="#E4002B", shape="spline"),
                    marker=dict(size=8, color="#E4002B", line=dict(width=2, color="#F5F7FB")),
                    fill="tozeroy", fillcolor="rgba(77,163,255,.08)",
                    hovertemplate="<b>%{x|%b %Y}</b><br>Resultado: <b>%{y:,.0f}</b><extra></extra>",
                ))
                # Point-level period change makes the graph answer "mejor o peor".
                pct = y[metric].pct_change().replace([np.inf,-np.inf],np.nan)*100
                for i in range(1,len(y)):
                    if pd.notna(pct.iloc[i]):
                        fig.add_annotation(x=y.iloc[i]["_period"], y=y.iloc[i][metric], text=f"{pct.iloc[i]:+.1f}%",
                                           showarrow=False, yshift=16,
                                           font=dict(size=10,color=chart_muted_color()))
                fig.update_xaxes(tickformat="%b %Y", showgrid=False)
                fig.update_yaxes(tickformat="~s", title=_label(schema, metric), showgrid=True, gridcolor="rgba(96,112,132,.16)")
                fig = _base(fig, 380, show_xgrid=False)
                _chart_card("Evolución del seleccionado", f"Resultado de {person_name} por mes", fig, key="individual_profile_trend_v47")
            with b:
                latest=float(y.iloc[-1][metric]); previous=float(y.iloc[-2][metric])
                delta=latest-previous
                pct=(delta/abs(previous)*100) if previous else None
                st.markdown("#### Lectura rápida")
                st.metric("Último periodo", _fmt_number(latest), f"{pct:+.1f}%" if pct is not None else "—")
                best=y.loc[y[metric].idxmax()]; worst=y.loc[y[metric].idxmin()]
                st.metric("Mejor periodo", format_month_year(best["_period"]), _fmt_number(best[metric]))
                st.metric("Peor periodo", format_month_year(worst["_period"]), _fmt_number(worst[metric]))
                allvals=numeric_series(df[metric]).dropna() if metric in df.columns else pd.Series(dtype=float)
                benchmark=float(allvals.mean()) if len(allvals) else None
                if benchmark is not None and total_or_avg is not None:
                    diff=total_or_avg-benchmark
                    st.metric("Vs. promedio visible", _fmt_number(diff), f"{diff/abs(benchmark)*100:+.1f}%" if benchmark else "—")
        else:
            fig=px.bar(y,x="_period",y=metric,text_auto=".3s")
            fig.update_traces(marker_color="#E4002B",marker_line_width=0)
            fig = _base(fig, 320, show_xgrid=False)
            _chart_card("Resultado disponible", f"Solo existe un periodo visible para {person_name}", fig, key="individual_profile_single_period_v47")

    # --- Diagnóstico ejecutivo del seleccionado ---
    stats = person_stats(df, schema, person_col, person_name, metric)
    if stats:
        c1,c2,c3,c4=st.columns(4)
        recent=stats.get("recent_pct")
        c1.metric("Cambio reciente", f"{recent:+.1f}%" if recent is not None else "—")
        vs=stats.get("vs_average_pct")
        c2.metric("Vs. promedio visible", f"{vs:+.1f}%" if vs is not None else "—")
        c3.metric("Mediana", _fmt(stats.get("median")) if stats.get("median") is not None else "—")
        c4.metric("Máximo", _fmt(stats.get("max")) if stats.get("max") is not None else "—")
        if recent is not None:
            tone="positive" if recent>=0 else "negative"
            reading="mejoró" if recent>=0 else "empeoró"
            st.markdown(f'<div class="decision-strip {tone}"><b>Lectura:</b> {person_name} {reading} {abs(recent):.1f}% frente al periodo anterior. La comparación contra el promedio visible es {vs:+.1f}%.</div>',unsafe_allow_html=True)
        if stats.get("series") is not None and not stats["series"].empty:
            best=stats.get("best_period"); worst=stats.get("worst_period")
            if best is not None and worst is not None:
                st.caption(f"Mejor periodo: {format_month_year(best)} · Peor periodo: {format_month_year(worst)}")

    # --- What explains the result: product/category/channel ---
    candidates=[]
    priority={"product":0,"category":1,"channel":2,"segment":3,"brand":4,"region":5,"city":6}
    for item in semcols:
        c,t=item.get("column"),item.get("semantic_type")
        if c in rows.columns and c!=person_col and t in priority:
            n=rows[c].dropna().astype(str).str.strip().replace("",pd.NA).dropna().nunique()
            if 1<n<=25: candidates.append((priority[t],c))
    candidates=[c for _,c in sorted(candidates)]
    if not candidates:
        for c in schema.get("categorical",[]):
            if c in rows.columns and c!=person_col and not str(c).startswith("__"):
                n=rows[c].dropna().astype(str).str.strip().replace("",pd.NA).dropna().nunique()
                if 1<n<=25: candidates.append(c)

    if candidates:
        mix_col=candidates[0]
        z=rows[[mix_col]+([metric] if metric and metric in rows.columns else [])].copy()
        z[mix_col]=z[mix_col].fillna("Sin dato").astype(str).str.strip().replace("","Sin dato")
        if metric and metric in z.columns:
            z[metric]=numeric_series(z[metric]); z=z.dropna(subset=[metric])
            agg=z.groupby(mix_col)[metric].sum() if additive else z.groupby(mix_col)[metric].mean()
            mix=agg.sort_values(ascending=False).head(8).reset_index(); value_col=metric
        else:
            mix=z[mix_col].value_counts().head(8).rename("Registros").reset_index(); mix.columns=[mix_col,"Registros"]; value_col="Registros"
        if not mix.empty:
            leader_name=str(mix.iloc[0][mix_col])
            leader_value=float(mix.iloc[0][value_col]) if pd.notna(mix.iloc[0][value_col]) else 0
            if _concept_for(schema,mix_col) == "product":
                st.markdown(f'<div class="decision-strip positive"><b>Producto más vendido:</b> {leader_name} · {_fmt(leader_value)} en {_label(schema,metric).lower() if metric else "resultado"}.</div>',unsafe_allow_html=True)
            fig=px.bar(mix.sort_values(value_col),x=value_col,y=mix_col,orientation="h",text_auto=".3s",
                       labels={mix_col:_label(schema,mix_col),value_col:_label(schema,value_col) if value_col in rows.columns else "Registros"})
            fig.update_traces(marker_color="#22C7B4",marker_line_width=0)
            fig.update_xaxes(showgrid=True,gridcolor="rgba(96,112,132,.16)"); fig.update_yaxes(showgrid=False,automargin=True)
            fig = _base(fig, max(330, 34*len(mix)+90), show_xgrid=True)
            _chart_card(f"Qué mueve el resultado · {_label(schema,mix_col)}", f"Principales elementos asociados a {person_name}", fig, key="individual_profile_mix_v47")

    # --- Data coverage / categorical footprint ---
    footprint=[]
    for c in candidates[:5]:
        n=rows[c].dropna().astype(str).str.strip().replace("",pd.NA).dropna().nunique()
        footprint.append({"Variable":_label(schema,c),"Valores distintos":int(n)})
    if footprint:
        st.markdown("#### Alcance del seleccionado")
        st.dataframe(pd.DataFrame(footprint),use_container_width=True,hide_index=True)


def _visual_controls(df, schema, key_prefix="main"):
    metrics = metric_candidates(df, schema)
    dims = dimension_candidates(df, schema)
    dates = schema.get("dates", [])
    with st.expander("🎛️ Segmentadores y controles", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        # Si se cambió de hoja o de archivo, una métrica/dimensión elegida en
        # una sesión anterior puede haber quedado guardada aunque ya no
        # exista en este dataframe nuevo. Sin este chequeo, el selector la
        # sigue mostrando como seleccionada y los gráficos truenan con un
        # KeyError al intentar usar una columna que ya no está.
        if metrics and st.session_state.get(f"{key_prefix}_metric") not in metrics:
            st.session_state.pop(f"{key_prefix}_metric", None)
        if dims and st.session_state.get(f"{key_prefix}_dimension") not in dims:
            st.session_state.pop(f"{key_prefix}_dimension", None)
        if metrics and st.session_state.get("focus_metric") in metrics and f"{key_prefix}_metric" not in st.session_state:
            st.session_state[f"{key_prefix}_metric"] = st.session_state.get("focus_metric")
        if dims and st.session_state.get("focus_dimension") in dims and f"{key_prefix}_dimension" not in st.session_state:
            st.session_state[f"{key_prefix}_dimension"] = st.session_state.get("focus_dimension")
        metric = c1.selectbox("Métrica", metrics, format_func=lambda x: _label(schema, x), key=f"{key_prefix}_metric") if metrics else None
        dimension = c2.selectbox("Dimensión", dims, format_func=lambda x: _label(schema, x), key=f"{key_prefix}_dimension") if dims else None
        grain = c3.selectbox("Periodo", ["Día", "Semana", "Mes", "Trimestre", "Año"], index=2, key=f"{key_prefix}_grain")
        semantic_type = next((x.get("semantic_type") for x in schema.get("semantic", {}).get("columns", []) if x.get("column") == metric), "") if metric else ""
        default_agg = 1 if semantic_type in {"price", "rating", "age", "percentage"} else 0
        agg = c4.selectbox("Cálculo", ["Suma", "Promedio", "Máximo", "Mínimo"], index=default_agg, key=f"{key_prefix}_agg")
        c5, c6, c7 = st.columns(3)
        top_n = c5.slider("Elementos a mostrar", 5, 20, 10, key=f"{key_prefix}_top")
        show_comparison = c6.checkbox("Mostrar variación", value=True, key=f"{key_prefix}_compare")
        normalize = c7.checkbox("Ver % del total", value=False, key=f"{key_prefix}_percent")
    return {"metric": metric, "dimension": dimension, "grain": grain, "agg": agg, "top_n": top_n, "comparison": show_comparison, "percent": normalize, "has_date": bool(dates)}


def _executive_headline(dashboard):
    """Solo el veredicto principal: siempre visible, sin detalle adicional."""
    _shared_executive_headline(dashboard)


def _executive_signals(dashboard):
    """Detalle de señales positivas y puntos a vigilar: pensado para vivir dentro de un expander."""
    _shared_executive_signals(dashboard)


def _alerts_panel(df, dashboard):
    alerts=dashboard.get("alerts",[])
    st.markdown('<div class="section-intro compact"><div><span class="eyebrow">CONTROL</span><h2>Alertas inteligentes</h2></div></div>',unsafe_allow_html=True)
    if not alerts:
        st.success("No hay alertas prioritarias con los datos visibles.")
        return
    for i,a in enumerate(alerts[:4]):
        cls="warning" if a.get("severity")=="Alta" else "positive"
        c1,c2=st.columns([4.2,1])
        with c1:
            implication=a.get("implication") or ""
            extra=f'<small><b>Qué significa:</b> {implication}</small>' if implication else ""
            st.markdown(f'<div class="alert-row compact {cls}"><div class="alert-severity">{clean_display_text(a.get("severity"))}</div><div><b>{clean_display_text(a.get("title"))}</b><div>{clean_display_text(a.get("text"))}</div>{extra}<small><b>Qué hacer:</b> {clean_display_text(a.get("action"))}</small></div></div>',unsafe_allow_html=True)
        with c2:
            target=a.get("target") or {}
            if target and st.button("Ver análisis",key=f"alert_focus_{i}",use_container_width=True):
                st.session_state["focus_dimension"]=target.get("dimension")
                st.session_state["focus_metric"]=target.get("metric") or dashboard.get("primary_metric")
                st.session_state["focus_view"]=target.get("view","análisis")
                if target.get("filter_column") in df.columns and target.get("filter_value") is not None:
                    st.session_state["filters"][target["filter_column"]]={"op":"in","value":[target["filter_value"]]}
                st.rerun()


def _why_changed(df, dashboard):
    change=dashboard.get("change_analysis")
    if not change:
        return
    st.markdown('<div class="section-intro compact"><div><span class="eyebrow">EXPLICACIÓN</span><h2>¿Por qué cambió?</h2></div></div>',unsafe_allow_html=True)
    pct=change.get("pct")
    if pct is None or pd.isna(pct) or not pd.api.types.is_number(pct):
        title = f'{change.get("metric_label")} cambió entre los periodos comparados'
    else:
        direction="subió" if pct>=0 else "bajó"
        title = f'{change.get("metric_label")} {direction} <strong>{abs(pct):.1f}%</strong>'
    st.markdown(f'<div class="why-card"><div class="why-title">{title}</div><div class="why-subtitle">{change.get("period_before")} → {change.get("period_after")}</div></div>',unsafe_allow_html=True)
    factors=change.get("factors",[])
    if factors:
        cols=st.columns(min(3,len(factors)))
        for i,f in enumerate(factors[:3]):
            tone="positive" if f["delta"]>=0 else "negative"
            with cols[i]:
                st.markdown(f'<div class="factor-card {tone}"><b>{f["label"]}</b><span>{"↑" if f["delta"]>=0 else "↓"} {_fmt(abs(f["delta"]))}</span><small>{_label(dashboard["schema"],f["dimension"])}</small></div>',unsafe_allow_html=True)
    st.caption("La explicación identifica los segmentos con mayor cambio absoluto; no implica causalidad por sí sola.")



def _profile_panel(df, dashboard):
    schema=dashboard.get("schema", {})
    metrics=metric_candidates(df,schema); dims=dimension_candidates(df,schema); dates=schema.get("dates",[])
    st.markdown('<div class="section-intro compact"><div><span class="eyebrow">PERFIL DEL ARCHIVO</span><h2>Qué entendió el sistema</h2></div></div>',unsafe_allow_html=True)
    c=st.columns(5)
    for col,label,val in zip(c,["Registros","Columnas","Métricas","Dimensiones","Fechas"],[len(df),len(df.columns),len(metrics),len(dims),len(dates)]): col.metric(label,f"{val:,}")


def _recommendations_panel(df, dashboard):
    recs=[]; ex=dashboard.get("executive",{}); change=dashboard.get("change_analysis"); alerts=dashboard.get("alerts",[])
    if ex.get("status")=="negative": recs.append("Revisar primero los segmentos que más contribuyen a la caída antes de tomar decisiones generales.")
    elif ex.get("status")=="positive": recs.append("Identificar qué segmentos impulsan la mejora y comprobar si el comportamiento se repite en los últimos periodos.")
    if change and change.get("factors"):
        top=change["factors"][0]; direction="cae" if top["delta"]<0 else "crece"
        recs.append(f"Investigar {top['label']}: es el segmento con mayor cambio absoluto y actualmente {direction} el indicador analizado.")
    if alerts: recs.append("Priorizar las alertas de mayor impacto y abrir el análisis correspondiente desde 'Ver análisis'.")
    if not recs: recs.append("No hay suficiente evidencia para una recomendación específica; conviene explorar los rankings y distribuciones disponibles.")
    st.markdown('<div class="section-intro compact"><div><span class="eyebrow">DECISIONES</span><h2>Qué conviene revisar</h2></div></div>',unsafe_allow_html=True)
    for i,r in enumerate(recs[:4],1): st.markdown(f'<div class="decision-strip"><b>{i}.</b> {r}</div>',unsafe_allow_html=True)


def _trend_signal(dashboard):
    growth=dashboard.get("growth")
    if growth is None: return
    tone="positive" if growth>2 else "negative" if growth<-2 else "neutral"
    label="Tendencia favorable" if tone=="positive" else "Tendencia a la baja" if tone=="negative" else "Tendencia estable"
    st.markdown(f'<div class="decision-strip {tone}"><b>{label}</b> · Variación del último periodo frente al anterior: {growth:+.1f}%.</div>',unsafe_allow_html=True)


def _performance_panel(df, dashboard):
    """Muestra automáticamente dónde está el mejor y peor desempeño.
    La dimensión se elige semánticamente (región/ciudad/producto/etc.) y el
    usuario puede cambiarla si el archivo ofrece varias opciones útiles.
    """
    from core.performance import analyze as analyze_performance
    schema=dashboard["schema"]
    metric=dashboard.get("primary_metric")
    sem={x.get("column"):x.get("semantic_type") for x in schema.get("semantic",{}).get("columns",[])}
    dims=schema.get("semantic",{}).get("dimensions") or schema.get("categorical",[])
    valid=[]
    geo_types={"region","country","city","zone","department","state"}
    business_types={"product","category","brand","customer","employee","segment"}
    for c in dims:
        if c not in df.columns or c in schema.get("dates",[]) or c in schema.get("ids",[]): continue
        n=df[c].dropna().astype(str).nunique()
        if 2<=n<=40:
            stype=sem.get(c,"")
            priority=0 if stype in geo_types else 1 if stype in business_types else 2
            valid.append((priority,c))
    if not valid:
        return
    valid.sort(key=lambda x:(x[0], str(x[1]).lower()))
    performance_cfg = dashboard.get("performance") or {}
    default_dim=performance_cfg.get("dimension") or valid[0][1]
    options=[c for _,c in valid]
    if default_dim not in options: default_dim=options[0]
    title_type="Zona" if sem.get(default_dim) in geo_types else "Desempeño por categoría"
    st.markdown('<div class="section-intro compact"><div><span class="eyebrow">DESEMPEÑO</span><h2>Dónde está el mejor y peor resultado</h2></div><span class="data-badge">Calculado con los datos actuales</span></div>',unsafe_allow_html=True)
    c1,c2=st.columns([1,3])
    with c1:
        dim=st.selectbox("Analizar por",options,index=options.index(default_dim),format_func=lambda c:_label(schema,c),key="performance_dimension")
    result=analyze_performance(df,schema,metric,dim,top_n=5)
    if not result:
        st.info("No hay suficientes datos para comparar grupos.")
        return
    with c2:
        agg_label="Total" if result["aggregation"]=="sum" else "Promedio"
        st.caption(f"{_label(schema,result['metric'])} por {_label(schema,dim).lower()} · {agg_label}")
    top=result["top"]; bottom=result["bottom"]
    # Para no duplicar grupos cuando hay pocos, construimos una sola lista
    # ordenada y destacamos extremos en el mismo gráfico.
    names=[]; vals=[]; tones=[]
    seen=set()
    for name,val in list(bottom)+list(reversed(top)):
        if name in seen: continue
        seen.add(name); names.append(name); vals.append(val)
        tones.append("top" if any(name==n for n,_ in top) else "bottom")
    fig=go.Figure()
    fig.add_trace(go.Bar(x=vals,y=names,orientation="h",marker_color=["#189A63" if t=="top" else "#E05252" for t in tones],text=[_fmt(v) for v in vals],textposition="outside",cliponaxis=False,hovertemplate="<b>%{y}</b><br>Valor: <b>%{x:,.0f}</b><extra></extra>"))
    fig.update_layout(showlegend=False,margin=dict(l=10,r=70,t=10,b=10),height=max(300,38*len(names)+80))
    fig.update_xaxes(title=None,tickformat="~s")
    fig.update_yaxes(title=None,categoryorder="array",categoryarray=names)
    fig=__import__('visualization.charts',fromlist=['_base'])._base(fig,max(300,38*len(names)+80),show_xgrid=True)
    a,b=two_column(1.65,1)
    with a:
        _chart_card("Mejor vs. menor desempeño",f"{_label(schema,dim)} · azul = mayor resultado · rojo = menor resultado",fig,"No hay datos suficientes.",key="performance_extremes_chart")
    with b:
        best=top[0] if top else ("—",0); worst=bottom[0] if bottom else ("—",0)
        st.markdown(f'<div class="insight-card positive"><div class="insight-body"><div class="insight-title">Más productivo</div><div class="insight-text"><b>{best[0]}</b><br>{_fmt(best[1])}</div></div></div>',unsafe_allow_html=True)
        st.markdown(f'<div class="insight-card warning"><div class="insight-body"><div class="insight-title">Menos productivo</div><div class="insight-text"><b>{worst[0]}</b><br>{_fmt(worst[1])}</div></div></div>',unsafe_allow_html=True)

def _insights_panel(insights):
    """Lectura analítica compacta: evidencia, impacto y acción en pocas líneas."""
    if not insights:
        return
    cols = st.columns(2)
    for i, item in enumerate(insights[:4]):
        cls = item.get("kind", "info")
        icon = "▲" if cls == "positive" else "!" if cls == "warning" else "i"
        title = clean_display_text(item.get("title", "Hallazgo"))
        finding = clean_display_text(item.get("finding", ""))
        action = clean_display_text(item.get("action", ""))
        html = insight_card(finding, title=title, kind=cls, icon=icon, action=action, compact=True)
        cols[i % 2].markdown(html, unsafe_allow_html=True)


def _primary_analysis_section(df, schema, controls, m, d, available_dates):
    """Gráfico principal (según el tipo elegido) + comparación individual +
    comparación temporal de los últimos periodos. Antes vivía inline dentro
    de render_dashboard; se extrajo tal cual (mismo código, mismas claves de
    widget) para que la pestaña "Visión general" del área de análisis sea
    autocontenida. Devuelve el tipo de gráfico elegido (o None) para que
    Diagnóstico no repita el mismo tipo de visual."""
    selected_kind = None
    if m:
        chart_options=_available_chart_types(df,schema,m,d,available_dates)
        labels=[x[0] for x in chart_options]
        kinds=[x[1] for x in chart_options]
        if chart_options:
            default_kind="line" if available_dates and "line" in kinds else kinds[0]
            default_idx=kinds.index(default_kind)
            selected_label=st.selectbox("Tipo de gráfico",labels,index=default_idx,key="primary_chart_type")
            selected_kind=kinds[labels.index(selected_label)]
            fig=_render_selected_chart(df,schema,controls,selected_kind)
            subtitle={
                "line":f"Evolución de {_label(schema,m).lower()} por {controls['grain'].lower()}",
                "bar":f"Comparación de {_label(schema,m).lower()} por periodo",
                "area":f"Volumen de {_label(schema,m).lower()} a través del tiempo",
                "ranking":f"Comparación por {_label(schema,d).lower() if d else 'categoría'}",
                "period_compare":f"Dos periodos en una misma barra · {_label(schema,m)}",
                "donut":f"Participación por {_label(schema,d).lower() if d else 'categoría'}",
                "histogram":f"Distribución de {_label(schema,m).lower()}",
                "scatter":"Relación entre dos indicadores",
            }.get(selected_kind,"Lectura visual de los datos")
            _chart_card("Visualización principal",subtitle,fig,"No hay datos suficientes para este gráfico.",_chart_insight(df,schema,m,d),key=f"primary_visual_{selected_kind}")

            # ── Comparación individual ─────────────────────────────────────
            # La comparación individual NO depende de que exista una dimensión
            # secundaria ni de que el usuario tenga que escoger Nombre/Apellido 1/
            # Apellido 2 por separado. Si el Excel representa personas, se usa
            # automáticamente el campo Nombre completo construido por el perfil.
            full_name_info = schema.get("full_name", {}) if isinstance(schema.get("full_name", {}), dict) else {}
            full_name_col = full_name_info.get("column") if full_name_info else None

            # Respaldo para hojas heterogéneas: reconstruir el nombre completo si
            # el perfil no lo conservó por alguna razón.
            if not full_name_col or full_name_col not in df.columns:
                norm_cols = {re.sub(r"[^a-z0-9]+", "", str(c).casefold()): c for c in df.columns}
                first = next((norm_cols[k] for k in ("nombre", "nombres", "name", "firstname", "first") if k in norm_cols), None)
                a1 = next((norm_cols[k] for k in ("apellido1", "primerapellido", "surname", "lastname", "lastname1") if k in norm_cols), None)
                a2 = next((norm_cols[k] for k in ("apellido2", "segundoapellido", "middlesurname") if k in norm_cols), None)
                parts = [c for c in (first, a1, a2) if c]
                if first and len(parts) >= 2:
                    full_name_col = "__nombre_completo_comparacion__"
                    temp = df[parts].fillna("").astype(str).apply(
                        lambda r: " ".join(v.strip() for v in r if v.strip()), axis=1
                    )
                    df[full_name_col] = temp
                    full_name_info = {"column": full_name_col, "parts": parts}

            candidate_dims = [
                c for c in dimension_candidates(df, schema)
                if c in df.columns
                and not str(c).startswith("__nombre_completo")
                and c not in set(full_name_info.get("parts", []))
            ]
            compare_options = []
            if full_name_col and full_name_col in df.columns:
                compare_options.append(full_name_col)
            for c in candidate_dims:
                n_unique = df[c].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()
                if 2 <= n_unique <= 500 and c not in compare_options:
                    compare_options.append(c)
            compare_dim = compare_options[0] if compare_options else None

            if compare_options:
                st.markdown("#### Comparación individual")
                st.caption("Primero selecciona qué quieres comparar; después elige los elementos. El gráfico general permanece arriba.")
                button_key = "show_individual_comparison_button_v47"
                compare_state_key = "show_individual_comparison_v47"
                if compare_state_key not in st.session_state:
                    st.session_state[compare_state_key] = False

                def _toggle_individual_comparison():
                    st.session_state[compare_state_key] = not st.session_state.get(compare_state_key, False)

                st.button(
                    "🔎 Comparar personas" if not st.session_state[compare_state_key]
                    else "✕ Ocultar comparación",
                    key=button_key,
                    on_click=_toggle_individual_comparison,
                )

                if st.session_state.get(compare_state_key, False):
                    # Mismo resguardo que en _visual_controls: si se cambió de
                    # hoja/archivo, la dimensión de comparación guardada de
                    # antes puede ya no existir en este dataframe.
                    if st.session_state.get("individual_compare_dimension_v47") not in compare_options:
                        st.session_state.pop("individual_compare_dimension_v47", None)
                    compare_dim = st.selectbox(
                        "Comparar por", compare_options,
                        format_func=lambda c: "Nombre completo" if c == full_name_col else _label(schema, c),
                        key="individual_compare_dimension_v47",
                    )
                    values = sorted(
                        df[compare_dim].dropna().astype(str).str.strip()
                        .replace("", pd.NA).dropna().unique().tolist(),
                        key=str.casefold,
                    )
                    compare_label = "Nombres completos a comparar" if compare_dim == full_name_col else f"Elementos a comparar · {str(compare_dim)}"
                    selected = st.multiselect(
                        compare_label, values, max_selections=6,
                        key="individual_compare_values_v47",
                        placeholder="Escribe para buscar y selecciona…",
                        help="Selecciona nombres reales del Excel. Se comparan todos sus registros visibles automáticamente.",
                    )

                    if selected:
                        if available_dates:
                            chart_choice = st.selectbox(
                                "Tipo de gráfico para la comparación",
                                ["Automático", "Líneas", "Área", "Barras agrupadas", "Barras apiladas", "Barras 100%", "Variación %", "Heatmap", "Radar"],
                                index=0,
                                key="individual_compare_chart_type_v47",
                                help="Todos los tipos usan la misma métrica y los mismos filtros; solo cambia la forma de visualizar la comparación."
                            )
                            selected_fig, compare_subtitle = _individual_trend(
                                df, schema, m, compare_dim, selected, controls["grain"], controls["agg"], chart_choice
                            )
                            if not compare_subtitle:
                                compare_subtitle = f"Comparación de {_label(schema, m)}"
                        else:
                            chart_choice = st.selectbox(
                                "Tipo de gráfico para la comparación",
                                ["Barras", "Barras agrupadas"],
                                key="individual_compare_chart_type_nodate_v47",
                            )
                            selected_df = df[df[compare_dim].astype(str).str.strip().isin(set(selected))].copy()
                            selected_df[m] = numeric_series(selected_df[m])
                            selected_df = selected_df.dropna(subset=[m])
                            agg_values = selected_df.groupby(compare_dim, as_index=False)[m].sum().sort_values(m, ascending=False)
                            if chart_choice == "Barras agrupadas":
                                selected_fig = px.bar(
                                    agg_values, x=compare_dim, y=m, color=compare_dim, text_auto=".3s",
                                    labels={compare_dim: _label(schema, compare_dim), m: _label(schema, m)},
                                )
                                selected_fig.update_layout(showlegend=False)
                            else:
                                selected_fig = px.bar(
                                    agg_values, x=compare_dim, y=m, text_auto=".3s",
                                    labels={compare_dim: _label(schema, compare_dim), m: _label(schema, m)},
                                )
                                selected_fig.update_layout(showlegend=False)
                            selected_fig.update_layout(height=390, margin=dict(l=20, r=20, t=20, b=20))
                            compare_subtitle = f"Comparación directa de {_label(schema, m)}"

                        if selected_fig is not None:
                            compare_title = "Personas seleccionadas" if compare_dim == full_name_col else str(compare_dim)
                            _chart_card(
                                f"Comparación: {compare_title}", compare_subtitle, selected_fig,
                                "No hay datos suficientes para las selecciones realizadas.",
                                key="individual_comparison_chart_v47",
                            )
                            if compare_dim == full_name_col and len(selected) == 1:
                                date_col = next((c for c in schema.get("dates",[]) if c in df.columns), None)
                                _person_profile(df, schema, compare_dim, selected[0], m, date_col)
                        else:
                            st.warning("No hay suficientes periodos para dibujar una línea. Se muestra una comparación directa para que el análisis no quede vacío.")
                            fallback=df[df[compare_dim].astype(str).str.strip().isin(set(selected))].copy()
                            fallback[m]=numeric_series(fallback[m])
                            fallback=fallback.dropna(subset=[m])
                            if not fallback.empty:
                                sem=next((x.get("semantic_type") for x in schema.get("semantic",{}).get("columns",[]) if x.get("column")==m),"")
                                agg=fallback.groupby(compare_dim)[m].mean() if sem not in {"revenue","profit","cost","quantity","discount","tax"} else fallback.groupby(compare_dim)[m].sum()
                                fig_fb=px.bar(agg.reset_index(),x=compare_dim,y=m,text_auto=".3s")
                                fig_fb.update_traces(marker_color="#E4002B",marker_line_width=0)
                                _chart_card("Comparación directa",f"{_label(schema,m)} por elemento seleccionado",fig_fb,"No hay datos.",key="individual_comparison_fallback_v47")
    else:
        st.info("Este archivo no contiene una variable cuantitativa suficiente para generar gráficos de desempeño.")

    # Solo una visualización principal por elección del usuario: evitamos repetir
    # automáticamente la misma información en línea, barras, dona, etc.
    if available_dates and m:
        _chart_card("Comparación temporal", "Últimos periodos disponibles · detecta subidas y caídas entre periodos", comparison(df,schema,m,controls["grain"] if controls["grain"] in {"Mes","Trimestre","Año"} else "Mes"), "No hay suficientes periodos comparables.", explain=explain_chart(df,schema,"comparison",m,d,controls["grain"]), key="explain_comparison_main")

    return selected_kind


def _diagnostic_and_smart_charts_section(df, schema, controls, m, d, available_dates, selected_kind):
    """Ranking de contribución / anterior vs. actual, y los "gráficos
    inteligentes" que la estructura del Excel permite responder. Evita
    repetir el mismo tipo de gráfico que ya se eligió en Visión general
    (antes se detectaba con `"selected_kind" in locals()`; ahora
    `selected_kind` es un parámetro explícito con el mismo efecto)."""
    st.markdown('<div class="section-intro compact"><div><span class="eyebrow">EXPLORACIÓN</span><h2>Más respuestas, menos interpretación manual</h2></div></div>', unsafe_allow_html=True)
    # Visuales complementarios: solo aparecen cuando aportan una pregunta distinta.
    # No se repite automáticamente la misma métrica en tres gráficos equivalentes.
    if m and d:
        # Complementos distintos al visual principal: no repetir el mismo tipo de
        # pregunta si el usuario ya lo seleccionó arriba.
        selected_primary = selected_kind if m else None
        diagnostic_specs = []
        if selected_primary != "ranking":
            diagnostic_specs.append((
                "Ranking de contribución",
                f"Quién aporta más a {_label(schema,m).lower()}",
                ranking(df, schema, m, d, controls["top_n"], controls["agg"]),
                "No hay categorías suficientes.",
                "diagnostic_ranking",
            ))
        if available_dates and selected_primary != "period_compare":
            diagnostic_specs.append((
                "Anterior vs. actual",
                f"Qué grupos mejoraron o empeoraron en {_label(schema,m).lower()}",
                period_compare_bar(df, schema, m, d, controls["grain"], controls["agg"], controls["top_n"]),
                "Se necesitan dos periodos comparables.",
                "diagnostic_period_compare",
            ))
        if diagnostic_specs:
            st.markdown('<div class="section-intro compact"><div><span class="eyebrow">DIAGNÓSTICO</span><h2>Qué está moviendo el resultado</h2></div></div>', unsafe_allow_html=True)
            cols = st.columns(min(2, len(diagnostic_specs)))
            for idx, (title, subtitle, fig, empty, key) in enumerate(diagnostic_specs[:2]):
                with cols[idx]:
                    _chart_card(title, subtitle, fig, empty, key=key)

    # Gráficos inteligentes: cada visual responde una pregunta distinta y solo
    # aparece si el Excel tiene la estructura necesaria.
    if m:
        smart_specs=smart_chart_questions(df,schema,m,d)
        used_smart={selected_kind} if selected_kind else set()
        used_smart.update({"ranking","period_compare"} if d else set())
        smart_specs=[spec for spec in smart_specs if spec[2] not in used_smart]
        rendered=[]
        for title,q,kind in smart_specs:
            if kind=="trend": fig=trend(df,schema,m,controls["grain"],controls["agg"],controls["comparison"])
            elif kind=="period_compare" and d: fig=period_compare_bar(df,schema,m,d,controls["grain"],controls["agg"],controls["top_n"])
            elif kind=="ranking" and d: fig=ranking(df,schema,m,d,controls["top_n"],controls["agg"])
            elif kind=="donut" and d: fig=donut(df,schema,m,d,controls["top_n"])
            elif kind=="histogram": fig=histogram(df,schema,m)
            elif kind=="scatter":
                mm=metric_candidates(df,schema); fig=scatter(df,schema,mm[0],mm[1]) if len(mm)>=2 else None
            else: fig=None
            if fig is not None: rendered.append((title,q,fig,kind))
        if rendered:
            st.markdown('<div class="section-intro compact"><div><span class="eyebrow">GRÁFICOS INTELIGENTES</span><h2>Las preguntas que este Excel sí puede responder</h2></div></div>',unsafe_allow_html=True)
            cols=st.columns(2)
            for i,(title,q,fig,kind) in enumerate(rendered[:4]):
                with cols[i%2]: _chart_card(title,q,fig,key=f"smart_chart_{kind}_{i}")


def _geo_section(df, schema, m):
    """Mapa e indicadores geográficos, cuando el Excel tiene ciudad, región,
    país o coordenadas utilizables."""
    st.markdown('<div class="section-intro compact"><div><span class="eyebrow">INTELIGENCIA GEOGRÁFICA</span><h2>Dónde se concentra el resultado</h2></div></div>', unsafe_allow_html=True)
    geo_summary = geographic_summary(df, schema, m)
    geo_meta = geo_summary.get("meta", {})
    geo_kpis = geo_summary.get("kpis", {})
    if geo_meta.get("mode") in {"coordinates", "city_geocoding", "region_geocoding", "country_geocoding"} and geo_summary.get("table") is not None and not geo_summary.get("table").empty:
        g1, g2, g3, g4 = st.columns(4)
        g1.metric(f"{geo_meta.get('level','Ubicaciones')} ubicados", f"{geo_kpis.get('cities', 0):,}")
        g2.metric("Ciudad líder", geo_kpis.get("leader", "—"))
        g3.metric("Valor líder", _fmt(geo_kpis.get("leader_value", 0)))
        g4.metric("Participación líder", f"{geo_kpis.get('leader_share', 0):.1f}%")
        if geo_meta.get("mode") in {"city_geocoding", "region_geocoding", "country_geocoding"}:
            unresolved = geo_meta.get("unresolved_places", 0) + geo_meta.get("ambiguous_places", 0)
            if unresolved:
                st.warning(f"{unresolved} ubicación(es) no pudieron confirmarse con suficiente confianza. No se colocaron en el mapa para evitar errores geográficos.")
        a, b = two_column(1.65, 1)
        with a:
            _chart_card("Mapa geográfico", f"El tamaño del punto representa el valor de la métrica seleccionada. Nivel: {geo_meta.get('level','Ubicación')}.", geo_summary_map(geo_summary), "No se pudieron construir ubicaciones suficientes.", insight=(f"{geo_kpis.get('leader','La ciudad líder')} concentra {geo_kpis.get('leader_share',0):.1f}% del valor analizado." if geo_kpis.get('leader') else None), explain=explain_chart(df, schema, "geo", m, geo_summary.get("meta",{}).get("dimension")), key="explain_geo_main")
        with b:
            table = geo_summary.get("table").copy()
            table["Participación"] = table["share_pct"].map(lambda x: f"{x:.1f}%")
            table["Valor"] = table["_geo_metric"].map(_fmt)
            table = table[["_geo_label", "Valor", "Participación"]].head(10)
            table.columns = [geo_meta.get("level","Ubicación"), "Valor", "Participación"]
            _chart_card("Ranking geográfico", "Las ubicaciones con mayor contribución a la métrica seleccionada.", None)
            st.dataframe(table, use_container_width=True, hide_index=True)
    else:
        reason = geo_meta.get("reason", "No se detectó una ciudad, región o coordenadas utilizables.")
        st.info(f"No hay un análisis geográfico disponible todavía. {reason}")


def _relationships_and_detail_section(df, schema, m, d):
    """Relación entre métricas (dispersión + correlación) y la tabla de
    detalle por dimensión, cuando hay suficientes métricas/dimensión."""
    metrics = metric_candidates(df, schema)
    if len(metrics) >= 2:
        a, b = st.columns(2)
        with a:
            x = st.selectbox("Eje X", metrics, index=0, format_func=lambda c: _label(schema,c), key="scatter_x")
            y_index = 1 if len(metrics) > 1 else 0
            y = st.selectbox("Eje Y", metrics, index=y_index, format_func=lambda c: _label(schema,c), key="scatter_y")
            _chart_card("Relación entre métricas", f"{_label(schema,x)} vs {_label(schema,y)} · la línea muestra la tendencia general", scatter(df, schema, x, y), "Se necesitan al menos dos métricas numéricas.", explain=f"La gráfica compara {_label(schema,x)} con {_label(schema,y)}. Una nube más alineada con la tendencia indica mayor asociación; no implica causalidad.", key="explain_scatter")
        with b:
            _chart_card("Mapa de relaciones", "1 = relación muy fuerte · 0 = poca relación · -1 = relación inversa", correlation(df, schema, metrics[:8]), "Se necesitan al menos tres métricas.", explain=explain_chart(df, schema, "correlation"), key="explain_correlation")

    if d and m:
        table = df.groupby(d, dropna=False)[m].agg(["sum", "mean", "count"]).sort_values("sum", ascending=False).head(15).reset_index()
        table.columns = [_label(schema, d), "Total", "Promedio", "Registros"]
        st.markdown('<div class="section-intro compact"><div><span class="eyebrow">DETALLE</span><h2>Tabla para tomar decisiones</h2></div></div>', unsafe_allow_html=True)
        st.dataframe(table, use_container_width=True, hide_index=True)


def render_dashboard(df, dashboard):
    schema = dashboard["schema"]
    ex = dashboard.get("executive", {})

    # ── Vista general: lo primero que se ve, sin necesidad de desplegar nada ──
    st.markdown(banner_header("Qué está pasando", "Descripción completa · todo recalculado con los filtros actuales.", "ciudad_red.jpg"), unsafe_allow_html=True)
    st.caption(dashboard["summary"])

    # Perfil individual integrado: se abre dentro del mismo dashboard.
    # Esto evita depender de /pages y mantiene el flujo en una sola pantalla.
    full_name = schema.get("full_name", {}) if isinstance(schema.get("full_name"), dict) else {}
    if full_name.get("column") in df.columns:
        cta1, cta2 = st.columns([1.35, 4])
        with cta1:
            if st.button("👤 Analizar perfil individual", type="primary", use_container_width=True, key="open_person_profile_v53"):
                st.session_state["show_profile_inline"] = True
        with cta2:
            st.caption("Abre el análisis completo de una persona sin salir del dashboard.")

        if st.session_state.get("show_profile_inline", False):
            st.markdown('<div class="decision-panel"><div class="decision-panel-title">Perfil individual</div><div class="decision-panel-subtitle">Todo el análisis disponible para la persona seleccionada, respetando los filtros actuales.</div></div>', unsafe_allow_html=True)
            if st.button("✕ Cerrar perfil", key="close_person_profile_v53"):
                st.session_state["show_profile_inline"] = False
                st.rerun()
            render_person_profile(df, schema, dashboard)

    _universal_kpi_grid(df, schema, dashboard)

    if dashboard.get("growth") is not None:
        g = dashboard["growth"]; cls = "positive" if g >= 0 else "negative"; text = "crecimiento" if g >= 0 else "caída"
        st.markdown(f'<div class="decision-strip {cls}"><span class="decision-dot"></span><b>Lectura rápida:</b> {text} reciente de <strong>{abs(g):.1f}%</strong> frente al periodo anterior.</div>', unsafe_allow_html=True)

    _executive_headline(dashboard)

    # ── Detalle progresivo: nada se elimina, solo se reorganiza en dos
    # columnas temáticas para que no sea una fila larga de acordeones y se
    # aproveche mejor el ancho disponible.
    st.markdown(
        '<div class="section-intro compact"><div><span class="eyebrow">DETALLE</span>'
        '<h2>Profundiza cuando lo necesites</h2></div>'
        '<span class="data-badge">Organizado por tema</span></div>',
        unsafe_allow_html=True,
    )

    # Se agrupan por tema en pestañas en vez de apilar 8 expanders uno tras
    # otro: mismo contenido, mismas funciones, solo más fácil de recorrer.
    alerts = dashboard.get("alerts", [])
    insights = dashboard.get("insights", [])[:4]
    detail_tabs = named_tabs(["📌 Diagnóstico", "🏆 Desempeño", "🗂️ Contexto y acción"])

    with detail_tabs["📌 Diagnóstico"]:
        if ex.get("positive") or ex.get("watch"):
            st.markdown("#### 📌 Señales positivas y puntos a vigilar")
            _executive_signals(dashboard)
            st.divider()
        if alerts:
            st.markdown(f"#### 🔔 Alertas inteligentes · {len(alerts[:4])} hallazgos prioritarios")
            _alerts_panel(df, dashboard)
            st.divider()
        if dashboard.get("change_analysis"):
            st.markdown("#### 🔍 ¿Por qué cambió?")
            _why_changed(df, dashboard)
            st.divider()
        if insights:
            st.markdown(f"#### 🧭 Hallazgos y líneas de acción ({len(insights)})")
            _insights_panel(insights)
        if not (ex.get("positive") or ex.get("watch") or alerts or dashboard.get("change_analysis") or insights):
            st.info("No hay señales, alertas ni hallazgos suficientes con los datos visibles.")

    with detail_tabs["🏆 Desempeño"]:
        st.markdown("#### 🏆 Dónde está el mejor y peor resultado")
        _performance_panel(df, dashboard)
        st.divider()
        st.markdown("#### 🔎 Profundizar en el resultado")
        _drilldown_panel(df, schema, dashboard.get("primary_metric"), dashboard.get("performance",{}).get("dimension"))

    with detail_tabs["🗂️ Contexto y acción"]:
        st.markdown("#### 🗂️ Perfil del archivo y cómo se interpretó")
        _profile_panel(df, dashboard)
        semantic = schema.get("semantic", {})
        interpretations = semantic.get("columns", [])
        if interpretations:
            st.markdown("Cómo interpretó el sistema cada columna")
            rows = []
            for item in interpretations:
                concept = item.get("semantic_type", "unknown")
                from ui.labels import pretty_technical
                rows.append({"Columna original": item["column"], "Interpretación": pretty_technical(concept), "Confianza": f'{item["confidence"]*100:.0f}%', "Revisar": "⚠ Sí" if item.get("ambiguous") else "✓ No"})
            st.dataframe(rows, use_container_width=True, hide_index=True)
        st.divider()
        st.markdown("#### ✅ Qué conviene revisar")
        _recommendations_panel(df, dashboard)

    # Estructura especial: Enero...Diciembre como columnas.
    # Se conserva la navegación original y se añade una lectura automática.
    wide = wide_month_chart(df, schema)
    if wide is not None and not schema.get("dates"):
        wide_fig, wide_subtitle = wide
        _chart_card(
            "Evolución mensual detectada",
            wide_subtitle,
            wide_fig,
            "Se detectaron columnas mensuales, pero no hay valores suficientes.",
            "El sistema identificó los meses en las columnas y los convirtió automáticamente en una lectura temporal.",
            key="wide_months_main",
        )

    controls = _visual_controls(df, schema)
    m, d = controls["metric"], controls["dimension"]
    # Última capa de seguridad: si por cualquier motivo (cambio de hoja,
    # estado viejo de otra sesión, etc.) la métrica o dimensión seleccionada
    # ya no existe en este dataframe, se descarta en vez de reventar más
    # abajo con un KeyError al intentar graficarla.
    if m is not None and m not in df.columns:
        m = None
    if d is not None and d not in df.columns:
        d = None

    available_dates = bool(schema.get("dates"))

    # ── Área de análisis: antes era una única sección larga (visión
    # general + comparación individual + diagnóstico + gráficos
    # inteligentes + geografía + relaciones + tabla de detalle) que se
    # desplazaba siempre entera. Se agrupa en pestañas — mismo patrón que
    # "Profundiza cuando lo necesites" arriba — para que solo una parte se
    # vea a la vez; el contenido y las funciones que lo generan no cambiaron.
    st.markdown(
        '<div class="analysis-toolbar"><div><span class="eyebrow">ÁREA DE ANÁLISIS</span><h2>Informe analítico</h2></div>'
        '<div class="analysis-toolbar-meta"><span>Filtros activos</span><span>Actualización automática</span></div></div>',
        unsafe_allow_html=True,
    )
    analysis_tabs = named_tabs(["📊 Visión general", "🔍 Diagnóstico", "🌍 Geografía", "🔗 Relaciones y detalle"])
    with analysis_tabs["📊 Visión general"]:
        selected_kind = _primary_analysis_section(df, schema, controls, m, d, available_dates)
    with analysis_tabs["🔍 Diagnóstico"]:
        _diagnostic_and_smart_charts_section(df, schema, controls, m, d, available_dates, selected_kind)
    with analysis_tabs["🌍 Geografía"]:
        _geo_section(df, schema, m)
    with analysis_tabs["🔗 Relaciones y detalle"]:
        _relationships_and_detail_section(df, schema, m, d)
