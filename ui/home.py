"""Pestaña de Inicio: una introducción breve antes de entrar al dashboard.

No repite el análisis de las demás pestañas; da contexto (qué hace la
herramienta, qué se cargó, cómo moverse) y usa clases de estilo ya definidas
en app.py para no introducir CSS adicional.
"""
from __future__ import annotations
import html
import re

import pandas as pd
import streamlit as st

from ui.components.cards import kpi_card, executive_headline, note_group
from ui.imagenes import render_imagenes
from ui.components.section import section_header, decision_strip
from ui.layouts.hero import hero


def _step(number: str, title: str, text: str) -> str:
    return (
        f'<div class="drilldown-card" style="display:flex;gap:14px;align-items:flex-start;padding:16px;">'
        f'<div class="action-number" style="flex:0 0 30px;width:30px;height:30px;border-radius:50%;'
        f'background:var(--brand-orb);color:#fff;'
        f'display:flex;align-items:center;justify-content:center;font-weight:800;font-size:13px;">{number}</div>'
        f'<div><b style="font-size:13.5px;">{title}</b>'
        f'<div style="color:var(--muted);font-size:12.5px;margin-top:3px;line-height:1.45;">{text}</div></div>'
        f'</div>'
    )


def filas_contenido(sheets: dict) -> list[dict]:
    """Una fila por tabla leída: qué es, cuánto trae, qué periodo cubre y qué mide."""
    filas = []
    for nombre, item in sheets.items():
        if not isinstance(item, dict):
            continue
        df = item.get("processed")
        perfil = item.get("profile") or {}
        schema = perfil.get("schema") or {}
        if df is None:
            continue
        periodo = "—"
        fechas = [d for d in schema.get("dates", []) if d in df.columns]
        if fechas:
            f = pd.to_datetime(df[fechas[0]], errors="coerce").dropna()
            if len(f):
                periodo = f"{f.min():%m/%Y} a {f.max():%m/%Y}" if f.min() != f.max() else f"{f.min():%m/%Y}"
        agrupa = [c for c in schema.get("categorical", []) + schema.get("text", []) if c in df.columns]
        filas.append({
            "Tabla": nombre,
            "Registros": len(df),
            "Agrupa por": ", ".join(dict.fromkeys(map(str, agrupa))) or "—",
            "Mide": ", ".join(map(str, schema.get("metrics", [])[:6])) or "—",
            "Periodo": periodo,
        })
    return filas


def _recorta_plano(texto: str) -> str:
    """Quita del aviso la parte que explica el motivo: esa va en el grupo.

    Los avisos los arma `core/loader.py` como frases completas y autónomas
    («…es idéntica a X: se muestra una sola vez.»), porque cada una vivía
    sola en su franja. Agrupadas, esa cola se repetía tantas veces como
    avisos hubiera; aquí se recorta para dejar solo el dato que cambia —el
    nombre de la tabla o de la hoja— y el motivo se dice una vez arriba.

    Devuelve el texto SIN escapar, para poder hacerle match con una
    expresión regular antes de escapar cada pieza por separado.
    """
    t = re.split(r"[:.]\s*[Uu]na imagen no trae", str(texto))[0]
    t = t.replace(": se muestra una sola vez.", "")
    return t.strip().rstrip(":.").strip()


def _recorta(texto: str) -> str:
    """Lo mismo, ya listo para pintar: es el respaldo para un aviso con una
    redacción que no reconoce ninguno de los formatos de abajo."""
    return html.escape(_recorta_plano(texto))


def _fila_repetida(texto: str) -> str:
    """«Tabla» — hoja X · ya estaba como «Otra». La frase completa decía lo
    mismo en 18 palabras; puestas en fila, lo único que se compara es el
    nombre, así que el nombre va primero y el resto queda en gris."""
    m = re.match(r"^«(.+?)» de la hoja «(.+?)» es idéntica a «(.+?)»$", _recorta_plano(texto))
    if not m:
        return _recorta(texto)
    tabla, hoja, igual = (html.escape(x) for x in m.groups())
    return f'<b>«{tabla}»</b> <span class="note-item-meta">hoja «{hoja}» · ya estaba como «{igual}»</span>'


