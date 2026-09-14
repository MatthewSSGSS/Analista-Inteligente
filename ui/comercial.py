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
3. El mapa de decisión: una fila por canal, así nada se monta aunque se
   muevan parecido.
4. Quién sumó y quién restó, y qué mueve a cada canal.
5. El detalle y las jugadas con su cifra.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.comercial import (CUADRANTES, UMBRAL_MOVIMIENTO, estado_salud, matriz_comercial,
                            oportunidades, puntaje_salud)
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

# Escala de salud: rojo, ámbar y verde de la misma paleta. Se interpola entre
# ellos para que un 88% de la meta no se pinte igual que un 40%.
_ROJO_RGB = (228, 0, 43)
_AMBAR_RGB = (245, 158, 11)
_VERDE_RGB = (34, 160, 107)


def _color_escala(puntaje: float) -> str:
    """Color para un puntaje de 0 (rojo) a 1 (verde), pasando por ámbar."""
    t = max(0.0, min(1.0, float(puntaje)))
    if t < 0.5:
        desde, hasta, u = _ROJO_RGB, _AMBAR_RGB, t / 0.5
    else:
        desde, hasta, u = _AMBAR_RGB, _VERDE_RGB, (t - 0.5) / 0.5
    r, g, b = (round(desde[i] + (hasta[i] - desde[i]) * u) for i in range(3))
    return f"#{r:02X}{g:02X}{b:02X}"


