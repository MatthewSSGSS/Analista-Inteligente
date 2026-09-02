from __future__ import annotations
import re
import pandas as pd
import streamlit as st

def apply_filters(df,filters):
    out=df
    for c,r in filters.items():
        if c not in out.columns: continue
        s=out[c]; op=r["op"]; v=r["value"]
        if op=="contains": out=out[s.astype(str).str.contains(str(v),case=False,na=False,regex=False)]
        elif op in {"equals", "eq"}: out=out[s.astype(str).str.casefold()==str(v).casefold()]
        elif op=="in": out=out[s.astype(str).isin([str(x) for x in (v if isinstance(v,(list,tuple,set)) else [v])])]
        elif op=="gt": out=out[pd.to_numeric(s,errors="coerce")>float(v)]
        elif op=="gte": out=out[pd.to_numeric(s,errors="coerce")>=float(v)]
        elif op=="lt": out=out[pd.to_numeric(s,errors="coerce")<float(v)]
        elif op=="lte": out=out[pd.to_numeric(s,errors="coerce")<=float(v)]
    return out

@st.cache_data(show_spinner=False, max_entries=24, ttl=1800)
def natural_filter(df,q,schema):
    if not q.strip(): return df,{"filters":{},"explanations":[]}
    filters={}; explanations=[]
    # Explicit column equality
    for c in df.columns:
        m=re.search(rf"{re.escape(str(c))}\s*(?:=|es|igual a)\s*([^,]+)",q,re.I)
        if m:
            filters[c]={"op":"equals","value":m.group(1).strip()}
            explanations.append(f"{c} = {m.group(1).strip()}")
    # Numeric comparisons
    m=re.search(r"(?:mayor(?:es)? que|más de|superior a|>)\s*([\d.,]+)",q,re.I)
    if m and schema["metrics"]:
        value=float(m.group(1).replace(".","").replace(",","."))
        c=schema["metrics"][0]
        filters[c]={"op":"gt","value":value}; explanations.append(f"{c} > {value:g}")
    if filters: return apply_filters(df,filters),{"filters":filters,"explanations":explanations}
    mask=df.astype(str).apply(lambda col:col.str.contains(q,case=False,na=False,regex=False)).any(axis=1)
    return df[mask],{"filters":{},"explanations":[f"búsqueda global: {q}"]}

@st.cache_data(show_spinner=False, max_entries=8, ttl=1800)
def search_across_sheets(workbook: dict, query: str, max_rows_per_sheet: int = 200) -> dict:
    """Busca `query` (texto libre) en TODAS las hojas con datos de un Excel
    a la vez — para encontrar algo (un cliente, un producto, un ID) sin
    tener que cambiar de "Hoja activa" una por una. Reutiliza el mismo
    patrón de búsqueda de texto libre que ya usa `natural_filter()` cuando
    no logra interpretar la consulta como un filtro estructurado, solo que
    aplicado a cada hoja del libro en vez de a una hoja ya elegida.

    Devuelve {nombre_hoja: DataFrame con las filas que coinciden}; una hoja
    sin coincidencias no aparece en el resultado.
    """
    results: dict[str, pd.DataFrame] = {}
    if not query or not query.strip():
        return results
    for name, item in (workbook.get("sheets") or {}).items():
        if not isinstance(item, dict):
            continue
        df = item.get("processed")
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        mask = df.astype(str).apply(lambda col: col.str.contains(query, case=False, na=False, regex=False)).any(axis=1)
        matches = df[mask]
        if not matches.empty:
            results[name] = matches.head(max_rows_per_sheet)
    return results


@st.cache_data(show_spinner=False, max_entries=24, ttl=1800)
def cascading_options(df, columns, active_filters=None, limit=80):
    """Return valid options for each categorical filter using the other active filters."""
    active_filters = active_filters or {}
    result = {}
    for target in columns:
        if target not in df.columns:
            continue
        mask = pd.Series(True, index=df.index)
        for col, rule in active_filters.items():
            if col == target or col not in df.columns or not isinstance(rule, dict):
                continue
            op = rule.get("op")
            value = rule.get("value")
            s = df[col]
            if op == "in":
                vals = value if isinstance(value, (list, tuple, set)) else [value]
                mask &= s.astype(str).str.casefold().isin({str(v).casefold() for v in vals})
            elif op in {"equals", "eq"}:
                mask &= s.astype(str).str.casefold().eq(str(value).casefold())
            elif op == "contains":
                mask &= s.astype(str).str.contains(str(value), case=False, na=False, regex=False)
            elif op in {"gt", "gte", "lt", "lte"}:
                n = pd.to_numeric(s, errors="coerce")
                try:
                    v = float(value)
                except (TypeError, ValueError):
                    continue
                if op == "gt": mask &= n > v
                elif op == "gte": mask &= n >= v
                elif op == "lt": mask &= n < v
                elif op == "lte": mask &= n <= v
        vals = df.loc[mask, target].dropna().astype(str).drop_duplicates().tolist()
        vals.sort(key=lambda x: x.casefold())
        result[target] = vals[:limit] if limit else vals
    return result

