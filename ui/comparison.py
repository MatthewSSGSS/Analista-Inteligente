import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from ui.labels import pretty_technical


def _fmt(v):
    if v is None or pd.isna(v): return "—"
    x = float(v)
    ax = abs(x)
    if ax >= 1_000_000_000: return f"{x/1_000_000_000:,.2f} mil M"
    if ax >= 1_000_000: return f"{x/1_000_000:,.2f} M"
    if ax >= 1_000: return f"{x/1_000:,.1f} mil"
    return f"{x:,.2f}"


def _pct(v):
    if v is None or pd.isna(v): return "—"
    return f"{'+' if v > 0 else ''}{v:,.1f}%"


def _tone(v):
    if v is None or pd.isna(v) or abs(v) < 0.05: return "neutral"
    return "positive" if v > 0 else "negative"


def render_comparison(result):
    st.markdown('<div class="section-intro"><div><div class="eyebrow">COMPARATIVA</div><h2>Qué cambió entre los archivos</h2></div><div class="data-badge">Último vs. anterior · primero vs. último</div></div>', unsafe_allow_html=True)
    files = result["files"]
    st.caption(" · ".join(f"{i+1}. {f['label']}" for i, f in enumerate(files)))

    metrics = result["recent_metrics"]
    if metrics:
        cols = st.columns(min(5, len(metrics)))
        for col, m in zip(cols, metrics[:5]):
            tone = _tone(m["cambio_pct"])
            arrow = "↑" if tone == "positive" else "↓" if tone == "negative" else "→"
            col.markdown(f'''<div class="kpi-card"><div class="kpi-top"><span class="kpi-icon">{arrow}</span><span class="kpi-label">{m['nombre']}</span></div><div class="kpi-value">{_fmt(m['actual'])}</div><div class="kpi-delta {tone}">{_pct(m['cambio_pct'])} · {m['etiqueta_operacion']}</div></div>''', unsafe_allow_html=True)

    if result["signals"]:
        st.markdown('<div class="decision-panel"><div class="decision-panel-title">Lectura ejecutiva</div><div class="decision-panel-subtitle">Cambios detectados automáticamente a partir de variables comparables.</div></div>', unsafe_allow_html=True)
        for s in result["signals"][:5]:
            icon = "↑" if s["tipo"] == "positive" else "↓" if s["tipo"] == "warning" else "i"
            st.markdown(f'<div class="insight-card {s["tipo"]}"><div class="insight-icon">{icon}</div><div class="insight-body"><div class="insight-label">HALLAZGO COMPARATIVO</div><div class="insight-text">{s["texto"]}</div></div></div>', unsafe_allow_html=True)

    tabs = st.tabs(["Resumen", "Ganadores y caídas", "Evolución", "Variables comparables"])
    with tabs[0]:
        rows=[]
        for m in result["metrics"]:
            rows.append({"Indicador": m["nombre"], result["first"]["label"]: _fmt(m["anterior"]), result["last"]["label"]: _fmt(m["actual"]), "Cambio": _pct(m["cambio_pct"])})
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.warning("No se encontraron métricas compatibles para comparar.")

        if result["dimension_results"]:
            st.markdown("### Cambios por dimensión")
            for dr in result["dimension_results"][:4]:
                st.markdown(f"**{dr['dimension']}** · usando **{dr['metric']}**")
                t=dr["table"].copy()
                t["Cambio"] = t["cambio"].map(lambda x: f"{'+' if x>0 else ''}{x:,.2f}")
                t["Variación"] = t["cambio_pct"].map(_pct)
                show=t.rename(columns={"categoria":"Categoría","anterior":"Periodo anterior","actual":"Periodo actual"})[["Categoría","Periodo anterior","Periodo actual","Cambio","Variación"]].head(10)
                st.dataframe(show, use_container_width=True, hide_index=True)
    with tabs[1]:
        for dr in result["dimension_results"][:4]:
            t=dr["table"]
            up=t.sort_values("cambio", ascending=False).head(5).copy()
            down=t.sort_values("cambio", ascending=True).head(5).copy()
            c1,c2=st.columns(2)
            with c1:
                st.markdown(f"#### 🟢 Mayor mejora · {dr['dimension']}")
                st.dataframe(up[["categoria","cambio","cambio_pct"]].rename(columns={"categoria":"Categoría","cambio":"Cambio","cambio_pct":"Variación"}).style.format({"Cambio":"{:,.2f}","Variación":"{:+.1f}%"}), use_container_width=True, hide_index=True)
            with c2:
                st.markdown(f"#### 🔴 Mayor caída · {dr['dimension']}")
                st.dataframe(down[["categoria","cambio","cambio_pct"]].rename(columns={"categoria":"Categoría","cambio":"Cambio","cambio_pct":"Variación"}).style.format({"Cambio":"{:,.2f}","Variación":"{:+.1f}%"}), use_container_width=True, hide_index=True)
    with tabs[2]:
        for history_index, h in enumerate(result["history"]):
            series=h["serie"]
            fig=px.line(series,x="periodo",y="valor",markers=True,title=f"{h['metrica']} · {h['operacion']}")
            fig.update_layout(height=360,margin=dict(l=20,r=20,t=50,b=20),paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",xaxis_title="Periodo",yaxis_title="Valor")
            st.plotly_chart(fig,use_container_width=True,key=f"comparison_history_{history_index}")
    with tabs[3]:
        matches=result["matches"]
        if matches:
            table=pd.DataFrame([{"Archivo base":"Primero","Columna":""+m["a"],"Archivo final":"Último","Columna equivalente":m["b"],"Coincidencia":f"{m['score']*100:.0f}%","Tipo":pretty_technical(m["concept"])} for m in matches])
            st.dataframe(table,use_container_width=True,hide_index=True)
        else:
            st.info("No se encontraron variables equivalentes.")
