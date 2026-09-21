"""Regresión del aplanador de tablas dinámicas (core/pivot_flatten.py).

Genera archivos .xlsx/.csv reales replicando las formas más comunes de
tabla dinámica de Excel (celdas combinadas, encabezado de varias filas,
subtotales, total general — en Compacto/Esquema, con y sin combinar) y
verifica que core/loader.py las aplane a una tabla normal. Incluye también
casos de control: datos planos normales, con o sin coincidencias que
podrían confundirse con una tabla dinámica, no deben tocarse.

Se corre igual que tests/smoke_test.py: PYTHONPATH=. python tests/pivot_test.py
"""
import io
import openpyxl

from core.loader import load_workbook


def _upload_xlsx(name, wb):
    b = io.BytesIO()
    wb.save(b)
    return type("Upload", (), {"getvalue": lambda self: b.getvalue(), "name": name})()


def _upload_csv(name, text):
    data = text.encode("utf-8")
    return type("Upload", (), {"getvalue": lambda self, d=data: d, "name": name})()


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


# ── Caso 1: layout Compacto, CON celdas combinadas reales para "Región"
# (grupo de filas), encabezado de 1 fila, subtotal por región y total
# general al final. ──
def caso_1_merges_y_subtotales():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ventas"
    ws.append(["Región", "Producto", "Ingresos"])
    for r in [
        ("Norte", "A", 100), ("Norte", "B", 150), ("Total Norte", "", 250),
        ("Sur", "A", 80), ("Sur", "B", 120), ("Sur", "C", 40), ("Total Sur", "", 240),
        ("Total general", "", 490),
    ]:
        ws.append(r)
    ws.merge_cells("A2:A3")
    ws.merge_cells("A5:A7")
    item = load_workbook(_upload_xlsx("dinamica_regiones.xlsx", wb))["sheets"]["Ventas"]
    df, log = item["processed"], item["profile"]["cleaning_log"]
    check("quita las 3 filas de subtotal/total", len(df) == 5)
    check("rellena la región heredada de la celda combinada", df["Región"].isna().sum() == 0)
    check("Norte aparece 2 veces, Sur 3 veces", (df["Región"] == "Norte").sum() == 2 and (df["Región"] == "Sur").sum() == 3)
    check("suma real (sin los totales) = 490", df["Ingresos"].sum() == 490)
    check("el log menciona celdas combinadas y subtotales", any("combinada" in x for x in log) and any("subtotal" in x.lower() for x in log))


# ── Caso 2: SIN celdas combinadas (texto simplemente en blanco), encabezado
# de 2 filas (Año arriba, Trimestre abajo), solo total general. ──
def caso_2_staircase_sin_merge_header_2_filas():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Trimestral"
    ws.append(["", "2024", "", "2025", ""])
    ws.append(["Vendedor", "Q1", "Q2", "Q1", "Q2"])
    ws.append(["Ana", 10, 12, 14, 16])
    ws.append(["", 11, 13, 15, 17])
    ws.append(["Beto", 20, 22, 24, 26])
    ws.append(["Total general", 41, 47, 53, 59])
    item = load_workbook(_upload_xlsx("dinamica_trimestral.xlsx", wb))["sheets"]["Trimestral"]
    df, log = item["processed"], item["profile"]["cleaning_log"]
    check("encabezado de 2 filas combinado en 1 (5 columnas)", len(df.columns) == 5 and "2024 · Q1" in df.columns)
    check("quita la fila de total general (2 personas quedan)", len(df) == 3)
    check("Ana hereda su nombre en la fila de abajo (sin merge real)", (df["Vendedor"] == "Ana").sum() == 2)
    check("el log menciona el encabezado combinado", any("Encabezado" in x for x in log))


