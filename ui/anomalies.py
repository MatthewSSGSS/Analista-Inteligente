"""Anomalías y lectura estadística (Finanzas) del modo Analista.

`render_anomalies` recibe las anomalías DETECTADAS (`dashboard["anomalies"]`,
de core/anomalies.detect) y los datos para dar contexto a cada caso. Antes
app.py le pasaba los datos visibles completos y la vista decía «684 posibles
anomalías» (todos los registros) con la tabla entera debajo.

Ambas se dibujan en JavaScript (ui/web/anomalias.*, ui/web/finanzas.*); sin
él, la tabla de siempre.
"""
import pandas as pd
import streamlit as st

from ui.components.escena import NO_DISPONIBLE, cabecera, escena


def _fmt(v) -> str:
    from core.diagnostics import _fmt as fmt
    try:
        return fmt(float(v))
    except (TypeError, ValueError):
        return str(v)


def _contexto(datos, fila: int, schema: dict, columna: str) -> str:
    """Fecha y un par de datos del registro, para saber de quién es el valor."""
    if datos is None or fila not in datos.index:
        return f"Fila {fila + 1} del archivo"
    reg = datos.loc[fila]
    partes = []
    for d in (schema or {}).get("dates", []):
        if d in datos.columns and d != columna:
            fecha = pd.to_datetime(reg.get(d), errors="coerce")
            if pd.notna(fecha):
                partes.append(f"{fecha:%d/%m/%Y}")
                break
    for c in (schema or {}).get("categorical", []) or []:
        valor = str(reg.get(c)).strip() if c in datos.columns and c != columna and pd.notna(reg.get(c)) else ""
        # Sin repetir lo que ya dice otro dato («Ximena Díaz Ortiz · Ximena»).
        if valor and not any(valor.lower() in x.lower() or x.lower() in valor.lower() for x in partes):
            partes.append(valor)
        if len(partes) >= 3:
            break
    return " · ".join(partes) or f"Fila {fila + 1} del archivo"


def _datos_anomalias(anomalias, schema, datos) -> dict:
    a = anomalias if isinstance(anomalias, pd.DataFrame) else pd.DataFrame()
    n = len(a)
    datos_n = len(datos) if datos is not None else 0
    columnas, casos = [], []
    if n:
        conteo = a.groupby("columna").size().sort_values(ascending=False)
        tope = int(conteo.max()) or 1
        for col, cuantos in conteo.items():
            tipos = a[a["columna"] == col]["tipo"].value_counts()
            columnas.append({"n": str(col), "cuantos": int(cuantos), "ancho": round(cuantos / tope * 100, 1),
                             "tipos": " · ".join(f"{t.lower()}: {k}" for t, k in tipos.items())})
        # Los más alejados de lo normal primero (en rangos intercuartílicos).
        rangos = {}
        for col in a["columna"].unique():
            if datos is not None and col in datos.columns:
                v = pd.to_numeric(datos[col], errors="coerce").dropna()
                if len(v):
                    q1, q3 = v.quantile([.25, .75])
                    rangos[col] = (float(v.min()), float(v.max()), float(q1), float(q3), float(v.median()))
        def distancia(f):
            r = rangos.get(f["columna"])
            val = pd.to_numeric(pd.Series([f["valor"]]), errors="coerce").iloc[0]
            if r is None or pd.isna(val):
                return 0.0
            iqr = (r[3] - r[2]) or 1
            return abs(float(val) - r[4]) / iqr
        ordenadas = sorted(a.to_dict("records"), key=distancia, reverse=True)[:12]
        for f in ordenadas:
            col = f["columna"]
            caso = {"col": str(col), "tipo": str(f["tipo"]), "contexto": _contexto(datos, int(f["fila"]), schema, col),
                    "x": None}
            val = pd.to_numeric(pd.Series([f["valor"]]), errors="coerce").iloc[0]
            if pd.isna(val):
                caso["valor"] = "Vacía" if "Fecha" in str(f["tipo"]) else str(f["valor"])
            else:
                caso["valor"] = _fmt(val)
                r = rangos.get(col)
                if r:
                    lo_v, hi_v, q1, q3, _ = r
                    ancho = (hi_v - lo_v) or 1
                    normal_lo, normal_hi = max(lo_v, q1 - 1.5 * (q3 - q1)), min(hi_v, q3 + 1.5 * (q3 - q1))
                    pos = lambda v: round(max(0.0, min(100.0, (v - lo_v) / ancho * 100)), 1)  # noqa: E731
                    caso.update({"x": pos(float(val)), "lo": pos(normal_lo), "hi": pos(normal_hi),
                                 "rango": f"{_fmt(normal_lo)} – {_fmt(normal_hi)}",
                                 "fuera": "arriba" if val > normal_hi else "abajo" if val < normal_lo else ""})
            casos.append(caso)
        principal = columnas[0]
        titular = (f"{n:,} valores fuera de lo normal en {len(columnas)} columna{'s' if len(columnas) != 1 else ''}; "
                   f"la que más tiene es {principal['n']} ({principal['cuantos']}).")
    else:
        titular = "Ningún valor se sale de lo normal con los filtros actuales."
    return {"total": f"{n:,}", "total_n": n, "registros": f"{datos_n:,}", "titular": titular,
            "columnas": columnas, "casos": casos}


