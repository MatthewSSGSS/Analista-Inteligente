"""Aplana tablas dinámicas de Excel (de cualquier layout: Compacto, Esquema
o Tabular; con o sin celdas combinadas; con o sin subtotales/total general)
para que el resto del pipeline (loader → cleaner → schema → profile) las
trate como una tabla plana normal.

Por qué hacía falta: pd.read_excel(header=None) lee la cuadrícula tal cual
quedó guardada en el Excel, y una tabla dinámica rompe 3 supuestos que el
resto del código sí hace sobre una tabla "normal":

1. Encabezado de una sola fila. Una dinámica con 2+ campos de columna
   (p. ej. Año arriba, Trimestre debajo) tiene 2+ filas de encabezado —
   _read_excel_sheet (ui/../core/loader.py) solo sabía elegir UNA.
2. Sin celdas vacías "heredadas". En layout Compacto/Esquema, la etiqueta
   de un grupo de filas (p. ej. "Región") solo aparece en la primera fila
   del grupo — el resto llegan vacías (por celda combinada real, o porque
   Excel simplemente no repite el texto). Sin relleno hacia abajo, esas
   filas quedan sin categoría.
3. Sin filas de subtotal/total mezcladas con los datos. "Total Norte",
   "Subtotal", "Total general"... son filas de AGREGADO, no un registro
   más — si se cuentan como dato, las sumas/promedios quedan infladas.

Cada paso de este módulo es seguro sobre una tabla plana normal: si no
encuentra nada que aplanar, no cambia nada (ver los tests al final del
archivo, ejecutables con `python -m core.pivot_flatten`).
"""
from __future__ import annotations

import io
import re

import pandas as pd

# Coincidencia EXACTA (toda la celda, no una palabra suelta dentro de un
# nombre) — así "Total Play" (un cliente real) o "Totalizadores S.A." nunca
# se confunden con una fila de agregado.
# El plural va como grupo —`total(?:es)?`, no `totales?`— porque con la
# segunda forma el `?` afecta solo a la "s" y la "e" queda OBLIGATORIA: la
# expresión aceptaba "totales" y "totale", pero NO "Total" ni "Subtotal", que
# son justo las dos etiquetas más comunes de todas. Esas filas se colaban
# como un registro más y toda suma del panel salía al doble.
_TOTAL_EXACT_RE = re.compile(
    r"^(total\s*general|gran\s*total|grand\s*total|total(?:es)?|sub\s*-?\s*total(?:es)?)$",
    re.I,
)
# Coincidencia de PREFIJO ("Total Norte", "Total Región X" — el subtotal por
# grupo que arma Excel al activar "Subtotales" en una dinámica). Se usa con
# una condición extra (ver total_row_mask) para no atrapar categorías reales
# que solo empiezan con esa palabra.
_TOTAL_PREFIX_RE = re.compile(r"^(total|sub\s*-?\s*total)\s+\S", re.I)


def _cell_text(v) -> str:
    if pd.isna(v):
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()


def es_total(texto) -> bool:
    """¿Esta etiqueta nombra un agregado ("Total", "Subtotales", "Gran total")?

    Fuente única para las dos rutas de carga. `core/informe.py` tenía su
    propia lista literal y las dos no decían lo mismo: aquella no reconocía
    "Sub total", "Sub-total" ni "Subtotales", así que esas filas entraban
    como un registro más en las hojas tipo informe y la suma salía inflada,
    mientras el mismo archivo por la otra ruta sí las excluía. Dos reglas
    para la misma pregunta terminan siempre así.

    Coincidencia EXACTA de toda la etiqueta: el caso "empieza por Total"
    ("Total Norte") pide una condición extra y lo resuelve `total_row_mask`.
    """
    return bool(_TOTAL_EXACT_RE.match(_cell_text(texto)))


