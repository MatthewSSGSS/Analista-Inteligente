"""Portada, elección de modo y acceso en JavaScript, sin marcas de terceros.

Las tres pantallas se dibujan con `st.components.v2` (ui/components/escena.py
+ ui/web/). Lo que se exige:

- que la app no nombre a ninguna empresa: el acceso decía «Claro», «Panel
  Analítico Universal Claro», «cuenta Claro» y tenía de fondo una foto con
  el logo; el nombre vive en `core/marca.NOMBRE_APP`;
- que cada acción que manda el JavaScript (`data-accion`) sea una que Python
  sabe atender — un nombre cambiado de un lado dejaría el botón sin efecto;
- que sin `st.components.v2` (Streamlit viejo) se dibuje la versión clásica
  con sus botones y el flujo llegue al panel: nunca una pantalla sin salida.

PYTHONPATH=. python tests/pantallas_js_test.py
"""
import re
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

RAIZ = Path(__file__).resolve().parent.parent


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def test_sin_marcas():
    from core.marca import NOMBRE_APP
    check("el nombre es neutral", NOMBRE_APP and "claro" not in NOMBRE_APP.lower())
    textos = [p.read_text(encoding="utf-8") for p in (RAIZ / "ui").rglob("*") if p.suffix in (".py", ".js", ".css")]
    textos.append((RAIZ / "app.py").read_text(encoding="utf-8"))
    check("ninguna pantalla nombra la marca", not any(re.search(r"Claro<|cuenta Claro|Universal Claro|oficina_claro", t) for t in textos))
    check("la foto con el logo ya no está", not (RAIZ / "assets" / "images" / "oficina_claro.jpg").exists())


def test_acciones_del_javascript():
    web = RAIZ / "ui" / "web"
    for nombre in ("portada", "modos", "acceso"):
        js = (web / f"{nombre}.js").read_text(encoding="utf-8")
        check(f"{nombre}.js exporta la función de la pantalla", "export default function" in js)
    portada = (web / "portada.js").read_text(encoding="utf-8")
    check("la portada manda «comenzar»", set(re.findall(r'data-accion="([a-z]+)"', portada)) == {"comenzar"})
    modos = (web / "modos.js").read_text(encoding="utf-8")
    from ui.mode_choice import _MODOS
    check("cada modo del JavaScript lo atiende Python", set(re.findall(r'clave: "([a-z]+)"', modos)) == set(_MODOS))
    # Inicio y Resumen: cada botón del JS tiene su botón oculto en Python.
    home = (RAIZ / "ui" / "home.py").read_text(encoding="utf-8")
    ejecutivo = (RAIZ / "ui" / "executive.py").read_text(encoding="utf-8")
    for js, py, nombre in (("parte.js", home, "Inicio"), ("resumen.js", ejecutivo, "Resumen")):
        en_js = set(re.findall(r'data-accion="([a-z]+)"', (web / js).read_text(encoding="utf-8")))
        check(f"{nombre}: cada botón del JavaScript tiene su botón oculto", en_js and all(f'"{a}":' in py for a in en_js))


def test_version_clasica_sin_v2():
    from streamlit.testing.v1 import AppTest
    codigo = (
        "import ui.components.escena as e\n"
        "e.disponible = lambda: False\n"
        f"exec(open({str(RAIZ / 'app.py')!r}, encoding='utf-8').read())\n"
    )
    import ui.components.escena as escena
    original = escena.disponible  # AppTest corre en este mismo proceso: se restaura al final
    try:
        at = AppTest.from_string(codigo, default_timeout=120)
        at.run()
        check("sin v2 la portada clásica tiene su botón", [b.key for b in at.button] == ["landing_start_btn"])
        at.button(key="landing_start_btn").click().run()
        check("y los modos clásicos los suyos", {"choose_completo", "choose_territorial", "choose_logistica"} <= {b.key for b in at.button})
        at.button(key="choose_completo").click().run()
        check("y el flujo llega al panel", at.session_state["analysis_mode"] == "completo" and not at.exception)
    finally:
        escena.disponible = original


