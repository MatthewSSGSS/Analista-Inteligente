import pandas as pd
import numpy as np
from .numeric import numeric_series, safe_sum, safe_mean, safe_median
from .diagnostics import PEOR_SI_SUBE

# A partir de cuánta variación se declara mejora o declive. Por debajo hay
# dirección pero no cambio: el veredicto lo dice como "estable con tendencia
# a la baja" en vez de dar por buena una caída que todavía no lo es.
UMBRAL_CAMBIO = 1.0


def _fmt(v):
    if v is None or pd.isna(v): return "—"
    v=float(v)
    sign='-' if v < 0 else ''
    v=abs(v)
    if v>=1_000_000_000: return f"{sign}{v/1_000_000_000:.1f} mil M"
    if v>=1_000_000: return f"{sign}{v/1_000_000:.1f}M"
    if v>=1_000: return f"{sign}{v/1_000:.1f}K"
    return f"{sign}{v:,.0f}"


def _label(schema, col):
    for x in schema.get('semantic',{}).get('columns',[]):
        if x.get('column') == col:
            return x.get('display_name') or col
    return str(col)


def _semantic(schema):
    return {x.get('column'):x.get('semantic_type') for x in schema.get('semantic',{}).get('columns',[])}


def primary_metric(df, schema):
    metrics=schema.get('semantic',{}).get('metrics') or schema.get('metrics',[])
    sem=_semantic(schema)
    priority=['revenue','profit','quantity','cost','discount','tax','price','percentage','rating','age']
    metrics=[c for c in metrics if c in df.columns]
    if schema.get('metrica_preferida') in metrics:
        return schema['metrica_preferida']  # la que eligió el usuario manda
    if schema.get('metrica_sugerida') in metrics:
        return schema['metrica_sugerida']  # la que trae meta propia (core/profile)
    return sorted(metrics,key=lambda c: priority.index(sem.get(c)) if sem.get(c) in priority else 99)[0] if metrics else None


def _monthly(df, date_col, metric, como='sum'):
    # Se arma columna por columna en vez de con df[[date_col, metric]]: si
    # date_col y metric son LA MISMA columna (o el archivo trae dos columnas
    # con el mismo nombre), ese doble corchete devuelve un DataFrame con la
    # columna repetida, y pd.to_datetime() sobre un DataFrame intenta
    # ensamblar una fecha a partir de los nombres de sus columnas y truena
    # con "cannot assemble with duplicate keys". El origen de esa
    # coincidencia ya se corrigió en core/schema.py (una columna no puede
    # ser fecha y métrica a la vez), pero esto lo deja imposible por
    # construcción: nunca hay dos columnas en juego, solo dos Series.
    if date_col is None or metric is None:
        return None
    if date_col == metric:
        return None
    dates = df[date_col]
    values = df[metric]
    if isinstance(dates, pd.DataFrame): dates = dates.iloc[:, 0]
    if isinstance(values, pd.DataFrame): values = values.iloc[:, 0]
    x = pd.DataFrame({
        '__fecha__': pd.to_datetime(dates, errors='coerce'),
        '__valor__': pd.to_numeric(values, errors='coerce'),
    }).dropna()
    if x.empty: return None
    por_mes = x.set_index('__fecha__')['__valor__'].resample('MS')
    return (por_mes.sum(min_count=1) if como == 'sum' else por_mes.mean()).dropna()  # un mes sin dato no es cero


