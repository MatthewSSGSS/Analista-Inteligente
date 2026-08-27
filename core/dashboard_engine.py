import pandas as pd
import numpy as np
from .statistics import describe
from .anomalies import detect
from .insights import generate
from .executive import build_executive, build_alerts, explain_change
from .numeric import numeric_series, safe_sum, safe_mean
from .performance import analyze as analyze_performance
from .universal_analysis import dynamic_kpis

def _fmt_number(v):
    if pd.isna(v): return "—"
    v=float(v)
    if abs(v)>=1_000_000_000: return f"{v/1_000_000_000:.1f}B"
    if abs(v)>=1_000_000: return f"{v/1_000_000:.1f}M"
    if abs(v)>=1_000: return f"{v/1_000:.1f}K"
    return f"{v:,.0f}"

def build_dashboard(df, profile):
    schema=profile["schema"]
    metrics=schema.get("semantic", {}).get("metrics") or schema["metrics"]
    # Prefer business-significant metrics when the semantic engine can identify them.
    priority = ["revenue", "profit", "quantity", "price", "cost", "discount", "tax", "percentage", "rating", "age"]
    semantic_cols = schema.get("semantic", {}).get("columns", [])
    rank = {x["column"]: priority.index(x["semantic_type"]) if x["semantic_type"] in priority else 99 for x in semantic_cols}
    metrics = sorted(metrics, key=lambda c: rank.get(c, 99))
    primary=metrics[0] if metrics else None

    anomalies=detect(df,schema)
    insights=generate(df,schema,anomalies)
    executive=build_executive(df,schema,insights,anomalies)
    alerts=build_alerts(df,schema,insights,anomalies)
    change_analysis=explain_change(df,schema,primary)
    performance=analyze_performance(df,schema,primary)
    summary=(
        f"El conjunto analizado contiene {len(df):,} registros y {len(df.columns)} columnas. "
        f"El motor identificó {len(metrics)} métricas, {len(schema['dates'])} campos de fecha, "
        f"{len(schema['categorical'])} dimensiones y {len(schema['ids'])} identificadores."
    )
    growth=None
    if schema["dates"] and primary:
        d=schema["dates"][0]
        tmp=df[[d,primary]].copy()
        tmp[d]=pd.to_datetime(tmp[d],errors="coerce")
        tmp[primary]=numeric_series(tmp[primary])
        tmp=tmp.dropna(subset=[d])
        if len(tmp)>=2:
            tmp=tmp.set_index(d)[primary].resample("MS").sum().dropna()
            if len(tmp)>=2:
                previous=float(tmp.iloc[-2]); current=float(tmp.iloc[-1])
                if np.isfinite(previous) and np.isfinite(current) and previous != 0:
                    growth=float((current-previous)/abs(previous)*100)

    # Tablas con Enero...Diciembre como columnas. En este caso el "último periodo"
    # es el último mes disponible y el periodo anterior es el mes inmediatamente anterior;
    # nunca se compara Enero contra Diciembre bajo la etiqueta "periodo anterior".
    if growth is None:
        from visualization.charts import month_columns
        month_cols = month_columns(df)
        if len(month_cols) >= 2:
            previous = safe_sum(df[month_cols[-2][1]])
            current = safe_sum(df[month_cols[-1][1]])
            if np.isfinite(previous) and np.isfinite(current) and previous != 0:
                growth=float((current-previous)/abs(previous)*100)
                if not np.isfinite(growth):
                    growth = None

    return {
        "kpis":dynamic_kpis(df, schema, {"primary_metric":primary}), "anomalies":anomalies, "insights":insights, "executive":executive, "alerts":alerts, "change_analysis":change_analysis,
        "summary":summary, "statistics":describe(df,schema),
        "performance": performance,
        "schema":schema, "primary_metric":primary, "growth":growth
    }
