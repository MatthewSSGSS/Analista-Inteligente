import io
import pandas as pd

from core.loader import load_workbook
from core.profile import profile_sheet
from core.dashboard_engine import build_dashboard
from core.comparison_engine import prepare_comparison, build_comparison
from visualization.charts import trend, ranking, donut, histogram, scatter, correlation, wide_month_chart
from core.geo_engine import supports_georeferencing, geographic_summary
from ui.dashboard import render_dashboard


def upload(name, df, sheet="Hoja1"):
    b = io.BytesIO()
    df.to_excel(b, index=False, sheet_name=sheet)
    return type("Upload", (), {"getvalue": lambda self: b.getvalue(), "name": name})()


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def main():
    sales = pd.DataFrame({
        "Fecha": pd.date_range("2026-01-01", periods=6, freq="MS"),
        "Ciudad": ["Bogotá", "Medellín", "Bogotá", "Cali", "Bogotá", "Medellín"],
        "Ingresos": [100000, 120000, 110000, 90000, 130000, 140000],
        "Cantidad": [10, 12, 11, 9, 13, 14],
        "Cedula": [10000001, 10000002, 10000003, 10000004, 10000005, 10000006],
    })
    item = profile_sheet(sales, {"sheet_name": "Ventas", "workbook_name": "ventas_2026.xlsx"})
    df = item["processed"]
    profile = item["profile"]
    schema = profile["schema"]
    check("detecta fecha", "Fecha" in schema["dates"])
    check("detecta ingresos como métrica", "Ingresos" in schema["metrics"])
    check("no usa cédula como métrica", "Cedula" not in schema["metrics"] and "Cedula" in schema["ids"])
    dashboard = build_dashboard(df, profile)
    check("construye dashboard", isinstance(dashboard, dict))
    check("crecimiento finito", dashboard["growth"] is None or pd.notna(dashboard["growth"]))

    for name, fn in [
        ("tendencia", lambda: trend(df, schema)),
        ("ranking", lambda: ranking(df, schema)),
        ("donut", lambda: donut(df, schema)),
        ("histograma", lambda: histogram(df, schema)),
        ("scatter", lambda: scatter(df, schema)),
        ("correlación", lambda: correlation(df, schema)),
    ]:
        check(f"gráfico {name} no falla", fn() is not None or name == "correlación")

    wide = pd.DataFrame({
        "Región": ["Antioquia", "Cundinamarca"],
        "Enero": [570, 300], "Febrero": [451, 400], "Marzo": [500, 450],
        "Abril": [600, 500], "Mayo": [700, 600], "Junio": [800, 700],
        "Julio": [900, 800], "Agosto": [1000, 900], "Septiembre": [1100, 1000],
        "Octubre": [1200, 1100], "Noviembre": [1300, 1200], "Diciembre": [1400, 1300],
    })
    wi = profile_sheet(wide, {"sheet_name": "Resumen", "workbook_name": "resumen_2026.xlsx"})
    ws = wi["profile"]["schema"]
    wd = build_dashboard(wi["processed"], wi["profile"])
    check("meses anchos no se vuelven métricas falsas", not ws["metrics"])
    check("gráfico Enero-Diciembre disponible", wide_month_chart(wi["processed"], ws) is not None)
    check("variación mensual usa últimos dos meses", wd["growth"] == 8.0)

    zero = pd.DataFrame({"Fecha": pd.to_datetime(["2026-01-01", "2026-02-01"]), "Ingresos": [0, 100]})
    zi = profile_sheet(zero, {"sheet_name": "Cero", "workbook_name": "cero.xlsx"})
    zd = build_dashboard(zi["processed"], zi["profile"])
    check("base cero no produce porcentaje inválido", zd["change_analysis"]["pct"] is None)

    wb_2025 = load_workbook(upload("2025-enero.xlsx", pd.DataFrame({"Fecha": ["2025-01-01"], "Ingresos": [100]})))
    wb_2024 = load_workbook(upload("2024-enero.xlsx", pd.DataFrame({"Fecha": ["2024-01-01"], "Ingresos": [80]})))
    prepared = prepare_comparison([wb_2025, wb_2024])
    check("comparación ordena fechas", [x["filename"] for x in prepared["files"]] == ["2024-enero.xlsx", "2025-enero.xlsx"])
    result = build_comparison(prepared)
    check("comparación calcula cambio", result["recent_metrics"][0]["cambio_pct"] == 25.0)

    # Loader/header inference smoke test.
    raw = io.BytesIO()
    pd.DataFrame([
        ["Resumen de ventas"],
        ["Fecha", "Ciudad", "Ingresos", "Cedula"],
        ["01/01/2026", "Bogotá", "100.000", "10000001"],
    ]).to_excel(raw, index=False, header=False, sheet_name="Ventas")
    obj = type("Upload", (), {"getvalue": lambda self: raw.getvalue(), "name": "header_test.xlsx"})()
    loaded = load_workbook(obj)
    ls = loaded["sheets"]["Ventas"]["profile"]["schema"]
    check("inferencia de encabezado funciona", "Fecha" in ls["dates"] and "Ingresos" in ls["metrics"])

    # Empty/all-missing selections must never crash KPI calculations.
    empty_like = pd.DataFrame({"Fecha": pd.to_datetime(["2026-01-01", "2026-02-01"]), "Ingresos": [None, None]})
    ei = profile_sheet(empty_like, {"sheet_name": "Vacío", "workbook_name": "vacio.xlsx"})
    ed = build_dashboard(ei["processed"], ei["profile"])
    check("selección sin valores numéricos no rompe el dashboard", isinstance(ed, dict))
    check("KPI sin datos devuelve valor seguro", all(pd.notna(k.get("raw", 0)) for k in ed.get("kpis", [])))

    # Regresión: sin ninguna columna categórica válida para desglosar (aquí
    # solo hay un identificador y una métrica), core/performance.py::analyze
    # devuelve None a propósito — dashboard["performance"] queda en None (la
    # clave EXISTE, con valor None). ui/dashboard.py tenía un
    # `dashboard.get("performance", {})` ahí: ese default solo aplica cuando
    # la clave falta, no cuando vale None, así que terminaba llamando
    # `.get("dimension")` sobre None y tronaba con AttributeError en
    # producción (pestaña 🏆 Desempeño). Reproduce exactamente ese caso.
    no_dim = pd.DataFrame({"Cedula": [10000001, 10000002, 10000003], "Ingresos": [100, 200, 150]})
    ndi = profile_sheet(no_dim, {"sheet_name": "SinDimension", "workbook_name": "sin_dimension.xlsx"})
    ndd = build_dashboard(ndi["processed"], ndi["profile"])
    check("caso sin dimensión válida deja performance en None", ndd.get("performance") is None)
    render_dashboard(ndi["processed"], ndd)
    check("performance=None no rompe render_dashboard (pestaña Desempeño)", True)

    # "Periodo" numérico AAAAMM (202608 = agosto 2026), típico de exportes de
    # BI/ERP: antes no se reconocía como fecha (ni excel_serial ni
    # unix_timestamp caen en ese rango de valores), así que nunca aparecía
    # "Cambio reciente"/evolución en el dashboard para ese tipo de archivo.
    periodo_df = pd.DataFrame({
        "periodo": [202608] * 3 + [202607] * 3 + [202606] * 3,
        "ventas": [100, 110, 120, 90, 95, 100, 80, 85, 90],
    })
    pdi = profile_sheet(periodo_df, {"sheet_name": "Periodo", "workbook_name": "periodo.xlsx"})
    check("columna 'periodo' AAAAMM se detecta como fecha", "periodo" in pdi["profile"]["schema"]["dates"])
    check("'periodo' ya fecha no queda también como métrica", "periodo" not in pdi["profile"]["schema"]["metrics"])
    pdd = build_dashboard(pdi["processed"], pdi["profile"])
    check("con 'periodo' como fecha, sí aparece Cambio reciente", pdd["growth"] is not None)
    # Control: una columna numérica en el MISMO rango de valores pero sin
    # nombre relacionado a fecha/periodo no debe interpretarse como AAAAMM
    # (evita falsos positivos sobre una cantidad/código cualquiera).
    control_df = pd.DataFrame({"Cantidad": [202608, 202607, 202606, 202605], "ventas": [1, 2, 3, 4]})
    cdi = profile_sheet(control_df, {"sheet_name": "Control", "workbook_name": "control.xlsx"})
    check("columna numérica sin nombre de fecha no se confunde con AAAAMM", "Cantidad" not in cdi["profile"]["schema"]["dates"])

    # Regresión de un crash real en producción: un archivo cuya ÚNICA columna
    # numérica es la fecha ("periodo" AAAAMM). El motor semántico la listaba
    # como métrica por su cuenta (schema["semantic"]["metrics"]), que es la
    # lista que la mayoría de la app lee con preferencia — así la métrica
    # principal y la fecha terminaban siendo la MISMA columna, y
    # core/executive.py::_monthly hacía df[[col, col]] → pandas recibía un
    # DataFrame con la columna repetida en to_datetime() y tronaba con
    # "cannot assemble with duplicate keys".
    solo_periodo = pd.DataFrame({"periodo": [202608] * 3 + [202607] * 3 + [202606] * 3})
    spi = profile_sheet(solo_periodo, {"sheet_name": "SoloPeriodo", "workbook_name": "solo_periodo.xlsx"})
    ss = spi["profile"]["schema"]
    check("una columna fecha no aparece como métrica semántica", "periodo" not in (ss.get("semantic", {}).get("metrics") or []))
    build_dashboard(spi["processed"], spi["profile"])
    check("archivo con solo una columna de fecha no rompe build_dashboard", True)

    # Regresión de un crash real en producción: una columna de fechas donde
    # cada fila trae un desfase horario distinto ("+00:00" en unas, "-05:00"
    # en otras, "Z" en otras). pandas se niega a construir la columna con
    # zonas mezcladas ("Mixed timezones detected") y tumbaba la carga del
    # archivo completo. Se resolvió quitando la hora (decisión de negocio:
    # en estos informes solo importa la fecha), lo que elimina el conflicto
    # de raíz. Ver core/dates.py::date_only.
    from core.dates import detect_date
    mezcla = pd.Series([
        "2026-01-15 10:00:00+00:00",
        "2026-06-20 23:30:00-05:00",   # registro nocturno: debe quedarse en el 20
        "2026-03-10 08:15:00Z",
        "2026-04-02 14:45:00",         # sin zona horaria
    ])
    dt_mix, rate_mix, _ = detect_date(mezcla, "Fecha")
    check("zonas horarias mezcladas ya no rompen la lectura", dt_mix is not None and rate_mix == 1.0)
    check("las fechas quedan sin hora", (dt_mix.dt.normalize() == dt_mix).all())
    check("un registro nocturno no se corre al día siguiente", str(dt_mix.iloc[1].date()) == "2026-06-20")

    # El arreglo anterior (solo en core/dates.py) NO alcanzaba: la
    # clasificación semántica corre ANTES que la conversión, dentro de
    # detect_schema(), y reventaba primero en semantic_engine._date_rate.
    # Esta prueba recorre el flujo COMPLETO de carga y, además, convierte
    # el aviso de pandas en error para reproducir el pandas de producción
    # (en el entorno de desarrollo esa misma situación solo advierte, que
    # es justo por lo que el fallo se escapó a producción la primera vez).
    import io as _io
    import warnings as _warnings
    from core.loader import load_workbook as _load_workbook
    _csv = (
        "Ref,Fecha,Venta\n"
        "D01,2026-01-15 10:00:00+00:00,100\n"
        "D02,2026-06-20 23:30:00-05:00,340\n"
        "D03,2026-03-10 08:15:00Z,120\n"
        "D04,2026-04-02 14:45:00,210\n"
    ).encode("utf-8")
    _upload = type("Upload", (), {"getvalue": lambda self: _csv, "name": "zonas.csv"})()
    with _warnings.catch_warnings():
        _warnings.filterwarnings("error", message=".*mixed time zones.*")
        _warnings.filterwarnings("error", message=".*Mixed timezones.*")
        _tz_item = _load_workbook(_upload)["sheets"]["CSV"]
    check("carga completa con zonas mezcladas no rompe (simulando pandas de producción)",
          list(_tz_item["processed"]["Fecha"].astype(str)) == ["2026-01-15", "2026-06-20", "2026-03-10", "2026-04-02"])

    # La normalización ocurre en la ENTRADA (core/cleaner.py::normalize_timezones),
    # antes de cualquier otra etapa, y pasa todo a hora de Colombia (UTC-5).
    from core.cleaner import normalize_timezones
    _tz = pd.DataFrame({"F": [
        "2026-01-15 10:00:00+00:00",   # UTC 10:00  -> Colombia 05:00, mismo día
        "2026-01-15 02:00:00+00:00",   # UTC 02:00  -> Colombia 21:00 del día anterior
        "2026-06-20 23:30:00-05:00",   # ya viene en hora Colombia: no se mueve
        "2026-05-05T14:00:00Z",        # otro formato (T y Z) en la misma columna
    ]})
    _conv = normalize_timezones(_tz)
    check("se convierte a hora de Colombia (UTC-5)", _conv == ["F"] and str(_tz["F"].iloc[0]) == "2026-01-15 05:00:00")
    check("una hora UTC de madrugada retrocede al día anterior en Colombia", str(_tz["F"].iloc[1]) == "2026-01-14 21:00:00")
    check("una hora que ya venía en Colombia no se mueve", str(_tz["F"].iloc[2]) == "2026-06-20 23:30:00")
    check("formatos distintos en la misma columna se leen igual", str(_tz["F"].iloc[3]) == "2026-05-05 09:00:00")
    # Control: nada que no sea una fecha con zona debe tocarse.
    _intacto = pd.DataFrame({"Codigo": ["D3243.00002", "D3244.00013", "D3251.00007"],
                             "Hora": ["10:00", "14:30", "08:15"],
                             "Fecha": ["2026-01-15 10:00:00", "2026-06-20 14:30:00", "2026-03-10 08:15:00"]})
    _antes = {c: list(_intacto[c]) for c in _intacto.columns}
    check("columnas sin zona horaria quedan intactas",
          normalize_timezones(_intacto) == [] and all(list(_intacto[c]) == _antes[c] for c in _intacto.columns))

    # Los casos que hicieron fallar los intentos anteriores: la zona horaria
    # aparece en POCAS filas, o más abajo de las primeras que se miraban.
    # Se revisa la columna entera y basta un valor con zona para actuar.
    def _sin_zona(serie):
        return int(serie.astype(str).str.contains(r"(?:Z|[+-]\d{2}:?\d{2})\s*$", regex=True).sum()) == 0

    _rara = pd.DataFrame({"F": ["2026-01-15 10:00:00"] * 300 + ["2026-06-20 08:00:00+00:00"]})
    check("una sola fila con zona, en la posición 301, también se normaliza",
          normalize_timezones(_rara) == ["F"] and _sin_zona(_rara["F"]))

    # Red de seguridad: valores que NO se pueden interpretar como fecha
    # igual deben quedar sin zona, para que nada aguas abajo tropiece.
    _rotas = pd.DataFrame({"F": ["15/13/2026 10:00:00+00:00", "xxx 10:00:00+02:00",
                                 "2026-06-20 23:30:00-05:00", "sin dato"]})
    normalize_timezones(_rotas)
    check("hasta las fechas ilegibles quedan sin zona horaria", _sin_zona(_rotas["F"]))

    # Formatos que la versión basada en expresiones regulares NO reconocía y
    # que dejaban pasar la zona horaria intacta: desfase de dos dígitos y
    # zonas con nombre. La detección ya no adivina con un patrón, le pregunta
    # a pandas (core/cleaner.py::_valor_tiene_zona), que es quien lanza el
    # error y por tanto quien sabe qué considera una zona horaria.
    def _pandas_ve_zona(serie):
        for _v in pd.unique(serie.dropna()):
            try:
                if pd.Timestamp(_v).tzinfo is not None:
                    return True
            except Exception:
                pass
        return False

    for _etiqueta, _valores in {
        "desfase de dos dígitos (-05)": ["2026-01-15 10:00:00-05", "2026-06-20 14:30:00+00:00"],
        "zona con nombre (UTC)": ["2026-01-15 10:00:00 UTC", "2026-06-20 14:30:00-05:00"],
        "zona con nombre (GMT)": ["2026-01-15 10:00:00 GMT", "2026-06-20 14:30:00"],
        "GMT con desplazamiento": ["2026-01-15 10:00 GMT-5", "2026-06-20 14:30:00Z"],
    }.items():
        _d = pd.DataFrame({"F": _valores})
        normalize_timezones(_d)
        check(f"se normaliza: {_etiqueta}", not _pandas_ve_zona(_d["F"]))

    plans = pd.DataFrame({
        "Categoría": ["Hogar", "Hogar"],
        "Segmento": ["Residencial", "Residencial"],
        "Plan": ["100M", "300M"],
        "Precio": [50000, 70000],
    })
    pi = profile_sheet(plans, {"sheet_name": "Planes", "workbook_name": "planes.xlsx"})
    geo_ok, _ = supports_georeferencing(pi["processed"], pi["profile"]["schema"])
    check("catálogo de planes no muestra georeferenciación", not geo_ok)

    geo_df = pd.DataFrame({
        "Ciudad": ["Bogotá", "Medellín"],
        "Ingresos": [100, 200],
    })
    gi = profile_sheet(geo_df, {"sheet_name": "Ventas", "workbook_name": "ventas.xlsx"})
    geo_ok, _ = supports_georeferencing(gi["processed"], gi["profile"]["schema"])
    check("datos con ciudad habilitan georeferenciación", geo_ok)

    # La ciudad metida dentro del nombre del punto de venta: el archivo no
    # tiene columna Ciudad, pero el lugar está escrito ahí y debe ubicarse.
    puntos = [
        "MC MULTICELL SAS CIENEGA MAGDALENA", "DANCELL RIOHACHA LA GUAJIRA",
        "COMMUTE SAS SOLEDAD ATLANTICO", "INVERSIONES GERA SAS CARTAGENA",
        "CELUNORTE COMUNICACIONES SAS SINCELEJO SUCRE",
    ]
    pdv = pd.DataFrame({"NOMBREPUNTO": puntos * 2, "Ventas": range(10)})
    pdv_i = profile_sheet(pdv, {"sheet_name": "Puntos", "workbook_name": "puntos.xlsx"})
    geo_ok, geo_meta = supports_georeferencing(pdv_i["processed"], pdv_i["profile"]["schema"])
    check("la ciudad dentro del nombre del punto habilita el mapa", geo_ok)
    check("se identifica la columna que contiene el lugar",
          geo_meta["columns"].get("embedded") == "NOMBREPUNTO")

    resumen = geographic_summary(pdv_i["processed"], pdv_i["profile"]["schema"], "Ventas")
    ubicados = set(resumen["table"]["_geo_label"]) if not resumen["table"].empty else set()
    check("se ubican los cinco puntos", len(ubicados) == 5)
    check("un nombre mal escrito igual se reconoce (CIENEGA → Ciénaga)", "Ciénaga" in ubicados)
    check("el municipio gana sobre el departamento (Sincelejo, no Sucre)", "Sincelejo" in ubicados)

    # El nombre de la columna no importa: lo que decide es el contenido. El
    # mismo archivo con el encabezado que sea tiene que ubicarse igual.
    for encabezado in ("Sucursal", "Razón Social", "Detalle", "Columna1", "Unnamed: 3"):
        otro = pd.DataFrame({encabezado: puntos * 2, "Ventas": range(10)})
        otro_i = profile_sheet(otro, {"sheet_name": "H", "workbook_name": "h.xlsx"})
        geo_ok, geo_meta = supports_georeferencing(otro_i["processed"], otro_i["profile"]["schema"])
        check(f"se ubica igual con la columna llamada '{encabezado}'",
              geo_ok and geo_meta["columns"].get("embedded") == encabezado)

    # Una columna llamada "Zona" o "Región" que en realidad trae nombres de
    # punto de venta se lleva el camino de geocodificación, que no resuelve
    # nada con esos textos. El archivo no puede quedarse sin mapa por eso.
    zona = pd.DataFrame({"Zona": puntos * 2, "Ventas": range(10)})
    zona_i = profile_sheet(zona, {"sheet_name": "Z", "workbook_name": "z.xlsx"})
    resumen_zona = geographic_summary(zona_i["processed"], zona_i["profile"]["schema"], "Ventas")
    ubicados_zona = set(resumen_zona["table"]["_geo_label"]) if not resumen_zona["table"].empty else set()
    check("una columna 'Zona' con nombres de punto igual se ubica", len(ubicados_zona) == 5)
    check("y se etiqueta por municipio, no por la frase completa", "Ciénaga" in ubicados_zona)

    # El apellido no es una ubicación: ubicar personas por su apellido sería
    # peor que no ubicarlas.
    personas = pd.DataFrame({
        "Nombre completo": ["Juan Córdoba Gómez", "María Pereira López", "Ana Santander Ruiz",
                            "Luis Bolívar Díaz", "Eva Sucre Mora"],
        "Ventas": [1, 2, 3, 4, 5],
    })
    per_i = profile_sheet(personas, {"sheet_name": "Equipo", "workbook_name": "equipo.xlsx"})
    geo_ok, _ = supports_georeferencing(per_i["processed"], per_i["profile"]["schema"])
    check("los apellidos que son municipios no se toman como ubicación", not geo_ok)

    # El veredicto ejecutivo: dónde está la frontera entre "cambió" y "sigue
    # igual". Un -0,6% no es un declive, pero tampoco es un empate: decirlo
    # como "estable con tendencia a la baja" es lo que distingue vigilar de
    # no mirar.
    def _veredicto(variacion, columna="ALTAS"):
        base = 100000.0
        vd = pd.DataFrame({"Fecha": ["2026-05-10", "2026-06-10"],
                           columna: [base, base * (1 + variacion / 100)]})
        vi = profile_sheet(vd, {"sheet_name": "H", "workbook_name": "h.xlsx"})
        return build_dashboard(vi["processed"], vi["profile"])["executive"]

    check("una caída del 1% ya es un declive", _veredicto(-1.0)["status"] == "negative")
    check("una subida del 1% ya es una mejora", _veredicto(1.0)["status"] == "positive")
    check("por debajo del 1% no se declara cambio", _veredicto(-0.6)["status"] == "neutral")
    check("pero sí se dice hacia dónde va",
          "tendencia a la baja" in _veredicto(-0.6)["headline"])
    check("y al alza cuando sube poco", "tendencia al alza" in _veredicto(0.4)["headline"])
    check("sin variación se dice sin variación", "sin variación" in _veredicto(0.0)["headline"])
    check("la etiqueta del estado acompaña al titular",
          _veredicto(-0.6)["status_label"] == "Estable con tendencia a la baja")

    # En días de mora o quejas, subir no es mejorar.
    check("más mora es un declive, no una mejora",
          _veredicto(8.0, "DiasMora")["status"] == "negative")
    check("y se dice que empeoró", "empeoró" in _veredicto(8.0, "DiasMora")["headline"])
    check("menos mora sí es una mejora", _veredicto(-8.0, "DiasMora")["status"] == "positive")

    _navegacion_de_modos()
    print("\nSmoke test completado sin errores.")