# ── Caso 3: encabezado de 3 niveles (Año > Región > Métrica), con celdas
# combinadas en los 2 niveles superiores. ──
def caso_3_encabezado_3_niveles():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Multi"
    ws.append(["", "2024", "", "", ""])
    ws.append(["", "Norte", "", "Sur", ""])
    ws.append(["Vendedor", "Ingresos", "Unidades", "Ingresos", "Unidades"])
    ws.append(["Ana", 100, 10, 80, 8])
    ws.append(["Beto", 120, 12, 90, 9])
    ws.merge_cells("B1:E1")
    ws.merge_cells("B2:C2")
    ws.merge_cells("D2:E2")
    item = load_workbook(_upload_xlsx("multinivel.xlsx", wb))["sheets"]["Multi"]
    df = item["processed"]
    check("junta los 3 niveles del encabezado", any("2024" in c and "Norte" in c and "Ingresos" in c for c in df.columns))
    check("quedan las 2 filas de datos", len(df) == 2)


# ── Caso 3b: regresión de un bug real reportado en producción — título del
# reporte combinado en la fila de arriba (p. ej. "INFORME PDC TaT TROPAS"),
# cayendo sobre columnas cuyas demás filas son puramente numéricas. pandas
# tipa esas columnas con un dtype "nulificable" estricto (Float64/Int64) que
# NO acepta texto — escribirle el título ahí tronaba con
# "Invalid value '...' for dtype '...'" al rellenar la celda combinada. ──
def caso_3b_titulo_combinado_sobre_columnas_numericas():
    import pandas as pd
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PDC"
    ws.append(["INFORME PDC TaT TROPAS", "", "", ""])
    ws.append(["Región", 2024, 2025, 2026])  # encabezados numéricos, no texto
    for r in [("Norte", 100, 110, 120), ("Sur", 80, 90, 95)]:
        ws.append(r)
    ws.merge_cells("A1:D1")
    item = load_workbook(_upload_xlsx("informe_pdc.xlsx", wb))["sheets"]["PDC"]
    df = item["processed"]
    log = item["profile"]["cleaning_log"]
    check("no truena con título combinado sobre columnas numéricas", len(df) == 2)
    check("el título no se cuela como fila/columna de datos", not any("INFORME" in str(c) for c in df.columns))
    check("las columnas de años se recuperan como datos numéricos", pd.to_numeric(df.iloc[:, 1], errors="coerce").notna().all())
    check("el log dice que se descartó la fila de título", any("título" in x.lower() for x in log))


# ── Caso 4: CSV exportado de una dinámica (sin celdas combinadas posibles
# en CSV, pero con el mismo hueco de etiquetas + total general). ──
def caso_4_csv_con_forma_de_dinamica():
    csv_text = "Región,Producto,Ingresos\nNorte,A,100\n,B,150\nSur,A,80\n,B,120\nTotal general,,450\n"
    item = load_workbook(_upload_csv("export_dinamica.csv", csv_text))["sheets"]["CSV"]
    df = item["processed"]
    check("quita la fila de total general del CSV", len(df) == 4)
    check("Norte y Sur se heredan en la fila de abajo", (df["Región"] == "Norte").sum() == 2 and (df["Región"] == "Sur").sum() == 2)


# ── Caso 5: la dinámica MÁS común y la que se escapaba: exportada a CSV,
# con UN solo encabezado, SIN fila de total y con los meses como columnas.
# No tenía ninguna de las dos señales "fuertes" de antes (encabezado de
# varias filas / fila de total), así que las etiquetas heredadas se quedaban
# sin rellenar y media columna de grupo llegaba vacía al análisis. ──
def caso_5_csv_sin_totales_con_meses_en_columnas():
    csv_text = (
        "Región,Ciudad,ene-26,feb-26,mar-26\n"
        "Norte,Bogotá,10,20,30\n"
        ",Medellín,5,6,7\n"
        ",Cali,1,2,3\n"
        "Sur,Cartagena,4,5,6\n"
        ",Barranquilla,7,8,9\n"
    )
    item = load_workbook(_upload_csv("dinamica_sin_totales.csv", csv_text))["sheets"]["CSV"]
    df, log = item["processed"], item["profile"]["cleaning_log"]
    check("sin fila de total ni encabezado doble, igual se reconoce la dinámica",
          any("dinámica" in x for x in log))
    check("las etiquetas heredadas se rellenan", int(df["Región"].isna().sum()) == 0)
    # Ya despivotada: 5 ciudades × 3 meses, una fila por (ciudad, mes).
    check("los meses vuelven a ser filas", "Mes" in df.columns and "Valor" in df.columns)
    check("ninguna columna de mes sobrevive", not any(str(c).startswith(("ene", "feb", "mar")) for c in df.columns))
    check("quedan las 15 combinaciones ciudad × mes", len(df) == 15)
    check("Norte agrupa 3 ciudades y Sur 2",
          (df["Región"] == "Norte").sum() == 9 and (df["Región"] == "Sur").sum() == 6)
    check("no se pierde ningún valor del original", df["Valor"].sum() == 10 + 20 + 30 + 5 + 6 + 7 + 1 + 2 + 3 + 4 + 5 + 6 + 7 + 8 + 9)


