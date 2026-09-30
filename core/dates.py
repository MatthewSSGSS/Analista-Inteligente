import re
import unicodedata
from datetime import timedelta, timezone

import pandas as pd

DATE_NAME = re.compile(
    r"(fecha|date|datetime|timestamp|created|updated|modified|period|periodo|"
    r"dia|día|mes|month|year|año)", re.IGNORECASE
)
# Fechas en formato ISO (YYYY-MM-DD, con u sin hora) NO son ambiguas: el año
# siempre va primero. pandas normalmente respeta esto, pero con
# dayfirst=True puede invertir día y mes igualmente (confirmado en pruebas),
# corrompiendo silenciosamente cualquier fecha con día <=12 (p. ej. "2025-02-01"
# se vuelve "2025-01-02"). Por eso el formato ISO se detecta aparte y se
# parsea siempre con dayfirst=False; dayfirst=True solo se usa para formatos
# genuinamente ambiguos como "01/02/2025" (común en archivos en español).
ISO_DATE_RE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}([ T]\d{1,2}:\d{2}(:\d{2})?)?$")
MONTHS = {
    "enero": 1, "ene": 1, "january": 1, "jan": 1,
    "febrero": 2, "feb": 2, "february": 2,
    "marzo": 3, "mar": 3, "march": 3,
    "abril": 4, "abr": 4, "april": 4, "apr": 4,
    "mayo": 5, "may": 5,
    "junio": 6, "jun": 6, "june": 6,
    "julio": 7, "jul": 7, "july": 7,
    "agosto": 8, "ago": 8, "august": 8, "aug": 8,
    "septiembre": 9, "setiembre": 9, "sep": 9, "sept": 9, "september": 9,
    "octubre": 10, "oct": 10, "october": 10,
    "noviembre": 11, "nov": 11, "november": 11,
    "diciembre": 12, "dic": 12, "december": 12, "dec": 12,
}

# Nombres de mes para mostrar en pantalla ("Ene 2026" / "Enero 2026"). No se
# usa strftime("%b"/"%B") para esto: ese formato depende del locale del
# sistema operativo, y la mayoría de los entornos donde se despliega esta
# app (contenedores, Streamlit Cloud) no tienen el locale es_ES instalado —
# strftime("%b") ahí muestra el mes en inglés ("Jan 2026") aunque toda la
# interfaz esté en español. Un diccionario fijo no depende de nada del
# entorno de ejecución.
MONTH_ABBR_ES = {1:"Ene",2:"Feb",3:"Mar",4:"Abr",5:"May",6:"Jun",7:"Jul",8:"Ago",9:"Sep",10:"Oct",11:"Nov",12:"Dic"}
MONTH_FULL_ES = {1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"}


def format_month_year(value, full: bool = False) -> str:
    """'Ene 2026' (full=False) o 'Enero 2026' (full=True) a partir de
    cualquier valor convertible a fecha, en español, sin depender del
    locale del sistema. Devuelve "—" si el valor es nulo/no es una fecha
    válida."""
    if value is None:
        return "—"
    try:
        ts = value if isinstance(value, pd.Timestamp) else pd.Timestamp(value)
    except (ValueError, TypeError):
        return "—"
    if pd.isna(ts):
        return "—"
    names = MONTH_FULL_ES if full else MONTH_ABBR_ES
    return f"{names[ts.month]} {ts.year}"


def _norm(v):
    s = "" if v is None else str(v)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s.lower().strip())


