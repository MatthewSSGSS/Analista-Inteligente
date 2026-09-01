from __future__ import annotations

import re
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from visualization.charts import apply_dashboard_theme

from core.geo_engine import geographic_summary
from visualization.charts import metric_candidates, _label, _compact_number


def _fmt(v):
    if pd.isna(v):
        return "—"
    try:
        v = float(v)
    except Exception:
        return str(v)
    if abs(v) >= 1_000_000_000:
        return f"{v/1_000_000_000:.1f}B"
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"{v/1_000:.1f}K"
    return f"{v:,.0f}"


def _safe_name(v):
    if pd.isna(v) or str(v).strip() == "":
        return "Sin dato"
    return str(v).strip()


def _person_column(df: pd.DataFrame, schema: dict):
    """Find a usable person/agent label without assuming a fixed workbook layout."""
    full = schema.get("full_name") if isinstance(schema.get("full_name"), dict) else {}
    col = full.get("column") if full else None
    if col and col in df.columns:
        return col
    # Prefer semantic employee/customer/name fields.
    for item in schema.get("semantic", {}).get("columns", []):
        if item.get("column") not in df.columns:
            continue
        if item.get("semantic_type") in {"employee", "customer", "person", "name"}:
            return item.get("column")
    aliases = {"nombre completo", "nombre", "nombres", "name", "agente", "asesor", "vendedor", "empleado", "cliente"}
    normalized = {re.sub(r"[^a-z0-9]+", "", str(c).casefold()): c for c in df.columns}
    for alias in aliases:
        key = re.sub(r"[^a-z0-9]+", "", alias.casefold())
        if key in normalized:
            return normalized[key]
    return None


def _performance_class(series: pd.Series) -> pd.Series:
    """Classify locations into high/medium/low value bands for the map."""
    if series.empty:
        return pd.Series(dtype=str)
    q1, q2 = series.quantile([0.33, 0.67]).tolist()
    if q1 == q2:
        return pd.Series(["Nivel alto" if v >= q2 else "Nivel bajo" for v in series], index=series.index)
    return series.map(lambda v: "Nivel alto" if v >= q2 else ("Nivel medio" if v >= q1 else "Nivel bajo"))


