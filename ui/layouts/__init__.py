"""Estructuras de layout reutilizadas por varias vistas de `ui/` y por
`app.py`: navegación por pestañas, columnas de contenido y grillas de
tarjetas.

A diferencia de `ui/components/` (que arma una pieza de UI concreta a
partir de datos ya calculados), esto solo resuelve la DISPOSICIÓN — cuántas
columnas, con qué proporción, cómo se llama cada pestaña — para que cada
vista deje de repetir `st.columns([...])`/`st.tabs([...])` con números
elegidos a mano cada vez. Cada vista sigue decidiendo qué contenido va en
cada columna/pestaña.

El comportamiento de apilado responsive (columnas una debajo de otra en
pantallas angostas) lo da Streamlit de forma nativa en `st.columns(...)`;
no hay que replicarlo aquí. El `@media (max-width:900px)` de
`ui/styles/theme.py` cubre el resto (paddings, tamaños de tarjeta).
"""
