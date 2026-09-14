"""Quién va mejor y quién va peor, comparado contra algo.

El problema que resuelve este módulo, y que antes tenía: ordenar por el total
no compara desempeño, compara tamaño. Una región con 40 puntos de venta
siempre le va a ganar a una con 3, y llamar "más productiva" a la primera es
una conclusión falsa dicha con un número exacto. Alguien lee eso y premia al
grande y castiga al pequeño.

Así que la comparación necesita una base, y se busca en este orden:

1. **La meta**, si el archivo la trae. Es la única base que el negocio ya
   definió: vender 10 con meta de 4 es mejor que vender 100 con meta de 200.
2. **Por unidad**, si dentro de cada grupo hay unidades contables (puntos,
   asesores). Ventas por punto compara regiones de tamaños distintos.
3. **Por registro**, que al menos descuenta el volumen de operaciones.
4. **El total**, y entonces se dice explícitamente que eso mide tamaño y no
   desempeño, en vez de dejar que se lea como un ranking de mérito.
"""
import re

import pandas as pd
import numpy as np
from .numeric import numeric_series
from .diagnostics import PEOR_SI_SUBE, ESTADOS_MALOS, _sin_tildes

ADDITIVE = {"revenue", "profit", "cost", "quantity", "discount", "tax"}

# Nombres con los que viene la meta en un archivo real. Se exige además que
# la columna sea numérica: "Plan" es meta en un archivo de ventas y nombre de
# producto en un catálogo, y el número es lo que los distingue.
META_RE = re.compile(
    # "presup" y no "presupuesto": en los archivos reales viene como Presup2026,
    # Presupto o Ppto, y exigir la palabra completa dejaba fuera la mitad.
    r"meta|objetivo|presup|ppto|cuota|target|budget|goal|planead|proyectad|esperad|forecast",
    re.I,
)
GEO = {"region": 0, "country": 1, "city": 2, "zone": 3, "department": 4, "state": 5}
BUSINESS = {"product": 10, "category": 11, "brand": 12, "customer": 13, "employee": 14, "segment": 15}

def _semantic(schema):
    return {x.get("column"): x.get("semantic_type") for x in schema.get("semantic", {}).get("columns", [])}

def _parece_estado(serie):
    """¿Esta columna dice en qué situación quedó el registro (Vencido, Cerrado)?"""
    valores = serie.dropna().astype(str).str.strip()
    valores = valores[valores.ne("")]
    if valores.empty or valores.nunique() > 12:
        return False
    return any(_sin_tildes(v) in ESTADOS_MALOS for v in valores.unique())

def choose_dimension(df, schema):
    sem = _semantic(schema)
    # Se UNEN las tres listas, no se prefiere una. Con `or`, un archivo cuyo
    # motor semántico solo reconocía "Estado" dejaba "Equipo" fuera y el panel
    # terminaba comparando "los Vencidos contra los Cerrados", que no compara
    # a nadie. Y el cajón de "texto" recoge los nombres de punto de venta
    # cuando hay cientos: sin él, ese archivo se quedaba sin panel.
    dims = list(schema.get("semantic", {}).get("dimensions") or [])
    dims += [c for c in schema.get("categorical", []) if c not in dims]
    dims += [c for c in schema.get("text", []) if c not in dims]
    dates = set(schema.get("dates", [])); ids = set(schema.get("ids", []))
    candidates=[]
    for c in dims:
        if c not in df.columns or c in dates or c in ids:
            continue
        n=df[c].dropna().astype(str).nunique()
        if n < 2 or n > 2000:
            continue
        st=sem.get(c, "")
        priority=GEO.get(st, BUSINESS.get(st, 30))
        # Una columna de estado describe en qué situación quedó algo, no quién
        # responde por ello. Como dimensión diría "los Vencidos vs. los
        # Cerrados", que no compara a nadie, y además deja al estado sin poder
        # usarse como base de la comparación.
        if st == "status" or _parece_estado(df[c]):
            priority=40
        # A igual prioridad gana la de menos grupos: una región con 5 valores
        # se lee de un vistazo y un listado de 300 puntos no.
        candidates.append((priority, n, c))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[0][2]

