"""Regresión: al unir variantes del mismo valor, queda la forma bien escrita.

core/cleaner une "CAV", "Cav" y "cav" como un solo valor, y antes conservaba
la variante más frecuente —o, en empate, la primera que aparecía—. Así
quedaban «juan PEREZ» o «Medellin» en filtros, gráficos e informes cuando el
mismo archivo también traía «Juan Perez» o «Medellín». Ver
core/cleaner._la_mejor_escrita.

Se corre igual que tests/smoke_test.py: PYTHONPATH=. python tests/variantes_test.py
"""
import pandas as pd

from core.cleaner import _consolidate_spelling_variants


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _queda(valores):
    out, _ = _consolidate_spelling_variants(pd.Series(valores, dtype="string"))
    return sorted(set(out))


def queda_la_forma_bien_escrita():
    check("«Juan Perez» gana a «juan PEREZ» en empate", _queda(["juan PEREZ", "Juan Perez"]) == ["Juan Perez"])
    check("las tildes ganan aunque sean minoría", _queda(["Medellin", "Medellin", "Medellín"]) == ["Medellín"])
    check("y se pasan a la forma bien escrita", _queda(["Medellin", "medellín", "Medellin"]) == ["Medellín"])
    check("igual con nombres de persona", _queda(["ana gómez", "Ana Gomez", "Ana Gomez"]) == ["Ana Gómez"])
    check("los conectores van en minúscula",
          _queda(["Valle del Cauca", "VALLE DEL CAUCA", "valle del cauca"]) == ["Valle del Cauca"])
    check("a igual frecuencia, «Bogotá» antes que «BOGOTÁ»", _queda(["bogotá", "BOGOTA", "Bogota"]) == ["Bogotá"])


def las_siglas_y_la_frecuencia_se_respetan():
    check("una sigla en mayúsculas se conserva si es la habitual", _queda(["CAV"] * 5 + ["Cav", "cav"]) == ["CAV"])
    check("lo que ya estaba escrito de una sola forma no cambia",
          _consolidate_spelling_variants(pd.Series(["Norte", "Sur", "Norte"], dtype="string"))[1] == 0)


if __name__ == "__main__":
    queda_la_forma_bien_escrita()
    las_siglas_y_la_frecuencia_se_respetan()
    print("\nVariantes test completado sin errores.")
