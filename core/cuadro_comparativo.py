"""Cuadro comparativo: varios elementos lado a lado, con la misma vara.

La pregunta que responde es la de una reunión de seguimiento: "tengo seis
vendedores, ¿cómo va cada uno?". El panel ya tenía piezas que la rozaban
—el mejor y el peor de una dimensión, la comparación A contra B de dos
personas— pero ninguna ponía a TODOS los elegidos en un mismo cuadro, con
su posición, su meta, su movimiento y un veredicto en palabras.

Tres decisiones que vale la pena conservar:

- **La vara es la meta cuando existe.** Vender 90 con meta de 80 es ir mejor
  que vender 120 con meta de 200. Si el archivo trae meta, el orden es por
  cumplimiento; si no, por el resultado, y entonces cada uno se compara
  contra el promedio de los elegidos.
- **Todo se calcula sobre los elegidos, no sobre el archivo.** El promedio,
  la participación y la posición son "entre estos seis". Comparar a seis
  vendedores contra un promedio que incluye a otros cuarenta no es lo que
  se pidió.
- **Se avisa cuando el total mide tamaño.** Sin meta, un vendedor con el
  triple de registros aparece arriba por atender más, no necesariamente por
  hacerlo mejor. No se cambia el orden —el total sigue siendo lo que se
  pregunta—, pero se dice y se muestra el promedio por registro al lado.

Funciona con una fila por elemento (la tabla típica "Vendedor · Ventas ·
Meta") y con muchas filas por elemento (el detalle de operaciones con
fecha). Sin columnas numéricas compara cuántos registros tiene cada uno.
"""
from __future__ import annotations

import re
from typing import Optional

import numpy as np
import pandas as pd

from .diagnostics import (METRICA_CONTEO, PEOR_SI_SUBE, PRIORIDAD_DIMENSION, _aditiva, _fmt,
                          _lista, _mes, _periodo_parcial, _semantica)
from .numeric import numeric_series
from .performance import columna_meta

# Encabezados que nombran a una persona o a quien responde por un resultado.
# Van primero en "Comparar por" porque es la comparación que más se pide. No
# se incluye "nombre" a secas: "Nombre punto de venta" no es una persona.
PERSONA_RE = re.compile(
    r"vendedor|asesor|ejecutiv|agente|representante|promotor|consultor|responsable|"
    r"jefe|supervisor|gerente|coordinador|empleado|colaborador|funcionario|"
    r"seller|salesperson|agent|employee",
    re.I,
)

# Más elementos que esto no caben en un cuadro que se lea de un vistazo. Es el
# tope de la selección, no de las opciones: la lista deja elegir entre todos.
MAX_ELEGIDOS = 12
SUGERIDOS = 8

# Por debajo de esta distancia del promedio se dice "en el promedio": un 2%
# arriba o abajo entre seis vendedores es ruido, no una diferencia.
UMBRAL_PROMEDIO = 5.0
# Movimiento mínimo para decir que alguien subió o bajó. El mismo umbral del
# veredicto ejecutivo y de la estrategia por canal.
UMBRAL_MOVIMIENTO = 1.0
# Cumplimiento desde el que se dice "cerca de la meta".
CERCA_DE_META = 90.0

_VACIOS = {"", "nan", "none", "nat", "<na>"}


def _limpiar_grupo(serie: pd.Series) -> pd.Series:
    texto = serie.astype(str).str.strip()
    return texto.where(~texto.str.lower().isin(_VACIOS))


