"""Piezas comunes de los informes HTML descargables: estilos, script y bloques.

Antes cada informe (el de la selección, el de todo el Excel, el comparativo y
el interactivo) traía su propia hoja de estilos, con tamaños, colores y
nombres distintos: el mismo equipo recibía cuatro documentos que no parecían
de la misma herramienta. Aquí vive el único sistema visual de los informes.

Principios del rediseño (lo que se vino a corregir):
- **Lo que hay que hacer va arriba.** El informe abre con el veredicto, el
  semáforo y las prioridades; el detalle técnico queda al final.
- **Cada cosa se dice una vez.** Un hallazgo que ya es un plan de acción no
  se repite como hallazgo, alerta y punto de atención.
- **El detalle se pliega, no se borra.** Tablas largas, metodología y
  gráficos de apoyo van en bloques desplegables (`<details>`); al imprimir
  se abren solos para que el PDF salga completo.

Es un documento independiente (no usa `ui/styles/theme.py`, que es de la app
viva): los dos nunca comparten DOM.
"""
from __future__ import annotations

import html as _html

from ui.labels import clean_display_text

_ESTADO = {
    "critico": ("Crítico", "neg"),
    "atencion": ("En observación", "warn"),
    "mejora": ("Oportunidad", "pos"),
}


def esc(value) -> str:
    return _html.escape(str(value))


def esc_limpio(value) -> str:
    return _html.escape(str(clean_display_text(value)))


def negritas(texto) -> str:
    """Las frases del motor traen **negritas**: se escapan y se convierten."""
    partes = esc_limpio(texto).split("**")
    return "".join(f"<b>{p}</b>" if i % 2 else p for i, p in enumerate(partes))


def seccion(sid: str, titulo: str, bajada: str, cuerpo: str, clase: str = "",
            leer: str = "", fuente: str = "") -> str:
    """Una sección numerada. El número lo pone el CSS (contador), así que
    nunca queda desordenado aunque una sección se descarte por falta de datos.

    Como el informe se proyecta ante gente que no conoce el archivo, cada
    sección puede decir `leer` (cómo interpretar lo que se ve: qué es cada
    barra, contra qué se compara) y `fuente` (de qué hoja, columna, periodo
    y cuántos registros sale). Van en HTML ya armado: quien llama escapa.
    """
    extra = f" {clase}" if clase else ""
    bajada_html = f"<p>{esc(bajada)}</p>" if bajada else ""
    leer_html = f'<div class="leer"><b>Cómo leerlo</b><span>{leer}</span></div>' if leer else ""
    fuente_html = f'<p class="fuente"><b>Fuente</b> {fuente}</p>' if fuente else ""
    return (f'<section class="section{extra}" id="{sid}"><div class="sec-head"><span class="sec-num"></span>'
            f'<div><h2>{esc(titulo)}</h2>{bajada_html}</div></div>{leer_html}{cuerpo}{fuente_html}</section>')


_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]


def mes(fecha, corto: bool = False) -> str:
    """«septiembre de 2026» (o «sep 2026»): los periodos se nombran siempre,
    nunca «el periodo anterior» a secas."""
    try:
        nombre = _MESES[fecha.month - 1]
        return f"{nombre[:3]} {fecha.year}" if corto else f"{nombre} de {fecha.year}"
    except Exception:
        return str(fecha)


def fecha_larga(fecha) -> str:
    try:
        return f"{fecha.day} de {_MESES[fecha.month - 1]} de {fecha.year}"
    except Exception:
        return str(fecha)


def desplegable(resumen: str, cuerpo: str, detalle: str = "", sid: str = "", abierto: bool = False) -> str:
    """Bloque plegable para lo que sirve de soporte pero no debe saturar."""
    if not cuerpo:
        return ""
    ident = f' id="{sid}"' if sid else ""
    nota = f"<small>{esc(detalle)}</small>" if detalle else ""
    return (f'<details class="more"{ident}{" open" if abierto else ""}><summary><span>{esc(resumen)}</span>{nota}</summary>'
            f'<div class="more-body">{cuerpo}</div></details>')


def estado_plan(estado: str) -> tuple[str, str]:
    return _ESTADO.get(estado, (str(estado).capitalize(), "muted"))


def semaforo(plan: dict) -> str:
    """Tres cifras que dicen de un vistazo cuánto hay que atender."""
    planes = (plan or {}).get("planes") or []
    if not planes:
        return ""
    criticos = sum(1 for p in planes if p.get("estado") == "critico")
    atencion = sum(1 for p in planes if p.get("estado") == "atencion")
    mejora = sum(1 for p in planes if p.get("estado") == "mejora")
    return (
        '<div class="semaforo">'
        f'<div class="sem neg"><b>{criticos}</b><span>Crítico{"s" if criticos != 1 else ""}</span></div>'
        f'<div class="sem warn"><b>{atencion}</b><span>En observación</span></div>'
        f'<div class="sem pos"><b>{mejora}</b><span>Oportunidad{"es" if mejora != 1 else ""}</span></div>'
        '</div>'
    )


