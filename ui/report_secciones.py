"""Las secciones de decisión del informe HTML: lo que antes solo vivía en la app.

El informe exportable traía la lectura ejecutiva, los KPIs, los gráficos
universales y las alertas, pero no lo que el panel usa para DECIDIR: cómo va
cada uno contra su meta, qué cambió entre los dos últimos periodos y quién lo
explica, el semáforo por canal con su jugada, y los frentes de trabajo con sus
pasos. Quien recibía el HTML tenía menos de lo que veía en pantalla.

Cada sección se arma con el MISMO motor de la pestaña equivalente —no hay
cálculo nuevo aquí— y se descarta sola si el archivo no da para ella:

- 📊 Cuadro comparativo  → `core.cuadro_comparativo`  (pestaña Cuadro comparativo)
- ⚖️ Qué cambió          → `core.explorador.periodo_vs_periodo`  (Analítica)
- 📈 Estrategia por canal → `core.comercial`  (Estrategia por canal)
- 🎯 Planes de mejora     → `core.planes`  (Planes de mejora)

Formato: cada sección muestra primero lo que se decide (un gráfico y 3-4
frases) y pliega lo que sirve de soporte —tabla completa, metodología,
gráficos secundarios— en bloques desplegables. Antes todo iba abierto y el
informe se volvía un muro de texto y tablas repetidas.
"""
from __future__ import annotations

import pandas as pd

from core.comercial import matriz_comercial, oportunidades
from core.cuadro_comparativo import base_de_comparacion, cuadro_comparativo, opciones_de_comparacion
from core.diagnostics import _fmt
from core.explorador import columna_fecha, periodo_vs_periodo, periodos_disponibles, ultimo_incompleto, resolver_calculo
from core.planes import generar as generar_planes
from ui.comercial import _frase_con_color, filas_peso_y_rumbo
from ui.labels import clean_display_text
from ui.cuadro_comparativo import figura_evolucion, figura_meta, figura_ranking, tabla_cuadro
from ui.report_base import (desplegable, esc, esc_limpio, estado_plan, negritas, seccion,
                            tablero_seguimiento)

# Cuántas frases de lectura se muestran abiertas; el resto se pliega.
_FRASES_VISIBLES = 3
# Con más de estos elementos, el cuadro muestra los mejores y los más
# rezagados en vez de solo los primeros: un informe para decidir que solo
# enseña a los que cumplen esconde justo a quienes hay que ayudar.
_EXTREMOS = 4
_MAX_PARA_ORDENAR = 400


def clean(texto) -> str:
    return str(clean_display_text(texto))


def _lista(frases, maximo: int = _FRASES_VISIBLES) -> str:
    """Las frases del motor (traen **negritas**) como viñetas; las que pasan
    de `maximo` quedan plegadas."""
    frases = [f for f in (frases or []) if f]
    if not frases:
        return ""
    # Plegar una sola frase no ahorra nada: solo se pliega desde dos.
    if len(frases) <= maximo + 1:
        maximo = len(frases)
    visibles = "".join(f"<li>{negritas(f)}</li>" for f in frases[:maximo])
    html = f'<ul class="bullets">{visibles}</ul>'
    resto = frases[maximo:]
    if resto:
        html += desplegable(f"{len(resto)} lectura(s) más",
                            f'<ul class="bullets">{"".join(f"<li>{negritas(f)}</li>" for f in resto)}</ul>')
    return html


