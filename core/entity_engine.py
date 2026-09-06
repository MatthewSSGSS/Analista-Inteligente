"""Detecta la ENTIDAD de una tabla: la columna cuyo valor identifica al
sujeto del que cada fila habla (un código de local, de punto de venta, de
funcionario, una cédula...), SIN depender de cómo se llame la columna.

Por qué existe: la detección de identificadores que ya había en
`core/semantic_engine.py` exige una señal en el NOMBRE de la columna
(`id_name_signal and (...)`, línea ~308): si la columna no se llama
`codigo`/`id`/`sku`/`factura`/..., nunca se reconoce, por muy código que
sean sus valores. En archivos reales el nombre varía (`Ref`, `Cod_Punto`,
`Identificador PDC`), así que hace falta reconocerlo por los DATOS.

Tres señales, ninguna depende del nombre:

1. FORMA. Un código lo genera una máquina, así que es rígido:
   "D3243.00002" → máscara "A9999.99999", y prácticamente todos los valores
   de la columna comparten esa misma máscara. Un nombre, una ciudad o una
   descripción nunca son así de regulares.

2. DETERMINACIÓN (la más importante). Si al agrupar por esa columna las
   demás quedan con UN solo valor por grupo, entonces esa columna las
   *determina*: el código "D3243.00002" siempre tiene el mismo Local, la
   misma Ciudad y el mismo Responsable, mientras que Ventas varía. Eso es
   exactamente la definición de entidad — y de paso separa sus ATRIBUTOS
   (lo que la describe) de su ACTIVIDAD (lo que se mide y se grafica).

3. REPETICIÓN. Un código de entidad agrupa varias filas. Si aparece una
   sola vez por fila, sigue siendo una entidad válida (un catálogo, una
   ficha por registro) pero se marca distinto, porque no se puede analizar
   su evolución igual.

Uso típico:
    cands = analyze_entity_candidates(df, schema)   # ranking completo
    best  = cands[0] if cands else None             # la entidad elegida
    best["determines"]  → columnas que describen a la entidad (atributos)
    best["varies"]      → columnas que varían (actividad/medidas)
"""
from __future__ import annotations

import re

import pandas as pd

# Máximo de filas que se analizan. Detectar la entidad es un problema de
# ESTRUCTURA, no de volumen: con una muestra amplia se llega a la misma
# conclusión que con millones de filas, y evita que un archivo grande
# congele la carga (mismo criterio que ya se usó al optimizar el lector de
# celdas combinadas).
SAMPLE_ROWS = 20000

# Debajo de esto una columna no es una entidad navegable: con 2 valores
# distintos no hay nada que "seleccionar y perfilar" — eso es una categoría
# (Norte/Sur), no un código.
MIN_DISTINCT = 3

# Una columna que determina a otra puede tener excepciones reales (un local
# que cambió de nombre, un dato mal escrito). Se exige que la determine en
# la gran mayoría de los grupos, no en el 100%.
DETERMINES_TOLERANCE = 0.95


def value_mask(value, collapse: bool = False) -> str:
    """Convierte un valor a su "forma": letras → A/a, dígitos → 9, y el
    resto (puntos, guiones, barras) se conserva tal cual.

        "D3243.00002" → "A9999.99999"
        "LOC-4021"    → "AAA-9999"

    Con collapse=True se colapsan las repeticiones ("A9999.99999" →
    "A9.9"), para reconocer familias de códigos donde la cantidad de
    dígitos varía entre un valor y otro ("D3243.2" y "D3243.00002" son el
    mismo formato en la práctica, aunque su máscara exacta difiera).
    """
    s = str(value).strip()
    if not s:
        return ""
    out = []
    for ch in s:
        if ch.isdigit():
            out.append("9")
        elif ch.isalpha():
            out.append("A" if ch.isupper() else "a")
        else:
            out.append(ch)
    mask = "".join(out)
    if collapse:
        mask = re.sub(r"(.)\1+", r"\1", mask)
    return mask


def is_code_like(mask: str) -> bool:
    """¿Esa máscara es de un CÓDIGO o de una palabra corriente?

    Sin este filtro, la máscara colapsada volvía "consistente" a cualquier
    columna de texto: "Norte"→"Aaaaa", "Sur"→"Aaa" y "Centro"→"Aaaaaa"
    colapsan las tres a "Aa", dando 100% de coincidencia y haciendo pasar
    una columna de categorías por un código. La diferencia real es la
    ESTRUCTURA:

    - Tiene dígitos ("A9999.99999", "9999")        → código
    - Tiene minúsculas ("Aaaaa")                   → palabra, no código
    - Solo mayúsculas y separadores ("AA", "AAA-AA") → código (p. ej. país,
      siglas de sucursal), porque una palabra normal no se escribe así.
    """
    if not mask:
        return False
    # Las minúsculas se revisan ANTES que los dígitos: "obs 41" → "aaa 99"
    # tiene dígitos, pero es texto libre, no un código. Un código generado
    # por un sistema no lleva palabras en minúscula.
    if "a" in mask:
        return False
    if "9" in mask:
        return True
    # Solo mayúsculas: cuenta como código a partir de 2 caracteres ("CO",
    # "MX", "AAA-AA"). Una sola letra no es evidencia de nada — columnas de
    # categoría como Zona N/S/C, Sexo M/F o Estado A/I quedarían marcadas
    # como códigos por pura coincidencia de forma.
    return "A" in mask and len(mask) >= 2


