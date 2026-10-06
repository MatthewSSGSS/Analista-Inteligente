"""🏢 Estructura: cómo va cada jefe, supervisor, agente y punto de venta.

Es la vista de la Estructura comercial (`core/estructura.py`): se suben
varios archivos —estructura, puntos, metas, ventas— en «🧰 Herramientas
avanzadas», se cruzan solos y la tabla cruzada pasa a ser el archivo activo
del Análisis Completo. Esta vista recibe esa tabla YA filtrada por la barra
lateral (el único motor de filtros) y la recorre por niveles:

- se elige un nivel y a alguien (buscando por nombre, código o cédula);
- se ve su cadena de mando hacia arriba —todas, si depende de dos jefes—,
  cómo va contra la meta y contra lo que debería llevar hoy, y lo que tiene
  debajo con semáforo; un clic en una fila baja a ese nivel.

La selección vive fuera de los widgets (`estructura_seleccion`) porque la
barra de vistas solo dibuja la vista activa y Streamlit borra el estado de
los widgets que no se dibujaron (ver ui/layouts/tabs.py).
"""
from __future__ import annotations

import html
import traceback

import pandas as pd
import streamlit as st

from core import estructura as E
from core.loader import load_workbook
from core.territorio import cifra
from ui.components.cards import kpi_card
from ui.components.section import decision_strip, section_header
from ui.layouts.tabs import VISTA_ESTRUCTURA, ir_a

_CLAVE_RES = "estructura_resultado"
_CLAVE_LIBROS = "estructura_libros"
_CLAVE_AJUSTES = "estructura_ajustes"
_CLAVE_ERROR = "estructura_error"
_CLAVE_SEL = "estructura_seleccion"      # {"nivel": ..., "nodo": ... | None}
_W_NIVEL = "estructura_w_nivel"
_W_NODO = "estructura_w_nodo"
_TODOS = "— Todos —"


# ── Barra lateral: subir y cruzar ─────────────────────────────────────────
def _aplicar(libros: list[dict], ajustes: dict) -> None:
    """Cruza y deja el resultado como archivo activo del panel."""
    res = E.cruzar(libros, ajustes)
    st.session_state[_CLAVE_LIBROS] = libros
    st.session_state[_CLAVE_AJUSTES] = ajustes
    st.session_state[_CLAVE_RES] = res
    st.session_state[_CLAVE_ERROR] = None
    st.session_state.workbook = E.libro_unificado(res)
    st.session_state.filters = {}
    nivel = "jefe" if "jefe" in res["niveles"] else res["niveles"][0]
    _seleccionar(nivel, None)
    ir_a(VISTA_ESTRUCTURA)


def render_cargador_estructura() -> None:
    """Bloque de «🧰 Herramientas avanzadas»: varios archivos → un cruce."""
    st.markdown('<p class="sidebar-section-label">🏢 Estructura comercial</p>', unsafe_allow_html=True)
    st.caption("Sube los archivos del equipo (estructura, puntos de venta, metas, ventas…): se cruzan solos "
               "por código, cédula y nombre, y el resultado se abre en el panel.")
    subidas = st.file_uploader(
        "Archivos a cruzar", type=["xlsx", "xls", "xlsb", "xlsm", "csv"], accept_multiple_files=True,
        key="estructura_uploads",
        help="Pueden ser 2, 4 o los que sean, cada uno con sus propias columnas.",
    )
    if subidas and st.button("Cruzar archivos", use_container_width=True, key="estructura_cruzar_btn"):
        with st.spinner("Leyendo los archivos y cruzándolos…"):
            try:
                _aplicar([load_workbook(f) for f in subidas], {})
            except Exception as exc:
                st.session_state[_CLAVE_ERROR] = (str(exc), traceback.format_exc())
            else:
                st.rerun()
    res = st.session_state.get(_CLAVE_RES)
    if res and (st.session_state.get("workbook") or {}).get("estructura"):
        st.success(f"Cruce abierto · {len(res['archivos'])} archivos · ver «{VISTA_ESTRUCTURA}»")
    error = st.session_state.get(_CLAVE_ERROR)
    if error:
        st.error(f"No se pudieron cruzar los archivos: {error[0]}")
        with st.expander("Detalle técnico (cópialo si necesitas ayuda)"):
            st.code(error[1], language=None)


