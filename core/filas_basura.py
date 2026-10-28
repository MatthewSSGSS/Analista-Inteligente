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

import numpy as np
import pandas as pd

# Columnas de tipo genérico que solo traen números (infer_dtype, en C).
_SOLO_NUMEROS = {"integer", "floating", "mixed-integer-float", "decimal", "empty"}

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


def _rotulo_suelto(fila: pd.Series) -> str | None:
    """El texto, si la fila es una sola celda de texto (un título o una nota)."""
    llenas = _celdas_llenas(fila)
    if len(llenas) != 1:
        return None
    valor = llenas.iloc[0]
    if not isinstance(valor, str) or re.fullmatch(r"[\d\s.,$%()-]+", valor):
        return None
    return valor.strip()


def _llenas_por_celda(df: pd.DataFrame) -> pd.DataFrame:
    """Matriz True/False de celdas con algo, columna por columna (vectorizado)."""
    llenas = {}
    for i, c in enumerate(df.columns):
        s = df.iloc[:, i]
        hay = s.notna().to_numpy()
        if not pd.api.types.is_numeric_dtype(s) and pd.api.types.infer_dtype(s, skipna=True) not in _SOLO_NUMEROS:
            # Sobre los valores distintos: «vacío» depende solo del valor.
            codigos, unicos = pd.factorize(s)
            texto = pd.Series(unicos, dtype=object).astype(str).str.strip()
            vacio = ((texto == "") | (texto.str.lower() == "nan")).to_numpy()
            hay = hay & ~np.where(codigos >= 0, vacio[np.maximum(codigos, 0)], True)
        llenas[i] = hay
    return pd.DataFrame(llenas, index=df.index)


def _filas_encabezado(df: pd.DataFrame, llenas: pd.DataFrame) -> list:
    """Las filas que repiten el encabezado, sin recorrer la tabla fila por fila.

    Se mira cada columna sobre sus valores DISTINTOS y solo los de largo
    parecido al nombre de la columna (normalizar 120.000 cédulas para
    compararlas con «Cédula» costaba minutos). Antes esto iba fila por fila y
    en una base de 120.000 registros se llevaba más de cuatro minutos.
    """
    iguales = pd.Series(0, index=df.index)
    for i, c in enumerate(df.columns):
        clave = _clave(re.sub(r"_\d+$", "", str(c)))
        s = df.iloc[:, i]
        # Una columna de solo cifras no tiene dónde repetir un encabezado (si lo
        # repitiera, traería ese texto y ya no sería «solo cifras»).
        if not clave or pd.api.types.is_numeric_dtype(s) or pd.api.types.infer_dtype(s, skipna=True) in _SOLO_NUMEROS:
            continue  # una celda numérica nunca repite un encabezado de texto
        texto = s.dropna().astype(str)
        candidatos = [u for u in texto.unique() if abs(len(u.strip()) - len(clave)) <= 3 and _clave(u) == clave]
        if candidatos:
            iguales = iguales.add(s.isin(candidatos).astype(int), fill_value=0)
    if not iguales.any():
        return []
    n_llenas = llenas.sum(axis=1)
    es = (iguales >= 2) & (iguales >= 0.6 * n_llenas)
    return list(df.index[es.to_numpy()])


def quitar_filas_basura(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """(tabla sin encabezados repetidos ni notas al pie, registro de lo quitado)."""
    if df is None or df.empty or len(df.columns) < 3 or len(df) < 3:
        return df, []
    llenas = _llenas_por_celda(df)
    quitar = set()
    encabezados = 0
    rotulos = []
    filas = list(df.index)
    posicion = {idx: i for i, idx in enumerate(filas)}
    for idx in _filas_encabezado(df, llenas):
        i = posicion[idx]
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
    n_llenas = llenas.sum(axis=1)
    for idx in reversed(filas):
        if idx in quitar:
            continue
        if n_llenas[idx] == 0:
            quitar.add(idx)  # fila vacía entre las notas
            continue
        rotulo = _rotulo_suelto(df.loc[idx]) if n_llenas[idx] == 1 else None
        if rotulo is None:
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
