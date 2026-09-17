"""Imágenes pegadas en el Excel: leerlas con OCR local y convertirlas en tablas.

Los informes comerciales pegan capturas de Power BI —un ranking de jefes por
mes, un gráfico de productividad—, y una imagen no trae números: el panel
solo podía avisar que existía. Aquí se leen con **RapidOCR**, que corre en el
mismo equipo o servidor del panel, con los modelos incluidos en el paquete:
la imagen no sale a ningún servicio externo, ni para leerla ni para
descargar nada.

El OCR solo devuelve textos y dónde están. Lo que convierte eso en una tabla
correcta está aquí, y se apoya en posiciones, no en el orden de lectura:

- **Tabla** (meses en una fila, un nombre por fila): cada número va a la
  columna cuyo mes tiene encima. Así una celda vacía queda vacía en vez de
  correr los valores al mes siguiente, que es el error típico de un OCR
  leído "de corrido".
- **Gráfico de líneas con etiquetas**: cada número va al mes del eje que
  tiene debajo, y a la serie cuya línea (por su color en la leyenda) pasa
  más cerca de él.

Nada de lo que sale de aquí se analiza a ciegas: la interfaz muestra la
tabla junto a la imagen para revisarla y corregirla antes de usarla
(`ui/imagenes.py`), y cada resultado trae sus avisos de celdas dudosas.

Dos hallazgos de probar con imágenes reales, que explican dos decisiones:

- El clasificador de orientación del OCR voltea textos cortos: "90 %" salía
  como "% 06", y "% 06" se leía como 6. Se apaga; en una captura de pantalla
  nada viene girado. OJO: la opción se llama distinto según la versión de
  RapidOCR (`use_angle_cls` en 1.2, `use_cls` en 1.3+), y apagar solo una
  dejó el giro activo en 1.4.4 sin ningún error: un informe real salió con
  "6" donde la imagen decía "90 %". Por eso hay tres defensas, no una:
  apagarlo en todas las formas (`_motor`, `_pasada`), releer cualquier cifra
  con el "%" delante (`_corregir_giradas`) y revisar la coherencia de la
  tabla contra su columna Total y contra los demás meses de cada fila
  (`_revisar_coherencia`), marcando para revisión lo que no cuadra.
- El modelo de reconocimiento pierde los espacios en mayúsculas
  ("CASTILLONAARJACKALVARO") y la Ñ. Los nombres se restauran contra los
  textos que ya existen en el libro (`vocabulario`), si coinciden.
"""
from __future__ import annotations

import difflib
import hashlib
import io
import posixpath
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from functools import lru_cache
from typing import Optional

import numpy as np
import pandas as pd

from .informe import _es_total, _relaciones, periodo_de

_XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

ESCALA = 2            # ampliar la imagen antes de leer mejora las cifras pequeñas
CONFIANZA_DUDOSA = 0.6
_NUMERO_RE = re.compile(r"[-+]?\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|[-+]?\d+(?:[.,]\d+)?")
_MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


# ── Disponibilidad ──────────────────────────────────────────────────────────

def disponible() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def _motor():
    from rapidocr_onnxruntime import RapidOCR
    motor = RapidOCR()
    # Ver el docstring del módulo: el clasificador voltea "90 %" a "% 06".
    # El nombre de la opción cambia entre versiones: se apagan todos.
    for atributo in ("use_angle_cls", "use_cls"):
        if hasattr(motor, atributo):
            setattr(motor, atributo, False)
    return motor


@lru_cache(maxsize=1)
def _acepta_use_cls() -> bool:
    import inspect
    try:
        return "use_cls" in inspect.signature(_motor().__call__).parameters
    except (TypeError, ValueError):
        return False


def _ejecutar(arr):
    """Llama al OCR con el giro apagado también en la llamada, si la versión lo permite."""
    if _acepta_use_cls():
        return _motor()(arr, use_cls=False)
    return _motor()(arr)


# ── Imágenes del libro ──────────────────────────────────────────────────────

