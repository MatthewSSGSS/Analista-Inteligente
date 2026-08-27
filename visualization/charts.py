import pandas as pd
from core.numeric import numeric_series
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

# Paleta ejecutiva alineada a la identidad de marca de Claro (rojo vivo +
# blanco). Los colores adicionales se usan solo cuando comunican una
# diferencia real (positivo/negativo/alerta), nunca de forma decorativa.
PRIMARY = "#E4002B"
PRIMARY_DARK = "#A80E1F"
TEAL = "#10B9A6"
GREEN = "#22A06B"
AMBER = "#F59E0B"
RED = "#E05252"
PURPLE = "#7C6FE8"
ORANGE = "#F97316"
TEXT = "#1A2233"
MUTED = "#5B6473"
GRID = "#E2E6ED"
CATEGORY_PALETTE = [PRIMARY, TEAL, PURPLE, AMBER, GREEN, ORANGE, "#334155", "#64748B", "#0EA5E9", "#8B5CF6"]

CONCEPT_LABELS = {
    "revenue": "Ingresos", "profit": "Beneficio", "cost": "Costos", "price": "Precio",
    "quantity": "Cantidad", "discount": "Descuento", "tax": "Impuestos", "percentage": "%",
    "rating": "Puntuación", "age": "Edad", "product": "Producto", "category": "Categoría",
    "region": "Región", "country": "País", "city": "Ciudad", "brand": "Marca",
    "customer": "Cliente", "employee": "Empleado", "gender": "Género", "status": "Estado",
}

MONTHS = {1:"Ene",2:"Feb",3:"Mar",4:"Abr",5:"May",6:"Jun",7:"Jul",8:"Ago",9:"Sep",10:"Oct",11:"Nov",12:"Dic"}

_MONTH_ALIASES = {
    "enero":1,"ene":1,"january":1,"jan":1,
    "febrero":2,"feb":2,"february":2,
    "marzo":3,"mar":3,"march":3,
    "abril":4,"abr":4,"april":4,"apr":4,
    "mayo":5,"may":5,
    "junio":6,"jun":6,"june":6,
    "julio":7,"jul":7,"july":7,
    "agosto":8,"ago":8,"august":8,"aug":8,
    "septiembre":9,"setiembre":9,"sep":9,"sept":9,"september":9,
    "octubre":10,"oct":10,"october":10,
    "noviembre":11,"nov":11,"november":11,
    "diciembre":12,"dic":12,"december":12,"dec":12,
}

def month_columns(df):
    """Detecta columnas cuyos encabezados son meses."""
    found=[]
    for c in df.columns:
        key=str(c).strip().lower().replace(".","")
        if key in _MONTH_ALIASES:
            found.append((_MONTH_ALIASES[key],c))
    return sorted(found,key=lambda x:x[0])

def _unique_display_labels(schema, columns):
    labels=[]
    used={}
    for c in columns:
        base=_label(schema,c)
        used[base]=used.get(base,0)+1
        labels.append(base if used[base]==1 else f"{base} · {c}")
    return labels

def wide_month_chart(df, schema):
    """Grafica estructuras donde los meses están distribuidos en columnas."""
    months=month_columns(df)
    if len(months)<2:
        return None
    month_cols=[c for _,c in months]
    candidates=[c for c in dimension_candidates(df,schema) if c not in month_cols]
    label_col=None
    for c in candidates:
        n=df[c].dropna().astype(str).nunique()
        if 2<=n<=8:
            label_col=c
            break
    fig=go.Figure()
    if label_col:
        labels=df[label_col].fillna("Sin categoría").astype(str)
        for i,value in enumerate(list(dict.fromkeys(labels.tolist()))[:8]):
            row=df[labels==value]
            vals=[float(numeric_series(row[c]).sum()) for c in month_cols]
            color=CATEGORY_PALETTE[i%len(CATEGORY_PALETTE)]
            fig.add_trace(go.Scatter(
                x=[MONTHS[n] for n,_ in months], y=vals, mode="lines+markers",
                name=value, line=dict(color=color,width=3,shape="linear"),
                marker=dict(size=7,color=color),
                hovertemplate=f"<b>%{{x}}</b><br>{_label(schema,label_col)}: <b>{value}</b><br>Valor: <b>%{{y:,.0f}}</b><extra></extra>"
            ))
        subtitle=f"Comparación mensual por {_label(schema,label_col).lower()}"
    else:
        vals=[float(numeric_series(df[c]).sum()) for c in month_cols]
        fig.add_trace(go.Scatter(
            x=[MONTHS[n] for n,_ in months], y=vals, mode="lines+markers",
            name="Total", line=dict(color=PRIMARY,width=3.5,shape="linear"),
            marker=dict(size=7,color="#FFFFFF",line=dict(width=2.5,color=PRIMARY)),
            fill="tozeroy",fillcolor="rgba(47,128,237,.10)",
            hovertemplate="<b>%{x}</b><br>Valor: <b>%{y:,.0f}</b><extra></extra>"
        ))
        subtitle="Evolución mensual agregada"
    fig.update_xaxes(categoryorder="array",categoryarray=[MONTHS[n] for n,_ in months],title=None)
    fig.update_yaxes(tickformat="~s",title=None)
    fig.update_layout(showlegend=bool(label_col),legend=dict(orientation="h",y=1.03,x=0,font=dict(size=10)))
    return _base(fig,380,show_xgrid=False),subtitle


