"""Estructura comercial: cruzar varios Excel sobre la jerarquía
Región › Jefe › Supervisor › Agente › PDV.

El problema que resuelve: un jefe recibe a diario varios archivos —uno con
la estructura (qué agente está con qué supervisor), otro con los puntos de
venta y su código, otro con las metas, otro con las ventas— y arma su informe
a mano con BUSCARV. Este módulo hace ese cruce solo:

1. **Lee qué es cada columna** por el encabezado (`Jefe de zona`, `Cédula
   asesor`, `Código M.`, `Meta`, `Ppto`…) y, si el encabezado no dice nada,
   por los VALORES: una columna `Nombre` cuyos nombres son los agentes de
   otro archivo es la columna de agentes, se llame como se llame.
2. **Reconoce a la misma persona o punto entre archivos** aunque venga
   distinto: código como número en uno y como texto en otro, con o sin ceros
   a la izquierda, nombre con o sin tildes. Un nombre se une a un código solo
   si ese nombre tiene UN código en todos los archivos: dos «Juan Pérez» con
   cédulas distintas son dos personas, no una.
3. **Arma la red** de quién está debajo de quién. Es una red y no un árbol:
   un agente puede estar con varios supervisores o jefes (pasa en la
   realidad). Cuando una fila de ventas no dice el supervisor, se deduce de
   la red; si el agente tiene dos, la fila queda como «A / B» —compartida—
   en vez de inventar a cuál le toca.
4. **Arma una tabla unificada**: cada fila de resultados con toda su
   jerarquía, más los puntos que están en la estructura pero no vendieron
   (vender cero también es un dato) y la meta en una sola fila por punto,
   para que sumar por cualquier nivel dé la meta correcta.

La tabla unificada se carga como archivo activo del Análisis Completo, así
que todo el panel (filtros, resumen, proyección…) funciona sobre ella; la
vista «🏢 Estructura» (`ui/estructura.py`) usa además las funciones de
navegación de abajo: `resumen_por_nivel`, `ficha` y `rutas`.

Sin Streamlit: recibe libros ya leídos por `core/loader.load_workbook`.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from typing import Optional

import numpy as np
import pandas as pd

from .numeric import numeric_series, numeric_valid

# ── Niveles ────────────────────────────────────────────────────────────────
# De arriba hacia abajo. El índice es la altura: menor = más arriba.
NIVELES = ["region", "jefe", "supervisor", "agente", "pdv"]
ETIQUETAS = {"region": "Región", "jefe": "Jefe", "supervisor": "Supervisor", "agente": "Agente", "pdv": "PDV"}
PLURALES = {"region": "regiones", "jefe": "jefes", "supervisor": "supervisores", "agente": "agentes",
            "pdv": "PDV"}
COLUMNA_CODIGO_PDV = "Código PDV"
COLUMNA_FECHA = "Fecha"
COLUMNA_META = "Meta"
COLUMNA_PRESUPUESTO = "Presupuesto"
# Cómo se escribe una fila que pertenece a dos jefes a la vez: «Ana / Luis».
SEPARADOR = " / "

# Qué nivel nombra el encabezado. El ORDEN es la prioridad: «Jefe de zona» es
# un jefe y no una región, «Supervisor zona» es un supervisor.
_NIVEL_RE = [
    ("jefe", re.compile(r"\bjefe|gerente|director")),
    ("supervisor", re.compile(r"supervis|\blider\b|coordinador|\bsup\b")),
    ("agente", re.compile(r"agente|asesor|vendedor|ejecutiv|promotor|gestor|tropa|\bvend\b")),
    ("pdv", re.compile(r"\bpdv|\bpdc\b|punto|tienda|establecimiento|comercio|\blocal\b|cliente|"
                       r"razon social|nombre comercial|\bpos\b")),
    ("region", re.compile(r"\bregi|\bzona|territori|distrito")),
]
# Un identificador (código, cédula, NIT). Sin nivel en el encabezado se asume
# que es el del PDV —el «Código M.» del tablero—, y la pasada por valores lo
# corrige si en realidad son las cédulas de los agentes.
_CODIGO_RE = re.compile(r"\bcod|codigo|cedula|\bcc\b|\bnit\b|\bid\b|identific|documento")
_META_RE = re.compile(r"meta|objetivo|cuota|target|goal")
_PRESUPUESTO_RE = re.compile(r"presup|ppto|budget")
# Un porcentaje se recalcula aquí (real ÷ meta): sumarlo no tiene sentido.
_PORCENTAJE_RE = re.compile(r"%|cump|porc|\btasa\b|ratio|particip")
_REAL_RE = re.compile(r"venta|real|ejecu|logro|resultado|altas|activa|recarga|valor|monto|total|"
                      r"cantidad|unidad|ingreso|facturac|recaudo|transacc")
# «PDV activos», «Cantidad de agentes»: cuentan, no nombran a nadie.
_CONTEO_RE = re.compile(r"cantidad|\bcant\b|numero|\bnum\b|\bnro\b|#|activos|total")
_CIUDAD_RE = re.compile(r"ciudad|municipio|\bmpio|localidad")
_DEPTO_RE = re.compile(r"departamento|\bdepto|\bdpto")
# Datos que DESCRIBEN a un punto o persona pero no lo identifican: «Dirección
# PDV» no es el nombre del PDV.
_ATRIBUTO_RE = re.compile(r"direcci|telefono|celular|correo|email|barrio|\btipo\b|categor|estado|canal|"
                          r"segmento|observ|\blat|\blon|coorden|clasific|formato|plan\b")

# Tipos semánticos que sí son un resultado que se suma (ver core/semantic_engine).
_SEMANTICA_REAL = {"revenue", "profit", "quantity", "cost"}

# Proporción mínima de valores compartidos para decidir, por los datos, que
# una columna sin encabezado claro es de cierto nivel (igual que core/cross_sheet).
UMBRAL_COINCIDENCIA = 0.5
MUESTRA_VALORES = 5000

ROLES = (
    [f"nivel:{n}:nombre" for n in NIVELES] + [f"nivel:{n}:codigo" for n in NIVELES]
    + ["real", "meta", "presupuesto", "fecha", "ciudad", "departamento", "otro", "ignorar"]
)


def etiqueta_rol(rol: str) -> str:
    """Cómo se le muestra el rol a quien revisa «lo que entendí»."""
    if rol.startswith("nivel:"):
        _, nivel, tipo = rol.split(":")
        if nivel == "pdv":
            return "Código PDV (Código M.)" if tipo == "codigo" else "PDV (nombre)"
        if nivel == "region":
            return "Región" if tipo == "nombre" else "Región (código)"
        return f"{ETIQUETAS[nivel]} ({'código / cédula' if tipo == 'codigo' else 'nombre'})"
    return {"real": "Resultado (ventas / avance)", "meta": "Meta", "presupuesto": "Presupuesto",
            "fecha": "Fecha", "ciudad": "Ciudad / municipio", "departamento": "Departamento",
            "otro": "Dato adicional", "ignorar": "No usar"}.get(rol, rol)


# ── Normalización ──────────────────────────────────────────────────────────
def _norm(texto) -> str:
    """Minúsculas, sin tildes, con `_ - .` como espacios: «COD_ASESOR» → «cod asesor»."""
    s = unicodedata.normalize("NFKD", str(texto))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[_\-.]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


_VACIOS = {"", "nan", "none", "nat", "sin dato", "sin datos", "n/a", "na", "-", "--", "null", "0"}


def clave(valor) -> Optional[str]:
    """La forma comparable de un código o nombre, para cruzar archivos.

    `12345`, `12345.0`, `"012345"` y `" 12345 "` son el mismo código: Excel
    se come los ceros a la izquierda y guarda como número lo que en otro
    archivo es texto. «PÉREZ  Juan» y «Perez Juan» son el mismo nombre.
    """
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(valor, (bool, np.bool_)):
        return None
    if isinstance(valor, (int, np.integer)):
        s = str(int(valor))
    elif isinstance(valor, (float, np.floating)):
        s = str(int(valor)) if float(valor).is_integer() else repr(float(valor))
    else:
        s = str(valor).strip()
        if re.fullmatch(r"\d+\.0+", s):
            s = s.split(".")[0]
    s = _norm(s)
    if s.isdigit():
        s = s.lstrip("0") or "0"
    return None if s in _VACIOS else s


def _claves(serie: pd.Series) -> list:
    cache: dict = {}
    salida = []
    for v in serie.tolist():
        try:
            k = cache[v]
        except (KeyError, TypeError):
            k = clave(v)
            try:
                cache[v] = k
            except TypeError:
                pass
        salida.append(k)
    return salida


def _texto_original(valor) -> Optional[str]:
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(valor, (float, np.floating)) and float(valor).is_integer():
        return str(int(valor))
    s = re.sub(r"\s+", " ", str(valor)).strip()
    return s or None


def partes(valor) -> list[str]:
    """«Ana / Luis» → ["Ana", "Luis"]; un valor vacío → []."""
    if valor is None:
        return []
    try:
        if pd.isna(valor):
            return []
    except (TypeError, ValueError):
        pass
    return [p for p in str(valor).split(SEPARADOR) if p]


# Un número escrito como texto: «1.234.567», «$ 45,5», «(300)», «12 %». NO
# «Jefe 3» ni «Tienda 12»: `numeric_valid` les quita las letras y los lee como
# 3 y 12, y entonces una columna de nombres parecía de códigos.
_NUMERO_TEXTO_RE = re.compile(r"^\s*[-+(]?\s*\$?\s*\d[\d.,\s]*%?\s*\)?\s*$")


def _es_numerica(serie: pd.Series) -> bool:
    x = serie.dropna()
    if x.empty:
        return False
    if pd.api.types.is_bool_dtype(x):
        return False
    if pd.api.types.is_numeric_dtype(x):
        return True
    muestra = x.head(MUESTRA_VALORES).astype(str)
    return float(muestra.str.match(_NUMERO_TEXTO_RE).mean()) >= 0.9


# ── 1. Qué es cada columna ─────────────────────────────────────────────────
def tablas_de(libros: list[dict]) -> list[dict]:
    """Todas las tablas de todos los archivos, sin hojas ocultas ni los datos
    copiados de los gráficos (son repeticiones de otras tablas)."""
    tablas = []
    for libro in libros:
        ocultas = libro.get("ocultas") or set()
        for hoja, item in (libro.get("sheets") or {}).items():
            if hoja in ocultas or str(hoja).startswith("Gráfico · "):
                continue
            df = item.get("processed")
            if df is None or df.empty:
                continue
            tablas.append({"archivo": libro.get("filename", "archivo"), "hoja": hoja, "df": df,
                           "schema": (item.get("profile") or {}).get("schema") or {}})
    return tablas


def _semantica(schema: dict) -> dict:
    return {i.get("column"): i.get("semantic_type")
            for i in (schema.get("semantic") or {}).get("columns", []) if isinstance(i, dict)}


def _rol_por_encabezado(col, serie: pd.Series, schema: dict, semantica: dict) -> tuple[str, bool]:
    """(rol, supuesto). `supuesto` = se adivinó y la pasada por valores puede corregirlo."""
    n = _norm(col)
    if col in set(schema.get("dates") or []):
        return "fecha", False
    numerica = _es_numerica(serie)
    es_codigo = bool(_CODIGO_RE.search(n))
    if numerica and not es_codigo:
        if _PRESUPUESTO_RE.search(n):
            return "presupuesto", False
        if _META_RE.search(n):
            return "meta", False
        if _PORCENTAJE_RE.search(n):
            return "ignorar", False
        if _REAL_RE.search(n) or _CONTEO_RE.search(n):
            return "real", False
    if _CIUDAD_RE.search(n):
        return "ciudad", False
    if _DEPTO_RE.search(n):
        return "departamento", False
    if _ATRIBUTO_RE.search(n):
        return "otro", False
    nivel = next((nv for nv, rx in _NIVEL_RE if rx.search(n)), None)
    if nivel is not None:
        tipo = "codigo" if es_codigo or (numerica and nivel != "region") else "nombre"
        return f"nivel:{nivel}:{tipo}", False
    if es_codigo:
        return "nivel:pdv:codigo", True
    if numerica:
        if semantica.get(col) in _SEMANTICA_REAL and col not in set(schema.get("ids") or []):
            return "real", True
        return "otro", False
    return "otro", True


def _deduplicar(roles: list[dict]) -> None:
    """Un solo rol de nivel por tabla (el explícito gana al supuesto) y una
    sola meta y un solo presupuesto: lo que sobra queda como dato adicional o
    sin usar, en vez de pisarse."""
    vistos: dict = {}
    for r in sorted(roles, key=lambda r: r["supuesto"]):
        rol = r["rol"]
        if not (rol.startswith("nivel:") or rol in {"meta", "presupuesto", "fecha", "ciudad", "departamento"}):
            continue
        if rol in vistos:
            r["rol"] = "ignorar" if rol in {"meta", "presupuesto"} else "otro"
            r["supuesto"] = False
        else:
            vistos[rol] = r


def _conjunto(serie: pd.Series) -> set:
    x = serie.dropna()
    if len(x) > MUESTRA_VALORES * 4:
        x = x.head(MUESTRA_VALORES * 4)
    return {k for k in _claves(pd.Series(pd.unique(x)[:MUESTRA_VALORES])) if k}


def clasificar(tablas: list[dict], ajustes: Optional[dict] = None) -> None:
    """Le pone a cada tabla `roles`: [{columna, rol, supuesto}], primero por el
    encabezado y luego por los valores; al final aplica las correcciones que
    hizo el usuario (`ajustes[(archivo, hoja, columna)] = rol`)."""
    for t in tablas:
        df, schema = t["df"], t["schema"]
        sem = _semantica(schema)
        roles = []
        for col in df.columns:
            if str(col).startswith("__") or str(col).startswith("_geo_"):
                continue
            rol, supuesto = _rol_por_encabezado(col, df[col], schema, sem)
            roles.append({"columna": col, "rol": rol, "supuesto": supuesto})
        _deduplicar(roles)
        t["roles"] = roles

    # Pasada por valores: lo que se sabe con certeza (encabezado explícito)
    # sirve para reconocer lo que no tenía nombre claro.
    conocidos: dict = defaultdict(set)
    for t in tablas:
        for r in t["roles"]:
            if r["rol"].startswith("nivel:") and not r["supuesto"]:
                conocidos[r["rol"]] |= _conjunto(t["df"][r["columna"]])
    if conocidos:
        for t in tablas:
            usados = {r["rol"] for r in t["roles"] if r["rol"].startswith("nivel:") and not r["supuesto"]}
            for r in t["roles"]:
                if not r["supuesto"]:
                    continue
                valores = _conjunto(t["df"][r["columna"]])
                if len(valores) < 2:
                    continue
                mejor, mejor_c = None, 0.0
                for rol, ref in conocidos.items():
                    if rol in usados:
                        continue
                    comunes = len(valores & ref)
                    c = comunes / max(min(len(valores), len(ref)), 1)
                    if comunes >= 2 and c >= UMBRAL_COINCIDENCIA and c > mejor_c:
                        mejor, mejor_c = rol, c
                if mejor:
                    r["rol"], r["supuesto"] = mejor, False
                    usados.add(mejor)
            _deduplicar(t["roles"])

    for t in tablas:
        for r in t["roles"]:
            ajuste = (ajustes or {}).get((t["archivo"], str(t["hoja"]), str(r["columna"])))
            if ajuste in ROLES:
                r["rol"], r["supuesto"] = ajuste, False
        t["niveles"] = {}
        for r in t["roles"]:
            if r["rol"].startswith("nivel:"):
                _, nivel, tipo = r["rol"].split(":")
                t["niveles"].setdefault(nivel, {})[tipo] = r["columna"]


# ── 2. Quién es quién entre archivos ──────────────────────────────────────
class _Identidades:
    """Las personas o puntos de UN nivel, reconocidos entre todos los archivos.

    Unión de conjuntos sobre claves `c:<código>` y `n:<nombre>`: un código y
    un nombre que aparecen en la misma fila son la misma entidad, pero solo
    si ese nombre tiene un único código en todos los archivos."""

    def __init__(self):
        self._padre: dict = {}
        self._nombres: dict = defaultdict(Counter)   # clave n: → nombres originales
        self._codigos: dict = {}                      # clave c: → código original
        self._pares: set = set()
        self.etiqueta: dict = {}                      # raíz → etiqueta única
        self.codigo: dict = {}                        # etiqueta → código original

    def _find(self, k):
        self._padre.setdefault(k, k)
        while self._padre[k] != k:
            self._padre[k] = self._padre[self._padre[k]]
            k = self._padre[k]
        return k

    def _union(self, a, b):
        ra, rb = self._find(a), self._find(b)
        if ra != rb:
            self._padre[rb] = ra

    def registrar(self, codigos: list, nombres: list, cod_orig: list, nom_orig: list):
        for c, n, co, no in zip(codigos, nombres, cod_orig, nom_orig):
            if c:
                kc = "c:" + c
                self._find(kc)
                self._codigos.setdefault(kc, co)
            if n:
                kn = "n:" + n
                self._find(kn)
                if no:
                    self._nombres[kn][no] += 1
            if c and n:
                self._pares.add(("c:" + c, "n:" + n))

    def cerrar(self):
        codigos_por_nombre: dict = defaultdict(set)
        for kc, kn in self._pares:
            codigos_por_nombre[kn].add(kc)
        for kc, kn in self._pares:
            if len(codigos_por_nombre[kn]) == 1:
                self._union(kc, kn)
        miembros: dict = defaultdict(list)
        for k in list(self._padre):
            miembros[self._find(k)].append(k)
        provisional = {}
        for raiz, ks in miembros.items():
            nombres = Counter()
            for k in ks:
                nombres.update(self._nombres.get(k, {}))
            cods = sorted(self._codigos[k] for k in ks if k in self._codigos)
            nombre = nombres.most_common(1)[0][0] if nombres else None
            provisional[raiz] = (nombre or (cods[0] if cods else raiz[2:]), cods[0] if cods else None)
        repetidas = Counter(e for e, _ in provisional.values())
        usadas: set = set()
        for raiz, (etq, cod) in sorted(provisional.items(), key=lambda x: str(x[1])):
            if repetidas[etq] > 1 and cod and cod != etq:
                etq = f"{etq} ({cod})"
            base, i = etq, 2
            while etq in usadas:
                etq, i = f"{base} ({i})", i + 1
            usadas.add(etq)
            self.etiqueta[raiz] = etq
            if cod:
                self.codigo[etq] = cod

    def resolver(self, c: Optional[str], n: Optional[str]) -> Optional[str]:
        if c and ("c:" + c) in self._padre:
            return self.etiqueta.get(self._find("c:" + c))
        if n and ("n:" + n) in self._padre:
            return self.etiqueta.get(self._find("n:" + n))
        return None

    def nombres_con_varios_codigos(self) -> list[str]:
        cuenta: dict = defaultdict(set)
        for kc, kn in self._pares:
            cuenta[kn].add(kc)
        return sorted(self._nombres[kn].most_common(1)[0][0] if self._nombres.get(kn) else kn[2:]
                      for kn, cs in cuenta.items() if len(cs) > 1)


def _columnas_de_nivel(t: dict, nivel: str) -> tuple[list, list, list, list]:
    df = t["df"]
    cols = t["niveles"].get(nivel, {})
    cc, cn = cols.get("codigo"), cols.get("nombre")
    vacio = [None] * len(df)
    return (_claves(df[cc]) if cc else vacio, _claves(df[cn]) if cn else vacio,
            [_texto_original(v) for v in df[cc].tolist()] if cc else vacio,
            [_texto_original(v) for v in df[cn].tolist()] if cn else vacio)


def _identidades(tablas: list[dict]) -> dict:
    ids = {}
    for nivel in NIVELES:
        ident = _Identidades()
        presente = False
        for t in tablas:
            if nivel in t["niveles"]:
                presente = True
                ident.registrar(*_columnas_de_nivel(t, nivel))
        if presente:
            ident.cerrar()
            ids[nivel] = ident
    return ids


def _resolver_tabla(t: dict, ids: dict) -> pd.DataFrame:
    """Una columna por nivel presente en la tabla, con la etiqueta única de cada fila."""
    salida = {}
    for nivel in t["niveles"]:
        cs, ns, _, _ = _columnas_de_nivel(t, nivel)
        cache: dict = {}
        valores = []
        for c, n in zip(cs, ns):
            par = (c, n)
            if par not in cache:
                cache[par] = ids[nivel].resolver(c, n)
            valores.append(cache[par])
        salida[nivel] = valores
    return pd.DataFrame(salida, index=t["df"].index)


# ── 3. La red: quién está debajo de quién ─────────────────────────────────
def _orden(nivel: str) -> int:
    return NIVELES.index(nivel)


def _red(resueltas: list[pd.DataFrame]) -> dict:
    """padres[nivel][nodo][nivel_padre] = {padres}. Solo entre niveles
    consecutivos PRESENTES en la fila: si un archivo trae agente y jefe sin
    supervisor, el agente queda colgado del jefe directamente."""
    padres: dict = {n: defaultdict(lambda: defaultdict(set)) for n in NIVELES}
    for r in resueltas:
        presentes = [n for n in NIVELES if n in r.columns]
        if len(presentes) < 2:
            continue
        for fila in r[presentes].drop_duplicates().itertuples(index=False):
            nodos = [(n, v) for n, v in zip(presentes, fila) if v is not None and not pd.isna(v)]
            for (np_, padre), (nh, hijo) in zip(nodos, nodos[1:]):
                padres[nh][hijo][np_].add(padre)
    return padres


def ancestros(padres: dict, nivel: str, nodo, objetivo: str, _memo: Optional[dict] = None) -> set:
    """Todos los nodos de `objetivo` (un nivel más arriba) de los que cuelga `nodo`."""
    memo = {} if _memo is None else _memo
    llave = (nivel, nodo, objetivo)
    if llave in memo:
        return memo[llave]
    res: set = set()
    for nivel_p, ps in padres.get(nivel, {}).get(nodo, {}).items():
        for p in ps:
            if nivel_p == objetivo:
                res.add(p)
            elif _orden(nivel_p) > _orden(objetivo):
                res |= ancestros(padres, nivel_p, p, objetivo, memo)
    memo[llave] = res
    return res


def rutas(red: dict, nivel: str, nodo, maximo: int = 8) -> list[list[tuple[str, str]]]:
    """Las cadenas de mando de un nodo, de arriba hacia él:
    [[("region","Norte"),("jefe","Ana"),("supervisor","Luis")], …]. Una por
    cada camino distinto (un agente con dos supervisores tiene dos)."""
    padres = red.get("padres", {})
    directos = [(nivel_p, p) for nivel_p, ps in padres.get(nivel, {}).get(nodo, {}).items() for p in sorted(ps)]
    if not directos:
        return [[]]
    salida = []
    for nivel_p, p in sorted(directos, key=lambda x: _orden(x[0])):
        for camino in rutas(red, nivel_p, p, maximo):
            salida.append(camino + [(nivel_p, p)])
            if len(salida) >= maximo:
                return salida
    return salida


# ── 4. Metas y presupuestos declarados ────────────────────────────────────
def _medidas_declaradas(tablas: list[dict], resueltas: list[pd.DataFrame], avisos: list) -> dict:
    """{"meta": {nivel: {nodo: valor}}, "presupuesto": {...}}.

    La medida se asigna al nivel más bajo de su tabla: «Meta» en un archivo
    de supervisores es la meta del supervisor. Si la tabla tiene fecha y el
    mismo valor se repite en todas las filas de un nodo, es la meta copiada
    en cada día y se toma una vez; si varía, se suma (meta por producto)."""
    declaradas: dict = {"meta": defaultdict(dict), "presupuesto": defaultdict(dict)}
    for t, r in zip(tablas, resueltas):
        presentes = [n for n in NIVELES if n in r.columns and r[n].notna().any()]
        if not presentes:
            continue
        nivel = presentes[-1]
        tiene_fecha = any(x["rol"] == "fecha" for x in t["roles"])
        for x in t["roles"]:
            if x["rol"] not in declaradas:
                continue
            valores = numeric_valid(t["df"][x["columna"]])
            datos = pd.DataFrame({"nodo": r[nivel], "v": valores}).dropna()
            if datos.empty:
                continue
            for nodo, g in datos.groupby("nodo", sort=False):
                v = float(g["v"].iloc[0]) if (tiene_fecha and len(g) > 1 and g["v"].nunique() == 1) \
                    else float(g["v"].sum())
                previo = declaradas[x["rol"]][nivel].get(nodo)
                if previo is None:
                    declaradas[x["rol"]][nivel][nodo] = v
                elif abs(previo - v) > 0.01 * max(abs(previo), abs(v), 1):
                    avisos.append({"tipo": "aviso", "texto":
                                   f"La {x['rol']} de {ETIQUETAS[nivel].lower()} «{nodo}» viene distinta en dos "
                                   f"archivos ({previo:,.0f} y {v:,.0f}): se usa la primera.",
                                   "ejemplos": []})
    return {k: {n: dict(v) for n, v in d.items()} for k, d in declaradas.items()}


# ── 5. La tabla unificada ─────────────────────────────────────────────────
def _completar_niveles(r: pd.DataFrame, padres: dict, niveles: list[str]) -> pd.DataFrame:
    """Los niveles que la fila no trae, deducidos de la red. Se recorre de
    abajo hacia arriba: el supervisor sale del agente, el jefe del supervisor
    (traído o deducido). Varios posibles → «A / B»."""
    presentes = [n for n in niveles if n in r.columns]
    if not presentes:
        return pd.DataFrame(index=r.index, columns=niveles)
    base = r[presentes].copy()
    memo: dict = {}
    combos = base.drop_duplicates()
    filas = []
    for fila in combos.itertuples(index=False):
        conjuntos: dict = {}
        valores = dict(zip(presentes, fila))
        for nivel in reversed(niveles):
            v = valores.get(nivel)
            if v is not None and not pd.isna(v):
                conjuntos[nivel] = {v}
                continue
            debajo = next((conjuntos[n] for n in niveles[niveles.index(nivel) + 1:] if conjuntos.get(n)), None)
            if not debajo:
                conjuntos[nivel] = set()
                continue
            arriba: set = set()
            nivel_debajo = next(n for n in niveles[niveles.index(nivel) + 1:] if conjuntos.get(n))
            for nodo in debajo:
                arriba |= ancestros(padres, nivel_debajo, nodo, nivel, memo)
            conjuntos[nivel] = arriba
        filas.append({n: (SEPARADOR.join(sorted(conjuntos[n])) if conjuntos[n] else np.nan) for n in niveles})
    completas = pd.DataFrame(filas, columns=niveles)
    completas.index = range(len(completas))
    llave = combos.reset_index(drop=True).astype(object).where(combos.reset_index(drop=True).notna(), "\x00")
    llave_filas = base.astype(object).where(base.notna(), "\x00")
    mapa = {tuple(k): i for i, k in enumerate(llave.itertuples(index=False))}
    posiciones = [mapa[tuple(k)] for k in llave_filas.itertuples(index=False)]
    salida = completas.iloc[posiciones].copy()
    salida.index = r.index
    return salida


def cruzar(libros: list[dict], ajustes: Optional[dict] = None) -> dict:
    """Cruza los libros y devuelve todo lo que necesitan el panel y la vista.

    Claves: `tabla` (la tabla unificada), `niveles` (presentes, de arriba
    abajo), `medidas` (columnas de resultado), `meta`/`presupuesto`/`fecha`
    (nombre de la columna en `tabla` o None), `nivel_base`, `declaradas`,
    `red`, `codigos`, `mapeo` (qué se entendió de cada archivo) y `avisos`
    (lo que no cruzó)."""
    tablas = tablas_de(libros)
    if not tablas:
        raise ValueError("Los archivos no traen ninguna tabla con datos.")
    clasificar(tablas, ajustes)
    con_nivel = [t for t in tablas if t["niveles"]]
    if not con_nivel:
        raise ValueError("No se reconoció ninguna columna de la estructura (jefe, supervisor, agente, PDV o "
                         "código del punto) en los archivos. Revisa «lo que entendí» y marca las columnas a mano.")
    ids = _identidades(con_nivel)
    resueltas = [_resolver_tabla(t, ids) for t in con_nivel]
    padres = _red(resueltas)
    avisos: list = []
    declaradas = _medidas_declaradas(con_nivel, resueltas, avisos)
    niveles = [n for n in NIVELES if n in ids]

    # Tablas de resultados: las que traen al menos una columna «real».
    reales = [(t, r) for t, r in zip(con_nivel, resueltas) if any(x["rol"] == "real" for x in t["roles"])]
    nivel_base = max(([n for n in NIVELES if n in r.columns][-1] for _, r in reales), key=_orden,
                     default=niveles[-1])

    medidas: list[str] = []
    bloques = []
    for t, r in reales:
        df = t["df"]
        bloque = _completar_niveles(r, padres, niveles)
        for x in t["roles"]:
            col = x["columna"]
            if x["rol"] == "real":
                nombre = re.sub(r"\s+", " ", str(col)).strip()
                bloque[nombre] = numeric_valid(df[col]).to_numpy()
                if nombre not in medidas:
                    medidas.append(nombre)
            elif x["rol"] == "fecha" and COLUMNA_FECHA not in bloque.columns:
                bloque[COLUMNA_FECHA] = pd.to_datetime(df[col], errors="coerce").to_numpy()
            elif x["rol"] == "ciudad" and "Ciudad" not in bloque.columns:
                bloque["Ciudad"] = df[col].map(_texto_original).to_numpy()
            elif x["rol"] == "departamento" and "Departamento" not in bloque.columns:
                bloque["Departamento"] = df[col].map(_texto_original).to_numpy()
            elif x["rol"] == "otro" and not _es_numerica(df[col]):
                nombre = re.sub(r"\s+", " ", str(col)).strip()
                if nombre not in bloque.columns and nombre not in {ETIQUETAS[n] for n in NIVELES}:
                    bloque[nombre] = df[col].map(_texto_original).to_numpy()
        bloques.append(bloque)
    tabla = pd.concat(bloques, ignore_index=True) if bloques else pd.DataFrame(columns=niveles)
    for n in niveles:
        if n not in tabla.columns:
            tabla[n] = np.nan

    # Lo que está en la estructura pero no tiene ninguna fila de resultados:
    # un PDV que no vendió es un cero que hay que ver, no un ausente.
    todos_nodos = {n: set(ids[n].etiqueta.values()) for n in niveles}
    presentes_tabla = {n: {p for v in tabla[n].dropna().unique() for p in partes(v)} for n in niveles}
    faltantes = []
    sin_resultados = defaultdict(list)
    for nivel in sorted(niveles, key=_orden, reverse=True):
        if _orden(nivel) > _orden(nivel_base):
            continue  # más abajo que los resultados: no tiene filas propias
        for nodo in sorted(todos_nodos[nivel] - presentes_tabla[nivel]):
            faltantes.append({nivel: nodo})
            sin_resultados[nivel].append(nodo)
            presentes_tabla[nivel].add(nodo)
            # Sus superiores ya quedan representados por esta fila.
            for arriba in niveles[:niveles.index(nivel)]:
                for a in ancestros(padres, nivel, nodo, arriba):
                    presentes_tabla[arriba].add(a)
    if faltantes:
        extra = _completar_niveles(pd.DataFrame(faltantes).reindex(columns=niveles), padres, niveles)
        for m in medidas:
            extra[m] = 0.0 if reales else np.nan
        tabla = pd.concat([tabla, extra], ignore_index=True)

    # Meta y presupuesto en la tabla: solo los del nivel base (o de más abajo,
    # sumados hasta él), UNA vez por nodo. Así sumar por cualquier nivel da la
    # meta correcta; una meta de supervisor puesta en las filas de sus PDV
    # haría que cada PDV pareciera tener la meta de todo el equipo.
    for tipo, columna in (("meta", COLUMNA_META), ("presupuesto", COLUMNA_PRESUPUESTO)):
        por_nodo: dict = defaultdict(float)
        hay = False
        for nivel, valores in declaradas[tipo].items():
            if _orden(nivel) < _orden(nivel_base):
                continue
            for nodo, v in valores.items():
                destino = {nodo} if nivel == nivel_base else ancestros(padres, nivel, nodo, nivel_base)
                for d in destino:
                    por_nodo[d] += v
                    hay = True
        if not hay:
            continue
        if nivel_base in niveles and nivel_base not in declaradas[tipo]:
            declaradas[tipo][nivel_base] = dict(por_nodo)
        tabla[columna] = np.nan
        col_base = tabla[nivel_base]
        primera = ~col_base.duplicated() & col_base.notna()
        for i in tabla.index[primera]:
            v = por_nodo.get(col_base.at[i])
            if v is not None:
                tabla.at[i, columna] = v
        con_fila = set(col_base.dropna())
        sin_fila = [n for n in por_nodo if n not in con_fila]
        if sin_fila:
            extra = _completar_niveles(pd.DataFrame({nivel_base: sin_fila}).reindex(columns=niveles), padres, niveles)
            extra[columna] = [por_nodo[n] for n in sin_fila]
            tabla = pd.concat([tabla, extra], ignore_index=True)

    # Datos que describen al nodo base (ciudad, tipo de punto…) traídos de
    # las tablas de estructura, donde viven: una fila de ventas no los repite.
    for t, r in zip(con_nivel, resueltas):
        if nivel_base not in r.columns:
            continue
        for x in t["roles"]:
            if x["rol"] not in {"ciudad", "departamento", "otro"}:
                continue
            serie = t["df"][x["columna"]]
            if x["rol"] == "otro" and _es_numerica(serie):
                continue
            nombre = {"ciudad": "Ciudad", "departamento": "Departamento"}.get(
                x["rol"], re.sub(r"\s+", " ", str(x["columna"])).strip())
            if nombre in {ETIQUETAS[n] for n in NIVELES} | {COLUMNA_CODIGO_PDV, COLUMNA_FECHA}:
                continue
            pares = pd.DataFrame({"nodo": r[nivel_base], "v": serie.map(_texto_original)}).dropna()
            if pares.empty:
                continue
            unicos = pares.groupby("nodo")["v"].nunique()
            if (unicos > 1).mean() > 0.2:
                continue  # varía dentro del nodo: no lo describe
            mapa = pares.drop_duplicates("nodo").set_index("nodo")["v"]
            desde = tabla[nivel_base].map(mapa)
            if nombre in tabla.columns:
                tabla[nombre] = tabla[nombre].where(tabla[nombre].notna(), desde)
            else:
                tabla[nombre] = desde

    if "pdv" in niveles:
        tabla[COLUMNA_CODIGO_PDV] = tabla["pdv"].map(ids["pdv"].codigo)

    # Orden y nombres finales.
    tabla = tabla.rename(columns={n: ETIQUETAS[n] for n in niveles})
    primeras = [ETIQUETAS[n] for n in niveles] + ([COLUMNA_CODIGO_PDV] if "pdv" in niveles else [])
    finales = medidas + [c for c in (COLUMNA_META, COLUMNA_PRESUPUESTO) if c in tabla.columns]
    medio = [c for c in tabla.columns if c not in primeras + finales]
    if COLUMNA_FECHA in medio:
        medio = [c for c in medio if c != COLUMNA_FECHA] + [COLUMNA_FECHA]
    tabla = tabla[primeras + medio + finales].reset_index(drop=True)

    avisos += _avisos(niveles, nivel_base, padres, ids, reales, tabla, sin_resultados, declaradas)
    mapeo = [{"archivo": t["archivo"], "hoja": t["hoja"], "filas": len(t["df"]),
              "uso": _uso(t), "columnas": [{"columna": x["columna"], "rol": x["rol"], "supuesto": x["supuesto"]}
                                           for x in t["roles"]]} for t in tablas]
    return {
        "tabla": tabla,
        "niveles": niveles,
        "nivel_base": nivel_base,
        "medidas": medidas,
        "meta": COLUMNA_META if COLUMNA_META in tabla.columns else None,
        "presupuesto": COLUMNA_PRESUPUESTO if COLUMNA_PRESUPUESTO in tabla.columns else None,
        "fecha": COLUMNA_FECHA if COLUMNA_FECHA in tabla.columns else None,
        "declaradas": declaradas,
        "red": {"padres": {n: {k: {p: set(s) for p, s in v.items()} for k, v in d.items()}
                           for n, d in padres.items()}},
        "codigos": {n: dict(ids[n].codigo) for n in niveles},
        "mapeo": mapeo,
        "avisos": avisos,
        "archivos": sorted({t["archivo"] for t in tablas}),
    }


def _uso(t: dict) -> str:
    roles = {x["rol"] for x in t["roles"]}
    partes_uso = []
    if t.get("niveles"):
        partes_uso.append("estructura (" + ", ".join(ETIQUETAS[n] for n in NIVELES if n in t["niveles"]) + ")")
    if "real" in roles:
        partes_uso.append("resultados")
    if "meta" in roles:
        partes_uso.append("metas")
    if "presupuesto" in roles:
        partes_uso.append("presupuesto")
    return " · ".join(partes_uso) if partes_uso else "no se usa (no trae columnas de la estructura)"


def _avisos(niveles, nivel_base, padres, ids, reales, tabla, sin_resultados, declaradas) -> list[dict]:
    """Lo que no cruzó: lo que a mano con BUSCARV se pierde sin que se note."""
    avisos = []
    # Nodos con resultados que no cuelgan de nadie, cuando hay estructura.
    for nivel in niveles[1:]:
        arriba = niveles[niveles.index(nivel) - 1]
        hay_estructura = any(padres[nivel].get(k) for k in padres[nivel])
        if not hay_estructura:
            continue
        memo: dict = {}
        huerfanos = sorted(k for k in ids[nivel].etiqueta.values()
                           if not any(ancestros(padres, nivel, k, a, memo) for a in niveles[:niveles.index(nivel)]))
        if huerfanos:
            avisos.append({"tipo": "error", "texto":
                           f"{len(huerfanos)} {PLURALES[nivel]} no tienen {ETIQUETAS[arriba].lower()} ni ningún "
                           f"superior asignado en los archivos: sus resultados no suman a ningún equipo.",
                           "ejemplos": huerfanos[:12]})
    for nivel in niveles:
        compartidos = sorted(k for k, ps in padres[nivel].items()
                             if any(len(s) > 1 for s in ps.values()))
        if compartidos:
            avisos.append({"tipo": "info", "texto":
                           f"{len(compartidos)} {PLURALES[nivel]} están con más de un superior a la vez. Sus "
                           f"resultados cuentan completos para cada uno, así que la suma de los equipos puede "
                           f"superar el total.", "ejemplos": compartidos[:12]})
    if reales and sin_resultados.get(nivel_base):
        nodos = sin_resultados[nivel_base]
        avisos.append({"tipo": "aviso", "texto":
                       f"{len(nodos)} {PLURALES[nivel_base]} están en la estructura pero no tienen ningún resultado "
                       f"en los archivos: quedan en cero.", "ejemplos": nodos[:12]})
    metas_base = declaradas["meta"].get(nivel_base, {})
    if metas_base:
        sin_meta = sorted(set(ids[nivel_base].etiqueta.values()) - set(metas_base))
        if sin_meta:
            avisos.append({"tipo": "aviso", "texto":
                           f"{len(sin_meta)} {PLURALES[nivel_base]} no tienen meta asignada.",
                           "ejemplos": sin_meta[:12]})
    for nivel in niveles:
        repetidos = ids[nivel].nombres_con_varios_codigos()
        if repetidos:
            avisos.append({"tipo": "aviso", "texto":
                           f"{len(repetidos)} nombre(s) de {PLURALES[nivel]} aparecen con más de un código: se "
                           f"tratan como personas o puntos distintos.", "ejemplos": repetidos[:12]})
    avisos += descuadres_de_meta(declaradas, padres, niveles)
    return avisos


def descuadres_de_meta(declaradas: dict, padres: dict, niveles: list[str]) -> list[dict]:
    """La meta de un nivel debe ser la suma de la de sus hijos (la del jefe,
    la de sus supervisores). Se avisa cuando no cuadra por más de 1 %."""
    avisos = []
    metas = declaradas.get("meta", {})
    con_meta = [n for n in niveles if metas.get(n)]
    for arriba, abajo in zip(con_meta, con_meta[1:]):
        suma: dict = defaultdict(float)
        for hijo, v in metas[abajo].items():
            for p in ancestros(padres, abajo, hijo, arriba):
                suma[p] += v
        malos = []
        for nodo, v in metas[arriba].items():
            s = suma.get(nodo)
            if s and abs(v - s) > 0.01 * max(abs(v), abs(s)):
                malos.append(f"{nodo}: {v:,.0f} vs {s:,.0f}")
        if malos:
            avisos.append({"tipo": "aviso", "texto":
                           f"La meta de {len(malos)} {PLURALES[arriba]} no es igual a la suma de la meta de sus "
                           f"{PLURALES[abajo]} (meta declarada vs suma).", "ejemplos": malos[:12]})
    return avisos


# ── 6. Navegación: cómo va cada uno ───────────────────────────────────────
def columna(nivel: str) -> str:
    return ETIQUETAS[nivel]


def miembros(serie: pd.Series, nodo: str) -> pd.Series:
    """Filas que pertenecen a `nodo`, incluidas las compartidas («A / B»)."""
    suyos = {v for v in serie.dropna().unique() if nodo in partes(v)}
    return serie.isin(suyos)


def corte(tabla: pd.DataFrame, res: dict, medida: Optional[str]) -> Optional[dict]:
    """Hasta qué día van los datos y cuánto del mes debería llevarse.

    El ritmo es por días calendario: al día 6 de un mes de 30 se espera el
    20 % de la meta. Si hay varios meses, se mide el último (la meta es del
    mes) y se dice."""
    fecha = res.get("fecha")
    if not fecha or fecha not in tabla.columns:
        return None
    validas = tabla[fecha]
    if medida and medida in tabla.columns:
        validas = validas[tabla[medida].notna() & (tabla[medida] != 0)]
    validas = pd.to_datetime(validas, errors="coerce").dropna()
    if validas.empty:
        return None
    ultimo = validas.max()
    meses = validas.dt.to_period("M").nunique()
    dias = ultimo.days_in_month
    return {"fecha": ultimo, "dia": int(ultimo.day), "dias_mes": int(dias),
            "esperado": ultimo.day / dias, "varios_meses": meses > 1, "mes": ultimo.to_period("M")}


def _del_mes(tabla: pd.DataFrame, res: dict, c: Optional[dict]) -> pd.Series:
    """Máscara de filas que cuentan para el resultado: las del mes de corte,
    más las que no tienen fecha (filas de estructura y de meta)."""
    if not c or not c["varios_meses"]:
        return pd.Series(True, index=tabla.index)
    f = pd.to_datetime(tabla[res["fecha"]], errors="coerce")
    return f.isna() | (f.dt.to_period("M") == c["mes"])


def _explotar(tabla: pd.DataFrame, col: str, valores: list[str]) -> pd.DataFrame:
    x = tabla[[col] + valores].copy()
    x[col] = x[col].map(partes)
    x = x.explode(col)
    return x[x[col].notna()]


def resumen_por_nivel(tabla: pd.DataFrame, res: dict, nivel: str, medida: Optional[str],
                      c: Optional[dict] = None) -> pd.DataFrame:
    """Un renglón por nodo del nivel con real, meta, cumplimiento, ritmo,
    proyección, faltante, estado y posición entre TODOS los del nivel que
    hay en `tabla` (la referencia es el grupo completo visible, no una
    selección)."""
    col = columna(nivel)
    if col not in tabla.columns:
        return pd.DataFrame()
    if c is None:
        c = corte(tabla, res, medida)
    filas = tabla[_del_mes(tabla, res, c)]
    valores = [medida] if medida and medida in filas.columns else []
    x = _explotar(filas, col, valores)
    if x.empty:
        return pd.DataFrame()
    g = x.groupby(col)
    out = pd.DataFrame(index=sorted(x[col].unique(), key=str))
    out.index.name = col
    out["Real"] = g[medida].sum() if valores else np.nan
    compartidas = filas[col].astype(str).str.contains(re.escape(SEPARADOR), na=False)
    if compartidas.any() and valores:
        xc = _explotar(filas[compartidas], col, valores)
        out["Compartido"] = xc.groupby(col)[medida].sum().reindex(out.index).fillna(0.0)
    else:
        out["Compartido"] = 0.0

    # Meta: la declarada para este nivel; si no hay, la suma de las del nivel
    # más cercano de abajo que sí tenga (la del jefe = suma de sus supervisores).
    meta_decl = res.get("declaradas", {}).get("meta", {})
    ppto_decl = res.get("declaradas", {}).get("presupuesto", {})
    out["Meta"], out["Origen meta"] = _medida_por_nodo(tabla, res, nivel, out.index, meta_decl)
    out["Presupuesto"], _ = _medida_por_nodo(tabla, res, nivel, out.index, ppto_decl)

    meta = out["Meta"]
    out["Cumplimiento"] = np.where(meta > 0, out["Real"] / meta, np.nan)
    out["Faltante"] = np.where(meta > 0, (meta - out["Real"]).clip(lower=0), np.nan)
    if c:
        out["Esperado hoy"] = np.where(meta > 0, meta * c["esperado"], np.nan)
        out["Proyección cierre"] = out["Real"] / c["dia"] * c["dias_mes"]
        out["Cumplimiento proyectado"] = np.where(meta > 0, out["Proyección cierre"] / meta, np.nan)
        restantes = c["dias_mes"] - c["dia"]
        out["Faltante por día"] = np.where((meta > 0) & (restantes > 0), out["Faltante"] / max(restantes, 1), np.nan)
    out["Estado"] = [estado(cu, c) for cu in out["Cumplimiento"]]

    return _posiciones(out).reset_index()


def _posiciones(out: pd.DataFrame) -> pd.DataFrame:
    """Puesto de cada uno dentro de la tabla que se le pasa: por cumplimiento
    si hay meta para comparar, si no por el resultado."""
    base = "Cumplimiento" if out["Cumplimiento"].notna().sum() >= 2 else "Real"
    out["Puesto"] = out[base].rank(ascending=False, method="min")
    out["De"] = int(out[base].notna().sum())
    return out


def _medida_por_nodo(tabla, res, nivel, nodos, declaradas: dict) -> tuple[pd.Series, pd.Series]:
    propias = declaradas.get(nivel, {})
    valores = pd.Series({n: propias.get(n, np.nan) for n in nodos}, dtype=float)
    origen = pd.Series({n: ("declarada" if n in propias else "") for n in nodos}, dtype=object)
    niveles = res["niveles"]
    abajo = next((n for n in niveles[niveles.index(nivel) + 1:] if declaradas.get(n)), None)
    if abajo is not None and columna(abajo) in tabla.columns:
        # Quién depende de quién sale de la RED, no de la fila: una fila de
        # Pedro dice «Marta / Sofía» y «Ana / Luis», y cruzar esas dos listas
        # le sumaría a Ana la meta de Marta, que es de Luis. Sí se respeta la
        # tabla para saber qué hijos están a la vista (filtros del panel).
        padres = res.get("red", {}).get("padres", {})
        visibles = {p for v in tabla[columna(abajo)].dropna().unique() for p in partes(v)}
        acumulado: dict = defaultdict(float)
        memo: dict = {}
        for hijo in visibles:
            v = declaradas[abajo].get(hijo)
            if v is None:
                continue
            for a in ancestros(padres, abajo, hijo, nivel, memo):
                acumulado[a] += v
        suma = pd.Series(acumulado, dtype=float)
        faltan = valores.isna()
        valores[faltan] = suma.reindex(valores.index)[faltan]
        origen[faltan & valores.notna()] = f"suma de {PLURALES[abajo]}"
    return valores, origen


def estado(cumplimiento, c: Optional[dict]) -> str:
    """Semáforo. Con fecha se mide contra lo que debería llevar hoy; sin
    fecha, contra la meta completa."""
    if cumplimiento is None or pd.isna(cumplimiento):
        return "⚪ Sin meta"
    referencia = c["esperado"] if c else 1.0
    r = cumplimiento / referencia if referencia else cumplimiento
    if r >= 1:
        return "🟢 Al día" if c else "🟢 Cumplió"
    if r >= 0.9:
        return "🟡 Algo atrasado" if c else "🟡 Cerca"
    return "🔴 Atrasado" if c else "🔴 Lejos"


def nivel_hijo(res: dict, nivel: str) -> Optional[str]:
    niveles = res["niveles"]
    i = niveles.index(nivel)
    return niveles[i + 1] if i + 1 < len(niveles) else None


def ficha(tabla: pd.DataFrame, res: dict, nivel: str, nodo: str, medida: Optional[str]) -> dict:
    """Todo lo de UN nodo: su renglón (comparado contra todo su nivel), sus
    cadenas de mando, lo que tiene debajo y los avisos que le tocan."""
    c = corte(tabla, res, medida)
    todos = resumen_por_nivel(tabla, res, nivel, medida, c)
    col = columna(nivel)
    fila = todos[todos[col] == nodo]
    propio = fila.iloc[0].to_dict() if not fila.empty else None
    hijo = nivel_hijo(res, nivel)
    debajo = pd.DataFrame()
    if hijo and col in tabla.columns:
        suyas = tabla[miembros(tabla[col], nodo)]
        debajo = resumen_por_nivel(suyas, res, hijo, medida, c)
        if not debajo.empty:
            # Solo los que de verdad dependen de él según la red: la fila de
            # un agente compartido dice «Marta / Sofía», y Marta no es de Ana.
            padres, memo = res.get("red", {}).get("padres", {}), {}
            propios = [nodo in ancestros(padres, hijo, h, nivel, memo) for h in debajo[columna(hijo)]]
            debajo = _posiciones(debajo[propios].set_index(columna(hijo))).reset_index()
    descuadre = None
    if propio and propio.get("Origen meta") == "declarada" and hijo:
        suma, _ = _medida_por_nodo(tabla, res, nivel, [nodo], {
            k: v for k, v in res.get("declaradas", {}).get("meta", {}).items() if k != nivel})
        s = suma.iloc[0] if len(suma) else np.nan
        m = propio.get("Meta")
        if pd.notna(s) and m and abs(m - s) > 0.01 * max(abs(m), abs(s)):
            descuadre = {"declarada": float(m), "suma": float(s)}
    datos = {}
    if nivel == "pdv" and col in tabla.columns:
        suyas = tabla[tabla[col] == nodo]
        for extra in suyas.columns:
            if extra in {columna(n) for n in NIVELES} or extra in (res.get("medidas") or []) \
                    or extra in {COLUMNA_META, COLUMNA_PRESUPUESTO, COLUMNA_FECHA}:
                continue
            v = suyas[extra].dropna()
            if not v.empty and v.nunique() == 1:
                datos[extra] = str(v.iloc[0])
    codigo = res.get("codigos", {}).get(nivel, {}).get(nodo)
    return {"nivel": nivel, "nodo": nodo, "codigo": codigo, "fila": propio, "grupo": len(todos),
            "rutas": rutas(res.get("red", {}), nivel, nodo), "hijo": hijo, "debajo": debajo,
            "corte": c, "descuadre": descuadre, "datos": datos}


def total_real(tabla: pd.DataFrame, res: dict, medida: Optional[str], c: Optional[dict] = None) -> Optional[float]:
    """El resultado de todo lo visible en el mes de corte, contado una vez
    (sumar los jefes contaría dos veces a los agentes compartidos)."""
    if not medida or medida not in tabla.columns:
        return None
    return float(numeric_series(tabla.loc[_del_mes(tabla, res, c), medida]).sum())


def meta_total(tabla: pd.DataFrame, res: dict, tipo: str = "meta") -> Optional[float]:
    """La meta de todo lo visible: la suma del nivel más bajo que tiene meta,
    cada nodo una sola vez. Es la única suma que no duplica a nadie."""
    declaradas = res.get("declaradas", {}).get(tipo, {})
    for nivel in reversed(res["niveles"]):
        valores = declaradas.get(nivel)
        if not valores or columna(nivel) not in tabla.columns:
            continue
        visibles = {p for v in tabla[columna(nivel)].dropna().unique() for p in partes(v)}
        suma = sum(v for n, v in valores.items() if n in visibles)
        return float(suma) if visibles & set(valores) else None
    return None


def nodos_de(tabla: pd.DataFrame, nivel: str) -> list[str]:
    col = columna(nivel)
    if col not in tabla.columns:
        return []
    return sorted({p for v in tabla[col].dropna().unique() for p in partes(v)}, key=str.casefold)


def medida_principal(res: dict) -> Optional[str]:
    """La medida de resultado que se compara contra la meta: la de escala más
    parecida a la meta (una meta se fija al tamaño de lo que mide); sin meta,
    la primera."""
    medidas = res.get("medidas") or []
    if not medidas:
        return None
    tabla, meta = res["tabla"], res.get("meta")
    if not meta or len(medidas) == 1:
        return medidas[0]
    objetivo = float(numeric_series(tabla[meta]).sum())

    def cercania(m):
        total = float(numeric_series(tabla[m]).sum())
        return min(total, objetivo) / max(total, objetivo) if total > 0 and objetivo > 0 else 0.0
    return max(medidas, key=cercania)


# ── 7. El cruce como archivo del panel ────────────────────────────────────
HOJA_UNIFICADA = "Estructura cruzada"


def libro_unificado(res: dict) -> dict:
    """La tabla unificada con la misma forma que devuelve
    `core/loader.load_workbook`, para cargarla como archivo activo del
    Análisis Completo: así todo el panel (filtros, resumen, cuadro,
    proyección, exportar) trabaja sobre los datos ya cruzados sin saber que
    vienen de varios archivos. `estructura: True` le dice a la app que
    muestre además la vista «🏢 Estructura»."""
    from datetime import datetime

    from .profile import profile_sheet

    tabla = res["tabla"]
    archivos = res.get("archivos") or []
    nombre = f"Estructura comercial ({len(archivos)} archivo{'s' if len(archivos) != 1 else ''})"
    item = profile_sheet(tabla, context={"sheet_name": HOJA_UNIFICADA, "workbook_name": nombre,
                                         "faltantes_son_cero": True},
                         structural_log=[f"Tabla armada cruzando: {', '.join(archivos)}."])
    item["profile"]["relationships"] = []
    item["profile"]["titulo"] = "Estructura comercial cruzada"
    return {
        "filename": nombre,
        "size_mb": float(tabla.memory_usage(deep=True).sum()) / 1024 / 1024,
        "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sheets": {HOJA_UNIFICADA: item},
        "ocultas": set(),
        "relationships": {HOJA_UNIFICADA: []},
        "avisos": [],
        "imagenes": [],
        "estructura": True,
    }
