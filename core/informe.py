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
        if len(t) < 8 or len(t.split()) < 2 or periodo_de(t) is not None or np.isfinite(_numero(t)):
            continue
        salida.append((r, t))
    return salida


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

def _columna_de_etiquetas(G, fila, primera_col):
    mejor, puntos = None, 0
    for c in range(primera_col):
        textos = sum(1 for r in range(fila + 1, min(G.shape[0], fila + 60))
                     if _txt(G[r, c]) and not np.isfinite(_numero(G[r, c])))
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


# ── Armado ──────────────────────────────────────────────────────────────────

def _subsecuencia(corta: str, larga: str) -> bool:
    it = iter(larga)
    return bool(corta) and corta[0] == larga[:1] and all(ch in it for ch in corta)


def _unificar_medidas(nombres) -> dict:
    """"Ejc" → "Ejecución", "Ppto" → "Presupuesto", "Cum" → "Cumplimiento", si ambas aparecen."""
    unicos = list(dict.fromkeys(nombres))
    mapa = {}
    for corta in unicos:
        nc = re.sub(r"[^a-z]", "", _norm(corta))
        candidatos = [l for l in unicos if l != corta and len(_norm(l)) > len(nc)
                      and _subsecuencia(nc, re.sub(r"[^a-z]", "", _norm(l)))]
        mapa[corta] = max(candidatos, key=len) if len(nc) <= 5 and candidatos else corta
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
    horizontales = _tablas_horizontales(G, filas_titulo, usadas)
    verticales = _tablas_verticales(G, usadas)
    if not horizontales and not any(t["con_bloques"] for t in verticales) and len(verticales) < 2:
        return []

    etiquetas = [t["entidad"] for t in horizontales] + [g for t in verticales for g, _ in t["grupos"]]
    resumenes = _tablas_resumen(G, usadas, etiquetas)

    secciones: dict = {}

    def seccion_para(fila):
        titulo = _seccion(fila, lista_titulos)
        return secciones.setdefault(titulo, {"registros": [], "dimension": None, "eje": None,
                                             "tablas": 0, "resumen": {}, "totales": 0})

    for t in horizontales:
        s = seccion_para(t["fila"])
        s["tablas"] += 1
        s["totales"] += t["totales_excluidos"]
        if _norm(t["eje"]) in _EJES and t["eje"]:
            s["eje"] = s["eje"] or t["eje"]
        for etiqueta, valores in t["filas"]:
            for periodo, valor in zip(t["periodos"], valores):
                if not np.isfinite(valor):
                    continue
                if t["filas_son_entidades"]:
                    s["dimension"] = s["dimension"] or t["eje"]
                    # Sin rótulo propio, la medida se llama por lo que es: un valor, o un porcentaje.
                    medida = t["entidad"] or ("Valor (%)" if t["porcentaje"] else "Valor")
                    s["registros"].append((etiqueta, periodo, medida, valor))
                else:
                    s["registros"].append((t["entidad"], periodo, etiqueta, valor))
    for t in verticales:
        s = seccion_para(t["fila"])
        s["tablas"] += 1
        if _norm(t["eje"]) in _EJES and t["eje"]:
            s["eje"] = s["eje"] or t["eje"]
        for grupo, medidas in t["grupos"]:
            for nombre, valores in medidas:
                for periodo, valor in zip(t["periodos"], valores):
                    if np.isfinite(valor):
                        s["registros"].append((grupo, periodo, nombre, valor))
    for t in resumenes:
        s = seccion_para(t["fila"])
        for grupo, valor in t["valores"].items():
            s["resumen"].setdefault(grupo, {})[t["columna"]] = valor

    salida = []
    for titulo, s in secciones.items():
        nombre_base = titulo or hoja
        if s["registros"]:
            df = _tabla_ordenada(s, anio_por_defecto)
            if df is not None and not df.empty:
                log = [f"Hoja «{hoja}» leída como informe: «{nombre_base}» sale de {s['tablas']} tabla(s) "
                       f"de la hoja, convertidas a una fila por grupo y mes."]
                if s["totales"]:
                    log.append(f"{s['totales']} fila(s) de Total excluida(s): son un agregado, no un registro.")
                salida.append({"nombre": nombre_base, "titulo": nombre_base, "datos": df, "log": log})
        if s["resumen"]:
            filas = [{"_grupo": g, **vals} for g, vals in s["resumen"].items()]
            resumen = pd.DataFrame(filas)
            dimension = s["dimension"] or _nombre_de_grupo(list(s["resumen"]))
            resumen = resumen.rename(columns={"_grupo": dimension})
            for col in resumen.columns[1:]:
                if _PORCENTAJE_RE.search(str(col)) and resumen[col].abs().max() <= 3:
                    resumen[col] = (resumen[col] * 100).round(2)
            salida.append({"nombre": f"{nombre_base} · Resumen", "titulo": f"{nombre_base} · Resumen",
                           "datos": resumen,
                           "log": [f"Tabla resumen de «{nombre_base}» ({', '.join(map(str, resumen.columns[1:]))}): "
                                   f"una fila por {dimension.lower()}."]})
    return salida


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
    dimension = s["dimension"] or _nombre_de_grupo(etiquetas)
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
        if _PORCENTAJE_RE.search(str(col)) and serie.abs().max() <= 3:
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
        graficos, imagenes = [], 0
        for _, tipo, dibujo in _relaciones(z, parte):
            if not tipo.endswith("/drawing") or dibujo not in z.namelist():
                continue
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
            salida[nombre] = {"graficos": graficos, "imagenes": imagenes}
    return salida
