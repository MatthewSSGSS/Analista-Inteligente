import streamlit as st

def render_data_table(df):
    st.subheader("Datos")
    st.caption(f"{len(df):,} registros")
    st.dataframe(df.head(10000),use_container_width=True,height=620)