def build_executive(df, schema, insights=None, anomalies=None):
    metric=primary_metric(df,schema)
    sem=_semantic(schema)
    result={'status':'neutral','headline':'El archivo está listo para análisis.','detail':'No hay suficientes datos para construir una lectura ejecutiva comparable.','positive':[],'watch':[]}
    if metric is None or metric not in df.columns:
        result['headline']='El archivo está listo para consulta y exploración.'
        result['detail']='No se detectó una métrica principal suficientemente clara para construir un resumen de desempeño.'
        return result
    s=pd.to_numeric(df[metric],errors='coerce').dropna()
    additive=sem.get(metric) in {'revenue','profit','cost','quantity','discount','tax'}
    current=safe_sum(s) if additive else safe_mean(s)
    label=_label(schema,metric)
    result['headline']=f"{label}: {_fmt(current)}"
    result['detail']=f"Se analizaron {len(df):,} registros. El indicador principal se presenta como {'total' if additive else 'promedio'} sobre la selección actual."
    dates=schema.get('dates',[])
    if dates:
        # Un porcentaje no se suma entre registros: ocho jefes al 90% no son
        # un 720%. Antes el veredicto sumaba siempre y decía "alcanzó 667".
        series=_monthly(df,dates[0],metric,'sum' if additive else 'mean')
        if series is not None and len(series)>=2:
            previous=float(series.iloc[-2]) if pd.notna(series.iloc[-2]) else 0.0
            current_period=float(series.iloc[-1]) if pd.notna(series.iloc[-1]) else 0.0
            if np.isfinite(previous) and np.isfinite(current_period) and previous != 0:
                pct=float((current_period-previous)/abs(previous)*100)
                result['change']=pct
                result['previous']=previous; result['current_period']=current_period
                comparacion=f"El último periodo alcanzó {_fmt(current_period)}, frente a {_fmt(previous)} en el periodo anterior."
                # En días de mora, quejas o devoluciones, subir no es mejorar.
                # Sin esta distinción el veredicto felicitaba por un 8% más de
                # mora, que es exactamente al revés de lo que pasó.
                peor_si_sube=bool(PEOR_SI_SUBE.search(str(metric)))
                if pct>=UMBRAL_CAMBIO or pct<=-UMBRAL_CAMBIO:
                    subio=pct>0
                    mejora=(not subio) if peor_si_sube else subio
                    result['status']='positive' if mejora else 'negative'
                    result['status_label']='Mejora' if mejora else 'Declive'
                    if peor_si_sube:
                        result['headline']=(f"{label} {'mejoró' if mejora else 'empeoró'}: "
                                            f"{'subió' if subio else 'bajó'} {abs(pct):.1f}% frente al periodo anterior.")
                    else:
                        result['headline']=(f"{label} {'mejoró' if mejora else 'retrocedió'} "
                                            f"{abs(pct):.1f}% frente al periodo anterior.")
                    result['detail']=comparacion
                else:
                    # Por debajo del umbral no hay mejora ni declive, pero sí
                    # hay dirección, y decirla cambia lo que se hace: "estable"
                    # a secas invita a no mirar, "estable con tendencia a la
                    # baja" invita a vigilar antes de que el mes que viene ya
                    # sea una caída.
                    result['status']='neutral'
                    if pct==0:
                        result['status_label']='Estable'
                        result['headline']=f"{label} se mantuvo sin variación frente al periodo anterior."
                    else:
                        rumbo='al alza' if pct>0 else 'a la baja'
                        result['status_label']=f"Estable con tendencia {rumbo}"
                        result['headline']=f"{label} se mantuvo estable, con tendencia {rumbo}."
                    result['detail']=(f"La variación frente al periodo anterior fue de {pct:+.1f}%, "
                                      f"por debajo del {UMBRAL_CAMBIO:.0f}% que se considera un cambio real. "
                                      + comparacion)
    # El propio veredicto es la primera señal. Antes las señales salían solo
    # de los 4 primeros hallazgos: si la mejora venía en el quinto, el panel
    # decía «Ingresos mejoró 17%» arriba y «No se detectaron mejoras» al lado.
    if result.get('status')=='positive':
        result['positive'].append(result['headline'])
    elif result.get('status')=='negative':
        result['watch'].append(result['headline'])
    if insights:
        for i in insights:
            if i.get('kind')=='positive': result['positive'].append(i.get('title','Mejora'))
            elif i.get('kind')=='warning': result['watch'].append(i.get('title','Revisión'))
    # Los atípicos solo si ningún hallazgo los nombró ya: eran dos avisos
    # seguidos con cifras distintas (los de una columna y los de todas).
    ya_atipicos = any('atípic' in str(x).lower() for x in result['watch'])
    if anomalies is not None and len(anomalies) and not ya_atipicos:
        result['watch'].append(f"{len(anomalies):,} valores atípicos requieren revisión")
    return result


def build_alerts(df, schema, insights=None, anomalies=None):
    """Las alertas son los hallazgos accionables, con su evidencia.

    Antes esta función añadía por su cuenta un aviso de atípicos aunque los
    hallazgos ya trajeran uno: el panel mostraba dos alertas seguidas
    diciendo lo mismo con distinto título ("164 observaciones atípicas" dos
    veces). Ahora solo se agrega si nadie lo dijo antes.
    """
    alerts=[]
    for i in (insights or []):
        kind=i.get('kind','info')
        if kind not in {'warning','positive'}: continue
        alerts.append({'severity':'Alta' if kind=='warning' else 'Oportunidad','title':i.get('title','Hallazgo'),'text':i.get('finding',''),'action':i.get('action',''),'implication':i.get('implication',''),'evidence':i.get('evidence') or [],'target':i.get('target',{})})
    ya_dicho={a.get('title') for a in alerts}
    if anomalies is not None and len(anomalies) and not ({'Valores atípicos: dónde están','Errores de captura','Calidad para la toma de decisiones'} & ya_dicho):
        alerts.append({'severity':'Alta','title':'Valores que requieren revisión','text':f"Se detectaron {len(anomalies):,} observaciones atípicas.",'action':'Validar primero las observaciones de mayor impacto antes de tomar decisiones.','evidence':[],'target':{'view':'anomalies'}})
    return alerts[:6]


