"""Semantic interpretation engine for arbitrary tabular/Excel data.

It never mutates the user's original values. It builds an internal semantic
layer using column names, dtypes, value patterns, cardinality and ranges.
"""
from __future__ import annotations
from .numeric import numeric_series
from .dates import TZ_SUFFIX_RE

import re
import unicodedata
import warnings
from difflib import SequenceMatcher
from typing import Any

import pandas as pd


CONCEPTS = {
    "date": ["fecha", "date", "dia", "día", "day", "periodo", "período", "mes", "month", "año", "year", "created", "created_at", "timestamp"],
    "datetime": ["datetime", "timestamp", "fecha hora", "fecha_hora", "date time", "created_at", "updated_at"],
    "id": ["id", "codigo", "código", "code", "sku", "uuid", "folio", "invoice", "factura", "documento", "numero", "número", "no.", "nro", "cedula", "cédula", "identificacion", "identificación", "serial", "numero de serie", "número de serie", "no de serie", "no. de serie", "serie", "codigo interno", "código interno"],
    "name": ["nombre", "name", "nombres", "full name", "fullname"],
    "email": ["email", "e-mail", "correo", "mail"],
    "phone": ["telefono", "teléfono", "phone", "mobile", "celular", "movil", "móvil", "contacto", "numero de telefono", "número de teléfono"],
    "address": ["direccion", "dirección", "address", "domicilio", "ubicacion", "ubicación"],
    "country": ["pais", "país", "country", "nation"],
    "city": ["ciudad", "city", "municipio", "localidad", "town"],
    "region": ["region", "región", "zona", "area", "área", "departamento", "provincia", "territorio", "territory"],
    "postal_code": ["codigo postal", "código postal", "postal", "zip", "zip code", "cp"],
    "latitude": ["lat", "latitude", "latitud"],
    "longitude": ["lon", "lng", "longitude", "longitud", "long"],
    "product": ["producto", "product", "articulo", "artículo", "item", "servicio", "service", "plan", "referencia"],
    "category": ["categoria", "categoría", "category", "tipo", "type", "clase", "class", "familia", "family", "segmento", "segment"],
    "brand": ["marca", "brand", "fabricante", "manufacturer"],
    "supplier": ["proveedor", "supplier", "vendor"],
    "customer": ["cliente", "customer", "comprador", "buyer", "usuario", "user", "cuenta", "account"],
    "employee": ["empleado", "employee", "colaborador", "staff", "trabajador", "worker", "asesor", "vendedor", "salesperson"],
    "gender": ["genero", "género", "gender", "sexo", "sex"],
    "age": ["edad", "age", "years old", "años"],
    "status": ["estado", "status", "situacion", "situación", "state", "condition", "activo", "active"],
    "quantity": ["cantidad", "cant", "qty", "quantity", "unidades", "units", "volumen", "volume", "piezas", "pieces"],
    "price": ["precio", "price", "tarifa", "rate", "unit price", "precio unitario"],
    "cost": ["costo", "cost", "coste", "gasto", "expense", "egreso", "expenditure"],
    "revenue": ["venta", "ventas", "ingreso", "ingresos", "revenue", "sales", "facturacion", "facturación", "importe venta", "total ventas"],
    "profit": ["beneficio", "beneficios", "profit", "ganancia", "ganancias", "utilidad", "margen bruto", "net profit"],
    "discount": ["descuento", "discount", "rebaja", "bonificacion", "bonificación"],
    "tax": ["impuesto", "tax", "iva", "vat", "tributo"],
    "percentage": ["porcentaje", "percent", "pct", "ratio", "tasa", "rate", "margen", "%"],
    "rating": ["rating", "calificacion", "calificación", "puntuacion", "puntuación", "score", "valoracion", "valoración", "stars", "estrellas"],
    "text": ["descripcion", "descripción", "description", "comentario", "comment", "observacion", "observación", "notes", "nota"],
    "task": ["tarea", "tareas", "task", "tasks", "actividad", "actividades", "pendiente", "to do", "todo"],
    "boolean": ["activo", "active", "habilitado", "enabled", "valido", "válido", "valid", "si/no", "yes/no"],
}

