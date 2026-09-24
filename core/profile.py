import pandas as pd

from .cleaner import clean
from .schema import detect_schema
from .quality import assess
from .performance import columna_meta, medida_de_cumplimiento
from .registro_largo import girar_por_registro


def _metrica_al_frente(schema, medida):
    """Deja `medida` primera en el esquema: es la que el panel toma como principal."""
    for lista in (schema.get("metrics"), schema.get("semantic", {}).get("metrics")):
        if lista and medida in lista:
            lista.remove(medida)
            lista.insert(0, medida)


def _metrica_con_meta(df, schema):
    """(métrica, su meta) de la medida para la que se fijó esa meta.

    Varias medidas pueden compartir el mismo presupuesto («Pry · Ejecución» y
    «Pry · Digitadas» contra «Pry · Presupuesto»): se queda la que está a la
    ESCALA de la meta, porque una meta se fija al tamaño de lo que mide —lo
    digitado es un paso intermedio y se queda corto contra ella—. A igual
    escala manda la que trae dato en más filas.
    """
    metricas = schema.get("semantic", {}).get("metrics") or schema.get("metrics", [])
    candidatas = []
    for m in metricas:
        if m not in df.columns:
            continue
        meta = columna_meta(df, schema, m)
        if meta is None:
            continue
        total = float(pd.to_numeric(df[m], errors="coerce").sum())
        objetivo = float(pd.to_numeric(df[meta], errors="coerce").sum())
        cerca = min(total, objetivo) / max(total, objetivo) if total > 0 and objetivo > 0 else 0.0
        candidatas.append((round(cerca, 2), int(df[m].notna().sum()), m, meta))
    if not candidatas:
        return None
    _, _, m, meta = max(candidatas, key=lambda x: (x[0], x[1]))
    return m, meta


def profile_sheet(raw, context=None, structural_log=None):
    # Un informe convertido marca que sus celdas vacías no son cero (ver clean).
    processed, log = clean(raw, faltantes_son_cero=(context or {}).get("faltantes_son_cero", True))
    schema = detect_schema(processed, context=context or {})
    # Meta y resultado en FILAS (una columna «Registro» con Presupuesto /
    # Ejecución) se giran a columnas para que la meta quede donde el resto del
    # panel la busca. Necesita el esquema —para no sumar una fecha como si
    # fuera una cifra—, así que el esquema se vuelve a detectar sobre la tabla
    # ya girada, que tiene otras columnas. Ver core/registro_largo.py.
    girada, log_giro = girar_por_registro(processed, schema)
    if log_giro:
        processed, log = girada, list(log) + log_giro
        schema = detect_schema(processed, context=context or {})
    cumplimiento = medida_de_cumplimiento(processed, schema)
    con_meta = None
    if cumplimiento is not None:
        # La medida con la que el propio archivo calcula su % de cumplimiento
        # pasa a ser la primera: es la que el panel toma como principal (KPIs,
        # cuadro comparativo, resumen). Ver medida_de_cumplimiento.
        _metrica_al_frente(schema, cumplimiento[0])
    elif log_giro:
        # Solo cuando la tabla se giró aquí: entonces la meta y el resultado
        # quedaron en columnas porque ESTE módulo los separó, así que se sabe
        # cuál mide contra cuál, y esa es la medida que el archivo lleva. Sin
        # el giro no se toca la elección de siempre: en un archivo que ya venía
        # ancho, una medida chica con meta no tiene por qué desplazar a la
        # principal (lo fija tests/comparaciones_test.py con ALTAS y Altas Eje).
        con_meta = _metrica_con_meta(processed, schema)
        if con_meta is not None:
            _metrica_al_frente(schema, con_meta[0])
            # No basta con dejarla primera: quien arma el tablero reordena las
            # métricas por su tipo semántico (los ingresos van antes que una
            # cantidad), así que una medida con meta quedaba otra vez detrás.
            schema["metrica_sugerida"] = con_meta[0]
    quality = assess(processed, schema)
    # structural_log viene de core/pivot_flatten.py (aplanado de tablas
    # dinámicas: encabezados combinados, filas de total excluidas, celdas
    # heredadas rellenadas) — pasó ANTES que clean(), así que se antepone:
    # es lo primero que le "pasó" al archivo, antes de la limpieza normal.
    full_log = list(structural_log or []) + log
    if cumplimiento is not None:
        medida, meta, porcentaje = cumplimiento
        full_log.append(f"«{porcentaje}» equivale a «{medida}» ÷ «{meta}»: se toma «{medida}» como la "
                        f"métrica principal y «{meta}» como su meta.")
    elif con_meta is not None:
        full_log.append(f"«{con_meta[0]}» trae su propia meta («{con_meta[1]}»): se toma como métrica "
                        f"principal, para que el panel compare contra la meta y no por volumen.")
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