# ── Selección (fuera de los widgets) ──────────────────────────────────────
def _seleccionar(nivel: str, nodo) -> None:
    """Cambia la selección. Pensada para callbacks: escribe también las
    claves de los widgets, cosa que Streamlit solo permite antes de dibujarlos."""
    st.session_state[_CLAVE_SEL] = {"nivel": nivel, "nodo": nodo}
    st.session_state[_W_NIVEL] = nivel
    st.session_state[f"{_W_NODO}_{nivel}"] = nodo if nodo is not None else _TODOS


def _al_elegir_fila(clave_tabla: str, nivel: str, nodos: list) -> None:
    filas = (st.session_state.get(clave_tabla) or {}).get("selection", {}).get("rows", [])
    if filas and filas[0] < len(nodos):
        _seleccionar(nivel, nodos[filas[0]])


# ── Formato ───────────────────────────────────────────────────────────────
def _nombre(nivel: str) -> str:
    """«jefe», «supervisor»… pero «PDV» se queda en mayúsculas."""
    return E.ETIQUETAS[nivel] if nivel == "pdv" else E.ETIQUETAS[nivel].lower()


def _pct(v) -> str:
    return "—" if v is None or pd.isna(v) else f"{v * 100:.0f} %"


def _num(v) -> str:
    return "—" if v is None or pd.isna(v) else cifra(float(v))


def _tono(fila: dict, c) -> str:
    cu = fila.get("Cumplimiento")
    if cu is None or pd.isna(cu):
        return "neutral"
    ref = c["esperado"] if c else 1.0
    return "positive" if cu >= ref else "negative"


_CSS = """
<style>
.estr-rutas{display:flex;flex-direction:column;gap:6px;margin:2px 0 14px}
.estr-ruta{display:flex;flex-wrap:wrap;align-items:center;gap:6px;font-size:13px;color:var(--muted)}
.estr-paso{background:var(--panel-2);border:1px solid var(--line);border-radius:999px;padding:3px 10px;color:var(--text)}
.estr-paso small{color:var(--muted);margin-right:4px;font-size:10.5px;text-transform:uppercase;letter-spacing:.06em}
.estr-paso.actual{border-color:var(--accent,var(--red));font-weight:750}
.estr-sep{opacity:.5}
.estr-datos{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 12px;font-size:12.5px}
.estr-datos span{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:4px 10px}
.estr-datos b{color:var(--muted);font-weight:700;margin-right:4px}
</style>
"""


# ── La vista ──────────────────────────────────────────────────────────────
def render_estructura(df: pd.DataFrame, res: dict | None) -> None:
    """`df` es la tabla cruzada con los filtros de la barra lateral ya aplicados."""
    if not res:
        st.info("Sube los archivos en «🧰 Herramientas avanzadas › 🏢 Estructura comercial» para empezar.")
        return
    st.markdown(_CSS, unsafe_allow_html=True)
    niveles = [n for n in res["niveles"] if E.columna(n) in df.columns]
    if not niveles or df.empty:
        st.info("Con los filtros actuales no queda nadie de la estructura a la vista.")
        return

    medidas = [m for m in (res.get("medidas") or []) if m in df.columns]
    principal = E.medida_principal(res)
    c = E.corte(df, res, principal)
    subtitulo = f"{len(res['archivos'])} archivos cruzados"
    if c:
        subtitulo += f" · datos al {c['fecha']:%d/%m/%Y} (día {c['dia']} de {c['dias_mes']})"
    st.markdown(section_header("Estructura comercial", subtitle=subtitulo,
                               badge=" › ".join(E.ETIQUETAS[n] for n in niveles)), unsafe_allow_html=True)

    _avisos(res)
    _lo_que_entendi(res)
    if c and c["varios_meses"]:
        st.caption(f"Los archivos traen varios meses: el cumplimiento se mide sobre {c['fecha']:%m/%Y}, "
                   "el mes de los datos más recientes (la meta es mensual).")

    medida = principal
    if len(medidas) > 1:
        medida = st.selectbox("Medir por", medidas, index=medidas.index(principal) if principal in medidas else 0,
                              key="estructura_medida",
                              help="La meta se compara contra esta medida.")
    if not medidas:
        st.caption("Los archivos no traen una columna de resultados (ventas, avance…): se muestran solo metas.")

    # Selección guardada → valores iniciales de los widgets.
    sel = st.session_state.get(_CLAVE_SEL) or {}
    nivel_def = sel.get("nivel") if sel.get("nivel") in niveles else ("jefe" if "jefe" in niveles else niveles[0])
    if st.session_state.get(_W_NIVEL) not in niveles:
        st.session_state[_W_NIVEL] = nivel_def
    col_n, col_b = st.columns([1.3, 2])
    with col_n:
        nivel = st.radio("Ver", niveles, key=_W_NIVEL, horizontal=True, format_func=lambda n: E.ETIQUETAS[n])
    nodos = E.nodos_de(df, nivel)
    codigos = res.get("codigos", {}).get(nivel, {})
    clave_nodo = f"{_W_NODO}_{nivel}"
    opciones = [_TODOS] + nodos
    if st.session_state.get(clave_nodo) not in opciones:
        guardado = sel.get("nodo") if sel.get("nivel") == nivel else None
        st.session_state[clave_nodo] = guardado if guardado in nodos else _TODOS
    with col_b:
        nodo = st.selectbox(
            f"Buscar {_nombre(nivel)}", opciones, key=clave_nodo,
            format_func=lambda n: n if n == _TODOS or not codigos.get(n) or codigos[n] == n else f"{n} · {codigos[n]}",
            help="Escribe parte del nombre, el código o la cédula.",
        )
    nodo = None if nodo == _TODOS else nodo
    st.session_state[_CLAVE_SEL] = {"nivel": nivel, "nodo": nodo}

    if nodo is None:
        _panorama(df, res, nivel, medida, c)
    else:
        _ficha(df, res, nivel, nodo, medida)


