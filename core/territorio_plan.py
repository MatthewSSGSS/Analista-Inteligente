"""Plan de acción territorial: qué hacer, dónde, quién lo hace y cuánto vale.

El mapa y el semáforo dicen qué pasó. Este módulo lo convierte en decisiones
que un gerente puede repartir el lunes:

1. **Estrategia por zona** (`plan()["zonas"]`). Cada municipio (o
   departamento) cae en una de seis, con reglas que se pueden explicar en
   una reunión:

   - 🚨 **Rescatar**: está cayendo y es de las zonas que hacen el 80% del
     resultado (Pareto). Es lo urgente: una caída aquí mueve el total.
   - 🔴 **Recuperar**: está cayendo, pero pesa menos.
   - 📈 **Desarrollar**: hay presencia, pero vende menos de la mitad de lo
     normal para su población (la penetración típica de la propia red).
   - 🟢 **Replicar**: está creciendo; lo que funcionó se lleva a otras zonas.
   - 🛡️ **Sostener**: estable y sana; se vigila.
   - 🎯 **Abrir**: municipios grandes sin presencia (`plan()["aperturas"]`).

2. **Cuánto vale cada una, al mes**. Recuperar = volver al nivel del mes
   anterior completo (si el mes actual va a medias, el ritmo se estima con
   la variación comparable al mismo día, sin extrapolar días). Desarrollar y
   abrir = la mitad del camino a la penetración típica, la misma regla de
   «nivelar» de `core/planes`: una meta exigente pero creíble.
   Las jugadas se ORDENAN por valor esperado (valor × qué tan alcanzable es,
   `ALCANZABLE`): recuperar es rápido y seguro, abrir es una apuesta.

3. **Las jugadas del mes** (`plan()["jugadas"]`): las acciones ordenadas por
   lo que valen, con pasos concretos, responsable, plazo, meta y la razón
   (`core/territorio.motivos`).

4. **Agentes comerciales** (`plan()["agentes"]`): si el archivo trae una
   columna de asesor, vendedor o agente, el plan de cada uno: dónde ganó y
   dónde perdió, sus clientes que dejaron de comprar, su ruta de visitas, su
   meta sugerida y una estrategia según su perfil. La posición y la mediana
   se calculan sobre TODOS los agentes (regla del dominio).

Solo con métricas que se suman (ventas, unidades, registros): en un
promedio, «cuánto vale recuperar» no tiene sentido. Sin Streamlit.
"""
from __future__ import annotations

import re
from typing import Optional

import numpy as np
import pandas as pd

from . import territorio as T
from .cuadro_comparativo import PERSONA_RE
from .numeric import numeric_valid

# Columnas que nombran al cliente o al punto que compra: con ellas el plan
# dice a QUIÉN visitar, no solo dónde.
CUENTA_RE = re.compile(r"client|punto|tienda|establec|comercio|raz[oó]n social|negocio|droguer|farmacia|"
                       r"cuenta|account|customer|store", re.I)
PARETO = 0.80          # las zonas que juntas hacen el 80% son las que «pesan»
REZAGO = 0.5           # menos de la mitad de la penetración típica = rezagado (como donde_crecer)
POBLACION_MINIMA = 20_000
# Qué tan alcanzable es cada peso, para ORDENAR las jugadas (no cambia el
# valor que se muestra). Recuperar a un cliente que compraba el mes pasado es
# rápido y seguro; abrir un municipio es una apuesta a 90 días. Sin este
# ajuste, «Abrir Medellín» le ganaba a cualquier rescate solo por tamaño.
ALCANZABLE = {"rescatar": 1.0, "recuperar": 0.9, "desarrollar": 0.5, "abrir": 0.25}
# Cuántas de cada tipo entran a la lista de jugadas, para que salga variada.
TOPE_JUGADAS = {"desarrollar": 3, "abrir": 2}
MOVIMIENTO = T.UMBRAL_ESTABLE

ESTRATEGIAS = {
    "rescatar": {"icono": "🚨", "titulo": "Rescatar", "tono": "bajo", "orden": 1, "plazo": "2 semanas",
                 "que": "Zona de las que hacen el 80% del resultado y está cayendo: una caída aquí mueve el total."},
    "recuperar": {"icono": "🔴", "titulo": "Recuperar", "tono": "bajo", "orden": 2, "plazo": "Este mes",
                  "que": "Está cayendo; pesa menos que las grandes, pero suma."},
    "desarrollar": {"icono": "📈", "titulo": "Desarrollar", "tono": "estable", "orden": 3, "plazo": "60 días",
                    "que": "Hay presencia, pero vende menos de la mitad de lo normal para su población."},
    "abrir": {"icono": "🎯", "titulo": "Abrir", "tono": "oport", "orden": 4, "plazo": "90 días",
              "que": "Municipio grande sin presencia en un departamento donde ya operas."},
    "replicar": {"icono": "🟢", "titulo": "Replicar", "tono": "subio", "orden": 5, "plazo": "Este mes",
                 "que": "Está creciendo: lo que funcionó aquí se puede llevar a otras zonas."},
    "sostener": {"icono": "🛡️", "titulo": "Sostener", "tono": "estable", "orden": 6, "plazo": "Seguimiento mensual",
                 "que": "Estable y con una penetración normal: mantener y vigilar el semáforo."},
}

