from __future__ import annotations
import pandas as pd
import streamlit as st

from ui.layouts.tabs import ir_a, VISTA_ATACAR, VISTA_SEGUIMIENTO
from core.universal_analysis import dynamic_kpis, smart_chart_questions, period_series
from core.tracking_engine import project_metric
from core.dates import format_month_year
from core.executive import indicadores_gerente
from visualization.charts import trend, ranking, period_compare_bar, donut, histogram, rangos, scatter, concentracion, metric_candidates, dimension_candidates, _label
from ui.labels import clean_display_text
from ui.dashboard import _fmt, _chart_insight, _display_kpi_value, _kpi_style
from ui.components.cards import kpi_card, insight_card, executive_headline, executive_signals
from ui.components.charts import chart_card
from ui.components.section import section_header, banner_header
from ui.layouts.columns import two_column, kpi_grid
from ui.person_profile import has_entity


def _gerencia(df, schema, dashboard):
    from core.gerencia import analisis_gerencial
    g = dashboard.get("gerencia") if isinstance(dashboard, dict) else None
    if g is None and not (isinstance(dashboard, dict) and "gerencia" in dashboard):
        try:
            g = analisis_gerencial(df, schema, dashboard)
        except Exception:
            g = None
    return g


def _por_que_y_que_atacar(df, schema, dashboard) -> None:
    """La lectura gerencial en tres frases, justo bajo el veredicto, con sus
    dos accesos directos dentro de la misma tarjeta.

    El veredicto dice CUÁNTO se movió el número; un gerente pregunta enseguida
    por qué y qué hacer. Aquí va la respuesta corta (causa, palanca y lo que
    más vale atacar) y, a la derecha, los botones al detalle: antes quedaban
    sueltos debajo, uno de cada ancho, y parecían mal puestos."""
    import html as _html
    g = _gerencia(df, schema, dashboard)
    con_seguimiento = has_entity(df, schema)
    frases = []
    if g and g.get("frases"):
        frases = [f for f in g["frases"] if not f.startswith("En sentido contrario") and not f.startswith("Le siguen")][:3]
    if not frases and not con_seguimiento:
        return
    st.markdown(
        """<style>
        .st-key-pq_bloque{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--blue);
          border-radius:var(--radius-md);padding:14px 18px;box-shadow:var(--shadow-sm);margin:6px 0 10px}
        .pq-eyebrow{font-size:10.5px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--blue)}
        .pq-lista{margin:6px 0 0;padding-left:18px}
        .pq-lista li{font-size:13.5px;color:var(--text);line-height:1.5;margin-bottom:3px}
        .st-key-pq_bloque .stButton>button{width:100%;justify-content:center}
        </style>""",
        unsafe_allow_html=True,
    )
    with st.container(key="pq_bloque"):
        if frases:
            texto, acciones = st.columns([2.6, 1], vertical_alignment="center", gap="medium")
            with texto:
                items = "".join(f"<li>{_html.escape(clean_display_text(f))}</li>" for f in frases)
                st.markdown(
                    f'<div class="pq-eyebrow">Por qué y qué atacar · {_html.escape(g["mes_b"])} vs {_html.escape(g["mes_a"])}</div>'
                    f'<ul class="pq-lista">{items}</ul>', unsafe_allow_html=True)
        else:
            acciones = st.container()
        with acciones:
            if frases:
                st.button("🎯 Ver qué atacar y el plan", key="ir_atacar_resumen", type="primary",
                          use_container_width=True, on_click=ir_a, args=(VISTA_ATACAR,))
            if con_seguimiento:
                # Sin `help=`: el tooltip envuelve el botón en otro div y deja de
                # aplicarle el estilo del tema (salía negro con el texto invisible).
                st.button("🔎 Ver un caso concreto", key="ir_seguimiento_res", use_container_width=True,
                          on_click=ir_a, args=(VISTA_SEGUIMIENTO,))


