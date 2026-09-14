"""Lectura comercial por canal: dónde invertir, dónde intervenir, dónde salir.

Lo que una gerencia de ventas necesita para dirigir la estrategia no es el
ranking de quién vendió más —eso ya lo sabe— sino el cruce de dos preguntas
que casi nunca se miran juntas:

    ¿cuánto pesa este canal?   ×   ¿hacia dónde va?

Un canal grande que cae es una urgencia aunque siga siendo el número uno.
Uno pequeño que crece al 40% es una apuesta, no un rezagado. Mirados por
separado, el primero parece sano y el segundo prescindible, que es
exactamente la decisión al revés.

Este módulo arma esa matriz y, para cada canal, separa además de dónde viene
su movimiento: si hace más operaciones o si cada operación vale más. Son dos
palancas distintas —cobertura y precio/mezcla— y se accionan distinto.

Todo sale del propio archivo: la dimensión de canal se detecta, y si no hay
una columna que se llame así se usa la unidad de negocio que exista.
"""
from __future__ import annotations

import re
from typing import Optional

import numpy as np
import pandas as pd

from .diagnostics import PEOR_SI_SUBE, _fmt, _lista, _mes

# Encabezados que nombran el canal de venta. Si ninguno aparece, se usa la
# unidad de negocio del archivo: la matriz funciona igual con puntos,
# regiones o productos, solo cambia de qué se está hablando.
CANAL_RE = re.compile(r"canal|channel|segmento|linea|línea|modalidad|tipo de venta|fuerza", re.I)

# Cuánto tiene que moverse un canal para considerarlo en crecimiento o en
# caída. Es el mismo umbral del veredicto ejecutivo: por debajo hay ruido,
# no tendencia.
UMBRAL_MOVIMIENTO = 1.0

CUADRANTES = {
    "proteger": {
        "etiqueta": "Proteger y escalar",
        "orden": 2,
        "lectura": "Pesa y crece. Es donde el negocio ya está funcionando.",
        "accion": "Asegurar capacidad y stock antes de que el crecimiento tope con el límite operativo.",
    },
    "intervenir": {
        "etiqueta": "Intervenir ya",
        "orden": 0,
        "lectura": "Pesa mucho y está cayendo. Es la urgencia del periodo.",
        "accion": "Diagnóstico esta semana: cada punto que cae aquí cuesta más que en cualquier otro cuadrante.",
    },
    "apostar": {
        "etiqueta": "Apostar",
        "orden": 3,
        "lectura": "Todavía pesa poco, pero crece. Es la apuesta del próximo año.",
        "accion": "Probar un aumento de cobertura acotado y medir si el crecimiento aguanta más volumen.",
    },
    "revisar": {
        "etiqueta": "Revisar continuidad",
        "orden": 1,
        "lectura": "Pesa poco y cae. Consume atención sin devolverla.",
        "accion": "Decidir explícitamente si se reactiva con un plan corto o se libera el recurso a otro canal.",
    },
    # Quinto estado, y el más frecuente en la práctica. Antes un canal que se
    # movía -0,5% caía como "proteger" o "revisar" según pesara, y en la
    # matriz aparecía una burbuja verde dentro de la zona roja: el fondo
    # partía en 0 y la clasificación en ±1%. Por debajo del umbral no hay
    # tendencia, y decirlo es más honesto que forzar una jugada.
    "estable": {
        "etiqueta": "Estable",
        "orden": 4,
        "lectura": "Se movió menos de 1% frente al periodo anterior: no hay tendencia que atender.",
        "accion": "Sostener y vigilar. El esfuerzo del periodo va donde sí hay movimiento.",
    },
}