# ── Control 4: hay meses como nombres de columna (señal de dinámica), pero
# la columna de texto NO tiene forma de escalera: sus huecos son datos
# ausentes de verdad. Una señal sola no debe rellenar nada. ──
def control_4_meses_en_columnas_pero_sin_escalera():
    import pandas as pd
    csv_text = (
        "Asesor,Zona,ene-26,feb-26\n"
        "Ana,Norte,10,20\n"
        "Luis,,5,6\n"
        "Marta,Sur,1,2\n"
        "Pedro,,4,5\n"
    )
    item = load_workbook(_upload_csv("meses_sin_escalera.csv", csv_text))["sheets"]["CSV"]
    df, log = item["processed"], item["profile"]["cleaning_log"]
    # La tabla sí se despivota (los meses en columnas son forma de dinámica),
    # así que se comprueba por asesor y no por posición de fila: al
    # despivotar, cada asesor pasa a tener una fila por mes.
    zona_de = lambda quien: df.loc[df["Asesor"] == quien, "Zona"]
    check("la zona vacía de Luis no hereda 'Norte'", zona_de("Luis").isna().all())
    check("la zona vacía de Pedro no hereda 'Sur'", zona_de("Pedro").isna().all())
    check("las zonas reales se conservan", set(zona_de("Ana")) == {"Norte"} and set(zona_de("Marta")) == {"Sur"})
    check("no se activó ningún relleno heredado", not any("heredad" in x for x in log))


# ── Caso 6: la ruta completa de una dinámica, en orden — fila de Total,
# columna de Total, etiquetas heredadas y meses en columnas, todo junto.
# El orden importa: si la columna "Total" no se quitara ANTES de despivotar,
# entraría al melt como si fuera un mes más. ──
def caso_6_ruta_completa_en_orden():
    csv_text = (
        "Región,Ciudad,ene-26,feb-26,mar-26,Total\n"
        "Norte,Bogotá,10,20,30,60\n"
        ",Medellín,5,6,7,18\n"
        "Sur,Cartagena,4,5,6,15\n"
        ",Barranquilla,7,8,9,24\n"
        "Total,,26,39,52,117\n"
    )
    item = load_workbook(_upload_csv("dinamica_completa.csv", csv_text))["sheets"]["CSV"]
    df, log = item["processed"], item["profile"]["cleaning_log"]
    check("(a) la fila de Total se excluye", "Total" not in set(df.get("Región", [])))
    check("(a) la columna de Total se excluye", "Total" not in df.columns)
    check("(b) las etiquetas heredadas se rellenan", int(df["Región"].isna().sum()) == 0)
    check("(c) los meses vuelven a ser filas", {"Mes", "Valor"}.issubset(set(df.columns)))
    check("(d) el esquema queda como el de una tabla plana",
          list(df.columns) == ["Región", "Ciudad", "Mes", "Valor"])
    check("quedan las 12 combinaciones ciudad × mes", len(df) == 12)
    check("la suma no se duplica con el Total (117, no 234)", df["Valor"].sum() == 117)
    check("el log cuenta los cuatro pasos",
          any("subtotal" in x.lower() for x in log) and any("columna(s) de total" in x for x in log)
          and any("heredad" in x for x in log) and any("convertidas en filas" in x for x in log))


