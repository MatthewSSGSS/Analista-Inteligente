from __future__ import annotations

import re
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.numeric import numeric_series
from core.cross_sheet import encontrar_hojas_relacionadas, datos_de_entidad, resumir_filas
from core.entity_engine import analyze_entity_candidates, describe_entity
from core.universal_analysis import semantic_map, ADDITIVE, period_series
from visualization.charts import metric_candidates, dimension_candidates, _label, chart_text_color
from ui.components.cards import kpi_card
from ui.components.charts import chart_card
from ui.components.section import section_header
from ui.layouts.columns import two_column


def _fmt(v):
    if v is None or pd.isna(v):
        return "—"
    try:
        x = float(v)
    except Exception:
        return str(v)
    ax = abs(x)
    if ax >= 1e9: return f"{x/1e9:.2f}B"
    if ax >= 1e6: return f"{x/1e6:.2f}M"
    if ax >= 1e3: return f"{x/1e3:.1f}K"
    return f"{x:,.0f}"


def _person_col(schema, df):
    full = schema.get("full_name", {}) if isinstance(schema.get("full_name"), dict) else {}
    c = full.get("column")
    if c in df.columns:
        return c
    sem = semantic_map(schema)
    for c, t in sem.items():
        if c in df.columns and t in {"employee", "customer", "person", "name"}:
            return c
    norm = {re.sub(r"[^a-z0-9]+", "", str(c).casefold()): c for c in df.columns}
    for alias in ("nombrecompleto", "nombre", "name", "agente", "asesor", "vendedor", "empleado", "cliente"):
        if alias in norm:
            return norm[alias]
    return None


def _entity_candidates(df, schema):
    """Candidatas a entidad, calculadas UNA vez por hoja y guardadas en la
    sesión. El análisis recorre todas las columnas comparándolas entre sí
    (~1s en 60.000 filas): barato una vez, caro si se repitiera en cada
    rerun de Streamlit — y Streamlit vuelve a ejecutar el script entero
    ante cualquier clic o cambio de filtro. La clave incluye las columnas
    para que al cambiar de hoja se recalcule, pero no al filtrar: qué
    columna identifica a la entidad es una propiedad de la TABLA, no de la
    selección visible."""
    key = (st.session_state.get("active_sheet"), tuple(str(c) for c in df.columns))
    cache = st.session_state.setdefault("_entity_candidates_cache", {})
    if key not in cache:
        cache[key] = analyze_entity_candidates(df, schema)
    return cache[key]


def resolve_entity(df, schema):
    """Sobre qué "sujeto" se puede armar un perfil en este archivo.

    Primero busca una persona (comportamiento de siempre, intacto). Si no
    hay, cae al detector universal de códigos (core/entity_engine.py), que
    reconoce identificadores por la FORMA de sus valores y por las columnas
    que determinan, sin depender de cómo se llame la columna.

    Devuelve None si el archivo no tiene ningún sujeto perfilable — mejor
    no ofrecer el perfil que armarlo sobre la columna equivocada.
    """
    person = _person_col(schema, df)
    if person:
        return {"column": person, "noun": "persona", "icon": "👤", "candidates": [], "detected": None}
    candidates = [c for c in _entity_candidates(df, schema) if c["column"] in df.columns]
    chosen = candidates[0] if candidates else None
    if chosen and chosen["score"] >= 0.50:
        return {"column": chosen["column"], "noun": "código", "icon": "🔖",
                "candidates": candidates, "detected": chosen}

    # Sin una entidad estricta todavía hay algo a lo que hacer seguimiento: la
    # unidad de negocio del archivo. Un punto de venta que se repite en 200
    # filas no es un "identificador" —no identifica a la fila— pero sí es
    # exactamente lo que alguien quiere seguir. Con el criterio anterior, el
    # archivo del que más se pregunta "¿cómo va este punto?" era justo el que
    # se quedaba sin la herramienta.
    from core.diagnostics import dimension_operativa

    try:
        unidad = dimension_operativa(df, schema)
    except Exception:
        unidad = None
    if unidad and unidad in df.columns:
        return {"column": unidad, "noun": "grupo", "icon": "🔎",
                "candidates": candidates, "detected": None}
    return None


def has_entity(df, schema) -> bool:
    """Si conviene ofrecer el botón de perfil. Lo usan el dashboard y el
    resumen ejecutivo para decidir si mostrarlo — antes preguntaban solo
    por una columna de nombre, así que con un archivo de códigos el botón
    nunca aparecía."""
    try:
        return resolve_entity(df, schema) is not None
    except Exception:
        return False


