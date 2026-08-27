"""Deterministic, Spanish explanations for charts."""
from __future__ import annotations
import pandas as pd
import numpy as np
from .numeric import safe_sum, safe_mean, safe_median, safe_min, safe_max


def _label(schema, c):
    for x in schema.get("semantic", {}).get("columns", []):
        if x.get("column") == c:
            return x.get("display_name") or c
    return str(c)


def _num(v):
    if pd.isna(v): return "—"
    v = float(v)
    if abs(v) >= 1_000_000_000: return f"{v/1_000_000_000:.1f} mil M"
    if abs(v) >= 1_000_000: return f"{v/1_000_000:.1f} M"
    if abs(v) >= 1_000: return f"{v/1_000:.1f} mil"
    return f"{v:,.0f}"


def explain_chart(df, schema, kind, metric=None, dimension=None, grain="Mes"):
    if metric not in df.columns if metric else False:
        return None
    mlabel = _label(schema, metric) if metric else "la métrica"
    if metric:
        s = pd.to_numeric(df[metric], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    else:
        s = pd.Series(dtype=float)
    if s.empty and kind not in {"correlation"}:
        return "No hay valores suficientes para explicar este gráfico."

    if kind in {"trend", "comparison"} and metric:
        dates = [c for c in schema.get("dates", []) if c in df.columns]
        if not dates: return f"No se detectó una fecha utilizable para explicar la evolución de {mlabel}."
        d = dates[0]
        x = df[[d, metric]].copy(); x[d] = pd.to_datetime(x[d], errors="coerce"); x[metric] = pd.to_numeric(x[metric], errors="coerce"); x=x.dropna()
        if x.empty: return "No hay periodos válidos suficientes."
        g = x.groupby(x[d].dt.to_period("M"))[metric].sum()
        if len(g) < 2: return "Hay un solo periodo disponible; no es posible explicar una variación temporal."
        first, last = float(g.iloc[0]), float(g.iloc[-1])
        pct = ((last-first)/abs(first)*100) if first else None
        peak = g.idxmax(); low = g.idxmin()
        if pct is None:
            return f"El periodo más reciente registra {_num(last)} en {mlabel}. El máximo aparece en {peak} y el mínimo en {low}."
        direction = "aumentó" if pct >= 0 else "disminuyó"
        return f"{mlabel} {direction} {abs(pct):.1f}% entre el primer y el último periodo visible. El máximo se observa en {peak} y el mínimo en {low}."

    if kind in {"ranking", "donut", "geo"} and metric and dimension in df.columns:
        x=df[[dimension,metric]].copy(); x[metric]=pd.to_numeric(x[metric],errors="coerce"); x=x.dropna();
        if x.empty: return None
        g=x.groupby(dimension)[metric].sum().sort_values(ascending=False)
        if g.empty: return None
        leader=str(g.index[0]); lv=float(g.iloc[0]); total=safe_sum(g)
        share=(lv/total*100) if total else 0
        if len(g)>=2:
            second=str(g.index[1]); sv=float(g.iloc[1]); gap=((lv-sv)/abs(sv)*100) if sv else None
            gap_txt=f" Está {abs(gap):.1f}% por encima de {second}." if gap is not None else ""
        else: gap_txt=""
        return f"{leader} lidera {mlabel} con {_num(lv)}, equivalente al {share:.1f}% del total.{gap_txt}"

    if kind == "histogram" and metric:
        return f"La mediana de {mlabel} es {_num(safe_median(s))} y el promedio es {_num(safe_mean(s))}. El rango observado va de {_num(safe_min(s))} a {_num(safe_max(s))}."

    if kind == "scatter" and metric and dimension in df.columns:
        return None

    if kind == "scatter":
        return "La nube de puntos permite ver si dos métricas se mueven juntas; una relación cercana a una línea indica mayor asociación, no causalidad."

    if kind == "correlation":
        nums=df.select_dtypes(include="number").corr(numeric_only=True)
        if nums.shape[0] < 2: return "No hay suficientes métricas numéricas para explicar relaciones."
        pairs=[]
        for i in range(len(nums.columns)):
            for j in range(i+1,len(nums.columns)):
                v=nums.iloc[i,j]
                if pd.notna(v): pairs.append((abs(v),v,nums.columns[i],nums.columns[j]))
        if not pairs: return "No se encontraron relaciones numéricas suficientes."
        _,v,a,b=max(pairs)
        fuerza="fuerte" if abs(v)>=.7 else "moderada" if abs(v)>=.4 else "débil"
        sentido="positiva" if v>=0 else "inversa"
        return f"La relación más marcada es entre {_label(schema,a)} y {_label(schema,b)}: asociación {sentido} {fuerza} (r={v:.2f}). Esto describe asociación, no causalidad."

    return None
