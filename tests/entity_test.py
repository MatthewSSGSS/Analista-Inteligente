"""Regresión del detector universal de entidades (core/entity_engine.py).

Verifica que encuentre la columna de código SIN pistas en el nombre, y —
igual de importante — que NO invente una entidad donde no la hay.

PYTHONPATH=. python tests/entity_test.py
"""
import pandas as pd

from core.entity_engine import analyze_entity_candidates, best_entity, describe_entity, value_mask
from core.profile import profile_sheet


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _schema(df):
    return profile_sheet(df, {"sheet_name": "X", "workbook_name": "x.xlsx"})["profile"]["schema"]


# ── Máscaras ──
def test_mascaras():
    check("máscara de D3243.00002", value_mask("D3243.00002") == "A9999.99999")
    check("máscara de LOC-4021", value_mask("LOC-4021") == "AAA-9999")
    check("máscara colapsada agrupa largos distintos",
          value_mask("D3243.00002", collapse=True) == value_mask("D3243.2", collapse=True))


# ── Caso principal: el de tu jefe. La columna se llama "Ref" (ninguna
# pista en el nombre) y el código determina local/ciudad/responsable. ──
def test_codigo_sin_pista_en_el_nombre():
    df = pd.DataFrame({
        "Ref": ["D3243.00002"] * 4 + ["D3244.00013"] * 3 + ["D3251.00007"] * 3,
        "Local": ["Tienda Norte"] * 4 + ["Tienda Sur"] * 3 + ["Tienda Centro"] * 3,
        "Ciudad": ["Bogotá"] * 4 + ["Cali"] * 3 + ["Medellín"] * 3,
        "Responsable": ["Ana Gómez"] * 4 + ["Luis Ruiz"] * 3 + ["Marta Díaz"] * 3,
        "Venta": [100, 340, 890, 120, 210, 430, 190, 300, 250, 410],
    })
    best = best_entity(df, _schema(df))
    print("    ", describe_entity(best))
    check("encuentra 'Ref' como entidad pese al nombre sin pistas", best and best["column"] == "Ref")
    check("reconoce el formato del código", best["mask"] == "A9999.99999")
    check("detecta los atributos que describe el código",
          set(best["determines"]) == {"Local", "Ciudad", "Responsable"})
    check("deja 'Venta' como actividad (varía, no describe)", "Venta" in best["varies"])
    check("confianza alta", best["confidence"] == "alta")


# ── Control 1: tabla sin ninguna entidad (categorías y medidas). No debe
# inventar un código. ──
def test_control_sin_entidad():
    df = pd.DataFrame({
        "Region": ["Norte", "Sur", "Centro", "Norte", "Sur", "Centro"] * 3,
        "Ventas": [100, 200, 150, 120, 210, 160] * 3,
        "Costos": [50, 90, 70, 60, 95, 75] * 3,
    })
    best = best_entity(df, _schema(df))
    check("no inventa entidad en una tabla de categorías y medidas", best is None)


# ── Control 2: una columna de cantidades con valores regulares (4 dígitos)
# no debe confundirse con un código. ──
def test_control_metrica_no_es_entidad():
    df = pd.DataFrame({
        "Vendedor": ["Ana", "Luis", "Marta", "Pedro", "Sofía", "Jorge"] * 3,
        "Unidades": [1200, 1350, 1480, 1510, 1620, 1730] * 3,
        "Ingresos": [5000, 6100, 7200, 8300, 9400, 10500] * 3,
    })
    cands = analyze_entity_candidates(df, _schema(df))
    picked = [c["column"] for c in cands]
    check("una métrica numérica no se propone como entidad", "Unidades" not in picked and "Ingresos" not in picked)


# ── Caso: código numérico (sin letras), que igual debe reconocerse. ──
def test_codigo_numerico():
    df = pd.DataFrame({
        "Punto": [4021] * 4 + [4022] * 4 + [4023] * 4,
        "Zona": ["Norte"] * 4 + ["Sur"] * 4 + ["Centro"] * 4,
        "Direccion": ["Cra 15"] * 4 + ["Cll 80"] * 4 + ["Av 68"] * 4,
        "Venta": [10, 20, 30, 40, 15, 25, 35, 45, 12, 22, 32, 42],
    })
    best = best_entity(df, _schema(df))
    print("    ", describe_entity(best))
    check("reconoce un código numérico como entidad", best and best["column"] == "Punto")
    check("y sus atributos", set(best["determines"]) == {"Zona", "Direccion"})


