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

from core.dates import format_month_year
from core.forecast import pronosticar, explicar, atribuir, explicar_atribucion, NOMBRES_METODO
from visualization.charts import metric_candidates, _base, _label, cifra_eje, en_espanol
from ui.components.cards import kpi_card
from ui.components.section import decision_strip, section_header
from ui.labels import clean_display_text
from ui.layouts.columns import kpi_grid

# Colores de confianza: el mismo lenguaje que el resto del panel, para que
# "verde/ámbar/rojo" signifique lo mismo aquí que en Calidad o en Alertas.
_TONO = {"alta": ("#0f8a5f", "Confianza alta"),
         "media": ("#b45309", "Confianza media"),
         "baja": ("#be123c", "Confianza baja")}


def _mes(valor, completo: bool = False) -> str:
    """«ago 2026» / «Agosto 2026»: la tabla y las fichas decían «Aug 2026»."""
    texto = format_month_year(valor, full=completo)
    return texto if completo else texto.lower()


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
    meses_proy = [_mes(x) for x in x_proy]
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
        customdata=list(zip(meses_proy, [cifra_eje(v) for v in [ultimo_y] + list(pred["maximo"])])),
        hovertemplate="<b>%{customdata[0]}</b><br>Si va bien: <b>%{customdata[1]}</b><extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=x_proy, y=[ultimo_y] + list(pred["minimo"]), mode="lines", name="Si va mal",
        line=dict(color="#be123c", width=1.6, dash="dot"),
        customdata=list(zip(meses_proy, [cifra_eje(v) for v in [ultimo_y] + list(pred["minimo"])])),
        hovertemplate="<b>%{customdata[0]}</b><br>Si va mal: <b>%{customdata[1]}</b><extra></extra>",
    ))
    # Histórico: lo que de verdad pasó.
    fig.add_trace(go.Scatter(
        x=historico.index, y=historico.values, mode="lines+markers", name="Histórico (real)",
        line=dict(color="#1e293b", width=2.6), marker=dict(size=6),
        customdata=list(zip([_mes(x) for x in historico.index], [cifra_eje(v) for v in historico.values])),
        hovertemplate="<b>%{customdata[0]}</b><br>" + etiqueta + ": <b>%{customdata[1]}</b><extra></extra>",
    ))
    # Proyección central. La cifra va escrita solo en el ÚLTIMO punto: con
    # una en cada punto («818,278,043» tres veces) se montaban unas sobre
    # otras y no se leía ninguna. El resto está en la ficha y en la tabla.
    estimados = list(pred["estimado"])
    fig.add_trace(go.Scatter(
        x=x_proy, y=[ultimo_y] + estimados,
        mode="lines+markers+text", name="Proyección esperada",
        line=dict(color="#e4002b", width=2.8, dash="dash"),
        marker=dict(size=9, symbol="diamond", line=dict(color="#fff", width=1.5)),
        text=[""] * len(estimados) + [cifra_eje(estimados[-1])],
        textposition="top center", textfont=dict(size=12, color="#1e293b"),
        customdata=list(zip(meses_proy, [cifra_eje(v) for v in [ultimo_y] + estimados])),
        hovertemplate="<b>%{customdata[0]}</b><br>Estimado: <b>%{customdata[1]}</b><extra></extra>",
    ))

    # Frontera entre lo real y lo proyectado.
    fig.add_vline(x=ultimo_x, line_width=1.4, line_dash="dot", line_color="#94a3b8")
    fig.add_annotation(x=ultimo_x, yref="paper", y=1.0, text="  proyección →",
                       showarrow=False, xanchor="left", yanchor="top",
                       font=dict(size=10.5, color="#64748b"))
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                      margin=dict(t=54))
    fig = _base(fig, 420)
    fig.update_yaxes(tickformat="~s")
    fig.update_xaxes(tickformat="%b %Y")
    return en_espanol(fig)


