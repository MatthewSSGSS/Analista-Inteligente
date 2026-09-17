"""Cálculos de la pestaña Analítica: siete lentes para explorar un archivo.

La versión anterior del explorador cruzaba "una columna contra una métrica"
y nada más, con tres problemas que se veían en pantalla con un archivo real:

- dejaba elegir CUALQUIER columna como dimensión, incluidas métricas y
  fechas: agrupar por "Altas Totales" daba 372 grupos de una fila cada uno;
- rotulaba todo con el concepto genérico ("Cantidad") en vez del nombre de
  la columna, así que elegir "Altas Eje" mostraba "Cantidad" por todas partes;
- sumaba siempre, también un ARPU o una participación, y la "Evolución"
  ignoraba la dimensión elegida.

Aquí cada lente responde UNA pregunta concreta y devuelve, además de la
tabla, los hallazgos en frases con nombre y cifra:

1. ranking          ¿Quién pesa más y cuántos explican el 80%?
2. evolucion        ¿Cómo se movió cada grupo en el tiempo?
3. periodo_vs_periodo  ¿Qué cambió entre dos periodos y quién lo explica?
4. tabla_cruzada    ¿Cómo se reparte una dimensión dentro de otra?
5. cumplimiento     ¿Cuánto se ejecutó de lo presupuestado?
6. relacion         ¿Dos métricas se mueven juntas? ¿Quién se sale de lo esperado?
7. distribucion     ¿Qué tan parejos son los registros dentro de cada grupo?

Nada de esto importa Streamlit: se prueba con `tests/explorador_test.py`.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

import numpy as np
import pandas as pd

from .cuadro_comparativo import _limpiar_grupo, opciones_de_comparacion
from .diagnostics import ADITIVAS, _fmt, _lista, _mes, _periodo_parcial, _semantica
from .numeric import numeric_valid

CALCULOS = ["Automático", "Suma", "Promedio", "Mediana", "Conteo", "Máximo", "Mínimo"]
_FUNCION = {"Suma": "sum", "Promedio": "mean", "Mediana": "median", "Conteo": "count",
            "Máximo": "max", "Mínimo": "min"}
GRANOS = ["Mes", "Trimestre", "Año", "Semana", "Día"]
NORMALIZACIONES = ["Valores", "% de la fila", "% de la columna", "% del total"]
PERIODO = "__periodo__"  # valor especial de "columnas" en la tabla cruzada

# Nombres que delatan una métrica que NO se suma aunque el motor semántico la
# haya clasificado como cantidad: un ARPU, una participación o un divisor
# sumados entre puntos dan una cifra que no existe.
RATIO_RE = re.compile(
    r"arpu|promedio|\bprom\b|tasa|ratio|%|porc|\bpct\b|\bpart\b|participaci|divisor|indice|índice|"
    r"margen|ticket|precio|price|rate|average|avg|score|calificaci|puntaje|nps|edad|age",
    re.I,
)

# Palabras que marcan una columna como meta o como ejecución. Se usan para
# emparejar "PPTO RECMES0" con "EJEC RECMES0" quitando esa palabra y
# comparando lo que queda.
_META = {"ppto", "presupuesto", "presup", "presupto", "meta", "metas", "objetivo", "cuota", "target",
         "budget", "goal", "plan", "planeado", "proyectado", "esperado", "forecast"}
_REAL = {"ejec", "ejecutado", "ejecucion", "ejecutada", "real", "logro", "logrado", "resultado",
         "actual", "cumplido", "venta", "ventas"}

_MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


# ── Utilidades ─────────────────────────────────────────────────────────────

def _palabras(texto) -> list[str]:
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).lower()
    return [p for p in re.split(r"[^a-z0-9]+", t) if p]


def _pct(v, signo=False) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v):
        return "—"
    if signo:
        return f"{v:+.1f}%" if abs(v) < 10 else f"{v:+.0f}%"
    return f"{v:.1f}%" if abs(v) < 10 else f"{v:.0f}%"


def dimensiones(df: pd.DataFrame, schema: dict) -> list[str]:
    """Columnas por las que tiene sentido agrupar. Nunca métricas, fechas ni códigos."""
    return opciones_de_comparacion(df, schema)


def metricas(df: pd.DataFrame, schema: dict) -> list[str]:
    """Columnas numéricas con al menos un valor, en el orden del esquema."""
    fechas, ids = set(schema.get("dates", [])), set(schema.get("ids", []))
    fuera = []
    for c in schema.get("metrics", []):
        if c in df.columns and c not in fechas and c not in ids and numeric_valid(df[c]).notna().any():
            fuera.append(c)
    preferida = schema.get("metrica_preferida")
    if preferida in fuera:
        fuera = [preferida] + [c for c in fuera if c != preferida]
    return fuera


def columna_fecha(df: pd.DataFrame, schema: dict) -> Optional[str]:
    for d in schema.get("dates", []):
        if d in df.columns and pd.to_datetime(df[d], errors="coerce").notna().any():
            return d
    return None


def calculo_automatico(df: pd.DataFrame, schema: dict, metrica) -> str:
    """Suma o promedio, según lo que la métrica ES y no solo cómo se clasificó.

    - Un nombre de tasa, precio o promedio (ARPU, PART, %) se promedia.
    - Una métrica que el motor reconoce como sumable se suma.
    - Una sin clasificar se suma si son enteros no negativos (altas,
      portabilidades, kits: conteos) y se promedia en cualquier otro caso.
    """
    if metrica is None:
        return "Conteo"
    if RATIO_RE.search(str(metrica)):
        return "Promedio"
    tipo = _semantica(schema).get(metrica, "")
    if tipo in ADITIVAS:
        return "Suma"
    if tipo in {"", "unknown"} and metrica in df.columns:
        v = numeric_valid(df[metrica]).dropna()
        if len(v) and float((v >= 0).mean()) == 1.0 and float((v % 1 == 0).mean()) >= 0.98:
            return "Suma"
    return "Promedio"


def resolver_calculo(df, schema, metrica, calculo: str) -> str:
    """El cálculo real que se aplica: 'Automático' se traduce a uno concreto."""
    if calculo == "Automático" or calculo not in _FUNCION:
        return calculo_automatico(df, schema, metrica)
    return calculo


def es_sumable(calculo: str) -> bool:
    """Participación, acumulado y aportes solo tienen sentido sobre sumas o conteos."""
    return calculo in {"Suma", "Conteo"}


def _base(df, metrica, dim=None) -> pd.DataFrame:
    """Tabla de trabajo: grupo (si hay) + valor numérico (NaN si falta, no 0)."""
    datos = pd.DataFrame(index=df.index)
    datos["_valor"] = 1.0 if metrica is None else numeric_valid(df[metrica])
    if dim is not None:
        datos["_grupo"] = _limpiar_grupo(df[dim])
        datos = datos.dropna(subset=["_grupo"])
    return datos


def _agregar(agrupado, calculo: str):
    fn = _FUNCION[calculo]
    return agrupado.size() if fn == "count" else getattr(agrupado, fn)()


def _periodizar(fechas: pd.Series, grano: str) -> pd.Series:
    f = pd.to_datetime(fechas, errors="coerce")
    if grano == "Día":
        return f.dt.floor("D")
    if grano == "Semana":
        return f.dt.to_period("W").dt.start_time
    if grano == "Trimestre":
        return f.dt.to_period("Q").dt.start_time
    if grano == "Año":
        return f.dt.to_period("Y").dt.start_time
    return f.dt.to_period("M").dt.start_time


def etiqueta_periodo(t, grano: str = "Mes") -> str:
    t = pd.Timestamp(t)
    if grano == "Año":
        return str(t.year)
    if grano == "Trimestre":
        return f"T{(t.month - 1) // 3 + 1} {t.year}"
    if grano == "Semana":
        return f"sem. {t:%d/%m/%Y}"
    if grano == "Día":
        return f"{t:%d/%m/%Y}"
    return f"{_MESES_CORTOS[t.month - 1]} {t.year}"


def grano_sugerido(df: pd.DataFrame, schema: dict) -> Optional[str]:
    """El grano más grueso que da al menos dos periodos. None si ninguno.

    Un archivo de cortes mensuales se lee por mes; uno con 30 días de un solo
    mes no tiene "evolución mensual", pero sí semanal o diaria.
    """
    for grano in ("Mes", "Semana", "Día"):
        if len(periodos_disponibles(df, schema, grano)) >= 2:
            return grano
    return None


def ultimo_incompleto(df: pd.DataFrame, schema: dict, metrica, calculo: str, grano: str = "Mes") -> bool:
    """¿El último periodo está a medias? Si lo está, parece que todo se desplomó.

    Dos señales, porque cada una sola falla con archivos reales:

    - por días (`diagnostics._periodo_parcial`): el último mes llega a menos
      días de lo habitual. No sirve cuando cada mes se registra con fecha
      del día 1, que es justo como vienen los cortes mensuales;
    - por volumen: en una suma, el último periodo vale menos de la mitad de
      la mediana de los anteriores. Un corte real de 50% en un mes existe,
      pero es mucho más raro que un mes que todavía no terminó, y se dice
      como posibilidad, no como hecho.
    """
    col = columna_fecha(df, schema)
    if col is None:
        return False
    if grano == "Mes" and _periodo_parcial(df, col):
        return True
    # Por día o por semana un periodo flojo es normal (un domingo, un festivo):
    # la señal por volumen solo se usa en periodos largos.
    if not es_sumable(calculo) or grano in {"Día", "Semana"}:
        return False
    datos = _base(df, None if calculo == "Conteo" else metrica)
    datos["_periodo"] = _periodizar(df[col], grano)
    serie = _agregar(datos.dropna(subset=["_periodo"]).groupby("_periodo")["_valor"], calculo).sort_index()
    if len(serie) < 3:
        return False
    previa = float(serie.iloc[:-1].median())
    return previa > 0 and float(serie.iloc[-1]) < previa * 0.5


def _frase_extremos(cambios: dict, contexto: str) -> str:
    """"El que más creció / el que más cayó", sin decir que creció algo que bajó."""
    mejor = max(cambios, key=cambios.get)
    peor = min(cambios, key=cambios.get)
    if cambios[peor] >= 0:
        return (f"{contexto}, todos subieron: más **{mejor}** ({_pct(cambios[mejor], True)}) "
                f"y menos **{peor}** ({_pct(cambios[peor], True)}).")
    if cambios[mejor] < 0:
        return (f"{contexto}, todos bajaron: la mayor caída fue **{peor}** ({_pct(cambios[peor], True)}) "
                f"y la menor **{mejor}** ({_pct(cambios[mejor], True)}).")
    return (f"{contexto}, **{mejor}** es el que más creció ({_pct(cambios[mejor], True)}) "
            f"y **{peor}** el que más cayó ({_pct(cambios[peor], True)}).")


def periodos_disponibles(df: pd.DataFrame, schema: dict, grano: str = "Mes") -> list:
    col = columna_fecha(df, schema)
    if col is None:
        return []
    return sorted(_periodizar(df[col], grano).dropna().unique())


# ── 1. Ranking y concentración ─────────────────────────────────────────────

def ranking(df, schema, dim, metrica, calculo="Automático", ascendente=False) -> Optional[dict]:
    calculo = resolver_calculo(df, schema, metrica, calculo)
    datos = _base(df, None if calculo == "Conteo" else metrica, dim)
    if datos.empty:
        return None
    valores = _agregar(datos.groupby("_grupo")["_valor"], calculo).dropna()
    registros = datos.groupby("_grupo").size()
    if len(valores) < 2:
        return None
    valores = valores.sort_values(ascending=ascendente)
    sumable = es_sumable(calculo)
    total = float(valores.sum())
    promedio = float(valores.mean())
    tabla = pd.DataFrame({
        "Posición": range(1, len(valores) + 1),
        dim: valores.index.astype(str),
        "Valor": valores.values,
        "Registros": registros.reindex(valores.index).values,
    })
    if sumable and total > 0:
        # La participación y el acumulado se calculan siempre de mayor a menor,
        # aunque la tabla se muestre al revés: "cuántos hacen el 80%" no cambia
        # con el orden en que se lee.
        desc = valores.sort_values(ascending=False)
        acumulado = (desc.cumsum() / total * 100)
        tabla["Participación %"] = (valores / total * 100).values
        tabla["Acumulado %"] = acumulado.reindex(valores.index).values
    tabla["Vs. promedio %"] = ((valores - promedio) / abs(promedio) * 100).values if promedio else np.nan

    hallazgos = []
    desc = valores.sort_values(ascending=False)
    n = len(desc)
    hallazgos.append(f"**{desc.index[0]}** es el más alto con {_fmt(desc.iloc[0])} y **{desc.index[-1]}** "
                     f"el más bajo con {_fmt(desc.iloc[-1])}; el promedio de los {n} es {_fmt(promedio)}.")
    pareto_n = None
    if sumable and total > 0:
        pareto_n = int((desc.cumsum() / total * 100 < 80).sum()) + 1
        pareto_n = min(pareto_n, n)
        top3 = float(desc.head(3).sum() / total * 100)
        hallazgos.append(f"{pareto_n} de {n} ({pareto_n / n * 100:.0f}%) explican el 80% del total. "
                         f"Los 3 primeros suman el {top3:.0f}%.")
        if pareto_n / n <= 0.2:
            hallazgos.append("El resultado está **muy concentrado**: perder a uno de los primeros pesa más "
                             "que mejorar a todos los de abajo.")
        elif pareto_n / n >= 0.6:
            hallazgos.append("El resultado está **repartido**: ningún grupo por sí solo mueve el total.")
    if desc.iloc[-1] != 0 and desc.iloc[0] / desc.iloc[-1] >= 3 and desc.iloc[-1] > 0:
        hallazgos.append(f"El primero multiplica por {desc.iloc[0] / desc.iloc[-1]:.1f} al último.")
    debajo = int((valores < promedio * 0.9).sum())
    if debajo:
        hallazgos.append(f"{debajo} de {n} están más de 10% por debajo del promedio.")
    return {"tabla": tabla, "calculo": calculo, "sumable": sumable, "total": total, "promedio": promedio,
            "n": n, "pareto_n": pareto_n, "hallazgos": hallazgos}


# ── 2. Evolución por grupo ─────────────────────────────────────────────────

def evolucion(df, schema, dim, metrica, calculo="Automático", grupos=None, grano="Mes",
              modo="Valor", top=5) -> Optional[dict]:
    """Matriz periodo × grupo. Sin `dim`, una sola serie con el total."""
    col = columna_fecha(df, schema)
    if col is None:
        return None
    calculo = resolver_calculo(df, schema, metrica, calculo)
    datos = _base(df, None if calculo == "Conteo" else metrica, dim)
    datos["_periodo"] = _periodizar(df.loc[datos.index, col], grano)
    datos = datos.dropna(subset=["_periodo"])
    if datos.empty:
        return None
    if dim is None:
        datos["_grupo"] = "Total"
        elegidos = ["Total"]
        promedio_grupo, total_grupo = None, 1
    else:
        orden = _agregar(datos.groupby("_grupo")["_valor"], calculo).sort_values(ascending=False)
        elegidos = [g for g in (grupos or []) if g in orden.index] or list(orden.index[:top])
        # Referencia: el promedio por periodo de TODOS los grupos, antes de
        # quedarse con los elegidos. Comparar 5 líneas solo entre ellas no dice
        # si van bien o mal frente al resto.
        por_grupo = _agregar(datos.groupby(["_periodo", "_grupo"])["_valor"], calculo).unstack("_grupo").sort_index()
        promedio_grupo, total_grupo = por_grupo.mean(axis=1), len(orden)
        datos = datos[datos["_grupo"].isin(elegidos)]
    matriz = _agregar(datos.groupby(["_periodo", "_grupo"])["_valor"], calculo).unstack("_grupo").sort_index()
    matriz = matriz.reindex(columns=[g for g in elegidos if g in matriz.columns])
    if es_sumable(calculo):
        matriz = matriz.fillna(0)  # sin registros en un periodo = cero real
    if len(matriz) < 2:
        return None
    if promedio_grupo is not None:
        promedio_grupo = promedio_grupo.reindex(matriz.index)

    parcial = len(matriz) >= 3 and ultimo_incompleto(df, schema, metrica, calculo, grano)
    base_mat = matriz
    if modo == "Acumulado" and es_sumable(calculo):
        matriz = matriz.cumsum()
    elif modo == "Índice (inicio = 100)":
        primeros = base_mat.apply(lambda s: s.dropna().iloc[0] if s.dropna().size else np.nan)
        matriz = base_mat.divide(primeros.replace(0, np.nan)) * 100

    # Hallazgos sobre los valores de cada periodo, no sobre el acumulado.
    comparable = base_mat.iloc[:-1] if parcial else base_mat
    hallazgos = []
    ini, fin = comparable.index[0], comparable.index[-1]
    cambios = {}
    for g in comparable.columns:
        s = comparable[g].dropna()
        if len(s) >= 2 and s.iloc[0] != 0:
            cambios[g] = float((s.iloc[-1] - s.iloc[0]) / abs(s.iloc[0]) * 100)
    rango = f"entre {etiqueta_periodo(ini, grano)} y {etiqueta_periodo(fin, grano)}"
    if cambios:
        if len(cambios) == 1:
            unico = next(iter(cambios))
            hallazgos.append(f"**{unico}** cambió {_pct(cambios[unico], True)} {rango}.")
        else:
            hallazgos.append(_frase_extremos(cambios, rango[0].upper() + rango[1:]))
    for g in comparable.columns[:3]:
        s = comparable[g].dropna()
        if len(s) >= 3:
            pico = s.idxmax()
            valle = s.idxmin()
            hallazgos.append(f"**{g}**: su mejor periodo fue {etiqueta_periodo(pico, grano)} ({_fmt(s.max())}) "
                             f"y el más bajo {etiqueta_periodo(valle, grano)} ({_fmt(s.min())}).")
    if len(comparable) >= 3:
        ultimos = comparable.iloc[-3:]
        cayendo = [g for g in ultimos.columns if ultimos[g].dropna().size == 3
                   and ultimos[g].iloc[2] < ultimos[g].iloc[1] < ultimos[g].iloc[0]]
        if cayendo:
            hallazgos.append(f"Caen dos periodos seguidos: {_lista(cayendo[:4])}.")
    if promedio_grupo is not None and total_grupo > len(comparable.columns):
        ultimo = comparable.index[-1]
        ref = promedio_grupo.get(ultimo)
        if ref is not None and pd.notna(ref):
            arriba = [g for g in comparable.columns if pd.notna(comparable[g].get(ultimo)) and comparable[g][ultimo] >= ref]
            hallazgos.append(f"En {etiqueta_periodo(ultimo, grano)}, {len(arriba)} de los {len(comparable.columns)} "
                             f"que estás viendo están en o sobre el promedio de los {total_grupo} ({_fmt(ref)}).")
    if parcial:
        hallazgos.insert(0, f"⚠️ {etiqueta_periodo(base_mat.index[-1], grano)} parece incompleto (vale mucho menos "
                            "que los anteriores o llega a menos días): se dejó fuera de estas conclusiones.")
    return {"matriz": matriz, "calculo": calculo, "grupos": list(matriz.columns), "grano": grano,
            "modo": modo, "parcial": bool(parcial), "hallazgos": hallazgos,
            "promedio_grupo": promedio_grupo, "total_grupo": total_grupo}


# ── 3. Periodo contra periodo ──────────────────────────────────────────────

def periodo_vs_periodo(df, schema, dim, metrica, a, b, calculo="Automático", grano="Mes") -> Optional[dict]:
    col = columna_fecha(df, schema)
    if col is None:
        return None
    calculo = resolver_calculo(df, schema, metrica, calculo)
    datos = _base(df, None if calculo == "Conteo" else metrica, dim)
    datos["_periodo"] = _periodizar(df.loc[datos.index, col], grano)
    a, b = pd.Timestamp(a), pd.Timestamp(b)
    va = _agregar(datos[datos["_periodo"] == a].groupby("_grupo")["_valor"], calculo)
    vb = _agregar(datos[datos["_periodo"] == b].groupby("_grupo")["_valor"], calculo)
    grupos = va.index.union(vb.index)
    if len(grupos) < 1:
        return None
    sumable = es_sumable(calculo)
    va, vb = va.reindex(grupos), vb.reindex(grupos)
    if sumable:
        va, vb = va.fillna(0), vb.fillna(0)
    ea, eb = etiqueta_periodo(a, grano), etiqueta_periodo(b, grano)
    dif = vb - va
    variacion = (dif / va.abs().replace(0, np.nan) * 100)
    tabla = pd.DataFrame({dim: grupos.astype(str), ea: va.values, eb: vb.values,
                          "Diferencia": dif.values, "Variación %": variacion.values})
    total_a = float(va.sum()) if sumable else float(va.mean())
    total_b = float(vb.sum()) if sumable else float(vb.mean())
    cambio_total = total_b - total_a
    if sumable and cambio_total != 0:
        # Dividido entre el cambio CON su signo: los que empujan en la misma
        # dirección que el total suman positivo y entre todos dan 100%. Así
        # "35%" siempre quiere decir "explica el 35% de lo que pasó", tanto si
        # el total subió como si bajó.
        tabla["Aporte al cambio %"] = (dif / cambio_total * 100).values
    tabla = tabla.reindex(tabla["Diferencia"].abs().sort_values(ascending=False).index).reset_index(drop=True)

    hallazgos = []
    que = "El total" if sumable else "El promedio"
    pct_total = (cambio_total / abs(total_a) * 100) if total_a else None
    hallazgos.append(f"{que} pasó de {_fmt(total_a)} en {ea} a {_fmt(total_b)} en {eb} "
                     f"({_pct(pct_total, True)}, {'+' if cambio_total >= 0 else ''}{_fmt(cambio_total)}).")
    suben = tabla[tabla["Diferencia"] > 0]
    bajan = tabla[tabla["Diferencia"] < 0]
    if not suben.empty:
        top = suben.head(3)
        hallazgos.append("Más sumaron: " + _lista([f"**{r[dim]}** (+{_fmt(r['Diferencia'])})" for _, r in top.iterrows()]) + ".")
    if not bajan.empty:
        top = bajan.head(3)
        hallazgos.append("Más restaron: " + _lista([f"**{r[dim]}** ({_fmt(r['Diferencia'])})" for _, r in top.iterrows()]) + ".")
    if sumable and cambio_total < 0 and not bajan.empty:
        peso = float(-bajan.head(3)["Diferencia"].sum() / abs(cambio_total) * 100)
        if peso >= 50:
            hallazgos.append(f"Esos 3 explican el {min(peso, 999):.0f}% de la caída: por ahí empezar.")
    elif sumable and cambio_total > 0 and not suben.empty:
        peso = float(suben.head(3)["Diferencia"].sum() / cambio_total * 100)
        if peso >= 50:
            hallazgos.append(f"Esos 3 explican el {min(peso, 999):.0f}% del crecimiento.")
    ultimo = periodos_disponibles(df, schema, grano)
    if ultimo and b == pd.Timestamp(ultimo[-1]) and ultimo_incompleto(df, schema, metrica, calculo, grano):
        hallazgos.insert(0, f"⚠️ {eb} parece incompleto: una caída así puede ser solo que el periodo no ha "
                            "terminado. Compara dos periodos cerrados antes de sacar conclusiones.")
    if sumable:
        nuevos = tabla[(tabla[ea] == 0) & (tabla[eb] > 0)][dim].tolist()
        perdidos = tabla[(tabla[ea] > 0) & (tabla[eb] == 0)][dim].tolist()
        if nuevos:
            hallazgos.append(f"Aparecen en {eb} sin actividad en {ea}: {_lista(nuevos[:4])}.")
        if perdidos:
            hallazgos.append(f"Tenían actividad en {ea} y nada en {eb}: {_lista(perdidos[:4])}.")
    return {"tabla": tabla, "calculo": calculo, "sumable": sumable, "etiqueta_a": ea, "etiqueta_b": eb,
            "total_a": total_a, "total_b": total_b, "hallazgos": hallazgos}


# ── 4. Tabla cruzada ───────────────────────────────────────────────────────

def tabla_cruzada(df, schema, filas, columnas, metrica, calculo="Automático", normalizar="Valores",
                  grano="Mes", max_filas=25, max_columnas=15) -> Optional[dict]:
    calculo = resolver_calculo(df, schema, metrica, calculo)
    datos = _base(df, None if calculo == "Conteo" else metrica, filas)
    if columnas == PERIODO:
        col = columna_fecha(df, schema)
        if col is None:
            return None
        datos["_col"] = _periodizar(df.loc[datos.index, col], grano)
    else:
        datos["_col"] = _limpiar_grupo(df.loc[datos.index, columnas])
    datos = datos.dropna(subset=["_col"])
    if datos.empty:
        return None
    # Los grupos con más peso primero; el resto se deja fuera y se dice.
    peso_f = datos.groupby("_grupo")["_valor"].size().sort_values(ascending=False)
    peso_c = datos.groupby("_col")["_valor"].size().sort_values(ascending=False)
    f_keep, c_keep = list(peso_f.index[:max_filas]), list(peso_c.index[:max_columnas])
    recorte = len(peso_f) > max_filas or len(peso_c) > max_columnas
    datos = datos[datos["_grupo"].isin(f_keep) & datos["_col"].isin(c_keep)]
    matriz = _agregar(datos.groupby(["_grupo", "_col"])["_valor"], calculo).unstack("_col")
    matriz = matriz.reindex(sorted(matriz.columns) if columnas == PERIODO else c_keep, axis=1)
    sumable = es_sumable(calculo)
    if sumable:
        matriz = matriz.fillna(0)
    # Filas en orden de su total, para que la matriz se lea de arriba a abajo.
    matriz = matriz.loc[matriz.sum(axis=1).sort_values(ascending=False).index]
    if columnas == PERIODO:
        matriz.columns = [etiqueta_periodo(c, grano) for c in matriz.columns]
    if matriz.shape[0] < 1 or matriz.shape[1] < 2:
        return None

    valores = matriz
    if sumable and normalizar == "% de la fila":
        valores = matriz.div(matriz.sum(axis=1).replace(0, np.nan), axis=0) * 100
    elif sumable and normalizar == "% de la columna":
        valores = matriz.div(matriz.sum(axis=0).replace(0, np.nan), axis=1) * 100
    elif sumable and normalizar == "% del total":
        valores = matriz / (matriz.values.sum() or np.nan) * 100
    else:
        normalizar = "Valores"

    hallazgos = []
    pila = matriz.stack()
    if not pila.empty:
        (fi, co), v = pila.idxmax(), pila.max()
        hallazgos.append(f"La combinación más alta es **{fi}** × **{co}** con {_fmt(v)}.")
    if sumable and matriz.shape[0] >= 2:
        reparto = matriz.div(matriz.sum(axis=1).replace(0, np.nan), axis=0)
        dominante = reparto.max(axis=1)
        concentrados = dominante[dominante >= 0.7]
        if not concentrados.empty:
            nombres = [f"**{f}** ({dominante[f] * 100:.0f}% en {reparto.loc[f].idxmax()})" for f in concentrados.index[:3]]
            hallazgos.append("Dependen casi de una sola columna: " + _lista(nombres) + ".")
    if columnas == PERIODO and matriz.shape[1] >= 2:
        ultima, previa = matriz.columns[-1], matriz.columns[-2]
        base_prev = matriz[previa].replace(0, np.nan)
        cambio = ((matriz[ultima] - matriz[previa]) / base_prev.abs() * 100).dropna()
        if len(cambio) >= 2 and cambio.abs().sum() > 0:
            hallazgos.append(_frase_extremos(cambio.to_dict(), f"De {previa} a {ultima}"))
        if ultimo_incompleto(df, schema, metrica, calculo, grano):
            hallazgos.insert(0, f"⚠️ {ultima} parece incompleto: vale mucho menos que los periodos anteriores.")
    vacias = int((matriz == 0).sum().sum()) if sumable else int(matriz.isna().sum().sum())
    if vacias:
        hallazgos.append(f"{vacias} combinaciones no tienen actividad.")
    if recorte:
        hallazgos.append(f"Se muestran las {len(f_keep)} filas y {len(c_keep)} columnas con más registros.")
    return {"matriz": matriz, "valores": valores, "normalizar": normalizar, "calculo": calculo,
            "sumable": sumable, "hallazgos": hallazgos}


# ── 5. Ejecutado contra presupuesto ────────────────────────────────────────

def pares_meta_real(df, schema) -> list[dict]:
    """Parejas (real, meta) que el archivo trae, emparejadas por nombre.

    "PPTO RECMES0" y "EJEC RECMES0" quedan en "recmes0" al quitar la palabra
    de meta y la de ejecución: son la misma cosa medida de dos formas. Si no
    hay palabra de ejecución, la meta se empareja con la columna que se llama
    igual sin la palabra de meta ("Meta Altas" ↔ "Altas").
    """
    cols = metricas(df, schema)
    clave = {}
    for c in cols:
        p = _palabras(c)
        clave[c] = (bool(set(p) & _META), bool(set(p) & _REAL),
                    " ".join(w for w in p if w not in _META and w not in _REAL))
    pares = []
    for meta, (es_meta, _, resto) in clave.items():
        if not es_meta or not resto:
            continue
        candidatos = [c for c, (m2, _, r2) in clave.items() if not m2 and r2 == resto and c != meta]
        if RATIO_RE.search(str(meta)):
            continue
        candidatos = [c for c in candidatos if not RATIO_RE.search(str(c))]
        if candidatos:
            # Con varias, la que trae palabra de ejecución ("EJEC …") gana.
            real = sorted(candidatos, key=lambda c: (not clave[c][1], len(str(c))))[0]
            pares.append({"real": real, "meta": meta, "etiqueta": f"{real} vs. {meta}"})
    return pares


def cumplimiento(df, schema, dim, real, meta) -> Optional[dict]:
    if real not in df.columns or meta not in df.columns:
        return None
    datos = pd.DataFrame({"_real": numeric_valid(df[real]), "_meta": numeric_valid(df[meta])})
    if dim is not None:
        datos["_grupo"] = _limpiar_grupo(df[dim])
        datos = datos.dropna(subset=["_grupo"])
        agr = datos.groupby("_grupo")[["_real", "_meta"]].sum()
    else:
        agr = pd.DataFrame({"_real": [datos["_real"].sum()], "_meta": [datos["_meta"].sum()]}, index=["Total"])
    agr = agr[agr["_meta"] > 0]
    if agr.empty:
        return None
    agr["cumplimiento"] = agr["_real"] / agr["_meta"] * 100
    agr["brecha"] = agr["_real"] - agr["_meta"]
    agr = agr.sort_values("cumplimiento", ascending=False)
    tabla = pd.DataFrame({dim or "Grupo": agr.index.astype(str), real: agr["_real"].values, meta: agr["_meta"].values,
                          "Cumplimiento %": agr["cumplimiento"].values, "Brecha": agr["brecha"].values})
    total_real, total_meta = float(agr["_real"].sum()), float(agr["_meta"].sum())
    total = total_real / total_meta * 100 if total_meta else None

    hallazgos = [f"En conjunto se ejecutó {_fmt(total_real)} de {_fmt(total_meta)}: **{_pct(total)}** de cumplimiento "
                 f"({'sobran' if total_real >= total_meta else 'faltan'} {_fmt(abs(total_real - total_meta))})."]
    n = len(agr)
    cumplen = agr[agr["cumplimiento"] >= 100]
    hallazgos.append(f"{len(cumplen)} de {n} llegan al 100%." + (
        f" Lo logran {_lista([f'**{x}**' for x in cumplen.index[:4]])}." if 0 < len(cumplen) <= 4 else ""))
    if n >= 2:
        hallazgos.append(f"Mejor cumplimiento: **{agr.index[0]}** ({_pct(agr['cumplimiento'].iloc[0])}); "
                         f"peor: **{agr.index[-1]}** ({_pct(agr['cumplimiento'].iloc[-1])}).")
        faltante = agr[agr["brecha"] < 0].sort_values("brecha")
        if not faltante.empty and total_real < total_meta:
            peso = float(-faltante["brecha"].head(3).sum() / (total_meta - total_real) * 100)
            hallazgos.append("Donde más falta en cifras: " + _lista(
                [f"**{x}** ({_fmt(faltante.loc[x, 'brecha'])})" for x in faltante.index[:3]])
                + f". Cerrar esas 3 brechas cubre el {min(peso, 100):.0f}% de lo que falta.")
    if total is not None and total < 30:
        hallazgos.append("Un cumplimiento tan bajo puede significar que el periodo aún está en curso "
                         "o que la meta es de un periodo más largo: revisa que las dos columnas midan lo mismo.")
    return {"tabla": tabla, "total": total, "total_real": total_real, "total_meta": total_meta, "hallazgos": hallazgos}


# ── 6. Relación entre dos métricas ─────────────────────────────────────────

def _fuerza(r: float) -> str:
    a = abs(r)
    if a >= 0.7:
        return "fuerte"
    if a >= 0.4:
        return "moderada"
    if a >= 0.2:
        return "débil"
    return "casi nula"


def relacion(df, schema, dim, mx, my, calculo="Automático") -> Optional[dict]:
    """Una métrica contra otra, por grupo (o por registro si no hay dimensión)."""
    if mx not in df.columns or my not in df.columns or mx == my:
        return None
    cx = resolver_calculo(df, schema, mx, calculo)
    cy = resolver_calculo(df, schema, my, calculo)
    datos = pd.DataFrame({"_x": numeric_valid(df[mx]), "_y": numeric_valid(df[my])})
    if dim is not None:
        datos["_grupo"] = _limpiar_grupo(df[dim])
        datos = datos.dropna(subset=["_grupo"])
        g = datos.groupby("_grupo")
        puntos = pd.DataFrame({"x": _agregar(g["_x"], cx), "y": _agregar(g["_y"], cy)})
    else:
        puntos = datos.rename(columns={"_x": "x", "_y": "y"})[["x", "y"]]
    puntos = puntos.dropna()
    if len(puntos) < 3 or puntos["x"].nunique() < 2 or puntos["y"].nunique() < 2:
        return None
    r = float(np.corrcoef(puntos["x"], puntos["y"])[0, 1])
    pendiente, intercepto = np.polyfit(puntos["x"], puntos["y"], 1)
    esperado = pendiente * puntos["x"] + intercepto
    residuo = puntos["y"] - esperado
    puntos = puntos.assign(esperado=esperado, residuo=residuo)
    med_x, med_y = float(puntos["x"].median()), float(puntos["y"].median())

    hallazgos = []
    sentido = "suben juntas" if r > 0 else "cuando una sube la otra baja"
    hallazgos.append(f"La relación entre «{mx}» y «{my}» es **{_fuerza(r)}** (r = {r:.2f}): "
                     + (f"{sentido}." if abs(r) >= 0.2 else "no se mueven juntas de forma clara."))
    if abs(r) >= 0.4:
        cifra = _fmt(pendiente) if abs(pendiente) >= 100 else f"{pendiente:,.2f}"
        hallazgos.append(f"En promedio, cada 1 más de «{mx}» va con {cifra} de «{my}».")
    if dim is not None and len(puntos) >= 5 and abs(r) >= 0.2:
        escala = float(residuo.std()) or 1.0
        arriba = puntos[puntos["residuo"] > escala].sort_values("residuo", ascending=False)
        abajo = puntos[puntos["residuo"] < -escala].sort_values("residuo")
        if not arriba.empty:
            hallazgos.append(f"Rinden **más de lo esperado** en «{my}» para su «{mx}»: "
                             + _lista([f"**{x}**" for x in arriba.index[:3]]) + ".")
        if not abajo.empty:
            hallazgos.append(f"Rinden **menos de lo esperado**: " + _lista([f"**{x}**" for x in abajo.index[:3]])
                             + ". Tienen el volumen para más.")
    altos = int(((puntos["x"] >= med_x) & (puntos["y"] >= med_y)).sum())
    hallazgos.append(f"{altos} de {len(puntos)} están por encima de la mediana en las dos métricas.")
    return {"puntos": puntos, "r": r, "pendiente": float(pendiente), "intercepto": float(intercepto),
            "mediana_x": med_x, "mediana_y": med_y, "calculo_x": cx, "calculo_y": cy, "hallazgos": hallazgos}


# ── 7. Distribución dentro de cada grupo ───────────────────────────────────

def distribucion(df, schema, dim, metrica, top=12) -> Optional[dict]:
    datos = _base(df, metrica, dim).dropna(subset=["_valor"])
    if datos.empty:
        return None
    if dim is None:
        datos["_grupo"] = "Todos"
    orden = datos.groupby("_grupo")["_valor"].median().sort_values(ascending=False)
    grupos = list(orden.index[:top])
    datos = datos[datos["_grupo"].isin(grupos)]
    g = datos.groupby("_grupo")["_valor"]
    tabla = pd.DataFrame({
        "Registros": g.size(), "Mínimo": g.min(), "P25": g.quantile(0.25), "Mediana": g.median(),
        "P75": g.quantile(0.75), "Máximo": g.max(), "Promedio": g.mean(),
    }).reindex(grupos)
    tabla["Dispersión %"] = (g.std() / g.mean().abs().replace(0, np.nan) * 100).reindex(grupos)
    tabla = tabla.reset_index().rename(columns={"_grupo": dim or "Grupo"})

    hallazgos = []
    validos = tabla.dropna(subset=["Dispersión %"])
    validos = validos[validos["Registros"] >= 3]
    if len(validos) >= 2:
        disperso = validos.sort_values("Dispersión %", ascending=False).iloc[0]
        parejo = validos.sort_values("Dispersión %").iloc[0]
        nombre = dim or "Grupo"
        hallazgos.append(f"**{disperso[nombre]}** es el más disparejo (sus registros varían ±{disperso['Dispersión %']:.0f}% "
                         f"alrededor del promedio) y **{parejo[nombre]}** el más parejo (±{parejo['Dispersión %']:.0f}%).")
    for _, fila in tabla.iterrows():
        if fila["Promedio"] and fila["Mediana"] and fila["Registros"] >= 5:
            sesgo = (fila["Promedio"] - fila["Mediana"]) / abs(fila["Mediana"]) * 100
            if sesgo >= 30:
                hallazgos.append(f"En **{fila[dim or 'Grupo']}** el promedio ({_fmt(fila['Promedio'])}) está "
                                 f"{sesgo:.0f}% sobre la mediana ({_fmt(fila['Mediana'])}): unos pocos registros "
                                 "muy altos inflan el promedio.")
                break
    q1, q3 = datos["_valor"].quantile(0.25), datos["_valor"].quantile(0.75)
    iqr = q3 - q1
    # El límite de abajo no baja del mínimo real: "habitual desde -9.5K" en
    # una métrica que nunca es negativa no significa nada.
    piso = max(q1 - 1.5 * iqr, float(datos["_valor"].min()))
    techo = q3 + 1.5 * iqr
    atipicos = datos[(datos["_valor"] > techo) | (datos["_valor"] < q1 - 1.5 * iqr)] if iqr > 0 else datos.iloc[0:0]
    if len(atipicos):
        hallazgos.append(f"{len(atipicos)} registros quedan fuera del rango habitual ({_fmt(piso)} a "
                         f"{_fmt(techo)}); son los puntos sueltos del gráfico.")
    return {"tabla": tabla, "datos": datos, "grupos": grupos, "hallazgos": hallazgos}