def dominant_mask(series: pd.Series) -> tuple[str, float, bool]:
    """(máscara más frecuente, proporción que la comparte, si es la EXACTA).

    Se prueba primero la máscara exacta y, si esa está repartida, la
    colapsada — así un código de largo variable no se descarta por una
    diferencia que en realidad no importa. El tercer valor dice cuál de las
    dos ganó, porque no valen lo mismo como evidencia: la colapsada es
    mucho más laxa (un consecutivo 1, 2, ... 5000 tiene máscaras exactas
    distintas —"9", "99", "9999"— pero todas colapsan a "9")."""
    vals = series.dropna().astype(str).str.strip()
    vals = vals[vals != ""]
    if vals.empty:
        return "", 0.0, False
    for collapse in (False, True):
        masks = vals.map(lambda v: value_mask(v, collapse=collapse))
        counts = masks.value_counts()
        if counts.empty:
            continue
        mask, ratio = counts.index[0], float(counts.iloc[0] / len(masks))
        if ratio >= 0.9 or collapse:
            return mask, ratio, not collapse
    return "", 0.0, False


def _determines(df: pd.DataFrame, key_col: str, other_col: str) -> bool:
    """True si `key_col` determina a `other_col`: cada valor de la clave
    tiene (casi) siempre el mismo valor en la otra columna. Los vacíos no
    cuentan: una ficha incompleta no debe descalificar la relación."""
    pair = df[[key_col, other_col]].dropna()
    if pair.empty:
        return False
    per_key = pair.groupby(key_col)[other_col].nunique(dropna=True)
    if per_key.empty:
        return False
    return float((per_key <= 1).mean()) >= DETERMINES_TOLERANCE


def _is_disqualified(col, series: pd.Series, schema: dict) -> bool:
    """Descarta de plano lo que nunca puede ser la entidad del archivo."""
    name = str(col)
    if name.startswith("__") or name.startswith("_geo_"):
        return True  # columnas internas del propio motor
    if col in schema.get("dates", []):
        return True  # una fecha no identifica al sujeto, lo ubica en el tiempo
    # Una medida real (dinero, cantidad, porcentaje...) no es un identificador
    # aunque sus valores sean regulares. Se mira el tipo SEMÁNTICO, no el
    # dtype: un código guardado como número entero sigue siendo un código.
    sem = {x.get("column"): x.get("semantic_type") for x in schema.get("semantic", {}).get("columns", [])}
    if sem.get(col) in {"revenue", "profit", "cost", "price", "quantity", "discount", "tax", "percentage", "rating", "age"}:
        return True
    # Se respeta la conclusión del motor SOLO cuando es una medida de la que
    # está seguro (Moneda, Cantidad, Porcentaje...). Deliberadamente NO se
    # descarta el tipo genérico "Número": ese es justo el cajón donde el
    # motor deja las numéricas que no supo clasificar, y donde caen los
    # códigos numéricos (4021, 202608) que este detector existe para
    # rescatar. Descartarlos ahí heredaría la misma ceguera que se quiere
    # corregir; mejor dejarlos competir y que el puntaje decida.
    if schema.get("types", {}).get(col) in {"Moneda", "Cantidad", "Porcentaje", "Puntuación", "Edad"}:
        return True
    nunique = series.nunique(dropna=True)
    if nunique < MIN_DISTINCT:
        return True
    return False


