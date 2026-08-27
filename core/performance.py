import pandas as pd
import numpy as np
from .numeric import numeric_series

ADDITIVE = {"revenue", "profit", "cost", "quantity", "discount", "tax"}
GEO = {"region": 0, "country": 1, "city": 2, "zone": 3, "department": 4, "state": 5}
BUSINESS = {"product": 10, "category": 11, "brand": 12, "customer": 13, "employee": 14, "segment": 15}

def _semantic(schema):
    return {x.get("column"): x.get("semantic_type") for x in schema.get("semantic", {}).get("columns", [])}

def choose_dimension(df, schema):
    sem = _semantic(schema)
    dims = schema.get("semantic", {}).get("dimensions") or schema.get("categorical", [])
    dates = set(schema.get("dates", [])); ids = set(schema.get("ids", []))
    candidates=[]
    for c in dims:
        if c not in df.columns or c in dates or c in ids:
            continue
        n=df[c].dropna().astype(str).nunique()
        if n < 2 or n > 40:
            continue
        st=sem.get(c, "")
        priority=GEO.get(st, BUSINESS.get(st, 30))
        candidates.append((priority, c))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]

def analyze(df, schema, metric=None, dimension=None, top_n=5):
    sem=_semantic(schema)
    metrics=schema.get("semantic", {}).get("metrics") or schema.get("metrics", [])
    metrics=[m for m in metrics if m in df.columns]
    if not metric or metric not in df.columns:
        priority=["revenue","profit","quantity","cost","price","discount","tax","percentage","rating"]
        metric=next((m for p in priority for m in metrics if sem.get(m)==p), metrics[0] if metrics else None)
    if not metric:
        return None
    if not dimension or dimension not in df.columns:
        dimension=choose_dimension(df,schema)
    if not dimension:
        return None
    x=df[[dimension,metric]].copy()
    x[metric]=numeric_series(x[metric])
    x[dimension]=x[dimension].fillna("Sin categoría").astype(str).str.strip().replace("", "Sin categoría")
    additive=sem.get(metric) in ADDITIVE
    agg="sum" if additive else "mean"
    grouped=x.groupby(dimension)[metric].sum() if additive else x.groupby(dimension)[metric].mean()
    grouped=grouped.replace([np.inf,-np.inf],np.nan).dropna()
    if grouped.empty:
        return None
    ordered=grouped.sort_values(ascending=False)
    top=ordered.head(top_n)
    bottom=ordered.tail(top_n).sort_values(ascending=True)
    total=float(grouped.sum()) if additive else float(grouped.mean())
    return {
        "metric": metric, "dimension": dimension, "aggregation": agg,
        "top": [(str(k), float(v)) for k,v in top.items()],
        "bottom": [(str(k), float(v)) for k,v in bottom.items()],
        "groups": int(len(grouped)), "total": total,
        "additive": additive,
    }
