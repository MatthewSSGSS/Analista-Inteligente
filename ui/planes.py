"""Pestaña "Planes de mejora".

Cada hallazgo del análisis convertido en un plan con pasos concretos y una
forma de medir si funcionó. Ver `core/planes.py` para el criterio; aquí solo
se presenta.

La primera versión mostraba todos los planes seguidos como bloques de texto:
correcta, pero en una reunión nadie encontraba nada. Esta se organiza para
usarse, no solo para leerse:

- **Arriba, la hoja de ruta**: una tabla con todos los frentes, a quién
  afectan y cómo se miden. Es lo que se proyecta al abrir la reunión.
- **Un filtro por urgencia**, para ir a lo crítico sin pasar por lo demás.
- **Cada plan plegable**, lo crítico abierto y el resto cerrado, con los
  pasos como casillas que se pueden marcar: el avance queda a la vista en el
  propio título ("2 de 4 pasos").

No se quitó nada de lo que tenía cada plan: situación, evidencia, por qué
importa, pasos y cómo se mide siguen todos, solo que ordenados.
"""
from __future__ import annotations

import hashlib

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


def _clave_plan(plan: dict) -> str:
    """Identificador estable de un plan, para que las casillas marcadas no se
    pierdan al cambiar el filtro o al volver a la pestaña."""
    base = f"{plan['titulo']}|{plan['situacion'][:80]}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()[:10]


def _casos(plan: dict) -> str:
    nombres = [str(e.get("nombre")) for e in (plan.get("evidencia") or [])
               if e.get("nombre") and str(e["nombre"]) not in _NO_SON_CASOS]
    return ", ".join(nombres[:3]) if nombres else "—"


def _avance(plan: dict) -> tuple[int, int]:
    clave = _clave_plan(plan)
    hechos = sum(1 for j in range(len(plan["pasos"])) if st.session_state.get(f"paso_{clave}_{j}"))
    return hechos, len(plan["pasos"])


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


def _hoja_de_ruta(planes: list) -> None:
    """Todos los frentes en una tabla: lo que se proyecta al abrir la reunión."""
    filas = []
    for i, plan in enumerate(planes, 1):
        hechos, total = _avance(plan)
        tono = _TONO.get(plan["estado"], _TONO["mejora"])
        filas.append({
            "#": i,
            "Urgencia": f"{tono['icono']} {tono['etiqueta']}",
            "Frente": plan["titulo"],
            "A quién afecta": _casos(plan),
            "Avance": hechos / total if total else 0.0,
            "Cómo se mide": plan["medir"],
        })
    st.dataframe(
        pd.DataFrame(filas), use_container_width=True, hide_index=True,
        column_config={
            "#": st.column_config.NumberColumn(width="small"),
            "Urgencia": st.column_config.TextColumn(width="small"),
            "Frente": st.column_config.TextColumn(width="medium"),
            "A quién afecta": st.column_config.TextColumn(width="medium"),
            "Avance": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1, width="small"),
            "Cómo se mide": st.column_config.TextColumn(width="large"),
        },
    )


def _plan(i: int, plan: dict) -> None:
    tono = _TONO.get(plan["estado"], _TONO["mejora"])
    clave = _clave_plan(plan)
    hechos, total = _avance(plan)
    etiqueta = (f"{tono['icono']}  {i}. {plan['titulo']}   ·   {tono['etiqueta']}"
                f"   ·   {hechos} de {total} pasos")
    with st.expander(etiqueta, expanded=(plan["estado"] == "critico")):
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
        hechos, total = _avance(plan)
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

    _tiles(resultado, planes)
    st.markdown(
        f"<div style='background:var(--panel-2);border:1px solid var(--line);border-radius:10px;"
        f"padding:11px 15px;margin:0 0 14px;font-size:13.5px;color:var(--text)'>"
        f"{clean_display_text(resultado['resumen'])}</div>",
        unsafe_allow_html=True,
    )

    st.markdown(section_header("Hoja de ruta", subtitle="Todos los frentes de un vistazo. El avance se actualiza al marcar los pasos de cada plan.",
                               compact=True), unsafe_allow_html=True)
    _hoja_de_ruta(planes)

    opciones = {"Todos": None, "🔴 Críticos": "critico", "🟡 En observación": "atencion", "🟢 Oportunidades": "mejora"}
    elegido = st.radio("Ver", list(opciones.keys()), horizontal=True, key="planes_filtro",
                       label_visibility="collapsed")
    estado = opciones[elegido]

    st.markdown(section_header("Planes en detalle", compact=True), unsafe_allow_html=True)
    visibles = [(i, p) for i, p in enumerate(planes, 1) if estado is None or p["estado"] == estado]
    if not visibles:
        st.info("No hay planes en esta categoría con los datos visibles.")
    for i, plan in visibles:
        _plan(i, plan)

    st.caption("Los planes salen del análisis de este archivo con los filtros activos. "
               "No incorporan lo que el archivo no contenga —una campaña, un cierre, un cambio de "
               "precio—, así que conviene contrastarlos con lo que sabes del negocio. "
               "Las casillas marcadas se guardan mientras dure la sesión.")
