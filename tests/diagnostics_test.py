"""Que las alertas digan algo que se pueda accionar.

La prueba de fondo no es que el código no truene: es que el hallazgo traiga
el NOMBRE de quien va mal y la CIFRA de cuánto. Una alerta que dice "se
detectaron 164 observaciones atípicas" pasa cualquier prueba técnica y no
sirve para decidir nada, así que aquí se verifica lo contrario: que el punto
que construimos para que caiga aparezca por su nombre en el hallazgo.
"""
import pandas as pd

from core.anomalies import detect
from core.diagnostics import diagnosticar, dimension_operativa
from core.profile import profile_sheet
from core.dashboard_engine import build_dashboard


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _archivo_de_puntos():
    """Un archivo con un desenlace conocido, para poder exigir el diagnóstico.

    - RIOHACHA cae los tres meses seguidos.
    - MAICAO desaparece en el último mes.
    - GERA concentra el volumen y trae un valor disparado.
    - El resto se mantiene estable.
    """
    puntos = ["MC MULTICELL SAS CIENEGA MAGDALENA", "DANCELL RIOHACHA LA GUAJIRA",
              "DANCELL VALLEDUPAR CESAR", "COMMUTE SAS SOLEDAD ATLANTICO",
              "COMMUTE SAS BARRANQUILLA ATLANTICO", "INVERSIONES GERA SAS CARTAGENA",
              "CELUNORTE SAS SINCELEJO SUCRE", "MOVIL SAS MAICAO LA GUAJIRA"]
    filas = []
    for mes in ("2026-04", "2026-05", "2026-06"):
        for p in puntos:
            if p.startswith("MOVIL SAS MAICAO") and mes == "2026-06":
                continue
            base = 900
            if p.startswith("DANCELL RIOHACHA"):
                base = {"2026-04": 1200, "2026-05": 700, "2026-06": 260}[mes]
            if p.startswith("INVERSIONES GERA"):
                base = 4200
            # Variación leve pero determinista: sin dispersión el detector de
            # atípicos no tiene rango intercuartílico con el que trabajar, y
            # un archivo real nunca es plano.
            for i, dia in enumerate((5, 12, 19, 26)):
                filas.append({"Fecha": f"{mes}-{dia:02d}", "NOMBREPUNTO": p,
                              "Ventas": int(base * (0.88 + 0.08 * i))})
    filas.append({"Fecha": "2026-06-15", "NOMBREPUNTO": "INVERSIONES GERA SAS CARTAGENA", "Ventas": 98000})
    return pd.DataFrame(filas)


def _por_titulo(hallazgos, titulo):
    return next((h for h in hallazgos if h["title"] == titulo), None)


def _menciona(hallazgo, texto):
    """¿El nombre aparece en el hallazgo, sea en la frase o en la evidencia?"""
    if hallazgo is None:
        return False
    donde = [hallazgo.get("finding", ""), hallazgo.get("action", "")]
    donde += [str(e.get("nombre", "")) for e in hallazgo.get("evidence", [])]
    return any(texto in d for d in donde)


