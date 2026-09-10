"""Hallazgos con nombre propio: qué va mal, dónde, y cuánto vale.

Las alertas decían "se detectaron 164 observaciones atípicas". Es cierto y no
sirve para decidir nada: no dice qué punto de venta cayó, cuánto costó la
caída, ni por dónde empezar. Quien lee eso todavía tiene que ir a buscar los
datos a mano, que es justo lo que la herramienta debería ahorrarle.

Este módulo produce la otra mitad: el nombre, la cifra y el orden de
atención. Cada afirmación viene con su evidencia —la lista de nombres
concretos con su número—, y si no hay evidencia suficiente el hallazgo no se
emite. Preferimos callar antes que decir una generalidad.

Nada de esto asume un archivo concreto: la unidad de análisis (punto de
venta, ciudad, producto, asesor) se elige del propio archivo.
"""
from __future__ import annotations

import re
from typing import Optional

import numpy as np
import pandas as pd

ADITIVAS = {"revenue", "profit", "cost", "quantity", "discount", "tax"}

# Cuando el archivo no tiene ninguna columna numérica —una lista de tickets,
# de tareas, de asistencia— la métrica es contar filas. Sin esto, media
# herramienta se apagaba con esos archivos: no había nada que sumar, así que
# no había ningún hallazgo, aunque "este mes entraron 40% menos casos y tres
# responsables concentran los vencidos" sea exactamente lo que se necesita.
METRICA_CONTEO = "_registros"

# Estados que describen algo que salió mal. Se comparan sin tildes y en
# minúsculas, y la coincidencia es por palabra para que "cancelado" no se
# active con "no cancelado".
ESTADOS_MALOS = (
    "vencido", "vencida", "atrasado", "atrasada", "mora", "moroso", "pendiente",
    "cancelado", "cancelada", "anulado", "anulada", "rechazado", "rechazada",
    "inactivo", "inactiva", "suspendido", "suspendida", "bloqueado", "bloqueada",
    "error", "fallido", "fallida", "fallo", "devuelto", "devuelta", "perdido",
    "perdida", "agotado", "agotada", "sin stock", "incompleto", "incompleta",
    "ausente", "no", "retirado", "retirada", "abandonado", "churn", "overdue",
    "pending", "cancelled", "canceled", "rejected", "failed", "inactive",
    "blocked", "lost", "returned", "expired", "absent",
)

# Métricas donde el problema es tener MÁS, no menos: días de mora, quejas,
# devoluciones. Se reconocen por el nombre porque el tipo semántico no
# distingue "ventas" de "reclamos" — las dos son números que suben.
PEOR_SI_SUBE = re.compile(
    r"mora|atras|retras|demora|vencid|deuda|queja|reclamo|devoluc|error|falla|"
    r"fallo|incidenc|ausenc|rotaci|merma|perdid|reproces|cancelac|churn|"
    r"defect|complaint|overdue|delay|backlog|refund|return",
    re.I,
)
# Qué columna nombra mejor "quién" va mal. La geografía y la unidad comercial
# van primero porque son las que se pueden accionar; lo demás sirve pero
# describe menos una decisión.
PRIORIDAD_DIMENSION = {
    "city": 0, "region": 1, "zone": 2, "department": 3, "state": 4, "country": 5,
    "product": 10, "category": 11, "brand": 12, "segment": 13,
    "customer": 14, "employee": 15, "channel": 16,
    # El estado va al final: describe en QUÉ situación está algo, no QUIÉN
    # responde por ello. Como unidad de análisis diría "los Vencidos cayeron",
    # que no es una frase sobre la que nadie pueda actuar.
    "status": 40,
}


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v):
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
    # Con calificaciones y porcentajes, redondear a entero borra el hallazgo:
    # "3 frente a una mediana de 4" esconde que son 3,4 y 4,2.
    if v < 100 and v != int(v):
        return f"{signo}{v:,.1f}"
    return f"{signo}{v:,.0f}"


def _semantica(schema: dict) -> dict:
    return {x.get("column"): x.get("semantic_type") for x in schema.get("semantic", {}).get("columns", [])}


def _etiqueta(schema: dict, col) -> str:
    if col == METRICA_CONTEO:
        return "registros"
    for x in schema.get("semantic", {}).get("columns", []):
        if x.get("column") == col:
            return str(x.get("display_name") or col)
    return str(col)


def _aditiva(schema: dict, metrica) -> bool:
    """¿Sumar tiene sentido para esta métrica? Contar filas siempre lo tiene."""
    return metrica == METRICA_CONTEO or _semantica(schema).get(metrica) in ADITIVAS


def _en_prosa(schema: dict, col) -> str:
    """La métrica escrita dentro de una frase.

    Se pasa a minúsculas solo cuando el nombre viene del motor semántico
    ("Ingresos" → "ingresos"). Si es el encabezado crudo del Excel se
    respeta tal cual: "DiasMora" en minúsculas queda como "diasmora", que
    no es una palabra y hace que la frase parezca un error.
    """
    etiqueta = _etiqueta(schema, col)
    return etiqueta.lower() if etiqueta != str(col) or etiqueta.islower() else etiqueta


def _sin_tildes(texto) -> str:
    limpio = str(texto).strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u")):
        limpio = limpio.replace(a, b)
    return limpio


def _lista(nombres: list) -> str:
    """"A", "A y B", "A, B y C" — sin comas colgando."""
    nombres = [str(n) for n in nombres]
    if len(nombres) <= 1:
        return nombres[0] if nombres else ""
    return f"{', '.join(nombres[:-1])} y {nombres[-1]}"


def _conc(n: int, singular: str, plural: str) -> str:
    """Concordancia: "1 cayó" / "5 cayeron", sin frases con el número pegado."""
    return singular if n == 1 else plural