def month_number_series(s):
    """Número de mes (1-12) por cada valor, o nulo si no es un nombre de mes.

    Se resuelve sobre los valores DISTINTOS y luego se mapea: `_norm` hace
    normalización Unicode y expresiones regulares por valor, y aplicarlo
    fila por fila era, medido, el mayor costo de perfilar una hoja —8,3 de
    13 segundos, con 640.000 llamadas—. Una columna de 40.000 filas rara vez
    tiene más de unas decenas de valores distintos, y un nombre de mes solo
    puede ser uno de doce, así que el trabajo real es diminuto. El resultado
    es idéntico: mismo mapeo, calculado una vez por valor en vez de una vez
    por fila."""
    # Y la limpieza (texto, sin espacios, minúsculas) también va sobre los
    # valores distintos: aplicada a las 70.000 filas de una base costaba más
    # que todo lo demás. `factorize` agrupa valores iguales en C; el
    # resultado por fila es el mismo.
    codigos, unicos = pd.factorize(s, use_na_sentinel=True)
    if not len(unicos):
        return pd.Series(pd.NA, index=s.index, dtype="Int64")
    x = pd.Series(unicos).astype("string").str.strip().str.lower()
    distintos = x.dropna().unique()
    # Segundo filtro, también por costo: un nombre de mes es una palabra
    # corta y sin dígitos. Descartar por longitud y por "es alfabético"
    # cuesta microsegundos y evita normalizar valores que nunca podrían
    # serlo — que es el caso de las columnas numéricas y de códigos, donde
    # cada fila es un valor distinto (60.000 normalizaciones por columna,
    # para nada). Es equivalente: todas las claves de MONTHS son palabras,
    # así que cualquier valor que este filtro descarta habría dado nulo.
    posibles = [v for v in distintos if len(v) <= 12 and str(v).replace(" ", "").isalpha()]
    equivalencias = {v: MONTHS.get(_norm(v), pd.NA) for v in posibles}
    por_unico = x.map(equivalencias).astype("Int64").array
    return pd.Series(por_unico.take(codigos, allow_fill=True), index=s.index)


def is_month_name_series(s):
    m = month_number_series(s)
    valid = m.notna()
    return bool(valid.any() and valid.mean() >= 0.80)


def extract_year_hint(*texts):
    """El año que nombra el archivo o la hoja ("Ventas 2026", "reporte_2026").

    Sirve de respaldo cuando los meses del archivo no traen año ("Oct", "Ene"):
    lo usan core/informe.py al ordenar un informe y core/pivot_flatten.py al
    despivotar meses que están como columnas.

    El límite se marca con "no haya otro dígito al lado" y no con `\\b`:
    el guion bajo es un carácter de palabra, así que `\\b` NO existe entre
    "_" y "2" y el año de "reporte_2026.xlsx" —la forma de nombrar un
    archivo más común que hay— no se encontraba nunca. Con este límite sigue
    sin colarse un año dentro de un número más largo ("120260").
    """
    for text in texts:
        if not text:
            continue
        m = re.search(r"(?<!\d)(19\d{2}|20\d{2}|21\d{2})(?!\d)", str(text))
        if m:
            return int(m.group(1))
    return None


def month_year_series(months, years=None, year_hint=None):
    m = month_number_series(months)
    if years is not None:
        y = pd.to_numeric(years, errors="coerce")
        y = y.where(y.between(1900, 2100))
    else:
        y = pd.Series(year_hint if year_hint else 2000, index=months.index, dtype="float64")
    if year_hint and years is not None:
        y = y.fillna(year_hint)
    out = pd.Series(pd.NaT, index=months.index, dtype="datetime64[ns]")
    valid = m.notna() & y.notna()
    if valid.any():
        vals = pd.to_datetime(
            {"year": y[valid].astype(int), "month": m[valid].astype(int), "day": 1},
            errors="coerce",
        )
        out.loc[valid] = vals
    return out


def excel_serial(s):
    numeric = pd.to_numeric(s, errors="coerce")
    valid = numeric.between(1, 60000)
    result = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    if valid.any():
        safe = numeric[valid]
        result.loc[safe.index] = pd.Timestamp("1899-12-30") + pd.to_timedelta(safe, unit="D")
    return result


def unix_timestamp(s):
    numeric = pd.to_numeric(s, errors="coerce")
    valid = numeric.between(600_000_000, 4_200_000_000)
    result = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    if valid.any():
        safe = numeric[valid]
        result.loc[safe.index] = pd.to_datetime(safe, unit="s", errors="coerce")
    return result