def _avisos(res: dict) -> None:
    avisos = res.get("avisos") or []
    if not avisos:
        st.markdown(decision_strip("✅ Todo cruzó: cada punto y cada persona quedó con su cadena de mando.",
                                   tone="positive"), unsafe_allow_html=True)
        return
    graves = sum(1 for a in avisos if a["tipo"] == "error")
    titulo = f"⚠️ Lo que no cruzó o no cuadra ({len(avisos)})" if graves or any(
        a["tipo"] == "aviso" for a in avisos) else f"ℹ️ Notas del cruce ({len(avisos)})"
    with st.expander(titulo, expanded=bool(graves)):
        for a in avisos:
            icono = {"error": "🔴", "aviso": "🟡"}.get(a["tipo"], "ℹ️")
            st.markdown(f"{icono} {html.escape(a['texto'])}")
            if a.get("ejemplos"):
                st.caption("Ej.: " + " · ".join(html.escape(str(e)) for e in a["ejemplos"]))


def _lo_que_entendi(res: dict) -> None:
    """Qué es cada columna de cada archivo, con la opción de corregirlo."""
    with st.expander("🔍 Lo que entendí de cada archivo", expanded=False):
        st.caption("Si alguna columna quedó mal, cámbiala y pulsa «Volver a cruzar». Lo que diga «(supuesto)» se "
                   "dedujo sin que el encabezado lo dijera.")
        etiquetas = {r: E.etiqueta_rol(r) for r in E.ROLES}
        por_etiqueta = {v: k for k, v in etiquetas.items()}
        cambios = {}
        for i, m in enumerate(res.get("mapeo") or []):
            st.markdown(f"**{html.escape(str(m['archivo']))}** · hoja {html.escape(str(m['hoja']))} · "
                        f"{m['filas']:,} filas — se usa como: {html.escape(m['uso'])}")
            tabla = pd.DataFrame([{"Columna": str(x["columna"]),
                                   "Es": etiquetas.get(x["rol"], x["rol"]),
                                   "Cómo se supo": "supuesto" if x["supuesto"] else "por el encabezado o los datos"}
                                  for x in m["columnas"]])
            editada = st.data_editor(
                tabla, hide_index=True, use_container_width=True, key=f"estructura_mapeo_{i}",
                disabled=["Columna", "Cómo se supo"],
                column_config={"Es": st.column_config.SelectboxColumn("Es", options=list(etiquetas.values()),
                                                                       required=True)},
            )
            for (_, antes), (_, despues) in zip(tabla.iterrows(), editada.iterrows()):
                if antes["Es"] != despues["Es"]:
                    cambios[(m["archivo"], str(m["hoja"]), antes["Columna"])] = por_etiqueta[despues["Es"]]
        libros = st.session_state.get(_CLAVE_LIBROS)
        if st.button("🔁 Volver a cruzar", disabled=not cambios or not libros, key="estructura_recruzar"):
            ajustes = dict(st.session_state.get(_CLAVE_AJUSTES) or {})
            ajustes.update(cambios)
            try:
                _aplicar(libros, ajustes)
            except Exception as exc:
                st.error(f"No se pudo cruzar con esos cambios: {exc}")
            else:
                st.rerun()