def _color_crecimiento(crecimiento) -> str:
    if crecimiento is None:
        return "#64748B"
    return _color_escala((float(crecimiento) + 5.0) / 10.0)


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

        .canal-escala{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:11.5px;
          color:var(--muted);margin:0 0 12px}
        .canal-escala-barra{flex:0 1 240px;min-width:120px;height:8px;border-radius:999px;
          background:linear-gradient(90deg,#E4002B 0%,#F59E0B 50%,#22A06B 100%)}
        .canal-card-cabeza{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}
        .canal-pill{flex:0 0 auto;font-size:9.5px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;
          color:var(--c);background:color-mix(in srgb,var(--c) 14%,transparent);padding:3px 7px;
          border-radius:999px;white-space:nowrap}

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

    El color de cada tarjeta dice qué tan bien va, de rojo a verde: contra la
    meta si el archivo la trae, o contra su crecimiento si no. Antes todas
    salían grises cuando los canales estaban quietos, y la meta en rojo
    aunque fuera un 90%: el color no distinguía nada. Además del color, cada
    tarjeta lo dice en palabras, para que se lea igual impreso en gris.
    """
    st.markdown(section_header(
        "Semáforo de canales",
        eyebrow="A SIMPLE VISTA",
        subtitle="Cada canal agrupado por lo que hay que hacer con él. Arriba lo urgente; abajo lo que está estable.",
        compact=True), unsafe_allow_html=True)
    con_meta = any(f["cumplimiento"] is not None for f in matriz["filas"])
    desde, hasta = (("80% de la meta o menos", "100% de la meta o más") if con_meta
                    else ("cae 5% o más", "crece 5% o más"))
    st.markdown(
        f'<div class="canal-escala"><span>Color de cada tarjeta:</span><span>{desde}</span>'
        f'<span class="canal-escala-barra"></span><span>{hasta}</span></div>',
        unsafe_allow_html=True)

    mayor = max((f["participacion"] for f in matriz["filas"]), default=1) or 1
    for clave in ORDEN_JUGADAS:
        grupo = [f for f in matriz["filas"] if f["cuadrante"] == clave]
        if not grupo:
            continue
        tarjetas = []
        for f in sorted(grupo, key=lambda z: z["participacion"], reverse=True):
            puntaje = puntaje_salud(f)[0]
            color = _color_escala(puntaje)
            flecha = _flecha(f["crecimiento"])[0]
            crecimiento = "—" if f["crecimiento"] is None else f"{f['crecimiento']:+.1f}%"
            nombre = clean_display_text(f["canal"])
            meta = ""
            if f["cumplimiento"] is not None:
                color_meta = _color_escala(puntaje_salud({"cumplimiento": f["cumplimiento"]})[0])
                meta = (f'<div class="canal-card-fila"><span>Meta</span>'
                        f'<b style="color:{color_meta}">{f["cumplimiento"]:.0f}%</b></div>')
            ancho = f["participacion"] / mayor * 100
            color_crec = _color_crecimiento(f["crecimiento"])
            tarjetas.append(
                f'<div class="canal-card" style="--c:{color}" title="{nombre}">'
                f'<div class="canal-card-cabeza"><div class="canal-card-nombre">{nombre}</div>'
                f'<span class="canal-pill">{estado_salud(puntaje)}</span></div>'
                f'<div class="canal-card-valor">{_fmt(f["valor"])}</div>'
                f'<div class="canal-card-fila"><span>Participación</span><b>{f["participacion"]:.1f}%</b></div>'
                f'<div class="canal-card-fila"><span>vs. {matriz["periodo_anterior_label"]}</span>'
                f'<b style="color:{color_crec}">{flecha} {crecimiento}</b></div>'
                f'{meta}'
                f'<div class="canal-barra"><span style="width:{ancho:.0f}%"></span></div>'
                f'</div>'
            )
        color_grupo = COLOR_CUADRANTE[clave]
        etiqueta_grupo = CUADRANTES[clave]["etiqueta"]
        accion_grupo = CUADRANTES[clave]["accion"]
        st.markdown(
            f'<div class="canal-grupo"><div class="canal-grupo-head">'
            f'<span class="canal-grupo-chip" style="background:{color_grupo}">'
            f'{etiqueta_grupo} · {len(grupo)}</span>'
            f'<span class="canal-grupo-lectura">{accion_grupo}</span></div>'
            f'<div class="canal-grid">{"".join(tarjetas)}</div></div>',
            unsafe_allow_html=True,
        )


def _matriz_figura(matriz: dict, schema: dict):
    """Mapa de decisión: una fila por canal, para que nada se monte.

    Reemplaza a la matriz de burbujas. De un mes a otro los canales suelen
    moverse parecido, y entonces todas las burbujas caían en la misma columna,
    se tapaban entre sí y los números dejaban de leerse. Este mapa dice lo
    mismo sin esas colisiones:

    - Cada fila es un canal, ordenado por cuánto pesa. La línea punteada
      separa a los que pesan más que el promedio de los que pesan menos.
    - La posición horizontal dice hacia dónde va: franja roja cae, gris
      estable, verde crece, con el mismo umbral que clasifica.
    - El color del punto es el del semáforo, y su tamaño, el peso.
    """
    filas = [f for f in matriz["filas"] if f["crecimiento"] is not None]
    if not filas:
        return None
    orden = sorted(filas, key=lambda f: f["participacion"], reverse=True)
    n = len(orden)
    u = UMBRAL_MOVIMIENTO
    maximo = max(abs(f["crecimiento"]) for f in orden)
    limite = max(maximo * 1.3, u * 3)
    pesan = sum(1 for f in orden if f.get("pesa"))
    colores = [_color_escala(puntaje_salud(f)[0]) for f in orden]

    fig = go.Figure()
    for x0, x1, clave, texto in ((-limite, -u, "intervenir", "CAE"),
                                 (-u, u, "estable", "ESTABLE"),
                                 (u, limite, "proteger", "CRECE")):
        color = COLOR_CUADRANTE[clave]
        fig.add_shape(type="rect", xref="x", yref="paper", x0=x0, x1=x1, y0=0, y1=1,
                      layer="below", fillcolor=color, opacity=0.07, line=dict(width=0))
        fig.add_annotation(xref="x", yref="paper", x=(x0 + x1) / 2, y=1, yanchor="bottom",
                           text=f"<b>{texto}</b>", showarrow=False,
                           font=dict(size=11, color=color, family="Inter"))
    fig.add_vline(x=0, line_width=1.2, line_color="#94A3B8")

    if 0 < pesan < n:
        fig.add_shape(type="line", xref="paper", yref="y", x0=0, x1=1, y0=pesan - 0.5, y1=pesan - 0.5,
                      line=dict(color="#94A3B8", width=1.3, dash="dot"))
        for desplazamiento, texto in ((11, "pesan más que el promedio"), (-11, "pesan menos que el promedio")):
            fig.add_annotation(xref="paper", yref="y", x=1, y=pesan - 0.5, yshift=desplazamiento,
                               xanchor="right", showarrow=False, text=texto,
                               font=dict(size=10, color="#64748B"))

    for i, f in enumerate(orden):
        fig.add_shape(type="line", xref="x", yref="y", x0=0, x1=f["crecimiento"], y0=i, y1=i,
                      line=dict(color=colores[i], width=3), layer="below")

    mayor = max(f["participacion"] for f in orden) or 1
    fig.add_trace(go.Scatter(
        x=[f["crecimiento"] for f in orden], y=list(range(n)), mode="markers+text",
        marker=dict(size=[13 + f["participacion"] / mayor * 15 for f in orden], color=colores,
                    line=dict(color="#FFFFFF", width=2)),
        text=[f"{f['crecimiento']:+.1f}%" for f in orden],
        textposition=["middle left" if f["crecimiento"] < 0 else "middle right" for f in orden],
        textfont=dict(size=11, color="#1A2233"),
        customdata=[[f["canal"], _fmt(f["valor"]), f["participacion"], f["crecimiento"],
                     f["cuadrante_label"],
                     ("—" if f["cumplimiento"] is None else f"{f['cumplimiento']:.0f}%"),
                     estado_salud(puntaje_salud(f)[0])] for f in orden],
        hovertemplate=("<b>%{customdata[0]}</b><br>"
                       + _label(schema, matriz["metrica"]) + ": <b>%{customdata[1]}</b><br>"
                       "Participación: <b>%{customdata[2]:.1f}%</b><br>"
                       "Crecimiento: <b>%{customdata[3]:+.1f}%</b><br>"
                       "Meta: <b>%{customdata[5]}</b> · %{customdata[6]}<br>"
                       "Jugada: <b>%{customdata[4]}</b><extra></extra>"),
        showlegend=False,
    ))

    etiquetas = [f"{_corto(f['canal'], 30)}   {f['participacion']:.1f}%" for f in orden]
    fig = _base(fig, max(300, 40 * n + 100), show_xgrid=True)
    # Después de _base, porque _base impone hover unificado, y aquí hace
    # falta ver un canal a la vez.
    fig.update_yaxes(tickmode="array", tickvals=list(range(n)), ticktext=etiquetas,
                     autorange="reversed", title=None)
    fig.update_xaxes(range=[-limite, limite], ticksuffix="%",
                     title="Crecimiento frente al periodo anterior")
    fig.update_layout(margin=dict(l=10, r=20, t=34, b=40), hovermode="closest", showlegend=False)
    return fig


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
    fig = realzar_barras(_base(fig, max(260, 40 * len(filas) + 90), show_xgrid=False))
    fig.update_layout(hovermode="closest")
    return fig


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

    figura = _matriz_figura(matriz, schema)
    if figura is not None:
        chart_card(
            f"Mapa de decisión · {_label(schema, matriz['canal'])}",
            "Una fila por canal, ordenados por cuánto pesan. La franja dice hacia dónde va: roja cae, "
            "gris estable, verde crece. La línea punteada separa a los que pesan más que el promedio. "
            "El color del punto es el mismo del semáforo.",
            figura, key="comercial_matriz")

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