def imagenes_del_libro(data: bytes) -> list[dict]:
    """Cada imagen pegada en un .xlsx/.xlsm: hoja, fila donde empieza y sus bytes."""
    salida = []
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return salida
    if "xl/workbook.xml" not in z.namelist():
        return salida
    rels_libro = {rid: destino for rid, _, destino in _relaciones(z, "xl/workbook.xml")}
    libro = ET.fromstring(z.read("xl/workbook.xml"))
    for hoja in libro.iter(f"{{{_S}}}sheet"):
        parte = rels_libro.get(hoja.get(f"{{{_R}}}id"))
        if not parte or parte not in z.namelist():
            continue
        for _, tipo, dibujo in _relaciones(z, parte):
            if not tipo.endswith("/drawing") or dibujo not in z.namelist():
                continue
            medios = {rid: destino for rid, t, destino in _relaciones(z, dibujo) if t.endswith("/image")}
            raiz = ET.fromstring(z.read(dibujo))
            for ancla in list(raiz.iter(f"{{{_XDR}}}twoCellAnchor")) + list(raiz.iter(f"{{{_XDR}}}oneCellAnchor")):
                pic = ancla.find(f"{{{_XDR}}}pic")
                blip = pic.find(f".//{{{_A}}}blip") if pic is not None else None
                destino = medios.get(blip.get(f"{{{_R}}}embed")) if blip is not None else None
                if not destino or destino not in z.namelist():
                    continue
                fila = ancla.find(f"{{{_XDR}}}from/{{{_XDR}}}row")
                contenido = z.read(destino)
                salida.append({
                    "hoja": hoja.get("name"),
                    "fila": int(fila.text) if fila is not None and (fila.text or "").isdigit() else 0,
                    "archivo": posixpath.basename(destino),
                    "bytes": contenido,
                    "id": hashlib.sha1(contenido).hexdigest()[:12],
                })
    return salida


# ── Lectura ─────────────────────────────────────────────────────────────────

def _imagen_rgb(contenido: bytes):
    from PIL import Image
    return Image.open(io.BytesIO(contenido)).convert("RGB")


def _pasada(img, escala: float) -> list[dict]:
    from PIL import Image
    arr = np.array(img.resize((int(img.width * escala), int(img.height * escala)), Image.LANCZOS)) if escala != 1 else np.array(img)
    resultado, _ = _ejecutar(arr)
    textos = []
    for caja, texto, score in resultado or []:
        xs = [p[0] / escala for p in caja]
        ys = [p[1] / escala for p in caja]
        texto = str(texto).strip()
        if not texto:
            continue
        textos.append({"texto": texto, "x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys),
                       "cx": (min(xs) + max(xs)) / 2, "cy": (min(ys) + max(ys)) / 2,
                       "h": max(ys) - min(ys), "score": float(score)})
    return textos


def leer_textos(contenido: bytes) -> list[dict]:
    """Los textos de la imagen con su caja, en coordenadas de la imagen original.

    Se lee dos veces, ampliada y a tamaño original, y se suman los textos que
    una pasada vio y la otra no. Con el gráfico real, cada pasada sola se
    saltaba una o dos etiquetas (el 7,6 de noviembre, el 255 de agosto) y
    no siempre las mismas.
    """
    img = _imagen_rgb(contenido)
    textos = _pasada(img, ESCALA)
    for t in _pasada(img, 1):
        repetido = any(o["x0"] - 3 <= t["cx"] <= o["x1"] + 3 and o["y0"] - 3 <= t["cy"] <= o["y1"] + 3
                       for o in textos)
        if not repetido:
            textos.append(t)
    return _corregir_giradas(img, textos)


_GIRADA_RE = re.compile(r"^\s*%\s*[\d.,]+\s*$")
_NORMAL_RE = re.compile(r"^\s*[-+]?[\d.,]+\s*%?\s*$")