def render_anomalies(anomalias, schema=None, datos=None):
    if escena("anomalias", _datos_anomalias(anomalias, schema, datos), clave="anomalias_js") is not NO_DISPONIBLE:
        if isinstance(anomalias, pd.DataFrame) and not anomalias.empty:
            with st.expander("Ver todas las anomalías en tabla", expanded=False):
                st.dataframe(anomalias, use_container_width=True)
        return
    n = 0 if anomalias is None else len(anomalias)
    cabecera("Anomalías", "Valores fuera de lo normal según los métodos estadísticos del panel.", ceja="Revisión",
             icono="🚨", cifras=[(f"{n:,}", "posibles anomalías")], clave="cab_anomalias", respaldo_html="")
    if anomalias is None or anomalias.empty:
        st.success("No se detectaron anomalías con los métodos actuales.")
    else:
        st.warning(f"{len(anomalias):,} posibles anomalías")
        st.dataframe(anomalias, use_container_width=True)


def _datos_finanzas(estadisticas: pd.DataFrame, schema: dict) -> dict:
    from visualization.charts import _label
    metricas = []
    for _, f in estadisticas.iterrows():
        try:
            lo, hi = float(f["Min"]), float(f["Max"])
            q1, q3, med, media, std = float(f["Q1"]), float(f["Q3"]), float(f["Mediana"]), float(f["Media"]), float(f["Std"])
        except (KeyError, TypeError, ValueError):
            continue
        ancho = (hi - lo) or 1
        pos = lambda v: round(max(0.0, min(100.0, (v - lo) / ancho * 100)), 1)  # noqa: E731
        lectura = f"La mitad central de los valores está entre {_fmt(q1)} y {_fmt(q3)}."
        if std and abs(media - med) / std > 0.2:
            lectura += (f" El promedio queda {'por encima' if media > med else 'por debajo'} de la mediana: unos pocos "
                        f"valores muy {'altos' if media > med else 'bajos'} lo arrastran, así que la mediana describe mejor "
                        f"el caso típico.")
        metricas.append({"n": _label(schema or {}, f["Columna"]), "cuenta": f"{int(f['N']):,}", "media": _fmt(media),
                         "mediana": _fmt(med), "std": _fmt(std), "min": _fmt(lo), "max": _fmt(hi), "q1": _fmt(q1),
                         "q3": _fmt(q3), "x": {"q1": pos(q1), "q3": pos(q3), "med": pos(med), "media": pos(media)},
                         "lectura": lectura})
    return {"metricas": metricas}


def render_finanzas(estadisticas, schema=None):
    """Lectura estadística por métrica (vista «💵 Finanzas» del modo Analista)."""
    from ui.components.section import section_header
    cabecera("Lectura financiera", "Cómo se reparte cada métrica: rango, mitad central, mediana y promedio.",
             ceja="Finanzas", icono="💵", clave="cab_finanzas",
             respaldo_html=section_header("Lectura financiera", eyebrow="ANÁLISIS", compact=True))
    if isinstance(estadisticas, pd.DataFrame) and not estadisticas.empty:
        if escena("finanzas", _datos_finanzas(estadisticas, schema), clave="finanzas_js") is not NO_DISPONIBLE:
            with st.expander("Ver la tabla de estadísticas", expanded=False):
                st.dataframe(estadisticas, use_container_width=True, hide_index=True)
        else:
            st.dataframe(estadisticas, use_container_width=True, hide_index=True)
    else:
        st.info("No hay métricas numéricas para resumir.")
    st.caption("Esta vista utiliza las métricas detectadas automáticamente; no presupone que el archivo sea de ventas.")