def _fila_imagen(texto: str) -> str:
    """«Sección» — hoja X. Igual que arriba: el qué antes del dónde."""
    plano = _recorta_plano(texto)
    m = re.match(r"^En la hoja «(.+?)», (.+?) (?:es una imagen pegada|son imágenes pegadas)$", plano)
    if m:
        hoja, secciones = html.escape(m.group(1)), html.escape(m.group(2))
        return f'<b>{secciones}</b> <span class="note-item-meta">hoja «{hoja}»</span>'
    # "imagen pegada" en singular, "imágenes pegadas" en plural: el acento
    # solo aparece en el plural, así que no se puede escribir como una sola
    # raíz con letras opcionales.
    m = re.match(r"^La hoja «(.+?)» tiene (\d+) (?:imagen|imágenes) pegadas?$", plano)
    if m:
        hoja, cuantas = html.escape(m.group(1)), m.group(2)
        cuenta = f'{cuantas} {"imagen" if cuantas == "1" else "imágenes"}'
        return f'<b>hoja «{hoja}»</b> <span class="note-item-meta">{cuenta}, sin título de sección</span>'
    return _recorta(texto)


def _notas_de_lectura(avisos: list) -> None:
    """Lo que el lector hizo con el archivo, agrupado por tipo.

    Antes cada aviso era una franja de ancho completo, una debajo de otra:
    un informe con cuatro tablas repetidas y dos hojas con imágenes pegadas
    abría con seis párrafos casi idénticos, y lo importante —que hay tablas
    que no se perdieron y que hay imágenes que sí se pueden leer con el
    OCR— quedaba enterrado en la repetición.

    Ahora: una línea visible con el recuento (nadie tiene que abrir nada
    para enterarse de que pasó algo) y el detalle completo, sin recortar
    ningún nombre, dentro del desplegable.
    """
    if not avisos:
        return
    repetidas, imagenes, otros = [], [], []
    for aviso in avisos:
        texto = str(aviso)
        if "idéntica" in texto:
            repetidas.append(_fila_repetida(texto))
        elif "imagen" in texto.lower():
            imagenes.append(_fila_imagen(texto))
        else:
            otros.append(html.escape(texto))

    resumen = []
    if repetidas:
        resumen.append(f"<b>{len(repetidas)}</b> tabla{'s' if len(repetidas) != 1 else ''} repetida"
                       f"{'s' if len(repetidas) != 1 else ''}")
    if imagenes:
        resumen.append(f"<b>{len(imagenes)}</b> aviso{'s' if len(imagenes) != 1 else ''} de imagen pegada")
    if otros:
        resumen.append(f"<b>{len(otros)}</b> nota{'s' if len(otros) != 1 else ''} más")
    st.markdown(
        decision_strip("<b>📋 Notas de lectura:</b> " + " · ".join(resumen)
                       + " — qué son y a qué hoja pertenecen, en el detalle."),
        unsafe_allow_html=True,
    )
    with st.expander("Ver el detalle de las notas de lectura", expanded=False):
        if repetidas:
            st.markdown(note_group("📑", "Tablas repetidas",
                                   "Ya estaban en otra hoja del archivo, con los mismos números: "
                                   "se muestran una sola vez para no duplicar el selector de hojas.",
                                   repetidas), unsafe_allow_html=True)
        if imagenes:
            st.markdown(note_group("🖼️", "Imágenes pegadas",
                                   "Una imagen no trae celdas con números, así que no entra en el análisis. "
                                   "Si muestra cifras escritas (una tabla o un gráfico con sus valores), "
                                   "se puede leer en «🖼️ Imágenes del archivo», más abajo en esta pestaña.",
                                   imagenes), unsafe_allow_html=True)
        if otros:
            st.markdown(note_group("ℹ️", "Otras notas",
                                   "Avisos del lector sobre cómo se interpretó el archivo.",
                                   otros), unsafe_allow_html=True)


