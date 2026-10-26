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

# ── Números escritos como texto, con su formato ──
# "$ 1.234.567", "(500.000)", "2.500.000,50", "1,200,000", "45%", "-1.234",
# "1.234-". Un Excel armado a mano los trae así, y la columna entera quedaba
# como texto: sin KPIs aunque se llamara «Valor». No se acepta nada con "/",
# letras sueltas o grupos que no sean de tres cifras, para no convertir
# fechas ("01/02/2025"), teléfonos ("300 123 4567") ni códigos ("A-102").
_MONEDA = r"(?:(?:US|COP|CLP|MXN)?\s*\$|COP|USD|EUR|€)"
_NUMERO_CON_FORMATO_RE = re.compile(
    r"^\s*(?P<neg1>[-−])?\s*(?P<par1>\()?\s*(?P<neg2>[-−])?\s*(?P<mon1>" + _MONEDA + r")?\s*(?P<neg3>[-−])?\s*"
    r"(?P<num>\d{1,3}(?:[., ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"\s*(?P<pct>%)?\s*(?P<mon2>" + _MONEDA + r")?\s*(?P<par2>\))?\s*(?P<neg4>-)?\s*$",
    re.I,
)


def _papel_separador(nums: list, sep: str) -> str:
    """'decimal' o 'miles' para `sep` en ESTA columna, mirando todos sus valores.

    Una celda suelta es ambigua ("1.234" puede ser mil doscientos o uno coma
    algo), la columna no: basta un "1.5", un "0.25" o un "1234.567" para
    saber que el punto es decimal, y un "1.234.567" para saber que es de
    miles. Si nada lo desempata, es de miles, como se escribe en Colombia.
    """
    otro = "," if sep == "." else "."
    con = [n for n in nums if sep in n and otro not in n]
    if any(n.count(sep) > 1 for n in con):
        return "miles"
    for n in con:
        entero, decimales = n.split(sep)
        if len(decimales) != 3 or entero == "0" or len(entero) > 3:
            return "decimal"
    return "miles"


def numeros_con_formato(s: pd.Series):
    """(serie numérica, formato) si la columna es de números escritos con
    formato; None si no lo es. `formato` es "porcentaje", "moneda" o None,
    según cómo venían escritos la mayoría de los valores."""
    valores = s.dropna()
    textos = valores[valores.map(lambda v: isinstance(v, str))].astype(str).str.strip()
    textos = textos[textos != ""]
    if textos.empty:
        return None
    unicos = pd.Series(textos.unique())
    partes = unicos.str.replace(" ", " ", regex=False).str.match(_NUMERO_CON_FORMATO_RE)
    if partes.mean() < 0.85 or len(valores) and len(textos) / len(valores) < 0.5:
        return None
    hallazgos = {u: _NUMERO_CON_FORMATO_RE.match(u.replace(" ", " ")) for u in unicos[partes]}
    nums = [m.group("num") for m in hallazgos.values()]
    # Sin ningún símbolo ni separador es un número común: lo resuelve
    # pd.to_numeric en core/cleaner, como siempre.
    if not any(re.search(r"[.,() %$€-]", u) or re.search(r"[A-Za-z]", u) for u in hallazgos):
        return None
    ambos = [n for n in nums if "." in n and "," in n]
    if ambos:
        ultimo_coma = sum(n.rfind(",") > n.rfind(".") for n in ambos)
        decimal = "," if ultimo_coma >= len(ambos) / 2 else "."
    else:
        punto, coma = _papel_separador(nums, "."), _papel_separador(nums, ",")
        decimal = "," if coma == "decimal" else "." if punto == "decimal" else None

    def _a_numero(m):
        n = m.group("num").replace(" ", "")
        # Lo que el valor resuelve solo, manda: con los dos separadores, el
        # último es el decimal; uno repetido es de miles. Así conviven en la
        # misma columna "2.500.000,50" y "1,200,000". La decisión de la
        # columna solo se usa en el caso ambiguo: un separador, una vez.
        if "." in n and "," in n:
            dec = "," if n.rfind(",") > n.rfind(".") else "."
        else:
            sep = "." if "." in n else "," if "," in n else None
            dec = sep if sep and n.count(sep) == 1 and sep == decimal else None
        for sep in ".,":
            if sep != dec:
                n = n.replace(sep, "")
        if dec:
            n = n.replace(dec, ".")
        x = float(n)
        negativo = any(m.group(g) for g in ("neg1", "neg2", "neg3", "neg4")) or (m.group("par1") and m.group("par2"))
        return -x if negativo else x

    convertidos = {u: _a_numero(m) for u, m in hallazgos.items()}
    con_pct = sum(1 for m in hallazgos.values() if m.group("pct"))
    con_moneda = sum(1 for m in hallazgos.values() if m.group("mon1") or m.group("mon2"))
    formato = ("porcentaje" if con_pct >= len(hallazgos) / 2 else
               "moneda" if con_moneda >= len(hallazgos) / 2 else None)

    def _celda(v):
        if v is None or (not isinstance(v, str) and pd.isna(v)):
            return np.nan
        if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
            return float(v)  # la celda ya era un número en el Excel
        return convertidos.get(str(v).strip(), np.nan)

    return s.map(_celda).astype("float64"), formato


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
