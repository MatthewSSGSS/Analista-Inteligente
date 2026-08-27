import streamlit as st
import pandas as pd
from datetime import datetime
from core.loader import load_workbook
from core.dashboard_engine import build_dashboard
from core.dataset_mode import detect_dataset_mode
from core.filter_engine import apply_filters, natural_filter, cascading_options
from ui.dashboard import render_dashboard
from ui.explorer import render_explorer
from ui.quality import render_quality
from ui.georeferencing import render_georeferencing
from core.geo_engine import supports_georeferencing
from ui.anomalies import render_anomalies
from ui.data_table import render_data_table
from ui.exports import render_exports
from ui.catalog import render_catalog
from ui.assistant import render_assistant
from core.comparison_engine import prepare_comparison, build_comparison
from ui.comparison import render_comparison
from ui.person_profile import render_person_profile
from ui.person_compare import render_person_compare
from ui.executive import render_executive
from ui.home import render_home
from ui.landing import render_landing
from ui.tracking import render_tracking
from core.tracking_engine import ingest_file, sources_to_long, merge_long, read_consolidated
import core.db_engine as db_engine

if "view_mode" not in st.session_state:
    st.session_state.view_mode = "Ejecutivo"
if "app_started" not in st.session_state:
    st.session_state.app_started = False