# Strong aliases used for fuzzy matching after normalization.
ALIASES = {
    "genero": "gender", "gnero": "gender", "sexo": "gender",
    "cant": "quantity", "cantidad": "quantity", "qty": "quantity",
    "importe": "revenue", "monto": "revenue", "valor total": "revenue",
    "facturacion": "revenue", "facturacion total": "revenue",
    "utilidad": "profit", "ganancia": "profit",
    "proveedor": "supplier", "articulo": "product", "articulo vendido": "product",
    "f venta": "date", "fecha venta": "date", "fecha compra": "date", "fecha ingreso": "date",
}


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[_\-/.]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _tokenize(text: str) -> set[str]:
    return {x for x in normalize_text(text).split() if x}


def _name_score(column: str, concept: str) -> float:
    name = normalize_text(column)
    if not name:
        return 0.0
    if name in ALIASES and ALIASES[name] == concept:
        return 1.0
    phrases = [normalize_text(x) for x in CONCEPTS.get(concept, [])]
    if name in phrases:
        return 1.0
    tokens = _tokenize(name)
    best = 0.0
    for phrase in phrases:
        if not phrase:
            continue
        # Match complete words/phrases, not arbitrary substrings. This avoids
        # false positives such as "Tarea" containing "area".
        pattern = r"(?:^|\s)" + re.escape(phrase) + r"(?:\s|$)"
        if re.search(pattern, name):
            best = max(best, 0.92 if len(phrase) >= 4 else 0.84)
        pt = _tokenize(phrase)
        if tokens and pt:
            best = max(best, len(tokens & pt) / max(len(tokens | pt), 1))
        # Typo-tolerant fuzzy match: only compared word-by-word against
        # words of comparable length, and only trusted above a high bar.
        # Never compare the *whole* column name against a short keyword
        # (e.g. "país") as a single string: short phrases share a handful of
        # letters with almost any unrelated longer word by pure coincidence
        # (SequenceMatcher gave "Especialistas" a 0.47 match against "país",
        # which made a specialist-type column get misread as a country
        # column). Requiring comparable lengths keeps genuine typos like
        # "ciudaad"/"ciudad" while rejecting that kind of noise.
        for tok in tokens:
            if not tok:
                continue
            shorter, longer = sorted([len(tok), len(phrase)])
            if shorter == 0 or shorter / longer < 0.6:
                continue
            ratio = SequenceMatcher(None, tok, phrase).ratio()
            if ratio >= 0.82:
                best = max(best, ratio)
    return min(best, 1.0)


# Cuántos valores se miran para ESTIMAR una proporción (qué porcentaje de la
# columna parece un correo, una fecha, una coordenada...). Estas funciones no
# transforman datos: solo puntúan qué tan probable es un concepto, y para eso
# una muestra amplia da el mismo resultado que la columna entera —a una
# fracción del costo. La conversión de verdad (la que sí toca todos los
# valores) vive aparte, en core/dates.py::detect_date.
CLASSIFY_SAMPLE = 5000


def _for_rate(s: pd.Series) -> pd.Series:
    """Los valores no nulos con los que se estima una proporción."""
    x = s.dropna()
    return x.head(CLASSIFY_SAMPLE) if len(x) > CLASSIFY_SAMPLE else x


