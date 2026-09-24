"""Lectura del formato binario de Excel (.xlsb), compartida.

Un .xlsb es un zip como el .xlsx, pero sus partes no son XML sino una
secuencia de registros binarios: cada uno trae su tipo, su largo y su
contenido. pandas lo lee para sacar los valores de las celdas (vía pyxlsb),
pero no expone nada de la ESTRUCTURA —qué hojas están ocultas, qué filas y
columnas se escondieron, qué celdas están combinadas—, y eso es justo lo que
hace falta para leer un tablero como se ve en pantalla.

Aquí está solo lo común a esas tres lecturas (`core/hojas_ocultas.py`,
`core/celdas_ocultas.py` y `core/pivot_flatten.py`): recorrer los registros y
saber qué parte del zip corresponde a cada hoja.
"""
from __future__ import annotations

import posixpath
import struct
import xml.etree.ElementTree as ET

_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"

BRT_BUNDLE_SH = 156     # una hoja del libro: su estado, su parte y su nombre


def registros(b: bytes):
    """Los registros de una parte binaria, como (id, contenido).

    Cada registro empieza con su tipo (uno o dos bytes, el bit alto del
    primero indica que sigue otro) y su largo (hasta cuatro bytes, siete bits
    útiles cada uno). Es el mismo recorrido para cualquier parte del archivo.
    """
    i = 0
    while i < len(b):
        x = b[i]; i += 1
        rid = x & 0x7F
        if x & 0x80:
            rid |= (b[i] & 0x7F) << 7; i += 1
        largo = desplazamiento = 0
        for _ in range(4):
            y = b[i]; i += 1
            largo |= (y & 0x7F) << desplazamiento
            desplazamiento += 7
            if not y & 0x80:
                break
        yield rid, b[i:i + largo]
        i += largo


def _texto(cuerpo: bytes, desde: int):
    """(texto, posición siguiente) de una cadena: su largo y luego UTF-16."""
    largo = struct.unpack("<I", cuerpo[desde:desde + 4])[0]
    if largo == 0xFFFFFFFF:
        return "", desde + 4
    fin = desde + 4 + 2 * largo
    return cuerpo[desde + 4:fin].decode("utf-16le", "ignore"), fin


def hojas(z) -> list:
    """[(nombre, estado, ruta de su parte)] de cada hoja del libro.

    El estado es 0 visible, 1 oculta y 2 muy oculta, tal como lo guarda Excel.
    """
    if "xl/workbook.bin" not in z.namelist():
        return []
    rels = {}
    if "xl/_rels/workbook.bin.rels" in z.namelist():
        for rel in ET.fromstring(z.read("xl/_rels/workbook.bin.rels")).findall(f"{{{_PKG}}}Relationship"):
            destino = rel.get("Target", "")
            destino = destino[1:] if destino.startswith("/") else posixpath.normpath(
                posixpath.join("xl", destino))
            rels[rel.get("Id")] = destino
    salida = []
    for rid, cuerpo in registros(z.read("xl/workbook.bin")):
        if rid != BRT_BUNDLE_SH or len(cuerpo) < 16:
            continue
        estado = struct.unpack("<I", cuerpo[0:4])[0]
        relid, siguiente = _texto(cuerpo, 8)
        nombre, _ = _texto(cuerpo, siguiente)
        if nombre:
            salida.append((nombre, estado, rels.get(relid)))
    return salida