def _corregir_giradas(img, textos: list[dict]) -> list[dict]:
    """Relee las cifras que salieron con el "%" delante ("% 06"): son lecturas giradas.

    Nadie escribe "% 90" en un informe; si aparece, el OCR leyó "90 %" al
    revés y la cifra (06) es falsa. Se recorta esa celda, se amplía y se lee
    sola. Si aun así no queda en su forma normal, la celda NO se adivina: se
    marca como ilegible para que quede vacía y se revise contra la imagen.
    """
    from PIL import Image
    for t in textos:
        if not _GIRADA_RE.match(t["texto"]):
            continue
        margen = 6
        caja = (int(max(0, t["x0"] - margen)), int(max(0, t["y0"] - margen)),
                int(min(img.width, t["x1"] + margen)), int(min(img.height, t["y1"] + margen)))
        recorte = img.crop(caja)
        recorte = recorte.resize((recorte.width * 4, recorte.height * 4), Image.LANCZOS)
        fondo = Image.new("RGB", (recorte.width + 80, recorte.height + 80), recorte.getpixel((0, 0)))
        fondo.paste(recorte, (40, 40))
        try:
            resultado, _ = _ejecutar(np.array(fondo))
        except Exception:
            resultado = None
        leido = " ".join(str(r[1]).strip() for r in (resultado or []))
        if leido and _NORMAL_RE.match(leido) and _numero(leido) is not None:
            t["texto"], t["releida"] = leido, True
        else:
            t["ilegible"] = t["texto"]
            t["texto"] = ""
    return textos


def _numero(texto: str) -> Optional[float]:
    """"77 %" → 77, "7,7" → 7.7, "1.234" → 1234. None si no es una cifra."""
    t = texto.replace("%", "").replace(" ", "").strip()
    if not t or not re.fullmatch(r"[-+]?[\d.,]+", t):
        return None
    if re.fullmatch(r"[-+]?\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    elif "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _filas_de_texto(textos: list[dict]) -> list[list[dict]]:
    """Agrupa los textos en renglones por su altura en la imagen."""
    if not textos:
        return []
    alto = float(np.median([t["h"] for t in textos])) or 10.0
    filas: list[list[dict]] = []
    for t in sorted(textos, key=lambda x: x["cy"]):
        if filas and abs(t["cy"] - np.mean([x["cy"] for x in filas[-1]])) <= alto * 0.55:
            filas[-1].append(t)
        else:
            filas.append([t])
    return [sorted(f, key=lambda x: x["cx"]) for f in filas]


def _clave(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).upper()
    return re.sub(r"[^A-Z0-9]", "", t)


def restaurar_nombre(texto: str, vocabulario: Optional[dict]) -> str:
    """"CASTILLONAARJACKALVARO" → "CASTILLO NAAR JACK ALVARO", si el libro ya trae ese nombre."""
    if not vocabulario:
        return texto
    clave = _clave(texto)
    if clave in vocabulario:
        return vocabulario[clave]
    parecidos = difflib.get_close_matches(clave, list(vocabulario), n=1, cutoff=0.88)
    return vocabulario[parecidos[0]] if parecidos else texto


def vocabulario_de(tablas) -> dict:
    """{clave sin espacios ni tildes: texto original} con los textos de todas las tablas del libro."""
    vocab = {}
    for df in tablas:
        if not isinstance(df, pd.DataFrame):
            continue
        for c in df.columns:
            s = df[c]
            if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s):
                continue
            for v in s.dropna().astype(str).unique()[:5000]:
                v = re.sub(r"\s+", " ", v).strip()
                if len(v) >= 6 and re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", v):
                    vocab.setdefault(_clave(v), v)
    return vocab


def _anio(texto) -> Optional[int]:
    m = re.fullmatch(r"(19|20)\d{2}", texto.strip())
    return int(texto) if m else None


def _mes_de_texto(texto: str) -> Optional[int]:
    """Mes de "Oct", "09.", "septi...", "enero"."""
    t = texto.strip().lower().rstrip(".").replace("…", "").rstrip(".")
    m = re.fullmatch(r"(\d{1,2})", t)
    if m and 1 <= int(m.group(1)) <= 12:
        return int(m.group(1))
    p = periodo_de(t[:10])
    if p:
        return p[1]
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    for i, corto in enumerate(_MESES_CORTOS, 1):
        if len(t) >= 3 and t.startswith(corto):
            return i
    if t.startswith("set"):
        return 9
    return None


