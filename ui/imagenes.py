"""Leer las imágenes pegadas del Excel, revisarlas y sumarlas al panel.

Vive en 🏠 Inicio, debajo de los avisos. El flujo es a propósito en tres
pasos y nunca automático:

1. **Leer** (botón): el OCR corre en este equipo (core/imagen_ocr.py) y tarda
   unos segundos por imagen; leer al cargar el archivo haría esperar a todos
   aunque nadie necesite las imágenes.
2. **Revisar**: la tabla leída aparece bajo la imagen original, editable, con
   los avisos de celdas vacías o dudosas. Un OCR se equivoca poco con
   capturas nítidas, pero se equivoca, y un número mal leído analizado a
   ciegas es peor que no tenerlo.
3. **Usar**: solo entonces entra como una tabla más —en «Hoja activa»— con el
   registro de que viene de una imagen.
"""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

import core.imagen_ocr as ocr
from core.informe import _nombrar_medida
from core.profile import profile_sheet


def _vocabulario(wb: dict) -> dict:
    return ocr.vocabulario_de([it.get("processed") for it in (wb.get("sheets") or {}).values()
                               if isinstance(it, dict)])


def _leer(wb: dict, img: dict, resultados: dict) -> None:
    with st.spinner(f"Leyendo «{img['seccion']}» en este equipo…"):
        try:
            resultados[img["id"]] = ocr.interpretar_imagen(img["bytes"], _vocabulario(wb), img.get("anio"))
        except Exception as exc:
            resultados[img["id"]] = {"tipo": None, "avisos": [f"No se pudo leer la imagen: {type(exc).__name__}: {exc}"]}


def _usar(wb: dict, img: dict, resultado: dict, editada: pd.DataFrame, nombre: str, medida: str) -> str:
    largo = ocr.a_tabla_larga(resultado, editada, medida)
    nombre = nombre.strip() or f"{img['seccion']} (imagen)"
    base, i = nombre, 2
    while nombre in wb["sheets"]:
        nombre, i = f"{base} ({i})", i + 1
    item = profile_sheet(
        largo,
        context={"sheet_name": nombre, "workbook_name": wb.get("filename", ""), "faltantes_son_cero": False},
        structural_log=[f"Leída de la imagen «{img['seccion']}» (hoja «{img['hoja']}») con OCR local (RapidOCR), "
                        "sin enviarla a ningún servicio, y revisada antes de usarse. No viene de celdas del Excel: "
                        "si una cifra no cuadra, compárala con la imagen original."],
    )
    item["profile"]["titulo"] = f"{img['seccion']} · leída de imagen"
    item["profile"]["relationships"] = []
    wb["sheets"][nombre] = item
    return nombre


def render_imagenes(wb: dict) -> None:
    imagenes = wb.get("imagenes") or []
    if not imagenes:
        return
    resultados = st.session_state.setdefault("ocr_resultados", {})
    usadas = st.session_state.setdefault("ocr_usadas", {})
    pendientes = [i for i in imagenes if i["id"] not in usadas]
    titulo = f"🖼️ Imágenes del archivo · {len(imagenes)}" + (f" · {len(pendientes)} sin usar" if pendientes else " · todas en el panel")
    with st.expander(titulo, expanded=False):
        if not ocr.disponible():
            st.warning("El lector de imágenes no está instalado en este equipo. Instálalo con "
                       "`pip install rapidocr_onnxruntime` y vuelve a abrir el panel.")
            return
        st.caption("Las imágenes se leen **en este equipo** con RapidOCR: no se envían a ningún servicio externo. "
                   "Cada tabla leída se revisa antes de sumarse al panel.")
        sin_leer = [i for i in pendientes if i["id"] not in resultados]
        if len(sin_leer) > 1 and st.button(f"🔍 Leer las {len(sin_leer)} imágenes", key="ocr_leer_todas"):
            for img in sin_leer:
                _leer(wb, img, resultados)
            st.rerun()

        for img in imagenes:
            clave = img["id"]
            st.markdown(f"**{html.escape(img['seccion'])}** · hoja «{html.escape(img['hoja'])}»")
            st.image(img["bytes"], use_container_width=True)
            if clave in usadas:
                st.success(f"Ya está en el panel como «{usadas[clave]}»: elígela en «Hoja activa».")
                st.divider()
                continue
            if clave not in resultados:
                if st.button("🔍 Leer esta imagen", key=f"ocr_leer_{clave}"):
                    _leer(wb, img, resultados)
                    st.rerun()
                st.divider()
                continue

            resultado = resultados[clave]
            if not resultado.get("tipo"):
                for aviso in resultado.get("avisos", []):
                    st.info(aviso)
                st.divider()
                continue

            que = "una tabla" if resultado["tipo"] == "tabla" else "un gráfico de líneas"
            st.markdown(f"Se reconoció **{que}**. " + " ".join(html.escape(a) for a in resultado.get("avisos", [])))
            if resultado.get("dudas"):
                with st.expander(f"⚠️ {len(resultado['dudas'])} valor(es) para revisar"):
                    for d in resultado["dudas"]:
                        st.caption("· " + d)
            st.caption("Revisa la tabla contra la imagen de arriba. Puedes corregir cualquier celda antes de usarla.")
            editada = st.data_editor(resultado["ancha"], key=f"ocr_editor_{clave}", use_container_width=True,
                                     hide_index=True, num_rows="fixed")
            a, b = st.columns(2)
            with a:
                nombre = st.text_input("Nombre de la tabla en el panel", value=f"{img['seccion']} (imagen)",
                                       key=f"ocr_nombre_{clave}")
            medida = "Valor"
            if resultado["tipo"] == "tabla":
                meses = [c for c in resultado["ancha"].columns if c in resultado["periodos"]]
                valores = resultado["ancha"][meses].stack().tolist()
                sugerida = _nombrar_medida(img["seccion"], valores, resultado.get("porcentaje", False))
                with b:
                    medida = st.text_input("¿Qué miden las cifras?", value=sugerida, key=f"ocr_medida_{clave}",
                                           help="Por ejemplo «Cumplimiento %». Es el nombre de la columna de valores.")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ Usar esta tabla en el panel", key=f"ocr_usar_{clave}", type="primary"):
                    usadas[clave] = _usar(wb, img, resultado, editada, nombre, medida)
                    st.rerun()
            with c2:
                if st.button("↺ Volver a leer", key=f"ocr_releer_{clave}"):
                    resultados.pop(clave, None)
                    st.session_state.pop(f"ocr_editor_{clave}", None)
                    st.rerun()
            st.divider()