# ── Caso: dos candidatos (código de local y cédula). Debe rankear, y el
# ganador debe ser el que describe a más columnas. ──
def test_varios_candidatos_rankeados():
    df = pd.DataFrame({
        "Cod_Local": ["D01"] * 4 + ["D02"] * 4 + ["D03"] * 4,
        "Ciudad": ["Bogotá"] * 4 + ["Cali"] * 4 + ["Medellín"] * 4,
        "Zona": ["Norte"] * 4 + ["Sur"] * 4 + ["Centro"] * 4,
        "Cedula": [111, 222, 333, 444] * 3,
        "Venta": list(range(12)),
    })
    cands = analyze_entity_candidates(df, _schema(df))
    print("     ranking:", [(c["column"], c["score"]) for c in cands])
    check("propone más de un candidato", len(cands) >= 2)
    check("gana el que describe a más columnas", cands[0]["column"] == "Cod_Local")


# ── Caso: una fila por código (catálogo/ficha). Se detecta, pero marcado
# como que NO agrupa filas. ──
def test_catalogo_una_fila_por_codigo():
    df = pd.DataFrame({
        "SKU": [f"P-{i:04d}" for i in range(1, 11)],
        "Producto": [f"Producto {i}" for i in range(1, 11)],
        "Precio": [100 + i for i in range(10)],
    })
    best = best_entity(df, _schema(df))
    print("    ", describe_entity(best))
    check("detecta la entidad de un catálogo", best and best["column"] == "SKU")
    check("marca que no agrupa filas (una ficha por código)", best["groups_rows"] is False)


# ── Conexión con la vista de perfil (ui/person_profile.py) ──
def test_integracion_con_la_vista_de_perfil():
    from ui.person_profile import resolve_entity, has_entity

    # Un archivo de personas debe seguir resolviéndose como persona: la
    # detección de códigos es un RESPALDO, no un reemplazo.
    personas = pd.DataFrame({
        "Nombre": ["Ana", "Ana", "Luis", "Luis", "Marta", "Marta"],
        "Ciudad": ["Bogotá"] * 2 + ["Cali"] * 2 + ["Medellín"] * 2,
        "Ventas": [10, 20, 30, 40, 50, 60],
    })
    ent = resolve_entity(personas, _schema(personas))
    check("un archivo con nombres sigue perfilándose como persona", ent and ent["noun"] == "persona")

    # Un archivo de códigos ahora también habilita el perfil (antes no).
    codigos = pd.DataFrame({
        "Ref": ["D01.001"] * 3 + ["D02.002"] * 3 + ["D03.003"] * 3,
        "Local": ["Norte"] * 3 + ["Sur"] * 3 + ["Centro"] * 3,
        "Venta": list(range(9)),
    })
    ent2 = resolve_entity(codigos, _schema(codigos))
    check("un archivo con códigos habilita el perfil", ent2 and ent2["column"] == "Ref" and ent2["noun"] == "código")

    # Sin una entidad estricta, el seguimiento se ofrece igual sobre la unidad
    # de negocio. Antes esto devolvía None: una región que se repite en 12
    # filas no "identifica" a la fila, pero es exactamente lo que alguien
    # quiere seguir, y el archivo del que más se pregunta "¿cómo va esta
    # región?" era justo el que se quedaba sin la herramienta.
    plano = pd.DataFrame({"Region": ["Norte", "Sur", "Centro"] * 4,
                          "Ventas": list(range(12)), "Costos": list(range(12))})
    ent3 = resolve_entity(plano, _schema(plano))
    check("sin entidad estricta, se sigue la unidad de negocio",
          ent3 and ent3["column"] == "Region" and ent3["noun"] == "grupo")

    # Pero sin NADA que agrupar tampoco se inventa un sujeto: si cada valor
    # aparece una sola vez, no hay a quién hacerle seguimiento.
    suelto = pd.DataFrame({"Ventas": list(range(12)), "Costos": list(range(12))})
    check("sin ninguna columna que agrupe, no se ofrece seguimiento",
          has_entity(suelto, _schema(suelto)) is False)


if __name__ == "__main__":
    test_mascaras()
    test_codigo_sin_pista_en_el_nombre()
    test_control_sin_entidad()
    test_control_metrica_no_es_entidad()
    test_codigo_numerico()
    test_varios_candidatos_rankeados()
    test_catalogo_una_fila_por_codigo()
    test_integracion_con_la_vista_de_perfil()
    print("\nEntity test completado sin errores.")