def yyyymm_series(s):
    """"Periodo" numérico tipo 202608 (= agosto 2026) — muy común en
    exportes de sistemas de BI/ERP como columna "Periodo"/"Período". Se
    interpreta como el día 1 de ese mes. Nunca se confunde con
    excel_serial (1-60000) ni con unix_timestamp (600 millones+): un
    AAAAMM real cae siempre entre 190001 y 210012, un rango que ninguno de
    los otros dos toca."""
    numeric = pd.to_numeric(s, errors="coerce")
    year = numeric // 100
    month = numeric % 100
    valid = numeric.between(190001, 210012) & month.between(1, 12)
    result = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    if valid.any():
        vals = pd.to_datetime(
            {"year": year[valid].astype(int), "month": month[valid].astype(int), "day": 1},
            errors="coerce",
        )
        result.loc[valid[valid].index] = vals
    return result


# Sufijo de zona horaria al final de una fecha escrita como texto:
# "+00:00", "-05:00", "-0500" o la "Z" de UTC.
TZ_SUFFIX_RE = re.compile(r"\s*(?:Z|[+-]\d{2}:?\d{2})$", re.I)
_TZ_SUFFIX_RE = TZ_SUFFIX_RE  # alias interno histórico

# El mismo sufijo, pero reconociendo TODAS las formas en que un archivo real
# escribe la zona. `TZ_SUFFIX_RE` (arriba) solo cubre "+00:00", "-0500" y "Z",
# y esa estrechez fue justo lo que hizo fallar dos intentos de arreglo: con
# "-05" (desfase de dos dígitos), " UTC" o "GMT-5" el desfase sobrevivía sin
# que nadie lo viera. Aquí se usa para decidir qué valores hay que pasar a
# hora de Colombia, así que dejar uno fuera significa reportarlo cinco horas
# corrido.
# Se exige que ANTES del desfase haya una hora ("10:30", "10:30:00"). Sin esa
# condición, el patrón mordía la propia fecha: en "2026-01-15" el "-15" final
# tiene exactamente la forma de un desfase de dos dígitos, así que toda fecha
# normal se habría dado por "con zona" y se habría corrido cinco horas al día
# anterior. Una zona horaria solo aparece detrás de una hora.
# La FECHA dentro de un valor de texto, en las dos formas que existen:
# año primero ("2026-01-15", "2026/1/5") o día primero ("15/01/2026",
# "15-1-26"). Se busca en cualquier posición, no solo al principio, para
# cubrir valores como "Fecha: 2026-01-15". Ver `solo_fecha`.
FECHA_EN_TEXTO_RE = re.compile(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})")

# La HORA al final de un valor de fecha, con su zona horaria si la trae:
# " 10:30", "T10:30:00", " 10:30:00.123+00:00", " 23:30 -05", " 10:00 UTC".
# Se usa para borrarla del texto antes de interpretarlo — ver `sin_hora`.
HORA_EN_TEXTO_RE = re.compile(
    r"[T\s]+\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\s*"
    r"(?:Z|[+-]\d{2}(?::?\d{2})?|(?:UTC|GMT)(?:[+-]\d{1,2}(?::?\d{2})?)?)?\s*$",
    re.I,
)

TZ_EN_TEXTO_RE = re.compile(
    r"\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\s*"
    r"(?:Z|[+-]\d{2}(?::?\d{2})?|(?:UTC|GMT)(?:[+-]\d{1,2}(?::?\d{2})?)?)\s*$",
    re.I,
)


def _parse_seguro(texto, **kwargs):
    """Interpreta texto como fecha SIN que pandas pueda quejarse de zonas.

    Dos garantías, y las dos hacen falta:

    - `utc=True`: es la única forma documentada de que `to_datetime` no
      lance "Mixed timezones detected". Funciona con desfases distintos en
      cada fila, con mezcla de valores con y sin desfase, y con formatos que
      ningún patrón previó. No hay input que lo rompa.
    - `tz_localize(None)` después, SIN convertir: devuelve la hora tal como
      estaba escrita. No se convierte aquí porque a esta altura los valores
      ya vienen en hora de Colombia —lo hizo `core/cleaner.normalize_timezones`,
      primer paso de la limpieza— y volver a convertir los correría otras
      cinco horas.

    Se usa en `detect_date`, que es donde el error tumbó la carga cuatro
    veces seguidas, cada vez por una llamada distinta que se había quedado
    sin `utc=True`.
    """
    fechas = pd.to_datetime(texto, errors="coerce", utc=True, format="mixed", **kwargs)
    tz = getattr(getattr(fechas, "dt", None), "tz", None)
    return fechas.dt.tz_localize(None) if tz is not None else fechas


