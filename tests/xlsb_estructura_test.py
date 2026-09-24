"""La estructura de un .xlsb: hojas ocultas, filas/columnas ocultas y celdas combinadas.

Un .xlsb no es XML sino una secuencia de registros binarios, y pandas (vía
pyxlsb) saca los valores pero nada de la estructura. Antes `merged_ranges_by_sheet`
devolvía `{}` para este formato, así que un tablero .xlsb perdía TODOS los
rótulos apoyados en una celda combinada: en el archivo real («Inf ventas -
R1.xlsb», hoja «Dash») «Pospago», «Accesos» y «Hogar» viven cada uno en una
sola celda combinada sobre sus columnas, y encima esa celda cae en una columna
oculta — así que al leer la hoja como se ve desaparecían y las columnas salían
«Presupuesto_2», «Presupuesto_3», sin decir de qué grupo eran.

El riesgo que cubre en especial: el registro guarda (fila1, fila2, col1, col2)
y el resto del proyecto usa (fila1, col1, fila2, col2). Confundirlos no falla
con un error, rellena la hoja con el valor equivocado.

Se arma aquí un .xlsb mínimo, byte a byte, porque openpyxl no sabe escribir
este formato.

PYTHONPATH=. python tests/xlsb_estructura_test.py
"""
import io
import struct
import zipfile

import pandas as pd

from core.celdas_ocultas import filas_y_columnas_ocultas
from core.hojas_ocultas import hojas_ocultas
from core.pivot_flatten import fill_merged_cells, merged_ranges_by_sheet
from core.xlsb import registros


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


# ── Escritura del formato binario, para poder probar la lectura ──────────────

def _registro(rid: int, cuerpo: bytes) -> bytes:
    """Un registro: su tipo, su largo y su contenido, como lo guarda Excel."""
    salida = bytearray()
    if rid < 0x80:
        salida.append(rid)
    else:
        salida.append((rid & 0x7F) | 0x80)
        salida.append((rid >> 7) & 0x7F)
    largo = len(cuerpo)
    while True:
        byte = largo & 0x7F
        largo >>= 7
        salida.append(byte | (0x80 if largo else 0))
        if not largo:
            break
    return bytes(salida) + cuerpo


def _cadena(texto: str) -> bytes:
    return struct.pack("<I", len(texto)) + texto.encode("utf-16le")


def _libro(hojas) -> bytes:
    """hojas: [(nombre, estado, filas ocultas, columnas ocultas, combinadas)]."""
    partes = {}
    libro = b""
    rels = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for i, (nombre, estado, filas, columnas, combinadas) in enumerate(hojas, 1):
        libro += _registro(156, struct.pack("<II", estado, i) + _cadena(f"rId{i}") + _cadena(nombre))
        rels.append(f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.bin" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships/worksheet"/>')
        hoja = b""
        for r in filas:
            # rw(4) ixfe(4) miyRw(2) banderas(2): el bit 4 del último byte es "oculta".
            hoja += _registro(0, struct.pack("<IIH", r, 0, 300) + bytes([0, 1 << 4]))
        for c1, c2 in columnas:
            hoja += _registro(60, struct.pack("<IIII", c1, c2, 2000, 0) + bytes([1, 0]))
        for r1, r2, c1, c2 in combinadas:
            hoja += _registro(176, struct.pack("<IIII", r1, r2, c1, c2))
        partes[f"xl/worksheets/sheet{i}.bin"] = hoja
    rels.append("</Relationships>")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.bin", libro)
        z.writestr("xl/_rels/workbook.bin.rels", "".join(rels))
        for ruta, contenido in partes.items():
            z.writestr(ruta, contenido)
    return buf.getvalue()


def test_los_registros_se_recorren_bien():
    datos = _registro(0, b"ab") + _registro(156, b"cd") + _registro(176, b"efgh")
    check("el tipo y el contenido de cada registro salen enteros",
          [(r, c) for r, c in registros(datos)] == [(0, b"ab"), (156, b"cd"), (176, b"efgh")])
    largo = _registro(60, b"x" * 300)
    check("un registro largo (más de 127 bytes) también",
          [(r, len(c)) for r, c in registros(largo)] == [(60, 300)])


def test_las_celdas_combinadas_salen_con_sus_coordenadas_en_orden():
    # Combinada de la fila 0, columnas 1 a 8: el registro la guarda como
    # (fila1, fila2, col1, col2) = (0, 0, 1, 8).
    data = _libro([("Dash", 0, [], [], [(0, 0, 1, 8), (2, 4, 3, 3)])])
    rangos = merged_ranges_by_sheet(data, "informe.xlsb")
    check("se leen las celdas combinadas de un .xlsb (antes devolvía vacío)",
          rangos.get("Dash") == [(0, 1, 0, 8), (2, 3, 4, 3)])

    # La prueba de fuego: rellenar con ellas tiene que extender el rótulo a lo
    # ANCHO, no hacia abajo. Con el orden cambiado, «Prepago» bajaría por la
    # columna 0 y las columnas 1-8 quedarían vacías.
    grid = pd.DataFrame([[None] * 10 for _ in range(5)])
    grid.iat[0, 1] = "Prepago"
    fill_merged_cells(grid, rangos["Dash"])
    check("el rótulo combinado llega a todas las columnas de su grupo",
          list(grid.iloc[0, 1:9]) == ["Prepago"] * 8)
    check("y no se derrama a la fila de abajo", grid.iat[1, 1] is None or pd.isna(grid.iat[1, 1]))


def test_las_hojas_ocultas_de_un_xlsb():
    data = _libro([("Dash", 0, [], [], []), ("Hoja2", 1, [], [], []), ("Respaldo", 2, [], [], [])])
    check("se leen las ocultas y las muy ocultas de un .xlsb",
          hojas_ocultas(data, "informe.xlsb") == {"Hoja2", "Respaldo"})


def test_las_filas_y_columnas_ocultas_de_un_xlsb():
    data = _libro([("Dash", 0, [2, 4, 5], [(6, 9)], [])])
    filas, columnas = filas_y_columnas_ocultas(data, "informe.xlsb")["Dash"]
    check("las filas ocultas salen contando desde 0", filas == {2, 4, 5})
    check("y un rango de columnas se expande a cada una", columnas == {6, 7, 8, 9})


def test_un_xlsb_ilegible_no_tumba_la_carga():
    check("celdas combinadas", merged_ranges_by_sheet(b"no soy un xlsb", "roto.xlsb") == {})
    check("hojas ocultas", hojas_ocultas(b"no soy un xlsb", "roto.xlsb") == set())
    check("filas y columnas ocultas", filas_y_columnas_ocultas(b"no soy un xlsb", "roto.xlsb") == {})


if __name__ == "__main__":
    test_los_registros_se_recorren_bien()
    test_las_celdas_combinadas_salen_con_sus_coordenadas_en_orden()
    test_las_hojas_ocultas_de_un_xlsb()
    test_las_filas_y_columnas_ocultas_de_un_xlsb()
    test_un_xlsb_ilegible_no_tumba_la_carga()
    print("\nEstructura .xlsb test completado sin errores.")