def test_con_v2_monta_la_escena():
    from streamlit.testing.v1 import AppTest
    from ui.components.escena import disponible
    if not disponible():
        print("SKIP escena: esta versión de Streamlit no tiene st.components.v2")
        return
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=120)
    at.run()
    check("con v2 la portada es la escena, sin la portada clásica",
          not at.exception and not any("landing-hero" in m.value for m in at.markdown))
    # El clic del JavaScript pulsa estos botones ocultos (en Streamlit Cloud el
    # aviso del componente no llegaba y la portada se quedaba pegada).
    check("con su botón oculto de respaldo", [b.key for b in at.button] == ["landing_start_btn"])
    at.button(key="landing_start_btn").click().run()
    check("que lleva a elegir el modo", {"choose_completo", "choose_territorial", "choose_logistica"} == {b.key for b in at.button})
    at.button(key="choose_completo").click().run()
    check("y de ahí al panel", at.session_state["analysis_mode"] == "completo" and not at.exception)


def test_todas_las_pantallas_existen():
    """Cada pantalla que la app monta con escena() tiene su .js con la función
    exportada: un nombre mal escrito dejaba la vista en blanco sin error."""
    import ast
    web = RAIZ / "ui" / "web"
    nombres = set()
    for py in list((RAIZ / "ui").rglob("*.py")) + [RAIZ / "app.py"]:
        for nodo in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if (isinstance(nodo, ast.Call) and getattr(nodo.func, "id", None) == "escena"
                    and nodo.args and isinstance(nodo.args[0], ast.Constant)):
                nombres.add(nodo.args[0].value)
    check("las vistas montan sus pantallas", {"portada", "modos", "acceso", "parte", "resumen", "atacar", "cuadro",
                                              "canales", "proyeccion", "cabecera", "caso", "calidad",
                                              "anomalias", "finanzas", "duelo", "analitica"} <= nombres)
    for n in sorted(nombres):
        js = web / f"{n}.js"
        check(f"{n}.js existe y exporta su función", js.exists() and "export default function" in js.read_text(encoding="utf-8"))


def test_datos_de_las_vistas():
    """Lo que reciben las pantallas es texto plano (sin HTML: el JS lo escapa)
    y trae lo que cada una dibuja."""
    import json
    import sys
    from datetime import date
    sys.path.insert(0, str(RAIZ / "tests"))
    from presentacion_test import _ventas
    from core.cuadro_comparativo import cuadro_comparativo
    from core.dashboard_engine import build_dashboard
    from core.forecast import pronosticar
    from core.planes import generar
    from ui.cuadro_comparativo import _datos_cuadro
    from ui.forecast import _datos_proyeccion
    from ui.planes import _clave_plan, _datos_atacar, _signo, filas_plan_de_accion

    df, perfil = _ventas()
    schema = perfil["schema"]
    db = build_dashboard(df, perfil)

    r = generar(df, schema, db)
    filas = filas_plan_de_accion(r["planes"], {}, {_clave_plan(x): [] for x in r["planes"]}, date.today())
    at = _datos_atacar(r, r["planes"], filas, r.get("gerencia"))
    check("Qué atacar: diagnóstico, oportunidades, plan y tablero de 3 columnas",
          at["diag"]["titular"] and at["oportunidades"] and at["plan"]["total"] >= 0 and len(at["tablero"]) == 3)
    check("Qué atacar: sin HTML", "<" not in json.dumps(at, ensure_ascii=False))
    check("un efecto que no se movió se dice «0», no «−0»", _signo(0.0) == "0" and _signo(-0.2) == "0")

    cu = _datos_cuadro(cuadro_comparativo(df, schema, "Region", "Ingresos"))
    check("Cómo va: una fila por región, con barra, estado y mini gráfico",
          len(cu["filas"]) == 4 and all(0 <= f["barra"] <= 100 and f["estado"] and f["serie"] for f in cu["filas"]))
    check("Cómo va: la referencia es la meta (100%)", cu["marca_txt"] == "100% de la meta")
    check("Cómo va: sin HTML", "<" not in json.dumps(cu, ensure_ascii=False))

    res = pronosticar(df, schema, "Ingresos", horizonte=3)
    tarjetas = [{"label": "jul · real", "value": "1", "delta": None}, {"label": "ago · estimado", "value": "2", "delta": "+1%"},
                {"label": "Lo más probable", "value": "1 – 3", "delta": None}, {"label": "Confianza", "value": "Media", "delta": None}]
    py = _datos_proyeccion(res, "Ingresos", tarjetas, "frase", "positive", None, res.get("error_tipico"))
    futuros = [x for x in py["puntos"] if x["futuro"]]
    check("Proyección: lo real y los 3 meses estimados con su rango",
          len(futuros) == 3 and all(x["lo"] <= x["v"] <= x["hi"] for x in futuros))
    check("Proyección: cada punto trae su cambio frente al mes anterior (para escribirlo en el gráfico)",
          all(x["vs"] for x in py["puntos"][1:]))
    check("Proyección: una ficha por mes estimado, con lo más probable, extremos y vs hoy",
          len(py["meses"]) == 3 and all(m["extremos"] and m["vs_hoy"] for m in py["meses"]))
    check("Proyección: con 19 meses, cada estimado se compara con el mismo mes del año pasado",
          all(m["vs_anio"] and m["anio_t"] for m in py["meses"]))
    check("Proyección: contexto del histórico (promedio, mejor, peor, frente a hace un año)",
          {"Mejor mes", "Peor mes", "Frente a hace un año"} <= {c["n"] for c in py["contexto"]})

    # Seguimiento de un caso: puesto sobre TODO el grupo, serie con el promedio del grupo.
    from core.universal_analysis import semantic_map
    from visualization.charts import metric_candidates
    from ui.person_profile import _caso_que_pide_atencion, _datos_caso
    filas_sur = df[df["Region"].astype(str).str.strip() == "Sur"]
    caso = _datos_caso(df, schema, "Region", "Sur", filas_sur, "Ingresos", "región", "",
                       metric_candidates(df, schema), semantic_map(schema))
    check("Seguimiento: su puesto entre las 4 regiones", caso["puesto"]["total"] == 4 and 1 <= caso["puesto"]["posicion"] <= 4)
    check("Seguimiento: serie mes a mes con el promedio del grupo", caso["serie"] and all(x["g"] is not None for x in caso["serie"]))
    check("Seguimiento: sin HTML", "<" not in json.dumps(caso, ensure_ascii=False))
    import pandas as pd
    x = pd.DataFrame({"Fecha": pd.to_datetime(["2026-06-05", "2026-06-05", "2026-07-05"]), "Q": ["A", "B", "A"], "V": [10.0, 50.0, 4.0]})
    nombre, _ = _caso_que_pide_atencion(x, {"dates": ["Fecha"]}, "Q", "V")
    check("Seguimiento abre en quien cayó de verdad, no en quien no tiene el último mes", nombre == "A")

    # Calidad, anomalías y finanzas.
    from ui.anomalies import _datos_anomalias, _datos_finanzas
    from ui.quality import _datos_calidad
    ca = _datos_calidad(perfil)
    check("Calidad: puntaje y columna por columna", 0 <= ca["puntaje"] <= 100 and ca["columnas"])
    an = _datos_anomalias(db["anomalies"], schema, df)
    check("Anomalías: cuenta las DETECTADAS, no los registros", an["total_n"] == len(db["anomalies"]) and an["registros"] == f"{len(df):,}")
    fi = _datos_finanzas(db["statistics"], schema)
    check("Finanzas: una tarjeta por métrica con su caja", fi["metricas"] and all(0 <= m["x"]["q1"] <= m["x"]["q3"] <= 100 for m in fi["metricas"]))