def solo_fecha(texto):
    """Se queda con la FECHA de cada valor y descarta todo lo que venga
    detrás: hora, zona horaria, lo que sea.

    Es el enfoque contrario a `sin_hora`, y la diferencia importa. Quitar la
    hora obliga a reconocer TODAS las formas en que un archivo puede
    escribirla al final del valor ("+00:00", "Z", "-05", " UTC", "GMT-5",
    "+00:00:00", nombres de zona...). Ese camino falló cuatro veces
    seguidas: siempre aparecía un formato más que el patrón no cubría, el
    desfase sobrevivía y pandas tumbaba la carga del archivo entero con
    "Mixed timezones detected".

    Quedarse con la fecha solo obliga a reconocer la FECHA, que tiene dos
    formas y son conocidas. Lo que haya después da igual: se descarta sin
    mirarlo. Por eso esta versión no depende de acertar con el formato del
    final, que es justo lo que no se podía garantizar.

    Un valor donde no se reconozca ninguna fecha se devuelve intacto, para
    que el resto del detector lo intente con sus propias reglas (nombres de
    mes, seriales de Excel...).
    """
    if texto is None:
        return texto
    try:
        extraida = texto.str.extract(FECHA_EN_TEXTO_RE, expand=False)
    except (AttributeError, TypeError, ValueError):
        return texto
    return extraida.where(extraida.notna(), texto)


def sin_hora(texto):
    """Borra la hora (y con ella la zona horaria) de una columna de TEXTO.

    Es la forma más simple de que el error "Mixed timezones detected" no
    pueda volver a ocurrir: pandas solo se queja de zonas cuando hay una
    hora a la que referirlas. Sin hora en el texto, no hay zona; sin zona,
    no hay nada que reconciliar.

    Se aplica al texto ANTES de interpretarlo, que es el único momento en
    que sirve — una vez que pandas intenta construir la columna, ya es
    tarde. Si el valor no lleva hora, se devuelve igual.
    """
    if texto is None:
        return texto
    try:
        return texto.str.replace(HORA_EN_TEXTO_RE, "", regex=True).str.strip()
    except AttributeError:
        return texto


