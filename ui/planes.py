"""Pestaña "Planes de mejora".

Antes se llamaba "Trabajo y decisiones" y listaba los hallazgos con su línea
de "qué hacer". El salto que faltaba es el que da esta vista: convertir cada
hallazgo en un plan con pasos en orden, sobre los casos que el análisis ya
identificó por nombre, y con un indicador para poder cerrarlo.

Ver `core/planes.py` para el criterio. Aquí solo se pinta.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.planes import generar
from ui.components.cards import evidence_list
from ui.components.section import section_header
from ui.labels import clean_display_text

_TONO = {
    "critico": ("#be123c", "Crítico", "Atender primero"),
    "atencion": ("#b45309", "En observación", "Revisar este periodo"),
    "mejora": ("#0f8a5f", "Oportunidad", "Margen disponible"),
}


def render_planes(df: pd.DataFrame, schema: dict, dashboard: dict) -> None:
    st.markdown(section_header(
        "Planes de mejora",
        eyebrow="DECISIONES",
        subtitle="Cada hallazgo del análisis, convertido en un plan con pasos concretos y una forma de medir si funcionó.",
    ), unsafe_allow_html=True)

    resultado = generar(df, schema, dashboard or {})
    planes = resultado["planes"]
    if not planes:
        st.success("No hay hallazgos que convertir en plan con los datos visibles. "
                   "Si esperabas ver algo aquí, revisa los filtros activos.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Frentes críticos", resultado["criticos"])
    c2.metric("En observación", resultado["atencion"])
    c3.metric("Oportunidades", sum(1 for p in planes if p["estado"] == "mejora"))
    st.markdown(
        f"<div style='background:var(--panel-2);border:1px solid var(--line);border-radius:10px;"
        f"padding:12px 15px;margin:10px 0 16px;font-size:13.5px'>{clean_display_text(resultado['resumen'])}</div>",
        unsafe_allow_html=True,
    )

    for i, plan in enumerate(planes, 1):
        color, etiqueta, urgencia = _TONO.get(plan["estado"], _TONO["mejora"])
        pasos = "".join(
            f"<li style='margin-bottom:5px'>{clean_display_text(p)}</li>" for p in plan["pasos"]
        )
        st.markdown(
            f"""<div style="background:var(--panel);border:1px solid var(--line);
            border-left:4px solid {color};border-radius:var(--radius-md);
            padding:14px 16px;margin-bottom:12px;box-shadow:var(--shadow-sm)">
              <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap">
                <span style="font-size:9px;font-weight:800;letter-spacing:.07em;
                      text-transform:uppercase;color:{color}">{etiqueta} · {urgencia}</span>
                <b style="font-size:15px;color:var(--text)">{i}. {clean_display_text(plan['titulo'])}</b>
              </div>
              <div style="font-size:13px;color:var(--muted);margin-top:6px">
                {clean_display_text(plan['situacion'])}</div>
              {evidence_list(plan.get('evidencia'))}
              <div style="font-size:12.5px;color:var(--soft);margin-top:9px">
                <b>Por qué importa:</b> {clean_display_text(plan['por_que'])}</div>
              <div style="margin-top:10px;padding:10px 12px;background:var(--panel-2);
                   border:1px solid var(--line);border-radius:var(--radius-sm)">
                <b style="font-size:12px;color:var(--text)">Plan</b>
                <ol style="margin:6px 0 0;padding-left:20px;font-size:12.5px;
                    color:var(--text);line-height:1.45">{pasos}</ol>
              </div>
              <div style="font-size:12.5px;color:var(--text);margin-top:9px">
                <b>Cómo se sabe que funcionó:</b> {clean_display_text(plan['medir'])}</div>
            </div>""",
            unsafe_allow_html=True,
        )

    st.caption("Los planes salen del análisis de este archivo con los filtros activos. "
               "No incorporan lo que el archivo no contenga —una campaña, un cierre, un cambio de "
               "precio—, así que conviene contrastarlos con lo que sabes del negocio.")
