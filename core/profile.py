from .cleaner import clean
from .schema import detect_schema
from .quality import assess


def profile_sheet(raw, context=None, structural_log=None):
    # Un informe convertido marca que sus celdas vacías no son cero (ver clean).
    processed, log = clean(raw, faltantes_son_cero=(context or {}).get("faltantes_son_cero", True))
    schema = detect_schema(processed, context=context or {})
    quality = assess(processed, schema)
    # structural_log viene de core/pivot_flatten.py (aplanado de tablas
    # dinámicas: encabezados combinados, filas de total excluidas, celdas
    # heredadas rellenadas) — pasó ANTES que clean(), así que se antepone:
    # es lo primero que le "pasó" al archivo, antes de la limpieza normal.
    full_log = list(structural_log or []) + log
    # "original" era una copia PROFUNDA de la hoja entera, guardada en la
    # sesión mientras el archivo estuviera abierto... y que no lee nadie
    # (comprobado en todo el proyecto). En la práctica duplicaba la memoria
    # de cada hoja sin dar nada a cambio: con 150.000 filas el pico de la
    # carga llegaba a 817 MB, peligrosamente cerca del límite del servidor.
    #
    # Se conservan solo las primeras filas, que es lo único para lo que
    # serviría —mostrar cómo se veía el archivo antes de limpiarlo— a un
    # costo insignificante.
    return {"original_muestra": raw.head(100).copy(), "processed": processed,
            "profile": {"schema": schema, "quality": quality, "cleaning_log": full_log}}