def a_datetime(series, **kwargs):
    """`pd.to_datetime` que NUNCA tumba la carga por zonas horarias.

    Desde pandas 2.2 en adelante, una columna que mezcla desfases —una fila
    "10:00+00:00" y otra "14:30-05:00", lo normal en un export de un sistema
    que guarda la hora local de cada registro— hace que `to_datetime` lance
    "Mixed timezones detected. Pass utc=True…". El mensaje llegaba tal cual
    a la pantalla y el archivo entero no se podía abrir.

    Es la única puerta por la que este proyecto convierte texto a fecha, así
    que la reconciliación se hace aquí una sola vez: **todo queda en hora de
    Colombia**, que es la de quien lee estos informes. Con eso, una misma
    columna deja de tener varias horas a la vez y las cifras por mes dejan de
    depender de en qué zona estaba el sistema que exportó cada fila.

    Se distinguen dos situaciones, y la diferencia es lo que evita el peor
    error posible aquí:

    - **El valor TRAE desfase** ("…+00:00", "…-05:00", "…Z"): se reconcilia
      en UTC —`utc=True` nunca lanza, con desfases mezclados o no— y se pasa
      a la hora de Colombia. Un registro guardado como "2026-02-16 04:30Z"
      se reporta, correctamente, como las 23:30 del 15 en Bogotá.
    - **El valor NO trae desfase** ("2026-01-15", "15/01/2026 08:30"): se
      deja como está, porque ya viene en hora local. Convertirlo sería el
      error grave: parsearlo como UTC y pasarlo a Bogotá le restaría cinco
      horas y mandaría al día anterior TODAS las fechas de TODOS los
      archivos normales, que son la inmensa mayoría.

    En una columna que mezcla las dos cosas, cada fila se trata según lo que
    ella misma dice, no según lo que diga el resto de la columna.

    Devuelve siempre fechas SIN zona horaria (ya convertidas): el resto del
    panel compara y agrupa con fechas ingenuas, y mezclar los dos tipos
    vuelve a romper más adelante ("Cannot compare tz-naive and tz-aware").
    """
    if series is None:
        return series
    if pd.api.types.is_datetime64_any_dtype(series):
        return _a_hora_colombia(series)
    if pd.api.types.is_numeric_dtype(series):
        return _a_hora_colombia(pd.to_datetime(series, errors="coerce", **kwargs))
    try:
        texto = series.astype("string").str.strip()
    except (AttributeError, TypeError, ValueError):
        return _a_hora_colombia(pd.to_datetime(series, errors="coerce", utc=True, **kwargs))

    con_zona = texto.str.contains(TZ_EN_TEXTO_RE, regex=True, na=False)

    # UNA sola interpretación para toda la columna, siempre con `utc=True`.
    #
    # Es la clave de que esto no pueda fallar. `utc=True` nunca lanza —da
    # igual que cada fila traiga un desfase distinto, o ninguno— y siempre
    # devuelve una columna de fechas de verdad, nunca una de objetos sueltos.
    #
    # La versión anterior de esta función hacía lo contrario: partía la
    # columna en dos trozos, los interpretaba por separado y los volvía a
    # juntar con `.loc`. Ahí, si un trozo volvía como objetos con zonas
    # distintas, la asignación metía fechas con zona dentro de una columna
    # sin zona y pandas reventaba por dentro con un "Something has gone
    # wrong, please report a bug". Interpretar una vez y transformar después
    # elimina por completo ese ensamblado.
    # `format="mixed"` interpreta CADA valor por su cuenta. Sin él, pandas
    # deduce un formato del primer valor y descarta como vacío todo el que no
    # encaje: una columna con "2026-01-15" en una fila y "20/02/2026 09:00"
    # en otra perdía la mitad de las fechas en silencio. Es el mismo ajuste
    # que ya usaba `detect_date` más abajo.
    opciones = {"format": "mixed", **kwargs}
    fechas = pd.to_datetime(texto, errors="coerce", utc=True, **opciones)

    # Un valor SIN desfase se acaba de interpretar como si fuera UTC, así que
    # quitarle la zona devuelve exactamente la hora que estaba escrita: no se
    # mueve nada. Un valor CON desfase sí se pasa a la hora de Colombia.
    como_esta = fechas.dt.tz_localize(None)
    if not bool(con_zona.any()):
        return como_esta.dt.normalize()
    en_colombia = fechas.dt.tz_convert(_zona_colombia()).dt.tz_localize(None)
    # `where` combina las dos columnas —ambas del mismo tipo y ya sin zona—
    # sin asignar nada por trozos.
    #
    # `normalize()` al final deja la fecha a medianoche: la hora se borra, que
    # es lo que se quiere (no se usa en ningún cálculo ni vista del panel), y
    # así ninguna etapa posterior puede volver a encontrarse una hora con
    # zona. Se hace DESPUÉS de convertir, no antes: "2026-02-16 04:30 UTC" es
    # la noche del 15 en Colombia, y recortar primero lo habría dejado en el
    # 16 — un día que aquí todavía no había empezado.
    return en_colombia.where(con_zona, como_esta).dt.normalize()


# Colombia no aplica horario de verano desde 1993, así que su hora es
# siempre UTC-5. Se usa el nombre de la zona cuando el sistema tiene la base
# de datos de zonas horarias, y si no, el desfase fijo — que para Colombia da
# exactamente el mismo resultado y no depende de que el servidor traiga
# `tzdata` instalado.
ZONA_COLOMBIA = "America/Bogota"
_DESFASE_COLOMBIA = timezone(timedelta(hours=-5))


