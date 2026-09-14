"""Que la lectura comercial sirva para decidir, no solo para informar.

Lo que se prueba es el cruce que da sentido a la vista: peso × crecimiento.
Un canal grande que cae tiene que salir como urgencia aunque siga siendo el
número uno, y uno pequeño que crece al 40% como apuesta y no como rezagado.
Mirados por separado, esas dos lecturas salen al revés — y es la decisión
que se lleva a una gerencia.

PYTHONPATH=. python tests/comercial_test.py
"""
import pandas as pd

from core.comercial import columna_canal, matriz_comercial, oportunidades
from core.profile import profile_sheet


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _archivo(con_meta=True):
    """Cuatro canales, uno por cuadrante, construidos a propósito.

    Retail: grande y cae por MENOS operaciones.
    Aliados: grande y crece.
    Digital: pequeño y crece porque cada operación vale más.
    Call Center: pequeño y cae.
    """
    perfil = {
        "Retail":      {"ops": {"2026-05": 300, "2026-06": 250}, "ticket": {"2026-05": 1000, "2026-06": 960}},
        "Aliados":     {"ops": {"2026-05": 200, "2026-06": 225}, "ticket": {"2026-05": 1000, "2026-06": 1010}},
        "Digital":     {"ops": {"2026-05": 40,  "2026-06": 44},  "ticket": {"2026-05": 800,  "2026-06": 1040}},
        "Call Center": {"ops": {"2026-05": 60,  "2026-06": 52},  "ticket": {"2026-05": 700,  "2026-06": 690}},
    }
    metas = {"Retail": 280000, "Aliados": 210000, "Digital": 40000, "Call Center": 45000}
    filas = []
    for canal, cfg in perfil.items():
        for mes in ("2026-05", "2026-06"):
            for i in range(cfg["ops"][mes]):
                fila = {"Fecha": f"{mes}-{(i % 27) + 1:02d}", "Canal": canal,
                        "Ventas": int(cfg["ticket"][mes] * (0.9 + (i % 5) * 0.05))}
                if con_meta:
                    fila["Meta"] = metas[canal] / cfg["ops"][mes]
                filas.append(fila)
    item = profile_sheet(pd.DataFrame(filas), {"sheet_name": "V", "workbook_name": "v.xlsx"})
    return item["processed"], item["profile"]["schema"]


def _canal(matriz, nombre):
    return next(f for f in matriz["filas"] if f["canal"] == nombre)


def test_cada_canal_cae_en_su_cuadrante():
    df, schema = _archivo()
    check("se reconoce la columna de canal", columna_canal(df, schema) == "Canal")
    matriz = matriz_comercial(df, schema)
    check("la matriz se construye", matriz is not None)

    check("el grande que cae es una urgencia", _canal(matriz, "Retail")["cuadrante"] == "intervenir")
    check("el grande que crece se protege", _canal(matriz, "Aliados")["cuadrante"] == "proteger")
    check("el pequeño que crece es una apuesta", _canal(matriz, "Digital")["cuadrante"] == "apostar")
    check("el pequeño que cae se revisa", _canal(matriz, "Call Center")["cuadrante"] == "revisar")

    # Lo contrario de lo que diría un ranking por volumen: Retail es el número
    # uno del archivo y aun así es el problema del periodo.
    check("el más grande sigue siendo el más grande",
          max(matriz["filas"], key=lambda f: f["valor"])["canal"] == "Retail")
    check("y aun así encabeza la lista de atención", matriz["filas"][0]["canal"] == "Retail")
    check("el titular nombra la urgencia", "Retail" in matriz["titular"])


def test_separa_volumen_de_ticket():
    """Cobertura y precio son dos palancas distintas y se accionan distinto."""
    df, schema = _archivo()
    matriz = matriz_comercial(df, schema)
    retail, digital = _canal(matriz, "Retail"), _canal(matriz, "Digital")
    check("del que hace menos operaciones, se dice eso", retail["palanca"] == "volumen")
    check("y se cuantifica", "operaciones" in (retail["mezcla"] or ""))
    check("del que sube el valor por operación, también", digital["palanca"] == "ticket")
    check("y se distingue del volumen", "vale más" in (digital["mezcla"] or ""))


def test_las_jugadas_traen_su_cifra():
    df, schema = _archivo()
    jugadas = oportunidades(matriz_comercial(df, schema))
    check("hay jugadas concretas", bool(jugadas))
    check("cada una trae su impacto", all(j["impacto"] > 0 for j in jugadas))
    check("ordenadas de mayor a menor impacto",
          [j["impacto"] for j in jugadas] == sorted([j["impacto"] for j in jugadas], reverse=True))
    check("la primera es recuperar lo que cayó el canal grande",
          jugadas[0]["canal"] == "Retail" and jugadas[0]["tipo"] == "Recuperar")
    check("ningún canal aparece dos veces",
          len({j["canal"] for j in jugadas}) == len(jugadas))