def explain_change(df, schema, metric=None):
    metric=metric or primary_metric(df,schema)
    dates=schema.get('dates',[])
    if metric is None or not dates or metric not in df.columns: return None
    d=dates[0]
    x=df[[d,metric]].copy(); x[d]=pd.to_datetime(x[d],errors='coerce'); x[metric]=pd.to_numeric(x[metric],errors='coerce'); x=x.dropna()
    if x.empty: return None
    x['_period']=x[d].dt.to_period('M').dt.start_time
    periods=sorted(x['_period'].unique())
    if len(periods)<2: return None
    p0,p1=periods[-2],periods[-1]
    sem=_semantic(schema); additive=sem.get(metric) in {'revenue','profit','cost','quantity','discount','tax'}
    total0=x.loc[x['_period']==p0,metric].sum() if additive else x.loc[x['_period']==p0,metric].mean()
    total1=x.loc[x['_period']==p1,metric].sum() if additive else x.loc[x['_period']==p1,metric].mean()
    delta=float(total1-total0)
    pct=float(delta/abs(total0)*100) if total0 else None
    if pct is not None and not np.isfinite(pct):
        pct=None
    dims=schema.get('semantic',{}).get('dimensions') or schema.get('categorical',[])
    factors=[]
    for dim in dims:
        if dim not in df.columns or dim in dates or dim==metric: continue
        z=df[[d,dim,metric]].copy(); z[d]=pd.to_datetime(z[d],errors='coerce'); z[metric]=pd.to_numeric(z[metric],errors='coerce'); z=z.dropna(subset=[d,metric])
        z['_period']=z[d].dt.to_period('M').dt.start_time
        if z[dim].nunique(dropna=True)>40 or z.empty: continue
        if additive:
            a=z[z['_period']==p0].groupby(dim)[metric].sum(); b=z[z['_period']==p1].groupby(dim)[metric].sum()
        else:
            a=z[z['_period']==p0].groupby(dim)[metric].mean(); b=z[z['_period']==p1].groupby(dim)[metric].mean()
        joined=pd.concat([a.rename('before'),b.rename('after')],axis=1).fillna(0); joined['delta']=joined['after']-joined['before']
        joined=joined.sort_values('delta',key=lambda s:s.abs(),ascending=False).head(5)
        if not joined.empty:
            for idx,row in joined.iterrows(): factors.append({'dimension':dim,'label':str(idx),'delta':float(row['delta'])})
        if factors: break
    factors=sorted(factors,key=lambda z:abs(z['delta']),reverse=True)[:5]
    # `additive` y `dimension` salen fuera porque quien dibuje esto necesita
    # saber si los cambios por segmento SUMAN el cambio total. En una
    # métrica que se suma (ingresos, unidades) sí: la cascada cierra exacta.
    # En un promedio o un porcentaje NO —la media de las medias no es la
    # media— y presentarlo como una suma sería afirmar algo falso.
    dimension = factors[0]['dimension'] if factors else None
    return {'metric':metric,'metric_label':_label(schema,metric),'before':float(total0),'after':float(total1),'delta':delta,'pct':pct,'period_before':str(p0)[:10],'period_after':str(p1)[:10],'factors':factors,'additive':bool(additive),'dimension':dimension}


def _tono(pct, peor_si_sube=False):
    """positive / negative / neutral según si el cambio es bueno para el negocio."""
    if pct is None or abs(pct) < 0.05:
        return "neutral"
    return "negative" if (pct > 0) == peor_si_sube else "positive"


def _mes_largo(ts) -> str:
    from .dates import format_month_year
    return format_month_year(ts, full=True).lower()


def _mes_corto(ts) -> str:
    from .dates import format_month_year
    return format_month_year(ts).lower()


