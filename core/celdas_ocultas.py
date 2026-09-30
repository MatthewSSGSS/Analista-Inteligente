"""Qué filas y columnas escondió Excel dentro de una hoja.

Un tablero armado sobre tablas dinámicas trae debajo su andamiaje, y quien lo
arma lo esconde en vez de borrarlo: la fila «Periodo», la de «Etiquetas de
columna», la de «Suma de Activaciones», y columnas enteras de un grupo que ya
no se reporta. En la pantalla de Excel no está; en el archivo sí.

Leída sin mirar eso, la hoja «Dash» del informe real salía de 127×61 con el
andamiaje mezclado entre los datos: los rótulos de las tablas se tomaban como
categorías («Suma de Activaciones») y las columnas quedaban como «Columna 7»
o «Columna 18». Quitando lo oculto queda en 107×36 y se lee lo mismo que se ve.

Esto se aplica SOLO a las hojas que se leen como tablero (ver `core/loader`):
en una hoja de datos, un filtro activo esconde filas, y descartarlas ahí sería
perder registros sin avisar.

Se calcula una sola vez por archivo, no una vez por hoja, por lo mismo que
explica `core/pivot_flatten.merged_ranges_by_sheet`.
"""
from __future__ import annotations

import io
import posixpath
import re
import zipfile
import struct
import xml.etree.ElementTree as ET

from .xlsb import hojas as hojas_del_libro, registros
from .pivot_flatten import xml_sin_celdas

_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"

# Ids del formato binario (.xlsb), los mismos que usa Excel al guardar.
_BRT_ROW_HDR = 0        # cabecera de fila: trae el bit "alto cero" = oculta
_BRT_COL_INFO = 60      # ancho y estado de un rango de columnas

# Una columna más angosta que un carácter no muestra nada, aunque Excel no la
# marque como oculta: es la otra forma de esconder una columna, estrecharla
# hasta que desaparezca. En el informe real la columna B quedó en 0,14
# caracteres (36 de los 256 por carácter que usa el formato binario) y traía
# un «Act» de más que salía como una columna repetida en el análisis.
_ANCHO_INVISIBLE = 1.0          # en caracteres (.xlsx)
_ANCHO_INVISIBLE_BIN = 256      # lo mismo en .xlsb: 1/256 de carácter por unidad


def _partes_xlsx(z) -> dict:
    """{nombre de hoja: ruta de su XML}."""
    rels = {}
    if "xl/_rels/workbook.xml.rels" in z.namelist():
        for rel in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).findall(f"{{{_PKG}}}Relationship"):
            destino = rel.get("Target", "")
            destino = destino[1:] if destino.startswith("/") else posixpath.normpath(
                posixpath.join("xl", destino))
            rels[rel.get("Id")] = destino
    salida = {}
    libro = ET.fromstring(z.read("xl/workbook.xml"))
    for hoja in libro.iter(f"{{{_S}}}sheet"):
        parte = rels.get(hoja.get(f"{{{_R}}}id"))
        if parte and hoja.get("name"):
            salida[hoja.get("name")] = parte
    return salida


_FILA_OCULTA = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?row\s[^>]*?\bhidden\s*=\s*[\"'](?:1|true)[\"'][^>]*>")
_NUMERO_FILA = re.compile(rb"\sr\s*=\s*[\"'](\d+)[\"']")


