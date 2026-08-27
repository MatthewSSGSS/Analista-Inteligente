import pandas as pd
from .numeric import numeric_series, safe_mean, safe_median, safe_sum


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


def _pretty(schema, column):
    for item in schema.get("semantic", {}).get("columns", []):
        if item.get("column") == column:
            return LABELS.get(item.get("semantic_type"), str(column))
    return str(column)


def generate(df, schema, anomalies):
    """Genera hallazgos ejecutivos con evidencia, implicación y acción sugerida."""
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
                "confidence":"Alta", "kind":"info", "priority":1,
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
                        "confidence":"Media", "kind":"warning", "priority":4,
                    })

    if cats and metrics:
        m = metrics[0]
        for c in cats:
            try:
                x = df[[c, m]].copy()
                x[m] = pd.to_numeric(x[m], errors="coerce")
                x = x.dropna(subset=[m])
                if x[c].nunique(dropna=True) < 2 or x[c].nunique(dropna=True) > 100:
                    continue
                g = x.groupby(c, dropna=False)[m].sum().sort_values(ascending=False)
                if len(g):
                    leader = str(g.index[0]); total = float(g.sum()); share = float(g.iloc[0]/total*100) if total else 0
                    if share >= 20:
                        dim_label = _pretty(schema, c); metric_label = _pretty(schema, m)
                        out.append({
                            "title":"Concentración por dimensión",
                            "finding":f"{leader} concentra el {share:.1f}% del total de {metric_label.lower()} dentro de {dim_label.lower()}.",
                            "implication":"Una parte relevante del resultado depende de un único segmento. Esto puede representar una fortaleza, pero también una exposición a concentración.",
                            "action":f"Revisar qué explica el liderazgo de {leader} y evaluar si sus prácticas pueden replicarse en los segmentos con menor desempeño.",
                            "confidence":"Alta", "kind":"positive" if share >= 30 else "info", "priority":2, "target":{"dimension":c,"metric":m,"filter_column":c,"filter_value":leader,"view":f"{dim_label}: {leader}"},
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
                        "confidence":"Alta", "kind":kind, "priority":3, "target":{"metric":m,"view":"evolución reciente"},
                    })
        except Exception:
            pass

    if len(anomalies):
        out.append({
            "title":"Calidad para la toma de decisiones",
            "finding":f"Se detectaron {len(anomalies):,} observaciones atípicas que conviene revisar.",
            "implication":"Los valores atípicos pueden distorsionar promedios, rankings y tendencias si corresponden a errores de captura o casos excepcionales.",
            "action":"Validar primero las observaciones de mayor impacto y confirmar si representan eventos reales o problemas de calidad antes de tomar decisiones.",
            "confidence":"Alta", "kind":"warning", "priority":5, "target":{"view":"anomalías"},
        })

    out.sort(key=lambda x: x.get("priority", 99))
    return out[:6]
