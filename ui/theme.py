"""Sistema de diseño compartido de la app: tokens de color/tipografía/espaciado
y todas las clases CSS que reutilizan las pantallas en `ui/*.py`.

Antes esto vivía repetido: un bloque gigante en `app.py` más cuatro bloques
`<style>` independientes en `login.py`, `landing.py`, `mode_choice.py` y
`practical.py` (cada uno redefiniendo o reusando los mismos tokens a su
manera). Ahora hay una sola fuente de verdad: `inject_theme()` se llama una
vez al arranque de cada pantalla/flujo y define los tokens (`--blue`,
`--panel`, `--radius-lg`, etc.) y las clases (`.kpi-card`, `.chart-card`,
`.nav-item`, ...) que el resto del código sigue usando exactamente por su
nombre de siempre — esto es un cambio de estructura/organización del CSS,
no de ninguna lógica de negocio.

Paleta: identidad de rojo oscuro sobre fondo claro y cálido (en vez del rojo
brillante sobre grises azulados de antes), tipografía Inter/Sora — la misma
dirección visual de `project/Propuesta UX.dc.html`.
"""
from __future__ import annotations
import streamlit as st

BASE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Sora:wght@600;700;800&display=swap');

:root{
  --bg:#fbfaf8;--panel:#ffffff;--panel-2:#faf8f5;--panel-3:#f3f0ea;
  --text:#141416;--muted:#6b665e;--soft:#8a857c;--line:#e2ded6;--line-soft:#eee9e1;
  --blue:#8c1420;--blue-soft:#fdf0ee;--teal:#0fa8a0;--teal-soft:#e6f8f6;
  --green:#1c7a4f;--green-soft:#e7f7ef;--amber:#a3660a;--amber-soft:#fdf2e2;
  --red:#a3231d;--red-soft:#fdeaee;--purple:#6a5bd8;--purple-soft:#efecfc;
  --accent-grad:linear-gradient(180deg,#a8323d,#8c1420);
  --accent-grad-hover:linear-gradient(180deg,#b23b46,#8c1420);
  --sidebar-bg:#141416;--sidebar-panel:#1d1d1f;--sidebar-line:#2c2c2f;--sidebar-text:#e9e6e0;--sidebar-muted:#9a958c;
  --radius-lg:16px;--radius-md:12px;--radius-sm:9px;
  --shadow-sm:0 1px 2px rgba(20,18,15,.05),0 1px 1px rgba(20,18,15,.03);
  --shadow-md:0 2px 6px rgba(20,18,15,.05),0 10px 24px rgba(20,18,15,.06);
  --shadow-lg:0 8px 20px rgba(20,18,15,.09),0 2px 6px rgba(20,18,15,.05);
}
html,body,[data-testid="stAppViewContainer"],[data-testid="stApp"],[data-testid="stMain"],[data-testid="stMainBlockContainer"],.main,.stAppViewContainer{
  background:
    radial-gradient(ellipse 950px 550px at 100% 0%, rgba(140,20,32,.06), transparent 58%),
    radial-gradient(ellipse 850px 550px at 0% 100%, rgba(140,20,32,.045), transparent 58%),
    radial-gradient(ellipse 700px 500px at 50% 45%, rgba(140,20,32,.02), transparent 65%),
    var(--bg)!important;
  color:var(--text)!important;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
[data-testid="stHeader"],[data-testid="stBottomBlockContainer"]{background:var(--bg)!important}
.stApp{background:var(--bg);color:var(--text)}
* {font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.block-container{max-width:1540px;padding:1.1rem 1.8rem 4rem}
header[data-testid="stHeader"]{background:rgba(251,250,248,.86);backdrop-filter:blur(6px)}
h1,h2,h3,h4,h5,h6{color:var(--text);font-family:'Sora','Inter',sans-serif;letter-spacing:-.01em}
p,span,div,li,label{color:var(--text)}

/* ===== Sidebar = rail de navegación: angosto, casi negro, contrasta con el contenido claro ===== */
section[data-testid="stSidebar"]{background:var(--sidebar-bg)!important;border-right:1px solid var(--sidebar-line)!important;min-width:250px!important;max-width:280px!important}
section[data-testid="stSidebar"] .block-container{padding:1.1rem .85rem 1.6rem}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:.45rem}
section[data-testid="stSidebar"] *{color:var(--sidebar-text)}
section[data-testid="stSidebar"] h1,section[data-testid="stSidebar"] h2,section[data-testid="stSidebar"] h3{color:#ffffff!important;font-family:'Sora','Inter',sans-serif;letter-spacing:-.01em}
section[data-testid="stSidebar"] .stCaption,section[data-testid="stSidebar"] [data-testid="stCaptionContainer"]{color:var(--sidebar-muted)!important}
section[data-testid="stSidebar"] hr{border-color:var(--sidebar-line);margin:.65rem 0}
section[data-testid="stSidebar"] input,section[data-testid="stSidebar"] textarea{background:var(--sidebar-panel)!important;border:1px solid var(--sidebar-line)!important;color:#ffffff!important;border-radius:9px!important}
section[data-testid="stSidebar"] [data-baseweb="select"]{background:var(--sidebar-panel)!important}
section[data-testid="stSidebar"] [data-baseweb="select"]>div{background:var(--sidebar-panel)!important;border:1px solid var(--sidebar-line)!important;border-radius:9px!important}
section[data-testid="stSidebar"] [data-baseweb="select"] *{color:#ffffff!important;background:transparent!important;background-color:transparent!important;fill:#ffffff!important}
section[data-testid="stSidebar"] [data-baseweb="select"] input::placeholder{color:var(--sidebar-muted)!important;opacity:1!important}
section[data-testid="stSidebar"] .stMultiSelect span[data-baseweb="tag"]{background:rgba(140,20,32,.32)!important;border:1px solid rgba(140,20,32,.55)!important}
section[data-testid="stSidebar"] .stMultiSelect span[data-baseweb="tag"] span{color:#ffffff!important}
section[data-testid="stSidebar"] [data-baseweb="popover"]{background:var(--sidebar-panel)!important;border:1px solid var(--sidebar-line)!important}
section[data-testid="stSidebar"] [data-baseweb="menu"]{background:var(--sidebar-panel)!important}
section[data-testid="stSidebar"] [data-baseweb="menu"] li:hover{background:rgba(140,20,32,.28)!important}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"]{background:var(--sidebar-panel)!important;border:1px dashed var(--sidebar-line)!important;border-radius:var(--radius-md)!important}
section[data-testid="stSidebar"] .stFileUploader small{color:var(--sidebar-muted)!important}
section[data-testid="stSidebar"] .stButton>button{background:var(--sidebar-panel);color:var(--sidebar-text);border:1px solid var(--sidebar-line);border-radius:var(--radius-sm);font-weight:600;text-align:left;justify-content:flex-start}
section[data-testid="stSidebar"] .stButton>button:hover{border-color:var(--blue);color:#ff9aa3;background:rgba(140,20,32,.20)}
section[data-testid="stSidebar"] button[kind="primary"]{background:var(--accent-grad)!important;border-color:#6e0f19!important;color:#fff!important;font-weight:700!important;text-align:left;justify-content:flex-start}
section[data-testid="stSidebar"] [data-testid="stExpander"]{background:var(--sidebar-panel)!important;border:1px solid var(--sidebar-line)!important}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary{background:var(--sidebar-panel)!important;color:#ffffff!important}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover{color:#ff9aa3!important}
section[data-testid="stSidebar"] [data-testid="stAlert"]{background:var(--sidebar-panel)!important;border:1px solid var(--sidebar-line)!important;color:var(--sidebar-text)!important}
section[data-testid="stSidebar"] .mode-banner{background:rgba(140,20,32,.22);border:1px solid rgba(140,20,32,.55);color:#ffffff}
section[data-testid="stSidebar"] .mode-banner .mode-banner-label{color:var(--sidebar-muted)}
section[data-testid="stSidebar"] .mode-banner b{color:#ffffff}
section[data-testid="stSidebar"] .mode-confidence{color:#ffb3ba!important;background:rgba(255,255,255,.08)!important}
section[data-testid="stSidebar"] [data-testid="stDownloadButton"] button{background:var(--sidebar-panel);color:#ff9aa3;border-color:rgba(140,20,32,.55)}
section[data-testid="stSidebar"] [data-testid="stDownloadButton"] button:hover{background:rgba(140,20,32,.28);color:#ffffff}

/* Bloque de marca arriba del rail, como en la referencia */
.sidebar-logo{display:flex;align-items:center;gap:10px;padding:2px 2px 14px;margin-bottom:6px;border-bottom:1px solid var(--sidebar-line)}
.sidebar-logo-mark{width:30px;height:30px;border-radius:8px;background:var(--accent-grad);display:flex;align-items:center;justify-content:center;font-size:14px;flex:0 0 30px}
.sidebar-logo-text{font-size:13.5px;font-weight:800;font-family:'Sora','Inter',sans-serif;color:#ffffff;line-height:1.2}
.sidebar-logo-text small{display:block;font-size:9.5px;font-weight:600;font-family:'Inter',sans-serif;letter-spacing:.06em;color:var(--sidebar-muted)}
.sidebar-section-label{font-size:10.5px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:var(--sidebar-muted)!important;margin:12px 0 6px}

/* Nota "módulos activos" al pie del rail — contorno punteado, como los
   módulos condicionales en la Propuesta UX. */
.nav-note{margin:10px 0 4px;padding:10px 11px;border:1px dashed rgba(255,255,255,.22);border-radius:var(--radius-sm)}
.nav-note-label{display:block;font:700 9px ui-monospace,Menlo,monospace;letter-spacing:.08em;color:var(--sidebar-muted);margin-bottom:4px}
.nav-note-text{font-size:10.5px;line-height:1.5;color:var(--sidebar-text)}

/* ===== Barra de contexto persistente (archivo/hoja/buscar/exportar/asistente) ===== */
.context-bar-row{display:flex;align-items:center;gap:8px;margin:2px 0 2px}
.context-chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:8px;padding:7px 11px;font-size:11.5px;font-weight:700;color:var(--text);background:var(--panel-2);white-space:nowrap}
.context-chip .mono{margin-right:2px}

/* ===== Etiqueta uppercase monoespaciada (títulos técnicos cortos) ===== */
.mono{font:700 9.5px ui-monospace,Menlo,monospace;letter-spacing:.07em;text-transform:uppercase;color:var(--soft)}

/* ===== Contorno punteado para módulos/placeholders condicionales ===== */
.dash{border:1px dashed #c8bfae;border-radius:var(--radius-md)}
.ph{background:var(--panel-3);border-radius:6px}

/* ===== Hero / encabezado de página: mínimo y plano ===== */
.hero{padding:6px 2px 14px;margin:0 0 6px;border:none;background:transparent;box-shadow:none;border-bottom:1px solid var(--line)}
.hero h1{margin:0;font-size:20px;font-weight:800;letter-spacing:-.01em;color:var(--text)}
.hero p{color:var(--muted);margin:4px 0 0;font-size:12.5px;max-width:900px}

/* ===== Encabezados de sección ===== */
.section-intro{display:flex;align-items:flex-start;justify-content:space-between;margin:26px 0 6px;flex-wrap:wrap;gap:8px}
.section-intro.compact{margin-top:26px}
.section-intro h2{margin:0;font-size:17px;font-weight:800;letter-spacing:-.01em;color:var(--text)}
.eyebrow{display:none}
.data-badge{font-size:10.5px;font-weight:700;color:var(--red);background:none;border:none;padding:0;box-shadow:none;text-transform:uppercase;letter-spacing:.05em}

/* ===== Tarjetas KPI: vidrio esmerilado en vez de blanco plano ===== */
.kpi-card{position:relative;background:rgba(255,255,255,.62);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  border:1px solid rgba(255,255,255,.75);border-radius:10px;padding:14px 16px;min-height:92px;
  box-shadow:0 1px 2px rgba(20,18,15,.04),0 10px 26px rgba(20,18,15,.07);
  transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
.kpi-card:hover{transform:translateY(-3px);box-shadow:0 16px 34px rgba(140,20,32,.14),0 2px 6px rgba(20,18,15,.06);border-color:rgba(140,20,32,.3)}
.kpi-label{display:block;font-size:10.5px;color:var(--muted);letter-spacing:.01em;font-weight:600}
.kpi-value{font-size:21px;font-weight:800;letter-spacing:-.01em;margin-top:9px;color:var(--text);font-variant-numeric:tabular-nums}
.kpi-card.negative .kpi-value{color:var(--red)}
.kpi-card.positive .kpi-value{color:var(--green)}
.kpi-delta{font-size:10.5px;margin-top:5px;font-weight:700}
.kpi-delta.positive{color:var(--green)}.kpi-delta.negative{color:var(--red)}.kpi-delta.neutral{color:var(--muted)}

/* ===== Franjas de decisión ===== */
.decision-strip{margin:10px 0 16px;padding:12px 15px;border:1px solid var(--line);border-radius:var(--radius-sm);background:var(--panel);color:var(--text);box-shadow:var(--shadow-sm);font-size:13px}
.decision-strip.positive{border-left:4px solid var(--green);background:var(--green-soft)}
.decision-strip.negative{border-left:4px solid var(--red);background:var(--red-soft)}
.decision-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--blue);margin-right:8px}

/* ===== Tarjetas de hallazgo: mismo vidrio esmerilado ===== */
.insight-card{display:flex;gap:12px;align-items:flex-start;border:1px solid rgba(255,255,255,.8);border-radius:var(--radius-md);
  padding:15px;margin:4px 0 8px;background:rgba(255,255,255,.68);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  min-height:88px;box-shadow:0 1px 2px rgba(20,18,15,.04),0 8px 20px rgba(20,18,15,.06);
  transition:transform .18s ease,box-shadow .18s ease}
.insight-card:hover{transform:translateY(-2px);box-shadow:0 14px 28px rgba(20,18,15,.09)}
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

/* ===== Panel de decisión / filas de acción ===== */
.decision-panel{margin:14px 0 8px;padding:13px 15px;background:var(--panel-2);border:1px solid var(--line);border-radius:var(--radius-md)}
.decision-panel-title{font-weight:800;color:var(--text);font-size:13px}
.decision-panel-subtitle{font-size:11.5px;color:var(--muted);margin-top:3px}
.action-row{display:flex;gap:11px;align-items:flex-start;padding:10px 12px;border-bottom:1px solid var(--line-soft);font-size:12.5px;line-height:1.5}
.action-number{width:24px;height:24px;border-radius:7px;background:var(--blue-soft);color:var(--blue);display:flex;align-items:center;justify-content:center;font-weight:800;flex:0 0 24px}
.action-row b{color:var(--text)}

/* ===== Envolturas de gráficos ===== */
.chart-reading{margin:0 3px 10px;padding:9px 11px;border-radius:var(--radius-sm);background:var(--panel-2);border:1px solid var(--line);color:var(--muted);font-size:11.5px;line-height:1.45}
.chart-card{background:rgba(255,255,255,.68);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  border:1px solid rgba(255,255,255,.8);border-radius:var(--radius-lg);padding:15px 17px 8px;margin:6px 0 16px;
  box-shadow:0 1px 2px rgba(20,18,15,.04),0 10px 26px rgba(20,18,15,.07);overflow:hidden;
  transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
.chart-card:hover{box-shadow:0 16px 34px rgba(140,20,32,.12),0 2px 6px rgba(20,18,15,.06);border-color:rgba(140,20,32,.26)}
.chart-card:before{content:"";display:block;width:26px;height:3px;border-radius:3px;background:linear-gradient(90deg,var(--blue),var(--teal));margin:0 0 10px 2px}
.chart-head{display:flex;justify-content:space-between;align-items:flex-start;padding:2px 3px 0}
.chart-title{font-size:15px;letter-spacing:-.01em;font-weight:750;color:var(--text)}
.chart-subtitle{font-size:11px;color:var(--muted);margin-top:3px}
.stPlotlyChart{margin-top:-3px}

/* ===== Tabs (sub-secciones dentro de Explorar/Personas/Informes) ===== */
.stTabs [data-baseweb="tab-list"]{gap:6px;background:var(--panel-2);border:1px solid var(--line);padding:6px;border-radius:14px;box-shadow:var(--shadow-sm);overflow-x:auto}
.stTabs [data-baseweb="tab"]{height:40px;border-radius:10px;padding:0 16px;color:var(--muted);font-weight:700;font-size:13.5px;transition:.15s ease;background:transparent}
.stTabs [data-baseweb="tab"] p{color:inherit;font-weight:inherit}
.stTabs [data-baseweb="tab"]:hover{background:var(--panel);color:var(--text)}
.stTabs [aria-selected="true"]{background:var(--accent-grad)!important;color:#ffffff!important;box-shadow:0 3px 10px rgba(140,20,32,.32)!important}
.stTabs [aria-selected="true"] p{color:#ffffff!important;font-weight:800!important}
.stTabs [data-baseweb="tab-highlight"]{display:none!important}
.stTabs [data-baseweb="tab-border"]{display:none!important}

/* ===== Botones: discretos por defecto, solo el CTA principal pesa visualmente ===== */
.stButton>button,[data-testid="stDownloadButton"] button,[data-testid="stFormSubmitButton"] button{
  min-height:40px;padding:0 18px;background:var(--panel);color:var(--muted);
  border:1px solid var(--line);border-radius:11px;font-weight:650;font-size:13.5px;
  box-shadow:none;transition:border-color .12s ease,color .12s ease,background .12s ease,transform .08s ease;
}
.stButton>button:hover,[data-testid="stDownloadButton"] button:hover,[data-testid="stFormSubmitButton"] button:hover{
  border-color:var(--blue);color:var(--blue);background:var(--blue-soft);
}
.stButton>button:active,[data-testid="stDownloadButton"] button:active{transform:scale(.98)}
button[kind="primary"],[data-testid="stDownloadButton"] button[kind="primary"]{
  background:var(--accent-grad)!important;border-color:#6e0f19!important;color:#fff!important;
  font-weight:750!important;box-shadow:0 4px 12px rgba(140,20,32,.22)!important;
}
button[kind="primary"]:hover,[data-testid="stDownloadButton"] button[kind="primary"]:hover{
  background:var(--accent-grad-hover)!important;color:#fff!important;box-shadow:0 6px 16px rgba(140,20,32,.3)!important;
}
[data-testid="stDownloadButton"] button{border-color:var(--blue);color:var(--blue);background:var(--blue-soft)}
[data-testid="stDownloadButton"] button:hover{background:var(--blue);color:#fff;border-color:var(--blue)}

/* ===== Inputs nativos ===== */
input,textarea{color:var(--text)!important;background:rgba(255,255,255,.75)!important;border:1px solid var(--line)!important;transition:border-color .15s ease,box-shadow .15s ease}
input:focus,textarea:focus{border-color:rgba(140,20,32,.5)!important;box-shadow:0 0 0 3px rgba(140,20,32,.1)!important}
input::placeholder,textarea::placeholder{color:var(--soft)!important;opacity:1!important}
[data-baseweb="select"]>div{background:var(--panel)!important;border:1px solid var(--line)!important;color:var(--text)!important;border-radius:9px!important}
[data-baseweb="select"] *{color:var(--text)!important}
[data-baseweb="popover"]{background:var(--panel)!important;border:1px solid var(--line)!important;box-shadow:var(--shadow-md)!important}
[data-baseweb="menu"]{background:var(--panel)!important}
.stMultiSelect [data-baseweb="tag"]{background:var(--blue-soft)!important}
.stMultiSelect [data-baseweb="tag"] span{color:var(--blue)!important}
label,p,li,span,div{scrollbar-color:#d8d0c2 #f3f0ea}
[data-testid="stMarkdownContainer"] p,[data-testid="stMarkdownContainer"] li{color:inherit}
[data-testid="stFileUploaderDropzone"]{background:var(--panel-2)!important;border:1px dashed var(--line)!important;border-radius:var(--radius-md)!important}
.stFileUploader label{color:var(--text)!important}
.stFileUploader small{color:var(--muted)!important}

/* ===== Expanders y popovers: el mecanismo principal de progressive disclosure ===== */
[data-testid="stExpander"]{background:var(--panel)!important;border:1px solid var(--line)!important;border-radius:var(--radius-md)!important;box-shadow:var(--shadow-sm)!important;margin-bottom:10px}
.streamlit-expanderHeader,[data-testid="stExpander"] summary{color:var(--text)!important;background:var(--panel)!important;font-weight:750!important;border-radius:var(--radius-md)!important}
[data-testid="stExpander"] summary:hover{color:var(--blue)!important}
[data-testid="stExpander"] summary svg{color:var(--blue)!important}
[data-testid="stPopoverBody"]{border-radius:var(--radius-md)!important}

[data-testid="stAlert"]{background:var(--panel)!important;color:var(--text)!important;border:1px solid var(--line)!important;border-radius:var(--radius-sm)!important}
.stCaption,[data-testid="stCaptionContainer"]{color:var(--muted)!important}
.stDataFrame,[data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:var(--radius-md);overflow:hidden}
[data-testid="stMetric"]{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-sm);padding:12px 14px;box-shadow:var(--shadow-sm)}
[data-testid="stMetricLabel"]{color:var(--muted)!important;font-size:11px!important}
[data-testid="stMetricValue"]{color:var(--text)!important;font-size:22px!important;font-variant-numeric:tabular-nums}

/* ===== Ejecutivo / alertas / por qué cambió / factores ===== */
.executive-card{padding:19px 21px;border:1px solid var(--line);border-radius:var(--radius-lg);background:var(--panel);box-shadow:var(--shadow-md);border-left:5px solid var(--blue);margin:4px 0 10px}
.executive-card.positive{border-left-color:var(--green)}
.executive-card.negative{border-left-color:var(--red)}
.executive-status{font-size:10px;text-transform:uppercase;letter-spacing:.11em;font-weight:800;color:var(--soft)}
.executive-headline{font-size:21px;font-weight:800;color:var(--text);margin-top:6px}
.executive-detail{font-size:12.5px;color:var(--muted);margin-top:7px;line-height:1.5}
.mini-list{padding:9px 12px;background:var(--panel-2);border:1px solid var(--line);border-radius:var(--radius-sm);color:var(--text);font-weight:700}
.mini-positive,.mini-warning{margin-top:6px;padding:9px 11px;border-radius:var(--radius-sm);font-size:12.5px}
.mini-positive{color:#0f5c39;background:var(--green-soft);border-left:3px solid var(--green)}
.mini-warning{color:#7a4c08;background:var(--amber-soft);border-left:3px solid var(--amber)}
.alert-row{display:flex;gap:12px;align-items:flex-start;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-md);padding:12px 14px;margin-bottom:8px;box-shadow:var(--shadow-sm)}
.alert-row.warning{border-left:4px solid var(--amber)}
.alert-row.positive{border-left:4px solid var(--green)}
.alert-row.negative{border-left:4px solid var(--red)}
.alert-severity{font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.04em;color:var(--soft);min-width:78px;white-space:nowrap}
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

/* ===== Catálogo ===== */
.catalog-card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-lg);padding:16px 17px;margin:6px 0 14px;box-shadow:var(--shadow-sm);min-height:190px}
.catalog-card-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;border-bottom:1px solid var(--line-soft);padding-bottom:10px;margin-bottom:9px}
.catalog-title{font-size:16px;font-weight:800;color:var(--text);line-height:1.25}
.catalog-subtitle{font-size:11px;color:var(--muted);margin-top:5px;line-height:1.4}
.catalog-price{font-size:20px;font-weight:850;color:var(--blue);white-space:nowrap}
.catalog-card ul{margin:0;padding-left:18px;color:var(--text);font-size:12px;line-height:1.55}
.catalog-card li{margin:4px 0}

/* ===== Análisis universal / drill-down ===== */
.drilldown-card{background:rgba(255,255,255,.68);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  border:1px solid rgba(255,255,255,.8);border-radius:var(--radius-md);padding:12px 14px;
  box-shadow:0 1px 2px rgba(20,18,15,.04),0 8px 20px rgba(20,18,15,.06);
  transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
.drilldown-card:hover{transform:translateY(-2px);box-shadow:0 14px 28px rgba(140,20,32,.12);border-color:rgba(140,20,32,.26)}
.smart-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.alert-row.compact{padding:10px 12px;margin-bottom:6px}
.analysis-note{font-size:11.5px;color:var(--muted);margin:4px 0 8px}

/* ===== Panel de comparación ===== */
.comparison-panel{margin:10px 0 8px;padding:12px 14px;border:1px solid var(--line);border-left:3px solid var(--blue);border-radius:var(--radius-sm);background:var(--blue-soft);color:var(--text)}
.comparison-panel b{color:var(--text);display:block;margin-bottom:3px}

/* ===== Banner de modo detectado ===== */
.mode-banner{margin:8px 0 8px;padding:10px 14px;border:1px solid var(--line);border-radius:var(--radius-md);background:var(--blue-soft);color:var(--text);font-size:13px;line-height:1.5}
.mode-banner-label{font-size:9.5px;font-weight:800;letter-spacing:.09em;color:var(--muted)}
.mode-banner b{color:var(--text)}
.mode-confidence{font-size:10.5px;font-weight:700;color:var(--muted);background:var(--panel);border-radius:999px;padding:2px 8px;white-space:nowrap}

/* ===== Accesibilidad ===== */
button:focus-visible,input:focus-visible,textarea:focus-visible,[role="tab"]:focus-visible{outline:2px solid var(--blue)!important;outline-offset:2px}
button:disabled{color:var(--soft)!important;background:var(--panel-2)!important;border-color:var(--line)!important}

/* ===== Barra de herramientas de análisis ===== */
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

/* ===== pbi-visual: variante de tarjeta de gráfico usada en el área de análisis ===== */
.pbi-visual{background:rgba(255,255,255,.68);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  border:1px solid rgba(255,255,255,.8);border-radius:13px;padding:12px 13px 9px;
  box-shadow:0 1px 2px rgba(20,18,15,.04),0 10px 24px rgba(20,18,15,.06);
  transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
.pbi-visual:hover{box-shadow:0 14px 28px rgba(140,20,32,.12);border-color:rgba(140,20,32,.24)}
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
 .hero{padding:20px}.hero h1{font-size:23px}
 .analysis-toolbar{align-items:flex-start;flex-direction:column;padding:15px 16px}
 .analysis-toolbar-meta{justify-content:flex-start}
 .pbi-visual .visual-badge{display:none}
 .kpi-card{min-height:100px!important}
 .context-bar-row{flex-wrap:wrap}
}
</style>
"""

def inject_theme() -> None:
    """Inyecta el bloque de tokens/clases compartido.

    Se llama UNA vez por ejecución del script, desde `app.py`, antes de
    despachar a cualquier pantalla (login, landing, mode_choice, práctico o
    el panel avanzado) — igual que antes vivía el bloque de CSS al principio
    de `app.py`. Streamlit vuelve a ejecutar todo el script en cada
    interacción y reconstruye el árbol de elementos desde cero, así que este
    `st.markdown` debe volver a llamarse en cada rerun (no solo la primera
    vez) para que el `<style>` siga presente.
    """
    st.markdown(BASE_CSS, unsafe_allow_html=True)
