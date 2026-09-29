"""Pestaña "Planes de mejora".

Cada hallazgo del análisis convertido en un plan con pasos concretos y una
forma de medir si funcionó. Ver `core/planes.py` para el criterio; aquí solo
se presenta.

La pantalla sigue el orden en que se usa en una reunión:

1. **El resumen del periodo**: cuántos frentes hay, repartidos por urgencia en
   una sola barra, y un anillo con el avance real del plan. Se entiende de un
   golpe si el plan está empezando, a medias o casi listo.
2. **El tablero**: una columna por urgencia y una tarjeta por plan, con a quién
   afecta, su avance, quién lo lleva y cómo se mide. Es la vista para mirar.
   Antes esa función la cumplía una tabla, que era práctica pero parecía una
   hoja de cálculo pegada en la pantalla.
3. **Asignar responsables y fechas**: la tabla sigue, pero solo con lo que se
   edita. Todo lo demás ya está en el tablero.
4. **Los pasos de cada plan**, plegables y con casillas para marcar.

Lo práctico se conserva completo: el estado y el avance salen de las casillas,
las alertas de vencido y sin responsable están a la vista, y el plan se
descarga en Excel o en texto. Las funciones sin interfaz (estado, alertas,
filas, Excel y resumen) están separadas del dibujo para poder probarlas sin
Streamlit.
"""
from __future__ import annotations

import hashlib
import html
import io
from datetime import date

import pandas as pd
import streamlit as st

from core.planes import generar
from ui.components.cards import evidence_list
from ui.components.section import section_header
from ui.labels import clean_display_text

_TONO = {
    "critico": {"color": "#E4002B", "etiqueta": "Crítico", "icono": "🔴", "urgencia": "Atender primero"},
    "atencion": {"color": "#F59E0B", "etiqueta": "En observación", "icono": "🟡", "urgencia": "Revisar este periodo"},
    "mejora": {"color": "#22A06B", "etiqueta": "Oportunidad", "icono": "🟢", "urgencia": "Margen disponible"},
}

# Nombres de evidencia que no son un caso sino una referencia ("Mediana del
# grupo") y no deben aparecer en "A quién afecta".
_NO_SON_CASOS = {"Valor más extremo", "Filas repetidas", "Su resultado", "Mediana del grupo",
                 "Total del archivo", "Registros propios", "Su aporte", "Su tasa", "Tasa del archivo"}

_ROJO, _AMBAR, _VERDE = "#E4002B", "#F59E0B", "#22A06B"


# ---------------------------------------------------------------- sin interfaz

def _clave_plan(plan: dict) -> str:
    """Identificador estable de un plan, para que las casillas marcadas y las
    asignaciones no se pierdan al cambiar el filtro o al volver a la pestaña."""
    base = f"{plan['titulo']}|{plan['situacion'][:80]}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()[:10]


def _casos(plan: dict) -> str:
    nombres = [str(e.get("nombre")) for e in (plan.get("evidencia") or [])
               if e.get("nombre") and str(e["nombre"]) not in _NO_SON_CASOS]
    return ", ".join(nombres[:3]) if nombres else "—"


def estado_plan(hechos: int, total: int) -> str:
    """El estado sale de los pasos marcados, no se escribe a mano."""
    if total and hechos >= total:
        return "Hecho"
    if hechos > 0:
        return "En curso"
    return "Pendiente"


def alerta_plan(asignacion: dict | None, hechos: int, total: int, hoy: date) -> str:
    """Lo que impide que el plan avance, en orden de gravedad.

    Un plan terminado no tiene alerta aunque le falte responsable: ya no
    necesita uno.
    """
    asignacion = asignacion or {}
    if total and hechos >= total:
        return ""
    fecha = asignacion.get("fecha")
    if fecha and fecha < hoy:
        return "Vencido"
    if not (asignacion.get("responsable") or "").strip():
        return "Sin responsable"
    if not fecha:
        return "Sin fecha"
    return ""


def filas_plan_de_accion(planes: list, asignaciones: dict, pasos_hechos: dict, hoy: date) -> list[dict]:
    """Una fila por plan con todo lo necesario para el tablero, la tabla, el Excel y el resumen."""
    filas = []
    for i, plan in enumerate(planes, 1):
        clave = _clave_plan(plan)
        total = len(plan["pasos"])
        marcados = list(pasos_hechos.get(clave) or [])[:total]
        hechos = sum(1 for marcado in marcados if marcado)
        asignacion = asignaciones.get(clave) or {}
        tono = _TONO.get(plan["estado"], _TONO["mejora"])
        filas.append({
            "#": i, "clave": clave,
            "Urgencia": f"{tono['icono']} {tono['etiqueta']}",
            "Frente": plan["titulo"],
            "A quién afecta": _casos(plan),
            "Responsable": (asignacion.get("responsable") or "").strip(),
            "Fecha compromiso": asignacion.get("fecha"),
            "Estado": estado_plan(hechos, total),
            "Avance": (hechos / total) if total else 0.0,
            "Alerta": alerta_plan(asignacion, hechos, total, hoy),
            "Cómo se mide": plan["medir"],
            "Situación": plan["situacion"],
            "Por qué importa": plan["por_que"],
            "hechos": hechos, "total": total,
        })
    return filas