def _base(fig, height=350, show_xgrid=False):
    """Estilo común: limpio, aireado, jerarquía visual y hover consistente."""
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, sans-serif", color=TEXT, size=12),
        margin=dict(l=10, r=18, t=24, b=24), height=height,
        hoverlabel=dict(bgcolor="#FFFFFF", font=dict(color="#1A2233", size=12), bordercolor="#D7DCE6"),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
            font=dict(size=10, color=MUTED), bgcolor="rgba(0,0,0,0)",
            itemclick="toggleothers", itemdoubleclick="toggle",
            tracegroupgap=8,
        ),
        hovermode="x unified",
        dragmode=False,
        colorway=CATEGORY_PALETTE,
        uniformtext=dict(minsize=9, mode="hide"),
    )
    fig.update_xaxes(
        showgrid=show_xgrid, gridcolor="rgba(96,112,132,.12)", zeroline=False,
        showline=False, tickfont=dict(color=MUTED, size=10.5), ticks="",
        automargin=True,
        title_font=dict(color="#475467", size=11),
    )
    fig.update_yaxes(
        showgrid=True, gridcolor="rgba(96,112,132,.16)", gridwidth=1, zeroline=False,
        showline=False, tickfont=dict(color=MUTED, size=10.5), ticks="",
        automargin=True,
        title_font=dict(color="#475467", size=11),
    )
    return fig


def _clean_label(value):
    return "Sin categoría" if pd.isna(value) or str(value).strip() == "" else str(value)


def _semantic_items(schema):
    return schema.get("semantic", {}).get("columns", [])


def _concept_for(schema, column):
    for x in _semantic_items(schema):
        if x.get("column") == column:
            return x.get("semantic_type", "unknown")
    return "unknown"


def _label(schema, column):
    concept = _concept_for(schema, column)
    return CONCEPT_LABELS.get(concept, str(column))


def _is_month_number(df, col):
    if col not in df.columns:
        return False
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    if s.empty:
        return False
    name = str(col).lower()
    return ("mes" in name or "month" in name) and bool(((s >= 1) & (s <= 12)).mean() >= .95) and bool((s % 1 == 0).mean() >= .95)


def _number_format(values):
    vals = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    if vals.empty:
        return ",.0f"
    max_abs = vals.abs().max()
    if max_abs >= 1_000_000:
        return ",.1f"
    if max_abs >= 1_000:
        return ",.0f"
    return ",.2f"


def _compact_number(v):
    try:
        v = float(v)
    except Exception:
        return str(v)
    a = abs(v)
    if a >= 1_000_000_000:
        return f"{v/1_000_000_000:.1f}B"
    if a >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if a >= 1_000:
        return f"{v/1_000:.1f}K"
    return f"{v:,.0f}"


def _periodize(df, date_col, grain):
    x = df[[date_col]].copy()
    x[date_col] = pd.to_datetime(x[date_col], errors="coerce")
    x = x.dropna()
    if grain == "Día":
        x["_period"] = x[date_col].dt.floor("D")
    elif grain == "Semana":
        x["_period"] = x[date_col].dt.to_period("W").dt.start_time
    elif grain == "Trimestre":
        x["_period"] = x[date_col].dt.to_period("Q").dt.start_time
    elif grain == "Año":
        x["_period"] = x[date_col].dt.to_period("Y").dt.start_time
    else:
        x["_period"] = x[date_col].dt.to_period("M").dt.start_time
    return x


def metric_candidates(df, schema):
    raw = schema.get("semantic", {}).get("metrics") or schema.get("metrics", [])
    out = []
    dates = set(schema.get("dates", []))
    ids = set(schema.get("ids", []))
    for c in raw:
        if c not in df.columns or c in dates or c in ids or _is_month_number(df, c) or any(c == mc for _, mc in month_columns(df)):
            continue
        s = pd.to_numeric(df[c], errors="coerce")
        if s.notna().sum() == 0:
            continue
        unique = s.dropna().nunique()
        if unique <= 12 and pd.api.types.is_integer_dtype(s) and _concept_for(schema, c) in {"unknown", "id"}:
            continue
        out.append(c)
    priority = {"revenue": 0, "profit": 1, "quantity": 2, "price": 3, "cost": 4,
                "discount": 5, "tax": 6, "percentage": 7, "rating": 8, "age": 9}
    return sorted(out, key=lambda c: priority.get(_concept_for(schema, c), 50))


