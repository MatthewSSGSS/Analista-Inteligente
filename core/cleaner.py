import re
import unicodedata
import pandas as pd
from .numeric import normalize_missing_series


def _normalize_key(value) -> str:
    s = str(value)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _consolidate_spelling_variants(series: pd.Series):
    """Une valores que son el mismo dato escrito distinto -p. ej. "CAV",
    "Cav" y "cav " en una columna de puestos- para que no se cuenten ni se
    grafiquen como categorías separadas. La variante más frecuente es la que
    se conserva. Solo toca columnas donde de verdad existe esa duplicación;
    si todo ya está escrito de forma consistente, no cambia nada.

    Se trabaja sobre los valores DISTINTOS, no sobre las filas: normalizar
    (quitar tildes, mayúsculas, espacios) es caro y una columna de 200.000
    filas suele tener unas pocas decenas de valores distintos. La versión
    anterior normalizaba fila por fila —dos veces, además: una para agrupar
    y otra al reemplazar— y encima recorría la columna entera por cada clave
    candidata (`non_null[keys == k]` dentro del bucle), lo que la volvía
    cuadrática. El resultado es el mismo, solo que proporcional a los
    valores distintos en vez de al tamaño del archivo.
    """
    non_null = series.dropna()
    if non_null.empty:
        return series, 0

    counts = non_null.value_counts()
    key_by_value = {v: _normalize_key(v) for v in counts.index}
    by_key: dict[str, list] = {}
    for value, key in key_by_value.items():
        by_key.setdefault(key, []).append(value)

    # Solo hay variante cuando una misma clave normalizada llega escrita de
    # más de una forma (con una sola forma no hay nada que unificar).
    canonical = {
        key: counts[values].idxmax()
        for key, values in by_key.items()
        if len(values) > 1
    }
    if not canonical:
        return series, 0

    replacements = {
        value: canonical[key_by_value[value]]
        for value in counts.index
        if key_by_value[value] in canonical and canonical[key_by_value[value]] != value
    }
    if not replacements:
        return series, 0
    changed = int(non_null.isin(list(replacements)).sum())
    return series.replace(replacements), changed


def clean(df):
    out=df.copy(deep=True); log=[]
    seen={}
    cols=[]
    for c in out.columns:
        base=re.sub(r"\s+"," ",str(c).replace("\n"," ").replace("\r"," ").strip()) or "Columna"
        seen[base]=seen.get(base,0)+1
        cols.append(base if seen[base]==1 else f"{base}_{seen[base]}")
    if list(out.columns)!=cols: out.columns=cols; log.append("Nombres de columnas normalizados.")
    missing_replaced = 0
    variants_merged_total = 0
    variant_columns = []
    for c in out.select_dtypes(include=["object","string"]).columns:
        before = out[c].isna().sum()
        out[c]=out[c].astype("string").str.replace(r"[\r\n\t]"," ",regex=True).str.strip()
        out[c] = normalize_missing_series(out[c])
        # Excel often stores numeric columns as text when the sheet contains a
        # title/header row. Recover numeric columns when most non-empty values
        # are numeric, without touching true categorical columns such as Mes.
        probe = pd.to_numeric(out[c], errors="coerce")
        nonempty = out[c].notna().sum()
        if nonempty and probe.notna().sum() / nonempty >= 0.85:
            out[c] = probe
        else:
            out[c], merged = _consolidate_spelling_variants(out[c])
            if merged:
                variants_merged_total += merged
                variant_columns.append(str(c))
        missing_replaced += int(out[c].isna().sum() - before)
    if variants_merged_total:
        cols_txt = ", ".join(variant_columns[:5]) + ("…" if len(variant_columns) > 5 else "")
        log.append(f"{variants_merged_total:,} valores unificados por escribirse distinto (mayúsculas/espacios/tildes) siendo el mismo dato, en: {cols_txt}.")
    # En columnas que ya son numéricas, los faltantes pasan a cero para que
    # cualquier cálculo posterior sea estable. Las columnas de texto/categoría
    # conservan sus faltantes para no convertir una categoría ausente en "0".
    numeric_cols = out.select_dtypes(include=["number"]).columns
    numeric_missing = int(out[numeric_cols].isna().sum().sum()) if len(numeric_cols) else 0
    if len(numeric_cols):
        out[numeric_cols] = out[numeric_cols].replace([float("inf"), float("-inf")], pd.NA).fillna(0)
    if numeric_missing:
        log.append(f"{numeric_missing:,} valores numéricos faltantes convertidos a 0 para los cálculos.")
    dup=int(out.duplicated().sum())
    if dup: log.append(f"{dup:,} filas duplicadas detectadas; no se eliminaron automáticamente.")
    return out,log
