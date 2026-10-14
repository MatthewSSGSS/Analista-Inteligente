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
                                              "canales", "proyeccion", "cabecera"} <= nombres)
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


def main():
    test_sin_marcas()
    test_acciones_del_javascript()
    test_todas_las_pantallas_existen()
    test_datos_de_las_vistas()
    test_con_v2_monta_la_escena()
    test_version_clasica_sin_v2()
    print("\nPantallas JS test completado sin errores.")


if __name__ == "__main__":
    main()