def dimension_candidates(df, schema):
    # Unión, no "o": las columnas que el motor semántico reconoce con
    # confianza van primero (mejor etiqueta), pero cualquier otra columna
    # categórica que no encaje en un concepto de negocio conocido (por
    # ejemplo, un nombre de columna ambiguo que no calzó con ningún
    # concepto) sigue apareciendo como filtro con su nombre original, en
    # vez de desaparecer silenciosamente del selector.
    semantic_dims = schema.get("semantic", {}).get("dimensions") or []
    fallback_dims = schema.get("categorical", [])
    dates = set(schema.get("dates", []))
    ids = set(schema.get("ids", []))
    out = []

    # Nombre completo es un campo analítico sintético creado por el detector
    # de esquema cuando el Excel separa Nombre/Apellido 1/Apellido 2.
    # El motor semántico puede no clasificar ese campo como dimensión, así que
    # debe entrar explícitamente en las dimensiones disponibles.
    full_name = (schema.get("full_name") or {}).get("column") if isinstance(schema.get("full_name"), dict) else None
    if full_name and full_name in df.columns:
        out.append(full_name)

    month_headers = {
        "enero","ene","january","jan","febrero","feb","february","marzo","mar","march",
        "abril","abr","april","mayo","may","junio","jun","june","julio","jul","july",
        "agosto","ago","august","aug","septiembre","setiembre","sep","sept","september",
        "octubre","oct","october","noviembre","nov","november","diciembre","dic","december","dec"
    }

    def _eligible(c):
        header_key = str(c).strip().lower().replace(".", "")
        return c in df.columns and c not in dates and c not in ids and c not in out and header_key not in month_headers

    for c in semantic_dims:
        if _eligible(c):
            out.append(c)
    for c in fallback_dims:
        if _eligible(c) and not pd.api.types.is_numeric_dtype(df[c]):
            out.append(c)
    return out



def adaptive_chart_specs(df, schema):
    """Return chart specs that are actually supported by the current sheet.

    The dashboard uses this to avoid leaving useful data without a visual just
    because a particular Excel has a different structure.
    """
    metrics = metric_candidates(df, schema)
    dims = dimension_candidates(df, schema)
    dates = [d for d in schema.get("dates", []) if d in df.columns]
    specs = []
    if dates and metrics:
        specs.append(("Evolución del indicador", "Cómo cambia el resultado en el tiempo", "trend"))
        if len(metrics) >= 2:
            specs.append(("Comparación de indicadores", "Dos métricas sobre el mismo periodo para ver brechas y evolución", "multi_trend"))
    if dims and metrics:
        specs.append(("Distribución por categoría", "Dónde se concentra el resultado", "donut"))
        specs.append(("Ranking de resultados", "Qué categorías lideran y cuáles quedan atrás", "ranking"))
    if len(metrics) >= 2:
        specs.append(("Relación entre indicadores", "Si dos variables se mueven juntas o en sentidos opuestos", "scatter"))
    if metrics:
        specs.append(("Distribución de valores", "Cómo se reparten los valores", "histogram"))
    return specs


def multi_trend(df, schema, metrics=None, grain="Mes", agg="Suma"):
    dates = [d for d in schema.get("dates", []) if d in df.columns]
    metrics = [m for m in (metrics or metric_candidates(df, schema)) if m in df.columns][:3]
    if not dates or len(metrics) < 2:
        return None
    d = dates[0]
    x = df[[d] + metrics].copy()
    x[d] = pd.to_datetime(x[d], errors="coerce")
    for m in metrics:
        x[m] = numeric_series(x[m])
    x = x.dropna(subset=[d])
    if x.empty:
        return None
    p = _periodize(x, d, grain)
    x = x.loc[p.index].copy(); x["_period"] = p["_period"]
    if agg == "Promedio":
        y = x.groupby("_period")[metrics].mean().reset_index()
    elif agg == "Máximo":
        y = x.groupby("_period")[metrics].max().reset_index()
    elif agg == "Mínimo":
        y = x.groupby("_period")[metrics].min().reset_index()
    else:
        y = x.groupby("_period")[metrics].sum().reset_index()
    fig = go.Figure()
    for i,m in enumerate(metrics):
        color = CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)]
        fig.add_trace(go.Scatter(x=y["_period"], y=y[m], mode="lines+markers", name=_label(schema,m),
                                 line=dict(color=color,width=2.8,shape="linear"), marker=dict(size=6,color=color),
                                 hovertemplate=f"<b>%{{x|%b %Y}}</b><br>{_label(schema,m)}: <b>%{{y:,.0f}}</b><extra></extra>"))
    fig.update_xaxes(tickformat="%b %Y")
    fig.update_yaxes(tickformat="~s", title=None)
    return _base(fig, 370, show_xgrid=False)


