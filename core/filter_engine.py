"""Motor único de filtros: qué filas quedan según las reglas activas.

Antes cada vista aplicaba los filtros a su manera. El panel entendía unas
operaciones, el análisis de seguimiento solo "in" y "equals", y las opciones
en cascada otras más. Un filtro por rango se aplicaba en el panel y se
ignoraba en silencio en el seguimiento, que terminaba mostrando filas que el
resto de la app ya había dejado fuera. Aquí vive la única definición de qué
significa cada regla, y todas las vistas la usan.

Reglas que entiende, una por columna:

- ``{"op": "in", "value": [...]}``: el valor está en la lista. ``VACIO`` en la
  lista incluye las celdas vacías.
- ``{"op": "between", "value": [desde, hasta], "incluir_vacios": bool}``:
  rango numérico inclusivo; cualquiera de los dos límites puede ser None.
- ``{"op": "date_between", "value": [inicio, fin], "incluir_vacios": bool}``:
  rango de fechas inclusivo.
- ``{"op": "contains", "value": "texto"}``: contiene el texto, sin importar
  mayúsculas.
- ``equals``, ``gt``, ``gte``, ``lt`` y ``lte``, que ya existían.
"""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

# Opción que representa las celdas vacías en las listas de valores. Sin ella,
# las filas sin dato en una columna no se podían seleccionar ni excluir, y se
# escapaban de cualquier filtro.
VACIO = "(Vacío)"

# Hasta cuántos valores distintos se ofrece una lista para elegir. Por encima
# de esto, una lista no se puede recorrer y se filtra por texto contenido.
LIMITE_OPCIONES = 2000

_TEXTOS_VACIOS = {"", "nan", "nat", "none", "<na>"}


def es_vacio(serie: pd.Series) -> pd.Series:
    """Celdas sin dato, contando los textos vacíos o que solo dicen "nan"."""
    return serie.isna() | serie.astype(str).str.strip().str.lower().isin(_TEXTOS_VACIOS)


def mascara_regla(serie: pd.Series, regla: dict) -> pd.Series:
    """Qué filas cumplen una regla. Una operación desconocida no filtra nada."""
    op = regla.get("op")
    valor = regla.get("value")
    if op == "in":
        valores = valor if isinstance(valor, (list, tuple, set)) else [valor]
        textos = [str(v) for v in valores if str(v) != VACIO]
        mascara = serie.astype(str).isin(textos)
        if any(str(v) == VACIO for v in valores):
            mascara = mascara | es_vacio(serie)
        return mascara
    if op in {"equals", "eq"}:
        return serie.astype(str).str.casefold() == str(valor).casefold()
    if op == "contains":
        return serie.astype(str).str.contains(str(valor), case=False, na=False, regex=False)
    if op in {"gt", "gte", "lt", "lte"}:
        numeros = pd.to_numeric(serie, errors="coerce")
        limite = float(valor)
        if op == "gt":
            return numeros > limite
        if op == "gte":
            return numeros >= limite
        if op == "lt":
            return numeros < limite
        return numeros <= limite
    if op == "between":
        numeros = pd.to_numeric(serie, errors="coerce")
        desde, hasta = (list(valor or []) + [None, None])[:2]
        mascara = numeros.notna()
        if desde is not None:
            mascara = mascara & (numeros >= float(desde))
        if hasta is not None:
            mascara = mascara & (numeros <= float(hasta))
        if regla.get("incluir_vacios", True):
            mascara = mascara | numeros.isna()
        return mascara
    if op == "date_between":
        fechas = pd.to_datetime(serie, errors="coerce")
        inicio, fin = (list(valor or []) + [None, None])[:2]
        mascara = fechas.notna()
        if inicio is not None:
            mascara = mascara & (fechas >= pd.Timestamp(inicio))
        if fin is not None:
            mascara = mascara & (fechas <= pd.Timestamp(fin))
        if regla.get("incluir_vacios", True):
            mascara = mascara | fechas.isna()
        return mascara
    return pd.Series(True, index=serie.index)


def apply_filters(df, filters):
    """Aplica todas las reglas por columna. Devuelve SOLO la tabla filtrada.

    Una regla sobre una columna que ya no existe, o una regla mal formada, se
    salta en vez de tumbar el panel: pasa al cambiar de hoja o de archivo con
    filtros puestos.
    """
    out = df
    for columna, regla in (filters or {}).items():
        if str(columna).startswith("__") or columna not in out.columns or not isinstance(regla, dict):
            continue
        try:
            out = out[mascara_regla(out[columna], regla)]
        except (TypeError, ValueError):
            continue
    return out


def _numero(valor) -> str:
    if valor is None:
        return "—"
    numero = float(valor)
    return f"{numero:,.0f}" if numero.is_integer() else f"{numero:,.2f}"


