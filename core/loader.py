import io
from datetime import datetime
import re
import pandas as pd
from .profile import profile_sheet
from .relationships import detect_relationships
from .pivot_flatten import merged_ranges, fill_merged_cells, flatten_pivot_grid


def _norm_header(v):
    if pd.isna(v):
        return ""
    return re.sub(r"\s+", " ", str(v).replace("\n", " ").replace("\r", " ").strip())


def _header_score(row):
    vals = [_norm_header(v) for v in row.tolist()]
    nonempty = [v for v in vals if v]
    if len(nonempty) < 2:
        return -1.0
    unique_ratio = len(set(nonempty)) / len(nonempty)
    string_ratio = sum(not re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", v) for v in nonempty) / len(nonempty)
    semantic_words = re.compile(
        r"fecha|date|mes|month|año|year|region|región|ciudad|city|producto|product|cliente|customer|"
        r"cantidad|ventas|venta|ingreso|revenue|precio|price|costo|cost|meta|objetivo|progreso|resultado|"
        r"total|id|codigo|código|nombre|name|estado|status|categoria|categoría|plan|periodo|período",
        re.I,
    )
    semantic_hits = sum(bool(semantic_words.search(v)) for v in nonempty)
    score = min(len(nonempty) / 8.0, 1.0) * 0.25 + unique_ratio * 0.20 + string_ratio * 0.25 + min(semantic_hits / max(len(nonempty), 1), 1.0) * 0.30
    return score


def _make_unique_columns(columns):
    seen = {}
    out = []
    for i, c in enumerate(columns, 1):
        base = _norm_header(c) or f"Columna {i}"
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return out


def _excel_engine(filename: str):
    """Elige el motor de lectura correcto según la extensión. .xlsb es un
    formato binario (no XML como .xlsx), así que necesita su propia
    librería (pyxlsb); openpyxl no sabe leerlo."""
    name = filename.lower()
    if name.endswith(".xlsb"):
        return "pyxlsb"
    if name.endswith(".xls"):
        return "xlrd"
    return None  # .xlsx/.xlsm: pandas ya elige openpyxl automáticamente.


def _read_excel_sheet(data, sheet_name, filename="", engine=None):
    # Read without assuming the first row is the header. Excel files often have
    # a title/merged row above the real table header — y, si el Excel trae una
    # tabla dinámica (encabezado de varias filas, celdas combinadas, filas de
    # subtotal/total general), esa forma se aplana aquí mismo antes de que le
    # llegue a cleaner/schema, que sí esperan una tabla plana normal. Ver
    # core/pivot_flatten.py para el detalle de cada paso.
    raw = pd.read_excel(io.BytesIO(data), sheet_name=sheet_name, header=None, engine=engine)
    if raw.empty:
        return raw, []
    # Celdas combinadas: pandas ya perdió esa información (solo la esquina
    # superior-izquierda del rango trae el valor, el resto llega vacío) —
    # se relee directo con openpyxl/xlrd para recuperar los rangos y
    # rellenar antes de decidir dónde está el encabezado real.
    ranges = merged_ranges(data, filename, sheet_name)
    n_merged = fill_merged_cells(raw, ranges) if ranges else 0
    data_df, pivot_log = flatten_pivot_grid(raw, _header_score, _norm_header, _make_unique_columns)
    if n_merged:
        pivot_log.insert(0, f"{n_merged} celda(s) combinada(s) del Excel rellenadas con su valor real.")
    return data_df, pivot_log


def _detect_csv_sep(data: bytes) -> str:
    """Detecta el separador real del CSV en vez de asumir siempre coma. Los
    CSV exportados desde Excel en configuración regional de Colombia y buena
    parte de Latinoamérica suelen usar punto y coma (;), porque la coma ya
    se usa como separador decimal ahí. Sin esto, pandas intenta leer todo
    como una sola columna y truena apenas encuentra una coma real dentro de
    un valor de texto (p. ej. 'Bogotá, Colombia').
    """
    sample = data[:16384].decode("utf-8", errors="ignore")
    candidates = [",", ";", "\t", "|"]
    try:
        import csv as _csv
        dialect = _csv.Sniffer().sniff(sample, delimiters="".join(candidates))
        if dialect.delimiter in candidates:
            return dialect.delimiter
    except Exception:
        pass
    # Respaldo: cuenta cuál separador aparece más seguido en la primera línea.
    first_line = sample.split("\n", 1)[0]
    counts = {d: first_line.count(d) for d in candidates}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def _read_csv(data):
    sep = _detect_csv_sep(data)
    try:
        raw = pd.read_csv(io.BytesIO(data), header=None, sep=sep, engine="python", on_bad_lines="skip")
    except UnicodeDecodeError:
        # Algunos CSV exportados desde Excel en Windows quedan en latin-1/cp1252
        # en vez de UTF-8 (tildes, ñ). Se reintenta con esa codificación antes
        # de rendirse.
        raw = pd.read_csv(io.BytesIO(data), header=None, sep=sep, engine="python", on_bad_lines="skip", encoding="latin-1")
    if raw.empty:
        return raw, []
    # Un CSV no puede traer celdas combinadas, pero un CSV exportado desde una
    # tabla dinámica sí hereda su forma (encabezado de varias filas, etiquetas
    # de fila que solo aparecen una vez, filas de subtotal/total general) —
    # mismo aplanador que usan los Excel, sin el paso de celdas combinadas.
    return flatten_pivot_grid(raw, _header_score, _norm_header, _make_unique_columns)


def load_workbook(uploaded):
    data = uploaded.getvalue()
    filename = uploaded.name
    name = filename.lower()
    if name.endswith(".csv"):
        raw = {"CSV": _read_csv(data)}
    elif name.endswith((".xlsx", ".xls", ".xlsb", ".xlsm")):
        # Discover sheet names first, then read each sheet with header inference.
        engine = _excel_engine(name)
        book = pd.ExcelFile(io.BytesIO(data), engine=engine)
        raw = {sheet: _read_excel_sheet(data, sheet, filename=filename, engine=engine) for sheet in book.sheet_names}
    else:
        raise ValueError("Formato no soportado")

    sheets = {}
    for sheet_name, (raw_df, structural_log) in raw.items():
        if raw_df is None or raw_df.empty or len(raw_df.columns) == 0:
            continue
        sheets[sheet_name] = profile_sheet(
            raw_df, context={"sheet_name": sheet_name, "workbook_name": filename}, structural_log=structural_log,
        )

    if not sheets:
        raise ValueError("No se encontraron hojas con datos.")
    relationships = detect_relationships(sheets)
    for sheet in sheets:
        sheets[sheet]["profile"]["relationships"] = relationships.get(sheet, [])
    return {
        "filename": filename,
        "size_mb": len(data) / 1024 / 1024,
        "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sheets": sheets,
        "relationships": relationships,
    }