def _tabla_html(tabla: pd.DataFrame, maximo: int = 30) -> str:
    if tabla is None or tabla.empty:
        return ""
    recorte = tabla.head(maximo)
    # Las columnas que son porcentaje se escriben con su signo: "108" y "108%"
    # se leen distinto, y la tabla de la app sí lo muestra.
    porcentuales = {c for c in recorte.columns
                    if "%" in str(c) or str(c) in {"Cumplimiento", "Participación", "Vs. promedio"}
                    or str(c).startswith("Variación")}
    # Los porcentajes van alineados a la izquierda igual que su encabezado.
    numericas = {c for c in recorte.columns
                 if pd.api.types.is_numeric_dtype(recorte[c]) and c not in porcentuales}
    encabezado = "".join(f'<th{" class=num" if c in numericas else ""}>{esc(c)}</th>' for c in recorte.columns)
    filas = []
    for _, fila in recorte.iterrows():
        celdas = []
        for columna, v in fila.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and not pd.isna(v):
                celdas.append(f"<td>{v:,.1f}%</td>" if columna in porcentuales else f"<td class=num>{_fmt(v)}</td>")
            elif v is None or (isinstance(v, float) and pd.isna(v)):
                celdas.append('<td class="muted">—</td>')
            else:
                celdas.append(f"<td>{esc_limpio(v)}</td>")
        filas.append(f"<tr>{''.join(celdas)}</tr>")
    extra = (f'<p class="note">Se muestran {maximo} de {len(tabla)} filas.</p>' if len(tabla) > maximo else "")
    return (f'<div class="table-card"><div class="table-scroll"><table><thead><tr>{encabezado}</tr></thead>'
            f'<tbody>{"".join(filas)}</tbody></table></div>{extra}</div>')


# ── 📊 Cómo va cada uno contra su meta ──────────────────────────────────────

def _cuadro_con_extremos(df, schema, dimension, metrica):
    """El cuadro con los mejores y los más rezagados del grupo completo.

    La referencia (promedio, cumplimiento del grupo, posición "de N") sigue
    siendo el grupo completo: la selección solo decide qué se dibuja.
    """
    base = cuadro_comparativo(df, schema, dimension, metrica)
    if base is None or base["total_grupo"] <= len(base["filas"]) or base["total_grupo"] > _MAX_PARA_ORDENAR:
        return base, False
    valores = df[dimension].dropna().astype(str).str.strip().unique().tolist()
    todos = cuadro_comparativo(df, schema, dimension, metrica, seleccion=valores)
    if todos is None or len(todos["filas"]) <= 2 * _EXTREMOS:
        return (todos or base), False
    nombres = [f["nombre"] for f in todos["filas"]]
    extremos = nombres[:_EXTREMOS] + nombres[-_EXTREMOS:]
    cuadro = cuadro_comparativo(df, schema, dimension, metrica, seleccion=extremos)
    return (cuadro or base), cuadro is not None