def describir_regla(columna, regla: dict) -> str | None:
    """La regla en una frase corta, para mostrar qué recorte está activo."""
    if not isinstance(regla, dict):
        return None
    op = regla.get("op")
    valor = regla.get("value")
    sin_vacios = "" if regla.get("incluir_vacios", True) else ", sin vacíos"
    if op == "in":
        valores = [str(v) for v in (valor if isinstance(valor, (list, tuple, set)) else [valor])]
        if not valores:
            return None
        mas = f" y {len(valores) - 3} más" if len(valores) > 3 else ""
        return f"{columna}: {', '.join(valores[:3])}{mas}"
    if op == "between":
        desde, hasta = (list(valor or []) + [None, None])[:2]
        return f"{columna}: de {_numero(desde)} a {_numero(hasta)}{sin_vacios}"
    if op == "date_between":
        inicio, fin = (list(valor or []) + [None, None])[:2]
        texto_inicio = pd.Timestamp(inicio).strftime("%d/%m/%Y") if inicio is not None else "el inicio"
        texto_fin = pd.Timestamp(fin).strftime("%d/%m/%Y") if fin is not None else "el final"
        return f"{columna}: del {texto_inicio} al {texto_fin}{sin_vacios}"
    if op == "contains":
        return f"{columna} contiene «{valor}»"
    signos = {"equals": "=", "eq": "=", "gt": ">", "gte": "≥", "lt": "<", "lte": "≤"}
    if op in signos:
        return f"{columna} {signos[op]} {valor}"
    return None


def resumen_seleccion(filters, visibles, total, rango_fechas=None, busqueda=None) -> dict:
    """Qué parte del archivo se está viendo, en palabras y contra el total.

    Filtrar sin que la pantalla lo dijera parecía no hacer nada: la pestaña
    con la que abre el panel mostraba el archivo completo, y la franja de
    arriba solo decía "N registros visibles", sin nada con qué compararlo.

    ``rango_fechas`` es el (mínimo, máximo) de la columna del periodo: el
    periodo siempre tiene regla, pero solo cuenta como filtro si recorta.
    """
    filters = filters or {}
    frases = [f for f in (describir_regla(c, r) for c, r in filters.items()
                          if not str(c).startswith("__")) if f]
    fecha = filters.get("__date__")
    if isinstance(fecha, dict) and rango_fechas and None not in rango_fechas:
        minimo, maximo = (pd.Timestamp(x).normalize() for x in rango_fechas)
        inicio, fin = pd.Timestamp(fecha.get("start")), pd.Timestamp(fecha.get("end"))
        if inicio.normalize() > minimo or fin.normalize() < maximo:
            frases.insert(0, describir_regla("Periodo", {"op": "date_between", "value": [inicio, fin]}))
    if busqueda and str(busqueda).strip():
        frases.append(f"Búsqueda «{str(busqueda).strip()}»")
    total = int(total or 0)
    visibles = int(visibles or 0)
    return {
        "filtrado": bool(frases) or visibles < total,
        "frases": frases,
        "visibles": visibles,
        "total": total,
        "porcentaje": (visibles / total * 100) if total else 0.0,
    }


@st.cache_data(show_spinner=False, max_entries=16, ttl=1800)
def columnas_filtrables(df, schema) -> list[dict]:
    """Todas las columnas reales del archivo, con el filtro que les corresponde.

    Antes solo se podían filtrar las columnas que el esquema clasificó como
    categoría. Las numéricas, las de texto con muchos valores, los códigos y
    las fechas secundarias no aparecían en ningún lado. Ahora cada columna con
    algún dato tiene su filtro:

    - "fecha": rango de fechas.
    - "numero": rango desde y hasta, para métricas y columnas con muchos
      valores numéricos.
    - "opciones": lista para elegir, hasta ``LIMITE_OPCIONES`` valores.
    - "texto": contiene, cuando hay demasiados valores para una lista.
    """
    schema = schema or {}
    fechas = set(schema.get("dates", []))
    metricas = set(schema.get("metrics", []))
    tipos = schema.get("types", {}) or {}
    salida = []
    for columna in df.columns:
        if str(columna).startswith("__"):
            continue
        serie = df[columna]
        vacios = es_vacio(serie)
        if bool(vacios.all()):
            continue  # una columna sin ningún dato no tiene nada que filtrar
        distintos = int(serie[~vacios].astype(str).nunique())
        if columna in fechas or pd.api.types.is_datetime64_any_dtype(serie):
            tipo = "fecha"
        elif tipos.get(columna) in {"Año", "Mes", "Booleano"} or pd.api.types.is_bool_dtype(serie):
            tipo = "opciones"
        elif (columna in metricas or pd.api.types.is_numeric_dtype(serie)) and distintos > 12:
            tipo = "numero"
        elif distintos <= LIMITE_OPCIONES:
            tipo = "opciones"
        else:
            tipo = "texto"
        salida.append({"columna": columna, "tipo": tipo, "distintos": distintos, "vacios": int(vacios.sum())})
    return salida


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
    """Opciones válidas de cada lista, según los demás filtros activos.

    Usa la misma definición de cada regla que `apply_filters`, así que un
    rango numérico o de fechas también acota las opciones de las listas. Si
    la columna tiene celdas vacías en esa selección, ``VACIO`` va primero.
    """
    active_filters = active_filters or {}
    result = {}
    for target in columns:
        if target not in df.columns:
            continue
        mask = pd.Series(True, index=df.index)
        for col, rule in active_filters.items():
            if col == target or col not in df.columns or not isinstance(rule, dict):
                continue
            try:
                mask &= mascara_regla(df[col], rule)
            except (TypeError, ValueError):
                continue
        serie = df.loc[mask, target]
        vacios = es_vacio(serie)
        vals = serie[~vacios].astype(str).drop_duplicates().tolist()
        vals.sort(key=lambda x: x.casefold())
        if limit:
            vals = vals[:limit]
        if bool(vacios.any()):
            vals = [VACIO] + vals
        result[target] = vals
    return result