def _map_figure(summary: dict, metric: str | None):
    table = summary.get("table")
    if table is None or table.empty:
        return None
    x = table.copy()
    for c in ("_geo_lat", "_geo_lon", "_geo_metric", "share_pct"):
        if c in x.columns:
            x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=["_geo_lat", "_geo_lon"]).copy()
    if x.empty:
        return None

    x["_geo_metric"] = x["_geo_metric"].fillna(0).clip(lower=0)
    x["share_pct"] = x["share_pct"].fillna(0)
    x["_geo_label"] = x["_geo_label"].astype(str)

    # Small, precise points. The metric controls only a modest size range so a
    # large city/value can never cover half the map. Color communicates the
    # relative level at a glance: high / medium / low.
    if len(x) == 1:
        x["marker_size"] = 8
    else:
        ranks = x["_geo_metric"].rank(method="average", pct=True)
        x["marker_size"] = (5 + ranks * 6).clip(5, 11)
    x["nivel"] = _performance_class(x["_geo_metric"])
    x = x.sort_values("_geo_metric", ascending=False).reset_index(drop=True)

    # Labels are intentionally sparse; every point still exposes its complete
    # context on hover/click.
    x["label"] = ""
    n_labels = min(6, len(x))
    x.loc[:n_labels - 1, "label"] = x.loc[:n_labels - 1, "_geo_label"]

    center_lat = float(x["_geo_lat"].mean())
    center_lon = float(x["_geo_lon"].mean())
    lat_span = max(float(x["_geo_lat"].max() - x["_geo_lat"].min()), 0.15)
    lon_span = max(float(x["_geo_lon"].max() - x["_geo_lon"].min()), 0.15)
    span = max(lat_span, lon_span)
    zoom = 5.2
    if span < 0.5: zoom = 10.5
    elif span < 1.2: zoom = 9.0
    elif span < 3: zoom = 7.0
    elif span < 7: zoom = 5.5
    elif span < 15: zoom = 4.0
    else: zoom = 2.7

    if -5.5 <= center_lat <= 13.5 and -80.5 <= center_lon <= -66:
        center_lat, center_lon = 4.57, -74.30
        if span < 1.2: zoom = 7.2
        elif span < 4: zoom = 5.8
        else: zoom = 4.4

    hover = (
        "<b>%{customdata[0]}</b><br>"
        + (_label(summary.get("schema", {}), metric) if metric else "Registros")
        + ": <b>%{customdata[1]:,.0f}</b><br>"
        "Participación: <b>%{customdata[2]:.1f}%</b><br>"
        "Nivel: <b>%{customdata[3]}</b><br>"
        "Lat: %{lat:.5f} · Lon: %{lon:.5f}<extra>Haz clic para ver el detalle</extra>"
    )

    # --- PASO 2: COLORES DINÁMICOS SEGÚN EL TEMA ---
    is_dark = st.session_state.get("theme", "Oscuro") == "Oscuro"

    if is_dark:
    # Colores brillantes/neón para contrastar sobre el mapa oscuro
        color_map = {"Nivel alto": "#00E676", "Nivel medio": "#FFD600", "Nivel bajo": "#FF2A5F"}
    else:
    # Colores mate sobrios para el mapa claro
        color_map = {"Nivel alto": "#22A06B", "Nivel medio": "#F59E0B", "Nivel bajo": "#E05252"}
    fig = px.scatter_map(
        x, lat="_geo_lat", lon="_geo_lon", size="marker_size", size_max=11,
        text="label", color="nivel",
        color_discrete_map=color_map,
        category_orders={"nivel": ["Nivel alto", "Nivel medio", "Nivel bajo"]},
        zoom=zoom, center={"lat": center_lat, "lon": center_lon},
        map_style="carto-darkmatter" if st.session_state.get("theme", "Oscuro") == "Oscuro" else "carto-positron",
    )
    fig.update_traces(
        marker=dict(opacity=0.92),
        customdata=x[["_geo_label", "_geo_metric", "share_pct", "nivel"]].to_numpy(),
        hovertemplate=hover,
        textposition="top center",
        textfont=dict(size=10, color="#1A2233"),
    )
    fig.update_layout(
        height=590, margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, sans-serif", color="#1A2233"),
        dragmode="pan", clickmode="event+select",
        legend=dict(orientation="h", yanchor="bottom", y=0.01, xanchor="left", x=0.01,
                    bgcolor="#FFFFFF", bordercolor="#344153", borderwidth=1,
                    font=dict(size=10, color="#1A2233")),
    )
    fig = apply_dashboard_theme(fig)

    return fig


