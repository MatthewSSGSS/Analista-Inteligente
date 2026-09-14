import pandas as pd
from .numeric import numeric_series, safe_mean, safe_median, safe_sum
from .diagnostics import diagnosticar


def _fmt(v):
    v = float(v)
    a = abs(v)
    if a >= 1_000_000_000: return f"{v/1_000_000_000:.1f}B"
    if a >= 1_000_000: return f"{v/1_000_000:.1f}M"
    if a >= 1_000: return f"{v/1_000:.1f}K"
    return f"{v:,.0f}"

LABELS = {
    "revenue":"Ingresos", "profit":"Beneficio", "cost":"Costos", "price":"Precio",
    "quantity":"Cantidad", "discount":"Descuento", "tax":"Impuestos", "percentage":"Porcentaje",
    "rating":"Puntuación", "age":"Edad", "product":"Producto", "category":"Categoría",
    "region":"Región", "country":"País", "city":"Ciudad", "brand":"Marca",
    "customer":"Cliente", "employee":"Empleado", "gender":"Género", "status":"Estado",
}


# En una métrica, el nombre que le puso el archivo dice más que el genérico:
# "Altas Eje" es más claro que "cantidad", y dos métricas del mismo tipo
# quedarían con el mismo nombre.
_METRICAS = {"revenue", "profit", "cost", "price", "quantity", "discount", "tax", "percentage", "rating", "age"}


def _pretty(schema, column):
    for item in schema.get("semantic", {}).get("columns", []):
        if item.get("column") == column:
            if item.get("semantic_type") in _METRICAS:
                return str(column)
            return LABELS.get(item.get("semantic_type"), str(column))
    return str(column)


def _lectura_de_concentracion(df, schema, dim, metrica, lider, share, dim_label, metric_label):
    """Qué significa que un segmento pese más, medido contra algo.

    Pesar más no es ir mejor: una región grande concentra el volumen por ser
    grande. Antes este hallazgo llamaba "liderazgo" al tamaño y sugería
    replicar las prácticas del más grande, aunque fuera el que peor cumplía
    su meta. Ahora el peso se contrasta con la base justa del panel de
    desempeño (meta, por unidad o por registro) y se dice contra qué.
    Devuelve (hallazgo, acción, tipo).
    """
    from .performance import base_comparativa

    sem = {x.get("column"): x.get("semantic_type") for x in schema.get("semantic", {}).get("columns", [])}
    aditiva = sem.get(metrica) in {"revenue", "profit", "cost", "quantity", "discount", "tax"}
    texto = (f"{lider} es el de mayor volumen en {dim_label}: aporta el {share:.1f}% del total "
             f"de {metric_label.lower()}.")
    try:
        base = base_comparativa(df, schema, dim, metrica, aditiva)
    except Exception:
        base = None
    justa = bool(base and base.get("justo") and base.get("clave") not in {"total", "total_parejo"})
    nombres = [f["nombre"] for f in base["ranking"]] if justa else []
    if str(lider) not in nombres:
        texto += " Eso mide tamaño, no desempeño: el archivo no trae una meta ni una base con qué compararlo."
        accion = (f"Vigilar la dependencia de {lider}: si baja, arrastra el total. Para saber quién rinde "
                  f"mejor hace falta una columna de meta.")
        return texto, accion, "info"
    puesto = nombres.index(str(lider)) + 1
    fila, mejor = base["ranking"][puesto - 1], base["mejor"]
    etiqueta = "cumplimiento de meta" if base["clave"] == "meta" else base["etiqueta"]
    if puesto == 1:
        texto += f" Y también es 1.º de {len(nombres)} en {etiqueta} ({fila['texto']}, {fila['detalle']})."
        accion = (f"Documentar qué hace {lider} y replicarlo en los que quedan abajo en {etiqueta}: "
                  f"pesa más y además rinde más.")
        return texto, accion, "positive"
    texto += (f" Pero medido por {etiqueta} queda {puesto}.º de {len(nombres)} ({fila['texto']}, "
              f"{fila['detalle']}). El mejor en {etiqueta} es {mejor['nombre']}, con {mejor['texto']}.")
    accion = (f"No tomar a {lider} como referente por su tamaño: el referente en {etiqueta} es "
              f"{mejor['nombre']}. Revisar por qué {lider} no convierte su volumen en {etiqueta}.")
    return texto, accion, ("warning" if puesto > len(nombres) / 2 else "info")


