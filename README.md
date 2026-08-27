# Excel Intelligence Universal V44 — VisualPremium PowerBI

## Qué se corrigió

- Claves únicas para todos los gráficos y botones de explicación de Streamlit.
- Protección contra crecimiento/comparaciones con base cero o valores no finitos.
- Las columnas Enero–Diciembre ya no se interpretan como métricas independientes ni generan KPIs falsos.
- Las tablas mensuales calculan la variación usando el último mes contra el mes inmediatamente anterior.
- Las gráficas de relación evitan fallar cuando una variable es constante o no tiene variación suficiente.
- La matriz de correlaciones evita mostrarse cuando no existen suficientes variables con variación real.
- Filtros de fecha aislados por hoja para evitar estados viejos al cambiar de Excel/hoja.
- Comparación de archivos ordenada cronológicamente cuando todos contienen fechas.
- Georreferenciación más protegida: coordenadas inválidas no entran al mapa y se limita la cantidad de ubicaciones nuevas a geocodificar para reducir bloqueos.
- Se mantiene la clasificación universal: ventas, clientes, inventarios, compras, catálogos, listas, tareas, planes, etc.
- Identificadores como cédulas, seriales, códigos y teléfonos continúan fuera de los cálculos analíticos cuando el motor puede identificarlos.
- Los valores faltantes de columnas numéricas siguen tratándose como 0 para los cálculos, sin convertir categorías faltantes en 0.
- Nuevo blindaje central contra `NaN`, `NaT`, infinitos y selecciones sin datos: los agregados seguros evitan que un filtro vacío rompa los KPI, hallazgos, comparación o asistente.
- Se añadieron pruebas específicas para conjuntos sin valores numéricos válidos.

## Importante

Esta versión contiene **una sola aplicación**. No hay un `app.py` duplicado en la raíz que pueda ejecutarse accidentalmente en lugar de la aplicación actual.

## Ejecución

```powershell
pip install -r requirements.txt
streamlit run app.py
```

## Verificación rápida sin abrir Streamlit

```powershell
python tests/smoke_test.py
```

La prueba verifica carga de Excel, detección de fechas, exclusión de identificadores, tablas Enero–Diciembre, gráficos, comparación de archivos y manejo de base cero.


## V25 — Filtros relacionados

Los filtros categóricos ahora funcionan como filtros en cascada: cada selector
calcula sus opciones a partir de las combinaciones que realmente existen bajo
la selección de los demás filtros. Por ejemplo, al seleccionar un Nombre,
Apellido1 y Apellido2 muestran únicamente valores compatibles con ese Nombre.
La selección de periodo también restringe las opciones disponibles.

Las selecciones que dejan de ser válidas se limpian automáticamente para evitar
resultados contradictorios o valores inválidos en los controles de Streamlit.

## V26 — comparación temporal por categoría
- La evolución temporal ahora puede desglosarse automáticamente por una dimensión categórica relevante.
- Si el Excel tiene Fecha + Métrica + una dimensión con varias categorías, se muestran líneas independientes por categoría.
- Se priorizan las categorías con mayor peso para mantener la lectura clara y evitar gráficos saturados.
- Ejemplo: Nombre = Adriana y Camilo → dos líneas comparables en la misma gráfica.


## Cambios V33
- Filtro global de persona mediante un único campo "Buscar por nombre completo"; admite nombre completo o parcial.
- La búsqueda por persona se aplica a todo el dashboard y participa en los filtros relacionados.
- La comparación individual usa nombres completos cuando existen Nombre + Apellido(s).
- Se redujo texto auxiliar y subtítulos innecesarios en la zona analítica.


## V33
- Añade lectura automática de mejor y menor desempeño por una dimensión relevante (región, ciudad, producto, categoría, etc.).
- Incluye gráfico de extremos y tarjetas de “Más productivo” / “Menos productivo”.
- La dimensión se puede cambiar sin perder la selección general.

## V35 — mapa geográfico robusto
- El mapa se centra automáticamente en las ubicaciones reales del archivo.
- Si existen latitud/longitud se usan directamente.
- Si hay ciudad o región, se intenta geocodificación y se dispone de respaldos conservadores para ubicaciones comunes cuando no hay conexión.
- Si el archivo solo tiene países, también se genera mapa por país.
- Las ubicaciones no confirmadas no se inventan ni alteran los datos originales.

