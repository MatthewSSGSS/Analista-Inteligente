"""Pestaña "Planes de mejora".

Cada hallazgo del análisis convertido en un plan con pasos concretos y una
forma de medir si funcionó. Ver `core/planes.py` para el criterio; aquí solo
se presenta.

Esta vista se pensó para usarse en la reunión, no solo para leerse. Un plan
sin dueño ni fecha no se ejecuta, así que lo práctico es poder resolver eso
aquí mismo y llevárselo:

- **La hoja de ruta es editable**: se escribe el responsable y la fecha
  compromiso de cada frente directamente en la tabla. El estado y el avance
  no se escriben, salen de los pasos marcados en cada plan, para no tener
  dos fuentes de la misma verdad.
- **Alertas a la vista**: vencidos y frentes sin responsable, contados arriba
  y señalados en la tabla.
- **Para llevarse**: el plan completo en Excel, con una hoja de frentes y otra
  de pasos, y un resumen en texto listo para pegar en un correo o un chat.
- **Cada plan plegable**, con los pasos como casillas. El título del plegable
  no cambia al marcar un paso: en Streamlit, cambiar el título lo cierra, y
  antes cada clic en una casilla cerraba el plan que se estaba trabajando.

No se quitó nada de lo que tenía cada plan: situación, evidencia, por qué
importa, pasos y cómo se mide siguen todos.

Las funciones sin interfaz (estado, alertas, filas, Excel y resumen) están
separadas del dibujo para poder probarlas sin Streamlit.
"""
from __future__ import annotations

import hashlib
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
# grupo") y no deben aparecer en la columna "A quién afecta".
_NO_SON_CASOS = {"Valor más extremo", "Filas repetidas", "Su resultado", "Mediana del grupo",
                 "Total del archivo", "Registros propios", "Su aporte", "Su tasa", "Tasa del archivo"}

_ROJO, _VERDE = "#E4002B", "#22A06B"


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
    """Una fila por plan con todo lo necesario para la tabla, el Excel y el resumen."""
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


# ---------------------------------------------------------------- interfaz

def _css() -> None:
    st.markdown(
        """
        <style>
        .planes-tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:6px 0 12px}
        .planes-tile{background:var(--panel);border:1px solid var(--line);border-left:5px solid var(--c);
          border-radius:var(--radius-md);padding:14px 16px;box-shadow:var(--shadow-sm);
          display:flex;align-items:center;gap:14px}
        .planes-tile-num{font-size:30px;font-weight:800;font-family:'Sora','Inter',sans-serif;
          color:var(--c);line-height:1;min-width:38px;text-align:center}
        .planes-tile-label{font-size:13px;font-weight:700;color:var(--text)}
        .planes-tile-sub{font-size:11.5px;color:var(--muted);margin-top:2px}
        @media(max-width:760px){.planes-tiles{grid-template-columns:1fr}}

        .plan-chips{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}
        .plan-chip{font-size:12.5px;color:var(--muted);background:var(--panel);border:1px solid var(--line);
          border-radius:999px;padding:5px 12px}
        .plan-chip b{font-size:15px;color:var(--c);margin-right:4px;font-family:'Sora','Inter',sans-serif}

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
        </style>
        """,
        unsafe_allow_html=True,
    )


def _pasos_hechos(plan: dict) -> list[bool]:
    clave = _clave_plan(plan)
    return [bool(st.session_state.get(f"paso_{clave}_{j}")) for j in range(len(plan["pasos"]))]


def _tiles(resultado: dict, planes: list) -> None:
    conteos = {
        "critico": resultado["criticos"],
        "atencion": resultado["atencion"],
        "mejora": sum(1 for p in planes if p["estado"] == "mejora"),
    }
    html = []
    for estado, n in conteos.items():
        tono = _TONO[estado]
        html.append(
            f'<div class="planes-tile" style="--c:{tono["color"]}">'
            f'<div class="planes-tile-num">{n}</div>'
            f'<div><div class="planes-tile-label">{tono["icono"]} {tono["etiqueta"]}</div>'
            f'<div class="planes-tile-sub">{tono["urgencia"]}</div></div></div>'
        )
    st.markdown(f'<div class="planes-tiles">{"".join(html)}</div>', unsafe_allow_html=True)


