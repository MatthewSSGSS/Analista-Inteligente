"""«Así entendí tus columnas»: qué papel tiene cada columna, y corregirlo.

core/abreviaturas.py y core/por_valores.py adivinan lo que se puede adivinar.
Lo que no —la meta en una columna «Col6», un código corto, una fecha que el
archivo guardó como texto raro— lo sabe quien conoce el archivo. Aquí se
arma la lectura columna por columna (con su motivo, para que se pueda juzgar)
y se aplica lo que la persona corrige.

La corrección se aplica sobre la hoja YA procesada, no volviendo a leer el
archivo: la hoja original no se guarda entera (ver core/profile.py, «original»
duplicaba la memoria). Por eso pasar una fecha a número usa la conversión
inversa de cómo se leyó (serie de Excel, AAAAMM).

Nada aquí depende de Streamlit; la pantalla es ui/columnas.py.
"""
from __future__ import annotations

import copy

import pandas as pd

from .dates import detect_date
from .numeric import numeric_series

PAPELES = ["Fecha", "Dinero", "Cantidad", "Porcentaje", "Número", "Meta",
           "Identificador", "Persona", "Lugar", "Categoría", "Texto", "No usar"]
_NUMERICOS = {"Dinero": "revenue", "Cantidad": "quantity", "Porcentaje": "percentage",
              "Número": "unknown", "Meta": "unknown"}
_PERSONA = {"name", "employee", "customer"}
_LISTAS = ("metrics", "dates", "ids", "categorical", "text", "emails", "geography")
_LISTAS_SEMANTICAS = ("metrics", "dimensions", "ids", "geography", "date")


def _semantica(schema: dict) -> dict:
    return {x.get("column"): x.get("semantic_type") for x in schema.get("semantic", {}).get("columns", [])}


def papel_actual(columna, schema: dict) -> str:
    """El papel con el que el panel está usando la columna hoy."""
    tipos, sem = schema.get("types", {}), _semantica(schema).get(columna)
    if columna in (schema.get("papeles_usuario") or {}):
        return schema["papeles_usuario"][columna]
    if columna in schema.get("dates", []):
        return "Fecha"
    if columna == schema.get("meta_declarada"):
        return "Meta"
    if columna in schema.get("ids", []):
        return "Identificador"
    if columna in schema.get("metrics", []):
        return {"Moneda": "Dinero", "Cantidad": "Cantidad", "Porcentaje": "Porcentaje"}.get(tipos.get(columna), "Número")
    if sem in _PERSONA:
        return "Persona"
    if columna in schema.get("geography", []):
        return "Lugar"
    if columna in schema.get("text", []):
        return "Texto"
    return "Categoría"


def _motivo(columna, schema: dict, papel: str) -> tuple[str, bool]:
    """(por qué se leyó así, si conviene revisarla)."""
    if columna in (schema.get("papeles_usuario") or {}):
        return "Lo indicaste tú.", False
    por_valores = (schema.get("por_valores") or {}).get(columna)
    if por_valores:
        return por_valores, False
    sem = _semantica(schema).get(columna)
    if sem not in {None, "unknown"} or papel in {"Fecha", "Identificador", "Lugar", "Meta"}:
        return "Por el nombre de la columna.", False
    # El nombre no dijo nada y los valores tampoco alcanzaron: es la que más
    # vale la pena mirar. Una métrica sin nombre puede ser la venta o la meta.
    if papel == "Número":
        return "Es un número, pero el nombre no dice de qué: ¿dinero, cantidad, meta?", True
    return "Por el tipo de dato: el nombre no dice qué es.", True


def lectura(df: pd.DataFrame, schema: dict) -> list[dict]:
    """Una fila por columna visible: papel, motivo, ejemplos y si conviene revisarla."""
    filas = []
    for c in df.columns:
        if str(c).startswith("_"):
            continue  # columnas internas del motor (__periodo_analisis__…)
        papel = papel_actual(c, schema)
        motivo, revisar = _motivo(c, schema, papel)
        ejemplos = df[c].dropna().astype(str).str.strip()
        ejemplos = ejemplos[ejemplos != ""].drop_duplicates().head(3).tolist()
        filas.append({"columna": c, "papel": papel, "motivo": motivo, "revisar": revisar,
                      "ejemplos": ", ".join(e[:30] for e in ejemplos)})
    return filas


def _de_fecha_a_numero(serie: pd.Series, metodo: str | None) -> pd.Series:
    """La inversa de cómo se leyó la fecha: lo que el archivo traía escrito."""
    if metodo == "yyyymm_period":
        return (serie.dt.year * 100 + serie.dt.month).astype("Int64")
    if metodo == "excel_serial":
        return (serie - pd.Timestamp("1899-12-30")).dt.days.astype("Int64")
    raise ValueError("esta columna venía escrita como fecha en el archivo, así que no hay un número "
                     "original al que volver")