def _xlsx_merged_ranges_by_sheet(data: bytes) -> dict:
    """{nombre_de_hoja: [(r1,c1,r2,c2), ...]} de TODO el .xlsx/.xlsm en una
    sola pasada ligera sobre el XML interno (es un ZIP) — nunca carga el
    árbol completo de celdas de openpyxl.load_workbook().

    Por qué el cambio: la primera versión llamaba a
    openpyxl.load_workbook(...) — que sí carga cada celda de cada hoja en
    memoria como objetos — UNA VEZ POR HOJA (load_workbook() se invocaba
    dentro de _read_excel_sheet, que corre por hoja). Un Excel de varias
    hojas terminaba parseándose por completo tantas veces como hojas
    tuviera, encima de lo que pandas ya hace — en Streamlit Cloud (memoria
    limitada) eso se tradujo en que el proceso se quedaba sin memoria o
    colgado al subir un archivo, y el healthcheck lo mataba
    ("connection reset by peer", no un error de Python normal).

    Esto en cambio solo lee <mergeCells> del XML de cada hoja (texto plano,
    sin instanciar ninguna celda) y se llama UNA sola vez por archivo
    completo, sin importar cuántas hojas tenga."""
    import zipfile
    from xml.etree import ElementTree as ET
    from openpyxl.utils.cell import range_boundaries

    ns_main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ns_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ns_pkg_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
            wb_xml = ET.fromstring(z.read("xl/workbook.xml"))
            rid_by_name = {
                sh.get("name"): sh.get(f"{{{ns_rel}}}id")
                for sh in wb_xml.findall(f"{{{ns_main}}}sheets/{{{ns_main}}}sheet")
            }
            wb_rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            target_by_rid = {
                rel.get("Id"): rel.get("Target")
                for rel in wb_rels.findall(f"{{{ns_pkg_rel}}}Relationship")
            }
            out = {}
            for sheet_name, rid in rid_by_name.items():
                target = target_by_rid.get(rid) or ""
                if not target:
                    continue
                # El Target de un Relationship en OOXML es o bien "absoluto
                # al paquete" (empieza con "/", p. ej. "/xl/worksheets/
                # sheet1.xml" — algunos generadores de Excel lo escriben
                # así) o relativo a la carpeta del propio .rels ("xl/_rels/",
                # así que relativo a "xl/", p. ej. "worksheets/sheet1.xml").
                # Tratar SIEMPRE el segundo caso sin distinguir el primero
                # producía "xl/xl/worksheets/sheet1.xml" (duplicado, no
                # existe en el zip) cada vez que el Target ya venía con "/"
                # — por eso nunca se encontraban celdas combinadas.
                sheet_path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
                if sheet_path not in names:
                    continue
                sheet_xml = ET.fromstring(z.read(sheet_path))
                ranges = []
                for mc in sheet_xml.findall(f"{{{ns_main}}}mergeCells/{{{ns_main}}}mergeCell"):
                    ref = mc.get("ref")
                    if not ref:
                        continue
                    try:
                        c1, r1, c2, r2 = range_boundaries(ref)
                    except ValueError:
                        continue
                    ranges.append((r1 - 1, c1 - 1, r2 - 1, c2 - 1))
                out[sheet_name] = ranges
            return out
    except Exception:
        return {}


def _xls_merged_ranges_by_sheet(data: bytes) -> dict:
    """Igual que la anterior pero para .xls legado (vía xlrd) — un solo
    xlrd.open_workbook() para todo el archivo, reutilizado por cada hoja en
    vez de reabrirlo por cada una."""
    try:
        import xlrd
        book = xlrd.open_workbook(file_contents=data)
        out = {}
        for sheet in book.sheets():
            out[sheet.name] = [(r0, c0, r1 - 1, c1 - 1) for (r0, r1, c0, c1) in sheet.merged_cells]
        return out
    except Exception:
        return {}


def merged_ranges_by_sheet(data: bytes, filename: str) -> dict:
    """{nombre_de_hoja: [(r1,c1,r2,c2), ...]} para TODO el archivo, en una
    sola pasada — se llama una vez por archivo (ver core/loader.py), nunca
    por hoja. {} si el formato no expone celdas combinadas (.xlsb) o si algo
    falla — nunca debe tumbar la carga del archivo."""
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        return _xlsx_merged_ranges_by_sheet(data)
    if name.endswith(".xls"):
        return _xls_merged_ranges_by_sheet(data)
    return {}


def fill_merged_cells(raw: pd.DataFrame, ranges) -> int:
    """Rellena, en el propio raw (in place), cada rango combinado con el
    valor de su celda superior-izquierda — la única que Excel guarda
    realmente; el resto de la combinación llega vacía. Devuelve cuántas
    celdas se rellenaron, para el log de calidad.

    Antes de escribir, sube a dtype `object` las columnas que participan en
    algún rango combinado (nunca la hoja entera — sería carísimo en un
    archivo grande sin necesidad). Por qué hace falta: `raw` es la
    cuadrícula cruda, tipada columna por columna por pandas según lo que
    haya en ESA columna a lo largo de TODA la hoja — una columna que en
    todas las demás filas es numérica queda tipada como float/entero
    "nulificable" (Float64/Int64). El título de un reporte, combinado en la
    fila de arriba, puede caer justo en una columna así — y escribir texto
    ahí truena ("Invalid value '...' for dtype 'Float64'") porque esos
    dtypes NO aceptan texto, a diferencia del float64 normal de numpy.
    `object` acepta cualquier tipo, así que el resto del pipeline (que ya
    maneja columnas mixtas más abajo, en cleaner.py) sigue funcionando
    igual, solo que sin ese riesgo de tipo."""
    if not ranges:
        return 0
    n_rows, n_cols = len(raw.index), len(raw.columns)
    merge_cols = {c for (_, c1, _, c2) in ranges for c in range(c1, c2 + 1) if c < n_cols}
    for c in merge_cols:
        if raw.dtypes.iloc[c] != object:
            raw.isetitem(c, raw.iloc[:, c].astype(object))
    filled = 0
    for (r1, c1, r2, c2) in ranges:
        if r1 >= n_rows or c1 >= n_cols:
            continue
        try:
            value = raw.iat[r1, c1]
        except Exception:
            continue
        if pd.isna(value):
            continue
        for r in range(r1, min(r2, n_rows - 1) + 1):
            for c in range(c1, min(c2, n_cols - 1) + 1):
                if r == r1 and c == c1:
                    continue
                if pd.isna(raw.iat[r, c]):
                    raw.iat[r, c] = value
                    filled += 1
    return filled


