"""Única fuente de verdad del lenguaje visual (colores, tipografía, radios,
sombras, breakpoints y gradiente de marca) para toda la app.

Sustituye:
- El bloque `<style>` que antes vivía inline en `app.py` (dos `st.markdown`
  consecutivos, construidos a partir de `_theme_vars`/`_bg_gradient`).
- `ui/theme.py` (paleta alternativa que nunca se llegó a conectar a nada).
- `assets/style.css.css` (tema neón 100% oscuro que tampoco estaba conectado
  y que, de haberse cargado, habría roto Light Mode).

El contenido visual (colores exactos, tamaños, sombras) es el mismo que ya
corría en producción vía `app.py`; aquí solo se centraliza y se sustituyen
algunos valores literales repetidos (tipografía, gradiente del isotipo,
breakpoint) por los tokens de abajo, sin cambiar el resultado renderizado.

`app.py` debe llamar únicamente a `inject_theme(dark=...)`. Ningún otro
módulo debe definir un nuevo bloque `<style>` que redefina `:root{--bg:...}`
— los `<style>` locales de `login.py`, `landing.py`, `mode_choice.py` y
`practical.py` siguen siendo válidos porque solo AÑADEN clases nuevas sobre
estos tokens (se inyectan después de este tema), nunca redefinen la paleta
base.
"""
from __future__ import annotations

import streamlit as st

from ui.assets import image_data_uri

# ---------------------------------------------------------------------------
# Tokens compartidos. Los breakpoints existen como constantes de Python (y no
# solo como texto dentro del CSS) para que cualquier otro `<style>` que
# necesite el mismo punto de corte lo importe de aquí en vez de repetir el
# número mágico — las media queries de CSS no admiten `var()`, así que la
# única forma de tener una fuente única es esta.
BREAKPOINT_CONTENT = 900  # colapso general de layout (sidebar/hero/kpis)
BREAKPOINT_CARDS = 760    # colapso de grillas de 2 tarjetas a 1 columna (mode_choice)

FONT_SANS = "'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif"
FONT_DISPLAY = "'Sora','Inter',sans-serif"

# Gradiente del isotipo de marca (el círculo rojo). Antes estaba repetido de
# forma idéntica en app.py (.sidebar-logo-mark), ui/home.py (x2) y
# ui/landing.py (.landing-mark).
BRAND_ORB = "radial-gradient(circle at 32% 28%,#ff4d4d,#e4002b 55%,#a80e1f 100%)"


def _theme_vars(dark: bool) -> str:
    """Paleta de color: superficie, texto, línea y acentos, para claro/oscuro.

    `--*-strong` son variantes de texto pequeño (badges, deltas, tags) que
    se pintan directamente sobre su propio `--*-soft`: el acento base
    (`--blue`/`--green`/`--amber`) ya está afinado para verse bien como
    borde, como texto grande o sobre un panel sólido, pero en texto chico
    sobre su propio fondo tintado (p. ej. `--blue` sobre `--blue-soft`) el
    contraste real medido (WCAG) cae a ~4.0–4.3:1 en ambos temas —
    perceptible sobre todo en Modo Oscuro. `--*-strong` reutiliza tonos que
    ya existían en algún lugar del CSS (nunca colores inventados) elegidos
    para que ese mismo texto llegue a ≥4.5:1.

    `--glow-ring` es un tercer valor de `box-shadow` (se añade con una coma
    al final del que ya tenía cada tarjeta, nunca lo reemplaza) para las
    tarjetas más importantes de leer primero — KPI, gráfico, ejecutivo,
    hallazgo — a pedido de imitar una referencia visual oscura con bordes
    con resplandor. En Oscuro es un halo de color real (así se ve la
    referencia); en Claro es solo un anillo de 1px muy sutil — un glow
    tan fuerte como el de Oscuro sobre fondo blanco se ve sucio, no
    "vivo", así que se afinó por separado en vez de copiar el mismo
    valor en los dos temas."""
    if dark:
        return """
  --bg:#0d1117;--panel:#161b22;--panel-2:#1c2129;--panel-3:#222833;
  --text:#e6e9ef;--muted:#9aa4b2;--soft:#7b8592;--line:#2a313d;--line-soft:#232a34;
  --blue:#ff3b52;--blue-soft:rgba(255,59,82,.14);--blue-strong:#ff6b7a;
  --teal:#2dd4c8;--teal-soft:rgba(45,212,200,.14);
  --green:#3ecf8e;--green-soft:rgba(62,207,142,.14);--green-strong:#3ecf8e;
  --amber:#f0a63e;--amber-soft:rgba(240,166,62,.14);--amber-strong:#f0a63e;
  --red:#ff5570;--red-soft:rgba(255,85,112,.14);--purple:#9b8cf2;--purple-soft:rgba(155,140,242,.14);
  --card-solid:#161b22;
  --glow-ring:0 0 0 1px rgba(255,59,82,.32),0 0 26px rgba(255,59,82,.24);
"""
    return """
  --bg:#ffffff;--panel:#ffffff;--panel-2:#f7f9fc;--panel-3:#eef2f8;
  --text:#131826;--muted:#5b6473;--soft:#5f6b80;--line:#d8dce6;--line-soft:#e8ebf1;
  --blue:#e4002b;--blue-soft:#fde8ea;--blue-strong:#c8001f;
  --teal:#0fa8a0;--teal-soft:#e6f8f6;
  --green:#189a63;--green-soft:#e7f7ef;--green-strong:#0f7a4e;
  --amber:#c8790a;--amber-soft:#fdf2e2;--amber-strong:#a15c04;
  --red:#e0223f;--red-soft:#fdeaee;--purple:#6a5bd8;--purple-soft:#efecfc;
  --card-solid:#ffffff;
  --glow-ring:0 0 0 1px rgba(228,0,43,.15),0 0 12px rgba(228,0,43,.09);
"""


def _sidebar_vars(dark: bool) -> str:
    """Paleta del sidebar (rail de navegación), separada de `_theme_vars`
    porque hasta ahora era fija (siempre navy oscuro, sin importar el
    tema) — ver hallazgo de QA: con el toggle en Claro la app quedaba
    mitad clara/mitad oscura. En oscuro se preservan los valores exactos
    que ya corrían en producción (cero cambio visual); en claro se
    reutilizan los mismos tonos que ya usa `_theme_vars(dark=False)` para
    el resto del contenido, para que el rail se sienta parte de la misma
    paleta en vez de inventar colores nuevos."""
    if dark:
        return """
  --sidebar-bg:#0d1119;--sidebar-panel:#171c29;--sidebar-line:#2a3040;
  --sidebar-text:#d7dbe6;--sidebar-text-strong:#ffffff;--sidebar-muted:#8992a8;
"""
    return """
  --sidebar-bg:#f7f9fc;--sidebar-panel:#ffffff;--sidebar-line:#d8dce6;
  --sidebar-text:#131826;--sidebar-text-strong:#131826;--sidebar-muted:#5b6473;
"""