def _quitar_de_todo(schema: dict, columna) -> None:
    for lista in _LISTAS:
        if columna in schema.get(lista, []):
            schema[lista] = [c for c in schema[lista] if c != columna]
    sem = schema.get("semantic", {})
    for lista in _LISTAS_SEMANTICAS:
        if columna in sem.get(lista, []):
            sem[lista] = [c for c in sem[lista] if c != columna]
    if schema.get("meta_declarada") == columna:
        schema.pop("meta_declarada")
    for clave in ("metrica_preferida", "metrica_sugerida"):
        if schema.get(clave) == columna:
            schema.pop(clave)


def _marcar_semantica(schema: dict, columna, concepto: str, lista: str | None = None) -> None:
    sem = schema.setdefault("semantic", {})
    for item in sem.setdefault("columns", []):
        if item.get("column") == columna:
            item["semantic_type"] = concepto
            break
    else:
        sem["columns"].append({"column": columna, "semantic_type": concepto})
    if lista and columna not in sem.setdefault(lista, []):
        sem[lista].append(columna)


def aplicar_papeles(df: pd.DataFrame, schema: dict, papeles: dict) -> tuple[pd.DataFrame, dict]:
    """Devuelve (df, schema) nuevos con cada columna en el papel indicado.

    Lanza ValueError con un mensaje para la persona si una columna no puede
    tener ese papel (p. ej. «Fecha» en una columna de nombres).
    """
    df = df.copy()
    schema = copy.deepcopy(schema)
    usuario = dict(schema.get("papeles_usuario") or {})
    for columna, papel in papeles.items():
        if columna not in df.columns or papel not in PAPELES:
            continue
        if papel == papel_actual(columna, schema) and columna not in usuario:
            continue
        serie = df[columna]
        era_fecha = pd.api.types.is_datetime64_any_dtype(serie)
        metodo = schema.get("date_metadata", {}).get(columna)
        _quitar_de_todo(schema, columna)

        if papel == "No usar":
            df = df.drop(columns=[columna])
            schema["types"].pop(columna, None)
            schema.setdefault("ignoradas", []).append(columna)
        elif papel == "Fecha":
            fechas, tasa, metodo_nuevo = (serie, 1.0, metodo) if era_fecha else detect_date(serie, "fecha")
            if fechas is None or tasa < 0.5:
                raise ValueError(f"«{columna}» no parece una fecha: menos de la mitad de sus valores se pueden "
                                 "leer como fecha.")
            df[columna] = fechas
            schema["dates"].append(columna); schema["types"][columna] = "Fecha"
            schema.setdefault("date_metadata", {})[columna] = metodo_nuevo or "usuario"
            _marcar_semantica(schema, columna, "date", "date")
        elif papel in _NUMERICOS:
            try:
                origen = _de_fecha_a_numero(serie, metodo) if era_fecha else serie
            except ValueError as e:
                raise ValueError(f"«{columna}» no se puede usar como {papel.lower()}: {e}.") from None
            numeros = pd.to_numeric(origen, errors="coerce")
            if not era_fecha and numeros.notna().sum() < 0.5 * max(serie.notna().sum(), 1):
                numeros = numeric_series(serie).where(serie.notna())
                if numeros.fillna(0).eq(0).all():
                    raise ValueError(f"«{columna}» no trae números: no se puede usar como {papel.lower()}.")
            df[columna] = numeros
            schema["metrics"].append(columna)
            schema["types"][columna] = {"Dinero": "Moneda", "Cantidad": "Cantidad", "Porcentaje": "Porcentaje",
                                        "Meta": "Meta"}.get(papel, "Número")
            _marcar_semantica(schema, columna, _NUMERICOS[papel], "metrics")
            if papel == "Meta":
                # La meta se compara contra la métrica, no compite con ella.
                schema["meta_declarada"] = columna
        else:
            if era_fecha:
                df[columna] = serie.dt.strftime("%d/%m/%Y")
            if papel == "Identificador":
                schema["ids"].append(columna); schema["types"][columna] = "Identificador"
                _marcar_semantica(schema, columna, "id", "ids")
            elif papel == "Persona":
                schema["categorical"].append(columna); schema["types"][columna] = "Persona"
                _marcar_semantica(schema, columna, "name", "dimensions")
            elif papel == "Lugar":
                schema["geography"].append(columna); schema["categorical"].append(columna)
                schema["types"][columna] = "Geografía"
            elif papel == "Texto":
                schema["text"].append(columna); schema["types"][columna] = "Texto"
                _marcar_semantica(schema, columna, "text")
            else:
                schema["categorical"].append(columna); schema["types"][columna] = "Categoría"
                _marcar_semantica(schema, columna, "category", "dimensions")
        usuario[columna] = papel
    schema["papeles_usuario"] = usuario
    return df, schema