def _por_que(atribucion: dict | None, schema: dict, resultado: dict) -> None:
    """Quién está empujando la proyección, y por qué motivo concreto.

    Es la pregunta que sigue a "va a bajar" y la que la pestaña no respondía:
    una línea descendente sin responsable no le dice a nadie qué hacer el
    lunes. Aquí cada nombre viene con cuánto aporta a la tendencia y con la
    causa separada —menos operaciones o de menor valor—, que son dos
    problemas distintos y se corrigen distinto.
    """
    if not atribucion or not atribucion.get("impulsores"):
        return
    baja = atribucion["direccion"] == "baja"
    st.markdown(section_header(
        "Por qué va en esa dirección",
        eyebrow="QUIÉN LA EMPUJA",
        subtitle=(f"La misma tendencia, abierta por {_label(schema, atribucion['dimension'])}. "
                  f"El reparto es exacto: el total de cada periodo es la suma de sus partes, "
                  f"así que la tendencia del total es la suma de las tendencias."),
    ), unsafe_allow_html=True)

    st.markdown(
        f"<div style='border-left:4px solid {'#be123c' if baja else '#0f8a5f'};background:#f8fafc;"
        f"border-radius:10px;padding:12px 15px;margin:4px 0 12px;font-size:13.5px'>"
        f"{explicar_atribucion(atribucion)}</div>",
        unsafe_allow_html=True,
    )

    if atribucion.get("disperso"):
        st.caption("Los de abajo son los mayores del grupo, no los responsables: "
                   "cada uno aporta una parte pequeña del movimiento.")
    columnas = st.columns(len(atribucion["impulsores"]))
    for columna, impulsor in zip(columnas, atribucion["impulsores"]):
        with columna:
            señales = []
            if impulsor["periodos_sin_actividad"]:
                señales.append(f"sin actividad hace {impulsor['periodos_sin_actividad']}")
            elif impulsor["periodos_bajando"] >= 2:
                señales.append(f"{impulsor['periodos_bajando']} periodos seguidos a la baja")
            if impulsor["operaciones"]:
                señales.append(f"{impulsor['operaciones']:,} registros en el histórico")
            nivel = (f"{cifra_eje(impulsor['ultimo'])} → {cifra_eje(impulsor['proyectado'])}"
                     if impulsor["ultimo"] else f"→ {cifra_eje(impulsor['proyectado'])}")
            # En una sola línea a propósito. Con el HTML repartido en líneas
            # indentadas, cuando no había motivo quedaba una línea en blanco:
            # Markdown cerraba ahí el bloque HTML y mostraba el resto como
            # código («<small style=…>» y «</div></div>» a la vista).
            motivo = (f'<div class="insight-action"><b>Por qué:</b> {clean_display_text(impulsor["motivo"])}</div>'
                      if impulsor.get("motivo") else "")
            detalle = (f'<small style="color:var(--soft);display:block;margin-top:7px">'
                       f'{clean_display_text(" · ".join(señales))}</small>' if señales else "")
            st.markdown(
                f'<div class="insight-card {"warning" if baja else "positive"} compact"><div class="insight-body">'
                f'<div class="insight-title">{clean_display_text(impulsor["nombre"])}</div>'
                f'<div class="insight-text"><b>{impulsor["peso"]:.0f}%</b> de la tendencia · nivel {nivel}</div>'
                f'{motivo}{detalle}</div></div>',
                unsafe_allow_html=True,
            )

    if atribucion.get("compensan"):
        nombres = ", ".join(f"{c['nombre']} ({'+' if c['delta'] > 0 else ''}{cifra_eje(c['delta'])})"
                            for c in atribucion["compensan"])
        sentido = "amortiguan la caída" if baja else "frenan el crecimiento"
        st.caption(f"En sentido contrario, {nombres} {sentido}.")

    if not atribucion.get("metodo_lineal"):
        st.caption(
            f"El reparto de arriba se calcula sobre la recta de tendencia de cada "
            f"{_label(schema, atribucion['dimension'])}. La línea del gráfico usa "
            f"{NOMBRES_METODO.get(resultado['metodo'], resultado['metodo'])}, así que los aportes "
            f"explican de dónde viene la dirección, no suman exactamente la cifra proyectada."
        )


