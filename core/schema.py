import re
import pandas as pd
from .dates import detect_date, is_month_name_series, month_year_series, extract_year_hint
from .semantic_engine import interpret_dataframe

ID_RE = re.compile(r"(^id$|(^|[_\s-])id([_\s-]|$)|codigo|código|sku|invoice|factura|documento|numero|número)", re.I)
MONEY_RE = re.compile(r"(money|currency|moneda|monto|importe|precio|price|cost|costo|ingreso|revenue|salary|salario|valor|total|amount|profit|utilidad)", re.I)
PCT_RE = re.compile(r"(%|porcentaje|percent|ratio|margen)", re.I)
GEO_RE = re.compile(r"(pais|país|country|ciudad|city|estado|state|region|región|zona|address|direccion|dirección|lat|lon|longitude|latitude)", re.I)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _find_name_parts(columns):
    """Detect common name/surname column combinations without assuming a fixed schema."""
    norm = {str(c).strip().casefold().replace("_", " "): c for c in columns}
    def pick(cands):
        for x in cands:
            if x in norm:
                return norm[x]
        return None
    full = pick(["nombre completo", "nombre y apellido", "nombre_apellido", "full name", "fullname"])
    if full:
        return {"full": full, "parts": []}
    first = pick(["nombre", "nombres", "name", "primer nombre", "first name", "firstname"])
    s1 = pick(["apellido 1", "apellido1", "primer apellido", "apellido paterno", "surname", "last name", "lastname", "last_name"])
    s2 = pick(["apellido 2", "apellido2", "segundo apellido", "apellido materno", "middle surname"])
    if first and (s1 or s2):
        return {"full": "__nombre_completo__", "parts": [c for c in [first, s1, s2] if c]}
    return None