def excel_plan_de_accion(planes: list, asignaciones: dict, pasos_hechos: dict, hoy: date) -> bytes:
    """El plan completo en Excel: una hoja de frentes y otra de pasos.

    Existe porque las casillas y las asignaciones de la app se pierden al
    cerrar la sesión. Lo que se decide en la reunión tiene que poder salir de
    aquí y seguirse en otro lado.
    """
    from openpyxl.styles import Font

    filas = filas_plan_de_accion(planes, asignaciones, pasos_hechos, hoy)
    frentes = pd.DataFrame([{
        "#": f["#"],
        "Urgencia": f["Urgencia"].split(" ", 1)[-1],
        "Frente": f["Frente"],
        "A quién afecta": f["A quién afecta"],
        "Responsable": f["Responsable"],
        "Fecha compromiso": f["Fecha compromiso"],
        "Estado": f["Estado"],
        "Avance": f"{f['hechos']} de {f['total']} pasos",
        "Alerta": f["Alerta"],
        "Situación": f["Situación"],
        "Por qué importa": f["Por qué importa"],
        "Cómo se mide": f["Cómo se mide"],
    } for f in filas])
    pasos = []
    for fila, plan in zip(filas, planes):
        marcados = list(pasos_hechos.get(fila["clave"]) or [])
        for j, paso in enumerate(plan["pasos"]):
            pasos.append({
                "#": fila["#"], "Frente": fila["Frente"], "Paso": j + 1, "Qué hacer": paso,
                "Hecho": "Sí" if (j < len(marcados) and marcados[j]) else "No",
                "Responsable": fila["Responsable"], "Fecha compromiso": fila["Fecha compromiso"],
            })
    salida = io.BytesIO()
    with pd.ExcelWriter(salida, engine="openpyxl") as escritor:
        for nombre, tabla in (("Plan de acción", frentes), ("Pasos", pd.DataFrame(pasos))):
            tabla.to_excel(escritor, sheet_name=nombre, index=False)
            hoja = escritor.sheets[nombre]
            for celda in hoja[1]:
                celda.font = Font(bold=True)
            for columna in hoja.columns:
                largo = max((len(str(c.value)) for c in columna if c.value is not None), default=8)
                hoja.column_dimensions[columna[0].column_letter].width = min(max(10, largo + 2), 60)
    return salida.getvalue()


def resumen_para_compartir(planes: list, asignaciones: dict, pasos_hechos: dict, hoy: date) -> str:
    """El plan en texto plano, para pegarlo en un correo o un chat."""
    filas = filas_plan_de_accion(planes, asignaciones, pasos_hechos, hoy)
    lineas = [f"PLAN DE MEJORA · {hoy:%d/%m/%Y}", ""]
    for f in filas:
        partes = [f"{f['Urgencia']} {f['#']}. {f['Frente']}",
                  f"Responsable: {f['Responsable'] or 'sin asignar'}"]
        if f["Fecha compromiso"]:
            partes.append(f"Fecha: {f['Fecha compromiso']:%d/%m/%Y}")
        partes.append(f"{f['Estado']}, {f['hechos']} de {f['total']} pasos")
        if f["Alerta"]:
            partes.append(f"⚠️ {f['Alerta']}")
        lineas.append(" · ".join(partes))
        lineas.append(f"   Cómo se mide: {f['Cómo se mide']}")
        lineas.append("")
    return "\n".join(lineas).rstrip() + "\n"


def _iniciales(nombre: str) -> str:
    partes = [p for p in str(nombre).split() if p]
    return "".join(p[0] for p in partes[:2]).upper() or "?"


# ---------------------------------------------------------------- interfaz