def _fmt(v):
    if v is None or pd.isna(v):
        return "—"
    v = float(v)
    signo = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1_000_000_000:
        return f"{signo}{v/1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"{signo}{v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"{signo}{v/1_000:.1f}K"
    if v < 100 and v != int(v):
        return f"{signo}{v:,.1f}"
    return f"{signo}{v:,.0f}"


def _etiqueta(schema, col):
    for x in schema.get("semantic", {}).get("columns", []):
        if x.get("column") == col:
            return str(x.get("display_name") or col)
    return str(col)


_CONECTORES_META = {"de", "del", "la", "el", "los", "las", "en", "por", "a", "al", "y", "total", "mes", "mensual"}


def _palabras(texto):
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).lower()
    return {p for p in re.split(r"[^a-z0-9]+", t) if p}


def columna_meta(df, schema, metric=None):
    """La columna que dice cuánto se esperaba lograr de ESTA métrica, si el archivo la trae.

    Antes se tomaba la primera columna con "meta" o "presupuesto" en el nombre,
    fuera de la métrica que fuera. Con un archivo que trae ALTAS y Altas Eje, la
    meta de una se usaba para la otra, y el panel decía "0% · 112.4K de una
    meta de 1.3B". Ahora se exige:

    - que el nombre no hable de otra métrica: "Meta Altas Eje" es meta de
      "Altas Eje", no de "ALTAS"; una meta sin más nombre ("Presupuesto")
      vale para cualquiera;
    - que la escala tenga sentido: una meta mil veces el resultado no es su meta.
    """
    fechas, ids = set(schema.get("dates", [])), set(schema.get("ids", []))
    palabras_metrica = _palabras(metric) if metric is not None else set()
    real = float(numeric_series(df[metric]).sum()) if metric is not None and metric in df.columns else None
    candidatas = []
    for c in df.columns:
        if c == metric or c in fechas or c in ids or str(c).startswith("_"):
            continue
        if not META_RE.search(str(c)):
            continue
        valores = pd.to_numeric(df[c], errors="coerce")
        if not (valores.notna().sum() >= len(df) * 0.5 and float(valores.sum()) > 0):
            continue
        resto = {p for p in _palabras(c) if not META_RE.search(p)} - _CONECTORES_META
        if metric is not None:
            if resto and not resto <= palabras_metrica:
                continue  # es la meta de otra métrica
            if real is not None and real > 0 and not 0.02 <= real / float(valores.sum()) <= 50:
                continue  # escala imposible: no es la meta de esta métrica
        candidatas.append((2 if resto else 1, c))
    return max(candidatas, key=lambda x: x[0])[1] if candidatas else None


def unidad_interna(df, schema, dimension, metric=None):
    """Qué se cuenta dentro de cada grupo: puntos, asesores, tiendas.

    Es lo que permite comparar una región de 40 puntos con una de 3 sin que
    gane la grande por serlo. Se exige que la columna sea más fina que la
    dimensión y que los grupos tengan de verdad varias unidades; si no, no
    normaliza nada.
    """
    fechas, ids = set(schema.get("dates", [])), set(schema.get("ids", []))
    metricas = set(schema.get("metrics", []))
    candidatas = list(schema.get("semantic", {}).get("dimensions") or [])
    candidatas += [c for c in schema.get("categorical", []) if c not in candidatas]
    candidatas += [c for c in schema.get("text", []) if c not in candidatas]
    grupos = df[dimension].astype(str).nunique()
    mejor, mejor_n = None, 0
    for c in candidatas:
        if c in {dimension, metric} or c not in df.columns or c in fechas or c in ids or c in metricas:
            continue
        if str(c).startswith("_"):
            continue
        n = df[c].dropna().astype(str).nunique()
        if n <= grupos * 1.5 or n > 5000:
            continue
        por_grupo = df.groupby(df[dimension].astype(str))[c].nunique()
        if float(por_grupo.mean()) < 2:
            continue
        if n > mejor_n:
            mejor, mejor_n = c, n
    return mejor


