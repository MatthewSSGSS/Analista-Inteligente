"""Universal dataset classifier.

Classifies a sheet by the structure actually available, not by a fixed Excel
layout. The result is descriptive and also exposes which analysis families are
reasonable for the current data.
"""
from __future__ import annotations
import re
import pandas as pd


def _norm(v):
    s = str(v).lower().strip()
    s = re.sub(r"[^a-z0-9áéíóúüñ]+", " ", s)
    return s


def classify_dataset(df, schema):
    sem = schema.get("semantic", {})
    cols = sem.get("columns", [])
    types = {x.get("column"): x.get("semantic_type") for x in cols}
    names = " ".join(_norm(c) for c in df.columns)
    dates = [c for c in schema.get("dates", []) if c in df.columns]
    metrics = [c for c in (sem.get("metrics") or schema.get("metrics", [])) if c in df.columns]
    cats = [c for c in (sem.get("dimensions") or schema.get("categorical", [])) if c in df.columns]
    text_cols = [c for c, t in types.items() if c in df.columns and t in {"text", "description", "name"}]

    has_product = any(t in {"product", "item"} for t in types.values()) or bool(re.search(r"producto|articulo|artículo|plan|item", names))
    has_customer = any(t in {"customer", "name"} for t in types.values())
    has_sales = any(t in {"revenue", "profit", "quantity"} for t in types.values()) or bool(re.search(r"venta|ventas|ingreso|facturacion|facturación", names))
    has_price = any(t in {"price", "cost"} for t in types.values()) or bool(re.search(r"precio|costo|coste|gasto", names))
    has_status = any(t == "status" for t in types.values())
    has_task_words = any(t == "task" for t in types.values()) or bool(re.search(r"tarea|tareas|pendiente|to do|todo|actividad|responsable", names))
    has_purchase_words = bool(re.search(r"compra|compras|lista de compra|shopping", names))
    has_inventory = bool(re.search(r"inventario|stock|existencia|existencias", names))
    has_finance = bool(re.search(r"balance|flujo|finanzas|contabilidad|presupuesto|gasto", names))
    has_survey = bool(re.search(r"encuesta|satisfaccion|satisfacción|respuesta", names))

    capabilities = []
    if dates and metrics: capabilities += ["evolucion", "comparacion_periodos"]
    if cats and metrics: capabilities += ["ranking", "distribucion"]
    if len(metrics) >= 2: capabilities += ["relaciones"]
    if metrics: capabilities += ["estadisticas", "grafico_distribucion"]
    if any(t in {"city", "region", "country", "latitude", "longitude"} for t in types.values()) and any(t in {"city", "region", "country", "latitude", "longitude"} and any(x.get("column") == c and x.get("confidence", 0) >= 0.80 for x in cols) for c, t in types.items()): capabilities += ["geografia"]
    if any(t in {"product", "category", "brand"} for t in types.values()): capabilities += ["catalogo"]
    if has_status: capabilities += ["estados"]

    if has_task_words and not metrics:
        kind, label, confidence = "tasks", "Lista de tareas / actividades", 0.88
        reason = "Predominan elementos de actividad o seguimiento y no hay una estructura cuantitativa suficiente para forzar un dashboard financiero."
    elif has_purchase_words or (has_product and has_price and any(t == "quantity" for t in types.values()) and not dates):
        kind, label, confidence = "shopping", "Lista de compras / productos", 0.90
        reason = "Se detectan productos, cantidades y/o precios sin una necesidad clara de análisis temporal."
    elif has_sales and dates:
        kind, label, confidence = "sales", "Seguimiento de ventas", 0.93
        reason = "Se detectan métricas comerciales y una dimensión temporal; el análisis de evolución y comparación es pertinente."
    elif has_product and (has_price or len(cats) >= 2) and not dates:
        kind, label, confidence = "catalog", "Catálogo / listado de productos", 0.90
        reason = "Predominan productos o servicios y atributos descriptivos; el archivo se beneficia más de consulta, comparación y visualizaciones puntuales."
    elif has_customer and metrics:
        kind, label, confidence = "customers", "Base de clientes", 0.82
        reason = "Se identifican clientes y métricas cuantitativas; se habilitan segmentación, concentración y rankings."
    elif has_inventory:
        kind, label, confidence = "inventory", "Inventario / existencias", 0.86
        reason = "Se detectan conceptos de inventario o existencias; se priorizan cantidades, distribución y concentración."
    elif has_finance:
        kind, label, confidence = "finance", "Datos financieros", 0.82
        reason = "Se detectan conceptos financieros; se priorizan indicadores, distribuciones, evolución y comparaciones disponibles."
    elif has_survey:
        kind, label, confidence = "survey", "Encuesta / respuestas", 0.80
        reason = "Se detecta una estructura de encuesta o respuestas; se priorizan distribuciones, estados y relaciones entre respuestas."
    elif metrics or dates or cats:
        kind, label, confidence = "general", "Datos generales", 0.70
        reason = "No se identificó un tipo específico, así que el sistema habilita únicamente los análisis respaldados por la estructura disponible."
    else:
        kind, label, confidence = "reference", "Tabla de referencia / listado", 0.76
        reason = "No hay suficiente estructura cuantitativa o temporal; se priorizan lectura, búsqueda, calidad y tabla."

    # If the sheet has almost no data, do not pretend to have a strong model.
    if len(df) < 3:
        confidence = min(confidence, 0.65)

    return {
        "kind": kind,
        "label": label,
        "confidence": round(confidence, 2),
        "reason": reason,
        "capabilities": list(dict.fromkeys(capabilities)),
        "metrics": metrics,
        "dimensions": cats,
        "dates": dates,
        "rows": len(df),
        "columns": len(df.columns),
    }
