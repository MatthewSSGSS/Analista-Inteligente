import pandas as pd
import numpy as np

def detect(df,schema):
    rows=[]
    for c in schema["metrics"]:
        s=pd.to_numeric(df[c],errors="coerce")
        v=s.dropna()
        if len(v)<8: continue
        q1,q3=v.quantile([.25,.75]); iqr=q3-q1
        if iqr:
            lo,hi=q1-1.5*iqr,q3+1.5*iqr
            for idx in df.index[(s<lo)|(s>hi)][:1000]:
                rows.append({"fila":int(idx),"columna":c,"valor":df.loc[idx,c],"tipo":"Outlier IQR"})
        if (v<0).any():
            for idx in df.index[s<0][:100]:
                rows.append({"fila":int(idx),"columna":c,"valor":df.loc[idx,c],"tipo":"Valor negativo"})
    for c in schema["dates"]:
        s=df[c]
        for idx in df.index[s.isna()][:100]:
            rows.append({"fila":int(idx),"columna":c,"valor":df.loc[idx,c],"tipo":"Fecha sospechosa"})
    return pd.DataFrame(rows)