# ── Caso 6b: la misma ruta, pero en Excel. Una hoja con 3+ meses la toma
# antes el lector de informes (core/informe.py, que tiene su propia ruta y
# ya despivotaba); con 2 meses no llega a su mínimo y cae aquí, que es
# justo lo que se quiere comprobar: en Excel la ruta también existe. ──
def caso_6b_excel_que_el_lector_de_informes_no_toma():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "DosMeses"
    ws.append(["Región", "Ciudad", "ene-26", "feb-26"])
    for r in [("Norte", "Bogotá", 10, 20), (None, "Medellín", 5, 6), ("Total", None, 15, 26)]:
        ws.append(r)
    ws.merge_cells("A2:A3")
    item = load_workbook(_upload_xlsx("dos_meses.xlsx", wb))["sheets"]["DosMeses"]
    df = item["processed"]
    check("también en Excel los meses vuelven a ser filas", list(df.columns) == ["Región", "Ciudad", "Mes", "Valor"])
    check("la fila de Total no entra", len(df) == 4)
    check("la región heredada de la celda combinada se conserva al despivotar",
          set(df["Región"]) == {"Norte"})


# ── Caso 7: meses SIN año en el encabezado ("Ene", "Feb"). El año sale del
# nombre del archivo, igual que ya hacía el lector de informes. ──
def caso_7_meses_sin_anio_usan_el_nombre_del_archivo():
    import pandas as pd
    csv_text = "Asesor,Ene,Feb,Mar\nAna,10,20,30\nLuis,4,5,6\n"
    item = load_workbook(_upload_csv("reporte_2026.csv", csv_text))["sheets"]["CSV"]
    df = item["processed"]
    check("el mes queda como fecha real, no como texto", pd.api.types.is_datetime64_any_dtype(df["Mes"]))
    check("con el año que dice el nombre del archivo", set(df["Mes"].dt.year) == {2026})


# ── Control 5: tabla plana con una columna llamada "Total" pero SIN ninguna
# señal de dinámica. La columna es parte de los datos: no se toca. ──
def control_5_columna_total_en_tabla_plana():
    csv_text = "Cliente,Ventas,Total\nAna,10,10\nLuis,20,20\nSara,30,30\n"
    item = load_workbook(_upload_csv("plana_con_total.csv", csv_text))["sheets"]["CSV"]
    df, log = item["processed"], item["profile"]["cleaning_log"]
    check("la columna Total sobrevive en una tabla plana", "Total" in df.columns)
    check("no se quitó ninguna columna", len(df.columns) == 3)
    check("no se registró nada de dinámica", not any("dinámica" in x for x in log))


# ── Control 6: los encabezados son meses, pero lo que hay debajo es texto,
# no una medida. Despivotar eso produciría una columna "Valor" de palabras:
# no se toca. ──
def control_6_meses_con_texto_no_se_despivotan():
    csv_text = "Asesor,ene-26,feb-26,mar-26\nAna,alto,bajo,medio\nLuis,bajo,alto,alto\n"
    item = load_workbook(_upload_csv("meses_texto.csv", csv_text))["sheets"]["CSV"]
    df = item["processed"]
    check("la tabla se queda como estaba", "Mes" not in df.columns and "ene-26" in df.columns)


# ── Control 7: la tabla YA trae una columna llamada "Mes" o "Valor" (otra
# cosa, no el periodo). Reusar el nombre al despivotar lanzaba un ValueError
# de pandas y el archivo entero dejaba de cargarse. ──
def control_7_nombres_que_ya_existen_no_tumban_la_carga():
    for csv_text, esperado in [
        ("Región,Mes,ene-26,feb-26\nNorte,algo,10,20\nSur,otro,4,5\n", "Mes_2"),
        ("Región,Valor,ene-26,feb-26\nNorte,9,10,20\nSur,8,4,5\n", "Valor_2"),
    ]:
        item = load_workbook(_upload_csv("choque.csv", csv_text))["sheets"]["CSV"]
        df = item["processed"]
        check(f"con una columna que ya se llamaba así, se usa «{esperado}» y la carga no truena",
              esperado in df.columns and len(df) == 4)