def analyze_entity_candidates(df: pd.DataFrame, schema: dict | None = None, top: int = 5) -> list[dict]:
    """Ranking de columnas que podrían ser LA entidad del archivo, de más a
    menos probable. Cada candidata trae con qué evidencia se eligió, para
    que la interfaz pueda explicarlo y el usuario corregirlo si hace falta.
    """
    schema = schema or {}
    if df is None or df.empty or not len(df.columns):
        return []

    data = df.sample(SAMPLE_ROWS, random_state=0) if len(df) > SAMPLE_ROWS else df
    n_rows = len(data)

    usable = [c for c in data.columns if not _is_disqualified(c, data[c], schema)]
    if not usable:
        return []

    results = []
    for col in usable:
        series = data[col]
        mask, mask_ratio, mask_exact = dominant_mask(series)
        n_entities = int(series.nunique(dropna=True))
        if n_entities < MIN_DISTINCT:
            continue
        # La regularidad de forma solo cuenta como evidencia si la forma es
        # de código. Una columna de palabras puede seguir siendo la entidad
        # (un nombre propio, p. ej.), pero entonces tendrá que ganarse el
        # puesto por lo que DETERMINA, no por su apariencia.
        # La máscara colapsada vale la MITAD que la exacta: es mucho más
        # fácil de cumplir. Cualquier columna de enteros (una venta, una
        # cantidad) tiene máscaras exactas distintas —"99", "999", "9999"—
        # que colapsan todas a "9", dando un falso "formato perfecto". Un
        # código de verdad suele tener largo fijo y gana por la exacta.
        format_score = 0.0
        if is_code_like(mask):
            format_score = mask_ratio if mask_exact else mask_ratio * 0.5

        # ── Señal 2: ¿a qué columnas determina? ──
        others = [c for c in data.columns if c != col and not str(c).startswith("__") and not str(c).startswith("_geo_")]
        determines, varies = [], []
        for other in others:
            (determines if _determines(data, col, other) else varies).append(other)
        determination = len(determines) / len(others) if others else 0.0

        # ── Señal 3: ¿agrupa filas o hay una por código? ──
        rows_per_entity = n_rows / n_entities if n_entities else 0.0
        groups_rows = rows_per_entity >= 1.5
        repetition = 1.0 if groups_rows else 0.5

        # ===== Determinación TRIVIAL =====
        # Si cada valor aparece en una sola fila, agrupar por esa columna da
        # grupos de tamaño 1, y entonces "determina" TODAS las demás por pura
        # aritmética, sin significar nada. Una columna de texto libre
        # ("obs 1", "obs 2"...) llegaba así a determinarlo todo y ganaba el
        # ranking. Sin agrupación no hay evidencia de determinación: se
        # descarta esa señal y se puntúa solo con lo que sí aplica —la forma,
        # y exigiendo la máscara EXACTA, que es la que distingue un código de
        # catálogo ("P-0001", exacta al 100%) de un consecutivo 1..N (exacta
        # baja, solo la colapsada coincide).
        if groups_rows:
            score = 0.35 * format_score + 0.45 * determination + 0.20 * repetition
        else:
            strict_format = format_score if mask_exact else 0.0
            determines, varies = [], others  # la determinación trivial no se reporta
            determination = 0.0
            score = 0.70 * strict_format + 0.20 * repetition
            if score < 0.30:
                continue  # ni agrupa ni tiene forma de código: no es la entidad
        results.append({
            "column": col,
            "score": round(score, 3),
            "confidence": "alta" if score >= 0.70 else "media" if score >= 0.50 else "baja",
            "mask": mask if is_code_like(mask) else "",
            "mask_ratio": round(format_score, 3),
            "n_entities": n_entities,
            "rows_per_entity": round(rows_per_entity, 2),
            "groups_rows": groups_rows,
            "determines": determines,
            "varies": varies,
            "sample_values": series.dropna().astype(str).drop_duplicates().head(3).tolist(),
        })

    results.sort(key=lambda r: (r["score"], len(r["determines"])), reverse=True)
    return results[:top]


def best_entity(df: pd.DataFrame, schema: dict | None = None, min_score: float = 0.50) -> dict | None:
    """La entidad más probable, o None si ninguna candidata tiene evidencia
    suficiente. Preferir None antes que una mala elección: un perfil armado
    sobre la columna equivocada confunde más que no ofrecer el perfil."""
    candidates = analyze_entity_candidates(df, schema)
    if not candidates:
        return None
    best = candidates[0]
    return best if best["score"] >= min_score else None


def describe_entity(candidate: dict) -> str:
    """Explicación en español de POR QUÉ se eligió esa columna, para
    mostrarla en la interfaz — que el usuario nunca se pregunte de dónde
    salió la decisión."""
    if not candidate:
        return "No se encontró una columna que identifique a una entidad en este archivo."
    parts = [f"**{candidate['column']}** · {candidate['n_entities']:,} valores distintos"]
    if candidate["mask_ratio"] >= 0.9 and candidate["mask"]:
        parts.append(f"formato consistente `{candidate['mask']}` en el {candidate['mask_ratio']*100:.0f}% de los casos")
    if candidate["determines"]:
        shown = ", ".join(str(c) for c in candidate["determines"][:4])
        extra = f" +{len(candidate['determines'])-4} más" if len(candidate["determines"]) > 4 else ""
        parts.append(f"determina {len(candidate['determines'])} columnas ({shown}{extra})")
    if candidate["groups_rows"]:
        parts.append(f"agrupa {candidate['rows_per_entity']:.1f} filas en promedio")
    return " · ".join(parts)