def is_super_header_row(values: list[str]) -> bool:
    """True si esta fila agrupa a la de abajo (p. ej. "2024" repetido sobre
    "Q1 Q2 Q3 Q4") en vez de ser un título suelto o ya la fila de nombres de
    columna real. Repetición (distintos < no-vacíos) es la señal: un título
    ocupa TODO el ancho de la fila tras el relleno de combinadas (título);
    un encabezado normal no repite nada (distintos==no vacíos). Un solo
    valor repetido que NO ocupa todo el ancho (p. ej. "2024" en B:E con la
    columna A —la de la etiqueta de fila— en blanco) sí cuenta: es un
    único grupo de nivel superior, no un título."""
    nonempty = [v for v in values if v]
    if len(nonempty) < 2:
        return False
    distinct = len(set(nonempty))
    if distinct == len(nonempty):
        return False
    if distinct <= 1 and len(nonempty) == len(values):
        return False
    string_ratio = sum(not re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", v) for v in nonempty) / len(nonempty)
    # Agrupar por año ("2024" repetido sobre varias columnas) es tan común
    # como agrupar por texto, pero "2024" es numérico → string_ratio solo no
    # lo detectaría. Una repetición FUERTE (cada valor cubre en promedio 2+
    # columnas) es igual de buena señal de agrupación aunque sea numérica.
    strong_repetition = distinct <= max(1, len(nonempty) // 2)
    return string_ratio >= 0.5 or strong_repetition


def combine_header_rows(top: list[str], bottom: list[str]) -> list[str]:
    """Unifica una fila super-encabezado (agrupa columnas; puede traer
    huecos si el agrupado no vino de una celda combinada real) con la fila
    de encabezado real debajo, tipo "2024 · Q1"."""
    combined = []
    last_top = ""
    for top_v, bottom_v in zip(top, bottom):
        if top_v:
            last_top = top_v
        if last_top and bottom_v:
            combined.append(f"{last_top} · {bottom_v}")
        else:
            combined.append(bottom_v or last_top)
    return combined


def total_row_mask(df: pd.DataFrame, label_cols) -> pd.Series:
    """True en cada fila de subtotal/total general. Dos criterios,
    deliberadamente conservadores para no tocar datos reales:
    - Coincidencia EXACTA de la primera celda no vacía de la fila
      ("Total", "Subtotal", "Total general"...) → siempre se excluye.
    - Coincidencia de PREFIJO ("Total Norte") en una columna de etiqueta,
      solo si ADEMÁS el resto de columnas de etiqueta de esa fila están
      vacías — la firma real de una fila de rollup (agrupa, no describe un
      registro). Evita que una categoría real que arranca con "Total..."
      (p. ej. la empresa "Total Play") se confunda con un agregado, porque
      esa sí trae sus demás columnas de etiqueta normalmente llenas.
    """
    label_cols = [c for c in label_cols if c in df.columns]

    def _row_is_total(row) -> bool:
        first_val, first_col = None, None
        for c in df.columns:
            s = _cell_text(row[c])
            if s:
                first_val, first_col = s, c
                break
        if not first_val:
            return False
        if _TOTAL_EXACT_RE.match(first_val):
            return True
        if _TOTAL_PREFIX_RE.match(first_val) and first_col in label_cols:
            others = [c for c in label_cols if c != first_col]
            if others and all(not _cell_text(row[c]) for c in others):
                return True
        return False

    return df.apply(_row_is_total, axis=1)


def total_columns(df: pd.DataFrame) -> list:
    """Las columnas de Total/Subtotal: el equivalente en vertical de las
    filas que quita `total_row_mask`.

    Una dinámica con "Mostrar totales" activado escribe una columna extra al
    final con la suma de la fila. Si se deja, toda suma del panel cuenta cada
    valor dos veces —una en su mes y otra dentro del Total— y el archivo
    reporta exactamente el doble de lo real.

    Solo coincidencia EXACTA del nombre ("Total", "Total general",
    "Subtotal"…), nunca por prefijo: una columna puede llamarse legítimamente
    "Total Play" (un cliente) o "Total Hogares" (una medida real), y
    borrarlas sería perder datos, no limpiar un agregado. El mismo criterio
    conservador que usa `total_row_mask` para su parte exacta.
    """
    return [c for c in df.columns if _TOTAL_EXACT_RE.match(_cell_text(c))]


def _nombre_libre(base: str, usados) -> str:
    """`base` si no está tomado; si no, "base_2", "base_3"… — el mismo
    criterio de `core/loader._make_unique_columns`."""
    usados = {_cell_text(c) for c in usados}
    if base not in usados:
        return base
    i = 2
    while f"{base}_{i}" in usados:
        i += 1
    return f"{base}_{i}"


def unpivot_period_columns(df: pd.DataFrame, period_cols, year_hint=None,
                           eje: str = "Mes", medida: str = "Valor"):
    """Despivota: los meses que están COMO COLUMNAS vuelven a ser filas.

    Es el paso que convierte

        Región | Ciudad | ene-26 | feb-26        Región | Ciudad | Mes     | Valor
        Norte  | Bogotá |   10   |   20     →    Norte  | Bogotá | ene-26  |  10
                                                 Norte  | Bogotá | feb-26  |  20

    y con él la tabla queda con el MISMO esquema que una tabla plana normal:
    columnas de etiqueta + UNA columna de fecha + UNA columna de medida. Ese
    esquema es el que el resto del panel sabe analizar — con los meses como
    columnas no hay ninguna fecha que graficar, y el detector semántico ni
    siquiera las cuenta como métricas (a propósito: doce columnas de mes no
    son doce indicadores distintos), así que una dinámica ancha llegaba al
    dashboard sin métricas y sin evolución posible.

    Los nombres de las dos columnas nuevas son los mismos que usa
    `core/informe.py` al aplanar esta forma desde una hoja de Excel ("Mes" y
    "Valor"), para que el mismo archivo dé el mismo resultado venga como
    .xlsx o como .csv.

    No se toca nada si la forma no es inequívoca: hacen falta 2+ columnas de
    periodo y que su contenido sea mayoritariamente numérico (si trae texto
    no es una medida y despivotarla produciría basura). Las columnas que no
    son periodo se conservan tal cual, repetidas en cada fila nueva, que es
    lo que hace cualquier melt.

    Devuelve (df, log). Los valores NO se convierten a número aquí a
    propósito: `core/cleaner.py` corre después y es quien sabe leer "1.234,5"
    según la configuración regional; forzarlos ahora los perdería.
    """
    period_cols = [c for c in (period_cols or []) if c in df.columns]
    if df.empty or len(period_cols) < 2:
        return df, []
    numerico = sum(
        pd.to_numeric(df[c], errors="coerce").notna().mean() >= 0.6 for c in period_cols
    )
    if numerico < len(period_cols) * 0.75:
        return df, []

    from .dates import MONTH_ABBR_ES
    from .informe import periodo_de

    etiquetas = {}
    for c in period_cols:
        periodo = periodo_de(c) or periodo_de(_cell_text(c))
        if not periodo:
            return df, []
        anio, mes = periodo
        anio = anio or year_hint
        # Sin año por ningún lado no se inventa uno: el mes queda como texto,
        # igual que en core/informe.py.
        etiquetas[c] = pd.Timestamp(year=int(anio), month=int(mes), day=1) if anio else MONTH_ABBR_ES[mes]

    id_vars = [c for c in df.columns if c not in period_cols]
    # Si la tabla YA trae una columna llamada "Mes" o "Valor" (otra cosa, no
    # el periodo que estamos creando), reusar ese nombre no es una colisión
    # cosmética: pandas lanza ValueError y el archivo entero deja de cargar.
    # Se le busca un nombre libre con el mismo criterio que
    # loader._make_unique_columns ("Mes_2", "Mes_3"…).
    eje, medida = _nombre_libre(eje, id_vars), _nombre_libre(medida, id_vars)
    largo = df.melt(id_vars=id_vars, value_vars=period_cols, var_name=eje, value_name=medida)
    largo[eje] = largo[eje].map(etiquetas)
    # Una fila sin valor en un mes no es un registro: en una dinámica esa
    # celda está vacía porque ese mes no tuvo nada, no porque falte el dato.
    largo = largo[largo[medida].notna() & (largo[medida].astype(str).str.strip() != "")]
    orden = [c for c in id_vars if c in largo.columns] + [eje]
    largo = largo.sort_values(orden, kind="stable").reset_index(drop=True)
    log = [
        f"{len(period_cols)} columnas de mes ({', '.join(str(c) for c in period_cols[:3])}"
        f"{'…' if len(period_cols) > 3 else ''}) convertidas en filas: la tabla queda con una "
        f"columna «{eje}» y una columna «{medida}», como una tabla normal."
    ]
    return largo, log


def staircase_fill(df: pd.DataFrame, columns) -> int:
    """Relleno hacia abajo (ffill), pero solo dentro de columnas que ya se
    confirmó que son de etiqueta/agrupación de una dinámica (ver el gateo en
    _read_excel_sheet — nunca se llama a esto sobre una tabla que no mostró
    ninguna otra señal de ser dinámica). Nunca rellena antes del primer
    valor real de la columna (si la propia tabla empieza sin ese dato, se
    queda sin dato, no se inventa uno)."""
    filled = 0
    for c in columns:
        if c not in df.columns:
            continue
        before = df[c].copy()
        df[c] = df[c].ffill()
        # No rellenar filas que nunca tuvieron un valor real arriba.
        first_valid = before.first_valid_index()
        if first_valid is not None:
            mask_before_first = df.index < first_valid
            df.loc[mask_before_first, c] = before.loc[mask_before_first]
        filled += int((before.isna() & df[c].notna()).sum())
    return filled


def _max_run(mask: pd.Series) -> int:
    """La racha más larga de True seguidos. Vectorizado (agrupando por el
    acumulado de los False) para no recorrer fila por fila: esto corre sobre
    la tabla completa, que puede traer cientos de miles de filas."""
    if mask is None or not len(mask) or not bool(mask.any()):
        return 0
    return int(mask.groupby((~mask).cumsum()).sum().max())


def _is_blank(series: pd.Series) -> pd.Series:
    """True donde la celda no tiene contenido real: NaN o texto vacío. Un
    CSV exportado desde una dinámica trae lo segundo (la celda existe, viene
    con ""), un Excel trae lo primero — para el análisis son lo mismo."""
    return series.isna() | (series.astype(str).str.strip().isin(["", "nan", "None"]))


def period_like_columns(columns) -> list:
    """(Señal b) Columnas cuyo NOMBRE es un mes, un año o una fecha.

    En una tabla ordenada el periodo es un VALOR dentro de una columna
    ("Mes"); si el periodo es el NOMBRE de la columna ("ene-26", "2025",
    "2026-01"), esos periodos fueron pivoteados a columnas — la firma de una
    dinámica ancha. Se exige más de una para que un nombre de columna que por
    casualidad parezca un mes no arrastre a toda la tabla.

    Reutiliza `informe.periodo_de` (el mismo parser de meses que usa el
    lector de informes: entiende "ene-26", "Oct", "2026-01", Timestamp) en
    vez de una segunda lista de meses que se desincronice con aquella.
    """
    from .informe import periodo_de  # import local: rompe cualquier riesgo de ciclo

    out = []
    for c in columns:
        texto = _cell_text(c)
        if not texto:
            continue
        try:
            if periodo_de(c) is not None or periodo_de(texto) is not None:
                out.append(c)
                continue
        except Exception:
            pass
        # Un año suelto como encabezado ("2024", "2025") no lo cubre
        # periodo_de (no nombra un mes) y es igual de buena señal.
        m = re.fullmatch(r"(?:a[ñn]o\s*)?(\d{4})", texto, re.I)
        if m and 1990 <= int(m.group(1)) <= 2100:
            out.append(c)
    return out


def staircase_columns(df: pd.DataFrame, label_cols) -> list:
    """(Señal a) Columnas de etiqueta con huecos "en escalera".

    Es la huella que deja el layout Compacto/Esquema de una dinámica (y una
    celda combinada exportada a CSV): la etiqueta del grupo aparece UNA vez,
    en su primera fila, y las demás filas del grupo llegan vacías.

    El problema de detectarlo es distinguirlo de un dato realmente ausente
    (una "Ciudad" que nadie llenó). Se piden cuatro condiciones a la vez, y
    las dos últimas son las que evitan el falso positivo:

    1. La columna tiene huecos, pero no está vacía.
    2. La primera fila NO es un hueco: una escalera siempre empieza por el
       nombre del grupo; un dato ausente puede faltar desde la primera fila.
    3. Hay al menos una racha de 2+ huecos seguidos ("consecutivos"): un
       grupo agrupa varias filas. Huecos sueltos y dispersos son ausencias.
    4. A su DERECHA hay otra columna de etiqueta prácticamente llena: la
       escalera existe porque un nivel de detalle se repite bajo un nivel de
       grupo. Una columna de ausencias reales no tiene por qué traer detrás
       una columna completa, y —sobre todo— la columna de ausencias suele ir
       DESPUÉS de la que identifica la fila, no antes.
    """
    label_cols = [c for c in label_cols if c in df.columns]
    if len(label_cols) < 2 or df.empty:
        return []
    blanks = {c: _is_blank(df[c]) for c in label_cols}
    ratios = {c: float(blanks[c].mean()) for c in label_cols}
    out = []
    for i, c in enumerate(label_cols[:-1]):
        hueco = blanks[c]
        if not bool(hueco.any()) or bool(hueco.all()):
            continue
        if bool(hueco.iloc[0]):
            continue
        if _max_run(hueco) < 2:
            continue
        if not any(ratios[r] <= 0.10 and ratios[r] < ratios[c] for r in label_cols[i + 1:]):
            continue
        out.append(c)
    return out


def detect_pivot_signals(df: pd.DataFrame, header_rows: int = 1, total_rows: int = 0,
                         label_cols=None) -> dict:
    """¿Esta tabla venía de una dinámica, o es una tabla plana de verdad?

    Se responde ANTES de tocar los datos, mirando las cuatro señales que deja
    una dinámica al aterrizar en una cuadrícula:

    a. `staircase_columns` — etiquetas heredadas (celdas combinadas o layout
       Compacto/Esquema).
    b. `period_like_columns` — meses/años/fechas como NOMBRES de columna.
    c. `total_rows` — filas de subtotal/total general mezcladas con los datos
       (las cuenta `total_row_mask`, que corre justo antes).
    d. `header_rows > 1` — más de una fila de encabezado antes de los datos
       (las detecta y combina `flatten_pivot_grid`).

    Las celdas combinadas reales del .xlsx no entran aquí porque se resuelven
    antes y en otro nivel (`merged_ranges_by_sheet` + `fill_merged_cells`, en
    core/loader.py): cuando esta función corre, esas celdas ya tienen su
    valor y lo que queda es la señal (a).

    Devuelve las señales encontradas y, en `motivos`, cómo decirlo en
    español para el log de la pestaña Calidad — nunca decide sola: quien
    llama sigue eligiendo qué hacer con cada señal.
    """
    if df is None or df.empty:
        return {"staircase_columns": [], "period_columns": [], "total_rows": 0,
                "header_rows": header_rows, "es_dinamica": False, "motivos": []}
    if label_cols is None:
        label_cols = [
            c for c in df.columns
            if pd.to_numeric(df[c], errors="coerce").notna().mean() < 0.5
        ][:6]
    escalera = staircase_columns(df, label_cols)
    periodos = period_like_columns(df.columns)
    motivos = []
    if header_rows > 1:
        motivos.append(f"encabezado de {header_rows} filas")
    if total_rows:
        motivos.append(f"{total_rows} fila(s) de subtotal/total")
    if len(periodos) >= 2:
        muestra = ", ".join(str(c) for c in periodos[:3])
        motivos.append(f"{len(periodos)} columnas con nombre de periodo ({muestra}…)")
    if escalera:
        motivos.append("etiquetas heredadas de la fila de arriba en: "
                       + ", ".join(str(c) for c in escalera))
    return {
        "staircase_columns": escalera,
        "period_columns": periodos,
        "total_rows": int(total_rows),
        "header_rows": int(header_rows),
        "es_dinamica": bool(motivos),
        "motivos": motivos,
    }


def flatten_pivot_grid(raw: pd.DataFrame, header_score_fn, norm_header_fn, make_unique_fn,
                       year_hint=None):
    """Punto de entrada único, usado por core/loader.py en vez del antiguo
    "una sola fila de encabezado, listo". Devuelve (data_df, log) — log es
    una lista de mensajes en español, listos para sumarse al log de
    limpieza que ya se muestra en la pestaña Calidad.

    header_score_fn/norm_header_fn/make_unique_fn: las mismas funciones de
    loader.py (_header_score, _norm_header, _make_unique_columns) — se
    reciben por parámetro en vez de importarlas para no crear un ciclo de
    imports entre los dos módulos.

    year_hint: el año deducido del nombre del archivo y de la hoja, para los
    meses que llegan como nombre de columna sin año ("Oct" en vez de
    "oct-26"). Sin él esos meses se quedan como texto en vez de fecha; es el
    mismo dato que core/loader.py ya le pasa a core/informe.py.
    """
    log: list[str] = []
    if raw.empty:
        return raw, log

    limit = min(len(raw), 15)
    candidates = [(i, header_score_fn(raw.iloc[i])) for i in range(limit)]
    best_i, best_score = max(candidates, key=lambda x: x[1])
    first_score = candidates[0][1]
    confident = True
    if first_score >= 0.58 and first_score >= best_score - 0.04:
        header_i = 0
    elif best_score >= 0.55:
        header_i = best_i
    else:
        header_i = 0
        confident = False

    def _nonempty_count(i):
        return sum(1 for v in raw.iloc[i].tolist() if norm_header_fn(v))

    def _is_title_row(i):
        """Fila con UN solo valor repetido en TODAS sus celdas, sin ningún
        hueco (p. ej. el título de un reporte, "INFORME PDC TaT TROPAS",
        combinado en toda la fila y ya rellenado por fill_merged_cells).
        Nunca es un encabezado real — un encabezado real, por definición,
        nombra columnas DISTINTAS. Se comprueba aparte de is_super_header_row
        (que sí permite un valor repetido, pero solo si agrupa una PARTE del
        ancho — un super-encabezado real dos niveles abajo)."""
        values = [norm_header_fn(v) for v in raw.iloc[i].tolist()]
        nonempty = [v for v in values if v]
        return len(nonempty) == len(values) and len(nonempty) >= 2 and len(set(nonempty)) == 1

    # ── "Mirar abajo": dos motivos para desconfiar de la fila elegida y
    # preferir la de abajo como encabezado real:
    # 1. Es un título de fila completa (_is_title_row) — nunca es un
    #    encabezado, así que este caso se corrige SIEMPRE, sin importar el
    #    puntaje (un título con una frase que por casualidad toca una
    #    palabra del diccionario semántico podría incluso puntuar "confident").
    # 2. (Solo si 1 no aplicó) NINGUNA fila superó el umbral de confianza de
    #    arriba — columnas tipo "Q1"/"Q2" casi nunca traen ninguna palabra
    #    del diccionario semántico de _header_score, así que un
    #    super-encabezado real puede quedar por debajo de 0.55 aunque sea
    #    perfectamente válido — la fila elegida por defecto (0) puede ser
    #    ese super-encabezado, con el encabezado real justo debajo; se
    #    detecta comparando: la fila de abajo puntúa claramente mejor Y
    #    tiene más celdas llenas (agrupa menos que lo que agrupa).
    # Sin ninguno de los dos, header_i se hubiera quedado apuntando a una
    # fila que no es el encabezado real, y esa fila real se habría leído
    # como si fuera un dato más. ──
    # Fila(s) de título descartadas — a diferencia de un super-encabezado,
    # un título NUNCA se combina con el encabezado real (produciría columnas
    # como "INFORME PDC TaT TROPAS · 2024"), se tira sin más.
    discarded_title_rows = 0
    while header_i + 1 < limit and _is_title_row(header_i):
        header_i += 1
        discarded_title_rows += 1
        confident = False  # la fila ahora elegida todavía no pasó el chequeo de puntaje
    if discarded_title_rows:
        log.append(
            f"{discarded_title_rows} fila(s) de título (texto repetido en toda la fila, "
            "sin relación con los datos) descartada(s) del encabezado."
        )

    header_rows = [header_i]
    if not confident and header_i + 1 < limit:
        below_score = candidates[header_i + 1][1]
        chosen_nonempty = _nonempty_count(header_i)
        below_nonempty = _nonempty_count(header_i + 1)
        if (
            below_score >= 0.45
            and below_score >= candidates[header_i][1] + 0.15
            and chosen_nonempty > 0
            and below_nonempty > chosen_nonempty
        ):
            header_rows = [header_i, header_i + 1]

    # ── Encabezado de varias filas: se absorben hasta 2 filas extra por
    # ARRIBA del primer renglón del encabezado mientras cada una siga
    # viéndose como un super-encabezado real (agrupa, no repite un título
    # suelto) — cubre el caso contrario al de arriba: cuando header_i SÍ
    # cayó bien en la fila de nombres de columna real, y el super-encabezado
    # (con sus celdas ya rellenadas si venían de una combinación real de
    # Excel) está un renglón antes. ──
    probe = header_rows[0] - 1
    levels_absorbed = 0
    while probe >= 0 and levels_absorbed < 2:
        values = [norm_header_fn(v) for v in raw.iloc[probe].tolist()]
        if not is_super_header_row(values):
            break
        header_rows.insert(0, probe)
        probe -= 1
        levels_absorbed += 1

    if len(header_rows) > 1:
        combined = [norm_header_fn(v) for v in raw.iloc[header_rows[0]].tolist()]
        for r in header_rows[1:]:
            combined = combine_header_rows(combined, [norm_header_fn(v) for v in raw.iloc[r].tolist()])
        header_values = combined
        log.append(
            f"Encabezado de {len(header_rows)} filas combinadas en una sola "
            f"(filas {header_rows[0] + 1} a {header_rows[-1] + 1} del Excel)."
        )
    else:
        header_values = [norm_header_fn(v) for v in raw.iloc[header_i].tolist()]

    header = make_unique_fn(header_values)
    data_df = raw.iloc[header_rows[-1] + 1:].copy()
    data_df.columns = header
    data_df = data_df.dropna(axis=0, how="all").dropna(axis=1, how="all")
    data_df = data_df.reset_index(drop=True)
    if data_df.empty:
        return data_df, log

    # ── Filas de subtotal / total general ──
    label_cols = [
        c for c in data_df.columns
        if pd.to_numeric(data_df[c], errors="coerce").notna().mean() < 0.5
    ][:6]
    mask = total_row_mask(data_df, label_cols)
    n_total_rows = int(mask.sum())
    pivot_signal = n_total_rows > 0 or len(header_rows) > 1
    if n_total_rows:
        log.append(
            f"{n_total_rows} fila(s) de subtotal/total general excluida(s) "
            "automáticamente (no son un registro, son un agregado)."
        )
        data_df = data_df.loc[~mask].reset_index(drop=True)

    # ── ¿Dinámica o tabla plana? ──
    # Se pregunta explícitamente antes de tocar nada (ver detect_pivot_signals:
    # etiquetas en escalera, meses/años como nombres de columna, filas de
    # total, encabezado de varias filas).
    señales = detect_pivot_signals(data_df, header_rows=len(header_rows),
                                   total_rows=n_total_rows, label_cols=label_cols)

    # ── Etiquetas de fila heredadas (layout Compacto/Esquema) ──
    # Gateado a propósito: una columna de texto con huecos, por sí sola, puede
    # ser dato real ausente y no una etiqueta heredada. Hay dos puertas:
    #
    # 1. Señal FUERTE ya conocida (encabezado multi-fila o filas de total):
    #    se mantiene exactamente la regla de siempre —laxa a propósito, porque
    #    con esa señal la tabla ya se sabe dinámica y conviene rellenar todo lo
    #    que parezca etiqueta.
    # 2. Sin esa señal: antes no se rellenaba NADA, y ahí caía el caso más
    #    común de todos —una dinámica exportada a CSV, con un solo encabezado y
    #    sin totales, que llegaba con la mitad de la columna de grupo vacía.
    #    Ahora se rellena, pero solo las columnas que pasan el test estricto de
    #    escalera (staircase_columns), que es el que sabe distinguirla de un
    #    dato ausente.
    if pivot_signal:
        candidate_cols = []
        for c in label_cols[:4]:
            s = data_df[c]
            blank_ratio = s.isna().mean()
            if 0.03 <= blank_ratio <= 0.85 and pd.notna(s.iloc[0] if len(s) else None):
                candidate_cols.append(c)
    elif señales["es_dinamica"]:
        candidate_cols = señales["staircase_columns"]
        if candidate_cols:
            log.append("Se leyó como tabla dinámica por: " + "; ".join(señales["motivos"]) + ".")
    else:
        candidate_cols = []

    if candidate_cols:
        n_filled = staircase_fill(data_df, candidate_cols)
        if n_filled:
            cols_txt = ", ".join(str(c) for c in candidate_cols)
            log.append(
                f"{n_filled} celda(s) de categoría heredadas de la fila de arriba "
                f"(típico de tablas dinámicas), rellenadas en: {cols_txt}."
            )

    # ── Columnas de Total y despivotado ──
    # Solo cuando la tabla se reconoció como dinámica: sobre una tabla plana
    # nada de esto aplica (no tiene columnas de mes que devolver a filas), y
    # el propio `unpivot_period_columns` vuelve a comprobarlo antes de tocar
    # nada. El orden importa: primero se quita el Total —si no, se despivota
    # también y aparece como un "mes" más—, y el relleno de etiquetas ya pasó
    # arriba, porque al despivotar cada etiqueta se copia en sus filas nuevas
    # y un hueco sin rellenar se multiplicaría por cada mes.
    if señales["es_dinamica"]:
        cols_total = total_columns(data_df)
        if cols_total and len(data_df.columns) > len(cols_total):
            data_df = data_df.drop(columns=cols_total)
            log.append(
                f"{len(cols_total)} columna(s) de total ({', '.join(str(c) for c in cols_total)}) "
                "excluida(s): repiten la suma de su propia fila."
            )
        data_df, log_melt = unpivot_period_columns(
            data_df, señales["period_columns"], year_hint=year_hint)
        log += log_melt

    return data_df, log
