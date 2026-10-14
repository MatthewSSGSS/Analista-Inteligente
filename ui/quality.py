import pandas as pd
import streamlit as st
from ui.components.escena import NO_DISPONIBLE, cabecera, escena


def _datos_calidad(profile) -> dict:
    """Lo que dibuja «Calidad del dato» en JavaScript (ui/web/calidad.*), en texto plano."""
    q = profile["quality"]
    score = float(q.get("score", 0))
    tono, estado = (("positive", "Base sólida") if score >= 90 else
                    ("neutral", "Utilizable con cuidado") if score >= 75 else ("negative", "Calidad baja"))
    veredicto = ("Los datos presentan una base sólida para el análisis automático." if score >= 90 else
                 "Los datos son utilizables, pero conviene revisar las columnas con faltantes o duplicados." if score >= 75
                 else "La calidad es baja: revisa los datos antes de tomar decisiones con estos resultados.")
    columnas = []
    tabla = q.get("columns")
    if isinstance(tabla, pd.DataFrame) and not tabla.empty:
        for _, f in tabla.iterrows():
            faltan_pct = float(f.get("Faltantes %", 0) or 0)
            columnas.append({"n": str(f.get("Columna", "")), "tipo": str(f.get("Tipo", "")),
                             "completo": max(0.0, 100 - faltan_pct),
                             "faltan": f"{int(f.get('Faltantes', 0) or 0):,}" if f.get("Faltantes") else "",
                             "unicos": f"{int(f.get('Únicos', 0) or 0):,}"})
        columnas.sort(key=lambda c: c["completo"])
    return {
        "puntaje": score, "tono": tono, "estado": estado, "veredicto": veredicto,
        "nota": ("La calidad mide estructura, valores faltantes y duplicados. Los faltantes numéricos cuentan como 0 en "
                 "los cálculos; los de texto se conservan como faltantes."),
        "medidas": [{"n": "Completitud", "v": float(q.get("completeness", 0))},
                    {"n": "Consistencia", "v": float(q.get("consistency", 0))},
                    {"n": "Validez", "v": float(q.get("validity", 0))}],
        "duplicados": f"{int(q.get('duplicate_rows', 0)):,}",
        "columnas": columnas,
        "cambios": [str(x) for x in profile.get("cleaning_log") or []],
    }


def render_quality(profile):
    q=profile["quality"]
    score=float(q.get("score",0))
    # Medidor, veredicto, columna por columna y la limpieza automática en
    # JavaScript (ui/web/calidad.*); sin él, la versión clásica de abajo.
    if escena("calidad", _datos_calidad(profile), clave="calidad_js") is not NO_DISPONIBLE:
        if profile.get("relationships"):
            st.markdown("### Relaciones detectadas")
            st.dataframe(profile["relationships"],use_container_width=True,hide_index=True)
        with st.expander("Ver la tabla de calidad por columna", expanded=False):
            st.dataframe(profile["quality"]["columns"],use_container_width=True,hide_index=True)
        return
    tone="🟢" if score>=90 else "🟡" if score>=75 else "🔴"
    cabecera("Estado de los datos", "Estructura, valores faltantes y duplicados del archivo.", ceja="Calidad del dato",
             icono=tone, cifras=[(f"{score:.0f}%", "calidad general"), (f"{q['completeness']:.0f}%", "completitud")],
             clave="cab_calidad", respaldo_html=f"<h3>{tone} Estado de los datos</h3>")
    a,b,c,d=st.columns(4)
    a.metric("Calidad general",f"{score:.1f}%")
    b.metric("Completitud",f"{q['completeness']:.1f}%")
    c.metric("Consistencia",f"{q['consistency']:.1f}%")
    d.metric("Duplicados",f"{q['duplicate_rows']:,}")
    st.caption("La calidad evalúa estructura, valores faltantes y duplicados. Los faltantes numéricos se convierten a 0 para los cálculos; los faltantes de texto se conservan como faltantes.")
    if q.get("score",0) >= 90:
        st.success("Los datos presentan una base sólida para el análisis automático.")
    elif q.get("score",0) >= 75:
        st.warning("Los datos son utilizables, pero conviene revisar las columnas con faltantes o duplicados.")
    else:
        st.error("La calidad es baja. Revisa los datos antes de tomar decisiones basadas en los resultados.")
    st.dataframe(profile["quality"]["columns"],use_container_width=True,hide_index=True)
    if profile["cleaning_log"]:
        st.markdown("### Cambios realizados automáticamente")
        for x in profile["cleaning_log"]: st.write("•",x)
    if profile.get("relationships"):
        st.markdown("### Relaciones detectadas")
        st.dataframe(profile["relationships"],use_container_width=True,hide_index=True)