def generate(df, schema, anomalies):
    """Genera hallazgos ejecutivos con evidencia, implicación y acción sugerida.

    Primero van los hallazgos con nombre propio (`core/diagnostics`): cuál
    punto cayó, cuánto y desde cuándo. Los de aquí abajo son lecturas
    generales del archivo —línea base, dispersión, evolución— y solo deben
    aparecer cuando no hay algo más concreto que decir en su lugar.
    """
    concretos = diagnosticar(df, schema, anomalies)
    cubiertos = {h.get("title") for h in concretos}
    out = []
    metrics = schema.get("semantic", {}).get("metrics") or schema.get("metrics", [])
    cats = schema.get("semantic", {}).get("dimensions") or schema.get("categorical", [])
    dates = schema.get("dates", [])
    sem = {x.get("column"): x.get("semantic_type") for x in schema.get("semantic", {}).get("columns", [])}
    priority = {"revenue":0,"profit":1,"quantity":2,"price":3,"cost":4,"discount":5,"tax":6,"percentage":7,"rating":8,"age":9}
    metrics = [c for c in metrics if c in df.columns]
    metrics = sorted(metrics, key=lambda c: priority.get(sem.get(c), 50))
    cats = [c for c in cats if c in df.columns and c not in metrics]

    if metrics:
        m = metrics[0]
        s = pd.to_numeric(df[m], errors="coerce").dropna()
        if len(s):
            label = _pretty(schema, m)
            additive = sem.get(m) in {"revenue", "profit", "cost", "quantity", "discount", "tax"}
            headline = f"El valor acumulado de {label.lower()} es {_fmt(safe_sum(s))}, con un promedio de {_fmt(safe_mean(s))} por registro." if additive else f"El valor promedio de {label.lower()} es {_fmt(safe_mean(s))}, con una mediana de {_fmt(safe_median(s))}."
            out.append({
                "title":"Nivel de actividad",
                "finding":headline,
                "implication":"Este indicador establece la línea base del periodo analizado y permite comparar segmentos y periodos con una referencia común.",
                "action":"Usar esta línea base y contrastarla con las principales dimensiones antes de definir prioridades." ,
                "confidence":"Alta", "kind":"info", "priority":11,
            })
            if len(s) >= 8:
                median = safe_median(s)
                q1, q3 = s.quantile([.25, .75])
                spread = float((q3-q1) / max(abs(median), 1e-9) * 100)
                if spread >= 75:
                    out.append({
                        "title":"Variabilidad relevante",
                        "finding":f"{label} presenta una dispersión elevada: el rango intercuartílico equivale aproximadamente al {spread:.0f}% de la mediana.",
                        "implication":"El promedio puede ocultar diferencias importantes entre registros; el comportamiento no es homogéneo.",
                        "action":"Segmentar por región, producto o periodo para localizar dónde se concentra la variabilidad y priorizar los segmentos más alejados del comportamiento normal.",
                        "confidence":"Media", "kind":"warning", "priority":14,
                    })

    # La concentración genérica solo tiene sentido si el diagnóstico con
    # nombre no la dijo ya, y con más detalle.
    if cats and metrics and "Concentración de riesgo" not in cubiertos:
        m = metrics[0]
        for c in cats:
            try:
                x = df[[c, m]].copy()
                x[m] = pd.to_numeric(x[m], errors="coerce")
                x = x.dropna(subset=[m])
                # Las filas sin valor en la dimensión se descartan: con
                # dropna=False el grupo vacío entraba al ranking y el panel
                # llegó a decir "<NA> concentra el 50% del total", que no es
                # el nombre de nada y no se puede accionar.
                x[c] = x[c].astype(str).str.strip()
                x = x[x[c].ne("") & ~x[c].str.lower().isin({"nan", "none", "<na>", "nat"})]
                if x[c].nunique() < 2 or x[c].nunique() > 100:
                    continue
                g = x.groupby(c)[m].sum().sort_values(ascending=False)
                if len(g):
                    leader = str(g.index[0]); total = float(g.sum()); share = float(g.iloc[0]/total*100) if total else 0
                    if share >= 20:
                        dim_label = _pretty(schema, c); metric_label = _pretty(schema, m)
                        finding, action, kind = _lectura_de_concentracion(df, schema, c, m, leader, share, dim_label, metric_label)
                        out.append({
                            "title":"Concentración por dimensión",
                            "finding":finding,
                            "implication":"Una parte relevante del resultado depende de un único segmento. Pesar más no es rendir más: el volumen se contrasta con la meta o con una base que no dependa del tamaño.",
                            "action":action,
                            "confidence":"Alta", "kind":kind, "priority":12, "target":{"dimension":c,"metric":m,"filter_column":c,"filter_value":leader,"view":f"{dim_label}: {leader}"},
                        })
                        break
            except Exception:
                continue

    if dates and metrics:
        d, m = dates[0], metrics[0]
        try:
            x = df[[d, m]].copy()
            x[d] = pd.to_datetime(x[d], errors="coerce")
            x[m] = pd.to_numeric(x[m], errors="coerce")
            x = x.dropna()
            if len(x) >= 4:
                tmp = x.set_index(d)[m].resample("MS").sum().dropna()
                if len(tmp) >= 2 and tmp.iloc[-2] != 0:
                    pct = float((tmp.iloc[-1]-tmp.iloc[-2])/abs(tmp.iloc[-2])*100)
                    metric_label = _pretty(schema, m)
                    if pct >= 5:
                        implication = "El resultado reciente es favorable, pero conviene distinguir entre un crecimiento estructural y un efecto puntual."
                        action = "Identificar qué segmentos explican el avance y comprobar si el crecimiento se mantiene antes de ampliar recursos."
                        kind = "positive"
                    elif pct <= -5:
                        implication = "La caída reciente puede estar concentrada en pocos segmentos; localizar el origen evita aplicar medidas generales que no ataquen el problema."
                        action = "Priorizar un diagnóstico por dimensión y periodo para localizar el origen de la caída y concentrar acciones correctivas donde el impacto sea mayor."
                        kind = "warning"
                    else:
                        implication = "El resultado reciente es relativamente estable; la prioridad pasa de reaccionar a vigilar cambios tempranos."
                        action = "Mantener el seguimiento y revisar los segmentos que más se alejen del comportamiento estable antes de realizar cambios de estrategia."
                        kind = "info"
                    out.append({
                        "title":"Evolución reciente",
                        "finding":f"El último periodo disponible registra un cambio de {pct:+.1f}% en {metric_label.lower()} frente al periodo anterior.",
                        "implication":implication,
                        "action":action,
                        "confidence":"Alta", "kind":kind, "priority":13, "target":{"metric":m,"view":"evolución reciente"},
                    })
        except Exception:
            pass

    # El aviso genérico de atípicos queda como último recurso: si el
    # diagnóstico pudo decir en qué segmento están, ese reemplaza a este.
    # Tres es el mínimo para que valga la pena ocupar un lugar en el panel:
    # con uno solo el aviso decía "se detectaron 1 observaciones atípicas",
    # que además de sonar mal no da nada que priorizar.
    if len(anomalies) >= 3 and not ({"Valores atípicos: dónde están", "Errores de captura"} & cubiertos):
        out.append({
            "title":"Calidad para la toma de decisiones",
            "finding":f"Se detectaron {len(anomalies):,} observaciones atípicas que conviene revisar.",
            "implication":"Los valores atípicos pueden distorsionar promedios, rankings y tendencias si corresponden a errores de captura o casos excepcionales.",
            "action":"Validar primero las observaciones de mayor impacto y confirmar si representan eventos reales o problemas de calidad antes de tomar decisiones.",
            "confidence":"Alta", "kind":"warning", "priority":15, "target":{"view":"anomalías"},
        })

    out = concretos + out
    out.sort(key=lambda x: x.get("priority", 99))
    return out[:6]
