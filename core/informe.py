"""Hojas tipo informe: varias tablas, títulos y gráficos en una misma hoja.

El resto del panel espera una tabla por hoja: una fila de encabezados y un
registro por fila. Un informe armado a mano en Excel rompe eso de varias
formas a la vez, y todas aparecen en los informes comerciales reales:

- **Varias tablas en la misma hoja**, separadas por filas o columnas vacías,
  cada una con su título ("ALTAS Y CUMPLIMIENTO @ MES A MES SIN PYME").
- **Los meses como columnas** (ene-26, feb-26…) y las medidas como filas
  (Ejecución, Presupuesto, Cumplimiento).
- **Bloques lado a lado**: R2, R3, R4 y R5, cada uno con Ejc / Ppto / Cum
  debajo, y los meses bajando por la primera columna.
- **Años en una fila y meses abreviados debajo** ("2025" sobre Oct, Nov, Dic).
- **Tablas resumen** (Prom Cum, Orden Cump) y filas o columnas de Total.
- **Gráficos e imágenes** pegados.

Leída como una sola tabla, la hoja salía con columnas "2026-01-01 00:00:00",
"Columna 13" y filas "R2 · Ppto" mezcladas con los datos: nada se podía
analizar. Aquí cada tabla se reconoce por su eje de meses, se le asigna el
título bajo el que está, y todo se convierte en una tabla ordenada —grupo,
mes y una columna por medida— que el resto del panel ya sabe analizar.

Nada de esto depende de los nombres de un archivo concreto: se buscan
formas (una fila de meses, una columna de meses, un encabezado que se
repite por bloque), no palabras.
"""
from __future__ import annotations

import datetime as _dt
import io
import posixpath
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional

import numpy as np
import pandas as pd

from .dates import MONTHS
from .numeric import _parse_number

MIN_PERIODOS = 3
_TOTALES = {"total", "total general", "gran total", "subtotal", "totales", "grand total"}
_EJES = {"mes", "meses", "month", "periodo", "fecha", "ano", "year", "corte", ""}
_PORCENTAJE_RE = re.compile(r"cum|%|porc|tasa|part|ratio|pct|avance", re.I)
_MES_RE = re.compile(r"(?:\d{1,2}\s*[.\-/]?\s*)?([a-z]{3,10})\.?(?:(?:\s*de\s+|\s*[\-/.\s]\s*)'?(\d{2}|\d{4}))?")


def _txt(v) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return re.sub(r"\s+", " ", str(v)).strip()


def _norm(texto) -> str:
    t = unicodedata.normalize("NFKD", _txt(texto))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return t.lower().strip()


def _numero(v) -> float:
    if isinstance(v, (pd.Timestamp, _dt.date, _dt.datetime)):
        return np.nan
    try:
        return float(_parse_number(v))
    except Exception:
        return np.nan


def periodo_de(v) -> Optional[tuple]:
    """(año, mes) si la celda nombra un mes. El año es None si la celda no lo dice ("Oct")."""
    if isinstance(v, (pd.Timestamp, _dt.datetime, _dt.date)):
        ts = pd.Timestamp(v)
        return None if pd.isna(ts) else (ts.year, ts.month)
    if isinstance(v, (int, float, np.integer, np.floating)):
        return None
    t = _norm(v)
    if not t or len(t) > 25:
        return None
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})(?:[-/]\d{1,2})?(?: 00:00:00)?", t)
    if m and 1 <= int(m.group(2)) <= 12:
        return int(m.group(1)), int(m.group(2))
    m = re.fullmatch(r"(\d{1,2})[-/](\d{4})", t)
    if m and 1 <= int(m.group(1)) <= 12:
        return int(m.group(2)), int(m.group(1))
    m = _MES_RE.fullmatch(t)
    if m and m.group(1) in MONTHS:
        anio = m.group(2)
        if anio is not None:
            anio = int(anio) + (2000 if len(anio) == 2 else 0)
        return anio, MONTHS[m.group(1)]
    return None


def _anio_de(v) -> Optional[int]:
    n = _numero(v)
    if np.isfinite(n) and float(n).is_integer() and 1990 <= n <= 2100:
        return int(n)
    m = re.fullmatch(r"(?:año|ano|year)?\s*(\d{4})", _norm(v))
    return int(m.group(1)) if m and 1990 <= int(m.group(1)) <= 2100 else None


def _es_total(texto) -> bool:
    return _norm(texto) in _TOTALES


# ── Títulos ─────────────────────────────────────────────────────────────────

def titulos(G: np.ndarray) -> list[tuple[int, str]]:
    """Filas que solo traen un texto: el título de lo que viene debajo.

    Tras rellenar las celdas combinadas un título se repite en toda la fila,
    así que se cuenta el texto distinto, no las celdas. Se exigen al menos dos
    palabras: "R1" o "Mes" solos rotulan una tabla, no la titulan.
    """
    salida = []
    for r in range(G.shape[0]):
        textos = {_txt(v) for v in G[r] if _txt(v)}
        if len(textos) != 1:
            continue
        t = next(iter(textos))
        if periodo_de(t) is not None or np.isfinite(_numero(t)):
            continue
        if len(t) < 8 or len(t.split()) < 2:
            if not _titulo_corto(G, r, t):
                continue
        salida.append((r, t))
    return salida