def _mes(periodo) -> str:
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    try:
        t = pd.Timestamp(periodo)
        return f"{meses[t.month - 1]} de {t.year}"
    except Exception:
        return str(periodo)[:10]


def dimension_operativa(df: pd.DataFrame, schema: dict, metrica=None) -> Optional[str]:
    """La mejor columna para nombrar quién va mal. Ver `dimensiones_candidatas`."""
    candidatas = dimensiones_candidatas(df, schema, metrica)
    return candidatas[0] if candidatas else None


def dimensiones_candidatas(df: pd.DataFrame, schema: dict, metrica=None) -> list[str]:
    """Todas las columnas que sirven para nombrar la unidad, de mejor a peor.

    Se devuelve la lista completa y no solo la primera porque a veces la más
    detallada no es la más útil: si el descenso está repartido entre 400
    puntos, abrirlo por ciudad o por zona dice algo y abrirlo por punto no.
    Quien llama decide con cuál se queda.

    No sirve cualquier columna de texto. Se descartan los identificadores (una
    fila por valor no agrupa nada) y las columnas con un solo valor. Se
    permite bastante más variedad que en otros módulos —cientos de puntos de
    venta son normales— pero se exige que cada valor aparezca varias veces:
    si cada fila es su propio grupo, comparar periodos no significa nada.
    """
    # Se unen las dos listas en vez de preferir una. Con `or`, un archivo cuyo
    # motor semántico reconocía "Estado" y "Prioridad" pero no "Responsable"
    # se quedaba sin ver al responsable, y terminaba diciendo cosas como "los
    # Vencidos cayeron 20%", que no es una frase sobre la que nadie actúe.
    dims = list(schema.get("semantic", {}).get("dimensions") or [])
    dims += [c for c in schema.get("categorical", []) if c not in dims]
    # También se miran las columnas que el clasificador dejó como "texto".
    # Ese cajón recoge todo lo que tiene demasiados valores distintos para
    # ser una categoría dibujable —justo donde caen los nombres de punto de
    # venta cuando hay cientos—, y sin esto el archivo que más necesita el
    # diagnóstico se quedaba sin ninguna unidad con la que nombrarlo.
    dims += [c for c in schema.get("text", []) if c not in dims]
    dims += [c for c in schema.get("geography", []) if c not in dims]
    fechas, ids = set(schema.get("dates", [])), set(schema.get("ids", []))
    metricas = set(schema.get("metrics", []))
    candidatas = []
    filas = len(df)
    for c in dims:
        if c not in df.columns or c in fechas or c in ids or c in metricas or c == metrica:
            continue
        if str(c).startswith("_"):
            continue
        valores = df[c].dropna().astype(str).str.strip().replace("", pd.NA).dropna()
        distintos = valores.nunique()
        if distintos < 2 or distintos > 2000:
            continue
        if filas / max(distintos, 1) < 3:  # cada valor debe repetirse varias veces
            continue
        if float(valores.str.len().mean()) > 80:
            continue  # un comentario largo no es la unidad de nadie
        tipo = _semantica(schema).get(c, "")
        candidatas.append((PRIORIDAD_DIMENSION.get(tipo, 30), -distintos, c))
    if not candidatas:
        return []
    # A igual prioridad gana la de más valores: describe el archivo con más
    # detalle y por tanto señala un responsable más concreto.
    candidatas.sort(key=lambda x: (x[0], x[1]))
    return [c for _, _, c in candidatas]


def _tabla_por_periodo(df, schema, dim, metrica, columna_fecha) -> Optional[pd.DataFrame]:
    """Matriz periodo × segmento con el valor de la métrica en cada celda."""
    x = pd.DataFrame({
        "_periodo": pd.to_datetime(df[columna_fecha], errors="coerce"),
        "_segmento": df[dim].astype(str).str.strip(),
        "_valor": pd.to_numeric(df[metrica], errors="coerce"),
    }).dropna(subset=["_periodo", "_valor"])
    x = x[x["_segmento"].ne("") & x["_segmento"].str.lower().ne("nan")]
    if x.empty:
        return None
    x["_periodo"] = x["_periodo"].dt.to_period("M").dt.start_time
    aditiva = _aditiva(schema, metrica)
    tabla = x.pivot_table(index="_periodo", columns="_segmento", values="_valor",
                          aggfunc="sum" if aditiva else "mean")
    tabla = tabla.sort_index()
    # En una métrica que se suma, "no aparece" significa "no hubo actividad",
    # que es un cero real y una señal importante. En un precio o una
    # calificación, en cambio, la ausencia no es un cero: es que no se midió.
    return tabla.fillna(0) if aditiva else tabla


def _periodo_parcial(df, columna_fecha, periodo=None) -> bool:
    """¿El último periodo está a medias? Si lo está, todo parece caer.

    No se compara contra el fin de mes del calendario: hay archivos que
    simplemente no registran los últimos días y saldrían marcados como
    incompletos todos los meses. Se compara contra el propio archivo — hasta
    qué día suele llegar cada mes — que es la única referencia honesta.
    """
    try:
        fechas = pd.to_datetime(df[columna_fecha], errors="coerce").dropna()
        if fechas.empty:
            return False
        ultimo_dia = fechas.groupby(fechas.dt.to_period("M")).max().dt.day
        if len(ultimo_dia) < 2:
            return False  # sin historia con qué comparar, no se afirma nada
        tipico = float(ultimo_dia.iloc[:-1].median())
        return bool(float(ultimo_dia.iloc[-1]) < tipico - 5)
    except Exception:
        return False


def _hallazgo(titulo, texto, implicacion, accion, evidencia, tipo, prioridad,
              confianza="Alta", objetivo=None) -> dict:
    return {
        "title": titulo, "finding": texto, "implication": implicacion,
        "action": accion, "evidence": evidencia, "kind": tipo,
        "priority": prioridad, "confidence": confianza,
        "target": objetivo or {},
    }