def test_el_cumplimiento_usa_la_meta_del_archivo():
    df, schema = _archivo(con_meta=True)
    matriz = matriz_comercial(df, schema)
    check("se detecta la columna de meta", matriz["meta_columna"] == "Meta")
    check("y cada canal trae su cumplimiento",
          all(f["cumplimiento"] is not None for f in matriz["filas"]))

    sin_meta = matriz_comercial(*_archivo(con_meta=False))
    check("sin meta, la matriz sigue funcionando", sin_meta is not None)
    check("pero no se inventa un cumplimiento",
          all(f["cumplimiento"] is None for f in sin_meta["filas"]))


def test_se_calla_cuando_no_aplica():
    catalogo = profile_sheet(
        pd.DataFrame({"Producto": [f"SKU{i}" for i in range(20)], "Precio": range(20)}),
        {"sheet_name": "H", "workbook_name": "h.xlsx"})
    check("un catálogo sin fechas no produce matriz",
          matriz_comercial(catalogo["processed"], catalogo["profile"]["schema"]) is None)

    un_periodo = profile_sheet(
        pd.DataFrame({"Fecha": ["2026-06-10"] * 12, "Canal": ["A", "B", "C"] * 4,
                      "Ventas": list(range(12))}),
        {"sheet_name": "H", "workbook_name": "h.xlsx"})
    check("con un solo periodo no hay crecimiento que medir",
          matriz_comercial(un_periodo["processed"], un_periodo["profile"]["schema"]) is None)


def test_las_barras_traen_referencia():
    """Un ranking sin referencia solo dice quién va primero."""
    from visualization.charts import ranking

    df, schema = _archivo()
    fig = ranking(df, schema)
    barras = [t for t in fig.data if t.type == "bar"]
    check("el ranking se dibuja", bool(barras))
    check("con las esquinas redondeadas", barras[0].marker.cornerradius == 7)
    check("y una línea de referencia para leer quién está por encima",
          any(sh.type == "line" for sh in fig.layout.shapes))


def _archivo_quieto():
    """Nueve puntos de nombre largo que se movieron menos de 1%: el caso real
    que dejó al descubierto la primera versión de la matriz."""
    nombres = ["INVERSIONES GERA SAS CARTAGENA", "INVERSIONES ARAUJO DOMINGUEZ SAS MONTERIA CORDOBA",
               "DANCELL RIOHACHA LA GUAJIRA", "MC MULTICELL SAS CIENEGA MAGDALENA",
               "DANCELL VALLEDUPAR CESAR", "CELUNORTE COMUNICACIONES SAS SINCELEJO SUCRE",
               "COMMUTE SAS SOLEDAD ATLANTICO", "COMMUTE SAS BARRANQUILLA ATLANTICO",
               "SOUL CENTRO DE TECNOLOGIA SAS SAN ANDRES"]
    pesos = [180, 175, 135, 120, 118, 95, 90, 82, 8]
    filas = []
    for nombre, peso in zip(nombres, pesos):
        for mes, factor in (("2026-07", 1.0), ("2026-08", 0.995)):
            for i in range(20):
                filas.append({"Fecha": f"{mes}-{i + 1:02d}", "NOMBREPUNTO": nombre,
                              "ALTAS": peso * factor * (0.95 + (i % 3) * 0.05)})
    item = profile_sheet(pd.DataFrame(filas), {"sheet_name": "V", "workbook_name": "v.xlsx"})
    return item["processed"], item["profile"]["schema"]


def test_lo_que_no_se_mueve_es_estable():
    """Un -0,5% no es una caída ni un crecimiento, y forzarle una jugada era
    lo que pintaba burbujas verdes dentro de la zona roja."""
    df, schema = _archivo_quieto()
    matriz = matriz_comercial(df, schema)
    check("con movimientos menores a 1%, todos los canales son estables",
          {f["cuadrante"] for f in matriz["filas"]} == {"estable"})
    check("el titular lo dice en vez de inventar una urgencia", "Ningún canal se movió" in matriz["titular"])
    check("y nombra lo que más pesa, que es lo que queda por decidir",
          "INVERSIONES GERA SAS CARTAGENA" in matriz["titular"])
    jugadas = oportunidades(matriz)
    check("sin urgencias, la jugada es sostener lo que pesa",
          bool(jugadas) and all(j["tipo"] == "Sostener" for j in jugadas))


