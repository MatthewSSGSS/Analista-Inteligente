from __future__ import annotations
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from core.numeric import numeric_series
from core.universal_analysis import semantic_map, ADDITIVE, period_series
from visualization.charts import metric_candidates, _label


def _fmt(v):
    if v is None or pd.isna(v): return "—"
    x=float(v); ax=abs(x)
    if ax>=1e9:return f"{x/1e9:.2f}B"
    if ax>=1e6:return f"{x/1e6:.2f}M"
    if ax>=1e3:return f"{x/1e3:.1f}K"
    return f"{x:,.0f}"


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
    c1,c2,c3,c4=st.columns(4)
    c1.metric(person_a,_fmt(va)); c2.metric(person_b,_fmt(vb)); c3.metric("Diferencia",_fmt(delta),f"{pct:+.1f}%" if pct is not None else None); c4.metric("Mejor resultado",person_b if vb>va else person_a if va>vb else "Empate")

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
    fig.update_layout(margin=dict(l=15,r=15,t=20,b=25),paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",font=dict(color="#172033"))
    st.plotly_chart(fig,use_container_width=True,key="ab_compare_chart_v52")

    # Explain the gap using the first useful business dimension.
    dims=[]
    priorities={"product":0,"category":1,"channel":2,"brand":3,"segment":4,"city":5,"region":6}
    for c,t in sem.items():
        if c in df.columns and c != person_col and t in priorities:
            n=df[c].dropna().astype(str).nunique()
            if 1<n<=30:dims.append((priorities[t],c))
    if dims:
        dim=sorted(dims)[0][1]
        def top(rows):
            z=rows[[dim,metric]].copy(); z[metric]=numeric_series(z[metric]); z=z.dropna(); z[dim]=z[dim].fillna("Sin dato").astype(str)
            agg=z.groupby(dim)[metric].sum() if additive else z.groupby(dim)[metric].mean()
            return agg.sort_values(ascending=False).head(5)
        ta,tb=top(rows_a),top(rows_b)
        comp=pd.concat([ta.rename(person_a),tb.rename(person_b)],axis=1).fillna(0).reset_index().rename(columns={"index":_label(schema,dim)})
        st.markdown(f"### Qué explica la diferencia · {_label(schema,dim)}")
        st.dataframe(comp,use_container_width=True,hide_index=True)
