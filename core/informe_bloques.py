"""Hojas tipo tablero: bloques apilados con cabecera de dos niveles, sin meses.

Son los informes comerciales armados con tablas dinámicas y segmentadores:

    (fila de grupos)    |  Prepago                 |  Pospago                 | …
    Total               |  158.386 79.146 113.066 …|  37.971 …
    (fila de cabecera)  Canal | Ppto | Act | Pry | % Cump | Ppto | Act | Pry | …
    CAV                 |  3.111 | 2.155 | 3.079 | 99,0% | …
    DIGITAL             |  …

y, más abajo, el mismo esquema otra vez pero con otra dimensión en la primera
columna (Jefe, Territorio, Coor/Sup/Esp…). Los segmentadores son objetos
flotantes, no celdas: no se pueden leer, y sus opciones ya salen en los filtros
del panel a partir de las columnas.

`core/informe.py` no lo reconoce porque no hay un eje de meses, y el camino de
hoja normal lo leía como una sola tabla con el segundo bloque metido entre los
datos. Aquí cada bloque se vuelve una tabla ordenada —una fila por Canal, Jefe,
etc.— con una columna por «Grupo · Medida» ("Prepago · Presupuesto",
"Hogar · % Cumplimiento"). La fila Total se excluye: es un agregado, y las
comparaciones se calculan sobre todo el grupo visible (ver CLAUDE.md).

Nada depende de nombres concretos: se busca una FORMA —una fila de cabecera
cuyos nombres se repiten bajo distintos grupos, con una fila de grupos
encima—, no las palabras Prepago o Canal.
"""
from __future__ import annotations

import re
from typing import Optional

import numpy as np
import pandas as pd

from .informe import _PORCENTAJE_RE, _es_texto, _norm, _numero, _parece_proporcion, _txt, periodo_de
from .pivot_flatten import es_total

MIN_COLUMNAS = 5     # columnas de medidas para considerar que hay una cabecera
MIN_FILAS = 2        # entidades mínimas bajo la cabecera
MAX_SUBIDA = 4       # filas que se miran hacia arriba buscando los grupos

# Abreviaturas de los informes comerciales, por palabra suelta.
_ABREV = {"ppto": "Presupuesto", "presup": "Presupuesto", "act": "Actual", "pry": "Proyección",
          "proy": "Proyección", "cump": "Cumplimiento", "cum": "Cumplimiento", "ejc": "Ejecución",
          "ejec": "Ejecución"}


def _es_cabecera_texto(v) -> bool:
    """Texto de cabecera: con letras y que no sea un mes ni un número."""
    return _es_texto(v) and periodo_de(v) is None


def _nombre_medida(texto: str) -> str:
    """"% Cump" → "% Cumplimiento"; "% C Dig" → "% Cumplimiento Dig"; "Pry Ins" → "Proyección Ins"."""
    t = re.sub(r"^%\s*c\b", "% Cump", _txt(texto), flags=re.I)
    palabras = [_ABREV.get(p.lower(), p) for p in t.split(" ")]
    return " ".join(palabras)


def _unico(nombres: list[str]) -> list[str]:
    vistos: dict = {}
    salida = []
    for n in nombres:
        vistos[n] = vistos.get(n, 0) + 1
        salida.append(n if vistos[n] == 1 else f"{n}_{vistos[n]}")
    return salida


# ── Cabeceras ───────────────────────────────────────────────────────────────

def _cabecera_en(G, r) -> Optional[tuple]:
    """(columna de la dimensión, columnas de medidas) si la fila r es una cabecera de bloque."""
    m = G.shape[1]
    celdas = [c for c in range(m) if _txt(G[r, c])]
    if len(celdas) < MIN_COLUMNAS + 1 or celdas[0] > 3:
        return None
    c0 = celdas[0]
    if not _es_cabecera_texto(G[r, c0]):
        return None
    medidas = [c for c in celdas[1:] if _es_cabecera_texto(G[r, c])]
    # Sin celdas numéricas ni fechas en la fila: si las hubiera sería una fila
    # de datos o un eje de meses, que es de core/informe.py.
    if len(medidas) < MIN_COLUMNAS or len(medidas) < 0.9 * (len(celdas) - 1):
        return None
    nombres = [_norm(G[r, c]) for c in medidas]
    repetidos = {x for x in nombres if nombres.count(x) >= 2}
    if len(repetidos) < 2:
        return None  # una tabla normal no repite sus encabezados bajo distintos grupos
    return c0, medidas


def _grupos_de(G, h, c0, medidas) -> dict:
    """{columna: grupo} leyendo la fila de grupos que esté sobre la cabecera (puede no haber)."""
    for k in range(1, MAX_SUBIDA + 1):
        r = h - k
        if r < 0:
            return {}
        fila = [(c, _txt(G[r, c])) for c in range(G.shape[1]) if _txt(G[r, c])]
        if not fila:
            continue  # fila oculta o en blanco
        if es_total(_txt(G[r, c0])) or any(np.isfinite(_numero(G[r, c])) for c, _ in fila):
            continue  # la fila Total va entre los grupos y la cabecera
        propios = {c: t for c, t in fila if c in medidas and _es_cabecera_texto(t)}
        if len(set(propios.values())) < 2:
            return {}
        # Con las celdas combinadas ya rellenas cada grupo ocupa varias columnas.
        # Si cada uno está en UNA sola celda ("centrar en la selección"), el
        # grupo sigue hasta el siguiente.
        if len(propios) == len(set(propios.values())):
            actual, grupos = None, {}
            for c in medidas:
                actual = propios.get(c, actual)
                if actual:
                    grupos[c] = actual
            return grupos
        return {c: propios[c] for c in medidas if c in propios}
    return {}