def _titulo_corto(G, r, t) -> bool:
    """¿Una sola palabra en mayúsculas ("FWA") que titula la tabla de abajo?

    Sin esto, una sección con nombre de una palabra no tenía título, y la
    tabla quedaba bajo el título anterior —en el informe real, el de un
    ranking que era una imagen—: salía como "RANKING SUPERVISORES" una tabla
    que no tenía nada que ver. Se exige mayúsculas y una tabla justo debajo
    para no confundirla con "R1" o "Mes", que rotulan una tabla, no la titulan.
    """
    limpio = re.sub(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ]", "", t)
    if len(limpio) < 3 or not t.isupper() or _norm(t) in _EJES or _es_total(t):
        return False
    if re.fullmatch(r"[RZ]\s?\d{1,2}", t, re.I):
        return False
    for rr in range(r + 1, min(G.shape[0], r + 4)):
        celdas = [v for v in G[rr] if _txt(v)]
        if len(celdas) >= 3:
            # "BMS" sobre "Mes | ene | feb…" con Ejecución y Presupuesto debajo
            # no titula: nombra al agente de esa tabla, como "R1" en otras. Un
            # título de verdad ("FWA") va sobre un encabezado que dice qué son
            # las filas ("Zona"), no sobre el eje de meses.
            return _norm(celdas[0]) not in _EJES
    return False


def titulo_principal(raw: pd.DataFrame, filas: int = 6) -> Optional[str]:
    """El título de una hoja normal, si lo tiene encima de la tabla."""
    if raw is None or raw.empty:
        return None
    encontrados = titulos(raw.head(filas).to_numpy(dtype=object))
    return encontrados[0][1] if encontrados else None


def _seccion(fila: int, lista_titulos: list) -> Optional[str]:
    previos = [t for r, t in lista_titulos if r < fila]
    return previos[-1] if previos else None


# ── Tablas con los meses en una fila ────────────────────────────────────────