def grouped_trend(df, schema, metric=None, dimension=None, grain="Mes", agg="Suma", top_n=6, selected_groups=None):
    """Evolución temporal desglosada por una dimensión categórica.

    Se usa cuando existe una fecha + una métrica + una dimensión con al menos
    dos categorías. La dimensión se limita a los principales grupos para que
    la lectura siga siendo clara; no se mezclan las categorías en una sola
    serie.
    """
    dates = [d for d in schema.get("dates", []) if d in df.columns]
    dims = dimension_candidates(df, schema)
    metrics = metric_candidates(df, schema)
    if not dates or not metrics or not dims:
        return None
    d = dates[0]
    m = metric or metrics[0]
    c = dimension if dimension in dims else dims[0]
    if any(x not in df.columns for x in [d, m, c]):
        return None

    x = df[[d, m, c]].copy()
    x[d] = pd.to_datetime(x[d], errors="coerce")
    x[m] = numeric_series(x[m])
    x[c] = x[c].map(_clean_label)
    x = x.dropna(subset=[d, m])
    if x.empty:
        return None

    # En la vista ejecutiva se eligen automáticamente los grupos más relevantes.
    # En la vista comparativa el usuario puede fijar exactamente qué categorías
    # quiere ver, evitando una gráfica saturada con decenas de líneas.
    if selected_groups:
        selected = {str(v) for v in selected_groups}
        x = x[x[c].astype(str).isin(selected)]
    else:
        if agg == "Promedio":
            totals = x.groupby(c)[m].mean().abs().sort_values(ascending=False)
        elif agg == "Máximo":
            totals = x.groupby(c)[m].max().abs().sort_values(ascending=False)
        elif agg == "Mínimo":
            totals = x.groupby(c)[m].min().abs().sort_values(ascending=False)
        else:
            totals = x.groupby(c)[m].sum().abs().sort_values(ascending=False)
        groups = list(totals.head(max(2, int(top_n))).index)
        x = x[x[c].isin(groups)]
    if x[c].nunique() < 2:
        return None

    p = _periodize(x, d, grain)
    x = x.loc[p.index].copy()
    x["_period"] = p["_period"]
    grouped = x.groupby(["_period", c], as_index=False)[m]
    if agg == "Promedio":
        y = grouped.mean()
    elif agg == "Máximo":
        y = grouped.max()
    elif agg == "Mínimo":
        y = grouped.min()
    else:
        y = grouped.sum()
    if y.empty:
        return None

    fig = go.Figure()
    labels = list(y[c].drop_duplicates())
    for i, group in enumerate(labels):
        z = y[y[c] == group].sort_values("_period")
        color = CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)]
        fig.add_trace(go.Scatter(
            x=z["_period"], y=z[m], mode="lines+markers", name=str(group),
            line=dict(color=color, width=3.0, shape="linear"),
            marker=dict(size=6, color=color, line=dict(width=1.5, color="#FFFFFF")),
            connectgaps=False,
            hovertemplate=(f"<b>%{{x|%b %Y}}</b><br>{_label(schema,c)}: "
                           f"<b>%{{fullData.name}}</b><br>{_label(schema,m)}: "
                           f"<b>%{{y:,.0f}}</b><extra></extra>"),
        ))

    fig.update_xaxes(tickformat="%b %Y" if grain != "Año" else "%Y")
    fig.update_yaxes(tickformat="~s", title=None)
    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(size=10, color=MUTED), bgcolor="rgba(0,0,0,0)"),
    )
    return _base(fig, 390, show_xgrid=False)

def trend(df, schema, metric=None, grain="Mes", agg="Suma", comparison=False):
    dates = schema.get("dates", [])
    metrics = metric_candidates(df, schema)
    if not dates or not metrics:
        return None
    d, m = dates[0], metric or metrics[0]
    if d not in df.columns or m not in df.columns:
        return None
    x = df[[d, m]].copy()
    x[d] = pd.to_datetime(x[d], errors="coerce")
    x[m] = numeric_series(x[m])
    x = x.dropna()
    if x.empty:
        return None
    p = _periodize(x, d, grain)
    x = x.loc[p.index].copy()
    x["_period"] = p["_period"]
    if agg == "Promedio":
        y = x.groupby("_period")[m].mean().reset_index(name="_value")
    elif agg == "Máximo":
        y = x.groupby("_period")[m].max().reset_index(name="_value")
    elif agg == "Mínimo":
        y = x.groupby("_period")[m].min().reset_index(name="_value")
    else:
        y = x.groupby("_period")[m].sum().reset_index(name="_value")
    if y.empty:
        return None
    y = y.sort_values("_period")
    fmt = _number_format(y["_value"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=y["_period"], y=y["_value"], mode="lines+markers", name=_label(schema, m),
        line=dict(color=PRIMARY, width=3.5, shape="linear"),
        marker=dict(size=7, color="#FFFFFF", line=dict(width=2.5, color=PRIMARY)),
        fill="tozeroy", fillcolor="rgba(47,128,237,0.10)",
        hovertemplate="<b>%{x|%b %Y}</b><br>" + _label(schema, m) + ": <b>%{y:" + fmt + "}</b><extra></extra>",
    ))
    if len(y) >= 2:
        last = y.iloc[-1]
        prev = y.iloc[-2]["_value"]
        delta = ((last["_value"] - prev) / abs(prev) * 100) if prev else np.nan
        if pd.notna(delta):
            color = GREEN if delta >= 0 else RED
            sign = "+" if delta >= 0 else ""
            fig.add_annotation(
                x=last["_period"], y=last["_value"], text=f"{sign}{delta:.1f}%",
                showarrow=True, arrowhead=2, ax=34, ay=-35,
                bgcolor="#FFFFFF", bordercolor=color, borderwidth=1,
                font=dict(color=color, size=11),
            )
    if comparison and len(y) >= 4:
        prev = y["_value"].shift(1)
        delta = ((y["_value"] - prev) / prev.abs().replace(0, np.nan) * 100)
        colors = [GREEN if v >= 0 else RED for v in delta.fillna(0)]
        fig.add_trace(go.Scatter(
            x=y["_period"], y=y["_value"], mode="markers", name="Cambio del periodo",
            marker=dict(size=10, color=colors, line=dict(width=1, color="#FFFFFF")),
            customdata=delta.fillna(0),
            hovertemplate="Cambio: <b>%{customdata:.1f}%</b><extra></extra>",
        ))
    if grain == "Año":
        fig.update_xaxes(tickformat="%Y")
    elif grain in {"Trimestre", "Semana", "Día"}:
        fig.update_xaxes(tickformat="%b %Y" if grain == "Trimestre" else "%d %b")
    else:
        fig.update_xaxes(tickformat="%b %Y")
    fig.update_yaxes(tickformat="~s", title=None)
    return _base(fig, 360, show_xgrid=False)


