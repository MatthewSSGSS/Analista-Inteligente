"""Filas que no son registros: encabezados repetidos y notas al pie.

Dos formas muy comunes en un Excel armado a mano, que llegaban al panel como
si fueran datos:

1. Encabezado repetido a mitad de la tabla. Quien junta dos bloques (enero y
   febrero, dos sucursales) copia también la fila de títulos. Esa fila metía
   la palabra «Valor» dentro de la columna Valor, y bastaba eso para que la
   columna no llegara al 85 % de números y quedara entera como texto: sin
   KPIs. Si encima del encabezado repetido hay un rótulo suelto («VENTAS
   FEBRERO»), también sale: es el título del segundo bloque.
2. Notas al pie: «Fuente: sistema comercial», «Elaboró: …», «* Cifras en
   pesos». Se contaban como registros con todo vacío menos la primera celda.

Solo se aplica a hojas de datos planas (core/loader, después de
`flatten_pivot_grid`); las tablas que salen de un informe tienen sus propias
reglas. Nunca se quita una fila que tenga cifras: un registro con el nombre
y los números en blanco tampoco se quita si es corto, porque puede ser real.
"""
from __future__ import annotations

import re
import unicodedata

import pandas as pd

# Cómo empieza una nota al pie. Se exige al principio del texto.
_NOTA_RE = re.compile(
    r"^\s*(\*|fuente|nota|notas|elabor|generad|actualizad|fecha de corte|corte\s*:|observaci|"
    r"cifras|valores en|datos tomados|preparado por|reporte generado|confidencial)",
    re.I,
)


def _clave(v) -> str:
    t = unicodedata.normalize("NFKD", str(v))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def _celdas_llenas(fila: pd.Series) -> pd.Series:
    texto = fila.astype(str).str.strip()
    return fila[fila.notna() & (texto != "") & (texto.str.lower() != "nan")]


def _es_encabezado(fila: pd.Series, claves_columnas: dict) -> bool:
    llenas = _celdas_llenas(fila)
    if len(llenas) < 2:
        return False
    iguales = sum(1 for c, v in llenas.items() if _clave(v) and _clave(v) == claves_columnas[c])
    return iguales >= 2 and iguales >= 0.6 * len(llenas)


def _rotulo_suelto(fila: pd.Series) -> str | None:
    """El texto, si la fila es una sola celda de texto (un título o una nota)."""
    llenas = _celdas_llenas(fila)
    if len(llenas) != 1:
        return None
    valor = llenas.iloc[0]
    if not isinstance(valor, str) or re.fullmatch(r"[\d\s.,$%()-]+", valor):
        return None
    return valor.strip()


def quitar_filas_basura(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """(tabla sin encabezados repetidos ni notas al pie, registro de lo quitado)."""
    if df is None or df.empty or len(df.columns) < 3 or len(df) < 3:
        return df, []
    claves_columnas = {c: _clave(re.sub(r"_\d+$", "", str(c))) for c in df.columns}
    quitar = set()
    encabezados = 0
    rotulos = []
    filas = list(df.index)
    for i, idx in enumerate(filas):
        if _es_encabezado(df.loc[idx], claves_columnas):
            quitar.add(idx)
            encabezados += 1
            # El rótulo justo encima del encabezado repetido es el título del
            # bloque que empieza ahí («VENTAS FEBRERO»).
            if i > 0 and filas[i - 1] not in quitar:
                rotulo = _rotulo_suelto(df.loc[filas[i - 1]])
                if rotulo:
                    quitar.add(filas[i - 1])
                    rotulos.append(rotulo)

    # Notas al pie: el bloque final de filas de una sola celda de texto. Se
    # recorre desde abajo y se para en el primer registro de verdad.
    notas = []
    for idx in reversed(filas):
        if idx in quitar:
            continue
        rotulo = _rotulo_suelto(df.loc[idx])
        if rotulo is None:
            if _celdas_llenas(df.loc[idx]).empty:
                quitar.add(idx)  # fila vacía entre las notas
                continue
            break
        # Una frase larga o algo que empieza como nota; un texto corto suelto
        # («Ana») puede ser un registro con las cifras en blanco.
        if _NOTA_RE.search(rotulo) or (len(rotulo) >= 25 and rotulo.count(" ") >= 3):
            quitar.add(idx)
            notas.append(rotulo)
        else:
            break

    if not quitar:
        return df, []
    log = []
    if encabezados:
        extra = f" y {len(rotulos)} título(s) de bloque («{rotulos[0][:40]}»)" if rotulos else ""
        log.append(f"{encabezados} fila(s) que repetían el encabezado a mitad de la tabla{extra} quitada(s): "
                   "no son registros.")
    if notas:
        log.append(f"{len(notas)} nota(s) al pie quitada(s) («{notas[-1][:40]}»): no son registros.")
    return df.drop(index=sorted(quitar)).reset_index(drop=True), log