def puntaje_salud(fila: dict) -> tuple[float, str]:
    """Qué tan bien va un canal, de 0 (mal) a 1 (bien), y contra qué se midió.

    Es lo que colorea el semáforo de rojo a verde. El color binario de antes
    (rojo si no llega a la meta, verde si llega) pintaba igual un 88% que un
    40%: todos los canales de un archivo real salían en rojo y el color dejó
    de distinguir nada. Una escala continua sí separa "casi" de "lejos".

    Referencia, en orden de preferencia:
    - Cumplimiento de meta: 80% o menos es rojo, 90% ámbar, 100% o más verde.
    - Si no hay meta, el crecimiento: -5% o menos rojo, 0% ámbar, +5% verde.
    """
    if fila.get("cumplimiento") is not None:
        return max(0.0, min(1.0, (float(fila["cumplimiento"]) - 80.0) / 20.0)), "meta"
    if fila.get("crecimiento") is not None:
        return max(0.0, min(1.0, (float(fila["crecimiento"]) + 5.0) / 10.0)), "crecimiento"
    return 0.5, "sin_referencia"


def estado_salud(puntaje: float) -> str:
    """El puntaje en palabras, para no depender solo del color."""
    if puntaje >= 0.75:
        return "Va bien"
    if puntaje >= 0.35:
        return "Atención"
    return "Crítico"


def columna_canal(df: pd.DataFrame, schema: dict, metrica=None) -> Optional[str]:
    """La columna que representa el canal de venta, o la unidad de negocio."""
    from .diagnostics import dimensiones_candidatas

    semantica = {x.get("column"): x.get("semantic_type")
                 for x in schema.get("semantic", {}).get("columns", [])}
    candidatas = dimensiones_candidatas(df, schema, metrica)
    # Prioridad: el tipo semántico "channel", luego el nombre, luego lo que haya.
    for c in candidatas:
        if semantica.get(c) == "channel":
            return c
    for c in candidatas:
        if CANAL_RE.search(str(c)):
            return c
    # Una matriz con 40 columnas no se lee; si la unidad es muy fina, no sirve
    # para una lectura de estrategia y es mejor no forzarla.
    for c in candidatas:
        if 2 <= df[c].astype(str).nunique() <= 25:
            return c
    return None


def _periodos(df, schema, canal, metrica) -> Optional[pd.DataFrame]:
    fechas = [c for c in schema.get("dates", []) if c in df.columns]
    if not fechas:
        return None
    x = pd.DataFrame({
        "_periodo": pd.to_datetime(df[fechas[0]], errors="coerce"),
        "_canal": df[canal].astype(str).str.strip(),
        "_valor": pd.to_numeric(df[metrica], errors="coerce"),
    }).dropna(subset=["_periodo", "_valor"])
    x = x[x["_canal"].ne("") & x["_canal"].str.lower().ne("nan")]
    if x.empty:
        return None
    x["_periodo"] = x["_periodo"].dt.to_period("M").dt.start_time
    return x


def _mezcla(sub: pd.DataFrame, ultimo, previo) -> dict:
    """De dónde viene el movimiento: más operaciones, o de mayor valor.

    Son dos palancas distintas. Crecer haciendo más operaciones se sostiene
    ampliando cobertura; crecer porque cada operación vale más se sostiene
    con mezcla o precio. Confundirlas hace que se invierta en lo que no era.
    """
    a = sub[sub["_periodo"] == previo]
    b = sub[sub["_periodo"] == ultimo]
    n_a, n_b = len(a), len(b)
    v_a, v_b = float(a["_valor"].sum()), float(b["_valor"].sum())
    ticket_a = v_a / n_a if n_a else 0.0
    ticket_b = v_b / n_b if n_b else 0.0
    vol_pct = ((n_b - n_a) / n_a * 100) if n_a else None
    tic_pct = ((ticket_b - ticket_a) / ticket_a * 100) if ticket_a else None
    palanca, detalle = None, None
    if vol_pct is not None and tic_pct is not None:
        if abs(vol_pct) >= abs(tic_pct) and abs(vol_pct) >= 5:
            palanca = "volumen"
            detalle = f"{'más' if vol_pct > 0 else 'menos'} operaciones ({vol_pct:+.0f}%)"
        elif abs(tic_pct) >= 5:
            palanca = "ticket"
            detalle = f"cada operación vale {'más' if tic_pct > 0 else 'menos'} ({tic_pct:+.0f}%)"
        else:
            palanca, detalle = "estable", "sin cambio relevante en operaciones ni en valor por operación"
    return {"volumen_pct": vol_pct, "ticket_pct": tic_pct,
            "palanca": palanca, "mezcla": detalle,
            "operaciones": n_b, "ticket": ticket_b}