def _xlsx(data: bytes) -> dict:
    z = zipfile.ZipFile(io.BytesIO(data))
    if "xl/workbook.xml" not in z.namelist():
        return {}
    salida = {}
    for nombre, parte in _partes_xlsx(z).items():
        if parte not in z.namelist():
            continue
        xml = z.read(parte)
        # Las filas ocultas se buscan como texto (en C) y el árbol se arma sin
        # las celdas: ver pivot_flatten.xml_sin_celdas.
        filas = set()
        for etiqueta in _FILA_OCULTA.finditer(xml):
            numero = _NUMERO_FILA.search(etiqueta.group(0))
            if numero:
                filas.add(int(numero.group(1)) - 1)
        hoja = ET.fromstring(xml_sin_celdas(xml))
        columnas = set()
        for col in hoja.iter(f"{{{_S}}}col"):
            try:
                ancho = float(col.get("width")) if col.get("width") else None
            except ValueError:
                ancho = None
            invisible = ancho is not None and ancho < _ANCHO_INVISIBLE and col.get("customWidth") in ("1", "true")
            if col.get("hidden") in ("1", "true") or invisible:
                try:
                    columnas.update(range(int(col.get("min")) - 1, int(col.get("max"))))
                except (TypeError, ValueError):
                    continue
        if filas or columnas:
            salida[nombre] = (filas, columnas)
    return salida


def _xlsb(data: bytes) -> dict:
    z = zipfile.ZipFile(io.BytesIO(data))
    salida = {}
    for nombre, _, parte in hojas_del_libro(z):
        if not parte or parte not in z.namelist():
            continue
        filas, columnas = set(), set()
        for rid, cuerpo in registros(z.read(parte)):
            # Fila: el bit "alto cero" (fDyZero) del byte de banderas.
            if rid == _BRT_ROW_HDR and len(cuerpo) >= 12 and (cuerpo[11] >> 4) & 1:
                filas.add(struct.unpack("<I", cuerpo[:4])[0])
            # Rango de columnas: el primer bit de sus banderas, o un ancho que
            # no da ni para un carácter (ver _ANCHO_INVISIBLE_BIN).
            elif rid == _BRT_COL_INFO and len(cuerpo) >= 18:
                primera, ultima, ancho = struct.unpack("<III", cuerpo[:12])
                if (cuerpo[16] & 1 or ancho < _ANCHO_INVISIBLE_BIN) and ultima - primera <= 16384:
                    columnas.update(range(primera, ultima + 1))
        if filas or columnas:
            salida[nombre] = (filas, columnas)
    return salida


def _xls(data: bytes) -> dict:
    import xlrd

    libro = xlrd.open_workbook(file_contents=data, formatting_info=True)
    salida = {}
    for hoja in libro.sheets():
        filas = {r for r, info in getattr(hoja, "rowinfo_map", {}).items() if getattr(info, "hidden", 0)}
        columnas = set()
        for c, info in getattr(hoja, "colinfo_map", {}).items():
            if getattr(info, "hidden", 0):
                columnas.add(c)
        if filas or columnas:
            salida[hoja.name] = (filas, columnas)
    return salida


def filas_y_columnas_ocultas(data: bytes, filename: str) -> dict:
    """{hoja: (filas ocultas, columnas ocultas)}, contando desde 0.

    Diccionario vacío si el formato no lo dice o si algo falla: no saberlo
    nunca debe impedir leer el archivo, solo deja la hoja como estaba.
    """
    nombre = (filename or "").lower()
    try:
        if nombre.endswith((".xlsx", ".xlsm")):
            return _xlsx(data)
        if nombre.endswith(".xlsb"):
            return _xlsb(data)
        if nombre.endswith(".xls"):
            return _xls(data)
    except Exception:
        return {}
    return {}


def sin_lo_oculto(grid, filas: set, columnas: set):
    """La cuadrícula con solo lo que se ve, reindexada desde 0.

    Devuelve la misma cuadrícula si no hay nada que quitar, o si quitarlo la
    dejaría sin filas o sin columnas (una hoja entera oculta no se analiza
    mejor vacía).
    """
    if grid is None or grid.empty or not (filas or columnas):
        return grid
    fuera_filas = [r for r in filas if r < grid.shape[0]]
    fuera_cols = [c for c in columnas if c < grid.shape[1]]
    if len(fuera_filas) >= grid.shape[0] or len(fuera_cols) >= grid.shape[1]:
        return grid
    visible = grid.drop(index=[grid.index[r] for r in fuera_filas],
                        columns=[grid.columns[c] for c in fuera_cols])
    visible = visible.reset_index(drop=True)
    visible.columns = range(visible.shape[1])
    return visible
