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

Los gráficos se insertan con el mismo bloque que el resto del informe, así que
el HTML sigue siendo un solo archivo que se abre sin internet.
"""
from __future__ import annotations

import html as _html

import pandas as pd

from core.comercial import estado_salud, matriz_comercial, oportunidades, puntaje_salud
from core.cuadro_comparativo import base_de_comparacion, cuadro_comparativo, opciones_de_comparacion
from core.diagnostics import _fmt
from core.explorador import columna_fecha, periodo_vs_periodo, periodos_disponibles, ultimo_incompleto, resolver_calculo
from core.planes import generar as generar_planes
from ui.comercial import _color_escala, _frase_con_color, filas_peso_y_rumbo
from ui.cuadro_comparativo import figura_evolucion, figura_meta, figura_ranking, tabla_cuadro
from ui.labels import clean_display_text

_COLOR_ESTADO = {"critico": "#e11d48", "atencion": "#f59e0b", "mejora": "#0f8a5f"}
_NOMBRE_ESTADO = {"critico": "Crítico", "atencion": "En observación", "mejora": "Oportunidad"}


def _esc(v) -> str:
    return _html.escape(str(clean_display_text(v)))


def _seccion(sid: str, titulo: str, bajada: str, cuerpo: str) -> str:
    return (f'<section class="section" id="{sid}"><div class="sec-head"><span class="sec-num">•</span>'
            f'<div><h2>{_html.escape(titulo)}</h2><p>{_html.escape(bajada)}</p></div></div>{cuerpo}</section>')


def _lista(frases) -> str:
    """Las frases del motor (traen **negritas**) como lista HTML."""
    filas = []
    for f in frases:
        partes = _html.escape(clean_display_text(f)).split("**")
        filas.append("<li>" + "".join(f"<b>{p}</b>" if i % 2 else p for i, p in enumerate(partes)) + "</li>")
    return f'<ul class="lectura-lista">{"".join(filas)}</ul>' if filas else ""


def _tabla_html(tabla: pd.DataFrame, maximo: int = 30) -> str:
    if tabla is None or tabla.empty:
        return ""
    recorte = tabla.head(maximo)
    encabezado = "".join(f"<th>{_html.escape(str(c))}</th>" for c in recorte.columns)
    # Las columnas que son porcentaje se escriben con su signo: "108" y "108%"
    # se leen distinto, y la tabla de la app sí lo muestra.
    porcentuales = {c for c in recorte.columns
                    if "%" in str(c) or str(c) in {"Cumplimiento", "Participación", "Vs. promedio"}
                    or str(c).startswith("Variación")}
    filas = []
    for _, fila in recorte.iterrows():
        celdas = []
        for columna, v in fila.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and not pd.isna(v):
                celdas.append(f"<td>{v:,.1f}%</td>" if columna in porcentuales else f"<td>{_fmt(v)}</td>")
            else:
                celdas.append(f"<td>{_esc(v)}</td>")
        filas.append(f"<tr>{''.join(celdas)}</tr>")
    extra = (f'<p class="muted">Se muestran {maximo} de {len(tabla)} filas.</p>' if len(tabla) > maximo else "")
    return f'<div class="table-card"><table><thead><tr>{encabezado}</tr></thead><tbody>{"".join(filas)}</tbody></table>{extra}</div>'


# ── 📊 Cómo va cada uno contra su meta ──────────────────────────────────────

def bloque_cuadro_comparativo(df, schema, metrica, chart_block, numerar) -> str:
    """El cuadro comparativo completo: gráfico, tabla, lectura y en qué se basa.

    `metrica` es la principal del análisis (la misma que encabeza el informe).
    Sin ella el cuadro caía en "cantidad de registros" y el informe comparaba
    cuántas filas tiene cada región en vez de sus altas contra su meta.
    """
    dims = opciones_de_comparacion(df, schema)
    if not dims:
        return ""
    cuadro = cuadro_comparativo(df, schema, dims[0], metrica)
    if cuadro is None:
        return ""

    base = "".join(
        f'<div class="base-item"><b>{_html.escape(b["icono"])} {_html.escape(b["titulo"])}</b>'
        f'<span>{_esc(b["texto"])}</span></div>'
        for b in base_de_comparacion(cuadro)
    )
    etiqueta = "Cantidad de registros" if cuadro["conteo"] else str(cuadro["metrica"])
    graficos = [chart_block(f"Cómo va cada uno · {cuadro['dimension']}",
                            ("Cumplimiento de meta, de mayor a menor · la línea marca el 100%"
                             if cuadro["base"] == "meta"
                             else f"{etiqueta} · la línea marca el promedio de los {cuadro['total_grupo']}"),
                            figura_ranking(cuadro), numerar())]
    for titulo, bajada, figura in (
        ("Resultado frente a meta", f"Barra de color = {etiqueta} · barra gris = {cuadro['meta_col']}", figura_meta(cuadro)),
        ("Evolución mes a mes", f"{etiqueta} por mes · discontinua = promedio de los {cuadro['total_grupo']}",
         figura_evolucion(cuadro)),
    ):
        if figura is not None:
            graficos.append(chart_block(titulo, bajada, figura, numerar()))

    cuerpo = (f'<div class="base-grid">{base}</div>'
              + "".join(graficos)
              + _lista(cuadro["lectura"])
              + (f'<p class="muted">{_esc(cuadro["aviso"])}</p>' if cuadro.get("aviso") else "")
              + _tabla_html(tabla_cuadro(cuadro)))
    return _seccion("cuadro-comparativo", f"Cómo va cada {cuadro['dimension']}",
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

    tabla = r["tabla"].head(15)
    figura = None
    try:
        import plotly.graph_objects as go
        from visualization.charts import _base, realzar_barras
        t = tabla.iloc[::-1]
        figura = go.Figure(go.Bar(
            x=t["Diferencia"], y=t[dims[0]].astype(str), orientation="h",
            marker=dict(color=["#22A06B" if v >= 0 else "#E4002B" for v in t["Diferencia"]]),
            text=[("+" if v >= 0 else "") + _fmt(v) for v in t["Diferencia"]],
            textposition="outside", cliponaxis=False,
        ))
        figura = _base(figura, max(320, 30 * len(t) + 120), show_xgrid=True)
        limite = float(t["Diferencia"].abs().max() or 1) * 1.35
        figura.update_xaxes(range=[-limite, limite], tickformat="~s", zeroline=True, zerolinecolor="#94A3B8")
        figura.update_layout(showlegend=False, hovermode="closest", bargap=.28, margin=dict(b=44))
        figura = realzar_barras(figura)
    except Exception:
        figura = None

    cuerpo = ((chart_block(f"Quién sumó y quién restó · {r['etiqueta_a']} → {r['etiqueta_b']}",
                           f"Diferencia de {metrica} por {dims[0]}", figura, numerar()) if figura is not None else "")
              + _lista(r["hallazgos"])
              + _tabla_html(tabla.round(1)))
    return _seccion("cambio-periodos", f"Qué cambió entre {r['etiqueta_a']} y {r['etiqueta_b']}",
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
            f'<div class="canal-card" style="border-left-color:{fila["color_barra"]}">'
            f'<div class="canal-head"><b>{_esc(fila["canal"])}</b><span>{_esc(fila["estado"])}</span></div>'
            f'<div class="canal-barra"><span style="width:{fila["ancho"]:.0f}%;background:{fila["color_barra"]}"></span></div>'
            f'<div class="canal-datos"><span>Participación <b>{fila["participacion"]:.1f}%</b></span>'
            f'<span>Movimiento <b style="color:{fila["color_crecimiento"]}">{crecimiento}</b></span>'
            f'<span>Meta <b style="color:{fila["color_meta"]}">{cumplimiento}</b></span></div>'
            f'<div class="canal-jugada">{_esc(fila["jugada"])}</div></div>'
        )

    jugadas = []
    for j in oportunidades(matriz):
        jugadas.append(
            f'<article class="jugada"><div class="jugada-tipo">{_esc(j["tipo"])}</div>'
            f'<p>{_frase_con_color(j["partes"])}</p>'
            + (f'<p class="muted">Palanca: {_esc(j["palanca"])}</p>' if j.get("palanca") else "")
            + f'<div class="jugada-impacto"><span>IMPACTO</span><b>{_fmt(j["impacto"])}</b></div></article>'
        )

    cuerpo = (f'<p class="narrative">{_esc(matriz["titular"])}</p>'
              f'<div class="canal-grid">{"".join(tarjetas)}</div>'
              + (f'<div class="jugadas-grid">{"".join(jugadas)}</div>' if jugadas else "")
              + f'<p class="muted">Comparación entre {_esc(matriz["periodo_anterior_label"])} y '
                f'{_esc(matriz["periodo_label"])}, sobre {_esc(matriz["metrica"])}.</p>')
    return _seccion("estrategia", f"Estrategia por {_esc(matriz['canal'])}",
                    "Cuánto pesa cada uno, hacia dónde va y qué jugada le corresponde.", cuerpo)


# ── 🎯 Planes de mejora ─────────────────────────────────────────────────────

def bloque_planes(df, schema, dashboard) -> str:
    """Los frentes de trabajo con sus pasos, para que el informe termine en acciones."""
    try:
        plan = generar_planes(df, schema, dashboard or {})
    except Exception:
        return ""
    planes = (plan or {}).get("planes") or []
    if not planes:
        return ""

    tarjetas = []
    for i, p in enumerate(planes[:8], 1):
        estado = p.get("estado", "mejora")
        pasos = "".join(f"<li>{_esc(paso)}</li>" for paso in (p.get("pasos") or [])[:6])
        # Los nombres concretos salen de la evidencia del hallazgo, igual que
        # en la pestaña: un plan sobre "RIOHACHA" se ejecuta; uno sobre "los
        # segmentos afectados", no.
        nombres = "".join(f'<span class="chip">{_esc(e.get("nombre"))}</span>'
                          for e in (p.get("evidencia") or [])[:4] if isinstance(e, dict) and e.get("nombre"))
        indicador = p.get("medir")
        tarjetas.append(
            f'<article class="plan" style="border-left-color:{_COLOR_ESTADO.get(estado, "#64748b")}">'
            f'<div class="plan-head"><span class="plan-num">#{i}</span>'
            f'<span class="plan-estado" style="color:{_COLOR_ESTADO.get(estado, "#64748b")}">'
            f'{_esc(_NOMBRE_ESTADO.get(estado, estado))}</span></div>'
            f'<h3>{_esc(p.get("titulo", "Frente de trabajo"))}</h3>'
            + (f'<p class="muted">{_esc(p.get("situacion"))}</p>' if p.get("situacion") else "")
            + (f'<p class="plan-porque"><b>Por qué importa:</b> {_esc(p.get("por_que"))}</p>' if p.get("por_que") else "")
            + (f'<div class="chips">{nombres}</div>' if nombres else "")
            + (f'<ol class="pasos">{pasos}</ol>' if pasos else "")
            + (f'<div class="plan-meta"><b>Para cerrarlo:</b> {_esc(indicador)}</div>' if indicador else "")
            + '</article>'
        )
    cuerpo = (f'<p class="narrative">{_esc(plan.get("resumen", ""))}</p>'
              f'<div class="planes-grid">{"".join(tarjetas)}</div>'
              '<p class="muted">Los responsables y las fechas se asignan en la pestaña «Planes de mejora» del panel; '
              'aquí van los frentes y sus pasos tal como el análisis los propone.</p>')
    return _seccion("planes", "Planes de mejora", "En qué trabajar, en orden de atención, con pasos concretos.", cuerpo)


# ── Estilos propios de estas secciones ──────────────────────────────────────

CSS = """
.base-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px 20px;margin-bottom:14px}
.base-item b{display:block;font-size:11.5px;color:var(--ink);margin-bottom:2px}
.base-item span{font-size:11.5px;color:var(--muted);line-height:1.5}
.lectura-lista{margin:8px 0 14px 18px;padding:0}
.lectura-lista li{font-size:12.5px;line-height:1.6;color:var(--text);margin-bottom:4px}
.canal-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:12px;margin:10px 0 16px}
.canal-card{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--brand);border-radius:12px;padding:12px 14px}
.canal-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.canal-head b{font-size:13px}
.canal-head span{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--soft)}
.canal-barra{height:6px;border-radius:99px;background:var(--line-soft);margin:9px 0}
.canal-barra span{display:block;height:6px;border-radius:99px}
.canal-datos{display:flex;flex-direction:column;gap:3px;font-size:11.5px;color:var(--muted)}
.canal-datos b{color:var(--ink)}
.canal-jugada{margin-top:8px;font-size:11px;font-weight:700;color:var(--brand-dark)}
.jugadas-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin-bottom:12px}
.jugada{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;position:relative}
.jugada-tipo{font-size:9.5px;font-weight:800;letter-spacing:.11em;text-transform:uppercase;color:var(--brand)}
.jugada p{font-size:12.5px;margin:6px 0 4px;line-height:1.55}
.jugada-impacto{position:absolute;top:12px;right:14px;text-align:right}
.jugada-impacto span{display:block;font-size:8.5px;letter-spacing:.1em;color:var(--soft)}
.jugada-impacto b{font-size:15px;color:var(--brand)}
.planes-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:12px;margin:10px 0 12px}
.plan{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--brand);border-radius:12px;padding:12px 14px}
.plan-head{display:flex;justify-content:space-between;font-size:10px;letter-spacing:.08em;text-transform:uppercase}
.plan-num{color:var(--soft);font-weight:800}
.plan-estado{font-weight:800}
.plan h3{font-size:13.5px;margin:6px 0 8px}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:8px}
.chip{font-size:10.5px;background:var(--line-soft);border-radius:99px;padding:2px 8px;color:var(--text)}
.pasos{margin:0 0 8px 16px;padding:0}
.pasos li{font-size:11.5px;line-height:1.5;color:var(--text);margin-bottom:3px}
.plan-porque{font-size:11.5px;color:var(--text);margin:0 0 8px}
.plan-meta{font-size:11.5px;color:var(--muted);border-top:1px dashed var(--line);padding-top:7px}
@media(max-width:900px){.base-grid{grid-template-columns:1fr}}
"""
