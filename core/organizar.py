"""«🧹 Ordenar y corregir»: dejar el archivo en orden antes de analizarlo.

Al cargar, core/cleaner.py ya unifica lo que es el mismo dato escrito con
otras mayúsculas, espacios o tildes, y core/por_valores.py reconoce columnas
sin nombre por lo que traen. Lo que quedaba sin resolver:

- **Palabras mal escritas** («Medelin», «Barranqulla», «Clinete»): el panel
  las contaba como otro municipio, otro cliente u otro vendedor, y partía las
  cifras en filtros, rankings y mapa.
- **Columnas con un nombre que no dice lo que son** («Corte» con fechas,
  «Unnamed: 3», «Fceha»): la fecha no se leía, y sin fecha no hay tendencia,
  comparación ni proyección.
- **Fechas con celdas basura** («N/A», «pendiente»): la carga exige que el
  90 % se lea como fecha, así que la columna entera quedaba como texto.
- **Filas repetidas** (se avisaban, nunca se quitaban) y el **orden**.

Aquí solo se PROPONE: cada corrección lleva su motivo y la persona la aprueba.
Al aplicar, la tabla corregida se vuelve a leer con `profile_sheet` —la misma
lectura de cualquier archivo—, así que un nombre corregido («Fceha» → «Fecha»,
«Corte» → «Mes») hace que el resto del panel la reconozca solo.

Criterios para no «corregir» lo que está bien:
- Una variante es error solo si es la rara: el valor correcto tiene al menos
  el doble de filas. «Mario Gómez» y «María Gómez», con sus propias ventas,
  son dos personas.
- Nunca se juntan valores que difieren en números («Zona 1»/«Zona 2») o en
  una palabra de 1-2 letras («Talla S»/«Talla M»), dos nombres de pila
  distintos, ni dos municipios que existen.

Nada aquí depende de Streamlit; la pantalla es ui/organizar.py.
"""
from __future__ import annotations

import io
import re
import unicodedata
from difflib import SequenceMatcher, get_close_matches
from functools import lru_cache

import pandas as pd

from .columnas import aplicar_papeles, papel_actual
from .dates import is_month_name_series, leer_como_fecha
from .gazetteer import buscar_lugar, normalizar
from .por_valores import NOMBRES_DE_PILA, _fecha_en_numero

# ── Utilidades ────────────────────────────────────────────────────────────
_MAX_DISTINTOS = 5000        # más que esto en una columna de texto: es texto libre o un código
_MUESTRA_FECHA = 2000        # valores distintos con los que se prueba si una columna es fecha


def _visibles(df: pd.DataFrame) -> list:
    """Las columnas del archivo, sin las internas del motor (__periodo_analisis__…)."""
    return [c for c in df.columns if not str(c).startswith("_")]


def _sin_tildes(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto))
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def _clave(valor) -> str:
    """Texto comparable: sin tildes ni signos, en minúscula."""
    return normalizar(valor)


def _distancia(a: str, b: str, tope: int) -> int:
    """Letras que hay que cambiar, quitar, poner o voltear para pasar de a a b
    (Damerau-Levenshtein restringida). Corta en cuanto supera `tope`."""
    if abs(len(a) - len(b)) > tope:
        return tope + 1
    previa, actual = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        antes_previa, previa = previa, actual
        actual = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            costo = 0 if a[i - 1] == b[j - 1] else 1
            actual[j] = min(previa[j] + 1, actual[j - 1] + 1, previa[j - 1] + costo)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                actual[j] = min(actual[j], antes_previa[j - 2] + 1)
        if min(actual) > tope:
            return tope + 1
    return actual[-1]


def _con_estilo_de(modelo: str, texto: str) -> str:
    """`texto` con las mayúsculas de `modelo` («MEDELIN» → «MEDELLÍN»)."""
    if modelo.isupper():
        return texto.upper()
    if modelo.islower():
        return texto.lower()
    return texto