def _asignar_anios(meses: list[int], anios_vistos: list[int], anio_por_defecto: Optional[int]) -> list[Optional[int]]:
    """Años de una secuencia de meses: el primero visto, y +1 cada vez que el mes vuelve a empezar."""
    inicio = anios_vistos[0] if anios_vistos else anio_por_defecto
    if inicio is None:
        return [None] * len(meses)
    salida, anio = [], inicio
    for i, m in enumerate(meses):
        if i and m < meses[i - 1]:
            anio += 1
        salida.append(anio)
    return salida


def _etiqueta_mes(anio, mes) -> str:
    return f"{_MESES_CORTOS[mes - 1]} {anio}" if anio else _MESES_CORTOS[mes - 1]


# ── Tablas ──────────────────────────────────────────────────────────────────

def interpretar_tabla(textos: list[dict], vocabulario=None, anio_por_defecto=None) -> Optional[dict]:
    """Una tabla con meses en una fila y un rótulo por fila, o None si no lo es."""
    filas = _filas_de_texto(textos)
    encabezado = None
    for i, fila in enumerate(filas):
        meses = [t for t in fila if _mes_de_texto(t["texto"]) and not _numero(t["texto"])]
        if len(meses) >= 3:
            encabezado = i
            break
    if encabezado is None:
        return None

    fila_h = filas[encabezado]
    columnas_mes = [t for t in fila_h if _mes_de_texto(t["texto"]) and not _numero(t["texto"])]
    primer_x = min(t["x0"] for t in columnas_mes)
    rotulo = next((t["texto"] for t in fila_h if t["cx"] < primer_x and re.search("[A-Za-z]", t["texto"])), None)
    # Columnas de la derecha que no son meses ("Total"): se leen aparte para no
    # confundir sus cifras con las del último mes.
    extras = [t for t in fila_h if t["cx"] > max(c["cx"] for c in columnas_mes) and re.search("[A-Za-z]", t["texto"])]
    # Algunas etiquetas del encabezado quedan en el renglón de arriba (Total, Año).
    if encabezado > 0:
        extras += [t for t in filas[encabezado - 1]
                   if t["cx"] > max(c["cx"] for c in columnas_mes) and re.search("[A-Za-z]", t["texto"])]
    anios = []
    for k in (1, 2):
        if encabezado - k >= 0:
            anios += [(t["cx"], _anio(t["texto"])) for t in filas[encabezado - k] if _anio(t["texto"])]
    anios = [a for _, a in sorted(anios)]
    meses = [_mes_de_texto(t["texto"]) for t in columnas_mes]
    anios_col = _asignar_anios(meses, anios, anio_por_defecto)
    etiquetas = [_etiqueta_mes(a, m) for a, m in zip(anios_col, meses)]
    anclas = [(t["cx"], etiquetas[i]) for i, t in enumerate(columnas_mes)]
    anclas += [(t["cx"], t["texto"].strip().title()) for t in extras]
    anclas.sort()
    paso = float(np.median(np.diff([a for a, _ in anclas]))) if len(anclas) > 1 else 80.0
    limite_rotulo = min(a for a, _ in anclas) - paso * 0.55

    registros, dudas, total = [], [], None
    ilegibles = []
    for fila in filas[encabezado + 1:]:
        for t in fila:
            if t.get("ilegible") and t["cx"] >= limite_rotulo:
                cx, col = min(anclas, key=lambda a: abs(a[0] - t["cx"]))
                ilegibles.append((t["cy"], col, t["ilegible"]))
        nombre = " ".join(t["texto"] for t in fila if t["cx"] < limite_rotulo and re.search("[A-Za-zÁÉÍÓÚÑ]", t["texto"]))
        valores = {}
        for t in fila:
            if t["cx"] < limite_rotulo:
                continue
            v = _numero(t["texto"])
            if v is None:
                continue  # íconos, "%" suelto
            cx, col = min(anclas, key=lambda a: abs(a[0] - t["cx"]))
            if abs(cx - t["cx"]) > paso * 0.6:
                continue
            if col not in valores or t["score"] > valores[col][1]:
                valores[col] = (v, t["score"], "%" in t["texto"])
        if not nombre and not valores:
            continue
        if nombre and not valores and registros:
            # Un nombre largo partido en dos renglones ("GUARNIZO SOTOMAYOR PAOLA" / "ALEXANDRA").
            registros[-1]["nombre"] += " " + nombre
            continue
        if not nombre and registros:
            for col, dato in valores.items():  # "101" en un renglón y "%" en el siguiente
                registros[-1]["valores"].setdefault(col, dato)
            continue
        registro = {"nombre": nombre, "valores": valores, "cy": float(np.mean([t["cy"] for t in fila]))}
        if _es_total(nombre):
            total = registro
        else:
            registros.append(registro)
    if len(registros) < 2:
        return None

    columnas = [e for _, e in anclas]
    porcentaje = np.mean([d[2] for r in registros for d in r["valores"].values()] or [0]) > 0.5
    filas_tabla = []
    for r in registros:
        nombre_ocr = r["nombre"]
        nombre = restaurar_nombre(nombre_ocr, vocabulario)
        fila = {"_nombre": nombre}
        for col in columnas:
            dato = r["valores"].get(col)
            fila[col] = dato[0] if dato else np.nan
            if dato and dato[1] < CONFIANZA_DUDOSA:
                dudas.append(f"{nombre} · {col}: se leyó {dato[0]:g} con poca seguridad")
        filas_tabla.append(fila)
    ancha = pd.DataFrame(filas_tabla)
    # Celdas que el OCR leyó giradas y no se pudieron releer: vacías y marcadas.
    for cy, col, texto in ilegibles:
        fila_cercana = min(range(len(registros)), key=lambda i: abs(registros[i]["cy"] - cy))
        dudas.append(f"{ancha.loc[fila_cercana, '_nombre']} · {col}: no se pudo leer con seguridad "
                     f"(el lector vio «{texto}»); la celda quedó vacía, escríbela mirando la imagen")
    dimension = rotulo.strip().title() if rotulo else "Nombre"
    ancha = ancha.rename(columns={"_nombre": dimension})
    columnas_mes_tabla = [e for e in etiquetas if e in ancha.columns]
    vacias = int(ancha[columnas_mes_tabla].isna().sum().sum())
    avisos = [f"Se leyeron {len(ancha)} filas × {len(columnas_mes_tabla)} meses."]
    if vacias:
        avisos.append(f"{vacias} celda(s) quedaron vacías: compáralas con la imagen (pueden estar vacías en el original).")
    sin_restaurar = [n for n in ancha[dimension] if " " not in n and len(n) > 14]
    if sin_restaurar:
        avisos.append(f"{len(sin_restaurar)} nombre(s) sin espacios: no coinciden con ningún nombre del libro; corrígelos a mano si hace falta.")
    fuera = [(r[dimension], c) for _, r in ancha.iterrows() for c in columnas_mes_tabla
             if pd.notna(r[c]) and porcentaje and not 0 <= r[c] <= 1000]
    if fuera:
        avisos.append(f"{len(fuera)} valor(es) fuera de rango para un porcentaje: revisa {fuera[0][0]} · {fuera[0][1]}.")
    dudas += _revisar_coherencia(ancha, dimension, columnas_mes_tabla, total, porcentaje)
    periodos = {e: (a, m) for e, a, m in zip(etiquetas, anios_col, meses)}
    return {"tipo": "tabla", "ancha": ancha, "dimension": dimension, "periodos": periodos,
            "porcentaje": bool(porcentaje), "dudas": dudas, "avisos": avisos,
            "total": total["valores"] if total else None}


