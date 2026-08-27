import pandas as pd
import numpy as np

def assess(df,schema):
    missing=df.isna().sum()
    duplicate=int(df.duplicated().sum())
    completeness=float(100-(missing/max(len(df),1)*100).mean())
    consistency=max(0.,100-duplicate/max(len(df),1)*100)
    validity=100.
    score=.5*completeness+.3*consistency+.2*validity
    rows=[]
    for c in df.columns:
        rows.append({"Columna":c,"Tipo":schema["types"].get(c,"Texto"),"Faltantes":int(missing[c]),
                     "Faltantes %":round(float(missing[c]/max(len(df),1)*100),2),
                     "Únicos":int(df[c].nunique(dropna=True))})
    return {"score":score,"completeness":completeness,"consistency":consistency,"validity":validity,
            "duplicate_rows":duplicate,"columns":pd.DataFrame(rows)}