def base_por_estado(df, schema, dimension):
    """Cuando no hay nada que sumar, se compara qué proporción salió bien.

    Es el caso de un archivo de tickets, tareas o asistencia: no tiene una
    columna numérica, así que antes no había panel de desempeño ninguno. Pero
    sí hay una pregunta clara —quién cierra y quién deja vencer— y la
    respuesta es una tasa, que además no depende del tamaño del grupo.
    """
    dim = df[dimension].fillna("Sin categoría").astype(str).str.strip().replace("", "Sin categoría")
    fechas, ids = set(schema.get("dates", [])), set(schema.get("ids", []))
    mejor = None
    for c in df.columns:
        if c == dimension or c in fechas or c in ids or str(c).startswith("_"):
            continue
        valores = df[c].dropna().astype(str).str.strip()
        valores = valores[valores.ne("")]
        if valores.empty or not 2 <= valores.nunique() <= 12:
            continue
        malos = {v for v in valores.unique() if _sin_tildes(v) in ESTADOS_MALOS}
        if not malos:
            continue
        proporcion = float(valores.isin(malos).mean())
        if 0.02 <= proporcion <= 0.95 and (mejor is None or proporcion > mejor[2]):
            mejor = (c, malos, proporcion)
    if mejor is None:
        return None
    columna, malos, _ = mejor
    marca = df[columna].astype(str).str.strip().isin(malos)
    tabla = pd.DataFrame({"_grupo": dim, "_malo": marca})
    resumen = tabla.groupby("_grupo")["_malo"].agg(["sum", "count", "mean"])
    resumen = resumen[resumen["count"] >= max(3, len(df) * 0.01)]
    if len(resumen) < 2:
        return None
    bien = (1 - resumen["mean"]) * 100
    orden = bien.sort_values(ascending=False)
    etiqueta_malos = ", ".join(sorted(malos)[:2])
    ranking = [{
        "nombre": str(n),
        "valor": float(v),
        "texto": f"{v:,.0f}%",
        "total": float(resumen.loc[n, "count"]),
        "detalle": f"{int(resumen.loc[n, 'count'] - resumen.loc[n, 'sum']):,} de {int(resumen.loc[n, 'count']):,}",
    } for n, v in orden.items()]
    return {
        "clave": "estado", "etiqueta": f"Registros fuera de «{etiqueta_malos}»", "sufijo": "%",
        "justo": True, "menos_es_mejor": False,
        "explicacion": (f"El archivo no tiene ninguna columna numérica que sumar, así que se compara la "
                        f"proporción de registros que NO quedaron en «{etiqueta_malos}» según "
                        f"{_etiqueta(schema, columna)}. Es una tasa, así que no depende del tamaño del grupo."),
        "ranking": ranking, "mejor": ranking[0], "peor": ranking[-1],
    }