def main():
    df = _archivo_de_puntos()
    item = profile_sheet(df, {"sheet_name": "Ventas", "workbook_name": "ventas.xlsx"})
    procesado, schema = item["processed"], item["profile"]["schema"]

    check("elige NOMBREPUNTO como unidad de análisis",
          dimension_operativa(procesado, schema) == "NOMBREPUNTO")

    dash = build_dashboard(procesado, item["profile"])
    hallazgos = dash["insights"]
    titulos = [h["title"] for h in hallazgos]

    caida = _por_titulo(hallazgos, "Dónde se concentra la caída")
    check("hay un hallazgo sobre dónde cayó", caida is not None)
    check("y nombra al punto que construimos cayendo", _menciona(caida, "RIOHACHA"))
    check("con su cifra, no solo el nombre", bool(caida.get("evidence")))
    check("la evidencia trae el porcentaje de la caída",
          any("%" in str(e.get("detalle", "")) for e in caida["evidence"]))
    check("y deja abrir ese punto desde la alerta",
          caida["target"].get("filter_column") == "NOMBREPUNTO" and caida["target"].get("filter_value"))

    sostenido = _por_titulo(hallazgos, "Deterioro sostenido")
    check("detecta el deterioro de tres periodos seguidos", sostenido is not None)
    check("y es el punto que cae mes a mes", _menciona(sostenido, "RIOHACHA"))

    inactivo = _por_titulo(hallazgos, "Dejaron de registrar")
    check("detecta al que dejó de registrar", inactivo is not None)
    check("y lo nombra", _menciona(inactivo, "MAICAO"))
    check("quien terminó en cero no se repite como 'deterioro sostenido'",
          not _menciona(sostenido, "MAICAO"))

    atipicos = _por_titulo(hallazgos, "Valores atípicos: dónde están")
    check("los atípicos dicen en qué punto están", atipicos is not None)
    check("y nombran al punto del valor disparado", _menciona(atipicos, "GERA"))
    check("el aviso genérico de atípicos ya no aparece al lado",
          "Calidad para la toma de decisiones" not in titulos)

    alertas = [a["title"] for a in dash["alerts"]]
    check("ninguna alerta se repite", len(alertas) == len(set(alertas)))
    check("y no vuelve el duplicado de 'Valores que requieren revisión'",
          "Valores que requieren revisión" not in alertas)

    # Un archivo sin nada que diagnosticar no debe inventar hallazgos.
    catalogo = pd.DataFrame({
        "Producto": ["Plan 100M", "Plan 300M", "Router", "Decodificador", "Cable"],
        "Precio": [50000, 70000, 120000, 90000, 15000],
    })
    ci = profile_sheet(catalogo, {"sheet_name": "Planes", "workbook_name": "planes.xlsx"})
    check("un catálogo no recibe diagnósticos de caída",
          not diagnosticar(ci["processed"], ci["profile"]["schema"], None))

    # Con el último mes a medias, todo parece caer: no debe declararse un
    # abandono que en realidad es un archivo cortado a mitad de mes.
    parcial = df[~((df["Fecha"] >= "2026-06-10"))].copy()
    pi = profile_sheet(parcial, {"sheet_name": "Ventas", "workbook_name": "ventas.xlsx"})
    hallazgos_parciales = diagnosticar(pi["processed"], pi["profile"]["schema"], None)
    check("con el mes incompleto no se declara que alguien dejó de registrar",
          _por_titulo(hallazgos_parciales, "Dejaron de registrar") is None)
    caida_parcial = _por_titulo(hallazgos_parciales, "Dónde se concentra la caída")
    check("y la caída avisa que el periodo puede estar incompleto",
          caida_parcial is None or "incompleto" in caida_parcial["finding"])

    # Con cientos de puntos y datos sin señal, unos cuantos bajan tres veces
    # seguidas por azar. Nombrarlos sería peor que callar: la alerta pierde
    # credibilidad justo cuando llegue una caída de verdad.
    import random
    random.seed(5)
    puntos_muchos = [f"PUNTO {i:04d}" for i in range(600)]
    ruido = pd.DataFrame({
        "Fecha": [f"2026-{random.randint(1, 6):02d}-{random.randint(1, 28):02d}" for _ in range(18000)],
        "PDV": [random.choice(puntos_muchos) for _ in range(18000)],
        "Ventas": [max(0, int(random.gauss(900, 400))) for _ in range(18000)],
    })
    ri = profile_sheet(ruido, {"sheet_name": "R", "workbook_name": "r.xlsx"})
    check("con 600 puntos, una columna de texto sigue sirviendo como unidad",
          dimension_operativa(ri["processed"], ri["profile"]["schema"]) == "PDV")
    hallazgos_ruido = diagnosticar(ri["processed"], ri["profile"]["schema"], None)
    check("el ruido no produce un 'deterioro sostenido' inventado",
          _por_titulo(hallazgos_ruido, "Deterioro sostenido") is None)
    check("ni un rezago irrelevante", _por_titulo(hallazgos_ruido, "Rezago frente a la mediana") is None)
    check("y una caída repartida se nombra como tal, sin señalar a tres al azar",
          _por_titulo(hallazgos_ruido, "Dónde se concentra la caída") is None)
    generalizada = _por_titulo(hallazgos_ruido, "Caída generalizada")
    check("la caída repartida sí se reporta, con su lectura propia", generalizada is not None)

    _otros_tipos_de_archivo()
    _comparar_contra_algo()
    print("\nDiagnostics test completado sin errores.")


