import io
from datetime import datetime
import re
import pandas as pd
from .profile import profile_sheet
from .relationships import detect_relationships
from .pivot_flatten import merged_ranges_by_sheet, fill_merged_cells, flatten_pivot_grid
from .informe import leer_informe, graficos_e_imagenes, titulo_principal, titulos as titulos_de
from .dates import extract_year_hint
from .imagen_ocr import imagenes_del_libro


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


def _grid(data, sheet_name, merge_ranges=None, engine=None):
    """La hoja tal cual está en el Excel, con las celdas combinadas ya rellenadas."""
    raw = pd.read_excel(io.BytesIO(data), sheet_name=sheet_name, header=None, engine=engine)
    # merge_ranges ya viene calculado UNA vez para todo el archivo (ver
    # load_workbook) — recalcularlo por hoja era carísimo (ver el
    # comentario largo en pivot_flatten.merged_ranges_by_sheet).
    n_merged = fill_merged_cells(raw, merge_ranges) if merge_ranges and not raw.empty else 0
    return raw, n_merged


def _misma_tabla(a, b) -> bool:
    """¿Dos tablas con exactamente las mismas columnas y valores?"""
    try:
        return (a is not None and b is not None and a.shape == b.shape
                and list(map(str, a.columns)) == list(map(str, b.columns))
                and a.reset_index(drop=True).equals(b.reset_index(drop=True)))
    except Exception:
        return False


def _nombre_unico(nombre, usados):
    base = str(nombre).strip()[:90] or "Tabla"
    candidato, i = base, 2
    while candidato in usados:
        candidato, i = f"{base} ({i})", i + 1
    return candidato