def _tabla_resumen(resumen: pd.DataFrame, nivel: str, c) -> tuple[pd.DataFrame, dict]:
    col = E.columna(nivel)
    t = pd.DataFrame({col: resumen[col], "Estado": resumen["Estado"]})
    t["Real"] = resumen["Real"]
    hay_meta = resumen["Meta"].notna().any()
    if hay_meta:
        t["Meta"] = resumen["Meta"]
        t["Cumplimiento"] = resumen["Cumplimiento"] * 100
        if c:
            t["Debería llevar"] = resumen["Esperado hoy"]
            t["Proyección al cierre"] = resumen["Proyección cierre"]
            t["Cierre proyectado"] = resumen["Cumplimiento proyectado"] * 100
        t["Faltante"] = resumen["Faltante"]
        if c and "Faltante por día" in resumen:
            t["Por día"] = resumen["Faltante por día"]
    if resumen["Presupuesto"].notna().any():
        t["Presupuesto"] = resumen["Presupuesto"]
    if (resumen["Compartido"] > 0).any():
        t["Compartido"] = resumen["Compartido"]
    de = int(resumen["De"].max()) if len(resumen) else 0
    t[f"Puesto (de {de})"] = resumen["Puesto"]
    numeros = {k: st.column_config.NumberColumn(k, format="localized") for k in
               ("Real", "Meta", "Debería llevar", "Proyección al cierre", "Faltante", "Por día", "Presupuesto",
                "Compartido")}
    config = dict(numeros)
    config[f"Puesto (de {de})"] = st.column_config.NumberColumn(
        f"Puesto (de {de})", format="%d", help=f"Entre los {de} de este grupo, no solo los que se ven arriba.")
    if "Cumplimiento" in t:
        config["Cumplimiento"] = st.column_config.ProgressColumn(
            "Cumplimiento", format="%.0f%%", min_value=0, max_value=max(100.0, float(t["Cumplimiento"].max() or 0)),
            help="Real ÷ meta del mes.")
    if "Cierre proyectado" in t:
        config["Cierre proyectado"] = st.column_config.NumberColumn(
            "Cierre proyectado", format="%.0f%%", help="Cumplimiento con que cerraría el mes a este ritmo.")
    if "Debería llevar" in t:
        config["Debería llevar"] = st.column_config.NumberColumn(
            "Debería llevar", format="localized",
            help=f"Meta × día {c['dia']} de {c['dias_mes']}: lo que debería llevar hoy para cumplir.")
    if "Compartido" in t:
        config["Compartido"] = st.column_config.NumberColumn(
            "Compartido", format="localized",
            help="Parte del real que viene de alguien que también está con otro superior: cuenta completa para ambos.")
    return t, config


def _tabla_navegable(resumen: pd.DataFrame, nivel: str, c, clave: str, titulo: str) -> None:
    if resumen.empty:
        st.caption("No hay nadie en este nivel con los filtros actuales.")
        return
    orden = resumen.sort_values(["Cumplimiento", "Real"], ascending=[True, True], na_position="last")
    tabla, config = _tabla_resumen(orden.reset_index(drop=True), nivel, c)
    nodos = list(tabla[E.columna(nivel)])
    st.markdown(section_header(titulo, compact=True,
                               subtitle="Ordenado del que va peor al que va mejor · clic en una fila para abrirla"),
                unsafe_allow_html=True)
    st.dataframe(tabla, use_container_width=True, hide_index=True, column_config=config, key=clave,
                 on_select=lambda: _al_elegir_fila(clave, nivel, nodos), selection_mode="single-row")
    st.download_button("⬇️ Descargar esta tabla (CSV)", tabla.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"estructura_{E.columna(nivel).lower()}.csv", mime="text/csv",
                       key=f"{clave}_csv")