def ranking(df, schema, metric=None, dimension=None, top_n=10, agg="Suma"):
    dims = dimension_candidates(df, schema)
    metrics = metric_candidates(df, schema)
    if not dims or not metrics:
        return None
    c, m = dimension or dims[0], metric or metrics[0]
    if c not in df.columns or m not in df.columns:
        return None
    x = df[[c, m]].copy()
    x[m] = numeric_series(x[m])
    x = x.dropna(subset=[m])
    if x.empty:
        return None
    x[c] = x[c].map(_clean_label)
    grouped = x.groupby(c, as_index=False)[m]
    if agg == "Promedio":
        x = grouped.mean()
    elif agg == "Máximo":
        x = grouped.max()
    elif agg == "Mínimo":
        x = grouped.min()
    else:
        x = grouped.sum()
    x = x.sort_values(m, ascending=False).head(int(top_n)).sort_values(m, ascending=True)
    # Semáforo visual: líder, zona media y rezagado.
    colors = []
    n = len(x)
    for i in range(n):
        if n == 1:
            colors.append(PRIMARY)
        elif i == n - 1:
            colors.append(PRIMARY)
        elif i == 0:
            colors.append(RED)
        else:
            colors.append(TEAL)
    fmt = _number_format(x[m])
    fig = go.Figure(go.Bar(
        x=x[m], y=x[c], orientation="h", marker=dict(color=colors, line=dict(width=0)),
        text=[_compact_number(v) for v in x[m]], textposition="outside", cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>" + _label(schema, m) + ": <b>%{x:" + fmt + "}</b><extra></extra>",
    ))
    fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title=None, bargap=.26, uniformtext_minsize=9, uniformtext_mode="hide")
    fig.update_xaxes(tickformat="~s")
    return _base(fig, max(330, 34 * len(x) + 100), show_xgrid=True)


def donut(df, schema, metric=None, dimension=None, top_n=6):
    """Participación adaptativa: evita donas ilegibles cuando hay muchas categorías.

    Regla visual:
    - máximo 6 segmentos visibles + Resto;
    - si Resto domina claramente, se cambia a barras horizontales para que la
      participación siga siendo interpretable y no termine en etiquetas apiladas;
    - la dona no imprime porcentajes sobre cada segmento: la cifra se consulta
      en hover y la leyenda queda limpia.
    """
    dims = dimension_candidates(df, schema)
    metrics = metric_candidates(df, schema)
    if not dims or not metrics:
        return None
    c, m = dimension or dims[0], metric or metrics[0]
    x = df[[c, m]].copy()
    x[m] = numeric_series(x[m])
    x = x.dropna(subset=[m])
    if x.empty:
        return None
    x[c] = x[c].map(_clean_label)
    x = x.groupby(c, as_index=False)[m].sum().sort_values(m, ascending=False)
    x = x[x[m].abs() > 0].copy()
    if x.empty:
        return None

    total = float(x[m].sum())
    if total == 0:
        return None

    # Una dona con 10-20 nombres produce leyendas partidas y textos que se
    # pisan. La visualización ejecutiva muestra solo los principales.
    visible_n = min(6, max(3, int(top_n)))
    if len(x) > visible_n:
        other = float(x.iloc[visible_n:][m].sum())
        x = pd.concat([
            x.iloc[:visible_n],
            pd.DataFrame({c: ["Resto"], m: [other]})
        ], ignore_index=True)

    x["pct"] = x[m] / total * 100

    # Si la categoría agrupada domina, una dona deja de comunicar bien la
    # distribución. En ese caso, las barras responden mejor a "quién pesa más".
    rest_pct = float(x.loc[x[c].eq("Resto"), "pct"].iloc[0]) if (x[c] == "Resto").any() else 0.0
    if rest_pct >= 80 and len(x) > 2:
        # Incluimos explícitamente "Resto": ocultarlo haría parecer que los
        # pocos segmentos visibles representan todo el universo.
        bar = x.copy().sort_values(m, ascending=True)
        bar["pct"] = bar[m] / total * 100
        colors = [
            ("#98A2B3" if str(label) == "Resto" else CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)])
            for i, label in enumerate(bar[c])
        ]
        fig = go.Figure(go.Bar(
            x=bar[m], y=bar[c], orientation="h",
            marker=dict(color=colors, line=dict(width=0)),
            text=[f"{p:.1f}%" for p in bar["pct"]],
            textposition="outside", cliponaxis=False,
            customdata=bar[["pct"]].to_numpy(),
            hovertemplate=(
                "<b>%{y}</b><br>Valor: <b>%{x:,.0f}</b><br>"
                "Participación: <b>%{customdata[0]:.1f}%</b><extra></extra>"
            ),
        ))
        fig.update_layout(
            showlegend=False,
            xaxis_title=None,
            yaxis_title=None,
            bargap=.28,
            margin=dict(l=10, r=60, t=24, b=24),
        )
        fig.update_xaxes(tickformat="~s")
        return _base(fig, max(300, 48 * len(bar) + 95), show_xgrid=True)

    labels = x[c].astype(str).tolist()
    # La leyenda lleva el porcentaje para que el gráfico no tenga números
    # flotando encima de la dona.
    legend_labels = [f"{label} · {pct:.1f}%" for label, pct in zip(labels, x["pct"])]
    custom = list(zip(labels, x[m].tolist(), x["pct"].tolist()))
    fig = go.Figure(go.Pie(
        labels=legend_labels,
        values=x[m],
        hole=0.70,
        marker=dict(
            colors=CATEGORY_PALETTE[:len(x)],
            line=dict(color="#FFFFFF", width=2),
        ),
        textinfo="none",
        customdata=custom,
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Valor: %{customdata[1]:,.0f}<br>"
            "Participación: <b>%{customdata[2]:.1f}%</b><extra></extra>"
        ),
        sort=False,
    ))
    fig.add_annotation(
        text=f"<b>{_compact_number(total)}</b><br>"
             f"<span style='font-size:11px;color:{MUTED}'>Total</span>",
        x=.5, y=.5, showarrow=False,
        font=dict(size=18, color=TEXT),
    )
    fig.update_layout(
        showlegend=True,
        legend=dict(
            orientation="h",
            x=.5, y=-.03, xanchor="center", yanchor="top",
            font=dict(size=10, color=MUTED),
            bgcolor="rgba(0,0,0,0)",
            itemclick="toggleothers",
            itemdoubleclick="toggle",
            tracegroupgap=5,
        ),
        margin=dict(l=10, r=10, t=18, b=70),
    )
    return _base(fig, 410)

