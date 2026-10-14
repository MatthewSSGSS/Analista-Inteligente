import pandas as pd
import streamlit as st
from ui.components.escena import cabecera


def _vista(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Copia para MOSTRAR (los datos no se tocan): fechas sin «00:00:00» y
    cifras grandes sin decimales sueltos («42001527.4657» → «42.001.528»)."""
    vista = df.head(10000).copy()
    config = {}
    for c in vista.columns:
        s = vista[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            sin_hora = s.dropna().empty or (s.dropna().dt.normalize() == s.dropna()).all()
            config[c] = st.column_config.DatetimeColumn(str(c), format="DD/MM/YYYY" if sin_hora else "DD/MM/YYYY HH:mm")
        elif pd.api.types.is_float_dtype(s) and s.abs().max() >= 1000:
            vista[c] = s.round(0)
            config[c] = st.column_config.NumberColumn(str(c), format="localized")
        elif pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            config[c] = st.column_config.NumberColumn(str(c), format="localized")
    return vista, config


def render_data_table(df):
    cabecera("Datos", "La tabla con los filtros activos (se muestran hasta 10.000 filas).", ceja="Tabla",
             icono="🧮", cifras=[(f"{len(df):,}", "registros"), (f"{df.shape[1]:,}", "columnas")], clave="cab_datos",
             respaldo_html=f"<h3>Datos</h3><p>{len(df):,} registros</p>")
    visibles = [c for c in df.columns if not str(c).startswith("__") and not str(c).startswith("_geo_")]
    vista, config = _vista(df[visibles])
    st.dataframe(vista, use_container_width=True, height=620, hide_index=True, column_config=config)
    st.download_button("⬇️ Descargar estos datos (CSV)", df[visibles].to_csv(index=False).encode("utf-8-sig"),
                       file_name="datos_filtrados.csv", mime="text/csv", key="datos_descarga_csv")
