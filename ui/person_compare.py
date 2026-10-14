"""Comparación A vs. B: dos personas, lado a lado, con los mismos
componentes que ya usa el perfil individual (ui/person_profile.py) —
kpi_card, chart_card, section_header — en vez de tarjetas/gráficos armados
a mano por separado.
"""
from __future__ import annotations
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from ui.components.escena import NO_DISPONIBLE, cabecera, escena
from core.numeric import numeric_series
from core.universal_analysis import semantic_map, ADDITIVE, period_series
from visualization.charts import metric_candidates, _label, chart_text_color
from ui.components.cards import kpi_card
from ui.components.charts import chart_card
from ui.components.section import section_header


def _fmt(v):
    if v is None or pd.isna(v): return "—"
    x=float(v); ax=abs(x)
    if ax>=1e9:return f"{x/1e9:.2f} mil M"
    if ax>=1e6:return f"{x/1e6:.2f}M"
    if ax>=1e3:return f"{x/1e3:.1f}K"
    return f"{x:,.0f}"


def _datos_duelo(df, schema, person_col, person_a, person_b, metric, metrics, sem, rows_a, rows_b, va, vb) -> dict:
    """Lo que dibuja «Comparar personas» en JavaScript (ui/web/duelo.*), en texto plano.
    El puesto de cada uno se mide sobre TODO el grupo visible, no solo entre los dos."""
    clave = df[person_col].astype(str).str.strip()
    additive = sem.get(metric) in ADDITIVE
    valores = numeric_series(df[metric])
    por_persona = (valores.groupby(clave).sum(min_count=1) if additive else valores.groupby(clave).mean()).dropna()
    orden = por_persona.sort_values(ascending=False)
    n = len(orden)

    def puesto(nombre):
        if nombre not in orden.index:
            return ""
        return f"{int((orden > orden[nombre]).sum()) + 1}.º de {n}"

    delta = vb - va
    pct = (delta / abs(va) * 100) if va else None
    ganador = "b" if vb > va else "a" if va > vb else ""
    lectura = ("Empatan en " + _label(schema, metric).lower()) if not ganador else (
        f"{person_b if ganador == 'b' else person_a} va adelante por {_fmt(abs(delta))}")

    def fila(nombre, x, y, menos_mejor=False):
        tope = max(abs(x), abs(y)) or 1
        gana = "" if x == y else (("a" if x < y else "b") if menos_mejor else ("a" if x > y else "b"))
        return {"n": nombre, "a": round(abs(x) / tope * 100, 1), "b": round(abs(y) / tope * 100, 1),
                "at": _fmt(x), "bt": _fmt(y), "gana": gana}

    duelos = []
    for m in metrics[:6]:
        sa, sb = numeric_series(rows_a[m]).dropna(), numeric_series(rows_b[m]).dropna()
        if not len(sa) and not len(sb):
            continue
        suma = sem.get(m) in ADDITIVE
        x = float(sa.sum()) if suma else (float(sa.mean()) if len(sa) else 0.0)
        y = float(sb.sum()) if suma else (float(sb.mean()) if len(sb) else 0.0)
        duelos.append(fila(f"{_label(schema, m)} ({'total' if suma else 'promedio'})", x, y))
    duelos.append({**fila("Registros", float(len(rows_a)), float(len(rows_b))),
                   "at": f"{len(rows_a):,}", "bt": f"{len(rows_b):,}"})

    desglose = None
    priorities = {"product": 0, "category": 1, "channel": 2, "brand": 3, "segment": 4, "city": 5, "region": 6}
    dims = sorted((priorities[t], c) for c, t in sem.items()
                  if c in df.columns and c != person_col and t in priorities and 1 < df[c].dropna().astype(str).nunique() <= 30)
    if dims:
        dim = dims[0][1]

        def agrupa(rows):
            z = pd.DataFrame({"d": rows[dim].fillna("Sin dato").astype(str), "v": numeric_series(rows[metric])}).dropna()
            return z.groupby("d")["v"].sum() if additive else z.groupby("d")["v"].mean()
        ga, gb = agrupa(rows_a), agrupa(rows_b)
        cats = (ga.add(gb, fill_value=0)).sort_values(ascending=False).head(8).index
        if len(cats):
            desglose = {"dimension": _label(schema, dim),
                        "filas": [fila(str(c), float(ga.get(c, 0)), float(gb.get(c, 0))) for c in cats]}
    return {
        "a": {"nombre": person_a, "valor": _fmt(va), "puesto": puesto(person_a)},
        "b": {"nombre": person_b, "valor": _fmt(vb), "puesto": puesto(person_b)},
        "metrica": _label(schema, metric), "diferencia": _fmt(abs(delta)),
        "pct": f"{pct:+.1f}% de B frente a A" if pct is not None else "", "ganador": ganador,
        "lectura": lectura, "duelos": duelos, "desglose": desglose,
    }


