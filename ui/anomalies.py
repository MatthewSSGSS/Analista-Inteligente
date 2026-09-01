import streamlit as st
from ui.components import card_kpi, section_header

def render_anomalies(df, schema=None):
    # 1. ENCABEZADO UNIFICADO
    section_header(
        "⚠️ Registro de Anomalías y Valores Atípicos", 
        "Detección automática de inconsistencias o desvíos en el dataset activo."
    )

    if df is None or df.empty:
        # Estado Limpio: Banner Positivo Neón Verde
        st.markdown("""
        <div class="signal-box-positive" style="display: flex; align-items: center; gap: 12px; margin-bottom: 20px;">
            <span style="font-size: 1.2rem;">✅</span>
            <div>
                <b>Sin anomalías detectadas:</b> El dataset no presenta valores atípicos críticos con los métodos actuales.
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        # Estado con Anomalías: KPI + Tabla estilizada en 2 Columnas
        col_summary, col_action = st.columns([1, 2.2])

        with col_summary:
            # Tarjeta KPI Neón que destaca el total detectado
            card_kpi(
                label="Anomalías Detectadas", 
                value=f"{len(df):,}", 
                delta="Revisión sugerida", 
                is_highlight=True
            )
            
            # Tarjeta contextual
            st.markdown("""
            <div style="background: rgba(255, 42, 95, 0.08); border: 1px solid rgba(255, 42, 95, 0.3); border-radius: 8px; padding: 14px; margin-top: 12px;">
                <p style="margin: 0; color: #F0F6FC; font-size: 0.85rem;">
                    <b>Impacto:</b> Los registros listados superan los umbrales estadísticos estándar respecto a la media del dataset.
                </p>
            </div>
            """, unsafe_allow_html=True)

        with col_action:
            # Subtítulo y Tabla Integrada
            st.markdown("<p style='color: #8B949E; font-size: 0.85rem; font-weight: 700; margin-bottom: 8px;'>REGISTROS AFECTADOS</p>", unsafe_allow_html=True)
            st.dataframe(df, use_container_width=True)