# ── 1. Nombres de columna ─────────────────────────────────────────────────
# Palabras de encabezado de un archivo de negocio, como deben escribirse.
_VOCABULARIO = [
    "fecha", "mes", "año", "día", "periodo", "semana", "trimestre",
    "venta", "ventas", "valor", "total", "precio", "costo", "costos", "cantidad", "unidades",
    "meta", "metas", "presupuesto", "objetivo", "cumplimiento", "margen", "utilidad", "descuento",
    "ingresos", "gastos", "comisión", "porcentaje", "saldo", "recaudo", "cartera",
    "municipio", "ciudad", "departamento", "región", "zona", "sucursal", "sede", "tienda", "barrio",
    "dirección", "país", "canal", "cliente", "clientes", "vendedor", "asesor", "agente", "supervisor",
    "jefe", "gerente", "coordinador", "producto", "productos", "referencia", "categoría", "línea",
    "marca", "código", "cédula", "documento", "nombre", "apellido", "apellidos", "teléfono", "celular",
    "correo", "estado", "tipo", "observaciones", "descripción", "pedido", "factura", "cargo", "área",
    "empresa", "proveedor", "bodega", "inventario", "existencias", "devoluciones", "número", "cuenta",
]
_VOCAB_CLAVE = {_sin_tildes(p).lower(): p for p in _VOCABULARIO}

_GENERICO_RE = re.compile(
    r"^(unnamed[:_ ]*\d*(_level_\d+)?|columna(_\d+)?|col(umna)?[ _.-]?\d+|campo[ _.-]?\d+|"
    r"column[ _.-]?\d+|field[ _.-]?\d+|f\d+|\d+)$", re.I)


def _es_generico(nombre) -> bool:
    return bool(_GENERICO_RE.match(str(nombre).strip()))


def _palabra_corregida(palabra: str) -> str | None:
    """La palabra del vocabulario que se quiso escribir, si es un error claro."""
    clave = _sin_tildes(palabra).lower()
    if len(clave) < 5 or clave in _VOCAB_CLAVE:
        return None
    cerca = get_close_matches(clave, list(_VOCAB_CLAVE), n=1, cutoff=0.8)
    if not cerca:
        return None
    buena = cerca[0]
    # Una palabra derivada no es un error: «Vendedora», «Regional», «Ventana».
    if clave.startswith(buena):
        return None
    # Una letra que falta al final sí («Cantida» → «Cantidad»), un plural no.
    if buena.startswith(clave) and (len(buena) - len(clave) > 1 or buena.endswith("s")):
        return None
    correcta = _VOCAB_CLAVE[buena]
    if palabra.isupper():
        return correcta.upper()
    if palabra[:1].isupper():
        return correcta[:1].upper() + correcta[1:]
    return correcta


