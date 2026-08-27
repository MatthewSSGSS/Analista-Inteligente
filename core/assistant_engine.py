"""AI assistant for Excel Intelligence.

The assistant never receives the whole workbook by default. It receives a compact
semantic context and can call safe, read-only pandas tools over the current
filtered DataFrame. An OpenAI Responses API key is optional; without one, a
small deterministic fallback handles common questions so the app still runs.
"""
from __future__ import annotations
from .numeric import numeric_series, safe_sum, safe_mean, safe_min, safe_max

import json
import os
import re
from typing import Any

import pandas as pd


def _fmt(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if isinstance(v, (int, float)):
        v = float(v)
        if abs(v) >= 1_000_000_000:
            return f"{v/1_000_000_000:.2f}B"
        if abs(v) >= 1_000_000:
            return f"{v/1_000_000:.2f}M"
        if abs(v) >= 1_000:
            return f"{v/1_000:.1f}K"
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return str(v)


def _semantic_map(schema: dict) -> dict[str, str]:
    return {
        x.get("column"): x.get("semantic_type", "unknown")
        for x in schema.get("semantic", {}).get("columns", [])
    }


def build_context(df: pd.DataFrame, schema: dict, profile: dict, mode_info: dict, dashboard: dict | None = None) -> str:
    sem = _semantic_map(schema)
    lines = [
        f"Modo: {mode_info.get('label', 'desconocido')}",
        f"Registros visibles: {len(df):,}",
        f"Columnas: {len(df.columns)}",
        "Columnas y significado: " + ", ".join(f"{c}→{sem.get(c,'unknown')}" for c in df.columns),
    ]
    if schema.get("dates"):
        for c in schema["dates"][:2]:
            if c in df.columns and df[c].notna().any():
                lines.append(f"Rango de {c}: {df[c].min()} a {df[c].max()}")
    if dashboard:
        lines.append(f"Métrica principal: {dashboard.get('primary_metric')}")
        if dashboard.get("growth") is not None:
            lines.append(f"Cambio del último periodo disponible: {dashboard['growth']:.2f}%")
        for i in dashboard.get("insights", [])[:5]:
            text = i.get("finding") or i.get("text") or i.get("message") or i.get("description") or i.get("title") or ""
            lines.append(f"Hallazgo existente: {text}")
    # Compact sample: enough for catalog questions without exposing the full file.
    if not df.empty:
        sample = df.head(8).copy()
        lines.append("Muestra de registros (solo referencia, no sustituye las herramientas):")
        lines.append(sample.to_json(orient="records", date_format="iso", force_ascii=False))
    return "\n".join(lines)


def _numeric(df, col):
    if col not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def execute_tool(df: pd.DataFrame, schema: dict, name: str, args: dict) -> dict:
    """Read-only analytics tools. Never mutates df."""
    limit = max(1, min(int(args.get("limit", 10)), 50))
    if name == "summarize_data":
        out = {"rows": len(df), "columns": list(map(str, df.columns))}
        numeric = []
        for c in df.columns:
            s = _numeric(df, c)
            if s.notna().any():
                numeric.append({"column": str(c), "sum": safe_sum(s), "mean": safe_mean(s), "min": safe_min(s), "max": safe_max(s)})
        out["numeric_summary"] = numeric[:20]
        out["nulls"] = {str(c): int(df[c].isna().sum()) for c in df.columns if df[c].isna().any()}
        return out

    if name == "group_compare":
        group = args.get("group_by")
        metric = args.get("metric")
        agg = args.get("aggregation", "sum")
        if group not in df.columns:
            return {"error": f"La columna de agrupación '{group}' no existe."}
        if metric not in df.columns:
            return {"error": f"La métrica '{metric}' no existe."}
        work = df[[group, metric]].copy()
        work[metric] = pd.to_numeric(work[metric], errors="coerce")
        work = work.dropna(subset=[group, metric])
        funcs = {"sum": "sum", "mean": "mean", "median": "median", "max": "max", "min": "min", "count": "count"}
        fn = funcs.get(agg, "sum")
        result = work.groupby(group, dropna=False)[metric].agg(fn).sort_values(ascending=False).head(limit)
        return {"group_by": group, "metric": metric, "aggregation": agg, "results": [{"group": str(k), "value": float(v)} for k, v in result.items()]}

    if name == "compare_values":
        group = args.get("group_by"); metric = args.get("metric"); values = args.get("values", [])
        if group not in df.columns or metric not in df.columns:
            return {"error": "La columna indicada no existe."}
        work = df[df[group].astype(str).isin([str(v) for v in values])].copy()
        work[metric] = pd.to_numeric(work[metric], errors="coerce")
        vals = work.groupby(group)[metric].sum().sort_values(ascending=False)
        return {"metric": metric, "comparison": [{"group": str(k), "value": float(v)} for k, v in vals.items()]}

    if name == "search_rows":
        query = str(args.get("query", "")).strip()
        if not query:
            return {"results": []}
        mask = pd.Series(False, index=df.index)
        for c in df.columns:
            mask |= df[c].astype(str).str.contains(query, case=False, na=False, regex=False)
        result = df.loc[mask].head(limit)
        return {"matches": int(mask.sum()), "results": result.to_dict(orient="records")}

    if name == "trend":
        date_col = args.get("date_column"); metric = args.get("metric"); agg = args.get("aggregation", "sum")
        if date_col not in df.columns or metric not in df.columns:
            return {"error": "La fecha o métrica indicada no existe."}
        work = df[[date_col, metric]].copy()
        work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
        work[metric] = pd.to_numeric(work[metric], errors="coerce")
        work = work.dropna()
        if work.empty:
            return {"error": "No hay fechas y métricas válidas."}
        grouped = work.set_index(date_col)[metric].resample("MS")
        vals = getattr(grouped, agg if agg in {"sum", "mean", "median", "max", "min"} else "sum")().tail(limit)
        return {"period": "mes", "metric": metric, "results": [{"period": str(k.date()), "value": float(v)} for k, v in vals.items()]}

    if name == "catalog_search":
        query = str(args.get("query", "")).strip().lower()
        if not query:
            return {"results": []}
        mask = pd.Series(False, index=df.index)
        for c in df.columns:
            mask |= df[c].astype(str).str.lower().str.contains(query, na=False, regex=False)
        return {"matches": int(mask.sum()), "results": df.loc[mask].head(limit).to_dict(orient="records")}

    return {"error": f"Herramienta desconocida: {name}"}


TOOLS = [
    {"type": "function", "name": "summarize_data", "description": "Resume los datos visibles: filas, columnas, métricas numéricas y nulos.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}, "strict": True},
    {"type": "function", "name": "group_compare", "description": "Agrupa una métrica por una dimensión y devuelve el ranking calculado.", "parameters": {"type": "object", "properties": {"group_by": {"type": "string"}, "metric": {"type": "string"}, "aggregation": {"type": "string", "enum": ["sum", "mean", "median", "max", "min", "count"]}, "limit": {"type": "integer"}}, "required": ["group_by", "metric", "aggregation", "limit"], "additionalProperties": False}, "strict": True},
    {"type": "function", "name": "compare_values", "description": "Compara valores concretos de una dimensión usando una métrica.", "parameters": {"type": "object", "properties": {"group_by": {"type": "string"}, "metric": {"type": "string"}, "values": {"type": "array", "items": {"type": "string"}}}, "required": ["group_by", "metric", "values"], "additionalProperties": False}, "strict": True},
    {"type": "function", "name": "search_rows", "description": "Busca texto en todas las columnas del conjunto visible y devuelve coincidencias.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query", "limit"], "additionalProperties": False}, "strict": True},
    {"type": "function", "name": "trend", "description": "Calcula una serie mensual de una métrica usando una columna de fecha.", "parameters": {"type": "object", "properties": {"date_column": {"type": "string"}, "metric": {"type": "string"}, "aggregation": {"type": "string", "enum": ["sum", "mean", "median", "max", "min"]}, "limit": {"type": "integer"}}, "required": ["date_column", "metric", "aggregation", "limit"], "additionalProperties": False}, "strict": True},
    {"type": "function", "name": "catalog_search", "description": "Busca productos, planes, servicios o registros de un catálogo.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query", "limit"], "additionalProperties": False}, "strict": True},
]


