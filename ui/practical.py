"""Análisis Práctico: sube un Excel, obtén un resumen simple, y pregúntale
lo que quieras en lenguaje natural. Reutiliza el mismo motor de limpieza y
detección semántica que el Análisis Avanzado — la diferencia es la
presentación (mucho más ligera) y la caja de preguntas.
"""
from __future__ import annotations

import streamlit as st
import pandas as pd

from core.loader import load_workbook
from core.dashboard_engine import build_dashboard
from core.dataset_mode import detect_dataset_mode
from core.query_engine import answer_question, suggest_questions
from core.assistant_engine import ask_assistant
from visualization.charts import metric_candidates, dimension_candidates, _label, _base


def _fmt(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    v = float(v)
    a = abs(v)
    if a >= 1_000_000_000:
        return f"{v/1_000_000_000:.1f}B"
    if a >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if a >= 1_000:
        return f"{v/1_000:.1f}K"
    return f"{v:,.0f}"


def _inject_css():
    st.markdown(
        """
        <style>
        @keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
        @keyframes popIn{from{opacity:0;transform:scale(.97)}to{opacity:1;transform:scale(1)}}
        @keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(228,0,43,.18)}50%{box-shadow:0 0 0 8px rgba(228,0,43,0)}}

        .practico-hero{animation:fadeUp .4s ease both}
        .practico-hero .eyebrow{font-size:11px;font-weight:800;letter-spacing:.11em;color:var(--blue);text-transform:uppercase;display:inline-flex;align-items:center;gap:6px}
        .practico-hero h1{margin:6px 0 4px;font-size:25px;font-family:'Sora','Inter',sans-serif;letter-spacing:-.02em;color:var(--text)}
        .practico-hero p{color:var(--muted);font-size:13px;margin:0}

        .practico-section-label{font-size:10.5px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin:18px 0 8px}

        .practico-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:6px 0 4px;animation:fadeUp .45s ease both}
        .practico-kpi{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-md);padding:14px 15px;box-shadow:var(--shadow-sm);transition:box-shadow .15s ease,transform .15s ease}
        .practico-kpi:hover{box-shadow:var(--shadow-md);transform:translateY(-2px)}
        .practico-kpi .label{font-size:10px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.04em}
        .practico-kpi .value{font-size:20px;font-weight:800;margin-top:6px;font-family:'Sora','Inter',sans-serif;color:var(--text)}

        .ask-box{background:linear-gradient(135deg,#ffffff 0%,var(--blue-soft) 130%);border:1px solid var(--line);border-radius:18px;
          padding:20px 22px;margin:18px 0 10px;box-shadow:var(--shadow-lg);animation:fadeUp .5s ease both;position:relative;overflow:hidden}
        .ask-box::before{content:"";position:absolute;top:-30px;right:-30px;width:110px;height:110px;border-radius:50%;
          background:radial-gradient(circle,rgba(228,0,43,.12),transparent 70%)}
        .ask-box h3{margin:0 0 3px;font-size:17px;font-family:'Sora','Inter',sans-serif;display:flex;align-items:center;gap:8px}
        .ask-box p{margin:0 0 12px;font-size:12.5px;color:var(--muted)}

        .practico-suggested{margin:10px 0 4px}
        .practico-suggested-label{font-size:11.5px;color:var(--muted);margin-bottom:8px;font-weight:600}
        div[data-testid="column"] .stButton button{white-space:normal;height:auto;min-height:38px}

        .answer-card{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:var(--radius-lg);
          padding:16px 19px;margin-top:12px;box-shadow:var(--shadow-md);animation:popIn .32s ease both}
        .answer-card.ambiguo{border-left-color:var(--amber);background:var(--amber-soft)}
        .answer-card .tag{font-size:10px;font-weight:800;letter-spacing:.08em;color:var(--blue);text-transform:uppercase;display:flex;align-items:center;gap:6px}
        .answer-card.ambiguo .tag{color:var(--amber-strong)}
        .answer-card .q{color:var(--muted);font-weight:600;font-size:11px;text-transform:none;letter-spacing:0}
        .answer-card .text{font-size:15.5px;margin-top:8px;line-height:1.55;color:var(--text);font-weight:500}

        .practico-upload-zone{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-lg);padding:4px;box-shadow:var(--shadow-sm);animation:fadeUp .42s ease both}
        .practico-cta{margin-top:26px;padding-top:18px;border-top:1px solid var(--line)}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_practical_page():
    _inject_css()

    top_l, top_r = st.columns([5, 1])
    with top_l:
        st.markdown(
            '<div class="practico-hero"><span class="eyebrow">⚡ ANÁLISIS PRÁCTICO</span>'
            '<h1>Sube tu Excel y pregúntale lo que quieras</h1>'
            '<p>Resumen rápido + respuestas en tus propias palabras, con datos reales — nunca inventadas.</p></div>',
            unsafe_allow_html=True,
        )
    with top_r:
        st.write("")
        if st.button("🧭 Ir a Avanzado", use_container_width=True):
            st.session_state.analysis_mode = "avanzado"
            st.rerun()

    st.markdown('<div class="practico-upload-zone">', unsafe_allow_html=True)
    upload = st.file_uploader(
        "Cargar Excel / CSV", type=["xlsx", "xls", "xlsb", "xlsm", "csv"],
        key="practico_upload", label_visibility="collapsed",
    )
    st.markdown('</div>', unsafe_allow_html=True)

    with st.expander("⚙️ Conectar IA (opcional) — para responder preguntas más difíciles", expanded=False):
        st.caption(
            "El motor normal ya responde la mayoría de preguntas sin esto. Conecta una API de IA solo si "
            "quieres que también entienda preguntas mal formuladas o poco comunes — nunca inventa números, "
            "la IA solo decide qué calcular; el cálculo real siempre sale de tus datos."
        )
        # Los widgets con `key` ignoran el parámetro value= después del
        # primer render (usan lo que ya está guardado en session_state para
        # esa key) — por eso el valor por defecto se siembra UNA sola vez,
        # antes de crear el widget, en vez de intentar "sincronizarlo" en
        # cada ejecución (eso nunca sobrescribe un valor ya guardado).
        if "practico_api_key_input" not in st.session_state:
            st.session_state["practico_api_key_input"] = st.session_state.get("assistant_api_key", "")
        st.session_state.practico_api_key = st.text_input("OpenAI API key", type="password", key="practico_api_key_input")
        if "practico_model_input" not in st.session_state:
            st.session_state["practico_model_input"] = st.session_state.get("assistant_model", "gpt-5.5")
        st.session_state.practico_model = st.text_input("Modelo", key="practico_model_input")

    if upload and st.button("Analizar archivo", type="primary", use_container_width=True, key="practico_analyze_btn"):
        with st.spinner("Leyendo, limpiando y detectando la estructura del archivo..."):
            try:
                st.session_state.practico_workbook = load_workbook(upload)
                st.session_state.practico_sheet = list(st.session_state.practico_workbook["sheets"].keys())[0]
                st.session_state.practico_chat = []
            except Exception as e:
                st.error(f"No pudimos procesar este archivo: {e}")

    wb = st.session_state.get("practico_workbook")
    if not wb:
        st.info("Sube un Excel o CSV arriba para empezar.")
        return

    sheets = list(wb["sheets"].keys())
    if len(sheets) > 1:
        st.session_state.practico_sheet = st.selectbox("Hoja", sheets, index=sheets.index(st.session_state.get("practico_sheet", sheets[0])))
    sheet = st.session_state.get("practico_sheet", sheets[0])
    item = wb["sheets"][sheet]
    df = item["processed"]
    schema = item["profile"]["schema"]

    # --- Resumen simple: mucho más ligero que el dashboard avanzado ---
    metrics = metric_candidates(df, schema)
    dims = dimension_candidates(df, schema)
    st.markdown('<div class="practico-section-label">Resumen rápido</div>', unsafe_allow_html=True)
    kpi_cards = [f'<div class="practico-kpi"><div class="label">Registros</div><div class="value">{len(df):,}</div></div>']
    for m in metrics[:3]:
        s = pd.to_numeric(df[m], errors="coerce").dropna()
        if len(s):
            kpi_cards.append(f'<div class="practico-kpi"><div class="label">{_label(schema, m)}</div><div class="value">{_fmt(s.sum())}</div></div>')
    st.markdown(f'<div class="practico-kpis">{"".join(kpi_cards)}</div>', unsafe_allow_html=True)
    st.caption(f"{len(df):,} registros · {len(df.columns)} columnas" + (f" · {len(dims)} categorías detectadas" if dims else ""))

    with st.expander("📄 Ver los datos", expanded=False):
        st.dataframe(df, use_container_width=True, hide_index=True)

    # --- Caja de preguntas ---
    st.markdown('<div class="ask-box"><h3>💬 ¿Qué quieres saber?</h3><p>Escribe tu pregunta como se la harías a un compañero de trabajo — no hace falta que esté perfecta.</p>', unsafe_allow_html=True)
    question = st.text_input("Pregunta", placeholder="Ej.: ¿Quién tiene el mayor valor? ¿Cómo evolucionó el total?", label_visibility="collapsed", key="practico_question")
    ask_col, _ = st.columns([1, 3])
    asked = ask_col.button("Preguntar →", type="primary", use_container_width=True, key="practico_ask_btn")
    st.markdown("</div>", unsafe_allow_html=True)

    suggestions = suggest_questions(df, schema)
    if suggestions:
        st.markdown('<div class="practico-suggested"><div class="practico-suggested-label">💡 Preguntas sugeridas para este archivo</div></div>', unsafe_allow_html=True)
        cols = st.columns(len(suggestions))
        for i, sq in enumerate(suggestions):
            if cols[i].button(sq, key=f"sugg_{i}", use_container_width=True):
                question = sq
                asked = True

    if asked and question:
        with st.spinner("Buscando la respuesta en tus datos..."):
            result = answer_question(df, schema, question)
            used_ai = False
            if result["status"] != "ok" and st.session_state.get("practico_api_key"):
                # Segunda capa: el motor de reglas no encontró una respuesta
                # segura, así que se le pasa la pregunta a la IA — pero la IA
                # solo decide QUÉ calcular (usando las mismas herramientas de
                # solo lectura), nunca inventa el número directamente.
                mode_info = detect_dataset_mode(df, schema)
                ai_text = ask_assistant(
                    question, df, schema, item["profile"], mode_info,
                    dashboard=None, history=None,
                    api_key=st.session_state.get("practico_api_key"),
                    model=st.session_state.get("practico_model", "gpt-5.5"),
                )
                result = {"status": "ok", "answer": ai_text, "detail": {"source": "ia"}, "chart_spec": None, "table": None}
                used_ai = True
        st.session_state.setdefault("practico_chat", [])
        st.session_state.practico_chat.insert(0, {"q": question, "r": result, "ai": used_ai})

    for entry in st.session_state.get("practico_chat", [])[:6]:
        q, r = entry["q"], entry["r"]
        status_tag = {"ok": "✅ Respuesta", "ambiguo": "🤔 No estoy seguro", "sin_datos": "⚠️ Sin datos suficientes"}.get(r["status"], "Respuesta")
        if entry.get("ai"):
            status_tag = "🤖 Respuesta (con IA)"
        css_class = "ambiguo" if r["status"] != "ok" else ""
        st.markdown(
            f'<div class="answer-card {css_class}"><div class="tag">{status_tag}<span class="q">· "{q}"</span></div><div class="text">{r["answer"]}</div></div>',
            unsafe_allow_html=True,
        )
        chart_spec = r.get("chart_spec")
        if chart_spec:
            import plotly.graph_objects as go
            if chart_spec["type"] == "trend":
                fig = go.Figure(go.Scatter(x=chart_spec["x"], y=chart_spec["y"], mode="lines+markers", line=dict(color="#e4002b", width=3), marker=dict(color="#e4002b", size=8)))
            else:
                fig = go.Figure(go.Bar(x=chart_spec["x"], y=chart_spec["y"], marker_color="#e4002b"))
            fig.update_yaxes(title=chart_spec.get("metric_label"))
            fig = _base(fig, height=300, show_xgrid=False)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        table = r.get("table")
        if isinstance(table, pd.DataFrame) and not table.empty:
            with st.expander("Ver detalle en tabla", expanded=False):
                st.dataframe(table, use_container_width=True, hide_index=True)

    st.markdown('<div class="practico-cta">', unsafe_allow_html=True)
    st.markdown("#### ¿Necesitas ir más a fondo?")
    if st.button("📊 Generar dashboard completo con este mismo archivo", use_container_width=True):
        st.session_state.workbook = wb
        st.session_state.active_sheet = sheet
        st.session_state.filters = {}
        st.session_state.analysis_mode = "avanzado"
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
