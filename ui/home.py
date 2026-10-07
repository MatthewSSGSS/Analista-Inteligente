"""Pestaña de Inicio: el parte del día para quien tiene que decidir.

Es la pantalla con la que abre el panel, así que responde primero lo que un
gerente pregunta al abrir el archivo: ¿cómo vamos?, ¿contra qué?, ¿qué hago?
Arriba, el titular del mes con su lectura frente al año anterior; debajo, las
cifras que importan (mes, mismo mes del año pasado, acumulado, margen, ticket)
y las tres cosas que más valen la pena, con cuánto valen y a quién tocan.

Antes abría con «Bienvenido», qué archivo se cargó, «confianza 93%»,
«herramientas activas» y un tutorial de cuatro pasos: nada del negocio. Eso
sigue disponible, pero abajo y plegado («Sobre el archivo»).
"""
from __future__ import annotations
import html
import re

import pandas as pd
import streamlit as st

from ui.components.cards import kpi_card, executive_headline, note_group
from core.executive import indicadores_gerente
from ui.imagenes import render_imagenes
from ui.components.section import section_header, decision_strip
from ui.layouts.tabs import VISTA_ATACAR, VISTA_RESUMEN, ir_a


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


_CSS_PARTE = """<style>
.parte-acciones{display:flex;flex-direction:column;gap:10px;margin:4px 0 6px}
.parte-accion{display:flex;gap:14px;align-items:flex-start;background:var(--panel);border:1px solid var(--line);
  border-radius:var(--radius-md);padding:14px 16px;box-shadow:var(--shadow-sm)}
.parte-accion .num{flex:0 0 30px;width:30px;height:30px;border-radius:50%;background:var(--brand-orb);color:#fff!important;
  display:flex;align-items:center;justify-content:center;font-weight:800;font-size:13px}
.parte-accion .cuerpo{flex:1;min-width:0}
.parte-accion .tit{font-weight:800;font-size:14.5px;color:var(--text)!important}
.parte-accion .txt{font-size:13px;color:var(--muted)!important;line-height:1.5;margin-top:3px}
.parte-accion .hacer{font-size:13px;color:var(--text)!important;margin-top:6px}
.parte-accion .medir{font-size:12px;color:var(--muted)!important;margin-top:4px}
.parte-accion .quien{display:inline-block;font-size:11.5px;font-weight:700;background:var(--panel-2);border:1px solid var(--line);
  border-radius:999px;padding:2px 9px;margin:6px 6px 0 0;color:var(--text)!important}
.parte-accion .valor{flex:0 0 auto;text-align:right}
.parte-accion .valor b{display:block;font-size:20px;font-weight:800;color:var(--green-strong)!important;font-family:var(--font-display)}
.parte-accion .valor small{font-size:11.5px;color:var(--muted)!important}
.parte-vigilar{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--amber);border-radius:var(--radius-md);
  padding:12px 16px;margin:6px 0}
.parte-vigilar b{font-size:13.5px;color:var(--text)!important}
.parte-vigilar div{font-size:12.5px;color:var(--muted)!important;margin-top:3px;line-height:1.45}
</style>"""


def _lectura_del_anio(indicadores: list[dict], g: dict) -> str:
    """La frase que pone el mes en contexto: un mes que sube dentro de un año
    que va mal (o al revés) es otra historia, y es justo lo que se escapa al
    mirar solo «frente al mes anterior»."""
    por_clave = {i.get("clave"): i for i in indicadores}
    acum, anual = por_clave.get("acumulado"), por_clave.get("anual")
    pct_mes = g.get("pct")
    if pct_mes is None or not (acum or anual):
        return ""
    def _pct(i):
        try:
            return float(str(i["detalle" if i.get("clave") == "acumulado" else "valor"]).split("%")[0])
        except (ValueError, KeyError):
            return None
    partes = []
    if anual:
        pa = _pct(anual)
        if pa is not None:
            partes.append(f"frente a {anual['etiqueta'].replace('Frente a ', '')} va <b>{pa:+.1f}%</b>")
    pac = _pct(acum) if acum else None
    if pac is not None:
        partes.append(f"el acumulado del año va <b>{pac:+.1f}%</b>")
    if not partes:
        return ""
    texto = "En perspectiva: " + " y ".join(partes) + "."
    if pac is not None and (pct_mes > 0) != (pac > 0) and abs(pac) >= 1:
        texto += (" El mes recupera terreno, pero el año sigue por debajo." if pct_mes > 0
                  else " Es un tropiezo dentro de un año que va bien: conviene atajarlo antes de que se vuelva tendencia.")
    return texto