def _read_excel_sheet(data, sheet_name, merge_ranges=None, engine=None):
    # Read without assuming the first row is the header. Excel files often have
    # a title/merged row above the real table header — y, si el Excel trae una
    # tabla dinámica (encabezado de varias filas, celdas combinadas, filas de
    # subtotal/total general), esa forma se aplana aquí mismo antes de que le
    # llegue a cleaner/schema, que sí esperan una tabla plana normal. Ver
    # core/pivot_flatten.py para el detalle de cada paso.
    raw, n_merged = _grid(data, sheet_name, merge_ranges, engine)
    if raw.empty:
        return raw, []
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
    titulos: dict = {}
    avisos: list = []
    sin_ceros: set = set()  # tablas de informe: una celda vacía es "sin reportar", no cero
    if name.endswith(".csv"):
        raw = {"CSV": _read_csv(data)}
    elif name.endswith((".xlsx", ".xls", ".xlsb", ".xlsm")):
        # Discover sheet names first, then read each sheet with header inference.
        engine = _excel_engine(name)
        book = pd.ExcelFile(io.BytesIO(data), engine=engine)
        # Celdas combinadas de TODO el archivo, en una sola pasada (no una
        # por hoja — ver el porqué en pivot_flatten.merged_ranges_by_sheet).
        merges_by_sheet = merged_ranges_by_sheet(data, filename)
        raw, grids = {}, {}
        for sheet in book.sheet_names:
            grid, n_merged = _grid(data, sheet, merges_by_sheet.get(sheet), engine)
            grids[sheet] = grid
            # Una hoja tipo informe (varias tablas, meses en columnas, bloques
            # por región) se reconoce por su forma y se convierte en una tabla
            # por sección, con su título. Una hoja normal devuelve lista vacía
            # y sigue exactamente el camino de antes. Ver core/informe.py.
            try:
                tablas = leer_informe(grid, sheet, extract_year_hint(sheet, filename)) if not grid.empty else []
            except Exception:
                tablas = []  # un informe raro nunca debe impedir leer la hoja como siempre
            if tablas:
                for t in tablas:
                    # Los informes suelen copiar la misma tabla en otra hoja
                    # (INDICADORES CLAVE repite tres de BUENAS NOTICIAS). Se
                    # muestra una vez y se avisa, en vez de llenar el selector
                    # de hojas con "(2)" que dicen exactamente lo mismo.
                    igual = next((n for n, (d, _) in raw.items() if _misma_tabla(d, t["datos"])), None)
                    if igual is not None:
                        avisos.append(f"«{t['nombre']}» de la hoja «{sheet}» es idéntica a «{igual}»: "
                                      "se muestra una sola vez.")
                        continue
                    nombre = _nombre_unico(t["nombre"], raw)
                    raw[nombre] = (t["datos"], t["log"])
                    if not t.get("faltantes_son_cero", True):
                        sin_ceros.add(nombre)
                    titulos[nombre] = t["titulo"]
                continue
            if grid.empty:
                raw[sheet] = (grid, [])
                continue
            data_df, pivot_log = flatten_pivot_grid(grid, _header_score, _norm_header, _make_unique_columns)
            if n_merged:
                pivot_log.insert(0, f"{n_merged} celda(s) combinada(s) del Excel rellenadas con su valor real.")
            raw[sheet] = (data_df, pivot_log)
            titulos[sheet] = titulo_principal(grid)
        if name.endswith((".xlsx", ".xlsm")):
            try:
                elementos = graficos_e_imagenes(data, grids.get)
            except Exception:
                elementos = {}
            for hoja, contenido in elementos.items():
                for grafico in contenido["graficos"]:
                    titulo = grafico["titulo"] or f"Gráfico de {hoja}"
                    nombre = _nombre_unico(f"Gráfico · {titulo}", raw)
                    raw[nombre] = (grafico["datos"], [f"Datos leídos del gráfico «{titulo}» de la hoja «{hoja}»: "
                                                      "Excel guarda una copia de los números de cada gráfico."])
                    titulos[nombre] = titulo
                if contenido["imagenes"]:
                    n = contenido["imagenes"]
                    # Qué sección es cada imagen: "tiene 2 imágenes" no dice
                    # qué se perdió; "RANKING DE LOS JEFES es una imagen" sí.
                    grid = grids.get(hoja)
                    secciones = []
                    if grid is not None and not grid.empty:
                        lista = titulos_de(grid.to_numpy(dtype=object))
                        for fila in contenido.get("filas_imagen", []):
                            previos = [t for r, t in lista if r <= fila]
                            if previos and previos[-1] not in secciones:
                                secciones.append(previos[-1])
                    if secciones:
                        nombres = " y ".join(f"«{s}»" for s in secciones) if len(secciones) <= 2 else \
                            ", ".join(f"«{s}»" for s in secciones[:-1]) + f" y «{secciones[-1]}»"
                        avisos.append(
                            f"En la hoja «{hoja}», {nombres} {'es una imagen pegada' if len(secciones) == 1 else 'son imágenes pegadas'}: "
                            "una imagen no trae celdas con números. Si muestra cifras escritas (una tabla o un gráfico "
                            "con sus valores), se puede leer en «🖼️ Imágenes del archivo», más abajo en esta pestaña.")
                    else:
                        avisos.append(
                            f"La hoja «{hoja}» tiene {n} imagen{'es' if n != 1 else ''} pegada{'s' if n != 1 else ''}. "
                            "Una imagen no trae números, así que no se puede analizar: si es un gráfico, "
                            "incluye también su tabla de datos o pégalo como gráfico de Excel.")
    else:
        raise ValueError("Formato no soportado")

    # Las imágenes se guardan con su sección para poder leerlas después con el
    # OCR local (core/imagen_ocr.py), a pedido y con revisión. No se leen aquí:
    # tarda varios segundos por imagen y el resultado hay que revisarlo antes
    # de analizarlo.
    imagenes = []
    if name.endswith((".xlsx", ".xlsm")):
        try:
            imagenes = imagenes_del_libro(data)
        except Exception:
            imagenes = []
        for img in imagenes:
            grid = grids.get(img["hoja"])
            lista = titulos_de(grid.to_numpy(dtype=object)) if grid is not None and not grid.empty else []
            previos = [t for r, t in lista if r <= img["fila"]]
            img["seccion"] = previos[-1] if previos else img["hoja"]
            img["anio"] = extract_year_hint(img["hoja"], filename)

    sheets = {}
    for sheet_name, (raw_df, structural_log) in raw.items():
        if raw_df is None or raw_df.empty or len(raw_df.columns) == 0:
            continue
        sheets[sheet_name] = profile_sheet(
            raw_df, context={"sheet_name": sheet_name, "workbook_name": filename,
                             "faltantes_son_cero": sheet_name not in sin_ceros},
            structural_log=structural_log,
        )

    if not sheets:
        raise ValueError("No se encontraron hojas con datos.")
    relationships = detect_relationships(sheets)
    for sheet in sheets:
        sheets[sheet]["profile"]["relationships"] = relationships.get(sheet, [])
        # El título dice qué información es ("RANKING DE LOS JEFES"): el nombre
        # de la hoja casi nunca lo dice, y sin él no se sabe qué se está viendo.
        sheets[sheet]["profile"]["titulo"] = titulos.get(sheet)
    return {
        "filename": filename,
        "size_mb": len(data) / 1024 / 1024,
        "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sheets": sheets,
        "relationships": relationships,
        "avisos": avisos,
        "imagenes": imagenes,
    }