# ── Convergencia: el MISMO dato lógico, entregado en las cuatro formas
# posibles (plana o dinámica, en .csv o en .xlsx), tiene que terminar con
# exactamente las mismas columnas, en el mismo orden y con los mismos tipos,
# antes de que nada más lo mire. Si cada ruta deja un formato distinto, todo
# lo que viene después (esquema, KPIs, filtros, historial) hereda esa
# diferencia y el mismo archivo da resultados distintos según cómo se
# guardó. ──
def convergencia_de_rutas_mismo_esquema():
    import pandas as pd
    meses = ["2026-01-01", "2026-02-01", "2026-03-01"]
    datos = [("Norte", "Bogotá", [10, 20, 30]), ("Sur", "Cali", [4, 5, 6])]

    plana = [["Región", "Ciudad", "Mes", "Valor"]]
    for region, ciudad, valores in datos:
        plana += [[region, ciudad, mes, v] for mes, v in zip(meses, valores)]
    dinamica = [["Región", "Ciudad", "ene-26", "feb-26", "mar-26"]]
    dinamica += [[region, ciudad, *valores] for region, ciudad, valores in datos]

    def _xlsx(nombre, filas):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Hoja1"
        for f in filas:
            ws.append(f)
        return load_workbook(_upload_xlsx(nombre, wb))["sheets"]["Hoja1"]["processed"]

    def _csv(nombre, filas):
        texto = "\n".join(",".join(map(str, f)) for f in filas) + "\n"
        return load_workbook(_upload_csv(nombre, texto))["sheets"]["CSV"]["processed"]

    rutas = {
        "plana .csv": _csv("plana.csv", plana),
        "plana .xlsx": _xlsx("plana.xlsx", plana),
        "dinámica .csv": _csv("dinamica.csv", dinamica),
        "dinámica .xlsx": _xlsx("dinamica.xlsx", dinamica),
    }
    firmas = {k: [(str(c), str(t)) for c, t in zip(df.columns, df.dtypes)] for k, df in rutas.items()}
    esperada = [("Región", "string"), ("Ciudad", "string"), ("Mes", "datetime64[ns]"), ("Valor", "Int64")]
    for nombre, firma in firmas.items():
        check(f"«{nombre}» entrega el esquema normalizado", firma == esperada)
    for nombre, df in rutas.items():
        check(f"«{nombre}» conserva las 6 filas y sus valores",
              len(df) == 6 and df["Valor"].sum() == 75 and set(df["Región"]) == {"Norte", "Sur"})
    check("las fechas son la misma serie por las cuatro rutas",
          len({tuple(pd.to_datetime(df["Mes"]).sort_values().dt.strftime("%Y-%m")) for df in rutas.values()}) == 1)

    # Y lo que de verdad importa: que las cuatro pasen por la MISMA
    # validación de columnas por nombre (core/schema.detect_schema, vía
    # profile_sheet) y salgan con la misma lectura. Si una ruta se la
    # saltara o tuviera la suya, esto se vería aquí.
    def _firma_esquema(nombre, filas, es_csv):
        if es_csv:
            texto = "\n".join(",".join(map(str, f)) for f in filas) + "\n"
            item = load_workbook(_upload_csv(nombre, texto))["sheets"]["CSV"]
        else:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Hoja1"
            for f in filas:
                ws.append(f)
            item = load_workbook(_upload_xlsx(nombre, wb))["sheets"]["Hoja1"]
        esquema = item["profile"]["schema"]
        return (
            tuple(esquema.get("dates") or []), tuple(esquema.get("metrics") or []),
            tuple(esquema.get("categorical") or []), tuple(esquema.get("ids") or []),
            tuple(sorted((x.get("column"), x.get("semantic_type"))
                         for x in esquema.get("semantic", {}).get("columns", []))),
        )

    esquemas = {
        "plana .csv": _firma_esquema("e_plana.csv", plana, True),
        "plana .xlsx": _firma_esquema("e_plana.xlsx", plana, False),
        "dinámica .csv": _firma_esquema("e_dinamica.csv", dinamica, True),
        "dinámica .xlsx": _firma_esquema("e_dinamica.xlsx", dinamica, False),
    }
    check("las cuatro rutas salen con el mismo esquema detectado", len(set(esquemas.values())) == 1)
    fechas, metricas, categoricas, _, _ = esquemas["plana .csv"]
    check("y ese esquema es el correcto (Mes como fecha, Valor como métrica)",
          fechas == ("Mes",) and metricas == ("Valor",) and set(categoricas) == {"Región", "Ciudad"})