def _comparar_contra_algo():
    """"El mejor es el que más vendió" compara tamaño, no desempeño.

    El caso que da nombre a la prueba: R1 vende 10 con meta de 4 y R5 vende
    100 con meta de 200. Por total gana R5; contra la meta, R1 lo hace seis
    veces mejor. Premiar a R5 por ser grande es la conclusión falsa que estos
    chequeos tienen que impedir que vuelva.
    """
    from core.performance import analyze, columna_meta, unidad_interna

    ventas = pd.DataFrame({
        "Region": ["R1", "R5", "R3", "R4"] * 5,
        "Ventas": [10, 100, 60, 30] * 5,
        "Meta": [4, 200, 50, 40] * 5,
    })
    vi = profile_sheet(ventas, {"sheet_name": "H", "workbook_name": "h.xlsx"})
    procesado, esquema = vi["processed"], vi["profile"]["schema"]

    check("se reconoce la columna de meta", columna_meta(procesado, esquema, "Ventas") == "Meta")
    resultado = analyze(procesado, esquema, dimension="Region")
    base = resultado["base"]
    check("la comparación se hace contra la meta", base["clave"] == "meta")
    check("y se declara una base justa", base["justo"])
    check("gana quien más cumplió, no quien más vendió", base["mejor"]["nombre"] == "R1")
    check("y el peor es quien menos cumplió", base["peor"]["nombre"] == "R5")
    check("el porcentaje de cumplimiento se muestra", base["mejor"]["texto"] == "250%")
    check("con la cifra que lo sostiene", "de" in base["mejor"]["detalle"])
    check("el orden por total sigue disponible aparte", resultado["top"][0][0] == "R5")

    # El diagnóstico también deja de comparar contra la mediana cuando hay meta.
    hallazgos = diagnosticar(procesado, esquema, None)
    meta_h = _por_titulo(hallazgos, "Cumplimiento de meta")
    check("el hallazgo habla de cumplimiento de meta", meta_h is not None)
    check("y nombra a quien no llegó", _menciona(meta_h, "R5"))
    check("el rezago contra la mediana ya no compite con él",
          _por_titulo(hallazgos, "Rezago frente a la mediana") is None)

    # Sin meta, se normaliza por lo que haya: puntos dentro de cada región.
    filas = []
    for region, puntos in (("Caribe", 40), ("Andina", 3), ("Pacifica", 10)):
        for p in range(puntos):
            for _ in range(4):
                filas.append({"Region": region, "Punto": f"{region}-{p:02d}",
                              "Ventas": 100 if region != "Andina" else 400})
    ui_ = profile_sheet(pd.DataFrame(filas), {"sheet_name": "H", "workbook_name": "h.xlsx"})
    procesado, esquema = ui_["processed"], ui_["profile"]["schema"]
    check("se reconoce la unidad que se cuenta dentro del grupo",
          unidad_interna(procesado, esquema, "Region") == "Punto")
    base = analyze(procesado, esquema, dimension="Region")["base"]
    check("sin meta se compara por unidad", base["clave"] == "unidad")
    check("y la región pequeña con más venta por punto queda primera",
          base["mejor"]["nombre"] == "Andina")

    # Una meta ambiciosa no es un dato sospechoso.
    check("la columna de meta no se revisa en busca de atípicos",
          "Meta" not in set(detect(vi["processed"], vi["profile"]["schema"]).get("columna", [])))

    # La meta viene escrita de mil formas. Si solo se reconoce "Meta", la
    # comparación justa se pierde en la mayoría de los archivos reales.
    for encabezado in ("META", "Meta Mensual", "Objetivo", "Presupuesto", "Ppto",
                       "Presup2026", "Cuota", "Target", "Budget", "Goal"):
        mi = profile_sheet(
            pd.DataFrame({"Region": ["A", "B", "C"] * 6, "Ventas": [10, 100, 60] * 6,
                          encabezado: [4, 200, 50] * 6}),
            {"sheet_name": "H", "workbook_name": "h.xlsx"})
        base_m = analyze(mi["processed"], mi["profile"]["schema"], dimension="Region")["base"]
        check(f"se reconoce la meta escrita como '{encabezado}'",
              base_m["clave"] == "meta" and base_m["mejor"]["nombre"] == "A")

    # Sin ninguna columna numérica todavía hay algo que comparar: la tasa.
    tickets = pd.DataFrame({
        "Ticket": [f"T{i}" for i in range(300)],
        "Responsable": ["Ana", "Luis", "Marta"] * 100,
        "Estado": (["Cerrado"] * 2 + ["Vencido"]) * 100,
    })
    ti = profile_sheet(tickets, {"sheet_name": "H", "workbook_name": "h.xlsx"})
    base_t = analyze(ti["processed"], ti["profile"]["schema"])["base"]
    check("un archivo sin columnas numéricas igual se puede comparar", base_t["clave"] == "estado")
    check("y se compara por tasa, no por cantidad de casos", base_t["mejor"]["texto"].endswith("%"))
    check("el estado no se usa como unidad de comparación",
          analyze(ti["processed"], ti["profile"]["schema"])["dimension"] != "Estado")

    # En una métrica donde subir es peor, el mejor es el que menos tiene.
    mora = pd.DataFrame({"Cliente": [f"C{i}" for i in range(6)] * 5,
                         "DiasMora": [0, 10, 20, 40, 80, 160] * 5})
    moi = profile_sheet(mora, {"sheet_name": "H", "workbook_name": "h.xlsx"})
    base_mo = analyze(moi["processed"], moi["profile"]["schema"], dimension="Cliente")["base"]
    check("con días de mora, el mejor es el que menos acumula",
          base_mo["mejor"]["nombre"] == "C0" and base_mo["peor"]["nombre"] == "C5")

    # Un catálogo no es una comparación de desempeño: cada fila es su grupo.
    catalogo = profile_sheet(
        pd.DataFrame({"Producto": [f"SKU{i}" for i in range(30)],
                      "Precio": list(range(1000, 31000, 1000))}),
        {"sheet_name": "H", "workbook_name": "h.xlsx"})
    resultado_cat = analyze(catalogo["processed"], catalogo["profile"]["schema"])
    check("sin agrupación real no se declara un mejor desempeño",
          resultado_cat is None or resultado_cat.get("base") is None)


