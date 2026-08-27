import pandas as pd
import numpy as np
from .numeric import numeric_valid

def describe(df,schema):
    result=[]
    for c in schema["metrics"]:
        s=numeric_valid(df[c]).dropna()
        if not len(s): continue
        result.append({"Columna":c,"N":len(s),"Media":s.mean(),"Mediana":s.median(),"Std":s.std(),
                       "Min":s.min(),"Max":s.max(),"Q1":s.quantile(.25),"Q3":s.quantile(.75)})
    return pd.DataFrame(result)