def bloque_cuadro_comparativo(df, schema, metrica, chart_block, numerar, fuente=None) -> str:
    """Cómo va cada uno: gráfico de posiciones y lectura; metodología, gráficos
    secundarios y tabla quedan plegados.

    `metrica` es la principal del análisis (la misma que encabeza el informe).
    Sin ella el cuadro caía en "cantidad de registros" y el informe comparaba
    cuántas filas tiene cada región en vez de sus altas contra su meta.
    """
    dims = opciones_de_comparacion(df, schema)
    if not dims:
        return ""
    cuadro, extremos = _cuadro_con_extremos(df, schema, dims[0], metrica)
    if cuadro is None:
        return ""

    dim, total = cuadro["dimension"], cuadro["total_grupo"]
    if extremos:
        quienes = (f"Los {_EXTREMOS} mejores y los {_EXTREMOS} más rezagados de los {total} valores de «{dim}». "
                   f"Las posiciones, el promedio y el cumplimiento del grupo se calculan sobre los {total}.")
    elif len(cuadro["filas"]) == total:
        quienes = f"Los {total} valores de «{dim}» que hay en los datos."
    else:
        quienes = None
    base_items = []
    for i, b in enumerate(base_de_comparacion(cuadro)):
        texto = quienes if (i == 0 and quienes) else b["texto"]
        base_items.append(f'<div class="base-item"><b>{esc(b["icono"])} {esc(b["titulo"])}</b>'
                          f'<span>{esc_limpio(texto)}</span></div>')

    etiqueta = "Cantidad de registros" if cuadro["conteo"] else str(cuadro["metrica"])
    alcance = (f"Mejores y más rezagados de {total}" if extremos else f"{len(cuadro['filas'])} de {total}")
    principal = chart_block(
        f"Posición de cada {dim}",
        (f"Cumplimiento de meta · la línea marca el 100% · {alcance}" if cuadro["base"] == "meta"
         else f"{etiqueta} · la línea marca el promedio de los {total} · {alcance}"),
        figura_ranking(cuadro), numerar())

    secundarios = []
    for titulo, bajada, figura in (
        ("Resultado frente a meta", f"Barra de color = {etiqueta} · barra gris = {cuadro['meta_col']}", figura_meta(cuadro)),
        ("Evolución mes a mes", f"{etiqueta} por mes · discontinua = promedio de los {total}",
         figura_evolucion(cuadro)),
    ):
        if figura is not None:
            secundarios.append(chart_block(titulo, bajada, figura, numerar()))

    aviso = f'<p class="note">{esc_limpio(cuadro["aviso"])}</p>' if cuadro.get("aviso") else ""
    cuerpo = (principal
              # "Los elegidos" es lenguaje de la app (quien usa el panel elige a
              # quiénes comparar); en el informe nadie eligió nada.
              + _lista([str(x).replace("entre los elegidos", "entre los mostrados")
                        .replace("de los elegidos", "de los mostrados") for x in cuadro["lectura"]])
              + desplegable("Tabla y gráficos de apoyo", "".join(secundarios) + _tabla_html(tabla_cuadro(cuadro)),
                            f"{len(cuadro['filas'])} filas")
              + desplegable("Cómo se calculó", f'<div class="base-grid">{"".join(base_items)}</div>{aviso}'))
    # Cómo leerlo, dicho para quien no conoce el archivo: qué es cada barra,
    # contra qué se mide y a quiénes se muestra.
    if cuadro["base"] == "meta":
        leer = (f"Cada barra es el cumplimiento de meta de un valor de «{esc(dim)}»: su {esc(etiqueta.lower())} dividido "
                f"por su meta (columna «{esc(cuadro['meta_col'])}»). 100% es la meta cumplida; verde la cumple, "
                "amarillo está cerca (90–99%) y rojo por debajo.")
    else:
        leer = (f"Cada barra es el {'total' if cuadro['aditiva'] else 'promedio'} de «{esc(etiqueta)}» de un valor de "
                f"«{esc(dim)}». La línea punteada es el promedio de los {total}: por encima rinde más que el grupo, "
                "por debajo, menos.")
    if extremos:
        leer += (f" Se muestran los {_EXTREMOS} mejores y los {_EXTREMOS} más rezagados; la posición de cada uno "
                 f"es sobre los {total}.")
    columnas = f"columna «{esc(etiqueta)}»" + (f" y «{esc(cuadro['meta_col'])}»" if cuadro.get("meta_col") else "")
    return seccion("cuadro-comparativo", f"Cómo va cada {dim}",
                   f"Los {total} valores de «{dim}» medidos con la misma vara: su meta si el archivo la trae, "
                   "o el promedio del grupo si no.", cuerpo,
                   leer=leer, fuente=fuente(f"{columnas} por «{esc(dim)}»") if fuente else "")


# ── ⚖️ Qué cambió entre los dos últimos periodos ────────────────────────────