def _contenido_del_archivo(sheets: dict) -> None:
    """Todo lo que se leyó, en una tabla: si algo del Excel no aparece aquí, no se leyó.

    Un informe con quince bloques se convierte en varias tablas y el selector
    de hojas solo muestra nombres. Sin este resumen no había forma de saber,
    sin revisar una por una, si se había saltado algo.
    """
    filas = filas_contenido(sheets)
    if len(filas) < 2:
        return
    with st.expander(f"📚 Qué se leyó del archivo · {len(filas)} tablas", expanded=False):
        st.caption("Cada tabla se elige en «Hoja activa» del menú lateral. Si una parte del Excel no aparece "
                   "aquí, no se pudo leer: los avisos de arriba dicen por qué.")
        st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)


def render_home(wb: dict, sheet: str, mode_info: dict, dashboard: dict, seleccion: dict | None = None) -> None:
    sheets = wb.get("sheets", {}) or {}
    total_records = sum(len(it.get("processed", [])) for it in sheets.values() if isinstance(it, dict))
    classification = (mode_info or {}).get("classification", {}) or {}
    # Es la pestaña con la que abre el panel. Antes mostraba siempre el
    # archivo completo: al aplicar un filtro, lo primero que se veía no
    # cambiaba y parecía que el filtro no hacía nada.
    filtrado = bool(seleccion and seleccion.get("filtrado"))

    # ── Hero de bienvenida + snapshot del archivo, envueltos en un
    # st.container(key=...) para que compartan un solo fondo con foto (ver
    # ".st-key-home_hero_band" en ui/styles/theme.py) — la misma extensión
    # visual de la franja de arriba, pero contenida SOLO a esta pestaña
    # (Inicio): la franja de arriba es compartida por toda la app (vive una
    # sola vez en .block-container, antes de las pestañas) y alargarla ahí
    # habría puesto esta misma foto detrás de otras pestañas (Resumen
    # ejecutivo, Descripción...) sin que su texto esté preparado para eso.
    # Un container propio, con su fondo propio, evita ese efecto secundario
    # por completo. El alto no es un número fijo: crece con el contenido
    # de adentro, así que termina justo después de la fila de 4 tarjetas
    # sin necesidad de calcular ningún píxel a mano.
    with st.container(key="home_hero_band"):
        hero(
            "Bienvenido al Panel Analítico Universal",
            "Sube cualquier Excel o CSV y obtén, en segundos, KPIs, hallazgos, "
            "alertas, comparaciones y un informe listo para compartir — sin depender de una estructura fija.",
            icon=True, tight=True, band=True,
        )

        # ── Snapshot del archivo cargado ─────────────────────────────────
        st.markdown(section_header("Qué se cargó", eyebrow="ARCHIVO ACTUAL", compact=True), unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(kpi_card("Archivo", wb.get("filename", "—"), small_value=True), unsafe_allow_html=True)
        c2.markdown(kpi_card("Hojas con datos", f"{len(sheets):,}"), unsafe_allow_html=True)
        if filtrado:
            c3.markdown(kpi_card("Registros en la vista", f"{seleccion['visibles']:,}",
                                 delta=f"de {seleccion['total']:,} · {seleccion['porcentaje']:.0f}% de la hoja"),
                        unsafe_allow_html=True)
        else:
            c3.markdown(kpi_card("Registros totales", f"{total_records:,}"), unsafe_allow_html=True)
        c4.markdown(kpi_card("Hoja activa", sheet, small_value=True), unsafe_allow_html=True)

    # ── Qué información es y qué no se pudo leer ────────────────────────────
    # Qué estoy viendo y cómo se interpretó son la misma pregunta, así que
    # van en una sola tarjeta. Antes eran dos franjas de ancho completo
    # separadas por media pantalla ("Estás viendo…" arriba del todo y "Tipo
    # detectado…" después de las imágenes y del contenido del archivo), y
    # las herramientas activadas se leían como una frase con comas.
    item = sheets.get(sheet) if isinstance(sheets.get(sheet), dict) else {}
    titulo = (item.get("profile") or {}).get("titulo")
    if titulo or classification:
        partes = []
        if titulo:
            partes.append('<div class="context-main"><span class="decision-dot"></span>'
                          f'<b>Estás viendo:</b> {html.escape(str(titulo))}</div>')
        if classification:
            cap_labels = {"evolucion": "evolución", "comparacion_periodos": "comparación de periodos",
                          "ranking": "rankings", "distribucion": "distribuciones",
                          "relaciones": "relaciones entre métricas", "estadisticas": "estadísticas",
                          "grafico_distribucion": "gráficos de distribución", "geografia": "geografía",
                          "catalogo": "consulta de catálogo", "estados": "seguimiento de estados"}
            caps = classification.get("capabilities", [])[:6]
            chips = "".join(f'<span class="context-chip">{html.escape(cap_labels.get(x, str(x)))}</span>'
                            for x in caps) or '<span class="context-chip">lectura y tabla</span>'
            partes.append(
                '<div class="context-meta">'
                f'<span class="context-tipo">{html.escape(str(classification.get("label", "Datos generales")))}</span>'
                f'<span class="context-conf">confianza {(classification.get("confidence") or 0) * 100:.0f}%</span>'
                '</div>'
                f'<div class="context-caps"><span class="context-caps-label">Herramientas activas</span>{chips}</div>'
            )
        st.markdown(f'<div class="context-bar">{"".join(partes)}</div>', unsafe_allow_html=True)
        reason = classification.get("reason") if classification else None
        if reason:
            with st.expander("¿Por qué se detectó este tipo de datos?", expanded=False):
                st.caption(reason)
    _notas_de_lectura(wb.get("avisos") or [])
    render_imagenes(wb)
    _contenido_del_archivo(sheets)

    # ── La selección actual: qué filtros hay y cómo va lo que queda ────────
    if filtrado:
        st.markdown(section_header("Tu selección", eyebrow="VISTA FILTRADA", compact=True), unsafe_allow_html=True)
        frases = [html.escape(str(f)) for f in seleccion.get("frases", [])]
        texto = (f"<b>Filtros activos:</b> {' · '.join(frases)}" if frases
                 else "<b>Vista acotada</b> por el periodo o la búsqueda.")
        st.markdown(decision_strip(texto, dot=True), unsafe_allow_html=True)
        if isinstance(dashboard, dict) and dashboard.get("executive"):
            executive_headline(dashboard)

    # ── Cómo moverse por la herramienta ────────────────────────────────────
    st.markdown(section_header("Recorrido rápido", eyebrow="CÓMO EMPEZAR", compact=True), unsafe_allow_html=True)
    s1, s2 = st.columns(2)
    with s1:
        st.markdown(_step("1", "Resumen ejecutivo", "KPIs, tendencia, hallazgos y alertas calculados automáticamente sobre tus datos."), unsafe_allow_html=True)
        st.write("")
        st.markdown(_step("2", "Filtros y segmentación", "Usa la barra lateral para acotar por persona, categoría, región o periodo. Todo el panel se recalcula solo."), unsafe_allow_html=True)
    with s2:
        st.markdown(_step("3", "Asistente IA y comparaciones", "Pregunta directamente sobre tus datos, compara personas o compara archivos/periodos completos."), unsafe_allow_html=True)
        st.write("")
        st.markdown(_step("4", "Exportar", "Descarga un informe HTML autocontenido (una hoja o el Excel completo) listo para compartir por correo."), unsafe_allow_html=True)

    st.markdown(
        '<div class="chart-reading" style="margin-top:18px;"><b>Tip:</b> cada pestaña recalcula sus '
        'indicadores en tiempo real según los filtros activos en la barra lateral.</div>',
        unsafe_allow_html=True,
    )