def _panorama(df, res, nivel, medida, c) -> None:
    """Sin nadie elegido: todos los del nivel."""
    resumen = E.resumen_por_nivel(df, res, nivel, medida, c)
    if resumen.empty:
        st.caption("No hay nadie en este nivel con los filtros actuales.")
        return
    real = E.total_real(df, res, medida, c)
    meta = E.meta_total(df, res)
    filas = resumen["Estado"].value_counts()
    k = st.columns(4)
    k[0].markdown(kpi_card(f"{E.PLURALES[nivel].capitalize()}", f"{len(resumen):,}"), unsafe_allow_html=True)
    k[1].markdown(kpi_card(f"Real ({medida})" if medida else "Real", _num(real)), unsafe_allow_html=True)
    if meta:
        cu = real / meta if real is not None and meta else None
        tono = "neutral" if cu is None else ("positive" if cu >= (c["esperado"] if c else 1) else "negative")
        k[2].markdown(kpi_card("Cumplimiento", _pct(cu), delta=f"meta {_num(meta)}"
                               + (f" · debería ir en {_pct(c['esperado'])}" if c else ""), tone=tono),
                      unsafe_allow_html=True)
    else:
        k[2].markdown(kpi_card("Meta", "—", delta="sin meta para este nivel"), unsafe_allow_html=True)
    rojos = int(sum(v for e, v in filas.items() if e.startswith("🔴")))
    k[3].markdown(kpi_card("Atrasados", f"{rojos} de {len(resumen)}", tone="negative" if rojos else "positive"),
                  unsafe_allow_html=True)
    _tabla_navegable(resumen, nivel, c, f"estructura_tabla_{nivel}", f"Cómo va cada {_nombre(nivel)}")


def _rutas_html(f: dict) -> str:
    lineas = []
    for camino in f["rutas"] or [[]]:
        pasos = [f'<span class="estr-paso"><small>{E.ETIQUETAS[n]}</small>{html.escape(str(v))}</span>'
                 for n, v in camino]
        pasos.append(f'<span class="estr-paso actual"><small>{E.ETIQUETAS[f["nivel"]]}</small>'
                     f'{html.escape(str(f["nodo"]))}</span>')
        lineas.append('<div class="estr-ruta">' + '<span class="estr-sep">›</span>'.join(pasos) + "</div>")
    return '<div class="estr-rutas">' + "".join(lineas) + "</div>"


def _ficha(df, res, nivel, nodo, medida) -> None:
    f = E.ficha(df, res, nivel, nodo, medida)
    fila, c = f["fila"], f["corte"]
    st.markdown(_rutas_html(f), unsafe_allow_html=True)
    if len(f["rutas"]) > 1:
        st.caption(f"Depende de {len(f['rutas'])} cadenas de mando a la vez: sus resultados cuentan completos para cada una.")

    # Subir: un botón por cada superior directo.
    directos = []
    for camino in f["rutas"]:
        if camino and camino[-1] not in directos:
            directos.append(camino[-1])
    if directos:
        botones = st.columns(min(len(directos), 4) + 1)
        for i, (n_p, p) in enumerate(directos[:4]):
            botones[i].button(f"⬆️ {E.ETIQUETAS[n_p]}: {p}", key=f"estructura_subir_{n_p}_{p}",
                              on_click=_seleccionar, args=(n_p, p), use_container_width=True)
        botones[-1].button("↩️ Ver todos", key="estructura_todos", on_click=_seleccionar, args=(nivel, None),
                           use_container_width=True)

    if f["datos"] or f["codigo"]:
        datos = ({"Código": f["codigo"]} if f["codigo"] and f["codigo"] != nodo else {}) | f["datos"]
        st.markdown('<div class="estr-datos">' + "".join(
            f"<span><b>{html.escape(str(k))}</b>{html.escape(str(v))}</span>" for k, v in datos.items()) + "</div>",
            unsafe_allow_html=True)

    if not fila:
        st.caption("No tiene resultados con los filtros actuales.")
        return
    tono = _tono(fila, c)
    puesto = fila.get("Puesto")
    grupo = f"{int(puesto)}.º de {int(fila['De'])} {E.PLURALES[nivel]}" if pd.notna(puesto) else None
    k = st.columns(5)
    k[0].markdown(kpi_card(f"Real ({medida})" if medida else "Real", _num(fila["Real"]), delta=grupo),
                  unsafe_allow_html=True)
    k[1].markdown(kpi_card("Meta", _num(fila["Meta"]), delta=fila.get("Origen meta") or None), unsafe_allow_html=True)
    k[2].markdown(kpi_card("Cumplimiento", _pct(fila["Cumplimiento"]),
                           delta=f"debería ir en {_pct(c['esperado'])}" if c else None, tone=tono),
                  unsafe_allow_html=True)
    if c:
        k[3].markdown(kpi_card("Cierre proyectado", _pct(fila.get("Cumplimiento proyectado")),
                               delta=f"{_num(fila.get('Proyección cierre'))} a este ritmo", tone=tono),
                      unsafe_allow_html=True)
    else:
        k[3].markdown(kpi_card("Faltante", _num(fila.get("Faltante"))), unsafe_allow_html=True)
    if pd.notna(fila.get("Presupuesto")):
        costo = (f"{_num(fila['Presupuesto'] / fila['Real'])} por unidad lograda"
                 if fila["Real"] and pd.notna(fila["Real"]) else None)
        k[4].markdown(kpi_card("Presupuesto", _num(fila["Presupuesto"]), delta=costo), unsafe_allow_html=True)
    else:
        k[4].markdown(kpi_card("Faltante", _num(fila.get("Faltante")),
                               delta=f"{_num(fila.get('Faltante por día'))} por día" if c and pd.notna(
                                   fila.get("Faltante por día")) else None), unsafe_allow_html=True)

    st.markdown(decision_strip(_lectura(fila, c, nivel), tone=tono if tono != "neutral" else "neutral"),
                unsafe_allow_html=True)
    if f["descuadre"]:
        d = f["descuadre"]
        hijos = E.PLURALES.get(f["hijo"] or "", "")
        st.warning(f"Su meta declarada ({_num(d['declarada'])}) no es igual a la suma de la de sus {hijos} "
                   f"({_num(d['suma'])}): diferencia de {_num(d['declarada'] - d['suma'])}.")
    if fila.get("Compartido", 0) and fila["Compartido"] > 0:
        st.caption(f"De su real, {_num(fila['Compartido'])} viene de gente que también está con otro superior.")

    if f["hijo"]:
        _tabla_navegable(f["debajo"], f["hijo"], c, f"estructura_tabla_{nivel}_{nodo}_{f['hijo']}",
                         f"Sus {E.PLURALES[f['hijo']]}")
    else:
        _registros_pdv(df, res, nivel, nodo, medida)