def _es_etiqueta(v) -> bool:
    """Un rótulo de fila: texto con letras. "R1" lo es aunque `_numero` le saque un 1."""
    t = _txt(v)
    return bool(t) and bool(re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", t)) and periodo_de(v) is None


def _columna_de_etiquetas(G, fila, primera_col):
    mejor, puntos = None, 0
    for c in range(primera_col):
        # Antes se contaba "texto que no es número", y `_numero("R1")` da 1:
        # una tabla con R1…R5 como filas (FWA en el informe real) no tenía
        # columna de etiquetas y se perdía, salvo el primer mes.
        textos = sum(1 for r in range(fila + 1, min(G.shape[0], fila + 60)) if _es_etiqueta(G[r, c]))
        if textos > puntos or (textos == puntos and textos and c > (mejor or -1)):
            mejor, puntos = c, textos
    return mejor if puntos else None


def _tablas_horizontales(G, filas_titulo, usadas):
    tablas = []
    n, m = G.shape
    for r in range(n):
        pcols = [c for c in range(m) if periodo_de(G[r, c]) is not None]
        if len(pcols) < MIN_PERIODOS or any((r, c) in usadas for c in pcols):
            continue
        lc = _columna_de_etiquetas(G, r, pcols[0])
        if lc is None:
            continue
        periodos = [periodo_de(G[r, c]) for c in pcols]
        # El año puede venir en la fila de arriba ("2025" sobre Oct, Nov, Dic).
        anios_arriba = [_anio_de(G[r - 1, c]) if r > 0 else None for c in pcols]
        periodos = _completar_anios(periodos, anios_arriba)

        filas, blancos, total_excluido, con_porcentaje = [], 0, 0, False
        for rr in range(r + 1, n):
            if rr in filas_titulo or sum(periodo_de(G[rr, c]) is not None for c in range(m)) >= MIN_PERIODOS:
                break
            etiqueta = _txt(G[rr, lc])
            valores = [_numero(G[rr, c]) for c in pcols]
            con_dato = sum(np.isfinite(v) for v in valores)
            if not etiqueta and con_dato == 0:
                if any(_txt(G[rr, c]) for c in range(lc, max(pcols) + 1)):
                    break  # empieza otra cosa debajo (el encabezado de otro bloque)
                blancos += 1
                if blancos >= 2:
                    break
                continue
            if not etiqueta or con_dato == 0:
                break
            blancos = 0
            if _es_total(etiqueta):
                total_excluido += 1
                continue
            filas.append((rr, etiqueta, valores))
            con_porcentaje = con_porcentaje or any("%" in _txt(G[rr, c]) for c in pcols)
        if not filas:
            continue

        eje = _txt(G[r, lc])
        entidad = None
        for k in (1, 2):
            if r - k < 0 or (r - k) in filas_titulo:
                break
            fila_arriba = [(c, _txt(G[r - k, c])) for c in range(m) if _txt(G[r - k, c])]
            if any(_anio_de(G[r - k, c]) for c in pcols):
                continue  # es la fila de los años, no un rótulo
            cortos = [t for c, t in fila_arriba if c <= lc and len(t) <= 25]
            if cortos and len(fila_arriba) == len(cortos):
                entidad = cortos[-1]
                break
        # Filas = medidas (Ejecución, Presupuesto) o filas = entidades (un jefe por fila).
        filas_son_entidades = _norm(eje) not in _EJES or len(filas) > 12
        if filas_son_entidades and _norm(eje) in _EJES:
            eje = "Grupo"
        for rr, *_ in filas:
            for c in range(lc, max(pcols) + 1):
                usadas.add((rr, c))
        for c in range(lc, max(pcols) + 1):
            usadas.add((r, c))
        tablas.append({
            "fila": r, "periodos": periodos, "filas": [(e, v) for _, e, v in filas],
            "entidad": entidad, "eje": eje, "filas_son_entidades": filas_son_entidades,
            "totales_excluidos": total_excluido, "porcentaje": con_porcentaje,
            "fin": filas[-1][0],
        })
    return tablas


def _completar_anios(periodos, anios_arriba):
    """Rellena los años que faltan: de la fila de arriba, hacia adelante, y con cambio de año."""
    anios = [p[0] for p in periodos]
    meses = [p[1] for p in periodos]
    actual = None
    for i in range(len(anios)):
        if anios_arriba[i] is not None:
            actual = anios_arriba[i]
        if anios[i] is None and actual is not None:
            anios[i] = actual
    if any(a is None for a in anios) and any(a is not None for a in anios):
        # Hacia atrás desde el primero conocido, y hacia adelante con cambio de año.
        primero = next(i for i, a in enumerate(anios) if a is not None)
        for i in range(primero - 1, -1, -1):
            anios[i] = anios[i + 1] - (1 if meses[i] > meses[i + 1] else 0)
        for i in range(primero + 1, len(anios)):
            if anios[i] is None:
                anios[i] = anios[i - 1] + (1 if meses[i] < meses[i - 1] else 0)
    return list(zip(anios, meses))


# ── Tablas con los meses bajando por una columna ────────────────────────────

def _tablas_verticales(G, usadas):
    tablas = []
    n, m = G.shape
    for c in range(m):
        r = 0
        while r < n:
            if (r, c) in usadas or periodo_de(G[r, c]) is None:
                r += 1
                continue
            r0 = r
            while r < n and (r, c) not in usadas and periodo_de(G[r, c]) is not None:
                r += 1
            r1 = r - 1
            h = r0 - 1
            if r1 - r0 + 1 < MIN_PERIODOS or h < 0:
                continue
            medidas, vacias = [], 0
            for c2 in range(c + 1, m):
                nombre = _txt(G[h, c2])
                valores = [_numero(G[x, c2]) for x in range(r0, r1 + 1)]
                con_dato = sum(np.isfinite(v) for v in valores)
                if not nombre and con_dato == 0:
                    vacias += 1
                    if vacias >= 2:
                        break
                    continue
                vacias = 0
                if nombre and periodo_de(nombre) is None and con_dato >= 0.5 * len(valores):
                    if not _es_total(nombre):
                        medidas.append((c2, nombre, valores))
                    continue
                break
            if not medidas:
                continue
            # Bloques: el nombre de la medida se repite al empezar el siguiente (Ejc, Ppto, Cum, Ejc…).
            bloques, actual, vistos = [], [], set()
            for item in medidas:
                clave = _norm(item[1])
                if clave in vistos:
                    bloques.append(actual)
                    actual, vistos = [], set()
                actual.append(item)
                vistos.add(clave)
            bloques.append(actual)
            grupos = []
            for i, bloque in enumerate(bloques):
                desde = bloque[0][0]
                hasta = bloques[i + 1][0][0] - 1 if i + 1 < len(bloques) else bloque[-1][0] + 1
                etiqueta = None
                if h - 1 >= 0:
                    textos = [_txt(G[h - 1, cc]) for cc in range(desde, min(hasta, m - 1) + 1) if _txt(G[h - 1, cc])]
                    textos = [t for t in dict.fromkeys(textos) if periodo_de(t) is None]
                    etiqueta = textos[0] if textos else None
                grupos.append((etiqueta, [(nombre, valores) for _, nombre, valores in bloque]))
            ultima = medidas[-1][0]
            for x in range(max(h - 1, 0), r1 + 1):
                for cc in range(c, ultima + 1):
                    usadas.add((x, cc))
            eje = _txt(G[h, c])
            tablas.append({
                "fila": h, "fin": r1, "periodos": [periodo_de(G[x, c]) for x in range(r0, r1 + 1)],
                "grupos": grupos, "eje": eje,
                "con_bloques": len(grupos) > 1 or any(g[0] for g in grupos),
            })
    return tablas


# ── Tablas resumen (una fila por grupo) ─────────────────────────────────────

def _tablas_resumen(G, usadas, grupos_conocidos):
    conocidos = {_norm(g) for g in grupos_conocidos if g}
    if not conocidos:
        return []
    tablas = []
    n, m = G.shape
    for c in range(m):
        r = 0
        while r < n:
            if (r, c) in usadas or _norm(G[r, c]) not in conocidos:
                r += 1
                continue
            r0 = r
            while r < n and _norm(G[r, c]) in conocidos:
                r += 1
            r1 = r - 1
            if r1 - r0 + 1 < 2:
                continue
            for c2 in range(c + 1, min(m, c + 4)):
                valores = [_numero(G[x, c2]) for x in range(r0, r1 + 1)]
                if all(np.isfinite(v) for v in valores):
                    nombre = (_txt(G[r0 - 1, c2]) if r0 > 0 else "") or (_txt(G[r0 - 1, c]) if r0 > 0 else "") or "Valor"
                    tablas.append({"fila": r0 - 1, "columna": nombre,
                                   "valores": {_txt(G[x, c]): v for x, v in zip(range(r0, r1 + 1), valores)}})
                    for x in range(r0 - 1, r1 + 1):
                        usadas.update({(x, c), (x, c2)})
                    break
    return tablas


# ── Tablas con los meses agrupando varias medidas ───────────────────────────

def _es_texto(v) -> bool:
    return bool(_txt(v)) and periodo_de(v) is None and not np.isfinite(_numero(v))


def _filas_de_datos(G, desde, lc, columnas, filas_titulo):
    """Filas con etiqueta y números debajo de un encabezado. Devuelve (filas, totales excluidos)."""
    filas, totales, blancos = [], 0, 0
    n = G.shape[0]
    for rr in range(desde, n):
        if rr in filas_titulo or sum(periodo_de(v) is not None for v in G[rr]) >= 2:
            break
        etiqueta = _txt(G[rr, lc])
        valores = [_numero(G[rr, c]) for c in columnas]
        con_dato = sum(np.isfinite(v) for v in valores)
        if not etiqueta and con_dato == 0:
            blancos += 1
            if blancos >= 1:
                break
            continue
        if not etiqueta or con_dato == 0:
            break
        blancos = 0
        if _es_total(etiqueta):
            totales += 1
            continue
        filas.append((rr, etiqueta, valores))
    return filas, totales


def _tablas_meses_agrupados(G, filas_titulo, usadas):
    """Meses que agrupan varias medidas. Dos formas reales:

    1. Los meses en una fila, combinados sobre sus medidas en la de abajo:
           Región | abr-26              | may-26              | …
                  | Altas | Meta | Cum  | Altas | Meta | Cum  | …
    2. Los meses intercalados en la misma fila con otra medida que se repite:
           Productos | abr-26 | % Participación | may-26 | % Participación | …

    Antes la primera forma se leía como "una tabla resumen" con solo las altas
    del primer mes, y la segunda perdía la participación. La columna del mes
    en la forma 2 no tiene nombre propio: se guarda sin nombre y se le pone
    después, con el título de la sección (ver `_nombrar_medida`).
    """
    tablas = []
    n, m = G.shape
    for r in range(n - 1):
        pcols = [c for c in range(m) if periodo_de(G[r, c]) is not None and (r, c) not in usadas]
        periodos_fila = [periodo_de(G[r, c]) for c in pcols]
        if len(pcols) < 2 or len(set(periodos_fila)) < 2 or r in filas_titulo:
            continue
        c0 = pcols[0]
        ultimo = max(c for c in range(m) if _txt(G[r, c]) or _txt(G[r + 1, c]))

        # Forma 1: medidas debajo de cada mes.
        debajo = {c: _txt(G[r + 1, c]) for c in range(c0, ultimo + 1) if _es_texto(G[r + 1, c])}
        nombres = [_norm(v) for v in debajo.values()]
        repetidas = {x for x in nombres if nombres.count(x) >= 2}
        if len(debajo) >= 2 * len(set(periodos_fila)) and len(set(nombres)) >= 2 and repetidas:
            columnas, periodo_actual, asignacion = [], None, {}
            for c in range(c0, ultimo + 1):
                if periodo_de(G[r, c]) is not None:
                    periodo_actual = periodo_de(G[r, c])
                if c in debajo and periodo_actual is not None:
                    columnas.append(c)
                    asignacion[c] = (periodo_actual, debajo[c])
            lc = _columna_de_etiquetas(G, r + 1, c0)
            if lc is not None and columnas:
                filas, totales = _filas_de_datos(G, r + 2, lc, columnas, filas_titulo)
                if filas:
                    eje = _txt(G[r, lc]) or _txt(G[r + 1, lc])
                    registros = [(etiqueta, asignacion[c][0], asignacion[c][1], v)
                                 for _, etiqueta, valores in filas for c, v in zip(columnas, valores)]
                    _marcar(usadas, r, filas[-1][0], lc, ultimo)
                    tablas.append({"fila": r, "fin": filas[-1][0], "eje": eje, "registros": registros,
                                   "etiquetas": [e for _, e, _ in filas], "totales": totales})
                    continue

        # Forma 2: el mes y, a su derecha, otra medida con el mismo nombre en cada mes.
        textos = {c: _txt(G[r, c]) for c in range(c0, ultimo + 1) if c not in pcols and _es_texto(G[r, c])}
        nombres = [_norm(v) for v in textos.values()]
        if textos and all(nombres.count(x) >= 2 for x in nombres):
            columnas, asignacion, periodo_actual = [], {}, None
            for c in range(c0, ultimo + 1):
                if c in pcols:
                    periodo_actual = periodo_de(G[r, c])
                    columnas.append(c)
                    asignacion[c] = (periodo_actual, None)  # la medida principal, sin nombre todavía
                elif c in textos and periodo_actual is not None:
                    columnas.append(c)
                    asignacion[c] = (periodo_actual, textos[c])
            lc = _columna_de_etiquetas(G, r, c0)
            if lc is None:
                continue
            filas, totales = _filas_de_datos(G, r + 1, lc, columnas, filas_titulo)
            if not filas:
                continue
            registros = [(etiqueta, asignacion[c][0], asignacion[c][1], v)
                         for _, etiqueta, valores in filas for c, v in zip(columnas, valores)]
            _marcar(usadas, r, filas[-1][0] + totales, lc, ultimo)
            tablas.append({"fila": r, "fin": filas[-1][0], "eje": _txt(G[r, lc]), "registros": registros,
                           "etiquetas": [e for _, e, _ in filas], "totales": totales})
    return tablas


def _marcar(usadas, r0, r1, c0, c1):
    for x in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            usadas.add((x, c))


# ── Tablas planas dentro de un informe ──────────────────────────────────────

def _tablas_planas(G, usadas, filas_titulo):
    """Una tabla normal (encabezado + registros) metida entre las demás.

    En el informe real, "DISTRIBUCIÓN DE LA ZONIFICACIÓN" es un listado de 65
    agentes con su jefe, zona y supervisor. No tiene meses, así que ninguno de
    los detectores de arriba lo veía, y al leer la hoja como informe
    desaparecía entero. Se exige un encabezado de al menos 3 textos seguidos
    y al menos 3 filas debajo que lo llenen, con alguna columna numérica: una
    lista de notas o un bloque de títulos no cumple eso.
    """
    tablas = []
    n, m = G.shape
    r = 0
    while r < n:
        if r in filas_titulo:
            r += 1
            continue
        cols = [c for c in range(m) if (r, c) not in usadas and _es_texto(G[r, c])]
        if len(cols) < 3 or len(cols) < 0.8 * (max(cols) - min(cols) + 1):
            r += 1
            continue
        filas = []
        for rr in range(r + 1, n):
            if rr in filas_titulo or any((rr, c) in usadas for c in cols):
                break
            if sum(1 for c in cols if _txt(G[rr, c])) < max(2, 0.5 * len(cols)):
                break
            filas.append(rr)
        numericas = [c for c in cols
                     if filas and sum(np.isfinite(_numero(G[x, c])) for x in filas) >= 0.6 * len(filas)]
        if len(filas) < 3 or not numericas:
            r += 1
            continue
        encabezados, vistos = [], {}
        for c in cols:
            base = _txt(G[r, c])
            vistos[base] = vistos.get(base, 0) + 1
            encabezados.append(base if vistos[base] == 1 else f"{base}_{vistos[base]}")
        datos = pd.DataFrame([[G[x, c] for c in cols] for x in filas], columns=encabezados)
        datos = datos[~datos.iloc[:, 0].map(_es_total)].reset_index(drop=True)
        _marcar(usadas, r, filas[-1], min(cols), max(cols))
        tablas.append({"fila": r, "datos": datos})
        r = filas[-1] + 1
    return tablas


# ── Nombres ─────────────────────────────────────────────────────────────────

def _parece_proporcion(valores) -> bool:
    """¿Son proporciones (0,92 = 92%)? Se mira el 90% de los valores, no el máximo:
    un agente con 1.280% de cumplimiento no convierte al resto en cifras absolutas."""
    v = pd.to_numeric(pd.Series(list(valores)), errors="coerce").dropna()
    v = v[v != 0]
    return len(v) > 0 and float(v.quantile(0.9)) <= 3 and float(v.min()) >= -1


def _nombrar_medida(titulo, valores, porcentaje=False) -> str:
    """El nombre de una medida sin rótulo propio, sacado del título de su sección.

    "EVOLUCIÓN CUMPLIMIENTO @ AGENTES" trae valores 0,85 → "Cumplimiento";
    "EVOLUCIÓN DE VENTA @ AGENTES" → "Ventas @". Antes todas se llamaban
    "Valor", y con cuatro tablas así no se sabía cuál era cuál.
    """
    t = _norm(titulo or "")
    if re.search(r"cumplim|\bcum\b", t) and (porcentaje or _parece_proporcion(valores)):
        return "Cumplimiento"
    if re.search(r"participa", t):
        return "Participación"
    if re.search(r"\bventa", t):
        return "Ventas @" if "@" in t else "Ventas"
    if re.search(r"\baltas?\b", t) or "@" in t:
        return "Altas @" if "@" in t else "Altas"
    palabras = _txt(titulo).split()
    if titulo and len(palabras) == 1:
        return _txt(titulo)  # "FWA": el título ya es el nombre de lo que se mide
    return "Valor (%)" if porcentaje else "Valor"


_UNIDADES_TITULO = [("agente", "Agente"), ("jefe", "Jefe"), ("supervisor", "Supervisor"), ("asesor", "Asesor"),
                    ("vendedor", "Vendedor"), ("distrito", "Distrito"), ("zona", "Zona"), ("region", "Región"),
                    ("producto", "Producto"), ("canal", "Canal"), ("punto", "Punto")]


def _dimension_por_titulo(titulo) -> Optional[str]:
    """"CASOS DE ÉXITO AGENTES CALLE COSTA" → "Agente", cuando las filas no traen encabezado."""
    t = _norm(titulo or "")
    return next((nombre for clave, nombre in _UNIDADES_TITULO if re.search(rf"\b{clave}", t)), None)


def _dimension(eje, etiquetas) -> str:
    """Cómo se llama lo que agrupan las filas: el encabezado si dice algo; si no, por sus valores."""
    if eje and _norm(eje) not in _EJES and _norm(eje) != "grupo":
        return _txt(eje)
    return _nombre_de_grupo(etiquetas)


# ── Armado ──────────────────────────────────────────────────────────────────

def _subsecuencia(corta: str, larga: str) -> bool:
    it = iter(larga)
    return bool(corta) and corta[0] == larga[:1] and all(ch in it for ch in corta)


# Abreviaturas de los informes comerciales, para cuando la forma larga no
# aparece en la misma tabla (en "CUMPLIMIENTO OTTS" solo dice "Cum").
_ABREVIATURAS = {"cum": "Cumplimiento", "cump": "Cumplimiento", "ejc": "Ejecución", "ejec": "Ejecución",
                 "ppto": "Presupuesto", "presup": "Presupuesto"}


def _unificar_medidas(nombres) -> dict:
    """"Ejc" → "Ejecución", "Ppto" → "Presupuesto", "Cum" → "Cumplimiento"."""
    unicos = list(dict.fromkeys(nombres))
    mapa = {}
    for corta in unicos:
        nc = re.sub(r"[^a-z]", "", _norm(corta))
        candidatos = [l for l in unicos if l != corta and len(_norm(l)) > len(nc)
                      and _subsecuencia(nc, re.sub(r"[^a-z]", "", _norm(l)))]
        if len(nc) <= 5 and candidatos:
            mapa[corta] = max(candidatos, key=len)
        else:
            mapa[corta] = _ABREVIATURAS.get(nc, corta)
    return mapa


def _nombre_de_grupo(etiquetas) -> str:
    etiquetas = [e for e in etiquetas if e]
    if etiquetas and all(re.fullmatch(r"R\s?\d{1,2}", e, re.I) for e in etiquetas):
        return "Región"
    if etiquetas and all(re.fullmatch(r"Z\s?\d{1,2}", e, re.I) for e in etiquetas):
        return "Zona"
    return "Grupo"


def _fecha(periodo, anio_por_defecto):
    anio, mes = periodo
    anio = anio if anio is not None else anio_por_defecto
    return pd.Timestamp(anio, mes, 1) if anio is not None else None


def leer_informe(raw: pd.DataFrame, hoja: str, anio_por_defecto: Optional[int] = None) -> list[dict]:
    """Las tablas de una hoja tipo informe, ya ordenadas. Lista vacía si la hoja no lo es.

    Cada elemento: {"nombre", "titulo", "datos": DataFrame, "log": [...]}.
    Una hoja normal —una tabla con su fecha en una columna— devuelve lista
    vacía y sigue su camino de siempre: solo se toma como informe si hay
    meses en una fila, bloques por grupo o más de una tabla.
    """
    if raw is None or raw.empty:
        return []
    G = raw.to_numpy(dtype=object)
    lista_titulos = titulos(G)
    filas_titulo = {r for r, _ in lista_titulos}
    usadas: set = set()
    # Los meses agrupados van primero: si no, el detector horizontal toma su
    # fila de meses y deja fuera las medidas de debajo.
    agrupados = _tablas_meses_agrupados(G, filas_titulo, usadas)
    horizontales = _tablas_horizontales(G, filas_titulo, usadas)
    verticales = _tablas_verticales(G, usadas)
    if (not agrupados and not horizontales and not any(t["con_bloques"] for t in verticales)
            and len(verticales) < 2):
        return []

    etiquetas = [t["entidad"] for t in horizontales] + [g for t in verticales for g, _ in t["grupos"]]
    resumenes = _tablas_resumen(G, usadas, etiquetas)
    planas = _tablas_planas(G, usadas, filas_titulo)

    # Una sección por (título, qué agrupan las filas). Bajo un mismo título
    # puede haber una tabla por región y otra por producto: juntarlas mezclaba
    # "R1" y "Netflix" en la misma columna.
    secciones: dict = {}

    def seccion_para(fila, dimension):
        titulo = _seccion(fila, lista_titulos)
        if dimension == "Grupo":
            dimension = _dimension_por_titulo(titulo) or dimension
        return secciones.setdefault((titulo, dimension), {
            "titulo": titulo, "registros": [], "dimension": dimension, "eje": None,
            "tablas": 0, "resumen": {}, "totales": 0})

    for t in agrupados:
        s = seccion_para(t["fila"], _dimension(t["eje"], t["etiquetas"]))
        s["tablas"] += 1
        s["totales"] += t["totales"]
        for etiqueta, periodo, medida, valor in t["registros"]:
            if np.isfinite(valor):
                s["registros"].append((etiqueta, periodo, medida, valor))
    for t in horizontales:
        etiquetas_t = [e for e, _ in t["filas"]] if t["filas_son_entidades"] else [t["entidad"]]
        eje_t = t["eje"] if t["filas_son_entidades"] else None
        s = seccion_para(t["fila"], _dimension(eje_t, etiquetas_t))
        s["tablas"] += 1
        s["totales"] += t["totales_excluidos"]
        if _norm(t["eje"]) in _EJES and t["eje"]:
            s["eje"] = s["eje"] or t["eje"]
        if t["filas_son_entidades"]:
            todos = [v for _, valores in t["filas"] for v in valores]
            medida = t["entidad"] or _nombrar_medida(s["titulo"], todos, t["porcentaje"])
        for etiqueta, valores in t["filas"]:
            for periodo, valor in zip(t["periodos"], valores):
                if not np.isfinite(valor):
                    continue
                if t["filas_son_entidades"]:
                    s["registros"].append((etiqueta, periodo, medida, valor))
                else:
                    s["registros"].append((t["entidad"], periodo, etiqueta, valor))
    for t in verticales:
        s = seccion_para(t["fila"], _dimension(None, [g for g, _ in t["grupos"]]))
        s["tablas"] += 1
        if _norm(t["eje"]) in _EJES and t["eje"]:
            s["eje"] = s["eje"] or t["eje"]
        for grupo, medidas in t["grupos"]:
            for nombre, valores in medidas:
                for periodo, valor in zip(t["periodos"], valores):
                    if np.isfinite(valor):
                        s["registros"].append((grupo, periodo, nombre, valor))
    for t in resumenes:
        s = seccion_para(t["fila"], _dimension(None, list(t["valores"])))
        for grupo, valor in t["valores"].items():
            s["resumen"].setdefault(grupo, {})[t["columna"]] = valor

    _nombrar_medidas_sin_nombre(secciones)

    por_titulo: dict = {}
    for (titulo, _), s in secciones.items():
        if s["registros"]:
            por_titulo[titulo] = por_titulo.get(titulo, 0) + 1

    salida = []
    for (titulo, dimension), s in secciones.items():
        nombre_base = titulo or hoja
        # Solo se agrega "· por X" cuando el título tiene más de una tabla distinta.
        nombre = f"{nombre_base} · por {dimension}" if por_titulo.get(titulo, 0) > 1 else nombre_base
        if s["registros"]:
            df = _tabla_ordenada(s, anio_por_defecto)
            if df is not None and not df.empty:
                log = [f"Hoja «{hoja}» leída como informe: «{nombre}» sale de {s['tablas']} tabla(s) "
                       f"de la hoja, convertidas a una fila por {dimension.lower()} y mes."]
                if s["totales"]:
                    log.append(f"{s['totales']} fila(s) de Total excluida(s): son un agregado, no un registro.")
                salida.append({"nombre": nombre, "titulo": nombre_base, "datos": df, "log": log,
                               "faltantes_son_cero": False})
        if s["resumen"]:
            filas = [{"_grupo": g, **vals} for g, vals in s["resumen"].items()]
            resumen = pd.DataFrame(filas).rename(columns={"_grupo": dimension})
            for col in resumen.columns[1:]:
                if _PORCENTAJE_RE.search(str(col)) and _parece_proporcion(resumen[col]):
                    resumen[col] = (resumen[col] * 100).round(2)
            salida.append({"nombre": f"{nombre} · Resumen", "titulo": f"{nombre_base} · Resumen",
                           "datos": resumen, "faltantes_son_cero": False,
                           "log": [f"Tabla resumen de «{nombre_base}» ({', '.join(map(str, resumen.columns[1:]))}): "
                                   f"una fila por {dimension.lower()}."]})
    for t in planas:
        titulo = _seccion(t["fila"], lista_titulos) or hoja
        salida.append({"nombre": titulo, "titulo": titulo, "datos": t["datos"],
                       "log": [f"Hoja «{hoja}»: «{titulo}» es una tabla normal dentro del informe "
                               f"({len(t['datos'])} registros); se lee tal cual."]})
    return salida


def _nombrar_medidas_sin_nombre(secciones: dict) -> None:
    """Le pone nombre a la medida principal de las tablas que no la rotulan.

    En "Productos | abr-26 | % Participación | …" el número bajo el mes no
    tiene encabezado. Si otra tabla del mismo título mide una sola cosa con
    nombre ("Altas" junto a Meta y Cum), es esa; si no, se nombra por el título.
    """
    for (titulo, dimension), s in secciones.items():
        if not any(r[2] is None for r in s["registros"]):
            continue
        hermanas = set()
        for (t2, d2), s2 in secciones.items():
            if t2 == titulo and d2 != dimension:
                hermanas |= {r[2] for r in s2["registros"] if r[2]
                             and not _PORCENTAJE_RE.search(str(r[2]))
                             and not re.search(r"meta|ppto|presup|objetivo", _norm(r[2]))}
        valores = [r[3] for r in s["registros"] if r[2] is None]
        nombre = next(iter(hermanas)) if len(hermanas) == 1 else _nombrar_medida(titulo, valores)
        s["registros"] = [(g, p, nombre if m is None else m, v) for g, p, m, v in s["registros"]]


def _tabla_ordenada(s, anio_por_defecto) -> Optional[pd.DataFrame]:
    registros = pd.DataFrame(s["registros"], columns=["_grupo", "_periodo", "_medida", "_valor"])
    mapa = _unificar_medidas(registros["_medida"].tolist())
    registros["_medida"] = registros["_medida"].map(mapa)
    fechas = [_fecha(p, anio_por_defecto) for p in registros["_periodo"]]
    if all(f is not None for f in fechas):
        registros["_periodo"] = fechas
    else:
        # Sin año en ningún lado no se inventa uno: el mes queda como texto.
        from .dates import MONTH_ABBR_ES
        registros["_periodo"] = [MONTH_ABBR_ES[p[1]] for p in registros["_periodo"]]
    tabla = registros.pivot_table(index=["_grupo", "_periodo"], columns="_medida", values="_valor",
                                  aggfunc="first", dropna=False, sort=False)
    tabla = tabla.dropna(how="all").reset_index()
    tabla.columns.name = None
    etiquetas = tabla["_grupo"].dropna().astype(str).unique().tolist()
    dimension = s["dimension"] if s["dimension"] and s["dimension"] != "Grupo" else _nombre_de_grupo(etiquetas)
    if dimension == "Grupo":
        dimension = _dimension_por_titulo(s.get("titulo")) or dimension
    eje = s["eje"] if s["eje"] and _norm(s["eje"]) not in {"", "ano", "year"} else "Mes"
    tabla = tabla.rename(columns={"_grupo": dimension, "_periodo": eje})
    if tabla[dimension].isna().all():
        tabla = tabla.drop(columns=[dimension])
    else:
        tabla = tabla[~tabla[dimension].astype(str).map(_es_total)]
    medidas = [c for c in tabla.columns if c not in {dimension, eje}]
    orden = list(dict.fromkeys(mapa[m] for m in registros["_medida"].unique() if m in mapa)) or medidas
    medidas = [m for m in orden if m in tabla.columns] + [m for m in medidas if m not in orden]
    for col in medidas:
        serie = pd.to_numeric(tabla[col], errors="coerce")
        if _PORCENTAJE_RE.search(str(col)) and _parece_proporcion(serie):
            tabla[col] = (serie * 100).round(2)
    columnas = ([dimension] if dimension in tabla.columns else []) + [eje] + medidas
    orden_filas = [c for c in [dimension, eje] if c in tabla.columns]
    return tabla[columnas].sort_values(orden_filas, kind="stable").reset_index(drop=True)


# ── Gráficos e imágenes del .xlsx ───────────────────────────────────────────

_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def _relaciones(z, parte):
    ruta = posixpath.join(posixpath.dirname(parte), "_rels", posixpath.basename(parte) + ".rels")
    if ruta not in z.namelist():
        return []
    salida = []
    for rel in ET.fromstring(z.read(ruta)).findall(f"{{{_PKG}}}Relationship"):
        destino = rel.get("Target", "")
        destino = destino[1:] if destino.startswith("/") else posixpath.normpath(
            posixpath.join(posixpath.dirname(parte), destino))
        salida.append((rel.get("Id"), rel.get("Type", ""), destino))
    return salida


def _cache(el):
    """(valores por posición, código de formato, fórmula) de una referencia de gráfico."""
    if el is None:
        return [], "", None
    puntos, total, formato = {}, 0, ""
    for cache in list(el.iter(f"{{{_C}}}numCache")) + list(el.iter(f"{{{_C}}}strCache")) + list(el.iter(f"{{{_C}}}strLit")) + list(el.iter(f"{{{_C}}}numLit")):
        fc = cache.find(f"{{{_C}}}formatCode")
        formato = fc.text if fc is not None and fc.text else formato
        cuenta = cache.find(f"{{{_C}}}ptCount")
        total = max(total, int(cuenta.get("val", 0)) if cuenta is not None else 0)
        for pt in cache.findall(f"{{{_C}}}pt"):
            v = pt.find(f"{{{_C}}}v")
            puntos[int(pt.get("idx", 0))] = v.text if v is not None else None
    formula = el.find(f".//{{{_C}}}f")
    total = max(total, (max(puntos) + 1) if puntos else 0)
    return [puntos.get(i) for i in range(total)], formato, (formula.text if formula is not None else None)


def _rango(formula, hojas_grid):
    """Valores de una fórmula como 'Datos'!$B$2:$B$25, leídos de la hoja."""
    m = re.fullmatch(r"'?(.+?)'?!\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?", (formula or "").strip())
    if not m or hojas_grid is None:
        return []
    grid = hojas_grid(m.group(1).replace("''", "'"))
    if grid is None:
        return []

    def col(letras):
        n = 0
        for ch in letras:
            n = n * 26 + ord(ch) - 64
        return n - 1

    c1, r1 = col(m.group(2)), int(m.group(3)) - 1
    c2, r2 = (col(m.group(4)), int(m.group(5)) - 1) if m.group(4) else (c1, r1)
    valores = []
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            valores.append(grid.iat[r, c] if r < grid.shape[0] and c < grid.shape[1] else None)
    return valores


def _categoria(v, formato):
    n = _numero(v)
    if np.isfinite(n) and formato and re.search(r"[dmy]", formato.lower()) and "general" not in formato.lower():
        return pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(n))
    p = periodo_de(v)
    if p and p[0] is not None:
        return pd.Timestamp(p[0], p[1], 1)
    return v if not isinstance(v, str) else _txt(v)