def _map_figure_3d(summary: dict, metric: str | None, schema: dict):
    """Mapa 3D estilo deck.gl: columnas que se elevan según el valor de cada
    ubicación. Usa un degradado frío→caliente (no solo tonos de rojo) para
    que se entienda de un vistazo qué punto es mejor y cuál es peor, con
    una leyenda visible debajo del mapa. No requiere API key de Mapbox (usa
    tiles de Carto, gratis). El clic-para-detalle sigue viviendo en el mapa
    clásico porque pydeck no ofrece ese mismo evento de selección en
    Streamlit todavía.
    """
    import pydeck as pdk

    table = summary.get("table")
    if table is None or table.empty:
        return None, None
    x = table.copy()
    for c in ("_geo_lat", "_geo_lon", "_geo_metric", "share_pct"):
        if c in x.columns:
            x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=["_geo_lat", "_geo_lon"]).copy()
    if x.empty:
        return None, None

    x["_geo_metric"] = x["_geo_metric"].fillna(0).clip(lower=0)
    x["_geo_label"] = x["_geo_label"].astype(str)
    min_val = float(x["_geo_metric"].min())
    max_val = float(x["_geo_metric"].max()) or 1.0

    # Degradado frío → caliente, en tonos neón vívidos (no colores apagados)
    # para que el mapa se sienta con más energía: cian brillante para lo
    # más bajo, ámbar en medio, rojo intenso para lo más alto.
    _LOW = (0, 224, 209)    # cian neón
    _MID = (255, 176, 32)   # ámbar vívido
    _HIGH = (255, 23, 68)   # rojo intenso (más vívido que el rojo de marca plano)

    def _color(v):
        span = (max_val - min_val) or 1.0
        ratio = min(max(((v - min_val) / span), 0.0), 1.0)
        if ratio < 0.5:
            t = ratio / 0.5
            r = int(_LOW[0] + (_MID[0] - _LOW[0]) * t)
            g = int(_LOW[1] + (_MID[1] - _LOW[1]) * t)
            b = int(_LOW[2] + (_MID[2] - _LOW[2]) * t)
        else:
            t = (ratio - 0.5) / 0.5
            r = int(_MID[0] + (_HIGH[0] - _MID[0]) * t)
            g = int(_MID[1] + (_HIGH[1] - _MID[1]) * t)
            b = int(_MID[2] + (_HIGH[2] - _MID[2]) * t)
        return [r, g, b, 225]

    x["color"] = x["_geo_metric"].apply(_color)
    x["glow_color"] = x["_geo_metric"].apply(lambda v: _color(v)[:3] + [70])
    x["glow_color_soft"] = x["_geo_metric"].apply(lambda v: _color(v)[:3] + [30])
    # La altura de cada columna es relativa al máximo, para que el mapa se
    # vea proporcionado sin importar la magnitud real de los números.
    x["elevation"] = (x["_geo_metric"] / max_val * 40000).clip(lower=500)
    base_radius = max(1200, 22000 / max(len(x), 1))
    x["halo_radius_1"] = base_radius * 2.6
    x["halo_radius_2"] = base_radius * 1.6
    metric_label = _label(schema, metric) if metric else "Registros"

    center_lat, center_lon = float(x["_geo_lat"].mean()), float(x["_geo_lon"].mean())
    lat_span = max(float(x["_geo_lat"].max() - x["_geo_lat"].min()), 0.15)
    lon_span = max(float(x["_geo_lon"].max() - x["_geo_lon"].min()), 0.15)
    span = max(lat_span, lon_span)
    zoom = 9.5
    if span >= 15: zoom = 3.2
    elif span >= 7: zoom = 4.3
    elif span >= 3: zoom = 5.8
    elif span >= 1.2: zoom = 7.2
    elif span >= 0.5: zoom = 8.5
    if -5.5 <= center_lat <= 13.5 and -80.5 <= center_lon <= -66:
        center_lat, center_lon = 4.57, -74.30
        zoom = 6.6 if span >= 3 else 7.8

    records = x.to_dict("records")

    # Dos capas de "halo" apiladas (una más ancha y tenue, otra más chica y
    # concentrada) debajo de cada columna — simulan el resplandor/glow que
    # una sola capa plana no logra, dándole ese aire "futurista" real.
    halo_outer = pdk.Layer(
        "ScatterplotLayer", data=records, get_position="[_geo_lon, _geo_lat]",
        get_radius="halo_radius_1", get_fill_color="glow_color_soft",
        stroked=False, filled=True, pickable=False,
    )
    halo_inner = pdk.Layer(
        "ScatterplotLayer", data=records, get_position="[_geo_lon, _geo_lat]",
        get_radius="halo_radius_2", get_fill_color="glow_color",
        stroked=False, filled=True, pickable=False,
    )
    layer = pdk.Layer(
        "ColumnLayer",
        data=records,
        get_position="[_geo_lon, _geo_lat]",
        get_elevation="elevation",
        elevation_scale=1,
        radius=base_radius,
        disk_resolution=6,  # columnas hexagonales: se ve más "data-viz", menos genérico
        get_fill_color="color",
        pickable=True,
        auto_highlight=True,
        highlight_color=[255, 255, 255, 160],
        material={"ambient": 0.4, "diffuse": 0.55, "shininess": 45, "specularColor": [255, 255, 255]},
    )
    view_state = pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom, pitch=55, bearing=18)
    tooltip = {
        "html": "<b>{_geo_label}</b><br/>" + metric_label + ": <b>{_geo_metric}</b>",
        "style": {"backgroundColor": "#171c29", "color": "#ffffff", "fontSize": "12px", "borderRadius": "8px", "padding": "8px 10px"},
    }
    # Mapa base oscuro (con calles/nombres visibles) para que el resplandor
    # de las columnas contraste de verdad — un mapa demasiado claro apaga el
    # efecto "glow"; uno completamente negro sin ninguna referencia se
    # sentía plano. CARTO_DARK es el punto medio: oscuro y con contexto.
    try:
        deck = pdk.Deck(
            layers=[halo_outer, halo_inner, layer], initial_view_state=view_state,
            map_style=pdk.map_styles.CARTO_DARK, map_provider="carto", tooltip=tooltip,
        )
    except Exception:
        try:
            deck = pdk.Deck(layers=[halo_outer, halo_inner, layer], initial_view_state=view_state, map_style="dark", map_provider="carto", tooltip=tooltip)
        except Exception:
            deck = pdk.Deck(layers=[layer], initial_view_state=view_state, tooltip=tooltip)

    legend = {
        "metric_label": metric_label,
        "min_label": _fmt(min_val),
        "max_label": _fmt(max_val),
        "low": _LOW, "mid": _MID, "high": _HIGH,
    }
    return deck, legend


