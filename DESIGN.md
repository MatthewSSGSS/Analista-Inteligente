# DESIGN.md — Arquitectura objetivo de UI

> Basado en `00_Auditoria` (mapa técnico + duplicaciones) y `01_Inventario_Funcionalidades`
> (`FEATURES.md`). Este documento es **solo diseño**: no se movió ni se modificó ningún archivo
> de código en esta tarea. Es el plano que las tareas de implementación deben seguir.

## 0. Principios que gobiernan esta arquitectura

1. **`core/` y `visualization/` no cambian de responsabilidad.** Ya están correctamente separados
   de la UI (motor de datos / motor de gráficos). El rediseño es de presentación y organización de
   `ui/` + `app.py`, no de lógica de negocio.
2. **Una sola fuente de verdad por cada cosa que hoy está duplicada** (tema, helpers de formato,
   "perfil individual"). Consolidar, no añadir una cuarta variante.
3. **CSS no tapa problemas de estructura.** Si un componente se ve mal porque su responsabilidad
   está mal definida (p. ej. una función que mezcla cálculo + HTML + estado de sesión), se
   reorganiza el componente; no se le agrega `!important`.
4. **Cero regresiones**: cada paso de implementación se valida contra `FEATURES.md`. Ningún
   archivo se reescribe "a ciegas" — se extrae/mueve función por función.
5. **Cambios incrementales y reversibles.** La migración se hace en capas (ver §5), cada una
   dejando la app funcional en Light y Dark Mode antes de pasar a la siguiente.

---

## 1. Responsabilidades por capa (objetivo)

```
app.py            Orquestador y router. Arranque de sesión, gate de login,
                   sidebar (carga de archivo + filtros + herramientas),
                   selección de tabs según capacidades detectadas.
                   NO contiene HTML/CSS de detalle ni lógica de negocio.

core/              Motor de datos: carga, perfilado, esquema semántico,
                   filtros, KPIs, insights, alertas, comparación, geografía,
                   seguimiento, asistente, calidad. Sin Streamlit salvo
                   auth_engine/db_engine (que ya dependen de st.secrets).
                   INTACTO en esta tarea.

visualization/     Motor de gráficos Plotly (charts.py) + selector de tipo
                   de gráfico (chart_selector.py). Reutilizado por toda la
                   UI. INTACTO en esta tarea.

ui/styles/         ÚNICA fuente de tema (tokens + CSS). Sustituye a la
                   mezcla actual (bloque inline en app.py + ui/theme.py
                   huérfano + assets/style.css.css huérfano).

ui/components/     Piezas visuales reutilizables y puras: reciben datos ya
                   calculados y devuelven HTML/renderizan un widget. Sin
                   lógica de negocio, sin leer core/ directamente.

ui/layouts/        Estructuras de página reutilizables (secciones de dos
                   columnas, grillas de KPIs, tabs temáticos) que combinan
                   components + contenido de una vista.

ui/views/           Lo que hoy son la mayoría de los ui/*.py: cada uno
                   arma UNA pantalla/tab combinando core/ + visualization/
                   + components/ + layouts/. Aquí puede vivir alguna lógica
                   de presentación específica de la vista (p. ej. qué
                   dimensión priorizar), pero no cálculo de negocio nuevo.
```

Node clave: hoy `ui/dashboard.py` mezcla las cuatro capas de arriba en un
solo archivo de 1220 líneas (helpers de formato, componentes de tarjeta,
lógica de selección de gráfico, y la vista completa). El objetivo es
**separar sin reescribir la lógica**: mover funciones a su capa, no
reinventarlas.

---

## 2. Estructura de carpetas propuesta