def opciones_de_comparacion(df: pd.DataFrame, schema: dict) -> list[str]:
    """Columnas por las que tiene sentido armar el cuadro, de mejor a peor.

    A diferencia de `diagnostics.dimensiones_candidatas`, aquí NO se exige
    que cada valor se repita: la tabla de seis vendedores con una fila cada
    uno es justamente el caso más común de esta pestaña, y con esa exigencia
    se quedaba sin opciones.
    """
    full = schema.get("full_name") if isinstance(schema.get("full_name"), dict) else {}
    nombre_completo = full.get("column")
    ocultas = set(full.get("parts", [])) if nombre_completo in df.columns else set()

    columnas = [nombre_completo] if nombre_completo else []
    columnas += [c for c in (schema.get("semantic", {}).get("dimensions") or []) if c not in columnas]
    for lista in ("categorical", "text", "geography"):
        columnas += [c for c in schema.get(lista, []) if c not in columnas]

    fechas, ids = set(schema.get("dates", [])), set(schema.get("ids", []))
    metricas = set(schema.get("metrics", []))
    tipos = _semantica(schema)
    candidatas = []
    for c in columnas:
        if c not in df.columns or c in fechas or c in ids or c in metricas or c in ocultas:
            continue
        if str(c).startswith("_") and c != nombre_completo:
            continue
        valores = _limpiar_grupo(df[c]).dropna()
        distintos = valores.nunique()
        if distintos < 2 or distintos > 2000:
            continue
        if float(valores.str.len().mean()) > 80:
            continue  # un comentario largo no es alguien a quien comparar
        if distintos == len(valores) and distintos > 60:
            continue  # un valor distinto por fila, y muchos: es un código o una descripción
        tipo = tipos.get(c, "")
        es_persona = c == nombre_completo or tipo == "employee" or bool(PERSONA_RE.search(str(c)))
        # El estado describe una situación, no a alguien: "Vencido contra
        # Cerrado" no es un cuadro comparativo.
        prioridad = 40 if tipo == "status" else PRIORIDAD_DIMENSION.get(tipo, 30)
        # A igual prioridad, la de menos valores: seis elementos se comparan
        # de un vistazo y trescientos no.
        candidatas.append((0 if es_persona else 1, prioridad, distintos, c))
    candidatas.sort(key=lambda x: x[:3])
    return [c for *_, c in candidatas]


def _estado(fila: dict, base: str, menos_es_mejor: bool) -> tuple[str, str]:
    """Veredicto en palabras y su tono (bueno / medio / malo)."""
    if base == "meta" and fila.get("cumplimiento") is not None:
        c = fila["cumplimiento"]
        if menos_es_mejor:
            if c <= 100:
                return "Dentro de la meta", "bueno"
            return ("Cerca de la meta", "medio") if c <= 110 else ("Por encima de la meta", "malo")
        if c >= 100:
            return "Cumple la meta", "bueno"
        return ("Cerca de la meta", "medio") if c >= CERCA_DE_META else ("Por debajo de la meta", "malo")
    d = fila.get("vs_promedio")
    if d is None or abs(d) < UMBRAL_PROMEDIO:
        return "En el promedio", "medio"
    arriba = d > 0
    if menos_es_mejor:
        return ("Por encima del promedio", "malo") if arriba else ("Por debajo del promedio", "bueno")
    return ("Por encima del promedio", "bueno") if arriba else ("Por debajo del promedio", "malo")


def _serie_por_periodo(grupo: pd.Series, valor: pd.Series, fechas: pd.Series, aditiva: bool):
    """Matriz mes × elemento. En una métrica que se suma, no aparecer un mes es un cero real."""
    x = pd.DataFrame({"_periodo": pd.to_datetime(fechas, errors="coerce"),
                      "_grupo": grupo, "_valor": valor}).dropna()
    if x.empty:
        return None
    x["_periodo"] = x["_periodo"].dt.to_period("M").dt.start_time
    tabla = x.pivot_table(index="_periodo", columns="_grupo", values="_valor",
                          aggfunc="sum" if aditiva else "mean").sort_index()
    return tabla.fillna(0) if aditiva else tabla


