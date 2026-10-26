"""Nombres de columna abreviados → el nombre que querían decir.

Los exportes de otros sistemas (ERP, CRM, el BI de la empresa) no escriben
«Ventas», «Municipio» o «Meta»: escriben VLR_NETO, Mpio, Obj. Toda la
detección de columnas que mira el nombre (core/schema.py, core/dates.py,
core/semantic_engine.py, core/performance.py) buscaba palabras completas, así
que con esos nombres una cédula («Doc») se sumaba como métrica, una columna de
municipios no daba mapa y la meta («Obj») no aparecía: el mismo archivo se leía
bien o mal según cómo se llamaran sus columnas.

Aquí solo se traduce el NOMBRE, palabra por palabra; ninguna regla de
clasificación cambia. Quien decide sigue siendo cada detector, que ahora
recibe «valor neto» en vez de «VLR_NETO».

Criterio para entrar en el diccionario: que la abreviatura casi nunca
signifique otra cosa en un archivo de negocio. Quedan fuera a propósito:
«pto» (punto de venta, no presupuesto), «desc» (descripción o descuento),
«num»/«no» (número de ventas no es un identificador), «reg» (región o
registro), «pres» (presupuesto o presentación).
"""
from __future__ import annotations

import re
import unicodedata

_ABREVIATURAS = {
    # Fechas
    "fec": "fecha", "fch": "fecha", "fcha": "fecha",
    # Dinero
    "vlr": "valor", "vr": "valor", "vta": "venta", "vtas": "ventas",
    "util": "utilidad", "dcto": "descuento", "dto": "descuento",
    "mg": "margen", "mgn": "margen",
    # Cantidades
    "und": "unidades", "uds": "unidades", "unid": "unidades", "ctd": "cantidad",
    # Metas
    "obj": "objetivo", "ppto": "presupuesto", "presup": "presupuesto",
    "cump": "cumplimiento",
    # Porcentajes
    "porc": "porcentaje",
    # Identificadores
    "cod": "codigo", "doc": "documento", "ced": "cedula", "cc": "cedula",
    # Geografía
    "mpio": "municipio", "mun": "municipio", "munic": "municipio",
    "dpto": "departamento", "depto": "departamento",
    # Personas, clientes, productos
    "resp": "responsable", "vend": "vendedor", "cli": "cliente", "prod": "producto",
    # Contacto
    "tel": "telefono", "cel": "celular", "dir": "direccion",
}

# Palabra = letras (con tildes); los dígitos y separadores quedan fuera, así
# que en "Vlr2026" o "VLR_NETO" cada palabra se mira sola.
_PALABRA_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")
_SEPARADORES_RE = re.compile(r"[_\-./]+")
# "VlrNeto" → "Vlr Neto": cambio de minúscula a mayúscula dentro de la palabra.
_CAMEL_RE = re.compile(r"(?<=[a-záéíóúüñ])(?=[A-ZÁÉÍÓÚÜÑ])")


def _clave(palabra: str) -> str:
    t = unicodedata.normalize("NFKD", palabra)
    return "".join(ch for ch in t if not unicodedata.combining(ch)).lower()


def nombre_legible(columna) -> str:
    """El nombre de la columna con sus abreviaturas escritas completas.

    "VLR_NETO" → "valor NETO", "F. Venta" → "fecha Venta", "Mpio" → "municipio".
    Un nombre sin abreviaturas sale EXACTAMENTE igual que entró: partir
    "DiasMora" en "Dias Mora" sin traducir nada hacía que el motor semántico
    leyera «dias» como «día» y la tomara por fecha.
    """
    original = str(columna)
    texto = re.sub(r"\s+", " ", _SEPARADORES_RE.sub(" ", _CAMEL_RE.sub(" ", original))).strip()
    palabras = _PALABRA_RE.findall(texto)
    traducidas = 0

    def _traducir(m):
        nonlocal traducidas
        clave = _clave(m.group(0))
        # "F" sola solo es fecha cuando abre un nombre compuesto ("F. Venta",
        # "F_Corte"); una columna que se llama solo "F" puede ser cualquier cosa.
        if clave == "f" and m.start() == 0 and len(palabras) > 1:
            traducidas += 1
            return "fecha"
        if clave in _ABREVIATURAS:
            traducidas += 1
            return _ABREVIATURAS[clave]
        return m.group(0)

    legible = _PALABRA_RE.sub(_traducir, texto)
    return legible if traducidas else original


def nombre_para_buscar(columna) -> str:
    """Original + traducción, para los detectores que buscan por expresión
    regular: lo que ya reconocían por el nombre original lo siguen
    reconociendo, y además encuentran lo que dice la traducción."""
    original = str(columna)
    legible = nombre_legible(columna)
    return original if legible == original else f"{original} | {legible}"
