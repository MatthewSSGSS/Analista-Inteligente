"""Metas con números: de "hay que recuperar a Barranquilla" a un plan medible.

Un plan de verdad responde, para cada caso, cinco cosas que se calculan con
su propia historia mensual y no con plantillas:

1. **¿Es real o es ruido?** El último mes contra el promedio y la desviación
   estándar de sus 6 meses anteriores (z). Una caída de −0.5 desviaciones es
   la variación normal de ese caso y no justifica intervenir; una de −2 sí.
2. **¿Es puntual o una tendencia?** La pendiente de una recta ajustada a sus
   últimos meses (mínimos cuadrados) y cuántos meses seguidos lleva cayendo.
   Con eso se proyecta dónde cerraría el próximo mes si nadie hace nada.
3. **¿A cuánto hay que llegar?** Un objetivo con cifra (su promedio de 3
   meses, su meta o la mitad del camino a la mediana), la brecha y cuánto
   es por semana. Si las filas son operaciones, también cuántas operaciones
   más hacen falta al ticket actual.
4. **¿Es alcanzable?** Se compara la brecha con su variación normal y con
   su mejor mes: si ya lo logró antes, la meta es exigente pero realista; si
   supera su récord, exige un cambio de fondo y conviene decirlo antes.
5. **¿Cómo se controla?** Hitos semanales (25%, 50%, 75%, 100% del objetivo)
   y una alarma a mitad de mes para escalar a tiempo.

Todo se calcula solo si hay historia suficiente; si no, se omite esa parte
en vez de inventarla.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .diagnostics import _fmt, _mes

# Semanas promedio de un mes, para pasar un objetivo mensual a uno semanal.
SEMANAS_MES = 4.33
# Meses de historia para el promedio y la desviación; y para la base.
VENTANA_VARIACION = 6
VENTANA_BASE = 3


def historia(df: pd.DataFrame, dim: str, metrica: str, periodos: pd.Series, hasta) -> Optional[pd.DataFrame]:
    """Matriz mes × segmento (suma de la métrica) hasta el mes `hasta` inclusive."""
    x = pd.DataFrame({"p": periodos, "s": df[dim].astype(str).str.strip(),
                      "v": pd.to_numeric(df[metrica], errors="coerce")}).dropna(subset=["p", "v"])
    x = x[(x["p"] <= hasta) & x["s"].ne("") & x["s"].str.lower().ne("nan")]
    if x.empty:
        return None
    tabla = x.pivot_table(index="p", columns="s", values="v", aggfunc="sum").sort_index()
    # Completa los meses que faltan en medio: un mes sin registros en una
    # métrica que se suma es un cero real (no hubo actividad).
    todos = pd.period_range(tabla.index.min(), tabla.index.max(), freq="M")
    return tabla.reindex(todos).fillna(0.0)


def estadistica(serie: pd.Series) -> dict:
    """Lo que dice la historia de un caso sobre su último mes."""
    serie = serie.astype(float)
    actual = float(serie.iloc[-1])
    previos = serie.iloc[:-1]
    ventana = previos.tail(VENTANA_VARIACION)
    salida = {"actual": actual, "meses": int(len(serie)), "promedio": None, "desviacion": None, "z": None,
              "base": float(previos.tail(VENTANA_BASE).mean()) if len(previos) else None,
              "pendiente": None, "racha": 0, "proyeccion": None, "mejor": None, "mejor_mes": None}
    if len(ventana) >= 3:
        prom, desv = float(ventana.mean()), float(ventana.std(ddof=1))
        salida["promedio"], salida["desviacion"] = prom, desv
        if desv > 0:
            salida["z"] = (actual - prom) / desv
    tramo = serie.tail(VENTANA_VARIACION)
    if len(tramo) >= 3:
        pendiente = float(np.polyfit(np.arange(len(tramo)), tramo.values, 1)[0])
        salida["pendiente"] = pendiente
        salida["proyeccion"] = max(actual + pendiente, 0.0)
    racha = 0
    for anterior, siguiente in zip(serie.iloc[-2::-1], serie.iloc[::-1]):
        if siguiente < anterior:
            racha += 1
        else:
            break
    salida["racha"] = racha
    if len(previos):
        salida["mejor"] = float(previos.max())
        salida["mejor_mes"] = _mes(previos.idxmax().to_timestamp()) if hasattr(previos.idxmax(), "to_timestamp") else str(previos.idxmax())
    return salida


def lectura(est: dict) -> str:
    """La historia del caso en una frase, sin tecnicismos de más."""
    partes = []
    z = est.get("z")
    if z is not None:
        if z <= -2:
            partes.append(f"Caída fuera de lo normal: {abs(z):.1f} desviaciones por debajo de su promedio de "
                          f"{VENTANA_VARIACION} meses ({_fmt(est['promedio'])}); no es variación del día a día.")
        elif z <= -1:
            partes.append(f"Caída moderada: {abs(z):.1f} desviaciones por debajo de su promedio de "
                          f"{VENTANA_VARIACION} meses ({_fmt(est['promedio'])}).")
        elif z < 1:
            partes.append(f"Dentro de su variación normal ({z:+.1f} desviaciones): vigilar antes de intervenir.")
        else:
            partes.append(f"Por encima de lo normal: {z:.1f} desviaciones sobre su promedio.")
    racha, pendiente = est.get("racha", 0), est.get("pendiente")
    if racha >= 3 and pendiente is not None and pendiente < 0:
        partes.append(f"No es de un mes: lleva {racha} meses seguidos cayendo (≈{_fmt(abs(pendiente))} menos por mes); "
                      f"sin acción cerraría el próximo mes en {_fmt(est['proyeccion'])}.")
    elif racha == 2 and pendiente is not None and pendiente < 0 and (z is None or z <= -1):
        partes.append(f"Dos meses seguidos a la baja (≈{_fmt(abs(pendiente))} por mes): todavía se corrige rápido.")
    elif racha == 1 and z is not None and z <= -2:
        partes.append("Es una caída puntual: hasta el mes anterior estaba en su nivel normal, así que algo pasó "
                      "este mes (un cliente, un quiebre de inventario, un cambio de ruta o de personal).")
    return " ".join(partes)


def lectura_corta(est: dict) -> str:
    """La misma lectura en una etiqueta, para tablas: tipo de caída y z."""
    z, racha = est.get("z"), est.get("racha", 0)
    partes = []
    if z is not None:
        if z <= -2:
            partes.append(f"🔻 Caída anómala · z {z:.1f}")
        elif z <= -1:
            partes.append(f"🔻 Caída moderada · z {z:.1f}")
        elif z < 1:
            partes.append(f"〰️ Variación normal · z {z:+.1f}")
        else:
            partes.append(f"🔺 Sobre lo normal · z {z:+.1f}")
    tipo = tipo_de_caida(est)
    if tipo == "sostenida":
        partes.append(f"📉 {racha} meses cayendo")
    elif tipo == "puntual":
        partes.append("⚡ puntual (solo este mes)")
    return " · ".join(partes) or "Sin historia suficiente"


def tipo_de_caida(est: dict) -> str:
    """'puntual', 'sostenida', 'normal' o '' — para elegir la acción."""
    z, racha, pendiente = est.get("z"), est.get("racha", 0), est.get("pendiente")
    if racha >= 3 and pendiente is not None and pendiente < 0:
        return "sostenida"
    if z is not None and z > -1:
        return "normal"
    if racha <= 1 and z is not None and z <= -2:
        return "puntual"
    return ""


def factibilidad(est: dict, objetivo: float) -> tuple[str, str]:
    """Qué tan alcanzable es el objetivo para ESTE caso, según su historia."""
    brecha = objetivo - est["actual"]
    if brecha <= 0:
        return "alta", "Ya está en el objetivo: el trabajo es sostenerlo."
    desv, mejor = est.get("desviacion"), est.get("mejor")
    if desv and brecha <= desv:
        return "alta", "La brecha cabe en su variación normal de un mes a otro."
    if mejor is not None and objetivo <= mejor:
        return "media", f"Exigente pero realista: ya lo logró en {est['mejor_mes']} ({_fmt(mejor)})."
    if mejor:
        exceso = (objetivo / mejor - 1) * 100
        if exceso <= 10:
            return "media", (f"Pide superar su mejor mes ({_fmt(mejor)}, {est['mejor_mes']}) en {exceso:.0f}%: "
                             "un esfuerzo extra, no un cambio de fondo.")
        return "baja", (f"Exige superar su mejor mes ({_fmt(mejor)}, {est['mejor_mes']}) en {exceso:.0f}%: "
                        "requiere un cambio de fondo (nuevos clientes, canal o precio), no solo más esfuerzo.")
    return "media", "Sin historia suficiente para juzgar qué tan alcanzable es."


def _factibilidad_corta(est: dict, objetivo: float, nivel: str) -> str:
    mejor = est.get("mejor")
    if objetivo <= est["actual"]:
        return "Ya en el objetivo"
    if nivel == "alta":
        return "Cabe en su variación normal"
    if mejor:
        if objetivo <= mejor:
            return f"Ya lo logró: {_fmt(mejor)} en {est['mejor_mes']}"
        return f"{(objetivo / mejor - 1) * 100:.0f}% sobre su récord ({_fmt(mejor)})"
    return "Sin historia"


def caso(nombre: str, serie: pd.Series, objetivo: float, ticket: Optional[float] = None,
         unidad: str = "operaciones", referencia: str = "") -> dict:
    """Un caso con su meta: de dónde parte, a dónde va y cómo se controla."""
    est = estadistica(serie)
    brecha = max(objetivo - est["actual"], 0.0)
    nivel, porque = factibilidad(est, objetivo)
    operaciones = int(np.ceil(brecha / ticket)) if ticket and ticket > 0 and brecha > 0 else None
    return {
        "nombre": str(nombre), **est, "objetivo": float(objetivo), "brecha": brecha,
        "semanal": brecha / SEMANAS_MES, "referencia": referencia,
        "ticket": ticket, "operaciones": operaciones, "unidad": unidad,
        "factibilidad": nivel, "factibilidad_txt": porque, "lectura": lectura(est), "tipo": tipo_de_caida(est),
        "lectura_corta": lectura_corta(est), "factibilidad_corta": _factibilidad_corta(est, objetivo, nivel),
        "hitos": [objetivo * p for p in (0.25, 0.5, 0.75, 1.0)],
    }


def significancia(serie_total: pd.Series) -> Optional[dict]:
    """¿El cambio del total es real o está dentro de su variación normal?"""
    if serie_total is None or len(serie_total) < 4:
        return None
    est = estadistica(serie_total)
    if est.get("z") is None:
        return None
    z = est["z"]
    if abs(z) >= 2:
        nivel = "fuerte"
        texto = (f"El último mes está {abs(z):.1f} desviaciones {'por debajo' if z < 0 else 'por encima'} del promedio de "
                 f"los {VENTANA_VARIACION} anteriores: el cambio es real, no ruido.")
    elif abs(z) >= 1:
        nivel = "moderado"
        texto = (f"El último mes está {abs(z):.1f} desviaciones {'por debajo' if z < 0 else 'por encima'} de su promedio: "
                 "un cambio a tomar en serio, aunque todavía podría ser en parte variación normal.")
    else:
        nivel = "ruido"
        texto = (f"El último mes está a solo {abs(z):.1f} desviaciones de su promedio: está dentro de la variación "
                 "normal. Conviene vigilar y confirmar el próximo mes antes de mover recursos.")
    return {"z": z, "nivel": nivel, "texto": texto, "promedio": est["promedio"], "desviacion": est["desviacion"],
            "pendiente": est["pendiente"], "proyeccion": est["proyeccion"], "racha": est["racha"]}


def filas_son_operaciones(df: pd.DataFrame, schema: dict, metrica, mascara) -> bool:
    """¿Contar filas mide operaciones? Solo si, en el mes, la columna más
    detallada repite valores (transacciones) y no trae una fila por caso."""
    excluir = set(schema.get("dates", [])) | set(schema.get("metrics", [])) | {metrica}
    candidatas = list(dict.fromkeys(
        c for c in (list(schema.get("semantic", {}).get("dimensions") or []) + schema.get("categorical", [])
                    + schema.get("text", []) + schema.get("geography", []) + schema.get("ids", []))
        if c in df.columns and c not in excluir))
    if not candidatas or not mascara.any():
        return False
    fina = max(candidatas, key=lambda c: df.loc[mascara, c].nunique(dropna=True))
    return float(mascara.sum()) / max(df.loc[mascara, fina].nunique(dropna=True), 1) >= 1.5


def mes_siguiente(periodo) -> str:
    try:
        return _mes((periodo + 1).to_timestamp())
    except Exception:
        return "el próximo mes"