def render_person_compare(df, schema):
    full = schema.get("full_name", {}) if isinstance(schema.get("full_name"), dict) else {}
    person_col = full.get("column") if full.get("column") in df.columns else None
    if not person_col:
        st.info("La comparación A vs B requiere una identidad individual detectable en el Excel.")
        return
    names = sorted(df[person_col].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique(), key=str.casefold)
    metrics = [m for m in metric_candidates(df, schema) if m in df.columns]
    if not names or not metrics:
        st.info("No hay suficientes nombres o métricas para construir una comparación A vs B.")
        return
    sem = semantic_map(schema)
    preferred = [m for m in metrics if sem.get(m) in {"revenue","profit","quantity","sales","rating"}]

    cabecera("Comparar personas", "Dos personas lado a lado: mismos indicadores, mismo gráfico.",
             ceja="Comparación A vs B", icono="⚔️", clave="cab_comparar_personas",
             respaldo_html=section_header("Comparar personas", eyebrow="COMPARACIÓN A VS B", subtitle="Compara dos personas lado a lado: mismos indicadores, mismo gráfico."))

    # ── Selección: métrica + las dos personas, lado a lado ─────────────────
    metric = st.selectbox("Métrica a comparar", preferred or metrics, format_func=lambda c:_label(schema,c), key="ab_metric_v52")
    a,b = st.columns(2)
    with a: person_a = st.selectbox("Persona A", names, key="ab_person_a_v52")
    with b:
        candidates_b = [n for n in names if n != person_a]
        person_b = st.selectbox("Persona B", candidates_b or names, key="ab_person_b_v52")
    rows_a=df[df[person_col].astype(str).str.strip().eq(person_a)].copy(); rows_b=df[df[person_col].astype(str).str.strip().eq(person_b)].copy()
    s_a=numeric_series(rows_a[metric]).dropna(); s_b=numeric_series(rows_b[metric]).dropna()
    additive=sem.get(metric) in ADDITIVE
    va=float(s_a.sum()) if additive else float(s_a.mean()) if len(s_a) else 0
    vb=float(s_b.sum()) if additive else float(s_b.mean()) if len(s_b) else 0
    delta=vb-va; pct=(delta/abs(va)*100) if va else None
    winner = person_b if vb>va else person_a if va>vb else "Empate"

    # Cara a cara en JavaScript (ui/web/duelo.*): las dos personas, quién gana
    # en cada indicador y qué explica la diferencia. Sin él, las tarjetas.
    en_js = escena("duelo", _datos_duelo(df, schema, person_col, person_a, person_b, metric, metrics, sem,
                                         rows_a, rows_b, va, vb), clave="duelo_js") is not NO_DISPONIBLE
    if not en_js:
        st.markdown(section_header("Métricas", compact=True), unsafe_allow_html=True)
        delta_tone = "neutral" if pct is None else ("positive" if delta >= 0 else "negative")
        c1,c2,c3,c4=st.columns(4)
        c1.markdown(kpi_card(person_a,_fmt(va)), unsafe_allow_html=True)
        c2.markdown(kpi_card(person_b,_fmt(vb)), unsafe_allow_html=True)
        c3.markdown(kpi_card("Diferencia",_fmt(delta), delta=f"{pct:+.1f}%" if pct is not None else None, tone=delta_tone), unsafe_allow_html=True)
        c4.markdown(kpi_card("Mejor resultado", winner), unsafe_allow_html=True)

    # ── Gráfico comparativo: mismos 5 tipos de siempre ──────────────────────
    st.markdown(section_header("Gráfico comparativo", compact=True), unsafe_allow_html=True)
    chart_type=st.selectbox("Tipo de comparación", ["Barras comparativas","Líneas","Barras apiladas","Barras 100%","Radar"], key="ab_chart_type_v52")
    date_cols=[d for d in schema.get("dates",[]) if d in df.columns]
    if date_cols:
        pa=period_series(rows_a,schema,metric,"Mes","Automático"); pb=period_series(rows_b,schema,metric,"Mes","Automático")
        if chart_type == "Líneas" and len(pa)>=1 and len(pb)>=1:
            fig=go.Figure()
            for label,series,color in [(person_a,pa,"#E4002B"),(person_b,pb,"#0FA8A0")]:
                fig.add_trace(go.Scatter(x=series["period"],y=series[metric],mode="lines+markers",name=label,line=dict(color=color,width=3.2),marker=dict(size=7)))
            fig.update_layout(height=400,hovermode="x unified")
        elif chart_type == "Radar":
            cats=["Total","Promedio","Máximo","Registros"]
            vals_a=[va,float(s_a.mean()) if len(s_a) else 0,float(s_a.max()) if len(s_a) else 0,len(rows_a)]
            vals_b=[vb,float(s_b.mean()) if len(s_b) else 0,float(s_b.max()) if len(s_b) else 0,len(rows_b)]
            def norm(vs):
                mx=max(vs) or 1; return [v/mx for v in vs]
            fig=go.Figure()
            fig.add_trace(go.Scatterpolar(r=norm(vals_a)+[norm(vals_a)[0]],theta=cats+[cats[0]],fill="toself",name=person_a,line=dict(color="#E4002B")))
            fig.add_trace(go.Scatterpolar(r=norm(vals_b)+[norm(vals_b)[0]],theta=cats+[cats[0]],fill="toself",name=person_b,line=dict(color="#0FA8A0")))
            fig.update_layout(height=420,polar=dict(radialaxis=dict(visible=False)))
        else:
            comp=pd.DataFrame({"Persona":[person_a,person_b],"Valor":[va,vb]})
            if chart_type=="Barras apiladas":
                fig=go.Figure(go.Bar(x=["Comparación"],y=[va],name=person_a,marker_color="#E4002B"))
                fig.add_trace(go.Bar(x=["Comparación"],y=[vb],name=person_b,marker_color="#0FA8A0")); fig.update_layout(barmode="stack",height=360)
            elif chart_type=="Barras 100%":
                fig=px.bar(comp,x="Persona",y="Valor",color="Persona",text_auto=".3s",color_discrete_sequence=["#E4002B","#0FA8A0"]); fig.update_layout(height=360)
            else:
                fig=px.bar(comp,x="Persona",y="Valor",color="Persona",text_auto=".3s",color_discrete_sequence=["#E4002B","#0FA8A0"]); fig.update_layout(height=360,showlegend=False)
    else:
        comp=pd.DataFrame({"Persona":[person_a,person_b],"Valor":[va,vb]})
        fig=px.bar(comp,x="Persona",y="Valor",color="Persona",text_auto=".3s",color_discrete_sequence=["#E4002B","#0FA8A0"]); fig.update_layout(height=360,showlegend=False)
    fig.update_layout(margin=dict(l=15,r=15,t=20,b=25),paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",font=dict(color=chart_text_color()))
    chart_card(
        f"{person_a} vs. {person_b}", f"{_label(schema, metric)} · {chart_type}", fig,
        key="ab_compare_chart_v52", visual_type="COMPARACIÓN", badge_text="Datos de A y B",
    )

    # Explain the gap using the first useful business dimension.
    dims=[]
    priorities={"product":0,"category":1,"channel":2,"brand":3,"segment":4,"city":5,"region":6}
    for c,t in sem.items():
        if c in df.columns and c != person_col and t in priorities:
            n=df[c].dropna().astype(str).nunique()
            if 1<n<=30:dims.append((priorities[t],c))
    if dims and not en_js:
        dim=sorted(dims)[0][1]
        def top(rows):
            z=rows[[dim,metric]].copy(); z[metric]=numeric_series(z[metric]); z=z.dropna(); z[dim]=z[dim].fillna("Sin dato").astype(str)
            agg=z.groupby(dim)[metric].sum() if additive else z.groupby(dim)[metric].mean()
            return agg.sort_values(ascending=False).head(5)
        ta,tb=top(rows_a),top(rows_b)
        comp=pd.concat([ta.rename(person_a),tb.rename(person_b)],axis=1).fillna(0).reset_index().rename(columns={"index":_label(schema,dim)})
        st.markdown(section_header(f"Qué explica la diferencia · {_label(schema,dim)}", compact=True), unsafe_allow_html=True)
        # Cifras cortas en las columnas de cada persona, no «1213564697.54».
        for col in (person_a, person_b):
            if col in comp.columns:
                comp[col] = comp[col].map(_fmt)
        st.dataframe(comp,use_container_width=True,hide_index=True)
