"""Calidad de los datos, mostrada como una cinta compacta arriba de la tabla
(sección Datos) en vez de su propia pestaña — mismo cálculo de siempre
(`profile["quality"]`, `profile["cleaning_log"]`, `profile["relationships"]`),
solo reorganizado como ribbon horizontal (Propuesta UX 1e)."""
import streamlit as st


def render_quality(profile):
    q = profile["quality"]
    score = float(q.get("score", 0))
    tone = "🟢" if score >= 90 else "🟡" if score >= 75 else "🔴"

    st.markdown('<span class="mono">CALIDAD GENERAL</span>', unsafe_allow_html=True)
    a, b, c, d = st.columns(4)
    a.metric(f"{tone} General", f"{score:.1f}%")
    b.metric("Completitud", f"{q['completeness']:.1f}%")
    c.metric("Consistencia", f"{q['consistency']:.1f}%")
    d.metric("Duplicados", f"{q['duplicate_rows']:,}")

    if score >= 90:
        st.success("Los datos presentan una base sólida para el análisis automático.")
    elif score >= 75:
        st.warning("Los datos son utilizables, pero conviene revisar las columnas con faltantes o duplicados.")
    else:
        st.error("La calidad es baja. Revisa los datos antes de tomar decisiones basadas en los resultados.")

    with st.expander("Ver detalle por columna", expanded=False):
        st.caption("La calidad evalúa estructura, valores faltantes y duplicados. Los faltantes numéricos se convierten a 0 para los cálculos; los faltantes de texto se conservan como faltantes.")
        st.dataframe(profile["quality"]["columns"], use_container_width=True, hide_index=True)
        if profile["cleaning_log"]:
            st.markdown("##### Cambios realizados automáticamente")
            for x in profile["cleaning_log"]:
                st.write("•", x)
        if profile.get("relationships"):
            st.markdown("##### Relaciones detectadas")
            st.dataframe(profile["relationships"], use_container_width=True, hide_index=True)
