"""Todo lo que se puede decir de UNO, comparado con los demás.

El perfil individual mostraba gráficos y cifras del registro seleccionado,
pero dejaba la lectura al ojo de quien miraba: ahí estaban los números y
adelante. Este módulo hace la parte que faltaba —decir qué significan— y
produce las mismas observaciones con nombre, cifra y acción que el resto del
panel, pero acotadas a un solo punto de venta, asesor o cliente.

La regla de fondo es la misma que en `core/performance.py`: una observación
solo vale si está comparada contra algo. "Vendió 3.2M" no dice nada; "está en
el puesto 12 de 30 y por debajo de la mediana" sí. Todo lo de aquí compara
contra los pares, contra la meta o contra el propio pasado de la entidad.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .diagnostics import ESTADOS_MALOS, PEOR_SI_SUBE, _fmt, _lista, _mes, _sin_tildes


def _hallazgo(titulo, texto, implicacion, accion, evidencia, tipo, prioridad) -> dict:
    return {"title": titulo, "finding": texto, "implication": implicacion, "action": accion,
            "evidence": evidencia, "kind": tipo, "priority": prioridad, "confidence": "Alta"}


def _ordinal(puesto: int) -> str:
    return f"{puesto}.º"


def _posicion(df, schema, columna, valor, metrica) -> Optional[dict]:
    """En qué puesto está y contra qué se le está midiendo.

    Se apoya en la misma base justa del panel de desempeño: si hay meta, se
    compara cumplimiento; si no, valor por unidad o por registro. Nunca el
    total pelado, que solo diría que es grande o pequeño.
    """
    from .performance import base_comparativa, _semantic, ADDITIVE

    additive = _semantic(schema).get(metrica) in ADDITIVE
    base = base_comparativa(df, schema, columna, metrica, additive)
    if not base:
        return None
    nombres = [f["nombre"] for f in base["ranking"]]
    objetivo = str(valor)
    if objetivo not in nombres:
        return None
    puesto = nombres.index(objetivo) + 1
    total = len(nombres)
    fila = base["ranking"][puesto - 1]
    valores = [f["valor"] for f in base["ranking"]]
    mediana = float(np.median(valores))
    mejor = base["ranking"][0]
    encima = fila["valor"] >= mediana if not base.get("menos_es_mejor") else fila["valor"] <= mediana

    evidencia = [
        {"nombre": "Su resultado", "valor": fila["texto"], "detalle": fila["detalle"]},
        {"nombre": "Mediana del grupo", "valor": (f"{mediana:,.0f}%" if base["sufijo"] == "%" else _fmt(mediana)),
         "detalle": f"sobre {total} comparables"},
        {"nombre": f"Mejor: {mejor['nombre']}", "valor": mejor["texto"], "detalle": mejor["detalle"]},
    ]
    tercio = max(1, total // 3)
    if puesto <= tercio:
        tipo, lectura = "positive", "Está en el tercio superior de su grupo."
    elif puesto > total - tercio:
        tipo, lectura = "warning", "Está en el tercio inferior de su grupo."
    else:
        tipo, lectura = "info", "Está en la zona media de su grupo."
    return _hallazgo(
        f"Posición: {_ordinal(puesto)} de {total}",
        f"Medido por {base['etiqueta'].lower()}, queda {_ordinal(puesto)} de {total}. {lectura}",
        base["explicacion"],
        (f"Comparar sus prácticas con {mejor['nombre']}, que lidera el grupo con {mejor['texto']}."
         if not encima else
         f"Sostener el resultado y revisar qué se puede replicar hacia el resto del grupo."),
        evidencia, tipo, 0,
    )


def _evolucion(df, schema, columna, valor, metrica) -> Optional[dict]:
    """Cómo viene: subiendo, bajando, o cuántos periodos lleva cayendo."""
    fechas = [c for c in schema.get("dates", []) if c in df.columns]
    if not fechas or metrica not in df.columns:
        return None
    propio = df[df[columna].astype(str).str.strip() == str(valor)]
    if propio.empty:
        return None
    serie = pd.DataFrame({
        "_periodo": pd.to_datetime(propio[fechas[0]], errors="coerce"),
        "_valor": pd.to_numeric(propio[metrica], errors="coerce"),
    }).dropna()
    if serie.empty:
        return None
    serie["_periodo"] = serie["_periodo"].dt.to_period("M").dt.start_time
    por_periodo = serie.groupby("_periodo")["_valor"].sum().sort_index()
    if len(por_periodo) < 2:
        return None
    ultimo, previo = float(por_periodo.iloc[-1]), float(por_periodo.iloc[-2])
    if previo == 0:
        return None
    pct = (ultimo - previo) / abs(previo) * 100
    seguidos = 0
    valores = por_periodo.to_numpy(dtype="float64")
    for i in range(len(valores) - 1, 0, -1):
        if valores[i] < valores[i - 1]:
            seguidos += 1
        else:
            break
    evidencia = [
        {"nombre": _mes(por_periodo.index[-1]), "valor": _fmt(ultimo), "detalle": "último periodo"},
        {"nombre": _mes(por_periodo.index[-2]), "valor": _fmt(previo), "detalle": "periodo anterior"},
        {"nombre": "Mejor periodo", "valor": _fmt(float(por_periodo.max())),
         "detalle": _mes(por_periodo.idxmax())},
    ]
    if seguidos >= 2:
        return _hallazgo(
            "Viene cayendo", f"Lleva {seguidos} periodos seguidos a la baja: {pct:+.1f}% en el último.",
            "Dos o más periodos consecutivos ya no es ruido. Cuanto más tarde la revisión, más caro sale corregirla.",
            "Revisar qué cambió en el primer periodo de la caída: es donde está la causa, no en el último.",
            evidencia, "warning", 1)
    if abs(pct) < 1:
        return _hallazgo(
            "Estable", f"Se mantuvo estable frente al periodo anterior ({pct:+.1f}%).",
            "Sin cambio relevante: la atención puede ir a otro lado, pero conviene vigilar la dirección.",
            "Mantener el seguimiento y comparar contra el grupo, no solo contra sí mismo.",
            evidencia, "info", 2)
    return _hallazgo(
        "Mejoró" if pct > 0 else "Retrocedió",
        f"{'Subió' if pct > 0 else 'Bajó'} {abs(pct):.1f}% frente al periodo anterior.",
        ("Un buen periodo puede ser tendencia o casualidad; la diferencia está en si se repite."
         if pct > 0 else "Un retroceso de un periodo todavía se corrige antes de volverse tendencia."),
        ("Confirmar si el avance se sostiene el próximo periodo antes de dar el caso por resuelto."
         if pct > 0 else "Revisar qué pasó en este periodo mientras el dato está fresco."),
        evidencia, "positive" if pct > 0 else "warning", 1)


def _peso_en_el_total(df, schema, columna, valor, metrica) -> Optional[dict]:
    """Cuánto pesa en el conjunto: si se cae, cuánto se lleva por delante."""
    from .performance import _semantic, ADDITIVE

    if _semantic(schema).get(metrica) not in ADDITIVE or metrica not in df.columns:
        return None
    valores = pd.to_numeric(df[metrica], errors="coerce")
    grupos = df[columna].astype(str).str.strip()
    total = float(valores.sum())
    propio = float(valores[grupos == str(valor)].sum())
    if total <= 0 or propio <= 0:
        return None
    parte = propio / total * 100
    registros = int((grupos == str(valor)).sum())
    evidencia = [
        {"nombre": "Su aporte", "valor": _fmt(propio), "detalle": f"{parte:.1f}% del total"},
        {"nombre": "Total del archivo", "valor": _fmt(total), "detalle": f"{grupos.nunique():,} comparables"},
        {"nombre": "Registros propios", "valor": f"{registros:,}", "detalle": f"de {len(df):,} del archivo"},
    ]
    if parte >= 20:
        return _hallazgo(
            "Pesa mucho en el total", f"Aporta el {parte:.1f}% de todo el archivo.",
            "Una parte importante del resultado depende de este solo caso: si falla, se nota en el total.",
            "Tratarlo como cuenta crítica: seguimiento más frecuente y un plan de contingencia si se cae.",
            evidencia, "info", 3)
    return _hallazgo(
        "Peso en el total", f"Aporta el {parte:.1f}% del total, con {registros:,} registros.",
        "Sirve para dimensionar: una mejora aquí mueve el total en esa proporción, no más.",
        "Dimensionar cualquier meta que se le fije con este peso en mente.",
        evidencia, "info", 4)


def _estado_propio(df, schema, columna, valor) -> Optional[dict]:
    """Su tasa de registros en mal estado, comparada con la del resto."""
    fechas, ids = set(schema.get("dates", [])), set(schema.get("ids", []))
    mejor = None
    for c in df.columns:
        if c == columna or c in fechas or c in ids or str(c).startswith("_"):
            continue
        vals = df[c].dropna().astype(str).str.strip()
        vals = vals[vals.ne("")]
        if vals.empty or not 2 <= vals.nunique() <= 12:
            continue
        malos = {v for v in vals.unique() if _sin_tildes(v) in ESTADOS_MALOS}
        if not malos:
            continue
        proporcion = float(vals.isin(malos).mean())
        if 0.02 <= proporcion <= 0.95 and (mejor is None or proporcion > mejor[2]):
            mejor = (c, malos, proporcion)
    if mejor is None:
        return None
    col_estado, malos, tasa_global = mejor
    propio = df[df[columna].astype(str).str.strip() == str(valor)]
    if len(propio) < 3:
        return None
    marca = propio[col_estado].astype(str).str.strip().isin(malos)
    tasa = float(marca.mean())
    etiqueta = _lista(sorted(malos)[:2])
    evidencia = [
        {"nombre": "Su tasa", "valor": f"{tasa*100:.0f}%", "detalle": f"{int(marca.sum())} de {len(propio)}"},
        {"nombre": "Tasa del archivo", "valor": f"{tasa_global*100:.0f}%", "detalle": "todos los comparables"},
    ]
    peor = tasa > tasa_global * 1.2
    return _hallazgo(
        f"Estado «{etiqueta}»",
        (f"{tasa*100:.0f}% de sus registros quedaron en «{etiqueta}», frente al "
         f"{tasa_global*100:.0f}% del archivo."),
        ("Está por encima del promedio del archivo: el problema es suyo, no del proceso general."
         if peor else "Está en línea o por debajo del promedio del archivo."),
        (f"Revisar los casos en «{etiqueta}» de este registro antes de generalizar la causa."
         if peor else "Sin acción específica por este frente."),
        evidencia, "warning" if peor else "positive", 1 if peor else 4)


def _datos_incompletos(df, schema, columna, valor) -> Optional[dict]:
    """Qué le falta en sus propias filas, que es lo que invalida su lectura."""
    propio = df[df[columna].astype(str).str.strip() == str(valor)]
    if propio.empty:
        return None
    faltantes = []
    for c in propio.columns:
        if str(c).startswith("_") or c == columna:
            continue
        serie = propio[c]
        vacio = serie.isna()
        if serie.dtype == object:
            texto = serie.astype(str).str.strip()
            vacio = vacio | texto.eq("") | texto.str.lower().isin({"nan", "none", "null", "-"})
        tasa = float(vacio.mean())
        if tasa >= 0.3:
            faltantes.append((str(c), tasa, int(vacio.sum())))
    if not faltantes:
        return None
    faltantes.sort(key=lambda z: z[1], reverse=True)
    evidencia = [{"nombre": c, "valor": f"{t*100:.0f}% vacío", "detalle": f"{n} de {len(propio)}"}
                 for c, t, n in faltantes[:3]]
    return _hallazgo(
        "Datos incompletos en sus registros",
        f"{faltantes[0][0]} está vacía en el {faltantes[0][1]*100:.0f}% de sus filas"
        + (f", y hay {len(faltantes)-1} columna(s) más igual." if len(faltantes) > 1 else "."),
        "Cualquier corte que use esas columnas deja fuera estas filas sin avisar, así que su resultado real puede ser otro.",
        f"Completar {faltantes[0][0]} en los registros de este caso antes de tomar decisiones sobre él.",
        evidencia, "warning", 3)


def observaciones(df: pd.DataFrame, schema: dict, columna: str, valor,
                  metrica: Optional[str] = None) -> list[dict]:
    """Las lecturas de este registro, de la más urgente a la menos.

    Devuelve lista vacía cuando no hay nada que comparar. Es preferible a
    llenar la ficha de frases genéricas: quien abre un seguimiento quiere
    saber si este caso va bien o mal, no leer definiciones.
    """
    if df is None or df.empty or columna not in df.columns:
        return []
    if metrica not in df.columns:
        metricas = [m for m in (schema.get("metrics") or []) if m in df.columns]
        neutras = [m for m in metricas if not PEOR_SI_SUBE.search(str(m))]
        metrica = (neutras or metricas or [None])[0]

    salida = []
    pruebas = [(_estado_propio, (df, schema, columna, valor)),
               (_datos_incompletos, (df, schema, columna, valor))]
    if metrica:
        pruebas = [(_posicion, (df, schema, columna, valor, metrica)),
                   (_evolucion, (df, schema, columna, valor, metrica)),
                   (_peso_en_el_total, (df, schema, columna, valor, metrica))] + pruebas
    for fn, args in pruebas:
        try:
            encontrado = fn(*args)
        except Exception:
            encontrado = None
        if encontrado:
            salida.append(encontrado)
    salida.sort(key=lambda h: h.get("priority", 99))
    return salida