def indicadores_gerente(df, schema, g, metrica) -> list[dict]:
    """Las cifras que mira un gerente: cómo cerró el último mes, contra el
    mismo mes del año pasado, el acumulado del año, el margen y el ticket.

    Antes la fila de tarjetas decía «Registros visibles», el total de TODO el
    archivo (19 meses sumados), la mediana y el máximo de una fila: datos del
    archivo, no del negocio. Solo se arma con una métrica que se suma y con el
    análisis gerencial (`g`, que ya resolvió qué meses comparar y el mes a
    medias); si no, devuelve lista vacía y la vista usa las tarjetas de siempre.

    Cada indicador: {"etiqueta", "valor", "detalle", "tono"} (texto listo)."""
    from .universal_analysis import semantic_map, ADDITIVE, period_series
    sem = semantic_map(schema)
    if not (g and metrica and g.get("metrica") == metrica and sem.get(metrica) in ADDITIVE
            and g.get("total_b") is not None):
        return []
    etiqueta = _label(schema, metrica)
    peor = bool(PEOR_SI_SUBE.search(str(metrica)))
    salida = [{"etiqueta": f"{etiqueta} · {g['mes_b']}", "valor": _fmt(g["total_b"]),
               "detalle": f"{g['pct']:+.1f}% vs {g['mes_a']}" if g.get("pct") is not None else None,
               "tono": _tono(g.get("pct"), peor), "clave": "mes"}]
    ps = period_series(df, schema, metrica, "Mes", "Automático")
    if len(ps) >= 2 and not g.get("parcial"):
        ps = ps.assign(period=pd.to_datetime(ps["period"]))
        ultimo = ps.iloc[-1]
        p = pd.Timestamp(ultimo["period"])
        valor = float(ultimo[metrica])
        # Cumplimiento de la meta del mes, si el archivo la trae: es la cifra
        # por la que se mide a un equipo comercial, va justo después del mes.
        from .performance import columna_meta
        meta = columna_meta(df, schema, metrica)
        if meta:
            pm = period_series(df, schema, meta, "Mes", "Suma")
            pm = pm.assign(period=pd.to_datetime(pm["period"])).set_index("period")[meta]
            if p in pm.index and float(pm[p]) > 0:
                objetivo = float(pm[p])
                cumple = valor / objetivo * 100
                falta = objetivo - valor
                salida.append({"etiqueta": f"Cumplimiento de meta · {g['mes_b']}", "valor": f"{cumple:.0f}%",
                               "detalle": (f"faltan {_fmt(falta)} de {_fmt(objetivo)}" if falta > 0
                                           else f"superó la meta por {_fmt(-falta)}"),
                               "tono": "positive" if cumple >= 100 else "negative" if cumple < 90 else "neutral",
                               "clave": "meta"})
        # El mismo mes del año pasado: quita la temporada del medio.
        hace_un_anio = ps[ps["period"] == p - pd.DateOffset(years=1)]
        if not hace_un_anio.empty and float(hace_un_anio[metrica].iloc[0]):
            antes = float(hace_un_anio[metrica].iloc[0])
            pct = (valor - antes) / abs(antes) * 100
            salida.append({"etiqueta": f"Frente a {_mes_largo(p - pd.DateOffset(years=1))}", "valor": f"{pct:+.1f}%",
                           "detalle": f"{_fmt(valor)} vs {_fmt(antes)}", "tono": _tono(pct, peor), "clave": "anual"})
        # Acumulado del año contra los mismos meses del año anterior (solo si están todos).
        este = ps[(ps["period"].dt.year == p.year) & (ps["period"] <= p)]
        previo = ps[(ps["period"].dt.year == p.year - 1) & (ps["period"].dt.month <= p.month)]
        if len(este) >= 2 and len(previo) == len(este) and float(previo[metrica].sum()):
            acum, acum_prev = float(este[metrica].sum()), float(previo[metrica].sum())
            pct = (acum - acum_prev) / abs(acum_prev) * 100
            salida.append({"etiqueta": f"Acumulado {p.year} (ene–{_mes_corto(p).split()[0]})", "valor": _fmt(acum),
                           "detalle": f"{pct:+.1f}% vs {p.year - 1}", "tono": _tono(pct, peor), "clave": "acumulado"})
        # Margen del último mes, si el archivo trae la utilidad aparte.
        utilidad = next((c for c, t in sem.items() if t == "profit" and c != metrica and c in df.columns), None)
        if utilidad and sem.get(metrica) == "revenue" and valor:
            pu = period_series(df, schema, utilidad, "Mes", "Suma")
            pu = pu.assign(period=pd.to_datetime(pu["period"])).set_index("period")[utilidad]
            if p in pu.index:
                margen = float(pu[p]) / valor * 100
                anterior = ps.iloc[-2]
                p_ant = pd.Timestamp(anterior["period"])
                detalle = None
                if p_ant in pu.index and float(anterior[metrica]):
                    puntos = margen - float(pu[p_ant]) / float(anterior[metrica]) * 100
                    detalle = f"{puntos:+.1f} pts vs {_mes_corto(p_ant)}"
                salida.append({"etiqueta": f"Margen ({_label(schema, utilidad)}) · {g['mes_b']}",
                               "valor": f"{margen:.1f}%", "detalle": detalle, "tono": "neutral", "clave": "margen"})
    # Volumen y ticket: dos problemas distintos que se atacan distinto.
    pal = g.get("palanca")
    if pal and pal.get("ticket_b"):
        salida.append({"etiqueta": f"{str(pal['ticket_nombre']).capitalize()} · {g['mes_b']}", "valor": _fmt(pal["ticket_b"]),
                       "detalle": f"{pal['ticket_pct']:+.1f}% · {pal['unidad']} {pal['ops_pct']:+.1f}%",
                       "tono": _tono(pal["ticket_pct"]), "clave": "ticket"})
    return salida
