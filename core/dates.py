import re
import unicodedata
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
    x = s.astype("string").str.strip().str.lower()
    return x.map(lambda v: MONTHS.get(_norm(v), pd.NA)).astype("Int64")


def is_month_name_series(s):
    m = month_number_series(s)
    valid = m.notna()
    return bool(valid.any() and valid.mean() >= 0.80)


def extract_year_hint(*texts):
    for text in texts:
        if not text:
            continue
        m = re.search(r"\b(19\d{2}|20\d{2}|21\d{2})\b", str(text))
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


def detect_date(s, name):
    if pd.api.types.is_datetime64_any_dtype(s):
        converted = pd.to_datetime(s, errors="coerce")
        return converted, converted.notna().mean(), "datetime"

    x = s.dropna()
    if not len(x):
        return None, 0, None

    if is_month_name_series(x) and ("mes" in _norm(name) or "month" in _norm(name) or "period" in _norm(name)):
        # A month-only column is still a valid period. The schema layer can
        # replace the placeholder year with a real year column or file/sheet hint.
        result = month_year_series(x, year_hint=2000)
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
                return result, unix.notna().mean(), "unix_timestamp"

        excel = excel_serial(x)
        valid = excel.dropna()
        if len(valid):
            years = valid.dt.year
            if years.between(1990, 2100).mean() > 0.95 and DATE_NAME.search(str(name)):
                result = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
                result.loc[x.index] = excel
                return result, excel.notna().mean(), "excel_serial"

    text = x.astype(str).str.strip()
    iso_ratio = text.str.match(ISO_DATE_RE).mean() if len(text) else 0
    # Si la mayoría de los valores ya vienen en formato ISO (típico tras
    # convertir una columna datetime a texto en el pipeline de limpieza),
    # dayfirst debe ir en False para no invertir día y mes.
    use_dayfirst = iso_ratio < 0.5
    parsed = pd.to_datetime(text, errors="coerce", format="mixed", dayfirst=use_dayfirst)
    rate = parsed.notna().mean()
    if rate >= 0.90:
        years = parsed.dropna().dt.year
        if len(years) and years.between(1900, 2100).mean() >= 0.95:
            result = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
            result.loc[x.index] = parsed
            return result, rate, "text_date"

    return None, rate, None