def histogram(df, schema, metric=None, bins=24):
    metrics = metric_candidates(df, schema)
    if not metrics:
        return None
    m = metric or metrics[0]
    x = numeric_series(df[m]).dropna()
    if x.empty:
        return None
    fig = px.histogram(x=x, nbins=int(bins))
    fig.update_traces(
        marker_color=PRIMARY, marker_line_color="#FFFFFF", marker_line_width=.7,
        hovertemplate="Intervalo: %{x}<br><b>%{y:,}</b> registros<extra></extra>",
    )
    fig.update_layout(showlegend=False, xaxis_title=_label(schema, m), yaxis_title="Registros", bargap=.10, uniformtext_minsize=9, uniformtext_mode="hide")
    return _base(fig, 350, show_xgrid=False)


def scatter(df, schema, x_metric=None, y_metric=None):
    metrics = metric_candidates(df, schema)
    if len(metrics) < 2:
        return None
    a, b = x_metric or metrics[0], y_metric or metrics[1]
    if a == b:
        return None
    x = df[[a, b]].copy()
    x[a] = pd.to_numeric(x[a], errors="coerce")
    x[b] = pd.to_numeric(x[b], errors="coerce")
    x = x.dropna().head(15000)
    if x.empty:
        return None
    if x[a].nunique(dropna=True) < 2 or x[b].nunique(dropna=True) < 2:
        return None
    corr = x[a].corr(x[b])
    fig = px.scatter(x, x=a, y=b)
    fig.update_traces(marker=dict(color=PRIMARY, size=7, opacity=.50, line=dict(width=1, color="#FFFFFF")))
    # Línea de tendencia calculada sin depender de librerías externas.
    if len(x) >= 3 and pd.notna(corr):
        coeff = np.polyfit(x[a], x[b], 1)
        xx = np.linspace(x[a].min(), x[a].max(), 80)
        yy = coeff[0] * xx + coeff[1]
        fig.add_trace(go.Scatter(x=xx, y=yy, mode="lines", name="Tendencia",
                                 line=dict(color=PURPLE, width=2.5, dash="dash"),
                                 hoverinfo="skip"))
    relation = "positiva" if corr > .15 else "negativa" if corr < -.15 else "débil"
    fig.add_annotation(x=.99, y=.99, xref="paper", yref="paper", xanchor="right", yanchor="top",
                       text=f"Relación: <b>{corr:.2f}</b> · {relation}", showarrow=False,
                       bgcolor="#FFFFFF", bordercolor=GRID, borderwidth=1,
                       font=dict(size=11, color=TEXT))
    fig.update_layout(showlegend=True, xaxis_title=_label(schema, a), yaxis_title=_label(schema, b))
    return _base(fig, 360, show_xgrid=True)


def correlation(df, schema, metrics=None):
    metrics = metrics or metric_candidates(df, schema)
    if len(metrics) < 3:
        return None
    x = df[metrics].apply(pd.to_numeric, errors="coerce")
    x = x.loc[:, x.nunique(dropna=True) >= 2]
    if x.shape[1] < 3:
        return None
    x = x.corr()
    labels = _unique_display_labels(schema, list(x.columns))
    fig = px.imshow(
        x, text_auto=".2f", aspect="auto", color_continuous_scale=[RED, "#FFFFFF", PRIMARY],
        zmin=-1, zmax=1, labels=dict(x="Indicador", y="Indicador", color="Relación"),
    )
    fig.update_xaxes(ticktext=labels, tickvals=list(range(len(labels))), tickangle=-35)
    fig.update_yaxes(ticktext=labels, tickvals=list(range(len(labels))))
    fig.update_traces(hovertemplate="%{x} · %{y}<br><b>%{z:.2f}</b><extra></extra>")
    fig.update_layout(coloraxis_colorbar=dict(title="Relación", thickness=12, len=.7), margin=dict(l=90, r=55, t=22, b=75))
    return _base(fig, max(380, 300 + 12 * len(labels)))