def _lectura(fila: dict, c, nivel: str) -> str:
    """Una frase con el veredicto, la cifra y qué hace falta."""
    cu, meta = fila.get("Cumplimiento"), fila.get("Meta")
    if cu is None or pd.isna(cu):
        return f"Sin meta para este {_nombre(nivel)}: se muestra solo su resultado."
    if not c:
        if cu >= 1:
            return f"Cumplió: lleva {_pct(cu)} de la meta."
        return f"Lleva {_pct(cu)} de la meta; le faltan {_num(fila['Faltante'])}."
    texto = (f"Lleva {_pct(cu)} de la meta al día {c['dia']} de {c['dias_mes']} (debería ir en "
             f"{_pct(c['esperado'])}). A este ritmo cerraría en {_pct(fila.get('Cumplimiento proyectado'))}.")
    falta, por_dia = fila.get("Faltante"), fila.get("Faltante por día")
    if falta and falta > 0 and por_dia and pd.notna(por_dia):
        texto += f" Para cumplir necesita {_num(por_dia)} por día los {c['dias_mes'] - c['dia']} días que quedan."
    elif falta == 0 and meta:
        texto += " Ya cumplió la meta del mes."
    return texto


def _registros_pdv(df, res, nivel, nodo, medida) -> None:
    """Un PDV no tiene a nadie debajo: se muestran sus registros."""
    col = E.columna(nivel)
    suyas = df[df[col] == nodo]
    fecha = res.get("fecha")
    visibles = [x for x in ([fecha] if fecha else []) + (res.get("medidas") or []) if x in suyas.columns]
    if not visibles or suyas.empty:
        return
    registros = suyas[visibles]
    if fecha:
        registros = registros[registros[fecha].notna()].sort_values(fecha, ascending=False)
    if registros.empty:
        st.caption("Este punto no tiene registros de resultados en los archivos.")
        return
    st.markdown(section_header("Sus registros", compact=True), unsafe_allow_html=True)
    st.dataframe(registros, use_container_width=True, hide_index=True,
                 column_config={m: st.column_config.NumberColumn(m, format="localized")
                                for m in res.get("medidas") or [] if m in registros})