```
ui/
  styles/
    theme.py            # tokens (--bg, --text, --blue, ...) + inject_theme()
                         # ÚNICA función que emite <style>. Sustituye al
                         # bloque de app.py:51-399 Y a ui/theme.py.
  components/
    cards.py             # kpi_card(), insight_card(), alert_row(), factor_card()
    charts.py             # chart_card(), chart_reading() — wrapper de st.plotly_chart
    section.py            # section_intro(), decision_strip(), data_badge()
    __init__.py
  layouts/
    kpi_grid.py           # grilla de N columnas con salto de línea (hoy _kpi_grid)
    two_column.py          # patrón "contenido + panel lateral de lectura"
                            # (repetido hoy en executive.py, georeferencing.py,
                            # comparison.py con distinto layout cada vez)
    detail_tabs.py          # patrón de tabs temáticos (Diagnóstico/Desempeño/Contexto)
  views/
    home.py, landing.py, mode_choice.py, login.py        # sin cambios de fondo
    catalog.py, quality.py, anomalies.py, explorer.py,
    data_table.py, assistant.py, exports.py               # sin cambios de fondo
    person_profile.py, person_compare.py                   # sin cambios de fondo
    comparison.py, tracking.py, georeferencing.py           # sin cambios de fondo
    executive.py                                            # usa layouts/components nuevos
    dashboard/
      __init__.py         # render_dashboard() — orquesta las piezas de abajo
      controls.py          # _visual_controls, _available_chart_types, _render_selected_chart
      charts_temporal.py    # _temporal_bar, _temporal_area, _individual_trend (el bloque
                             # más grande y más delicado: 9 tipos de gráfico comparativo)
      panels.py             # _executive_headline/_signals, _alerts_panel, _why_changed,
                             # _profile_panel, _recommendations_panel, _performance_panel,
                             # _insights_panel, _drilldown_panel
      geo_panel.py           # bloque de "Inteligencia geográfica" embebido (líneas 1173-1202)
  format.py               # _fmt, _label, _concept_for, _compact_number — ÚNICA
                           # implementación; sustituye ~10 copias (ver auditoría §3)
  labels.py                # sin cambios (ya es de responsabilidad única: traducciones)
```

`practical.py` se mantiene como vista independiente (ya es coherente: reutiliza
`core/query_engine` y solo añade animaciones propias sobre las variables de
`ui/styles/theme.py`).

---

## 3. Qué se conserva, qué se divide, qué se retira

| Archivo actual | Decisión | Razón |
|---|---|---|
| `core/*.py` (25 módulos) | **Intacto** | Ya es la capa de datos; no forma parte del rediseño de UI. |
| `visualization/charts.py`, `chart_selector.py` | **Intacto** | Motor de gráficos ya reutilizado correctamente por toda la UI. |
| `app.py` | **Se reduce**, no se reescribe desde cero | El bloque CSS (líneas 51-399) se mueve tal cual a `ui/styles/theme.py`; el resto (sidebar, filtros, routing de tabs) se mantiene en `app.py` porque es legítimamente el orquestador. |
| `ui/dashboard.py` (1220 líneas) | **Se divide** en `ui/views/dashboard/*.py` (ver §2) | Es el único archivo que mezcla las 4 capas; dividir función-por-función sin tocar su lógica interna. |
| `ui/report_html.py` (808), `ui/interactive_report.py` (389) | **Intactos por ahora** | Generan HTML standalone con su propio sistema de estilos (no usan `st.markdown`/tema de Streamlit); no forman parte de la superficie visual que este rediseño toca. Se documentan como fuera de alcance. |
| `ui/georeferencing.py` (651) | **Intacto por ahora**, candidato a dividir en una fase posterior (no en esta) | Es grande pero internamente cohesivo (todo es "el mapa y su detalle"); dividirlo no es necesario para resolver la duplicación de tema/helpers, que es el problema real detectado en la auditoría. |
| `ui/executive.py`, `ui/comparison.py`, `ui/person_profile.py`, `ui/person_compare.py`, etc. | **Se adaptan** para consumir `ui/components/` y `ui/format.py` en vez de reimplementar `_fmt`/`_card`/`_chart` localmente | Elimina la duplicación de helpers detectada en la auditoría, sin tocar el cálculo. |
| `ui/theme.py` | **Se retira** (contenido útil se funde en `ui/styles/theme.py` si su paleta se prefiere; si no, se borra) | Hoy es código muerto (`inject_theme` nunca se llama) — mantenerlo junto al sistema nuevo perpetuaría la ambigüedad de "cuál es el tema real". |
| `ui/alerts.py` | **Se retira** | Import roto (`ui.components` con ese nombre no existe hoy), nunca importado desde `app.py`. Su única función útil (`render_alerts`) ya está cubierta por `ui/views/dashboard/panels.py::_alerts_panel`. Si se quiere conservar su idea (columna lateral con headline + banner de anomalías), se reimplementa limpio dentro de la nueva estructura, no se resucita el archivo roto. |
| `assets/style.css.css` | **Se retira del repo** (o se archiva fuera de `assets/` si se quiere conservar como referencia histórica) | No está conectado a nada; su paleta (neón, 100% oscura, `!important`) es incompatible con el toggle Light/Dark real. Mantenerlo en `assets/` invita a que alguien lo enganche por error. |
| `ui/labels.py` | **Intacto** | Responsabilidad única y ya limpia. |
| `.streamlit/config.toml` | **Intacto** | Fuente adicional de tema base para Streamlit (`base="light"`); coherente con Light Mode por defecto. |

