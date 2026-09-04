import pandas as pd
import numpy as np
from .numeric import numeric_series, safe_sum, safe_mean, safe_median


def _fmt(v):
    if v is None or pd.isna(v): return "—"
    v=float(v)
    sign='-' if v < 0 else ''
    v=abs(v)
    if v>=1_000_000_000: return f"{sign}{v/1_000_000_000:.1f}B"
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
    return sorted(metrics,key=lambda c: priority.index(sem.get(c)) if sem.get(c) in priority else 99)[0] if metrics else None


def _monthly(df, date_col, metric):
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
    return x.set_index('__fecha__')['__valor__'].resample('MS').sum().dropna()


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
        series=_monthly(df,dates[0],metric)
        if series is not None and len(series)>=2:
            previous=float(series.iloc[-2]) if pd.notna(series.iloc[-2]) else 0.0
            current_period=float(series.iloc[-1]) if pd.notna(series.iloc[-1]) else 0.0
            if np.isfinite(previous) and np.isfinite(current_period) and previous != 0:
                pct=float((current_period-previous)/abs(previous)*100)
                result['change']=pct
                result['previous']=previous; result['current_period']=current_period
                if pct>2:
                    result['status']='positive'; result['headline']=f"{label} creció {pct:.1f}% frente al periodo anterior."
                    result['detail']=f"El último periodo alcanzó {_fmt(current_period)}, frente a {_fmt(previous)} en el periodo anterior."
                elif pct<-2:
                    result['status']='negative'; result['headline']=f"{label} cayó {abs(pct):.1f}% frente al periodo anterior."
                    result['detail']=f"El último periodo alcanzó {_fmt(current_period)}, frente a {_fmt(previous)} en el periodo anterior."
                else:
                    result['status']='neutral'; result['headline']=f"{label} se mantuvo relativamente estable."
                    result['detail']=f"La variación frente al periodo anterior fue de {pct:+.1f}%."
    if insights:
        for i in insights[:4]:
            if i.get('kind')=='positive': result['positive'].append(i.get('title','Mejora'))
            elif i.get('kind')=='warning': result['watch'].append(i.get('title','Revisión'))
    if anomalies is not None and len(anomalies):
        result['watch'].append(f"{len(anomalies):,} valores atípicos requieren revisión")
    return result


def build_alerts(df, schema, insights=None, anomalies=None):
    alerts=[]
    for i in (insights or []):
        kind=i.get('kind','info')
        if kind not in {'warning','positive'}: continue
        alerts.append({'severity':'Alta' if kind=='warning' else 'Oportunidad','title':i.get('title','Hallazgo'),'text':i.get('finding',''),'action':i.get('action',''),'implication':i.get('implication',''),'target':i.get('target',{})})
    if anomalies is not None and len(anomalies):
        alerts.append({'severity':'Alta','title':'Valores que requieren revisión','text':f"Se detectaron {len(anomalies):,} observaciones atípicas.",'action':'Validar primero las observaciones de mayor impacto antes de tomar decisiones.','target':{'view':'anomalies'}})
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
    return {'metric':metric,'metric_label':_label(schema,metric),'before':float(total0),'after':float(total1),'delta':delta,'pct':pct,'period_before':str(p0)[:10],'period_after':str(p1)[:10],'factors':factors}
