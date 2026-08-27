import re
import pandas as pd
import numpy as np

MISSING_TOKENS = {
    "", "na", "n/a", "nan", "null", "none", "nil", "-", "--",
    "sin dato", "sin datos", "no aplica", "n/d", "s/d"
}
_CURRENCY_RE = re.compile(r"[^\d,.\-+()]+")

def normalize_missing_series(s):
    if pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s):
        x = s.astype("string")
        key = x.str.strip().str.lower()
        x = x.mask(key.isin(MISSING_TOKENS), pd.NA)
        return x
    return s

def _parse_number(value):
    if value is None or pd.isna(value):
        return np.nan
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        return float(value)
    s = str(value).strip()
    if not s or s.lower() in MISSING_TOKENS:
        return np.nan
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("\u00a0", " ")
    s = _CURRENCY_RE.sub("", s)
    if not s:
        return np.nan
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        s = parts[0] + "." + parts[1] if len(parts) == 2 and len(parts[1]) in (1, 2) else "".join(parts)
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 2:
            s = "".join(parts)
        elif len(parts) == 2 and len(parts[1]) == 3 and parts[0].isdigit():
            s = "".join(parts)
    try:
        out = float(s)
        return -out if negative else out
    except Exception:
        return np.nan

def numeric_series(s):
    """Convierte una columna métrica a número y deja faltantes/no válidos en 0."""
    x = normalize_missing_series(s)
    out = pd.to_numeric(x, errors="coerce") if pd.api.types.is_numeric_dtype(x) else x.map(_parse_number)
    return out.replace([np.inf, -np.inf], np.nan).fillna(0.0)

def numeric_valid(s):
    """Convierte a número conservando NaN para controles de calidad."""
    x = normalize_missing_series(s)
    out = pd.to_numeric(x, errors="coerce") if pd.api.types.is_numeric_dtype(x) else x.map(_parse_number)
    return out.replace([np.inf, -np.inf], np.nan)

# Safe aggregations for universal datasets. They never return NaN/inf for an
# empty or invalid selection, so a filter cannot crash the dashboard.
def safe_sum(s, default=0.0):
    x = numeric_valid(s)
    if x.empty:
        return float(default)
    v = x.sum(skipna=True)
    return float(v) if pd.notna(v) and np.isfinite(v) else float(default)

def safe_mean(s, default=0.0):
    x = numeric_valid(s).dropna()
    if x.empty:
        return float(default)
    v = x.mean()
    return float(v) if pd.notna(v) and np.isfinite(v) else float(default)

def safe_median(s, default=0.0):
    x = numeric_valid(s).dropna()
    if x.empty:
        return float(default)
    v = x.median()
    return float(v) if pd.notna(v) and np.isfinite(v) else float(default)

def safe_min(s, default=0.0):
    x = numeric_valid(s).dropna()
    if x.empty:
        return float(default)
    v = x.min()
    return float(v) if pd.notna(v) and np.isfinite(v) else float(default)

def safe_max(s, default=0.0):
    x = numeric_valid(s).dropna()
    if x.empty:
        return float(default)
    v = x.max()
    return float(v) if pd.notna(v) and np.isfinite(v) else float(default)

def safe_float(value, default=0.0):
    try:
        v = float(value)
        return v if np.isfinite(v) else float(default)
    except (TypeError, ValueError):
        return float(default)