def geo(df, schema, metric=None):
    lat = next((x["column"] for x in _semantic_items(schema) if x.get("semantic_type") == "latitude" and x["column"] in df.columns), None)
    lon = next((x["column"] for x in _semantic_items(schema) if x.get("semantic_type") == "longitude" and x["column"] in df.columns), None)
    lat = lat or next((c for c in df.columns if str(c).lower() in {"lat", "latitude", "latitud"}), None)
    lon = lon or next((c for c in df.columns if str(c).lower() in {"lon", "lng", "longitude", "longitud"}), None)
    if not lat or not lon:
        return None
    metrics = metric_candidates(df, schema)
    m = metric or (metrics[0] if metrics else None)
    cols = [lat, lon] + ([m] if m else [])
    x = df[cols].copy().dropna().head(10000)
    if x.empty:
        return None
    if m:
        x[m] = numeric_series(x[m])
    fig = px.scatter_geo(x, lat=lat, lon=lon, size=m if m else None, projection="natural earth", size_max=32)
    fig.update_traces(marker=dict(color=TEAL, opacity=.72, line=dict(width=.7, color="#FFFFFF")))
    fig.update_geos(showland=True, landcolor="#E7EBF2", showocean=True, oceancolor="#EAF1FA",
                    showcountries=True, countrycolor="#AEB8C6", showlakes=True, lakecolor="#DCEBFA",
                    showcoastlines=True, coastlinecolor="#9AA6B5", bgcolor="#FFFFFF")
    return _base(fig, 380)


def geo_summary_map(summary: dict):
    """Mapa geográfico estable: puntos pequeños, zoom a los datos y sin burbujas gigantes."""
    table = summary.get("table") if isinstance(summary, dict) else None
    meta = (summary.get("meta") or {}) if isinstance(summary, dict) else {}
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
    x = x.sort_values("_geo_metric", ascending=False).reset_index(drop=True)

    # Importante: no usamos size=valor con Plotly. Esa escala puede convertir
    # una ciudad con un valor alto en una burbuja que tapa todo el mapa.
    # El tamaño aquí es deliberadamente pequeño y limitado.
    if len(x) == 1:
        x["_marker_size"] = 11
    else:
        ranks = x["_geo_metric"].rank(method="average", pct=True)
        x["_marker_size"] = (6 + ranks * 8).clip(6, 14)

    q1, q2 = x["_geo_metric"].quantile([0.33, 0.67]).tolist()
    if q1 == q2:
        x["_level"] = np.where(x["_geo_metric"] >= q2, "Nivel alto", "Nivel bajo")
    else:
        x["_level"] = np.where(x["_geo_metric"] >= q2, "Nivel alto", np.where(x["_geo_metric"] >= q1, "Nivel medio", "Nivel bajo"))
    x["_marker_color"] = x["_level"].map({"Nivel alto": GREEN, "Nivel medio": AMBER, "Nivel bajo": RED}).fillna(PRIMARY)

    # Solo mostramos etiquetas para las ubicaciones principales.
    x["_map_label"] = ""
    n_labels = min(6, len(x))
    x.loc[:n_labels - 1, "_map_label"] = x.loc[:n_labels - 1, "_geo_label"].astype(str)

    fig = go.Figure()
    fig.add_trace(go.Scattergeo(
        lat=x["_geo_lat"],
        lon=x["_geo_lon"],
        text=x["_map_label"],
        mode="markers+text",
        textposition="top center",
        textfont=dict(size=9, color="#1A2233"),
        customdata=x[["_geo_label", "_geo_metric", "share_pct", "_level"]].to_numpy(),
        marker=dict(
            size=x["_marker_size"],
            color=x["_marker_color"],
            opacity=.90,
            line=dict(width=.8, color="#FFFFFF"),
        ),
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Valor: <b>%{customdata[1]:,.0f}</b><br>"
            "Participación: <b>%{customdata[2]:.1f}%</b><br>"
            "Nivel: <b>%{customdata[3]}</b><extra></extra>"
        ),
        showlegend=False,
    ))

    lat_min, lat_max = float(x["_geo_lat"].min()), float(x["_geo_lat"].max())
    lon_min, lon_max = float(x["_geo_lon"].min()), float(x["_geo_lon"].max())
    lat_span = max(lat_max - lat_min, 0.25)
    lon_span = max(lon_max - lon_min, 0.25)
    span = max(lat_span, lon_span)
    center_lat = (lat_min + lat_max) / 2
    center_lon = (lon_min + lon_max) / 2

    # Para Colombia no dejamos que el auto-zoom se vaya a Centroamérica o al
    # continente entero. El nivel se calcula según la dispersión real.
    colombia = -5.5 <= center_lat <= 13.5 and -80.5 <= center_lon <= -66.0
    if colombia:
        center_lat, center_lon = 4.57, -74.30
        projection_scale = max(5.2, min(12.0, 8.5 / (span ** .35)))
        if span < 2.0:
            projection_scale = 8.5
        elif span < 5.0:
            projection_scale = 7.0
        else:
            projection_scale = 5.8
    else:
        projection_scale = max(2.8, min(9.0, 8.0 / (span ** .35)))

    fig.update_geos(
        projection_type="mercator",
        projection_scale=projection_scale,
        center=dict(lat=center_lat, lon=center_lon),
        showland=True,
        landcolor="#E7EBF2",
        showocean=True,
        oceancolor="#EAF1FA",
        showlakes=True,
        lakecolor="#DCEBFA",
        showcountries=True,
        countrycolor="#AEB8C6",
        countrywidth=.7,
        showcoastlines=True,
        coastlinecolor="#9AA6B5",
        showframe=False,
        bgcolor="#FFFFFF",
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=6, b=4),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=460,
    )
    return _base(fig, 460)