def _base_calculo(resultado: dict, schema: dict, df: pd.DataFrame) -> None:
    """Ficha de trazabilidad: exactamente sobre qué datos se calculó.

    Va aparte del texto del método a propósito. Son dos preguntas distintas:
    "¿cómo lo calculaste?" (el bloque de arriba) y "¿de dónde salen los
    datos?" (esto). Un pronóstico que no puede responder la segunda no se
    puede defender en una reunión.
    """
    metrica = _label(schema, resultado["metric"])
    fecha = resultado.get("columna_fecha") or "—"
    desde = _mes(resultado["desde"])
    hasta = _mes(resultado["hasta"])
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
    mes_real, mes_prox = _mes(resultado["historico"].index[-1]), _mes(pred["periodo"].iloc[0])
    mes_real_largo = _mes(resultado["historico"].index[-1], True).lower()
    mes_prox_largo = _mes(pred["periodo"].iloc[0], True).lower()
    etiqueta = _label(schema, metrica)
    # «Lo más probable» = el estimado ± el error que el método tuvo en
    # promedio con estos mismos datos. El rango de los escenarios usa el PEOR
    # error medido, que es honesto pero, solo, no sirve para planear (en el
    # archivo de prueba iba de 232 M a 1.400 M para un mes de ~880 M).
    error = resultado.get("error_tipico")
    probable = (max(primero * (1 - error), 0), primero * (1 + error)) if error is not None else None

    # La conclusión primero, en una frase.
    if variacion is not None:
        rumbo = "subiría" if variacion > 1 else "bajaría" if variacion < -1 else "se mantendría"
        frase = (f"Si el comportamiento se mantiene, <b>{etiqueta}</b> {rumbo} en <b>{mes_prox_largo}</b> a "
                 f"<b>≈ {cifra_eje(primero)}</b> ({variacion:+.1f}% frente a {mes_real_largo})")
        frase += (f"; lo más probable es que quede entre <b>{cifra_eje(probable[0])}</b> y "
                  f"<b>{cifra_eje(probable[1])}</b>." if probable else ".")
        tono = "positive" if variacion > 1 else "negative" if variacion < -1 else "neutral"
        st.markdown(decision_strip(frase, tone=tono), unsafe_allow_html=True)

    # kpi_grid recibe los datos y una función que dibuja cada tarjeta; no
    # tarjetas ya construidas (ver ui/layouts/columns.py).
    peor = f"{cifra_eje(pred['minimo'].iloc[0])} – {cifra_eje(pred['maximo'].iloc[0])}"
    tarjetas = [
        {"label": f"{mes_real} · real", "value": cifra_eje(ultimo_real), "delta": None},
        {"label": f"{mes_prox} · estimado", "value": cifra_eje(primero),
         "delta": (f"{variacion:+.1f}% vs {mes_real}" if variacion is not None else None)},
        {"label": "Lo más probable" if probable else "Rango posible",
         "value": f"{cifra_eje(probable[0])} – {cifra_eje(probable[1])}" if probable else peor,
         "delta": f"error típico de {error * 100:.0f}% con tus datos" if probable else None},
        {"label": "Confianza", "value": texto_conf.replace("Confianza ", "").capitalize(),
         "delta": f"peor caso: {peor}" if probable else None},
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

    # Quién empuja la proyección. Va justo después del gráfico: primero se ve
    # hacia dónde va la línea, e inmediatamente después de quién es la línea.
    _por_que(atribuir(df, schema, resultado), schema, resultado)

    # La tabla con las mismas cifras cortas del resto (antes: «818278043»).
    tabla = pd.DataFrame({
        "Periodo": [_mes(p, True) for p in pred["periodo"]],
        "Estimado": [cifra_eje(v) for v in pred["estimado"]],
        "Si va mal": [cifra_eje(v) for v in pred["minimo"]],
        "Si va bien": [cifra_eje(v) for v in pred["maximo"]],
    })
    st.dataframe(tabla, use_container_width=True, hide_index=True)

    st.caption("Cómo leerlo: la proyección supone que se mantiene el comportamiento del histórico. "
               "No incorpora hechos que el archivo no contenga —una campaña, un cierre, un cambio de "
               "precio—, así que conviene contrastarla con lo que sabes del negocio.")