def _seguimiento(filas: list) -> None:
    """Contadores de seguimiento, con el número en rojo, verde o negro.

    Rojo cuando hay algo que va mal, verde cuando hay algo terminado y negro
    cuando el conteo es cero: un cero en rojo sería una alarma falsa.
    """
    vencidos = sum(1 for f in filas if f["Alerta"] == "Vencido")
    sin_responsable = sum(1 for f in filas if f["Alerta"] == "Sin responsable")
    terminados = sum(1 for f in filas if f["Estado"] == "Hecho")
    chips = [
        (vencidos, "vencido(s)", _ROJO),
        (sin_responsable, "sin responsable", _ROJO),
        (terminados, "terminado(s)", _VERDE),
    ]
    html = []
    for n, texto, color in chips:
        color_numero = color if n else "var(--text)"
        html.append(f'<span class="plan-chip" style="--c:{color_numero}"><b>{n}</b>{texto}</span>')
    st.markdown(f'<div class="plan-chips">{"".join(html)}</div>', unsafe_allow_html=True)


def _hoja_de_ruta(filas: list, asignaciones: dict) -> bool:
    """La tabla de todos los frentes, con responsable y fecha editables.

    Devuelve True si hubo cambios, para que la pantalla se redibuje con los
    estados y alertas ya actualizados.
    """
    claves = [f["clave"] for f in filas]
    # La clave del widget depende de qué planes hay: si los filtros del panel
    # cambian los planes, la tabla empieza de nuevo en vez de aplicar una
    # edición vieja a la fila equivocada.
    firma = hashlib.md5("|".join(claves).encode("utf-8")).hexdigest()[:10]
    tabla = pd.DataFrame([{
        "#": f["#"],
        "Urgencia": f["Urgencia"],
        "Frente": f["Frente"],
        "A quién afecta": f["A quién afecta"],
        "Responsable": f["Responsable"],
        "Fecha compromiso": f["Fecha compromiso"],
        "Estado": f["Estado"],
        "Avance": f["Avance"],
        "Alerta": f["Alerta"],
        "Cómo se mide": f["Cómo se mide"],
    } for f in filas])
    tabla["Fecha compromiso"] = pd.to_datetime(tabla["Fecha compromiso"])
    editada = st.data_editor(
        tabla, key=f"planes_hoja_{firma}", hide_index=True, use_container_width=True, num_rows="fixed",
        disabled=["#", "Urgencia", "Frente", "A quién afecta", "Estado", "Avance", "Alerta", "Cómo se mide"],
        column_config={
            "#": st.column_config.NumberColumn(width="small"),
            "Urgencia": st.column_config.TextColumn(width="small"),
            "Frente": st.column_config.TextColumn(width="medium"),
            "A quién afecta": st.column_config.TextColumn(width="medium"),
            "Responsable": st.column_config.TextColumn("✏️ Responsable", width="medium",
                                                       help="Escribe quién se hace cargo de este frente."),
            "Fecha compromiso": st.column_config.DateColumn("✏️ Fecha compromiso", format="DD/MM/YYYY",
                                                            width="small"),
            "Estado": st.column_config.TextColumn(width="small",
                                                  help="Sale de los pasos marcados en cada plan."),
            "Avance": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1, width="small"),
            "Alerta": st.column_config.TextColumn(width="small"),
            "Cómo se mide": st.column_config.TextColumn(width="large"),
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


def _plan(i: int, plan: dict, fila: dict) -> None:
    tono = _TONO.get(plan["estado"], _TONO["mejora"])
    clave = fila["clave"]
    # Título fijo: si incluyera el avance o el responsable, cambiaría con cada
    # casilla marcada, y Streamlit cierra un plegable cuando cambia su título.
    etiqueta = f"{tono['icono']}  {i}. {plan['titulo']}   ·   {tono['etiqueta']}"
    abierto = plan["estado"] == "critico" or fila["Alerta"] == "Vencido"
    with st.expander(etiqueta, expanded=abierto):
        datos = [f'<span class="plan-dato">{fila["Estado"]} · {fila["hechos"]} de {fila["total"]} pasos</span>']
        if fila["Responsable"]:
            datos.append(f'<span class="plan-dato">👤 {clean_display_text(fila["Responsable"])}</span>')
        else:
            datos.append('<span class="plan-dato falta">👤 Sin responsable · asígnalo en la hoja de ruta</span>')
        if fila["Fecha compromiso"]:
            color_fecha = _ROJO if fila["Alerta"] == "Vencido" else "var(--text)"
            fecha_txt = f"{fila['Fecha compromiso']:%d/%m/%Y}"
            vencido = " · vencido" if fila["Alerta"] == "Vencido" else ""
            datos.append(f'<span class="plan-dato" style="color:{color_fecha}">📅 {fecha_txt}{vencido}</span>')
        else:
            datos.append('<span class="plan-dato falta">📅 Sin fecha compromiso</span>')
        st.markdown(f'<div class="plan-datos">{"".join(datos)}</div>', unsafe_allow_html=True)

        izquierda, derecha = st.columns([1.6, 1], gap="medium")
        with izquierda:
            st.markdown(f'<div class="plan-situacion">{clean_display_text(plan["situacion"])}</div>',
                        unsafe_allow_html=True)
            if plan.get("evidencia"):
                st.markdown(evidence_list(plan["evidencia"]), unsafe_allow_html=True)
        with derecha:
            st.markdown(
                f'<div class="plan-caja" style="--c:{tono["color"]}">'
                f'<div class="plan-caja-titulo">🎯 Cómo se sabe que funcionó</div>'
                f'<div class="plan-caja-texto">{clean_display_text(plan["medir"])}</div></div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="plan-caja" style="--c:var(--muted);margin-top:8px">'
                f'<div class="plan-caja-titulo">Por qué importa</div>'
                f'<div class="plan-caja-texto" style="font-size:12.5px;color:var(--muted)">'
                f'{clean_display_text(plan["por_que"])}</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown('<div class="plan-pasos-titulo">Plan · marca cada paso cuando esté hecho</div>',
                    unsafe_allow_html=True)
        for j, paso in enumerate(plan["pasos"]):
            st.checkbox(f"{j + 1}. {paso}", key=f"paso_{clave}_{j}")
        hechos = sum(_pasos_hechos(plan))
        total = len(plan["pasos"])
        if total:
            st.progress(hechos / total, text=f"{hechos} de {total} pasos completados")


def render_planes(df: pd.DataFrame, schema: dict, dashboard: dict) -> None:
    _css()
    st.markdown(section_header(
        "Planes de mejora",
        eyebrow="DECISIONES",
        subtitle="Cada hallazgo del análisis convertido en un plan con pasos concretos y una forma de medir si funcionó.",
    ), unsafe_allow_html=True)

    resultado = generar(df, schema, dashboard or {})
    planes = resultado["planes"]
    if not planes:
        st.success("No hay hallazgos que convertir en plan con los datos visibles. "
                   "Si esperabas ver algo aquí, revisa los filtros activos.")
        return

    hoy = date.today()
    asignaciones = st.session_state.setdefault("planes_asignacion", {})
    pasos = {_clave_plan(p): _pasos_hechos(p) for p in planes}
    filas = filas_plan_de_accion(planes, asignaciones, pasos, hoy)

    _tiles(resultado, planes)
    st.markdown(
        f"<div style='background:var(--panel-2);border:1px solid var(--line);border-radius:10px;"
        f"padding:11px 15px;margin:0 0 10px;font-size:13.5px;color:var(--text)'>"
        f"{clean_display_text(resultado['resumen'])}</div>",
        unsafe_allow_html=True,
    )
    _seguimiento(filas)

    st.markdown(section_header(
        "Hoja de ruta",
        subtitle="Escribe el responsable y la fecha compromiso de cada frente aquí mismo. "
                 "El estado y el avance salen de los pasos que se marquen en cada plan.",
        compact=True), unsafe_allow_html=True)
    if _hoja_de_ruta(filas, asignaciones):
        st.rerun()
    _exportar(planes, asignaciones, pasos, hoy)

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

    st.markdown(section_header("Planes en detalle", compact=True), unsafe_allow_html=True)
    visibles = [(i, p, f) for i, (p, f) in enumerate(zip(planes, filas), 1) if criterio(p, f)]
    if not visibles:
        st.info("No hay planes en esta categoría con los datos visibles.")
    for i, plan, fila in visibles:
        _plan(i, plan, fila)

    st.caption("Los planes salen del análisis de este archivo con los filtros activos. No incorporan lo que "
               "el archivo no contenga, como una campaña, un cierre o un cambio de precio, así que conviene "
               "contrastarlos con lo que sabes del negocio. Responsables, fechas y pasos marcados se guardan "
               "mientras dure la sesión: descarga el Excel para conservarlos.")
