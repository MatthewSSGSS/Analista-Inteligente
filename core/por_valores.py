"""Reconocer columnas por lo que traen, cuando el nombre no dice nada.

core/abreviaturas.py resuelve «Mpio» o «VLR_NETO». Pero un exporte también
puede traer «Col4», «Campo 7» o un encabezado en blanco, y ahí ninguna regla
basada en el nombre sirve: los municipios quedaban como una categoría (sin
mapa), las cédulas como una métrica (se sumaban), los vendedores como una
categoría más (sin «Comparar personas») y una fecha en número de serie como un
número, con lo que el archivo caía en «📚 Vista principal».

Este paso corre al final de `core/schema.detect_schema` y SOLO mira las
columnas que el nombre dejó sin papel claro (tipo genérico y semántica
desconocida): nunca contradice lo que el nombre ya decidió. Cada papel exige
una prueba en los valores que una columna de otro tipo no puede dar:

- Lugar: el valor COMPLETO es un municipio o departamento de Colombia (no un
  pedazo: «Juan Córdoba Gómez» tiene un departamento dentro y es una persona).
  Solo cambia el tipo visible y los filtros; el mapa ya lo encontraba solo.
- Persona: valores de 2 a 5 palabras y casi todos con un nombre de pila
  conocido. Sin la lista de nombres, «Plan Oro» o «Zona Norte» pasarían.
- Documento: un entero de 6 a 11 dígitos, casi nunca redondo, que se repite
  y va 1 a 1 con una columna de texto (cada cédula es siempre la misma
  persona y al revés). La meta fija de cada región también va 1 a 1, pero es
  redonda; una venta no se repite así en una base de registros.
- Fecha: un entero en el rango de los números de serie de Excel (1990-2049)
  o un AAAAMM, solo si la hoja no tiene ya otra fecha. Los precios caen en el
  mismo rango pero son casi siempre redondos (múltiplos de 100): se descartan.

- Porcentaje o dinero: solo si los valores venían escritos con «%» o con signo
  de moneda (core/cleaner lo anota en `df.attrs["formato_numeros"]`).

Queda fuera a propósito la meta: «Col5» y «Col6» pueden ser venta y meta, o
venta y costo, y los valores no permiten saber cuál es cuál. Eso lo confirma
la persona que conoce el archivo.

Lo que se reconoce queda anotado en `schema["por_valores"]` ({columna: motivo})
para poder explicarlo en pantalla.
"""
from __future__ import annotations

import re

import pandas as pd

from .dates import date_only, excel_serial, yyyymm_series

# Tipos con los que el nombre deja una columna "sin decidir".
_GENERICOS = {"Número", "Categoría", "Texto", "Dimensión"}
_MUESTRA_FILAS = 5000
_MUESTRA_DISTINTOS = 300

# Nombres de pila frecuentes en Colombia, sin tildes y en minúscula.
NOMBRES_DE_PILA = set("""
adriana alba alberto alejandra alejandro alexander alexandra alfonso alicia alvaro amparo ana andrea andres
angela angelica antonio armando arturo beatriz camila camilo carlos carmen carolina catalina cecilia cesar
claudia constanza cristian cristina daniel daniela david diana diego dora edgar edison eduardo elizabeth elsa
emilio enrique esperanza esteban fabian fanny felipe fernando francisco gabriel gabriela german gina gladys gloria
gonzalo guillermo gustavo hector helena henry hernan hugo isabel ivan jaime javier jenny jesus jhon jhonatan
jorge jose juan juliana julian julio karen katherine laura leidy leonardo liliana lina lorena luis luisa luz
manuel marcela marco margarita maria mariana marina mario marta martha mateo mauricio miguel milena monica
nancy natalia nelson nicolas nora olga omar oscar pablo patricia paola pedro rafael ramiro raul ricardo roberto
rocio rodrigo rosa ruben samuel sandra santiago sara sebastian sergio sofia sonia stella susana tatiana teresa
valentina valeria vanessa veronica victor viviana wilson william yolanda yuliana
""".split())

_PALABRA_NOMBRE_RE = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ'.]+$")


