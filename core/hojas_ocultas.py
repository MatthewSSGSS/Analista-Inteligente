"""Qué hojas escondió Excel, para no analizar lo que nadie ve.

Un informe real lleva dentro sus hojas de trabajo: la base sin depurar, una
copia de respaldo, tablas de apoyo. Quien lo arma las oculta y deja a la vista
solo lo que se lee. El panel las abría todas por igual, así que un archivo de
dos pestañas visibles salía con ocho en el selector y arrancaba en una hoja
oculta —en el archivo real, «Hoja2», siete filas de apoyo— en vez de en la
base de 64.646 registros.

Aquí se lee ese estado tal como lo guarda cada formato. No se borra nada: las
ocultas siguen cargadas y se pueden mostrar cuando se piden, porque a veces la
que interesa es justo una de ellas («Compromiso»).
"""
from __future__ import annotations

import io
import re
import struct
import zipfile
import xml.etree.ElementTree as ET

_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _xlsx(data: bytes) -> set:
    z = zipfile.ZipFile(io.BytesIO(data))
    if "xl/workbook.xml" not in z.namelist():
        return set()
    libro = ET.fromstring(z.read("xl/workbook.xml"))
    return {h.get("name") for h in libro.iter(f"{{{_S}}}sheet")
            if (h.get("state") or "visible") != "visible" and h.get("name")}


def _registros(b: bytes):
    """Los registros del formato binario de Excel: (id, contenido)."""
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


def _xlsb(data: bytes) -> set:
    z = zipfile.ZipFile(io.BytesIO(data))
    if "xl/workbook.bin" not in z.namelist():
        return set()
    ocultas = set()
    for rid, cuerpo in _registros(z.read("xl/workbook.bin")):
        if rid != 156 or len(cuerpo) < 16:   # BrtBundleSh: una hoja del libro
            continue
        estado = struct.unpack("<I", cuerpo[0:4])[0]   # 0 visible, 1 oculta, 2 muy oculta
        largo_rel = struct.unpack("<I", cuerpo[8:12])[0]
        if largo_rel == 0xFFFFFFFF:
            largo_rel = 0
        inicio = 12 + 2 * largo_rel
        largo_nombre = struct.unpack("<I", cuerpo[inicio:inicio + 4])[0]
        nombre = cuerpo[inicio + 4:inicio + 4 + 2 * largo_nombre].decode("utf-16le", "ignore")
        if estado and nombre:
            ocultas.add(nombre)
    return ocultas


def _xls(data: bytes) -> set:
    import xlrd

    libro = xlrd.open_workbook(file_contents=data, on_demand=True)
    return {h.name for h in libro.sheets() if getattr(h, "visibility", 0)}


def hojas_ocultas(data: bytes, filename: str) -> set:
    """Los nombres de las hojas que Excel no muestra. Conjunto vacío si el
    formato no lo dice o si algo falla: no saberlo nunca debe impedir leer
    el archivo, solo hace que se muestren todas como hasta ahora."""
    nombre = (filename or "").lower()
    try:
        if nombre.endswith((".xlsx", ".xlsm")):
            return _xlsx(data)
        if nombre.endswith(".xlsb"):
            return _xlsb(data)
        if nombre.endswith(".xls"):
            return _xls(data)
    except Exception:
        return set()
    return set()
