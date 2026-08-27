from .cleaner import clean
from .schema import detect_schema
from .quality import assess


def profile_sheet(raw, context=None):
    processed, log = clean(raw)
    schema = detect_schema(processed, context=context or {})
    quality = assess(processed, schema)
    return {"original": raw.copy(deep=True), "processed": processed,
            "profile": {"schema": schema, "quality": quality, "cleaning_log": log}}