def matriz_comercial(df: pd.DataFrame, schema: dict, canal: Optional[str] = None,
                     metrica: Optional[str] = None) -> Optional[dict]:
    """La matriz peso × crecimiento por canal, con su acción recomendada."""
    from .performance import columna_meta

    if df is None or df.empty:
        return None
    metricas = [m for m in (schema.get("metrics") or []) if m in df.columns]
    if metrica not in metricas:
        neutras = [m for m in metricas if not PEOR_SI_SUBE.search(str(m))]
        metrica = (neutras or metricas or [None])[0]
    if not metrica:
        return None
    canal = canal or columna_canal(df, schema, metrica)
    if not canal or canal not in df.columns:
        return None

    serie = _periodos(df, schema, canal, metrica)
    if serie is None or serie["_periodo"].nunique() < 2:
        return None
    periodos = sorted(serie["_periodo"].unique())
    ultimo, previo = periodos[-1], periodos[-2]

    actual = serie[serie["_periodo"] == ultimo].groupby("_canal")["_valor"].sum()
    anterior = serie[serie["_periodo"] == previo].groupby("_canal")["_valor"].sum()
    canales = sorted(set(actual.index) | set(anterior.index))
    if len(canales) < 2:
        return None
    total_actual = float(actual.sum())
    if total_actual <= 0:
        return None

    # Meta por canal, si el archivo la trae: es la referencia que el negocio
    # ya definió y manda sobre cualquier comparación que inventemos aquí.
    meta_col = columna_meta(df, schema, metrica)
    metas = None
    if meta_col is not None:
        m = pd.DataFrame({"_canal": df[canal].astype(str).str.strip(),
                          "_meta": pd.to_numeric(df[meta_col], errors="coerce")}).dropna()
        fechas = [c for c in schema.get("dates", []) if c in df.columns]
        if fechas:
            m["_periodo"] = pd.to_datetime(df.loc[m.index, fechas[0]], errors="coerce").dt.to_period("M").dt.start_time
            m = m[m["_periodo"] == ultimo]
        metas = m.groupby("_canal")["_meta"].sum()
        metas = metas[metas > 0]

    filas = []
    for nombre in canales:
        valor = float(actual.get(nombre, 0.0))
        base = float(anterior.get(nombre, 0.0))
        participacion = valor / total_actual * 100
        crecimiento = ((valor - base) / abs(base) * 100) if base else None
        sub = serie[serie["_canal"] == nombre]
        mezcla = _mezcla(sub, ultimo, previo)
        cumplimiento = None
        if metas is not None and nombre in metas.index:
            cumplimiento = valor / float(metas[nombre]) * 100
        filas.append({
            "canal": str(nombre), "valor": valor, "anterior": base,
            "participacion": participacion, "crecimiento": crecimiento,
            "delta": valor - base, "cumplimiento": cumplimiento,
            "meta": float(metas[nombre]) if (metas is not None and nombre in metas.index) else None,
            **mezcla,
        })

    # El corte de "pesa mucho" es la participación media, no un número fijo:
    # con 4 canales el promedio es 25% y con 20 es 5%, y un umbral fijo
    # llamaría "pequeños" a todos en el segundo caso.
    corte_peso = 100.0 / len(filas)
    for fila in filas:
        crece = (fila["crecimiento"] or 0) >= UMBRAL_MOVIMIENTO
        cae = (fila["crecimiento"] or 0) <= -UMBRAL_MOVIMIENTO
        pesa = fila["participacion"] >= corte_peso
        fila["pesa"] = pesa
        if cae:
            clave = "intervenir" if pesa else "revisar"
        elif crece:
            clave = "proteger" if pesa else "apostar"
        else:
            clave = "estable"
        fila["cuadrante"] = clave
        fila["cuadrante_label"] = CUADRANTES[clave]["etiqueta"]
        fila["accion"] = CUADRANTES[clave]["accion"]

    filas.sort(key=lambda f: (CUADRANTES[f["cuadrante"]]["orden"], -f["participacion"]))
    en_riesgo = [f for f in filas if f["cuadrante"] == "intervenir"]
    creciendo = [f for f in filas if (f["crecimiento"] or 0) >= UMBRAL_MOVIMIENTO]
    cayendo = [f for f in filas if (f["crecimiento"] or 0) <= -UMBRAL_MOVIMIENTO]
    total_anterior = float(anterior.sum())
    crecimiento_total = ((total_actual - total_anterior) / abs(total_anterior) * 100) if total_anterior else None

    return {
        "canal": canal, "metrica": metrica, "meta_columna": meta_col,
        "periodo": ultimo, "periodo_anterior": previo,
        "periodo_label": _mes(ultimo), "periodo_anterior_label": _mes(previo),
        "total": total_actual, "total_anterior": total_anterior,
        "crecimiento_total": crecimiento_total,
        "corte_peso": corte_peso,
        "filas": filas,
        "en_riesgo": en_riesgo,
        "creciendo": creciendo, "cayendo": cayendo,
        "peso_en_riesgo": sum(f["participacion"] for f in en_riesgo),
        "titular": _titular(filas, en_riesgo, cayendo, crecimiento_total),
    }


