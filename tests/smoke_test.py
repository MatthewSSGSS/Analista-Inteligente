import io
import pandas as pd

from core.loader import load_workbook
from core.profile import profile_sheet
from core.dashboard_engine import build_dashboard
from core.comparison_engine import prepare_comparison, build_comparison
from visualization.charts import trend, ranking, donut, histogram, scatter, correlation, wide_month_chart
from core.geo_engine import supports_georeferencing


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

    print("\nSmoke test completado sin errores.")


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
