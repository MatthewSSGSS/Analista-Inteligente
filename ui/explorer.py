import streamlit as st
import pandas as pd
from ui.labels import agg_label


def render_explorer(df, schema):
    st.subheader("Explorador")
    x = st.selectbox("Dimensión / X", list(df.columns), key="explore_x")
    y = st.selectbox("Métrica / Y", ["(conteo)"] + schema["metrics"], key="explore_y")

    if y == "(conteo)":
        result = df[x].value_counts(dropna=False).head(100).rename("Registros").reset_index()
        result.columns = [x, "Registros"]
    else:
        result = df.groupby(x, dropna=False)[y].agg(["sum", "mean", "count"]).reset_index()
        result.columns = [x, agg_label("sum"), agg_label("mean"), agg_label("count")]

    st.dataframe(result, use_container_width=True)
