"""Pantalla de login: usuario y contraseña, antes de cualquier otra cosa."""
from __future__ import annotations
import streamlit as st

import core.auth_engine as auth_engine
from ui.assets import image_data_uri

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
    # Foto de fondo (assets/images/oficina_claro.jpg, provista por el
    # usuario): trae texto de mentira incrustado en la propia imagen
    # ("Google SSO"/"Microsoft SSO", que esta app no tiene) — por eso NO va
    # directa y visible. Se pone detrás de un velo crema casi opaco (92%),
    # así que se ve la escena (oficina, gente, marca Claro) pero ningún
    # texto de la foto se alcanza a leer. El formulario real de abajo sigue
    # siendo la única fuente de "qué opciones de login existen".
    login_bg = image_data_uri("oficina_claro.jpg")
    # Marcador de texto en vez de f-string: el resto del bloque CSS de abajo
    # tiene decenas de llaves {} propias (selectores) que un f-string
    # interpretaría como variables — un solo .replace() al final evita tener
    # que escapar cada una a mano (alto riesgo de error tipográfico en un
    # bloque tan largo).
    style_block = """
        <style>
        @keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}

        /* Mismo resplandor rojo de siempre, un velo crema casi opaco encima
           de la foto (para que su texto no se lea) y la foto al fondo. */
        [data-testid="stAppViewContainer"],[data-testid="stApp"],[data-testid="stMain"],html,body{
          background-image:
            radial-gradient(ellipse 900px 500px at 8% 6%, rgba(228,0,43,.20), transparent 60%),
            radial-gradient(ellipse 900px 550px at 92% 96%, rgba(228,0,43,.16), transparent 60%),
            radial-gradient(ellipse 700px 500px at 50% 100%, rgba(228,0,43,.10), transparent 65%),
            linear-gradient(rgba(250,246,240,.92),rgba(250,246,240,.92)),
            url(__LOGIN_BG__);
          background-size: auto, auto, auto, cover, cover;
          background-position: 8% 6%, 92% 96%, 50% 100%, center, center;
          background-repeat: no-repeat, no-repeat, no-repeat, no-repeat, no-repeat;
          background-attachment: fixed, fixed, fixed, fixed, fixed;
          background-color: #faf6f0 !important;
        }
        [data-testid="stHeader"]{background:transparent!important}

        .login-wrap{max-width:440px;margin:7vh auto 0;padding:0 16px;animation:fadeUp .45s ease both;text-align:center}
        .login-wordmark{font-family:'Sora','Inter',sans-serif;font-weight:800;font-size:44px;color:#e4002b;
          letter-spacing:-.03em;line-height:1;margin:0 0 18px;display:inline-block}
        .login-wordmark sup{color:#e4002b;font-size:22px;position:relative;top:-18px;left:1px}
        .login-hero{margin-bottom:26px}
        .login-hero h1{font-size:20px;font-weight:800;font-family:'Sora','Inter',sans-serif;letter-spacing:-.02em;margin:0 0 6px;color:#1a1a1a}
        .login-hero p{font-size:12.5px;color:#6b6b6b;margin:0}

        .login-card{background:transparent;padding:0;text-align:left}

        /* Pestañas tipo píldora dividida: activa en rojo, inactiva en negro. */
        .stTabs [data-baseweb="tab-list"]{background:#161616!important;border:none!important;border-radius:999px!important;
          padding:5px!important;gap:0!important;box-shadow:0 10px 26px rgba(0,0,0,.14)!important}
        .stTabs [data-baseweb="tab"]{flex:1;justify-content:center;border-radius:999px!important;height:42px!important;
          color:#e8e8e8!important;font-weight:700!important;background:transparent!important}
        .stTabs [data-baseweb="tab"] p{color:inherit!important;font-weight:inherit!important}
        .stTabs [aria-selected="true"]{background:linear-gradient(180deg,#ff3b4e,#e4002b)!important;color:#fff!important;
          box-shadow:0 4px 12px rgba(228,0,43,.35)!important}
        .stTabs [data-baseweb="tab-highlight"],.stTabs [data-baseweb="tab-border"]{display:none!important}
        .stTabs [data-baseweb="tab-panel"]{padding-top:22px!important}

        /* Campos redondeados, blancos, sobre el fondo crema. */
        .login-card input{background:#ffffff!important;border:1px solid #e7e2da!important;border-radius:12px!important;
          padding:12px 14px!important;font-size:14px!important;box-shadow:0 1px 2px rgba(20,20,20,.04)!important}
        .login-card label p{color:#3a3a3a!important;font-weight:650!important;font-size:12.5px!important}

        .login-card button[kind="primary"]{background:linear-gradient(180deg,#8c1420,#6e0f19)!important;
          border:none!important;border-radius:12px!important;height:46px!important;font-weight:750!important;
          font-size:14px!important;box-shadow:0 8px 18px rgba(110,15,25,.28)!important}
        .login-card button[kind="secondary"]{background:linear-gradient(180deg,#ff3b4e,#e4002b)!important;
          border:none!important;color:#fff!important;border-radius:12px!important;height:46px!important;font-weight:750!important}
        </style>
        """
    st.markdown(style_block.replace("__LOGIN_BG__", login_bg), unsafe_allow_html=True)

    st.markdown(
        '<div class="login-wrap"><div class="login-wordmark">Claro<sup>⚡</sup></div>'
        '<div class="login-hero"><h1>Panel Analítico Universal Claro</h1>'
        '<p>Inicia sesión para continuar con tu cuenta Claro</p></div></div>',
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
            st.caption("Crea tu cuenta para entrar al Panel Analítico de tu equipo.")
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
