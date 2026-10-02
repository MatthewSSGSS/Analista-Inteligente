"""Motor del Análisis Territorial: ubicar, resumir por zona y decir dónde crecer.

Sobre qué datos trabaja (todos en `assets/geo/`, sin conexión):

- `municipios_colombia.csv`: los 1.122 municipios del DIVIPOLA (DANE, vía
  datos.gov.co, dataset gdxc-w37w) con sus coordenadas y la población 2026 de
  las proyecciones municipales del DANE (PPED-AreaMun-2018-2042, actualizado
  en julio de 2025): total, cabecera, rural y proyección a 2030.
- `departamentos_colombia.geojson`: los contornos de los 33 departamentos
  (shapes de Maurix Suárez, simplificados a ~1 km), con su código DANE.

Qué hace:

1. `ubicar`: le pone a cada fila municipio y departamento, venga como venga
   el lugar —coordenadas, columna de municipio o de departamento, o el
   municipio escrito dentro de otro texto ("MC MULTICELL CIENEGA MAGDALENA")—.
   Se resuelve sobre los valores distintos, no fila por fila.
2. `zonas`: el resultado por municipio o departamento en el periodo elegido,
   con su variación frente al mes anterior, la meta si existe, la
   participación, la posición entre TODAS las zonas y la penetración por
   cada 10.000 habitantes.
3. `donde_crecer`: municipios grandes sin presencia en los departamentos
   donde ya se opera, y municipios con presencia muy por debajo de la
   penetración típica, con lo que valdría cerrar la mitad de esa brecha.
4. `motivos`: por qué subió o bajó una zona (o todo el territorio): la
   columna que concentra el movimiento —municipio, canal, asesor…— y los
   nombres que lo explican, y lo que se movió en contra.
5. `lectura`: las conclusiones en frases con nombre y cifra.

Mes a medias: si el último mes llega hasta un día bastante anterior al que
suelen llegar los demás meses del archivo, se compara contra el mes anterior
HASTA ESE MISMO DÍA (`corte_dia`). Sin eso, un mes cargado hasta el día 7
pinta todo el mapa de rojo con caídas del 80%.

No depende de Streamlit (ver CLAUDE.md): la vista cachea los resultados.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .gazetteer import buscar_lugar, columna_con_lugares, normalizar
from .numeric import numeric_valid

_RUTA = Path(__file__).resolve().parent.parent / "assets" / "geo"
# Caja de Colombia (con San Andrés): un punto fuera de aquí no se asigna a un
# municipio aunque haya uno "más cercano".
_COLOMBIA = (-4.5, 13.6, -82.0, -66.7)  # lat mín, lat máx, lon mín, lon máx
_DISTANCIA_MAXIMA_KM = 40.0             # más lejos que esto del centro del municipio, no se asigna
UMBRAL_ESTABLE = 0.05                  # ±5%: el semáforo lo deja en amarillo
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]


# ── Datos de Colombia ─────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def municipios() -> pd.DataFrame:
    df = pd.read_csv(_RUTA / "municipios_colombia.csv", dtype={"cod_mpio": str, "cod_dpto": str})
    return df


@lru_cache(maxsize=1)
def departamentos_geojson() -> dict:
    with open(_RUTA / "departamentos_colombia.geojson", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def municipios_geojson() -> dict:
    """Contornos de los municipios (DANE, Marco Geoestadístico Nacional 2018,
    simplificados a ~500 m). Cada feature trae `cod_mpio` y, para dibujar sin
    buscar, el índice del municipio en `municipios()` (`idx`)."""
    with open(_RUTA / "municipios_colombia.geojson", encoding="utf-8") as f:
        datos = json.load(f)
    indice = {cod: i for i, cod in enumerate(municipios()["cod_mpio"])}
    for feat in datos["features"]:
        feat["properties"]["idx"] = indice.get(feat["properties"]["cod_mpio"], -1)
    return datos


@lru_cache(maxsize=1)
def departamentos() -> pd.DataFrame:
    """Un renglón por departamento: nombre, población y su punto de referencia
    (el centro de su población, que cae sobre sus ciudades y no en la selva)."""
    m = municipios()
    pesos = m["poblacion"].clip(lower=1)
    g = m.assign(_lat=m["lat"] * pesos, _lon=m["lon"] * pesos, _w=pesos).groupby(["cod_dpto", "departamento"], as_index=False)
    d = g.agg(lat=("_lat", "sum"), lon=("_lon", "sum"), w=("_w", "sum"), poblacion=("poblacion", "sum"),
              municipios=("cod_mpio", "count"))
    d["lat"] /= d["w"]
    d["lon"] /= d["w"]
    return d.drop(columns="w")


def _variantes(nombre: str) -> set[str]:
    """Formas en que un archivo escribe un municipio: "Bogotá, D.C." también es
    "Bogota", "Bogota DC"; "San José de Cúcuta" también es "Cúcuta"."""
    base = normalizar(nombre)
    salida = {base}
    for sufijo in (" d c", " dc"):
        if base.endswith(sufijo):
            salida.add(base[: -len(sufijo)].strip())
    if base.startswith("san jose de "):
        salida.add(base[len("san jose de "):])
    return {s for s in salida if s}


@lru_cache(maxsize=1)
def _indice() -> tuple[dict, dict]:
    """{nombre normalizado: [índices de municipio]} y {departamento normalizado: código}."""
    m = municipios()
    por_nombre: dict[str, list[int]] = {}
    for i, nombre in enumerate(m["municipio"]):
        for clave in _variantes(nombre):
            por_nombre.setdefault(clave, []).append(i)
    por_depto = {}
    for cod, nombre in zip(m["cod_dpto"], m["departamento"]):
        for clave in _variantes(nombre):
            por_depto[clave] = cod
    # Nombres comunes de departamentos en los archivos.
    for alias, nombre in {"bogota": "11", "bogota dc": "11", "san andres": "88", "valle": "76",
                          "norte de santander": "54", "guajira": "44", "la guajira": "44"}.items():
        por_depto.setdefault(alias, nombre)
    return por_nombre, por_depto


def _mas_cercano(lat: np.ndarray, lon: np.ndarray, cod_dpto: Optional[str] = None) -> tuple[np.ndarray, np.ndarray]:
    """Índice del municipio más cercano a cada punto y su distancia en km."""
    m = municipios()
    candidatos = m.index.to_numpy() if cod_dpto is None else m.index[m["cod_dpto"] == cod_dpto].to_numpy()
    if not len(candidatos):
        candidatos = m.index.to_numpy()
    mlat = np.radians(m.loc[candidatos, "lat"].to_numpy())
    mlon = np.radians(m.loc[candidatos, "lon"].to_numpy())
    plat, plon = np.radians(lat)[:, None], np.radians(lon)[:, None]
    # Distancia equirrectangular: de sobra precisa a escala de municipio.
    x = (mlon[None, :] - plon) * np.cos((mlat[None, :] + plat) / 2)
    y = mlat[None, :] - plat
    d = np.sqrt(x * x + y * y) * 6371.0
    mejor = d.argmin(axis=1)
    return candidatos[mejor], d[np.arange(len(lat)), mejor]


def _resolver_nombre(texto, cod_dpto: Optional[str]) -> Optional[int]:
    """El municipio que nombra un texto, o None. Si el nombre se repite en
    varios departamentos y no hay pista, gana el más poblado."""
    if texto is None or (isinstance(texto, float) and math.isnan(texto)):
        return None
    por_nombre, _ = _indice()
    m = municipios()
    for clave in _variantes(str(texto)):
        indices = por_nombre.get(clave)
        if indices:
            if cod_dpto:
                del_depto = [i for i in indices if m.at[i, "cod_dpto"] == cod_dpto]
                if del_depto:
                    return del_depto[0]
            return max(indices, key=lambda i: m.at[i, "poblacion"])
    # Escritura aproximada o lugar dentro del texto: el lector del gazetteer
    # da coordenadas, y de ahí se toma el municipio del directorio completo.
    lugar = buscar_lugar(texto)
    if lugar and lugar.get("nivel") == "municipio":
        cod = cod_dpto or _depto_de_texto(lugar.get("departamento"))
        idx, dist = _mas_cercano(np.array([lugar["lat"]]), np.array([lugar["lon"]]), cod)
        if dist[0] <= _DISTANCIA_MAXIMA_KM:
            return int(idx[0])
    return None


def _depto_de_texto(texto) -> Optional[str]:
    if texto is None or (isinstance(texto, float) and math.isnan(texto)):
        return None
    _, por_depto = _indice()
    for clave in _variantes(str(texto)):
        if clave in por_depto:
            return por_depto[clave]
    lugar = buscar_lugar(texto)
    if lugar and lugar.get("departamento"):
        for clave in _variantes(lugar["departamento"]):
            if clave in por_depto:
                return por_depto[clave]
    return None


# ── 1. Ubicar ─────────────────────────────────────────────────────────────

def ubicar(df: pd.DataFrame, schema: dict) -> tuple[pd.DataFrame, dict]:
    """Copia de `df` con `_t_lat`, `_t_lon`, `_t_idx` (municipio), `_t_cod_dpto`
    y `_t_ok`, más un resumen de cómo se ubicó.

    Orden de confianza: coordenadas del archivo → columna de municipio o
    ciudad (con el departamento como desempate si viene) → columna de
    departamento → municipio escrito dentro de otro texto.
    """
    from .geo_engine import _columnas_de_persona, geo_columns

    out = df.copy()
    out["_t_lat"] = np.nan
    out["_t_lon"] = np.nan
    out["_t_idx"] = -1
    out["_t_cod_dpto"] = None
    meta = {"origen": "ninguno", "columna": None, "nivel": None, "total": len(df)}
    if df.empty:
        meta["ubicadas"] = 0
        return out.assign(_t_ok=False), meta
    cols = geo_columns(df, schema)
    m = municipios()

    # Coordenadas: el punto exacto, y el municipio más cercano si cae en Colombia.
    if cols["lat"] and cols["lon"]:
        lat = pd.to_numeric(df[cols["lat"]], errors="coerce")
        lon = pd.to_numeric(df[cols["lon"]], errors="coerce")
        validas = lat.between(-90, 90) & lon.between(-180, 180) & ~((lat == 0) & (lon == 0))
        if validas.mean() >= 0.3:
            out["_t_lat"] = lat.where(validas)
            out["_t_lon"] = lon.where(validas)
            en_col = validas & lat.between(_COLOMBIA[0], _COLOMBIA[1]) & lon.between(_COLOMBIA[2], _COLOMBIA[3])
            if en_col.any():
                pares = pd.DataFrame({"lat": lat[en_col].round(4), "lon": lon[en_col].round(4)}).drop_duplicates()
                idx, dist = _mas_cercano(pares["lat"].to_numpy(), pares["lon"].to_numpy())
                pares["_idx"] = np.where(dist <= _DISTANCIA_MAXIMA_KM, idx, -1)
                clave = pd.Series(list(zip(lat.round(4), lon.round(4))), index=df.index)
                mapa = dict(zip(zip(pares["lat"], pares["lon"]), pares["_idx"]))
                out.loc[en_col, "_t_idx"] = clave[en_col].map(mapa).fillna(-1).astype(int)
            meta.update(origen="coordenadas", columna=f"{cols['lat']} / {cols['lon']}", nivel="punto")
            return _cerrar(out, meta, m)

    depto_col = cols["region"] if cols["region"] and cols["region"] != cols["city"] else None
    if cols["city"]:
        # "" = sin pista de departamento. Un None o NaN como clave no se
        # encuentra a sí mismo al cruzar (NaN != NaN) y no se ubicaba nada.
        pistas = (df[depto_col].map(_depto_de_texto) if depto_col else pd.Series(None, index=df.index)).fillna("")
        pares = pd.DataFrame({"t": df[cols["city"]].astype(object), "d": pistas}).drop_duplicates()
        pares["_idx"] = [(_resolver_nombre(t, d or None) if pd.notna(t) else None) for t, d in zip(pares["t"], pares["d"])]
        resueltas = pares["_idx"].notna().mean() if len(pares) else 0
        if resueltas >= 0.3:
            mapa = {(t, d): i for t, d, i in zip(pares["t"], pares["d"], pares["_idx"])}
            idx = pd.Series([mapa.get((t, d)) for t, d in zip(df[cols["city"]].astype(object), pistas)], index=df.index)
            out["_t_idx"] = idx.fillna(-1).astype(int)
            meta.update(origen="municipio", columna=cols["city"], nivel="municipio")
            return _cerrar(out, meta, m)

    if depto_col:
        distintos = df[depto_col].dropna().unique()
        codigos = {v: _depto_de_texto(v) for v in distintos}
        if distintos.size and sum(c is not None for c in codigos.values()) / distintos.size >= 0.3:
            out["_t_cod_dpto"] = df[depto_col].map(codigos)
            d = departamentos().set_index("cod_dpto")
            out["_t_lat"] = out["_t_cod_dpto"].map(d["lat"])
            out["_t_lon"] = out["_t_cod_dpto"].map(d["lon"])
            meta.update(origen="departamento", columna=depto_col, nivel="departamento")
            return _cerrar(out, meta, m)

    columna, _ = columna_con_lugares(df, excluir=_columnas_de_persona(df, schema))
    if columna:
        distintos = df[columna].dropna().unique()
        mapa = {v: _resolver_nombre(v, None) for v in distintos}
        if distintos.size and sum(i is not None for i in mapa.values()) / distintos.size >= 0.2:
            out["_t_idx"] = df[columna].map(mapa).fillna(-1).astype(int)
            meta.update(origen="texto", columna=columna, nivel="municipio")
            return _cerrar(out, meta, m)

    meta["ubicadas"] = 0
    return out.assign(_t_ok=False), meta


def _cerrar(out: pd.DataFrame, meta: dict, m: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    con_mpio = out["_t_idx"] >= 0
    idx = out.loc[con_mpio, "_t_idx"].to_numpy()
    out.loc[con_mpio, "_t_cod_dpto"] = m["cod_dpto"].to_numpy()[idx]
    # Sin coordenadas propias, el punto es el centro del municipio.
    sin_punto = con_mpio & out["_t_lat"].isna()
    out.loc[sin_punto, "_t_lat"] = m["lat"].to_numpy()[out.loc[sin_punto, "_t_idx"].to_numpy()]
    out.loc[sin_punto, "_t_lon"] = m["lon"].to_numpy()[out.loc[sin_punto, "_t_idx"].to_numpy()]
    out["_t_ok"] = out["_t_lat"].notna() & out["_t_lon"].notna()
    meta["ubicadas"] = int(out["_t_ok"].sum())
    meta["con_municipio"] = int(con_mpio.sum())
    meta["en_colombia"] = bool(out["_t_cod_dpto"].notna().any())
    if meta["columna"] and meta["origen"] in {"municipio", "texto", "departamento"}:
        sin = out.loc[~out["_t_ok"], meta["columna"]].dropna().astype(str).str.strip()
        meta["no_ubicados"] = sin[sin != ""].value_counts().head(8).to_dict()
    return out, meta


# ── 2. Resumen por zona ───────────────────────────────────────────────────

def meses_disponibles(ub: pd.DataFrame, fecha_col: Optional[str]) -> list[str]:
    if not fecha_col or fecha_col not in ub.columns:
        return []
    f = pd.to_datetime(ub[fecha_col], errors="coerce").dropna()
    return sorted(f.dt.strftime("%Y-%m").unique())


def etiqueta_mes(clave: Optional[str], corta: bool = False) -> str:
    if not clave:
        return ""
    anio, mes = clave.split("-")
    nombre = _MESES[int(mes) - 1]
    return f"{nombre[:3]} {anio}" if corta else f"{nombre} de {anio}"


def _dia_de_corte(datos: pd.DataFrame, fecha_col: str, mes_b: str) -> Optional[int]:
    """Hasta qué día llega `mes_b` si está a medias; None si está completo.

    Misma regla que `core/diagnostics._periodo_parcial`: no se compara con
    el fin de mes del calendario (hay archivos que nunca registran los
    últimos días) sino con hasta dónde suelen llegar los demás meses del
    propio archivo.
    """
    f = pd.to_datetime(datos[fecha_col], errors="coerce")
    ultimo = f.groupby(f.dt.strftime("%Y-%m")).max().dt.day
    if mes_b not in ultimo.index or len(ultimo) < 2:
        return None
    tipico = float(ultimo.drop(mes_b).median())
    dia = int(ultimo[mes_b])
    return dia if dia < tipico - 5 else None


def _agregar(serie: pd.Series, calculo: str) -> float:
    if calculo == "Conteo":
        return float(len(serie))
    v = serie.dropna()
    if not len(v):
        return np.nan
    return float(v.mean() if calculo == "Promedio" else v.sum())


def zonas(ub: pd.DataFrame, metrica: Optional[str], calculo: str = "Suma", nivel: str = "municipio",
          fecha_col: Optional[str] = None, mes: Optional[str] = None, meta_col: Optional[str] = None) -> dict:
    """El resultado de cada zona en el periodo elegido.

    `mes` = "YYYY-MM" o None (todo el periodo). La variación es siempre el mes
    elegido (o el último con datos) frente al anterior; si ese mes está a
    medias, el anterior se corta en el mismo día (`corte_dia`). La posición,
    la participación y el promedio de referencia se calculan sobre TODAS las
    zonas visibles (regla del dominio), y se dice sobre cuántas.

    `estado` es el semáforo de cada zona: "subio" / "estable" / "bajo"
    (±`UMBRAL_ESTABLE`). En una métrica que se suma, una zona que aparece o
    desaparece entre los dos meses también cuenta (`tendencia` ±1).
    """
    m = municipios()
    datos = ub[ub["_t_ok"]].copy()
    vacio = {"tabla": pd.DataFrame(), "mes_a": None, "mes_b": None, "n": 0, "total": 0.0, "promedio": None,
             "corte_dia": None, "total_a": None, "total_b": None}
    if datos.empty:
        return vacio
    datos["_v"] = 1.0 if (metrica is None or calculo == "Conteo") else numeric_valid(datos[metrica])
    if meta_col and meta_col in datos.columns:
        datos["_meta"] = numeric_valid(datos[meta_col])
    meses = meses_disponibles(datos, fecha_col)
    if meses:
        fechas = pd.to_datetime(datos[fecha_col], errors="coerce")
        datos["_mes"] = fechas.dt.strftime("%Y-%m")
        datos["_dia"] = fechas.dt.day
    mes_b = mes if mes in meses else (meses[-1] if meses else None)
    mes_a = meses[meses.index(mes_b) - 1] if mes_b and meses.index(mes_b) > 0 else None
    corte = _dia_de_corte(datos, fecha_col, mes_b) if (mes_a and mes_b == meses[-1]) else None
    en_a = ((datos["_mes"] == mes_a) & ((datos["_dia"] <= corte) if corte else True)) if mes_a else None
    en_b = (datos["_mes"] == mes_b) if mes_a else None
    periodo = datos[datos["_mes"] == mes] if (mes and meses) else datos

    if nivel == "departamento":
        datos["_zona"] = datos["_t_cod_dpto"]
        periodo = periodo.assign(_zona=periodo["_t_cod_dpto"])
    elif nivel == "punto":
        datos["_zona"] = datos["_t_lat"].round(5).astype(str) + "," + datos["_t_lon"].round(5).astype(str)
        periodo = periodo.assign(_zona=datos.loc[periodo.index, "_zona"])
    else:
        datos["_zona"] = datos["_t_idx"].where(datos["_t_idx"] >= 0)
        periodo = periodo.assign(_zona=datos.loc[periodo.index, "_zona"])
    datos = datos.dropna(subset=["_zona"])
    periodo = periodo.dropna(subset=["_zona"])
    if periodo.empty:
        return vacio
    # Totales de los dos meses comparados, sobre las mismas filas que las zonas.
    total_a = _agregar(datos.loc[en_a.reindex(datos.index, fill_value=False), "_v"], calculo) if mes_a else None
    total_b = _agregar(datos.loc[en_b.reindex(datos.index, fill_value=False), "_v"], calculo) if mes_a else None

    g = periodo.groupby("_zona")
    tabla = pd.DataFrame({"valor": g["_v"].agg(lambda s: _agregar(s, calculo)), "registros": g.size(),
                          "lat": g["_t_lat"].mean(), "lon": g["_t_lon"].mean()})
    if "_meta" in periodo.columns:
        tabla["meta"] = g["_meta"].agg(lambda s: _agregar(s, "Promedio" if calculo == "Promedio" else "Suma"))
    if mes_a and mes_b:
        def del_mes(mascara):
            x = datos[mascara.reindex(datos.index, fill_value=False)].groupby("_zona")["_v"]
            return x.agg(lambda s: _agregar(s, calculo))
        tabla["mes_b"] = del_mes(en_b).reindex(tabla.index)
        tabla["mes_a"] = del_mes(en_a).reindex(tabla.index)
        a, b = tabla["mes_a"], tabla["mes_b"]
        tabla["variacion"] = np.where(a.notna() & (a != 0) & b.notna(), (b - a) / a.abs(), np.nan)
        # En una suma, no aparecer un mes es no aportar: el cambio cuenta como 0.
        tabla["cambio"] = (b.fillna(0) - a.fillna(0)) if calculo != "Promedio" else (b - a)
        tendencia = tabla["variacion"].astype(float).copy()
        if calculo != "Promedio":
            # Apareció o desapareció entre un mes y otro: ±100% para el semáforo.
            sin = tendencia.isna() & tabla["cambio"].fillna(0).ne(0)
            tendencia[sin] = np.sign(tabla.loc[sin, "cambio"]).astype(float)
        estado = pd.Series(None, index=tabla.index, dtype=object)
        estado[tendencia.notna()] = "estable"
        estado[tendencia < -UMBRAL_ESTABLE] = "bajo"
        estado[tendencia >= UMBRAL_ESTABLE] = "subio"
        tabla["tendencia"] = tendencia
        tabla["estado"] = estado

    # Nombres, departamento y población.
    if nivel == "departamento":
        d = departamentos().set_index("cod_dpto")
        tabla["nombre"] = tabla.index.map(d["departamento"])
        tabla["departamento"] = tabla["nombre"]
        tabla["poblacion"] = tabla.index.map(d["poblacion"])
        tabla["lat"] = tabla.index.map(d["lat"])
        tabla["lon"] = tabla.index.map(d["lon"])
    elif nivel == "punto":
        idx = periodo.groupby("_zona")["_t_idx"].first().reindex(tabla.index)
        ok = idx >= 0
        tabla["nombre"] = np.where(ok, m["municipio"].reindex(idx.clip(lower=0).to_numpy()).to_numpy(), "Punto")
        tabla["departamento"] = np.where(ok, m["departamento"].reindex(idx.clip(lower=0).to_numpy()).to_numpy(), "")
        tabla["poblacion"] = np.nan
    else:
        i = tabla.index.astype(int)
        tabla["nombre"] = m["municipio"].to_numpy()[i]
        tabla["departamento"] = m["departamento"].to_numpy()[i]
        tabla["cod_mpio"] = m["cod_mpio"].to_numpy()[i]
        tabla["poblacion"] = m["poblacion"].to_numpy()[i]
        tabla["lat"] = m["lat"].to_numpy()[i]
        tabla["lon"] = m["lon"].to_numpy()[i]

    tabla = tabla[tabla["valor"].notna()]
    sumable = calculo in {"Suma", "Conteo"}
    total = float(tabla["valor"].sum()) if sumable else float(tabla["valor"].mean())
    promedio = float(tabla["valor"].mean()) if len(tabla) else None
    tabla["participacion"] = tabla["valor"] / total if sumable and total else np.nan
    tabla["vs_promedio"] = (tabla["valor"] - promedio) / abs(promedio) if promedio else np.nan
    if "meta" in tabla.columns:
        tabla["cumplimiento"] = np.where(tabla["meta"] > 0, tabla["valor"] / tabla["meta"], np.nan)
    if sumable:
        tabla["por_10k"] = np.where(tabla["poblacion"] > 0, tabla["valor"] / tabla["poblacion"] * 10_000, np.nan)
    tabla = tabla.sort_values("valor", ascending=False)
    tabla["posicion"] = np.arange(1, len(tabla) + 1)
    tabla.index.name = "zona"
    return {"tabla": tabla.reset_index(), "mes_a": mes_a, "mes_b": mes_b, "n": len(tabla),
            "total": total, "promedio": promedio, "sumable": sumable, "nivel": nivel, "meses": meses,
            "corte_dia": corte, "total_a": total_a, "total_b": total_b}


def serie_total(ub: pd.DataFrame, metrica: Optional[str], calculo: str, fecha_col: Optional[str]) -> pd.DataFrame:
    """Mes a mes del total de los registros ubicados (para los mini-gráficos)."""
    datos = ub[ub["_t_ok"]]
    if not fecha_col or fecha_col not in datos.columns or datos.empty:
        return pd.DataFrame()
    v = 1.0 if (metrica is None or calculo == "Conteo") else numeric_valid(datos[metrica])
    tabla = pd.DataFrame({"mes": pd.to_datetime(datos[fecha_col], errors="coerce").dt.strftime("%Y-%m"), "_v": v})
    tabla = tabla.dropna(subset=["mes"])
    serie = tabla.groupby("mes")["_v"].agg(lambda s: _agregar(s, calculo)).sort_index()
    return serie.rename("valor").reset_index()


def serie_zona(ub: pd.DataFrame, zona, nivel: str, metrica: Optional[str], calculo: str,
               fecha_col: Optional[str]) -> pd.DataFrame:
    """Mes a mes de una zona y el promedio de todas las zonas ese mes."""
    datos = ub[ub["_t_ok"]].copy()
    if not fecha_col or datos.empty:
        return pd.DataFrame()
    datos["_v"] = 1.0 if (metrica is None or calculo == "Conteo") else numeric_valid(datos[metrica])
    datos["_mes"] = pd.to_datetime(datos[fecha_col], errors="coerce").dt.strftime("%Y-%m")
    if nivel == "departamento":
        datos["_zona"] = datos["_t_cod_dpto"]
    else:
        datos["_zona"] = datos["_t_idx"].where(datos["_t_idx"] >= 0)
    datos = datos.dropna(subset=["_mes", "_zona"])
    por = datos.groupby(["_mes", "_zona"])["_v"].agg(lambda s: _agregar(s, calculo)).unstack()
    if zona not in por.columns:
        try:
            zona = type(por.columns[0])(zona)
        except Exception:
            return pd.DataFrame()
    if zona not in por.columns:
        return pd.DataFrame()
    return pd.DataFrame({"mes": por.index, "zona": por[zona].to_numpy(), "promedio": por.mean(axis=1).to_numpy()})


def hexagonos(ub: pd.DataFrame, metrica: Optional[str], calculo: str, radio_km: float,
              fecha_col: Optional[str] = None, mes: Optional[str] = None) -> pd.DataFrame:
    """Agrupa los puntos en hexágonos de `radio_km` y suma (o promedia) cada uno.

    Se calcula aquí y no con el HexagonLayer de deck.gl: en la versión 9.3 la
    agregación con pesos ignora la escala de color pedida y, con la
    agregación explícita, dibuja los hexágonos planos. Calculándolos en
    Python, cada hexágono trae su valor real para el tooltip y la misma
    escala de color y altura que el resto de las vistas.

    Rejilla hexagonal «punta arriba» en coordenadas axiales sobre una
    proyección local en km (de sobra precisa a escala de país).
    """
    datos = ub[ub["_t_ok"]]
    if fecha_col and mes and fecha_col in datos.columns:
        datos = datos[pd.to_datetime(datos[fecha_col], errors="coerce").dt.strftime("%Y-%m") == mes]
    if datos.empty or radio_km <= 0:
        return pd.DataFrame()
    lat = datos["_t_lat"].astype(float).to_numpy()
    lon = datos["_t_lon"].astype(float).to_numpy()
    lat0 = float(np.nanmean(lat))
    kx, ky = 111.32 * math.cos(math.radians(lat0)), 110.574
    x, y = (lon - float(np.nanmean(lon))) * kx, (lat - lat0) * ky
    q = (math.sqrt(3) / 3 * x - y / 3) / radio_km
    r = (2 / 3 * y) / radio_km
    # Redondeo cúbico: el hexágono que de verdad contiene el punto.
    cx, cz = q, r
    cy = -cx - cz
    rx, ry, rz = np.round(cx), np.round(cy), np.round(cz)
    dx, dy, dz = np.abs(rx - cx), np.abs(ry - cy), np.abs(rz - cz)
    rx = np.where((dx > dy) & (dx > dz), -ry - rz, rx)
    rz = np.where(~((dx > dy) & (dx > dz)) & ~(dy > dz), -rx - ry, rz)
    tabla = pd.DataFrame({"q": rx.astype(int), "r": rz.astype(int),
                          "_v": 1.0 if (metrica is None or calculo == "Conteo") else numeric_valid(datos[metrica]).to_numpy(),
                          "_idx": datos["_t_idx"].to_numpy()})
    g = tabla.groupby(["q", "r"])
    salida = pd.DataFrame({"valor": g["_v"].agg(lambda s: _agregar(s, calculo)), "registros": g.size(),
                           "_idx": g["_idx"].agg(lambda s: s[s >= 0].mode().iloc[0] if (s >= 0).any() else -1)}).reset_index()
    salida = salida[salida["valor"].notna()]
    cx_km = radio_km * math.sqrt(3) * (salida["q"] + salida["r"] / 2)
    cy_km = radio_km * 1.5 * salida["r"]
    salida["lon"] = float(np.nanmean(lon)) + cx_km / kx
    salida["lat"] = lat0 + cy_km / ky
    m = municipios()
    con = salida["_idx"] >= 0
    salida["nombre"] = np.where(con, "Cerca de " + m["municipio"].reindex(salida["_idx"].clip(lower=0)).fillna("").to_numpy(),
                                f"Zona de {radio_km:g} km")
    salida["departamento"] = np.where(con, m["departamento"].reindex(salida["_idx"].clip(lower=0)).fillna("").to_numpy(), "")
    salida = salida.sort_values("valor", ascending=False).reset_index(drop=True)
    total = float(salida["valor"].sum()) if calculo != "Promedio" else np.nan
    salida["participacion"] = salida["valor"] / total if total else np.nan
    salida["posicion"] = np.arange(1, len(salida) + 1)
    salida["poblacion"] = np.nan
    salida["zona"] = salida["q"].astype(str) + "," + salida["r"].astype(str)
    return salida


# ── 3. Dónde crecer ───────────────────────────────────────────────────────

def donde_crecer(z: dict, maximo: int = 12) -> dict:
    """Blancos y rezagados, con lo que valdría cerrar la brecha a la mitad.

    Solo con métricas que se suman y nivel municipio: la penetración (valor
    por cada 10.000 habitantes) es lo que hace comparable a Montería con
    Bogotá. La referencia es la penetración MEDIANA de los municipios donde ya
    se opera; prometer llegar a la mediana sería optimista, así que se valora
    la mitad del camino (la misma regla que «nivelar» en los planes).
    """
    tabla = z.get("tabla")
    if tabla is None or tabla.empty or z.get("nivel") != "municipio" or not z.get("sumable"):
        return {"blancos": pd.DataFrame(), "rezagados": pd.DataFrame(), "penetracion_tipica": None}
    activos = tabla[(tabla["valor"] > 0) & (tabla["poblacion"] > 0)]
    if len(activos) < 5:
        return {"blancos": pd.DataFrame(), "rezagados": pd.DataFrame(), "penetracion_tipica": None}
    tipica = float(activos["por_10k"].median())
    m = municipios()
    deptos = set(activos["departamento"])
    presentes = set(activos["cod_mpio"])
    blancos = m[m["departamento"].isin(deptos) & ~m["cod_mpio"].isin(presentes)].copy()
    blancos["potencial"] = tipica * blancos["poblacion"] / 10_000 * 0.5
    blancos = blancos.sort_values("poblacion", ascending=False).head(maximo)
    rezagados = activos[(activos["por_10k"] < tipica * 0.5) & (activos["poblacion"] >= 20_000)].copy()
    rezagados["potencial"] = (tipica - rezagados["por_10k"]) * rezagados["poblacion"] / 10_000 * 0.5
    rezagados = rezagados.sort_values("potencial", ascending=False).head(maximo)
    return {"blancos": blancos, "rezagados": rezagados, "penetracion_tipica": tipica}


def cobertura(z: dict) -> dict:
    """Cuánta gente vive donde hay presencia: en el país y en los departamentos donde se opera."""
    tabla = z.get("tabla")
    if tabla is None or tabla.empty or z.get("nivel") != "municipio":
        return {}
    m = municipios()
    activos = tabla[tabla["valor"] > 0]
    deptos = set(activos["departamento"])
    pob_activos = float(activos["poblacion"].sum())
    pob_deptos = float(m.loc[m["departamento"].isin(deptos), "poblacion"].sum())
    return {"municipios": len(activos), "de_municipios": len(m),
            "municipios_deptos": int(m["departamento"].isin(deptos).sum()), "departamentos": len(deptos),
            "pob_cubierta": pob_activos, "pct_pais": pob_activos / float(m["poblacion"].sum()),
            "pct_deptos": pob_activos / pob_deptos if pob_deptos else None}


# ── 4. Semáforo y por qué se movió ────────────────────────────────────────

def semaforo(z: dict) -> dict:
    """Cuántas zonas subieron, se quedaron estables o bajaron, y cuánto movieron.

    {"subio": {"n", "cambio", "tabla"}, "estable": {...}, "bajo": {...}, "con_dato": n}
    o {} si no hay mes anterior con qué comparar.
    """
    tabla = z.get("tabla")
    if tabla is None or tabla.empty or "estado" not in tabla.columns:
        return {}
    salida = {"con_dato": int(tabla["estado"].notna().sum())}
    if not salida["con_dato"]:
        return {}
    for clave in ("subio", "estable", "bajo"):
        parte = tabla[tabla["estado"] == clave]
        orden = parte.sort_values("cambio", ascending=clave == "bajo") if "cambio" in parte.columns else parte
        salida[clave] = {"n": int(len(parte)), "cambio": float(parte["cambio"].sum()) if "cambio" in parte.columns else 0.0,
                         "tabla": orden}
    return salida


def _filas_zona(ub: pd.DataFrame, zona, nivel: str) -> pd.DataFrame:
    datos = ub[ub["_t_ok"]]
    if zona is None:
        return datos
    if nivel == "departamento":
        return datos[datos["_t_cod_dpto"] == str(zona)]
    if nivel == "punto":
        clave = datos["_t_lat"].round(5).astype(str) + "," + datos["_t_lon"].round(5).astype(str)
        return datos[clave == str(zona)]
    try:
        return datos[datos["_t_idx"] == int(float(zona))]
    except (TypeError, ValueError):
        return datos.iloc[0:0]


def motivos(ub: pd.DataFrame, metrica: Optional[str], calculo: str, fecha_col: Optional[str], z: dict,
            dims: list, zona=None, nivel: str = "municipio", geografia: bool = False, maximo: int = 3) -> Optional[dict]:
    """Por qué subió o bajó una zona (o todo el territorio, con `zona=None`).

    Compara los mismos dos meses que `zonas` (`z["mes_a"]` → `z["mes_b"]`,
    con el mismo corte de día si el último mes va a medias). Entre las
    columnas candidatas —`dims` y, con `geografia=True`, el municipio y el
    departamento de cada fila— elige la que concentra el movimiento en menos
    nombres: la parte del movimiento que explican sus dos mayores segmentos,
    menos la que explicarían si todo estuviera repartido parejo (2 de N).
    Con 4 canales, que 2 expliquen el 60% no dice nada; con 30 asesores, sí.

    Solo en métricas que se suman: en un promedio, el cambio de cada
    segmento no se suma al del total y la explicación sería falsa.
    """
    if not (fecha_col and z.get("mes_a") and z.get("sumable")):
        return None
    datos = _filas_zona(ub, zona, nivel)
    if datos.empty or fecha_col not in datos.columns:
        return None
    v = 1.0 if (metrica is None or calculo == "Conteo") else numeric_valid(datos[metrica]).fillna(0.0)
    datos = datos.assign(_v=v)
    fechas = pd.to_datetime(datos[fecha_col], errors="coerce")
    mes = fechas.dt.strftime("%Y-%m")
    en_b = mes == z["mes_b"]
    en_a = mes == z["mes_a"]
    if z.get("corte_dia"):
        en_a &= fechas.dt.day <= z["corte_dia"]
    antes, ahora = float(datos.loc[en_a, "_v"].sum()), float(datos.loc[en_b, "_v"].sum())
    delta = ahora - antes
    if not delta:
        return None

    candidatas = {}
    if geografia:
        m = municipios()
        if zona is None or nivel == "departamento":
            idx = datos["_t_idx"].fillna(-1).astype(int)
            nombres = m["municipio"].reindex(idx.clip(lower=0).to_numpy()).to_numpy()
            candidatas["Municipio"] = pd.Series(np.where(idx.to_numpy() >= 0, nombres, None), index=datos.index)
        if zona is None:
            candidatas["Departamento"] = datos["_t_cod_dpto"].map(departamentos().set_index("cod_dpto")["departamento"])
    for c in dims:
        if c in datos.columns and c not in candidatas:
            candidatas[c] = datos[c]

    signo = 1 if delta > 0 else -1
    mejor = None
    for orden, (columna, serie) in enumerate(candidatas.items()):
        texto = serie.astype(str).str.strip()
        valido = serie.notna() & texto.ne("") & texto.str.lower().ne("nan")
        a = datos.loc[en_a & valido, "_v"].groupby(texto[en_a & valido]).sum()
        b = datos.loc[en_b & valido, "_v"].groupby(texto[en_b & valido]).sum()
        mov = pd.DataFrame({"antes": a, "ahora": b}).fillna(0.0)
        if len(mov) < 2 or len(mov) > 80:
            continue
        mov["delta"] = mov["ahora"] - mov["antes"]
        mismo = mov["delta"][mov["delta"] * signo > 0].abs().sort_values(ascending=False)
        bruto = float(mismo.sum())
        if bruto <= 0:
            continue
        n = len(mov)
        concentracion = (float(mismo.head(1).sum()) / bruto - 1 / n + float(mismo.head(2).sum()) / bruto - min(2, n) / n) / 2
        # Ruido: una columna cuyos segmentos suben y bajan mucho entre sí (los
        # asesores se reparten clientes de un mes a otro) mueve mucho en bruto
        # y poco en neto; no explica el cambio de la zona. Se pondera por la
        # parte neta del movimiento.
        neto = abs(delta) / float(mov["delta"].abs().sum())
        puntaje = concentracion * min(neto, 1.0)
        clave = (round(puntaje, 3), -orden)
        if mejor is None or clave > mejor[0]:
            mejor = (clave, columna, mov)
    if mejor is None:
        return None
    _, columna, mov = mejor
    principales = mov[mov["delta"] * signo > 0].sort_values("delta", ascending=signo < 0).head(maximo)
    contrarios = mov[mov["delta"] * signo < 0].sort_values("delta", ascending=signo > 0).head(2)

    def _seg(nombre, f):
        return {"nombre": str(nombre), "antes": float(f["antes"]), "ahora": float(f["ahora"]), "delta": float(f["delta"]),
                "pct": float(f["delta"] / f["antes"]) if f["antes"] else None,
                "peso": float(f["delta"] / delta), "nuevo": bool(not f["antes"] and f["ahora"] > 0),
                "perdido": bool(f["antes"] > 0 and not f["ahora"])}

    segmentos = [_seg(n, f) for n, f in principales.iterrows()]
    return {"dimension": columna, "antes": antes, "ahora": ahora, "delta": delta,
            "pct": delta / abs(antes) if antes else None, "segmentos": segmentos,
            "compensaron": [_seg(n, f) for n, f in contrarios.iterrows()],
            "explicado": sum(s["delta"] for s in segmentos) / delta, "n_segmentos": int(len(mov)),
            "movimiento": mov.sort_values("delta")}


def cifra_signo(v) -> str:
    """+12 mil / −9 mil (con el signo menos tipográfico)."""
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return ("+" if v > 0 else "−" if v < 0 else "") + cifra(abs(v))


def frase_motivo(m: Optional[dict], etiqueta: str, corta: bool = False) -> str:
    """«por canal: **Tienda** (−90 mil) y **Online** (−30 mil); en contra fue **Calle** (+5 mil)»."""
    if not m or not m.get("segmentos"):
        return ""

    def _uno(s):
        extra = " · nuevo" if s["nuevo"] else " · dejó de vender" if s["perdido"] else ""
        return f"**{s['nombre']}** ({cifra_signo(s['delta'])}{extra})"

    segs = m["segmentos"][:2] if corta else m["segmentos"]
    nombres = [_uno(s) for s in segs]
    texto = f"por {etiqueta.lower()}: " + (", ".join(nombres[:-1]) + " y " + nombres[-1] if len(nombres) > 1 else nombres[0])
    if not corta and m.get("compensaron"):
        texto += f"; en contra fue {_uno(m['compensaron'][0])}"
    return texto


# ── 5. Lectura ────────────────────────────────────────────────────────────

def cifra(v) -> str:
    """Cifra corta en español: 1,2 M · 609 mil · 4.300."""
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    a = abs(v)
    if a >= 1e9:
        return f"{v / 1e9:,.1f} mil M"
    if a >= 1e6:
        return f"{v / 1e6:,.1f} M"
    if a >= 1e4:
        return f"{v / 1e3:,.0f} mil"
    return f"{v:,.0f}" if float(v).is_integer() or a >= 100 else f"{v:,.1f}"


def lectura(z: dict, crecer: dict, cob: dict, metrica_label: str) -> list[str]:
    """Las conclusiones del territorio, en frases con nombre y cifra."""
    tabla = z.get("tabla")
    if tabla is None or tabla.empty:
        return []
    frases = []
    n = z["n"]
    zona = "departamentos" if z.get("nivel") == "departamento" else "municipios"
    articulo = "Los"
    if z.get("corte_dia"):
        frases.append(f"**{etiqueta_mes(z['mes_b']).capitalize()}** va hasta el día {z['corte_dia']}: se compara contra "
                      f"{etiqueta_mes(z['mes_a'])} hasta ese mismo día, para no confundir un mes a medias con una caída.")
    sem = semaforo(z)
    if sem:
        frases.append(f"Semáforo de {etiqueta_mes(z['mes_b'])} frente a {etiqueta_mes(z['mes_a'])}: "
                      f"**{sem['subio']['n']} {zona} subieron**, {sem['estable']['n']} se mantuvieron (±5%) y "
                      f"**{sem['bajo']['n']} bajaron**.")
    if z.get("sumable") and n >= 3:
        top = tabla.head(3)
        pct = float(top["valor"].sum() / tabla["valor"].sum()) if tabla["valor"].sum() else 0
        frases.append(f"{articulo} 3 {zona} más fuertes ({', '.join(top['nombre'].astype(str))}) concentran el "
                      f"**{pct:.0%}** de {metrica_label.lower()}; hay {n} {zona} con actividad.")
    if "cambio" in tabla.columns and z.get("mes_a"):
        caidas = tabla[tabla["cambio"] < 0].sort_values("cambio").head(3)
        subidas = tabla[tabla["cambio"] > 0].sort_values("cambio", ascending=False).head(3)
        periodo = f"{etiqueta_mes(z['mes_b'])} frente a {etiqueta_mes(z['mes_a'])}"
        if len(caidas):
            frases.append("Donde más se perdió en " + periodo + ": " + ", ".join(
                f"**{r.nombre}** ({cifra(r.cambio)}" + (f", {r.variacion:+.0%}" if pd.notna(r.variacion) else "") + ")"
                for r in caidas.itertuples()) + ".")
        if len(subidas):
            frases.append("Donde más se ganó: " + ", ".join(
                f"**{r.nombre}** (+{cifra(r.cambio)})" for r in subidas.itertuples()) + ".")
    if "cumplimiento" in tabla.columns and tabla["cumplimiento"].notna().sum() >= 2:
        con = tabla.dropna(subset=["cumplimiento"])
        cumplen = int((con["cumplimiento"] >= 1).sum())
        frases.append(f"{cumplen} de {len(con)} {zona} cumplen su meta.")
    if cob:
        frases.append(f"Hay presencia en **{cob['municipios']} de {cob['municipios_deptos']} municipios** de los "
                      f"{cob['departamentos']} departamentos donde se opera: ahí vive el "
                      f"**{cob['pct_deptos']:.0%}** de su población ({cifra(cob['pob_cubierta'])} personas, "
                      f"el {cob['pct_pais']:.0%} del país).")
    blancos = crecer.get("blancos")
    if blancos is not None and len(blancos):
        b = blancos.head(3)
        frases.append("Municipios grandes sin presencia en tus departamentos: " + ", ".join(
            f"**{r.municipio}** ({cifra(r.poblacion)} hab.)" for r in b.itertuples()) + ".")
    rez = crecer.get("rezagados")
    if rez is not None and len(rez):
        r0 = rez.iloc[0]
        frases.append(f"**{r0['nombre']}** ({cifra(r0['poblacion'])} hab.) tiene {cifra(r0['por_10k'])} por cada "
                      f"10.000 habitantes, frente a {cifra(crecer['penetracion_tipica'])} en un municipio típico de tu "
                      f"red: llevarlo a la mitad del camino vale **{cifra(r0['potencial'])}**.")
    return frases
