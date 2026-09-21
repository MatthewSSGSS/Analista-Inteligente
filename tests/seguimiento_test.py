"""Regresión del camino que alimenta el historial compartido (Supabase).

El recorrido completo es: archivo subido → core/loader (aplana dinámicas)
→ core/tracking_engine.ingest_file (decide quién es cada fila) →
sources_to_long (tabla larga) → core/db_engine.save_to_db (la escribe en la
base). Aquí se cubren los dos primeros tramos, que son los que deciden si un
archivo entra al historial o se queda fuera; db_engine no se toca porque
necesita una base real.

Lo que se verifica es que ese recorrido acepte por igual las dos formas en
que la gente entrega un archivo: tabla ordenada (una fila por registro) y
tabla dinámica (una fila por persona y una columna por mes).

Se corre igual que tests/smoke_test.py: PYTHONPATH=. python tests/seguimiento_test.py
"""
import io

import pandas as pd

from core.tracking_engine import (CONSOLIDATED_COLUMNS, ingest_file, merge_long,
                                  sources_to_long)


def _upload_xlsx(name, rows, sheet="Hoja1"):
    b = io.BytesIO()
    pd.DataFrame(rows).to_excel(b, index=False, sheet_name=sheet, header=False)
    return type("Upload", (), {"getvalue": lambda self: b.getvalue(), "name": name})()


def _upload_csv(name, text):
    data = text.encode("utf-8")
    return type("Upload", (), {"getvalue": lambda self, d=data: d, "name": name})()


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


def _largo(upload):
    fuentes = ingest_file(upload, batch_label="test")
    return fuentes, sources_to_long(fuentes, upload_batch="test")


# ── Tabla ordenada: el caso que siempre funcionó. Es el control de que
# ninguna de las correcciones para dinámicas le cambió nada. ──
def plana_con_id_y_fecha():
    fuentes, largo = _largo(_upload_xlsx("plana.xlsx", [
        ["Cedula", "Nombre", "Mes", "Ventas"],
        ["1001", "Ana Ruiz", "2026-01-01", 10],
        ["1001", "Ana Ruiz", "2026-02-01", 12],
        ["1002", "Luis Paz", "2026-01-01", 8],
    ]))
    check("la tabla ordenada entra al historial", len(fuentes) == 1)
    check("se cruza por cédula, no por nombre", set(largo["person_key"]) == {"1001", "1002"})
    check("la confianza del cruce es alta (hay ID)", set(largo["match_confidence"]) == {"alta"})
    check("el periodo sale de la columna de fecha", largo["period"].notna().all())
    check("cada medida conserva su nombre", "Ventas" in set(largo["column"]))


# ── Sin ID y con la persona en una columna llamada "Asesor": el motor
# semántico la tipa como `employee`, no como `name`. Antes ingest_file
# descartaba la hoja entera ("no tiene una columna de ID o nombre
# reconocible") y el archivo no llegaba nunca a la base. ──
def sin_id_con_columna_asesor():
    fuentes, largo = _largo(_upload_xlsx("asesores.xlsx", [
        ["Asesor", "Mes", "Ventas"],
        ["Ana Ruiz", "2026-01-01", 10],
        ["Ana Ruiz", "2026-02-01", 12],
        ["Luis Paz", "2026-01-01", 8],
    ]))
    check("una hoja sin ID pero con 'Asesor' ya no se descarta", len(fuentes) == 1)
    check("'Asesor' se reconoce como la columna de la persona", fuentes[0]["name_col"] == "Asesor")
    check("el cruce cae a nombre, con confianza media", set(largo["match_confidence"]) == {"media"})
    check("el nombre queda guardado", set(largo["person_name"]) == {"Ana Ruiz", "Luis Paz"})
    check("'Asesor' no se guarda además como si fuera una medida", "Asesor" not in set(largo["column"]))


# ── Dinámica ancha en CSV: una fila por persona, una columna por mes. El
# lector de informes (que convierte esta forma en tabla ordenada) solo corre
# sobre hojas de Excel, así que en CSV los meses siguen siendo columnas:
# antes cada mes entraba como una medida distinta y con el periodo en NULL,
# que es justo lo que deja sin línea de tiempo ni proyección. ──
def dinamica_csv_meses_en_columnas():
    fuentes, largo = _largo(_upload_csv("dinamica.csv",
        "Cedula,Nombre,ene-26,feb-26,mar-26\n"
        "1001,Ana Ruiz,10,12,15\n"
        "1002,Luis Paz,8,9,11\n"
    ))
    check("la dinámica en CSV entra al historial", len(fuentes) == 1)
    check("ninguna fila queda sin periodo", largo["period"].notna().all())
    check("los meses se leen como periodos reales, no como nombres de medida",
          sorted(largo["period"].dt.strftime("%Y-%m").unique().tolist()) == ["2026-01", "2026-02", "2026-03"])
    check("los 3 meses dejan de ser 3 medidas distintas", set(largo["column"]) == {"Valor"})
    check("se conservan los 6 valores (2 personas × 3 meses)", len(largo) == 6)
    check("sigue cruzando por cédula", set(largo["person_key"]) == {"1001", "1002"})


