"""Etiquetas de presentación en español.
Mantiene los nombres originales de las columnas y solo traduce conceptos técnicos de la interfaz.
"""

AGG_LABELS = {
    "__periodo_analisis__": "Periodo",
    "sum": "Total",
    "mean": "Promedio",
    "median": "Mediana",
    "count": "Registros",
    "min": "Mínimo",
    "max": "Máximo",
    "std": "Desviación estándar",
    "var": "Variación",
    "size": "Registros",
}

TECH_LABELS = {
    "__periodo_analisis__": "Periodo",
    "sum": "Total",
    "mean": "Promedio",
    "median": "Mediana",
    "count": "Registros",
    "min": "Mínimo",
    "max": "Máximo",
    "std": "Desviación estándar",
    "variance": "Variación",
    "unknown": "Sin clasificar",
    "metric": "Métrica",
    "metrics": "Métricas",
    "dimension": "Dimensión",
    "dimensions": "Dimensiones",
    "category": "Categoría",
    "date": "Fecha",
    "datetime": "Fecha y hora",
    "id": "Identificador",
}


def agg_label(value: str) -> str:
    return AGG_LABELS.get(str(value).lower(), str(value))


def pretty_technical(value: str) -> str:
    text = str(value).replace("_", " ").strip()
    return TECH_LABELS.get(text.lower(), text.title())


def clean_display_text(value: object) -> str:
    """Limpia etiquetas HTML heredadas para mostrar texto legible."""
    import html as _html
    import re as _re
    text = _html.unescape("" if value is None else str(value))
    text = _re.sub(r"<[^>]+>", "", text)
    text = _html.unescape(text)
    return _re.sub(r"[ \t]+", " ", text).strip()