def _fallback(question: str, df: pd.DataFrame, schema: dict, mode_info: dict) -> str:
    q = question.lower()
    if mode_info.get("mode") in {"catalog", "reference"}:
        if any(w in q for w in ["buscar", "encuentra", "muéstrame", "muestrame", "plan", "producto"]):
            words = [w for w in re.findall(r"[\wáéíóúñ$.-]+", question) if len(w) >= 3]
            query = words[-1] if words else question
            r = execute_tool(df, schema, "catalog_search", {"query": query, "limit": 8})
            return f"Encontré {r.get('matches', 0)} coincidencias para **{query}**.\n\n" + "\n".join("- " + ", ".join(f"{k}: {v}" for k,v in row.items() if str(v) not in {'nan','None'}) for row in r.get("results", []))
        return "Puedo ayudarte a buscar, comparar y resumir este catálogo. Conecta una API de IA para respuestas conversacionales más profundas."
    sem = _semantic_map(schema)
    metric = next((c for c,t in sem.items() if t in {"revenue","profit","quantity","price","cost"}), None)
    group = next((c for c,t in sem.items() if t in {"city","region","product","category","brand"}), None)
    if metric and group and any(w in q for w in ["más", "mas", "mayor", "lider", "líder", "vende"]):
        r = execute_tool(df, schema, "group_compare", {"group_by": group, "metric": metric, "aggregation": "sum", "limit": 5})
        if r.get("results"):
            top = r["results"][0]
            return f"La dimensión **{group}** está liderada por **{top['group']}**, con {_fmt(top['value'])} de **{metric}**. Para una explicación más profunda, conecta la IA para que pueda comparar periodos, segmentos y hallazgos."
    return "Puedo analizar los datos visibles, pero necesito una API de IA para mantener una conversación completa. Puedes preguntar, por ejemplo: '¿dónde estamos vendiendo más?', 'compara Bogotá y Medellín' o '¿qué debería revisar?'."