def _caida_por_segmento(df, schema, dim, metrica, columna_fecha, tabla) -> Optional[dict]:
    if tabla is None or len(tabla) < 2:
        return None
    ultimo, previo = tabla.iloc[-1], tabla.iloc[-2]
    activos = previo[previo > 0].index
    if not len(activos):
        return None
    delta = (ultimo - previo).reindex(activos).dropna()
    caidas = delta[delta < 0].sort_values()
    if caidas.empty:
        return None
    total_caida = float(caidas.sum())
    top = caidas.head(3)
    peso = float(top.sum() / total_caida * 100) if total_caida else 0
    etiqueta_m = _en_prosa(schema, metrica)
    parcial = _periodo_parcial(df, columna_fecha, tabla.index[-1])

    evidencia = []
    for nombre, valor in top.items():
        base = float(previo[nombre])
        pct = valor / base * 100 if base else 0
        evidencia.append({"nombre": str(nombre), "valor": _fmt(valor), "detalle": f"{pct:+.0f}% · antes {_fmt(base)}"})

    cambio_total = float(ultimo.sum() - previo.sum())
    if peso < 25 and len(caidas) > 5:
        # La caída está repartida. Nombrar tres es dar una pista falsa: aquí
        # el hallazgo es justamente que no hay culpables concretos, y eso
        # cambia la decisión (se revisa el proceso, no el punto).
        return _hallazgo(
            "Caída generalizada",
            (f"{len(caidas)} de {len(activos)} cayeron frente a {_mes(tabla.index[-2])} en {etiqueta_m}, "
             f"y ninguno explica más del {abs(float(caidas.iloc[0] / total_caida * 100)):.0f}% del retroceso."),
            "La caída no viene de unos pocos casos, está repartida. Perseguir nombres uno por uno no la va a corregir.",
            "Buscar la causa común —periodo, precio, disponibilidad, un cambio de proceso— antes de fijar metas individuales.",
            evidencia, "warning", 0, "Media" if parcial else "Alta",
            {"dimension": dim, "metric": metrica, "view": "evolución reciente"},
        )
    if cambio_total < 0:
        texto = (f"{_lista([e['nombre'] for e in evidencia])} "
                 f"{_conc(len(evidencia), 'explica', 'explican')} el {peso:.0f}% de la caída "
                 f"de {etiqueta_m} frente a {_mes(tabla.index[-2])}.")
        implicacion = (f"La caída no está repartida: {len(caidas)} de {len(activos)} "
                       f"{_conc(len(caidas), 'bajó', 'bajaron')}, y la mayor parte del daño viene de "
                       f"unos pocos. Una medida general no ataca el problema.")
    else:
        texto = (f"El total subió, pero {len(caidas)} de {len(activos)} "
                 f"{_conc(len(caidas), 'cayó', 'cayeron')}. "
                 f"{_conc(len(evidencia), 'El mayor retroceso es', 'Los mayores retrocesos son')} "
                 f"{_lista([e['nombre'] for e in evidencia])}.")
        implicacion = ("El crecimiento global está tapando retrocesos concretos. Sin abrir por segmento, "
                       "estos casos no aparecen en ningún indicador.")
    if parcial:
        texto += " Ojo: el último periodo parece incompleto, así que parte de la caída puede ser solo eso."

    peor = str(top.index[0])
    return _hallazgo(
        "Dónde se concentra la caída", texto, implicacion,
        f"Empezar por {peor}: es el mayor retroceso en cifras absolutas. Abrir su detalle y confirmar si es operación, precio o registro.",
        evidencia, "warning", 0, "Media" if parcial else "Alta",
        {"dimension": dim, "metric": metrica, "filter_column": dim, "filter_value": peor,
         "view": f"{_etiqueta(schema, dim)}: {peor}"},
    )


def _deterioro_sostenido(df, schema, dim, metrica, tabla) -> Optional[dict]:
    if tabla is None or len(tabla) < 3:
        return None
    ventana = tabla.iloc[-3:]
    # Con cientos de segmentos, unos cuantos bajan tres veces seguidas por
    # puro azar. Se exige que el segmento pese algo —al menos lo que pesa el
    # segmento típico— para no llenar la alerta de casos irrelevantes que
    # además le quitan credibilidad a los que sí importan.
    piso = float(ventana.iloc[0].median())
    sostenidas = []
    for nombre in ventana.columns:
        v0, v1, v2 = [float(x) for x in ventana[nombre].tolist()]
        # v2 > 0 a propósito: quien terminó en cero no está deteriorándose,
        # se fue. De ese caso habla "Dejaron de registrar", y repetirlo aquí
        # llenaría el panel de tres alertas sobre el mismo nombre.
        if v0 <= 0 or v2 <= 0 or v0 < piso or not (v0 > v1 > v2):
            continue
        pct = (v2 - v0) / v0 * 100
        if pct <= -25:
            sostenidas.append((nombre, v0, v2, pct))
    if not sostenidas:
        return None
    if len(sostenidas) > max(3, len(ventana.columns) * 0.1):
        return None  # si le pasa a tantos, no es una señal sobre nadie en particular
    sostenidas.sort(key=lambda z: z[1] - z[2], reverse=True)
    top = sostenidas[:3]
    evidencia = [{"nombre": str(n), "valor": f"{_fmt(v0)} → {_fmt(v2)}", "detalle": f"{pct:+.0f}% en 3 periodos"}
                 for n, v0, v2, pct in top]
    etiqueta_m = _en_prosa(schema, metrica)
    peor = str(top[0][0])
    return _hallazgo(
        "Deterioro sostenido",
        (f"{_lista([e['nombre'] for e in evidencia])} "
         f"{_conc(len(evidencia), 'lleva', 'llevan')} tres periodos seguidos a la baja en {etiqueta_m}."),
        "Tres periodos consecutivos ya no es ruido: es una tendencia. Cuanto más tarde la revisión, más caro sale corregirla.",
        f"Revisar {peor} primero y decidir si se interviene o se acepta la salida. Una caída sostenida rara vez se corrige sola.",
        evidencia, "warning", 1,
        objetivo={"dimension": dim, "metric": metrica, "filter_column": dim, "filter_value": peor,
                  "view": f"{_etiqueta(schema, dim)}: {peor}"},
    )


