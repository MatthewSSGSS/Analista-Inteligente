import re
import unicodedata
import pandas as pd
from .numeric import normalize_missing_series

# Zona horaria única de todo el análisis. Colombia no usa horario de verano,
# así que es siempre UTC-5: no hay saltos ni ambigüedades a lo largo del año.
COLOMBIA_TZ = "America/Bogota"

# Un valor de fecha que TRAE zona horaria pegada: "...10:30:00+00:00",
# "...14:45-0500", "...09:00Z". Se exige que haya una hora (\d{2}:\d{2})
# antes del desfase para no confundirlo con cualquier texto que termine en
# algo parecido a un número con signo.
_TZ_VALUE_RE = re.compile(r"\d{1,2}:\d{2}.*?(?:Z|[+-]\d{2}:?\d{2})\s*$", re.I)


def normalize_timezones(df: pd.DataFrame) -> list[str]:
    """Pasa TODA columna con zona horaria a hora de Colombia y le quita la
    zona. Devuelve los nombres de las columnas convertidas.

    Por qué aquí y no en el detector de fechas: este es el primer punto que
    toca los datos (`clean()` corre antes que `detect_schema`, que a su vez
    corre antes que la conversión de core/dates.py). Los dos intentos
    anteriores parchearon puntos más abajo del flujo y el archivo ya había
    reventado antes de llegar: el error "Mixed timezones detected" aparecía
    en la CLASIFICACIÓN semántica, no en la conversión. Normalizando una
    sola vez en la entrada, ninguna parte del sistema vuelve a ver una
    columna con zonas mezcladas — sin importar por dónde la lea.

    El mecanismo es el que recomienda el propio mensaje de error de pandas:
    `utc=True` al interpretar (eso nunca falla, aunque cada fila traiga un
    desfase distinto) y después convertir a Colombia. Así "10:00+00:00" y
    "14:30-05:00" quedan comparables entre sí, referidas al mismo reloj.
    """
    convertidas = []
    for col in df.columns:
        serie = df[col]
        try:
            # Caso 1: la columna ya es fecha CON zona (un solo desfase).
            if isinstance(serie.dtype, pd.DatetimeTZDtype):
                df[col] = serie.dt.tz_convert(COLOMBIA_TZ).dt.tz_localize(None)
                convertidas.append(str(col))
                continue

            if not (serie.dtype == object or pd.api.types.is_string_dtype(serie)):
                continue

            # Caso 2: el desfase viene pegado al valor, que es como Excel lo
            # guarda (su formato NO admite zona horaria en una celda de
            # fecha, así que llega como texto).
            #
            # Se revisa la columna ENTERA, valor por valor, y basta UNO con
            # zona para actuar. Las dos versiones anteriores fallaron por
            # confiar en atajos: miraban solo las primeras 200 filas y exigían
            # que el 80% trajera zona. Un archivo donde solo algunas filas la
            # traen —o donde la primera aparece más abajo de la fila 200— se
            # saltaba entero, y el error volvía a aparecer.
            texto = serie.astype(str)
            con_zona = texto.str.contains(_TZ_VALUE_RE, na=False)
            if not bool(con_zona.any()):
                continue

            # Se convierten SOLO los valores que traen zona; el resto de la
            # columna no se toca. Es deliberado: un valor sin zona ya está en
            # hora local, y reinterpretarlo arriesgaría además invertir día y
            # mes (la lógica de formatos ambiguos vive en core/dates.py, con
            # sus propias reglas). Aquí el objetivo es uno solo: que ningún
            # valor conserve zona horaria.
            aware = pd.to_datetime(texto[con_zona], errors="coerce", utc=True, format="mixed")
            local = aware.dt.tz_convert(COLOMBIA_TZ).dt.tz_localize(None)
            # Se reescribe en texto ISO, sin desfase. Así la columna sigue
            # siendo lo que era y el detector de fechas de siempre la
            # interpreta con sus reglas, sin ambigüedad de día/mes.
            reescrito = local.dt.strftime("%Y-%m-%d %H:%M:%S")
            validos = reescrito.notna()
            if not bool(validos.any()):
                continue
            nueva = serie.astype(object).copy()
            nueva.loc[reescrito.index[validos]] = reescrito[validos]
            df[col] = nueva
            convertidas.append(str(col))
        except Exception:
            # Nunca tumbar la carga por esto: si una columna rara no se deja
            # normalizar, se queda como está y el resto del archivo carga.
            continue

    # ===== Red de seguridad =====
    # Segunda pasada: si después de todo lo anterior QUEDA algún valor con
    # zona horaria, se le arranca el desfase por texto plano. Es un recurso
    # bruto —no convierte a hora de Colombia, solo deja el valor tal como
    # está escrito, sin zona— y por eso va al final: solo actúa sobre lo que
    # la conversión ordenada no supo interpretar.
    #
    # Existe porque este error tumbó la carga tres veces seguidas, cada vez
    # por un camino distinto que no se había previsto. Perder la precisión
    # de la zona en un puñado de valores raros es mucho mejor que dejar al
    # usuario sin poder abrir su archivo.
    for col in df.columns:
        try:
            serie = df[col]
            if not (serie.dtype == object or pd.api.types.is_string_dtype(serie)):
                continue
            texto = serie.astype(str)
            pendientes = texto.str.contains(_TZ_VALUE_RE, na=False)
            if not bool(pendientes.any()):
                continue
            limpio = texto[pendientes].str.replace(r"\s*(?:Z|[+-]\d{2}:?\d{2})\s*$", "", regex=True)
            nueva = serie.astype(object).copy()
            nueva.loc[limpio.index] = limpio
            df[col] = nueva
            if str(col) not in convertidas:
                convertidas.append(str(col))
        except Exception:
            continue
    return convertidas