def _titular(filas, en_riesgo, cayendo, crecimiento_total) -> str:
    """La frase con la que abre la lectura ante gerencia."""
    if en_riesgo:
        peso = sum(f["participacion"] for f in en_riesgo)
        return (f"{_lista([f['canal'] for f in en_riesgo[:3]])} "
                f"{'concentra' if len(en_riesgo) == 1 else 'concentran'} el {peso:.0f}% del negocio "
                f"y {'está cayendo' if len(en_riesgo) == 1 else 'están cayendo'}. Es la prioridad del periodo.")
    if cayendo:
        return (f"Ningún canal grande está en caída. {len(cayendo)} de {len(filas)} retroceden, "
                f"pero pesan poco: la decisión ahí es de continuidad, no de urgencia.")
    if (crecimiento_total or 0) >= UMBRAL_MOVIMIENTO:
        return (f"Todos los canales sostienen o crecen y el total sube {crecimiento_total:.1f}%. "
                f"La pregunta pasa a ser dónde poner capacidad antes de que el crecimiento tope.")
    grandes = sorted(filas, key=lambda f: f["participacion"], reverse=True)[:2]
    peso = sum(f["participacion"] for f in grandes)
    return (f"Ningún canal se movió más de {UMBRAL_MOVIMIENTO:.0f}% frente al periodo anterior. "
            f"La lectura es de peso, no de tendencia: {_lista([f['canal'] for f in grandes])} "
            f"concentran el {peso:.0f}% del negocio.")


def _tono_palanca(fila: dict) -> str:
    """Si la palanca de un canal suma o resta, para pintarla con sentido."""
    palanca = fila.get("palanca")
    if palanca == "volumen" and fila.get("volumen_pct") is not None:
        return "bueno" if fila["volumen_pct"] > 0 else "malo"
    if palanca == "ticket" and fila.get("ticket_pct") is not None:
        return "bueno" if fila["ticket_pct"] > 0 else "malo"
    return "info"