def _revisar_coherencia(ancha: pd.DataFrame, dimension: str, meses: list, total, porcentaje: bool) -> list[str]:
    """Lo que no cuadra dentro de la propia tabla, dicho con nombre y mes.

    No corrige nada —una cifra rara puede ser real—, pero la señala para que
    se mire contra la imagen antes de usarla. Dos comprobaciones:

    - **Cada celda contra los demás meses de su fila.** Un 6 entre valores de
      80 a 100 es casi siempre una mala lectura (el "90 %" girado del informe
      real). Se exige una diferencia grande para no marcar meses malos de verdad.
    - **Cada fila contra su columna Total**, si la imagen la trae: si el
      promedio de los meses se aleja mucho del Total escrito, algún mes está mal.
    """
    dudas = []
    if not meses:
        return dudas
    for _, fila in ancha.iterrows():
        valores = pd.to_numeric(fila[meses], errors="coerce")
        validos = valores.dropna()
        if len(validos) < 4:
            continue
        mediana = float(validos.median())
        if mediana <= 0:
            continue
        for mes, v in validos.items():
            resto = validos.drop(mes)
            if v < mediana * 0.35 and v < float(resto.min()) * 0.5:
                dudas.append(f"{fila[dimension]} · {mes}: {v:g} es muy distinto a sus otros meses "
                             f"(mediana {mediana:g}); compáralo con la imagen")
        if "Total" in ancha.columns and pd.notna(fila.get("Total")):
            promedio = float(validos.mean())
            escrito = float(fila["Total"])
            tolerancia = max(5.0, abs(escrito) * 0.08) if porcentaje else max(abs(escrito) * 0.08, 1.0)
            if porcentaje and abs(promedio - escrito) > tolerancia:
                dudas.append(f"{fila[dimension]}: el promedio de sus meses ({promedio:.0f}) no cuadra con su Total "
                             f"escrito ({escrito:g}); revisa sus celdas")
    return dudas


