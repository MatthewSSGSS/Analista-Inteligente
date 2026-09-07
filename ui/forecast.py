"""Pestaña de Predicciones.

Muestra hacia dónde va el indicador principal según su propio histórico, y
—igual de importante— cuánto se puede confiar en esa proyección. Ver
core/forecast.py para el criterio: si el archivo no da para pronosticar, esta
pestaña lo dice en vez de dibujar una línea inventada.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.forecast import pronosticar, explicar, NOMBRES_METODO
from visualization.charts import metric_candidates, _base, _label
from ui.components.cards import kpi_card
from ui.components.section import section_header
from ui.layouts.columns import kpi_grid

# Colores de confianza: el mismo lenguaje que el resto del panel, para que
# "verde/ámbar/rojo" signifique lo mismo aquí que en Calidad o en Alertas.
_TONO = {"alta": ("#0f8a5f", "Confianza alta"),
         "media": ("#b45309", "Confianza media"),
         "baja": ("#be123c", "Confianza baja")}


def _grafico(resultado: dict, schema: dict) -> go.Figure:
    """Histórico y proyección, dibujados como TRES escenarios.

    La banda sombreada sola no terminaba de comunicar: se leía como un
    adorno alrededor de "el número". Dibujar además las líneas del escenario
    optimista y del pesimista hace ver que el futuro es un abanico, no un
    punto — que es exactamente lo que dice el cálculo.

    Se marca también dónde termina lo real y empieza lo proyectado, para que
    nadie confunda un dato con una estimación de un vistazo.
    """
    historico = resultado["historico"]
    pred = resultado["prediccion"]
    etiqueta = _label(schema, resultado["metric"])
    ultimo_x, ultimo_y = historico.index[-1], float(historico.iloc[-1])
    # Cada escenario arranca del último dato real: así las tres líneas nacen
    # del mismo punto conocido y se ve cómo se abren hacia adelante.
    x_proy = [ultimo_x] + list(pred["periodo"])
    fig = go.Figure()

    # Banda del rango, al fondo.
    fig.add_trace(go.Scatter(
        x=x_proy + x_proy[::-1],
        y=[ultimo_y] + list(pred["maximo"]) + ([ultimo_y] + list(pred["minimo"]))[::-1],
        fill="toself", fillcolor="rgba(228,0,43,0.10)",
        line=dict(color="rgba(0,0,0,0)"), hoverinfo="skip",
        name="Rango posible", showlegend=False,
    ))
    # Escenarios extremos: línea fina, sin marcadores, para que acompañen sin
    # competir con la proyección central.
    fig.add_trace(go.Scatter(
        x=x_proy, y=[ultimo_y] + list(pred["maximo"]), mode="lines", name="Si va bien",
        line=dict(color="#0f8a5f", width=1.6, dash="dot"),
        hovertemplate="<b>%{x|%b %Y}</b><br>Escenario optimista: <b>%{y:,.0f}</b><extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=x_proy, y=[ultimo_y] + list(pred["minimo"]), mode="lines", name="Si va mal",
        line=dict(color="#be123c", width=1.6, dash="dot"),
        hovertemplate="<b>%{x|%b %Y}</b><br>Escenario pesimista: <b>%{y:,.0f}</b><extra></extra>",
    ))
    # Histórico: lo que de verdad pasó.
    fig.add_trace(go.Scatter(
        x=historico.index, y=historico.values, mode="lines+markers", name="Histórico (real)",
        line=dict(color="#1e293b", width=2.6), marker=dict(size=6),
        hovertemplate="<b>%{x|%b %Y}</b><br>" + etiqueta + ": <b>%{y:,.0f}</b><extra></extra>",
    ))
    # Proyección central, con el valor escrito sobre cada punto para poder
    # leer la cifra sin pasar el mouse (importante al presentar en pantalla).
    fig.add_trace(go.Scatter(
        x=x_proy, y=[ultimo_y] + list(pred["estimado"]),
        mode="lines+markers+text", name="Proyección esperada",
        line=dict(color="#e4002b", width=2.8, dash="dash"),
        marker=dict(size=9, symbol="diamond", line=dict(color="#fff", width=1.5)),
        text=[""] + [f"{v:,.0f}" for v in pred["estimado"]],
        textposition="top center", textfont=dict(size=11, color="#e4002b"),
        hovertemplate="<b>%{x|%b %Y}</b><br>Estimado: <b>%{y:,.0f}</b><extra></extra>",
    ))

    # Frontera entre lo real y lo proyectado.
    fig.add_vline(x=ultimo_x, line_width=1.4, line_dash="dot", line_color="#94a3b8")
    fig.add_annotation(x=ultimo_x, yref="paper", y=1.0, text="  proyección →",
                       showarrow=False, xanchor="left", yanchor="top",
                       font=dict(size=10.5, color="#64748b"))
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                      margin=dict(t=54))
    return _base(fig, 420)


def _base_calculo(resultado: dict, schema: dict, df: pd.DataFrame) -> None:
    """Ficha de trazabilidad: exactamente sobre qué datos se calculó.

    Va aparte del texto del método a propósito. Son dos preguntas distintas:
    "¿cómo lo calculaste?" (el bloque de arriba) y "¿de dónde salen los
    datos?" (esto). Un pronóstico que no puede responder la segunda no se
    puede defender en una reunión.
    """
    metrica = _label(schema, resultado["metric"])
    fecha = resultado.get("columna_fecha") or "—"
    desde = pd.Timestamp(resultado["desde"]).strftime("%b %Y")
    hasta = pd.Timestamp(resultado["hasta"]).strftime("%b %Y")
    grano = {"Mes": "mes", "Día": "día", "Semana": "semana"}.get(resultado.get("grain", "Mes"), "periodo")

    with st.expander("¿En qué se basa esta predicción?", expanded=False):
        st.markdown(
            f"""