def _senales_con_nombres(dashboard, g):
    """Señales con nombre y cifra («Caribe +148.9M»), no títulos de hallazgos
    («Dónde se concentra la caída»): quién empujó hacia arriba y quién frenó,
    sacado del análisis gerencial. Sin él, quedan las de siempre."""
    ex = dict((dashboard or {}).get("executive") or {})
    causas = (g or {}).get("causas") or {}
    nodos, contra = causas.get("nodos") or [], causas.get("compensaron") or []
    if not (g and g.get("se_movio") and (nodos or contra)):
        return dashboard
    subio = (g.get("delta") or 0) > 0
    suben = nodos if subio else contra
    bajan = contra if subio else nodos
    dim = causas.get("etiqueta") or causas.get("dimension") or ""

    def _linea(n):
        signo = "+" if n["delta"] > 0 else ""
        return f"{n['nombre']} {signo}{_fmt(n['delta'])}" + (f" ({dim})" if dim else "")
    positivas = [_linea(n) for n in suben if n.get("delta", 0) > 0][:3]
    vigilar = [_linea(n) for n in bajan if n.get("delta", 0) < 0][:2]
    # Lo que no es de una zona (calidad, atípicos, estados) sigue en «a vigilar».
    vigilar += [w for w in ex.get("watch", []) if w not in vigilar and "caída" not in str(w).lower()][:3 - len(vigilar)]
    ex["positive"] = positivas or ex.get("positive", [])
    ex["watch"] = vigilar or ex.get("watch", [])
    return {**dashboard, "executive": ex}


def _kpis_gerente(df, schema, g, m) -> list[str]:
    """Las tarjetas del gerente (ver core/executive.indicadores_gerente), ya dibujadas."""
    return [kpi_card(i["etiqueta"], i["valor"], delta=i["detalle"], tone=i["tono"])
            for i in indicadores_gerente(df, schema, g, m)]


def _dimension_de_lectura(df, schema, dims, g):
    """La dimensión de los gráficos del resumen: la que explica el cambio
    (la causa del análisis gerencial) y, si no hay, la primera con pocas
    categorías. Antes era la primera de la lista —que en un archivo de ventas
    es «Cliente», con 5.000 valores—, y los gráficos mostraban «Cliente 9695»."""
    causa = ((g or {}).get("causas") or {}).get("dimension")
    if causa and causa in df.columns:
        return causa
    for d in dims:
        if 2 <= df[d].dropna().astype(str).str.strip().nunique() <= 30:
            return d
    return dims[0] if dims else None


def _veredicto_con_meses(dashboard, g):
    """El veredicto con los meses nombrados: «frente al periodo anterior» a
    secas obligaba a preguntar cuál; la tarjeta de abajo ya decía los meses."""
    if not (isinstance(dashboard, dict) and dashboard.get("executive") and g and g.get("mes_a")):
        return dashboard
    ex = dict(dashboard["executive"])
    for campo in ("headline", "detail"):
        if ex.get(campo):
            ex[campo] = (str(ex[campo])
                         .replace("frente al periodo anterior", f"en {g['mes_b']} frente a {g['mes_a']}")
                         .replace("El último periodo alcanzó", f"{g['mes_b'].capitalize()} alcanzó")
                         .replace("en el periodo anterior", f"en {g['mes_a']}"))
    return {**dashboard, "executive": ex}


