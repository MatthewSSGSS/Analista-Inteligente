
import re
import pandas as pd
import streamlit as st
from .dataset_classifier import classify_dataset

def _norm(x):
    return re.sub(r"[^a-z0-9]+", " ", str(x).lower()).strip()

@st.cache_data(show_spinner=False, max_entries=24, ttl=1800)
def detect_dataset_mode(df, schema):
    """Classify the sheet into a useful UI mode without changing source data."""
    cols = list(df.columns)
    n_rows, n_cols = len(df), len(cols)
    sem = schema.get("semantic", {}).get("columns", [])
    by_col = {x.get("column"): x.get("semantic_type") for x in sem}

    dates = list(schema.get("dates", []))
    metrics = list(schema.get("metrics", []))
    cats = list(schema.get("categorical", []))

    names = " ".join(_norm(c) for c in cols)
    catalog_words = [
        "producto", "product", "articulo", "item", "servicio", "plan",
        "paquete", "sku", "modelo", "referencia", "variante", "categoria",
        "segmento", "tipo", "caracteristica", "descripcion", "description",
        "precio", "price", "tarifa", "campaign", "campania", "vigencia",
        "instalacion", "beneficio", "incluye", "marca", "brand"
    ]
    catalog_hits = sum(1 for w in catalog_words if w in names)

    # A row-oriented reference/catalog dataset normally has no useful time axis,
    # few additive metrics, and several descriptive/category fields.
    non_date_metrics = [c for c in metrics if c not in dates]
    descriptive = [c for c in cats if c in df.columns]
    semantic_catalog = sum(
        1 for c, t in by_col.items()
        if t in {"product", "category", "brand", "price", "status", "supplier"}
    )

    text_like = 0
    for c in cols:
        s = df[c]
        if pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s):
            text_like += 1
    text_ratio = text_like / max(n_cols, 1)

    # Strong catalog/reference signature.
    strong_catalog = (
        not dates
        and n_rows > 0
        and (
            catalog_hits >= 3
            or semantic_catalog >= 2
            or ("price" in by_col.values() and len(descriptive) >= 2)
        )
        and len(non_date_metrics) <= 3
    )

    # Generic reference table: useful to browse/search, but not enough structure
    # to justify executive time-series/anomaly UI.
    generic_reference = (
        not dates
        and len(non_date_metrics) <= 2
        and n_cols >= 3
        and text_ratio >= 0.35
        and len(descriptive) >= 1
    )

    if strong_catalog:
        mode = "catalog"
        confidence = 0.90 if catalog_hits >= 4 else 0.82
    elif generic_reference:
        mode = "reference"
        confidence = 0.72
    else:
        mode = "analytical"
        confidence = 0.80

    # Tiny, documentation/instructions or lookup sheets are reference material,
    # not executive datasets. This also prevents a helper sheet from triggering
    # a full analytical dashboard when the workbook contains multiple sheets.
    if n_cols <= 2:
        mode = "reference"
        confidence = max(confidence, 0.86 if n_rows <= 20 else 0.76)
    elif n_rows <= 3 and n_cols >= 2:
        mode = "reference"
        confidence = max(confidence, 0.76)

    classification = classify_dataset(df, schema)
    # The universal classifier can refine the generic mode without forcing a
    # specific dashboard. It only enables capabilities supported by the data.
    mode_map = {"sales": "analytical", "customers": "analytical", "inventory": "analytical", "finance": "analytical", "survey": "analytical", "shopping": "reference", "tasks": "reference", "catalog": "catalog", "reference": "reference", "general": mode}
    refined_mode = mode_map.get(classification["kind"], mode)
    if refined_mode == "catalog" and classification["confidence"] >= 0.75:
        mode = "catalog"
    elif refined_mode == "reference" and classification["confidence"] >= 0.78:
        mode = "reference"
    elif refined_mode == "analytical" and classification["confidence"] >= 0.78:
        mode = "analytical"

    return {
        "mode": mode,
        "confidence": max(round(confidence, 2), classification["confidence"] if classification["kind"] in {"sales", "shopping", "tasks", "customers", "catalog"} else round(confidence, 2)),
        "label": {
            "catalog": "Catálogo / consulta",
            "reference": "Tabla de referencia",
            "analytical": "Análisis ejecutivo",
        }[mode],
        "reason": classification.get("reason") or {
            "catalog": "El archivo parece un catálogo o listado de elementos.",
            "reference": "El archivo parece una tabla de referencia.",
            "analytical": "El archivo contiene suficiente estructura para un análisis ejecutivo.",
        }[mode],
        "classification": classification,
    }
