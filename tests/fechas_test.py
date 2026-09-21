"""Regresión de las fechas con zona horaria mezclada.

Un export que guarda la hora LOCAL de cada registro deja una columna con
desfases distintos en la misma columna ("10:00+00:00" en una fila y
"23:30-05:00" en otra). Desde pandas 2.2 eso hace que `to_datetime` lance
"Mixed timezones detected. Pass utc=True…", y ese mensaje llegaba tal cual a
la pantalla: el archivo entero no se podía abrir.

Lo importante de este archivo: la simulación de pandas ESTRICTO
(`_pandas_estricto`). En algunas versiones el caso solo avisa en vez de
lanzar, así que un test que dependa de la versión instalada puede pasar en
el portátil y fallar en el servidor — que es justo lo que ocurrió. Aquí se
fuerza el comportamiento estricto para comprobarlo siempre.

Se corre igual que tests/smoke_test.py: PYTHONPATH=. python tests/fechas_test.py
"""
import io
import re
from contextlib import contextmanager

import pandas as pd
from openpyxl import Workbook

from core import dates as D
from core.dates import a_datetime, date_only
from core.filter_engine import mascara_regla
from core.loader import load_workbook

_TZ = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})\s*$", re.I)


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("OK  ", label)


@contextmanager
def _pandas_estricto():
    """Obliga a `to_datetime` a lanzar con desfases mezclados, como hace el
    pandas del servidor. Sin esto el test pasaría por la versión instalada,
    no por el código."""
    real = pd.to_datetime

    def estricto(arg, *a, **kw):
        if not kw.get("utc"):
            try:
                valores = [str(v) for v in list(arg)]
            except TypeError:
                valores = [str(arg)]
            desfases = {m.group(0) for m in (_TZ.search(v) for v in valores if v and v != "nan") if m}
            if len(desfases) > 1:
                raise ValueError(
                    "Mixed timezones detected. Pass utc=True in to_datetime or tz='UTC' "
                    "in DatetimeIndex to convert to a common timezone."
                )
        return real(arg, *a, **kw)

    pd.to_datetime, D.pd.to_datetime = estricto, estricto
    try:
        yield
    finally:
        pd.to_datetime, D.pd.to_datetime = real, real


MEZCLA = ["2026-01-15 10:00:00+00:00", "2026-02-15 23:30:00-05:00", "2026-03-15 08:00:00+02:00"]


def _upload_xlsx(name, filas, titulo="Hoja1"):
    wb = Workbook()
    ws = wb.active
    ws.title = titulo
    for f in filas:
        ws.append(f)
    b = io.BytesIO()
    wb.save(b)
    return type("Upload", (), {"getvalue": lambda self, d=b.getvalue(): d, "name": name})()


def la_simulacion_reproduce_el_error():
    with _pandas_estricto():
        try:
            pd.to_datetime(pd.Series(MEZCLA))
            check("la simulación reproduce el error del servidor", False)
        except ValueError as e:
            check("la simulación reproduce el error del servidor", "Mixed timezones" in str(e))


def fechas_mezcladas_se_leen_sin_tumbar_nada():
    for etiqueta, contexto in [("con pandas normal", None), ("con pandas estricto", _pandas_estricto)]:
        gestor = contexto() if contexto else None
        if gestor:
            gestor.__enter__()
        try:
            r = date_only(pd.Series(MEZCLA))
            check(f"{etiqueta}: las tres fechas se leen", r.notna().all())
            check(f"{etiqueta}: quedan sin zona horaria", str(r.dtype) == "datetime64[ns]")
            check(f"{etiqueta}: con el día que dice el archivo",
                  r.dt.strftime("%Y-%m-%d").tolist() == ["2026-01-15", "2026-02-15", "2026-03-15"])
        finally:
            if gestor:
                gestor.__exit__(None, None, None)


def un_registro_nocturno_no_salta_de_dia():
    """La decisión de negocio que ya documentaba `date_only`: no se convierte
    a UTC, porque un registro de las 23:30 en -05:00 se reportaría al día
    siguiente y para quien lee el informe eso es sencillamente un error."""
    with _pandas_estricto():
        r = date_only(pd.Series(["2026-02-15 23:30:00-05:00", "2026-02-15 10:00:00+00:00"]))
    check("«15/02 23:30 -05:00» se reporta el día 15, no el 16", r.dt.day.tolist() == [15, 15])


def columnas_ya_fechadas_y_casos_raros():
    with _pandas_estricto():
        check("una columna ya con zona única sale sin zona",
              str(a_datetime(pd.Series(pd.to_datetime(
                  ["2026-01-15 10:00:00+00:00", "2026-02-15 10:00:00+00:00"], utc=True))).dtype)
              == "datetime64[ns]")
        check("una columna sin fechas no se rompe", a_datetime(pd.Series(["hola", "qué tal"])).isna().all())
        check("vacíos y basura mezclados con fechas se toleran",
              a_datetime(pd.Series([MEZCLA[0], None, "no es fecha", MEZCLA[1]])).notna().sum() == 2)


def el_archivo_completo_carga_y_se_puede_filtrar():
    filas = [["Fecha", "Ciudad", "Ventas"]]
    filas += [[f, c, v] for f, c, v in zip(MEZCLA, ["Bogotá", "Cali", "Medellín"], [10, 20, 30])]
    with _pandas_estricto():
        libro = load_workbook(_upload_xlsx("mixto_tz.xlsx", filas))
        item = libro["sheets"]["Hoja1"]
        df, esquema = item["processed"], item["profile"]["schema"]
        check("el archivo con zonas mezcladas se abre", len(df) == 3)
        check("y la columna queda reconocida como fecha", esquema.get("dates") == ["Fecha"])
        check("sin zona horaria, que es lo que el resto del panel compara",
              str(df["Fecha"].dtype) == "datetime64[ns]")

        # El filtro de fechas de la barra lateral, sobre esa misma columna.
        mascara = mascara_regla(df["Fecha"], {"op": "date_between",
                                              "value": ["2026-02-01", "2026-03-31"],
                                              "incluir_vacios": False})
        check("el filtro por rango de fechas funciona sobre esa columna", int(mascara.sum()) == 2)


if __name__ == "__main__":
    la_simulacion_reproduce_el_error()
    fechas_mezcladas_se_leen_sin_tumbar_nada()
    un_registro_nocturno_no_salta_de_dia()
    columnas_ya_fechadas_y_casos_raros()
    el_archivo_completo_carga_y_se_puede_filtrar()
    print("\nFechas test completado sin errores.")
