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
_FRASES_VISIBLES = 4
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


def bloque_cuadro_comparativo(df, schema, metrica, chart_block, numerar) -> str:
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
              + _lista(cuadro["lectura"])
              + desplegable("Tabla y gráficos de apoyo", "".join(secundarios) + _tabla_html(tabla_cuadro(cuadro)),
                            f"{len(cuadro['filas'])} filas")
              + desplegable("Cómo se calculó", f'<div class="base-grid">{"".join(base_items)}</div>{aviso}'))
    return seccion("cuadro-comparativo", f"Cómo va cada {dim}",
                   "Todos con la misma vara: su meta si el archivo la trae, o el promedio del grupo.", cuerpo)


# ── ⚖️ Qué cambió entre los dos últimos periodos ────────────────────────────

def bloque_cambio_periodos(df, schema, metrica, chart_block, numerar) -> str:
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
    return seccion("cambio-periodos", f"Qué cambió entre {r['etiqueta_a']} y {r['etiqueta_b']}",
                   "El movimiento del total, abierto por quién lo empujó y quién lo frenó.", cuerpo)


# ── 📈 Estrategia por canal ─────────────────────────────────────────────────

def bloque_estrategia(df, schema) -> str:
    """El semáforo por canal y las jugadas con su cifra de impacto."""
    try:
        matriz = matriz_comercial(df, schema)
    except Exception:
        matriz = None
    if not matriz or not matriz.get("filas"):
        return ""

    tarjetas = []
    for fila in filas_peso_y_rumbo(matriz)["filas"]:
        cumplimiento = ("—" if fila["cumplimiento"] is None else f"{fila['cumplimiento']:.0f}%")
        crecimiento = ("—" if fila["crecimiento"] is None else f"{fila['crecimiento']:+.1f}%")
        tarjetas.append(
            f'<div class="canal-card" style="border-top-color:{fila["color_barra"]}">'
            f'<div class="canal-head"><b>{esc_limpio(fila["canal"])}</b><span>{esc_limpio(fila["estado"])}</span></div>'
            f'<div class="canal-barra"><span style="width:{fila["ancho"]:.0f}%;background:{fila["color_barra"]}"></span></div>'
            f'<div class="canal-datos"><span>Participación<b>{fila["participacion"]:.1f}%</b></span>'
            f'<span>Movimiento<b style="color:{fila["color_crecimiento"]}">{crecimiento}</b></span>'
            f'<span>Meta<b style="color:{fila["color_meta"]}">{cumplimiento}</b></span></div>'
            f'<div class="canal-jugada">→ {esc_limpio(fila["jugada"])}</div></div>'
        )

    jugadas = []
    for j in oportunidades(matriz):
        jugadas.append(
            f'<article class="jugada"><div class="jugada-top"><span class="jugada-tipo">{esc_limpio(j["tipo"])}</span>'
            f'<span class="jugada-impacto"><span>IMPACTO</span><b>{_fmt(j["impacto"])}</b></span></div>'
            f'<p>{_frase_con_color(j["partes"])}</p>'
            + (f'<p class="muted">Palanca: {esc_limpio(j["palanca"])}</p>' if j.get("palanca") else "")
            + '</article>'
        )

    cuerpo = (f'<div class="callout">{esc_limpio(matriz["titular"])}</div>'
              f'<div class="canal-grid">{"".join(tarjetas)}</div>'
              + (f'<div class="jugadas-grid">{"".join(jugadas)}</div>' if jugadas else "")
              + f'<p class="note">Comparación entre {esc_limpio(matriz["periodo_anterior_label"])} y '
                f'{esc_limpio(matriz["periodo_label"])}, sobre {esc_limpio(matriz["metrica"])}.</p>')
    return seccion("estrategia", f"Estrategia por {clean(matriz['canal'])}",
                   "Cuánto pesa cada uno, hacia dónde va y qué jugada le corresponde.", cuerpo)


# ── 🎯 Planes de mejora ─────────────────────────────────────────────────────

def calcular_planes(df, schema, dashboard) -> dict:
    """Los planes del análisis, calculados una vez y compartidos por el
    resumen (prioridades y semáforo) y la sección completa."""
    try:
        return generar_planes(df, schema, dashboard or {}) or {}
    except Exception:
        return {}


def bloque_planes(df, schema, dashboard, plan: dict | None = None) -> str:
    """Los frentes de trabajo con sus pasos, para que el informe termine en acciones."""
    if plan is None:
        plan = calcular_planes(df, schema, dashboard)
    planes = (plan or {}).get("planes") or []
    if not planes:
        return ""

    tarjetas = []
    for i, p in enumerate(planes[:8], 1):
        nombre, tono = estado_plan(p.get("estado", "mejora"))
        pasos = "".join(f"<li>{esc_limpio(paso)}</li>" for paso in (p.get("pasos") or [])[:4])
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
            + (f'<p class="situacion">{esc_limpio(p.get("situacion"))}</p>' if p.get("situacion") else "")
            + (f'<div class="chips">{nombres}</div>' if nombres else "")
            + (f'<ol class="pasos">{pasos}</ol>' if pasos else "")
            + (f'<div class="plan-meta"><b>Para cerrarlo:</b> {esc_limpio(indicador)}</div>' if indicador else "")
            + '</article>'
        )
    cuerpo = (f'<div class="planes-grid">{"".join(tarjetas)}</div>'
              + desplegable("Tablero de seguimiento para el equipo", tablero_seguimiento(planes[:8]),
                            "responsable y fecha para llenar en la reunión"))
    return seccion("planes", "Planes de mejora",
                   f"{clean(plan.get('resumen', ''))}", cuerpo)