def leer_grafico(xml: bytes, hojas_grid=None) -> Optional[dict]:
    """Los datos de un gráfico nativo de Excel: su título y una columna por serie."""
    raiz = ET.fromstring(xml)
    titulo = " ".join(t.text for t in raiz.findall(f".//{{{_C}}}chart/{{{_C}}}title//{{{_A}}}t") if t.text).strip()
    categorias, formato_cat, series = None, "", []
    for i, ser in enumerate(raiz.iter(f"{{{_C}}}ser")):
        nombres, _, f_nombre = _cache(ser.find(f"{{{_C}}}tx"))
        nombre = next((n for n in nombres if n), None)
        if not nombre and f_nombre:
            nombre = next((_txt(v) for v in _rango(f_nombre, hojas_grid) if _txt(v)), None)
        cats, fmt, f_cat = _cache(ser.find(f"{{{_C}}}cat") if ser.find(f"{{{_C}}}cat") is not None else ser.find(f"{{{_C}}}xVal"))
        vals, _, f_val = _cache(ser.find(f"{{{_C}}}val") if ser.find(f"{{{_C}}}val") is not None else ser.find(f"{{{_C}}}yVal"))
        if not any(v is not None for v in vals) and f_val:
            vals = _rango(f_val, hojas_grid)
        if not any(v is not None for v in cats) and f_cat:
            cats = _rango(f_cat, hojas_grid)
        if categorias is None and cats:
            categorias, formato_cat = cats, fmt
        series.append((nombre or f"Serie {i + 1}", [_numero(v) for v in vals]))
    series = [(n, v) for n, v in series if any(np.isfinite(x) for x in v)]
    if not series:
        return None
    largo = max(len(v) for _, v in series)
    categorias = list(categorias or [])[:largo] + [None] * max(0, largo - len(categorias or []))
    valores_cat = [_categoria(v, formato_cat) for v in categorias]
    es_fecha = all(isinstance(v, pd.Timestamp) for v in valores_cat) and valores_cat
    datos = {("Mes" if es_fecha else "Categoría"): valores_cat if any(v is not None for v in valores_cat)
             else list(range(1, largo + 1))}
    for nombre, v in series:
        datos[nombre] = list(v) + [np.nan] * (largo - len(v))
    return {"titulo": titulo, "datos": pd.DataFrame(datos)}


