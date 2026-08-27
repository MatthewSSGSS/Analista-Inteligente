from __future__ import annotations
import pandas as pd
import numpy as np

ADDITIVE = {"revenue","profit","cost","quantity","discount","tax"}
PRIORITY_METRICS = ["revenue","profit","quantity","price","cost","discount","tax","percentage","rating","age"]


def semantic_map(schema):
    return {x.get("column"): x.get("semantic_type", "") for x in schema.get("semantic", {}).get("columns", [])}


def choose_metric(df, schema, preferred=None):
    sem = semantic_map(schema)
    metrics = schema.get("semantic", {}).get("metrics") or schema.get("metrics", [])
    metrics = [m for m in metrics if m in df.columns]
    if preferred in metrics:
        return preferred
    for kind in PRIORITY_METRICS:
        for m in metrics:
            if sem.get(m) == kind:
                return m
    return metrics[0] if metrics else None


def aggregate_value(series, semantic_type, agg="Suma"):
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    if agg == "Promedio": return float(s.mean())
    if agg == "Máximo": return float(s.max())
    if agg == "Mínimo": return float(s.min())
    return float(s.sum()) if semantic_type in ADDITIVE else float(s.mean())


def period_series(df, schema, metric, grain="Mes", agg="Suma"):
    dates = [d for d in schema.get("dates", []) if d in df.columns]
    if not dates or metric not in df.columns:
        return pd.DataFrame(columns=["period", metric])
    d = dates[0]
    x = df[[d, metric]].copy()
    x[d] = pd.to_datetime(x[d], errors="coerce")
    x[metric] = pd.to_numeric(x[metric], errors="coerce")
    x = x.dropna(subset=[d, metric])
    if x.empty:
        return pd.DataFrame(columns=["period", metric])
    if grain == "Día": x["period"] = x[d].dt.floor("D")
    elif grain == "Semana": x["period"] = x[d].dt.to_period("W").dt.start_time
    elif grain == "Trimestre": x["period"] = x[d].dt.to_period("Q").dt.start_time
    elif grain == "Año": x["period"] = x[d].dt.to_period("Y").dt.start_time
    else: x["period"] = x[d].dt.to_period("M").dt.start_time
    sem = semantic_map(schema).get(metric, "")
    reducer = "sum" if agg == "Suma" or (agg == "Automático" and sem in ADDITIVE) else "mean"
    if agg == "Máximo": reducer = "max"
    if agg == "Mínimo": reducer = "min"
    return x.groupby("period", as_index=False)[metric].agg(reducer).sort_values("period")


def dynamic_kpis(df, schema, dashboard=None):
    """Build KPI candidates from the actual workbook semantics, not a fixed sales template."""
    sem = semantic_map(schema)
    metric = choose_metric(df, schema, (dashboard or {}).get("primary_metric"))
    kpis = [{"label":"Registros visibles", "value":f"{len(df):,}", "raw":len(df), "kind":"count"}]
    if metric:
        s = pd.to_numeric(df[metric], errors="coerce").dropna()
        if not s.empty:
            additive = sem.get(metric) in ADDITIVE
            total = float(s.sum()) if additive else float(s.mean())
            kpis.append({"label": "Total" if additive else "Promedio", "value": total, "raw": total, "metric": metric, "kind":"primary"})
            kpis.append({"label":"Mediana", "value":float(s.median()), "raw":float(s.median()), "metric":metric, "kind":"median"})
            if additive:
                kpis.append({"label":"Máximo registrado", "value":float(s.max()), "raw":float(s.max()), "metric":metric, "kind":"max"})
            else:
                kpis.append({"label":"Valor máximo", "value":float(s.max()), "raw":float(s.max()), "metric":metric, "kind":"max"})
    dates = [d for d in schema.get("dates", []) if d in df.columns]
    if metric and dates:
        ps = period_series(df, schema, metric, "Mes", "Automático")
        if len(ps) >= 2:
            prev = float(ps.iloc[-2][metric]); cur = float(ps.iloc[-1][metric])
            if np.isfinite(prev) and prev != 0:
                pct = (cur-prev)/abs(prev)*100
                kpis.append({"label":"Cambio reciente", "value":pct, "raw":pct, "kind":"growth", "metric":metric})
    dims = schema.get("semantic", {}).get("dimensions") or schema.get("categorical", [])
    dims = [d for d in dims if d in df.columns and d not in schema.get("ids", []) and d not in schema.get("dates", [])]
    if metric:
        for dim in dims:
            vals = df[dim].dropna().astype(str).str.strip()
            if vals.nunique() < 2 or vals.nunique() > 100:
                continue
            x = pd.DataFrame({dim: vals, metric: pd.to_numeric(df.loc[vals.index, metric], errors="coerce")}).dropna()
            if x.empty: continue
            grouped = x.groupby(dim)[metric].sum() if sem.get(metric) in ADDITIVE else x.groupby(dim)[metric].mean()
            if grouped.empty: continue
            sorted_grouped = grouped.sort_values(ascending=False)
            top_name, top_val = str(sorted_grouped.index[0]), float(sorted_grouped.iloc[0])
            kpis.append({"label":f"Líder · {dim}", "value":top_name, "raw":top_val, "kind":"leader", "dimension":dim, "metric":metric})
            break
    # Normalize labels/values and keep a compact executive row.
    return kpis[:8]


