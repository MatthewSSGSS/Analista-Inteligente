"""Cruce de una misma entidad entre las hojas de un mismo Excel.

Responde la pregunta que pidió el usuario: *"si el código aparece en otra
hoja, ¿puede mostrarme también la info de esa otra hoja?"*.

Por qué no bastaba lo que ya había: `core/relationships.py` ya detecta hojas
emparentadas, pero exige que la columna se llame IGUAL en ambas
(`if ca not in dfb.columns: continue`). En archivos reales el nombre cambia
—`Código` en una hoja, `Cod_Punto` en otra, `Ref` en la tercera— y ahí no
encuentra nada. Aquí el emparejamiento es por VALORES: si los códigos de una
columna aparecen en otra, están relacionadas, se llamen como se llamen.

Además, aquello solo se mostraba como una tabla informativa en la pestaña
Calidad; nunca se usaba para traer datos. Este módulo sí: dado un valor
concreto (un código), devuelve lo que cada hoja sabe de él.
"""
from __future__ import annotations

import pandas as pd

# Cuántos valores distintos se comparan para decidir si dos columnas hablan
# de lo mismo. Con unos miles ya se distingue perfectamente una coincidencia
# real de una casualidad, y evita recorrer columnas enormes.
MUESTRA_VALORES = 5000

# Qué proporción de los códigos debe encontrarse en la otra columna para
# considerarlas la misma entidad. Es alto a propósito: un solape pequeño
# suele ser casualidad (números que coinciden sin relación), y un cruce
# equivocado mostraría datos de otro registro, que es peor que no mostrar
# nada.
UMBRAL_COINCIDENCIA = 0.5


def _valores_clave(serie: pd.Series) -> set:
    """Valores distintos, como texto normalizado, para poder comparar entre
    hojas aunque una guarde el código como número y otra como texto."""
    x = serie.dropna()
    if x.empty:
        return set()
    if len(x) > MUESTRA_VALORES * 4:
        x = x.head(MUESTRA_VALORES * 4)
    return {str(v).strip() for v in pd.unique(x)[:MUESTRA_VALORES] if str(v).strip()}


def encontrar_hojas_relacionadas(workbook: dict, hoja_actual: str, columna_clave: str) -> list[dict]:
    """Hojas del libro que hablan de la misma entidad que `columna_clave`.

    Devuelve, por cada hoja relacionada, con qué columna suya empareja y qué
    tan fuerte es la coincidencia — ordenadas de mejor a peor. Lista vacía
    si el libro tiene una sola hoja o ninguna coincide.
    """
    hojas = (workbook or {}).get("sheets") or {}
    actual = hojas.get(hoja_actual)
    if actual is None or columna_clave not in actual["processed"].columns:
        return []
    claves = _valores_clave(actual["processed"][columna_clave])
    if len(claves) < 2:
        return []

    encontradas = []
    for nombre, hoja in hojas.items():
        if nombre == hoja_actual:
            continue
        df = hoja.get("processed")
        if df is None or df.empty:
            continue
        mejor = None
        for col in df.columns:
            if str(col).startswith("__") or str(col).startswith("_geo_"):
                continue
            otros = _valores_clave(df[col])
            if len(otros) < 2:
                continue
            comunes = len(claves & otros)
            if not comunes:
                continue
            # Se mide contra el conjunto más pequeño: si una hoja es un
            # catálogo de 50 locales y la otra un histórico de 3 de ellos,
            # que coincidan esos 3 completos es una relación válida.
            coincidencia = comunes / max(min(len(claves), len(otros)), 1)
            if coincidencia >= UMBRAL_COINCIDENCIA and (mejor is None or coincidencia > mejor["coincidencia"]):
                mejor = {"hoja": nombre, "columna": col,
                         "coincidencia": round(coincidencia, 3), "comunes": comunes}
        if mejor:
            encontradas.append(mejor)

    encontradas.sort(key=lambda r: r["coincidencia"], reverse=True)
    return encontradas


def datos_de_entidad(workbook: dict, relacion: dict, valor) -> pd.DataFrame:
    """Las filas de la hoja relacionada que corresponden a este código."""
    hojas = (workbook or {}).get("sheets") or {}
    hoja = hojas.get(relacion.get("hoja"))
    if hoja is None:
        return pd.DataFrame()
    df = hoja.get("processed")
    col = relacion.get("columna")
    if df is None or col not in df.columns:
        return pd.DataFrame()
    objetivo = str(valor).strip()
    filas = df[df[col].astype(str).str.strip() == objetivo]
    visibles = [c for c in filas.columns
                if not str(c).startswith("__") and not str(c).startswith("_geo_")]
    return filas[visibles]


def resumir_filas(df: pd.DataFrame, columna_clave: str = "") -> list[dict]:
    """Convierte las filas encontradas en una ficha legible: un renglón por
    campo, con el dato si es único y un resumen si varía.

    Es la misma idea que la tabla "Todo lo relacionado" del perfil: en una
    presentación no sirve volcar 40 filas crudas, sirve saber *qué dice*
    esa hoja sobre este código.
    """
    if df is None or df.empty:
        return []
    resumen = []
    for col in df.columns:
        if col == columna_clave:
            continue
        serie = df[col].dropna()
        if serie.empty:
            valor = "Sin dato"
        elif serie.nunique() == 1:
            valor = str(serie.iloc[0])
        elif pd.api.types.is_numeric_dtype(serie):
            valor = f"min {serie.min():,.0f} · promedio {serie.mean():,.0f} · max {serie.max():,.0f}"
        else:
            distintos = [str(v) for v in pd.unique(serie)][:5]
            valor = ", ".join(distintos)
            if serie.nunique() > 5:
                valor += f" · +{serie.nunique() - 5} más"
        resumen.append({"Campo": str(col), "Información encontrada": valor})
    return resumen