def _email_rate(s: pd.Series) -> float:
    x = _for_rate(s).astype(str).str.strip()
    if x.empty:
        return 0.0
    return float(x.str.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$").mean())


def _date_rate(s: pd.Series) -> float:
    if pd.api.types.is_datetime64_any_dtype(s):
        return 1.0
    x = _for_rate(s)
    if x.empty:
        return 0.0
    # Avoid interpreting arbitrary large integers as dates.
    if pd.api.types.is_numeric_dtype(x):
        finite = pd.to_numeric(x, errors="coerce").dropna()
        # Excel serial dates normally live around 1..60000, but common numeric
        # columns such as age/quantity can also fall there. Require a much
        # narrower plausible serial-date window and avoid tiny integers.
        if finite.empty or finite.abs().median() > 200000:
            return 0.0
        if not bool(((finite >= 20000) & (finite <= 60000)).mean() > 0.9):
            return 0.0
    # Se recorta el sufijo de zona horaria antes de convertir, igual que en
    # core/dates.py::detect_date. Sin esto, una columna con desfases
    # distintos entre filas ("+00:00" en unas, "-05:00" en otras) hace que
    # pandas se niegue a construirla ("Mixed timezones detected") y tumbe la
    # carga del archivo COMPLETO.
    #
    # Y este es el punto que de verdad importa: la clasificación semántica
    # (esta función) corre ANTES que la conversión de core/dates.py, dentro
    # de detect_schema(). Arreglarlo solo allá no servía de nada — el
    # archivo ya había reventado aquí. Aquí solo se estima una proporción
    # ("¿qué % parece fecha?"), así que quitar la zona no altera ningún dato:
    # la conversión real, con sus reglas, sigue viviendo en core/dates.py.
    if not pd.api.types.is_numeric_dtype(x):
        x = x.astype(str).str.strip().str.replace(TZ_SUFFIX_RE, "", regex=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        parsed = pd.to_datetime(x, errors="coerce", dayfirst=True)
    return float(parsed.notna().mean())


def _geo_rate(s: pd.Series, concept: str) -> float:
    x = _for_rate(s).astype(str).str.strip()
    if x.empty:
        return 0.0
    if concept == "latitude":
        n = pd.to_numeric(x, errors="coerce")
        return float(((n >= -90) & (n <= 90)).mean())
    if concept == "longitude":
        n = pd.to_numeric(x, errors="coerce")
        return float(((n >= -180) & (n <= 180)).mean())
    return 0.0


def _numeric_signal(s: pd.Series, concept: str) -> float:
    if not pd.api.types.is_numeric_dtype(s):
        x = pd.to_numeric(s, errors="coerce")
    else:
        x = s
    x = x.dropna()
    if x.empty:
        return 0.0
    if concept == "age":
        return float(((x >= 0) & (x <= 110)).mean())
    if concept == "percentage":
        return float((((x >= -100) & (x <= 100)).mean()))
    if concept == "rating":
        return float((((x >= 0) & (x <= 10)).mean()))
    if concept == "quantity":
        return float((x >= 0).mean())
    if concept in {"price", "cost", "revenue", "profit", "discount", "tax"}:
        return float((x.notna()).mean())
    return 0.0


def _categorical_signal(s: pd.Series) -> float:
    x = _for_rate(s).astype(str).str.strip()
    if x.empty:
        return 0.0
    unique = x.nunique()
    ratio = unique / max(len(x), 1)
    if unique <= 30:
        return 1.0
    if unique <= 100 and ratio <= 0.15:
        return 0.75
    return 0.0


def _text_sample(s: pd.Series) -> list[str]:
    """Hasta 500 valores normalizados de la columna, para las señales que se
    resuelven mirando ejemplos ("masculino"/"femenino", "si"/"no").

    Ojo con el ORDEN de las operaciones, que era el problema: antes se hacía
    `s.dropna().astype(str).str.strip()` sobre la columna COMPLETA y recién
    después `.head(500)`. Convertir 50.000 valores a texto para quedarse con
    500 ya es caro; hacerlo una vez POR CONCEPTO (~30) y por columna lo
    multiplicaba hasta volverse el mayor costo de la carga del archivo
    (7,5 s de los 9,5 s que tardaba perfilar una hoja de 50.000 filas).
    Recortar primero y convertir después da exactamente el mismo resultado.
    """
    x = s.dropna().head(500)
    if x.empty:
        return []
    return x.astype(str).str.strip().map(normalize_text).tolist()


def _concept_prior_from_values(s: pd.Series, concept: str, cache: dict | None = None) -> float:
    """`cache` es un diccionario por COLUMNA (lo crea classify_column): las
    señales pesadas —fecha, categórica, correo, geo— no dependen del
    concepto que se esté evaluando, así que se calculan una sola vez y se
    reutilizan. Sin él, `_categorical_signal` se recalculaba 8 veces
    seguidas sobre la misma columna (una por cada concepto categórico) y
    `_date_rate` 2 veces."""
    cache = {} if cache is None else cache

    def once(key, fn):
        if key not in cache:
            cache[key] = fn()
        return cache[key]

    if concept == "gender":
        sample = once("sample", lambda: _text_sample(s))
        return 1.0 if any(v in sample for v in ["masculino", "femenino", "male", "female", "hombre", "mujer", "man", "woman"]) else 0.0
    if concept == "boolean":
        sample = once("sample", lambda: _text_sample(s))
        vals = set(sample)
        return 1.0 if vals and vals <= {"si", "no", "yes", "no", "true", "false", "1", "0", "activo", "inactivo"} else 0.0
    if concept == "email":
        return once("email", lambda: _email_rate(s))
    if concept in {"latitude", "longitude"}:
        return once(f"geo_{concept}", lambda: _geo_rate(s, concept))
    if concept in {"date", "datetime"}:
        return once("date", lambda: _date_rate(s))
    if concept in {"country", "city", "region", "category", "status", "brand", "supplier", "product"}:
        return once("categorical", lambda: _categorical_signal(s))
    return 0.0


def classify_column(s: pd.Series, column: str) -> dict:
    scores: dict[str, float] = {}
    name = normalize_text(column)
    dtype = str(s.dtype)
    non_null = s.dropna()
    unique = int(non_null.nunique()) if len(non_null) else 0
    cardinality = unique / max(len(non_null), 1)

    # Una sola caché para las ~30 evaluaciones de conceptos de ESTA columna:
    # las señales de valores (fecha, categórica, correo, geo) no cambian
    # según el concepto que se esté puntuando, así que basta calcularlas una
    # vez. Se crea aquí y muere aquí — no hay estado entre columnas.
    value_cache: dict = {}
    for concept in CONCEPTS:
        ns = _name_score(column, concept)
        vs = _concept_prior_from_values(s, concept, value_cache)
        # Exact/alias names are strong evidence. Value patterns are a fallback,
        # not a license to override an explicit column name.
        if ns >= 0.98:
            score = 0.94 + 0.06 * vs
        else:
            score = 0.72 * ns + 0.28 * vs
        scores[concept] = min(score, 1.0)

    # A number can never be someone's name, a customer, a country, etc., and
    # text can never be an age or a percentage — no matter how well a stray
    # word in a compound header happens to match. Without this, a numeric
    # column titled "Calificación del cliente" could win on the word
    # "cliente" (matching the customer concept) even though the column holds
    # ratings, not customer identities. This is a hard compatibility rule,
    # applied after name/value scoring so it can only remove wrong answers,
    # never invent a right one.
    is_numeric = pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
    text_only_concepts = {"name", "email", "phone", "address", "country", "city", "region",
                           "product", "category", "brand", "supplier", "customer", "employee",
                           "gender", "status", "text", "task"}
    numeric_only_concepts = {"age", "price", "cost", "revenue", "profit", "discount", "tax",
                              "percentage", "rating", "quantity", "latitude", "longitude"}
    if is_numeric:
        for concept in text_only_concepts:
            scores[concept] = 0.0
    else:
        for concept in numeric_only_concepts:
            scores[concept] = 0.0

    # Strong type evidence. Only override when the underlying dtype itself is
    # definitive; numeric ranges alone stay below explicit semantic names.
    if pd.api.types.is_datetime64_any_dtype(s):
        scores["datetime"] = max(scores["datetime"], 0.98)
        scores["date"] = max(scores["date"], 0.95)
    if pd.api.types.is_bool_dtype(s):
        scores["boolean"] = max(scores["boolean"], 0.98)
    if _email_rate(s) >= 0.95:
        scores["email"] = max(scores["email"], 0.99)
    if pd.api.types.is_numeric_dtype(s):
        # Value-only clues (does the number merely fall in a plausible range?)
        # must never be enough on their own to produce a confident label —
        # almost any small positive number "looks like" an age, a rating, a
        # quantity AND a percentage at once. These caps are kept below the
        # 0.58 threshold used below to fall back to "unknown", so a column
        # only becomes e.g. "age" when its name also supports it (through the
        # scoring loop above); pure numeric coincidence alone stays unknown
        # instead of inventing a category the spreadsheet never had.
        scores["age"] = max(scores["age"], min(_numeric_signal(s, "age") * 0.40, 0.40))
        scores["percentage"] = max(scores["percentage"], min(_numeric_signal(s, "percentage") * 0.38, 0.38))
        scores["quantity"] = max(scores["quantity"], min(_numeric_signal(s, "quantity") * 0.35, 0.35))
        scores["rating"] = max(scores["rating"], min(_numeric_signal(s, "rating") * 0.38, 0.38))
        scores["latitude"] = max(scores["latitude"], min(_geo_rate(s, "latitude") * 0.38, 0.38))
        scores["longitude"] = max(scores["longitude"], min(_geo_rate(s, "longitude") * 0.38, 0.38))

    # Numeric identifiers are still identifiers even when Excel stores them as
    # integers. Use semantic/name evidence plus shape/cardinality; never rely
    # on dtype alone. This covers cédulas, serial numbers, document numbers,
    # phone numbers, internal codes, etc.
    id_tokens = {
        "id", "codigo", "code", "sku", "uuid", "folio", "factura",
        "documento", "numero", "número", "no", "nro", "cedula",
        "cédula", "identificacion", "identificación", "serial", "serie",
        "telefono", "teléfono", "phone", "mobile", "celular", "postal",
        "zip"
    }
    id_name_signal = bool(set(name.split()) & id_tokens) or any(
        phrase in name for phrase in ["numero de serie", "número de serie",
                                      "codigo interno", "código interno",
                                      "numero de telefono", "número de teléfono",
                                      "codigo postal", "código postal"]
    )
    numeric_values = pd.to_numeric(s, errors="coerce").dropna()
    integer_like = bool(not numeric_values.empty and ((numeric_values % 1).abs() < 1e-9).mean() >= 0.98)
    large_integer_like = bool(integer_like and numeric_values.abs().median() >= 10000)
    if id_name_signal and (cardinality > 0.35 or large_integer_like):
        scores["id"] = max(scores["id"], 0.97)

    # Phone/postal identifiers are never analytical metrics.
    if any(t in name.split() for t in {"telefono", "teléfono", "phone", "mobile", "celular", "postal", "zip"}):
        scores["id"] = max(scores["id"], 0.96)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_concept, best_score = ranked[0] if ranked else ("unknown", 0.0)
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    # Don't force weak fuzzy guesses. Unknown is a valid universal outcome.
    if best_score < 0.58:
        best_concept = "unknown"
        confidence = best_score
    else:
        confidence = best_score

    ambiguous = confidence < 0.72 or (confidence - second_score < 0.08 and confidence < 0.90)
    return {
        "column": column,
        "semantic_type": best_concept,
        "confidence": round(float(confidence), 3),
        "ambiguous": bool(ambiguous),
        "second_best": ranked[1][0] if len(ranked) > 1 else None,
        "second_confidence": round(float(second_score), 3),
        "dtype": dtype,
        "non_null": int(len(non_null)),
        "unique": unique,
        "cardinality": round(float(cardinality), 4),
        "normalized_name": name,
    }


# Palabras de conteo: lo que se registra por unidades y tiene sentido sumar.
CONTEO_TOKENS = {
    "altas", "alta", "bajas", "activaciones", "activacion", "pedidos", "ordenes", "transacciones",
    "recargas", "portabilidades", "portabilidad", "llamadas", "visitas", "contratos", "lineas",
    "polizas", "creditos", "desembolsos", "colocaciones", "suscripciones", "instalaciones",
    "renovaciones", "migraciones", "clientes", "afiliaciones", "inscripciones", "matriculas",
    # Lo ejecutado frente a un presupuesto también es un total por periodo.
    "ejecucion", "ejecutado", "ejecutada", "ejecutados", "ejecutadas", "logrado", "logro",
}
_CONECTORES = {"de", "del", "la", "el", "los", "las", "en", "por", "a", "al", "y", "total", "mes", "mensual"}


def _promover_cantidades(df: pd.DataFrame, columns: list[dict]) -> None:
    """Marca como cantidad las columnas numéricas que se suman y el motor no reconoció.

    "Altas Eje" no se parece a ningún concepto conocido y quedaba "unknown":
    todo el panel la promediaba. El KPI decía "Promedio 93" en vez del total,
    y la región grande salía "líder" por su promedio por fila. Dos señales,
    que no dependen de un archivo concreto, dicen que una columna se suma:

    - tiene una meta que la nombra ("Meta Altas Eje", "Presupuesto Ventas"):
      una meta siempre es un total por alcanzar, y la meta también se suma;
    - su nombre es un conteo ("Altas", "Activaciones", "Pedidos").
    """
    from .performance import META_RE

    def numerica(c):
        return pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])

    candidatas = {item["column"]: item for item in columns
                  if item["semantic_type"] == "unknown" and item["column"] in df.columns and numerica(item["column"])}
    if not candidatas:
        return
    promover = set()
    for c in candidatas:
        if CONTEO_TOKENS & _tokenize(normalize_text(c)):
            promover.add(c)
    numericas = [str(c) for c in df.columns if numerica(c)]
    metas_solas = []
    for meta in numericas:
        if not META_RE.search(meta):
            continue
        # Se quita la palabra de meta entera: con la subcadena, "Presupuesto"
        # dejaba "uesto" como resto y nunca emparejaba con nada.
        resto = {t for t in _tokenize(normalize_text(meta)) if not META_RE.search(t)} - _CONECTORES
        if not resto:
            metas_solas.append(meta)
            continue
        for c in numericas:
            if c != meta and not META_RE.search(c) and resto <= _tokenize(normalize_text(c)):
                promover.update({c, meta})
    # Una meta sin más nombre ("Presupuesto", "Meta") es el total esperado de
    # lo que ya se reconoció como cantidad: también se suma.
    if promover:
        promover.update(metas_solas)
    for c in promover:
        item = candidatas.get(c)
        if item is None:
            continue
        valores = pd.to_numeric(df[c], errors="coerce").dropna()
        if valores.empty or float((valores >= 0).mean()) < 0.95:
            continue  # con negativos no es un conteo: puede ser un saldo o una variación
        item["semantic_type"] = "quantity"
        item["confidence"] = max(float(item.get("confidence", 0)), 0.75)
        item["ambiguous"] = False


