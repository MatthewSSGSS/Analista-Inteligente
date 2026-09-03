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

from ui.assets import image_data_uri, background_data_uri

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
    valor en los dos temas.

    Los `--*-soft` de Oscuro eran `rgba(...,.14)` — translúcidos de
    verdad, no un color plano: se mezclaban con lo que hubiera detrás
    (glassmorphism, literal). En Claro esto nunca fue un problema porque
    esos mismos tokens ya eran hex opacos (`#fde8ea` etc.) — la
    inconsistencia era solo de Oscuro. Los valores de abajo son el
    resultado de componer cada rgba(...,.14) sobre `--panel` (#161b22): el
    mismo tinte de color, a simple vista indistinguible del original, pero
    ahora un color plano — sólido y opaco de verdad, para que cualquier
    tarjeta/panel que lo use quede separada del fondo con texto legible,
    sin importar qué haya detrás (incluida la foto del header)."""
    if dark:
        return """
  --bg:#0d1117;--panel:#161b22;--panel-2:#1c2129;--panel-3:#222833;
  --text:#e6e9ef;--muted:#9aa4b2;--soft:#7b8592;--line:#2a313d;--line-soft:#232a34;
  --blue:#ff3b52;--blue-soft:#372129;--blue-strong:#ff6b7a;
  --teal:#2dd4c8;--teal-soft:#193539;
  --green:#3ecf8e;--green-soft:#1c3431;--green-strong:#3ecf8e;
  --amber:#f0a63e;--amber-soft:#352e26;--amber-strong:#f0a63e;
  --red:#ff5570;--red-soft:#37232d;--purple:#9b8cf2;--purple-soft:#292b3f;
  --card-solid:#161b22;
  --glow-ring:0 0 0 1px rgba(255,59,82,.32),0 0 26px rgba(255,59,82,.24);
  --overlay-veil:rgba(13,17,23,.22);
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
  --overlay-veil:rgba(255,255,255,.20);
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
/* ===== PASO 1 de la nueva foto de fondo general (pidió explícitamente NO
   preocuparse todavía por legibilidad — eso es el paso siguiente).

   Va en [data-testid="stAppViewContainer"], no en .block-container: ese
   último solo mide lo que mide su contenido (por eso los intentos
   anteriores dejaban la foto como una franja arriba); stAppViewContainer
   es el contenedor de más afuera, cubre sidebar + contenido a pantalla
   completa. background-attachment:fixed la deja quieta al hacer scroll
   sin importar qué tan largo sea el contenido de abajo.

   !important en cada propiedad porque esta MISMA regla ya existe una vez
   en base_layer_css() (el degradado rojo sutil + color sólido de fondo,
   ver _bg_gradient()) — ese bloque se inyecta ANTES que este
   (inject_theme() llama primero base_layer_css(), después
   components_css()), así que en igualdad de !important, este gana por
   orden de aparición. No se borró esa regla vieja: se queda ahí, por si
   en algún momento se quita esta foto y hay que volver al fondo anterior. */
[data-testid="stAppViewContainer"]{
  background-image:url("__APP_BG__")!important;
  background-size:cover!important;
  background-position:center!important;
  background-attachment:fixed!important;
  background-repeat:no-repeat!important;
}
/* ===== PASO 2 → PASO 3: este velo empezó como el mecanismo PRINCIPAL de
   legibilidad (88%/90% de opacidad, tapaba casi toda la foto). Cambio de
   estrategia explícito: ahora la legibilidad la da que cada bloque de
   contenido tenga su propia caja opaca (ver .hero-band, .section-intro,
   tarjetas, tablas, expanders... más abajo) — este velo baja a un tinte
   MUY sutil (22%/20%, tope pedido de 0.25) solo para unificar un poco el
   tono de la foto con la paleta de la app, sin taparla. `var(--overlay-veil)`
   sigue definido por tema en _theme_vars() (arriba), mismo mecanismo,
   valores nuevos.

   `position:fixed;inset:0` en vez de absolute: no depende de que
   stAppViewContainer tenga position propio, siempre cubre el viewport
   completo. z-index:0 (no negativo) + `> *{position:relative;z-index:1}`
   en la regla de abajo: dos elementos EXPLÍCITAMENTE comparados por
   z-index (1 gana a 0) es más confiable aquí que apoyarse en que los
   hijos de stAppViewContainer sean o no positioned por su cuenta — con
   z-index negativo en el ::before, esa comparación habría dependido de
   si el sidebar/main ya eran positioned o no (no lo son por defecto), y
   se corría el riesgo de que el velo terminara TAPANDO el contenido en
   vez de quedar detrás. `pointer-events:none` para que la capa no
   bloquee clics en nada de lo que hay debajo. */
[data-testid="stAppViewContainer"]::before{
  content:"";position:fixed;inset:0;
  background:var(--overlay-veil);
  z-index:0;pointer-events:none;
}
[data-testid="stAppViewContainer"]>*{position:relative;z-index:1}
/* El header nativo de Streamlit (arriba del todo) tenía fondo sólido
   opaco (regla de arriba, `[data-testid="stHeader"]{background:var(--bg)
   !important}`) — se vuelve transparente aquí, DESPUÉS de esa regla en el
   mismo bloque de texto (misma especificidad + !important en ambas: gana
   la que aparece después), para que se vea la foto detrás. Esto
   CONTRADICE a propósito una decisión de una tarea anterior ("nada de
   glassmorphism", header opaco) — es la primera mitad de un cambio de
   diseño que el usuario pidió hacer en dos pasos: primero que la foto se
   vea en toda la app (este paso, sin preocuparse por legibilidad),
   después arreglar el contraste del texto encima suyo (paso siguiente,
   todavía no hecho). */
[data-testid="stHeader"]{background:rgba(0,0,0,0)!important}
/* LA CAUSA REAL de que la foto solo se viera en la franja de arriba: esta
   MISMA regla (arriba del todo, dentro de base_layer_css()) le pone un
   fondo SÓLIDO Y OPACO — no solo a stAppViewContainer, al mismo tiempo
   también a [data-testid="stMain"], [data-testid="stMainBlockContainer"]
   (= .block-container) y .main — con !important:

     html,body,[data-testid="stAppViewContainer"],[data-testid="stApp"],
     [data-testid="stMain"],[data-testid="stMainBlockContainer"],.main,
     .stAppViewContainer{background:<gradiente rojo>,#ffffff!important;...}

   stMain/.block-container/.main viven DENTRO de stAppViewContainer y
   cubren casi toda el área de contenido de arriba a abajo — aunque a
   stAppViewContainer ya se le puso la foto (regla de más arriba), ese
   fondo opaco de sus hijos la tapaba por completo en cuanto se salía de
   los ~300px de la franja del hero (la única zona con algo pintado
   ENCIMA de ese opaco: el ::before de .block-container:has(.hero-band),
   más abajo en este archivo, que sí se alcanza a ver porque se pinta
   después del propio fondo de .block-container). De ahí para abajo, puro
   blanco/negro opaco — exactamente el síntoma reportado.

   Arreglo: estos 3 selectores (NO stAppViewContainer, ese sí debe quedarse
   con la foto) pasan a transparent!important, para que la foto de
   stAppViewContainer se vea a través suyo en TODA la altura. El sidebar
   tiene su .block-container propio y también queda transparent con esta
   regla — no es un problema: section[data-testid="stSidebar"] ya tiene su
   propio fondo opaco (más abajo, sin tocar), así que se sigue viendo
   sólido igual que antes, nada por detrás lo atraviesa. */
[data-testid="stMain"],[data-testid="stMainBlockContainer"],.main,.block-container{background:transparent!important}
.stApp{background:var(--bg);color:var(--text)}
* {font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.block-container{max-width:1540px;padding:1.1rem 1.2rem 4rem;position:relative;z-index:0}
/* ===== Contenedor principal (todo lo que va a la derecha del sidebar):
   antes tenía un tope fijo de 1540px heredado del `.block-container` de
   arriba — en un monitor de escritorio normal (1920px+) eso dejaba
   franjas vacías grandes a los lados y hacía sentir el dashboard como una
   página web angosta, no como una app de escritorio.

   Va en un selector aparte, prefijado con `[data-testid="stMain"]`, en
   vez de tocar la regla `.block-container` de arriba directamente: el
   sidebar TIENE su propio `.block-container` (ver
   `section[data-testid="stSidebar"] .block-container` más abajo, sin
   tocar) y un `max-width:100%`/`min-height:100vh` puesto en el selector
   genérico se habría colado ahí también. Con este prefijo, el tope de
   1540px de la regla de arriba se queda intacto para el sidebar (no le
   afecta en la práctica — su ancho real lo define el propio panel de
   Streamlit, no este max-width — pero así queda explícitamente sin
   tocar) y solo el contenido principal gana el ancho completo. */
[data-testid="stMain"] .block-container{width:100%!important;max-width:100%!important;min-height:100vh}
/* Espacio vertical ENTRE elementos del contenido principal (el "hueco" que
   Streamlit deja por defecto entre cada st.markdown/gráfico/tabla propios,
   no el padding interno de cada tarjeta — eso no se toca aquí). El
   sidebar ya tenía su propia reducción (`gap:.5rem`, ver más abajo); el
   contenido principal no tenía ninguna, así que se apoyaba en el valor
   por defecto de Streamlit, más grande de lo necesario. */
[data-testid="stMain"] [data-testid="stVerticalBlock"]{gap:.75rem}
/* ===== Filas de tarjetas/KPIs (kpi_grid(), y cualquier fila de 3+
   st.columns() usada para tarjetas — Resumen ejecutivo, Descripción,
   Georeferenciación, Inicio, Comparar personas, Calidad...): Streamlit las
   arma como columnas de ancho fijo entre sí (flex, sin wrap), así que en
   pantalla angosta se aprietan hasta verse minúsculas, y en pantalla ancha
   simplemente se estiran sin ganar densidad visual real (eso ya lo
   resuelven los clamp() de cada tarjeta, arriba). Este selector las
   convierte en una grilla flexible tipo CSS Grid/minmax: cada tarjeta
   pide un ancho "cómodo" (el segundo valor de clamp) pero puede encogerse
   hasta un mínimo legible o envolver a la fila siguiente si no caben —
   eso es el breakpoint responsive, continuo en vez de un punto de quiebre
   fijo. Solo apunta a filas de 3 COLUMNAS O MÁS (`:has(> ... :nth-child(3))`)
   para no tocar los layouts de 2 columnas con proporciones intencionales
   (contenido principal + panel lateral, botón + descripción, etc.) — esos
   ya funcionan bien y no son "una fila de tarjetas". */
[data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(3)){
  flex-wrap:wrap;row-gap:clamp(10px,1vw,20px);
}
[data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(3)) > [data-testid="stColumn"]{
  flex:1 1 clamp(215px,22vw,360px);min-width:0;
}
@media (max-width:640px){
  [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(3)) > [data-testid="stColumn"]{
    flex-basis:100%;
  }
}
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
/* La barra nativa de Streamlit (arriba del todo, íconos de compartir/menú)
   tenía un fondo translúcido con blur — glassmorphism real. En la
   práctica ya perdía siempre contra la regla `!important` de más arriba
   (`[data-testid="stHeader"]{background:var(--bg)!important}`), así que
   era peso muerto sin efecto visible, pero se deja explícita y sólida
   para que no quede ningún rastro de transparencia en el código. */
header[data-testid="stHeader"]{background:var(--bg)!important}
h1,h2,h3,h4,h5,h6{color:var(--text);font-family:'Sora','Inter',sans-serif;letter-spacing:-.01em}
p,span,div,li,label{color:var(--text)}

/* ===== Sidebar: nav rail with its own surface tokens (--sidebar-*), navy in
   Dark Mode and off-white in Light Mode — same tokens, values swapped in
   _sidebar_vars() so this block never needs to know which mode is active.

   Ancho: antes no tenía ninguna regla propia, así que usaba el ancho por
   defecto/redimensionable de Streamlit (bastante más ancho de lo que su
   contenido — un logo, dos botones de tema, un dropdown, filtros — de
   verdad necesita). 270px alcanza para que el rango de fechas
   ("2025/01/01 – 2025/06/30") y el nombre del archivo sigan leyéndose sin
   verse forzados, dejando el resto de la pantalla para el contenido
   principal. Todo el contenido sigue siendo el mismo — nada se quitó ni
   se reordenó, solo el ancho del panel que lo contiene. Con !important
   porque Streamlit redimensiona el sidebar con su propio estilo inline;
   esto también fija el ancho, así que el tirador para arrastrarlo y
   cambiarlo a mano deja de tener efecto. */
section[data-testid="stSidebar"]{width:270px!important;min-width:270px!important;max-width:270px!important;background:var(--sidebar-bg)!important;border-right:1px solid var(--sidebar-line)!important}
section[data-testid="stSidebar"]>div{width:270px!important}
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
/* var(--blue-soft), no un rgba() propio — mismo motivo que el mode-banner
   de más arriba: mismo tinte, ya opaco. El borde se queda translúcido
   (no afecta legibilidad del texto de adentro). */
section[data-testid="stSidebar"] .stMultiSelect span[data-baseweb="tag"]{background:var(--blue-soft)!important;border:1px solid rgba(228,0,43,.4)!important}
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
/* var(--blue-soft), no un rgba() propio: mismo tinte, pero ya sólido y
   opaco (ver la nota sobre los tokens --*-soft en _theme_vars) — el
   borde sí se queda translúcido, un borde con transparencia no afecta
   la legibilidad del texto de adentro como sí lo hace un fondo. */
section[data-testid="stSidebar"] .mode-banner{background:var(--blue-soft);border:1px solid rgba(228,0,43,.4);color:var(--sidebar-text-strong)}
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

/* ===== Hero / page header =====
   Era transparente + un borde inferior fino (pensado para fondo plano
   normal). Con la foto ahora detrás de TODA la app (.block-container es
   transparent!important en toda vista, no solo en el header), cualquier
   .hero — incluido el de ui/tracking.py, que nunca llevó .hero-band —
   necesita su propia caja opaca igual que las demás. */
.hero{padding:12px 20px;margin:0 0 14px;border:1px solid var(--line);background:var(--card-solid);
  box-shadow:var(--shadow-md);border-radius:var(--radius-lg)}
.hero h1{margin:0;font-size:20px;font-weight:800;letter-spacing:-.01em;color:var(--text)}
.hero p{color:var(--muted);margin:4px 0 0;font-size:12.5px;max-width:900px}
/* El hero que se sienta sobre la franja de foto (.block-container:before,
   .st-key-home_hero_band) usaba texto blanco fijo + text-shadow porque el
   texto flotaba directo sobre la foto, sin nada opaco detrás. Cambio de
   estrategia: ahora es una caja sólida propia (fondo del tema, borde,
   sombra) — vuelve a var(--text)/var(--muted) normales, como cualquier
   .hero, porque ya no hay foto directamente detrás del texto, hay esta
   caja. La foto sigue viéndose alrededor, en el espacio que la caja no
   ocupa (ese "aire" es justo lo que se pidió). */
.hero-band{border-bottom:none;background:var(--card-solid);border:1px solid var(--line);
  border-radius:var(--radius-lg);padding:14px 22px;box-shadow:var(--shadow-md)}
.hero-band h1{color:var(--text)!important;text-shadow:none}
.hero-band p{color:var(--muted)!important;text-shadow:none}
.hero-band-meta{background:var(--card-solid);border:1px solid var(--line);border-radius:var(--radius-sm);
  padding:8px 14px;color:var(--text)!important;text-shadow:none;font-size:13.5px;margin:10px 0}
.hero-band-meta b{color:var(--text)!important}

/* ===== Section headers: bold title with a quiet subtitle directly beneath =====
   Antes flotaba suelto sobre el fondo (sin caja) — con la foto detrás de
   TODA la app (no solo el header), un título de sección sin nada opaco
   detrás quedaba directo sobre la imagen. Caja sólida propia, más angosta
   que una tarjeta normal (menos padding vertical) porque es solo un
   título, no un bloque de contenido. */
.section-intro{display:flex;align-items:flex-start;justify-content:space-between;margin:22px 0 10px;flex-wrap:wrap;gap:8px;
  background:var(--card-solid);border:1px solid var(--line);border-radius:var(--radius-md);
  padding:11px 16px;box-shadow:var(--shadow-sm)}
.section-intro.compact{margin-top:22px}
.section-intro h2{margin:0;font-size:17px;font-weight:800;letter-spacing:-.01em;color:var(--text)}
.eyebrow{display:none}
.data-badge{font-size:10.5px;font-weight:700;color:var(--red);background:none;border:none;padding:0;box-shadow:none;text-transform:uppercase;letter-spacing:.05em}

/* ===== View banner: encabezado de vista (ui/components/section.py ::
   banner_header) — usado en Resumen ejecutivo, Georeferenciación,
   Asistente IA, Descripción, Comparativa, Varias hojas.

   ANTES tenía su propia foto (una de las 4 de assets/images/) con un velo
   oscuro y texto blanco fijo encima — un tercer sistema de imagen,
   redundante ahora que TODA la app ya tiene la foto general de fondo
   (stAppViewContainer) detrás. Pedido explícito: "quita la imagen que se
   sobrepone, solo deja el fondo" — banner_header() en Python SIGUE
   pasando `image=...` en cada llamada (no se tocó esa función, para no
   romper nada), pero acá se ignora a propósito: `background-image:none
   !important` le gana al `style="background-image:url(...)"` inline que
   ese Python todavía genera. El resultado es una caja sólida normal,
   igual que .section-intro/.hero — el texto vuelve a var(--text)/
   var(--muted) normales, ya no hace falta blanco fijo ni text-shadow
   porque ya no hay foto directamente detrás. */
.view-banner{position:relative;border-radius:var(--radius-lg);overflow:hidden;margin:4px 0 22px;
  height:112px;background-image:none!important;background:var(--card-solid);
  border:1px solid var(--line);animation:fadeUp .4s ease both;
  box-shadow:0 1px 2px rgba(20,26,43,.04),0 8px 20px rgba(20,26,43,.06),var(--glow-ring)}
.view-banner:before{content:"";position:absolute;inset:0;background:none}
.view-banner-content{position:relative;z-index:1;height:100%;display:flex;flex-direction:column;justify-content:center;padding:0 26px}
.view-banner h2{margin:0;font-size:21px;font-weight:800;letter-spacing:-.01em;color:var(--text);text-shadow:none}
.view-banner p{margin:5px 0 0;font-size:12px;color:var(--muted);max-width:600px;line-height:1.5;text-shadow:none}
@media(max-width:900px){.view-banner{height:130px}.view-banner-content{justify-content:flex-end;padding:0 18px 14px}}

/* ===== Franja de foto propia de Inicio (ui/home.py): extiende la misma
   foto/velo de la franja compartida de arriba, pero SOLO por el alto del
   hero de bienvenida + la fila de 4 tarjetas "Qué se cargó" — no la
   fila de tarjetas completa de la pestaña. `st.container(key="home_hero_
   band")` (Streamlit ≥1.36) envuelve exactamente ese tramo con una clase
   estable (`st-key-home_hero_band`), así que este fondo puede ir
   directo en el propio contenedor (no hace falta el truco de ::before con
   z-index negativo de la franja de arriba — acá el texto blanco SÍ es
   descendiente real de este mismo elemento, no un hermano flotando al
   lado). Es un container SEPARADO de la franja compartida (no la misma
   alargada) a propósito: la franja de arriba vive una sola vez en
   .block-container y la comparten TODAS las pestañas — alargarla ahí
   habría puesto esta misma foto detrás de Resumen ejecutivo, Descripción,
   etc., cuyo texto no está preparado para eso. Con un container propio,
   el efecto queda contenido 100% a Inicio.

   El alto no es un número fijo — crece con el padding + el contenido de
   adentro (hero + fila de tarjetas), así que termina justo después de la
   última tarjeta sin necesitar calibrar ningún píxel a mano; el siguiente
   contenido ("Tipo detectado en...") queda automáticamente fuera, sobre
   fondo normal otra vez.

   Aviso honesto (no hay navegador en este entorno para afinarlo a ojo):
   esta franja usa la MISMA foto que la de arriba pero en una caja de
   alto distinto — "cover" recorta cada una por separado, así que el
   empalme entre las dos puede no ser perfectamente continuo (un salto
   sutil en el encuadre de la imagen en la costura). Minimizado alineando
   ambas a "top" y sin redondear la esquina superior (mismo truco que ya
   usa la franja de arriba: solo se redondean las esquinas de abajo, para
   que la pila se lea como un solo bloque). */
[data-testid="stMain"] .st-key-home_hero_band{
  position:relative;margin:-6px 0 18px;padding:16px 22px 22px;
  border-radius:0 0 var(--radius-lg) var(--radius-lg);
  background-image:
    linear-gradient(90deg,rgba(6,8,13,.94) 0%,rgba(6,8,13,.8) 45%,rgba(6,8,13,.35) 78%,rgba(6,8,13,.12) 100%),
    url(__HERO_BG__);
  background-size:cover,cover;background-position:top,top;background-repeat:no-repeat,no-repeat;
}
/* "Qué se cargó" es un section_header() normal (texto oscuro por defecto,
   pensado para fondo blanco) — se sobreescribe SOLO dentro de esta franja,
   sin tocar la regla general que usa el resto de la app. Las 4 tarjetas
   (kpi_card()) no se tocan: ya son fondo sólido opaco (--card-solid), se
   siguen leyendo bien encima tal cual estaban. */
[data-testid="stMain"] .st-key-home_hero_band .section-intro h2{color:#ffffff!important;text-shadow:0 2px 8px rgba(0,0,0,.6)}

/* ===== KPI scorecards: light glassmorphism — frosted glass, not flat white =====
   clamp(mínimo, preferido-en-vw, máximo): el mínimo es EXACTAMENTE el
   valor fijo que ya tenía cada propiedad (así en pantallas normales/chicas
   no cambia nada), el máximo es un tope razonable — entre ambos, crece de
   forma continua con el ancho de la ventana en vez de quedarse siempre en
   el mismo tamaño chico aunque sobre media pantalla vacía alrededor. */
.kpi-card{position:relative;background:var(--card-solid);border:1px solid var(--line);border-left:4px solid var(--blue);
  border-radius:12px;padding:clamp(14px,1vw,22px) clamp(16px,1.15vw,26px) clamp(14px,1vw,22px) clamp(18px,1.25vw,28px);
  min-height:clamp(92px,7vw,132px);animation:fadeUp .4s ease both;
  box-shadow:0 1px 2px rgba(20,26,43,.04),0 8px 20px rgba(20,26,43,.055),var(--glow-ring);
  transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
.kpi-card:hover{transform:translateY(-3px);box-shadow:0 14px 28px rgba(20,26,43,.09),var(--glow-ring)}
.kpi-label{display:block;font-size:clamp(10.5px,.75vw,13px);color:var(--muted);letter-spacing:.02em;font-weight:700;text-transform:uppercase}
.kpi-value{font-size:clamp(22px,1.65vw,34px);font-weight:800;letter-spacing:-.01em;margin-top:9px;color:var(--text);font-variant-numeric:tabular-nums;font-family:'Sora','Inter',sans-serif}
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
.kpi-delta{font-size:clamp(10.5px,.75vw,13px);margin-top:5px;font-weight:700}
.kpi-delta.positive{color:var(--green-strong)}.kpi-delta.negative{color:var(--red)}.kpi-delta.neutral{color:var(--muted)}

/* ===== Decision strips / trend lines ===== */
.decision-strip{margin:10px 0 16px;padding:12px 15px;border:1px solid var(--line);border-radius:var(--radius-sm);background:var(--panel);color:var(--text);box-shadow:var(--shadow-sm);font-size:13px}
.decision-strip.positive{border-left:4px solid var(--green);background:var(--green-soft)}
.decision-strip.negative{border-left:4px solid var(--red);background:var(--red-soft)}
.decision-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--blue);margin-right:8px}

/* ===== Insight / finding cards ===== */
.insight-card{display:flex;gap:12px;align-items:flex-start;border:1px solid var(--line);border-radius:var(--radius-md);
  padding:clamp(15px,1.1vw,24px);margin:4px 0 8px;background:var(--card-solid);animation:fadeUp .4s ease both;
  min-height:clamp(88px,6.5vw,124px);box-shadow:0 1px 2px rgba(20,26,43,.04),0 8px 20px rgba(20,26,43,.055),var(--glow-ring);
  transition:transform .18s ease,box-shadow .18s ease}
.insight-card:hover{transform:translateY(-2px);box-shadow:0 14px 28px rgba(20,26,43,.09),var(--glow-ring)}
.insight-card.positive{border-left:4px solid var(--green)}
.insight-card.warning{border-left:4px solid var(--amber)}
.insight-card.info{border-left:4px solid var(--blue)}
.insight-icon{width:28px;height:28px;flex:0 0 28px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:var(--panel-3);color:var(--muted);font-weight:800}
.insight-title{font-size:clamp(10px,.7vw,12px);color:var(--soft);text-transform:uppercase;letter-spacing:.09em;margin-bottom:5px;font-weight:800}
.insight-text{font-size:clamp(13px,.95vw,16px);line-height:1.45;color:var(--text)}
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
  border:1px solid var(--line);border-radius:var(--radius-lg);padding:clamp(15px,1.1vw,24px) clamp(17px,1.25vw,26px) clamp(8px,.6vw,14px);margin:6px 0 16px;
  box-shadow:0 1px 2px rgba(20,26,43,.04),0 8px 22px rgba(20,26,43,.06),var(--glow-ring);overflow:hidden;
  transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
.chart-card:hover{box-shadow:0 14px 28px rgba(20,26,43,.09),var(--glow-ring);border-color:rgba(228,0,43,.18)}
.chart-card:before{content:"";display:block;width:26px;height:3px;border-radius:3px;background:linear-gradient(90deg,var(--blue),var(--teal));margin:0 0 10px 2px}
.chart-head{display:flex;justify-content:space-between;align-items:flex-start;padding:2px 3px 0}
.chart-title{font-size:clamp(15px,1.05vw,19px);letter-spacing:-.01em;font-weight:750;color:var(--text)}
.chart-subtitle{font-size:clamp(11px,.8vw,13px);color:var(--muted);margin-top:3px}
.stPlotlyChart{margin-top:-3px}

/* ===== Tabs =====
   La fila de pestañas de nivel superior (Inicio/Asistente IA/Datos/.../
   Georeferenciación) tuvo 3 versiones por lo mismo — vivía sobre una foto
   sin nada detrás que garantizara contraste: fondo transparente + texto
   blanco (fallaba donde el velo diagonal se desvanecía), luego un fondo
   oscuro semi-translúcido, luego un oscuro sólido fijo (#161616, ganaba
   siempre pero no respetaba el tema Claro).

   ahora hay un velo semitranslúcido propio del tema entre la foto de
   stAppViewContainer y TODO el contenido (::before + var(--overlay-veil),
   ver más abajo) — con eso ya no hace falta que la pestaña "compita" sola
   contra una foto sin filtrar: vuelve a un fondo sólido normal del tema
   (var(--panel-2) — blanco en Claro, panel oscuro en Oscuro) con
   !important, porque BaseWeb trae su propio fondo con peso suficiente
   para ganarle a una regla sin él (ese SÍ era un bug real, no cosmético:
   sin !important la pestaña quedaba prácticamente transparente encima de
   cualquier fondo, no solo de una foto).

   Las pestañas ANIDADAS (dentro de otra pestaña, p. ej. las internas de
   Descripción) tienen su propio bloque más abajo (".stTabs .stTabs"), sin
   tocar. */
.stTabs [data-baseweb="tab-list"]{gap:6px;background:var(--panel-2)!important;border:1px solid var(--line)!important;padding:6px;border-radius:999px;box-shadow:var(--shadow-sm)!important;overflow-x:auto}
.stTabs [data-baseweb="tab"]{height:40px;border-radius:999px;padding:0 18px;color:var(--muted)!important;font-weight:700!important;font-size:13.5px;
  transition:background .15s ease,border-color .15s ease,color .15s ease,transform .15s ease,box-shadow .15s ease;
  background:transparent;border:1px solid transparent}
/* El color no se deja solo en `inherit` sobre <p> — se repite explícito en
   TODOS los descendientes (`*`), porque no hay forma de confirmar en este
   entorno qué elemento exacto envuelve el texto en cada versión de
   BaseWeb, y un solo selector que no acierte deja el texto invisible sin
   ningún aviso. Esto es más ancho de lo estrictamente necesario a
   propósito — mejor una regla de más que un texto ilegible. */
.stTabs [data-baseweb="tab"],.stTabs [data-baseweb="tab"] *{color:var(--muted)!important;font-weight:700!important}
.stTabs [data-baseweb="tab"]:hover{background:var(--panel);border-color:var(--line);transform:translateY(-1px);box-shadow:var(--shadow-sm)}
.stTabs [data-baseweb="tab"]:hover,.stTabs [data-baseweb="tab"]:hover *{color:var(--text)!important}
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
/* Fondo transparent original: pensaba que estas pestañas SIEMPRE vivían
   sobre fondo normal del tema, nunca sobre foto — eso dejó de ser cierto
   en cuanto .block-container pasó a transparent!important en TODA vista,
   no solo en el header (ver arriba). Pasa a var(--card-solid), sólido,
   para no quedar flotando sobre la imagen igual que cualquier otra caja
   de texto — sigue siendo más liviana que la barra de nivel superior
   (sin píldora, solo el subrayado inferior) para que se note la
   jerarquía entre las dos filas. */
.stTabs .stTabs [data-baseweb="tab-list"]{
  background:var(--card-solid)!important;border:1px solid var(--line-soft);box-shadow:var(--shadow-sm);border-radius:var(--radius-sm);
  padding:2px 8px 0;gap:20px;border-bottom:1px solid var(--line);
}
.stTabs .stTabs [data-baseweb="tab"]{height:34px;padding:0 2px;border-radius:0;font-size:12.5px;font-weight:650;text-shadow:none}
/* Estas viven sobre la caja sólida de arriba (ya no sobre la foto
   directamente) — recuperan var(--muted)/sin sombra de texto por encima
   del texto claro fijo que la regla de nivel superior les habría
   heredado. Doble ".stTabs" pesa más que uno solo, así que esto gana sin
   necesitar tocar la regla de arriba. */
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
/* Los caption (textos auxiliares chicos — "X registros analizados", avisos
   cortos) no tenían fondo propio, solo color de texto: quedaban sueltos
   sobre la foto igual que cualquier otro texto. Caja mínima, no una
   tarjeta completa — son una línea de texto secundario, no un bloque de
   contenido. */
.stCaption,[data-testid="stCaptionContainer"]{color:var(--muted)!important;background:var(--card-solid);
  border:1px solid var(--line-soft);border-radius:var(--radius-sm);padding:4px 10px;display:inline-block}
/* stDataFrame ya traía borde/radio pero nunca un fondo propio explícito —
   dependía de que la tabla nativa de Streamlit trajera el suyo. Se fuerza
   opaco (--card-solid) para no depender de eso. */
.stDataFrame,[data-testid="stDataFrame"]{background:var(--card-solid)!important;border:1px solid var(--line);border-radius:var(--radius-md);box-shadow:var(--shadow-sm);overflow:hidden}
[data-testid="stMetric"]{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-sm);padding:12px 14px;box-shadow:var(--shadow-sm)}
[data-testid="stMetricLabel"]{color:var(--muted)!important;font-size:11px!important}
[data-testid="stMetricValue"]{color:var(--text)!important;font-size:22px!important;font-variant-numeric:tabular-nums}

/* ===== Executive / alerts / why-changed / factors ===== */
.executive-card{padding:clamp(19px,1.4vw,30px) clamp(21px,1.5vw,32px);border:1px solid var(--line);border-radius:var(--radius-lg);background:var(--panel);box-shadow:var(--shadow-md),var(--glow-ring);border-left:5px solid var(--blue);margin:4px 0 10px;animation:fadeUp .4s ease both}
.executive-card.positive{border-left-color:var(--green)}
.executive-card.negative{border-left-color:var(--red)}
.executive-status{font-size:10px;text-transform:uppercase;letter-spacing:.11em;font-weight:800;color:var(--soft)}
.executive-headline{font-size:clamp(21px,1.55vw,30px);font-weight:800;color:var(--text);margin-top:6px}
.executive-detail{font-size:clamp(12.5px,.9vw,15px);color:var(--muted);margin-top:7px;line-height:1.5}
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
  border:1px solid var(--line);border-radius:13px;padding:clamp(12px,.9vw,19px) clamp(13px,1vw,20px) clamp(9px,.65vw,14px);
  box-shadow:0 1px 2px rgba(20,26,43,.04),0 8px 20px rgba(20,26,43,.055),var(--glow-ring);
  transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
.pbi-visual:hover{box-shadow:0 14px 28px rgba(228,0,43,.10),var(--glow-ring);border-color:rgba(228,0,43,.2)}
.pbi-visual:before{width:22px;height:3px;margin-bottom:8px;background:linear-gradient(90deg,var(--blue),var(--teal))}
.pbi-visual .chart-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;min-height:42px;padding:0 3px 2px}
.pbi-visual .chart-head-main{min-width:0}
.pbi-visual .visual-type{display:block;color:var(--blue);font-size:8px;font-weight:800;letter-spacing:.15em;margin-bottom:4px}
.pbi-visual .chart-title{font-size:clamp(14px,1vw,17px);font-weight:800;line-height:1.2}
.pbi-visual .chart-subtitle{font-size:clamp(10px,.72vw,12px);color:var(--muted);margin-top:3px;line-height:1.35}
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
    css = css.replace("__APP_BG__", background_data_uri("fondo.jpg"))
    return css


def inject_theme(dark: bool) -> None:
    """Punto de entrada único: inyecta el tema completo (tokens + clases).
    Sustituye a los dos `st.markdown(...)` que antes vivían inline en
    `app.py`."""
    st.markdown(base_layer_css(dark), unsafe_allow_html=True)
    st.markdown(components_css(), unsafe_allow_html=True)
