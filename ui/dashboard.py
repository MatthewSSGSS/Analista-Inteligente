import streamlit as st
import pandas as pd
import numpy as np
from ui.labels import clean_display_text
from visualization.charts import (
    trend, ranking, donut, histogram, scatter, correlation, geo_summary_map, comparison, period_compare_bar,
    metric_candidates, dimension_candidates, _label, wide_month_chart, _base
)
from core.executive import UMBRAL_CAMBIO
from core.geo_engine import geographic_summary
from core.chart_explainer import explain_chart
from core.universal_analysis import dynamic_kpis, drilldown_options, drilldown_table, smart_chart_questions
import plotly.graph_objects as go
from ui.person_profile import has_entity
from ui.components.cards import kpi_card, insight_card, evidence_list, executive_headline as _shared_executive_headline, executive_signals as _shared_executive_signals
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
        if k.get("texto"):
            return f"{value} · {k['texto']}"
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
        # Con base de comparación la etiqueta ya dice contra qué se mide
        # ("Mejor en cumplimiento de meta"); repetir la métrica la alarga.
        if schema is not None and k.get("metric") and not k.get("base"):
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
            elif k.get("kind")=="leader":
                delta=k.get("detalle")
            st.markdown(_card(label,_display_kpi_value(k),delta,tone,icon),unsafe_allow_html=True)
    if len(kpis)>4:
        cols=st.columns(min(4,len(kpis)-4))
        for i,k in enumerate(kpis[4:8]):
            with cols[i]:
                label,tone,icon=_kpi_style(k,schema)
                st.markdown(_card(label,_display_kpi_value(k),k.get("detalle") if k.get("kind")=="leader" else None,tone,icon),unsafe_allow_html=True)


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
                # Aportar más al total es tamaño, no desempeño: se dice así.
                base += (f" {_clean_text(x.index[0])} es el que más aporta: {share:.1f}% del total. "
                         f"Mide volumen, no qué tan bien le va contra su meta.")
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
            pruebas=evidence_list(a.get("evidence"))
            st.markdown(f'<div class="alert-row compact {cls}"><div class="alert-severity">{clean_display_text(a.get("severity"))}</div><div><b>{clean_display_text(a.get("title"))}</b><div>{clean_display_text(a.get("text"))}</div>{pruebas}{extra}<small><b>Qué hacer:</b> {clean_display_text(a.get("action"))}</small></div></div>',unsafe_allow_html=True)
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
    # Mismo umbral que el veredicto ejecutivo (core/executive.UMBRAL_CAMBIO):
    # tenía 2% aquí y 2% allá, y al bajar el del veredicto a 1% esta franja
    # habría dicho "estable" justo debajo de un titular que declaraba mejora.
    tone="positive" if growth>=UMBRAL_CAMBIO else "negative" if growth<=-UMBRAL_CAMBIO else "neutral"
    if tone=="neutral" and growth:
        label=f"Estable con tendencia {'al alza' if growth>0 else 'a la baja'}"
    else:
        label="Tendencia favorable" if tone=="positive" else "Tendencia a la baja" if tone=="negative" else "Tendencia estable"
    st.markdown(f'<div class="decision-strip {tone}"><b>{label}</b> · Variación del último periodo frente al anterior: {growth:+.1f}%.</div>',unsafe_allow_html=True)