def _selection_label(event, labels):
    """Recover the clicked map label even when Plotly split points into color traces."""
    try:
        selection = event.selection
    except Exception:
        try:
            selection = event.get("selection", {})
        except Exception:
            selection = {}

    # Preferred path: Streamlit/Plotly exposes selected points with customdata.
    try:
        points = selection.points
    except Exception:
        try:
            points = selection.get("points", [])
        except Exception:
            points = []
    for point in points or []:
        try:
            custom = point.customdata
        except Exception:
            try:
                custom = point.get("customdata")
            except Exception:
                custom = None
        if custom is not None:
            if isinstance(custom, (list, tuple)) and custom:
                return str(custom[0])
            if hasattr(custom, "__len__") and not isinstance(custom, str) and len(custom):
                return str(custom[0])
            return str(custom)

    # Fallback for older Streamlit event shapes. With multiple color traces, a
    # raw point index is only safe when there is one trace, so use it cautiously.
    try:
        indices = selection.point_indices
    except Exception:
        try:
            indices = selection.get("point_indices", [])
        except Exception:
            indices = []
    if indices:
        try:
            idx = int(indices[0])
            return labels.iloc[idx] if 0 <= idx < len(labels) else None
        except Exception:
            return None
    return None


def _geo_card(title, subtitle, fig, key):
    st.markdown(
        f'<div class="chart-card pbi-visual"><div class="chart-head">'
        f'<div class="chart-head-main"><span class="visual-type">VISUAL</span>'
        f'<div class="chart-title">{title}</div><div class="chart-subtitle">{subtitle}</div></div>'
        f'<span class="data-badge visual-badge">Datos de la zona</span></div>',
        unsafe_allow_html=True,
    )
    if fig is None:
        st.info("No hay datos suficientes para este análisis.")
    else:
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "responsive": True}, key=key)
    st.markdown('</div>', unsafe_allow_html=True)


def _geo_semantic(schema, col):
    return next((x.get("semantic_type", "") for x in schema.get("semantic", {}).get("columns", []) if x.get("column") == col), "")


def _geo_business_dimension(rows, schema, person_col=None):
    sem_priority = {"product": 0, "category": 1, "channel": 2, "brand": 3, "segment": 4}
    candidates = []
    for item in schema.get("semantic", {}).get("columns", []):
        c, t = item.get("column"), item.get("semantic_type", "")
        if c in rows.columns and c != person_col and t in sem_priority:
            nun = rows[c].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()
            if 1 < nun <= 30:
                candidates.append((sem_priority[t], c))
    if candidates:
        return sorted(candidates)[0][1]
    for c in schema.get("categorical", []):
        if c in rows.columns and c != person_col and not str(c).startswith("__"):
            nun = rows[c].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()
            if 1 < nun <= 20:
                return c
    return None