def _zona_colombia():
    try:
        pd.Timestamp("2026-01-01", tz="UTC").tz_convert(ZONA_COLOMBIA)
        return ZONA_COLOMBIA
    except Exception:
        return _DESFASE_COLOMBIA


def _a_hora_colombia(fechas):
    """Pasa las fechas CON zona a la hora de Colombia y les quita la zona.

    Lo que no trae zona se devuelve intacto: ya está en hora local y
    convertirlo restaría 5 horas a fechas que nadie pidió mover.

    Se quita la zona al final porque el resto del panel compara y agrupa con
    fechas ingenuas; mezclar los dos tipos rompe con "Cannot compare tz-naive
    and tz-aware". Después de convertir, la hora que queda ES la colombiana.
    """
    serie_tz = getattr(getattr(fechas, "dt", None), "tz", None)
    if serie_tz is not None:
        return fechas.dt.tz_convert(_zona_colombia()).dt.tz_localize(None)
    if getattr(fechas, "tzinfo", None) is not None:  # un Timestamp suelto
        return fechas.tz_convert(_zona_colombia()).tz_localize(None)
    return fechas


def date_only(series):
    """Deja solo la FECHA: sin hora y sin zona horaria.

    Decisión de negocio (pedida explícitamente): en estos informes la hora
    no aporta y sí estorba, así que se reduce a la fecha.

    El día que queda es el COLOMBIANO: `a_datetime` ya pasó a esa zona todo
    lo que traía desfase antes de llegar aquí (ver allá el porqué y el caso
    que no debe convertirse). El orden importa —convertir primero, recortar
    después—: un registro guardado como "2026-02-16 04:30Z" es de la noche
    del 15 en Colombia, y recortar antes de convertir lo habría reportado el
    16, un día que en Bogotá todavía no había empezado.
    """
    if series is None:
        return series
    out = a_datetime(series)
    # Una columna con zona horaria única: se le quita la zona conservando la
    # hora local (tz_localize(None) mantiene el reloj de pared, no el
    # instante), y después se normaliza a medianoche.
    tz = getattr(getattr(out, "dt", None), "tz", None)
    if tz is not None:
        out = out.dt.tz_localize(None)
    return out.dt.normalize()