def _acciones(g: dict) -> list[dict]:
    """Las tres cosas que más valen la pena, del análisis gerencial."""
    acciones = []
    for o in (g.get("oportunidades") or [])[:3]:
        quienes = [q["nombre"] for q in (o.get("quienes") or [])][:4]
        acciones.append({"titulo": o["titulo"], "texto": o.get("texto", ""), "hacer": o.get("accion", ""),
                         "medir": o.get("medir", ""), "quienes": quienes,
                         "valor": o.get("monto"), "pct": o.get("pct_total")})
    # La palanca (volumen o ticket) también es una acción, si queda sitio.
    if len(acciones) < 3 and g.get("accion_palanca") and g.get("texto_palanca"):
        acciones.append({"titulo": "Cuidar la palanca que movió el mes" if not g.get("empeoro")
                         else "Corregir la palanca que lo hundió",
                         "texto": g["texto_palanca"], "hacer": g["accion_palanca"], "medir": "",
                         "quienes": [], "valor": None, "pct": None})
    return acciones


def _tarjeta_accion(n: int, a: dict, mes: str) -> str:
    esc = html.escape
    quienes = "".join(f'<span class="quien">{esc(str(q))}</span>' for q in a["quienes"])
    valor = ""
    if a.get("valor"):
        from core.territorio import cifra
        valor = (f'<div class="valor"><b>+{esc(cifra(a["valor"]))}</b><small>al mes'
                 + (f' · {a["pct"]:.0f}% de {esc(mes)}' if a.get("pct") else "") + "</small></div>")
    return (f'<div class="parte-accion"><div class="num">{n}</div><div class="cuerpo">'
            f'<div class="tit">{esc(a["titulo"])}</div><div class="txt">{esc(a["texto"])}</div>'
            + (f'<div class="hacer">👉 {esc(a["hacer"])}</div>' if a.get("hacer") else "")
            + (f'<div class="medir">🎯 Se sabe que funcionó si: {esc(a["medir"])}</div>' if a.get("medir") else "")
            + (f"<div>{quienes}</div>" if quienes else "")
            + f"</div>{valor}</div>")


def _parte_del_dia(df, schema, dashboard) -> bool:
    """Titular + cifras + qué hacer. Devuelve False si no hay con qué armarlo."""
    g = dashboard.get("gerencia") if isinstance(dashboard, dict) else None
    if not (g and g.get("titular") and df is not None and schema):
        return False
    st.markdown(_CSS_PARTE, unsafe_allow_html=True)
    metrica = g.get("metrica")
    indicadores = indicadores_gerente(df, schema, g, metrica) if metrica else []
    st.markdown(section_header("Lo que tienes que saber", eyebrow="PARTE DEL DÍA",
                               subtitle=f"{html.escape(str(g.get('etiqueta') or metrica))} · "
                                        f"{html.escape(str(g['mes_b']))} frente a {html.escape(str(g['mes_a']))}"),
                unsafe_allow_html=True)
    ex = dict((dashboard.get("executive") or {}))
    ex["headline"] = html.escape(str(g["titular"]))
    contexto = _lectura_del_anio(indicadores, g)
    causa = next((f for f in g.get("frases") or [] if f.startswith("La causa")), "")
    ex["detail"] = " ".join(x for x in (contexto, html.escape(causa)) if x)
    ex["status"] = ("negative" if g.get("empeoro") else "positive") if g.get("se_movio") else "neutral"
    ex["status_label"] = ("Requiere atención" if g.get("empeoro") else "Va mejor") if g.get("se_movio") else "Estable"
    executive_headline({**dashboard, "executive": ex})
    if indicadores:
        # Siempre 4 columnas: con una sola cifra, la tarjeta se estiraba a todo el ancho.
        cols = st.columns(4)
        for col, i in zip(cols, indicadores[:4]):
            col.markdown(kpi_card(html.escape(i["etiqueta"]), html.escape(i["valor"]),
                                  delta=html.escape(i["detalle"]) if i.get("detalle") else None, tone=i["tono"]),
                         unsafe_allow_html=True)

    acciones = _acciones(g)
    if acciones:
        st.markdown(section_header("Qué hacer ahora", eyebrow="PRIORIDADES",
                                   subtitle="Ordenadas por lo que valen al mes. El plan completo, con responsables y "
                                            "pasos, está en «🎯 Qué atacar»."),
                    unsafe_allow_html=True)
        st.markdown('<div class="parte-acciones">' + "".join(
            _tarjeta_accion(n, a, str(g["mes_b"])) for n, a in enumerate(acciones, 1)) + "</div>",
            unsafe_allow_html=True)
    # Lo que no es una oportunidad pero no se puede dejar pasar (calidad,
    # estados, atípicos): dos, con su cifra.
    alertas = [a for a in (dashboard.get("alerts") or []) if a.get("severity") == "Alta"
               and "caída" not in str(a.get("title", "")).lower()][:2]
    for a in alertas:
        st.markdown(f'<div class="parte-vigilar"><b>⚠️ {html.escape(str(a.get("title", "")))}</b>'
                    f'<div>{html.escape(str(a.get("text", "")))}</div></div>', unsafe_allow_html=True)
    b1, b2, _ = st.columns([1.3, 1.1, 2])
    b1.button("🎯 Ver el plan completo", key="inicio_ir_atacar", type="primary", use_container_width=True,
              on_click=ir_a, args=(VISTA_ATACAR,))
    b2.button("📋 Ver el resumen", key="inicio_ir_resumen", use_container_width=True,
              on_click=ir_a, args=(VISTA_RESUMEN,))
    return True


