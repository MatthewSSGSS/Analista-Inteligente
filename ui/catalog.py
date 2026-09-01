
import html
import pandas as pd
import streamlit as st
from visualization.charts import ranking, histogram, metric_candidates, dimension_candidates, _label
from ui.components.section import section_header

def _label(schema, c):
    for x in schema.get("semantic", {}).get("columns", []):
        if x.get("column") == c:
            return x.get("display_name") or c
    return str(c)

def _semantic_cols(schema, kinds):
    return [
        x["column"] for x in schema.get("semantic", {}).get("columns", [])
        if x.get("semantic_type") in kinds
    ]

def _pick_title(df, schema):
    candidates = []
    candidates += _semantic_cols(schema, {"product", "name", "brand"})
    candidates += _semantic_cols(schema, {"category", "variant", "status"})
    candidates += [c for c in df.columns if any(k in str(c).lower() for k in ["nombre","name","producto","plan","articulo","variante","descripcion","description"])]
    for c in candidates:
        if c in df.columns and df[c].notna().any():
            return c
    return df.columns[0] if len(df.columns) else None

def _pick_price(df, schema):
    for c in _semantic_cols(schema, {"price", "revenue", "cost"}):
        if c in df.columns:
            return c
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]):
            return c
    return None

def _text_columns(df, schema):
    semantic = _semantic_cols(schema, {"description", "text"})
    for c in df.columns:
        name = str(c).lower()
        if any(k in name for k in ["caracter", "detalle", "beneficio", "incluye", "descripcion", "description", "campania", "campaign"]):
            semantic.append(c)
    return list(dict.fromkeys([c for c in semantic if c in df.columns]))

def _split_points(v):
    if pd.isna(v):
        return []
    s = str(v)
    return [x.strip() for x in s.split("|") if x.strip()]

def render_catalog(df, schema, mode_info):
    st.markdown(section_header("Consulta del catálogo", eyebrow="MODO ADAPTATIVO", badge="Análisis simplificado · búsqueda y comparación"), unsafe_allow_html=True)
    st.caption(mode_info.get("reason", "Este archivo se ha identificado como un catálogo o tabla de referencia."))

    if df.empty:
        st.warning("No hay registros que mostrar con los filtros actuales.")
        return

    title_col = _pick_title(df, schema)
    price_col = _pick_price(df, schema)
    text_cols = _text_columns(df, schema)
    cats = [c for c in schema.get("categorical", []) if c in df.columns]

    with st.expander("🎛️ Buscar y filtrar catálogo", expanded=True):
        q = st.text_input("Buscar", placeholder="Ej.: Amazon, Residencial, 99.900, Ultra Wifi...", key="catalog_search")
        filter_cols = cats[:6]
        selections = {}
        if filter_cols:
            cc = st.columns(min(3, len(filter_cols)))
            for i, c in enumerate(filter_cols):
                vals = sorted(df[c].dropna().astype(str).unique().tolist())
                if 0 < len(vals) <= 80:
                    selections[c] = cc[i % len(cc)].multiselect(_label(schema, c), vals, key=f"catalog_filter_{c}")

    view = df.copy()
    if q:
        mask = pd.Series(False, index=view.index)
        qn = q.strip().lower()
        for c in view.columns:
            mask = mask | view[c].astype(str).str.lower().str.contains(qn, na=False)
        view = view[mask]
    for c, vals in selections.items():
        if vals:
            view = view[view[c].astype(str).isin([str(v) for v in vals])]

    c1, c2, c3 = st.columns(3)
    c1.metric("Elementos disponibles", f"{len(view):,}")
    if price_col:
        p = pd.to_numeric(view[price_col], errors="coerce")
        c2.metric("Precio mínimo", f"{p.min():,.2f}" if p.notna().any() else "—")
        c3.metric("Precio máximo", f"{p.max():,.2f}" if p.notna().any() else "—")
    else:
        c2.metric("Columnas", f"{len(view.columns):,}")
        c3.metric("Resultados de búsqueda", f"{len(view):,}")

    st.markdown("### Opciones disponibles")
    cols = st.columns(2)
    for idx, (_, row) in enumerate(view.iterrows()):
        title = html.escape(str(row.get(title_col, "Elemento"))) if title_col else "Elemento"
        subtitle_parts = []
        for c in cats[:3]:
            if c != title_col and pd.notna(row.get(c)):
                subtitle_parts.append(f"{html.escape(_label(schema,c))}: {html.escape(str(row[c]))}")
        subtitle = " · ".join(subtitle_parts)

        price_html = ""
        if price_col and pd.notna(row.get(price_col)):
            try:
                price_html = f'<div class="catalog-price">{float(row[price_col]):,.2f}</div>' if pd.notna(pd.to_numeric(row[price_col], errors="coerce")) else ""
            except Exception:
                price_html = f'<div class="catalog-price">{html.escape(str(row[price_col]))}</div>'

        bullets = []
        for c in text_cols:
            if pd.notna(row.get(c)):
                bullets.extend(_split_points(row[c])[:6])
        if not bullets:
            for c in df.columns:
                if c not in {title_col, price_col} and pd.notna(row.get(c)):
                    bullets.append(f"<b>{html.escape(_label(schema,c))}:</b> {html.escape(str(row[c]))}")
                if len(bullets) >= 5:
                    break
        bullet_html = "".join(f"<li>{html.escape(str(b)) if not str(b).startswith('<b>') else b}</li>" for b in bullets[:6])
        card = (
            f'<div class="catalog-card"><div class="catalog-card-head">'
            f'<div><div class="catalog-title">{title}</div><div class="catalog-subtitle">{subtitle}</div></div>{price_html}</div>'
            f'<ul>{bullet_html}</ul></div>'
        )
        with cols[idx % 2]:
            st.markdown(card, unsafe_allow_html=True)

    if len(view) > 20:
        st.caption("Mostrando los primeros 20 elementos. Usa la búsqueda y los filtros para localizar un registro concreto.")

    # A catalog/reference sheet can still contain a useful quantitative view.
    # Keep it to one compact chart so the simplified mode remains simple.
    visual_metrics = metric_candidates(view, schema)
    visual_dims = dimension_candidates(view, schema)
    if visual_metrics:
        st.markdown("### Visualización rápida")
        if visual_dims:
            st.caption(f"El sistema detectó una métrica y una dimensión que pueden compararse visualmente: {_label(schema, visual_metrics[0])} por {_label(schema, visual_dims[0])}.")
            fig = ranking(view, schema, visual_metrics[0], visual_dims[0], top_n=10, agg="Suma")
        else:
            st.caption(f"El sistema detectó una métrica cuantitativa: {_label(schema, visual_metrics[0])}.")
            fig = histogram(view, schema, visual_metrics[0])
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "responsive": True}, key="catalog_quick_visual")

    with st.expander("📋 Ver tabla completa"):
        st.dataframe(view, use_container_width=True, hide_index=True)
