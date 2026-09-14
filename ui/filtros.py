"""Filtros del menú lateral por cualquier columna del archivo.

Antes el menú solo ofrecía las columnas que el esquema clasificó como
categoría. Las métricas, los códigos, las fechas secundarias y las columnas
de texto con muchos valores —justo donde suele estar el nombre del punto de
venta— no se podían filtrar desde ningún lado.

Ahora el menú tiene dos partes:

- **Segmentación**: hasta cuatro listas visibles con las columnas de negocio
  más útiles, como antes, para no alargar el menú en el caso común.
- **Cualquier columna**: un selector con todas las demás columnas del
  archivo. Al elegir una aparece el filtro que le corresponde según su tipo:
  lista de valores, rango numérico, rango de fechas o texto contenido.

Las reglas se escriben en ``st.session_state.filters`` y las aplica
``core/filter_engine.apply_filters``, el mismo motor que usan todas las
vistas.
"""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from core.filter_engine import LIMITE_OPCIONES, cascading_options, columnas_filtrables

ICONOS = {"opciones": "🏷️", "numero": "🔢", "fecha": "📅", "texto": "🔤"}

# Tipos de columna que merecen estar a la vista sin tener que buscarlos.
TIPOS_PREFERIDOS = {"region", "department", "state", "zone", "city", "country", "segment", "category",
                    "product", "brand", "status", "type", "customer", "employee", "channel"}


def metrica_recien_elegida(anteriores, elegidas, metricas):
    """La última métrica que se agregó al selector en este clic, si hubo una.

    Agregar "Altas Eje" como filtro es decir "quiero ver Altas Eje": antes el
    análisis seguía en la métrica de siempre y el filtro parecía no servir.
    """
    anteriores = set(anteriores or [])
    nuevas = [c for c in (elegidas or []) if c not in anteriores and c in set(metricas or [])]
    return nuevas[-1] if nuevas else None


def _rotulo(texto: str) -> None:
    st.markdown(
        f'<p style="font-size:13px;font-weight:600;margin:10px 0 2px;color:var(--text)">{html.escape(texto)}</p>',
        unsafe_allow_html=True,
    )


def _render_opciones(columna, opciones: list, clave: str, etiqueta: str) -> None:
    filtros = st.session_state.filters
    validas = {str(v) for v in opciones}
    # Un filtro puesto desde otra parte del panel ("Ver análisis" en una
    # alerta) llega sin valor en el widget. Antes la lista arrancaba vacía y
    # en el mismo redibujo borraba el filtro recién puesto: el botón parecía
    # no hacer nada. Se siembra la lista con el valor del filtro.
    regla = filtros.get(columna)
    if clave not in st.session_state and isinstance(regla, dict) and regla.get("op") == "in":
        st.session_state[clave] = [v for v in regla.get("value", []) if str(v) in validas]
    actual = st.session_state.get(clave, [])
    if not isinstance(actual, list):
        actual = list(actual) if actual else []
    limpio = [v for v in actual if str(v) in validas]
    if limpio != actual:
        st.session_state[clave] = limpio
    seleccion = st.multiselect(etiqueta, opciones, key=clave, placeholder="Selecciona opciones…")
    if seleccion:
        filtros[columna] = {"op": "in", "value": list(seleccion)}
    else:
        filtros.pop(columna, None)


def _render_numero(columna, df_completo: pd.DataFrame, clave: str, etiqueta: str) -> None:
    filtros = st.session_state.filters
    serie = pd.to_numeric(df_completo[columna], errors="coerce")
    validos = serie.dropna()
    if validos.empty:
        return
    entero = bool(((validos % 1) == 0).all())
    if entero:
        minimo, maximo, paso, formato, tolerancia = int(validos.min()), int(validos.max()), 1, "%d", 0.5
    else:
        minimo, maximo, paso, formato, tolerancia = float(validos.min()), float(validos.max()), None, "%.2f", 0.005
    _rotulo(etiqueta)
    izquierda, derecha = st.columns(2)
    desde = izquierda.number_input("Desde", value=minimo, step=paso, format=formato, key=clave + "_desde")
    hasta = derecha.number_input("Hasta", value=maximo, step=paso, format=formato, key=clave + "_hasta")
    incluir = True
    if bool(serie.isna().any()):
        incluir = st.checkbox("Incluir filas vacías", value=True, key=clave + "_vacios")
    if desde > hasta:
        st.caption("⚠️ «Desde» es mayor que «Hasta»: no quedará ninguna fila.")
    # Con decimales el campo muestra el valor redondeado. Si se comparara al
    # pie de la letra, abrir el filtro sin tocarlo ya contaría como un
    # cambio y podría dejar afuera la fila del extremo.
    cambio_desde = abs(float(desde) - float(minimo)) >= tolerancia
    cambio_hasta = abs(float(hasta) - float(maximo)) >= tolerancia
    if cambio_desde or cambio_hasta or not incluir:
        filtros[columna] = {
            "op": "between",
            "value": [desde if cambio_desde else minimo, hasta if cambio_hasta else maximo],
            "incluir_vacios": incluir,
        }
    else:
        filtros.pop(columna, None)


