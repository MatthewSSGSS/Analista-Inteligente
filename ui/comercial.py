"""Pestaña "Estrategia por canal": la lectura para dirigir, no para leer.

Pensada para una presentación a gerencia regional, y rehecha para que se
entienda a simple vista. La primera versión tenía tres problemas que se
veían en pantalla con datos reales:

- En la matriz, burbujas verdes dentro de la zona roja: el fondo partía en
  0% y la clasificación en ±1%, así que el color contradecía a la zona.
- El eje iba de -12% a +12% aunque los canales se movieran menos de 1%:
  todos quedaban apilados en una franja y los nombres largos se montaban
  unos sobre otros hasta no leerse ninguno.
- Las barras recortaban por el borde y las cifras no tenían contexto: "-143"
  sin decir de cuánto ni qué porcentaje es.

El orden de la pantalla sigue siendo el orden de la decisión:

1. Titular y KPIs: qué pasa y qué es lo urgente.
2. Semáforo: cada canal en una tarjeta, agrupado por jugada. Es lo que se lee
   sin saber leer una matriz.
3. La matriz, con burbujas numeradas y su leyenda al lado.
4. Quién sumó y quién restó, y qué mueve a cada canal.
5. El detalle y las jugadas con su cifra.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.comercial import CUADRANTES, UMBRAL_MOVIMIENTO, matriz_comercial, oportunidades
from core.diagnostics import _fmt
from ui.components.charts import chart_card
from ui.components.section import section_header
from ui.labels import clean_display_text
from ui.layouts.columns import two_column
from visualization.charts import _base, _label, realzar_barras

# Colores de la paleta del panel, uno por jugada. El rojo corporativo se
# reserva para la urgencia: si se usa en todo, deja de significar nada. Lo
# estable va en gris a propósito: no pide nada, y no debe competir por la
# atención con lo que sí la pide.
COLOR_CUADRANTE = {
    "intervenir": "#E4002B",
    "revisar": "#F59E0B",
    "proteger": "#22A06B",
    "apostar": "#10B9A6",
    "estable": "#64748B",
}
ORDEN_JUGADAS = ("intervenir", "revisar", "proteger", "apostar", "estable")


def _corto(texto, n: int = 28) -> str:
    """Nombre recortado para ejes y burbujas; el completo va en el hover.

    Los nombres de punto de venta reales ("INVERSIONES ARAUJO DOMINGUEZ SAS
    MONTERIA CORDOBA") no caben en un eje sin empujar el gráfico a la mitad
    del ancho, y montados unos sobre otros no se lee ninguno.
    """
    texto = str(texto).strip()
    return texto if len(texto) <= n else texto[: n - 1].rstrip() + "…"


def _flecha(valor, umbral: float = UMBRAL_MOVIMIENTO) -> tuple[str, str]:
    """Flecha y color de una variación, con el mismo umbral del resto."""
    if valor is None:
        return "·", "var(--muted)"
    if valor >= umbral:
        return "▲", "#22A06B"
    if valor <= -umbral:
        return "▼", "#E4002B"
    return "▬", "#64748B"


def _css() -> None:
    st.markdown(
        """
        <style>
        .canal-grupo{margin:4px 0 14px}
        .canal-grupo-head{display:flex;align-items:center;gap:8px;margin:0 0 8px}
        .canal-grupo-chip{font-size:10px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;
          color:#fff;padding:4px 10px;border-radius:999px}
        .canal-grupo-lectura{font-size:12px;color:var(--muted)}
        .canal-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}
        .canal-card{background:var(--panel);border:1px solid var(--line);border-top:4px solid var(--c);
          border-radius:var(--radius-md);padding:12px 14px;box-shadow:var(--shadow-sm);
          transition:transform .15s ease,box-shadow .15s ease}
        .canal-card:hover{transform:translateY(-2px);box-shadow:var(--shadow-md)}
        .canal-card-nombre{font-size:12px;font-weight:700;color:var(--text);line-height:1.3;
          min-height:31px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
        .canal-card-valor{font-size:21px;font-weight:800;font-family:'Sora','Inter',sans-serif;
          color:var(--text);margin-top:6px;line-height:1.1}
        .canal-card-fila{display:flex;justify-content:space-between;align-items:baseline;
          font-size:11.5px;color:var(--muted);margin-top:6px}
        .canal-card-fila b{font-size:13px}
        .canal-barra{height:6px;background:var(--panel-2);border-radius:999px;overflow:hidden;margin-top:8px}
        .canal-barra span{display:block;height:100%;border-radius:999px;background:var(--c)}

        .canal-leyenda{display:flex;flex-direction:column;gap:6px}
        .canal-leyenda-item{display:flex;align-items:center;gap:9px;font-size:12px;color:var(--text);
          padding:6px 9px;border:1px solid var(--line);border-radius:var(--radius-sm);background:var(--panel)}
        .canal-leyenda-num{flex:0 0 22px;height:22px;border-radius:50%;color:#fff;font-size:11px;
          font-weight:800;display:flex;align-items:center;justify-content:center}
        .canal-leyenda-nombre{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
        .canal-leyenda-dato{font-variant-numeric:tabular-nums;color:var(--muted);white-space:nowrap}

        .mueve-lista{display:flex;flex-direction:column;gap:7px}
        .mueve-item{display:grid;grid-template-columns:minmax(0,1.5fr) 1fr 1fr;gap:10px;align-items:center;
          padding:9px 12px;border:1px solid var(--line);border-radius:var(--radius-sm);background:var(--panel)}
        .mueve-nombre{font-size:12px;font-weight:700;color:var(--text);overflow:hidden;
          text-overflow:ellipsis;white-space:nowrap}
        .mueve-veredicto{font-size:11px;color:var(--muted);margin-top:2px;white-space:nowrap;
          overflow:hidden;text-overflow:ellipsis}
        .mueve-dato{font-size:11px;color:var(--muted);line-height:1.25}
        .mueve-dato b{font-size:14px;font-variant-numeric:tabular-nums}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _kpis(matriz: dict, schema: dict) -> None:
    crecimiento = matriz["crecimiento_total"]
    columnas = st.columns(4)
    columnas[0].metric(f"{_label(schema, matriz['metrica'])} · {matriz['periodo_label']}",
                       _fmt(matriz["total"]),
                       delta=(f"{crecimiento:+.1f}%" if crecimiento is not None else None))
    columnas[1].metric("Canales en crecimiento", f"{len(matriz['creciendo'])} de {len(matriz['filas'])}")
    columnas[2].metric("Canales en caída", f"{len(matriz['cayendo'])} de {len(matriz['filas'])}")
    columnas[3].metric("Negocio en riesgo", f"{matriz['peso_en_riesgo']:.0f}%",
                       help="Participación de los canales que pesan y además están cayendo.")


def _semaforo(matriz: dict, schema: dict) -> None:
    """Cada canal en una tarjeta, agrupado por jugada, urgencias primero.

    Es la vista que se entiende sin saber leer una matriz: el color dice qué
    hacer, la cifra dice cuánto pesa y la flecha dice hacia dónde va.
    """
    st.markdown(section_header(
        "Semáforo de canales",
        eyebrow="A SIMPLE VISTA",
        subtitle="Cada canal agrupado por lo que hay que hacer con él. Arriba lo urgente; abajo lo que está estable.",
        compact=True), unsafe_allow_html=True)
    mayor = max((f["participacion"] for f in matriz["filas"]), default=1) or 1
    for clave in ORDEN_JUGADAS:
        grupo = [f for f in matriz["filas"] if f["cuadrante"] == clave]
        if not grupo:
            continue
        color = COLOR_CUADRANTE[clave]
        tarjetas = []
        for f in sorted(grupo, key=lambda z: z["participacion"], reverse=True):
            flecha, color_flecha = _flecha(f["crecimiento"])
            crecimiento = "—" if f["crecimiento"] is None else f"{f['crecimiento']:+.1f}%"
            meta = ("" if f["cumplimiento"] is None else
                    f'<div class="canal-card-fila"><span>Meta</span><b style="color:'
                    f'{"#22A06B" if f["cumplimiento"] >= 100 else "#E4002B"}">{f["cumplimiento"]:.0f}%</b></div>')
            tarjetas.append(
                f'<div class="canal-card" style="--c:{color}" title="{clean_display_text(f["canal"])}">'
                f'<div class="canal-card-nombre">{clean_display_text(f["canal"])}</div>'
                f'<div class="canal-card-valor">{_fmt(f["valor"])}</div>'
                f'<div class="canal-card-fila"><span>Participación</span><b>{f["participacion"]:.1f}%</b></div>'
                f'<div class="canal-card-fila"><span>vs. {matriz["periodo_anterior_label"]}</span>'
                f'<b style="color:{color_flecha}">{flecha} {crecimiento}</b></div>'
                f'{meta}'
                f'<div class="canal-barra"><span style="width:{f["participacion"] / mayor * 100:.0f}%"></span></div>'
                f'</div>'
            )
        st.markdown(
            f'<div class="canal-grupo"><div class="canal-grupo-head">'
            f'<span class="canal-grupo-chip" style="background:{color}">{CUADRANTES[clave]["etiqueta"]} · {len(grupo)}</span>'
            f'<span class="canal-grupo-lectura">{CUADRANTES[clave]["accion"]}</span></div>'
            f'<div class="canal-grid">{"".join(tarjetas)}</div></div>',
            unsafe_allow_html=True,
        )


def _matriz_figura(matriz: dict, schema: dict):
    """Peso × crecimiento, con burbujas numeradas en vez de nombres.

    El eje se ajusta a lo que de verdad se movieron los canales, y la franja
    central de ±1% se pinta en gris como "estable": así la zona y el color de
    la burbuja siempre dicen lo mismo.
    """
    filas = [f for f in matriz["filas"] if f["crecimiento"] is not None]
    if not filas:
        return None
    orden = sorted(filas, key=lambda f: f["participacion"], reverse=True)
    numero = {f["canal"]: i + 1 for i, f in enumerate(orden)}

    maximo = max(abs(f["crecimiento"]) for f in filas)
    limite = max(maximo * 1.3, UMBRAL_MOVIMIENTO * 3)
    techo = max(f["participacion"] for f in filas) * 1.25
    corte = matriz["corte_peso"]
    u = UMBRAL_MOVIMIENTO

    fig = go.Figure()
    zonas = (
        (-limite, -u, corte, techo, "intervenir"),
        (u, limite, corte, techo, "proteger"),
        (u, limite, 0, corte, "apostar"),
        (-limite, -u, 0, corte, "revisar"),
        (-u, u, 0, techo, "estable"),
    )
    for x0, x1, y0, y1, clave in zonas:
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, layer="below",
                      fillcolor=COLOR_CUADRANTE[clave], opacity=0.07 if clave != "estable" else 0.10,
                      line=dict(width=0))
        fig.add_annotation(x=(x0 + x1) / 2, y=y1, text=f"<b>{CUADRANTES[clave]['etiqueta'].upper()}</b>",
                           showarrow=False, yanchor="top", yshift=-4,
                           font=dict(size=11, color=COLOR_CUADRANTE[clave], family="Inter"))

    mayor = max(f["valor"] for f in filas) or 1
    for clave in ORDEN_JUGADAS:
        grupo = [f for f in filas if f["cuadrante"] == clave]
        if not grupo:
            continue
        fig.add_trace(go.Scatter(
            x=[f["crecimiento"] for f in grupo],
            y=[f["participacion"] for f in grupo],
            mode="markers+text",
            name=CUADRANTES[clave]["etiqueta"],
            text=[str(numero[f["canal"]]) for f in grupo],
            textposition="middle center",
            textfont=dict(size=12, color="#FFFFFF", family="Inter"),
            marker=dict(size=[26 + (f["valor"] / mayor) * 30 for f in grupo],
                        color=COLOR_CUADRANTE[clave], opacity=0.92,
                        line=dict(color="#FFFFFF", width=2.5)),
            customdata=[[f["canal"], _fmt(f["valor"]), f["participacion"], f["crecimiento"],
                         CUADRANTES[clave]["etiqueta"]] for f in grupo],
            hovertemplate=("<b>%{customdata[0]}</b><br>"
                           + _label(schema, matriz["metrica"]) + ": <b>%{customdata[1]}</b><br>"
                           "Participación: <b>%{customdata[2]:.1f}%</b><br>"
                           "Crecimiento: <b>%{customdata[3]:+.1f}%</b><br>"
                           "Jugada: <b>%{customdata[4]}</b><extra></extra>"),
        ))

    fig.add_hline(y=corte, line_width=1.3, line_dash="dot", line_color="#94A3B8",
                  annotation_text=f"participación media {corte:.1f}%",
                  annotation_position="bottom right", annotation_font=dict(size=10, color="#64748B"))
    fig.update_xaxes(title="← cae      Crecimiento vs. periodo anterior      crece →",
                     ticksuffix="%", range=[-limite, limite], zeroline=False)
    fig.update_yaxes(title="Participación en el total", ticksuffix="%", range=[0, techo])
    fig.update_layout(showlegend=False, margin=dict(l=10, r=16, t=16, b=44), hovermode="closest")
    return _base(fig, 440, show_xgrid=True), orden, numero


def _leyenda(orden: list, matriz: dict) -> None:
    items = []
    for i, f in enumerate(orden, 1):
        flecha, color_flecha = _flecha(f["crecimiento"])
        crecimiento = "—" if f["crecimiento"] is None else f"{f['crecimiento']:+.1f}%"
        items.append(
            f'<div class="canal-leyenda-item" title="{clean_display_text(f["canal"])}">'
            f'<span class="canal-leyenda-num" style="background:{COLOR_CUADRANTE[f["cuadrante"]]}">{i}</span>'
            f'<span class="canal-leyenda-nombre">{clean_display_text(f["canal"])}</span>'
            f'<span class="canal-leyenda-dato">{f["participacion"]:.1f}%</span>'
            f'<span class="canal-leyenda-dato" style="color:{color_flecha}">{flecha} {crecimiento}</span></div>'
        )
    st.markdown(f'<div class="canal-leyenda">{"".join(items)}</div>', unsafe_allow_html=True)


def _aporte_figura(matriz: dict, schema: dict):
    """Quién sumó y quién restó al total, con su cifra y su porcentaje.

    El rango del eje incluye el cero con aire a los dos lados: antes, si todos
    caían, el eje terminaba justo en cero y las barras se veían recortadas
    por el borde derecho.
    """
    filas = sorted(matriz["filas"], key=lambda f: f["delta"], reverse=True)
    nombres = [_corto(f["canal"]) for f in filas]
    valores = [f["delta"] for f in filas]
    colores = ["#22A06B" if v >= 0 else "#E4002B" for v in valores]
    textos = []
    for f in filas:
        pct = f"{f['crecimiento']:+.1f}%" if f["crecimiento"] is not None else "nuevo"
        textos.append(f"<b>{_fmt(f['delta'])}</b>  ({pct})")

    maxabs = max((abs(v) for v in valores), default=1) or 1
    izquierda = min(min(valores), 0) - maxabs * 0.55
    derecha = max(max(valores), 0) + maxabs * 0.55

    fig = go.Figure(go.Bar(
        y=nombres, x=valores, orientation="h",
        marker=dict(color=colores, line=dict(width=0)),
        text=textos, textposition="outside", cliponaxis=False, textfont=dict(size=11),
        customdata=[[f["canal"], _fmt(f["anterior"]), _fmt(f["valor"])] for f in filas],
        hovertemplate=("<b>%{customdata[0]}</b><br>Antes: %{customdata[1]} · Ahora: %{customdata[2]}"
                       "<br>Cambio: <b>%{x:,.0f}</b><extra></extra>"),
    ))
    fig.add_vline(x=0, line_width=1.4, line_color="#94A3B8")
    total_delta = matriz["total"] - matriz["total_anterior"]
    fig.update_layout(showlegend=False, bargap=0.34, margin=dict(l=10, r=24, t=34, b=24),
                      hovermode="closest")
    fig.add_annotation(
        xref="paper", yref="paper", x=0, y=1.07, showarrow=False, xanchor="left",
        text=(f"<b>Total: {_fmt(matriz['total_anterior'])} → {_fmt(matriz['total'])}</b>  "
              f"({_fmt(total_delta)}"
              + (f", {matriz['crecimiento_total']:+.1f}%" if matriz["crecimiento_total"] is not None else "")
              + ")"),
        font=dict(size=12, color="#1A2233"))
    fig.update_xaxes(range=[izquierda, derecha], showticklabels=False, title=None)
    fig.update_yaxes(title=None, autorange="reversed")
    return realzar_barras(_base(fig, max(260, 40 * len(filas) + 90), show_xgrid=False))


def _que_mueve(matriz: dict) -> None:
    """Por qué se movió cada canal: más o menos operaciones, o más o menos valor.

    Antes era un gráfico de barras agrupadas con dos series. Con variaciones
    pequeñas una de las series ni se veía, y aunque se viera, pedirle a
    alguien de ventas que compare dos barras por canal es pedirle que haga el
    análisis. Aquí se lee la conclusión directamente.
    """
    filas = [f for f in matriz["filas"]
             if f.get("volumen_pct") is not None and f.get("ticket_pct") is not None]
    if not filas:
        st.caption("No hay operaciones suficientes en los dos periodos para separar volumen de valor.")
        return
    items = []
    for f in sorted(filas, key=lambda z: z["participacion"], reverse=True):
        fv, cv = _flecha(f["volumen_pct"], umbral=5)
        ft, ct = _flecha(f["ticket_pct"], umbral=5)
        veredicto = (f.get("mezcla") or "sin cambio relevante").capitalize()
        items.append(
            f'<div class="mueve-item" title="{clean_display_text(f["canal"])}">'
            f'<div><div class="mueve-nombre">{clean_display_text(f["canal"])}</div>'
            f'<div class="mueve-veredicto">{clean_display_text(veredicto)}</div></div>'
            f'<div class="mueve-dato">Operaciones<br><b style="color:{cv}">{fv} {f["volumen_pct"]:+.0f}%</b></div>'
            f'<div class="mueve-dato">Valor por operación<br><b style="color:{ct}">{ft} {f["ticket_pct"]:+.0f}%</b></div>'
            f'</div>'
        )
    st.markdown(f'<div class="mueve-lista">{"".join(items)}</div>', unsafe_allow_html=True)
    st.caption("Una variación menor a 5% se marca como sin cambio (▬). Más operaciones se sostiene "
               "ampliando cobertura; más valor por operación, con mezcla o precio.")


def _tabla(matriz: dict, schema: dict) -> None:
    filas = []
    for f in matriz["filas"]:
        filas.append({
            "Canal": f["canal"],
            _label(schema, matriz["metrica"]): _fmt(f["valor"]),
            "Part.": f"{f['participacion']:.1f}%",
            "Crecim.": ("—" if f["crecimiento"] is None else f"{f['crecimiento']:+.1f}%"),
            "Meta": ("—" if f["cumplimiento"] is None else f"{f['cumplimiento']:.0f}%"),
            "Qué lo mueve": (f.get("mezcla") or "—").capitalize(),
            "Jugada": f["cuadrante_label"],
        })
    st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)


def _jugadas(matriz: dict) -> None:
    lista = oportunidades(matriz)
    if not lista:
        return
    st.markdown(section_header(
        "Las jugadas, por impacto",
        eyebrow="DÓNDE PONER EL ESFUERZO",
        subtitle="Cada una con su cifra, para poder compararlas y elegir en vez de discutirlas.",
        compact=True), unsafe_allow_html=True)
    for jugada in lista:
        color = COLOR_CUADRANTE.get(jugada["cuadrante"], "#10B9A6")
        palanca = (f'<div style="font-size:12px;color:var(--soft);margin-top:6px">'
                   f'Palanca: {clean_display_text(jugada["palanca"])}</div>') if jugada["palanca"] else ""
        st.markdown(
            f"""<div style="background:var(--panel);border:1px solid var(--line);
            border-left:4px solid {color};border-radius:var(--radius-md);padding:13px 16px;
            margin-bottom:9px;box-shadow:var(--shadow-sm);display:flex;gap:16px;
            align-items:flex-start;justify-content:space-between;flex-wrap:wrap">
              <div style="flex:1;min-width:240px">
                <span style="font-size:9px;font-weight:800;letter-spacing:.07em;
                      text-transform:uppercase;color:{color}">{clean_display_text(jugada['tipo'])}</span>
                <div style="font-size:13.5px;color:var(--text);margin-top:4px">
                  {clean_display_text(jugada['texto'])}</div>
                {palanca}
              </div>
              <div style="text-align:right;min-width:96px">
                <div style="font-size:9px;color:var(--muted);font-weight:700;
                     text-transform:uppercase;letter-spacing:.05em">Impacto</div>
                <div style="font-size:19px;font-weight:800;color:{color};
                     font-family:'Sora','Inter',sans-serif">{_fmt(jugada['impacto'])}</div>
              </div>
            </div>""",
            unsafe_allow_html=True,
        )


def render_comercial(df: pd.DataFrame, schema: dict, dashboard: dict | None = None) -> None:
    _css()
    st.markdown(section_header(
        "Estrategia por canal",
        eyebrow="LECTURA COMERCIAL",
        subtitle="Cuánto pesa cada canal y hacia dónde va, en una sola vista. "
                 "Mirados por separado, un canal grande que cae parece sano.",
    ), unsafe_allow_html=True)

    matriz = matriz_comercial(df, schema)
    if not matriz:
        st.info("Para esta lectura hace falta una columna de canal (o una unidad de negocio con "
                "entre 2 y 25 valores), una métrica numérica y al menos dos periodos con fecha. "
                "Este archivo no reúne las tres cosas.")
        return

    # Permite cambiar la dimensión: el motor elige bien casi siempre, pero la
    # gerencia puede querer leer lo mismo por zona o por producto.
    from core.diagnostics import dimensiones_candidatas

    opciones = [c for c in dimensiones_candidatas(df, schema, matriz["metrica"])
                if 2 <= df[c].astype(str).nunique() <= 25]
    if len(opciones) > 1:
        elegida = st.selectbox("Leer por", opciones, index=opciones.index(matriz["canal"])
                               if matriz["canal"] in opciones else 0,
                               format_func=lambda c: _label(schema, c), key="comercial_dimension")
        if elegida != matriz["canal"]:
            matriz = matriz_comercial(df, schema, canal=elegida) or matriz

    st.markdown(
        f"<div style='border-left:4px solid {'#E4002B' if matriz['en_riesgo'] else '#22A06B'};"
        f"background:var(--panel-2);border-radius:10px;padding:13px 16px;margin:4px 0 14px;"
        f"font-size:14px;color:var(--text);font-weight:600'>{clean_display_text(matriz['titular'])}</div>",
        unsafe_allow_html=True,
    )
    _kpis(matriz, schema)
    _semaforo(matriz, schema)

    resultado = _matriz_figura(matriz, schema)
    if resultado is not None:
        figura, orden, _ = resultado
        grafico, leyenda = two_column(2.1, 1)
        with grafico:
            chart_card(
                f"Matriz de decisión · {_label(schema, matriz['canal'])}",
                "Cada número es un canal (ver la lista). Arriba de la línea punteada pesa más que el "
                "promedio; a la derecha crece, a la izquierda cae. La franja gris del centro es estable.",
                figura, key="comercial_matriz")
        with leyenda:
            st.markdown('<div style="height:62px"></div>', unsafe_allow_html=True)
            _leyenda(orden, matriz)

    principal, lateral = two_column(1.25, 1)
    with principal:
        aporte = _aporte_figura(matriz, schema)
        if aporte is not None:
            chart_card("Quién sumó y quién restó",
                       f"Cuánto aportó cada canal al cambio del total, de {matriz['periodo_anterior_label']} "
                       f"a {matriz['periodo_label']}. Verde suma, rojo resta.",
                       aporte, key="comercial_aporte")
    with lateral:
        st.markdown(section_header(
            "Qué mueve a cada canal",
            subtitle="Si cambió por cantidad de operaciones o por el valor de cada una.",
            compact=True), unsafe_allow_html=True)
        _que_mueve(matriz)

    with st.expander("Ver el detalle por canal en tabla", expanded=False):
        _tabla(matriz, schema)

    _jugadas(matriz)

    st.caption(f"Comparación entre {matriz['periodo_anterior_label']} y {matriz['periodo_label']}, "
               f"sobre los filtros activos. Un canal que se mueve menos de {UMBRAL_MOVIMIENTO:.0f}% se "
               f"considera estable. "
               + (f"La meta sale de la columna «{matriz['meta_columna']}»."
                  if matriz["meta_columna"] else
                  "Sin columna de meta en el archivo: el cumplimiento no se puede calcular."))