def dimension_candidates(df, schema):
    sem = semantic_map(schema)
    dims = schema.get("semantic", {}).get("dimensions") or schema.get("categorical", [])
    out=[]
    full = schema.get("full_name", {}) if isinstance(schema.get("full_name", {}), dict) else {}
    full_col = full.get("column")
    if full_col in df.columns: out.append(full_col)
    for d in dims:
        if d not in df.columns or d in schema.get("ids", []) or d in schema.get("dates", []) or d in out: continue
        n=df[d].dropna().astype(str).str.strip().nunique()
        if 2 <= n <= 500: out.append(d)
    return out


def drilldown_options(df, schema, exclude=None):
    exclude=set(exclude or [])
    return [d for d in dimension_candidates(df,schema) if d not in exclude]


def drilldown_table(df, schema, metric, dimension, limit=12):
    if not metric or not dimension or metric not in df.columns or dimension not in df.columns:
        return pd.DataFrame()
    sem=semantic_map(schema).get(metric,"")
    x=df[[dimension,metric]].copy(); x[metric]=pd.to_numeric(x[metric],errors="coerce"); x[dimension]=x[dimension].fillna("Sin dato").astype(str).str.strip(); x=x.dropna(subset=[metric])
    if x.empty: return pd.DataFrame()
    grouped=x.groupby(dimension)[metric].sum() if sem in ADDITIVE else x.groupby(dimension)[metric].mean()
    total=float(grouped.sum()) if sem in ADDITIVE else float(grouped.mean())
    out=grouped.sort_values(ascending=False).head(limit).reset_index()
    out.columns=[dimension,"Valor"]
    out["Participación"]=(out["Valor"]/total*100).round(1) if total else 0
    return out


def person_stats(df, schema, person_col, person_name, metric):
    if not person_col or person_col not in df.columns or metric not in df.columns: return {}
    rows=df[df[person_col].astype(str).str.strip().eq(str(person_name).strip())].copy()
    if rows.empty: return {}
    sem=semantic_map(schema).get(metric,""); s=pd.to_numeric(rows[metric],errors="coerce").dropna()
    if s.empty: return {"rows":rows,"count":len(rows)}
    additive=sem in ADDITIVE
    total=float(s.sum()) if additive else float(s.mean())
    all_s=pd.to_numeric(df[metric],errors="coerce").dropna()
    stats={"rows":rows,"count":len(rows),"value":total,"average":float(s.mean()),"median":float(s.median()),"max":float(s.max()),"min":float(s.min())}
    if len(all_s):
        benchmark=float(all_s.mean())
        compare_value=float(s.mean())
        stats["vs_average_pct"]=(compare_value-benchmark)/abs(benchmark)*100 if benchmark!=0 else None
    dates=[d for d in schema.get("dates",[]) if d in rows.columns]
    if dates:
        ps=period_series(rows,schema,metric,"Mes","Automático")
        stats["series"]=ps
        if len(ps)>=2 and float(ps.iloc[-2][metric])!=0:
            stats["recent_pct"]=(float(ps.iloc[-1][metric])-float(ps.iloc[-2][metric]))/abs(float(ps.iloc[-2][metric]))*100
            stats["best_period"]=ps.loc[ps[metric].idxmax(),"period"]
            stats["worst_period"]=ps.loc[ps[metric].idxmin(),"period"]
    return stats


def smart_chart_questions(df, schema, metric, dimension=None):
    dates=bool([d for d in schema.get("dates",[]) if d in df.columns])
    metrics=[m for m in (schema.get("semantic",{}).get("metrics") or schema.get("metrics",[])) if m in df.columns]
    specs=[]
    if dates and metric: specs.append(("Evolución","¿Está mejorando o empeorando?","trend"))
    if dates and dimension and metric: specs.append(("Cambio por segmento","¿Quién explica la subida o caída?","period_compare"))
    if dimension and metric: specs.append(("Contribución","¿Quién aporta más al resultado?","ranking"))
    if dimension and metric: specs.append(("Participación","¿Cómo se reparte el total?","donut"))
    if metric: specs.append(("Distribución","¿Hay valores concentrados o dispersos?","histogram"))
    if len(metrics)>=2: specs.append(("Relación","¿Qué variables se mueven juntas?","scatter"))
    return specs