def _relaciones_entre_hojas(columna_clave: str):
    """Hojas del libro que hablan de la misma entidad, calculadas UNA vez
    por hoja+columna y guardadas en la sesión.

    Se cachea por el mismo motivo que las candidatas a entidad: comparar los
    valores de todas las columnas de todas las hojas es caro, y Streamlit
    reejecuta el script entero ante cualquier clic o cambio de filtro."""
    workbook = st.session_state.get("workbook")
    hoja = st.session_state.get("active_sheet")
    if not workbook or not hoja:
        return []
    clave = (hoja, columna_clave, tuple(sorted((workbook.get("sheets") or {}).keys())))
    cache = st.session_state.setdefault("_cross_sheet_cache", {})
    if clave not in cache:
        try:
            cache[clave] = encontrar_hojas_relacionadas(workbook, hoja, columna_clave)
        except Exception:
            cache[clave] = []
    return cache[clave]


def _render_otras_hojas(columna_clave: str, valor, noun: str) -> None:
    """Qué dicen las OTRAS hojas del libro sobre este mismo código.

    Es la pregunta que quedaba sin responder: el perfil mostraba todo lo que
    sabía la hoja actual, pero si el mismo código aparecía en otra hoja
    —el maestro de locales, el de responsables, un histórico— esa
    información no se veía por ningún lado, aunque estuviera en el mismo
    archivo. El emparejamiento es por valores (ver core/cross_sheet.py), así
    que funciona aunque cada hoja llame distinto a su columna de código.
    """
    relaciones = _relaciones_entre_hojas(columna_clave)
    if not relaciones:
        return
    workbook = st.session_state.get("workbook")
    st.markdown(
        section_header(
            f"En otras hojas del archivo",
            eyebrow="INFORMACIÓN RELACIONADA",
            subtitle=f"Lo que el resto del libro sabe sobre este {noun}, cruzado por su valor.",
            compact=True,
        ),
        unsafe_allow_html=True,
    )
    for rel in relaciones:
        filas = datos_de_entidad(workbook, rel, valor)
        cabecera = (f"**{rel['hoja']}** · vinculada por `{rel['columna']}` "
                    f"({rel['coincidencia'] * 100:.0f}% de coincidencia)")
        if filas.empty:
            st.markdown(f"{cabecera} — sin registros para este {noun}.")
            continue
        st.markdown(f"{cabecera} · {len(filas):,} registro(s)")
        ficha = resumir_filas(filas, rel["columna"])
        if ficha:
            st.dataframe(pd.DataFrame(ficha), use_container_width=True, hide_index=True)
        if len(filas) > 1:
            with st.expander(f"Ver los {len(filas):,} registros de {rel['hoja']}", expanded=False):
                st.dataframe(filas.head(300), use_container_width=True, hide_index=True)


def _card(label, value, delta=None):
    return kpi_card(label, value, delta=delta)


def _chart(title, subtitle, fig, key):
    chart_card(title, subtitle, fig, key=key, visual_type="PERFIL", badge_text="Datos del seleccionado")


def _apply_current_filters(df):
    out = df.copy()
    filters = st.session_state.get("filters", {}) or {}
    date_rule = filters.get("__date__")
    if isinstance(date_rule, dict) and date_rule.get("column") in out.columns:
        d = date_rule["column"]
        out[d] = pd.to_datetime(out[d], errors="coerce")
        out = out[(out[d] >= date_rule.get("start")) & (out[d] <= date_rule.get("end"))]
    # Mismo motor que el panel. Antes aquí solo se entendían "in" y "equals":
    # un filtro por rango o por texto se ignoraba en silencio, y el
    # seguimiento mostraba filas que el resto del panel ya había dejado fuera.
    from core.filter_engine import apply_filters

    reglas = {c: r for c, r in filters.items() if not str(c).startswith("__") and isinstance(r, dict)}
    return apply_filters(out, reglas) if reglas else out


