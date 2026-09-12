"""Pestaña "Estrategia por canal": la lectura para dirigir, no para leer.

Pensada para una presentación a gerencia regional. El orden de la pantalla es
el orden en que se toma la decisión:

1. El titular: qué pasa y qué es lo urgente.
2. La matriz peso × crecimiento, que es donde se ve de un golpe qué canal se
   protege, cuál se interviene, cuál se apuesta y cuál se revisa.
3. Qué mueve a cada canal: más operaciones o mayor valor por operación. Son
   dos palancas distintas y se accionan distinto.
4. Las jugadas, con su impacto en la moneda del archivo para poder compararlas.

Ver `core/comercial.py` para el criterio. Aquí solo se pinta, respetando la
paleta y el estilo del resto del panel.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.comercial import CUADRANTES, matriz_comercial, oportunidades
from core.diagnostics import _fmt
from ui.components.charts import chart_card
from ui.components.section import section_header
from ui.labels import clean_display_text
from ui.layouts.columns import two_column
from visualization.charts import _base, _label, realzar_barras

# Colores de la paleta del panel, uno por cuadrante. El rojo corporativo se
# reserva para la urgencia: si se usa en todo, deja de significar nada.
COLOR_CUADRANTE = {
    "intervenir": "#E4002B",
    "proteger": "#22A06B",
    "apostar": "#10B9A6",
    "revisar": "#F59E0B",
}


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


def _matriz_figura(matriz: dict, schema: dict) -> go.Figure:
    """Peso × crecimiento. Cada burbuja es un canal; el color, su jugada."""
    filas = [f for f in matriz["filas"] if f["crecimiento"] is not None]
    if not filas:
        return None
    fig = go.Figure()
    maximo = max(abs(f["crecimiento"]) for f in filas) or 1
    limite = max(maximo * 1.35, 12)
    techo = max(f["participacion"] for f in filas) * 1.35

    # Fondos de cuadrante: tinte muy suave, solo para orientar la lectura.
    corte = matriz["corte_peso"]
    for x0, x1, y0, y1, clave in (
        (-limite, 0, corte, techo, "intervenir"),
        (0, limite, corte, techo, "proteger"),
        (0, limite, 0, corte, "apostar"),
        (-limite, 0, 0, corte, "revisar"),
    ):
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, layer="below",
                      fillcolor=COLOR_CUADRANTE[clave], opacity=0.055, line=dict(width=0))
        fig.add_annotation(x=(x0 + x1) / 2, y=y1, text=CUADRANTES[clave]["etiqueta"].upper(),
                           showarrow=False, yanchor="top",
                           font=dict(size=9.5, color=COLOR_CUADRANTE[clave], family="Inter"),
                           opacity=0.85)

    tamanos = [f["valor"] for f in filas]
    mayor = max(tamanos) or 1
    for clave in ("intervenir", "proteger", "apostar", "revisar"):
        grupo = [f for f in filas if f["cuadrante"] == clave]
        if not grupo:
            continue
        fig.add_trace(go.Scatter(
            x=[f["crecimiento"] for f in grupo],
            y=[f["participacion"] for f in grupo],
            mode="markers+text",
            name=CUADRANTES[clave]["etiqueta"],
            text=[f["canal"] for f in grupo],
            textposition="top center",
            textfont=dict(size=11, color=COLOR_CUADRANTE[clave]),
            marker=dict(
                size=[18 + (f["valor"] / mayor) * 42 for f in grupo],
                color=COLOR_CUADRANTE[clave], opacity=0.82,
                line=dict(color="#FFFFFF", width=2.2),
            ),
            customdata=[[f["canal"], _fmt(f["valor"]), f["participacion"],
                         f["crecimiento"], f.get("mezcla") or "sin cambio relevante"] for f in grupo],
            hovertemplate=("<b>%{customdata[0]}</b><br>"
                           + _label(schema, matriz["metrica"]) + ": <b>%{customdata[1]}</b><br>"
                           "Participación: <b>%{customdata[2]:.1f}%</b><br>"
                           "Crecimiento: <b>%{customdata[3]:+.1f}%</b><br>"
                           "%{customdata[4]}<extra></extra>"),
        ))

    fig.add_vline(x=0, line_width=1.3, line_dash="dot", line_color="#94A3B8")
    fig.add_hline(y=corte, line_width=1.3, line_dash="dot", line_color="#94A3B8")
    fig.update_xaxes(title="Crecimiento vs. periodo anterior", ticksuffix="%",
                     range=[-limite, limite], zeroline=False)
    fig.update_yaxes(title="Participación en el total", ticksuffix="%", range=[0, techo])
    fig.update_layout(showlegend=False, margin=dict(l=10, r=20, t=30, b=40), hovermode="closest")
    return _base(fig, 460, show_xgrid=True)


def _palancas_figura(matriz: dict) -> go.Figure:
    """Qué mueve a cada canal: operaciones contra valor por operación."""
    filas = [f for f in matriz["filas"]
             if f.get("volumen_pct") is not None and f.get("ticket_pct") is not None]
    if not filas:
        return None
    filas = sorted(filas, key=lambda f: f["participacion"])
    nombres = [f["canal"] for f in filas]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=nombres, x=[f["volumen_pct"] for f in filas], orientation="h",
        name="Nº de operaciones", marker=dict(color="#7C6FE8", line=dict(width=0)),
        hovertemplate="<b>%{y}</b><br>Operaciones: <b>%{x:+.0f}%</b><extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=nombres, x=[f["ticket_pct"] for f in filas], orientation="h",
        name="Valor por operación", marker=dict(color="#10B9A6", line=dict(width=0)),
        hovertemplate="<b>%{y}</b><br>Valor por operación: <b>%{x:+.0f}%</b><extra></extra>",
    ))
    fig.add_vline(x=0, line_width=1.2, line_color="#94A3B8")
    fig.update_layout(barmode="group", bargap=0.28, bargroupgap=0.08,
                      margin=dict(l=10, r=24, t=30, b=24), hovermode="closest")
    fig.update_xaxes(ticksuffix="%", title="Variación frente al periodo anterior")
    fig.update_yaxes(title=None)
    return realzar_barras(_base(fig, max(280, 46 * len(filas) + 90), show_xgrid=True), radio=5)


def _aporte_figura(matriz: dict, schema: dict) -> go.Figure:
    """Quién sumó y quién restó al total, en la moneda del archivo."""
    filas = sorted(matriz["filas"], key=lambda f: f["delta"])
    nombres = [f["canal"] for f in filas]
    valores = [f["delta"] for f in filas]
    colores = ["#E4002B" if v < 0 else "#22A06B" for v in valores]
    fig = go.Figure(go.Bar(
        y=nombres, x=valores, orientation="h",
        marker=dict(color=colores, line=dict(width=0)),
        text=[_fmt(v) for v in valores], textposition="outside", cliponaxis=False,
        textfont=dict(size=11),
        hovertemplate="<b>%{y}</b><br>Aporte al cambio: <b>%{text}</b><extra></extra>",
    ))
    fig.add_vline(x=0, line_width=1.2, line_color="#94A3B8")
    fig.update_layout(showlegend=False, bargap=0.32, margin=dict(l=10, r=70, t=24, b=24),
                      hovermode="closest")
    fig.update_xaxes(title=f"Aporte al cambio del total · {matriz['periodo_anterior_label']} → {matriz['periodo_label']}")
    fig.update_yaxes(title=None)
    return realzar_barras(_base(fig, max(260, 40 * len(filas) + 80), show_xgrid=True))


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
    st.markdown(section_header(
        "Estrategia por canal",
        eyebrow="LECTURA COMERCIAL",
        subtitle="Cuánto pesa cada canal y hacia dónde va, cruzado en una sola vista. "
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

    figura = _matriz_figura(matriz, schema)
    if figura is not None:
        chart_card(
            f"Matriz de decisión · {_label(schema, matriz['canal'])}",
            "El tamaño de cada burbuja es su volumen. La línea horizontal es la participación media: "
            "por encima, el canal pesa; a la derecha del cero, crece.",
            figura, key="comercial_matriz")

    principal, lateral = two_column(1.35, 1)
    with principal:
        aporte = _aporte_figura(matriz, schema)
        if aporte is not None:
            chart_card("Quién sumó y quién restó",
                       f"Aporte de cada canal al cambio del total frente a {matriz['periodo_anterior_label']}.",
                       aporte, key="comercial_aporte")
    with lateral:
        palancas = _palancas_figura(matriz)
        if palancas is not None:
            chart_card("Qué mueve a cada canal",
                       "Más operaciones se sostiene ampliando cobertura; más valor por operación, con mezcla o precio.",
                       palancas, key="comercial_palancas")

    st.markdown(section_header("Detalle por canal", compact=True), unsafe_allow_html=True)
    _tabla(matriz, schema)

    _jugadas(matriz)

    st.caption(f"Comparación entre {matriz['periodo_anterior_label']} y {matriz['periodo_label']}, "
               f"sobre los filtros activos. "
               + (f"La meta sale de la columna «{matriz['meta_columna']}»."
                  if matriz["meta_columna"] else
                  "Sin columna de meta en el archivo: el cumplimiento no se puede calcular."))