# ── Las dos rutas tienen que llamar a la MISMA regla para decidir qué es una
# fila de total. Tenían cada una la suya y no decían lo mismo: la de
# core/informe.py no reconocía "Sub total", "Sub-total" ni "Subtotales", así
# que esas filas se sumaban como un registro más en las hojas tipo informe
# mientras la otra ruta sí las excluía. ──
def misma_regla_de_totales_en_las_dos_rutas():
    from core.informe import _es_total
    from core.pivot_flatten import es_total
    etiquetas = ["Total", "Totales", "Total general", "TOTAL", "Subtotal", "Sub total",
                 "Sub-total", "Subtotales", "Gran total", "Total Play", "Totalizadores S.A."]
    check("las dos rutas responden igual a cada etiqueta",
          all(_es_total(t) == es_total(t) for t in etiquetas))
    check("y reconocen el subtotal escrito de cualquier forma",
          all(es_total(t) for t in ["Subtotal", "Sub total", "Sub-total", "Subtotales"]))
    check("sin llevarse por delante una categoría real que empieza igual",
          not es_total("Total Play") and not es_total("Totalizadores S.A."))

    # Y el efecto real, extremo a extremo, en una hoja tipo informe.
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Informe"
    ws.append(["CUMPLIMIENTO POR REGION COSTA"])
    ws.append(["Region", "ene-26", "feb-26", "mar-26"])
    for f in [("R1", 10, 20, 30), ("R2", 4, 5, 6), ("Subtotales", 14, 25, 36)]:
        ws.append(list(f))
    hojas = load_workbook(_upload_xlsx("informe_subtotales.xlsx", wb))["sheets"]
    df = next(it["processed"] for it in hojas.values())
    check("la fila «Subtotales» de un informe ya no entra como un registro",
          set(df.iloc[:, 0].dropna()) == {"R1", "R2"})
    check("y la suma no queda inflada por ella", int(df["Valor"].sum()) == 75)


# ── Una tabla pequeña tiene que seguir teniendo métrica y gráficos. Es el
# control de la normalización de tipos: al unificar los enteros en Int64
# (para que las dos rutas entreguen el mismo esquema), una medida de un
# informe corto pasó a parecerle un CÓDIGO al selector de métricas
# —`unique <= 12` + dtype entero— y desaparecía de los gráficos y los KPIs.
# La tabla cargaba bien, con sus tipos correctos, y aun así el panel salía
# sin nada que graficar: por eso se comprueba hasta el gráfico, no solo el
# esquema. ──
def tabla_pequena_conserva_su_metrica():
    import pandas as pd
    from visualization.charts import metric_candidates, trend, ranking

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Informe"
    ws.append(["CUMPLIMIENTO POR REGION COSTA"])
    ws.append(["Region", "ene-26", "feb-26", "mar-26"])
    for f in [("R1", 10, 20, 30), ("R2", 4, 5, 6), ("R3", 7, 8, 9)]:
        ws.append(list(f))
    item = next(iter(load_workbook(_upload_xlsx("informe_2026.xlsx", wb))["sheets"].values()))
    df, esquema = item["processed"], item["profile"]["schema"]
    check("la medida sigue siendo una métrica seleccionable", metric_candidates(df, esquema) == ["Valor"])
    check("y hay gráficos que dibujar", trend(df, esquema) is not None and ranking(df, esquema) is not None)

    # Control: un código de verdad (5 zonas repetidas en 100 filas) sigue sin
    # contarse como métrica — es lo que ese filtro existe para evitar.
    codigo = pd.DataFrame({"Zona": [1, 2, 3, 4, 5] * 20, "Ciudad": [f"C{i % 7}" for i in range(100)]})
    esquema_codigo = {"metrics": ["Zona"], "dates": [], "ids": [], "categorical": ["Ciudad"],
                      "semantic": {"columns": [{"column": "Zona", "semantic_type": "unknown"}]}}
    check("un código que se repite no se confunde con una medida",
          metric_candidates(codigo, esquema_codigo) == [])