def prioridades(planes: list, maximo: int = 3, con_hoja: bool = False, enlace: str = "") -> str:
    """Las primeras cosas que hay que hacer: frente, estado, dato y primer paso."""
    filas = []
    for p in (planes or [])[:maximo]:
        nombre, tono = estado_plan(p.get("estado", ""))
        pasos = p.get("pasos") or []
        primero = f'<p class="prio-next"><b>Primer paso:</b> {esc_limpio(pasos[0])}</p>' if pasos else ""
        hoja = f'<span class="tag">{esc(p.get("_hoja"))}</span>' if con_hoja and p.get("_hoja") else ""
        filas.append(
            f'<li class="prio {tono}"><span class="pill {tono}">{esc(nombre)}</span>'
            f'<div class="prio-body"><h3>{hoja}{esc_limpio(p.get("titulo", "Frente de trabajo"))}</h3>'
            f'<p>{esc_limpio(p.get("situacion", ""))}</p>{primero}</div></li>'
        )
    if not filas:
        return ""
    ver = f'<a class="link-more" href="#{enlace}">Ver el plan completo →</a>' if enlace else ""
    return f'<ol class="prio-list">{"".join(filas)}</ol>{ver}'


def tablero_seguimiento(planes: list) -> str:
    """Tabla para llevar a la reunión: frente, responsable, fecha y cómo se
    sabe que quedó cerrado. Responsable y fecha van en blanco a propósito:
    se llenan con el equipo, no los inventa el análisis."""
    if not planes:
        return ""
    filas = []
    for i, p in enumerate(planes, 1):
        nombre, tono = estado_plan(p.get("estado", ""))
        filas.append(
            f'<tr><td class="num muted">{i}</td><td><b>{esc_limpio(p.get("titulo", ""))}</b></td>'
            f'<td><span class="pill {tono}">{esc(nombre)}</span></td>'
            f'<td class="fill"></td><td class="fill"></td>'
            f'<td class="muted">{esc_limpio(p.get("medir", ""))}</td></tr>'
        )
    return ('<div class="table-card"><table class="tablero"><thead><tr><th class="num">#</th><th>Frente</th>'
            '<th>Estado</th><th>Responsable</th><th>Fecha</th><th>Se cierra cuando…</th></tr></thead>'
            f'<tbody>{"".join(filas)}</tbody></table></div>')


def nav(grupos: list[tuple[str, list[tuple[str, str]]]], titulo: str, subtitulo: str) -> str:
    """Menú lateral. Los números siguen el orden del documento."""
    partes, n = [], 0
    for etiqueta, items in grupos:
        if not items:
            continue
        partes.append(f'<div class="nav-group">{esc(etiqueta)}</div>')
        for sid, texto in items:
            n += 1
            partes.append(f'<a href="#{sid}"><i>{n:02d}</i><span>{esc(texto)}</span></a>')
    return (f'<nav class="side-nav"><div class="nav-brand"><div class="nav-dot"></div><div><b>{esc(titulo)}</b>'
            f'<small>{esc(subtitulo)}</small></div></div>{"".join(partes)}</nav>')


def documento(titulo: str, cuerpo: str, nav_html: str = "", css_extra: str = "", head_extra: str = "",
              presentar: bool = True) -> str:
    """Envuelve el informe con estilos, menú y script comunes.

    `presentar` agrega el botón «▶ Presentar»: el informe pasa a pantalla
    completa y muestra una sección por diapositiva (flechas para avanzar,
    Esc para salir). Estos HTML se proyectan en reuniones; sin este modo
    había que ir haciendo scroll delante de todos.
    """
    shell = (f'<div class="report-shell">{nav_html}<main class="wrap">{cuerpo}</main></div>' if nav_html
             else f'<div class="report-shell single"><main class="wrap">{cuerpo}</main></div>')
    marca = ' data-presentar="1"' if presentar else ""
    return (f'<!doctype html>\n<html lang="es">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">\n<title>{esc(titulo)}</title>\n'
            f'{head_extra}<style>{CSS}{css_extra}</style>\n</head>\n<body{marca}>\n{shell}\n<script>{JS}</script>\n</body></html>')