def _nombre_corregido(nombre: str) -> tuple[str, list[str]] | None:
    """(nombre con las palabras corregidas, [«Fceha → Fecha», …]) o None."""
    cambios = []

    def cambiar(m):
        nueva = _palabra_corregida(m.group(0))
        if nueva:
            cambios.append(f"«{m.group(0)}» → «{nueva}»")
            return nueva
        return m.group(0)

    nuevo = re.sub(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", cambiar, nombre)
    return (nuevo, cambios) if cambios else None


def _nombre_por_papel(columna, schema: dict) -> str | None:
    """Un nombre para una columna sin nombre, según lo que se reconoció en ella."""
    papel = papel_actual(columna, schema)
    motivo = str((schema.get("por_valores") or {}).get(columna, ""))
    if papel == "Lugar":
        return "Departamento" if "departamento" in motivo else "Municipio"
    if papel == "Identificador":
        return "Documento" if "documento" in motivo.lower() or "cédula" in motivo.lower() else "Código"
    return {"Fecha": "Fecha", "Persona": "Nombre", "Dinero": "Valor", "Cantidad": "Cantidad",
            "Porcentaje": "Porcentaje", "Meta": "Meta"}.get(papel)


def _libre(nombre: str, usados: set) -> str:
    """`nombre`, o «nombre 2», «nombre 3»… si ya hay una columna que se llama así."""
    if nombre.lower() not in usados:
        return nombre
    n = 2
    while f"{nombre} {n}".lower() in usados:
        n += 1
    return f"{nombre} {n}"


def _ejemplos(serie: pd.Series, n: int = 3) -> str:
    if pd.api.types.is_datetime64_any_dtype(serie):
        valores = serie.dropna().drop_duplicates().head(n).dt.strftime("%d/%m/%Y").tolist()
    else:
        valores = serie.dropna().astype(str).str.strip()
        valores = valores[valores != ""].drop_duplicates().head(n).tolist()
    return ", ".join(str(v)[:30] for v in valores)


# ── 2. Fechas que no se estaban leyendo ───────────────────────────────────
def _fecha_escondida(serie: pd.Series) -> str | None:
    """Por qué esta columna (que hoy no es fecha) parece una fecha, o None."""
    x = serie.dropna()
    if not len(x):
        return None
    if pd.api.types.is_numeric_dtype(x) and not pd.api.types.is_bool_dtype(x):
        hallada = _fecha_en_numero(pd.to_numeric(x, errors="coerce").dropna())
        return hallada[2] if hallada else None
    texto = x.astype(str).str.strip()
    texto = texto[texto != ""]
    distintos = texto.drop_duplicates()
    if len(distintos) < 2 or is_month_name_series(distintos):
        return None   # meses escritos: se resuelven con el nombre «Mes» (ver _sugerir_nombres)
    muestra = distintos.head(_MUESTRA_FECHA)
    fechas, tasa, _ = leer_como_fecha(muestra)
    if fechas is None or tasa < 0.6 or fechas.dropna().nunique() < 2:
        return None
    # Pesado por filas, no por valores distintos: lo que se perdería al leerla.
    leidas = texto.isin(set(muestra[fechas.notna()]))
    pct = leidas.mean() if len(distintos) <= _MUESTRA_FECHA else tasa
    ejemplo = muestra[fechas.notna()].iloc[0]
    if pct >= 0.995:
        return f"todos sus valores son fechas (p. ej. «{ejemplo}»)"
    return (f"el {pct:.0%} de sus valores son fechas (p. ej. «{ejemplo}»); el resto "
            "(celdas como «N/A» o «pendiente») quedaría vacío")


def _fechas(df: pd.DataFrame, schema: dict) -> list[dict]:
    tipos = schema.get("types", {})
    salida = []
    for c in _visibles(df):
        if c in schema.get("dates", []) or tipos.get(c) in {"Mes", "Año"}:
            continue
        if c in schema.get("metrics", []) and papel_actual(c, schema) in {"Dinero", "Porcentaje", "Meta"}:
            continue   # una cifra con nombre de dinero no es una fecha aunque caiga en el rango
        motivo = _fecha_escondida(df[c])
        if motivo:
            salida.append({"columna": c, "motivo": motivo, "ejemplos": _ejemplos(df[c])})
    return salida


# ── 3. Nombres de columna (usa lo de fechas) ─────────────────────────────
def _sugerir_nombres(df: pd.DataFrame, schema: dict, fechas: list[dict]) -> list[dict]:
    visibles = _visibles(df)
    usados = {str(c).lower() for c in visibles}
    de_fecha = {f["columna"] for f in fechas}
    tipos = schema.get("types", {})
    hay_mes = any(tipos.get(c) == "Mes" for c in visibles) or "__periodo_analisis__" in df.columns
    hay_anio = any(tipos.get(c) == "Año" for c in visibles)
    filas = []
    sugerido_mes = None
    for c in visibles:
        nombre = str(c)
        nuevo, motivo = None, ""
        serie = df[c]
        distintos = serie.dropna().astype(str).str.strip().drop_duplicates()
        es_texto = not (pd.api.types.is_numeric_dtype(serie) or pd.api.types.is_datetime64_any_dtype(serie))
        if not hay_mes and sugerido_mes is None and es_texto and len(distintos) \
                and is_month_name_series(distintos):
            nuevo, motivo = "Mes", "trae meses escritos («enero», «feb»…): con el nombre «Mes» se lee como periodo"
            sugerido_mes = c
        elif _es_generico(nombre):
            propuesto = "Fecha" if c in de_fecha else _nombre_por_papel(c, schema)
            if propuesto:
                nuevo, motivo = propuesto, f"el encabezado «{nombre}» no dice nada; por sus valores es {propuesto.lower()}"
            else:
                motivo = f"el encabezado «{nombre}» no dice qué es: ponle un nombre"
        else:
            corregido = _nombre_corregido(nombre)
            if corregido:
                nuevo, motivo = corregido[0], "parece mal escrito: " + ", ".join(corregido[1])
        if nuevo and nuevo.lower() != nombre.lower():
            usados.discard(nombre.lower())
            nuevo = _libre(nuevo, usados)
            usados.add(nuevo.lower())
        filas.append({"columna": c, "nuevo": nuevo or nombre, "motivo": motivo,
                      "sugerido": bool(motivo), "ejemplos": _ejemplos(serie)})
    # Un año suelto junto a los meses: «Corte» = 2024, 2025 → «Año».
    if sugerido_mes is not None and not hay_anio:
        for fila in filas:
            c = fila["columna"]
            numeros = _anios(df[c])
            if fila["sugerido"] or c == sugerido_mes or not len(numeros) or numeros.nunique() > 30:
                continue
            if (numeros % 1 == 0).all() and numeros.between(1990, 2100).mean() >= 0.95 \
                    and numeros.notna().sum() >= 0.9 * df[c].notna().sum():
                fila.update(nuevo=_libre("Año", usados), sugerido=True,
                            motivo="trae años (p. ej. «%d»); con el nombre «Año» se juntan con los meses" % int(numeros.iloc[0]))
                break
    return filas


def _anios(serie: pd.Series) -> pd.Series:
    """Los valores como número de año. Un año suelto («2024») a veces se lee
    como fecha (1 de enero): también cuenta."""
    if pd.api.types.is_datetime64_any_dtype(serie):
        f = serie.dropna()
        return f.dt.year if len(f) and ((f.dt.month == 1) & (f.dt.day == 1)).all() else f.iloc[:0]
    return pd.to_numeric(serie, errors="coerce").dropna()


# ── 4. Palabras mal escritas ──────────────────────────────────────────────
def _parecidos(a: str, b: str, es_persona: bool) -> tuple[bool, bool]:
    """(¿son el mismo dato mal escrito?, ¿es un caso claro?) para dos claves."""
    if re.sub(r"\D", "", a) != re.sub(r"\D", "", b):
        return False, False          # «Zona 1» / «Zona 2»
    pa, pb = a.split(), b.split()
    if sorted(pa) == sorted(pb):
        return True, True            # «Pérez Juan» / «Juan Pérez»
    largo = min(len(a), len(b))
    tope = 1 if largo <= 6 else 2 if largo <= 12 else 3
    if abs(len(a) - len(b)) > tope or SequenceMatcher(None, a, b).quick_ratio() < 0.75:
        return False, False
    if _distancia(a, b, tope) > tope:
        return False, False
    if len(pa) != len(pb):
        # «Barran quilla» / «Barranquilla»: solo un espacio de más o de menos.
        return (_distancia(a.replace(" ", ""), b.replace(" ", ""), 1) <= 1), False
    if len(pa) == len(pb):
        distintas = [(x, y) for x, y in zip(pa, pb) if x != y]
        # Cada palabra distinta, con un error pequeño, no otra palabra:
        # «Peres»/«Pérez» sí; «Carla»/«Laura» o «Ana»/«Carla», no.
        if any(_distancia(x, y, 2) > (1 if min(len(x), len(y)) <= 6 else 2) for x, y in distintas):
            return False, False
        # «Talla S» / «Talla M», «Tipo A» / «Tipo B»: no es un error.
        if any(min(len(x), len(y)) <= 2 for x, y in distintas):
            return False, False
        # «María» / «Mario»: dos nombres de pila son dos personas.
        if any(x in NOMBRES_DE_PILA and y in NOMBRES_DE_PILA for x, y in distintas):
            return False, False
        # «Activo» / «Activa», «Niño» / «Niña»: puede ser a propósito; se
        # propone, pero sin marcar.
        if len(distintas) == 1 and distintas[0][0][:-1] == distintas[0][1][:-1] \
                and {distintas[0][0][-1], distintas[0][1][-1]} <= {"a", "o"}:
            return True, False
    return True, True


@lru_cache(maxsize=20000)
def _lugar_oficial(valor: str) -> str | None:
    """El municipio que se quiso escribir, si `valor` entero es uno mal escrito."""
    r = buscar_lugar(valor)
    if not r or r.get("exacto") or r.get("nivel") != "municipio":
        return None
    clave, oficial = _clave(valor), _clave(r["lugar"])
    if len(clave.split()) != len(oficial.split()) or SequenceMatcher(None, clave, oficial).ratio() < 0.85:
        return None
    return r["lugar"]


@lru_cache(maxsize=20000)
def _es_lugar_real(valor: str) -> bool:
    r = buscar_lugar(valor)
    return bool(r and r.get("exacto") and r.get("fragmento") == _clave(valor))


def _columnas_de_texto(df: pd.DataFrame, schema: dict) -> list:
    tipos = schema.get("types", {})
    excluir = set(schema.get("ids", [])) | set(schema.get("emails", [])) | set(schema.get("dates", []))
    salida = []
    for c in _visibles(df):
        if c in excluir or tipos.get(c) in {"Mes", "Año", "Identificador", "Booleano"}:
            continue
        if not (pd.api.types.is_object_dtype(df[c]) or pd.api.types.is_string_dtype(df[c])):
            continue
        # «Texto» también: asesores o productos con muchos valores distintos
        # quedan como texto. Lo que no entra es el texto libre (observaciones):
        # frases largas que casi nunca se repiten.
        if tipos.get(c) == "Texto" or c in schema.get("text", []):
            muestra = df[c].dropna().astype(str).head(2000)
            if not len(muestra) or muestra.str.len().median() > 40:
                continue
        salida.append(c)
    return salida


def _errores_columna(serie: pd.Series, es_lugar: bool, es_persona: bool) -> list[dict]:
    texto = serie.dropna().astype(str).str.strip()
    conteo = texto[texto != ""].value_counts()
    if len(conteo) < 2 or len(conteo) > _MAX_DISTINTOS:
        return []
    valores = list(conteo.index)
    claves = {v: _clave(v) for v in valores}
    por_clave = {k: v for v, k in reversed(list(claves.items()))}   # la forma más frecuente de cada clave
    canonicos: list[str] = []
    propuestas = []
    for v in valores:
        k, filas = claves[v], int(conteo[v])
        destino, claro = None, False
        if len(k) >= 4 and not (es_lugar and _es_lugar_real(v)):
            for c in canonicos:
                if int(conteo[c]) < 2 * filas:
                    break                      # los siguientes tienen aún menos filas
                if es_lugar and _es_lugar_real(c) is False and _lugar_oficial(c):
                    continue                   # el «correcto» también está mal escrito
                iguales, claro = _parecidos(k, claves[c], es_persona)
                if iguales:
                    destino = c
                    claro = claro and int(conteo[c]) >= 5 * filas
                    break
        if destino is None and es_lugar:
            oficial = _lugar_oficial(v)
            if oficial:
                destino = por_clave.get(_clave(oficial)) or _con_estilo_de(v, oficial)
                claro = True
                motivo = f"«{oficial}» es el nombre oficial del municipio"
        else:
            motivo = (f"se parece a «{destino}», que aparece en {int(conteo[destino]):,} filas"
                      if destino is not None else "")
        if destino is None or destino == v:
            canonicos.append(v)
            continue
        propuestas.append({"valor": v, "filas": filas, "corregir_a": destino, "motivo": motivo,
                           "marcado": claro})
    return propuestas


def _errores(df: pd.DataFrame, schema: dict) -> list[dict]:
    geo = set(schema.get("geography", []))
    salida = []
    for c in _columnas_de_texto(df, schema):
        papel = papel_actual(c, schema)
        for p in _errores_columna(df[c], es_lugar=c in geo or papel == "Lugar", es_persona=papel == "Persona"):
            salida.append({"columna": c, **p})
    return salida


# ── 5. Filas repetidas y orden ────────────────────────────────────────────
def filas_repetidas(df: pd.DataFrame) -> int:
    visibles = _visibles(df)
    return int(df[visibles].duplicated().sum()) if visibles else 0


def _orden_columnas(df: pd.DataFrame, schema: dict, de_tiempo=()) -> list:
    """Fechas, luego quién/dónde/qué (códigos, personas, lugares, categorías),
    luego texto y al final las cifras. Dentro de cada grupo, el orden del
    archivo: así la métrica principal sigue siendo la misma. `de_tiempo`: las
    que van a pasar a ser fecha, mes o año con esta misma corrección."""
    def grupo(c):
        if c in schema.get("dates", []) or schema.get("types", {}).get(c) in {"Mes", "Año"} or c in de_tiempo:
            return 0
        if c in schema.get("metrics", []):
            return 4
        if c in schema.get("text", []):
            return 3
        if c in schema.get("ids", []):
            return 1
        return 2
    visibles = _visibles(df)
    return sorted(visibles, key=lambda c: (grupo(c), visibles.index(c)))


def _orden_filas(df: pd.DataFrame, schema: dict) -> list:
    """Por la primera fecha y, dentro, por la primera categoría."""
    claves = [c for c in schema.get("dates", []) if c in df.columns and not str(c).startswith("_")][:1]
    claves += [c for c in schema.get("categorical", []) if c in df.columns and not str(c).startswith("_")
               and c not in claves][:1]
    return claves


# ── Lo que se le muestra a la persona ─────────────────────────────────────
def revisar(df: pd.DataFrame, schema: dict) -> dict:
    """Todo lo que se puede ordenar o corregir en la hoja, con su motivo.

    {"nombres": [{columna, nuevo, motivo, sugerido, ejemplos}],   # una fila por columna
     "fechas": [{columna, motivo, ejemplos}],
     "errores": [{columna, valor, filas, corregir_a, motivo, marcado}],
     "repetidas": int, "orden": {"columnas": [...], "filas": [...], "cambia": bool}}
    """
    fechas = _fechas(df, schema)
    columnas = _orden_columnas(df, schema)
    por = _orden_filas(df, schema)
    cambia = columnas != _visibles(df)
    if por and not cambia:
        ordenada = df[por].sort_values(por, kind="stable", na_position="last")
        cambia = not ordenada.index.equals(df.index)
    return {
        "nombres": _sugerir_nombres(df, schema, fechas),
        "fechas": fechas,
        "errores": _errores(df, schema),
        "repetidas": filas_repetidas(df),
        "orden": {"columnas": columnas, "filas": por, "cambia": bool(cambia)},
    }


# ── Aplicar ───────────────────────────────────────────────────────────────
def aplicar(df: pd.DataFrame, schema: dict, *, nombres: dict | None = None, fechas: list | None = None,
            valores: dict | None = None, quitar_repetidas: bool = False,
            ordenar: bool = False) -> tuple[pd.DataFrame, list[str]]:
    """La tabla corregida (sin columnas internas, lista para volver a leerse)
    y la lista de lo que se hizo, en palabras.

    nombres: {columna: nombre nuevo}; fechas: [columnas a leer como fecha];
    valores: {columna: {valor escrito: valor correcto}}.
    """
    nombres, fechas, valores = nombres or {}, fechas or [], valores or {}
    tabla = df[_visibles(df)].copy()
    hecho = []

    corregidos = 0
    for c, cambios in valores.items():
        if c not in tabla.columns or not cambios:
            continue
        texto = tabla[c].astype("string").str.strip()
        mascara = texto.isin(list(cambios))
        if mascara.any():
            tabla.loc[mascara, c] = texto[mascara].map(cambios).astype(object)
            corregidos += int(mascara.sum())
    if corregidos:
        n = sum(len(v) for v in valores.values())
        hecho.append(f"{n} palabra(s) mal escrita(s) corregida(s) en {corregidos:,} celdas.")

    for c in fechas:
        if c not in tabla.columns or pd.api.types.is_datetime64_any_dtype(tabla[c]):
            continue
        convertidas, tasa, _ = leer_como_fecha(tabla[c])
        if convertidas is None:
            raise ValueError(f"«{c}» no se pudo leer como fecha.")
        tabla[c] = convertidas
        perdidas = int(df[c].notna().sum() - convertidas.notna().sum())
        hecho.append(f"«{c}» leída como fecha" + (f" ({perdidas:,} celda(s) que no eran fecha quedaron vacías)."
                                                 if perdidas > 0 else "."))

    if quitar_repetidas:
        antes = len(tabla)
        tabla = tabla.drop_duplicates()
        if len(tabla) < antes:
            hecho.append(f"{antes - len(tabla):,} fila(s) repetida(s) quitada(s).")

    if ordenar:
        de_tiempo = set(fechas) | {c for c, n in nombres.items()
                                   if re.match(r"^(fecha|mes|año|ano|periodo)(\s|$)", str(n).strip(), re.I)}
        columnas = [c for c in _orden_columnas(df, schema, de_tiempo) if c in tabla.columns]
        por = [c for c in _orden_filas(df, schema) if c in tabla.columns]
        tabla = tabla[columnas]
        if por:
            tabla = tabla.sort_values(por, kind="stable", na_position="last")
        tabla = tabla.reset_index(drop=True)
        hecho.append("Columnas ordenadas (fechas, datos, cifras)" + (f" y filas por «{por[0]}»." if por else "."))

    renombrar = {c: str(n).strip() for c, n in nombres.items()
                 if c in tabla.columns and str(n).strip() and str(n).strip() != str(c)}
    for c, n in renombrar.items():
        # Un año que se había leído como fecha (1 de enero) vuelve a ser el
        # número: así lo espera la lectura de «Mes» + «Año».
        if re.match(r"^(año|ano|year)(\s|$)", n, re.I) and pd.api.types.is_datetime64_any_dtype(tabla[c]):
            tabla[c] = tabla[c].dt.year.astype("Int64")
    finales = [renombrar.get(c, str(c)) for c in tabla.columns]
    repetidos = {n for n in finales if finales.count(n) > 1}
    if repetidos:
        raise ValueError("Dos columnas quedarían con el mismo nombre: " + ", ".join(f"«{n}»" for n in repetidos) + ".")
    if renombrar:
        tabla = tabla.rename(columns=renombrar)
        hecho.append("Columnas renombradas: " + ", ".join(f"«{a}» → «{b}»" for a, b in renombrar.items()) + ".")
    return tabla, hecho


def volver_a_leer(tabla: pd.DataFrame, item: dict, contexto: dict, nombres: dict | None = None,
                  hecho: list | None = None) -> dict:
    """La hoja corregida leída de nuevo como cualquier archivo, conservando lo
    que la persona ya había indicado en «🔎 Columnas» (con los nombres nuevos)."""
    from .profile import profile_sheet

    esquema_viejo = item["profile"]["schema"]
    metricas = [c for c in esquema_viejo.get("metrics", []) if c in item["processed"].columns]
    # En un informe una celda vacía es «no reportado», no cero (core/informe.py):
    # si las cifras traían vacíos, así se cargó la hoja.
    faltantes_son_cero = not any(item["processed"][c].isna().any() for c in metricas)
    nuevo = profile_sheet(tabla, context={**contexto, "faltantes_son_cero": faltantes_son_cero},
                          structural_log=["Ordenado y corregido: " + " ".join(hecho or [])] if hecho else None)
    papeles = {(nombres or {}).get(c, c): p for c, p in (esquema_viejo.get("papeles_usuario") or {}).items()}
    papeles = {c: p for c, p in papeles.items() if c in nuevo["processed"].columns}
    if papeles:
        try:
            df2, schema2 = aplicar_papeles(nuevo["processed"], nuevo["profile"]["schema"], papeles)
            nuevo["processed"], nuevo["profile"]["schema"] = df2, schema2
        except ValueError:
            pass   # la corrección vieja ya no aplica a la columna corregida
    return nuevo


def a_excel(df: pd.DataFrame, hoja: str = "Datos") -> bytes:
    """La tabla en un Excel, con los encabezados en negrilla y anchos legibles."""
    from openpyxl.styles import Font

    tabla = df[_visibles(df)]
    salida = io.BytesIO()
    with pd.ExcelWriter(salida, engine="openpyxl") as escritor:
        nombre = re.sub(r"[\[\]:*?/\\]", " ", str(hoja))[:31] or "Datos"
        tabla.to_excel(escritor, index=False, sheet_name=nombre)
        ws = escritor.sheets[nombre]
        for celda in ws[1]:
            celda.font = Font(bold=True)
        ws.freeze_panes = "A2"
        for i, c in enumerate(tabla.columns, start=1):
            muestra = tabla[c].head(200).astype(str).str.len()
            ancho = max(len(str(c)), int(muestra.max()) if len(muestra) else 0)
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(max(10, ancho + 2), 45)
            if pd.api.types.is_datetime64_any_dtype(tabla[c]):
                for fila in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                    fila[0].number_format = "DD/MM/YYYY"
    return salida.getvalue()