def interpret_dataframe(df: pd.DataFrame) -> dict:
    columns = [classify_column(df[c], str(c)) for c in df.columns]
    _promover_cantidades(df, columns)
    by_concept: dict[str, list[str]] = {}
    for item in columns:
        by_concept.setdefault(item["semantic_type"], []).append(item["column"])

    # Generic role groups consumed by the dashboard. Keep the existing schema
    # categories compatible while adding semantic meaning.
    semantic = {
        "columns": columns,
        "by_concept": by_concept,
        "date": by_concept.get("datetime", []) + by_concept.get("date", []),
        "dimensions": [],
        "metrics": [],
        # Phone/postal values are identifiers/categories, not measures.
        "ids": by_concept.get("id", []) + by_concept.get("phone", []) + by_concept.get("postal_code", []),
        "geography": [],
    }
    dimension_concepts = {"category", "product", "brand", "supplier", "customer", "employee", "gender", "status", "country", "city", "region", "name", "address"}
    metric_concepts = {"quantity", "price", "cost", "revenue", "profit", "discount", "tax", "percentage", "rating", "age"}
    for item in columns:
        c, concept = item["column"], item["semantic_type"]
        if concept in dimension_concepts:
            semantic["dimensions"].append(c)
        if concept in metric_concepts:
            semantic["metrics"].append(c)
        if concept in {"country", "city", "region", "address", "latitude", "longitude", "postal_code"}:
            semantic["geography"].append(c)

    # Include strong numeric columns not semantically recognized as a metric.
    # Month headers (Enero...Diciembre) are wide time-series columns, not
    # independent business metrics. They are handled by the wide-month chart.
    month_headers = {
        "enero","ene","january","jan","febrero","feb","february","marzo","mar","march",
        "abril","abr","april","mayo","may","junio","jun","june","julio","jul","july",
        "agosto","ago","august","aug","septiembre","setiembre","sep","sept","september",
        "octubre","oct","october","noviembre","nov","november","diciembre","dic","december","dec"
    }
    for c in df.columns:
        if normalize_text(c) in month_headers:
            continue
        if c not in semantic["metrics"] and pd.api.types.is_numeric_dtype(df[c]) and c not in semantic["ids"]:
            # No tratar como métrica variables temporales simples (mes 1-12, año, día).
            n = normalize_text(c)
            vals = pd.to_numeric(df[c], errors="coerce").dropna()
            month_like = ("mes" in n or "month" in n) and not vals.empty and bool(((vals >= 1) & (vals <= 12)).mean() >= .95) and bool((vals % 1 == 0).mean() >= .95)
            year_like = ("año" in n or "ano" in n or "year" in n) and not vals.empty and bool(((vals >= 1900) & (vals <= 2100)).mean() >= .95) and bool((vals % 1 == 0).mean() >= .95)
            day_like = ("dia" in n or "day" in n) and not vals.empty and bool(((vals >= 1) & (vals <= 31)).mean() >= .95) and bool((vals % 1 == 0).mean() >= .95)
            if not (month_like or year_like or day_like):
                semantic["metrics"].append(c)

    return semantic


def confidence_label(value: float) -> str:
    if value >= 0.90:
        return "Alta"
    if value >= 0.72:
        return "Media"
    return "Baja"