def bloque_cambio_periodos(df, schema, metrica, chart_block, numerar, fuente=None) -> str:
    """Quién sumó y quién restó entre los dos últimos periodos cerrados."""
    import core.explorador as ex

    if columna_fecha(df, schema) is None:
        return ""
    dims = opciones_de_comparacion(df, schema)
    metrica = metrica or (ex.metricas(df, schema) or [None])[0]
    if not dims or metrica is None:
        return ""
    periodos = periodos_disponibles(df, schema, "Mes")
    if len(periodos) < 2:
        return ""
    calculo = resolver_calculo(df, schema, metrica, "Automático")
    # Si el último mes está a medias, se comparan los dos anteriores: si no,
    # el informe diría que todo se desplomó por un mes sin cerrar.
    incompleto = ultimo_incompleto(df, schema, metrica, calculo, "Mes")
    fin = -2 if incompleto and len(periodos) >= 3 else -1
    r = periodo_vs_periodo(df, schema, dims[0], metrica, periodos[fin - 1], periodos[fin], "Automático", "Mes")
    if r is None:
        return ""

    tabla = r["tabla"]
    # El gráfico muestra a los que más movieron en cada sentido, ordenados de
    # mayor suma a mayor resta: leído de arriba abajo cuenta la historia.
    grafico = tabla.sort_values("Diferencia", ascending=False)
    if len(grafico) > 12:
        grafico = pd.concat([grafico.head(6), grafico.tail(6)])
    figura = None
    try:
        import plotly.graph_objects as go
        from visualization.charts import _base, realzar_barras
        t = grafico.iloc[::-1]
        figura = go.Figure(go.Bar(
            x=t["Diferencia"], y=t[dims[0]].astype(str), orientation="h",
            marker=dict(color=["#22A06B" if v >= 0 else "#E4002B" for v in t["Diferencia"]]),
            text=[("+" if v >= 0 else "") + _fmt(v) for v in t["Diferencia"]],
            textposition="outside", cliponaxis=False,
        ))
        figura = _base(figura, max(300, 28 * len(t) + 110), show_xgrid=True)
        limite = float(t["Diferencia"].abs().max() or 1) * 1.35
        figura.update_xaxes(range=[-limite, limite], tickformat="~s", zeroline=True, zerolinecolor="#94A3B8")
        figura.update_layout(showlegend=False, hovermode="closest", bargap=.28, margin=dict(b=44))
        figura = realzar_barras(figura)
    except Exception:
        figura = None

    subtitulo = f"Diferencia de {metrica} por {dims[0]}"
    if len(tabla) > len(grafico):
        subtitulo += f" · los 6 que más sumaron y los 6 que más restaron, de {len(tabla)}"
    cuerpo = ((chart_block(f"Quién sumó y quién restó · {r['etiqueta_a']} → {r['etiqueta_b']}",
                           subtitulo, figura, numerar()) if figura is not None else "")
              + _lista(r["hallazgos"])
              + desplegable("Ver la tabla completa", _tabla_html(tabla.round(1)), f"{len(tabla)} filas"))
    leer = (f"Cada barra es la diferencia de «{esc(metrica)}» de un valor de «{esc(dims[0])}» entre "
            f"{esc(r['etiqueta_a'])} y {esc(r['etiqueta_b'])}. Verde: sumó al total. Rojo: restó. "
            "Arriba los que más sumaron y abajo los que más restaron.")
    if fin == -2:
        leer += (" El último mes con datos todavía está incompleto, por eso se comparan los dos anteriores: "
                 "así una caída no es solo un mes a medias.")
    return seccion("cambio-periodos", f"Qué cambió entre {r['etiqueta_a']} y {r['etiqueta_b']}",
                   f"El total de {metrica} entre los dos últimos meses cerrados, abierto por quién lo empujó "
                   "y quién lo frenó.", cuerpo,
                   leer=leer,
                   fuente=fuente(f"columna «{esc(metrica)}» por «{esc(dims[0])}», meses {esc(r['etiqueta_a'])} "
                                 f"y {esc(r['etiqueta_b'])}") if fuente else "")


# ── 📈 Estrategia por canal ─────────────────────────────────────────────────

_TONO_JUGADA = {"malo": "neg", "bueno": "pos"}
# Qué significa la cifra grande de cada jugada, dicho en dos palabras.
_QUE_ES_IMPACTO = {"Recuperar": "perdido", "Cerrar brecha": "falta para la meta",
                   "Escalar": "base actual", "Sostener": "base actual"}
# Palancas que no dicen nada: se omiten en vez de ocupar una línea.
_PALANCA_VACIA = ("sin cambio relevante",)


def _cifras(partes, tono: str) -> list[str]:
    return [clean(t) for t, x in partes if x == tono and clean(t)]


