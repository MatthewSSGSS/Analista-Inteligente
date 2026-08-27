"""Motor de comparación entre múltiples archivos/periodos.
No presupone nombres de columnas: utiliza el esquema semántico detectado por el proyecto.
"""
from __future__ import annotations
from .numeric import numeric_series, safe_sum, safe_mean

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

import numpy as np
import pandas as pd


def _norm(v: Any) -> str:
    s = "" if v is None else str(v)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", " ", s).strip().lower()
    return s


def _semantic_map(schema: dict) -> dict[str, list[str]]:
    out = {}
    sem = schema.get("semantic", {}) or {}
    for item in sem.get("columns", []) or []:
        out.setdefault(item.get("semantic_type", "unknown"), []).append(item.get("column"))
    return out


def _concept(col: str, schema: dict) -> str:
    for item in (schema.get("semantic", {}) or {}).get("columns", []) or []:
        if item.get("column") == col:
            return item.get("semantic_type", "unknown")
    t = schema.get("types", {}).get(col, "")
    if t == "Moneda": return "revenue"
    if t == "Cantidad": return "quantity"
    if t == "Porcentaje": return "percentage"
    if t == "Puntuación": return "rating"
    if t == "Edad": return "age"
    if col in schema.get("dates", []): return "date"
    if col in schema.get("geography", []): return "city"
    if col in schema.get("categorical", []): return "category"
    return "unknown"


def _is_dimension(col: str, schema: dict) -> bool:
    return (col in schema.get("categorical", []) or col in schema.get("geography", [])) and col not in schema.get("metrics", []) and col not in schema.get("ids", [])


def _is_metric(col: str, schema: dict) -> bool:
    return col in schema.get("metrics", []) and col not in schema.get("ids", [])


def _metric_operation(col: str, schema: dict) -> str:
    concept = _concept(col, schema)
    if concept in {"price", "rating", "age", "percentage", "discount", "margin"}:
        return "mean"
    if concept in {"revenue", "profit", "cost", "quantity", "count"}:
        return "sum"
    typ = str(schema.get("types", {}).get(col, "")).lower()
    if "porcentaje" in typ or "puntuacion" in typ or "edad" in typ or "precio" in typ:
        return "mean"
    return "sum"


def _metric_label(op: str) -> str:
    return {"sum": "Total", "mean": "Promedio"}.get(op, "Valor")


def _match_columns(schema_a: dict, schema_b: dict, df_a: pd.DataFrame, df_b: pd.DataFrame) -> list[dict]:
    a_cols = list(df_a.columns)
    b_cols = list(df_b.columns)
    used = set()
    matches = []
    for a in a_cols:
        ca = _concept(a, schema_a)
        best = None
        for b in b_cols:
            if b in used:
                continue
            cb = _concept(b, schema_b)
            name_score = SequenceMatcher(None, _norm(a), _norm(b)).ratio()
            semantic_score = 1.0 if ca != "unknown" and ca == cb else 0.0
            # Same role + vaguely similar name is enough. Also allow explicit same names.
            score = 0.78 * semantic_score + 0.22 * name_score
            if _norm(a) == _norm(b):
                score = max(score, 0.98)
            if ca == cb and ca not in {"unknown", "category"}:
                score = max(score, 0.88)
            if score >= 0.72:
                if best is None or score > best[0]:
                    best = (score, b, cb)
        if best:
            used.add(best[1])
            matches.append({"a": a, "b": best[1], "score": round(best[0], 3), "concept": ca if ca != "unknown" else best[2]})
    return matches


def _period_label(filename: str, df: pd.DataFrame, schema: dict) -> str:
    # Prefer date range when the file contains dates.
    dates = [c for c in schema.get("dates", []) if c in df.columns]
    if dates:
        s = pd.to_datetime(df[dates[0]], errors="coerce").dropna()
        if not s.empty:
            lo, hi = s.min(), s.max()
            if lo.to_period("M") == hi.to_period("M"):
                return lo.strftime("%B %Y").capitalize()
            return f"{lo.strftime('%d/%m/%Y')} – {hi.strftime('%d/%m/%Y')}"
    stem = re.sub(r"\.(xlsx|xls|csv)$", "", filename, flags=re.I)
    # 2024-enero / enero 2024 / 2024 enero
    return stem.replace("_", " ").replace("-", " ").strip()


