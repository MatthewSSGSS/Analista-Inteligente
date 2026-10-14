import streamlit as st
from core.assistant_engine import ask_assistant
from core.marca import NOMBRE_APP
from ui.components.escena import cabecera
from ui.components.section import banner_header


def render_assistant(df, schema, profile, mode_info, dashboard):
    cabecera(f"Asistente de {NOMBRE_APP}", "Pregúntale en tus palabras: compara, busca registros o pide una recomendación.",
             ceja="Asistente IA", icono="🤖", cifras=[(f"{len(df):,}", "registros visibles")], clave="cab_asistente",
             respaldo_html=banner_header(f"Asistente de {NOMBRE_APP}", "Datos visibles · lectura y cálculo.", "ciudad_red.jpg"))

    if "assistant_messages" not in st.session_state:
        st.session_state.assistant_messages = []

    # Clear conversation when the active sheet changes.
    current_key = f"{st.session_state.get('workbook',{}).get('filename','')}::{mode_info.get('label','')}::{len(df)}::{','.join(map(str,df.columns))}"
    if st.session_state.get("assistant_context_key") != current_key:
        st.session_state.assistant_messages = []
        st.session_state.assistant_context_key = current_key

    for m in st.session_state.assistant_messages:
        with st.chat_message("user" if m["role"] == "user" else "assistant"):
            st.markdown(m["content"])

    if not st.session_state.assistant_messages:
        st.markdown('<div class="as-intro"><span class="as-ico">✨</span><div><b>Pregúntale lo que quieras saber de tus datos</b>'
                    '<p>Responde con las cifras de la selección actual: compara grupos, busca registros, explica un cambio o '
                    'propone qué revisar. Empieza con una de estas preguntas o escribe la tuya abajo.</p></div></div>',
                    unsafe_allow_html=True)

    prompts = ["💡 ¿Qué es lo más importante que debería saber de estos datos?",
               "🏆 ¿Dónde está el mejor y el peor resultado?",
               "🎯 ¿Qué debería revisar primero?"]
    # Tres más, armadas con lo que este archivo sí tiene (la causa del cambio,
    # la métrica principal y la dimensión que lo explica).
    g = (dashboard or {}).get("gerencia") if isinstance(dashboard, dict) else None
    if g and g.get("mes_b"):
        verbo = "bajó" if g.get("empeoro") else "subió"
        prompts.append(f"📉 ¿Por qué {g.get('etiqueta') or g.get('metrica')} {verbo} en {g['mes_b']}?")
        dim = (g.get("causas") or {}).get("etiqueta")
        if dim:
            prompts.append(f"🔍 Por {dim}: ¿quién va mejor y quién peor?")
        prompts.append(f"🔮 ¿Cómo cerraría {g.get('etiqueta') or g.get('metrica')} el próximo mes si sigue así?")
    for fila in range(0, len(prompts), 3):
        cols = st.columns(3)
        for j, p in enumerate(prompts[fila:fila + 3]):
            i = fila + j
            if cols[j].button(p, key=f"assistant_suggest_{i}", use_container_width=True):
                st.session_state.assistant_pending = p.split(" ", 1)[1]

    pending = st.session_state.pop("assistant_pending", None)
    question = st.chat_input("Pregunta al asistente…")
    question = question or pending
    if question:
        st.session_state.assistant_messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Analizando los datos visibles…"):
                answer = ask_assistant(
                    question, df, schema, profile, mode_info, dashboard,
                    history=st.session_state.assistant_messages[:-1],
                    api_key=st.session_state.get("assistant_api_key"),
                    model=st.session_state.get("assistant_model", "gpt-5.5"),
                )
            st.markdown(answer)
        st.session_state.assistant_messages.append({"role": "assistant", "content": answer})

    with st.expander("⚙️ Configuración del asistente", expanded=False):
        st.caption("La IA es opcional. Sin API key, el dashboard conserva un modo de consulta local limitado. La clave se mantiene en la sesión de Streamlit y no se escribe en el Excel.")
        st.session_state.assistant_api_key = st.text_input("OpenAI API key", value=st.session_state.get("assistant_api_key", ""), type="password", key="assistant_key_input")
        st.session_state.assistant_model = st.text_input("Modelo", value=st.session_state.get("assistant_model", "gpt-5.5"), key="assistant_model_input")
        if st.button("Limpiar conversación", key="assistant_clear"):
            st.session_state.assistant_messages = []
            st.rerun()