def _dato_jugada(j: dict, anterior: str = "") -> str:
    """El dato clave de la jugada en una línea corta, sin la frase completa.

    La frase del motor ("Recuperar lo que Win+ perdió frente a julio de 2026:
    -174, una caída de -17.0%.") repetía el tipo, el canal y la cifra que la
    tarjeta ya muestra en grande; aquí queda solo lo que falta decir.
    """
    partes, tipo = j.get("partes") or [], j.get("tipo")
    malos, buenos = _cifras(partes, "malo"), _cifras(partes, "bueno")
    info = _cifras(partes, "info")
    pct = [c for c in info if c.endswith("%")]
    if tipo == "Recuperar":
        frente = f"frente a {esc(anterior)}" if anterior else "frente al periodo anterior"
        return f'Cayó <b class="neg">{esc(malos[1])}</b> {frente}' if len(malos) > 1 else f"Cayó {frente}"
    if tipo == "Cerrar brecha" and malos:
        return f'Va en <b class="neg">{esc(malos[0])}</b> de su meta'
    if tipo == "Escalar" and buenos:
        return (f'Crece <b class="pos">{esc(buenos[0])}</b>'
                + (f' con solo {esc(pct[0])} del negocio' if pct else ""))
    if tipo == "Sostener" and pct:
        return f"Aporta {esc(pct[0])} del negocio y está estable"
    return _frase_con_color(partes)


def _jugada_html(j: dict, anterior: str = "") -> str:
    tono = _TONO_JUGADA.get(j.get("tono"), "")
    palanca = clean(j.get("palanca") or "")
    if palanca.lower().startswith(_PALANCA_VACIA):
        palanca = ""
    return (
        f'<article class="jugada {tono}">'
        f'<div class="jugada-top"><div><span class="jugada-tipo">{esc_limpio(j["tipo"])}</span>'
        f'<b class="jugada-canal">{esc_limpio(j["canal"])}</b></div>'
        f'<div class="jugada-impacto"><b>{_fmt(j["impacto"])}</b>'
        f'<span>{esc(_QUE_ES_IMPACTO.get(j["tipo"], "impacto"))}</span></div></div>'
        f'<p>{_dato_jugada(j, anterior)}</p>'
        + (f'<p class="palanca">{esc(palanca[:1].upper() + palanca[1:])}</p>' if palanca else "")
        + '</article>'
    )


def bloque_estrategia(df, schema, fuente=None) -> str:
    """El semáforo por canal y las jugadas con su cifra de impacto."""
    try:
        matriz = matriz_comercial(df, schema)
    except Exception:
        matriz = None
    if not matriz or not matriz.get("filas"):
        return ""

    tarjetas = []
    filas_canal = filas_peso_y_rumbo(matriz)["filas"]
    # Sin meta en el archivo, la columna "Meta —" repetida en cada tarjeta no dice nada.
    con_meta = any(f["cumplimiento"] is not None for f in filas_canal)
    for fila in filas_canal:
        cumplimiento = ("—" if fila["cumplimiento"] is None else f"{fila['cumplimiento']:.0f}%")
        crecimiento = ("—" if fila["crecimiento"] is None else f"{fila['crecimiento']:+.1f}%")
        tarjetas.append(
            f'<div class="canal-card" style="border-top-color:{fila["color_barra"]}">'
            f'<div class="canal-head"><b>{esc_limpio(fila["canal"])}</b><span>{esc_limpio(fila["estado"])}</span></div>'
            f'<div class="canal-barra"><span style="width:{fila["ancho"]:.0f}%;background:{fila["color_barra"]}"></span></div>'
            f'<div class="canal-datos"{"" if con_meta else " style=grid-template-columns:repeat(2,1fr)"}>'
            f'<span>Participación<b>{fila["participacion"]:.1f}%</b></span>'
            f'<span>Movimiento<b style="color:{fila["color_crecimiento"]}">{crecimiento}</b></span>'
            + (f'<span>Meta<b style="color:{fila["color_meta"]}">{cumplimiento}</b></span>' if con_meta else "")
            + '</div>'
            f'<div class="canal-jugada">→ {esc_limpio(fila["jugada"])}</div></div>'
        )

    jugadas = [_jugada_html(j, clean(matriz["periodo_anterior_label"])) for j in oportunidades(matriz)]

    cuerpo = (f'<div class="callout">{esc_limpio(matriz["titular"])}</div>'
              f'<div class="canal-grid">{"".join(tarjetas)}</div>'
              + (f'<p class="subhead" style="margin-top:18px">Jugadas, de mayor a menor impacto</p>'
                 f'<p class="note" style="margin:-4px 0 10px">La cifra grande estima cuánto está en juego: '
                 f'lo que se perdió, lo que falta para la meta o la base que ya crece.</p>'
                 f'<div class="jugadas-grid">{"".join(jugadas)}</div>' if jugadas else ""))
    canal, metrica = clean(matriz["canal"]), clean(matriz["metrica"])
    actual, anterior = clean(matriz["periodo_label"]), clean(matriz["periodo_anterior_label"])
    leer = (f"Cada tarjeta es un valor de «{esc(canal)}». <b>Participación</b>: qué parte del total de "
            f"{esc(metrica.lower())} aportó en {esc(actual)}. <b>Movimiento</b>: cuánto cambió frente a {esc(anterior)}."
            + (" <b>Meta</b>: cumplimiento de su meta." if con_meta else "")
            + " La recomendación sale de cruzar peso y rumbo: pesar mucho y estar cayendo es lo más urgente.")
    return seccion("estrategia", f"Estrategia por {canal}",
                   f"Cuánto pesa cada {canal.lower()} en {metrica.lower()}, hacia dónde va y qué conviene hacer con cada uno.",
                   cuerpo, leer=leer,
                   fuente=fuente(f"columna «{esc(metrica)}» por «{esc(canal)}», {esc(actual)} frente a {esc(anterior)}")
                   if fuente else "")