def _sin_tildes(texto: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", texto)
    return "".join(ch for ch in t if not unicodedata.combining(ch)).lower()


def _distintos(serie: pd.Series) -> list:
    valores = serie.dropna().astype(str).str.strip()
    valores = valores[valores != ""]
    return valores.drop_duplicates().head(_MUESTRA_DISTINTOS).tolist()


def _es_persona(valores: list) -> tuple[bool, str]:
    if len(valores) < 3:
        return False, ""
    con_forma = [v for v in valores if 2 <= len(v.split()) <= 5
                 and all(_PALABRA_NOMBRE_RE.match(p) for p in v.split())]
    if len(con_forma) < 0.9 * len(valores):
        return False, ""
    con_nombre = [v for v in con_forma if any(_sin_tildes(p) in NOMBRES_DE_PILA for p in v.split())]
    if len(con_nombre) < 0.6 * len(valores):
        return False, ""
    return True, f"{len(con_nombre)} de {len(valores)} valores son nombres de persona (p. ej. «{con_nombre[0]}»)"


def _es_lugar(valores: list) -> tuple[str | None, str]:
    from .gazetteer import buscar_lugar, normalizar
    if len(valores) < 3:
        return None, ""
    municipios = departamentos = 0
    ejemplo = ""
    for v in valores:
        r = buscar_lugar(v)
        # El lugar tiene que ser el valor entero, no una palabra suelta dentro.
        if not r or not r.get("exacto") or r.get("fragmento") != normalizar(v):
            continue
        ejemplo = ejemplo or v
        if r["nivel"] == "municipio":
            municipios += 1
        else:
            departamentos += 1
    encontrados = municipios + departamentos
    if encontrados < 0.7 * len(valores):
        return None, ""
    concepto = "city" if municipios >= departamentos else "region"
    que = "municipios" if concepto == "city" else "departamentos"
    return concepto, f"{encontrados} de {len(valores)} valores son {que} de Colombia (p. ej. «{ejemplo}»)"


def _es_entero(numeros: pd.Series) -> bool:
    return len(numeros) > 0 and bool((numeros % 1 == 0).all())


def _parece_documento(col, numeros: pd.Series) -> bool:
    """¿Cédula/NIT? Ir 1 a 1 con una columna de texto no basta: la meta de
    cada región, fija mes a mes, también lo hace. Lo que la distingue es la
    forma: un documento tiene de 6 a 11 dígitos y casi nunca termina en 000,
    una meta casi siempre. Los códigos cortos (101, 102) se dejan para que
    los confirme la persona."""
    from .abreviaturas import nombre_para_buscar
    from .performance import META_RE
    if META_RE.search(nombre_para_buscar(col)):
        return False
    distintos = numeros.nunique()
    if not _es_entero(numeros) or distintos < 3 or len(numeros) / distintos < 1.5:
        return False
    if not numeros.between(100_000, 99_999_999_999).all():
        return False
    return float((numeros.drop_duplicates() % 1000 == 0).mean()) <= 0.2


def _pareja_uno_a_uno(df: pd.DataFrame, col, textos: list):
    """La columna de texto con la que `col` va 1 a 1, si la hay."""
    for otra in textos:
        par = df[[col, otra]].dropna()
        if par.empty:
            continue
        if (par.groupby(col)[otra].nunique().max() == 1
                and par.groupby(otra)[col].nunique().max() == 1):
            return otra
    return None


def _fecha_en_numero(numeros: pd.Series):
    """(fechas, método, motivo) si el entero es una fecha de Excel o un AAAAMM."""
    if not _es_entero(numeros) or numeros.nunique() < 2:
        return None
    periodo = yyyymm_series(numeros)
    if periodo.notna().mean() >= 0.95 and periodo.dropna().dt.year.between(1990, 2049).all():
        return periodo, "yyyymm_period", "los valores son periodos AAAAMM (p. ej. «%d»)" % int(numeros.iloc[0])
    en_rango = numeros.between(32874, 54789)   # 1990-01-01 … 2049-12-31 como serie de Excel
    redondos = (numeros % 100 == 0).mean()
    if en_rango.mean() >= 0.95 and redondos < 0.3 and numeros.max() - numeros.min() <= 9200:
        fechas = excel_serial(numeros)
        ejemplo = fechas.dropna().iloc[0].strftime("%d/%m/%Y")
        return fechas, "excel_serial", f"los valores son fechas de Excel guardadas como número (p. ej. «{ejemplo}»)"
    return None


def completar_por_valores(df: pd.DataFrame, schema: dict, hay_periodo: bool = False) -> dict:
    """Asigna papel a las columnas sin decidir. Modifica `schema` (y `df` si
    convierte una fecha) y devuelve {columna: motivo} de lo que reconoció."""
    semantic = schema.get("semantic") if isinstance(schema.get("semantic"), dict) else {}
    items = {x.get("column"): x for x in semantic.get("columns", [])}
    tipos = schema["types"]

    def sin_decidir(c):
        sem = (items.get(c) or {}).get("semantic_type")
        return tipos.get(c) in _GENERICOS and sem in {None, "unknown"} and not str(c).startswith("_")

    def marcar_semantica(c, concepto, lista=None):
        if c in items:
            items[c]["semantic_type"] = concepto
        if lista is not None and c not in semantic.setdefault(lista, []):
            semantic[lista].append(c)

    def quitar_de_metricas(c):
        schema["metrics"] = [m for m in schema["metrics"] if m != c]
        if semantic.get("metrics"):
            semantic["metrics"] = [m for m in semantic["metrics"] if m != c]

    muestra = df.head(_MUESTRA_FILAS)
    motivos = {}
    textos = [c for c in df.columns if c not in schema["dates"] and c not in schema["metrics"]
              and not pd.api.types.is_numeric_dtype(df[c]) and not str(c).startswith("_")]

    for c in list(df.columns):
        if not sin_decidir(c):
            continue
        if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c]):
            numeros = pd.to_numeric(muestra[c], errors="coerce").dropna()
            if numeros.empty:
                continue
            # Venían escritos con % o con $ (core/cleaner lo anota al leerlos):
            # eso dice qué son aunque la columna se llame «Col8».
            formato = (df.attrs.get("formato_numeros") or {}).get(c)
            if formato in {"porcentaje", "moneda"}:
                tipos[c] = "Porcentaje" if formato == "porcentaje" else "Moneda"
                marcar_semantica(c, "percentage" if formato == "porcentaje" else "revenue")
                motivos[c] = ("Porcentaje: los valores venían escritos con «%»." if formato == "porcentaje"
                              else "Dinero: los valores venían escritos con signo de moneda.")
                continue
            # Fecha: solo si la hoja todavía no tiene ninguna.
            if not schema["dates"] and not hay_periodo:
                hallada = _fecha_en_numero(numeros)
                if hallada:
                    _, metodo, motivo = hallada
                    convertida = excel_serial(df[c]) if metodo == "excel_serial" else yyyymm_series(df[c])
                    df[c] = date_only(convertida)
                    quitar_de_metricas(c)
                    schema["dates"].append(c); tipos[c] = "Fecha"; schema["date_metadata"][c] = metodo
                    marcar_semantica(c, "date")
                    motivos[c] = f"Fecha: {motivo}."
                    continue
            # Documento: entero que se repite y va 1 a 1 con una columna de texto.
            if _parece_documento(c, numeros):
                pareja = _pareja_uno_a_uno(muestra, c, textos)
                if pareja is not None:
                    quitar_de_metricas(c)
                    if c not in schema["ids"]:
                        schema["ids"].append(c)
                    tipos[c] = "Identificador"
                    marcar_semantica(c, "id", "ids")
                    motivos[c] = (f"Código: cada valor corresponde siempre al mismo «{pareja}» "
                                  "y al revés, así que no se suma.")
            continue

        valores = _distintos(muestra[c])
        es_persona, motivo = _es_persona(valores)
        if es_persona:
            marcar_semantica(c, "name", "dimensions")
            if c not in schema["categorical"] and c not in schema.get("text", []):
                schema["categorical"].append(c)
            motivos[c] = f"Persona: {motivo}."
            continue
        concepto, motivo = _es_lugar(valores)
        if concepto:
            # Sin tocar la semántica a propósito: el mapa ya encuentra los
            # lugares por sus valores (core/geo_engine.columna_con_lugares), y
            # un tipo semántico «city» haría que la ciudad pasara por delante
            # del asesor como unidad de los diagnósticos (PRIORIDAD_DIMENSION),
            # cambiando qué dice el panel en archivos que hoy se leen bien.
            if c not in schema["geography"]:
                schema["geography"].append(c)
            if c not in schema["categorical"]:
                schema["categorical"].append(c)
            tipos[c] = "Geografía"
            motivos[c] = f"Lugar: {motivo}."

    if motivos:
        schema["por_valores"] = motivos
    return motivos