# ── Control 1: tabla PLANA normal con una categoría real que EMPIEZA con
# "Total" (cliente real "Total Play") — no debe excluirse ni tocarse. ──
def control_1_categoria_real_total_play():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Clientes"
    ws.append(["Cliente", "Ciudad", "Ingresos"])
    ws.append(["Total Play", "Bogotá", 5000])
    ws.append(["Claro", "Medellín", 4000])
    ws.append(["Movistar", "Cali", 3000])
    item = load_workbook(_upload_xlsx("clientes.xlsx", wb))["sheets"]["Clientes"]
    df, log = item["processed"], item["profile"]["cleaning_log"]
    check("Total Play sigue en los datos", (df["Cliente"] == "Total Play").sum() == 1)
    check("siguen las 3 filas", len(df) == 3)
    check("no se detectó ningún subtotal (no debía aplicar)", not any("subtotal" in x.lower() for x in log))


# ── Control 2: columna de texto genuinamente dispersa (segundo apellido en
# blanco para varias personas) SIN ninguna otra señal de dinámica — no debe
# rellenarse con el valor de arriba. ──
def control_2_columna_dispersa_no_se_rellena():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Personas"
    ws.append(["Nombre", "Segundo apellido", "Edad"])
    ws.append(["Ana", "Gómez", 30])
    ws.append(["Luis", "", 40])
    ws.append(["Marta", "Ruiz", 25])
    ws.append(["Pedro", "", 35])
    item = load_workbook(_upload_xlsx("personas.xlsx", wb))["sheets"]["Personas"]
    df, log = item["processed"], item["profile"]["cleaning_log"]
    import pandas as pd
    check("el segundo apellido de Luis se queda vacío (no hereda 'Gómez')", pd.isna(df["Segundo apellido"].iloc[1]))
    check("el segundo apellido de Pedro se queda vacío (no hereda 'Ruiz')", pd.isna(df["Segundo apellido"].iloc[3]))
    check("no se activó ningún relleno heredado", not any("heredad" in x for x in log))


# ── Control 3: hoja de solo encabezado (sin filas de dato) no debe tronar
# el proceso de carga completo. ──
def control_3_hoja_sin_filas_de_dato():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "SoloEncabezado"
    ws.append(["Nombre", "Valor"])
    try:
        load_workbook(_upload_xlsx("solo_encabezado.xlsx", wb))
        check("hoja sin filas de dato no truena", True)
    except ValueError:
        check("hoja sin filas de dato: error controlado (esperado), no un crash", True)


if __name__ == "__main__":
    caso_1_merges_y_subtotales()
    caso_2_staircase_sin_merge_header_2_filas()
    caso_3_encabezado_3_niveles()
    caso_3b_titulo_combinado_sobre_columnas_numericas()
    caso_4_csv_con_forma_de_dinamica()
    caso_5_csv_sin_totales_con_meses_en_columnas()
    caso_6_ruta_completa_en_orden()
    caso_6b_excel_que_el_lector_de_informes_no_toma()
    caso_7_meses_sin_anio_usan_el_nombre_del_archivo()
    convergencia_de_rutas_mismo_esquema()
    misma_regla_de_totales_en_las_dos_rutas()
    tabla_pequena_conserva_su_metrica()
    control_1_categoria_real_total_play()
    control_2_columna_dispersa_no_se_rellena()
    control_3_hoja_sin_filas_de_dato()
    control_4_meses_en_columnas_pero_sin_escalera()
    control_5_columna_total_en_tabla_plana()
    control_6_meses_con_texto_no_se_despivotan()
    control_7_nombres_que_ya_existen_no_tumban_la_carga()
    print("\nPivot test completado sin errores.")