def ask_assistant(question: str, df: pd.DataFrame, schema: dict, profile: dict, mode_info: dict, dashboard: dict | None = None, history: list[dict] | None = None, api_key: str | None = None, model: str = "gpt-5.5") -> str:
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        return _fallback(question, df, schema, mode_info)
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        context = build_context(df, schema, profile, mode_info, dashboard)
        instructions = """Eres el asistente de Excel Intelligence. Hablas español claro y profesional. Tu trabajo es ayudar a un jefe a entender un Excel y tomar mejores decisiones.

REGLAS:
- Usa únicamente los datos que recibes o que obtengas mediante tus herramientas. No inventes cifras.
- Si una interpretación es incierta, dilo claramente.
- Diferencia hecho, interpretación y recomendación.
- Para preguntas de negocio responde: 1) respuesta directa, 2) evidencia numérica, 3) por qué importa, 4) qué conviene revisar/acción sugerida.
- No fuerces análisis ejecutivo si el modo es catálogo o referencia. En esos casos prioriza búsqueda, comparación y explicación de registros.
- Si el usuario pregunta algo que requiere cálculo o ranking, usa una herramienta antes de responder.
- Sé conciso, pero suficientemente claro para que una persona no técnica entienda el resultado.
"""
        history = history or []
        input_items = []
        for m in history[-8:]:
            input_items.append({"role": m["role"], "content": m["content"]})
        input_items.append({"role": "user", "content": f"CONTEXTO ACTUAL DEL EXCEL:\n{context}\n\nPREGUNTA DEL USUARIO:\n{question}"})
        response = client.responses.create(model=model, instructions=instructions, input=input_items, tools=TOOLS, tool_choice="auto", max_output_tokens=1200)
        for _ in range(3):
            calls = [x for x in response.output if getattr(x, "type", None) == "function_call"]
            if not calls:
                return response.output_text.strip()
            tool_outputs = []
            for call in calls:
                try:
                    args = json.loads(call.arguments or "{}")
                    result = execute_tool(df, schema, call.name, args)
                except Exception as exc:
                    result = {"error": f"No se pudo ejecutar la consulta: {exc}"}
                tool_outputs.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(result, ensure_ascii=False, default=str)})
            response = client.responses.create(model=model, instructions=instructions, input=input_items + response.output + tool_outputs, tools=TOOLS, tool_choice="auto", max_output_tokens=1200)
        return response.output_text.strip()
    except Exception as exc:
        return f"No pude conectar con el asistente de IA. El dashboard sigue funcionando sin IA. Detalle técnico: `{type(exc).__name__}: {exc}`"
