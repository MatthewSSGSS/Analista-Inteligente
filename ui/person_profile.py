from __future__ import annotations

import re
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.numeric import numeric_series
from core.universal_analysis import semantic_map, ADDITIVE, period_series
from visualization.charts import metric_candidates, dimension_candidates, _label, chart_text_color
from ui.components.cards import kpi_card
from ui.components.charts import chart_card
from ui.components.section import section_header
from ui.layouts.columns import two_column


def _fmt(v):
    if v is None or pd.isna(v):
        return "—"
    try:
        x = float(v)
    except Exception:
        return str(v)
    ax = abs(x)
    if ax >= 1e9: return f"{x/1e9:.2f}B"
    if ax >= 1e6: return f"{x/1e6:.2f}M"
    if ax >= 1e3: return f"{x/1e3:.1f}K"
    return f"{x:,.0f}"


def _person_col(schema, df):
    full = schema.get("full_name", {}) if isinstance(schema.get("full_name"), dict) else {}
    c = full.get("column")
    if c in df.columns:
        return c
    sem = semantic_map(schema)
    for c, t in sem.items():
        if c in df.columns and t in {"employee", "customer", "person", "name"}:
            return c
    norm = {re.sub(r"[^a-z0-9]+", "", str(c).casefold()): c for c in df.columns}
    for alias in ("nombrecompleto", "nombre", "name", "agente", "asesor", "vendedor", "empleado", "cliente"):
        if alias in norm:
            return norm[alias]
    return None


def _card(label, value, delta=None):
    return kpi_card(label, value, delta=delta)


def _chart(title, subtitle, fig, key):
    chart_card(title, subtitle, fig, key=key, visual_type="PERFIL", badge_text="Datos del seleccionado")


def _apply_current_filters(df):
    out = df.copy()
    filters = st.session_state.get("filters", {}) or {}
    date_rule = filters.get("__date__")
    if isinstance(date_rule, dict) and date_rule.get("column") in out.columns:
        d = date_rule["column"]
        out[d] = pd.to_datetime(out[d], errors="coerce")
        out = out[(out[d] >= date_rule.get("start")) & (out[d] <= date_rule.get("end"))]
    for c, rule in filters.items():
        if str(c).startswith("__") or c not in out.columns or not isinstance(rule, dict):
            continue
        op, val = rule.get("op"), rule.get("value")
        s = out[c]
        if op == "in":
            vals = val if isinstance(val, (list, tuple, set)) else [val]
            out = out[s.astype(str).isin([str(v) for v in vals])]
        elif op in {"equals", "eq"}:
            out = out[s.astype(str).str.casefold() == str(val).casefold()]
    return out