def _dejaron_de_registrar(df, schema, dim, metrica, columna_fecha, tabla) -> Optional[dict]:
    if tabla is None or len(tabla) < 2:
        return None
    if not _aditiva(schema, metrica):
        return None  # en un promedio, "no aparece" no significa "dejó de operar"
    ultimo, previo = tabla.iloc[-1], tabla.iloc[-2]
    inactivos = previo[(previo > 0) & (ultimo <= 0)].sort_values(ascending=False)
    if inactivos.empty:
        return None
    if _periodo_parcial(df, columna_fecha, tabla.index[-1]):
        return None  # con el mes a medias, media base parecería inactiva
    total = float(inactivos.sum())
    top = inactivos.head(3)
    evidencia = [{"nombre": str(n), "valor": _fmt(v), "detalle": f"su aporte en {_mes(tabla.index[-2])}"}
                 for n, v in top.items()]
    etiqueta_m = _en_prosa(schema, metrica)
    if len(inactivos) == 1:
        texto = (f"{top.index[0]} registró en {_mes(tabla.index[-2])} y no tiene ninguna actividad en "
                 f"{_mes(tabla.index[-1])}. Aportaba {_fmt(total)} de {etiqueta_m}.")
    else:
        texto = (f"{len(inactivos)} que sí registraron en {_mes(tabla.index[-2])} no tienen actividad en "
                 f"{_mes(tabla.index[-1])}. Sumaban {_fmt(total)} de {etiqueta_m}.")
    return _hallazgo(
        "Dejaron de registrar", texto,
        "Una ausencia total no es una caída: o dejaron de operar, o dejaron de reportar. Las dos cosas requieren acción, pero distinta.",
        f"Confirmar con {_lista([e['nombre'] for e in evidencia])} si es cierre, pausa o un problema de captura de datos.",
        evidencia, "warning", 1,
        objetivo={"dimension": dim, "metric": metrica, "filter_column": dim,
                  "filter_value": str(top.index[0]), "view": f"{_etiqueta(schema, dim)}: {top.index[0]}"},
    )


def _rezago_frente_a_la_mediana(df, schema, dim, metrica) -> Optional[dict]:
    aditiva = _aditiva(schema, metrica)
    x = pd.DataFrame({
        "_segmento": df[dim].astype(str).str.strip(),
        "_valor": pd.to_numeric(df[metrica], errors="coerce"),
    }).dropna()
    x = x[x["_segmento"].ne("") & x["_segmento"].str.lower().ne("nan")]
    if x.empty:
        return None
    g = x.groupby("_segmento")["_valor"].sum() if aditiva else x.groupby("_segmento")["_valor"].mean()
    g = g.replace([np.inf, -np.inf], np.nan).dropna()
    if len(g) < 4:
        return None
    mediana = float(g.median())
    if mediana <= 0:
        return None
    etiqueta_m = _en_prosa(schema, metrica)
    if aditiva:
        # En un total, la mitad de la mediana es un corte razonable: los
        # tamaños de segmento varían mucho y esa distancia sí es anómala.
        rezagados = g[g < mediana * 0.5].sort_values()
        if len(rezagados) < 2:
            return None
        brecha = float((mediana - rezagados).sum())
        # Solo vale la pena decirlo si cerrar la brecha mueve el resultado.
        # "2 de 1200 están rezagados" es cierto y no cambia ninguna decisión.
        if brecha < float(g.sum()) * 0.05:
            return None
        texto = (f"{len(rezagados)} de {len(g)} están por debajo de la mitad de la mediana ({_fmt(mediana)}) "
                 f"en {etiqueta_m}. Llevarlos a la mediana valdría {_fmt(brecha)}.")
    else:
        # En un promedio —una calificación, un precio, un porcentaje— pedir la
        # mitad de la mediana no detecta nada: nadie califica 2 cuando el
        # resto califica 4,2. El corte se toma de la dispersión real entre
        # segmentos, así que se adapta a la escala de cada archivo.
        q1, q3 = g.quantile([0.25, 0.75])
        corte = float(mediana - 1.5 * (q3 - q1))
        if not np.isfinite(corte) or corte <= float(g.min()) - 1e-9:
            return None
        rezagados = g[g < corte].sort_values()
        if rezagados.empty:
            return None
        texto = (f"{_lista([str(n) for n in rezagados.head(3).index])} "
                 f"{_conc(len(rezagados), 'queda', 'quedan')} claramente por debajo del resto en "
                 f"{etiqueta_m}: {_fmt(rezagados.iloc[0])} frente a una mediana de {_fmt(mediana)}.")
    peores = rezagados.head(3)
    evidencia = [{"nombre": str(n), "valor": _fmt(v), "detalle": f"{v/mediana*100:.0f}% de la mediana"}
                 for n, v in peores.items()]
    return _hallazgo(
        "Rezago frente a la mediana", texto,
        "La distancia se mide contra la mediana y no contra el promedio a propósito: el promedio lo mueve el líder y hace parecer rezagado a medio archivo.",
        f"Mirar qué tienen en común {_lista([e['nombre'] for e in evidencia])} antes de fijarles meta: puede ser tamaño, zona o surtido, y no desempeño.",
        evidencia, "warning", 2,
        objetivo={"dimension": dim, "metric": metrica, "filter_column": dim,
                  "filter_value": str(peores.index[0]), "view": f"{_etiqueta(schema, dim)}: {peores.index[0]}"},
    )