def _bg_gradient(dark: bool) -> str:
    """Resplandor radial de fondo (rojo de marca sobre negro/blanco)."""
    if dark:
        return """
    radial-gradient(ellipse 950px 550px at 100% 0%, rgba(255,59,82,.10), transparent 58%),
    radial-gradient(ellipse 850px 550px at 0% 100%, rgba(255,59,82,.07), transparent 58%),
    radial-gradient(ellipse 700px 500px at 50% 45%, rgba(255,59,82,.04), transparent 65%),
    #0d1117!important;
"""
    return """
    radial-gradient(ellipse 950px 550px at 100% 0%, rgba(228,0,43,.065), transparent 58%),
    radial-gradient(ellipse 850px 550px at 0% 100%, rgba(228,0,43,.05), transparent 58%),
    radial-gradient(ellipse 700px 500px at 50% 45%, rgba(228,0,43,.025), transparent 65%),
    #ffffff!important;
"""


def base_layer_css(dark: bool) -> str:
    """Tokens (`:root`) + fondo + tipografía base. Es el único bloque que
    depende de `dark`; todo lo demás (`components_css`) es estático y usa
    exclusivamente `var(--...)`."""
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Sora:wght@600;700;800&display=swap');

:root{{
{_theme_vars(dark)}
{_sidebar_vars(dark)}
  --radius-lg:16px;--radius-md:12px;--radius-sm:9px;
  --shadow-sm:0 1px 2px rgba(20,26,43,.04),0 1px 1px rgba(20,26,43,.03);
  --shadow-md:0 2px 6px rgba(20,26,43,.05),0 10px 24px rgba(20,26,43,.055);
  --shadow-lg:0 8px 20px rgba(20,26,43,.08),0 2px 6px rgba(20,26,43,.05);
  --font-sans:{FONT_SANS};
  --font-display:{FONT_DISPLAY};
  --brand-orb:{BRAND_ORB};
}}
html,body,[data-testid="stAppViewContainer"],[data-testid="stApp"],[data-testid="stMain"],[data-testid="stMainBlockContainer"],.main,.stAppViewContainer{{
  background:
    {_bg_gradient(dark)}
  color:var(--text)!important;font-family:var(--font-sans)}}
</style>
"""


# Clases de componentes reutilizadas por toda la UI (KPIs, tarjetas, tabs,
# botones, sidebar, expanders, etc.). No depende de dark/light: todo usa
# var(--...), definidas arriba en base_layer_css(). Se mantiene como texto
# literal (idéntico al que corría inline en app.py) y las pocas
# sustituciones de tokens se aplican en components_css() vía .replace(),
# para poder verificar que cada sustitución es un cambio de forma, no de
# valor computado.
_COMPONENTS_CSS_RAW = """
<style>
/* Entrada suave para las tarjetas del panel — ya existía este mismo
   keyframe, pero repetido y solo local a login/mode_choice/practical
   (pantallas de antes de entrar a la app); el dashboard en sí nunca lo
   tenía. Una sola definición aquí, reutilizada por las tarjetas
   compartidas de todo el panel — cada vez que se aplica un filtro o se
   cambia de pestaña, las tarjetas nuevas entran con este mismo gesto en
   vez de aparecer de golpe. */
@keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
[data-testid="stHeader"],[data-testid="stBottomBlockContainer"]{background:var(--bg)!important}
.stApp{background:var(--bg);color:var(--text)}
* {font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.block-container{max-width:1540px;padding:1.1rem 1.8rem 4rem;position:relative;z-index:0}
/* ===== Franja de foto de toda la app: la misma ciudad_red.jpg de los
   banners de cada vista (ui/components/section.py::banner_header), pero
   detrás del hero + el buscador + la fila de pestañas — lo único que se
   repite igual en TODAS las vistas, así que es la única franja que tiene
   sentido pintar una sola vez a nivel de página en vez de vista por vista.
   Es un ::before absoluto con z-index negativo (no una foto puesta en cada
   elemento): así no importa cómo Streamlit anide los divs de arriba, el
   texto normal (en flujo, sin position) siempre pinta ENCIMA de un
   descendiente absoluto con z-index negativo — la misma garantía de orden
   de pintado en la que se apoya .view-banner, aplicada aquí a una franja
   compartida en vez de a una sola tarjeta. Por debajo de esta altura
   (~300px) todo vuelve al fondo normal de la app — las tablas, tarjetas y
   gráficos de cada pestaña NO viven bajo la foto.

   Ojo con el selector: `.block-container` NO es exclusivo del contenido
   principal — el sidebar tiene el suyo propio
   (`section[data-testid="stSidebar"] .block-container`, ver más abajo), y
   un selector desnudo `.block-container:before` habría pintado esta misma
   foto detrás del logo/filtros del sidebar también. Por eso va con el
   prefijo `[data-testid="stMain"]`, que solo envuelve el contenido
   principal.

   Segundo problema real, encontrado después de ver la franja pisar el
   login y el landing: `inject_theme()` se llama SIEMPRE, en cada rerun,
   antes incluso de decidir si toca mostrar login/landing/mode_choice o el
   dashboard — así que esta regla, sin más, se pintaba en TODAS esas
   pantallas, duplicada encima del fondo propio que cada una ya trae
   (el velo crema de ui/login.py, el de ui/landing.py). `:has(.hero-band)`
   hace que el `::before` solo exista cuando el `.block-container`
   de turno de verdad contiene un `.hero-band` — y esa clase solo la pone
   `hero(..., band=True)`, que solo se llama una vez en toda la app
   (app.py, ya dentro del dashboard). En login/landing/mode_choice no
   existe ningún `.hero-band`, así que ahí `:has()` no matchea y la franja
   simplemente no se pinta — cada pantalla vuelve a depender solo de su
   propio fondo, sin pisarse. */
[data-testid="stMain"] .block-container:has(.hero-band):before{content:"";position:absolute;top:0;left:0;right:0;height:300px;z-index:-1;
  border-radius:0 0 var(--radius-lg) var(--radius-lg);
  background-image:
    linear-gradient(120deg,rgba(8,4,7,.95) 0%,rgba(110,8,20,.62) 38%,rgba(20,4,8,.24) 68%,transparent 90%),
    url(__HERO_BG__);
  background-size:cover,cover;background-position:center,center;background-repeat:no-repeat,no-repeat}
header[data-testid="stHeader"]{background:rgba(238,241,246,.86);backdrop-filter:blur(6px)}
h1,h2,h3,h4,h5,h6{color:var(--text);font-family:'Sora','Inter',sans-serif;letter-spacing:-.01em}
p,span,div,li,label{color:var(--text)}

/* ===== Sidebar: nav rail with its own surface tokens (--sidebar-*), navy in
   Dark Mode and off-white in Light Mode — same tokens, values swapped in
   _sidebar_vars() so this block never needs to know which mode is active. */
section[data-testid="stSidebar"]{background:var(--sidebar-bg)!important;border-right:1px solid var(--sidebar-line)!important}
section[data-testid="stSidebar"] .block-container{padding:1rem 1rem 1.5rem}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:.5rem}
section[data-testid="stSidebar"] *{color:var(--sidebar-text)}
section[data-testid="stSidebar"] h1,section[data-testid="stSidebar"] h2,section[data-testid="stSidebar"] h3{color:var(--sidebar-text-strong)!important;font-family:'Sora','Inter',sans-serif;letter-spacing:-.01em}
section[data-testid="stSidebar"] .stCaption,section[data-testid="stSidebar"] [data-testid="stCaptionContainer"]{color:var(--sidebar-muted)!important}
section[data-testid="stSidebar"] hr{border-color:var(--sidebar-line);margin:.75rem 0}
section[data-testid="stSidebar"] input,section[data-testid="stSidebar"] textarea{background:var(--sidebar-panel)!important;border:1px solid var(--sidebar-line)!important;color:var(--sidebar-text-strong)!important;border-radius:9px!important}
section[data-testid="stSidebar"] [data-baseweb="select"]{background:var(--sidebar-panel)!important}
section[data-testid="stSidebar"] [data-baseweb="select"]>div{background:var(--sidebar-panel)!important;border:1px solid var(--sidebar-line)!important;border-radius:9px!important}
/* Baseweb nests several layers inside the select (value box, indicator
   separator, dropdown-arrow box) that each carry their own background —
   forcing every descendant transparent is the only reliable way to stop the
   two-tone "dark pill with a white patch near the arrow" look. */