def _sobre_el_archivo(wb, sheet, sheets, classification, seleccion, filtrado) -> None:
    """Qué se cargó y cómo se interpretó: plegado, para quien lo necesite."""
    total_records = sum(len(it.get("processed", [])) for it in sheets.values() if isinstance(it, dict))
    tipo = classification.get("label") if classification else None
    resumen = (f"📄 {html.escape(str(wb.get('filename', '—')))} · {len(sheets)} hoja{'s' if len(sheets) != 1 else ''}"
               f" · hoja activa «{html.escape(str(sheet))}»" + (f" · {html.escape(str(tipo))}" if tipo else ""))
    st.markdown(f'<div class="chart-reading" style="margin-top:14px">{resumen}</div>', unsafe_allow_html=True)
    with st.expander("Sobre el archivo: qué se cargó y cómo se leyó", expanded=filtrado):
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(kpi_card("Archivo", wb.get("filename", "—"), small_value=True), unsafe_allow_html=True)
        c2.markdown(kpi_card("Hojas con datos", f"{len(sheets):,}"), unsafe_allow_html=True)
        if filtrado:
            c3.markdown(kpi_card("Registros en la vista", f"{seleccion['visibles']:,}",
                                 delta=f"de {seleccion['total']:,} · {seleccion['porcentaje']:.0f}% de la hoja"),
                        unsafe_allow_html=True)
        else:
            activa = sheets.get(sheet) if isinstance(sheets.get(sheet), dict) else {}
            en_hoja = len(activa.get("processed", [])) if activa else None
            # El total suma TODAS las hojas; arriba se ve el de la hoja activa
            # (5.015 vs 5.032 parecían cifras que no cuadraban).
            c3.markdown(kpi_card("Registros totales", f"{total_records:,}",
                                 delta=(f"{en_hoja:,} en la hoja activa" if en_hoja is not None and len(sheets) > 1
                                        else None)), unsafe_allow_html=True)
        c4.markdown(kpi_card("Hoja activa", sheet, small_value=True), unsafe_allow_html=True)
        if classification:
            cap_labels = {"evolucion": "evolución", "comparacion_periodos": "comparación de periodos",
                          "ranking": "rankings", "distribucion": "distribuciones",
                          "relaciones": "relaciones entre métricas", "estadisticas": "estadísticas",
                          "grafico_distribucion": "gráficos de distribución", "geografia": "geografía",
                          "catalogo": "consulta de catálogo", "estados": "seguimiento de estados"}
            caps = ", ".join(cap_labels.get(x, str(x)) for x in classification.get("capabilities", [])[:6])
            st.caption(f"Tipo de datos detectado: **{classification.get('label', 'Datos generales')}** "
                       f"({(classification.get('confidence') or 0) * 100:.0f}% de confianza)"
                       + (f" · análisis disponibles: {caps}." if caps else ".")
                       + (f" {classification.get('reason')}" if classification.get("reason") else ""))


def render_home(wb: dict, sheet: str, mode_info: dict, dashboard: dict, seleccion: dict | None = None,
                df: pd.DataFrame | None = None, schema: dict | None = None) -> None:
    sheets = wb.get("sheets", {}) or {}
    classification = (mode_info or {}).get("classification", {}) or {}
    # Es la pestaña con la que abre el panel. Antes mostraba siempre el
    # archivo completo: al aplicar un filtro, lo primero que se veía no
    # cambiaba y parecía que el filtro no hacía nada.
    filtrado = bool(seleccion and seleccion.get("filtrado"))

    # El título de la tabla («RANKING DE LOS JEFES») dice qué información es.
    item = sheets.get(sheet) if isinstance(sheets.get(sheet), dict) else {}
    titulo = (item.get("profile") or {}).get("titulo")
    if titulo:
        st.markdown(f'<div class="context-bar"><div class="context-main"><span class="decision-dot"></span>'
                    f'<b>Estás viendo:</b> {html.escape(str(titulo))}</div></div>', unsafe_allow_html=True)

    # ── La selección actual: qué filtros hay ───────────────────────────────
    if filtrado:
        frases = [html.escape(str(f)) for f in seleccion.get("frases", [])]
        texto = (f"<b>🎯 Vista filtrada · {seleccion['visibles']:,} de {seleccion['total']:,} registros:</b> "
                 f"{' · '.join(frases)}" if frases else "<b>Vista acotada</b> por el periodo o la búsqueda.")
        st.markdown(decision_strip(texto, dot=True), unsafe_allow_html=True)

    # ── El parte del día: cómo vamos y qué hacer ───────────────────────────
    if not _parte_del_dia(df, schema, dashboard or {}):
        # Sin fechas o sin una métrica que se sume no hay «mes contra mes»:
        # queda el veredicto general, si lo hay.
        if isinstance(dashboard, dict) and dashboard.get("executive"):
            executive_headline(dashboard)

    _sobre_el_archivo(wb, sheet, sheets, classification, seleccion, filtrado)
    _notas_de_lectura(wb.get("avisos") or [])
    render_imagenes(wb)
    _contenido_del_archivo(sheets)