# ── La misma dinámica, pero en Excel: ahí sí la aplana el lector de informes
# (queda Asesor | Mes | Valor). Debe llegar al historial con los mismos
# periodos que la versión CSV — el resultado no puede depender del formato
# en que se entregó el archivo. ──
def dinamica_xlsx_equivale_a_la_csv():
    _, largo = _largo(_upload_xlsx("dinamica.xlsx", [
        ["Nombre", "ene-26", "feb-26", "mar-26"],
        ["Ana Ruiz", 10, 12, 15],
        ["Luis Paz", 8, 9, 11],
    ]))
    check("la dinámica en Excel también entra al historial", len(largo) == 6)
    check("con los mismos 3 periodos que la versión CSV",
          sorted(largo["period"].dt.strftime("%Y-%m").unique().tolist()) == ["2026-01", "2026-02", "2026-03"])
    check("y con una sola medida", set(largo["column"]) == {"Valor"})


# ── Una tabla ordenada que además trae una columna llamada como un mes no
# debe reinterpretarse: si la hoja tiene su propia columna de fecha, manda
# esa. Es el control de que la lectura de meses-en-columnas no se active
# donde no toca. ──
def plana_con_fecha_propia_no_se_reinterpreta():
    _, largo = _largo(_upload_xlsx("mixta.xlsx", [
        ["Cedula", "Nombre", "Mes", "Ventas"],
        ["1001", "Ana Ruiz", "2026-01-01", 10],
        ["1001", "Ana Ruiz", "2026-02-01", 12],
    ]))
    check("el periodo sigue saliendo de la columna de fecha", largo["period"].notna().all())
    check("la medida conserva su nombre original", set(largo["column"]) == {"Ventas"})


# ── Lo que la base recibe al final: subir dos veces el mismo archivo no
# puede duplicar el historial (save_to_db escribe merge_long tal cual). ──
def merge_no_duplica_al_resubir():
    _, largo = _largo(_upload_csv("dinamica.csv",
        "Cedula,Nombre,ene-26,feb-26\n1001,Ana Ruiz,10,12\n"))
    combinado = merge_long(largo, largo)
    check("resubir el mismo archivo no duplica filas", len(combinado) == len(largo))


# ── Lo que se escribe en la base tiene un esquema FIJO (CONSOLIDATED_COLUMNS,
# la tabla `tracking_history`): venga el archivo plano o dinámico, las
# columnas y los tipos que recibe `save_to_db` tienen que ser los mismos, o
# la misma persona quedaría guardada de dos formas distintas según cómo se
# entregó el archivo. ──
def convergencia_del_esquema_que_va_a_la_base():
    plano = ("Cedula,Nombre,Mes,Valor\n"
             "1001,Ana Ruiz,2026-01-01,10\n1001,Ana Ruiz,2026-02-01,12\n1001,Ana Ruiz,2026-03-01,15\n"
             "1002,Luis Paz,2026-01-01,8\n1002,Luis Paz,2026-02-01,9\n1002,Luis Paz,2026-03-01,11\n")
    dinamico = ("Cedula,Nombre,ene-26,feb-26,mar-26\n"
                "1001,Ana Ruiz,10,12,15\n1002,Luis Paz,8,9,11\n")
    _, largo_plano = _largo(_upload_csv("plano.csv", plano))
    _, largo_dinamico = _largo(_upload_csv("dinamico.csv", dinamico))

    check("las dos rutas entregan las mismas columnas, en el mismo orden",
          list(largo_plano.columns) == list(largo_dinamico.columns) == CONSOLIDATED_COLUMNS)
    check("y con los mismos tipos",
          [str(t) for t in largo_plano.dtypes] == [str(t) for t in largo_dinamico.dtypes])
    check("el periodo es fecha en las dos", all(
        str(d["period"].dtype).startswith("datetime64") for d in (largo_plano, largo_dinamico)))
    # Mismo dato lógico: mismas personas, mismos periodos, mismos valores.
    clave = lambda d: sorted(zip(d["person_key"], d["period"].astype(str), d["value"].astype(str)))
    check("y el mismo contenido persona × periodo × valor", clave(largo_plano) == clave(largo_dinamico))


if __name__ == "__main__":
    plana_con_id_y_fecha()
    sin_id_con_columna_asesor()
    dinamica_csv_meses_en_columnas()
    dinamica_xlsx_equivale_a_la_csv()
    plana_con_fecha_propia_no_se_reinterpreta()
    merge_no_duplica_al_resubir()
    convergencia_del_esquema_que_va_a_la_base()
    print("\nSeguimiento test completado sin errores.")
