"""Tabla ancha de meses (Enero…Diciembre como columnas) → una fila por elemento y mes.

Los informes descargables (Excel ejecutivo e HTML interactivo) necesitan una
fecha por registro para la tendencia, la comparación entre meses y las tablas
dinámicas. Una tabla resumen que trae los meses como columnas y no tiene
columna de fecha se pasa aquí a formato largo con una fecha sintética (día 1
de cada mes, del año que nombra el archivo o la hoja).

Un mes sin dato queda fuera, no en cero: "aún no reportado" no es "cero".
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from .dates import extract_year_hint
from .explorador import columna_fecha
from .numeric import numeric_valid


def meses_a_filas(df: pd.DataFrame, schema: dict, filename: str = "", sheet: str = "") -> Optional[tuple]:
    """(df_largo, schema_largo) o None si la tabla no es de meses en columnas
    o ya trae su propia fecha."""
    from visualization.charts import dimension_candidates, month_columns

    meses = month_columns(df)
    if len(meses) < 2 or columna_fecha(df, schema):
        return None
    try:
        anio = extract_year_hint(filename, sheet) or datetime.now().year
    except Exception:
        anio = datetime.now().year
    dims = [c for c in dimension_candidates(df, schema) if c in df.columns][:4]
    cols = {c: n for n, c in meses}
    largo = df[dims + list(cols)].melt(id_vars=dims, value_vars=list(cols), var_name="Mes", value_name="Valor")
    largo["Fecha"] = [pd.Timestamp(int(anio), int(cols[m]), 1) for m in largo["Mes"]]
    largo["Valor"] = numeric_valid(largo["Valor"])
    largo = largo.dropna(subset=["Valor"])[["Fecha"] + dims + ["Valor"]]
    if largo.empty:
        return None
    esquema = {
        "dates": ["Fecha"], "metrics": ["Valor"], "categorical": dims, "ids": [], "text": [], "geography": [],
        "semantic": {"columns": [{"column": "Valor", "semantic_type": "quantity", "display_name": "Valor"}]
                     + [c for c in schema.get("semantic", {}).get("columns", []) if c.get("column") in dims],
                     "metrics": ["Valor"], "dimensions": dims},
    }
    return largo.reset_index(drop=True), esquema