def cuadro_comparativo(df: pd.DataFrame, schema: dict, dimension: str, metrica=None,
                       seleccion: Optional[list] = None) -> Optional[dict]:
    """El cuadro de los elementos elegidos. None si no hay al menos dos que comparar."""
    if dimension not in df.columns or df.empty:
        return None
    conteo = metrica is None or metrica == METRICA_CONTEO or metrica not in df.columns
    metrica = METRICA_CONTEO if conteo else metrica

    grupo = _limpiar_grupo(df[dimension])
    valor = pd.Series(1.0, index=df.index) if conteo else numeric_series(df[metrica])
    datos = pd.DataFrame({"_grupo": grupo, "_valor": valor}).dropna()
    if datos["_grupo"].nunique() < 2:
        return None

    aditiva = conteo or _aditiva(schema, metrica)
    menos_es_mejor = (not conteo) and bool(PEOR_SI_SUBE.search(str(metrica)))
    agrupado = datos.groupby("_grupo")["_valor"]
    valores = agrupado.sum() if aditiva else agrupado.mean()
    registros = agrupado.size()

    # La meta, agregada igual que la métrica: sumada si la métrica se suma.
    meta_col = None if conteo else columna_meta(df, schema, metrica)
    metas = pd.Series(dtype=float)
    if meta_col is not None:
        m = pd.DataFrame({"_grupo": grupo, "_meta": pd.to_numeric(df[meta_col], errors="coerce")}).dropna()
        metas = (m.groupby("_grupo")["_meta"].sum() if aditiva else m.groupby("_grupo")["_meta"].mean())
        metas = metas[metas > 0]
    cumplimiento = (valores.reindex(metas.index) / metas * 100).replace([np.inf, -np.inf], np.nan).dropna()

    # Orden de TODOS los elementos, que es también el orden de la lista para
    # elegir. Con meta en al menos dos se ordena por cumplimiento; quien no
    # tiene meta queda al final en vez de desaparecer.
    usa_meta = len(cumplimiento) >= 2
    clave = cumplimiento.reindex(valores.index) if usa_meta else valores
    orden_todos = clave.sort_values(ascending=menos_es_mejor, na_position="last").index.tolist()

    elegidos = [n for n in (seleccion or []) if n in valores.index]
    if not seleccion:
        elegidos = orden_todos[:SUGERIDOS]
    elegidos = [n for n in orden_todos if n in set(elegidos)][:MAX_ELEGIDOS]
    if len(elegidos) < 2:
        return None

    base = "meta" if usa_meta and cumplimiento.reindex(elegidos).notna().sum() >= 2 else "valor"
    v = valores.reindex(elegidos)
    promedio = float(v.mean())
    suma = float(v.sum())

    # Movimiento del último mes frente al anterior, por elemento.
    periodos, tabla, parcial = [], None, False
    fechas = [d for d in schema.get("dates", []) if d in df.columns]
    if fechas:
        tabla = _serie_por_periodo(grupo, valor, df[fechas[0]], aditiva)
        if tabla is not None:
            tabla = tabla.reindex(columns=elegidos)
            # Un mes a medias hace parecer que todos cayeron: si el último
            # está incompleto, se compara el anterior contra el previo.
            parcial = len(tabla) >= 3 and _periodo_parcial(df, fechas[0])
            periodos = list(tabla.index)
    comparables = periodos[:-1] if parcial else periodos
    actual = comparables[-1] if len(comparables) >= 2 else None
    anterior = comparables[-2] if len(comparables) >= 2 else None

    filas = []
    for n in elegidos:
        val = float(valores[n])
        fila = {
            "nombre": str(n),
            "valor": val,
            "registros": int(registros[n]),
            "por_registro": val / int(registros[n]) if aditiva and int(registros[n]) else None,
            "participacion": (val / suma * 100) if aditiva and suma > 0 else None,
            "meta": float(metas[n]) if n in metas.index else None,
            "cumplimiento": float(cumplimiento[n]) if n in cumplimiento.index else None,
            "vs_promedio": ((val - promedio) / abs(promedio) * 100) if promedio else None,
            "variacion": None,
            "serie": {},
        }
        if tabla is not None and n in tabla.columns:
            serie = tabla[n]
            fila["serie"] = {p: float(x) for p, x in serie.items() if pd.notna(x)}
            if actual is not None:
                a, b = serie.get(anterior), serie.get(actual)
                if pd.notna(a) and pd.notna(b) and a != 0:
                    fila["variacion"] = float((b - a) / abs(a) * 100)
        fila["estado"], fila["tono"] = _estado(fila, base, menos_es_mejor)
        filas.append(fila)

    clave_orden = "cumplimiento" if base == "meta" else "valor"
    filas.sort(key=lambda f: (f[clave_orden] is None,
                              (f[clave_orden] or 0) if menos_es_mejor else -(f[clave_orden] or 0)))
    for i, f in enumerate(filas, 1):
        f["posicion"] = i

    resultado = {
        "dimension": dimension,
        "metrica": metrica,
        "conteo": conteo,
        "aditiva": aditiva,
        "menos_es_mejor": menos_es_mejor,
        "base": base,
        "meta_col": meta_col,
        "filas": filas,
        "opciones": [str(n) for n in orden_todos],
        "sugeridos": [str(n) for n in orden_todos[:SUGERIDOS]],
        "total_opciones": len(orden_todos),
        "promedio": promedio,
        "referencia": 100.0 if base == "meta" else promedio,
        "periodos": periodos,
        "periodo_label": _mes(actual) if actual is not None else None,
        "periodo_anterior_label": _mes(anterior) if anterior is not None else None,
        "parcial": bool(parcial),
        "aviso": None,
    }

    # Sin meta y con carteras de tamaño muy distinto, el total premia al que
    # atiende más. Se dice, sin cambiar el orden.
    r = registros.reindex(elegidos)
    if base == "valor" and aditiva and not conteo and int(r.min()) > 0 and r.max() / r.min() >= 2:
        resultado["aviso"] = (
            f"Ojo: no todos tienen el mismo volumen de registros (de {int(r.min()):,} a {int(r.max()):,}). "
            "El total también refleja cuánto atiende cada uno; mira el promedio por registro del cuadro "
            "antes de concluir quién lo hace mejor. Con una columna de meta la comparación sería directa.")
    resultado["lectura"] = lectura(resultado)
    return resultado