def _profile_for_comparison(workbook: dict) -> tuple[str, pd.DataFrame, dict]:
    candidates = []
    for name, item in workbook["sheets"].items():
        df = item["processed"]
        schema = item["profile"]["schema"]
        score = len(df) + 500 * len(schema.get("metrics", [])) + 300 * len(schema.get("dates", [])) + 100 * len(schema.get("categorical", []))
        candidates.append((score, name, df, schema))
    _, name, df, schema = max(candidates, key=lambda x: x[0])
    return name, df.copy(), schema


def prepare_comparison(workbooks: list[dict]) -> dict:
    prepared = []
    for wb in workbooks:
        sheet, df, schema = _profile_for_comparison(wb)
        prepared.append({
            "filename": wb["filename"],
            "sheet": sheet,
            "df": df,
            "schema": schema,
            "label": _period_label(wb["filename"], df, schema),
        })
    # If every selected file has a usable date, compare chronologically regardless
    # of upload order. Otherwise preserve the user's upload order.
    date_keys = []
    all_dated = True
    for item in prepared:
        dates = [c for c in item["schema"].get("dates", []) if c in item["df"].columns]
        if not dates:
            all_dated = False
            break
        vals = pd.to_datetime(item["df"][dates[0]], errors="coerce").dropna()
        if vals.empty:
            all_dated = False
            break
        date_keys.append((vals.min(), item))
    if all_dated:
        prepared = [item for _, item in sorted(date_keys, key=lambda z: z[0])]
    return {"files": prepared}


def _aggregate(df: pd.DataFrame, col: str, schema: dict) -> float:
    s = pd.to_numeric(df[col], errors="coerce")
    if _metric_operation(col, schema) == "mean":
        return safe_mean(s) if s.notna().any() else 0.0
    return safe_sum(s) if s.notna().any() else 0.0


def _pct_change(old: float, new: float) -> float | None:
    if old is None or new is None or pd.isna(old) or pd.isna(new):
        return None
    if old == 0:
        return None
    return (new - old) / abs(old) * 100.0


def _compare_metric_pair(old: dict, new: dict, match: dict) -> dict:
    a, b = match["a"], match["b"]
    ov = _aggregate(old["df"], a, old["schema"])
    nv = _aggregate(new["df"], b, new["schema"])
    return {
        "nombre": a,
        "columna_nueva": b,
        "operacion": _metric_operation(a, old["schema"]),
        "etiqueta_operacion": _metric_label(_metric_operation(a, old["schema"])),
        "anterior": ov,
        "actual": nv,
        "cambio": (nv - ov) if not pd.isna(ov) and not pd.isna(nv) else np.nan,
        "cambio_pct": _pct_change(ov, nv),
    }


def _dimension_changes(old: dict, new: dict, metric_match: dict, dimension_match: dict) -> pd.DataFrame:
    old_dim, new_dim = dimension_match["a"], dimension_match["b"]
    old_metric, new_metric = metric_match["a"], metric_match["b"]
    op = _metric_operation(old_metric, old["schema"])
    def agg(d, dim, met, schema):
        tmp = d[[dim, met]].copy()
        tmp[met] = pd.to_numeric(tmp[met], errors="coerce")
        tmp[dim] = tmp[dim].fillna("Sin dato").astype(str).str.strip()
        tmp = tmp[tmp[met].notna()]
        if op == "mean":
            return tmp.groupby(dim, dropna=False)[met].mean()
        return tmp.groupby(dim, dropna=False)[met].sum()
    a = agg(old["df"], old_dim, old_metric, old["schema"])
    b = agg(new["df"], new_dim, new_metric, new["schema"])
    joined = pd.concat([a.rename("anterior"), b.rename("actual")], axis=1).fillna(0)
    joined["cambio"] = joined["actual"] - joined["anterior"]
    joined["cambio_pct"] = np.where(joined["anterior"] != 0, joined["cambio"] / joined["anterior"].abs() * 100, np.nan)
    joined.index.name = "categoria"
    return joined.reset_index().sort_values("cambio", ascending=False)