section[data-testid="stSidebar"] [data-baseweb="select"] *{color:var(--sidebar-text-strong)!important;background:transparent!important;background-color:transparent!important;fill:var(--sidebar-text-strong)!important}
section[data-testid="stSidebar"] [data-baseweb="select"] input::placeholder{color:var(--sidebar-muted)!important;opacity:1!important}
section[data-testid="stSidebar"] .stMultiSelect span[data-baseweb="tag"]{background:rgba(228,0,43,.22)!important;border:1px solid rgba(228,0,43,.4)!important}
section[data-testid="stSidebar"] .stMultiSelect span[data-baseweb="tag"] span{color:var(--sidebar-text-strong)!important}
section[data-testid="stSidebar"] [data-baseweb="popover"]{background:var(--sidebar-panel)!important;border:1px solid var(--sidebar-line)!important}
section[data-testid="stSidebar"] [data-baseweb="menu"]{background:var(--sidebar-panel)!important}
section[data-testid="stSidebar"] [data-baseweb="menu"] li:hover{background:rgba(228,0,43,.18)!important}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"]{background:var(--sidebar-panel)!important;border:1px dashed var(--sidebar-line)!important;border-radius:var(--radius-md)!important}
section[data-testid="stSidebar"] .stFileUploader small{color:var(--sidebar-muted)!important}
section[data-testid="stSidebar"] .stButton>button{background:var(--sidebar-panel);color:var(--sidebar-text-strong);border:1px solid var(--sidebar-muted);border-radius:var(--radius-sm);transition:transform .12s ease,box-shadow .12s ease,border-color .12s ease,color .12s ease,background .12s ease}
section[data-testid="stSidebar"] .stButton>button:hover{border-color:var(--blue);color:var(--blue-strong);background:rgba(228,0,43,.12);transform:translateY(-1px);box-shadow:0 4px 12px rgba(228,0,43,.18)}
section[data-testid="stSidebar"] .stButton>button:active{border-color:var(--blue);color:var(--blue-strong);background:rgba(228,0,43,.18);transform:translateY(0) scale(.98)}
section[data-testid="stSidebar"] button[kind="primary"]{background:linear-gradient(180deg,#ff3b4e,#e4002b)!important;border-color:#c8001f!important;color:#fff!important;transition:transform .12s ease,box-shadow .12s ease!important}
section[data-testid="stSidebar"] button[kind="primary"]:hover{transform:translateY(-1px);box-shadow:0 6px 16px rgba(228,0,43,.3)!important}
section[data-testid="stSidebar"] button[kind="primary"]:active{transform:translateY(0) scale(.98)!important}
section[data-testid="stSidebar"] [data-testid="stExpander"]{background:var(--sidebar-panel)!important;border:1px solid var(--sidebar-line)!important}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary{background:var(--sidebar-panel)!important;color:var(--sidebar-text-strong)!important}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover{color:var(--blue)!important}
section[data-testid="stSidebar"] [data-testid="stAlert"]{background:var(--sidebar-panel)!important;border:1px solid var(--sidebar-line)!important;color:var(--sidebar-text)!important}
section[data-testid="stSidebar"] .mode-banner{background:rgba(228,0,43,.16);border:1px solid rgba(228,0,43,.4);color:var(--sidebar-text-strong)}
section[data-testid="stSidebar"] .mode-banner .mode-banner-label{color:var(--sidebar-muted)}
section[data-testid="stSidebar"] .mode-banner b{color:var(--sidebar-text-strong)}
section[data-testid="stSidebar"] .mode-confidence{color:var(--sidebar-muted)!important;background:var(--sidebar-panel)!important}
/* Sidebar logo block, like the reference nav header */
.sidebar-logo{display:flex;align-items:center;gap:10px;padding:2px 2px 14px;margin-bottom:10px;border-bottom:1px solid var(--sidebar-line)}
.sidebar-logo-mark{width:34px;height:34px;border-radius:50%;background:radial-gradient(circle at 32% 28%,#ff4d4d,#e4002b 55%,#a80e1f 100%);box-shadow:inset 0 -3px 6px rgba(0,0,0,.22),inset 0 2px 3px rgba(255,255,255,.35);display:flex;align-items:center;justify-content:center;font-size:16px;flex:0 0 34px}
.sidebar-logo-text{font-size:14px;font-weight:800;font-family:'Sora','Inter',sans-serif;color:var(--sidebar-text-strong);line-height:1.2}
.sidebar-logo-text small{display:block;font-size:10.5px;font-weight:600;font-family:'Inter',sans-serif;color:var(--sidebar-muted)}
.sidebar-section-label{font-size:10.5px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:var(--sidebar-muted)!important;margin:10px 0 5px}
.sidebar-group-header{font-size:12px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;color:var(--sidebar-text-strong)!important;
  margin:14px 0 7px;padding-top:11px;border-top:1px solid var(--sidebar-line);font-family:'Sora','Inter',sans-serif}
.sidebar-group-header:first-of-type{border-top:none;padding-top:0;margin-top:4px}
/* View-mode selector styled as a dark nav pill row, matching the sidebar */
section[data-testid="stSidebar"] div[role="radiogroup"]{background:var(--sidebar-panel);border:1px solid var(--sidebar-line);border-radius:10px;padding:4px;gap:2px}
section[data-testid="stSidebar"] div[role="radiogroup"] label{border-radius:7px;padding:6px 10px}
section[data-testid="stSidebar"] div[role="radiogroup"] label p{color:var(--sidebar-muted)!important;font-weight:650}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked){background:linear-gradient(180deg,#ff3b4e,#e4002b)}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p{color:#ffffff!important;font-weight:750}

/* ===== Hero / page header: minimal and flat, like the reference report header ===== */
.hero{padding:6px 2px 14px;margin:0 0 6px;border:none;background:transparent;box-shadow:none;border-bottom:1px solid var(--line)}
.hero h1{margin:0;font-size:20px;font-weight:800;letter-spacing:-.01em;color:var(--text)}
.hero p{color:var(--muted);margin:4px 0 0;font-size:12.5px;max-width:900px}
/* Único hero que se sienta sobre la franja de foto de .block-container:before
   (ver arriba) — texto blanco fijo, igual que .view-banner, porque debajo
   siempre hay una foto oscura sin importar si el tema activo es Claro u
   Oscuro. Los otros dos hero() de la app (Inicio, perfil individual) no
   llevan esta clase y se quedan con var(--text) normal. */
.hero-band{border-bottom:none}
.hero-band h1{color:#ffffff!important;text-shadow:0 2px 10px rgba(0,0,0,.65)}
.hero-band p{color:rgba(255,255,255,.9)!important;text-shadow:0 1px 6px rgba(0,0,0,.6)}
.hero-band-meta{color:#ffffff!important;text-shadow:0 1px 6px rgba(0,0,0,.6);font-size:13.5px;margin:0 0 10px}
.hero-band-meta b{color:#ffffff!important}

/* ===== Section headers: bold title with a quiet subtitle directly beneath, no pill chrome ===== */
.section-intro{display:flex;align-items:flex-start;justify-content:space-between;margin:26px 0 6px;flex-wrap:wrap;gap:8px}
.section-intro.compact{margin-top:26px}
.section-intro h2{margin:0;font-size:17px;font-weight:800;letter-spacing:-.01em;color:var(--text)}
.eyebrow{display:none}
.data-badge{font-size:10.5px;font-weight:700;color:var(--red);background:none;border:none;padding:0;box-shadow:none;text-transform:uppercase;letter-spacing:.05em}

/* ===== View banner: encabezado de vista con foto (ui/components/section.py
   :: banner_header) — usado en un puñado de vistas donde una de las 4
   fotos de assets/images/ tiene sentido temático. El texto es blanco fijo
   sobre un velo oscuro que SIEMPRE está ahí (con opacidad, no con
   var(--panel)) — funciona igual en Claro y Oscuro sin dos versiones. */
.view-banner{position:relative;border-radius:var(--radius-lg);overflow:hidden;margin:4px 0 22px;
  height:112px;background-size:cover;background-position:center;animation:fadeUp .4s ease both;
  box-shadow:0 1px 2px rgba(20,26,43,.04),0 8px 20px rgba(20,26,43,.06),var(--glow-ring)}
/* La foto sola no basta para que el texto se lea con una imagen tan
   detallada: el ojo pierde el trazo de las letras contra tanto ruido
   visual, aunque el contraste numérico diera bien. El velo se subió a
   94%/70% (antes 85%/45%) y se extiende más hacia la derecha, y el texto
   suma su propia sombra (text-shadow) — dos capas de seguridad, no solo
   una. Ojo: esto va en `:before` (una capa aparte, detrás del texto por
   `z-index`), NO en un `filter` sobre `.view-banner` — un filter ahí
   oscurecería también el texto, que es descendiente del mismo elemento. */
.view-banner:before{content:"";position:absolute;inset:0;
  background:linear-gradient(90deg,rgba(6,8,13,.94) 0%,rgba(6,8,13,.7) 55%,rgba(6,8,13,.2) 85%)}
.view-banner-content{position:relative;z-index:1;height:100%;display:flex;flex-direction:column;justify-content:center;padding:0 26px}
.view-banner h2{margin:0;font-size:21px;font-weight:800;letter-spacing:-.01em;color:#ffffff;text-shadow:0 2px 10px rgba(0,0,0,.65)}
.view-banner p{margin:5px 0 0;font-size:12px;color:rgba(255,255,255,.88);max-width:600px;line-height:1.5;text-shadow:0 1px 6px rgba(0,0,0,.6)}
@media(max-width:900px){.view-banner{height:130px}.view-banner:before{background:linear-gradient(180deg,rgba(6,8,13,.45) 0%,rgba(6,8,13,.94) 100%)}.view-banner-content{justify-content:flex-end;padding:0 18px 14px}}

/* ===== KPI scorecards: light glassmorphism — frosted glass, not flat white ===== */
.kpi-card{position:relative;background:var(--card-solid);border:1px solid var(--line);border-left:4px solid var(--blue);
  border-radius:12px;padding:14px 16px 14px 18px;min-height:92px;animation:fadeUp .4s ease both;
  box-shadow:0 1px 2px rgba(20,26,43,.04),0 8px 20px rgba(20,26,43,.055),var(--glow-ring);
  transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
.kpi-card:hover{transform:translateY(-3px);box-shadow:0 14px 28px rgba(20,26,43,.09),var(--glow-ring)}
.kpi-label{display:block;font-size:10.5px;color:var(--muted);letter-spacing:.02em;font-weight:700;text-transform:uppercase}
.kpi-value{font-size:22px;font-weight:800;letter-spacing:-.01em;margin-top:9px;color:var(--text);font-variant-numeric:tabular-nums;font-family:'Sora','Inter',sans-serif}
.kpi-card.negative .kpi-value{color:var(--red)}
.kpi-card.positive .kpi-value{color:var(--green)}
/* "Líder · X" (quién encabeza una categoría) es un tipo de dato distinto a
   un total/promedio — antes se veía IGUAL a cualquier otra tarjeta (mismo
   borde rojo, mismo texto negro), lo que hacía fácil confundir "esta es la
   tarjeta que destaca a alguien" con "esta es solo una cifra más". Color
   propio (morado, un tono ya definido en el tema pero sin uso hasta ahora)
   para que se distinga de un vistazo. */
.kpi-card.leader{border-left-color:var(--purple)}
.kpi-card.leader .kpi-value{color:var(--purple)}
.kpi-delta{font-size:10.5px;margin-top:5px;font-weight:700}
.kpi-delta.positive{color:var(--green-strong)}.kpi-delta.negative{color:var(--red)}.kpi-delta.neutral{color:var(--muted)}

/* ===== Decision strips / trend lines ===== */
.decision-strip{margin:10px 0 16px;padding:12px 15px;border:1px solid var(--line);border-radius:var(--radius-sm);background:var(--panel);color:var(--text);box-shadow:var(--shadow-sm);font-size:13px}
.decision-strip.positive{border-left:4px solid var(--green);background:var(--green-soft)}
.decision-strip.negative{border-left:4px solid var(--red);background:var(--red-soft)}
.decision-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--blue);margin-right:8px}

/* ===== Insight / finding cards ===== */
.insight-card{display:flex;gap:12px;align-items:flex-start;border:1px solid var(--line);border-radius:var(--radius-md);
  padding:15px;margin:4px 0 8px;background:var(--card-solid);animation:fadeUp .4s ease both;
  min-height:88px;box-shadow:0 1px 2px rgba(20,26,43,.04),0 8px 20px rgba(20,26,43,.055),var(--glow-ring);
  transition:transform .18s ease,box-shadow .18s ease}
.insight-card:hover{transform:translateY(-2px);box-shadow:0 14px 28px rgba(20,26,43,.09),var(--glow-ring)}
.insight-card.positive{border-left:4px solid var(--green)}
.insight-card.warning{border-left:4px solid var(--amber)}
.insight-card.info{border-left:4px solid var(--blue)}
.insight-icon{width:28px;height:28px;flex:0 0 28px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:var(--panel-3);color:var(--muted);font-weight:800}
.insight-title{font-size:10px;color:var(--soft);text-transform:uppercase;letter-spacing:.09em;margin-bottom:5px;font-weight:800}
.insight-text{font-size:13px;line-height:1.45;color:var(--text)}
.insight-text.secondary{color:var(--muted)}
.insight-card small{display:block;color:var(--soft);margin-top:6px}
.insight-body{flex:1}
.insight-label{font-size:9px;text-transform:uppercase;letter-spacing:.09em;color:var(--soft);font-weight:800;margin-top:7px}
.insight-action{margin-top:9px;padding:9px 10px;background:var(--panel-2);border:1px solid var(--line);border-radius:var(--radius-sm);color:var(--text);font-size:12px;line-height:1.45}

/* ===== Decision panel / action rows ===== */
.decision-panel{margin:14px 0 8px;padding:13px 15px;background:var(--panel-2);border:1px solid var(--line);border-radius:var(--radius-md)}
.decision-panel-title{font-weight:800;color:var(--text);font-size:13px}
.decision-panel-subtitle{font-size:11.5px;color:var(--muted);margin-top:3px}
.action-row{display:flex;gap:11px;align-items:flex-start;padding:10px 12px;border-bottom:1px solid var(--line-soft);font-size:12.5px;line-height:1.5}
.action-number{width:24px;height:24px;border-radius:7px;background:var(--blue-soft);color:var(--blue-strong);display:flex;align-items:center;justify-content:center;font-weight:800;flex:0 0 24px}
.action-row b{color:var(--text)}

/* ===== Chart shells ===== */
.chart-reading{margin:0 3px 10px;padding:9px 11px;border-radius:var(--radius-sm);background:var(--panel-2);border:1px solid var(--line);color:var(--muted);font-size:11.5px;line-height:1.45}
/* Estado vacío ("no hay datos suficientes para este gráfico") — antes era
   un st.info() genérico, la misma caja azul/gris para cualquier mensaje
   informativo. El borde punteado + ícono lo distingue de un aviso real
   (algo que SÍ pasó) de "acá simplemente no hay nada que mostrar todavía". */
.empty-state{display:flex;align-items:center;gap:11px;padding:16px 18px;margin:6px 0;
  border:1px dashed var(--line);border-radius:var(--radius-md);background:var(--panel-2);
  color:var(--muted);font-size:12.5px;line-height:1.5}
.empty-state .empty-icon{font-size:19px;flex:0 0 auto;opacity:.55}
.chart-card{background:var(--card-solid);animation:fadeUp .4s ease both;
  border:1px solid var(--line);border-radius:var(--radius-lg);padding:15px 17px 8px;margin:6px 0 16px;
  box-shadow:0 1px 2px rgba(20,26,43,.04),0 8px 22px rgba(20,26,43,.06),var(--glow-ring);overflow:hidden;
  transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
.chart-card:hover{box-shadow:0 14px 28px rgba(20,26,43,.09),var(--glow-ring);border-color:rgba(228,0,43,.18)}
.chart-card:before{content:"";display:block;width:26px;height:3px;border-radius:3px;background:linear-gradient(90deg,var(--blue),var(--teal));margin:0 0 10px 2px}
.chart-head{display:flex;justify-content:space-between;align-items:flex-start;padding:2px 3px 0}
.chart-title{font-size:15px;letter-spacing:-.01em;font-weight:750;color:var(--text)}
.chart-subtitle{font-size:11px;color:var(--muted);margin-top:3px}
.stPlotlyChart{margin-top:-3px}

/* ===== Tabs =====
   La fila de pestañas de nivel superior (Inicio/Asistente IA/Datos/.../
   Georeferenciación, la que arma grouped_nav() en app.py) es la ÚNICA
   `.stTabs` de toda la app que no vive anidada dentro de otra — por eso
   puede tener un estilo fijo propio sin afectar a las demás: SIEMPRE se
   renderiza justo debajo de la franja de foto (.block-container:before,
   arriba), nunca sobre un fondo plano normal.

   Primer intento (fondo transparente, solo texto blanco + text-shadow):
   se veía bien donde el velo de la franja está más cargado (izquierda),
   pero ese velo es un degradado diagonal que se desvanece a "transparent"
   hacia la derecha — justo donde vive la mayoría de las pestañas. Ahí el
   texto quedaba flotando sobre la foto sin ningún respaldo oscuro debajo,
   y un text-shadow no basta cuando detrás hay rojo saturado, no negro.
   Corrección: la píldora vuelve a tener su propio fondo, pero ahora fijo
   y oscuro semi-translúcido (no var(--panel-2) del tema, que era blanco
   en Claro) — un respaldo constante para el texto sin importar en qué
   punto del degradado de la franja caiga cada pestaña, dejando ver la
   foto de fondo a través suyo en vez de taparla del todo.

   Las pestañas ANIDADAS (dentro de otra pestaña, p. ej. las internas de
   Descripción) NUNCA están sobre la foto — más abajo, el bloque
   ".stTabs .stTabs" les devuelve explícitamente los colores normales del
   tema con selectores más específicos, así que este cambio no las toca. */
.stTabs [data-baseweb="tab-list"]{gap:6px;background:rgba(8,6,10,.62)!important;border:1px solid rgba(255,255,255,.09)!important;padding:6px;border-radius:999px;box-shadow:0 6px 18px rgba(0,0,0,.35)!important;overflow-x:auto}
.stTabs [data-baseweb="tab"]{height:40px;border-radius:999px;padding:0 18px;color:rgba(255,255,255,.86)!important;font-weight:700!important;font-size:13.5px;
  text-shadow:0 1px 4px rgba(0,0,0,.5);
  transition:background .15s ease,border-color .15s ease,color .15s ease,transform .15s ease,box-shadow .15s ease;
  background:transparent;border:1px solid transparent}
/* El color no se deja solo en `inherit` sobre <p> — se repite explícito en
   TODOS los descendientes (`*`), porque no hay forma de confirmar en este
   entorno qué elemento exacto envuelve el texto en cada versión de
   BaseWeb, y un solo selector que no acierte deja el texto invisible sin
   ningún aviso. Esto es más ancho de lo estrictamente necesario a
   propósito — mejor una regla de más que un texto ilegible. */
.stTabs [data-baseweb="tab"],.stTabs [data-baseweb="tab"] *{color:rgba(255,255,255,.86)!important;font-weight:700!important}
.stTabs [data-baseweb="tab"]:hover{background:rgba(255,255,255,.14);border-color:rgba(255,255,255,.22);transform:translateY(-1px)}
.stTabs [data-baseweb="tab"]:hover,.stTabs [data-baseweb="tab"]:hover *{color:#ffffff!important}
/* Pestaña seleccionada: no es un rectángulo rojo plano — el radial-gradient
   agrega un brillo/reflejo (como una píldora con volumen, no un color
   sólido) encima del degradado de marca, más el mismo --glow-ring que ya
   usan las tarjetas y los botones, para que se sienta parte del mismo
   lenguaje visual en vez de un elemento aparte. */
.stTabs [aria-selected="true"]{
  background:
    radial-gradient(circle at 28% 22%,rgba(255,255,255,.4),transparent 55%),
    linear-gradient(180deg,#ff3b4e,#e4002b)!important;
  border-color:transparent!important;color:#ffffff!important;
  box-shadow:0 4px 14px rgba(228,0,43,.35),var(--glow-ring)!important;
  transform:translateY(-1px);
}
.stTabs [aria-selected="true"]:hover{box-shadow:0 6px 18px rgba(228,0,43,.4),var(--glow-ring)!important}
.stTabs [aria-selected="true"],.stTabs [aria-selected="true"] *{color:#ffffff!important;font-weight:800!important}
.stTabs [data-baseweb="tab-highlight"]{display:none!important}
.stTabs [data-baseweb="tab-border"]{display:none!important}

/* Pestañas anidadas (una barra de pestañas que vive DENTRO de otra, p. ej.
   las pestañas internas de ui/dashboard.py — "📊 Visión general/🔍
   Diagnóstico/🌍 Geografía/🔗 Relaciones y detalle" — dentro de la pestaña
   "Descripción" de la fila principal) se ven más livianas que la barra de
   nivel superior — con el mismo estilo (píldora rellena + gradiente rojo)
   en los dos niveles, dos filas de pestañas apiladas se veían como dos
   elecciones de igual peso y no quedaba claro cuál era la sección y cuál
   la página dentro de ella. El selector ".stTabs .stTabs" alcanza
   cualquier nivel anidado sin tocar el Python de grouped_nav()/
   named_tabs() — es "una barra de pestañas dentro de otra", pase lo que
   pase cuántos niveles haya. La fila principal ya no tiene un segundo
   nivel propio (grouped_nav() ahora aplana sus grupos en una sola fila),
   pero esta regla se queda: sigue aplicando a cualquier vista que anide
   sus propias pestañas internamente. */
.stTabs .stTabs [data-baseweb="tab-list"]{
  background:transparent!important;border:none;box-shadow:none;border-radius:0;
  padding:0 0 2px;gap:20px;border-bottom:1px solid var(--line);
}
.stTabs .stTabs [data-baseweb="tab"]{height:34px;padding:0 2px;border-radius:0;font-size:12.5px;font-weight:650;text-shadow:none}
/* Estas SÍ viven sobre fondo normal del tema (nunca sobre la foto de
   arriba) — recuperan var(--muted)/sin sombra de texto por encima del
   texto claro fijo que la regla de nivel superior les habría heredado.
   Doble ".stTabs" pesa más que uno solo, así que esto gana sin necesitar
   tocar la regla de arriba. */
.stTabs .stTabs [data-baseweb="tab"],.stTabs .stTabs [data-baseweb="tab"] *{color:var(--muted)!important;font-weight:650!important;text-shadow:none}
.stTabs .stTabs [data-baseweb="tab"]:hover,.stTabs .stTabs [data-baseweb="tab"]:hover *{background:transparent;color:var(--blue-strong)!important}
.stTabs .stTabs [aria-selected="true"]{
  background:transparent!important;box-shadow:none!important;
  border-bottom:2px solid var(--blue)!important;
}
.stTabs .stTabs [aria-selected="true"],.stTabs .stTabs [aria-selected="true"] *{color:var(--text)!important;font-weight:800!important}

/* ===== Buttons: quiet by default, only primary CTAs carry visual weight.
   Border uses --soft (not the fainter --line used for dividers/cards) so a
   secondary button always reads as a button against its own panel-colored
   background, in both themes — not just on hover. Every button now has a
   little real depth at rest (a soft shadow, not "box-shadow:none" like
   before) plus a lift-on-hover/press-on-active motion — the same
   language the KPI/chart cards already use (--glow-ring), so a button
   doesn't feel like a flatter, older element sitting next to them. */
.stButton>button,[data-testid="stDownloadButton"] button,[data-testid="stFormSubmitButton"] button{
  min-height:40px;padding:0 18px;background:var(--panel);color:var(--muted);
  border:1px solid var(--soft);border-radius:11px;font-weight:650;font-size:13.5px;
  box-shadow:0 1px 2px rgba(20,26,43,.05),0 2px 6px rgba(20,26,43,.04);
  transition:border-color .12s ease,color .12s ease,background .12s ease,transform .12s ease,box-shadow .12s ease;
}
.stButton>button:hover,[data-testid="stDownloadButton"] button:hover,[data-testid="stFormSubmitButton"] button:hover{
  border-color:var(--blue);color:var(--blue-strong);background:var(--blue-soft);
  transform:translateY(-1px);box-shadow:0 6px 14px rgba(20,26,43,.09),var(--glow-ring);
}
.stButton>button:active,[data-testid="stDownloadButton"] button:active{transform:translateY(0) scale(.98)}
/* Pressed state for the plain/secondary and form-submit buttons — explicit
   (not just inherited via :hover) so a touch tap without a hover state
   still shows a clear "this was clicked" color, not just the scale. The
   download button keeps its own hover-driven solid-blue treatment below,
   so it's excluded here to avoid the click briefly dimming it back to the
   soft tint. */
.stButton>button:active,[data-testid="stFormSubmitButton"] button:active{
  border-color:var(--blue);color:var(--blue-strong);background:var(--blue-soft);
}
button[kind="primary"],[data-testid="stDownloadButton"] button[kind="primary"]{
  background:linear-gradient(180deg,#ff3b4e,#e4002b)!important;border-color:#e4002b!important;color:#fff!important;
  font-weight:750!important;box-shadow:0 4px 12px rgba(228,0,43,.25),var(--glow-ring)!important;
  transition:transform .12s ease,box-shadow .12s ease,background .12s ease!important;
}
button[kind="primary"]:hover,[data-testid="stDownloadButton"] button[kind="primary"]:hover{
  background:linear-gradient(180deg,#ff5464,#e4002b)!important;color:#fff!important;
  transform:translateY(-1px);box-shadow:0 8px 20px rgba(228,0,43,.32),var(--glow-ring)!important;
}
button[kind="primary"]:active,[data-testid="stDownloadButton"] button[kind="primary"]:active{transform:translateY(0) scale(.98)!important}
/* Secondary/download buttons that are still an important action (exports)
   get a subtle brand-tinted outline so they read as "do this" without
   competing with the one true primary action on screen. */
[data-testid="stDownloadButton"] button{border-color:var(--blue);color:var(--blue-strong);background:var(--blue-soft);box-shadow:0 1px 2px rgba(20,26,43,.05),0 2px 8px rgba(228,0,43,.1)}
[data-testid="stDownloadButton"] button:hover{background:var(--blue);color:#fff;border-color:var(--blue);transform:translateY(-1px);box-shadow:0 6px 16px rgba(228,0,43,.22),var(--glow-ring)}
section[data-testid="stSidebar"] [data-testid="stDownloadButton"] button{background:var(--sidebar-panel);color:var(--blue);border-color:rgba(228,0,43,.4)}
section[data-testid="stSidebar"] [data-testid="stDownloadButton"] button:hover{background:rgba(228,0,43,.18);color:var(--sidebar-text-strong);transform:translateY(-1px)}

/* ===== Native inputs: keep readable on a light surface, with a real visible border ===== */
input,textarea{color:var(--text)!important;background:var(--panel)!important;border:1px solid var(--line)!important;transition:border-color .15s ease,box-shadow .15s ease}
input:focus,textarea:focus{border-color:rgba(228,0,43,.45)!important;box-shadow:0 0 0 3px rgba(228,0,43,.08)!important}
input::placeholder,textarea::placeholder{color:var(--soft)!important;opacity:1!important}
[data-baseweb="select"]>div{background:var(--panel)!important;border:1px solid var(--line)!important;color:var(--text)!important;border-radius:9px!important}
[data-baseweb="select"] *{color:var(--text)!important}
/* El desplegable de opciones (selectbox/multiselect) se abre en un
   "portal": React lo saca del árbol normal del documento y lo cuelga
   aparte (típicamente de <body>), así que NO es descendiente de
   [data-baseweb="select"] ni de section[data-testid="stSidebar"] aunque
   visualmente aparezca pegado a ellos — las reglas de arriba (y las del
   sidebar, más abajo) nunca lo alcanzan. Necesita sus propias reglas
   globales, cubriendo varios nombres de contenedor porque BaseWeb no usa
   siempre el mismo atributo para la lista de opciones entre versiones —
   y `!important` en cada uno, porque BaseWeb trae su propio tema por
   defecto (claro) con el peso suficiente para ganarle a una regla sin él;
   sin esto, el desplegable se queda con su blanco de fábrica encima de
   una app en Modo Oscuro, con texto que casi no se distingue. */
[data-baseweb="popover"],[data-baseweb="menu"],ul[role="listbox"]{background:var(--panel)!important;border:1px solid var(--line)!important;box-shadow:var(--shadow-md)!important}
[data-baseweb="popover"] *,[data-baseweb="menu"] *,ul[role="listbox"] *{color:var(--text)!important;background:transparent!important}
[data-baseweb="menu"] li:hover,li[role="option"]:hover{background:var(--panel-2)!important}
.stMultiSelect [data-baseweb="tag"]{background:var(--blue-soft)!important}
.stMultiSelect [data-baseweb="tag"] span{color:var(--blue-strong)!important}
label,p,li,span,div{scrollbar-color:#c7cedb #eef1f6}
[data-testid="stMarkdownContainer"] p,[data-testid="stMarkdownContainer"] li{color:inherit}
[data-testid="stFileUploaderDropzone"]{background:var(--panel-2)!important;border:1px dashed var(--line)!important;border-radius:var(--radius-md)!important}
.stFileUploader label{color:var(--text)!important}
.stFileUploader small{color:var(--muted)!important}

/* ===== Expanders: the main progressive-disclosure mechanism ===== */
[data-testid="stExpander"]{background:var(--panel)!important;border:1px solid var(--line)!important;border-radius:var(--radius-md)!important;box-shadow:var(--shadow-sm)!important;margin-bottom:10px}
.streamlit-expanderHeader,[data-testid="stExpander"] summary{color:var(--text)!important;background:var(--panel)!important;font-weight:750!important;border-radius:var(--radius-md)!important}
[data-testid="stExpander"] summary:hover{color:var(--blue)!important}
[data-testid="stExpander"] summary svg{color:var(--blue)!important}

[data-testid="stAlert"]{background:var(--panel)!important;color:var(--text)!important;border:1px solid var(--line)!important;border-radius:var(--radius-sm)!important}
.stCaption,[data-testid="stCaptionContainer"]{color:var(--muted)!important}
.stDataFrame,[data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:var(--radius-md);overflow:hidden}
[data-testid="stMetric"]{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-sm);padding:12px 14px;box-shadow:var(--shadow-sm)}
[data-testid="stMetricLabel"]{color:var(--muted)!important;font-size:11px!important}
[data-testid="stMetricValue"]{color:var(--text)!important;font-size:22px!important;font-variant-numeric:tabular-nums}

/* ===== Executive / alerts / why-changed / factors ===== */
.executive-card{padding:19px 21px;border:1px solid var(--line);border-radius:var(--radius-lg);background:var(--panel);box-shadow:var(--shadow-md),var(--glow-ring);border-left:5px solid var(--blue);margin:4px 0 10px;animation:fadeUp .4s ease both}
.executive-card.positive{border-left-color:var(--green)}
.executive-card.negative{border-left-color:var(--red)}
.executive-status{font-size:10px;text-transform:uppercase;letter-spacing:.11em;font-weight:800;color:var(--soft)}
.executive-headline{font-size:21px;font-weight:800;color:var(--text);margin-top:6px}
.executive-detail{font-size:12.5px;color:var(--muted);margin-top:7px;line-height:1.5}
.mini-list{padding:9px 12px;background:var(--panel-2);border:1px solid var(--line);border-radius:var(--radius-sm);color:var(--text);font-weight:700}
.mini-positive,.mini-warning{margin-top:6px;padding:9px 11px;border-radius:var(--radius-sm);font-size:12.5px}
.mini-positive{color:var(--green-strong);background:var(--green-soft);border-left:3px solid var(--green)}
.mini-warning{color:var(--amber-strong);background:var(--amber-soft);border-left:3px solid var(--amber)}
.alert-row{display:flex;gap:12px;align-items:flex-start;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-md);padding:12px 14px;margin-bottom:8px;box-shadow:var(--shadow-sm)}
.alert-row.warning{border-left:4px solid var(--amber)}
.alert-row.positive{border-left:4px solid var(--green)}
.alert-severity{font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.07em;color:var(--soft);min-width:60px}
.alert-row b{color:var(--text)}
.alert-row div div{font-size:12.5px;color:var(--muted);margin-top:3px}
.alert-row small{display:block;color:var(--soft);margin-top:6px;line-height:1.4}
.why-card{background:var(--panel-2);border:1px solid var(--line);border-radius:var(--radius-md);padding:15px 18px;margin-bottom:10px}
.why-title{font-size:16px;color:var(--text);font-weight:750}
.why-subtitle{font-size:11px;color:var(--muted);margin-top:4px}
.factor-card{padding:12px;border:1px solid var(--line);border-radius:var(--radius-sm);background:var(--panel);display:flex;flex-direction:column;gap:4px;box-shadow:var(--shadow-sm)}
.factor-card span{font-size:18px;font-weight:800}
.factor-card.positive span{color:var(--green)}
.factor-card.negative span{color:var(--red)}
.factor-card small{color:var(--muted)}

/* ===== Catalog ===== */
.catalog-card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-lg);padding:16px 17px;margin:6px 0 14px;box-shadow:var(--shadow-sm);min-height:190px}
.catalog-card-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;border-bottom:1px solid var(--line-soft);padding-bottom:10px;margin-bottom:9px}
.catalog-title{font-size:16px;font-weight:800;color:var(--text);line-height:1.25}
.catalog-subtitle{font-size:11px;color:var(--muted);margin-top:5px;line-height:1.4}
.catalog-price{font-size:20px;font-weight:850;color:var(--blue);white-space:nowrap}
.catalog-card ul{margin:0;padding-left:18px;color:var(--text);font-size:12px;line-height:1.55}
.catalog-card li{margin:4px 0}

/* ===== Universal analysis / drill-down ===== */
.drilldown-card{background:var(--card-solid);
  border:1px solid var(--line);border-radius:var(--radius-md);padding:12px 14px;
  box-shadow:0 1px 2px rgba(20,26,43,.04),0 6px 16px rgba(20,26,43,.05);
  transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
.drilldown-card:hover{transform:translateY(-2px);box-shadow:0 14px 28px rgba(228,0,43,.10);border-color:rgba(228,0,43,.22)}
.alert-row.compact{padding:10px 12px;margin-bottom:6px}
.analysis-note{font-size:11.5px;color:var(--muted);margin:4px 0 8px}

/* ===== Comparison panel ===== */
.comparison-panel{margin:10px 0 8px;padding:12px 14px;border:1px solid var(--line);border-left:3px solid var(--blue);border-radius:var(--radius-sm);background:var(--blue-soft);color:var(--text)}
.comparison-panel b{color:var(--text);display:block;margin-bottom:3px}

/* ===== Mode banner: compact two-line block, never wraps awkwardly ===== */
.mode-banner{margin:8px 0 8px;padding:10px 14px;border:1px solid var(--line);border-radius:var(--radius-md);background:var(--blue-soft);color:var(--text);font-size:13px;line-height:1.5}
.mode-banner-label{font-size:9.5px;font-weight:800;letter-spacing:.09em;color:var(--muted)}
.mode-banner b{color:var(--text)}
.mode-confidence{font-size:10.5px;font-weight:700;color:var(--muted);background:var(--panel);border-radius:999px;padding:2px 8px;white-space:nowrap}

/* ===== Accessibility ===== */
button:focus-visible,input:focus-visible,textarea:focus-visible,[role="tab"]:focus-visible{outline:2px solid var(--blue)!important;outline-offset:2px}
button:disabled{color:var(--soft)!important;background:var(--panel-2)!important;border-color:var(--line)!important}

/* ===== Analysis toolbar (Power BI-style report canvas header) ===== */
.analysis-toolbar{
  position:relative;overflow:hidden;display:flex;align-items:flex-end;justify-content:space-between;gap:22px;
  margin:24px 0 14px;padding:18px 20px;border:1px solid var(--line);border-radius:var(--radius-lg);
  background:var(--panel);box-shadow:var(--shadow-md);
}
.analysis-toolbar:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:linear-gradient(180deg,var(--blue),var(--teal))}
.analysis-toolbar h2{margin:4px 0 3px;font-size:20px;font-weight:800;letter-spacing:-.02em}
.analysis-toolbar p{margin:0;color:var(--muted);font-size:11.5px}
.analysis-toolbar-meta{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:7px}
.analysis-toolbar-meta span{padding:7px 10px;border:1px solid var(--line);border-radius:999px;background:var(--panel-2);color:var(--muted);font-size:10px;font-weight:700}
.analysis-section-title{margin-top:16px}
.analysis-section-title .data-badge{align-self:center}

/* ===== pbi-visual: chart card variant used in the analysis area ===== */
.pbi-visual{background:var(--card-solid);animation:fadeUp .4s ease both;
  border:1px solid var(--line);border-radius:13px;padding:12px 13px 9px;
  box-shadow:0 1px 2px rgba(20,26,43,.04),0 8px 20px rgba(20,26,43,.055),var(--glow-ring);
  transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
.pbi-visual:hover{box-shadow:0 14px 28px rgba(228,0,43,.10),var(--glow-ring);border-color:rgba(228,0,43,.2)}
.pbi-visual:before{width:22px;height:3px;margin-bottom:8px;background:linear-gradient(90deg,var(--blue),var(--teal))}
.pbi-visual .chart-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;min-height:42px;padding:0 3px 2px}
.pbi-visual .chart-head-main{min-width:0}
.pbi-visual .visual-type{display:block;color:var(--blue);font-size:8px;font-weight:800;letter-spacing:.15em;margin-bottom:4px}
.pbi-visual .chart-title{font-size:14px;font-weight:800;line-height:1.2}
.pbi-visual .chart-subtitle{font-size:10px;color:var(--muted);margin-top:3px;line-height:1.35}
.pbi-visual .visual-badge{white-space:nowrap;margin-top:1px;background:var(--panel-2);color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:5px 8px;font-size:8px}
.pbi-visual .chart-reading{margin-top:4px;font-size:10.5px}
[data-testid="stHorizontalBlock"]:has(.pbi-visual){align-items:stretch}

@media (max-width:900px){
 .block-container{padding-left:.8rem;padding-right:.8rem}
 [data-testid="stMain"] .block-container:has(.hero-band):before{height:360px}
 .hero{padding:20px}.hero h1{font-size:23px}
 .analysis-toolbar{align-items:flex-start;flex-direction:column;padding:15px 16px}
 .analysis-toolbar-meta{justify-content:flex-start}
 .pbi-visual .visual-badge{display:none}
 .kpi-card{min-height:100px!important}
}

/* Quien tenga activado "reducir movimiento" a nivel de sistema operativo
   no pidió ver nada moviéndose — ni las animaciones de entrada de arriba
   ni ningún hover/transición de toda la hoja de estilos. Estándar de
   accesibilidad, no algo específico de esta app. */
@media (prefers-reduced-motion:reduce){
  *{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}
}
</style>
"""


def components_css() -> str:
    """Clases estáticas (no dependen de dark/light). Sustituye, sobre el
    texto literal de arriba, los valores que estaban duplicados en varios
    sitios por los tokens ya definidos en `:root` — mismo resultado
    computado, una sola fuente para cada valor."""
    css = _COMPONENTS_CSS_RAW
    css = css.replace(
        "font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
        "font-family:var(--font-sans)",
    )
    css = css.replace(
        "font-family:'Sora','Inter',sans-serif",
        "font-family:var(--font-display)",
    )
    css = css.replace(
        "background:radial-gradient(circle at 32% 28%,#ff4d4d,#e4002b 55%,#a80e1f 100%);",
        "background:var(--brand-orb);",
    )
    css = css.replace(
        "@media (max-width:900px){",
        f"@media (max-width:{BREAKPOINT_CONTENT}px){{",
    )
    # Marcador de texto, no f-string: _COMPONENTS_CSS_RAW tiene decenas de
    # llaves {} de selectores propias (mismo motivo que ui/login.py) — un
    # solo .replace() al final evita escaparlas todas a mano.
    css = css.replace("__HERO_BG__", image_data_uri("ciudad_red.jpg"))
    return css


def inject_theme(dark: bool) -> None:
    """Punto de entrada único: inyecta el tema completo (tokens + clases).
    Sustituye a los dos `st.markdown(...)` que antes vivían inline en
    `app.py`."""
    st.markdown(base_layer_css(dark), unsafe_allow_html=True)
    st.markdown(components_css(), unsafe_allow_html=True)