def period_compare_bar(df, schema, metric=None, dimension=None, grain="Mes", agg="Suma", top_n=10):
    """Barras apiladas: periodo anterior vs periodo actual por categoría.

    Responde una pregunta distinta a una línea: cuánto aporta cada categoría
    y cuánto de esa barra corresponde al periodo anterior o al actual.
    """
    dates = [d for d in schema.get("dates", []) if d in df.columns]
    if not dates or not metric or metric not in df.columns or not dimension or dimension not in df.columns:
        return None
    d = dates[0]
    x = df[[d, dimension, metric]].copy()
    x[d] = pd.to_datetime(x[d], errors="coerce")
    x[metric] = pd.to_numeric(x[metric], errors="coerce")
    x = x.dropna(subset=[d, dimension, metric])
    if x.empty:
        return None
    x[dimension] = x[dimension].astype(str).replace("", "Sin categoría")

    if grain == "Día": x["_period"] = x[d].dt.floor("D")
    elif grain == "Semana": x["_period"] = x[d].dt.to_period("W").dt.start_time
    elif grain == "Trimestre": x["_period"] = x[d].dt.to_period("Q").dt.start_time
    elif grain == "Año": x["_period"] = x[d].dt.to_period("Y").dt.start_time
    else: x["_period"] = x[d].dt.to_period("M").dt.start_time

    periods = sorted(x["_period"].dropna().unique())
    if len(periods) < 2:
        return None
    previous, current = periods[-2], periods[-1]
    g = x.groupby([dimension, "_period"])[metric]
    agg_values = {"Promedio": g.mean(), "Máximo": g.max(), "Mínimo": g.min()}.get(agg, g.sum())
    y = agg_values.unstack(fill_value=0).reindex(columns=[previous, current], fill_value=0)
    totals = y.sum(axis=1).sort_values(ascending=False)
    y = y.loc[totals.head(top_n).index].sort_values(by=current, ascending=False)
    if y.empty:
        return None

    fig = go.Figure()
    prev_label = pd.Timestamp(previous).strftime("%b %Y")
    curr_label = pd.Timestamp(current).strftime("%b %Y")
    fig.add_trace(go.Bar(
        x=y.index.astype(str), y=y[previous], name=f"Anterior · {prev_label}",
        marker_color="#64748B", hovertemplate="<b>%{x}</b><br>Anterior: %{y:,.0f}<extra></extra>"
    ))
    fig.add_trace(go.Bar(
        x=y.index.astype(str), y=y[current], name=f"Actual · {curr_label}",
        marker_color=PRIMARY, hovertemplate="<b>%{x}</b><br>Actual: %{y:,.0f}<extra></extra>"
    ))
    fig.update_layout(
        barmode="stack",
        xaxis_title=_label(schema, dimension),
        yaxis_title=_label(schema, metric),
        legend=dict(orientation="h", y=1.02, x=0),
    )
    return _base(fig, 390, show_xgrid=False)

def comparison(df, schema, metric=None, period="Mes"):
    dates = schema.get("dates", [])
    metrics = metric_candidates(df, schema)
    if not dates or not metrics:
        return None
    d, m = dates[0], metric or metrics[0]
    x = df[[d, m]].dropna().copy()
    if x.empty:
        return None
    x[d] = pd.to_datetime(x[d], errors="coerce")
    x[m] = numeric_series(x[m])
    x = x.dropna()
    if period == "Año":
        x["period"] = x[d].dt.year.astype(str)
    elif period == "Trimestre":
        x["period"] = x[d].dt.to_period("Q").astype(str)
    else:
        x["period"] = x[d].dt.to_period("M").astype(str)
    y = x.groupby("period")[m].sum().reset_index()
    if len(y) < 2:
        return None
    y["Variación"] = y[m].pct_change() * 100
    y = y.tail(12)
    # Barras suaves + color semántico solo para señalar subidas/bajadas.
    colors = [PRIMARY] * len(y)
    if len(y) > 1:
        colors = [GREEN if v >= 0 else RED for v in y["Variación"].fillna(0)]
        colors[0] = PRIMARY
    fig = go.Figure(go.Bar(
        x=y["period"], y=y[m], marker=dict(color=colors, line=dict(width=0)),
        text=[_compact_number(v) for v in y[m]], textposition="outside", cliponaxis=False,
        hovertemplate="<b>%{x}</b><br>Valor: <b>%{y:,.0f}</b><br>Variación: %{customdata:.1f}%<extra></extra>",
        customdata=y["Variación"].fillna(0),
    ))
    fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title=None, bargap=.24, uniformtext_minsize=9, uniformtext_mode="hide")
    fig.update_yaxes(tickformat="~s")
    return _base(fig, 350, show_xgrid=False)