def _css() -> None:
    st.markdown(
        """
        <style>
        .planes-hero{display:flex;gap:26px;align-items:center;justify-content:space-between;flex-wrap:wrap;
          background:linear-gradient(115deg,var(--panel) 52%,var(--blue-soft) 150%);border:1px solid var(--line);
          border-radius:var(--radius-lg);padding:22px 26px;box-shadow:var(--shadow-md);margin:4px 0 18px}
        .planes-hero-texto{flex:1;min-width:280px}
        .planes-hero-eyebrow{font-size:10.5px;font-weight:800;letter-spacing:.11em;color:var(--blue);
          text-transform:uppercase}
        .planes-hero-titulo{font-size:25px;font-weight:850;font-family:'Sora','Inter',sans-serif;
          color:var(--text);margin:4px 0 6px;letter-spacing:-.02em}
        .planes-hero-resumen{font-size:13px;color:var(--muted);line-height:1.5;max-width:720px}
        .planes-hero-barra{display:flex;gap:4px;height:12px;max-width:580px;margin:16px 0 9px}
        .planes-hero-barra span{display:block;border-radius:999px}
        .planes-hero-leyenda{display:flex;gap:18px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);margin-bottom:12px}
        .planes-hero-leyenda i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;
          vertical-align:middle}
        .planes-hero-leyenda b{color:var(--text);margin-right:3px;font-size:14px}
        .planes-anillo{width:138px;height:138px;flex:0 0 138px;border-radius:50%;display:grid;place-items:center;
          background:conic-gradient(var(--c) calc(var(--p) * 1%),var(--panel-2) 0)}
        .planes-anillo span{width:108px;height:108px;border-radius:50%;background:var(--panel);display:flex;
          flex-direction:column;align-items:center;justify-content:center;box-shadow:inset 0 0 0 1px var(--line)}
        .planes-anillo b{font-size:28px;font-family:'Sora','Inter',sans-serif;color:var(--text);line-height:1}
        .planes-anillo small{font-size:10.5px;color:var(--muted);margin-top:5px;text-align:center;line-height:1.25}

        .plan-chips{display:flex;gap:8px;flex-wrap:wrap}
        .plan-chip{font-size:12.5px;color:var(--muted);background:var(--panel);border:1px solid var(--line);
          border-radius:999px;padding:5px 12px}
        .plan-chip b{font-size:15px;color:var(--c);margin-right:4px;font-family:'Sora','Inter',sans-serif}

        .tablero{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:4px 0 22px}
        @media(max-width:980px){.tablero{grid-template-columns:1fr}}
        .tablero-col{background:var(--panel-2);border:1px solid var(--line);border-radius:var(--radius-lg);padding:12px}
        .tablero-col-head{display:flex;justify-content:space-between;align-items:center;font-size:13.5px;
          font-weight:800;color:var(--text);padding:2px 4px}
        .tablero-col-head b{background:var(--c);color:#fff;border-radius:999px;min-width:26px;height:24px;
          display:inline-flex;align-items:center;justify-content:center;font-size:12px;padding:0 8px}
        .tablero-col-sub{font-size:11.5px;color:var(--muted);margin:2px 4px 12px;padding-bottom:10px;
          border-bottom:3px solid var(--c)}
        .tablero-vacio{font-size:12px;color:var(--muted);text-align:center;padding:20px 8px;
          border:1px dashed var(--line);border-radius:var(--radius-md)}
        .tarjeta{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--c);
          border-radius:var(--radius-md);padding:12px 14px;margin-bottom:10px;box-shadow:var(--shadow-sm);
          transition:transform .15s ease,box-shadow .15s ease}
        .tarjeta:hover{transform:translateY(-2px);box-shadow:var(--shadow-md)}
        .tarjeta-top{display:flex;justify-content:space-between;align-items:center;gap:8px;min-height:20px}
        .tarjeta-num{font-size:11px;font-weight:800;color:var(--muted)}
        .tarjeta-alerta{font-size:10.5px;font-weight:700;color:var(--a);border-radius:999px;padding:2px 9px;
          background:color-mix(in srgb,var(--a) 12%,transparent)}
        .tarjeta-titulo{font-size:14.5px;font-weight:750;color:var(--text);line-height:1.35;margin:4px 0 8px;
          font-family:'Sora','Inter',sans-serif}
        .tarjeta-casos{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:11px}
        .tarjeta-caso{font-size:10.5px;background:var(--panel-2);border:1px solid var(--line);border-radius:6px;
          padding:2px 7px;color:var(--text);max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
        .tarjeta-caso.mas{color:var(--muted)}
        .tarjeta-avance{height:7px;background:var(--panel-2);border-radius:999px;overflow:hidden}
        .tarjeta-avance span{display:block;height:100%;background:#22A06B;border-radius:999px}
        .tarjeta-pie{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:12px;
          color:var(--muted);margin-top:9px}
        .tarjeta-persona{display:inline-flex;align-items:center;gap:7px;color:var(--text);font-weight:600}
        .tarjeta-persona i{font-style:normal;width:24px;height:24px;border-radius:50%;background:var(--c);color:#fff;
          font-size:10px;font-weight:800;display:inline-flex;align-items:center;justify-content:center}
        .tarjeta-persona.falta{color:var(--muted);font-weight:500}
        .tarjeta-persona.falta i{background:var(--panel-2);color:var(--muted);border:1px dashed #94A3B8}
        .tarjeta-medir{font-size:11.5px;color:var(--muted);line-height:1.4;margin-top:10px;padding-top:9px;
          border-top:1px dashed var(--line);overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;
          -webkit-box-orient:vertical}

        .plan-datos{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 10px}
        .plan-dato{font-size:12px;border:1px solid var(--line);border-radius:999px;padding:3px 10px;
          background:var(--panel-2);color:var(--text)}
        .plan-dato.falta{color:var(--muted);border-style:dashed}
        .plan-situacion{font-size:14px;color:var(--text);line-height:1.5;margin:2px 0 4px}
        .plan-caja{background:var(--panel-2);border:1px solid var(--line);border-radius:var(--radius-sm);
          padding:11px 13px;height:100%}
        .plan-caja-titulo{font-size:10px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;
          color:var(--c);margin-bottom:5px}
        .plan-caja-texto{font-size:13px;color:var(--text);line-height:1.45}
        .plan-pasos-titulo{font-size:10px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;
          color:var(--muted);margin:12px 0 2px}

        .dx{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-lg);
          padding:20px 22px;box-shadow:var(--shadow-md);margin:4px 0 16px}
        .dx-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;flex-wrap:wrap}
        .dx-eyebrow{font-size:10.5px;font-weight:800;letter-spacing:.11em;color:var(--blue);text-transform:uppercase}
        .dx-titular{font-size:21px;font-weight:850;font-family:'Sora','Inter',sans-serif;color:var(--text);
          margin:4px 0 2px;letter-spacing:-.015em;line-height:1.3}
        .dx-sub{font-size:13px;color:var(--muted)}
        .dx-delta{font-size:24px;font-weight:850;font-family:'Sora','Inter',sans-serif;padding:8px 14px;
          border-radius:12px;white-space:nowrap}
        .dx-delta.neg{color:#E4002B;background:color-mix(in srgb,#E4002B 10%,transparent)}
        .dx-delta.pos{color:#22A06B;background:color-mix(in srgb,#22A06B 10%,transparent)}
        .dx-grid{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);gap:14px;margin-top:16px}
        @media(max-width:980px){.dx-grid{grid-template-columns:1fr}}
        .dx-card{background:var(--panel-2);border:1px solid var(--line);border-radius:var(--radius-md);padding:14px 16px}
        .dx-lbl{font-size:10px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin-bottom:10px}
        .dx-row{margin-bottom:12px}
        .dx-row-top{display:flex;justify-content:space-between;gap:10px;align-items:baseline;font-size:13.5px}
        .dx-row-top b{color:var(--text)}
        .dx-row-top span{font-weight:800;font-variant-numeric:tabular-nums}
        .dx-bar{height:7px;background:var(--line-soft);border-radius:999px;margin:5px 0 4px;overflow:hidden}
        .dx-bar i{display:block;height:100%;border-radius:999px}
        .dx-row-sub{font-size:12px;color:var(--muted)}
        .dx-row-sub b{color:var(--text);font-weight:650}
        .dx-nota{font-size:12px;color:var(--muted);margin-top:4px;padding-top:8px;border-top:1px dashed var(--line)}
        .dx-lever{display:grid;grid-template-columns:90px 1fr auto;gap:8px 10px;align-items:center;font-size:12.5px}
        .dx-lever .dx-bar{margin:0}
        .dx-lever span{font-weight:800;font-variant-numeric:tabular-nums;text-align:right}
        .dx-lever-txt{font-size:13px;color:var(--text);line-height:1.5;margin-top:10px}
        .dx-lever-acc{font-size:12.5px;color:var(--text);margin-top:8px;padding:8px 10px;border-radius:8px;
          background:var(--panel);border-left:3px solid var(--blue)}
        .atq{display:grid;gap:10px;margin:2px 0 18px}
        .atq-item{display:grid;grid-template-columns:42px minmax(0,1fr) 150px;gap:14px;align-items:center;
          background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-md);padding:12px 16px;
          box-shadow:var(--shadow-sm)}
        @media(max-width:760px){.atq-item{grid-template-columns:34px 1fr}.atq-monto{grid-column:2}}
        .atq-num{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;font-weight:850;
          font-family:'Sora','Inter',sans-serif;color:#fff;background:var(--blue)}
        .atq-titulo{font-size:15px;font-weight:800;color:var(--text);font-family:'Sora','Inter',sans-serif}
        .atq-texto{font-size:12.5px;color:var(--muted);line-height:1.45;margin-top:2px}
        .atq-quien{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
        .atq-quien span{font-size:11px;background:var(--panel-2);border:1px solid var(--line);border-radius:6px;padding:2px 7px}
        .atq-quien b{margin-left:4px;color:var(--text)}
        .atq-acc{font-size:12.5px;color:var(--text);margin-top:6px}
        .atq-monto{text-align:right}
        .atq-monto b{display:block;font-size:22px;font-weight:850;font-family:'Sora','Inter',sans-serif;color:#22A06B}
        .atq-monto small{font-size:11px;color:var(--muted)}
        .tarjeta-valor{font-size:12px;font-weight:800;color:#22A06B;margin:-4px 0 8px}

        [class*="st-key-plancard_"]{background:var(--panel);border:1px solid var(--line);border-left:5px solid #94A3B8;
          border-radius:var(--radius-lg);padding:16px 18px;box-shadow:var(--shadow-md);margin-bottom:14px;gap:.4rem}
        [class*="st-key-plancard_critico"]{border-left-color:#E4002B}
        [class*="st-key-plancard_atencion"]{border-left-color:#F59E0B}
        [class*="st-key-plancard_mejora"]{border-left-color:#22A06B}
        .pc-head{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
        .pc-num{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;flex:0 0 34px;
          background:var(--c);color:#fff;font-weight:850;font-family:'Sora','Inter',sans-serif}
        .pc-tit{flex:1;min-width:220px}
        .pc-tit b{display:block;font-size:17px;font-family:'Sora','Inter',sans-serif;color:var(--text);line-height:1.3}
        .pc-pill{display:inline-block;font-size:10px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;
          color:var(--c);background:color-mix(in srgb,var(--c) 12%,transparent);border-radius:999px;padding:2px 9px;margin-bottom:3px}
        .pc-valor{font-size:15px;font-weight:850;color:#22A06B;background:color-mix(in srgb,#22A06B 10%,transparent);
          border-radius:10px;padding:6px 12px;white-space:nowrap}
        .pc-situacion{font-size:13.5px;color:var(--text);line-height:1.5;margin:8px 0 6px}
        .pc-dx{font-size:12.5px;color:var(--text);background:var(--panel-2);border:1px dashed var(--line);
          border-radius:8px;padding:7px 10px;margin-bottom:8px}
        .metas{overflow-x:auto;margin:6px 0 4px;border:1px solid var(--line);border-radius:var(--radius-md)}
        .metas table{width:100%;border-collapse:collapse;font-size:12.5px}
        .metas th{font-size:10px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);
          text-align:left;padding:8px 10px;background:var(--panel-2);border-bottom:1px solid var(--line);white-space:nowrap}
        .metas td{padding:9px 10px;border-bottom:1px solid var(--line-soft);vertical-align:top;color:var(--text)}
        .metas tr:last-child td{border-bottom:none}
        .metas .n{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
        .metas .pos{color:#22A06B;font-weight:800}
        .metas small{display:block;font-size:10.5px;color:var(--muted);margin-top:2px;white-space:normal;max-width:220px}
        .metas td.n small{margin-left:auto;text-align:right}
        .metas .lec{font-size:12px;color:var(--text);min-width:170px;max-width:260px;cursor:help}
        .fact{display:inline-block;font-size:10.5px;font-weight:800;color:var(--f);border:1px solid var(--f);
          border-radius:999px;padding:1px 8px;background:color-mix(in srgb,var(--f) 10%,transparent)}
        .st-key-planes_filtro [data-testid="stWidgetLabel"]{display:none!important}
        .st-key-planes_filtro [role="radiogroup"]{gap:6px;flex-wrap:wrap}
        .st-key-planes_filtro [role="radiogroup"] label{border:1px solid var(--line);border-radius:999px;
          padding:5px 14px;background:var(--panel);margin:0!important;cursor:pointer}
        .st-key-planes_filtro [role="radiogroup"] label>div:first-child{display:none}
        .st-key-planes_filtro [role="radiogroup"] label:has(input:checked){
          background:linear-gradient(180deg,#ff3b4e,#e4002b);border-color:#e4002b}
        .st-key-planes_filtro [role="radiogroup"] label:has(input:checked) p{color:#fff!important;font-weight:800}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _pasos_guardados() -> dict:
    """Copia de las casillas marcadas fuera de los widgets.

    La navegación solo dibuja la vista activa, y Streamlit borra el estado de
    un widget que no se dibujó: sin esta copia, los pasos marcados se perdían
    al pasar a otra vista y volver."""
    return st.session_state.setdefault("planes_pasos_marcados", {})


def _pasos_hechos(plan: dict) -> list[bool]:
    clave = _clave_plan(plan)
    guardados = _pasos_guardados()
    return [bool(st.session_state.get(f"paso_{clave}_{j}", guardados.get(f"paso_{clave}_{j}", False)))
            for j in range(len(plan["pasos"]))]


def _chips_seguimiento(filas: list) -> str:
    """Contadores de seguimiento: rojo si hay algo mal, verde si hay algo
    terminado y negro en cero, porque un cero en rojo sería una alarma falsa."""
    conteos = [
        (sum(1 for f in filas if f["Alerta"] == "Vencido"), "vencido(s)", _ROJO),
        (sum(1 for f in filas if f["Alerta"] == "Sin responsable"), "sin responsable", _ROJO),
        (sum(1 for f in filas if f["Estado"] == "Hecho"), "terminado(s)", _VERDE),
    ]
    html = []
    for n, texto, color in conteos:
        color_numero = color if n else "var(--text)"
        html.append(f'<span class="plan-chip" style="--c:{color_numero}"><b>{n}</b>{texto}</span>')
    return f'<div class="plan-chips">{"".join(html)}</div>'


def _hero(resultado: dict, planes: list, filas: list) -> None:
    """El resumen del periodo: frentes por urgencia y el avance real del plan."""
    total_pasos = sum(f["total"] for f in filas)
    hechos = sum(f["hechos"] for f in filas)
    avance = round(hechos / total_pasos * 100) if total_pasos else 0
    color_anillo = _VERDE if avance >= 100 else (_AMBAR if avance > 0 else "#94A3B8")
    conteos = {
        "critico": resultado["criticos"],
        "atencion": resultado["atencion"],
        "mejora": sum(1 for p in planes if p["estado"] == "mejora"),
    }
    segmentos = "".join(
        f'<span style="flex:{n};background:{_TONO[estado]["color"]}"></span>'
        for estado, n in conteos.items() if n)
    leyenda = "".join(
        f'<span><i style="background:{_TONO[estado]["color"]}"></i><b>{n}</b>{_TONO[estado]["etiqueta"].lower()}</span>'
        for estado, n in conteos.items())
    titulo = f"{len(planes)} {'frente' if len(planes) == 1 else 'frentes'} para trabajar"
    resumen = clean_display_text(resultado["resumen"])
    chips = _chips_seguimiento(filas)
    st.markdown(
        f"""<div class="planes-hero">
          <div class="planes-hero-texto">
            <div class="planes-hero-eyebrow">Plan del periodo</div>
            <div class="planes-hero-titulo">{titulo}</div>
            <div class="planes-hero-resumen">{resumen}</div>
            <div class="planes-hero-barra">{segmentos}</div>
            <div class="planes-hero-leyenda">{leyenda}</div>
            {chips}
          </div>
          <div class="planes-anillo" style="--p:{avance};--c:{color_anillo}">
            <span><b>{avance}%</b><small>{hechos} de {total_pasos} pasos</small></span>
          </div>
        </div>""",
        unsafe_allow_html=True,
    )


def _tablero(planes: list, filas: list) -> None:
    """Una columna por urgencia y una tarjeta por plan."""
    columnas = []
    for estado in ("critico", "atencion", "mejora"):
        tono = _TONO[estado]
        tarjetas = []
        for plan, fila in zip(planes, filas):
            if plan["estado"] != estado:
                continue
            casos = [c for c in fila["A quién afecta"].split(", ") if c and c != "—"]
            chips_casos = "".join(f'<span class="tarjeta-caso">{clean_display_text(c)}</span>' for c in casos[:2])
            if len(casos) > 2:
                chips_casos += f'<span class="tarjeta-caso mas">+{len(casos) - 2}</span>'
            if fila["Responsable"]:
                nombre = clean_display_text(fila["Responsable"])
                persona = (f'<span class="tarjeta-persona"><i>{_iniciales(fila["Responsable"])}</i>'
                           f'{nombre}</span>')
            else:
                persona = '<span class="tarjeta-persona falta"><i>?</i>Sin responsable</span>'
            fecha = ""
            if fila["Fecha compromiso"]:
                color_fecha = _ROJO if fila["Alerta"] == "Vencido" else "var(--text)"
                fecha = f'<span style="color:{color_fecha}">📅 {fila["Fecha compromiso"]:%d/%m}</span>'
            alerta = ""
            if fila["Alerta"]:
                color_alerta = _ROJO if fila["Alerta"] in ("Vencido", "Sin responsable") else "var(--text)"
                alerta = f'<span class="tarjeta-alerta" style="--a:{color_alerta}">⚠️ {fila["Alerta"]}</span>'
            color_estado = _VERDE if fila["Estado"] == "Hecho" else "var(--text)"
            ancho = fila["Avance"] * 100
            tarjetas.append(
                f'<div class="tarjeta" style="--c:{tono["color"]}">'
                f'<div class="tarjeta-top"><span class="tarjeta-num">#{fila["#"]}</span>{alerta}</div>'
                f'<div class="tarjeta-titulo">{clean_display_text(plan["titulo"])}</div>'
                + (f'<div class="tarjeta-valor">💰 {plan["impacto_txt"]}</div>' if plan.get("impacto_txt") else "")
                + f'<div class="tarjeta-casos">{chips_casos}</div>'
                f'<div class="tarjeta-avance"><span style="width:{ancho:.0f}%"></span></div>'
                f'<div class="tarjeta-pie"><span style="color:{color_estado};font-weight:600">'
                f'{fila["Estado"]} · {fila["hechos"]}/{fila["total"]} pasos</span>{fecha}</div>'
                f'<div class="tarjeta-pie">{persona}</div>'
                f'<div class="tarjeta-medir">🎯 {clean_display_text(plan["medir"])}</div>'
                f'</div>'
            )
        cuerpo = "".join(tarjetas) if tarjetas else '<div class="tablero-vacio">Nada en esta categoría</div>'
        columnas.append(
            f'<div class="tablero-col" style="--c:{tono["color"]}">'
            f'<div class="tablero-col-head"><span>{tono["icono"]} {tono["etiqueta"]}</span><b>{len(tarjetas)}</b></div>'
            f'<div class="tablero-col-sub">{tono["urgencia"]}</div>{cuerpo}</div>'
        )
    st.markdown(f'<div class="tablero">{"".join(columnas)}</div>', unsafe_allow_html=True)


def _hoja_de_ruta(filas: list, asignaciones: dict) -> bool:
    """La tabla para asignar responsable y fecha, y nada más.

    Todo lo que no se edita ya está en el tablero, así que la tabla se quedó
    con lo justo: cabe sin cortar textos y se lee como un formulario, no como
    una hoja de cálculo. Devuelve True si hubo cambios, para que la pantalla
    se redibuje con los estados y alertas ya actualizados.
    """
    claves = [f["clave"] for f in filas]
    # La clave del widget depende de qué planes hay: si los filtros del panel
    # cambian los planes, la tabla empieza de nuevo en vez de aplicar una
    # edición vieja a la fila equivocada.
    firma = hashlib.md5("|".join(claves).encode("utf-8")).hexdigest()[:10]
    tabla = pd.DataFrame([{
        "#": f["#"],
        "Frente": f"{f['Urgencia'].split(' ', 1)[0]} {f['Frente']}",
        "Responsable": f["Responsable"],
        "Fecha compromiso": f["Fecha compromiso"],
        "Estado": f["Estado"],
        "Alerta": f["Alerta"],
    } for f in filas])
    tabla["Fecha compromiso"] = pd.to_datetime(tabla["Fecha compromiso"])
    editada = st.data_editor(
        tabla, key=f"planes_hoja_{firma}", hide_index=True, use_container_width=True, num_rows="fixed",
        disabled=["#", "Frente", "Estado", "Alerta"],
        column_config={
            "#": st.column_config.NumberColumn(width="small"),
            "Frente": st.column_config.TextColumn(width="large"),
            "Responsable": st.column_config.TextColumn("✏️ Responsable", width="medium",
                                                       help="Escribe quién se hace cargo de este frente."),
            "Fecha compromiso": st.column_config.DateColumn("✏️ Fecha compromiso", format="DD/MM/YYYY",
                                                            width="medium"),
            "Estado": st.column_config.TextColumn(width="small",
                                                  help="Sale de los pasos marcados en cada plan."),
            "Alerta": st.column_config.TextColumn(width="small"),
        },
    )
    cambios = False
    for posicion, fila in enumerate(editada.to_dict("records")):
        clave = claves[posicion]
        responsable = fila.get("Responsable")
        if responsable is None or (isinstance(responsable, float) and pd.isna(responsable)):
            responsable = ""
        responsable = str(responsable).strip()
        fecha = fila.get("Fecha compromiso")
        fecha = None if fecha is None or pd.isna(fecha) else pd.Timestamp(fecha).date()
        anterior = asignaciones.get(clave) or {}
        if (anterior.get("responsable") or "") != responsable or anterior.get("fecha") != fecha:
            asignaciones[clave] = {"responsable": responsable, "fecha": fecha}
            cambios = True
    return cambios


def _exportar(planes: list, asignaciones: dict, pasos: dict, hoy: date) -> None:
    izquierda, derecha = st.columns(2)
    with izquierda:
        st.download_button(
            "⬇ Descargar plan de acción (Excel)",
            data=excel_plan_de_accion(planes, asignaciones, pasos, hoy),
            file_name=f"plan_de_mejora_{hoy:%Y%m%d}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True, type="primary", key="planes_excel")
    texto = resumen_para_compartir(planes, asignaciones, pasos, hoy)
    with derecha:
        st.download_button(
            "⬇ Descargar resumen (texto)", data=texto.encode("utf-8"),
            file_name=f"plan_de_mejora_{hoy:%Y%m%d}.txt", mime="text/plain",
            use_container_width=True, key="planes_texto")
    with st.expander("📋 Resumen listo para pegar en un correo o un chat", expanded=False):
        st.code(texto, language=None)


_FACTIBILIDAD = {"alta": ("Alcanzable", "#22A06B"), "media": ("Exigente", "#F59E0B"), "baja": ("Difícil", "#E4002B")}


def _tabla_metas(plan: dict, g: dict | None) -> str:
    """Las metas del plan, caso por caso, con lo que dice su historia."""
    casos = plan.get("casos") or []
    if not casos:
        return ""
    esc = lambda t: html.escape(str(clean_display_text(t)))  # noqa: E731
    hoy = esc((g or {}).get("mes_b", "Último mes")).split(" de ")[0].capitalize()
    sig = esc((g or {}).get("mes_siguiente", "Próximo mes")).split(" de ")[0].capitalize()
    filas = []
    for c in casos:
        etiqueta, color = _FACTIBILIDAD.get(c.get("factibilidad"), ("—", "#94A3B8"))
        ops = f'{c["operaciones"]:,} {esc(c["unidad"])}' if c.get("operaciones") else "—"
        filas.append(
            f'<tr><td><b>{esc(c["nombre"])}</b></td><td class="n">{_monto(c["actual"])}</td>'
            f'<td class="n"><b>{_monto(c["objetivo"])}</b><small>{esc(c["referencia"])}</small></td>'
            f'<td class="n pos">+{_monto(c["brecha"])}</td><td class="n">{_monto(c["semanal"])}</td><td class="n">{ops}</td>'
            f'<td class="lec" title="{esc(c.get("lectura") or "")}">{esc(c.get("lectura_corta") or "—")}</td>'
            f'<td title="{esc(c["factibilidad_txt"])}"><span class="fact" style="--f:{color}">{etiqueta}</span>'
            f'<small>{esc(c.get("factibilidad_corta") or "")}</small></td></tr>')
    return (f'<div class="metas"><table><thead><tr><th>Caso</th><th class="n">Hoy · {hoy}</th>'
            f'<th class="n">Objetivo · {sig}</th><th class="n">Brecha</th><th class="n">Por semana</th>'
            f'<th class="n">Operaciones</th><th>Qué dicen sus datos <span title="Pasa el mouse sobre cada fila para ver la explicación">ⓘ</span></th><th>¿Alcanzable?</th></tr></thead>'
            f'<tbody>{"".join(filas)}</tbody></table></div>')


def _plan(i: int, plan: dict, fila: dict, g: dict | None = None) -> None:
    """Un plan como tarjeta: encabezado, diagnóstico, metas por caso, pasos
    para marcar y cómo se controla. Antes era un desplegable con el texto del
    hallazgo y pasos de plantilla; ahora cada cifra sale de la historia del
    caso (ver core/metas.py)."""
    tono = _TONO.get(plan["estado"], _TONO["mejora"])
    clave = fila["clave"]
    esc = lambda t: html.escape(str(clean_display_text(t)))  # noqa: E731
    with st.container(key=f"plancard_{plan['estado']}_{clave}"):
        datos = [f'<span class="plan-dato">{fila["Estado"]} · {fila["hechos"]} de {fila["total"]} pasos</span>']
        if fila["Responsable"]:
            datos.append(f'<span class="plan-dato">👤 {esc(fila["Responsable"])}</span>')
        else:
            datos.append('<span class="plan-dato falta">👤 Sin responsable</span>')
        if fila["Fecha compromiso"]:
            color_fecha = _ROJO if fila["Alerta"] == "Vencido" else "var(--text)"
            vencido = " · vencido" if fila["Alerta"] == "Vencido" else ""
            datos.append(f'<span class="plan-dato" style="color:{color_fecha}">📅 {fila["Fecha compromiso"]:%d/%m/%Y}{vencido}</span>')
        else:
            datos.append('<span class="plan-dato falta">📅 Sin fecha</span>')
        valor = f'<span class="pc-valor">💰 {esc(plan["impacto_txt"])}</span>' if plan.get("impacto_txt") else ""
        diagnostico = (f'<div class="pc-dx">📐 {esc(plan["diagnostico"])}</div>' if plan.get("diagnostico") else "")
        st.markdown(
            f'<div class="pc-head"><span class="pc-num" style="--c:{tono["color"]}">{i}</span>'
            f'<div class="pc-tit"><span class="pc-pill" style="--c:{tono["color"]}">{tono["icono"]} {tono["etiqueta"]}</span>'
            f'<b>{esc(plan["titulo"])}</b></div>{valor}</div>'
            f'<div class="plan-datos">{"".join(datos)}</div>'
            f'<div class="pc-situacion">{esc(plan["situacion"])}</div>{diagnostico}{_tabla_metas(plan, g)}',
            unsafe_allow_html=True)

        izquierda, derecha = st.columns([1.55, 1], gap="medium")
        with izquierda:
            st.markdown('<div class="plan-pasos-titulo">Plan de acción · marca cada paso cuando esté hecho</div>',
                        unsafe_allow_html=True)
            guardados = _pasos_guardados()
            for j, paso in enumerate(plan["pasos"]):
                k = f"paso_{clave}_{j}"
                st.checkbox(f"{j + 1}. {paso}", key=k, value=bool(guardados.get(k, False)))
                guardados[k] = bool(st.session_state.get(k, False))
            hechos = sum(_pasos_hechos(plan))
            total = len(plan["pasos"])
            if total:
                st.progress(hechos / total, text=f"{hechos} de {total} pasos completados")
        with derecha:
            cajas = [("🎯 Cómo se sabe que funcionó", plan.get("medir"), tono["color"])]
            if plan.get("control"):
                cajas.append(("📅 Control semanal", plan["control"], "#2563EB"))
            if plan.get("alarma"):
                cajas.append(("🚨 Cuándo escalar", plan["alarma"], _ROJO))
            if not plan.get("casos") and plan.get("evidencia"):
                st.markdown(evidence_list(plan["evidencia"]), unsafe_allow_html=True)
            cajas.append(("Por qué importa", plan.get("por_que"), "var(--muted)"))
            st.markdown("".join(
                f'<div class="plan-caja" style="--c:{color};margin-bottom:8px"><div class="plan-caja-titulo">{titulo}</div>'
                f'<div class="plan-caja-texto">{esc(texto)}</div></div>' for titulo, texto, color in cajas if texto),
                unsafe_allow_html=True)


def _monto(v: float) -> str:
    from core.diagnostics import _fmt
    return _fmt(v)


def _signo(v: float) -> str:
    return ("+" if v > 0 else "−") + _monto(abs(v))


def _diagnostico(g: dict) -> None:
    """Por qué se movió el número: causa raíz en dos niveles y palanca.

    Es la pregunta que un gerente hace antes de aprobar cualquier plan: si
    no se sabe dónde nació el cambio ni si fue volumen o precio, el plan
    ataca a ciegas."""
    esc = lambda t: html.escape(str(clean_display_text(t)))  # noqa: E731
    tono = "neg" if g.get("empeoro") else "pos"
    delta = ""
    if g.get("pct") is not None and g.get("se_movio"):
        delta = f'<div class="dx-delta {tono}">{"▲" if g["delta"] > 0 else "▼"} {abs(g["pct"]):.1f}%</div>'

    causa_html = ""
    c = g.get("causas")
    if c and c.get("nodos"):
        mayor = max(abs(n["delta"]) for n in c["nodos"]) or 1
        color = "#E4002B" if g["delta"] < 0 else "#22A06B"
        filas = []
        for n in c["nodos"]:
            peso = (f' · {n["peso"]:.0f}% del cambio' if n.get("peso") is not None and 0 < abs(n["peso"]) <= 300 else "")
            sub = ""
            if n.get("detalle") and n["detalle"]["segmentos"]:
                partes = [f'<b>{esc(x["nombre"])}</b> {_signo(x["delta"])}' for x in n["detalle"]["segmentos"]]
                sub = f'<div class="dx-row-sub">↳ Por {esc(n["detalle"]["etiqueta"].lower())}: {" · ".join(partes)}</div>'
            filas.append(
                f'<div class="dx-row"><div class="dx-row-top"><b>{esc(n["nombre"])}</b>'
                f'<span style="color:{color}">{_signo(n["delta"])}</span></div>'
                f'<div class="dx-bar"><i style="width:{abs(n["delta"]) / mayor * 100:.0f}%;background:{color}"></i></div>'
                f'<div class="dx-row-sub">De {_monto(n["antes"])} a {_monto(n["ahora"])}{peso}</div>{sub}</div>')
        nota = ""
        if c.get("compensaron"):
            k = c["compensaron"][0]
            nota = (f'<div class="dx-nota">En sentido contrario: <b>{esc(k["nombre"])}</b> {_signo(k["delta"])} '
                    f'{"amortiguó la caída" if g["delta"] < 0 else "frenó la subida"}.</div>')
        causa_html = (f'<div class="dx-card"><div class="dx-lbl">Dónde nació el cambio · por {esc(c["etiqueta"].lower())}</div>'
                      f'{"".join(filas)}{nota}</div>')

    palanca_html = ""
    p = g.get("palanca")
    if p:
        mayor = max(abs(p["efecto_volumen"]), abs(p["efecto_ticket"])) or 1
        def barra(etq, v, pct):
            col = "#22A06B" if v >= 0 else "#E4002B"
            return (f'<b>{etq}</b><div class="dx-bar"><i style="width:{abs(v) / mayor * 100:.0f}%;background:{col}"></i></div>'
                    f'<span style="color:{col}">{_signo(v)}</span>')
        texto = g.get("texto_palanca") or ""
        palanca_html = (
            '<div class="dx-card"><div class="dx-lbl">La palanca · volumen o ticket</div>'
            f'<div class="dx-lever">{barra("Volumen", p["efecto_volumen"], p["ops_pct"])}'
            f'{barra("Ticket", p["efecto_ticket"], p["ticket_pct"])}</div>'
            f'<div class="dx-lever-txt">{esc(texto)}</div>'
            + (f'<div class="dx-lever-acc">👉 {esc(g["accion_palanca"])}</div>' if g.get("accion_palanca") else "")
            + '</div>')

    grid = ""
    if causa_html or palanca_html:
        grid = f'<div class="dx-grid">{causa_html or "<div></div>"}{palanca_html or ""}</div>'
    sub = f'{esc(g["mes_b"])} frente a {esc(g["mes_a"])} · {esc(g["etiqueta"])}'
    if g.get("parcial"):
        sub += " · el último mes está incompleto y se dejó fuera"
    st.markdown(
        f'<div class="dx"><div class="dx-head"><div><div class="dx-eyebrow">Por qué se movió el número</div>'
        f'<div class="dx-titular">{esc(g["titular"])}</div><div class="dx-sub">{sub}</div></div>{delta}</div>'
        f'{grid}</div>', unsafe_allow_html=True)


def _que_atacar(g: dict) -> None:
    """Las oportunidades con cifra, de la que más vale a la que menos."""
    oportunidades = g.get("oportunidades") or []
    if not oportunidades:
        return
    esc = lambda t: html.escape(str(clean_display_text(t)))  # noqa: E731
    items = []
    for i, o in enumerate(oportunidades, 1):
        quienes = "".join(f'<span>{esc(q["nombre"])}<b>{_monto(q["monto"])}</b></span>' for q in o["quienes"])
        pct = f'{o["pct_total"]:.0f}% de {esc(g["mes_b"])}' if o.get("pct_total") else "al mes"
        items.append(
            f'<div class="atq-item"><div class="atq-num">{i}</div><div><div class="atq-titulo">{esc(o["titulo"])}</div>'
            f'<div class="atq-texto">{esc(o["texto"])}</div><div class="atq-quien">{quienes}</div>'
            f'<div class="atq-acc">👉 {esc(o["accion"])}</div></div>'
            f'<div class="atq-monto"><b>+{_monto(o["monto"])}</b><small>{pct}</small></div></div>')
    st.markdown(section_header(
        "Qué atacar primero",
        subtitle="Cada oportunidad con lo que vale al mes. Van en orden de valor: empieza por la de arriba.",
        compact=True), unsafe_allow_html=True)
    st.markdown(f'<div class="atq">{"".join(items)}</div>', unsafe_allow_html=True)
    st.caption("Recuperar lo perdido, cerrar la meta y subir a los rezagados se pueden solapar (un mismo caso puede "
               "estar en dos), así que no se suman entre sí. «Subir a los rezagados» cuenta solo la mitad del camino "
               "hasta la mediana: es lo que un plan de un mes puede mover.")


def render_planes(df: pd.DataFrame, schema: dict, dashboard: dict) -> None:
    _css()
    st.markdown(section_header(
        "Qué atacar para mejorar los números",
        eyebrow="DECISIONES",
        subtitle="Por qué se movió el resultado, qué vale más la pena atacar y el plan para hacerlo.",
    ), unsafe_allow_html=True)

    resultado = generar(df, schema, dashboard or {})
    planes = resultado["planes"]
    g = resultado.get("gerencia")
    if g:
        _diagnostico(g)
        _que_atacar(g)
        st.markdown(section_header(
            "Plan de acción",
            subtitle="Cada frente con su urgencia, lo que vale, quién lo lleva y cómo se sabe que funcionó.",
            compact=True), unsafe_allow_html=True)
    if not planes:
        st.success("No hay hallazgos que convertir en plan con los datos visibles. "
                   "Si esperabas ver algo aquí, revisa los filtros activos.")
        return

    hoy = date.today()
    asignaciones = st.session_state.setdefault("planes_asignacion", {})
    pasos = {_clave_plan(p): _pasos_hechos(p) for p in planes}
    filas = filas_plan_de_accion(planes, asignaciones, pasos, hoy)

    _hero(resultado, planes, filas)
    _tablero(planes, filas)

    st.markdown(section_header(
        "Asignar responsables y fechas",
        subtitle="Escribe quién se hace cargo de cada frente y para cuándo. El tablero se actualiza solo.",
        compact=True), unsafe_allow_html=True)
    if _hoja_de_ruta(filas, asignaciones):
        st.rerun()
    _exportar(planes, asignaciones, pasos, hoy)

    st.markdown(section_header(
        "Plan detallado",
        subtitle="Cada frente con sus metas por caso (calculadas con su historia), los pasos para marcar, "
                 "el control semanal y cuándo escalar.",
        compact=True), unsafe_allow_html=True)
    opciones = {
        "Todos": lambda p, f: True,
        "🔴 Críticos": lambda p, f: p["estado"] == "critico",
        "🟡 En observación": lambda p, f: p["estado"] == "atencion",
        "🟢 Oportunidades": lambda p, f: p["estado"] == "mejora",
        "⚠️ Con alerta": lambda p, f: bool(f["Alerta"]),
    }
    elegido = st.radio("Ver", list(opciones.keys()), horizontal=True, key="planes_filtro",
                       label_visibility="collapsed")
    criterio = opciones[elegido]
    visibles = [(i, p, f) for i, (p, f) in enumerate(zip(planes, filas), 1) if criterio(p, f)]
    if not visibles:
        st.info("No hay planes en esta categoría con los datos visibles.")
    for i, plan, fila in visibles:
        _plan(i, plan, fila, g)

    st.caption("Los planes salen del análisis de este archivo con los filtros activos. No incorporan lo que "
               "el archivo no contenga, como una campaña, un cierre o un cambio de precio, así que conviene "
               "contrastarlos con lo que sabes del negocio. Responsables, fechas y pasos marcados se guardan "
               "mientras dure la sesión: descarga el Excel para conservarlos.")