def _concentracion(df, schema, dim, metrica) -> Optional[dict]:
    if not _aditiva(schema, metrica):
        return None
    x = pd.DataFrame({
        "_segmento": df[dim].astype(str).str.strip(),
        "_valor": pd.to_numeric(df[metrica], errors="coerce"),
    }).dropna()
    x = x[x["_segmento"].ne("")]
    g = x.groupby("_segmento")["_valor"].sum().sort_values(ascending=False)
    g = g[g > 0]
    if len(g) < 5:
        return None
    total = float(g.sum())
    if total <= 0:
        return None
    acumulado = (g.cumsum() / total)
    cuantos = int((acumulado < 0.8).sum()) + 1
    if cuantos > len(g) * 0.3:
        return None
    top = g.head(3)
    evidencia = [{"nombre": str(n), "valor": _fmt(v), "detalle": f"{v/total*100:.1f}% del total"}
                 for n, v in top.items()]
    etiqueta_m = _en_prosa(schema, metrica)
    return _hallazgo(
        "Concentración de riesgo",
        f"{cuantos} de {len(g)} concentran el 80% de {etiqueta_m}. El primero solo, {top.iloc[0]/total*100:.1f}%.",
        "Es una fortaleza y una exposición al mismo tiempo: perder uno de esos pocos mueve el resultado completo.",
        f"Verificar qué tan estable es la relación con {_lista([e['nombre'] for e in evidencia])} y qué pasaría si uno se cae.",
        evidencia, "info", 3,
        objetivo={"dimension": dim, "metric": metrica, "filter_column": dim,
                  "filter_value": str(top.index[0]), "view": f"{_etiqueta(schema, dim)}: {top.index[0]}"},
    )


def _columna_de_estado(df, schema, dim) -> Optional[tuple]:
    """Una columna de estado y cuáles de sus valores describen algo mal.

    Sirve para los archivos que no tienen nada que sumar: tickets, tareas,
    asistencia, cartera. Ahí el problema no es un número que baja, es una
    fila que dice "Vencido".
    """
    candidatas = list(schema.get("categorical", [])) + list(schema.get("semantic", {}).get("dimensions", []))
    mejor = None
    for c in dict.fromkeys(candidatas):
        if c not in df.columns or c == dim or str(c).startswith("_"):
            continue
        valores = df[c].dropna().astype(str).str.strip()
        valores = valores[valores.ne("")]
        if valores.empty or valores.nunique() > 12:
            continue
        malos = {v for v in valores.unique() if _sin_tildes(v) in ESTADOS_MALOS}
        if not malos:
            continue
        proporcion = float(valores.isin(malos).mean())
        if proporcion < 0.05 or proporcion > 0.9:
            continue  # ni anecdótico ni la norma del archivo
        if mejor is None or proporcion > mejor[2]:
            mejor = (c, malos, proporcion)
    return mejor


def _estados_problematicos(df, schema, dim) -> Optional[dict]:
    hallado = _columna_de_estado(df, schema, dim)
    if hallado is None:
        return None
    columna, malos, proporcion = hallado
    valores = df[columna].astype(str).str.strip()
    marca = valores.isin(malos)
    afectadas = int(marca.sum())
    if afectadas < 3:
        return None
    ordenados = sorted(malos)
    etiquetas = _lista(ordenados)
    # Con muchos estados distintos el título se vuelve una lista larga que no
    # cabe ni se lee; el detalle sigue en el texto del hallazgo.
    titulo = f"Estado {etiquetas}: quién concentra" if len(ordenados) <= 2 else "Estados con problema: quién concentra"

    evidencia = []
    peor = None
    if dim and dim in df.columns:
        base = pd.DataFrame({"_segmento": df[dim].astype(str).str.strip(), "_malo": marca})
        base = base[base["_segmento"].ne("")]
        resumen = base.groupby("_segmento")["_malo"].agg(["sum", "count", "mean"])
        # Se compara la TASA, no el total: el segmento más grande siempre
        # tendría más casos, y señalarlo por tamaño no es un hallazgo.
        resumen = resumen[resumen["count"] >= max(5, len(df) * 0.01)]
        resumen = resumen.sort_values("mean", ascending=False)
        if len(resumen) >= 2:
            for nombre, fila in resumen.head(3).iterrows():
                evidencia.append({"nombre": str(nombre), "valor": f"{fila['mean']*100:.0f}%",
                                  "detalle": f"{int(fila['sum'])} de {int(fila['count'])}"})
            peor = str(resumen.index[0])

    texto = f"{afectadas:,} de {len(df):,} registros están en estado {etiquetas} ({proporcion*100:.0f}%)."
    if peor:
        texto += f" La tasa más alta es {peor}, con {resumen.iloc[0]['mean']*100:.0f}%."
    return _hallazgo(
        titulo, texto,
        "El promedio del archivo esconde a quién le pasa: la tasa por responsable dice si es un problema general o de unos pocos.",
        (f"Revisar {peor} primero: tiene la tasa más alta, no solo más casos."
         if peor else f"Revisar los registros en estado {etiquetas} y confirmar si es un problema de proceso o de registro."),
        evidencia, "warning", 1,
        objetivo=({"dimension": dim, "filter_column": dim, "filter_value": peor,
                   "view": f"{_etiqueta(schema, dim)}: {peor}"} if peor else {"view": "datos"}),
    )


