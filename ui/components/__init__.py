"""Componentes de presentación reutilizados por varias vistas de `ui/`.

Antes de este paquete, patrones como la tarjeta KPI, la tarjeta de hallazgo
o la tarjeta de gráfico vivían copiados (con pequeñas variaciones) en
`ui/dashboard.py`, `ui/person_profile.py`, `ui/georeferencing.py`,
`ui/comparison.py`, `ui/home.py` y `ui/executive.py`. Cada función de aquí
reemplaza esas copias: mismo HTML/CSS resultante, una sola definición.

Estos componentes solo arman HTML/widgets a partir de datos ya calculados —
no leen `st.session_state` de negocio ni conocen `core/`. La composición de
cada pantalla (qué mostrar, con qué datos) sigue viviendo en `ui/*.py`.
"""