- **Indicador proyectado:** {metrica}, sumado por {grano}
- **Columna de fecha usada:** `{fecha}`
- **Historia disponible:** {resultado['periodos']} periodos, de **{desde}** a **{hasta}**
- **Registros del archivo considerados:** {resultado['filas_usadas']:,} (los que pasan los filtros activos)
- **Método:** {NOMBRES_METODO.get(resultado['metodo'], resultado['metodo'])}
"""
        )
        st.markdown(
            "**Cómo se calculó el rango:** no sale de una fórmula teórica. Se esconden los últimos "
            "periodos de tu histórico, se predicen *como si no se conocieran* y se compara con lo que "
            "realmente pasó. Ese error medido es el que define el rango — por eso se puede afirmar "
            "cuánto suele equivocarse con **tus** datos y no con datos de ejemplo."
        )
        st.markdown(
            "**Lo único que mira son estos datos.** No usa información externa, ni datos de otros "
            "archivos, ni supuestos del mercado: solo el histórico de esta hoja, con los filtros que "
            "tengas puestos ahora mismo."
        )


def render_forecast(df: pd.DataFrame, schema: dict, dashboard: dict | None = None) -> None:
    st.markdown(section_header(
        "Hacia dónde va",
        eyebrow="PREDICCIONES",
        subtitle="Proyección del indicador a partir de su propio histórico, con el margen de error medido sobre tus datos.",
    ), unsafe_allow_html=True)

    metricas = [m for m in metric_candidates(df, schema) if m in df.columns]
    if not metricas:
        st.info("Este archivo no tiene una métrica numérica que se pueda proyectar en el tiempo.")
        return
    if not [d for d in schema.get("dates", []) if d in df.columns]:
        st.info("Para proyectar hace falta una columna de fecha o periodo. "
                "Este archivo no tiene una que el motor haya podido reconocer.")
        return

    principal = (dashboard or {}).get("primary_metric")
    indice = metricas.index(principal) if principal in metricas else 0
    c1, c2 = st.columns([2, 1])
    with c1:
        metrica = st.selectbox("Indicador a proyectar", metricas, index=indice,
                               format_func=lambda c: _label(schema, c), key="forecast_metric")
    with c2:
        horizonte = st.slider("Periodos a futuro", 1, 6, 3, key="forecast_horizonte")

    resultado = pronosticar(df, schema, metrica, horizonte=horizonte)

    if not resultado.get("viable"):
        st.warning(f"**No se puede proyectar este indicador.** {resultado.get('motivo', '')}")
        st.caption("No se muestra ninguna cifra a propósito: con esta cantidad de historia, cualquier "
                   "proyección sería una suposición disfrazada de dato.")
        return

    color, texto_conf = _TONO.get(resultado["confianza"], _TONO["baja"])
    pred = resultado["prediccion"]
    ultimo_real = float(resultado["historico"].iloc[-1])
    primero = float(pred["estimado"].iloc[0])
    variacion = ((primero - ultimo_real) / abs(ultimo_real) * 100) if ultimo_real else None

    # kpi_grid recibe los datos y una función que dibuja cada tarjeta; no
    # tarjetas ya construidas (ver ui/layouts/columns.py).
    tarjetas = [
        {"label": "Último periodo real", "value": f"{ultimo_real:,.0f}", "delta": None},
        {"label": "Próximo periodo (estimado)", "value": f"{primero:,.0f}",
         "delta": (f"{variacion:+.1f}%" if variacion is not None else None)},
        {"label": "Rango posible",
         "value": f"{pred['minimo'].iloc[0]:,.0f} – {pred['maximo'].iloc[0]:,.0f}", "delta": None},
        {"label": "Confianza", "value": texto_conf.replace("Confianza ", "").capitalize(), "delta": None},
    ]
    kpi_grid(tarjetas, lambda t: kpi_card(t["label"], t["value"], delta=t["delta"]))

    st.markdown(
        f"<div style='border-left:4px solid {color};background:#f8fafc;border-radius:10px;"
        f"padding:12px 15px;margin:12px 0;font-size:13.5px'>{explicar(resultado)}</div>",
        unsafe_allow_html=True,
    )

    # En qué se basa, en concreto. El bloque de arriba explica el MÉTODO y
    # su margen de error; esto dice de dónde salieron los datos: qué columna
    # de fecha, qué se sumó y entre qué periodos. Es lo primero que van a
    # preguntar cuando alguien presente este número.
    _base_calculo(resultado, schema, df)

    st.plotly_chart(_grafico(resultado, schema), use_container_width=True,
                    key="forecast_chart")

    tabla = pred.copy()
    tabla["periodo"] = pd.to_datetime(tabla["periodo"]).dt.strftime("%b %Y")
    tabla.columns = ["Periodo", "Estimado", "Mínimo esperado", "Máximo esperado"]
    st.dataframe(tabla.round(0), use_container_width=True, hide_index=True)

    st.caption("Cómo leerlo: la proyección supone que se mantiene el comportamiento del histórico. "
               "No incorpora hechos que el archivo no contenga —una campaña, un cierre, un cambio de "
               "precio—, así que conviene contrastarla con lo que sabes del negocio.")
