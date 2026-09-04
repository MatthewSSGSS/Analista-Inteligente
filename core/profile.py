from .cleaner import clean
from .schema import detect_schema
from .quality import assess


def profile_sheet(raw, context=None, structural_log=None):
    processed, log = clean(raw)
    schema = detect_schema(processed, context=context or {})
    quality = assess(processed, schema)
    # structural_log viene de core/pivot_flatten.py (aplanado de tablas
    # dinámicas: encabezados combinados, filas de total excluidas, celdas
    # heredadas rellenadas) — pasó ANTES que clean(), así que se antepone:
    # es lo primero que le "pasó" al archivo, antes de la limpieza normal.
    full_log = list(structural_log or []) + log
    return {"original": raw.copy(deep=True), "processed": processed,
            "profile": {"schema": schema, "quality": quality, "cleaning_log": full_log}}