def build_comparison(prepared: dict) -> dict:
    files = prepared["files"]
    if len(files) < 2:
        raise ValueError("Se necesitan al menos dos archivos para comparar.")
    first, last = files[0], files[-1]
    matches = _match_columns(first["schema"], last["schema"], first["df"], last["df"])
    metric_matches = [m for m in matches if _is_metric(m["a"], first["schema"]) and _is_metric(m["b"], last["schema"])]
    dim_matches = [m for m in matches if _is_dimension(m["a"], first["schema"]) and _is_dimension(m["b"], last["schema"])]
    metrics = [_compare_metric_pair(first, last, m) for m in metric_matches]

    # A previous-vs-latest view is the most actionable when there are >2 files.
    previous = files[-2]
    prev_matches = _match_columns(previous["schema"], last["schema"], previous["df"], last["df"])
    prev_metric_matches = [m for m in prev_matches if _is_metric(m["a"], previous["schema"]) and _is_metric(m["b"], last["schema"])]
    recent_metrics = [_compare_metric_pair(previous, last, m) for m in prev_metric_matches]

    dimension_results = []
    # Compare dimensions against the first/last and select the best metric available.
    chosen_metric = metric_matches[0] if metric_matches else None
    if chosen_metric:
        for dm in dim_matches[:8]:
            try:
                table = _dimension_changes(first, last, chosen_metric, dm)
                dimension_results.append({"dimension": dm["a"], "dimension_nueva": dm["b"], "metric": chosen_metric["a"], "table": table})
            except Exception:
                pass

    history_rows = []
    # Build a compact series for every metric shared across all files.
    if files:
        for m in metric_matches:
            rows = []
            for f in files:
                best_col = None
                best_score = -1
                for c in f["df"].columns:
                    if not _is_metric(c, f["schema"]):
                        continue
                    concept_match = _concept(m["a"], first["schema"]) == _concept(c, f["schema"])
                    score = (1.0 if concept_match else 0.0) + SequenceMatcher(None, _norm(m["a"]), _norm(c)).ratio() * 0.2
                    if score > best_score:
                        best_score, best_col = score, c
                if best_col:
                    rows.append({"periodo": f["label"], "archivo": f["filename"], "valor": _aggregate(f["df"], best_col, f["schema"])})
            if rows:
                history_rows.append({"metrica": m["a"], "operacion": _metric_label(_metric_operation(m["a"], first["schema"])), "serie": pd.DataFrame(rows)})

    # Executive signals.
    signals = []
    for m in recent_metrics:
        cp = m["cambio_pct"]
        if cp is None:
            continue
        if cp > 0:
            text = f"{m['nombre']} aumentó {abs(cp):.1f}% frente al periodo anterior."
            tone = "positive"
        elif cp < 0:
            text = f"{m['nombre']} disminuyó {abs(cp):.1f}% frente al periodo anterior."
            tone = "warning"
        else:
            text = f"{m['nombre']} se mantuvo estable frente al periodo anterior."
            tone = "info"
        signals.append({"tipo": tone, "texto": text})
    if dimension_results:
        for dr in dimension_results:
            t = dr["table"]
            if len(t):
                up = t.iloc[0]
                down = t.sort_values("cambio", ascending=True).iloc[0]
                signals.append({"tipo": "positive" if up["cambio"] >= 0 else "warning", "texto": f"{dr['dimension']}: {up['categoria']} presenta la mayor mejora y {down['categoria']} la mayor caída en términos absolutos."})
                break

    return {
        "files": files,
        "first": first,
        "last": last,
        "previous": previous,
        "matches": matches,
        "metric_matches": metric_matches,
        "dimension_matches": dim_matches,
        "metrics": metrics,
        "recent_metrics": recent_metrics,
        "dimension_results": dimension_results,
        "history": history_rows,
        "signals": signals[:8],
    }