# ── Lectura de un bloque ────────────────────────────────────────────────────

def _fila_de_datos(G, r, c0, medidas) -> Optional[tuple]:
    """(etiqueta, valores) de una fila de entidad; None si ya no es del bloque."""
    etiqueta = _txt(G[r, c0])
    if not etiqueta:
        return None
    return etiqueta, [_numero(G[r, c]) for c in medidas]


def _leer_bloque(G, h, c0, medidas) -> Optional[dict]:
    n = G.shape[0]
    filas, totales, vacias = [], 0, 0
    r = h + 1
    while r < n:
        etiqueta = _txt(G[r, c0])
        if not etiqueta:
            break
        if _cabecera_en(G, r) is not None:
            break  # empieza el bloque siguiente
        if es_total(etiqueta):
            totales += 1
            r += 1
            continue
        _, valores = _fila_de_datos(G, r, c0, medidas)
        if any(np.isfinite(v) for v in valores):
            filas.append((etiqueta, valores))
        else:
            vacias += 1
            # Un rótulo suelto sin cifras (un título, la cabecera de otra cosa) cierra el bloque.
            if sum(1 for c in range(G.shape[1]) if _es_cabecera_texto(G[r, c])) >= 3:
                break
        r += 1
    if len(filas) < MIN_FILAS:
        return None
    return {"fila": h, "fin": r - 1, "dimension": _txt(G[h, c0]), "filas": filas,
            "totales": totales, "sin_cifras": vacias,
            "grupos": _grupos_de(G, h, c0, medidas), "columnas": medidas,
            "encabezados": [_txt(G[h, c]) for c in medidas]}


def _tabla(bloque: dict) -> pd.DataFrame:
    nombres = []
    for c, enc in zip(bloque["columnas"], bloque["encabezados"]):
        medida = _nombre_medida(enc)
        grupo = bloque["grupos"].get(c)
        nombres.append(f"{grupo} · {medida}" if grupo else medida)
    nombres = _unico(nombres)
    df = pd.DataFrame([[e] + v for e, v in bloque["filas"]], columns=[bloque["dimension"]] + nombres)
    df = df.drop_duplicates(subset=bloque["dimension"], keep="first").reset_index(drop=True)
    for col in nombres:
        if df[col].notna().sum() == 0:
            df = df.drop(columns=[col])
        elif _PORCENTAJE_RE.search(col) and _parece_proporcion(df[col]):
            df[col] = (df[col] * 100).round(2)  # 0,99 → 99 (%), como en core/informe.py
    return df


def leer_bloques(raw: pd.DataFrame, hoja: str) -> list[dict]:
    """Los bloques de una hoja tipo tablero, como {"nombre", "titulo", "datos", "log", "faltantes_son_cero"}.

    Lista vacía si la hoja no tiene esa forma: entonces sigue su camino de siempre.
    """
    if raw is None or raw.empty:
        return []
    G = raw.to_numpy(dtype=object)
    bloques, r = [], 0
    while r < G.shape[0]:
        cab = _cabecera_en(G, r)
        bloque = _leer_bloque(G, r, *cab) if cab else None
        if bloque is None:
            r += 1
            continue
        bloques.append(bloque)
        r = bloque["fin"] + 1
    # Es un tablero si algún bloque trae la fila de grupos, o si hay varios
    # bloques con la misma cabecera repetida (varias dimensiones).
    if not bloques or not (any(b["grupos"] for b in bloques) or len(bloques) > 1):
        return []

    salida, usados = [], {}
    for b in bloques:
        df = _tabla(b)
        if df.shape[1] < 2:
            continue
        dim = b["dimension"]
        usados[dim] = usados.get(dim, 0) + 1
        base = f"{hoja} · por {dim}" if len(bloques) > 1 else hoja
        nombre = base if usados[dim] == 1 else f"{base} ({usados[dim]})"
        grupos = list(dict.fromkeys(b["grupos"].values()))
        log = [f"Hoja «{hoja}» leída como tablero: «{nombre}» es el bloque de la fila {b['fila'] + 1} "
               f"({len(df)} filas por {dim.lower()}, {df.shape[1] - 1} columnas"
               + (f", agrupadas en {', '.join(grupos)}" if grupos else "") + ")."]
        if b["totales"]:
            log.append(f"{b['totales']} fila(s) de Total excluida(s): son un agregado, no un registro.")
        salida.append({"nombre": nombre, "titulo": nombre, "datos": df, "log": log,
                       "faltantes_son_cero": False})
    return salida