def _navegacion_de_modos():
    """Que cada tarjeta del home lleve a su ruta, y que la ruta exista.

    Son dos piezas en archivos distintos —el botón devuelve una cadena en
    `ui/mode_choice.py`, y `app.py` decide qué dibujar con ella— unidas por
    un texto suelto. Renombrar uno de los dos lados deja el botón sin hacer
    nada y no lo nota nadie hasta que alguien lo pulsa, así que se comprueba
    el recorrido entero: clic → valor devuelto → función que lo atiende.
    """
    import ast
    import io as _io

    import streamlit as _st
    from ui.mode_choice import render_mode_choice

    boton_real = _st.button
    try:
        for clave, esperado in (("choose_practico", "practico"),
                                ("choose_avanzado", "avanzado"),
                                ("choose_territorial", "territorial")):
            _st.button = lambda *a, **k: k.get("key") == clave
            check(f"la tarjeta '{esperado}' devuelve su modo", render_mode_choice() == esperado)
        _st.button = lambda *a, **k: False
        check("sin clic no se elige ningún modo", render_mode_choice() is None)
    finally:
        _st.button = boton_real

    # Y que app.py atienda cada modo con una función de render.
    arbol = ast.parse(_io.open("app.py", encoding="utf-8").read())
    rutas = {}
    for nodo in ast.walk(arbol):
        if not (isinstance(nodo, ast.If) and isinstance(nodo.test, ast.Compare)):
            continue
        izquierda = nodo.test.left
        derecha = nodo.test.comparators[0]
        if (isinstance(izquierda, ast.Attribute) and izquierda.attr == "analysis_mode"
                and isinstance(derecha, ast.Constant)):
            rutas[derecha.value] = [n.func.id for n in ast.walk(nodo)
                                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                                    and n.func.id.startswith("render_")]
    check("la ruta de Práctico existe", "render_practical_page" in rutas.get("practico", []))
    check("la ruta de Territorial existe", "render_territorial_page" in rutas.get("territorial", []))
    # Avanzado no tiene un `if` propio: es el camino que sigue cuando ninguna
    # ruta anterior corta, así que se comprueba que ninguna lo intercepte.
    check("Avanzado sigue siendo el camino por defecto", "avanzado" not in rutas)


if __name__ == "__main__":
    main()

# Comparación temporal por dimensión: dos categorías deben producir dos series.
from visualization.charts import grouped_trend

test_df = pd.DataFrame({
    "Fecha": pd.date_range("2026-01-01", periods=6, freq="MS").tolist() * 2,
    "Nombre": ["Adriana"] * 6 + ["Camilo"] * 6,
    "Ingresos": [50, 60, 80, 70, 90, 100, 70, 55, 90, 85, 110, 120],
})
test_schema = {
    "dates": ["Fecha"], "metrics": ["Ingresos"], "categorical": ["Nombre"], "ids": [],
    "semantic": {
        "metrics": ["Ingresos"], "dimensions": ["Nombre"],
        "columns": [
            {"column": "Fecha", "semantic_type": "date", "confidence": 1},
            {"column": "Nombre", "semantic_type": "customer", "confidence": 1},
            {"column": "Ingresos", "semantic_type": "revenue", "confidence": 1},
        ],
    },
}
fig_grouped = grouped_trend(test_df, test_schema, "Ingresos", "Nombre", "Mes", "Suma", 6)
check("comparación temporal por dimensión crea dos líneas", fig_grouped is not None and len(fig_grouped.data) == 2)