# ── 🎯 Planes de mejora ─────────────────────────────────────────────────────

def calcular_planes(df, schema, dashboard) -> dict:
    """Los planes del análisis, calculados una vez y compartidos por el
    resumen (prioridades y semáforo) y la sección completa."""
    try:
        return generar_planes(df, schema, dashboard or {}) or {}
    except Exception:
        return {}


_FACT_TONO = {"alta": ("Alcanzable", "pos"), "media": ("Exigente", "warn"), "baja": ("Difícil", "neg")}


def _metas_html(p: dict) -> str:
    """Metas del plan por caso, calculadas con la historia de cada uno (core/metas)."""
    casos = p.get("casos") or []
    if not casos:
        return ""
    filas = []
    for c in casos:
        nombre, tono = _FACT_TONO.get(c.get("factibilidad"), ("—", ""))
        ops = f'<br><small>{c["operaciones"]:,} {esc(c["unidad"])}</small>' if c.get("operaciones") else ""
        filas.append(
            f'<tr><td><b>{esc_limpio(c["nombre"])}</b><br><small>{esc_limpio(c.get("lectura_corta") or "")}</small></td>'
            f'<td class="num">{_fmt(c["actual"])}</td><td class="num"><b>{_fmt(c["objetivo"])}</b></td>'
            f'<td class="num" style="color:var(--pos)"><b>+{_fmt(c["brecha"])}</b>{ops}</td>'
            f'<td class="num">{_fmt(c["semanal"])}</td>'
            f'<td><span class="pill {tono}">{nombre}</span><br><small>{esc_limpio(c.get("factibilidad_corta") or "")}</small></td></tr>')
    return ('<p class="plan-lbl">Metas por caso</p><div class="table-scroll"><table class="metas-tab"><thead><tr>'
            '<th>Caso</th><th class="num">Hoy</th><th class="num">Objetivo</th><th class="num">Brecha</th>'
            f'<th class="num">Por semana</th><th>¿Alcanzable?</th></tr></thead><tbody>{"".join(filas)}</tbody></table></div>')