st.set_page_config(
    page_title="Panel Analítico Universal", page_icon="📊", layout="wide",
    initial_sidebar_state="collapsed" if not st.session_state.app_started else "auto",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Sora:wght@600;700;800&display=swap');

:root{
  --bg:#ffffff;--panel:#ffffff;--panel-2:#f7f9fc;--panel-3:#eef2f8;
  --text:#131826;--muted:#5b6473;--soft:#8792a3;--line:#d8dce6;--line-soft:#e8ebf1;
  --blue:#e4002b;--blue-soft:#fde8ea;--teal:#0fa8a0;--teal-soft:#e6f8f6;
  --green:#189a63;--green-soft:#e7f7ef;--amber:#c8790a;--amber-soft:#fdf2e2;
  --red:#e0223f;--red-soft:#fdeaee;--purple:#6a5bd8;--purple-soft:#efecfc;
  --sidebar-bg:#0d1119;--sidebar-panel:#171c29;--sidebar-line:#2a3040;--sidebar-text:#d7dbe6;--sidebar-muted:#8992a8;
  --radius-lg:16px;--radius-md:12px;--radius-sm:9px;
  --shadow-sm:0 1px 2px rgba(20,26,43,.04),0 1px 1px rgba(20,26,43,.03);
  --shadow-md:0 2px 6px rgba(20,26,43,.05),0 10px 24px rgba(20,26,43,.055);
  --shadow-lg:0 8px 20px rgba(20,26,43,.08),0 2px 6px rgba(20,26,43,.05);
}
html,body,[data-testid="stAppViewContainer"],[data-testid="stApp"],[data-testid="stMain"],[data-testid="stMainBlockContainer"],.main,.stAppViewContainer{background:#ffffff!important;color:#131826!important;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
[data-testid="stHeader"],[data-testid="stBottomBlockContainer"]{background:#ffffff!important}
.stApp{background:var(--bg);color:var(--text)}
* {font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.block-container{max-width:1540px;padding:1.1rem 1.8rem 4rem}
header[data-testid="stHeader"]{background:rgba(238,241,246,.86);backdrop-filter:blur(6px)}
h1,h2,h3,h4,h5,h6{color:var(--text);font-family:'Sora','Inter',sans-serif;letter-spacing:-.01em}
p,span,div,li,label{color:var(--text)}

/* ===== Sidebar: dark navy nav rail, contrasts with the light content ===== */
section[data-testid="stSidebar"]{background:var(--sidebar-bg)!important;border-right:1px solid var(--sidebar-line)!important}
section[data-testid="stSidebar"] .block-container{padding:1.3rem 1rem 2rem}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:.55rem}
section[data-testid="stSidebar"] *{color:var(--sidebar-text)}
section[data-testid="stSidebar"] h1,section[data-testid="stSidebar"] h2,section[data-testid="stSidebar"] h3{color:#ffffff!important;font-family:'Sora','Inter',sans-serif;letter-spacing:-.01em}
section[data-testid="stSidebar"] .stCaption,section[data-testid="stSidebar"] [data-testid="stCaptionContainer"]{color:var(--sidebar-muted)!important}
section[data-testid="stSidebar"] hr{border-color:var(--sidebar-line);margin:.75rem 0}
section[data-testid="stSidebar"] input,section[data-testid="stSidebar"] textarea{background:var(--sidebar-panel)!important;border:1px solid var(--sidebar-line)!important;color:#ffffff!important;border-radius:9px!important}
section[data-testid="stSidebar"] [data-baseweb="select"]{background:var(--sidebar-panel)!important}
section[data-testid="stSidebar"] [data-baseweb="select"]>div{background:var(--sidebar-panel)!important;border:1px solid var(--sidebar-line)!important;border-radius:9px!important}
/* Baseweb nests several layers inside the select (value box, indicator
   separator, dropdown-arrow box) that each carry their own background —
   forcing every descendant transparent is the only reliable way to stop the
   two-tone "dark pill with a white patch near the arrow" look. */
section[data-testid="stSidebar"] [data-baseweb="select"] *{color:#ffffff!important;background:transparent!important;background-color:transparent!important;fill:#ffffff!important}
section[data-testid="stSidebar"] [data-baseweb="select"] input::placeholder{color:var(--sidebar-muted)!important;opacity:1!important}
section[data-testid="stSidebar"] .stMultiSelect span[data-baseweb="tag"]{background:rgba(228,0,43,.22)!important;border:1px solid rgba(228,0,43,.4)!important}
section[data-testid="stSidebar"] .stMultiSelect span[data-baseweb="tag"] span{color:#ffffff!important}
section[data-testid="stSidebar"] [data-baseweb="popover"]{background:var(--sidebar-panel)!important;border:1px solid var(--sidebar-line)!important}
section[data-testid="stSidebar"] [data-baseweb="menu"]{background:var(--sidebar-panel)!important}
section[data-testid="stSidebar"] [data-baseweb="menu"] li:hover{background:rgba(228,0,43,.18)!important}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"]{background:var(--sidebar-panel)!important;border:1px dashed var(--sidebar-line)!important;border-radius:var(--radius-md)!important}
section[data-testid="stSidebar"] .stFileUploader small{color:var(--sidebar-muted)!important}
section[data-testid="stSidebar"] .stButton>button{background:var(--sidebar-panel);color:#ffffff;border:1px solid var(--sidebar-line);border-radius:var(--radius-sm)}
section[data-testid="stSidebar"] .stButton>button:hover{border-color:var(--blue);color:#ff6b7a;background:rgba(228,0,43,.12)}
section[data-testid="stSidebar"] button[kind="primary"]{background:linear-gradient(180deg,#ff3b4e,#e4002b)!important;border-color:#c8001f!important;color:#fff!important}
section[data-testid="stSidebar"] [data-testid="stExpander"]{background:var(--sidebar-panel)!important;border:1px solid var(--sidebar-line)!important}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary{background:var(--sidebar-panel)!important;color:#ffffff!important}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover{color:#ff6b7a!important}
section[data-testid="stSidebar"] [data-testid="stAlert"]{background:var(--sidebar-panel)!important;border:1px solid var(--sidebar-line)!important;color:var(--sidebar-text)!important}
section[data-testid="stSidebar"] .mode-banner{background:rgba(228,0,43,.16);border:1px solid rgba(228,0,43,.4);color:#ffffff}
section[data-testid="stSidebar"] .mode-banner .mode-banner-label{color:var(--sidebar-muted)}
section[data-testid="stSidebar"] .mode-banner b{color:#ffffff}
section[data-testid="stSidebar"] .mode-confidence{color:#ffb3ba!important;background:rgba(255,255,255,.08)!important}
/* Sidebar logo block, like the reference nav header */
.sidebar-logo{display:flex;align-items:center;gap:10px;padding:2px 2px 14px;margin-bottom:10px;border-bottom:1px solid var(--sidebar-line)}
.sidebar-logo-mark{width:34px;height:34px;border-radius:50%;background:radial-gradient(circle at 32% 28%,#ff4d4d,#e4002b 55%,#a80e1f 100%);box-shadow:inset 0 -3px 6px rgba(0,0,0,.22),inset 0 2px 3px rgba(255,255,255,.35);display:flex;align-items:center;justify-content:center;font-size:16px;flex:0 0 34px}
.sidebar-logo-text{font-size:14px;font-weight:800;font-family:'Sora','Inter',sans-serif;color:#ffffff;line-height:1.2}
.sidebar-logo-text small{display:block;font-size:10.5px;font-weight:600;font-family:'Inter',sans-serif;color:var(--sidebar-muted)}
.sidebar-section-label{font-size:10.5px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:var(--sidebar-muted)!important;margin:14px 0 6px}
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

/* ===== Section headers: bold title with a quiet subtitle directly beneath, no pill chrome ===== */
.section-intro{display:flex;align-items:flex-start;justify-content:space-between;margin:26px 0 6px;flex-wrap:wrap;gap:8px}
.section-intro.compact{margin-top:26px}
.section-intro h2{margin:0;font-size:17px;font-weight:800;letter-spacing:-.01em;color:var(--text)}
.eyebrow{display:none}
.data-badge{font-size:10.5px;font-weight:700;color:var(--red);background:none;border:none;padding:0;box-shadow:none;text-transform:uppercase;letter-spacing:.05em}

/* ===== KPI scorecards: plain white cards, no icon, value carries the color ===== */
.kpi-card{position:relative;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;min-height:92px;box-shadow:var(--shadow-sm);transition:transform .12s ease,box-shadow .12s ease}
.kpi-card:hover{transform:translateY(-1px);box-shadow:var(--shadow-md)}
.kpi-label{display:block;font-size:10.5px;color:var(--muted);letter-spacing:.01em;font-weight:600}
.kpi-value{font-size:21px;font-weight:800;letter-spacing:-.01em;margin-top:9px;color:var(--text);font-variant-numeric:tabular-nums}
.kpi-card.negative .kpi-value{color:var(--red)}
.kpi-card.positive .kpi-value{color:var(--green)}
.kpi-delta{font-size:10.5px;margin-top:5px;font-weight:700}
.kpi-delta.positive{color:var(--green)}.kpi-delta.negative{color:var(--red)}.kpi-delta.neutral{color:var(--muted)}

/* ===== Decision strips / trend lines ===== */
.decision-strip{margin:10px 0 16px;padding:12px 15px;border:1px solid var(--line);border-radius:var(--radius-sm);background:var(--panel);color:var(--text);box-shadow:var(--shadow-sm);font-size:13px}
.decision-strip.positive{border-left:4px solid var(--green);background:var(--green-soft)}
.decision-strip.negative{border-left:4px solid var(--red);background:var(--red-soft)}
.decision-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--blue);margin-right:8px}

/* ===== Insight / finding cards ===== */
.insight-card{display:flex;gap:12px;align-items:flex-start;border:1px solid var(--line);border-radius:var(--radius-md);padding:15px;margin:4px 0 8px;background:var(--panel);min-height:88px;box-shadow:var(--shadow-sm)}
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
.action-number{width:24px;height:24px;border-radius:7px;background:var(--blue-soft);color:var(--blue);display:flex;align-items:center;justify-content:center;font-weight:800;flex:0 0 24px}
.action-row b{color:var(--text)}

/* ===== Chart shells ===== */
.chart-reading{margin:0 3px 10px;padding:9px 11px;border-radius:var(--radius-sm);background:var(--panel-2);border:1px solid var(--line);color:var(--muted);font-size:11.5px;line-height:1.45}
.chart-card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-lg);padding:15px 17px 8px;margin:6px 0 16px;box-shadow:var(--shadow-sm);overflow:hidden}
.chart-card:before{content:"";display:block;width:26px;height:3px;border-radius:3px;background:linear-gradient(90deg,var(--blue),var(--teal));margin:0 0 10px 2px}
.chart-head{display:flex;justify-content:space-between;align-items:flex-start;padding:2px 3px 0}
.chart-title{font-size:15px;letter-spacing:-.01em;font-weight:750;color:var(--text)}
.chart-subtitle{font-size:11px;color:var(--muted);margin-top:3px}
.stPlotlyChart{margin-top:-3px}

/* ===== Tabs ===== */
.stTabs [data-baseweb="tab-list"]{gap:6px;background:var(--panel-2);border:1px solid var(--line);padding:6px;border-radius:14px;box-shadow:var(--shadow-sm);overflow-x:auto}
.stTabs [data-baseweb="tab"]{height:40px;border-radius:10px;padding:0 16px;color:var(--muted);font-weight:700;font-size:13.5px;transition:.15s ease;background:transparent}
.stTabs [data-baseweb="tab"] p{color:inherit;font-weight:inherit}
.stTabs [data-baseweb="tab"]:hover{background:var(--panel);color:var(--text)}
.stTabs [aria-selected="true"]{background:linear-gradient(180deg,#ff3b4e,#e4002b)!important;color:#ffffff!important;box-shadow:0 3px 10px rgba(228,0,43,.3)!important}
.stTabs [aria-selected="true"] p{color:#ffffff!important;font-weight:800!important}
.stTabs [data-baseweb="tab-highlight"]{display:none!important}
.stTabs [data-baseweb="tab-border"]{display:none!important}

/* ===== Buttons: quiet by default, only primary CTAs carry visual weight ===== */
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
  background:linear-gradient(180deg,#ff3b4e,#e4002b)!important;border-color:#e4002b!important;color:#fff!important;
  font-weight:750!important;box-shadow:0 4px 12px rgba(228,0,43,.2)!important;
}
button[kind="primary"]:hover,[data-testid="stDownloadButton"] button[kind="primary"]:hover{
  background:linear-gradient(180deg,#ff5464,#e4002b)!important;color:#fff!important;box-shadow:0 6px 16px rgba(228,0,43,.28)!important;
}
/* Secondary/download buttons that are still an important action (exports)
   get a subtle brand-tinted outline so they read as "do this" without
   competing with the one true primary action on screen. */
[data-testid="stDownloadButton"] button{border-color:var(--blue);color:var(--blue);background:var(--blue-soft)}
[data-testid="stDownloadButton"] button:hover{background:var(--blue);color:#fff;border-color:var(--blue)}
section[data-testid="stSidebar"] [data-testid="stDownloadButton"] button{background:var(--sidebar-panel);color:#ff8f97;border-color:rgba(228,0,43,.4)}
section[data-testid="stSidebar"] [data-testid="stDownloadButton"] button:hover{background:rgba(228,0,43,.18);color:#ffffff}

/* ===== Native inputs: keep readable on a light surface, with a real visible border ===== */
input,textarea{color:var(--text)!important;background:var(--panel)!important;border:1px solid var(--line)!important}
input::placeholder,textarea::placeholder{color:var(--soft)!important;opacity:1!important}
[data-baseweb="select"]>div{background:var(--panel)!important;border:1px solid var(--line)!important;color:var(--text)!important;border-radius:9px!important}
[data-baseweb="select"] *{color:var(--text)!important}
[data-baseweb="popover"]{background:var(--panel)!important;border:1px solid var(--line)!important;box-shadow:var(--shadow-md)!important}
[data-baseweb="menu"]{background:var(--panel)!important}
.stMultiSelect [data-baseweb="tag"]{background:var(--blue-soft)!important}
.stMultiSelect [data-baseweb="tag"] span{color:var(--blue)!important}
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
.executive-card{padding:19px 21px;border:1px solid var(--line);border-radius:var(--radius-lg);background:var(--panel);box-shadow:var(--shadow-md);border-left:5px solid var(--blue);margin:4px 0 10px}
.executive-card.positive{border-left-color:var(--green)}
.executive-card.negative{border-left-color:var(--red)}
.executive-status{font-size:10px;text-transform:uppercase;letter-spacing:.11em;font-weight:800;color:var(--soft)}
.executive-headline{font-size:21px;font-weight:800;color:var(--text);margin-top:6px}
.executive-detail{font-size:12.5px;color:var(--muted);margin-top:7px;line-height:1.5}
.mini-list{padding:9px 12px;background:var(--panel-2);border:1px solid var(--line);border-radius:var(--radius-sm);color:var(--text);font-weight:700}
.mini-positive,.mini-warning{margin-top:6px;padding:9px 11px;border-radius:var(--radius-sm);font-size:12.5px}
.mini-positive{color:#0f7a4e;background:var(--green-soft);border-left:3px solid var(--green)}
.mini-warning{color:#a15c04;background:var(--amber-soft);border-left:3px solid var(--amber)}
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
.drilldown-card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-md);padding:12px 14px}
.smart-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
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
.pbi-visual{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:12px 13px 9px;box-shadow:var(--shadow-sm)}
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
}
</style>
""",unsafe_allow_html=True)

if "workbook" not in st.session_state: st.session_state.workbook=None
if "filters" not in st.session_state: st.session_state.filters={}
if "comparison_result" not in st.session_state: st.session_state.comparison_result=None
if "comparison_error" not in st.session_state: st.session_state.comparison_error=None
if "tracking_data" not in st.session_state: st.session_state.tracking_data=None
if "tracking_error" not in st.session_state: st.session_state.tracking_error=None

# Si hay una base de datos compartida configurada (ver core/db_engine.py),
# cualquiera que abra la app ve automáticamente el historial más reciente
# que haya guardado cualquier otra persona del equipo — sin subir nada.
if db_engine.is_configured() and st.session_state.tracking_data is None:
    try:
        loaded = db_engine.load_from_db()
        if not loaded.empty:
            st.session_state.tracking_data = loaded
    except Exception as e:
        st.session_state.tracking_error = f"No se pudo conectar a la base de datos compartida: {e}"
if "focus_dimension" not in st.session_state: st.session_state.focus_dimension=None
if "focus_metric" not in st.session_state: st.session_state.focus_metric=None
if "focus_view" not in st.session_state: st.session_state.focus_view=None

if not st.session_state.app_started:
    started = render_landing()
    if started:
        st.session_state.app_started = True
        st.rerun()
    st.stop()

st.markdown('<div class="hero"><h1>📊 Panel Analítico Universal</h1><p>De Excel crudo a decisiones: qué pasó, dónde pasó, qué lo explica y qué conviene revisar.</p></div>',unsafe_allow_html=True)

with st.sidebar:
    st.markdown('<div class="sidebar-logo"><div class="sidebar-logo-mark">📊</div><div class="sidebar-logo-text">Panel Analítico<small>Centro de control universal</small></div></div>', unsafe_allow_html=True)

    st.markdown('<p class="sidebar-section-label">Tu archivo</p>', unsafe_allow_html=True)
    upload=st.file_uploader("Cargar Excel / CSV",type=["xlsx","xls","xlsb","xlsm","csv"], key="single_upload", label_visibility="collapsed")
    if upload and st.button("Analizar archivo",type="primary",use_container_width=True):
        with st.spinner("Analizando estructura, fechas, calidad y relaciones..."):
            try:
                st.session_state.workbook=load_workbook(upload)
                st.session_state.filters={}
            except Exception as e:
                st.error(f"No pudimos procesar este archivo: {e}")

    with st.expander("🧰 Herramientas avanzadas", expanded=False):
        st.markdown('<p class="sidebar-section-label" style="margin-top:0;">⚖️ Comparar periodos o archivos</p>', unsafe_allow_html=True)
        compare_uploads=st.file_uploader(
            "Selecciona 2 o más archivos",
            type=["xlsx","xls","xlsb","xlsm","csv"],
            accept_multiple_files=True,
            key="compare_uploads",
            help="Ej.: Enero 2024, Enero 2025. También puedes cargar varios periodos."
        )
        if compare_uploads and st.button("Comparar archivos", use_container_width=True):
            if len(compare_uploads) < 2:
                st.warning("Selecciona al menos dos archivos para comparar.")
            else:
                with st.spinner("Buscando variables equivalentes y calculando cambios..."):
                    try:
                        workbooks=[load_workbook(f) for f in compare_uploads]
                        prepared=prepare_comparison(workbooks)
                        st.session_state.comparison_result=build_comparison(prepared)
                        st.session_state.comparison_error=None
                    except Exception as e:
                        st.session_state.comparison_result=None
                        st.session_state.comparison_error=str(e)
        if st.session_state.comparison_result:
            cr=st.session_state.comparison_result
            st.success(f"Comparativa lista · {len(cr['files'])} archivos")
        if st.session_state.comparison_error:
            st.error(f"No pudimos crear la comparativa: {st.session_state.comparison_error}")

        st.divider()
        st.markdown('<p class="sidebar-section-label">📍 Análisis de seguimiento</p>', unsafe_allow_html=True)
        if db_engine.is_configured():
            st.caption("🟢 Conectado a la base de datos compartida — todo el equipo ve la misma información con este link.")
        else:
            st.caption("🟡 Sin base de datos conectada todavía — modo manual: exporta el consolidado y vuelve a subirlo la próxima vez.")
        tracking_new_files = st.file_uploader(
            "Excel nuevos a procesar",
            type=["xlsx", "xls", "xlsb", "xlsm", "csv"],
            accept_multiple_files=True,
            key="tracking_new_uploads",
        )
        tracking_consolidated_file = None
        if not db_engine.is_configured():
            tracking_consolidated_file = st.file_uploader(
                "Historial consolidado (opcional, el que descargaste la vez anterior)",
                type=["xlsx"],
                accept_multiple_files=False,
                key="tracking_consolidated_upload",
                help="Si no lo subes, se parte de cero solo con los archivos nuevos.",
            )
        if tracking_new_files and st.button("Procesar seguimiento", use_container_width=True, key="tracking_process_btn"):
            with st.spinner("Cruzando funcionarios entre archivos..."):
                try:
                    if db_engine.is_configured():
                        existing = db_engine.load_from_db()
                    elif tracking_consolidated_file is not None:
                        existing = read_consolidated(tracking_consolidated_file)
                    else:
                        existing = None
                    batch_label = datetime.now().strftime("%Y-%m-%d %H:%M")
                    new_long_parts = []
                    for f in tracking_new_files:
                        sources = ingest_file(f, batch_label=batch_label)
                        if not sources:
                            st.warning(f"'{f.name}' no tiene una columna de ID o nombre reconocible; se omitió del cruce.")
                            continue
                        new_long_parts.append(sources_to_long(sources, upload_batch=batch_label))
                    new_long = pd.concat(new_long_parts, ignore_index=True) if new_long_parts else pd.DataFrame()
                    combined = merge_long(existing, new_long)
                    if db_engine.is_configured():
                        db_engine.save_to_db(combined)
                    st.session_state.tracking_data = combined
                    st.session_state.tracking_error = None
                except Exception as e:
                    st.session_state.tracking_error = str(e)
        if st.session_state.tracking_data is not None and not st.session_state.tracking_data.empty:
            td = st.session_state.tracking_data
            st.success(f"Seguimiento listo · {td['person_key'].nunique()} funcionarios · {td['source_file'].nunique()} archivos")
        if st.session_state.tracking_error:
            st.error(f"No pudimos procesar el seguimiento: {st.session_state.tracking_error}")

    wb=st.session_state.workbook
    if wb:
        st.markdown('<p class="sidebar-section-label" style="margin-top:16px;">Hoja activa</p>', unsafe_allow_html=True)
        sheet=st.selectbox("Hoja",list(wb["sheets"]), label_visibility="collapsed")
        item=wb["sheets"][sheet]
        st.session_state.active_sheet = sheet
        df=item["processed"]
        schema=item["profile"]["schema"]
        mode_info=detect_dataset_mode(df, schema)
        st.markdown(f'<div class="mode-banner"><span class="mode-banner-label">MODO DETECTADO</span><br><b>{mode_info["label"]}</b> <span class="mode-confidence">{mode_info["confidence"]*100:.0f}%</span></div>', unsafe_allow_html=True)
        with st.expander("🤖 Asistente IA", expanded=False):
            st.caption("Opcional: conecta una API key para habilitar conversación y análisis asistido.")
            st.session_state.assistant_api_key = st.text_input("OpenAI API key", value=st.session_state.get("assistant_api_key", ""), type="password", key="sidebar_assistant_key")
            st.session_state.assistant_model = st.text_input("Modelo", value=st.session_state.get("assistant_model", "gpt-5.5"), key="sidebar_assistant_model")
        st.markdown('<p class="sidebar-section-label">Vista</p>', unsafe_allow_html=True)
        st.session_state.view_mode = st.radio(
            "Nivel de detalle",
            ["Ejecutivo", "Analista"],
            horizontal=True,
            key="view_mode_radio",
            help="Ejecutivo prioriza conclusiones y visualizaciones. Analista muestra todas las herramientas y controles.",
            label_visibility="collapsed",
        )
        st.markdown('<p class="sidebar-section-label">Filtros</p>', unsafe_allow_html=True)
        st.caption("Selecciona una persona o usa los filtros de contexto. Todo el dashboard se actualiza con la selección.")

        # ── Búsqueda principal de persona ────────────────────────────────
        # Si el archivo tiene Nombre + Apellidos, el usuario trabaja con una
        # sola identidad completa. No debe tener que combinar tres filtros.
        full_name = schema.get("full_name", {})
        full_name_col = full_name.get("column") if isinstance(full_name, dict) else None
        hidden_name_parts = set(full_name.get("parts", [])) if isinstance(full_name, dict) else set()

        if full_name_col and full_name_col in df.columns:
            names = (df[full_name_col].dropna().astype(str).str.strip())
            names = sorted([x for x in names.unique().tolist() if x], key=str.casefold)
            name_key = f"person_filter_{sheet}"
            # El selector es searchable: el usuario puede escribir unas letras
            # para encontrar el nombre, pero siempre selecciona un nombre real
            # existente en el Excel.
            current_name = st.session_state.get(name_key)
            if current_name not in names:
                current_name = None
            selected_name = st.selectbox(
                "Buscar persona",
                names,
                index=(names.index(current_name) if current_name in names else None),
                key=name_key,
                placeholder="Busca y selecciona un nombre completo…",
                help="Empieza a escribir para encontrar un nombre. Al seleccionarlo, todos los datos relacionados se filtran automáticamente.",
            )
            if selected_name:
                st.session_state.filters[full_name_col] = {"op":"in", "value":[selected_name]}
                st.success(f"Mostrando todo lo relacionado con **{selected_name}**")
            elif full_name_col in st.session_state.filters:
                st.session_state.filters.pop(full_name_col, None)

        # ── Periodo ───────────────────────────────────────────────────────
        if schema["dates"]:
            with st.expander("📅 Tiempo", expanded=True):
                dc=schema["dates"][0]
                vals=df[dc].dropna()
                if len(vals):
                    lo,hi=vals.min().date(),vals.max().date()
                    dr=st.date_input("Periodo",value=(lo,hi),min_value=lo,max_value=hi, key=f"period_filter_{sheet}")
                    if isinstance(dr,tuple) and len(dr)==2:
                        st.session_state.filters["__date__"]={"column":dc,"start":pd.Timestamp(dr[0]),"end":pd.Timestamp(dr[1])}

        # ── Filtros de contexto ──────────────────────────────────────────
        filter_columns=[x for x in schema.get("categorical", []) if x in df.columns and not str(x).startswith("__")]
        if full_name_col and full_name_col in df.columns:
            filter_columns=[x for x in filter_columns if x not in hidden_name_parts and x != full_name_col]
        # Evita una barra lateral interminable: muestra primero los campos más
        # útiles y deja el resto dentro de "Más filtros".
        preferred=[]
        sem_map={x.get("column"):x.get("semantic_type") for x in schema.get("semantic",{}).get("columns",[])}
        preferred_types={"region","department","state","zone","city","country","segment","category","product","brand","status","type","customer","employee"}
        for c in filter_columns:
            if sem_map.get(c) in preferred_types:
                preferred.append(c)
        preferred += [c for c in filter_columns if c not in preferred]
        visible_filters=preferred[:4]
        extra_filters=preferred[4:]

        # La fecha también participa en la cascada.
        filter_source=df
        date_rule=st.session_state.filters.get("__date__")
        if isinstance(date_rule,dict) and date_rule.get("column") in df.columns:
            try:
                dcol=date_rule["column"]
                filter_source=df[(df[dcol]>=date_rule["start"]) & (df[dcol]<=date_rule["end"])].copy()
            except Exception:
                filter_source=df

        all_filter_cols=([full_name_col] if full_name_col and full_name_col in df.columns else []) + preferred
        active_categorical={c:r for c,r in st.session_state.filters.items()
                            if not str(c).startswith("__") and isinstance(r,dict) and c in df.columns}
        options_by_col=cascading_options(filter_source, all_filter_cols, active_categorical, limit=2000)

        def render_context_filter(c):
            opts=options_by_col.get(c, [])
            widget_key=f"filter_{sheet}_{c}"
            current=st.session_state.get(widget_key, [])
            if not isinstance(current, list): current=list(current) if current else []
            valid_current=[v for v in current if str(v) in set(opts)]
            if valid_current != current: st.session_state[widget_key]=valid_current
            selected=st.multiselect(str(c),opts,key=widget_key,placeholder="Selecciona opciones…")
            if selected:
                st.session_state.filters[c]={"op":"in","value":selected}
            elif c in st.session_state.filters:
                st.session_state.filters.pop(c,None)

        if visible_filters:
            with st.expander("🎯 Segmentación", expanded=True):
                for c in visible_filters:
                    render_context_filter(c)
        if extra_filters:
            with st.expander(f"Más filtros · {len(extra_filters)} disponibles", expanded=False):
                for c in extra_filters:
                    render_context_filter(c)

        active_count=sum(1 for c in st.session_state.filters if not str(c).startswith("__")) + (1 if "__date__" in st.session_state.filters else 0)
        if active_count:
            if st.button("✕ Limpiar filtros", use_container_width=True, key=f"clear_filters_{sheet}"):
                # Limpia reglas y valores de widgets de la hoja actual.
                st.session_state.filters={}
                for k in list(st.session_state.keys()):
                    if str(k).startswith("filter_") or str(k).startswith("person_filter_") or str(k).startswith("period_filter_"):
                        st.session_state.pop(k, None)
                st.rerun()
            st.caption(f"{active_count} filtro(s) activo(s)")
        st.divider()
        st.caption(f"{wb['filename']} · {wb['size_mb']:.2f} MB")
        st.caption(f"{len(df):,} registros · {len(df.columns)} columnas")

if not st.session_state.workbook:
    if st.session_state.comparison_result:
        render_comparison(st.session_state.comparison_result)
        st.stop()
    if st.session_state.tracking_data is not None and not st.session_state.tracking_data.empty:
        render_tracking(st.session_state.tracking_data)
        st.stop()
    st.info("Carga un archivo para comenzar, o selecciona varios archivos en la sección Comparar periodos o archivos, o usa Análisis de seguimiento en la barra lateral.")
    st.stop()

st.session_state.active_sheet = sheet
item=wb["sheets"][sheet]
df=item["processed"].copy()
schema=item["profile"]["schema"]

# Apply filters globally and defensively.
# A filter must never be able to crash the dashboard if its column
# no longer exists (for example after changing sheets).
valid_filters = {}
if "__date__" in st.session_state.filters:
    f=st.session_state.filters["__date__"]
    date_col=f.get("column")
    if date_col in df.columns:
        valid_filters["__date__"]=f
    else:
        st.session_state.filters.pop("__date__", None)

for c,r in list(st.session_state.filters.items()):
    if c.startswith("__"): continue
    if c in df.columns:
        valid_filters[c]=r
    else:
        # Remove stale filters from previous sheets/files.
        st.session_state.filters.pop(c, None)

if "__date__" in valid_filters:
    f=valid_filters["__date__"]
    date_col=f["column"]
    df=df[(df[date_col]>=f["start"]) & (df[date_col]<=f["end"])]

# Categorical/numeric filters are applied only when their source column exists.
for c,r in valid_filters.items():
    if c.startswith("__"): continue
    op=r.get("op")
    if op=="in":
        df=df[df[c].astype(str).isin([str(v) for v in r.get("value",[])])]
    elif op in {"equals","contains","gt","gte","lt","lte"}:
        df,_meta=apply_filters(df,{c:r})

st.markdown(f"**{len(df):,} registros visibles** · Todos los indicadores y gráficos se recalculan sobre la selección actual.")

query=st.text_input("🔎 Pregúntale al Excel",placeholder="Ej.: mayores a 100000, Bogotá, producto X...")
if query:
    df,_=natural_filter(df,query,schema)
    st.caption(f"Resultado de la consulta: {len(df):,} registros")

mode_info=detect_dataset_mode(df, schema)
dashboard=build_dashboard(df,item["profile"])
classification = mode_info.get("classification", {})
geo_enabled, geo_meta = supports_georeferencing(df, schema)

if classification:
    capabilities = classification.get("capabilities", [])
    cap_labels = {"evolucion":"evolución", "comparacion_periodos":"comparación de periodos", "ranking":"rankings", "distribucion":"distribuciones", "relaciones":"relaciones entre métricas", "estadisticas":"estadísticas", "grafico_distribucion":"gráficos de distribución", "geografia":"geografía", "catalogo":"consulta de catálogo", "estados":"seguimiento de estados"}
    readable_caps = ", ".join(cap_labels.get(x, x) for x in capabilities[:6]) or "lectura y tabla"
    st.markdown(
        f'<div class="mode-banner"><b>Tipo detectado:</b> {classification.get("label", "Datos generales")}'
        f'<span class="mode-confidence">confianza {classification.get("confidence",0)*100:.0f}%</span></div>',
        unsafe_allow_html=True,
    )
    with st.expander("¿Por qué este tipo? Ver detalle", expanded=False):
        st.caption(f'{classification.get("reason", "")} · Herramientas activadas: {readable_caps}.')

if st.session_state.get("focus_view"):
    st.info(f"Análisis enfocado: {st.session_state.focus_view}. Revisa los gráficos y filtros visibles para profundizar.")

# Capacidades individuales: solo aparecen si el Excel realmente contiene una identidad.
full_name_info = schema.get("full_name", {}) if isinstance(schema.get("full_name"), dict) else {}
profile_enabled = bool(full_name_info.get("column") and full_name_info.get("column") in df.columns)

# La comparativa vive en el mismo producto, pero separada del análisis individual.
# El perfil individual NO es una pestaña adicional: se abre con su botón dentro del dashboard.
if mode_info["mode"] in {"catalog", "reference"}:
    st.markdown(f'<div class="mode-banner"><b>{mode_info["label"]}</b> · {mode_info["reason"]}</div>', unsafe_allow_html=True)
    tab_names=["🏠 Inicio","Vista principal"]
    if geo_enabled: tab_names.append("Georeferenciación")
    tab_names += ["Asistente IA","Datos","Calidad","Exportar"]
    if st.session_state.comparison_result: tab_names.append("⚖️ Comparativa")
    if st.session_state.tracking_data is not None and not st.session_state.tracking_data.empty: tab_names.append("📍 Análisis Seguimiento")
    tabs=st.tabs(tab_names)
    tab_map={name: tabs[i] for i,name in enumerate(tab_names)}
    with tab_map["🏠 Inicio"]: render_home(wb, sheet, mode_info, dashboard)
    with tab_map["Vista principal"]: render_catalog(df, schema, mode_info)
    if geo_enabled:
        with tab_map["Georeferenciación"]: render_georeferencing(df, schema)
    with tab_map["Asistente IA"]: render_assistant(df, schema, item["profile"], mode_info, dashboard)
    with tab_map["Datos"]: render_data_table(df)
    with tab_map["Calidad"]: render_quality(item["profile"])
    with tab_map["Exportar"]: render_exports(df,dashboard,wb["filename"],sheet,full_df=item["processed"],schema=schema,workbook=wb)
    if st.session_state.comparison_result:
        with tab_map["⚖️ Comparativa"]: render_comparison(st.session_state.comparison_result)
    if st.session_state.tracking_data is not None and not st.session_state.tracking_data.empty:
        with tab_map["📍 Análisis Seguimiento"]: render_tracking(st.session_state.tracking_data)
else:
    # Executive mode is deliberately compact; Analyst mode exposes every tool.
    if st.session_state.get("view_mode", "Ejecutivo") == "Ejecutivo":
        tab_names=["🏠 Inicio","Resumen ejecutivo"]
        if profile_enabled: tab_names.append("⚔️ Comparar personas")
        if geo_enabled: tab_names.append("Georeferenciación")
        tab_names += ["Asistente IA", "Datos", "Calidad", "Exportar"]
        if st.session_state.comparison_result: tab_names.append("⚖️ Comparativa")
        if st.session_state.tracking_data is not None and not st.session_state.tracking_data.empty: tab_names.append("📍 Análisis Seguimiento")
        tabs=st.tabs(tab_names)
        tab_map={name: tabs[i] for i,name in enumerate(tab_names)}
        with tab_map["🏠 Inicio"]: render_home(wb, sheet, mode_info, dashboard)
        with tab_map["Resumen ejecutivo"]: render_executive(df, schema, dashboard)
        if profile_enabled:
            with tab_map["⚔️ Comparar personas"]: render_person_compare(df, schema)
        if geo_enabled:
            with tab_map["Georeferenciación"]: render_georeferencing(df, schema)
        with tab_map["Asistente IA"]: render_assistant(df, schema, item["profile"], mode_info, dashboard)
        with tab_map["Datos"]: render_data_table(df)
        with tab_map["Calidad"]: render_quality(item["profile"])
        with tab_map["Exportar"]: render_exports(df,dashboard,wb["filename"],sheet,full_df=item["processed"],schema=schema,workbook=wb)
        if st.session_state.comparison_result:
            with tab_map["⚖️ Comparativa"]: render_comparison(st.session_state.comparison_result)
        if st.session_state.tracking_data is not None and not st.session_state.tracking_data.empty:
            with tab_map["📍 Análisis Seguimiento"]: render_tracking(st.session_state.tracking_data)
    else:
        tab_names=["🏠 Inicio","Asistente IA","Descripción"]
        if profile_enabled: tab_names.append("⚔️ Comparar personas")
        if geo_enabled: tab_names.append("Georeferenciación")
        tab_names += ["Analítica","Finanzas","Trabajo","Datos","Calidad","Anomalías","Exportar"]
        if st.session_state.comparison_result: tab_names.append("⚖️ Comparativa")
        if st.session_state.tracking_data is not None and not st.session_state.tracking_data.empty: tab_names.append("📍 Análisis Seguimiento")
        tabs=st.tabs(tab_names)
        tab_map={name: tabs[i] for i,name in enumerate(tab_names)}
        with tab_map["🏠 Inicio"]: render_home(wb, sheet, mode_info, dashboard)
        with tab_map["Asistente IA"]: render_assistant(df, schema, item["profile"], mode_info, dashboard)
        with tab_map["Descripción"]: render_dashboard(df,dashboard)
        if profile_enabled:
            with tab_map["⚔️ Comparar personas"]: render_person_compare(df, schema)
        if geo_enabled:
            with tab_map["Georeferenciación"]: render_georeferencing(df, schema)
        with tab_map["Analítica"]: render_explorer(df,schema)
        with tab_map["Finanzas"]:
            st.subheader("Lectura financiera")
            st.dataframe(dashboard["statistics"],use_container_width=True,hide_index=True)
            st.caption("Esta vista utiliza las métricas detectadas automáticamente; no presupone que el archivo sea de ventas.")
        with tab_map["Trabajo"]:
            st.subheader("Trabajo y decisiones")
            for x in dashboard.get("insights", []):
                title = x.get("title") or x.get("label") or "Hallazgo"
                text = x.get("finding") or x.get("message") or x.get("text") or x.get("description") or "Sin detalle disponible."
                action = x.get("action")
                line = f"**{title}:** {text}"
                if action: line += f"  \n**Qué hacer:** {action}"
                st.markdown(line)
        with tab_map["Datos"]: render_data_table(df)
        with tab_map["Calidad"]: render_quality(item["profile"])
        with tab_map["Anomalías"]: render_anomalies(df, schema)
        with tab_map["Exportar"]: render_exports(df,dashboard,wb["filename"],sheet,full_df=item["processed"],schema=schema,workbook=wb)
        if st.session_state.comparison_result:
            with tab_map["⚖️ Comparativa"]: render_comparison(st.session_state.comparison_result)
        if st.session_state.tracking_data is not None and not st.session_state.tracking_data.empty:
            with tab_map["📍 Análisis Seguimiento"]: render_tracking(st.session_state.tracking_data)