**Nota de alcance**: la división de `ui/dashboard.py` es la única reestructuración de código que
este documento recomienda como parte del "rediseño de UI mantenible". Todo lo demás (`report_html`,
`interactive_report`, `georeferencing`) son candidatos legítimos para una segunda ronda, pero
tocarlos ahora no resuelve ningún problema identificado en la auditoría y aumenta el riesgo de
regresión sin necesidad.

---

## 4. Decisión de tema (resuelve el hallazgo de la auditoría)

**Se adopta como canónico el sistema hoy activo en `app.py:44-49,56-103,460-469`** (toggle
`theme_mode` con variables `--bg/--text/--panel/...` en claro y oscuro), porque:
- Es el único de los tres que efectivamente corre y ha sido probado por el usuario.
- Ya está referenciado por nombre de variable en el resto de `ui/*.py` (`var(--blue)`, etc.).

Plan:
1. Mover ese bloque literal a `ui/styles/theme.py` como `THEME_CSS(dark: bool) -> str` +
   `inject_theme(dark: bool)`.
2. `app.py` pasa a llamar `ui.styles.theme.inject_theme(dark)` en vez de tener el `<style>` inline.
3. `ui/theme.py` (el módulo huérfano) y `assets/style.css.css` se retiran (ver tabla §3) — no se
   fusionan variable por variable porque tienen paletas visualmente incompatibles entre sí; migrar
   el sistema que ya se probó es la opción de menor riesgo.
4. Los `<style>` locales de `login.py`, `landing.py`, `mode_choice.py`, `practical.py` **se
   mantienen** donde están (son aditivos: solo agregan clases nuevas sobre las variables del tema
   central) — no hace falta centralizarlos también; el problema de la auditoría era el tema base
   duplicado, no estos complementos.

Este único cambio de estructura (sin tocar un solo valor de color) ya elimina el riesgo #5 de
`FEATURES.md` ("no conectar `assets/style.css.css`/`ui/theme.py` por error").

---

## 5. Orden de migración recomendado (fases, cada una deja la app funcional)

1. **Fase A — Limpieza de código muerto** (menor riesgo posible, cero superficie visual tocada):
   retirar `ui/alerts.py` y `assets/style.css.css` (no están conectados a nada; confirmado en la
   auditoría). Probar: la app sigue igual porque nada los importaba.
2. **Fase B — Tema único**: crear `ui/styles/theme.py`, mover el CSS de `app.py`, retirar
   `ui/theme.py`. Probar explícitamente Light Mode y Dark Mode en cada pantalla del checklist de
   `FEATURES.md` §13.
3. **Fase C — `ui/format.py`**: extraer `_fmt`/`_label`/`_concept_for`/`_compact_number` a un
   único módulo; reemplazar las ~10 copias por imports. Probar: valores numéricos se ven igual en
   todas las pantallas (KPIs, tablas, tooltips de gráficos).
4. **Fase D — `ui/components/` + `ui/layouts/`**: extraer los patrones de tarjeta/sección/grilla
   repetidos (`_card`, `_chart_card`, `.section-intro`, `.kpi-card`, panel de dos columnas) a
   funciones compartidas; adaptar `executive.py`, `comparison.py`, `georeferencing.py`,
   `person_profile.py` para usarlas en vez de sus copias locales.