def detect_date(s, name):
    if pd.api.types.is_datetime64_any_dtype(s):
        converted = date_only(s)
        return converted, converted.notna().mean(), "datetime"

    x = s.dropna()
    if not len(x):
        return None, 0, None

    if is_month_name_series(x) and ("mes" in _norm(name) or "month" in _norm(name) or "period" in _norm(name)):
        # A month-only column is still a valid period. The schema layer can
        # replace the placeholder year with a real year column or file/sheet hint.
        result = date_only(month_year_series(x, year_hint=2000))
        return result.reindex(s.index), result.notna().mean(), "month_name"

    numeric = pd.to_numeric(x, errors="coerce")
    if numeric.notna().mean() > 0.95:
        unix = unix_timestamp(x)
        valid = unix.dropna()
        if len(valid):
            years = valid.dt.year
            if years.between(1990, 2100).mean() > 0.95 and (
                DATE_NAME.search(str(name)) or numeric.median() >= 1_000_000_000
            ):
                result = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
                result.loc[x.index] = unix
                return date_only(result), unix.notna().mean(), "unix_timestamp"

        excel = excel_serial(x)
        valid = excel.dropna()
        if len(valid):
            years = valid.dt.year
            if years.between(1990, 2100).mean() > 0.95 and DATE_NAME.search(str(name)):
                result = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
                result.loc[x.index] = excel
                return date_only(result), excel.notna().mean(), "excel_serial"

        # "Periodo" AAAAMM (p. ej. 202608 = agosto 2026) — columna numérica,
        # sin separador, muy común en exportes de BI/ERP. Se exige que el
        # NOMBRE de la columna sugiera fecha/periodo (mismo criterio que
        # excel_serial arriba): un AAAAMM real siempre cae en el rango
        # 190001-210012 con mes 01-12, pero esos mismos números también
        # podrían ser una cantidad o un código cualquiera en una columna sin
        # relación con fechas — el nombre es lo que evita ese falso positivo.
        yyyymm = yyyymm_series(x)
        valid = yyyymm.dropna()
        if len(valid):
            years = valid.dt.year
            if years.between(1990, 2100).mean() > 0.95 and DATE_NAME.search(str(name)):
                result = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
                result.loc[x.index] = yyyymm
                return date_only(result), yyyymm.notna().mean(), "yyyymm_period"

    text = x.astype(str).str.strip()
    # Se borra la HORA COMPLETA del texto antes de convertir, no solo el
    # sufijo de zona.
    #
    # Antes se recortaba únicamente la zona, con un patrón que reconocía
    # "+00:00" y "Z" pero no "-05", " UTC" ni "GMT-5". Con cualquiera de
    # esos, el desfase sobrevivía al recorte y pandas se negaba a construir
    # la columna: "Mixed timezones detected", y el archivo entero no se
    # podía abrir. Ampliar el patrón era la trampa en la que ya se cayó dos
    # veces —siempre faltaba un formato—, así que ahora se quita la hora
    # entera: sin hora no puede haber zona, y el error deja de ser posible
    # por construcción.
    #
    # No se pierde nada: en estos informes la hora no se usa en ningún
    # cálculo ni se muestra en ninguna vista (lo único que lleva hora son
    # los sellos de "generado el ..."), y esta función termina pasando por
    # `date_only()`, que de todos modos reduce el valor a solo la fecha.
    # La corrección de zona a hora de Colombia ya ocurrió antes, en
    # `core/cleaner.normalize_timezones`, que es el primer paso de la
    # limpieza.
    # Quitar la hora y extraer la fecha son operaciones celda por celda: se
    # hacen sobre los valores distintos y se reparten a cada fila. Una
    # columna de nombres (220 distintos en 70.000 filas) pasaba por dos
    # expresiones regulares 70.000 veces para terminar descartada.
    codigos, unicos = pd.factorize(text)
    limpios = solo_fecha(sin_hora(pd.Series(unicos, dtype=object)))
    text = pd.Series(limpios.to_numpy(dtype=object)[codigos], index=text.index)
    iso_ratio = text.str.match(ISO_DATE_RE).mean() if len(text) else 0
    # Si la mayoría de los valores ya vienen en formato ISO (típico tras
    # convertir una columna datetime a texto en el pipeline de limpieza),
    # dayfirst debe ir en False para no invertir día y mes.
    use_dayfirst = iso_ratio < 0.5

    # Sondeo con una muestra antes de convertir la columna ENTERA. Para que
    # una columna se acepte como fecha hace falta que parsee >=0.90 (ver
    # core/schema.py), así que si en 1.000 valores no llega ni a la mitad,
    # la columna completa tampoco va a llegar — y convertirla es carísimo:
    # en una hoja de 200.000 filas, intentar leer como fecha una columna de
    # códigos ("D3243.00002") costaba 4 segundos para terminar
    # descartándola. El sondeo cuesta milisegundos y llega a la misma
    # conclusión. Solo se salta cuando hay bastantes valores: por debajo de
    # eso, convertir todo ya es barato y no vale la pena arriesgar.
    if len(text) > 2000:
        # Muestra REPARTIDA a lo largo de la columna, no las primeras 1.000
        # filas: un archivo ordenado puede tener al principio un tramo que no
        # se parece al resto (encabezados de sección, registros viejos con
        # otro formato), y decidir con solo el arranque sería frágil.
        probe = text.iloc[:: max(1, len(text) // 1000)]
        probe_rate = _parse_seguro(probe, dayfirst=use_dayfirst).notna().mean()
        if probe_rate < 0.5:
            return None, float(probe_rate), None

    parsed = _parse_seguro(text, dayfirst=use_dayfirst)
    rate = parsed.notna().mean()
    if rate >= 0.90:
        years = parsed.dropna().dt.year
        if len(years) and years.between(1900, 2100).mean() >= 0.95:
            result = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
            result.loc[x.index] = parsed
            return date_only(result), rate, "text_date"

    return None, rate, None