def base_comparativa(df, schema, dimension, metric, additive):
    """Contra qué se compara a los grupos, y el ranking según esa base."""
    dim = df[dimension].fillna("Sin categoría").astype(str).str.strip().replace("", "Sin categoría")
    valores = numeric_series(df[metric])
    tabla = pd.DataFrame({"_grupo": dim, "_valor": valores}).dropna(subset=["_valor"])
    if tabla.empty:
        return None
    totales = tabla.groupby("_grupo")["_valor"].sum()
    registros = tabla.groupby("_grupo")["_valor"].size()
    etiqueta_m = _etiqueta(schema, metric)

    # Si cada grupo es una sola fila, no se está agregando nada: ordenar 30
    # productos por su precio no es una comparación de desempeño, es la
    # columna ordenada. Llamar "mejor desempeño" a eso sería inventar.
    if float(registros.median()) < 2:
        return None

    # En días de mora, quejas o devoluciones, el mejor es el que menos tiene.
    # Sin esto el panel coronaba como "mejor desempeño" al cliente con más
    # mora del archivo.
    peor_si_sube = bool(PEOR_SI_SUBE.search(str(metric)))

    def armar(clave, etiqueta, serie, sufijo, detalles, explicacion, justo=True):
        serie = serie.replace([np.inf, -np.inf], np.nan).dropna()
        if len(serie) < 2:
            return None
        orden = serie.sort_values(ascending=peor_si_sube)
        ranking = [{
            "nombre": str(n),
            "valor": float(v),
            "texto": (f"{v:,.0f}%" if sufijo == "%" else _fmt(v)),
            "total": float(totales.get(n, 0.0)),
            "detalle": detalles.get(n, ""),
        } for n, v in orden.items()]
        if peor_si_sube:
            explicacion += f" En {etiqueta_m} el mejor es el que menos tiene, así que el orden va al revés."
        return {"clave": clave, "etiqueta": etiqueta, "sufijo": sufijo, "justo": justo,
                "explicacion": explicacion, "ranking": ranking, "menos_es_mejor": peor_si_sube,
                "mejor": ranking[0], "peor": ranking[-1]}

    # 1. La meta. Es la base que el propio negocio ya definió.
    meta = columna_meta(df, schema, metric)
    if meta is not None:
        metas = pd.DataFrame({"_grupo": dim, "_meta": pd.to_numeric(df[meta], errors="coerce")})
        metas = metas.dropna().groupby("_grupo")["_meta"].sum()
        metas = metas[metas > 0]
        if len(metas) >= 2:
            cumplimiento = (totales.reindex(metas.index) / metas * 100)
            # "541 de 360" no dice qué es el 360: se nombra la meta.
            detalles = {n: f"{_fmt(totales.get(n, 0))} de una meta de {_fmt(metas[n])}" for n in metas.index}
            armado = armar("meta", "Cumplimiento de meta", cumplimiento, "%", detalles,
                           f"Se compara cuánto cumplió cada grupo de su propia meta ({_etiqueta(schema, meta)}), "
                           f"no cuánto vendió. Así un grupo pequeño que supera su meta gana a uno grande que no llega a la suya.")
            if armado:
                return armado

    # 2. Por unidad contable dentro del grupo (puntos, asesores).
    if additive:
        unidad = unidad_interna(df, schema, dimension, metric)
        if unidad is not None:
            unidades = tabla.assign(_unidad=df.loc[tabla.index, unidad].astype(str)) \
                            .groupby("_grupo")["_unidad"].nunique()
            unidades = unidades[unidades > 0]
            if len(unidades) >= 2 and int(unidades.max()) > int(unidades.min()):
                por_unidad = totales.reindex(unidades.index) / unidades
                etiqueta_u = _etiqueta(schema, unidad)
                detalles = {n: f"{_fmt(totales.get(n, 0))} entre {int(unidades[n])}" for n in unidades.index}
                # El nombre de la columna lo pone el archivo, así que la frase
                # no puede pluralizarlo: "cuántos nombrepuntos tiene" sale mal
                # con la mitad de los encabezados reales.
                armado = armar("unidad", f"{etiqueta_m} por {etiqueta_u}", por_unidad, "", detalles,
                               f"El total de cada grupo se divide entre cuántos valores distintos de "
                               f"«{etiqueta_u}» tiene. Comparar totales premiaría al grupo más grande por serlo.")
                if armado:
                    return armado

        # 3. Por registro: al menos descuenta el volumen de operaciones.
        if int(registros.max()) != int(registros.min()):
            por_registro = totales / registros
            detalles = {n: f"{_fmt(totales.get(n, 0))} en {int(registros[n]):,} registros" for n in registros.index}
            armado = armar("registro", f"{etiqueta_m} por registro", por_registro, "", detalles,
                           "El archivo no trae metas ni una unidad que contar, así que se compara el valor "
                           "promedio por registro. No mide tamaño, pero tampoco sustituye a una meta.")
            if armado:
                return armado

    if not additive:
        # Un promedio ya viene normalizado: comparar promedios es justo.
        promedios = tabla.groupby("_grupo")["_valor"].mean()
        detalles = {n: f"sobre {int(registros[n]):,} registros" for n in registros.index}
        armado = armar("promedio", f"{etiqueta_m} promedio", promedios, "", detalles,
                       "Se comparan promedios, que no dependen del tamaño de cada grupo.")
        if armado:
            return armado

    detalles = {n: f"{int(registros[n]):,} registros" for n in registros.index}
    # Caso justo por casualidad: si todos los grupos tienen el mismo número de
    # registros, el total ya está normalizado y ordenarlo no premia a nadie
    # por tamaño. Vale la pena distinguirlo del caso de abajo en vez de
    # advertir de un sesgo que aquí no existe.
    if int(registros.max()) == int(registros.min()):
        armado = armar("total_parejo", f"{etiqueta_m} total", totales, "", detalles,
                       f"Todos los grupos tienen el mismo número de registros "
                       f"({int(registros.max()):,}), así que comparar totales no premia a ninguno por tamaño.")
        if armado:
            return armado

    # 4. Sin nada contra qué comparar: se ordena por total, y se dice.
    return armar("total", f"{etiqueta_m} total", totales, "", detalles,
                 "Ojo: este orden mide tamaño, no desempeño. El archivo no trae metas ni una unidad "
                 "con la que dividir, así que un grupo grande aparece arriba por serlo. "
                 "Agregar una columna de meta cambia la lectura por completo.",
                 justo=False)


