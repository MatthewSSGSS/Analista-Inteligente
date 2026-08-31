"""Motor de preguntas en lenguaje natural.

Principio no negociable: la IA/heurística decide QUÉ calcular (qué métrica,
qué dimensión, qué filtro, qué operación) — pero el resultado numérico
siempre sale de pandas ejecutando sobre los datos reales. Nunca se inventa
un número. Si no se puede determinar con confianza qué pide la pregunta, se
dice explícitamente en vez de adivinar.

No hay lógica específica de un dominio (RH, ventas, telecom...): todo se
resuelve comparando la pregunta contra el diccionario semántico que ya
construye core/semantic_engine.py para cualquier Excel.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

import numpy as np
import pandas as pd

from core.universal_analysis import ADDITIVE, semantic_map, choose_metric
from visualization.charts import metric_candidates, dimension_candidates, _label

MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

MONEY_WORDS = {"pago", "pagaron", "pague", "pagó", "dinero", "plata", "gasto", "gastaron", "costo", "valor", "cop", "pesos", "dolares"}
MONEY_NAME_HINTS = {"valor", "pago", "costo", "precio", "monto", "importe", "salario", "sueldo"}
WHO_WORDS = {"quien", "quienes"}
TOP_WORDS = {"mas", "mayor", "mejor", "maximo", "top", "primero", "primeros", "principal", "principales"}
BOTTOM_WORDS = {"menos", "menor", "peor", "minimo", "bottom", "ultimo", "ultimos"}
AVG_WORDS = {"promedio", "media", "en promedio"}
COUNT_WORDS = {"cuantos", "cuantas", "cantidad de", "numero de"}
TREND_WORDS = {"evoluciono", "evolucion", "tendencia", "a lo largo", "por mes", "mes a mes", "historico", "historial"}
WHY_WORDS = {"por que", "porque", "razon", "causa", "explicacion"}
COMPARE_WORDS = {"compara", "comparar", "comparacion", "versus", " vs "}


def _norm(text: str) -> str:
    s = str(text or "").lower().strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _contains_any(text: str, words: set) -> bool:
    return any(w in text for w in words)


def _fuzzy_contains_any(text: str, words: set, threshold: float = 0.82) -> bool:
    """Igual que _contains_any pero tolera errores de tipeo: si el usuario
    escribe 'qien' en vez de 'quien', o 'mayro' en vez de 'mayor', igual lo
    reconoce. Las frases de varias palabras (p. ej. 'por que') se buscan
    tanto exactas como con tolerancia; las de una sola palabra se comparan
    contra cada palabra de la pregunta con similitud de texto.
    """
    if _contains_any(text, words):
        return True
    tokens = [t for t in text.split() if len(t) >= 3]
    for phrase in words:
        if " " in phrase:
            continue  # las frases largas ya se intentaron exactas arriba
        for tok in tokens:
            if abs(len(tok) - len(phrase)) > 2:
                continue
            if SequenceMatcher(None, tok, phrase).ratio() >= threshold:
                return True
    return False


def _best_column_match(question_norm: str, candidates: list, schema: dict, prefer_money: bool = False) -> tuple[str | None, float]:
    """Encuentra qué columna (entre las candidatas) menciona la pregunta,
    comparando el nombre de cada columna (y su etiqueta legible) contra el
    texto completo de la pregunta. Solo cuenta si aparece como palabra/frase
    real dentro de la pregunta, no por coincidencia de letras sueltas.

    Cuando varias columnas matchean con puntaje parecido (p. ej. "Horas
    Extra" y "Valor Horas Extra" ambas aparecen porque una contiene a la
    otra), y la pregunta usa palabras de dinero ("pagó", "costo", "valor"),
    se prefiere la columna cuyo concepto semántico es monetario — es una
    señal real ya calculada por el motor semántico, no una suposición nueva.
    """
    sem = semantic_map(schema)
    money_concepts = {"revenue", "cost", "profit", "price", "discount", "tax"}
    money_name_hints = MONEY_NAME_HINTS
    scored = []
    for col in candidates:
        label_norm = _norm(_label(schema, col))
        col_norm = _norm(col)
        best_for_col = 0.0
        for phrase in {label_norm, col_norm}:
            if not phrase:
                continue
            if phrase in question_norm:
                score = 0.9 + min(len(phrase) / 40, 0.1)
                best_for_col = max(best_for_col, score)
                continue
            for tok in phrase.split():
                if len(tok) < 4:
                    continue
                for qtok in question_norm.split():
                    if len(qtok) < 4:
                        continue
                    ratio = SequenceMatcher(None, tok, qtok).ratio()
                    if ratio >= 0.86:
                        best_for_col = max(best_for_col, ratio)
        if best_for_col > 0:
            scored.append((col, best_for_col))
    if not scored:
        return None, 0.0
    scored.sort(key=lambda x: x[1], reverse=True)
    best_score = scored[0][1]
    # Entre los que están casi empatados con el mejor puntaje, el desempate
    # es el concepto monetario si la pregunta lo sugiere.
    close = [c for c, sc in scored if sc >= best_score - 0.05]
    if prefer_money and len(close) > 1:
        # Primero se confía en la clasificación semántica general (más
        # robusta); si ninguna de las columnas empatadas tiene un concepto
        # monetario reconocido, se revisa si el propio nombre de la columna
        # sugiere dinero (p. ej. "Valor Horas Extra") — más permisivo que el
        # clasificador general porque aquí ya hay una pista extra: la
        # pregunta misma usa palabras de dinero.
        for c in close:
            if sem.get(c) in money_concepts:
                return c, best_score
        for c in close:
            if any(hint in _norm(c) for hint in money_name_hints):
                return c, best_score
    return scored[0][0], best_score


def _detect_filters(question_norm: str, df: pd.DataFrame, schema: dict, dims: list) -> dict:
    """Detecta filtros implícitos: valores concretos de una dimensión que
    aparecen mencionados en la pregunta (p. ej. 'en Bogotá', 'Producto X').
    Solo se aplica un filtro si el valor existe de verdad en esa columna.
    Tolera errores de tipeo leves (p. ej. 'bogot' o 'medelin') comparando
    palabra por palabra cuando la coincidencia exacta no aparece.
    """
    filters = {}
    q_tokens = [t for t in question_norm.split() if len(t) >= 3]
    for col in dims:
        try:
            values = df[col].dropna().astype(str).unique().tolist()
        except Exception:
            continue
        for v in values:
            v_norm = _norm(v)
            if len(v_norm) < 3:
                continue
            if re.search(r"(?:^|\s)" + re.escape(v_norm) + r"(?:\s|$)", question_norm):
                filters.setdefault(col, []).append(v)
                continue
            # Valores de una sola palabra: tolerar errores de tipeo leves.
            if " " not in v_norm:
                for qt in q_tokens:
                    if abs(len(qt) - len(v_norm)) > 2:
                        continue
                    if SequenceMatcher(None, qt, v_norm).ratio() >= 0.82:
                        filters.setdefault(col, []).append(v)
                        break
    return filters


def _detect_period(question_norm: str, df: pd.DataFrame, date_col: str | None):
    if not date_col or date_col not in df.columns:
        return None
    s = pd.to_datetime(df[date_col], errors="coerce")
    years = sorted({int(y) for y in s.dropna().dt.year.unique()})
    found_year = None
    for y in years:
        if str(y) in question_norm:
            found_year = y
            break
    found_month = None
    for name, num in MONTHS_ES.items():
        if name in question_norm:
            found_month = num
            break
    if found_month is None and found_year is None:
        return None
    return {"year": found_year, "month": found_month}


def _detect_operation(question_norm: str) -> str:
    if _fuzzy_contains_any(question_norm, WHY_WORDS):
        return "why"
    if _fuzzy_contains_any(question_norm, COMPARE_WORDS):
        return "compare"
    if _fuzzy_contains_any(question_norm, TREND_WORDS):
        return "trend"
    # "Cuánto" (monto) y "cuántos" (cantidad) son palabras distintas pero
    # casi idénticas entre sí como texto — aquí se compara exacto para no
    # confundir una pregunta de monto con una de conteo.
    if _contains_any(question_norm, COUNT_WORDS):
        return "count"
    if _fuzzy_contains_any(question_norm, TOP_WORDS):
        return "top"
    if _fuzzy_contains_any(question_norm, BOTTOM_WORDS):
        return "bottom"
    if _fuzzy_contains_any(question_norm, AVG_WORDS):
        return "avg"
    return "sum"


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "—"
    v = float(v)
    a = abs(v)
    if a >= 1_000_000_000:
        return f"{v/1_000_000_000:.1f}B"
    if a >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if a >= 1_000:
        return f"{v/1_000:.1f}K"
    return f"{v:,.0f}"


def answer_question(df: pd.DataFrame, schema: dict, question: str) -> dict:
    """Devuelve un dict con: status ('ok'|'ambiguo'|'sin_datos'), answer
    (texto listo para mostrar), detail (dict con metric/dimension/filtro/
    operación usados, para transparencia), chart_spec (o None), y table
    (DataFrame opcional para mostrar detalle).
    """
    q_norm = _norm(question)
    if not q_norm:
        return {"status": "sin_datos", "answer": "Escribe una pregunta para que pueda buscar la respuesta en tus datos.", "detail": {}, "chart_spec": None, "table": None}

    metrics = metric_candidates(df, schema)
    dims = dimension_candidates(df, schema)
    dates = [d for d in schema.get("dates", []) if d in df.columns]
    date_col = dates[0] if dates else None

    operation = _detect_operation(q_norm)
    prefer_money = _fuzzy_contains_any(q_norm, MONEY_WORDS)
    metric, metric_score = _best_column_match(q_norm, metrics, schema, prefer_money=prefer_money)
    dimension, dim_score = _best_column_match(q_norm, dims, schema)

    # "Quién" es una señal inequívoca de que se agrupa por persona, aunque
    # la pregunta no mencione literalmente el nombre de esa columna. Solo se
    # usa si el archivo de verdad tiene una columna clasificada como
    # persona/cliente/empleado — nunca se adivina una dimensión cualquiera.
    if not dimension and _fuzzy_contains_any(q_norm, WHO_WORDS):
        sem_for_dims = semantic_map(schema)
        person_dims = [d for d in dims if sem_for_dims.get(d) in {"name", "employee", "customer"}]
        if not person_dims and schema.get("full_name", {}).get("column") in dims:
            person_dims = [schema["full_name"]["column"]]
        if person_dims:
            dimension = person_dims[0]

    filters = _detect_filters(q_norm, df, schema, dims)
    period = _detect_period(q_norm, df, date_col)

    # Si no se detectó una métrica explícita en la pregunta, se usa la
    # principal del archivo — pero se avisa en el detalle, para que quede
    # claro que fue una suposición razonable, no algo que la pregunta pidió.
    metric_was_guessed = False
    if not metric:
        metric = choose_metric(df, schema)
        metric_was_guessed = True

    if not metric or metric not in df.columns:
        return {
            "status": "sin_datos",
            "answer": "No encuentro ninguna columna numérica en este archivo que pueda usar como indicador para responder.",
            "detail": {}, "chart_spec": None, "table": None,
        }

    # Aplicar filtros detectados (valores mencionados) + periodo.
    work = df.copy()
    applied_filters = []
    for col, values in filters.items():
        work = work[work[col].astype(str).isin(values)]
        applied_filters.append(f"{_label(schema, col)} = {', '.join(values)}")
    if period and date_col:
        s = pd.to_datetime(work[date_col], errors="coerce")
        if period.get("year"):
            work = work[s.dt.year == period["year"]]
            applied_filters.append(f"Año = {period['year']}")
        if period.get("month"):
            work = work[pd.to_datetime(work[date_col], errors="coerce").dt.month == period["month"]]
            applied_filters.append(f"Mes = {[k for k,v in MONTHS_ES.items() if v==period['month']][0].capitalize()}")

    if work.empty:
        return {
            "status": "sin_datos",
            "answer": f"No hay registros que cumplan {', '.join(applied_filters) if applied_filters else 'esa condición'}.",
            "detail": {"metric": metric, "filters": applied_filters}, "chart_spec": None, "table": None,
        }

    sem = semantic_map(schema)
    additive = sem.get(metric) in ADDITIVE
    # Si el motor semántico general no logró clasificar la columna (quedó
    # "unknown", como pasa con nombres genéricos tipo "Valor Horas Extra"),
    # pero la pregunta usa palabras de dinero Y el propio nombre de la
    # columna también las sugiere, se trata como sumable para esta
    # respuesta puntual — "cuánto se pagó" pide un total, no un promedio.
    if not additive and prefer_money and any(h in _norm(metric) for h in MONEY_NAME_HINTS):
        additive = True
    metric_label = _label(schema, metric)
    s = pd.to_numeric(work[metric], errors="coerce").dropna()

    detail = {
        "metric": metric, "metric_guessed": metric_was_guessed,
        "dimension": dimension, "filters": applied_filters, "operation": operation,
    }

    if operation == "why":
        # Reutiliza el mismo principio de "explicar con datos" sin inventar:
        # si no hay fecha, no se puede explicar un cambio en el tiempo.
        if not date_col:
            return {"status": "ambiguo", "answer": "Para explicar por qué cambió algo necesito una columna de fecha, y este archivo no tiene ninguna que pueda usar con confianza.", "detail": detail, "chart_spec": None, "table": None}
        operation = "trend"  # se resuelve mostrando la tendencia real; la causa se infiere de ahí, no se inventa.

    if operation == "count":
        n = len(work)
        answer = f"{n:,} registros" + (f" cumplen {', '.join(applied_filters)}." if applied_filters else " en total.")
        return {"status": "ok", "answer": answer, "detail": detail, "chart_spec": None, "table": None}

    if operation == "trend":
        if not date_col:
            return {"status": "ambiguo", "answer": "No hay ninguna columna de fecha en este archivo, así que no puedo mostrar una evolución en el tiempo.", "detail": detail, "chart_spec": None, "table": None}
        tmp = work[[date_col, metric]].copy()
        tmp[date_col] = pd.to_datetime(tmp[date_col], errors="coerce")
        tmp[metric] = pd.to_numeric(tmp[metric], errors="coerce")
        tmp = tmp.dropna()
        if tmp.empty:
            return {"status": "sin_datos", "answer": "No hay suficientes datos con fecha y valor numérico para mostrar una evolución.", "detail": detail, "chart_spec": None, "table": None}
        tmp["Periodo"] = tmp[date_col].dt.to_period("M").astype(str)
        grouped = tmp.groupby("Periodo")[metric].agg("sum" if additive else "mean").reset_index()
        first_v, last_v = grouped[metric].iloc[0], grouped[metric].iloc[-1]
        change = ((last_v - first_v) / first_v * 100) if first_v else None
        direction = "subió" if (change or 0) > 0 else "bajó" if (change or 0) is not None and change < 0 else "se mantuvo estable"
        answer = f"{metric_label} {direction}" + (f" {abs(change):.1f}%" if change is not None else "") + f" entre {grouped['Periodo'].iloc[0]} y {grouped['Periodo'].iloc[-1]} (de {_fmt(first_v)} a {_fmt(last_v)})."
        return {"status": "ok", "answer": answer, "detail": detail, "chart_spec": {"type": "trend", "x": grouped["Periodo"].tolist(), "y": grouped[metric].tolist(), "metric_label": metric_label}, "table": grouped.rename(columns={metric: metric_label})}

    if operation == "compare":
        if not dimension:
            return {"status": "ambiguo", "answer": "Para comparar necesito saber qué categoría comparar (por ejemplo, una ciudad o un producto), y no logré identificar cuál mencionas en tu Excel.", "detail": detail, "chart_spec": None, "table": None}
        grouped = work.groupby(dimension)[metric].agg("sum" if additive else "mean").sort_values(ascending=False)
        top = grouped.head(6)
        rows = ", ".join(f"{k}: {_fmt(v)}" for k, v in top.items())
        return {"status": "ok", "answer": f"Comparación de {metric_label} por {_label(schema, dimension)}: {rows}.", "detail": detail, "chart_spec": {"type": "bar", "x": top.index.tolist(), "y": top.values.tolist(), "metric_label": metric_label}, "table": top.rename("Valor").reset_index()}

    if operation in {"top", "bottom"}:
        if not dimension:
            # Sin dimensión no hay "quién"/"qué" que rankear — se informa en
            # vez de adivinar una columna al azar.
            candidates = ", ".join(_label(schema, d) for d in dims[:5]) or "ninguna"
            return {"status": "ambiguo", "answer": f"Puedo calcular el {'mayor' if operation=='top' else 'menor'} valor, pero no identifiqué sobre qué categoría (¿por persona? ¿por ciudad?). Categorías disponibles en este archivo: {candidates}.", "detail": detail, "chart_spec": None, "table": None}
        ascending = operation == "bottom"
        grouped = work.groupby(dimension)[metric].agg("sum" if additive else "mean").sort_values(ascending=ascending)
        top_n = grouped.head(10)
        leader_name, leader_val = top_n.index[0], top_n.iloc[0]
        qualifier = "mayor" if operation == "top" else "menor"
        answer = f"{leader_name} tiene el {qualifier} {metric_label.lower()}: {_fmt(leader_val)}."
        if applied_filters:
            answer += f" (filtrado por {', '.join(applied_filters)})"
        return {
            "status": "ok", "answer": answer, "detail": detail,
            "chart_spec": {"type": "bar", "x": top_n.index.tolist(), "y": top_n.values.tolist(), "metric_label": metric_label},
            "table": top_n.rename("Valor").reset_index(),
        }

    # sum / avg (por defecto)
    if s.empty:
        return {"status": "sin_datos", "answer": f"No hay valores numéricos utilizables en {metric_label.lower()} para esta selección.", "detail": detail, "chart_spec": None, "table": None}
    if operation == "avg":
        value = float(s.mean())
    else:
        # "Cuánto" pide un total, pero sumar algo no-aditivo (una
        # calificación, un porcentaje) no tiene sentido de negocio, así que
        # ahí se respeta el promedio aunque la pregunta diga "total".
        value = float(s.sum()) if additive else float(s.mean())
    verb = "El total de" if (operation != "avg" and additive) else "El promedio de"
    answer = f"{verb} {metric_label.lower()} es {_fmt(value)}"
    if applied_filters:
        answer += f", filtrado por {', '.join(applied_filters)}"
    answer += f" ({len(work):,} registros)."
    if metric_was_guessed and not applied_filters and not dimension:
        answer += f" (No detecté qué indicador pedías exactamente, así que usé {metric_label.lower()}, el principal de este archivo.)"

    chart_spec = None
    if dimension:
        grouped = work.groupby(dimension)[metric].agg("sum" if additive else "mean").sort_values(ascending=False).head(10)
        chart_spec = {"type": "bar", "x": grouped.index.tolist(), "y": grouped.values.tolist(), "metric_label": metric_label}

    return {"status": "ok", "answer": answer, "detail": detail, "chart_spec": chart_spec, "table": None}


def suggest_questions(df: pd.DataFrame, schema: dict) -> list[str]:
    """Preguntas sugeridas según lo que este archivo realmente tiene — nunca
    una lista fija igual para cualquier Excel."""
    metrics = metric_candidates(df, schema)
    dims = dimension_candidates(df, schema)
    dates = [d for d in schema.get("dates", []) if d in df.columns]
    out = []
    if metrics and dims:
        m, d = _label(schema, metrics[0]), _label(schema, dims[0])
        out.append(f"¿Quién tiene mayor {m.lower()}?")
        out.append(f"Compara {m.lower()} por {d.lower()}")
    if metrics and dates:
        out.append(f"¿Cómo evolucionó {_label(schema, metrics[0]).lower()}?")
    if metrics:
        out.append(f"¿Cuál es el total de {_label(schema, metrics[0]).lower()}?")
    if dims:
        out.append(f"¿Cuántos registros hay por {_label(schema, dims[0]).lower()}?")
    return out[:4]
