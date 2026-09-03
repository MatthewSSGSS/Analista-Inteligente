import streamlit as st
from core.assistant_engine import ask_assistant
from ui.components.section import banner_header


def render_assistant(df, schema, profile, mode_info, dashboard):
    st.markdown(banner_header("Asistente de Excel Intelligence", "Datos visibles · lectura y cálculo.", "ciudad_red.jpg"), unsafe_allow_html=True)
    st.caption("Pregunta sobre lo que está ocurriendo, compara segmentos, busca registros o pide una recomendación. El asistente trabaja sobre la selección actual.")

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

    prompts = [
        "¿Qué es lo más importante que debería saber de estos datos?",
        "¿Dónde está el mejor y el peor resultado?",
        "¿Qué debería revisar primero?",
    ]
    cols = st.columns(3)
    for i, p in enumerate(prompts):
        if cols[i].button(p, key=f"assistant_suggest_{i}", use_container_width=True):
            st.session_state.assistant_pending = p

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