def graficos_e_imagenes(data: bytes, hojas_grid=None) -> dict:
    """{hoja: {"graficos": [{"titulo", "datos"}], "imagenes": n}} de un .xlsx/.xlsm.

    Un gráfico nativo de Excel guarda una copia de sus números, así que se
    puede analizar aunque la tabla de origen no esté a la vista. Una imagen
    pegada (una captura de Power BI, por ejemplo) no trae números: se cuenta
    para poder avisarlo, en vez de ignorarla en silencio.
    """
    salida: dict = {}
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return salida
    if "xl/workbook.xml" not in z.namelist():
        return salida
    rels_libro = {rid: destino for rid, _, destino in _relaciones(z, "xl/workbook.xml")}
    libro = ET.fromstring(z.read("xl/workbook.xml"))
    for hoja in libro.iter(f"{{{_S}}}sheet"):
        nombre = hoja.get("name")
        parte = rels_libro.get(hoja.get(f"{{{_R}}}id"))
        if not parte or parte not in z.namelist():
            continue
        graficos, imagenes, filas_imagen = [], 0, []
        for _, tipo, dibujo in _relaciones(z, parte):
            if not tipo.endswith("/drawing") or dibujo not in z.namelist():
                continue
            filas_imagen += _filas_de_imagenes(z.read(dibujo))
            for _, tipo_d, destino in _relaciones(z, dibujo):
                if tipo_d.endswith("/image"):
                    imagenes += 1
                elif tipo_d.endswith("/chart") and destino in z.namelist():
                    try:
                        grafico = leer_grafico(z.read(destino), hojas_grid)
                    except Exception:
                        grafico = None
                    if grafico:
                        graficos.append(grafico)
        if graficos or imagenes:
            salida[nombre] = {"graficos": graficos, "imagenes": imagenes, "filas_imagen": sorted(filas_imagen)}
    return salida


_XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"


def _filas_de_imagenes(xml: bytes) -> list[int]:
    """Fila (desde 0) donde empieza cada imagen pegada, para decir en qué sección está."""
    try:
        raiz = ET.fromstring(xml)
    except ET.ParseError:
        return []
    filas = []
    for ancla in list(raiz.iter(f"{{{_XDR}}}twoCellAnchor")) + list(raiz.iter(f"{{{_XDR}}}oneCellAnchor")):
        fila = ancla.find(f"{{{_XDR}}}from/{{{_XDR}}}row")
        if ancla.find(f"{{{_XDR}}}pic") is not None and fila is not None and (fila.text or "").isdigit():
            filas.append(int(fila.text))
    return filas