def _jugada(fila: dict, tipo: str, impacto: float, tono: str, partes: list) -> dict:
    """Arma una jugada con su frase guardada por partes, cada una con su tono.

    Los tonos son tres, y cada uno tiene un color fijo en la interfaz: "malo"
    en rojo, "bueno" en verde e "info" en negro, más "enfasis" para el nombre
    del canal. Guardar la frase por partes permite pintar cada cifra según lo
    que significa sin que la interfaz tenga que volver a interpretar el texto.
    `texto` sigue siendo la frase entera, para quien la necesite sin colores.
    """
    return {
        "canal": fila["canal"], "tipo": tipo, "impacto": float(impacto), "tono": tono,
        "partes": partes, "texto": "".join(texto for texto, _ in partes),
        "palanca": fila.get("mezcla") or "", "palanca_tono": _tono_palanca(fila),
        "cuadrante": fila["cuadrante"],
    }


def oportunidades(matriz: dict, top: int = 4) -> list[dict]:
    """Las jugadas concretas que salen de la matriz, ordenadas por impacto.

    El impacto se estima en la moneda del archivo, no en adjetivos: recuperar
    lo que un canal perdió, o cerrar su brecha contra la meta. Poner la cifra
    al lado es lo que permite comparar dos jugadas y elegir.

    Cada jugada trae además su tono: una pérdida o una brecha es "malo", un
    canal que crece es "bueno" y sostener lo que ya pesa es "info".
    """
    if not matriz:
        return []
    anterior = matriz["periodo_anterior_label"]
    jugadas = []
    for fila in matriz["filas"]:
        canal = fila["canal"]
        if fila["cuadrante"] == "intervenir" and fila["delta"] < 0:
            partes = [("Recuperar lo que ", "info"), (canal, "enfasis"),
                      (" perdió frente a " + anterior + ": ", "info"),
                      (_fmt(fila["delta"]), "malo")]
            if fila["crecimiento"] is not None:
                partes += [(", una caída de ", "info"), (f"{fila['crecimiento']:+.1f}%", "malo")]
            partes.append((".", "info"))
            jugadas.append(_jugada(fila, "Recuperar", abs(fila["delta"]), "malo", partes))
        if fila["cumplimiento"] is not None and fila["cumplimiento"] < 100 and fila["meta"]:
            brecha = float(fila["meta"]) - fila["valor"]
            if brecha > 0:
                partes = [(canal, "enfasis"), (" va en ", "info"),
                          (f"{fila['cumplimiento']:.0f}%", "malo"),
                          (" de su meta: faltan ", "info"), (_fmt(brecha), "malo"),
                          (" para cerrarla.", "info")]
                jugadas.append(_jugada(fila, "Cerrar brecha", brecha, "malo", partes))
        if fila["cuadrante"] == "apostar" and (fila["crecimiento"] or 0) >= 10:
            partes = [(canal, "enfasis"), (" crece ", "info"),
                      (f"{fila['crecimiento']:+.0f}%", "bueno"),
                      (" con solo ", "info"), (f"{fila['participacion']:.1f}%", "info"),
                      (" del negocio: hay espacio para ampliarlo.", "info")]
            jugadas.append(_jugada(fila, "Escalar", fila["valor"], "bueno", partes))
    if not jugadas:
        # Sin urgencias ni apuestas la sección no queda vacía: cuando nada se
        # mueve, la jugada del periodo es no perder lo que más pesa. Es un dato
        # para cuidar, no una alarma, y por eso va en tono informativo.
        for fila in sorted(matriz["filas"], key=lambda f: f["participacion"], reverse=True)[:2]:
            partes = [(fila["canal"], "enfasis"), (" aporta el ", "info"),
                      (f"{fila['participacion']:.1f}%", "info"),
                      (" del negocio y está estable: la prioridad es que no empiece a caer.", "info")]
            jugadas.append(_jugada(fila, "Sostener", fila["valor"], "info", partes))
    jugadas.sort(key=lambda j: j["impacto"], reverse=True)
    # Una misma jugada por canal: dos líneas del mismo canal compiten entre
    # ellas en la lista y desplazan a un canal que no aparece nunca.
    vistos, salida = set(), []
    for jugada in jugadas:
        if jugada["canal"] in vistos:
            continue
        vistos.add(jugada["canal"])
        salida.append(jugada)
        if len(salida) >= top:
            break
    return salida
