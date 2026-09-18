"""El informe HTML trae lo mismo que sirve para decidir en el panel.

El export traía KPIs, gráficos universales y alertas, pero no las secciones
con las que se decide: cómo va cada uno contra su meta, qué cambió entre los
dos últimos periodos y quién lo explica, la estrategia por canal y los planes
de mejora con sus pasos. Aquí se exige que estén, que traigan sus gráficos y
que se descarten solas cuando el archivo no da para ellas.

PYTHONPATH=. python tests/informe_html_test.py
"""
import re
import warnings

import pandas as pd

from core.dashboard_engine import build_dashboard
from core.profile import profile_sheet
from ui.report_html import build_html_report

warnings.filterwarnings("ignore")


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _hoja_comercial():
    """Cinco regiones × seis meses, con meta: da para todas las secciones."""
    filas = []
    ritmo = {"R1": (5200, 4800), "R2": (6400, 6600), "R3": (5900, 6000), "R4": (9800, 9500), "R5": (4500, 4700)}
    for i, mes in enumerate(pd.date_range("2026-03-01", periods=6, freq="MS")):
        for region, (base, meta) in ritmo.items():
            filas.append({"Mes": mes, "Región": region,
                          "Altas": int(base * (1 - 0.03 * i if region == "R4" else 1 + 0.01 * i)),
                          "Meta": meta})
    item = profile_sheet(pd.DataFrame(filas), {"sheet_name": "Comercial", "workbook_name": "c.xlsx"})
    df, schema = item["processed"], item["profile"]["schema"]
    return df, schema, build_dashboard(df, item["profile"])


_CACHE = {}


def _informe():
    if "html" not in _CACHE:
        df, schema, dashboard = _hoja_comercial()
        _CACHE["html"] = build_html_report(df, schema, dashboard, "c.xlsx", "Comercial")
    return _CACHE["html"]


def test_las_secciones_de_decision_estan():
    html = _informe()
    for sid, titulo in (("cuadro-comparativo", "Cómo va cada"),
                        ("cambio-periodos", "Qué cambió entre"),
                        ("estrategia", "Estrategia por"),
                        ("planes", "Planes de mejora")):
        check(f"el informe trae la sección «{titulo}»", f'id="{sid}"' in html and titulo in html)
    check("y se puede llegar a ellas desde el menú lateral",
          all(f'href="#{sid}"' in html for sid in ("cuadro-comparativo", "cambio-periodos", "estrategia", "planes")))


def test_traen_sus_graficos_y_sus_cifras():
    html = _informe()
    check("hay gráficos de las secciones nuevas", html.count("VISUAL") >= 5)
    check("el motor de gráficos se incrusta UNA sola vez (el archivo abre sin internet)",
          html.count("plotly.js v") <= 1 and "Plotly.newPlot" in html)
    check("el cuadro compara contra la meta del archivo", "Cumplimiento = resultado ÷ meta" in html)
    check("con la referencia del grupo completo", "los 5 valores de «Región»" in html)
    check("los porcentajes de la tabla llevan su signo", _re_busca(r"<td>\d{2,3}[.,]\d%</td>", html))
    check("la estrategia trae el semáforo por región", 'class="canal-card"' in html and "Participación" in html)
    check("y las jugadas con su impacto", 'class="jugada-impacto"' in html)
    check("los planes traen pasos concretos", 'class="pasos"' in html and "Para cerrarlo:" in html)
    check("el cambio entre periodos nombra quién restó", "Más restaron" in html or "Más sumaron" in html)


def _re_busca(patron, texto):
    return bool(re.search(patron, texto))


def test_se_descartan_solas_sin_datos_para_ellas():
    """Un catálogo sin fechas ni meta no debe producir secciones vacías."""
    catalogo = pd.DataFrame({"Producto": [f"Plan {i}" for i in range(12)],
                             "Precio": [30000 + i * 1500 for i in range(12)],
                             "Categoría": ["Hogar", "Móvil"] * 6})
    item = profile_sheet(catalogo, {"sheet_name": "Catálogo", "workbook_name": "c.xlsx"})
    df, schema = item["processed"], item["profile"]["schema"]
    html = build_html_report(df, schema, build_dashboard(df, item["profile"]), "c.xlsx", "Catálogo")
    check("sin fechas no se inventa el cambio entre periodos", 'id="cambio-periodos"' not in html)
    check("y el informe se genera igual", "Indicadores clave" in html and len(html) > 10000)


if __name__ == "__main__":
    test_las_secciones_de_decision_estan()
    test_traen_sus_graficos_y_sus_cifras()
    test_se_descartan_solas_sin_datos_para_ellas()
    print("\nInforme HTML test completado sin errores.")