def _performance_por_base(base, schema, dim, result):
    """El ranking contra la base que sí compara, no contra el tamaño.

    Ordenar por total responde "quién es más grande" y se lee como "quién lo
    hace mejor", que son cosas distintas y a veces opuestas: una región que
    vende 10 con meta de 4 lo está haciendo mejor que una que vende 100 con
    meta de 200. Aquí manda `base['clave']`, que dice contra qué se comparó,
    y el total sigue visible al lado para no perder la magnitud.
    """
    ranking=base["ranking"]
    mostrar=ranking[:5] if len(ranking)<=10 else ranking[:5]+ranking[-5:]
    nombres=[f["nombre"] for f in mostrar]
    valores=[f["valor"] for f in mostrar]
    mejor_valor=ranking[0]["valor"]
    peor_valor=ranking[-1]["valor"]
    colores=["#189A63" if f["valor"]>=(mejor_valor+peor_valor)/2 else "#E05252" for f in mostrar]
    fig=go.Figure(go.Bar(
        x=valores, y=nombres, orientation="h",
        marker=dict(color=colores, line=dict(width=0)),
        text=[f["texto"] for f in mostrar], textposition="outside", cliponaxis=False,
        customdata=[[f["detalle"]] for f in mostrar],
        hovertemplate="<b>%{y}</b><br>"+base["etiqueta"]+": <b>%{text}</b><br>%{customdata[0]}<extra></extra>",
    ))
    alto=max(300,38*len(nombres)+80)
    fig.update_layout(showlegend=False,margin=dict(l=10,r=90,t=10,b=10),height=alto)
    fig.update_xaxes(title=None,tickformat="~s")
    fig.update_yaxes(title=None,categoryorder="array",categoryarray=list(reversed(nombres)))
    charts=__import__('visualization.charts',fromlist=['_base','realzar_barras'])
    fig=charts._base(fig,alto,show_xgrid=True)
    # La referencia depende de contra qué se esté comparando: con meta, el
    # 100% es la línea que importa; sin meta, la mediana del grupo.
    if base["clave"]=="meta":
        fig=charts.realzar_barras(fig,referencia=100,referencia_texto="meta 100%")
    else:
        import numpy as _np
        fig=charts.realzar_barras(fig,referencia=float(_np.median([f["valor"] for f in ranking])),
                                  referencia_texto="mediana")

    a,b=two_column(1.65,1)
    with a:
        _chart_card(f"Mejor vs. menor desempeño · {base['etiqueta']}",
                    base["explicacion"], fig, "No hay datos suficientes.",
                    key="performance_extremes_chart")
    with b:
        mejor,peor=base["mejor"],base["peor"]
        # "Mejor desempeño" solo se afirma cuando hay una base que de verdad
        # mide desempeño. Con un salario promedio o un stock promedio lo
        # honesto es decir "valor más alto": nadie rinde más por cobrar más.
        titulos=(("Mejor desempeño","Menor desempeño")
                 if base["clave"] in {"meta","unidad","estado","registro"}
                 else ("Valor más alto","Valor más bajo"))
        st.markdown(f'<div class="insight-card positive"><div class="insight-body"><div class="insight-title">{titulos[0]}</div><div class="insight-text"><b>{clean_display_text(mejor["nombre"])}</b><br>{mejor["texto"]}<br><small style="color:var(--soft)">{clean_display_text(mejor["detalle"])}</small></div></div></div>',unsafe_allow_html=True)
        st.markdown(f'<div class="insight-card warning"><div class="insight-body"><div class="insight-title">{titulos[1]}</div><div class="insight-text"><b>{clean_display_text(peor["nombre"])}</b><br>{peor["texto"]}<br><small style="color:var(--soft)">{clean_display_text(peor["detalle"])}</small></div></div></div>',unsafe_allow_html=True)
        if not base["justo"]:
            st.warning("Esta comparación mide tamaño. Agrega una columna de meta al archivo "
                       "para que el ranking mida desempeño.")

    # El orden por total sigue disponible: responde otra pregunta legítima
    # —de dónde sale el volumen— y perderlo sería cambiar un sesgo por otro.
    orden_total=sorted(ranking,key=lambda f:f["total"],reverse=True)
    if base["clave"] not in {"total","total_parejo"} and orden_total[0]["nombre"]!=base["mejor"]["nombre"]:
        st.caption(f"Por volumen el primero es **{orden_total[0]['nombre']}** "
                   f"({_fmt(orden_total[0]['total'])}), pero en {base['etiqueta'].lower()} "
                   f"queda {[f['nombre'] for f in ranking].index(orden_total[0]['nombre'])+1}.º de {len(ranking)}.")


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
        if 2<=n<=2000:
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
    base=result.get("base")
    with c2:
        if base:
            st.caption(f"Comparado por **{base['etiqueta']}** · {_label(schema,dim)}")
        else:
            agg_label="Total" if result["aggregation"]=="sum" else "Promedio"
            st.caption(f"{_label(schema,result['metric'])} por {_label(schema,dim).lower()} · {agg_label}")
    if base:
        _performance_por_base(base, schema, dim, result)
        return
    if result.get("aggregation")!="sum" and not result.get("additive"):
        # Sin base no hay nada que agregar: cada grupo es una fila suelta y
        # ordenarlas por su valor sería la columna ordenada, no un ranking de
        # desempeño. Antes esto coronaba al producto más caro como "el más
        # productivo" de un catálogo.
        st.info(f"Este archivo no permite comparar desempeño entre valores de "
                f"{_label(schema,dim)}: cada uno aparece una sola vez, así que no hay nada que agregar. "
                f"Con una columna de meta, o con varias filas por grupo, sí se puede.")
        return
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
        html = insight_card(finding, title=title, kind=cls, icon=icon, action=action, compact=True,
                            evidence=item.get("evidence"))
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

            # La «Comparación individual» que vivía aquí (elegir una dimensión,
            # hasta 6 elementos y 9 tipos de gráfico, con la ficha de persona
            # embebida) se quitó: la pestaña «📊 Cuadro comparativo» hace lo
            # mismo y mejor —sin tope de elementos, con meta, posición y la
            # referencia del grupo completo—, y «⚔️ Comparar personas» cubre el
            # A vs B. Tenerla también aquí obligaba a mantener dos caminos para
            # la misma pregunta. Con ella se fueron `_individual_trend` y
            # `_person_profile`, que ya no llamaba nadie más.
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
    if geo_meta.get("mode") in {"coordinates", "city_geocoding", "region_geocoding", "country_geocoding", "embedded_text"} and geo_summary.get("table") is not None and not geo_summary.get("table").empty:
        g1, g2, g3, g4 = st.columns(4)
        g1.metric(f"{geo_meta.get('level','Ubicaciones')} ubicados", f"{geo_kpis.get('cities', 0):,}")
        g2.metric("Ciudad líder", geo_kpis.get("leader", "—"))
        g3.metric("Valor líder", _fmt(geo_kpis.get("leader_value", 0)))
        g4.metric("Participación líder", f"{geo_kpis.get('leader_share', 0):.1f}%")
        if geo_meta.get("mode") in {"city_geocoding", "region_geocoding", "country_geocoding", "embedded_text"}:
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

    # El análisis de seguimiento ya no vive aquí dentro: tiene pestaña propia
    # ("🔎 Análisis de seguimiento"). Enterrado a media página, con un botón
    # que había que descubrir, era de las herramientas menos usadas del panel
    # pese a responder una de las preguntas más frecuentes.
    if has_entity(df, schema):
        st.caption("¿Quieres ver un punto, asesor o código en concreto? Está en la pestaña "
                   "**🔎 Análisis de seguimiento**, con sus alertas y su comparación contra el grupo.")

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
        # dashboard.get("performance", {}) NO alcanza cuando la clave existe
        # pero su valor es None (analyze_performance() en core/performance.py
        # devuelve None explícitamente si no hay una dimensión categórica
        # válida para desglosar, p. ej. datos ya reducidos a una sola
        # categoría visible) — .get(clave, default) solo usa el default
        # cuando la clave falta, no cuando vale None, así que quedaba
        # ".get(...)" sobre None y tronaba con AttributeError. "or {}"
        # cubre ambos casos; es el mismo patrón que ya usa
        # performance_cfg más arriba en este archivo.
        _drilldown_panel(df, schema, dashboard.get("primary_metric"), (dashboard.get("performance") or {}).get("dimension"))

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
