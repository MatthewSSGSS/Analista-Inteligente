"""Pantalla de login: usuario y contraseña, antes de cualquier otra cosa."""
from __future__ import annotations
import streamlit as st

import core.auth_engine as auth_engine


def render_login():
    st.markdown(
        """
        <style>
        @keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
        .login-wrap{max-width:400px;margin:8vh auto 0;padding:0 16px;animation:fadeUp .45s ease both}
        .login-mark{width:56px;height:56px;border-radius:50%;margin:0 auto 18px;
          background:radial-gradient(circle at 32% 28%,#ff4d4d,#e4002b 55%,#a80e1f 100%);
          box-shadow:inset 0 -4px 8px rgba(0,0,0,.22),inset 0 3px 4px rgba(255,255,255,.35),0 10px 24px rgba(228,0,43,.22)}
        .login-hero{text-align:center;margin-bottom:22px}
        .login-hero h1{font-size:21px;font-weight:800;font-family:'Sora','Inter',sans-serif;letter-spacing:-.02em;margin:0 0 6px;color:var(--text)}
        .login-hero p{font-size:12.5px;color:var(--muted);margin:0}
        .login-card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-lg);
          padding:26px 26px 22px;box-shadow:var(--shadow-lg)}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="login-wrap"><div class="login-mark" style="display:flex;align-items:center;justify-content:center;font-size:24px;">🔒</div>'
        '<div class="login-hero"><h1>Panel Analítico Universal</h1>'
        '<p>Inicia sesión para continuar</p></div></div>',
        unsafe_allow_html=True,
    )

    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown('<div class="login-card">', unsafe_allow_html=True)
        tab_login, tab_signup = st.tabs(["Iniciar sesión", "Crear cuenta"])

        with tab_login:
            username = st.text_input("Usuario", key="login_username")
            password = st.text_input("Contraseña", type="password", key="login_password")
            if st.button("Entrar →", type="primary", use_container_width=True, key="login_submit"):
                if not username or not password:
                    st.warning("Escribe tu usuario y tu contraseña.")
                else:
                    ok, msg = auth_engine.authenticate(username, password)
                    if ok:
                        st.rerun()
                    else:
                        st.error(msg)

        with tab_signup:
            st.caption("Crea tu cuenta para entrar al Panel Analítico de tu equipo.")
            new_name = st.text_input("Tu nombre (opcional)", key="signup_name")
            new_username = st.text_input("Elige un usuario", key="signup_username", help="Solo letras, números, puntos y guiones. Sin espacios.")
            new_password = st.text_input("Elige una contraseña", type="password", key="signup_password")
            new_password2 = st.text_input("Repite la contraseña", type="password", key="signup_password2")
            if st.button("Crear cuenta →", use_container_width=True, key="signup_submit"):
                if not new_username or not new_password:
                    st.warning("Completa usuario y contraseña.")
                elif new_password != new_password2:
                    st.error("Las contraseñas no coinciden.")
                else:
                    ok, msg = auth_engine.create_user(new_username, new_password, new_name)
                    if ok:
                        st.success(msg + " Ya puedes iniciar sesión en la otra pestaña.")
                    else:
                        st.error(msg)
        st.markdown('</div>', unsafe_allow_html=True)