def bloque_planes(df, schema, dashboard, plan: dict | None = None, fuente=None) -> str:
    """Los frentes de trabajo con sus pasos, para que el informe termine en acciones."""
    if plan is None:
        plan = calcular_planes(df, schema, dashboard)
    planes = (plan or {}).get("planes") or []
    if not planes:
        return ""

    tarjetas = []
    for i, p in enumerate(planes[:8], 1):
        nombre, tono = estado_plan(p.get("estado", "mejora"))
        pasos = "".join(f"<li>{esc_limpio(paso)}</li>" for paso in (p.get("pasos") or [])[:3])
        # Los nombres concretos salen de la evidencia del hallazgo, igual que
        # en la pestaña: un plan sobre "RIOHACHA" se ejecuta; uno sobre "los
        # segmentos afectados", no.
        nombres = "".join(f'<span class="chip">{esc_limpio(e.get("nombre"))}</span>'
                          for e in (p.get("evidencia") or [])[:4] if isinstance(e, dict) and e.get("nombre"))
        indicador = p.get("medir")
        tarjetas.append(
            f'<article class="plan {tono}">'
            f'<div class="plan-head"><span class="plan-num">#{i}</span><span class="pill {tono}">{esc(nombre)}</span></div>'
            f'<h3>{esc_limpio(p.get("titulo", "Frente de trabajo"))}</h3>'
            + (f'<p class="plan-valor">💰 {esc(p["impacto_txt"])}</p>' if p.get("impacto_txt") else "")
            + (f'<p class="plan-lbl">Qué muestran los datos</p><p class="situacion">{esc_limpio(p.get("situacion"))}</p>'
               if p.get("situacion") else "")
            + (f'<p class="plan-lbl">A quiénes involucra</p><div class="chips">{nombres}</div>' if nombres else "")
            + (f'<p class="plan-lbl">Qué hacer</p><ol class="pasos">{pasos}</ol>' if pasos else "")
            + _metas_html(p)
            + (f'<p class="plan-lbl">Control semanal</p><p class="plan-ctrl">{esc_limpio(p["control"])}</p>' if p.get("control") else "")
            + (f'<p class="plan-lbl">Cuándo escalar</p><p class="plan-ctrl alarma">{esc_limpio(p["alarma"])}</p>' if p.get("alarma") else "")
            + (f'<div class="plan-meta"><b>Para cerrarlo:</b> {esc_limpio(indicador)}</div>' if indicador else "")
            + '</article>'
        )
    cuerpo = (f'<div class="planes-grid">{"".join(tarjetas)}</div>'
              + desplegable("Tablero de seguimiento para el equipo", tablero_seguimiento(planes[:8]),
                            "responsable y fecha para llenar en la reunión"))
    leer = ("Cada tarjeta es un frente de trabajo que salió del análisis, en orden de urgencia. El color de la "
            "etiqueta dice qué tan urgente es; debajo, el dato que lo originó, a quiénes involucra, los pasos "
            "sugeridos y cómo saber que quedó resuelto.")
    return seccion("planes", "Planes de mejora",
                   f"{clean(plan.get('resumen', ''))}", cuerpo, leer=leer,
                   fuente=(fuente("") + " · Frentes generados a partir de los hallazgos del análisis automático.")
                   if fuente else "")


# ── 🔎 Por qué se movió el número y qué atacar ──────────────────────────────