5. **Fase E — División de `ui/dashboard.py`**: mover funciones (sin reescribirlas) a
   `ui/views/dashboard/{controls,charts_temporal,panels,geo_panel}.py`; `ui/views/dashboard/__init__.py`
   conserva `render_dashboard()` como punto de entrada con la misma firma que hoy
   (`render_dashboard(df, dashboard)`), para que `app.py` no cambie su forma de invocarla.
6. **Fase F (fuera de esta tarea, solo queda documentada)**: evaluar si `report_html.py`,
   `interactive_report.py` y `georeferencing.py` necesitan la misma división, una vez que el resto
   del sistema esté estable.

Cada fase corresponde a una tarea futura separada (03, 04, ...), con su propio checklist de
regresión contra `FEATURES.md` antes de avanzar a la siguiente.

---

## 6. Contrato entre capas (para que la división no rompa nada)

- **`views/*` nunca importan de otro `views/*` sus funciones privadas** (hoy `ui/executive.py`
  importa `_fmt, _card, _chart_card, _chart_insight, _display_kpi_value` directamente de
  `ui/dashboard.py` — es exactamente el acoplamiento que `components/`+`format.py` deben
  eliminar). Tras la migración, `views/*` solo importan de `core/`, `visualization/`,
  `ui/components/`, `ui/layouts/`, `ui/format.py`.
- **`components/*` y `layouts/*` no leen `st.session_state` de claves de negocio** (sí pueden usar
  `key=` para widgets propios). El estado de negocio (`filters`, `focus_*`, `show_profile_inline`,
  etc.) se sigue leyendo/escribiendo en `views/*` y `app.py`, como hoy — no se mueve, porque
  moverlo es un cambio de comportamiento, no de estructura.
- **`ui/styles/theme.py` es la única fuente de `<style>` de tema base.** Un `<style>` adicional en
  un `views/*` solo puede *añadir* clases (como hoy hace `practical.py`), nunca redefinir
  `:root{--bg:...}`.
- **Ninguna función de `core/` recibe objetos de Streamlit** (ya es así hoy; se mantiene como
  regla explícita).

---

## 7. Cómo esta arquitectura cubre los hallazgos de 00 y 01

| Hallazgo (auditoría / FEATURES.md) | Cómo lo resuelve esta arquitectura |
|---|---|
| 3 sistemas de tema en paralelo | §4: uno solo, en `ui/styles/theme.py` |
| `ui/alerts.py` con import roto y huérfano | §3: se retira en la Fase A |
| Helpers `_fmt`/`_label` duplicados ~10 veces | §2/§5 Fase C: `ui/format.py` único |
| Doble implementación de "perfil individual" (`ui/dashboard._person_profile` vs. `ui/person_profile.render_person_profile`) | Al dividir `dashboard.py` (Fase E), `_person_profile` local queda expuesto como caso a decidir explícitamente: fusionarlo con `render_person_profile` reutilizando componentes, en vez de mantenerlo como segunda copia silenciosa. Se deja como tarea explícita de la Fase E, no implícita. |
| Estado de sesión disperso (~25 claves inicializadas ad-hoc en `app.py`) | No se resuelve en esta arquitectura de UI (es un cambio de `app.py`/estado, no de capas visuales); queda documentado como mejora futura fuera de alcance, igual que en la auditoría. |
| `ui/dashboard.py` como archivo monolítico de alto riesgo | §5 Fase E: dividido en 4 módulos por responsabilidad, misma lógica. |

---

## 8. No-objetivos explícitos de esta arquitectura

- No cambia ningún cálculo de `core/` (KPIs, insights, alertas, comparación, geografía, etc.).
- No cambia ninguna función de `visualization/charts.py` ni su firma.
- No introduce un framework de componentes nuevo (React, un design system externo, etc.) — sigue
  siendo Streamlit + HTML/CSS inyectado vía `st.markdown`, solo mejor organizado.
- No toca `ui/report_html.py` / `ui/interactive_report.py` (generación de HTML standalone) ni
  `ui/georeferencing.py` en esta ronda.
- No resuelve el estado de `BYPASS_AUTH_TEMPORARY` en `ui/login.py` (es una decisión de producto/
  seguridad, no de arquitectura de UI).
