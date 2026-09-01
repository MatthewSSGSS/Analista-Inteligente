import streamlit as st

def render_anomalies(df, schema=None):
    if df is None or df.empty:
        st.success("No se detectaron anomalías con los métodos actuales.")
    else:
        st.warning(f"{len(df):,} posibles anomalías")
        st.dataframe(df,use_container_width=True)
