"""Pantalla de login: usuario y contraseña, antes de cualquier otra cosa."""
from __future__ import annotations
import streamlit as st

import core.auth_engine as auth_engine
from core.marca import NOMBRE_APP
from ui.components.escena import NO_DISPONIBLE, escena

# ─────────────────────────────────────────────────────────────────────────
# INTERRUPTOR TEMPORAL: mientras la conexión a la base de datos esté rota
# (el error NoSuchModuleError), validar la contraseña de verdad haría
# tronar la app en cada intento de entrar. Con esto en True, el botón
# "Entrar" deja pasar sin comprobar nada contra la base de datos — el
# diseño y el flujo de "Crear cuenta" quedan intactos para cuando se
# arregle la conexión.
#
# Para volver a exigir usuario/contraseña reales: cambia esto a False.
# ─────────────────────────────────────────────────────────────────────────
BYPASS_AUTH_TEMPORARY = True


def render_login():
    # Pantalla completa oscura con la red de datos animada (ui/web/acceso.*
    # pone el canvas fijo detrás de la app) y el formulario en una tarjeta de
    # vidrio encima. Antes la animación vivía en un recuadro suelto sobre
    # fondo crema y se veía desordenado. Sin foto: la que había (una oficina
    # con la marca de una empresa) ataba la app a una compañía. Los campos
    # siguen siendo de Streamlit: la contraseña va directo a Python.
    style_block = """
        <style>
        @keyframes fadeUp{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}

        [data-testid="stApp"]{
          background:
            radial-gradient(1100px 620px at 88% -8%, rgba(228,0,43,.30), transparent 60%),
            radial-gradient(900px 640px at -6% 108%, rgba(15,168,160,.22), transparent 58%),
            linear-gradient(160deg,#080b13 0%,#0c1120 55%,#080a12 100%) !important;
          background-attachment: fixed !important;
        }
        html,body{background:#080b13!important}
        /* Transparentes y por encima del canvas del fondo. */
        [data-testid="stAppViewContainer"]{position:relative;z-index:1;background:transparent!important}
        [data-testid="stMain"],[data-testid="stHeader"]{background:transparent!important}
        [data-testid="stHeader"] *{color:#cfd5e2!important}

        .login-wrap{max-width:440px;margin:9vh auto 26px;padding:0 16px;animation:fadeUp .45s ease both;text-align:center}
        .login-wordmark{font-family:'Sora','Inter',sans-serif;font-weight:800;font-size:34px;color:#fff;
          letter-spacing:-.03em;line-height:1;margin:0 0 12px;display:inline-block}
        .login-hero p{font-size:13.5px;color:#b9c0cf;margin:0}

        /* La tarjeta de vidrio con el formulario. */
        .st-key-acceso_tarjeta{background:rgba(15,20,33,.72)!important;border:1px solid rgba(255,255,255,.10)!important;
          border-radius:24px!important;padding:24px 26px 26px!important;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
          box-shadow:0 30px 70px rgba(0,0,0,.45),inset 0 1px 0 rgba(255,255,255,.06)!important;animation:fadeUp .55s ease .15s both}
        .st-key-acceso_tarjeta label p,.st-key-acceso_tarjeta label{color:#dfe4ee!important;font-weight:650!important;font-size:12.5px!important}
        /* El tema pone etiquetas y notas sobre «píldoras» blancas: aquí, transparentes. */
        .st-key-acceso_tarjeta [data-testid="stWidgetLabel"],.st-key-acceso_tarjeta [data-testid="stCaptionContainer"]{
          background:transparent!important;border:none!important;box-shadow:none!important;padding-left:0!important}
        .st-key-acceso_tarjeta [data-testid="stCaptionContainer"],.st-key-acceso_tarjeta [data-testid="stCaptionContainer"] p{color:#9aa3b5!important}
        .st-key-acceso_tarjeta [data-testid="stTextInputRootElement"]{background:rgba(8,11,19,.75)!important;
          border:1px solid rgba(255,255,255,.12)!important;border-radius:12px!important}
        .st-key-acceso_tarjeta [data-testid="stTextInputRootElement"]:focus-within{border-color:#ff3b4e!important;
          box-shadow:0 0 0 3px rgba(255,59,78,.18)!important}
        .st-key-acceso_tarjeta [data-testid="stTextInputRootElement"] *{background-color:transparent!important;color:#cfd5e2!important}
        /* «Press Enter to apply» de Streamlit: en inglés y encima de la contraseña. */
        .st-key-acceso_tarjeta [data-testid="InputInstructions"]{display:none!important}
        /* La rayita del tema bajo la pestaña activa (React Aria). */
        .stTabs .react-aria-SelectionIndicator{display:none!important}
        .st-key-acceso_tarjeta [data-testid="stAlert"]{background:rgba(255,255,255,.05)!important;border:1px solid rgba(255,255,255,.08)!important}
        .st-key-acceso_tarjeta [data-testid="stAlert"] p{color:#cfd5e2!important}

        /* Campos oscuros con borde de acento al escribir. */
        .st-key-acceso_tarjeta [data-baseweb="input"],.st-key-acceso_tarjeta [data-baseweb="base-input"]{
          background:rgba(8,11,19,.75)!important;border-color:rgba(255,255,255,.12)!important;border-radius:12px!important}
        .st-key-acceso_tarjeta [data-baseweb="input"]:focus-within{border-color:#ff3b4e!important;box-shadow:0 0 0 3px rgba(255,59,78,.18)!important}
        .st-key-acceso_tarjeta input{background:transparent!important;color:#fff!important;font-size:14px!important;
          border:none!important;box-shadow:none!important;outline:none!important;
          -webkit-text-fill-color:#fff!important;caret-color:#ff6b7d}
        .st-key-acceso_tarjeta button[kind="minimal"],.st-key-acceso_tarjeta [data-baseweb="input"] button{background:transparent!important;color:#cfd5e2!important}

        /* Pestañas tipo píldora: activa en el acento, inactiva translúcida.
           Selectores reales de Streamlit 1.50+: [role="tablist"],
           [data-testid="stTab"], [role="tabpanel"]. */
        .stTabs [role="tablist"]{background:rgba(255,255,255,.06)!important;border:1px solid rgba(255,255,255,.08)!important;
          border-radius:999px!important;padding:5px!important;gap:0!important}
        .stTabs [data-testid="stTab"]{flex:1;justify-content:center;border-radius:999px!important;height:40px!important;
          color:#cfd5e2!important;font-weight:700!important;background:transparent!important}
        .stTabs [data-testid="stTab"] p{color:inherit!important;font-weight:inherit!important}
        .stTabs [aria-selected="true"]{background:linear-gradient(180deg,#ff3b4e,#e4002b)!important;color:#fff!important;
          box-shadow:0 6px 16px rgba(228,0,43,.4)!important}
        .stTabs [data-baseweb="tab-highlight"],.stTabs [data-baseweb="tab-border"]{display:none!important}
        .stTabs [role="tabpanel"]{padding-top:20px!important}

        /* Botones: texto blanco siempre (el tema lo dejaba oscuro sobre rojo). */
        .st-key-acceso_tarjeta .stButton>button{border:none!important;border-radius:12px!important;height:46px!important;
          font-weight:750!important;font-size:14px!important;color:#fff!important;
          background:linear-gradient(180deg,#ff3b4e,#e4002b)!important;box-shadow:0 10px 24px rgba(228,0,43,.35)!important;
          transition:transform .15s ease,box-shadow .15s ease}
        .st-key-acceso_tarjeta .stButton>button:hover{transform:translateY(-1px);box-shadow:0 14px 30px rgba(228,0,43,.45)!important}
        .st-key-acceso_tarjeta .stButton>button p{color:#fff!important;font-weight:750!important}
        .st-key-acceso_tarjeta .stButton>button:disabled{opacity:.45}
        </style>
        """
    st.markdown(style_block, unsafe_allow_html=True)

    if escena("acceso", {"nombre": NOMBRE_APP}, clave="acceso_js") is NO_DISPONIBLE:
        st.markdown(
            f'<div class="login-wrap"><div class="login-wordmark">{NOMBRE_APP}</div>'
            '<div class="login-hero"><p>Inicia sesión para continuar</p></div></div>',
            unsafe_allow_html=True,
        )

    _, mid, _ = st.columns([1, 1.25, 1])
    with mid, st.container(key="acceso_tarjeta"):
        tab_login, tab_signup = st.tabs(["Iniciar sesión", "Crear cuenta"])

        with tab_login:
            username = st.text_input("Usuario", key="login_username")
            password = st.text_input("Contraseña", type="password", key="login_password")
            if BYPASS_AUTH_TEMPORARY:
                st.caption("⚠️ Modo temporal: la verificación real está pausada mientras se arregla la conexión a la base de datos.")
            if st.button("Entrar →", type="primary", use_container_width=True, key="login_submit"):
                if BYPASS_AUTH_TEMPORARY:
                    # No toca la base de datos (que ahora mismo está rota) —
                    # solo deja pasar. El nombre que se muestra en la sidebar
                    # usa lo que hayas escrito, o "Invitado" si lo dejaste vacío.
                    st.session_state.auth_user = {"username": username or "invitado", "display_name": username or "Invitado"}
                    st.session_state.authenticated = True
                    st.rerun()
                elif not username or not password:
                    st.warning("Escribe tu usuario y tu contraseña.")
                else:
                    ok, msg = auth_engine.authenticate(username, password)
                    if ok:
                        st.rerun()
                    else:
                        st.error(msg)

        with tab_signup:
            st.caption(f"Crea tu cuenta para entrar a {NOMBRE_APP} con tu equipo.")
            if BYPASS_AUTH_TEMPORARY:
                st.info("⚠️ Crear cuenta está pausado temporalmente mientras se arregla la conexión a la base de datos. Usa \"Iniciar sesión\" — por ahora te deja entrar sin pedir credenciales reales.")
            new_name = st.text_input("Tu nombre (opcional)", key="signup_name", disabled=BYPASS_AUTH_TEMPORARY)
            new_username = st.text_input("Elige un usuario", key="signup_username", help="Solo letras, números, puntos y guiones. Sin espacios.", disabled=BYPASS_AUTH_TEMPORARY)
            new_password = st.text_input("Elige una contraseña", type="password", key="signup_password", disabled=BYPASS_AUTH_TEMPORARY)
            new_password2 = st.text_input("Repite la contraseña", type="password", key="signup_password2", disabled=BYPASS_AUTH_TEMPORARY)
            if st.button("Crear cuenta →", use_container_width=True, key="signup_submit", disabled=BYPASS_AUTH_TEMPORARY):
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