## V37 — mapa y comparación mejorados
- El mapa ya no escala las burbujas directamente por el valor: el tamaño queda limitado para que una ubicación no tape a las demás.
- El mapa usa una proyección Mercator y centra el área sobre las ubicaciones reales; para datos colombianos prioriza una vista de Colombia en lugar de mostrar medio continente.
- La comparación individual reconstruye automáticamente el campo **Nombre completo** si el perfil no lo conservó.
- En “Comparar por” se muestra **Nombre completo** como una sola dimensión cuando existen Nombre + Apellido(s).
- Los valores de comparación se deduplican y se muestran como nombres completos reales del Excel.
- Las dimensiones de comparación muestran el nombre real de la columna para evitar etiquetas repetidas como “Categoría” o “Estado”.
- Se añadió **Barras: anterior vs actual**, una visualización de barras apiladas de dos colores para comparar los dos últimos periodos dentro de cada categoría.

## V39 — Georeferenciación interactiva

La sección **Georeferenciación** convierte las ubicaciones detectadas en un mapa interactivo. Los puntos se agrupan por ubicación para evitar burbujas duplicadas y el tamaño se limita para conservar la lectura del mapa.

- Haz clic en un punto para abrir el detalle de esa ubicación.
- Se muestran registros, métrica seleccionada, coordenadas y categorías relacionadas.
- Si existen fechas y una métrica, se muestra una evolución temporal de la ubicación seleccionada.
- Los registros originales de la ubicación quedan disponibles al final para auditoría.
- Se priorizan coordenadas del Excel; si no existen, se usa ciudad/región/país y el motor geográfico existente.


## V40 — Corrección de georeferenciación y comparación individual

- Corregido el error de Plotly `Invalid property ... Marker: 'line'` en el mapa interactivo.
- Los marcadores del mapa ya no reciben propiedades no soportadas por `scatter_map`.
- Cuando el Excel trae Latitud/Longitud, el mapa utiliza Ciudad, Región o País como etiqueta disponible en lugar de agrupar todo bajo “Ubicación”.
- La comparación individual ya no depende de que exista una dimensión seleccionada previamente.
- **Nombre completo** queda disponible directamente en “Comparar por” cuando el Excel contiene Nombre + Apellido(s).
- El selector de nombres acepta búsqueda escribiendo y muestra nombres reales completos del Excel.
- La comparación usa el dataframe ya filtrado, por lo que al seleccionar una persona se analiza todo lo relacionado con ella dentro del contexto actual.
- Si no hay fecha, la comparación individual usa barras directas en lugar de intentar fabricar una evolución temporal.


## V41 — Georeferenciación condicional
La georeferenciación ahora es una capacidad opcional. La pestaña y el mapa solo aparecen cuando el Excel contiene coordenadas válidas o campos geográficos con datos utilizables (ciudad, región o país). Catálogos de planes, listas de compras y tablas sin ubicación no muestran un mapa vacío o irrelevante.

## V61 — Texto limpio y presentación consistente

- Corregido el problema por el que los hallazgos mostraban literalmente etiquetas como `<b>...</b>` o `&lt;b&gt;...&lt;/b&gt;`.
- El motor de hallazgos ahora genera texto analítico limpio, sin HTML incrustado.
- Dashboard, Resumen ejecutivo, Alertas y exportaciones HTML pasan por una limpieza común de texto para evitar etiquetas visibles heredadas.
- Se conserva el formato visual de las tarjetas; el cambio afecta únicamente a la presentación del contenido.
- La limpieza también deshace HTML escapado previamente, evitando dobles escapes en informes generados.
- Se verificó compilación de todos los módulos y el smoke test completo.

## V44 — Georeferenciación analítica + comparación individual reforzada

- Georeferenciación interactiva con puntos más pequeños y una escala visual por nivel: **alto / medio / bajo**.
- Los colores del mapa permiten detectar rápidamente las ubicaciones con mayor y menor valor relativo de la métrica seleccionada.
- El detalle de una ubicación ahora incluye, cuando el Excel permite identificar personas/agentes, un ranking gráfico de sus resultados, mejor y menor resultado de la zona, composición por categorías y evolución temporal cuando existen fechas.
- La selección de un punto en mapas con varios colores recupera la ubicación correcta mediante `customdata`, evitando que un clic termine mostrando otra ciudad.
- La precisión geográfica respeta las coordenadas reales del Excel cuando existen; si el archivo solo contiene ciudad/región/país, el sistema mantiene la precisión disponible de esa fuente sin inventar coordenadas.
- La comparación individual prioriza **Nombre completo** automáticamente cuando existe; ya no obliga a escoger otra dimensión antes de poder seleccionar personas.
- La comparación individual temporal usa un motor dedicado y robusto para garantizar una línea por persona seleccionada, incluso cuando hay datos dispersos o el campo de nombre es sintético.
- Se mantienen las capacidades universales y la georeferenciación sigue siendo condicional: archivos sin datos geográficos no reciben un mapa.


