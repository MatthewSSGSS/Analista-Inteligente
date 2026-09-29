"""Lectura gerencial: por qué se movió el número, con qué palanca y qué atacar.

Los hallazgos de `core/diagnostics.py` dicen QUIÉN va mal. Un gerente de
ventas o un jefe de mercado necesita además otras tres respuestas antes de
mover a su equipo:

1. **Causa**: de dónde salió el cambio del total. No basta con "Barranquilla
   cayó"; hay que ver si la mejor explicación está en la región, en el canal
   o en el asesor, y bajar un nivel más ("en Barranquilla, sobre todo el
   canal Tienda"). Se prueban todas las columnas que sirven para agrupar y se
   queda la que concentra el movimiento en menos nombres: esa es la que
   señala dónde actuar.
2. **Palanca**: si el cambio vino de hacer menos operaciones (volumen:
   cobertura, visitas, disponibilidad) o de que cada operación valiera menos
   (ticket: precio, descuento, mezcla). Las acciones son distintas; confundir
   una con otra hace que el plan no mueva el número.
3. **Qué atacar**: las oportunidades con su cifra —recuperar lo perdido,
   cerrar la brecha de meta, nivelar a los rezagados— ordenadas por lo que
   valen. Lo que vale más va primero, no lo que suena más grave.

Todo sale del archivo, sin supuestos de negocio. Si algo no se puede
afirmar con los datos (métrica que no se suma, un solo mes, filas ya
agregadas donde el conteo no significa operaciones), esa parte se omite en
vez de inventarse.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .diagnostics import (METRICA_CONTEO, PEOR_SI_SUBE, _aditiva, _conc, _etiqueta, _fmt, _lista, _mes,
                          _periodo_parcial, _semantica, dimensiones_candidatas)

# Una dimensión con más valores que esto no sirve para nombrar la causa
# principal: "la caída está en 400 puntos" no orienta a nadie. Sí sirve
# para el segundo nivel, donde ya se está dentro de un solo segmento.
_MAX_VALORES_CAUSA = 60
_MAX_VALORES_DETALLE = 400
# Por debajo de este cambio (en %) el total se considera estable y no se
# busca "causa" de nada: se habla de oportunidades.
_UMBRAL_CAMBIO = 1.0


def _metrica(df: pd.DataFrame, schema: dict, dashboard: dict | None, metrica=None):
    """La misma métrica que el resto del panel: la elegida por el usuario, la
    principal del dashboard o, si no hay números, contar registros."""
    metricas = [c for c in (schema.get("semantic", {}).get("metrics") or schema.get("metrics", [])) if c in df.columns]
    for candidata in (metrica, schema.get("metrica_preferida"), (dashboard or {}).get("primary_metric")):
        if candidata in metricas:
            return candidata
    neutras = [m for m in metricas if not PEOR_SI_SUBE.search(str(m))]
    prioridad = ["revenue", "profit", "quantity", "cost", "price"]
    sem = _semantica(schema)
    elegida = next((m for p in prioridad for m in neutras if sem.get(m) == p), neutras[0] if neutras else None)
    return elegida


def _columna_unidades(df: pd.DataFrame, schema: dict, metrica) -> Optional[str]:
    """Una columna de cantidad (unidades, operaciones) distinta de la métrica.

    Si existe, el volumen se mide con ella y el ticket es valor por unidad
    (precio medio). Si no, se usan los registros como operaciones."""
    sem = _semantica(schema)
    if sem.get(metrica) not in {"revenue", "profit"}:
        return None
    for c in schema.get("metrics", []):
        if c != metrica and c in df.columns and sem.get(c) == "quantity":
            return c
    return None


def _meses(df: pd.DataFrame, columna_fecha: str) -> pd.Series:
    return pd.to_datetime(df[columna_fecha], errors="coerce").dt.to_period("M")


def _elegir_meses(df, columna_fecha, metrica) -> Optional[tuple]:
    """Los dos meses que se comparan: los dos últimos con datos, o los dos
    anteriores si el último está a medias (si no, todo parecería caer)."""
    periodos = _meses(df, columna_fecha)
    con_dato = periodos[pd.to_numeric(df[metrica], errors="coerce").notna()].dropna()
    disponibles = sorted(con_dato.unique())
    if len(disponibles) < 2:
        return None
    parcial = _periodo_parcial(df, columna_fecha)
    if parcial and len(disponibles) >= 3:
        return disponibles[-3], disponibles[-2], True
    return disponibles[-2], disponibles[-1], False


def _suma_por(df, col, metrica, mascara) -> pd.Series:
    x = df.loc[mascara, [col, metrica]].copy()
    x[col] = x[col].astype(str).str.strip()
    x = x[x[col].ne("") & x[col].str.lower().ne("nan")]
    return pd.to_numeric(x[metrica], errors="coerce").groupby(x[col]).sum()


def _movimiento(df, col, metrica, en_a, en_b) -> pd.DataFrame:
    """Valor de cada segmento en los dos meses y su diferencia."""
    a = _suma_por(df, col, metrica, en_a)
    b = _suma_por(df, col, metrica, en_b)
    tabla = pd.DataFrame({"antes": a, "ahora": b}).fillna(0.0)
    tabla["delta"] = tabla["ahora"] - tabla["antes"]
    return tabla


def _mejor_dimension(df, candidatas, metrica, en_a, en_b, delta_total, max_valores) -> Optional[tuple]:
    """La columna que concentra el movimiento en menos nombres.

    Para cada columna se mira qué parte del movimiento en la dirección del
    total explican sus dos mayores segmentos, y se compara contra lo que
    explicarían si todo estuviera repartido parejo (2 de N). La que más se
    despega de ese reparto parejo es la que mejor señala dónde actuar: con 4
    canales, que 2 expliquen el 60% no dice nada; con 30 asesores, sí.
    """
    signo = 1 if delta_total >= 0 else -1
    mejor = None
    for orden, col in enumerate(candidatas):
        if col not in df.columns:
            continue
        distintos = df.loc[en_a | en_b, col].nunique(dropna=True)
        if distintos < 2 or distintos > max_valores:
            continue
        mov = _movimiento(df, col, metrica, en_a, en_b)
        mismo_sentido = mov["delta"][mov["delta"] * signo > 0].abs().sort_values(ascending=False)
        bruto = float(mismo_sentido.sum())
        if bruto <= 0 or len(mov) < 2:
            continue
        cubre = float(mismo_sentido.head(2).sum()) / bruto
        puntaje = cubre - min(2, len(mov)) / len(mov)
        # A igual puntaje gana la columna más accionable (ya vienen en ese orden).
        clave = (round(puntaje, 3), -orden)
        if mejor is None or clave > mejor[0]:
            mejor = (clave, col, mov)
    if mejor is None:
        return None
    return mejor[1], mejor[2]


def _causas(df, schema, metrica, en_a, en_b, delta_total) -> Optional[dict]:
    candidatas = dimensiones_candidatas(df, schema, metrica)
    if not candidatas:
        return None
    elegida = _mejor_dimension(df, candidatas, metrica, en_a, en_b, delta_total, _MAX_VALORES_CAUSA)
    if not elegida:
        return None
    dim, mov = elegida
    signo = 1 if delta_total >= 0 else -1
    principales = mov[mov["delta"] * signo > 0].sort_values("delta", ascending=signo < 0).head(3)
    if principales.empty:
        return None
    nodos = []
    for nombre, fila in principales.iterrows():
        nodo = {
            "nombre": str(nombre), "delta": float(fila["delta"]), "antes": float(fila["antes"]),
            "ahora": float(fila["ahora"]),
            "pct": float(fila["delta"] / fila["antes"] * 100) if fila["antes"] else None,
            "peso": float(fila["delta"] / delta_total * 100) if delta_total else None,
            "detalle": None,
        }
        # Segundo nivel: dentro de este segmento, ¿dónde está el movimiento?
        dentro = df[dim].astype(str).str.strip().eq(str(nombre))
        otras = [c for c in candidatas if c != dim]
        sub = _mejor_dimension(df, otras, metrica, en_a & dentro, en_b & dentro, nodo["delta"], _MAX_VALORES_DETALLE)
        if sub:
            dim2, mov2 = sub
            top2 = mov2[mov2["delta"] * signo > 0].sort_values("delta", ascending=signo < 0).head(2)
            if not top2.empty and nodo["delta"]:
                nodo["detalle"] = {
                    "dimension": str(dim2),
                    "etiqueta": _etiqueta(schema, dim2),
                    "segmentos": [{"nombre": str(n), "delta": float(f["delta"]),
                                   "peso": float(f["delta"] / nodo["delta"] * 100)} for n, f in top2.iterrows()],
                }
        nodos.append(nodo)
    # Lo que se movió en sentido contrario y amortiguó (o frenó) el cambio.
    contrarios = mov[mov["delta"] * signo < 0].sort_values("delta", ascending=signo > 0).head(2)
    compensaron = [{"nombre": str(n), "delta": float(f["delta"])} for n, f in contrarios.iterrows()]
    explicado = sum(n["delta"] for n in nodos) / delta_total * 100 if delta_total else None
    return {"dimension": str(dim), "etiqueta": _etiqueta(schema, dim), "nodos": nodos,
            "compensaron": compensaron, "explicado": explicado, "segmentos": int(len(mov))}


def _palanca(df, schema, metrica, en_a, en_b, total_a, total_b, unidades_col=None) -> Optional[dict]:
    """¿El cambio vino del volumen o del valor por operación?

    total = operaciones × ticket, así que el cambio se separa en
    (Δoperaciones × ticket anterior) + (operaciones actuales × Δticket).
    Sin una columna de unidades se cuentan registros, pero solo si las filas
    son transacciones: cuando el archivo trae una fila fija por asesor y mes,
    el conteo no mide operaciones y la separación no significaría nada.
    """
    if metrica == METRICA_CONTEO:
        return None
    if unidades_col:
        ops_a = float(pd.to_numeric(df.loc[en_a, unidades_col], errors="coerce").sum())
        ops_b = float(pd.to_numeric(df.loc[en_b, unidades_col], errors="coerce").sum())
        unidad, ticket_nombre = str(unidades_col).lower(), "precio medio por unidad"
    else:
        # Contar filas solo mide operaciones si las filas son transacciones.
        # Si cada valor de la columna más detallada aparece una vez por mes
        # (una fila por asesor y mes), el archivo ya viene resumido y el
        # conteo no dice nada del volumen: se calla en vez de inventar.
        excluir = set(schema.get("dates", [])) | set(schema.get("metrics", [])) | {metrica}
        candidatas = list(dict.fromkeys(
            c for c in (list(schema.get("semantic", {}).get("dimensions") or []) + schema.get("categorical", [])
                        + schema.get("text", []) + schema.get("geography", []) + schema.get("ids", []))
            if c in df.columns and c not in excluir))
        if candidatas:
            fina = max(candidatas, key=lambda c: df.loc[en_b, c].nunique(dropna=True))
            if float(en_b.sum()) / max(df.loc[en_b, fina].nunique(dropna=True), 1) < 1.5:
                return None
        ops_a, ops_b = float(en_a.sum()), float(en_b.sum())
        unidad, ticket_nombre = "registros", "valor por registro"
    if ops_a <= 0 or ops_b <= 0:
        return None
    ticket_a, ticket_b = total_a / ops_a, total_b / ops_b
    efecto_volumen = (ops_b - ops_a) * ticket_a
    efecto_ticket = ops_b * (ticket_b - ticket_a)
    delta = total_b - total_a
    if not delta:
        return None
    ops_pct = (ops_b - ops_a) / ops_a * 100
    ticket_pct = (ticket_b - ticket_a) / abs(ticket_a) * 100 if ticket_a else 0.0
    peso_vol = abs(efecto_volumen) / (abs(efecto_volumen) + abs(efecto_ticket) or 1)
    if peso_vol >= 0.65:
        dominante = "volumen"
    elif peso_vol <= 0.35:
        dominante = "ticket"
    else:
        dominante = "ambos"
    return {"unidad": unidad, "ticket_nombre": ticket_nombre, "operaciones_a": ops_a, "operaciones_b": ops_b,
            "ops_pct": ops_pct, "ticket_a": ticket_a, "ticket_b": ticket_b, "ticket_pct": ticket_pct,
            "efecto_volumen": efecto_volumen, "efecto_ticket": efecto_ticket, "dominante": dominante}


def _texto_palanca(p: dict, subio: bool) -> tuple[str, str]:
    """La palanca en una frase y la acción que le corresponde."""
    ops = f"{p['ops_pct']:+.1f}% en {p['unidad']}"
    tic = f"{p['ticket_pct']:+.1f}% en {p['ticket_nombre']}"
    if p["dominante"] == "volumen":
        texto = (f"El movimiento vino del volumen ({ops}); el {p['ticket_nombre']} casi no cambió ({p['ticket_pct']:+.1f}%).")
        accion = ("Es un tema de actividad comercial: cobertura, visitas, prospección y disponibilidad de producto."
                  if not subio else "Sostener la actividad que trajo más volumen y revisar que no se haya comprado con descuento.")
    elif p["dominante"] == "ticket":
        texto = (f"El movimiento vino del {p['ticket_nombre']} ({tic}); el volumen se movió poco ({p['ops_pct']:+.1f}%).")
        accion = ("Es un tema de precio y mezcla: revisar descuentos, promociones y qué productos se están vendiendo."
                  if not subio else "Identificar qué subió el valor por operación (precio, mezcla, venta cruzada) y replicarlo.")
    else:
        texto = f"El movimiento combina volumen ({ops}) y valor por operación ({tic})."
        accion = ("Atacar las dos cosas: la actividad comercial y la política de precio y descuentos."
                  if not subio else "Las dos palancas empujaron: documentar qué cambió en actividad y en precio.")
    return texto, accion


def _oportunidades(df, schema, metrica, dim_causa, en_b, mov_causa, mes_a, mes_b) -> list[dict]:
    """Lo que vale la pena atacar, con su cifra, del mayor valor al menor."""
    from .performance import columna_meta

    salida = []
    total_b = float(pd.to_numeric(df.loc[en_b, metrica], errors="coerce").sum())

    # 1. Recuperar lo que se perdió frente al mes anterior.
    if mov_causa is not None:
        caidas = mov_causa[mov_causa["delta"] < 0].sort_values("delta")
        if not caidas.empty:
            top = caidas.head(3)
            monto = float(-top["delta"].sum())
            salida.append({
                "clave": "recuperar", "titulo": "Recuperar lo perdido",
                "monto": monto,
                "quienes": [{"nombre": str(n), "monto": float(-f["delta"]),
                             "detalle": f"de {_fmt(f['antes'])} a {_fmt(f['ahora'])}"} for n, f in top.iterrows()],
                "texto": (f"{_lista([str(n) for n in top.index])} {_conc(len(top), 'perdió', 'perdieron')} {_fmt(monto)} entre {mes_a} y {mes_b}. "
                          f"Volver a su nivel de {mes_a} devuelve esa cifra."),
                "accion": f"Revisar con cada uno qué cambió en {mes_b} (clientes perdidos, visitas, precio, disponibilidad) y fijar una meta de recuperación.",
                "medir": f"Que {top.index[0]} vuelva a {_fmt(top.iloc[0]['antes'])} el próximo mes.",
                "dimension": dim_causa,
            })

    # 2. Cerrar la brecha de meta del último mes.
    meta = columna_meta(df, schema, metrica) if metrica != METRICA_CONTEO else None
    dim_meta = dim_causa or next(iter(dimensiones_candidatas(df, schema, metrica)), None)
    if meta is not None and dim_meta:
        x = pd.DataFrame({"s": df.loc[en_b, dim_meta].astype(str).str.strip(),
                          "v": pd.to_numeric(df.loc[en_b, metrica], errors="coerce"),
                          "m": pd.to_numeric(df.loc[en_b, meta], errors="coerce")}).dropna()
        if not x.empty:
            g = x.groupby("s")[["v", "m"]].sum()
            g = g[g["m"] > 0]
            g["brecha"] = g["m"] - g["v"]
            debajo = g[g["brecha"] > 0].sort_values("brecha", ascending=False)
            if not debajo.empty:
                monto = float(debajo["brecha"].sum())
                top = debajo.head(3)
                salida.append({
                    "clave": "meta", "titulo": "Cerrar la brecha de meta",
                    "monto": monto,
                    "quienes": [{"nombre": str(n), "monto": float(f["brecha"]),
                                 "detalle": f"{f['v'] / f['m'] * 100:.0f}% de su meta"} for n, f in top.iterrows()],
                    "texto": (f"En {mes_b}, {len(debajo)} de {len(g)} {_conc(len(debajo), 'quedó', 'quedaron')} por debajo de su meta. "
                              f"Faltaron {_fmt(monto)}; {_lista([str(n) for n in top.index])} "
                              f"{_conc(len(top), 'concentra', 'concentran')} "
                              f"{float(top['brecha'].sum()) / monto * 100:.0f}% de ese faltante."),
                    "accion": "Empezar por quienes más faltante acumulan: revisar si la meta era alcanzable y acordar un plan semanal de cierre.",
                    "medir": f"Que {top.index[0]} llegue al 100% de su meta el próximo mes.",
                    "dimension": dim_meta,
                })

    # 3. Nivelar a los rezagados hasta la mediana del grupo (último mes).
    dim_niv = dim_causa or dim_meta
    if dim_niv:
        g = _suma_por(df, dim_niv, metrica, en_b)
        g = g[g > 0]
        if len(g) >= 4:
            mediana = float(g.median())
            debajo = g[g < mediana].sort_values()
            brecha = (mediana - debajo)
            # Llevar a TODOS a la mediana es optimista; se promete la mitad del
            # camino, que es lo que un plan de un mes puede mover.
            monto = float(brecha.sum()) * 0.5
            if monto > total_b * 0.01:
                top = brecha.sort_values(ascending=False).head(3)
                salida.append({
                    "clave": "nivelar", "titulo": "Subir a los rezagados",
                    "monto": monto,
                    "quienes": [{"nombre": str(n), "monto": float(v) * 0.5,
                                 "detalle": f"{_fmt(g[n])} frente a una mediana de {_fmt(mediana)}"} for n, v in top.items()],
                    "texto": (f"{len(debajo)} de {len(g)} {_conc(len(debajo), 'está', 'están')} por debajo de la mediana del grupo ({_fmt(mediana)}) en {mes_b}. "
                              f"Si recorren la mitad de esa distancia, suman {_fmt(monto)} al mes."),
                    "accion": "Emparejar a cada rezagado con alguien que esté por encima de la mediana y copiar una práctica concreta (ruta, argumento, surtido).",
                    "medir": f"Que la mitad de los {len(debajo)} rezagados supere la mediana en dos meses.",
                    "dimension": dim_niv,
                })

    for o in salida:
        o["pct_total"] = o["monto"] / total_b * 100 if total_b else None
    salida.sort(key=lambda o: o["monto"], reverse=True)
    return salida


def analisis_gerencial(df: pd.DataFrame, schema: dict, dashboard: dict | None = None, metrica=None) -> Optional[dict]:
    """La lectura completa: titular, causas, palanca y oportunidades.

    Devuelve None cuando el archivo no da para una lectura de este tipo (sin
    fechas, un solo mes o una métrica que no se suma, como un porcentaje o
    un precio: ahí "la parte del total que explica cada uno" no existe).
    """
    if df is None or df.empty:
        return None
    fechas = [c for c in schema.get("dates", []) if c in df.columns]
    if not fechas:
        return None
    trabajo = df
    metrica = _metrica(df, schema, dashboard, metrica)
    if metrica is None:
        trabajo = df.assign(**{METRICA_CONTEO: 1})
        metrica = METRICA_CONTEO
    elif not _aditiva(schema, metrica):
        return None
    meses = _elegir_meses(trabajo, fechas[0], metrica)
    if not meses:
        return None
    mes_a, mes_b, salto_parcial = meses
    periodos = _meses(trabajo, fechas[0])
    en_a, en_b = periodos.eq(mes_a), periodos.eq(mes_b)
    valores = pd.to_numeric(trabajo[metrica], errors="coerce")
    total_a, total_b = float(valores[en_a].sum()), float(valores[en_b].sum())
    delta = total_b - total_a
    pct = delta / abs(total_a) * 100 if total_a else None
    etiqueta = "Registros" if metrica == METRICA_CONTEO else _etiqueta(schema, metrica)
    nombre_a, nombre_b = _mes(mes_a.to_timestamp()), _mes(mes_b.to_timestamp())
    peor_si_sube = bool(PEOR_SI_SUBE.search(str(metrica)))
    se_movio = pct is not None and abs(pct) >= _UMBRAL_CAMBIO

    causas = _causas(trabajo, schema, metrica, en_a, en_b, delta) if se_movio and delta else None
    palanca = None
    if se_movio:
        palanca = _palanca(trabajo, schema, metrica, en_a, en_b, total_a, total_b,
                           _columna_unidades(trabajo, schema, metrica))
    mov_causa = None
    dim_causa = causas["dimension"] if causas else None
    if dim_causa is None:
        dims = [c for c in dimensiones_candidatas(trabajo, schema, metrica)
                if trabajo[c].nunique(dropna=True) <= _MAX_VALORES_CAUSA]
        dim_causa = dims[0] if dims else None
    if dim_causa:
        mov_causa = _movimiento(trabajo, dim_causa, metrica, en_a, en_b)
    oportunidades = _oportunidades(trabajo, schema, metrica, dim_causa, en_b, mov_causa, nombre_a, nombre_b)

    # ── Titular y lectura en frases de gerente ──
    if pct is None:
        titular = f"{etiqueta}: {_fmt(total_b)} en {nombre_b}."
    elif not se_movio:
        titular = f"{etiqueta} se mantuvo estable en {nombre_b} ({pct:+.1f}% frente a {nombre_a})."
    else:
        verbo = "subió" if delta > 0 else "bajó"
        titular = (f"{etiqueta} {verbo} {abs(pct):.1f}% en {nombre_b} frente a {nombre_a}: "
                   f"{'+' if delta > 0 else '−'}{_fmt(abs(delta))}.")
    frases = []
    if causas and causas["nodos"]:
        n0 = causas["nodos"][0]
        frase = (f"La causa principal está en «{causas['etiqueta']}»: {n0['nombre']} "
                 f"({'+' if n0['delta'] > 0 else '−'}{_fmt(abs(n0['delta']))}"
                 + (f", {n0['peso']:.0f}% del cambio" if n0.get("peso") is not None and abs(n0['peso']) <= 300 else "")
                 + ")")
        if n0.get("detalle") and n0["detalle"]["segmentos"]:
            s0 = n0["detalle"]["segmentos"][0]
            frase += f", sobre todo en {n0['detalle']['etiqueta'].lower()} {s0['nombre']}"
        frases.append(frase + ".")
        if len(causas["nodos"]) > 1:
            otros = causas["nodos"][1:]
            frases.append("Le siguen " + _lista([f"{n['nombre']} ({'+' if n['delta'] > 0 else '−'}{_fmt(abs(n['delta']))})"
                                                  for n in otros]) + ".")
        if causas["compensaron"]:
            c0 = causas["compensaron"][0]
            frases.append(f"En sentido contrario, {c0['nombre']} ({'+' if c0['delta'] > 0 else '−'}{_fmt(abs(c0['delta']))}) "
                          f"{'amortiguó la caída' if delta < 0 else 'frenó la subida'}.")
    accion_palanca = texto_palanca = None
    if palanca:
        texto_palanca, accion_palanca = _texto_palanca(palanca, subio=(delta > 0) != peor_si_sube)
        frases.append(texto_palanca)
    if oportunidades:
        o = oportunidades[0]
        frases.append(f"Lo que más vale atacar: {o['titulo'].lower()} ({_fmt(o['monto'])}"
                      + (f", {o['pct_total']:.0f}% de {nombre_b}" if o.get("pct_total") else "") + ").")
    if salto_parcial:
        frases.append(f"El último mes con datos está incompleto, por eso se compara {nombre_b} contra {nombre_a}.")

    return {
        "metrica": metrica, "etiqueta": etiqueta, "mes_a": nombre_a, "mes_b": nombre_b,
        "total_a": total_a, "total_b": total_b, "delta": delta, "pct": pct, "se_movio": se_movio,
        "empeoro": (delta < 0) != peor_si_sube if se_movio else False,
        "parcial": salto_parcial, "titular": titular, "frases": frases,
        "causas": causas, "palanca": palanca, "accion_palanca": accion_palanca, "texto_palanca": texto_palanca,
        "oportunidades": oportunidades,
        "potencial": float(sum(o["monto"] for o in oportunidades[:1])) if oportunidades else 0.0,
    }


# Qué alerta corresponde a qué oportunidad, para decir cuánto vale atenderla.
_ALERTA_OPORTUNIDAD = {
    "Dónde se concentra la caída": "recuperar", "Caída generalizada": "recuperar",
    "Cumplimiento de meta": "meta", "Rezago frente a la mediana": "nivelar",
}


def alertas_con_gerencia(alertas: list, g: Optional[dict]) -> list:
    """Las alertas con la lectura de un gerente encima.

    - Si el número empeoró, la primera alerta es por qué: dónde nació el
      cambio (con el segundo nivel) y qué palanca lo movió. Es la que un jefe
      de ventas lee primero; antes la primera alerta nombraba casos sueltos
      sin decir si explicaban el total.
    - Cada alerta que corresponde a una oportunidad dice cuánto vale atenderla.
    """
    if not g:
        return alertas
    salida = [dict(a) for a in (alertas or [])]
    oportunidades = {o["clave"]: o for o in g.get("oportunidades") or []}
    for a in salida:
        o = oportunidades.get(_ALERTA_OPORTUNIDAD.get(a.get("title")))
        if o:
            a["impacto"] = o["monto"]
            accion = str(a.get("action") or "").rstrip(".")
            a["action"] = f"{accion}. Vale {_fmt(o['monto'])} al mes." if accion else f"Vale {_fmt(o['monto'])} al mes."
    causas = g.get("causas") or {}
    if g.get("se_movio") and g.get("empeoro") and causas.get("nodos"):
        n0 = causas["nodos"][0]
        evidencia = []
        for n in causas["nodos"]:
            detalle = f"{n['peso']:.0f}% del cambio" if n.get("peso") is not None and 0 < abs(n["peso"]) <= 300 else ""
            if n.get("detalle") and n["detalle"]["segmentos"]:
                s0 = n["detalle"]["segmentos"][0]
                detalle += (" · " if detalle else "") + f"sobre todo {n['detalle']['etiqueta'].lower()} {s0['nombre']}"
            evidencia.append({"nombre": n["nombre"], "valor": ("+" if n["delta"] > 0 else "-") + _fmt(abs(n["delta"])),
                              "detalle": detalle})
        texto = " ".join([g["titular"]] + [f for f in g.get("frases", [])[:1]])
        accion = g.get("accion_palanca") or (g["oportunidades"][0]["accion"] if g.get("oportunidades") else "")
        verbo = "bajó" if g["delta"] < 0 else "subió"
        salida.insert(0, {
            "severity": "Alta", "title": f"Por qué {verbo} {g['etiqueta']}", "text": texto,
            "action": accion, "implication": g.get("texto_palanca") or "", "evidence": evidencia,
            "impacto": abs(g["delta"]),
            "target": {"dimension": causas["dimension"], "metric": g["metrica"],
                       "filter_column": causas["dimension"], "filter_value": n0["nombre"],
                       "view": f"{causas['etiqueta']}: {n0['nombre']}"},
        })
    return salida[:6]