def _exceso_en_metrica_negativa(df, schema, dim) -> Optional[dict]:
    """Quién está peor en una métrica donde subir es malo (mora, quejas)."""
    if not dim or dim not in df.columns:
        return None
    candidatas = [c for c in schema.get("metrics", []) if c in df.columns and PEOR_SI_SUBE.search(str(c))]
    if not candidatas:
        return None
    metrica = candidatas[0]
    x = pd.DataFrame({
        "_segmento": df[dim].astype(str).str.strip(),
        "_valor": pd.to_numeric(df[metrica], errors="coerce"),
    }).dropna()
    x = x[x["_segmento"].ne("")]
    if x.empty:
        return None
    resumen = x.groupby("_segmento")["_valor"].agg(["mean", "count"])
    resumen = resumen[resumen["count"] >= max(3, len(x) * 0.01)]
    if len(resumen) < 4:
        return None
    tipico = float(resumen["mean"].median())
    if tipico <= 0:
        return None
    resumen = resumen.sort_values("mean", ascending=False)
    if float(resumen.iloc[0]["mean"]) < tipico * 1.5:
        return None  # nadie se sale realmente de la norma
    evidencia = [{"nombre": str(n), "valor": _fmt(f["mean"]),
                  "detalle": f"{f['mean']/tipico:.1f}× lo normal · {int(f['count'])} registros"}
                 for n, f in resumen.head(3).iterrows()]
    etiqueta_m = _en_prosa(schema, metrica)
    peor = str(resumen.index[0])
    return _hallazgo(
        f"Exceso en {etiqueta_m}",
        (f"{peor} promedia {_fmt(resumen.iloc[0]['mean'])} en {etiqueta_m}, "
         f"{resumen.iloc[0]['mean']/tipico:.1f} veces lo normal del archivo ({_fmt(tipico)})."),
        "En esta métrica el problema es tener más, no menos. La comparación es contra la mediana del resto, no contra una meta inventada.",
        f"Empezar por {peor}: es donde una corrección tiene más recorrido.",
        evidencia, "warning", 1,
        objetivo={"dimension": dim, "metric": metrica, "filter_column": dim, "filter_value": peor,
                  "view": f"{_etiqueta(schema, dim)}: {peor}"},
    )


def _en_cero(df, schema, dim, metrica) -> Optional[dict]:
    """Filas en cero: sin stock, sin venta, sin horas. Un cero es una decisión."""
    # Se excluyen las métricas donde el cero es un valor legítimo de la escala
    # —una calificación de 0, una edad, un porcentaje— y no una ausencia.
    if metrica == METRICA_CONTEO or _semantica(schema).get(metrica) in {"rating", "percentage", "age"}:
        return None
    valores = pd.to_numeric(df[metrica], errors="coerce")
    validos = valores.dropna()
    if len(validos) < 10:
        return None
    en_cero = validos.eq(0)
    proporcion = float(en_cero.mean())
    if proporcion < 0.1 or proporcion > 0.9:
        return None
    etiqueta_m = _en_prosa(schema, metrica)
    evidencia = []
    peor = None
    if dim and dim in df.columns:
        base = pd.DataFrame({"_segmento": df[dim].astype(str).str.strip(), "_cero": valores.eq(0)}).dropna()
        base = base[base["_segmento"].ne("")]
        resumen = base.groupby("_segmento")["_cero"].agg(["sum", "count", "mean"])
        resumen = resumen[(resumen["count"] >= 3) & (resumen["sum"] > 0)].sort_values("mean", ascending=False)
        if len(resumen) >= 2:
            evidencia = [{"nombre": str(n), "valor": f"{f['mean']*100:.0f}% en cero",
                          "detalle": f"{int(f['sum'])} de {int(f['count'])}"}
                         for n, f in resumen.head(3).iterrows()]
            peor = str(resumen.index[0])
    return _hallazgo(
        f"Registros en cero · {etiqueta_m}",
        (f"{int(en_cero.sum()):,} de {len(validos):,} registros tienen {etiqueta_m} en cero ({proporcion*100:.0f}%)."
         + (f" El caso más marcado es {peor}." if peor else "")),
        "Un cero no es un valor bajo, es una ausencia: agotado, sin operación o sin registrar. Mezclado con el resto, arrastra hacia abajo cualquier promedio.",
        (f"Separar los ceros del análisis y confirmar en {peor} si son reales o falta el dato."
         if peor else "Separar los ceros del análisis y confirmar si son reales o falta el dato."),
        evidencia, "warning", 3,
        objetivo=({"dimension": dim, "metric": metrica, "filter_column": dim, "filter_value": peor,
                   "view": f"{_etiqueta(schema, dim)}: {peor}"} if peor else {"view": "datos"}),
    )


def _columnas_incompletas(df, schema, dim) -> Optional[dict]:
    """Qué columna está vacía y en qué medida eso invalida el análisis."""
    if not len(df):
        return None
    faltantes = []
    for c in df.columns:
        if str(c).startswith("_") or str(c).startswith("__"):
            continue
        serie = df[c]
        vacio = serie.isna()
        if serie.dtype == object:
            texto = serie.astype(str).str.strip()
            vacio = vacio | texto.eq("") | texto.str.lower().isin({"nan", "none", "null", "-"})
        tasa = float(vacio.mean())
        if tasa >= 0.2:
            faltantes.append((c, tasa, int(vacio.sum())))
    if not faltantes:
        return None
    faltantes.sort(key=lambda z: z[1], reverse=True)
    evidencia = [{"nombre": _etiqueta(schema, c), "valor": f"{tasa*100:.0f}% vacío",
                  "detalle": f"{n:,} de {len(df):,} registros"} for c, tasa, n in faltantes[:3]]
    peor_col, peor_tasa, _ = faltantes[0]
    return _hallazgo(
        "Datos que faltan",
        (f"{_etiqueta(schema, peor_col)} está vacía en el {peor_tasa*100:.0f}% de los registros"
         + (f", y hay {len(faltantes) - 1} columna(s) más en la misma situación." if len(faltantes) > 1 else ".")),
        "Todo corte o ranking que use esa columna deja fuera esas filas sin avisar, así que el total por segmento no cuadra con el total del archivo.",
        f"Decidir qué hacer con las filas sin {_etiqueta(schema, peor_col)}: completarlas, excluirlas o reportarlas aparte. Lo que no funciona es ignorarlas.",
        evidencia, "warning", 5,
        objetivo={"view": "calidad"},
    )