def bloque_gerencia(g: dict | None, fuente=None) -> str:
    """La lectura de un gerente: dónde nació el cambio, con qué palanca y qué
    vale más la pena atacar. Sale de `core.gerencia` (la misma que la vista
    «Qué atacar» del panel)."""
    if not g or not (g.get("causas") or g.get("palanca") or g.get("oportunidades")):
        return ""
    color = "var(--neg)" if g["delta"] < 0 else "var(--pos)"

    def signo(v):
        return ("+" if v > 0 else "−") + _fmt(abs(v))

    causa = ""
    c = g.get("causas")
    if c and c.get("nodos"):
        mayor = max(abs(n["delta"]) for n in c["nodos"]) or 1
        filas = []
        for n in c["nodos"]:
            peso = f" · {n['peso']:.0f}% del cambio" if n.get("peso") is not None and 0 < abs(n["peso"]) <= 300 else ""
            sub = ""
            if n.get("detalle") and n["detalle"]["segmentos"]:
                partes = " · ".join(f"<b>{esc_limpio(x['nombre'])}</b> {signo(x['delta'])}"
                                    for x in n["detalle"]["segmentos"])
                sub = f'<div class="gx-sub">↳ Por {esc(n["detalle"]["etiqueta"].lower())}: {partes}</div>'
            filas.append(
                f'<div class="gx-row"><div class="gx-top"><b>{esc_limpio(n["nombre"])}</b>'
                f'<span style="color:{color}">{signo(n["delta"])}</span></div>'
                f'<div class="gx-bar"><i style="width:{abs(n["delta"]) / mayor * 100:.0f}%;background:{color}"></i></div>'
                f'<div class="gx-sub">De {_fmt(n["antes"])} a {_fmt(n["ahora"])}{peso}</div>{sub}</div>')
        contra = ""
        if c.get("compensaron"):
            k = c["compensaron"][0]
            efecto = "amortiguó la caída" if g["delta"] < 0 else "frenó la subida"
            contra = f'<p class="note">En sentido contrario, <b>{esc_limpio(k["nombre"])}</b> {signo(k["delta"])} {efecto}.</p>'
        causa = (f'<div class="gx-card"><p class="subhead">Dónde nació el cambio · por {esc(c["etiqueta"].lower())}</p>'
                 f'{"".join(filas)}{contra}</div>')

    palanca = ""
    p = g.get("palanca")
    if p:
        mayor = max(abs(p["efecto_volumen"]), abs(p["efecto_ticket"])) or 1

        def barra(etq, v):
            col = "var(--pos)" if v >= 0 else "var(--neg)"
            return (f'<b>{etq}</b><div class="gx-bar"><i style="width:{abs(v) / mayor * 100:.0f}%;background:{col}"></i></div>'
                    f'<span style="color:{col}">{signo(v)}</span>')
        accion = f'<p class="gx-acc">→ {esc_limpio(g["accion_palanca"])}</p>' if g.get("accion_palanca") else ""
        palanca = (f'<div class="gx-card"><p class="subhead">La palanca · volumen o ticket</p>'
                   f'<div class="gx-lever">{barra("Volumen", p["efecto_volumen"])}{barra("Ticket", p["efecto_ticket"])}</div>'
                   f'<p class="gx-txt">{esc_limpio(g.get("texto_palanca") or "")}</p>{accion}</div>')

    atacar = ""
    if g.get("oportunidades"):
        items = []
        for i, o in enumerate(g["oportunidades"], 1):
            quienes = " · ".join(f"{esc_limpio(q['nombre'])} <b>{_fmt(q['monto'])}</b>" for q in o["quienes"])
            items.append(
                f'<div class="gx-opp"><span class="gx-num">{i}</span><div><b class="gx-opp-t">{esc(o["titulo"])}</b>'
                f'<p>{esc_limpio(o["texto"])}</p><p class="gx-quien">{quienes}</p>'
                f'<p class="gx-acc">→ {esc_limpio(o["accion"])}</p></div>'
                f'<div class="gx-monto"><b>+{_fmt(o["monto"])}</b><small>al mes</small></div></div>')
        atacar = ('<p class="subhead" style="margin-top:18px">Qué atacar primero · en orden de valor</p>'
                  f'<div class="gx-opps">{"".join(items)}</div>'
                  '<p class="note">Las cifras pueden solaparse (un mismo caso puede estar en dos frentes), así que no se '
                  'suman entre sí. «Subir a los rezagados» cuenta solo la mitad del camino hasta la mediana.</p>')

    grid = f'<div class="gx-grid">{causa}{palanca}</div>' if (causa or palanca) else ""
    tono = "neg" if g.get("empeoro") else "pos"
    titular = f'<div class="callout {tono}"><b>{esc(g["titular"])}</b></div>'
    leer = (f"Se compara {esc(g['mes_b'])} con {esc(g['mes_a'])}. «Dónde nació el cambio» prueba todas las columnas y "
            "muestra la que concentra el movimiento en menos nombres y, dentro de cada uno, dónde está. «La palanca» "
            "separa si el cambio vino de hacer menos operaciones (volumen) o de que cada una valiera menos (ticket).")
    columnas = f"columna «{esc(g['etiqueta'])}», {esc(g['mes_a'])} y {esc(g['mes_b'])}"
    return seccion("por-que", "Por qué se movió el número y qué atacar",
                   "La causa, la palanca y las oportunidades con su valor, antes del plan de acción.",
                   titular + grid + atacar, leer=leer, fuente=fuente(columnas) if fuente else "")