CSS = """
:root{--bg:#f3f5f9;--card:#fff;--ink:#0f172a;--text:#1e293b;--muted:#5b6b82;--soft:#94a3b8;
--line:#e2e8f0;--line-soft:#f1f4f8;--brand:#e4002b;--brand-dark:#b00020;--brand-soft:#fff1f3;
--pos:#0f8a5f;--pos-soft:#e7f6ef;--warn:#b45309;--warn-soft:#fdf3e2;--neg:#be123c;--neg-soft:#fdecef;
--radius:14px;--shadow:0 1px 2px rgba(15,23,42,.04),0 4px 14px rgba(15,23,42,.05)}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,"Segoe UI",Roboto,Arial,sans-serif;font-size:14px;line-height:1.55;-webkit-font-smoothing:antialiased}
.report-shell{display:flex;align-items:flex-start;gap:28px;max-width:1440px;margin:0 auto;padding:28px 24px 72px}
.report-shell.single{max-width:1180px}
.wrap{flex:1;min-width:0;counter-reset:sec}
p{margin:0}
b{color:var(--ink)}

/* Menú lateral */
.side-nav{width:228px;flex:0 0 228px;position:sticky;top:20px;max-height:calc(100vh - 40px);overflow-y:auto;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:16px 12px;box-shadow:var(--shadow)}
.nav-brand{display:flex;align-items:center;gap:10px;padding:0 6px 13px;border-bottom:1px solid var(--line-soft);margin-bottom:8px}
.nav-dot{width:24px;height:24px;border-radius:50%;background:radial-gradient(circle at 32% 28%,#ff4d5f,var(--brand) 60%,var(--brand-dark));flex:0 0 24px}
.nav-brand b{font-size:12.5px;display:block;line-height:1.25}
.nav-brand small{font-size:10.5px;color:var(--soft);display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:150px}
.nav-group{font-size:9.5px;font-weight:800;letter-spacing:.12em;color:var(--soft);text-transform:uppercase;margin:14px 8px 5px}
.side-nav a{display:flex;gap:9px;align-items:baseline;padding:6px 8px;border-radius:8px;font-size:12.5px;color:var(--text);text-decoration:none;border-left:3px solid transparent}
.side-nav a i{font-style:normal;font-size:9.5px;font-weight:800;color:var(--soft);min-width:15px}
.side-nav a span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.side-nav a:hover{background:var(--line-soft);color:var(--brand)}
.side-nav a.active{background:var(--brand-soft);color:var(--brand-dark);border-left-color:var(--brand);font-weight:700}

/* Portada */
.cover{background:linear-gradient(135deg,#111827 0%,#1c2340 60%,#3b0f1f 100%);border-radius:18px;padding:28px 32px 24px;color:#fff;position:relative;overflow:hidden}
.cover:before{content:"";position:absolute;right:-110px;top:-110px;width:340px;height:340px;border-radius:50%;background:radial-gradient(circle,rgba(228,0,43,.38),transparent 68%)}
.cover>*{position:relative}
.cover-kicker{font-size:10.5px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:#ff8da0}
.cover h1{margin:8px 0 8px;font-size:30px;letter-spacing:-.03em;line-height:1.15;color:#fff}
.cover .lead{color:#cbd3e3;font-size:14.5px;max-width:760px}
.cover-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:18px;margin-top:22px;padding-top:18px;border-top:1px solid rgba(255,255,255,.14)}
.cover-stat b{display:block;font-size:24px;font-weight:800;letter-spacing:-.02em;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cover-stat span{font-size:10.5px;color:#9aa4bd;text-transform:uppercase;letter-spacing:.08em;font-weight:700}
.cover-stat.pos b{color:#5ee0a4}.cover-stat.neg b{color:#ff8da0}.cover-stat.warn b{color:#fcd38a}
.cover-meta{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:16px;font-size:11.5px;color:#9aa4bd}
.cover-meta b{color:#dfe5f0;font-weight:600}

/* Secciones */
.section{margin-top:40px;scroll-margin-top:16px}
.sec-head{display:flex;gap:12px;align-items:flex-start;margin-bottom:16px}
.sec-num{font-size:11px;font-weight:800;color:var(--brand);background:var(--brand-soft);border-radius:7px;padding:5px 8px;flex:0 0 auto;margin-top:2px;min-width:30px;text-align:center}
.sec-num:before{counter-increment:sec;content:counter(sec,decimal-leading-zero)}
body.num-fijo .sec-num:before{content:attr(data-n)}
.sec-head h2{font-size:20px;margin:0;letter-spacing:-.02em;color:var(--ink);line-height:1.25}
.sec-head p{margin-top:3px;color:var(--muted);font-size:13px}
h3{color:var(--ink)}

/* Veredicto */
.verdict{display:grid;grid-template-columns:1fr auto;gap:18px;align-items:center;background:var(--card);border:1px solid var(--line);border-left:5px solid var(--soft);border-radius:var(--radius);padding:18px 22px;box-shadow:var(--shadow)}
.verdict.pos{border-left-color:var(--pos)}.verdict.neg{border-left-color:var(--neg)}.verdict.warn{border-left-color:var(--warn)}
.verdict h3{margin:0 0 4px;font-size:19px;letter-spacing:-.015em;line-height:1.3}
.verdict p{color:var(--muted);font-size:13px}
.delta{font-size:26px;font-weight:800;white-space:nowrap;padding:8px 14px;border-radius:12px;background:var(--line-soft);color:var(--muted)}
.delta.pos{background:var(--pos-soft);color:var(--pos)}.delta.neg{background:var(--neg-soft);color:var(--neg)}.delta.warn{background:var(--warn-soft);color:var(--warn)}
.resumen-grid{display:grid;grid-template-columns:minmax(0,1fr) 250px;gap:16px;margin-top:16px;align-items:start}
.subhead{font-size:10.5px;font-weight:800;letter-spacing:.11em;text-transform:uppercase;color:var(--muted);margin:0 0 8px}
.semaforo{display:grid;gap:8px}
.sem{display:flex;align-items:center;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px}
.sem b{font-size:24px;font-weight:800;min-width:30px}
.sem span{font-size:12px;color:var(--muted);font-weight:600}
.sem.neg b{color:var(--neg)}.sem.warn b{color:var(--warn)}.sem.pos b{color:var(--pos)}
.a-favor{margin-top:10px;background:var(--pos-soft);border-radius:12px;padding:10px 14px;font-size:12.5px}
.a-favor ul{margin:4px 0 0;padding-left:16px}

/* Prioridades */
.prio-list{list-style:none;margin:0;padding:0;display:grid;gap:10px}
.prio{display:flex;gap:14px;align-items:flex-start;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--soft);border-radius:12px;padding:13px 16px;box-shadow:var(--shadow)}
.prio.neg{border-left-color:var(--neg)}.prio.warn{border-left-color:var(--warn)}.prio.pos{border-left-color:var(--pos)}
.prio .pill{margin-top:2px;flex:0 0 auto;min-width:104px;text-align:center}
.prio-body h3{margin:0 0 3px;font-size:14.5px}
.prio-body p{font-size:13px;color:var(--text)}
.prio-body .prio-next{margin-top:5px;font-size:12.5px;color:var(--muted)}
.tag{display:inline-block;font-size:9.5px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--brand);background:var(--brand-soft);border-radius:6px;padding:2px 7px;margin-right:8px;vertical-align:2px}
.link-more{display:inline-block;margin-top:10px;font-size:12.5px;font-weight:700;color:var(--brand);text-decoration:none}

/* Píldoras */
.pill{display:inline-block;font-size:10px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;padding:4px 9px;border-radius:999px;background:var(--line-soft);color:var(--muted);white-space:nowrap}
.pill.neg{background:var(--neg-soft);color:var(--neg)}.pill.warn{background:var(--warn-soft);color:var(--warn)}.pill.pos{background:var(--pos-soft);color:var(--pos)}

/* KPIs */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;box-shadow:var(--shadow)}
.kpi-label{font-size:10.5px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.05em;line-height:1.35}
.kpi-value{font-size:24px;font-weight:800;margin-top:6px;letter-spacing:-.02em;color:var(--ink);line-height:1.2;overflow-wrap:anywhere}
.kpi-sub{font-size:12px;color:var(--muted);margin-top:2px}
.kpi-delta{font-size:12px;font-weight:700;margin-top:4px;color:var(--muted)}
.kpi-delta.pos{color:var(--pos)}.kpi-delta.neg{color:var(--neg)}

/* Tarjetas, gráficos y tablas */
.grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.chart-card,.table-card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;box-shadow:var(--shadow);margin-top:12px;min-width:0}
.grid2>.chart-card,.grid2>.table-card{margin-top:0}
.chart-head h3{margin:0;font-size:14.5px}
.chart-head p{margin:2px 0 4px;color:var(--muted);font-size:12px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{padding:8px 9px;border-bottom:1px solid var(--line-soft);text-align:left;vertical-align:middle}
thead th{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.07em;border-bottom:1.5px solid var(--line);font-weight:700}
tbody tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.table-scroll{overflow-x:auto}
.barcell{width:34%}
.bar{display:block;height:8px;border-radius:4px;background:var(--brand);min-width:2px}
.bar.soft{background:#cbd5e1}
.muted{color:var(--muted)}
.note{font-size:12px;color:var(--muted);margin-top:8px}
.empty{padding:20px;background:var(--card);border:1px dashed var(--line);border-radius:12px;color:var(--muted);font-size:13px}
.callout{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--brand);border-radius:12px;padding:12px 16px;font-size:13.5px;color:var(--ink);box-shadow:var(--shadow)}
.callout.pos{border-left-color:var(--pos)}.callout.warn{border-left-color:var(--warn)}.callout.neg{border-left-color:var(--neg)}

/* Cómo leerlo y fuente: el contexto que el público no tiene */
.leer{display:flex;gap:12px;align-items:baseline;background:var(--line-soft);border-radius:10px;padding:9px 14px;margin:-4px 0 14px;font-size:13px;color:var(--text)}
.leer b{flex:0 0 auto;font-size:10px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.fuente{margin-top:14px;font-size:11.5px;color:var(--muted);line-height:1.5}
.fuente b{font-size:9.5px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--soft);margin-right:6px}

/* Sobre este informe */
.ctx-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
.ctx-card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;box-shadow:var(--shadow)}
.ctx-card h3{margin:0 0 10px;font-size:14px;display:flex;gap:8px;align-items:center}
.ctx-card dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:6px 12px;font-size:13px}
.ctx-card dt{color:var(--muted);font-weight:600}
.ctx-card dd{margin:0;color:var(--ink);font-weight:600;overflow-wrap:anywhere}
.ctx-card p{font-size:13px;line-height:1.55}
.ctx-card p+p{margin-top:6px}
.leyenda{list-style:none;margin:0;padding:0;display:grid;gap:8px;font-size:13px}
.leyenda li{display:flex;gap:10px;align-items:baseline}
.leyenda .pill{min-width:112px;text-align:center}
.agenda{list-style:none;margin:14px 0 0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:8px 18px;counter-reset:ag}
.agenda li{counter-increment:ag;display:flex;gap:10px;font-size:13px;line-height:1.45;padding:8px 0;border-top:1px solid var(--line)}
.agenda li:before{content:counter(ag,decimal-leading-zero);font-size:11px;font-weight:800;color:var(--brand);min-width:20px;padding-top:2px}
.agenda b{display:block;color:var(--ink)}
.agenda span{color:var(--muted)}
@media(max-width:860px){.ctx-grid{grid-template-columns:1fr}}

/* Lecturas en viñetas */
.bullets{margin:12px 0 0;padding:0;list-style:none;display:grid;gap:6px}
.bullets li{position:relative;padding-left:18px;font-size:13px;line-height:1.5}
.bullets li:before{content:"";position:absolute;left:4px;top:.6em;width:6px;height:6px;border-radius:50%;background:var(--brand)}

/* Hallazgos */
.findings{display:grid;gap:10px}
.finding{display:grid;grid-template-columns:10px 1fr;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:13px 16px;box-shadow:var(--shadow)}
.finding .dot{width:10px;height:10px;border-radius:50%;margin-top:6px;background:var(--soft)}
.finding.pos .dot{background:var(--pos)}.finding.warn .dot{background:var(--warn)}.finding.neg .dot{background:var(--neg)}
.finding h3{margin:0 0 2px;font-size:14px}
.finding p{font-size:13px}
.finding .action{margin-top:6px;font-size:12.5px;color:var(--muted)}
.finding .action b{color:var(--brand-dark)}
.evidence{list-style:none;margin:8px 0 0;padding:0;display:flex;flex-wrap:wrap;gap:6px}
.evidence li{font-size:11.5px;background:var(--line-soft);border-radius:8px;padding:4px 9px;line-height:1.35}
.evidence .ev-name{font-weight:700;color:var(--ink)}
.evidence .ev-value{font-weight:700;margin-left:6px;font-variant-numeric:tabular-nums}
.evidence .ev-detail{color:var(--muted);margin-left:6px}

/* Desplegables */
details.more{margin-top:12px;background:var(--card);border:1px solid var(--line);border-radius:12px;scroll-margin-top:16px}
details.more>summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:10px;padding:11px 16px;font-size:13px;font-weight:700;color:var(--ink)}
details.more>summary::-webkit-details-marker{display:none}
details.more>summary:before{content:"";width:7px;height:7px;border-right:2px solid var(--brand);border-bottom:2px solid var(--brand);transform:rotate(-45deg);transition:transform .15s ease;flex:0 0 auto}
details.more[open]>summary:before{transform:rotate(45deg)}
details.more>summary small{margin-left:auto;font-weight:500;color:var(--soft);font-size:11.5px}
details.more>summary:hover{color:var(--brand)}
.more-body{padding:0 16px 16px}
.more-body>.table-card:first-child,.more-body>.chart-card:first-child{margin-top:0}
.more-body .table-card,.more-body .chart-card{box-shadow:none}
details.more details.more{background:var(--line-soft)}

/* Metodología del cuadro */
.base-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px 20px}
.base-item b{display:block;font-size:12px;margin-bottom:2px}
.base-item span{font-size:12px;color:var(--muted);line-height:1.5}

/* Estrategia por canal */
.canal-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin-top:12px}
.canal-card{background:var(--card);border:1px solid var(--line);border-top:4px solid var(--brand);border-radius:12px;padding:12px 14px;box-shadow:var(--shadow)}
.canal-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.canal-head b{font-size:14px}
.canal-head span{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);font-weight:700}
.canal-barra{height:6px;border-radius:99px;background:var(--line-soft);margin:10px 0}
.canal-barra span{display:block;height:6px;border-radius:99px}
.canal-datos{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;text-align:center}
.canal-datos span{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.canal-datos b{display:block;font-size:15px;color:var(--ink);letter-spacing:0;text-transform:none}
.canal-jugada{margin-top:10px;padding-top:8px;border-top:1px dashed var(--line);font-size:12px;font-weight:700;color:var(--brand-dark)}
.jugadas-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;margin-top:4px}
.jugada{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--soft);border-radius:12px;padding:12px 14px;box-shadow:var(--shadow);min-width:0}
.jugada.neg{border-left-color:var(--neg)}.jugada.pos{border-left-color:var(--pos)}
.jugada-top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:8px}
.jugada-top>div:first-child{min-width:0}
.jugada-tipo{display:block;font-size:10px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.jugada-canal{display:block;font-size:15px;margin-top:2px;overflow-wrap:anywhere}
.jugada-impacto{text-align:right;flex:0 0 auto}
.jugada-impacto b{display:block;font-size:20px;font-weight:800;line-height:1.1;color:var(--ink)}
.jugada-impacto span{display:block;font-size:10px;color:var(--soft);margin-top:2px}
.jugada.neg .jugada-impacto b{color:var(--neg)}.jugada.pos .jugada-impacto b{color:var(--pos)}
.jugada p{font-size:13px;line-height:1.45}
.jugada b.neg{color:var(--neg)}.jugada b.pos{color:var(--pos)}
.jugada p.palanca{font-size:12px;color:var(--muted);margin-top:4px}

/* Plan de acción */
.planes-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.plan{background:var(--card);border:1px solid var(--line);border-top:4px solid var(--soft);border-radius:12px;padding:14px 16px;box-shadow:var(--shadow);display:flex;flex-direction:column}
.plan.neg{border-top-color:var(--neg)}.plan.warn{border-top-color:var(--warn)}.plan.pos{border-top-color:var(--pos)}
.plan-head{display:flex;justify-content:space-between;align-items:center}
.plan-num{font-size:11px;color:var(--soft);font-weight:800}
.plan h3{font-size:15px;margin:8px 0 4px;line-height:1.3}
.plan .situacion{font-size:13px;color:var(--text)}
.plan-lbl{font-size:9.5px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--soft);margin:10px 0 3px}
.plan-lbl+.chips{margin-top:0}
.plan-lbl+.pasos{margin-top:0}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
.chip{font-size:11px;background:var(--line-soft);border-radius:99px;padding:2px 9px;color:var(--ink);font-weight:600}
.pasos{margin:10px 0 0 18px;padding:0}
.pasos li{font-size:12.5px;line-height:1.5;margin-bottom:3px}
.plan-meta{margin-top:auto;padding-top:9px;font-size:12px;color:var(--muted);border-top:1px dashed var(--line)}
.plan .pasos+.plan-meta,.plan .chips+.plan-meta{margin-top:10px}
.tablero td.fill{min-width:120px;border-bottom:1px solid var(--line)}

/* Libro completo */
.sheet-section{margin-top:48px;padding-top:26px;border-top:2px solid var(--line);scroll-margin-top:16px}
.sheet-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:14px}
.sheet-heading .kicker{font-size:10px;font-weight:800;letter-spacing:.13em;color:var(--brand);text-transform:uppercase}
.sheet-heading h2{margin:3px 0 2px;font-size:23px;letter-spacing:-.02em;color:var(--ink)}
.sheet-heading p{color:var(--muted);font-size:12.5px}
.sheet-section .section{margin-top:28px}
.sheet-section .sec-num{display:none}
.sheet-section .sec-head h2{font-size:17px}
.go{font-size:12px;font-weight:700;color:var(--brand);text-decoration:none;white-space:nowrap}
.footer{margin-top:48px;padding-top:14px;border-top:1px solid var(--line);color:var(--soft);font-size:11.5px;text-align:center}

/* Modo presentación: una sección por diapositiva, a pantalla completa */
.present-btn{position:fixed;bottom:22px;right:22px;z-index:60;display:flex;align-items:center;gap:7px;background:var(--ink);color:#fff;border:0;border-radius:999px;padding:10px 17px;font:700 12.5px/1 Inter,"Segoe UI",Arial,sans-serif;cursor:pointer;box-shadow:0 6px 18px rgba(15,23,42,.22)}
.present-btn:hover{background:var(--brand)}
.present-bar{display:none}
body.presenting{background:#fff}
body.presenting .side-nav,body.presenting .present-btn,body.presenting .footer{display:none!important}
body.presenting .report-shell{display:block;max-width:1320px;padding:40px 56px 110px}
body.presenting .wrap>*{display:none}
body.presenting .wrap>.slide-on{display:block;margin-top:0;animation:slideIn .28s ease}
body.presenting .cover.slide-on{min-height:calc(100vh - 160px);display:flex;flex-direction:column;justify-content:center;padding:56px 60px}
body.presenting .cover h1{font-size:46px}
body.presenting .cover .lead{font-size:18px}
body.presenting .cover-stat b{font-size:34px}
body.presenting .sec-head{margin-bottom:22px}
body.presenting .sec-head h2{font-size:32px}
body.presenting .sec-head p{font-size:16px}
body.presenting .sec-num{font-size:14px;padding:7px 11px}
body.presenting .verdict h3{font-size:24px}
body.presenting .prio-body h3,body.presenting .plan h3{font-size:17px}
body.presenting .prio-body p,body.presenting .bullets li,body.presenting .plan .situacion,body.presenting .finding p,body.presenting .callout,body.presenting .jugada p{font-size:15px}
body.presenting .kpi-value{font-size:30px}
body.presenting .sheet-heading h2{font-size:32px}
body.presenting .present-bar{display:flex;align-items:center;gap:6px;position:fixed;left:50%;bottom:20px;transform:translateX(-50%);z-index:60;background:rgba(15,23,42,.92);color:#fff;border-radius:999px;padding:6px 8px;box-shadow:0 10px 30px rgba(15,23,42,.3);font-size:13px;max-width:calc(100vw - 32px)}
.present-bar button{background:transparent;border:0;color:#fff;font:700 15px/1 inherit;padding:8px 12px;border-radius:999px;cursor:pointer}
.present-bar button:hover{background:rgba(255,255,255,.14)}
.present-bar .p-count{font-weight:800;padding:0 4px;font-variant-numeric:tabular-nums}
.present-bar .p-title{color:#cbd3e3;max-width:340px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:0 6px}
.present-bar .p-exit{font-size:12px;color:#ff8da0}
@keyframes slideIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@media(max-width:860px){.present-btn{bottom:16px;right:16px}body.presenting .report-shell{padding:20px 14px 100px}.present-bar .p-title{display:none}}
@media print{.present-btn,.present-bar{display:none!important}}
@media(max-width:1100px){.side-nav{display:none}}
@media(max-width:860px){
  .report-shell{padding:16px 12px 48px}
  .cover{padding:22px 20px}.cover h1{font-size:24px}
  .grid2,.resumen-grid,.base-grid{grid-template-columns:1fr}
  .verdict{grid-template-columns:1fr}
  .prio{flex-direction:column;gap:8px}
  .sheet-heading{flex-direction:column}
}
@media print{
  @page{margin:13mm}
  body{background:#fff;font-size:12.5px}
  .side-nav,.link-more{display:none!important}
  .report-shell{padding:0;display:block;max-width:none}
  .cover{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .section{margin-top:24px}
  .sheet-section,#anexo{break-before:page;page-break-before:always}
  .kpi,.chart-card,.table-card,.verdict,.prio,.plan,.canal-card,.jugada,.finding,.sem,details.more{box-shadow:none!important;break-inside:avoid;page-break-inside:avoid}
  details.more>summary:before{display:none}
  a{text-decoration:none;color:inherit}
}
"""