def _identificador_repetido(df, schema) -> Optional[dict]:
    """Un identificador que se repite: un cruce mal hecho o un pegado doble.

    No se buscan filas idénticas sin más. En un archivo de pocas columnas
    —sede, asesor, calificación— dos filas iguales aparecen solas y no son
    ningún error; avisarlo sería ruido. En cambio, un número de factura o un
    código de producto repetido no tiene lectura inocente, y ahí sí el total
    de arriba está contando dos veces lo mismo.
    """
    if len(df) < 20:
        return None
    candidatas = [c for c in schema.get("ids", []) if c in df.columns]
    # También sirve cualquier columna que sea casi un identificador de hecho,
    # aunque el encabezado no lo diga.
    for c in df.columns:
        if str(c).startswith("_") or c in candidatas or c in set(schema.get("dates", [])):
            continue
        serie = df[c].dropna()
        if len(serie) >= len(df) * 0.9 and serie.nunique() >= len(serie) * 0.9:
            candidatas.append(c)
    for columna in candidatas:
        valores = df[columna].dropna().astype(str).str.strip()
        valores = valores[valores.ne("")]
        if len(valores) < len(df) * 0.9:
            continue
        repetidos = valores[valores.duplicated(keep=False)]
        if repetidos.empty:
            continue
        conteo = repetidos.value_counts()
        sobrantes = int(len(repetidos) - conteo.size)
        if sobrantes < 3 or sobrantes / len(df) < 0.01:
            continue
        evidencia = [{"nombre": str(v), "valor": f"{int(n)} veces", "detalle": "debería aparecer una vez"}
                     for v, n in conteo.head(3).items()]
        return _hallazgo(
            "Identificador repetido",
            (f"{_etiqueta(schema, columna)} se repite: {conteo.size:,} valores aparecen más de una vez, "
             f"{sobrantes:,} filas de más ({sobrantes/len(df)*100:.1f}% del archivo)."),
            "Un identificador repetido cuenta dos veces lo mismo: infla totales, rankings y participaciones sin que se note en ningún indicador.",
            "Confirmar si es un cruce repetido o si el identificador no es único de verdad. Si es lo primero, todos los totales están sobreestimados.",
            evidencia, "warning", 2,
            objetivo={"view": "calidad"},
        )
    return None


def _atipicos_con_nombre(df, schema, dim, anomalias) -> Optional[dict]:
    if anomalias is None or not len(anomalias):
        return None
    a = anomalias[anomalias["tipo"].astype(str).str.contains("Outlier", na=False)]
    if a.empty:
        return None
    filas = pd.to_numeric(a["fila"], errors="coerce").dropna().astype(int)
    filas = [i for i in filas if i in df.index]
    # Un solo valor atípico no es un hallazgo, es una fila. Con menos de tres
    # no hay nada que priorizar y la alerta ocupa un lugar que le hace falta
    # a otra que sí cambia una decisión.
    if len(filas) < 3:
        return None

    columna = str(a["columna"].value_counts().index[0])
    evidencia, texto_donde = [], ""
    if dim and dim in df.columns:
        nombres = df.loc[filas, dim].astype(str).str.strip()
        conteo = nombres.value_counts()
        top = conteo.head(3)
        concentracion = float(top.sum() / len(filas) * 100)
        evidencia = [{"nombre": str(n), "valor": f"{int(v)} casos", "detalle": f"{v/len(filas)*100:.0f}% de los atípicos"}
                     for n, v in top.items()]
        if concentracion >= 40:
            texto_donde = f" El {concentracion:.0f}% está en {_lista([e['nombre'] for e in evidencia])}."

    detalle_mayor = ""
    if columna in df.columns:
        valores = pd.to_numeric(df.loc[filas, columna], errors="coerce").dropna()
        base = pd.to_numeric(df[columna], errors="coerce").dropna()
        if len(valores) and len(base) and float(base.median()) > 0:
            idx = valores.abs().idxmax()
            mayor, mediana = float(valores.loc[idx]), float(base.median())
            quien = f" en {df.loc[idx, dim]}" if dim and dim in df.columns else ""
            # Un atípico puede estar muy por DEBAJO de la mediana. Decir
            # "0 veces la mediana" ahí era literalmente falso; la distancia se
            # expresa en la dirección en la que de verdad está.
            if abs(mayor) >= mediana:
                relacion = f"{abs(mayor)/mediana:.0f} veces la mediana"
                corto = f"{abs(mayor)/mediana:.0f}× la mediana"
            else:
                relacion = f"{mediana/max(abs(mayor), 1e-9):.0f} veces por debajo de la mediana"
                corto = f"{mediana/max(abs(mayor), 1e-9):.0f}× por debajo"
            detalle_mayor = f" El más extremo es {_fmt(mayor)}{quien}, {relacion} de la columna."
            evidencia.append({"nombre": "Valor más extremo", "valor": _fmt(mayor),
                              "detalle": f"{corto}{quien}"})

    return _hallazgo(
        "Valores atípicos: dónde están",
        f"{len(filas):,} valores atípicos en {_etiqueta(schema, columna)}.{texto_donde}{detalle_mayor}",
        "Si son errores de captura, están inflando promedios y rankings. Si son reales, son los casos que más enseñan. Lo que no se puede es dejarlos sin clasificar.",
        ("Revisar primero los pocos registros que concentran los atípicos: es donde una corrección cambia más el resultado."
         if evidencia else "Revisar los registros de mayor valor y confirmar si son eventos reales o errores de captura."),
        evidencia, "warning", 4,
        objetivo={"view": "anomalías"},
    )