def _cifra(fila: dict, cuadro: dict) -> str:
    if cuadro["base"] == "meta" and fila.get("cumplimiento") is not None:
        return f"{fila['cumplimiento']:,.0f}% de su meta ({_fmt(fila['valor'])} de {_fmt(fila['meta'])})"
    return _fmt(fila["valor"]) + (" registros" if cuadro["conteo"] else "")


def lectura(cuadro: dict) -> list[str]:
    """Las conclusiones del cuadro, en frases con nombre y cifra."""
    filas = cuadro["filas"]
    n = len(filas)
    primero, ultimo = filas[0], filas[-1]
    frases = [f"**{primero['nombre']}** va primero con {_cifra(primero, cuadro)}.",
              f"**{ultimo['nombre']}** va último con {_cifra(ultimo, cuadro)}."]

    if cuadro["base"] == "meta":
        cumplen = [f["nombre"] for f in filas if f["tono"] == "bueno"]
        if not cumplen:
            frases.append(f"Ninguno de los {n} está dentro de su meta.")
        elif len(cumplen) == n:
            frases.append(f"Los {n} están dentro de su meta.")
        else:
            frases.append(f"{len(cumplen)} de {n} están dentro de su meta: {_lista(cumplen[:5])}"
                          + (" y otros." if len(cumplen) > 5 else "."))
    else:
        brecha = abs(primero["valor"] - ultimo["valor"])
        if brecha > 0:
            frases.append(f"Entre el primero y el último hay {_fmt(brecha)} de diferencia; "
                          f"el promedio de los {n} es {_fmt(cuadro['promedio'])}.")
        malos = [f["nombre"] for f in filas if f["tono"] == "malo"]
        if malos:
            lado = "por encima" if cuadro["menos_es_mejor"] else "por debajo"
            frases.append(f"{len(malos)} de {n} están {lado} del promedio en más de "
                          f"{UMBRAL_PROMEDIO:.0f}%: {_lista(malos[:5])}" + (" y otros." if len(malos) > 5 else "."))

    con_mov = [f for f in filas if f["variacion"] is not None]
    if con_mov and cuadro["periodo_label"]:
        sube = max(con_mov, key=lambda f: f["variacion"])
        baja = min(con_mov, key=lambda f: f["variacion"])
        partes = []
        if sube["variacion"] >= UMBRAL_MOVIMIENTO:
            partes.append(f"el que más subió fue **{sube['nombre']}** ({sube['variacion']:+.1f}%)")
        if baja["variacion"] <= -UMBRAL_MOVIMIENTO:
            partes.append(f"el que más bajó fue **{baja['nombre']}** ({baja['variacion']:+.1f}%)")
        if partes:
            frase = f"En {cuadro['periodo_label']} frente a {cuadro['periodo_anterior_label']}, " + " y ".join(partes) + "."
            frases.append(frase[0].upper() + frase[1:])
        else:
            frases.append(f"Nadie se movió más de {UMBRAL_MOVIMIENTO:.0f}% entre "
                          f"{cuadro['periodo_anterior_label']} y {cuadro['periodo_label']}.")

    lider = max(filas, key=lambda f: f["participacion"] or 0)
    if lider["participacion"] and lider["participacion"] >= 2 * 100 / n and n >= 3:
        frases.append(f"**{lider['nombre']}** concentra el {lider['participacion']:.0f}% de lo que suman los {n}.")
    return frases
