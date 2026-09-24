"""Tablas donde la meta y el resultado son FILAS, no columnas.

La base de un informe comercial exportado suele venir así: una columna dice de
qué tipo es cada fila —Presupuesto, Ejecución, Digitadas— y la cifra está en
la misma columna para todas:

    Producto | Tipología | Canal | Registro     | Activaciones | Pry
    CHIPS    | Prepago   | CAV   | Presupuesto  |            0 | 3.111
    CHIPS    | Prepago   | CAV   | Ejecución    |        2.155 | 3.079

Leída tal cual, «Activaciones» mezcla en una sola columna el presupuesto y lo
ejecutado, así que sumarla no significa nada, y el motor de comparación
—que busca la meta en una COLUMNA (`core/performance.columna_meta`)— no
encuentra ninguna: el panel dice «el archivo no trae una meta» aunque la
traiga en 2.710 filas.

Aquí esa tabla se gira: una fila por combinación real (producto, canal, jefe,
fecha…) y una columna por cada cruce medida × tipo de registro
(«Pry · Presupuesto», «Activaciones · Ejecución»). Es exactamente lo que hace
la tabla dinámica del propio archivo, y deja la meta donde el resto del panel
ya sabe buscarla.

Nada depende de nombres concretos: se busca una columna con pocos valores
distintos donde alguno nombre una meta y otro no, y que al girarla las filas
se junten de verdad. Si no se cumple, la tabla sigue su camino sin tocar.
"""
from __future__ import annotations

import pandas as pd

from .performance import META_RE

MIN_TIPOS = 2          # Presupuesto vs. Ejecución: menos de dos no es un cruce
MAX_TIPOS = 6          # con más, no es un tipo de registro sino una categoría
MAX_COLUMNAS = 60      # medidas × tipos: más que esto es ilegible, no se gira
MIN_AHORRO = 0.05      # las filas se tienen que juntar al menos un 5 %


def _medidas(df: pd.DataFrame, schema: dict) -> list:
    """Las columnas con la cifra. Las fechas y los identificadores NO lo son,
    aunque lleguen como número: una fecha se agrupa, no se suma, y sumarla
    junta en una sola fila todos los días del mes."""
    fuera = set(schema.get("dates", [])) | set(schema.get("ids", []))
    metricas = schema.get("semantic", {}).get("metrics") or schema.get("metrics", [])
    return [c for c in metricas
            if c in df.columns and c not in fuera and pd.api.types.is_numeric_dtype(df[c])
            and df[c].notna().any()]


def _candidatas(df: pd.DataFrame, medidas: set) -> list:
    """Columnas que parecen decir «de qué tipo es esta fila»."""
    salida = []
    for c in df.columns:
        if c in medidas or str(c).startswith("_"):
            continue
        valores = df[c].dropna().astype(str).str.strip()
        valores = valores[valores.ne("")]
        distintos = valores.unique().tolist()
        if not (MIN_TIPOS <= len(distintos) <= MAX_TIPOS):
            continue
        # Alguno tiene que nombrar una meta y alguno NO: si todos son metas
        # (o ninguno lo es) no hay nada contra qué comparar y no es este caso.
        metas = [v for v in distintos if META_RE.search(v)]
        if not metas or len(metas) == len(distintos):
            continue
        # Cada tipo tiene que repetirse: un «Presupuesto» suelto entre miles
        # de filas es un dato raro, no la estructura de la tabla.
        if int(valores.value_counts().min()) < 2:
            continue
        salida.append((c, distintos))
    return salida


def girar_por_registro(df: pd.DataFrame, schema: dict):
    """(tabla girada, log). Devuelve la tabla tal cual si no aplica.

    El giro suma las cifras de cada combinación, igual que la tabla dinámica
    del archivo: si dos filas comparten todo menos la cifra, se suman.
    """
    if df is None or df.empty or len(df.columns) < 3:
        return df, []
    medidas = _medidas(df, schema or {})
    if not medidas:
        return df, []
    candidatas = _candidatas(df, set(medidas))
    if not candidatas:
        return df, []

    for columna, tipos in candidatas:
        indice = [c for c in df.columns if c != columna and c not in medidas]
        if not indice or len(medidas) * len(tipos) > MAX_COLUMNAS:
            continue
        # Si al girar no se junta ninguna fila, la columna no estaba
        # partiendo la tabla en mitades comparables: es una categoría más
        # («Tipo de cliente»), y girarla solo llenaría todo de vacíos.
        combinaciones = int(df.groupby(indice, dropna=False, observed=True).ngroups)
        if combinaciones > len(df) * (1 - MIN_AHORRO):
            continue

        tipo = df[columna].astype(str).str.strip()
        girada = (df.assign(_tipo_=tipo)
                    .groupby(indice + ["_tipo_"], dropna=False, observed=True)[medidas]
                    .sum(min_count=1)
                    .unstack("_tipo_"))
        # Una sola medida: la columna se llama por el tipo a secas
        # («Presupuesto»), que es como lo nombra quien hizo el archivo.
        if len(medidas) == 1:
            girada.columns = [str(t) for _, t in girada.columns]
        else:
            girada.columns = [f"{m} · {t}" for m, t in girada.columns]
        # Un cruce sin ninguna cifra (las Activaciones de una fila de
        # Presupuesto, que siempre vienen en cero) es ruido: se quita.
        vacias = [c for c in girada.columns if girada[c].fillna(0).eq(0).all()]
        girada = girada.drop(columns=vacias)
        if girada.empty or not len(girada.columns):
            continue

        salida = girada.reset_index()
        log = [f"«{columna}» separaba en filas lo que se compara entre sí "
               f"({', '.join(map(str, tipos))}): la tabla se giró a una fila por combinación "
               f"y una columna por cada cruce, que es como la lee la tabla dinámica del archivo. "
               f"{len(df):,} filas → {len(salida):,}."]
        if vacias:
            log.append(f"{len(vacias)} columna(s) del cruce quedaron sin ninguna cifra y se omitieron "
                       f"({', '.join(map(str, vacias[:3]))}{'…' if len(vacias) > 3 else ''}).")
        return salida, log
    return df, []