def test_colores_de_seccion():
    """Cada vista tiene su color y su clave estable en la barra; verde y rojo
    quedan para bien/mal, así que ninguna sección los usa."""
    from ui.components.colores import color_de, slug
    vistas = ["🏠 Inicio", "📋 Resumen", "🎯 Qué atacar", "📊 Cómo va cada uno", "📈 Canales", "🔮 Proyección",
              "🗺️ Georreferenciación", "🔎 Seguimiento de un caso", "🤖 Asistente IA", "⬇️ Exportar",
              "🧮 Datos", "✅ Calidad del dato", "🗂️ Varias hojas", "⚔️ Comparar personas", "🧾 Descripción",
              "🔬 Analítica", "🚨 Anomalías", "💵 Finanzas", "🏢 Estructura"]
    claves = [slug(v) for v in vistas]
    check("cada vista tiene una clave distinta y válida para CSS",
          len(set(claves)) == len(claves) and all(re.fullmatch(r"[a-z0-9_]+", c) for c in claves))
    check("las secciones principales tienen colores distintos",
          len({color_de(v) for v in vistas[:9]}) == 9)
    check("ninguna sección usa el verde de «va bien»", all(color_de(v).upper() not in {"#22A06B", "#16A34A"} for v in vistas))
    tabs = (RAIZ / "ui" / "layouts" / "tabs.py").read_text(encoding="utf-8")
    check("la barra usa claves por nombre (no por posición)", 'key=f"nav_btn_{slug(etiqueta)}"' in tabs)