def _normalize_key(value) -> str:
    s = str(value)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _consolidate_spelling_variants(series: pd.Series):
    """Une valores que son el mismo dato escrito distinto -p. ej. "CAV",
    "Cav" y "cav " en una columna de puestos- para que no se cuenten ni se
    grafiquen como categorías separadas. La variante más frecuente es la que
    se conserva. Solo toca columnas donde de verdad existe esa duplicación;
    si todo ya está escrito de forma consistente, no cambia nada.

    Se trabaja sobre los valores DISTINTOS, no sobre las filas: normalizar
    (quitar tildes, mayúsculas, espacios) es caro y una columna de 200.000
    filas suele tener unas pocas decenas de valores distintos. La versión
    anterior normalizaba fila por fila —dos veces, además: una para agrupar
    y otra al reemplazar— y encima recorría la columna entera por cada clave
    candidata (`non_null[keys == k]` dentro del bucle), lo que la volvía
    cuadrática. El resultado es el mismo, solo que proporcional a los
    valores distintos en vez de al tamaño del archivo.
    """
    non_null = series.dropna()
    if non_null.empty:
        return series, 0

    counts = non_null.value_counts()
    key_by_value = {v: _normalize_key(v) for v in counts.index}
    by_key: dict[str, list] = {}
    for value, key in key_by_value.items():
        by_key.setdefault(key, []).append(value)

    # Solo hay variante cuando una misma clave normalizada llega escrita de
    # más de una forma (con una sola forma no hay nada que unificar).
    canonical = {
        key: counts[values].idxmax()
        for key, values in by_key.items()
        if len(values) > 1
    }
    if not canonical:
        return series, 0

    replacements = {
        value: canonical[key_by_value[value]]
        for value in counts.index
        if key_by_value[value] in canonical and canonical[key_by_value[value]] != value
    }
    if not replacements:
        return series, 0
    changed = int(non_null.isin(list(replacements)).sum())
    return series.replace(replacements), changed


def clean(df):
    out=df.copy(deep=True); log=[]
    # PRIMER paso, antes que cualquier otra cosa: unificar zonas horarias.
    # Todo lo que venga con desfase horario pasa a hora de Colombia y pierde
    # la zona, para que ninguna etapa posterior (limpieza, clasificación
    # semántica, detección de fechas, gráficos) se encuentre nunca con una
    # columna de zonas mezcladas.
    zonas = normalize_timezones(out)
    if zonas:
        log.append(
            f"{len(zonas)} columna(s) de fecha con zona horaria convertidas a hora de Colombia "
            f"(UTC-5): {', '.join(zonas[:5])}" + ("…" if len(zonas) > 5 else "") + "."
        )
    seen={}
    cols=[]
    for c in out.columns:
        base=re.sub(r"\s+"," ",str(c).replace("\n"," ").replace("\r"," ").strip()) or "Columna"
        seen[base]=seen.get(base,0)+1
        cols.append(base if seen[base]==1 else f"{base}_{seen[base]}")
    if list(out.columns)!=cols: out.columns=cols; log.append("Nombres de columnas normalizados.")
    missing_replaced = 0
    variants_merged_total = 0
    variant_columns = []
    for c in out.select_dtypes(include=["object","string"]).columns:
        before = out[c].isna().sum()
        out[c]=out[c].astype("string").str.replace(r"[\r\n\t]"," ",regex=True).str.strip()
        out[c] = normalize_missing_series(out[c])
        # Excel often stores numeric columns as text when the sheet contains a
        # title/header row. Recover numeric columns when most non-empty values
        # are numeric, without touching true categorical columns such as Mes.
        probe = pd.to_numeric(out[c], errors="coerce")
        nonempty = out[c].notna().sum()
        if nonempty and probe.notna().sum() / nonempty >= 0.85:
            out[c] = probe
        else:
            out[c], merged = _consolidate_spelling_variants(out[c])
            if merged:
                variants_merged_total += merged
                variant_columns.append(str(c))
        missing_replaced += int(out[c].isna().sum() - before)
    if variants_merged_total:
        cols_txt = ", ".join(variant_columns[:5]) + ("…" if len(variant_columns) > 5 else "")
        log.append(f"{variants_merged_total:,} valores unificados por escribirse distinto (mayúsculas/espacios/tildes) siendo el mismo dato, en: {cols_txt}.")
    # En columnas que ya son numéricas, los faltantes pasan a cero para que
    # cualquier cálculo posterior sea estable. Las columnas de texto/categoría
    # conservan sus faltantes para no convertir una categoría ausente en "0".
    numeric_cols = out.select_dtypes(include=["number"]).columns
    numeric_missing = int(out[numeric_cols].isna().sum().sum()) if len(numeric_cols) else 0
    if len(numeric_cols):
        out[numeric_cols] = out[numeric_cols].replace([float("inf"), float("-inf")], pd.NA).fillna(0)
    if numeric_missing:
        log.append(f"{numeric_missing:,} valores numéricos faltantes convertidos a 0 para los cálculos.")
    dup=int(out.duplicated().sum())
    if dup: log.append(f"{dup:,} filas duplicadas detectadas; no se eliminaron automáticamente.")
    return out,log