def render_person_profile(df, schema, dashboard=None):
    """Dedicated universal profile: everything the workbook can legitimately say about one person."""
    person_col = _person_col(schema, df)
    if not person_col:
        st.info("Este Excel no contiene una persona, agente, cliente o nombre identificable para construir un perfil individual.")
        return

    data = _apply_current_filters(df)
    names = sorted(data[person_col].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique(), key=str.casefold)
    if not names:
        st.info("No hay personas disponibles con los filtros actuales.")
        return

    st.markdown(section_header("Analizar perfil individual", eyebrow="PERFIL INDIVIDUAL", subtitle="Selecciona una persona y revisa todo lo que el Excel permite conocer sobre ella."), unsafe_allow_html=True)
    selected = st.selectbox("Buscar y seleccionar nombre completo", names, key="profile_person_selector_inline", placeholder="Escribe para buscar…")
    rows = data[data[person_col].astype(str).str.strip().eq(str(selected).strip())].copy()
    if rows.empty:
        return

    sem = semantic_map(schema)
    # Qué métricas existen se decide con el archivo completo (respetando los
    # filtros globales), no con el subconjunto de esta persona: si alguien
    # tiene pocos registros, sus valores podrían parecer un código/ID por
    # casualidad y ocultar una métrica que sí es válida para todos los demás.
    metrics = [m for m in metric_candidates(data, schema) if m in rows.columns]
    primary = metrics[0] if metrics else None
    preferred = [m for m in metrics if sem.get(m) in {"revenue", "profit", "quantity", "sales", "price", "rating"}]
    if preferred:
        primary = preferred[0]

    st.markdown(f'<div class="decision-strip positive"><b>{selected}</b> · {len(rows):,} registros relacionados encontrados. Todo el análisis de esta pestaña está restringido a esta persona.</div>', unsafe_allow_html=True)

    # 1. KPI layer
    st.markdown(section_header("KPIs", compact=True), unsafe_allow_html=True)
    kpis = [{"label": "Registros relacionados", "value": f"{len(rows):,}"}]
    if primary:
        s = numeric_series(rows[primary]).dropna()
        additive = sem.get(primary) in ADDITIVE
        val = float(s.sum()) if additive else float(s.mean()) if len(s) else None
        kpis.append({"label": "Total" if additive else "Promedio", "value": _fmt(val)})
        kpis.append({"label": "Máximo", "value": _fmt(s.max()) if len(s) else "—"})
        # Mínimo, no un "Promedio" repetido: cuando la métrica principal no es
        # aditiva (precio, calificación, edad...), la 2ª tarjeta ya muestra el
        # promedio — mostrarlo otra vez en la 4ª no aportaba nada nuevo.
        kpis.append({"label": "Mínimo", "value": _fmt(s.min()) if len(s) else "—"})
    cols = st.columns(min(4, len(kpis)))
    for i, k in enumerate(kpis[:4]):
        with cols[i]: st.markdown(_card(k["label"], k["value"]), unsafe_allow_html=True)

    # 2. Temporal performance
    date_cols = [d for d in schema.get("dates", []) if d in rows.columns]
    if primary and date_cols:
        st.markdown(section_header("Evolución", compact=True), unsafe_allow_html=True)
        ps = period_series(rows, schema, primary, "Mes", "Automático")
        if len(ps) >= 2:
            prev, cur = float(ps.iloc[-2][primary]), float(ps.iloc[-1][primary])
            pct = ((cur-prev)/abs(prev)*100) if prev else None
            tone = "positive" if pct is not None and pct >= 0 else "negative"
            text = f"{selected} {'mejoró' if tone == 'positive' else 'empeoró'} {abs(pct):.1f}% en el último periodo." if pct is not None else "Hay varios periodos disponibles para analizar la evolución."
            st.markdown(f'<div class="decision-strip {tone}"><b>Lectura principal:</b> {text}</div>', unsafe_allow_html=True)
            fig = go.Figure(go.Scatter(
                x=ps["period"], y=ps[primary], mode="lines+markers", name=selected,
                line=dict(color="#E4002B", width=3.5), marker=dict(size=8),
                hovertemplate="<b>%{x|%b %Y}</b><br>" + _label(schema, primary) + ": <b>%{y:,.0f}</b><extra></extra>",
            ))
            fig.update_layout(height=380, margin=dict(l=15,r=15,t=20,b=25), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=chart_text_color()))
            fig.update_xaxes(showgrid=False); fig.update_yaxes(showgrid=True, gridcolor="rgba(96,112,132,.16)", title=_label(schema, primary))
            _chart("Evolución de la persona", f"Cómo ha cambiado {_label(schema, primary).lower()} por periodo", fig, "profile_person_trend_v52")

    # 3-4. Características: qué explica el resultado + cómo se compara con
    # el resto. Antes eran dos secciones apiladas siempre a todo el ancho;
    # ahora, cuando ambas tienen datos, se muestran una junto a la otra
    # (two_column) para no alargar la página con dos gráficos de ancho
    # completo que responden preguntas relacionadas.
    dim_candidates = []
    priorities = {"product": 0, "category": 1, "channel": 2, "brand": 3, "segment": 4, "city": 5, "region": 6, "status": 7}
    for c, t in sem.items():
        if c in rows.columns and c != person_col and t in priorities:
            n = rows[c].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()
            if 1 < n <= 30: dim_candidates.append((priorities[t], c))
    dim_candidates = [c for _, c in sorted(dim_candidates)]

    mix_fig = mix_title = mix_subtitle = mix_lead = None
    if dim_candidates:
        dim = dim_candidates[0]
        z = rows[[dim] + ([primary] if primary else [])].copy()
        z[dim] = z[dim].fillna("Sin dato").astype(str).str.strip().replace("", "Sin dato")
        if primary:
            z[primary] = numeric_series(z[primary])
            z = z.dropna(subset=[primary])
            agg = z.groupby(dim)[primary].sum() if sem.get(primary) in ADDITIVE else z.groupby(dim)[primary].mean()
            top = agg.sort_values(ascending=False).head(10).reset_index(name=primary)
            if not top.empty:
                mix_lead = f'**{_label(schema, dim)} que más explica el resultado:** {top.iloc[0][dim]} · {_fmt(top.iloc[0][primary])}'
                fig = px.bar(top.sort_values(primary), x=primary, y=dim, orientation="h", text_auto=".3s")
                fig.update_traces(marker_color="#0FA8A0", marker_line_width=0)
                fig.update_layout(height=max(330, 34*len(top)+90), margin=dict(l=10,r=20,t=15,b=15), showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=chart_text_color()))
                fig.update_xaxes(showgrid=True, gridcolor="rgba(96,112,132,.16)"); fig.update_yaxes(showgrid=False)
                mix_fig = fig
                mix_title = f"Desglose por {_label(schema, dim)}"
                mix_subtitle = "Qué productos, categorías, canales u otras dimensiones mueven el resultado"

    bench_fig = None
    if primary:
        s_person = numeric_series(rows[primary]).dropna()
        s_all = numeric_series(data[primary]).dropna()
        if len(s_person) and len(s_all):
            additive = sem.get(primary) in ADDITIVE
            person_value = float(s_person.sum()) if additive else float(s_person.mean())
            global_value = float(s_all.mean())
            comp = pd.DataFrame({"Referencia": [selected, "Promedio visible"], "Valor": [person_value, global_value]})
            fig = px.bar(comp, x="Referencia", y="Valor", color="Referencia", text_auto=".3s", color_discrete_sequence=["#E4002B", "#94A3B8"])
            fig.update_layout(height=320, margin=dict(l=10,r=10,t=15,b=20), showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=chart_text_color()))
            fig.update_yaxes(showgrid=True, gridcolor="rgba(96,112,132,.16)")
            bench_fig = fig

    bench_title = "Persona vs. promedio visible"
    bench_subtitle = "Permite saber rápidamente si el resultado está por encima o por debajo del contexto"
    if mix_fig is not None or bench_fig is not None:
        st.markdown(section_header("Características", compact=True), unsafe_allow_html=True)
        if mix_fig is not None and bench_fig is not None:
            main_col, side_col = two_column(1.4, 1)
            with main_col:
                if mix_lead: st.markdown(mix_lead)
                _chart(mix_title, mix_subtitle, mix_fig, "profile_person_mix_v52")
            with side_col:
                _chart(bench_title, bench_subtitle, bench_fig, "profile_person_benchmark_v52")
        elif mix_fig is not None:
            if mix_lead: st.markdown(mix_lead)
            _chart(mix_title, mix_subtitle, mix_fig, "profile_person_mix_v52")
        else:
            _chart(bench_title, bench_subtitle, bench_fig, "profile_person_benchmark_v52")

    # 5. Everything else the workbook knows: compact metadata + raw records
    st.markdown(section_header("Todo lo relacionado con la persona", eyebrow="CONTEXTO COMPLETO", compact=True), unsafe_allow_html=True)
    context_rows = []
    for c in rows.columns:
        if str(c).startswith("__") or str(c).startswith("_geo_") or c == person_col:
            continue
        s = rows[c]
        if c in schema.get("dates", []):
            dt = pd.to_datetime(s, errors="coerce").dropna()
            value = f"{dt.min().strftime('%d/%m/%Y')} → {dt.max().strftime('%d/%m/%Y')}" if len(dt) else "Sin fecha válida"
        elif c in metrics:
            ns = numeric_series(s).dropna()
            value = f"min {_fmt(ns.min())} · promedio {_fmt(ns.mean())} · max {_fmt(ns.max())}" if len(ns) else "Sin valor numérico válido"
        else:
            vals = s.dropna().astype(str).str.strip().replace("", pd.NA).dropna().drop_duplicates().tolist()
            value = ", ".join(vals[:8]) if vals else "Sin dato"
            if len(vals) > 8: value += f" · +{len(vals)-8} más"
        context_rows.append({"Campo": _label(schema, c), "Información encontrada": value})
    if context_rows:
        st.dataframe(pd.DataFrame(context_rows), use_container_width=True, hide_index=True)

    with st.expander("Ver registros originales relacionados", expanded=False):
        visible = [c for c in rows.columns if not str(c).startswith("__") and not str(c).startswith("_geo_")]
        st.dataframe(rows[visible].head(500), use_container_width=True, hide_index=True)
        if len(rows) > 500:
            st.caption(f"Mostrando 500 de {len(rows):,} registros relacionados.")