def test_regiones_naturales():
    """«Caribe», «Andina», «Pacífico»… son regiones naturales de Colombia, no
    lugares de otro país: el mapa decía «no son de Colombia» y las ubicaba mal."""
    import pandas as pd
    import core.territorio as T
    check("se reconocen con sus variantes", [T.region_natural(x) for x in
          ["Caribe", "REGIÓN PACÍFICO", "Llanos Orientales", "Amazonía", "Centro", "R1", "Antioquia"]]
          == ["Caribe", "Pacífica", "Orinoquía", "Amazonía", None, None, None])
    todos = sorted(c for cods in T.REGIONES_NATURALES.values() for c in cods)
    check("las 6 regiones cubren los 33 departamentos, sin repetir", todos == sorted(T.departamentos()["cod_dpto"]))
    df = pd.DataFrame({"Region": ["Caribe", "Andina", "Pacífico", "Orinoquía", "Caribe"], "Ventas": [1, 2, 3, 4, 5]})
    info = T.regiones_naturales(df, {})
    check("se encuentra la columna de regiones", info and info["columna"] == "Region" and not info["sin_ubicar"])
    otra = pd.DataFrame({"Zona": ["Norte", "Sur", "Centro", "Caribe"]})
    check("una columna con solo una región entre muchas no se toma por regiones", T.regiones_naturales(otra, {}) is None)


_APP_ANALITICA = '''
import json, sys
sys.path.insert(0, {tests!r})
import streamlit as st
import ui.explorer as X
from presentacion_test import _ventas
if st.session_state.get("_modo", "js") == "js":
    X.disponible = lambda: True
    def _captura(nombre, datos, clave):
        st.session_state.setdefault("_capturas", []).append((nombre, json.loads(json.dumps(datos, default=str))))
        return None
    X.escena = _captura
else:
    X.disponible = lambda: False
df, perfil = _ventas()
X.render_explorer(df, perfil["schema"])
'''


def test_analitica():
    """«🔬 Analítica» en JavaScript: el selector de lentes y la lectura de cada
    una (base, cifras, gráfico, qué dice) son datos en texto plano; el clic en
    una tarjeta pulsa su botón oculto y cambia de lente; sin JavaScript, cada
    lente dibuja su versión clásica en Plotly."""
    import json
    from streamlit.testing.v1 import AppTest
    codigo = _APP_ANALITICA.format(tests=str(RAIZ / "tests"))
    graficos = {"ranking": "barras", "evolucion": "lineas", "periodos": "barras", "cruzada": "calor",
                "cumplimiento": "barras", "relacion": "puntos", "distribucion": "cajas"}
    for lente, tipo in graficos.items():
        at = AppTest.from_string(codigo, default_timeout=120)
        at.session_state["an__lente"] = lente
        at.run()
        capturas = at.session_state["_capturas"]
        lectura = next(d for n, d in capturas if d.get("modo") == "lectura")
        selector = next(d for n, d in capturas if d.get("modo") == "lentes")
        check(f"Analítica · {lente}: dibuja «{tipo}» con su qué dice y sin errores",
              not at.exception and lectura["grafico"]["tipo"] == tipo and lectura["hallazgos"] and lectura["base"])
        check(f"Analítica · {lente}: sin HTML", "<" not in json.dumps(lectura, ensure_ascii=False))
        check(f"Analítica · {lente}: el selector marca la lente abierta",
              [l["clave"] for l in selector["lentes"] if l["activa"]] == [lente])
    at = AppTest.from_string(codigo, default_timeout=120)
    at.session_state["an__lente"] = "periodos"
    at.run()
    lectura = next(d for n, d in at.session_state["_capturas"] if d.get("modo") == "lectura")
    check("Periodo vs. periodo: tres cifras y barras que divergen desde el centro",
          len(lectura["kpis"]) == 3 and lectura["grafico"]["divergente"])
    at.button(key="an__ir_evolucion").click().run()
    check("el clic en una tarjeta (su botón oculto) abre esa lente", at.session_state["an__lente"] == "evolucion")
    for lente in graficos:
        at = AppTest.from_string(codigo, default_timeout=120)
        at.session_state["_modo"] = "clasico"
        at.session_state["an__lente"] = lente
        at.run()
        check(f"Analítica clásica · {lente}: su gráfico de siempre", not at.exception and len(at.get("plotly_chart")) == 1)


def main():
    test_sin_marcas()
    test_acciones_del_javascript()
    test_todas_las_pantallas_existen()
    test_colores_de_seccion()
    test_regiones_naturales()
    test_datos_de_las_vistas()
    test_analitica()
    test_con_v2_monta_la_escena()
    test_version_clasica_sin_v2()
    print("\nPantallas JS test completado sin errores.")


if __name__ == "__main__":
    main()