# ── Gráficos de líneas ──────────────────────────────────────────────────────

def _marcador_leyenda(img: np.ndarray, t: dict) -> Optional[dict]:
    """El marcador de color de una serie en la leyenda: su color y dónde está.

    Se busca a la izquierda del nombre Y en su primer carácter, porque según
    la versión de RapidOCR el círculo queda fuera de la caja del texto (1.2)
    o dentro, leído como una letra ("OAsesores" en 1.4). El marcador es la
    mancha más grande de UN solo color: las letras, aunque sean negras, son
    trazos finos con bordes suavizados y no forman una mancha tan grande.
    Antes se tomaba "el píxel más oscuro", que con el marcador dentro de la
    caja era el negro del texto: Asesores (rojo) salía negro y perdía sus valores.
    """
    alto = max(8.0, t["h"])
    x0 = int(max(0, t["x0"] - 22)); x1 = int(min(img.shape[1], t["x0"] + alto * 1.4))
    y0 = int(max(0, t["cy"] - alto * 0.6)); y1 = int(min(img.shape[0], t["cy"] + alto * 0.6))
    zona = img[y0:y1, x0:x1].astype(int)
    if zona.size == 0:
        return None
    pix = zona.reshape(-1, 3)
    xs = np.tile(np.arange(x0, x1), y1 - y0)
    tinta = pix.sum(axis=1) < 700
    if tinta.sum() < 10:
        return None
    grupos = {}
    for (r, g, b), x in zip(pix[tinta] // 16, xs[tinta]):
        grupos.setdefault((r, g, b), []).append(x)
    candidatos = sorted(((len(v), k, v) for k, v in grupos.items()), reverse=True)
    elegido = None
    for n, clave, pos in candidatos:
        if n < 18:
            break
        casi_negro = sum(clave) * 16 < 110
        if casi_negro and any(m >= 18 and sum(k) * 16 >= 110 for m, k, _ in candidatos):
            continue  # es el texto; hay otra mancha con color
        elegido = (clave, pos)
        break
    if elegido is None:
        return None
    clave, pos = elegido
    mascara = tinta & np.all(pix // 16 == np.array(clave), axis=1)
    return {"color": tuple(pix[mascara].mean(axis=0).round().astype(int)),
            "cx": float(np.mean(pos))}


_MARCADOR_COMO_LETRA = re.compile(r"^[Oo0●•○◦·]\s*(?=[A-ZÁÉÍÓÚÑ])")


def interpretar_grafico(textos: list[dict], contenido: bytes, anio_por_defecto=None) -> Optional[dict]:
    """Un gráfico de líneas con el valor escrito en cada punto, o None si no lo es."""
    img = np.array(_imagen_rgb(contenido)).astype(int)
    alto = img.shape[0]
    filas = _filas_de_texto(textos)
    if not filas:
        return None

    # Eje X: los renglones de abajo con meses ("09.", "septi...").
    marcas = []
    for fila in filas:
        if fila[0]["cy"] < alto * 0.6:
            continue
        for t in fila:
            partes = t["texto"].split()
            ancho = (t["x1"] - t["x0"]) / max(len(partes), 1)
            for k, parte in enumerate(partes):
                m = _mes_de_texto(parte)
                if m and not _anio(parte):
                    marcas.append({"cx": t["x0"] + ancho * (k + 0.5), "cy": t["cy"], "mes": m,
                                   "numerico": bool(re.fullmatch(r"\d{1,2}\.?", parte))})
    numericas = [m for m in marcas if m["numerico"]]
    marcas = numericas if len(numericas) >= 3 else marcas
    # Una marca por posición: "09." y "septi..." del mismo mes caen en la misma x.
    marcas.sort(key=lambda m: m["cx"])
    unicas = []
    for m in marcas:
        if unicas and abs(m["cx"] - unicas[-1]["cx"]) < 15:
            continue
        unicas.append(m)
    if len(unicas) < 3:
        return None
    paso = float(np.median(np.diff([m["cx"] for m in unicas])))
    # Completar marcas que el OCR no vio, con el espaciado regular del eje.
    completas = [unicas[0]]
    for m in unicas[1:]:
        previo = completas[-1]
        huecos = int(round((m["cx"] - previo["cx"]) / paso)) - 1
        for k in range(1, huecos + 1):
            completas.append({"cx": previo["cx"] + paso * k, "mes": (previo["mes"] + k - 1) % 12 + 1, "inferida": True})
        completas.append(m)
    y_eje = min(m.get("cy", alto) for m in unicas)
    anios = sorted((t["cx"], _anio(t["texto"])) for t in textos if _anio(t["texto"]) and t["cy"] > y_eje)
    meses = [m["mes"] for m in completas]
    anios_col = _asignar_anios(meses, [a for _, a in anios], anio_por_defecto)
    etiquetas = [_etiqueta_mes(a, m) for a, m in zip(anios_col, meses)]

    # Título y leyenda: los textos de arriba con letras.
    arriba = [t for t in textos if t["cy"] < alto * 0.25 and re.search("[A-Za-z]", t["texto"])]
    titulo = max(arriba, key=lambda t: t["h"] * len(t["texto"]))["texto"] if arriba else None
    series = []
    for t in arriba:
        if t["texto"] == titulo:
            continue
        marcador = _marcador_leyenda(img, t)
        if marcador is None:
            continue
        nombre = t["texto"].strip()
        if marcador["cx"] > t["x0"]:
            # El círculo quedó dentro de la caja y se leyó como una letra.
            nombre = _MARCADOR_COMO_LETRA.sub("", nombre)
        series.append({"nombre": nombre, "color": np.array(marcador["color"]), "y_leyenda": t["y1"]})
    if not series:
        return None
    y_arriba = max(s["y_leyenda"] for s in series) + 2

    datos = {s["nombre"]: {} for s in series}
    dudas = []
    for t in textos:
        v = _numero(t["texto"])
        if v is None or not (y_arriba < t["cy"] < y_eje - 4) or _anio(t["texto"]):
            continue
        cx, i = min((abs(m["cx"] - t["cx"]), i) for i, m in enumerate(completas))
        if cx > paso * 0.6:
            continue
        # Serie: la línea de su color más cercana en vertical. Primero en la
        # columna del centro de la etiqueta; solo si ahí no pasa ninguna línea,
        # bajo todo su ancho (la etiqueta del último punto suele correrse a la
        # derecha del final de la línea). Empezar por el ancho completo le daba
        # el 11,3 de enero a la línea roja, que baja empinada justo al lado.
        mejor = None
        for x0, x1 in ((t["cx"] - 3, t["cx"] + 4), (t["x0"] - 4, t["x1"] + 4)):
            franja = img[int(y_arriba):int(y_eje), int(max(0, x0)):int(min(img.shape[1], x1))]
            for s in series:
                dist = np.sqrt(((franja - s["color"]) ** 2).sum(axis=2))
                ys = np.where((dist < 70).any(axis=1))[0]
                if not len(ys):
                    continue
                ys = ys + int(y_arriba)
                fuera_caja = ys[(ys < t["y0"] - 1) | (ys > t["y1"] + 1)]
                if not len(fuera_caja):
                    continue
                d = float(np.min(np.abs(fuera_caja - t["cy"])))
                if mejor is None or d < mejor[0]:
                    mejor = (d, s["nombre"])
            if mejor is not None:
                break
        if mejor is None or mejor[0] > 60:
            dudas.append(f"{t['texto']} en {etiquetas[i]}: no se pudo saber de qué serie es")
            continue
        previo = datos[mejor[1]].get(etiquetas[i])
        if previo is None or mejor[0] < previo[1]:
            datos[mejor[1]][etiquetas[i]] = (v, mejor[0], t["score"])

    ancha = pd.DataFrame({"Mes": etiquetas})
    for s in series:
        ancha[s["nombre"]] = [datos[s["nombre"]].get(e, (np.nan,))[0] for e in etiquetas]
    llenas = int(ancha[[s["nombre"] for s in series]].notna().sum().sum())
    if llenas < 3:
        return None
    avisos = [f"Se leyeron {len(series)} serie(s) × {len(etiquetas)} meses."]
    for sname in [s["nombre"] for s in series]:
        faltan = int(ancha[sname].isna().sum())
        if faltan > max(2, len(etiquetas) * 0.2):
            dudas.append(f"{sname}: faltan {faltan} de {len(etiquetas)} valores; puede que no se haya reconocido bien "
                         "el color de su línea. Complétalos mirando la imagen o vuelve a leerla.")
    vacias = int(ancha[[s["nombre"] for s in series]].isna().sum().sum())
    if vacias:
        avisos.append(f"{vacias} punto(s) sin valor: suelen ser etiquetas encimadas donde las líneas se cruzan; "
                      "compáralos con la imagen.")
    inferidas = sum(1 for m in completas if m.get("inferida"))
    if inferidas:
        avisos.append(f"{inferidas} mes(es) del eje no se leyeron y se dedujeron por el espaciado.")
    if any(a is None for a in anios_col):
        avisos.append("El gráfico no muestra el año: los meses quedan sin año.")
    periodos = {e: (a, m) for e, a, m in zip(etiquetas, anios_col, meses)}
    return {"tipo": "grafico", "ancha": ancha, "titulo": titulo, "periodos": periodos,
            "series": [s["nombre"] for s in series], "dudas": dudas, "avisos": avisos}


# ── Entrada principal ───────────────────────────────────────────────────────

def interpretar_imagen(contenido: bytes, vocabulario=None, anio_por_defecto=None) -> dict:
    """Lee la imagen y la convierte en tabla. Siempre devuelve un dict con "tipo" (None si no se pudo)."""
    textos = leer_textos(contenido)
    if not textos:
        return {"tipo": None, "avisos": ["La imagen no tiene texto legible."], "textos": 0}
    resultado = interpretar_tabla(textos, vocabulario, anio_por_defecto)
    if resultado is None:
        resultado = interpretar_grafico(textos, contenido, anio_por_defecto)
    if resultado is None:
        return {"tipo": None, "textos": len(textos),
                "avisos": [f"Se leyeron {len(textos)} textos, pero no tienen forma de tabla con meses ni de gráfico "
                           "con valores escritos. Una imagen sin cifras visibles no se puede convertir en datos."]}
    resultado["textos"] = len(textos)
    resultado["confianza"] = float(np.mean([t["score"] for t in textos]))
    return resultado


def a_tabla_larga(resultado: dict, ancha: pd.DataFrame, medida: str = "Valor") -> pd.DataFrame:
    """La tabla revisada, en el formato del resto del panel: una fila por grupo y mes."""
    periodos = resultado["periodos"]

    def fecha(etiqueta):
        anio, mes = periodos.get(etiqueta, (None, None))
        return pd.Timestamp(anio, mes, 1) if anio and mes else etiqueta

    if resultado["tipo"] == "grafico":
        largo = ancha.copy()
        largo["Mes"] = largo["Mes"].map(fecha)
        return largo
    dimension = resultado["dimension"]
    meses = [c for c in ancha.columns if c in periodos]
    largo = ancha.melt(id_vars=[dimension], value_vars=meses, var_name="Mes", value_name=medida)
    largo["Mes"] = largo["Mes"].map(fecha)
    return largo.dropna(subset=[medida]).reset_index(drop=True)