def _errores_de_captura(df, schema, anomalias) -> Optional[dict]:
    """Negativos donde no deberían existir y fechas ilegibles: errores duros."""
    if anomalias is None or not len(anomalias):
        return None
    tipos = anomalias["tipo"].astype(str)
    negativos = anomalias[tipos.str.contains("negativo", case=False, na=False)]
    fechas = anomalias[tipos.str.contains("Fecha", case=False, na=False)]
    evidencia = []
    partes = []
    if len(negativos):
        por_columna = negativos["columna"].value_counts()
        partes.append(f"{len(negativos):,} valores negativos")
        evidencia += [{"nombre": _etiqueta(schema, c), "valor": f"{int(v)} negativos",
                       "detalle": "revisar signo o devoluciones"} for c, v in por_columna.head(2).items()]
    if len(fechas):
        por_columna = fechas["columna"].value_counts()
        partes.append(f"{len(fechas):,} fechas ilegibles")
        evidencia += [{"nombre": _etiqueta(schema, c), "valor": f"{int(v)} sin fecha",
                       "detalle": "esas filas no entran en ninguna tendencia"} for c, v in por_columna.head(2).items()]
    if not partes:
        return None
    return _hallazgo(
        "Errores de captura",
        f"El archivo trae {_lista(partes)}.",
        "No son casos límite, son datos que no deberían existir: mientras estén ahí, cualquier total que los incluya está mal.",
        "Corregirlos en el origen. Son pocos y de arreglo mecánico, y arreglarlos mejora todos los indicadores a la vez.",
        evidencia, "warning", 5,
        objetivo={"view": "anomalías"},
    )


def diagnosticar(df: pd.DataFrame, schema: dict, anomalias=None, metrica=None) -> list[dict]:
    """Los hallazgos accionables de este archivo, del más urgente al menos.

    Devuelve lista vacía sin drama cuando el archivo no da para más: un
    catálogo o una lista de referencia no tiene nada que diagnosticar, y
    llenar la pantalla de avisos vacíos es peor que no mostrar ninguno.
    """
    if df is None or not len(df):
        return []
    metricas = schema.get("semantic", {}).get("metrics") or schema.get("metrics", [])
    metricas = [c for c in metricas if c in df.columns]
    if metrica not in metricas:
        prioridad = ["revenue", "profit", "quantity", "cost", "price", "discount", "tax"]
        sem = _semantica(schema)
        # Una métrica donde subir es malo (días de mora, quejas) no sirve como
        # métrica principal: "la mora cayó 30%" leído como logro sería al revés.
        # Esas tienen su propio detector; aquí se prefiere cualquier otra.
        neutras = [m for m in metricas if not PEOR_SI_SUBE.search(str(m))]
        candidatas = neutras or metricas
        metrica = next((m for p in prioridad for m in candidatas if sem.get(m) == p),
                       candidatas[0] if candidatas else None)

    # Sin ninguna columna numérica, la métrica es contar filas. Es lo que
    # convierte una lista de tickets o de asistencia en algo analizable: los
    # mismos detectores funcionan sobre "cuántos casos" en vez de "cuánto".
    trabajo = df
    if metrica is None:
        trabajo = df.assign(**{METRICA_CONTEO: 1})
        metrica = METRICA_CONTEO

    hallazgos = []
    dim = dimension_operativa(trabajo, schema, metrica)
    fechas = [c for c in schema.get("dates", []) if c in df.columns]

    if dim:
        tabla = None
        if fechas:
            try:
                tabla = _tabla_por_periodo(trabajo, schema, dim, metrica, fechas[0])
            except Exception:
                tabla = None
        temporales = (_caida_por_segmento, _deterioro_sostenido, _dejaron_de_registrar)
        for fn, args in (
            (_caida_por_segmento, (trabajo, schema, dim, metrica, fechas[0] if fechas else None, tabla)),
            (_deterioro_sostenido, (trabajo, schema, dim, metrica, tabla)),
            (_dejaron_de_registrar, (trabajo, schema, dim, metrica, fechas[0] if fechas else None, tabla)),
            (_estados_problematicos, (trabajo, schema, dim)),
            (_exceso_en_metrica_negativa, (trabajo, schema, dim)),
            (_en_cero, (trabajo, schema, dim, metrica)),
            (_rezago_frente_a_la_mediana, (trabajo, schema, dim, metrica)),
            (_concentracion, (trabajo, schema, dim, metrica)),
        ):
            if tabla is None and fn in temporales:
                continue
            try:
                encontrado = fn(*args)
            except Exception:
                encontrado = None
            if encontrado:
                hallazgos.append(encontrado)
    else:
        # Sin unidad con la que nombrar a nadie, todavía se puede decir qué
        # está mal en el archivo mismo.
        for fn, args in ((_estados_problematicos, (trabajo, schema, None)),
                         (_en_cero, (trabajo, schema, None, metrica))):
            try:
                encontrado = fn(*args)
            except Exception:
                encontrado = None
            if encontrado:
                hallazgos.append(encontrado)

    for fn, args in ((_atipicos_con_nombre, (df, schema, dim, anomalias)),
                     (_identificador_repetido, (df, schema)),
                     (_columnas_incompletas, (df, schema, dim)),
                     (_errores_de_captura, (df, schema, anomalias))):
        try:
            encontrado = fn(*args)
        except Exception:
            encontrado = None
        if encontrado:
            hallazgos.append(encontrado)

    hallazgos.sort(key=lambda h: h.get("priority", 99))
    return hallazgos
