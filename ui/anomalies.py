import streamlit as st
from ui.components.escena import cabecera

def render_anomalies(df, schema=None):
    n = 0 if df is None else len(df)
    cabecera("Anomalías", "Valores fuera de lo normal según los métodos estadísticos del panel.", ceja="Revisión",
             icono="🚨", cifras=[(f"{n:,}", "posibles anomalías")], clave="cab_anomalias", respaldo_html="")
    if df is None or df.empty:
        st.success("No se detectaron anomalías con los métodos actuales.")
    else:
        st.warning(f"{len(df):,} posibles anomalías")
        st.dataframe(df,use_container_width=True)