def test_el_mapa_no_se_monta():
    """Con canales que se mueven parecido, la matriz de burbujas los apilaba en
    una columna y los números dejaban de leerse. En el mapa, cada canal tiene
    su fila: no hay forma de que dos se tapen."""
    from core.comercial import UMBRAL_MOVIMIENTO
    from ui.comercial import _aporte_figura, _matriz_figura

    for nombre, (df, schema) in (("quieto", _archivo_quieto()), ("con movimiento", _archivo())):
        matriz = matriz_comercial(df, schema)
        figura = _matriz_figura(matriz, schema)
        puntos = [t for t in figura.data if t.type == "scatter"][0]
        check(f"[{nombre}] cada canal ocupa su propia fila",
              len(set(puntos.y)) == len(puntos.y) == len(matriz["filas"]))
        maximo = max(abs(f["crecimiento"]) for f in matriz["filas"] if f["crecimiento"] is not None)
        check(f"[{nombre}] el eje se ajusta a lo que se movieron los canales",
              figura.layout.xaxis.range[1] <= max(maximo * 1.3, 3) + 1e-9)
        bordes = {round(v, 9) for forma in figura.layout.shapes if forma.type == "rect"
                  for v in (forma.x0, forma.x1)}
        check(f"[{nombre}] las franjas cortan en el mismo umbral que clasifica",
              -UMBRAL_MOVIMIENTO in bordes and UMBRAL_MOVIMIENTO in bordes)
        pesan = sum(1 for f in matriz["filas"] if f.get("pesa"))
        if 0 < pesan < len(matriz["filas"]):
            separadores = [forma for forma in figura.layout.shapes
                           if forma.type == "line" and forma.xref == "paper"]
            check(f"[{nombre}] la línea punteada separa a los que pesan más que el promedio",
                  any(abs(forma.y0 - (pesan - 0.5)) < 1e-9 for forma in separadores))
        check(f"[{nombre}] el hover muestra un canal a la vez", figura.layout.hovermode == "closest")
        aporte = _aporte_figura(matriz, schema)
        izquierda, derecha = aporte.layout.xaxis.range
        valores = list(aporte.data[0].x)
        check(f"[{nombre}] las barras de aporte no se recortan contra el borde",
              izquierda < min(min(valores), 0) and derecha > max(max(valores), 0))


def test_la_escala_de_color_distingue_casi_de_lejos():
    """Rojo o verde a secas pintaba igual un 88% que un 40% de la meta."""
    import streamlit as st

    from core.comercial import estado_salud, puntaje_salud
    from ui.comercial import _color_escala, _semaforo

    check("80% de la meta o menos es el extremo rojo", puntaje_salud({"cumplimiento": 70})[0] == 0.0)
    check("90% de la meta queda en el medio", abs(puntaje_salud({"cumplimiento": 90})[0] - 0.5) < 1e-9)
    check("100% o más es el extremo verde", puntaje_salud({"cumplimiento": 130})[0] == 1.0)
    check("si hay meta, manda sobre el crecimiento",
          puntaje_salud({"cumplimiento": 100, "crecimiento": -20})[1] == "meta")
    check("sin meta, se usa el crecimiento",
          puntaje_salud({"cumplimiento": None, "crecimiento": 5})[0] == 1.0)
    check("los extremos son el rojo y el verde de la paleta",
          _color_escala(0) == "#E4002B" and _color_escala(1) == "#22A06B")
    check("un 88% y un 91% no se pintan igual",
          _color_escala(puntaje_salud({"cumplimiento": 88})[0])
          != _color_escala(puntaje_salud({"cumplimiento": 91})[0]))
    check("el estado también se dice en palabras",
          (estado_salud(0.1), estado_salud(0.5), estado_salud(0.9)) == ("Crítico", "Atención", "Va bien"))

    df, schema = _archivo()
    capturado = []
    original = st.markdown
    st.markdown = lambda html, **k: (capturado.append(str(html)), original(html, **k))[1]
    try:
        _semaforo(matriz_comercial(df, schema), schema)
    finally:
        st.markdown = original
    html = "".join(capturado)
    colores = {parte.split(")")[0].split('"')[0] for parte in html.split("--c:")[1:]}
    check("en el semáforo las tarjetas ya no salen todas del mismo color", len(colores) >= 3)
    check("y se explica qué significa el color", "Color de cada tarjeta" in html)


if __name__ == "__main__":
    test_cada_canal_cae_en_su_cuadrante()
    test_separa_volumen_de_ticket()
    test_las_jugadas_traen_su_cifra()
    test_el_cumplimiento_usa_la_meta_del_archivo()
    test_se_calla_cuando_no_aplica()
    test_las_barras_traen_referencia()
    test_lo_que_no_se_mueve_es_estable()
    test_el_mapa_no_se_monta()
    test_la_escala_de_color_distingue_casi_de_lejos()
    print("\nComercial test completado sin errores.")
