import streamlit as st
from ui.components.escena import cabecera

def render_data_table(df):
    cabecera("Datos", "La tabla con los filtros activos (se muestran hasta 10.000 filas).", ceja="Tabla",
             icono="🧮", cifras=[(f"{len(df):,}", "registros"), (f"{df.shape[1]:,}", "columnas")], clave="cab_datos",
             respaldo_html=f"<h3>Datos</h3><p>{len(df):,} registros</p>")
    st.dataframe(df.head(10000),use_container_width=True,height=620)