def render_executive(df, schema, dashboard):
    st.markdown(banner_header("Resumen ejecutivo", "Vista ejecutiva · lectura compacta para decidir rápido. El contenido se adapta al tipo de Excel detectado.", "ciudad_red.jpg"), unsafe_allow_html=True)

    # ── Veredicto ejecutivo: lo primero que se lee, antes que cualquier KPI
    # o gráfico. dashboard["executive"] ya lo calcula core/executive.py
    # específicamente para esta vista, pero antes esta pantalla no lo
    # mostraba — solo ui/dashboard.py lo usaba. Es la pieza que más
    # protagonismo merece aquí.
    if isinstance(dashboard, dict) and dashboard.get("executive"):
        executive_headline(_veredicto_con_meses(dashboard, _gerencia(df, schema, dashboard)))

    # Por qué y qué atacar, con los accesos a «Qué atacar» y al seguimiento de
    # un caso dentro de la misma tarjeta.
    _por_que_y_que_atacar(df, schema, dashboard)

    # ── Layout de dos columnas: a la izquierda los KPIs y los gráficos
    # principales (lo que ocupa más espacio de lectura), a la derecha la
    # Lectura Analítica en un panel angosto — igual que el resto de la app
    # ya usa (comparación de layouts en Georeferenciación, Comparativa).
    main_col, side_col = two_column(gap="medium")

    def _render_kpi(k):
        label, tone, icon = _kpi_style(k, schema)
        # El líder se mide sobre TODO el periodo; las demás tarjetas, sobre el
        # último mes. Sin decirlo, Tolima salía «mejor» aquí y «a vigilar» al
        # lado (cayó en julio), y parecía una contradicción.
        if k.get("kind") == "leader" and schema.get("dates"):
            label = f"{label} · todo el periodo"
        # En la tarjeta de quién va primero, la cifra que lo sostiene
        # ("541 de una meta de 360") va debajo: sin ella no se sabe contra qué.
        delta = k.get("detalle") if k.get("kind") == "leader" else None
        # Un nombre largo ("COMMUTE SAS SOLEDAD ATLANTICO") con la letra de una
        # cifra ocupaba tres renglones enormes: se muestra en tamaño de texto.
        return kpi_card(label, _display_kpi_value(k), delta=delta, tone=tone, icon=icon,
                        small_value=k.get("kind") == "leader")

    g = _gerencia(df, schema, dashboard)
    with main_col:
        metrics=metric_candidates(df,schema); dims=dimension_candidates(df,schema)
        m=metrics[0] if metrics else None
        principal = (dashboard or {}).get("primary_metric") if isinstance(dashboard, dict) else None
        if principal in metrics:
            m = principal
        d = _dimension_de_lectura(df, schema, dims, g)

        kpis=dynamic_kpis(df,schema,dashboard)
        gerente = _kpis_gerente(df, schema, g, m)
        if len(gerente) >= 3:
            # Las del gerente, más quién va primero (con su base justa).
            lider = [k for k in kpis if k.get("kind") == "leader"][:1]
            tarjetas = gerente[:5] + [_render_kpi(k) for k in lider]
            kpi_grid(tarjetas, render=lambda t: t, per_row=3)
        elif kpis:
            kpi_grid(kpis[:6], render=_render_kpi, per_row=3)
        if m:
            specs=smart_chart_questions(df,schema,m,d)
            rendered=0
            chart_items=[]
            for title,q,kind in specs:
                if rendered>=3: break
                if kind=="trend": fig=trend(df,schema,m,"Mes","Automático",False)
                elif kind=="trend_dia": fig=trend(df,schema,m,"Día","Automático",False)
                elif kind=="concentracion" and d: fig=concentracion(df,schema,m,d)
                elif kind=="ranking" and d: fig=ranking(df,schema,m,d,8,"Automático")
                elif kind=="period_compare" and d: fig=period_compare_bar(df,schema,m,d,"Mes","Automático",8)
                elif kind=="donut" and d: fig=donut(df,schema,m,d,8)
                elif kind=="rangos": fig=rangos(df,schema,m)
                elif kind=="histogram": fig=histogram(df,schema,m)
                else: continue
                if fig is not None:
                    chart_items.append((title,q,fig,kind,rendered)); rendered+=1
            if chart_items:
                st.markdown(section_header("Gráficos que importan", eyebrow="ANÁLISIS", compact=True), unsafe_allow_html=True)
                # El primero es el gráfico principal: a todo el ancho de la
                # columna, para que sea lo primero que se lea. Los que
                # siguen son análisis secundarios, uno al lado del otro.
                main_title,main_q,main_fig,main_kind,main_idx = chart_items[0]
                chart_card(main_title,main_q,main_fig,key=f"executive_{main_kind}_{main_idx}")
                secondary=chart_items[1:3]
                if secondary:
                    cols=st.columns(len(secondary))
                    for i,(title,q,fig,kind,idx) in enumerate(secondary):
                        with cols[i]:
                            chart_card(title,q,fig,key=f"executive_{kind}_{idx}")

    with side_col:
        ex=dashboard.get("executive",{}) if isinstance(dashboard,dict) else {}
        con_nombres = _senales_con_nombres(dashboard, _gerencia(df, schema, dashboard))
        ex = con_nombres.get("executive", {}) if isinstance(con_nombres, dict) else {}
        if ex.get("positive") or ex.get("watch"):
            st.markdown(section_header("Señales", compact=True), unsafe_allow_html=True)
            executive_signals(con_nombres)

        # ── Proyección: "a este ritmo, ¿a cuánto llegarías?" ────────────────
        # Reutiliza project_metric() (regresión lineal simple), que ya existía
        # pero solo se usaba en Análisis de Seguimiento — nunca en el
        # Resumen ejecutivo normal, que es donde la mayoría de la gente
        # primero se pregunta esto. Nada de cálculo nuevo: solo se le da a
        # period_series() (ya usada en toda esta vista) la forma de columnas
        # que project_metric() espera ("period"/"_num").
        if m and schema.get("dates"):
            ps = period_series(df, schema, m, "Mes", "Automático")
            if len(ps) >= 3:
                timeline = ps.rename(columns={m: "_num"})
                last_period = pd.to_datetime(ps["period"]).max()
                target = last_period + pd.DateOffset(months=3)
                proj = project_metric(timeline, target)
                if proj.get("status") == "ok":
                    r2 = proj.get("r2", 0) or 0
                    # Se informa la confianza en vez de mostrar el número
                    # pelado: un r² bajo significa que la tendencia es
                    # ruidosa, y presentarlo con el mismo peso que una
                    # proyección confiable sería engañoso.
                    confidence = "alta" if r2 >= 0.6 else "media" if r2 >= 0.3 else "baja"
                    st.markdown(section_header("Proyección", compact=True), unsafe_allow_html=True)
                    metric_label = _label(schema, m)
                    # La dirección se dice frente al ÚLTIMO dato real, que es
                    # lo que el gerente tiene en la cabeza. Antes decía «la
                    # tendencia creciente» (la de la recta de 19 meses) y daba
                    # una cifra menor que la del último mes.
                    ultimo = float(ps.iloc[-1][m])
                    cambio = (proj["projected"] - ultimo) / abs(ultimo) * 100 if ultimo else None
                    rumbo = ("" if cambio is None else
                             f", {'por encima' if cambio > 1 else 'por debajo' if cambio < -1 else 'cerca'} "
                             f"de {format_month_year(last_period, full=True).lower()} ({cambio:+.0f}%)")
                    text = (
                        f"A este ritmo, <b>{metric_label}</b> estaría en <b>≈ {_fmt(proj['projected'])}</b> en "
                        f"{format_month_year(target, full=True).lower()}{rumbo}. Confianza {confidence}: "
                        f"sale de la tendencia de {proj['points']} meses. El detalle, en «🔮 Proyección»."
                    )
                    st.markdown(insight_card(text, title="A este ritmo...", kind="info"), unsafe_allow_html=True)

        insights=dashboard.get("insights",[]) if isinstance(dashboard,dict) else []
        if insights:
            st.markdown(section_header("Lectura analítica", compact=True), unsafe_allow_html=True)
            # Primero lo que pide acción (alertas y mejoras); lo informativo
            # («El valor acumulado es…») solo si queda sitio.
            orden = {"warning": 0, "positive": 1}
            for x in sorted(insights, key=lambda i: orden.get(i.get("kind"), 2))[:3]:
                title=clean_display_text(x.get("title") or x.get("label") or "Hallazgo")
                finding=clean_display_text(x.get("finding") or x.get("message") or x.get("text") or x.get("description") or "Sin detalle disponible.")
                action=clean_display_text(x.get("action")) if x.get("action") else None
                st.markdown(insight_card(finding, title=title, kind="info", action=action, action_label="Qué revisar"),unsafe_allow_html=True)

    st.caption(f"{len(df):,} registros visibles · los indicadores se recalculan con la selección actual.")