def analyze(df, schema, metric=None, dimension=None, top_n=5):
    sem=_semantic(schema)
    metrics=schema.get("semantic", {}).get("metrics") or schema.get("metrics", [])
    metrics=[m for m in metrics if m in df.columns]
    if not metric or metric not in df.columns:
        priority=["revenue","profit","quantity","cost","price","discount","tax","percentage","rating"]
        metric=(schema.get("metrica_preferida") if schema.get("metrica_preferida") in metrics
                else next((m for p in priority for m in metrics if sem.get(m)==p), metrics[0] if metrics else None))
    if not dimension or dimension not in df.columns:
        dimension=choose_dimension(df,schema)
    if not dimension:
        return None
    if not metric:
        # Sin columna numérica todavía se puede comparar, si el archivo dice en
        # qué estado quedó cada registro. Antes esto devolvía None y el panel
        # de desempeño simplemente no existía para tickets, tareas o asistencia.
        base=base_por_estado(df,schema,dimension)
        if not base:
            return None
        return {"metric": None, "dimension": dimension, "aggregation": "rate",
                "top": [], "bottom": [], "groups": len(base["ranking"]),
                "total": None, "additive": False, "base": base}
    x=df[[dimension,metric]].copy()
    x[metric]=numeric_series(x[metric])
    x[dimension]=x[dimension].fillna("Sin categoría").astype(str).str.strip().replace("", "Sin categoría")
    additive=sem.get(metric) in ADDITIVE
    agg="sum" if additive else "mean"
    grouped=x.groupby(dimension)[metric].sum() if additive else x.groupby(dimension)[metric].mean()
    grouped=grouped.replace([np.inf,-np.inf],np.nan).dropna()
    if grouped.empty:
        return None
    ordered=grouped.sort_values(ascending=False)
    top=ordered.head(top_n)
    bottom=ordered.tail(top_n).sort_values(ascending=True)
    total=float(grouped.sum()) if additive else float(grouped.mean())
    # `top`/`bottom` siguen siendo absolutos: el informe los usa para calcular
    # participación y concentración, donde el tamaño SÍ es lo que se mide.
    # La comparación de desempeño va aparte, en `base`, porque responde otra
    # pregunta y ordenarla por total sería la conclusión falsa de siempre.
    return {
        "metric": metric, "dimension": dimension, "aggregation": agg,
        "top": [(str(k), float(v)) for k,v in top.items()],
        "bottom": [(str(k), float(v)) for k,v in bottom.items()],
        "groups": int(len(grouped)), "total": total,
        "additive": additive,
        "base": base_comparativa(df, schema, dimension, metric, additive),
    }
