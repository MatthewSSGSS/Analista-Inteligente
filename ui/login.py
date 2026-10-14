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
    # Sin foto de fondo: la que había (una oficina con la marca de una
    # empresa) ataba la app a una compañía. El fondo es el resplandor del
    # tema sobre crema, y la cabecera animada (ui/web/acceso.*) pone la marca
    # neutral de la app. Los campos siguen siendo de Streamlit: la
    # contraseña va directo a Python, no pasa por JavaScript.
    style_block = """
        <style>
        @keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}

        /* Resplandor del color de acento sobre fondo crema. */
        [data-testid="stAppViewContainer"],[data-testid="stApp"],[data-testid="stMain"],html,body{
          background-image:
            radial-gradient(ellipse 900px 500px at 8% 6%, rgba(228,0,43,.20), transparent 60%),
            radial-gradient(ellipse 900px 550px at 92% 96%, rgba(228,0,43,.16), transparent 60%),
            radial-gradient(ellipse 700px 500px at 50% 100%, rgba(228,0,43,.10), transparent 65%),
            linear-gradient(rgba(250,246,240,1),rgba(250,246,240,1));
          background-size: auto, auto, auto, cover;
          background-position: 8% 6%, 92% 96%, 50% 100%, center;
          background-repeat: no-repeat, no-repeat, no-repeat, no-repeat;
          background-attachment: fixed, fixed, fixed, fixed;
          background-color: #faf6f0 !important;
        }
        [data-testid="stHeader"]{background:transparent!important}

        .login-wrap{max-width:440px;margin:7vh auto 0;padding:0 16px;animation:fadeUp .45s ease both;text-align:center}
        .login-wordmark{font-family:'Sora','Inter',sans-serif;font-weight:800;font-size:34px;color:#e4002b;
          letter-spacing:-.03em;line-height:1;margin:0 0 18px;display:inline-block}
        .login-hero{margin-bottom:26px}
        .login-hero h1{font-size:20px;font-weight:800;font-family:'Sora','Inter',sans-serif;letter-spacing:-.02em;margin:0 0 6px;color:#1a1a1a}
        .login-hero p{font-size:12.5px;color:#6b6b6b;margin:0}

        .login-card{background:transparent;padding:0;text-align:left}

        /* Pestañas tipo píldora dividida: activa en rojo, inactiva en negro.
           `[data-baseweb="tab-list"/"tab"/"tab-panel"]` ya no existen en el
           DOM de Streamlit 1.50+ (confirmado con un navegador real) — estas
           reglas nunca hacían match. Selectores reales: [role="tablist"],
           [data-testid="stTab"], [role="tabpanel"]. */
        .stTabs [role="tablist"]{background:#161616!important;border:none!important;border-radius:999px!important;
          padding:5px!important;gap:0!important;box-shadow:0 10px 26px rgba(0,0,0,.14)!important}
        .stTabs [data-testid="stTab"]{flex:1;justify-content:center;border-radius:999px!important;height:42px!important;
          color:#e8e8e8!important;font-weight:700!important;background:transparent!important}
        .stTabs [data-testid="stTab"] p{color:inherit!important;font-weight:inherit!important}
        .stTabs [aria-selected="true"]{background:linear-gradient(180deg,#ff3b4e,#e4002b)!important;color:#fff!important;
          box-shadow:0 4px 12px rgba(228,0,43,.35)!important}
        .stTabs [role="tabpanel"]{padding-top:22px!important}

        /* Campos redondeados, blancos, sobre el fondo crema. */
        .login-card input{background:#ffffff!important;border:1px solid #e7e2da!important;border-radius:12px!important;
          padding:12px 14px!important;font-size:14px!important;box-shadow:0 1px 2px rgba(20,20,20,.04)!important}
        .login-card label p{color:#3a3a3a!important;font-weight:650!important;font-size:12.5px!important}

        /* `.login-card` no envuelve de verdad a los widgets (un st.markdown
           abre el div y Streamlit lo cierra solo), así que el botón «Entrar»
           tomaba el texto oscuro del tema sobre el rojo: se fuerza blanco. */
        [data-testid="stMain"] .stButton>button[kind="primary"],
        [data-testid="stMain"] .stButton>button[kind="primary"] p{color:#fff!important;font-weight:750!important}
        .login-card button[kind="primary"]{background:linear-gradient(180deg,#8c1420,#6e0f19)!important;
          border:none!important;border-radius:12px!important;height:46px!important;font-weight:750!important;
          font-size:14px!important;box-shadow:0 8px 18px rgba(110,15,25,.28)!important}
        .login-card button[kind="secondary"]{background:linear-gradient(180deg,#ff3b4e,#e4002b)!important;
          border:none!important;color:#fff!important;border-radius:12px!important;height:46px!important;font-weight:750!important}
        </style>
        """
    st.markdown(style_block, unsafe_allow_html=True)

    if escena("acceso", {"nombre": NOMBRE_APP}, clave="acceso_js") is NO_DISPONIBLE:
        st.markdown(
            f'<div class="login-wrap"><div class="login-wordmark">{NOMBRE_APP}</div>'
            '<div class="login-hero"><p>Inicia sesión para continuar</p></div></div>',
            unsafe_allow_html=True,
        )

    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown('<div class="login-card">', unsafe_allow_html=True)
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
        st.markdown('</div>', unsafe_allow_html=True)