def _observaciones(data, schema, person_col, selected, primary):
    """Alertas y lecturas de este registro, comparadas contra sus pares."""
    from core.seguimiento import observaciones
    from ui.components.cards import insight_card

    try:
        hallazgos = observaciones(data, schema, person_col, selected, primary)
    except Exception:
        hallazgos = []
    if not hallazgos:
        return
    st.markdown(section_header(
        "Alertas y observaciones",
        subtitle="Cada lectura está comparada contra el resto del grupo, contra la meta o contra su propio pasado.",
        compact=True), unsafe_allow_html=True)
    columnas = st.columns(2)
    for i, hallazgo in enumerate(hallazgos[:6]):
        tipo = hallazgo.get("kind", "info")
        icono = "▲" if tipo == "positive" else "!" if tipo == "warning" else "i"
        columnas[i % 2].markdown(
            insight_card(hallazgo.get("finding", ""), title=hallazgo.get("title", ""),
                         kind=tipo, icon=icono, action=hallazgo.get("action"),
                         compact=True, evidence=hallazgo.get("evidence")),
            unsafe_allow_html=True)


def render_person_profile(df, schema, dashboard=None):
    """Perfil universal de UNA entidad: todo lo que el archivo puede decir
    legítimamente sobre ella. La entidad es una persona cuando el archivo
    tiene nombres, o un código (de local, de punto, de funcionario...)
    cuando no — ver resolve_entity()."""
    entity = resolve_entity(df, schema)
    if not entity:
        st.info("Este Excel no contiene una persona ni un código identificable para construir un perfil individual.")
        return
    person_col, noun = entity["column"], entity["noun"]

    # Si hay varias columnas que podrían ser la entidad (p. ej. código de
    # local y cédula), se deja cambiar: la detección acierta sola en la
    # mayoría de los casos, pero cuando no, el usuario corrige en un clic
    # en vez de quedarse sin la herramienta.
    candidates = entity.get("candidates") or []
    if len(candidates) > 1:
        options = [c["column"] for c in candidates]
        picked = st.selectbox(
            "Analizar por", options, index=0, key="profile_entity_column_v54",
            help="Columna que identifica al sujeto del análisis. Se eligió automáticamente por el formato de sus valores y por las columnas que describe.",
        )
        if picked != person_col:
            person_col = picked
        entity["detected"] = next((c for c in candidates if c["column"] == person_col), entity.get("detected"))

    data = _apply_current_filters(df)
    if person_col not in data.columns:
        st.info("La columna seleccionada no está disponible con los filtros actuales.")
        return
    names = sorted(data[person_col].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique(), key=str.casefold)
    if not names:
        st.info(f"No hay valores de {noun} disponibles con los filtros actuales.")
        return

    subtitle = ("Selecciona una persona y revisa todo lo que el Excel permite conocer sobre ella."
                if noun == "persona" else
                f"Selecciona un {noun} y revisa todo lo que el Excel permite conocer sobre él, "
                f"con sus alertas y su comparación contra el resto.")
    st.markdown(section_header("Análisis de seguimiento", eyebrow="SEGUIMIENTO", subtitle=subtitle), unsafe_allow_html=True)

    # Cuando la entidad se dedujo de los datos (no es un nombre evidente),
    # se explica en qué se basó: nadie debería preguntarse de dónde salió
    # que "Ref" es el código del archivo.
    detected = entity.get("detected")
    if detected:
        st.caption("Entidad detectada automáticamente · " + describe_entity(detected).replace("**", ""))

    selected = st.selectbox(
        f"Buscar y seleccionar {'nombre completo' if noun == 'persona' else noun}",
        names, key="profile_person_selector_inline", placeholder="Escribe para buscar…",
    )
    rows = data[data[person_col].astype(str).str.strip().eq(str(selected).strip())].copy()
    if rows.empty:
        return

    sem = semantic_map(schema)
    # Qué métricas existen se decide con el archivo completo (respetando los
    # filtros globales), no con el subconjunto de esta persona: si alguien
    # tiene pocos registros, sus valores podrían parecer un código/ID por
    # casualidad y ocultar una métrica que sí es válida para todos los demás.
    metrics = [m for m in metric_candidates(data, schema) if m in rows.columns]
    primary = metrics[0] if metrics else None
    preferred = [m for m in metrics if sem.get(m) in {"revenue", "profit", "quantity", "sales", "price", "rating"}]
    if preferred:
        primary = preferred[0]

    st.markdown(f'<div class="decision-strip positive"><b>{selected}</b> · {len(rows):,} registros relacionados encontrados. Todo el análisis de esta pestaña está restringido a este registro.</div>', unsafe_allow_html=True)

    # 0. La lectura antes que los números. El perfil mostraba gráficos y
    # dejaba la interpretación al ojo de quien miraba; esto dice si el caso
    # va bien o mal y contra qué se le está midiendo, que es lo primero que
    # alguien quiere saber al abrir un seguimiento.
    _observaciones(data, schema, person_col, selected, primary)

    # 1. KPI layer
    st.markdown(section_header("KPIs", compact=True), unsafe_allow_html=True)
    kpis = [{"label": "Registros relacionados", "value": f"{len(rows):,}"}]
    if primary:
        s = numeric_series(rows[primary]).dropna()
        additive = sem.get(primary) in ADDITIVE
        val = float(s.sum()) if additive else float(s.mean()) if len(s) else None
        kpis.append({"label": "Total" if additive else "Promedio", "value": _fmt(val)})
        kpis.append({"label": "Máximo", "value": _fmt(s.max()) if len(s) else "—"})
        # Mínimo, no un "Promedio" repetido: cuando la métrica principal no es
        # aditiva (precio, calificación, edad...), la 2ª tarjeta ya muestra el
        # promedio — mostrarlo otra vez en la 4ª no aportaba nada nuevo.
        kpis.append({"label": "Mínimo", "value": _fmt(s.min()) if len(s) else "—"})
    cols = st.columns(min(4, len(kpis)))
    for i, k in enumerate(kpis[:4]):
        with cols[i]: st.markdown(_card(k["label"], k["value"]), unsafe_allow_html=True)

    # 2. Temporal performance
    date_cols = [d for d in schema.get("dates", []) if d in rows.columns]
    if primary and date_cols:
        st.markdown(section_header("Evolución", compact=True), unsafe_allow_html=True)
        ps = period_series(rows, schema, primary, "Mes", "Automático")
        if len(ps) >= 2:
            prev, cur = float(ps.iloc[-2][primary]), float(ps.iloc[-1][primary])
            pct = ((cur-prev)/abs(prev)*100) if prev else None
            tone = "positive" if pct is not None and pct >= 0 else "negative"
            text = f"{selected} {'mejoró' if tone == 'positive' else 'empeoró'} {abs(pct):.1f}% en el último periodo." if pct is not None else "Hay varios periodos disponibles para analizar la evolución."
            st.markdown(f'<div class="decision-strip {tone}"><b>Lectura principal:</b> {text}</div>', unsafe_allow_html=True)
            fig = go.Figure(go.Scatter(
                x=ps["period"], y=ps[primary], mode="lines+markers", name=selected,
                line=dict(color="#E4002B", width=3.5), marker=dict(size=8),
                hovertemplate="<b>%{x|%b %Y}</b><br>" + _label(schema, primary) + ": <b>%{y:,.0f}</b><extra></extra>",
            ))
            fig.update_layout(height=380, margin=dict(l=15,r=15,t=20,b=25), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=chart_text_color()))
            fig.update_xaxes(showgrid=False); fig.update_yaxes(showgrid=True, gridcolor="rgba(96,112,132,.16)", title=_label(schema, primary))
            _chart("Evolución de la persona", f"Cómo ha cambiado {_label(schema, primary).lower()} por periodo", fig, "profile_person_trend_v52")

    # 3-4. Características: qué explica el resultado + cómo se compara con
    # el resto. Antes eran dos secciones apiladas siempre a todo el ancho;
    # ahora, cuando ambas tienen datos, se muestran una junto a la otra
    # (two_column) para no alargar la página con dos gráficos de ancho
    # completo que responden preguntas relacionadas.
    dim_candidates = []
    priorities = {"product": 0, "category": 1, "channel": 2, "brand": 3, "segment": 4, "city": 5, "region": 6, "status": 7}
    for c, t in sem.items():
        if c in rows.columns and c != person_col and t in priorities:
            n = rows[c].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()
            if 1 < n <= 30: dim_candidates.append((priorities[t], c))
    dim_candidates = [c for _, c in sorted(dim_candidates)]

    mix_fig = mix_title = mix_subtitle = mix_lead = None
    if dim_candidates:
        dim = dim_candidates[0]
        z = rows[[dim] + ([primary] if primary else [])].copy()
        z[dim] = z[dim].fillna("Sin dato").astype(str).str.strip().replace("", "Sin dato")
        if primary:
            z[primary] = numeric_series(z[primary])
            z = z.dropna(subset=[primary])
            agg = z.groupby(dim)[primary].sum() if sem.get(primary) in ADDITIVE else z.groupby(dim)[primary].mean()
            top = agg.sort_values(ascending=False).head(10).reset_index(name=primary)
            if not top.empty:
                mix_lead = f'**{_label(schema, dim)} que más explica el resultado:** {top.iloc[0][dim]} · {_fmt(top.iloc[0][primary])}'
                fig = px.bar(top.sort_values(primary), x=primary, y=dim, orientation="h", text_auto=".3s")
                fig.update_traces(marker_color="#0FA8A0", marker_line_width=0)
                fig.update_layout(height=max(330, 34*len(top)+90), margin=dict(l=10,r=20,t=15,b=15), showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=chart_text_color()))
                fig.update_xaxes(showgrid=True, gridcolor="rgba(96,112,132,.16)"); fig.update_yaxes(showgrid=False)
                mix_fig = fig
                mix_title = f"Desglose por {_label(schema, dim)}"
                mix_subtitle = "Qué productos, categorías, canales u otras dimensiones mueven el resultado"

    bench_fig = None
    if primary:
        s_person = numeric_series(rows[primary]).dropna()
        s_all = numeric_series(data[primary]).dropna()
        if len(s_person) and len(s_all):
            additive = sem.get(primary) in ADDITIVE
            person_value = float(s_person.sum()) if additive else float(s_person.mean())
            global_value = float(s_all.mean())
            comp = pd.DataFrame({"Referencia": [selected, "Promedio visible"], "Valor": [person_value, global_value]})
            fig = px.bar(comp, x="Referencia", y="Valor", color="Referencia", text_auto=".3s", color_discrete_sequence=["#E4002B", "#94A3B8"])
            fig.update_layout(height=320, margin=dict(l=10,r=10,t=15,b=20), showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=chart_text_color()))
            fig.update_yaxes(showgrid=True, gridcolor="rgba(96,112,132,.16)")
            bench_fig = fig

    bench_title = "Persona vs. promedio visible"
    bench_subtitle = "Permite saber rápidamente si el resultado está por encima o por debajo del contexto"
    if mix_fig is not None or bench_fig is not None:
        st.markdown(section_header("Características", compact=True), unsafe_allow_html=True)
        if mix_fig is not None and bench_fig is not None:
            main_col, side_col = two_column(1.4, 1)
            with main_col:
                if mix_lead: st.markdown(mix_lead)
                _chart(mix_title, mix_subtitle, mix_fig, "profile_person_mix_v52")
            with side_col:
                _chart(bench_title, bench_subtitle, bench_fig, "profile_person_benchmark_v52")
        elif mix_fig is not None:
            if mix_lead: st.markdown(mix_lead)
            _chart(mix_title, mix_subtitle, mix_fig, "profile_person_mix_v52")
        else:
            _chart(bench_title, bench_subtitle, bench_fig, "profile_person_benchmark_v52")

    # 5. Everything else the workbook knows: compact metadata + raw records
    st.markdown(section_header(f"Todo lo relacionado con {'la persona' if noun == 'persona' else 'el ' + noun}", eyebrow="CONTEXTO COMPLETO", compact=True), unsafe_allow_html=True)
    context_rows = []
    for c in rows.columns:
        if str(c).startswith("__") or str(c).startswith("_geo_") or c == person_col:
            continue
        s = rows[c]
        if c in schema.get("dates", []):
            dt = pd.to_datetime(s, errors="coerce").dropna()
            value = f"{dt.min().strftime('%d/%m/%Y')} → {dt.max().strftime('%d/%m/%Y')}" if len(dt) else "Sin fecha válida"
        elif c in metrics:
            ns = numeric_series(s).dropna()
            value = f"min {_fmt(ns.min())} · promedio {_fmt(ns.mean())} · max {_fmt(ns.max())}" if len(ns) else "Sin valor numérico válido"
        else:
            vals = s.dropna().astype(str).str.strip().replace("", pd.NA).dropna().drop_duplicates().tolist()
            value = ", ".join(vals[:8]) if vals else "Sin dato"
            if len(vals) > 8: value += f" · +{len(vals)-8} más"
        context_rows.append({"Campo": _label(schema, c), "Información encontrada": value})
    if context_rows:
        st.dataframe(pd.DataFrame(context_rows), use_container_width=True, hide_index=True)

    _render_otras_hojas(person_col, selected, noun)

    with st.expander("Ver registros originales relacionados", expanded=False):
        visible = [c for c in rows.columns if not str(c).startswith("__") and not str(c).startswith("_geo_")]
        st.dataframe(rows[visible].head(500), use_container_width=True, hide_index=True)
        if len(rows) > 500:
            st.caption(f"Mostrando 500 de {len(rows):,} registros relacionados.")