## V44 – mejoras de análisis individual y georeferenciación
- Evaluación individual: selección de nombres completos y comparación por otras dimensiones sin perder la opción de personas.
- Comparación individual robusta: líneas cuando existen suficientes periodos; barras cuando los datos son demasiado escasos para representar una tendencia honestamente.
- Perfil individual: KPIs de resultado, mejor/peor periodo, variación y comparación contra el promedio visible; visual de producto/categoría principal.
- Georeferenciación: al seleccionar una zona ahora muestra zona vs promedio de otras zonas, evolución temporal, rendimiento de agentes y composición por producto/categoría.
- Se conserva la georeferenciación como capacidad opcional: solo aparece cuando el Excel tiene geografía utilizable.
- Puntos del mapa se mantienen pequeños y coloreados por nivel de desempeño.
- Se corrigió el uso de `_fmt_number` que podía dejar la evaluación individual sin renderizar.


## V51 — Analítica universal reforzada
- KPIs ejecutivos adaptativos según las métricas, fechas y dimensiones realmente detectadas.
- Nuevo drill-down “Del total al detalle” para pasar del indicador general a una dimensión y elemento concreto sin imponer una estructura de ventas.
- Perfil individual ampliado con cambio reciente, comparación contra el promedio visible, mediana, máximo, mejor/peor periodo y producto líder cuando existe.
- Alertas compactas con evidencia, significado y acción recomendada.
- Biblioteca de gráficos inteligentes: el sistema propone visuales según las preguntas que la estructura del Excel puede responder y evita repetir visuales equivalentes.
- Georeferenciación analítica reforzada: el detalle de una zona incorpora cambio reciente, comparación contra otras zonas, agentes y composición de producto/categoría.
- Se mantiene la detección universal: las funciones solo se muestran cuando los datos necesarios existen y la georeferenciación sigue siendo condicional.


## V52 — Perfil individual + comparación A/B + geografía avanzada + modo ejecutivo

- **Perfil individual dedicado:** botón "Analizar perfil individual" y página independiente. Selecciona un nombre completo y el sistema reúne métricas, evolución, contexto, dimensiones relacionadas y registros originales que el Excel permita conocer.
- **Comparación A vs B:** nueva pestaña para comparar dos personas con KPI de diferencia, mejor resultado, líneas, barras, apiladas, 100% y radar cuando la estructura del archivo lo permite; incluye una tabla de qué dimensión explica la diferencia.
- **Georeferenciación avanzada:** además del detalle de una zona, permite comparar dos zonas directamente y responde con valor, diferencia porcentual y gráfico comparativo.
- **Modo ejecutivo reforzado:** resumen compacto, KPIs adaptativos, lectura analítica priorizada y hasta tres visuales distintos en una cuadrícula compacta.
- Se conserva la adaptación universal y la georeferenciación sigue siendo condicional.

## Informe HTML para compartir

La pestaña **Exportar** ahora permite generar un informe HTML autocontenido. El informe puede incluir, según la estructura real del Excel:

- KPIs y resumen ejecutivo.
- Cambio principal entre periodos cuando existe una fecha utilizable.
- Hallazgos, alertas, implicaciones y acciones sugeridas.
- Gráficos de evolución, comparación, rankings, distribución, relaciones y correlaciones cuando aplican.
- Mapa de desempeño únicamente cuando el Excel tiene geografía utilizable.
- Lectura de calidad del dato.
- Principales categorías.

Hay dos opciones: **selección actual** y **Excel completo**. El archivo HTML contiene los gráficos dentro del propio documento y puede abrirse directamente en Chrome/Edge sin ejecutar Streamlit.

## Informe general de todo el Excel

La pestaña **Exportar** incluye ahora **📊 Exportar informe general · TODO el Excel**. Este informe no representa una captura de los filtros actuales: recorre todas las hojas con datos del libro cargado y construye un reporte HTML independiente para compartir.

El informe incluye:
- Resumen ejecutivo del libro completo.
- Total de hojas, registros y celdas analizadas.
- Calidad y completitud global ponderadas.
- Hallazgos destacados por hoja.
- Mapa del contenido de cada hoja (registros, columnas, periodo y métrica principal).
- KPIs y análisis de cada hoja.
- Gráficos adaptativos por hoja, incluyendo mapa solo cuando existe geografía utilizable.
- Alertas/lecturas y calidad de datos.

También se conserva **Informe de esta hoja completa**, que analiza únicamente la hoja visible pero sin filtros.

## V59 — Informe HTML individual por hoja

La pestaña **Exportar** ahora permite elegir cualquier hoja con datos y descargar un HTML independiente de esa hoja.

- Selector de hoja para elegir exactamente qué parte del Excel se quiere reportar.
- El informe individual analiza la hoja completa, sin depender de los filtros actuales.
- Conserva KPIs, hallazgos, calidad y gráficos adaptativos que tengan sentido para esa hoja.
- El informe general de **TODO el Excel** se mantiene como opción separada.
- La interfaz de Exportar queda organizada en dos niveles: informe individual (más corto) e informe general (más amplio).