PERFILES = {
    "caida": {"icono": "🚨", "titulo": "En caída", "tono": "bajo"},
    "referente": {"icono": "⭐", "titulo": "Referente", "tono": "subio"},
    "desarrollo": {"icono": "🧭", "titulo": "Por desarrollar", "tono": "estable"},
    "solido": {"icono": "✅", "titulo": "Sólido", "tono": "estable"},
}


# ── Columnas ──────────────────────────────────────────────────────────────

def columna_agente(df: pd.DataFrame, candidatas) -> Optional[str]:
    """La columna del asesor / vendedor / agente, si el archivo la trae."""
    for c in candidatas:
        if c in df.columns and PERSONA_RE.search(str(c)):
            n = df[c].nunique(dropna=True)
            if 2 <= n <= 500:
                return c
    return None


def columna_cuenta(df: pd.DataFrame, candidatas, excluir=()) -> Optional[str]:
    """La columna del cliente o punto de venta, si el archivo la trae."""
    for c in candidatas:
        if c in df.columns and c not in excluir and CUENTA_RE.search(str(c)) and not PERSONA_RE.search(str(c)):
            if not (df[c].dtype == object or pd.api.types.is_string_dtype(df[c])):
                continue
            n = df[c].nunique(dropna=True)
            if 2 <= n <= 50_000:
                return c
    return None


# ── Utilidades ────────────────────────────────────────────────────────────

def _texto(serie: pd.Series) -> pd.Series:
    t = serie.astype(str).str.strip()
    return t.where(serie.notna() & t.ne("") & t.str.lower().ne("nan"))


def _lista(nombres: list) -> str:
    nombres = [f"**{n}**" for n in nombres if n]
    if not nombres:
        return ""
    return nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1]