def _otros_tipos_de_archivo():
    """El diagnóstico no puede servir solo para un archivo de ventas.

    Cada caso se construye con un culpable conocido —el equipo atrasado, el
    asesor mal calificado, la línea con merma— y se exige que el hallazgo lo
    nombre. Si el motor solo funcionara con ventas mensuales por punto, aquí
    se vería de inmediato.
    """
    import random
    random.seed(9)

    def hallazgos_de(df):
        it = profile_sheet(df, {"sheet_name": "H", "workbook_name": "h.xlsx"})
        procesado, esquema = it["processed"], it["profile"]["schema"]
        return diagnosticar(procesado, esquema, detect(procesado, esquema))

    def alguno_menciona(hallazgos, texto):
        return any(_menciona(h, texto) for h in hallazgos)

    # 1. Tickets sin ninguna columna numérica: la métrica es contar filas.
    tickets = pd.DataFrame({
        "Tarea": [f"TSK-{i:04d}" for i in range(400)],
        "Equipo": [random.choice(["Infra", "Producto", "Datos", "Soporte"]) for _ in range(400)],
    })
    tickets["Estado"] = [
        random.choice(["Vencido", "Vencido", "En curso"]) if eq == "Datos"
        else random.choice(["Cerrado", "Cerrado", "En curso", "Vencido"])
        for eq in tickets["Equipo"]
    ]
    h = hallazgos_de(tickets)
    check("un archivo sin columnas numéricas igual produce hallazgos", bool(h))
    check("y nombra al equipo que concentra los vencidos", alguno_menciona(h, "Datos"))

    # 2. Encuesta: una calificación baja no se detecta con "la mitad de la
    #    mediana", porque nadie califica 2 cuando el resto califica 4.
    filas = []
    for _ in range(600):
        asesor = random.choice([f"Asesor {i}" for i in range(10)])
        nota = random.choice([1, 1, 2, 3]) if asesor == "Asesor 3" else random.choice([4, 4, 5, 5, 3])
        filas.append({"Sede": random.choice(["Cali", "Bogotá", "Medellín"]),
                      "Asesor": asesor, "Calificacion": nota})
    h = hallazgos_de(pd.DataFrame(filas))
    check("en una encuesta se detecta al asesor mal calificado", alguno_menciona(h, "Asesor 3"))

    # 3. Métrica donde el problema es tener MÁS: merma, mora, quejas.
    filas = []
    for _ in range(500):
        linea = random.choice(["L1", "L2", "L3", "L4", "L5"])
        merma = random.gauss(18, 3) if linea == "L3" else random.gauss(4, 1.5)
        filas.append({"Linea": linea, "Unidades": random.randint(800, 1200),
                      "PorcentajeMerma": round(max(0, merma), 1)})
    h = hallazgos_de(pd.DataFrame(filas))
    exceso = next((x for x in h if x["title"].startswith("Exceso en")), None)
    check("en una métrica donde subir es malo, se detecta el exceso", exceso is not None)
    check("y se nombra la línea con más merma", _menciona(exceso, "L3"))

    # 4. Inventario: un cero no es un valor bajo, es una ausencia.
    inventario = pd.DataFrame({
        "Producto": [f"SKU-{i:03d}" for i in range(120)] * 3,
        "Bodega": [random.choice(["Norte", "Sur", "Centro"]) for _ in range(360)],
        "Stock": [random.choice([0, 0, 5, 12, 40, 120, 300]) for _ in range(360)],
    })
    h = hallazgos_de(inventario)
    check("los registros en cero se reportan aparte",
          any(x["title"].startswith("Registros en cero") for x in h))

    # 5. Un consecutivo repetido no tiene lectura inocente.
    facturas = pd.DataFrame({
        "NumeroFactura": [f"F-{i:05d}" for i in range(400)],
        "Cliente": [random.choice([f"Cliente {i}" for i in range(25)]) for _ in range(400)],
        "Total": [random.randint(50_000, 900_000) for _ in range(400)],
    })
    h = hallazgos_de(pd.concat([facturas, facturas.head(12)], ignore_index=True))
    repetido = _por_titulo(h, "Identificador repetido")
    check("un identificador repetido se detecta", repetido is not None)
    check("y dice cuántas filas sobran", "12" in repetido["finding"])

    # Y el reverso: filas iguales por coincidencia, en un archivo de pocas
    # columnas categóricas, NO son un duplicado que haya que reportar.
    encuesta = pd.DataFrame({
        "Sede": [random.choice(["Cali", "Bogotá"]) for _ in range(400)],
        "Turno": [random.choice(["AM", "PM"]) for _ in range(400)],
        "Calificacion": [random.choice([3, 4, 5]) for _ in range(400)],
    })
    check("las filas iguales por coincidencia no se reportan como duplicados",
          _por_titulo(hallazgos_de(encuesta), "Identificador repetido") is None)


if __name__ == "__main__":
    main()