def detect_schema(df, context=None):
    context = context or {}
    # Preserve month/year source columns before date detection can transform them.
    month_source_col = next((c for c in df.columns if is_month_name_series(df[c]) and ("mes" in str(c).lower() or "month" in str(c).lower() or "period" in str(c).lower())), None)
    year_source_col = next((c for c in df.columns if re.search(r"(^|[^a-z])(año|ano|year)([^a-z]|$)", str(c), re.I) and c != month_source_col), None)
    month_source = df[month_source_col].copy() if month_source_col else None
    year_source = df[year_source_col].copy() if year_source_col else None
    schema = {"metrics": [], "dates": [], "categorical": [], "ids": [], "text": [], "emails": [], "geography": [], "types": {}, "date_metadata": {}}
    # Build a universal, optional full-name field for sheets that split a person
    # across Nombre/Apellido columns. It is an internal analytical field and
    # later becomes the single user-facing filter "Nombre completo".
    name_parts = _find_name_parts(df.columns)
    if name_parts and name_parts.get("full") == "__nombre_completo__":
        parts = name_parts["parts"]
        values = []
        for _, row in df[parts].iterrows():
            bits = [str(row[c]).strip() for c in parts if pd.notna(row[c]) and str(row[c]).strip()]
            values.append(" ".join(bits))
        df["__nombre_completo__"] = pd.Series(values, index=df.index, dtype="string")
        schema["categorical"].append("__nombre_completo__")
        schema["types"]["__nombre_completo__"] = "Nombre completo"
        schema["full_name"] = {"column": "__nombre_completo__", "parts": parts}
    elif name_parts and name_parts.get("full") in df.columns:
        schema["full_name"] = {"column": name_parts["full"], "parts": [name_parts["full"]]}
    semantic = interpret_dataframe(df)
    schema["semantic"] = semantic

    # Keep the original deterministic detection for compatibility, then enrich
    # it with semantic concepts. Strong semantic classifications are promoted.
    month_header_aliases = {
        "enero","ene","january","jan","febrero","feb","february","marzo","mar","march",
        "abril","abr","april","mayo","may","junio","jun","june","julio","jul","july",
        "agosto","ago","august","aug","septiembre","setiembre","sep","sept","september",
        "octubre","oct","october","noviembre","nov","november","diciembre","dic","december","dec"
    }
    for c in df.columns:
        s = df[c]
        # Month/year component columns are kept in their original form; the
        # synthesized __periodo_analisis__ field is the only temporal axis used
        # by filters and charts. This prevents "Enero" from becoming 2000-01-01
        # in the visible table.
        header_key = re.sub(r"\s+", " ", str(c).strip().lower()).rstrip(".")
        if c in {month_source_col, year_source_col} or header_key in month_header_aliases:
            if c == year_source_col:
                schema["categorical"].append(c)
                schema["types"][c] = "Año"
            else:
                schema["categorical"].append(c)
                schema["types"][c] = "Mes"
            continue
        dt, rate, method = detect_date(s, c)
        if dt is not None and rate >= .90:
            df[c] = dt
            schema["dates"].append(c); schema["types"][c] = "Fecha"; schema["date_metadata"][c] = method
            continue
        if pd.api.types.is_bool_dtype(s):
            schema["categorical"].append(c); schema["types"][c] = "Booleano"; continue
        if pd.api.types.is_numeric_dtype(s):
            ratio = s.dropna().nunique() / max(s.notna().sum(), 1)
            sem_item = next((x for x in semantic.get("columns", []) if x.get("column") == c), {})
            sem_type = sem_item.get("semantic_type")
            # Never treat numeric identifiers as measures. This is semantic,
            # so cédulas, seriales, teléfonos, códigos, etc. stay out of
            # sums/averages even when Excel stores them as numbers.
            if c in semantic.get("ids", []) or sem_type in {"id", "phone", "postal_code"} or (ID_RE.search(str(c)) and ratio > .5):
                if c not in schema["ids"]:
                    schema["ids"].append(c)
                schema["types"][c] = "Identificador"
            elif PCT_RE.search(str(c)) or sem_type == "percentage":
                schema["metrics"].append(c); schema["types"][c] = "Porcentaje"
            elif MONEY_RE.search(str(c)) or sem_type in {"revenue", "profit", "cost", "price", "discount", "tax"}:
                schema["metrics"].append(c); schema["types"][c] = "Moneda"
            elif sem_type in {"quantity", "rating", "age"} or sem_type in {"unknown", None}:
                schema["metrics"].append(c); schema["types"][c] = {"quantity": "Cantidad", "rating": "Puntuación", "age": "Edad"}.get(sem_type, "Número")
            elif sem_type in {"latitude", "longitude"}:
                schema["geography"].append(c); schema["types"][c] = "Geografía"
            else:
                # Conservative fallback: if semantic detection does not call it
                # a measure, do not invent a KPI from it.
                schema["categorical"].append(c); schema["types"][c] = "Dato numérico no medible"
            continue
        x = s.dropna().astype(str).str.strip()
        if len(x) and x.map(lambda v: bool(EMAIL_RE.match(v))).mean() > .95:
            schema["emails"].append(c); schema["types"][c] = "Correo"; continue
        ratio = x.nunique() / max(len(x), 1)
        if ID_RE.search(str(c)) and ratio > .5:
            schema["ids"].append(c); schema["types"][c] = "Identificador"
        elif GEO_RE.search(str(c)):
            schema["geography"].append(c); schema["categorical"].append(c); schema["types"][c] = "Geografía"
        elif x.nunique() <= min(100, max(10, int(len(x) * .05))):
            schema["categorical"].append(c); schema["types"][c] = "Categoría"
        else:
            schema["text"].append(c); schema["types"][c] = "Texto"

    # Semantic layer can recover poorly named columns and provides better roles.
    for c in semantic["date"]:
        if c in {month_source_col, year_source_col}:
            continue
        if c in df.columns and c not in schema["dates"]:
            dt, rate, method = detect_date(df[c], c)
            if dt is not None and rate >= .80:
                df[c] = dt
                schema["dates"].append(c); schema["types"][c] = "Fecha"; schema["date_metadata"][c] = method or "semantic"
    for c in semantic["metrics"]:
        if c in df.columns and c not in schema["metrics"] and c not in schema["ids"]:
            schema["metrics"].append(c)
            item = next((x for x in semantic["columns"] if x["column"] == c), None)
            schema["types"][c] = {
                "revenue": "Moneda", "profit": "Moneda", "cost": "Moneda", "price": "Moneda",
                "quantity": "Cantidad", "percentage": "Porcentaje", "rating": "Puntuación", "age": "Edad"
            }.get(item["semantic_type"] if item else "", "Número")
    for c in semantic["dimensions"]:
        if c in df.columns and c not in schema["categorical"] and c not in schema["ids"]:
            schema["categorical"].append(c)
            schema["types"].setdefault(c, "Dimensión")
    for c in semantic["ids"]:
        if c in df.columns and c not in schema["ids"]:
            schema["ids"].append(c); schema["types"][c] = "Identificador"
    for c in semantic["geography"]:
        if c in df.columns and c not in schema["geography"]:
            schema["geography"].append(c)

    # Periodos escritos como "Enero", "Febrero" o como Mes + Año son fechas
    # válidas para el análisis. Creamos una fecha interna universal y retiramos
    # las columnas componentes del eje temporal para evitar fechas falsas como
    # "2000-01-01" en la interfaz.
    if month_source_col:
        year_hint = extract_year_hint(context.get("sheet_name"), context.get("workbook_name"))
        period = month_year_series(month_source, year_source, year_hint=year_hint)
        internal = "__periodo_analisis__"
        suffix = 2
        while internal in df.columns:
            internal = f"__periodo_analisis_{suffix}__"
            suffix += 1
        df[internal] = period
        schema["dates"] = [c for c in schema["dates"] if c not in {month_source_col, year_source_col}]
        schema["types"].pop(month_source_col, None)
        schema["types"].pop(year_source_col, None)
        schema["date_metadata"].pop(month_source_col, None)
        schema["date_metadata"].pop(year_source_col, None)
        schema["dates"].append(internal)
        schema["types"][internal] = "Fecha de periodo"
        schema["date_metadata"][internal] = "mes_nombre" if year_source_col is None else "mes_año"
        schema.setdefault("period_sources", {})[internal] = {"month": month_source_col, "year": year_source_col, "year_hint": year_hint}

    return schema