def _render_fecha(columna, df_completo: pd.DataFrame, clave: str, etiqueta: str) -> None:
    filtros = st.session_state.filters
    fechas = pd.to_datetime(df_completo[columna], errors="coerce")
    validas = fechas.dropna()
    if validas.empty:
        return
    inicio, fin = validas.min().date(), validas.max().date()
    rango = st.date_input(etiqueta, value=(inicio, fin), min_value=inicio, max_value=fin, key=clave + "_rango")
    incluir = True
    if bool(fechas.isna().any()):
        incluir = st.checkbox("Incluir filas sin fecha", value=True, key=clave + "_vacios")
    if not (isinstance(rango, (tuple, list)) and len(rango) == 2):
        return  # a mitad de elegir el rango: se conserva la regla anterior
    if tuple(rango) != (inicio, fin) or not incluir:
        # Hasta el final del día elegido: comparar contra la medianoche dejaba
        # fuera todo lo registrado ese mismo día después de las 00:00.
        final = pd.Timestamp(rango[1]) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        filtros[columna] = {"op": "date_between", "value": [pd.Timestamp(rango[0]), final],
                            "incluir_vacios": incluir}
    else:
        filtros.pop(columna, None)


def _render_texto(columna, clave: str, etiqueta: str, distintos: int) -> None:
    filtros = st.session_state.filters
    regla = filtros.get(columna)
    if clave + "_texto" not in st.session_state and isinstance(regla, dict) and regla.get("op") == "contains":
        st.session_state[clave + "_texto"] = str(regla.get("value", ""))
    texto = st.text_input(
        etiqueta, key=clave + "_texto", placeholder="Escribe parte del valor…",
        help=f"Tiene {distintos:,} valores distintos, demasiados para una lista: se filtra por lo que contenga.")
    if texto.strip():
        filtros[columna] = {"op": "contains", "value": texto.strip()}
    else:
        filtros.pop(columna, None)


def render_filtros_por_columna(df: pd.DataFrame, schema: dict, sheet: str,
                               full_name_col=None, filter_source: pd.DataFrame | None = None) -> list:
    """Dibuja la segmentación visible y el selector de cualquier columna.

    ``df`` es la hoja completa: de ahí salen los rangos, que deben ser estables
    aunque cambien los demás filtros. ``filter_source`` es la hoja ya acotada
    por el periodo, de donde salen las opciones en cascada. Devuelve las
    columnas de la segmentación visible.
    """
    filtros = st.session_state.filters
    filter_source = df if filter_source is None else filter_source
    columnas = columnas_filtrables(df, schema)
    por_nombre = {c["columna"]: c for c in columnas}
    fechas = schema.get("dates") or []
    # El periodo y la persona ya tienen su propio filtro arriba en el menú.
    # Ofrecerlos de nuevo aquí crearía dos controles escribiendo la misma regla.
    excluir = {fechas[0] if fechas else None, full_name_col}

    semantica = {x.get("column"): x.get("semantic_type") for x in schema.get("semantic", {}).get("columns", [])}
    listas = [c["columna"] for c in columnas if c["tipo"] == "opciones" and c["columna"] not in excluir]
    categoricas = [c for c in schema.get("categorical", []) if c in listas]
    preferidas = [c for c in categoricas if semantica.get(c) in TIPOS_PREFERIDOS]
    visibles = (preferidas + [c for c in categoricas if c not in preferidas])[:4]

    disponibles = [c for c in columnas if c["columna"] not in excluir and c["columna"] not in visibles]
    etiquetas = {c["columna"]: f"{ICONOS[c['tipo']]} {c['columna']}" for c in disponibles}
    clave_selector = f"filter_{sheet}__columnas"
    # Una columna con filtro activo queda elegida en el selector, para que el
    # filtro nunca quede aplicado sin estar a la vista.
    elegidas = [c for c in st.session_state.get(clave_selector, []) if c in etiquetas]
    for columna in etiquetas:
        if columna in filtros and columna not in elegidas:
            elegidas.append(columna)
    st.session_state[clave_selector] = elegidas

    con_lista = visibles + [c for c in elegidas if por_nombre[c]["tipo"] == "opciones"]
    activas = {c: r for c, r in filtros.items()
               if not str(c).startswith("__") and isinstance(r, dict) and c in df.columns}
    opciones = cascading_options(filter_source, con_lista, activas, limit=LIMITE_OPCIONES) if con_lista else {}

    if visibles:
        st.markdown('<p class="sidebar-section-label">🎯 Segmentación</p>', unsafe_allow_html=True)
        for columna in visibles:
            _render_opciones(columna, opciones.get(columna, []), f"filter_{sheet}_{columna}", str(columna))

    if disponibles:
        st.markdown('<p class="sidebar-section-label">🧰 Más columnas</p>', unsafe_allow_html=True)
        elegidas = st.multiselect(
            "Agregar filtro",
            list(etiquetas), format_func=lambda c: etiquetas[c], key=clave_selector,
            placeholder=f"Busca entre {len(disponibles)} columnas…", label_visibility="collapsed",
            help="Todas las columnas del archivo. Al elegir una aparece el filtro que le corresponde: "
                 "lista de valores, rango de números, rango de fechas o texto contenido. Si eliges una "
                 "columna numérica, el análisis pasa a esa métrica.")
        clave_previas = clave_selector + "__previas"
        nueva = metrica_recien_elegida(st.session_state.get(clave_previas), elegidas, schema.get("metrics"))
        if nueva is not None:
            st.session_state[f"metrica_{sheet}"] = nueva
        st.session_state[clave_previas] = list(elegidas)
        for columna in elegidas:
            info = por_nombre[columna]
            clave = f"filter_{sheet}_{columna}"
            etiqueta = etiquetas[columna]
            if info["tipo"] == "opciones":
                _render_opciones(columna, opciones.get(columna, []), clave, etiqueta)
            elif info["tipo"] == "numero":
                _render_numero(columna, df, clave, etiqueta)
            elif info["tipo"] == "fecha":
                _render_fecha(columna, df, clave, etiqueta)
            else:
                _render_texto(columna, clave, etiqueta, info["distintos"])
        # Quitar una columna del selector quita también su filtro.
        for columna in etiquetas:
            if columna not in elegidas:
                filtros.pop(columna, None)
    return visibles