def _detail_panel(enriched: pd.DataFrame, summary: dict, label: str, schema: dict, metric: str | None):
    if not label:
        return
    meta = summary.get("meta", {})
    label_col = meta.get("city_column") or meta.get("dimension")
    geo_label = enriched.get("_geo_label", pd.Series(index=enriched.index, dtype=str)).astype(str).str.strip()
    if label_col and label_col in enriched.columns:
        mask = enriched[label_col].astype(str).str.strip().eq(str(label).strip()) | geo_label.eq(str(label).strip())
    else:
        mask = geo_label.eq(str(label).strip())
    rows = enriched[mask & (enriched["_geo_status"] == "ok")].copy()
    if rows.empty:
        st.info("No encontramos registros asociados a ese punto.")
        return

    st.markdown(f"### 📍 {label}")
    person_col = _person_column(rows, schema)
    metric_value = None
    if metric and metric in rows.columns:
        vals = pd.to_numeric(rows[metric], errors="coerce").dropna()
        sem = _geo_semantic(schema, metric)
        additive = sem in {"revenue", "profit", "cost", "quantity", "discount", "tax"}
        metric_value = float(vals.sum()) if additive else float(vals.mean()) if len(vals) else None

    # KPI row: answer the questions users actually need first.
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Registros", f"{len(rows):,}")
    c2.metric(_label(schema, metric) if metric else "Valor", _fmt(metric_value) if metric_value is not None else "—")
    c3.metric("Personas / agentes", f"{rows[person_col].nunique():,}" if person_col and person_col in rows.columns else "—")

    # Benchmark against the other geographic groups.
    benchmark = None
    zone_total = metric_value
    if metric and metric in enriched.columns:
        valid = enriched[enriched["_geo_status"] == "ok"].copy()
        valid["_geo_metric"] = pd.to_numeric(valid[metric], errors="coerce").fillna(0)
        by_zone = valid.groupby("_geo_label")["_geo_metric"].sum().sort_values(ascending=False)
        others = by_zone.drop(index=label, errors="ignore")
        if len(others):
            benchmark = float(others.mean())
    if benchmark is not None and zone_total is not None:
        diff_pct = ((zone_total - benchmark) / abs(benchmark) * 100) if benchmark else None
        c4.metric("Vs. otras zonas", _fmt(zone_total - benchmark), f"{diff_pct:+.1f}%" if diff_pct is not None else "—")
    else:
        c4.metric("Vs. otras zonas", "—")

    # 1) Zone vs benchmark: grouped bars answer "¿le fue mejor o peor?".
    if metric and metric in enriched.columns:
        valid = enriched[enriched["_geo_status"] == "ok"].copy()
        valid["_geo_metric"] = pd.to_numeric(valid[metric], errors="coerce").fillna(0)
        by_zone = valid.groupby("_geo_label", as_index=False)["_geo_metric"].sum().sort_values("_geo_metric", ascending=False)
        others = by_zone.loc[by_zone["_geo_label"].astype(str) != str(label), "_geo_metric"]
        if not others.empty:
            other_avg = float(others.mean())
            comp = pd.DataFrame({"Referencia": [str(label), "Promedio otras zonas"], "Valor": [float(zone_total or 0), other_avg]})
            fig = px.bar(comp, x="Referencia", y="Valor", color="Referencia", text_auto=".3s",
                         color_discrete_sequence=["#E4002B", "#7D8794"])
            fig.update_layout(height=320, margin=dict(l=10,r=10,t=10,b=10), showlegend=False,
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#1A2233"))
            fig.update_yaxes(title=_label(schema, metric), showgrid=True, gridcolor="rgba(96,112,132,.16)")
            # Visual comparativo: barras limpias y colores semánticos.
            fig.update_traces(marker_line_width=0)
            _geo_card("Zona vs. promedio de otras zonas", f"¿{label} está por encima o por debajo del resto?", fig, "geo_zone_benchmark_v45")

            # Participación: responde cuánto pesa realmente la zona dentro del total.
            zone_abs = float(zone_total or 0)
            other_total = float(others.sum())
            if zone_abs + other_total > 0:
                share_df = pd.DataFrame({"Parte": [str(label), "Resto de zonas"], "Valor": [zone_abs, other_total]})
                share_fig = go.Figure(go.Pie(
                    labels=share_df["Parte"], values=share_df["Valor"], hole=.72,
                    marker=dict(colors=["#E4002B", "#3A4655"], line=dict(color="#FFFFFF", width=2)),
                    textinfo="percent",
                    hovertemplate="<b>%{label}</b><br>Valor: %{value:,.0f}<br>Participación: %{percent}<extra></extra>",
                ))
                share_fig.add_annotation(text=f"<b>{zone_abs/(zone_abs+other_total)*100:.1f}%</b><br><span style='font-size:10px'>participación</span>",
                                          x=.5,y=.5,showarrow=False,font=dict(size=17,color="#1A2233"))
                share_fig.update_layout(height=300, margin=dict(l=10,r=10,t=8,b=8), showlegend=True,
                                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                        font=dict(color="#1A2233"), legend=dict(orientation="h",y=-.05,x=.1))
                _geo_card("Peso de la zona", f"Qué porcentaje del resultado total representa {label}", share_fig, "geo_zone_share_v45")

    # 2) Evolution of the selected zone.
    date_cols = [c for c in schema.get("dates", []) if c in rows.columns]
    if metric and metric in rows.columns and date_cols:
        d = date_cols[0]
        tmp = rows[[d, metric]].copy()
        tmp[d] = pd.to_datetime(tmp[d], errors="coerce")
        tmp[metric] = pd.to_numeric(tmp[metric], errors="coerce")
        tmp = tmp.dropna().sort_values(d)
        if not tmp.empty:
            tmp["_period"] = tmp[d].dt.to_period("M").dt.start_time
            sem = _geo_semantic(schema, metric)
            if sem in {"revenue", "profit", "cost", "quantity", "discount", "tax"}:
                trend_df = tmp.groupby("_period", as_index=False)[metric].sum()
            else:
                trend_df = tmp.groupby("_period", as_index=False)[metric].mean()
            if len(trend_df) >= 2:
                fig = go.Figure(go.Scatter(x=trend_df["_period"], y=trend_df[metric], mode="lines+markers",
                    line=dict(color="#22C7B4", width=3, shape="spline"), marker=dict(size=7),
                    hovertemplate="%{x|%b %Y}<br>" + _label(schema, metric) + ": <b>%{y:,.0f}</b><extra></extra>"))
                fig.update_layout(height=320, margin=dict(l=10,r=10,t=10,b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#1A2233"))
                fig.update_yaxes(showgrid=True, gridcolor="rgba(96,112,132,.16)"); fig.update_xaxes(showgrid=False)
                _geo_card("Evolución de la zona", f"Cómo se comportó {_label(schema, metric).lower()} en {label}", fig, "geo_zone_trend_v45")

    # 3) Agent/person ranking inside the selected zone.
    if person_col and person_col in rows.columns and metric and metric in rows.columns:
        agents = rows[[person_col, metric]].copy()
        agents[person_col] = agents[person_col].map(_safe_name)
        agents[metric] = pd.to_numeric(agents[metric], errors="coerce")
        agents = agents.dropna(subset=[metric])
        sem = _geo_semantic(schema, metric)
        agg = agents.groupby(person_col)[metric].sum() if sem in {"revenue", "profit", "cost", "quantity", "discount", "tax"} else agents.groupby(person_col)[metric].mean()
        agent_df = agg.sort_values(ascending=False).head(12).reset_index()
        if not agent_df.empty:
            agent_df["nivel"] = agent_df[metric].apply(lambda v: "Sobre promedio zona" if v >= float(agg.mean()) else "Bajo promedio zona")
            fig = px.bar(agent_df.sort_values(metric), x=metric, y=person_col, orientation="h", color="nivel", text_auto=".3s",
                         color_discrete_map={"Sobre promedio zona":"#22C7B4", "Bajo promedio zona":"#E05252"})
            fig.update_traces(marker_line_width=0)
            fig.update_layout(height=max(360, 35*len(agent_df)+100), margin=dict(l=10,r=35,t=10,b=10),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#1A2233"),
                              legend=dict(orientation="h", y=1.05, x=0))
            fig.update_xaxes(title=_label(schema, metric), showgrid=True, gridcolor="rgba(96,112,132,.16)"); fig.update_yaxes(title=None)
            _geo_card("Rendimiento de agentes", f"Quién está por encima o por debajo del promedio de la zona · {label}", fig, "geo_agents_v45")

    # 4) Product/category mix: useful for understanding what is driving the zone.
    dim_col = _geo_business_dimension(rows, schema, person_col)
    if dim_col:
        z = rows[[dim_col] + ([metric] if metric and metric in rows.columns else [])].copy()
        z[dim_col] = z[dim_col].fillna("Sin dato").astype(str).str.strip().replace("", "Sin dato")
        if metric and metric in z.columns:
            z[metric] = pd.to_numeric(z[metric], errors="coerce")
            z = z.dropna(subset=[metric])
            sem = _geo_semantic(schema, metric)
            agg = z.groupby(dim_col)[metric].sum() if sem in {"revenue", "profit", "cost", "quantity", "discount", "tax"} else z.groupby(dim_col)[metric].mean()
            mix = agg.sort_values(ascending=False).head(10).reset_index()
            val_col = metric
        else:
            mix = z[dim_col].value_counts().head(10).rename("Registros").reset_index()
            mix.columns = [dim_col, "Registros"]
            val_col = "Registros"
        if not mix.empty:
            fig = px.bar(mix.sort_values(val_col), x=val_col, y=dim_col, orientation="h", text_auto=".3s")
            fig.update_traces(marker_color="#A67CFF", marker_line_width=0)
            fig.update_layout(height=max(340, 34*len(mix)+100), margin=dict(l=10,r=35,t=10,b=10), showlegend=False,
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#1A2233"))
            fig.update_xaxes(title=_label(schema, val_col) if val_col in rows.columns else "Registros", showgrid=True, gridcolor="rgba(96,112,132,.16)"); fig.update_yaxes(title=None)
            _geo_card(f"Qué mueve la zona: {_label(schema, dim_col)}", f"Top elementos que explican el resultado de {label}", fig, "geo_zone_mix_v45")

    # Keep the raw detail available, but place it after the analytical visuals.
    with st.expander("Ver registros de la zona", expanded=False):
        display_cols = [c for c in rows.columns if not str(c).startswith("_geo_") and not str(c).startswith("__")]
        st.dataframe(rows[display_cols].head(100), use_container_width=True, hide_index=True)
        if len(rows) > 100:
            st.caption(f"Mostrando 100 de {len(rows):,} registros de esta ubicación.")


def render_georeferencing(df: pd.DataFrame, schema: dict):
    """Interactive geographic workspace: map first, then automatic detail."""
    st.markdown(
        '<div class="section-intro"><div><span class="eyebrow">UBICACIÓN</span>'
        '<h2>Georeferenciación</h2></div>'
        '<span class="data-badge">Mapa interactivo</span></div>',
        unsafe_allow_html=True,
    )
    st.caption("Haz clic en un punto para abrir toda la información relacionada con esa ubicación.")

    metrics = metric_candidates(df, schema)
    metric = st.selectbox(
        "Métrica del mapa",
        [None] + metrics,
        format_func=lambda x: "Número de registros" if x is None else _label(schema, x),
        key="geo_metric_selector_v43",
    )
    summary = geographic_summary(df, schema, metric)
    summary["schema"] = schema
    meta = summary.get("meta", {})
    table = summary.get("table")
    if table is None or table.empty:
        reason = meta.get("reason", "No se detectaron coordenadas, ciudad, región o país utilizables.")
        st.info(f"No hay ubicaciones suficientes para construir el mapa. {reason}")
        return

    enriched = summary.get("data", pd.DataFrame())
    labels = table.sort_values("_geo_metric", ascending=False).reset_index(drop=True)["_geo_label"].astype(str)

    map_mode = st.radio(
        "Estilo de mapa", ["🗺️ Clásico", "🌐 3D"], horizontal=True,
        key="geo_map_mode_v60",
        help="El mapa 3D es más vistoso; el clásico permite hacer clic en un punto para ver su detalle completo abajo.",
    )

    if map_mode == "🌐 3D":
        try:
            deck, legend = _map_figure_3d(summary, metric, schema)
        except Exception as exc:
            deck, legend = None, None
            st.warning(f"No se pudo construir el mapa 3D ({exc}); mostrando el mapa clásico.")
            map_mode = "🗺️ Clásico"
        if deck is not None:
            st.pydeck_chart(deck, use_container_width=True, height=560)
            if legend:
                low, mid, high = legend["low"], legend["mid"], legend["high"]
                grad = f"rgb{low}, rgb{mid}, rgb{high}"
                st.markdown(
                    f'''<div style="display:flex;align-items:center;gap:10px;margin-top:8px;padding:10px 14px;
                    background:var(--panel-2);border:1px solid var(--line);border-radius:10px;font-size:12px;color:var(--muted)">
                    <span style="font-weight:700;color:var(--text)">{legend["metric_label"]}:</span>
                    <span>{legend["min_label"]}</span>
                    <div style="flex:1;height:10px;border-radius:999px;background:linear-gradient(90deg,{grad})"></div>
                    <span>{legend["max_label"]}</span>
                    <span style="color:var(--muted);margin-left:6px;">← menor &nbsp;&nbsp; mayor →</span>
                    </div>''',
                    unsafe_allow_html=True,
                )
            st.caption("Arrastra para rotar, rueda del mouse para acercar/alejar. Para ver el detalle de una zona, cambia a \"🗺️ Clásico\" y haz clic sobre el punto.")

    fig = None
    if map_mode == "🗺️ Clásico":
        fig = _map_figure(summary, metric)
        if fig is None:
            st.info("No se pudo construir el mapa con las ubicaciones disponibles.")
            return

    selected = st.session_state.get("geo_selected_location_v43")
    if selected and selected not in set(labels):
        st.session_state.geo_selected_location_v43 = None
        selected = None

    if fig is not None:
        event = st.plotly_chart(
            fig,
            use_container_width=True,
            config={"displayModeBar": True, "scrollZoom": True, "displaylogo": False},
            key="geo_interactive_map_v43",
            on_select="rerun",
            selection_mode=["points"],
        )
        clicked = _selection_label(event, labels)
        if clicked:
            st.session_state.geo_selected_location_v43 = str(clicked)
            selected = str(clicked)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Ubicaciones", f"{len(table):,}")
    k2.metric("Ubicación líder", str(table.iloc[0]["_geo_label"]))
    k3.metric("Valor líder", _fmt(table.iloc[0]["_geo_metric"]))
    k4.metric("Puntos sin resolver", f"{sum(meta.get(k, 0) for k in ('unresolved_places','ambiguous_places')):,}")

    # Zone-vs-zone analysis: a direct decision visual, not just a map.
    if len(labels) >= 2 and metric and metric in table.columns:
        st.markdown("### ⚔️ Comparar dos zonas")
        z1, z2 = st.columns(2)
        with z1:
            zone_a = st.selectbox("Zona A", labels.tolist(), key="geo_zone_a_v52")
        with z2:
            zone_b_options = [x for x in labels.tolist() if x != zone_a] or labels.tolist()
            zone_b = st.selectbox("Zona B", zone_b_options, key="geo_zone_b_v52")
        va = float(table.loc[table["_geo_label"].astype(str).eq(str(zone_a)), "_geo_metric"].iloc[0])
        vb = float(table.loc[table["_geo_label"].astype(str).eq(str(zone_b)), "_geo_metric"].iloc[0])
        delta = va - vb
        pct = (delta / abs(vb) * 100) if vb else None
        a,b,c = st.columns(3)
        a.metric(str(zone_a), _fmt(va))
        b.metric(str(zone_b), _fmt(vb))
        c.metric("Diferencia A vs B", _fmt(delta), f"{pct:+.1f}%" if pct is not None else None)
        comp = pd.DataFrame({"Zona": [str(zone_a), str(zone_b)], "Valor": [va, vb]})
        fig_cmp = px.bar(comp, x="Zona", y="Valor", color="Zona", text_auto=".3s", color_discrete_sequence=["#E4002B", "#0FA8A0"])
        fig_cmp.update_layout(height=330, margin=dict(l=10,r=10,t=10,b=20), showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#1A2233"))
        fig_cmp.update_yaxes(title=_label(schema, metric), showgrid=True, gridcolor="rgba(96,112,132,.16)")
        _geo_card("Comparación directa de zonas", f"¿Cuál de las dos zonas tiene mejor resultado en {_label(schema, metric).lower()}?", fig_cmp, "geo_zone_compare_v52")

    if selected:
        _detail_panel(enriched, summary, selected, schema, metric)
    else:
        st.info("Selecciona un punto del mapa para ver sus datos, indicadores, categorías relacionadas y registros.")