def _km(lat1, lon1, lat2, lon2):
    """Distancia en km (haversine), vectorizada."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def _datos(ub: pd.DataFrame, metrica: Optional[str], calculo: str, fecha_col: Optional[str], nivel: str) -> pd.DataFrame:
    datos = ub[ub["_t_ok"]].copy()
    datos["_v"] = 1.0 if (metrica is None or calculo == "Conteo") else numeric_valid(datos[metrica]).fillna(0.0)
    if fecha_col and fecha_col in datos.columns:
        f = pd.to_datetime(datos[fecha_col], errors="coerce")
        datos["_mes"], datos["_dia"] = f.dt.strftime("%Y-%m"), f.dt.day
    else:
        datos["_mes"], datos["_dia"] = None, None
    datos["_zona"] = datos["_t_cod_dpto"].astype(str) if nivel == "departamento" else datos["_t_idx"]
    return datos


def _mascaras(datos: pd.DataFrame, z: dict):
    """(antes cortado al mismo día, mes actual, mes anterior completo), como en `zonas`."""
    mes_a, mes_b, corte = z.get("mes_a"), z.get("mes_b"), z.get("corte_dia")
    en_b = datos["_mes"] == mes_b
    en_a_full = datos["_mes"] == mes_a
    en_a = en_a_full & ((datos["_dia"] <= corte) if corte else True)
    return en_a, en_b, en_a_full


def _cambio_por(datos: pd.DataFrame, clave: str, en_a, en_b) -> pd.DataFrame:
    """Antes (cortado) y ahora por `clave`, con su diferencia."""
    x = datos[datos[clave].notna()]
    a = x.loc[en_a.reindex(x.index, fill_value=False)].groupby(clave)["_v"].sum()
    b = x.loc[en_b.reindex(x.index, fill_value=False)].groupby(clave)["_v"].sum()
    t = pd.DataFrame({"antes": a, "ahora": b}).fillna(0.0)
    t["delta"] = t["ahora"] - t["antes"]
    return t


# ── Plan ──────────────────────────────────────────────────────────────────

def plan(ub: pd.DataFrame, metrica: Optional[str], calculo: str, fecha_col: Optional[str], z: dict,
         dims=(), etiquetas: Optional[dict] = None, agente: Optional[str] = None, cuenta: Optional[str] = None,
         max_jugadas: int = 8, max_aperturas: int = 15) -> dict:
    """El plan de acción del territorio. Ver el docstring del módulo.

    `z` = `territorio.zonas(...)` a nivel municipio (o departamento si el
    archivo solo trae departamento). `dims` = columnas donde buscar la razón
    de cada caída; `agente` y `cuenta` = columnas de asesor y de cliente."""
    etiquetas = etiquetas or {}
    tabla = z.get("tabla")
    nivel = z.get("nivel")
    if tabla is None or tabla.empty or not z.get("sumable") or nivel not in ("municipio", "departamento"):
        return {}
    datos = _datos(ub, metrica, calculo, fecha_col, nivel)
    mes_a, mes_b, corte = z.get("mes_a"), z.get("mes_b"), z.get("corte_dia")
    con_mes = bool(fecha_col and mes_a)
    t = tabla.copy()
    t["_clave"] = t["zona"].astype(str) if nivel == "departamento" else pd.to_numeric(t["zona"], errors="coerce").astype(int)

    # 1) Ritmo mensual de cada zona y su nivel de referencia (mes anterior completo).
    if con_mes:
        en_a, en_b, en_a_full = _mascaras(datos, z)
        ref = datos[en_a_full].groupby("_zona")["_v"].sum()
        t["ref_mes"] = t["_clave"].map(ref).fillna(0.0).astype(float)
        tend = pd.to_numeric(t.get("tendencia"), errors="coerce") if "tendencia" in t.columns else pd.Series(np.nan, index=t.index)
        var = pd.to_numeric(t.get("variacion"), errors="coerce") if "variacion" in t.columns else pd.Series(np.nan, index=t.index)
        ahora = pd.to_numeric(t.get("mes_b"), errors="coerce").fillna(0.0) if "mes_b" in t.columns else 0.0
        # Con variación comparable: ref × (1 + var). Zona nueva: lo que lleva el
        # mes (sin extrapolar días). Zona que dejó de vender: 0.
        t["ritmo"] = np.where(var.notna(), t["ref_mes"] * (1 + var), np.where(tend == 1, ahora, np.where(tend == -1, 0.0, t["ref_mes"])))
    else:
        n_meses = max(len(z.get("meses") or []), 1)
        t["ref_mes"] = t["valor"].astype(float) / n_meses
        t["ritmo"] = t["ref_mes"]
        en_a = en_b = en_a_full = None

    # 2) Peso (Pareto) y penetración mensual.
    total = float(t["valor"].clip(lower=0).sum()) or 1.0
    acumulado = t["valor"].clip(lower=0).cumsum() - t["valor"].clip(lower=0)
    t["pesa"] = acumulado / total < PARETO
    tipica = None
    if "poblacion" in t.columns and t["poblacion"].notna().any():
        t["pen_mes"] = np.where(t["poblacion"] > 0, t["ritmo"] / t["poblacion"] * 10_000, np.nan)
        activos = t[(t["ritmo"] > 0) & (t["poblacion"] > 0)]
        if len(activos) >= 5:
            tipica = float(activos["pen_mes"].median())
    else:
        t["pen_mes"] = np.nan

    # 3) Estrategia y valor al mes.
    estado = t["estado"] if "estado" in t.columns else pd.Series(None, index=t.index)
    cae, sube = estado.eq("bajo"), estado.eq("subio")
    rezagado = (pd.Series(False, index=t.index) if tipica is None else
                (t["pen_mes"] < tipica * REZAGO) & (t["poblacion"] >= POBLACION_MINIMA))
    t["estrategia"] = np.select([cae & t["pesa"], cae, rezagado, sube],
                                ["rescatar", "recuperar", "desarrollar", "replicar"], "sostener")
    recuperar = (t["ref_mes"] - t["ritmo"]).clip(lower=0)
    desarrollar = ((tipica or 0) - t["pen_mes"]).clip(lower=0) * t["poblacion"].fillna(0) / 10_000 * 0.5 \
        if tipica is not None else pd.Series(0.0, index=t.index)
    t["valor_mes"] = np.select([t["estrategia"].isin(["rescatar", "recuperar"]), t["estrategia"].eq("desarrollar")],
                               [recuperar, desarrollar.fillna(0)], 0.0)
    t["meta_mes"] = np.where(t["estrategia"].isin(["rescatar", "recuperar"]), t["ref_mes"], t["ritmo"] + t["valor_mes"])

    # 4) Responsable de cada zona: el agente que más perdió en ella si cae; si
    #    no, el que más vende ahí.
    t["responsable"] = ""
    t["agentes_zona"] = [[] for _ in range(len(t))]
    por_agente_zona = None
    if agente and agente in datos.columns:
        datos["_agente"] = _texto(datos[agente])
        vendido = datos[datos["_agente"].notna()].groupby(["_zona", "_agente"])["_v"].sum()
        if con_mes:
            x = datos[datos["_agente"].notna()]
            a = x.loc[en_a.reindex(x.index, fill_value=False)].groupby(["_zona", "_agente"])["_v"].sum()
            b = x.loc[en_b.reindex(x.index, fill_value=False)].groupby(["_zona", "_agente"])["_v"].sum()
            por_agente_zona = pd.DataFrame({"antes": a, "ahora": b}).fillna(0.0)
            por_agente_zona["delta"] = por_agente_zona["ahora"] - por_agente_zona["antes"]
        for i, r in t.iterrows():
            if r["_clave"] not in vendido.index.get_level_values(0):
                continue
            top = vendido.loc[r["_clave"]].sort_values(ascending=False)
            t.at[i, "agentes_zona"] = list(top.index[:3])
            nombre = top.index[0]
            if r["estrategia"] in ("rescatar", "recuperar") and por_agente_zona is not None \
                    and r["_clave"] in por_agente_zona.index.get_level_values(0):
                d = por_agente_zona.loc[r["_clave"], "delta"].sort_values()
                if len(d) and d.iloc[0] < 0:
                    nombre = d.index[0]
            t.at[i, "responsable"] = str(nombre)

    # 5) Cuentas que dejaron de comprar en cada zona que cae.
    t["cuentas"] = [[] for _ in range(len(t))]
    if cuenta and cuenta in datos.columns and con_mes:
        datos["_cuenta"] = _texto(datos[cuenta])
        caen = set(t.loc[t["estrategia"].isin(["rescatar", "recuperar"]), "_clave"])
        x = datos[datos["_cuenta"].notna() & datos["_zona"].isin(caen)]
        if len(x):
            a = x.loc[en_a.reindex(x.index, fill_value=False)].groupby(["_zona", "_cuenta"])["_v"].sum()
            b = x.loc[en_b.reindex(x.index, fill_value=False)].groupby(["_zona", "_cuenta"])["_v"].sum()
            c = pd.DataFrame({"antes": a, "ahora": b}).fillna(0.0)
            c["delta"] = c["ahora"] - c["antes"]
            for i, r in t[t["_clave"].isin(caen)].iterrows():
                if r["_clave"] not in c.index.get_level_values(0):
                    continue
                cz = c.loc[r["_clave"]]
                perdidas = cz[(cz["antes"] > 0) & (cz["ahora"] <= 0)].sort_values("antes", ascending=False)
                bajaron = cz[(cz["delta"] < 0) & (cz["ahora"] > 0)].sort_values("delta")
                t.at[i, "cuentas"] = ([{"nombre": str(n), "antes": float(f["antes"]), "ahora": 0.0, "perdida": True}
                                       for n, f in perdidas.head(5).iterrows()]
                                      + [{"nombre": str(n), "antes": float(f["antes"]), "ahora": float(f["ahora"]),
                                          "perdida": False} for n, f in bajaron.head(max(0, 5 - len(perdidas))).iterrows()])

    # 6) La razón (solo para las zonas que van a las jugadas: cada una es un cálculo).
    t["por_que"] = ""
    candidatas = t[t["valor_mes"] > 0].sort_values("valor_mes", ascending=False).head(max_jugadas + 4)
    candidatas = pd.concat([candidatas, t[t["estrategia"] == "replicar"].sort_values("cambio", ascending=False).head(3)
                            if "cambio" in t.columns else t.iloc[0:0]])
    if con_mes:
        for i, r in candidatas.iterrows():
            m = T.motivos(ub, metrica, calculo, fecha_col, z, list(dims), zona=r["zona"], nivel=nivel,
                          geografia=nivel == "departamento")
            if m:
                t.at[i, "por_que"] = T.frase_motivo(m, etiquetas.get(m["dimension"], m["dimension"]), corta=True)

    # 7) Pasos, KPI y plazo de cada zona.
    t["pasos"] = [_pasos(r, tipica, mes_a, t) for _, r in t.iterrows()]
    t["kpi"] = [_kpi(r) for _, r in t.iterrows()]
    t["plazo"] = t["estrategia"].map(lambda e: ESTRATEGIAS[e]["plazo"])

    aperturas = _aperturas(t, tipica, max_aperturas) if nivel == "municipio" and tipica is not None else pd.DataFrame()
    agentes = _agentes(datos, z, t, aperturas, agente, cuenta, con_mes) if agente else []
    jugadas = _jugadas(t, aperturas, max_jugadas)
    bolsa = {e: {"n": int((t["estrategia"] == e).sum()), "valor": float(t.loc[t["estrategia"] == e, "valor_mes"].sum())}
             for e in ESTRATEGIAS if e != "abrir"}
    bolsa["abrir"] = {"n": int(len(aperturas)), "valor": float(aperturas["potencial_mes"].sum()) if len(aperturas) else 0.0}
    salida = {"zonas": t.drop(columns=["_clave"]), "jugadas": jugadas, "bolsa": bolsa, "aperturas": aperturas,
              "agentes": agentes, "agente_col": agente, "cuenta_col": cuenta, "tipica": tipica, "nivel": nivel,
              "mes_a": mes_a, "mes_b": mes_b, "corte_dia": corte, "con_mes": con_mes}
    salida["resumen"] = _resumen(salida)
    return salida


def _pasos(r, tipica, mes_a, t) -> list[str]:
    e = r["estrategia"]
    cifra = T.cifra
    resp = r.get("responsable") or ""
    por_que = r.get("por_que") or ""
    if e in ("rescatar", "recuperar"):
        pasos = [(f"Revisar la causa con **{resp}** esta semana: {por_que}." if resp and por_que else
                  f"Revisar la causa con **{resp}** esta semana." if resp else
                  f"Causa: {por_que}." if por_que else "Reunión con el equipo de la zona esta semana para entender la caída.")]
        cuentas = r.get("cuentas") or []
        perdidas = [c for c in cuentas if c["perdida"]]
        if perdidas:
            pasos.append(f"Visitar primero a quienes dejaron de comprar: {_lista([c['nombre'] for c in perdidas[:3]])} "
                         f"(compraban {cifra(sum(c['antes'] for c in perdidas[:3]))} y este mes nada).")
        elif cuentas:
            pasos.append(f"Visitar a los que más bajaron: {_lista([c['nombre'] for c in cuentas[:3]])}.")
        else:
            pasos.append(f"Visitar los puntos que más compraban en {T.etiqueta_mes(mes_a) or 'el mes anterior'} para reactivarlos.")
        if e == "rescatar":
            pasos.append("Plan de choque de 2 semanas: el supervisor acompaña la ruta en campo y se revisa cada viernes.")
        pasos.append(f"Meta: volver a **{cifra(r['meta_mes'])} al mes** (hoy va a ritmo de {cifra(r['ritmo'])}).")
        return pasos
    if e == "desarrollar":
        return [f"Tiene **{cifra(r['poblacion'])} habitantes** y vende {cifra(r['pen_mes'])} por cada 10.000 al mes, frente a "
                f"{cifra(tipica)} en un municipio típico de tu red.",
                "Ampliar cobertura: más puntos de venta y más frecuencia de visita en el casco urbano"
                + (f", con **{resp}**." if resp else "."),
                "Activación local: exhibición, promoción de entrada o convenio con un aliado de la zona.",
                f"Meta a 60 días: **{cifra(r['meta_mes'])} al mes** (la mitad del camino a lo típico)."]
    if e == "replicar":
        cercanas = t[(t["departamento"] == r["departamento"]) & t["estrategia"].isin(["rescatar", "recuperar"])]["nombre"].head(3)
        pasos = [f"Creció {r['variacion']:+.0%}" + (f": {por_que}." if por_que else ".") if pd.notna(r.get("variacion")) else
                 ("Empezó a vender este mes" + (f": {por_que}." if por_que else "."))]
        pasos.append(f"Documentar qué hizo {('**' + resp + '**') if resp else 'el equipo'} (precio, exhibición, frecuencia, cliente nuevo) "
                     "y compartirlo en la reunión comercial.")
        if len(cercanas):
            pasos.append(f"Llevar esa práctica a las zonas en rojo del mismo departamento: {_lista(list(cercanas))}.")
        pasos.append("Reconocer al equipo: lo que se reconoce se repite.")
        return pasos
    return ["Mantener la frecuencia de visita y vigilar el semáforo cada mes.",
            f"Proteger a los clientes principales{(' con ' + '**' + resp + '**') if resp else ''}."]


def _kpi(r) -> str:
    e = r["estrategia"]
    if e in ("rescatar", "recuperar"):
        return f"{T.cifra(r['meta_mes'])} al mes (hoy {T.cifra(r['ritmo'])})"
    if e == "desarrollar":
        return f"{T.cifra(r['meta_mes'])} al mes en 60 días"
    if e == "replicar":
        return "Sostener el crecimiento y replicarlo en 1–2 zonas"
    return "Semáforo en verde o amarillo"


def _aperturas(t: pd.DataFrame, tipica: float, maximo: int) -> pd.DataFrame:
    """Municipios grandes sin presencia, con la zona más cercana desde donde atenderlos."""
    m = T.municipios()
    activos = t[t["ritmo"] > 0]
    if activos.empty:
        return pd.DataFrame()
    presentes = set(t["cod_mpio"]) if "cod_mpio" in t.columns else set()
    b = m[m["departamento"].isin(set(activos["departamento"])) & ~m["cod_mpio"].isin(presentes)
          & (m["poblacion"] >= POBLACION_MINIMA)].copy()
    if b.empty:
        return pd.DataFrame()
    b["potencial_mes"] = tipica * b["poblacion"] / 10_000 * 0.5
    b = b.sort_values("potencial_mes", ascending=False).head(maximo)
    d = _km(b["lat"].to_numpy()[:, None], b["lon"].to_numpy()[:, None],
            activos["lat"].to_numpy()[None, :], activos["lon"].to_numpy()[None, :])
    cerca = d.argmin(axis=1)
    b["base"] = activos["nombre"].to_numpy()[cerca]
    b["distancia_km"] = d[np.arange(len(b)), cerca]
    b["agente_sugerido"] = [(activos["agentes_zona"].iloc[j] or [""])[0] for j in cerca]
    b["crecimiento_2030"] = np.where(b["poblacion"] > 0, b["poblacion_2030"] / b["poblacion"] - 1, np.nan)

    def _modelo(km_, base):
        if km_ <= 30:
            return f"Ruta desde {base} ({km_:.0f} km): 1–2 días por semana del equipo de {base}."
        if km_ <= 80:
            return f"Agente o distribuidor local con apoyo desde {base} ({km_:.0f} km)."
        return f"Punto propio o aliado: queda a {km_:.0f} km de {base}, la zona más cercana de tu red."
    b["modelo"] = [_modelo(k, s) for k, s in zip(b["distancia_km"], b["base"])]
    b["pasos"] = [[f"Validar el mercado: **{T.cifra(r.poblacion)} habitantes** ({T.cifra(r.poblacion_cabecera)} en el casco urbano)"
                   + (f", proyección 2030 {r.crecimiento_2030:+.1%}." if np.isfinite(r.crecimiento_2030) else "."),
                   r.modelo,
                   (f"Asignar la prospección a **{r.agente_sugerido}** (es quien más vende en {r.base})." if r.agente_sugerido
                    else f"Asignar la prospección al equipo de {r.base}."),
                   f"Meta a 90 días: **{T.cifra(r.potencial_mes)} al mes** (la mitad de la penetración típica)."]
                  for r in b.itertuples()]
    return b.reset_index(drop=True)


def _jugadas(t: pd.DataFrame, aperturas: pd.DataFrame, maximo: int) -> list[dict]:
    filas = []
    for _, r in t[t["valor_mes"] > 0].iterrows():
        e = ESTRATEGIAS[r["estrategia"]]
        filas.append({"estrategia": r["estrategia"], **e, "zona": str(r["nombre"]), "departamento": str(r.get("departamento", "")),
                      "valor": float(r["valor_mes"]), "meta": float(r["meta_mes"]), "ritmo": float(r["ritmo"]),
                      "responsable": r.get("responsable") or "", "por_que": r.get("por_que") or "",
                      "pasos": r["pasos"], "kpi": r["kpi"], "clave_zona": str(r["zona"])})
    for _, r in aperturas.iterrows() if len(aperturas) else []:
        e = ESTRATEGIAS["abrir"]
        filas.append({"estrategia": "abrir", **e, "zona": str(r["municipio"]), "departamento": str(r["departamento"]),
                      "valor": float(r["potencial_mes"]), "meta": float(r["potencial_mes"]), "ritmo": 0.0,
                      "responsable": r.get("agente_sugerido") or "", "por_que": "",
                      "pasos": r["pasos"], "kpi": f"{T.cifra(r['potencial_mes'])} al mes en 90 días",
                      "clave_zona": str(int(T.municipios().index[T.municipios()["cod_mpio"] == r["cod_mpio"]][0]))})
    for f in filas:
        f["valor_esperado"] = f["valor"] * ALCANZABLE.get(f["estrategia"], 1.0)
    filas.sort(key=lambda f: -f["valor_esperado"])
    jugadas, usadas = [], {}
    for f in filas:
        tope = TOPE_JUGADAS.get(f["estrategia"])
        if tope is not None and usadas.get(f["estrategia"], 0) >= tope:
            continue
        usadas[f["estrategia"]] = usadas.get(f["estrategia"], 0) + 1
        jugadas.append(f)
        if len(jugadas) >= maximo:
            break
    # Una buena práctica al final: lo que se aprende de la zona que más creció.
    rep = t[t["estrategia"] == "replicar"]
    if len(rep) and "cambio" in rep.columns:
        r = rep.sort_values("cambio", ascending=False).iloc[0]
        jugadas.append({"estrategia": "replicar", **ESTRATEGIAS["replicar"], "zona": str(r["nombre"]),
                        "departamento": str(r.get("departamento", "")), "valor": 0.0, "meta": float(r["ritmo"]),
                        "ritmo": float(r["ritmo"]), "responsable": r.get("responsable") or "",
                        "por_que": r.get("por_que") or "", "pasos": r["pasos"], "kpi": r["kpi"], "clave_zona": str(r["zona"]),
                        "ganancia": float(r["cambio"])})
    for n, j in enumerate(jugadas, start=1):
        j["n"] = n
    return jugadas


def _agentes(datos, z, t, aperturas, agente, cuenta, con_mes) -> list[dict]:
    """El plan de cada agente comercial."""
    if agente not in datos.columns:
        return []
    x = datos[_texto(datos[agente]).notna()].copy()
    x["_agente"] = _texto(x[agente])
    if x.empty:
        return []
    nombres_zona = dict(zip(t["_clave"], t["nombre"]))
    estrategia_zona = dict(zip(t["_clave"], t["estrategia"]))
    valor_zona = dict(zip(t["_clave"], t["valor_mes"]))
    duenos_zona = dict(zip(t["_clave"], t["agentes_zona"]))
    meses = sorted(m for m in x["_mes"].dropna().unique())
    completos = [m for m in meses if not (z.get("corte_dia") and m == z.get("mes_b"))]
    mensual = x[x["_mes"].isin(completos)].groupby(["_agente", "_mes"])["_v"].sum().unstack(fill_value=0.0)

    if con_mes:
        en_a, en_b, en_a_full = _mascaras(x, z)
        cam = _cambio_por(x, "_agente", en_a, en_b)
        ref = x[en_a_full].groupby("_agente")["_v"].sum()
        cam["ref"] = ref.reindex(cam.index).fillna(0.0)
        cam["var"] = np.where(cam["antes"] > 0, cam["delta"] / cam["antes"], np.nan)
        cam["ritmo"] = np.where(cam["antes"] > 0, cam["ref"] * (1 + cam["var"]), cam["ahora"])
        zx = _cambio_por(x.assign(_par=list(zip(x["_agente"], x["_zona"]))), "_par", en_a, en_b)
        cuentas = None
        if cuenta and cuenta in x.columns:
            x["_cuenta"] = _texto(x[cuenta])
            cuentas = _cambio_por(x.assign(_par=list(zip(x["_agente"], x["_cuenta"]))), "_par", en_a, en_b)
    else:
        total = x.groupby("_agente")["_v"].sum() / max(len(meses), 1)
        cam = pd.DataFrame({"ritmo": total, "ref": total, "var": np.nan, "delta": 0.0})
        zx, cuentas = None, None

    cam = cam.sort_values("ritmo", ascending=False)
    n = len(cam)
    mediana = float(cam["ritmo"].median()) if n else 0.0
    por_zona = x.groupby(["_agente", "_zona"])["_v"].sum()
    agentes = []
    for pos, (nombre, f) in enumerate(cam.iterrows(), start=1):
        var = f["var"]
        estado = None if pd.isna(var) else "bajo" if var < -MOVIMIENTO else "subio" if var > MOVIMIENTO else "estable"
        if estado == "bajo":
            perfil = "caida"
        elif estado == "subio" and f["ritmo"] >= mediana:
            perfil = "referente"
        elif f["ritmo"] < mediana * 0.7:
            perfil = "desarrollo"
        else:
            perfil = "solido"
        zonas_ag = por_zona.loc[nombre].sort_values(ascending=False) if nombre in por_zona.index.get_level_values(0) else pd.Series(dtype=float)
        principales = [nombres_zona.get(k, str(k)) for k in zonas_ag.index[:3]]
        perdio, gano = [], []
        if zx is not None:
            propias = zx[[isinstance(k, tuple) and k[0] == nombre for k in zx.index]]
            for k, g in propias.sort_values("delta").iterrows():
                if g["delta"] < 0 and len(perdio) < 3:
                    perdio.append({"zona": nombres_zona.get(k[1], str(k[1])), "delta": float(g["delta"]), "clave": k[1]})
            for k, g in propias.sort_values("delta", ascending=False).iterrows():
                if g["delta"] > 0 and len(gano) < 2:
                    gano.append({"zona": nombres_zona.get(k[1], str(k[1])), "delta": float(g["delta"])})
        perdidas = []
        if cuentas is not None:
            propias = cuentas[[isinstance(k, tuple) and k[0] == nombre for k in cuentas.index]]
            for k, g in propias[(propias["antes"] > 0) & (propias["ahora"] <= 0)].sort_values("antes", ascending=False).head(5).iterrows():
                perdidas.append({"nombre": str(k[1]), "antes": float(g["antes"])})
        # Ruta: sus zonas con plan (por valor), solo donde es uno de los dos que
        # más venden (una venta suelta en otra zona no la vuelve suya), y luego
        # las aperturas que le tocan.
        ruta = sorted([k for k in zonas_ag.index if estrategia_zona.get(k) in ("rescatar", "recuperar", "desarrollar")
                       and nombre in (duenos_zona.get(k) or [])[:2]], key=lambda k: -valor_zona.get(k, 0))[:4]
        ruta = [{"zona": nombres_zona.get(k, str(k)), "estrategia": estrategia_zona.get(k), "valor": float(valor_zona.get(k, 0))}
                for k in ruta]
        if len(aperturas) and "agente_sugerido" in aperturas.columns:
            for r in aperturas[aperturas["agente_sugerido"] == nombre].head(2).itertuples():
                ruta.append({"zona": r.municipio, "estrategia": "abrir", "valor": float(r.potencial_mes)})
        historia = mensual.loc[nombre] if nombre in mensual.index else pd.Series(dtype=float)
        ultimos = historia.tail(3)
        meta = max(float(ultimos.mean()) if len(ultimos) else 0.0, float(f["ref"]))
        agentes.append({
            "nombre": str(nombre), "posicion": pos, "de": n, "ritmo": float(f["ritmo"]), "ref": float(f["ref"]),
            "var": None if pd.isna(var) else float(var), "delta": float(f.get("delta", 0.0)), "estado": estado,
            "perfil": perfil, **{f"perfil_{k}": v for k, v in PERFILES[perfil].items()},
            "vs_mediana": (float(f["ritmo"]) / mediana - 1) if mediana else None, "mediana": mediana,
            "zonas": int(len(zonas_ag)), "principales": principales, "perdio": perdio, "gano": gano,
            "cuentas_perdidas": perdidas, "ruta": ruta, "meta": meta,
            "historia": [float(v) for v in historia.tolist()], "meses": list(historia.index),
        })
    referentes = [a["nombre"] for a in agentes if a["perfil"] == "referente"]
    for a in agentes:
        a["estrategia"] = _estrategia_agente(a, referentes)
    return agentes


def _estrategia_agente(a: dict, referentes: list) -> list[str]:
    cifra = T.cifra
    otros = [r for r in referentes if r != a["nombre"]]
    pasos = []
    if a["perfil"] == "caida":
        if a["perdio"]:
            pasos.append("Su caída está en " + ", ".join(f"**{p['zona']}** ({T.cifra_signo(p['delta'])})" for p in a["perdio"])
                         + ": empezar la semana por ahí.")
        if a["cuentas_perdidas"]:
            pasos.append(f"Llamar y visitar a sus clientes que dejaron de comprar: "
                         f"{_lista([c['nombre'] for c in a['cuentas_perdidas'][:3]])}.")
        pasos.append("Revisión semanal 1 a 1 con su supervisor hasta volver a verde.")
        if otros:
            pasos.append(f"Un día de ruta acompañando a **{otros[0]}** (referente del equipo) para ver qué hace distinto.")
    elif a["perfil"] == "referente":
        pasos.append("Pedirle que comparta en la reunión comercial qué está haciendo distinto"
                     + (f" en **{a['gano'][0]['zona']}**." if a["gano"] else "."))
        pasos.append("Darle una zona de expansión: es quien mejor puede abrir mercado.")
        pasos.append("Reconocimiento público e incentivo atado a sostener el ritmo.")
    elif a["perfil"] == "desarrollo":
        pasos.append(f"Vende {abs(a['vs_mediana']):.0%} menos que la mediana de los {a['de']} agentes: plan de acompañamiento de 30 días."
                     if a.get("vs_mediana") is not None else "Plan de acompañamiento de 30 días.")
        if otros:
            pasos.append(f"Ruta en pareja con **{otros[0]}** una vez por semana.")
        pasos.append("Revisar su cartera: cuántos clientes visita, con qué frecuencia y cuánto compra cada uno.")
    else:
        pasos.append("Sostener la frecuencia de visita y proteger a sus clientes principales.")
        if a["ruta"]:
            pasos.append(f"Sumar a su ruta **{a['ruta'][0]['zona']}**, la oportunidad más grande de sus zonas.")
    pasos.append(f"Meta sugerida: **{cifra(a['meta'])} al mes** (su mejor nivel reciente; hoy va a ritmo de {cifra(a['ritmo'])}).")
    return pasos


def _n(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _resumen(p: dict) -> list[str]:
    cifra = T.cifra
    b = p["bolsa"]
    rec = b["rescatar"]["valor"] + b["recuperar"]["valor"]
    n_rec = b["rescatar"]["n"] + b["recuperar"]["n"]
    total = rec + b["desarrollar"]["valor"] + b["abrir"]["valor"]
    frases = []
    if total > 0:
        partes = []
        if rec:
            partes.append(f"**{cifra(rec)}** por recuperar en {_n(n_rec, 'zona que cayó', 'zonas que cayeron')}")
        if b["desarrollar"]["valor"]:
            partes.append(f"**{cifra(b['desarrollar']['valor'])}** por desarrollar en "
                          f"{_n(b['desarrollar']['n'], 'zona', 'zonas')} con baja penetración")
        if b["abrir"]["valor"]:
            partes.append(f"**{cifra(b['abrir']['valor'])}** por abrir en {_n(b['abrir']['n'], 'municipio', 'municipios')} sin presencia")
        frases.append(f"Hay **{cifra(total)} al mes** en juego: " + (", ".join(partes[:-1]) + " y " + partes[-1]
                                                                    if len(partes) > 1 else partes[0]) + ".")
    if b["rescatar"]["n"]:
        n = b["rescatar"]["n"]
        frases.append(f"**{n} {'zona grande' if n == 1 else 'zonas grandes'}** (de las que hacen el 80% del resultado) "
                      f"{'está' if n == 1 else 'están'} cayendo: es lo primero de la semana.")
    if p["jugadas"]:
        j = p["jugadas"][0]
        frases.append(f"La primera jugada: {j['icono']} **{j['titulo']} {j['zona']}**, vale ≈ {cifra(j['valor'])} al mes.")
    ag = p["agentes"]
    if ag:
        caen = [a for a in ag if a["perfil"] == "caida"]
        refs = [a for a in ag if a["perfil"] == "referente"]
        if caen:
            frases.append(f"{len(caen)} de {len(ag)} agentes vienen cayendo ({_lista([a['nombre'] for a in caen[:3]])}); "
                          + (f"{_lista([a['nombre'] for a in refs[:2]])} son los referentes para acompañarlos." if refs else
                             "ninguno está creciendo por encima de la mediana: revisar la estrategia del equipo."))
    if p.get("corte_dia"):
        frases.append(f"El mes actual va hasta el día {p['corte_dia']}: el ritmo de cada zona se estima con la variación "
                      "comparable al mismo día, sin inventar los días que faltan.")
    return frases