JS = """
(function(){
  function resizePlots(root){
    if(!window.Plotly||!root)return;
    root.querySelectorAll('.js-plotly-plot').forEach(function(p){try{Plotly.Plots.resize(p);}catch(e){}});
  }
  // Un gráfico dibujado dentro de un bloque cerrado nace con el tamaño por
  // defecto: al abrirlo se ajusta al ancho real.
  document.querySelectorAll('details').forEach(function(d){
    d.addEventListener('toggle',function(){ if(d.open) resizePlots(d); });
  });
  // Un enlace del menú que apunta a algo plegado lo abre antes de saltar.
  function openTarget(id){
    var el=document.getElementById(id); if(!el)return;
    var n=el; while(n){ if(n.tagName==='DETAILS') n.open=true; n=n.parentElement; }
  }
  document.querySelectorAll('a[href^="#"]').forEach(function(a){
    a.addEventListener('click',function(){ openTarget(a.getAttribute('href').slice(1)); });
  });
  if(location.hash) openTarget(location.hash.slice(1));
  // Al imprimir o guardar como PDF sale todo, no solo lo que estaba abierto.
  window.addEventListener('beforeprint',function(){
    document.querySelectorAll('details').forEach(function(d){d.open=true;});
    resizePlots(document);
  });
  var links=Array.prototype.slice.call(document.querySelectorAll('.side-nav a[href^="#"]'));
  var targets=links.map(function(a){return document.getElementById(a.getAttribute('href').slice(1));});
  function onScroll(){
    var pos=window.scrollY+140, current=-1;
    targets.forEach(function(s,i){ if(s&&s.offsetParent!==null&&s.getBoundingClientRect().top+window.scrollY<=pos) current=i; });
    links.forEach(function(a,i){ a.classList.toggle('active', i===current); });
  }
  if(links.length){ window.addEventListener('scroll',onScroll,{passive:true}); onScroll(); }

  // Números de sección fijos: el contador de CSS no cuenta lo que está
  // oculto, y en modo presentación todas menos una lo están.
  var n=0;
  document.querySelectorAll('.wrap .sec-num').forEach(function(el){
    if(el.offsetParent!==null){ n+=1; el.setAttribute('data-n',(n<10?'0':'')+n); }
  });
  document.body.classList.add('num-fijo');

  // Modo presentación.
  if(document.body.getAttribute('data-presentar')){
    var slides=Array.prototype.slice.call(document.querySelectorAll('.wrap > .cover, .wrap > .section, .wrap > .sheet-section'));
    if(slides.length>1){
      var idx=0, pantalla=false;
      var btn=document.createElement('button');
      btn.className='present-btn'; btn.type='button'; btn.title='Mostrar una sección por pantalla (flechas para avanzar, Esc para salir)';
      btn.innerHTML='&#9654; Presentar';
      var bar=document.createElement('div');
      bar.className='present-bar';
      bar.innerHTML='<button type="button" data-a="prev" title="Anterior">&#8249;</button><span class="p-count"></span>'+
        '<button type="button" data-a="next" title="Siguiente">&#8250;</button><span class="p-title"></span>'+
        '<button type="button" class="p-exit" data-a="exit">Salir &#10005;</button>';
      document.body.appendChild(btn); document.body.appendChild(bar);
      var titulo=function(el){var h=el.querySelector('h1,h2');return h?h.textContent.trim():'';};
      var show=function(i){
        idx=Math.max(0,Math.min(slides.length-1,i));
        slides.forEach(function(el,k){el.classList.toggle('slide-on',k===idx);});
        window.scrollTo(0,0);
        bar.querySelector('.p-count').textContent=(idx+1)+' / '+slides.length;
        bar.querySelector('.p-title').textContent=titulo(slides[idx]);
        setTimeout(function(){resizePlots(slides[idx]);},30);
      };
      var start=function(){
        document.body.classList.add('presenting'); show(0);
        var de=document.documentElement;
        if(de.requestFullscreen){ de.requestFullscreen().then(function(){pantalla=true;}).catch(function(){}); }
      };
      var stop=function(){
        document.body.classList.remove('presenting');
        slides.forEach(function(el){el.classList.remove('slide-on');});
        if(document.fullscreenElement&&document.exitFullscreen){ document.exitFullscreen().catch(function(){}); }
        pantalla=false; setTimeout(function(){resizePlots(document);},30);
      };
      btn.addEventListener('click',start);
      bar.addEventListener('click',function(e){
        var a=e.target.closest('button'); if(!a)return;
        var acc=a.getAttribute('data-a');
        if(acc==='prev')show(idx-1); else if(acc==='next')show(idx+1); else if(acc==='exit')stop();
      });
      document.addEventListener('keydown',function(e){
        if(!document.body.classList.contains('presenting'))return;
        if(/INPUT|SELECT|TEXTAREA/.test((e.target||{}).tagName||''))return;
        var k=e.key;
        if(k==='ArrowRight'||k==='PageDown'||k===' '){e.preventDefault();show(idx+1);}
        else if(k==='ArrowLeft'||k==='PageUp'){e.preventDefault();show(idx-1);}
        else if(k==='Home'){show(0);} else if(k==='End'){show(slides.length-1);}
        else if(k==='Escape'){stop();}
      });
      // Si el navegador sale de pantalla completa (Esc), se sale también del modo.
      document.addEventListener('fullscreenchange',function(){
        if(!document.fullscreenElement&&pantalla&&document.body.classList.contains('presenting'))stop();
      });
    }
  }
})();
"""
