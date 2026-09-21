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
from core.semantic_engine import _date_rate
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
    """Todo queda en hora de Colombia, y el día que se reporta es el
    colombiano. Un registro guardado en UTC como "2026-02-16 04:30Z" ocurrió
    la noche del 15 en Bogotá: reportarlo el 16 sería contarlo en un día que
    aquí todavía no había empezado."""
    with _pandas_estricto():
        r = date_only(pd.Series(["2026-02-15 23:30:00-05:00", "2026-02-16 04:30:00+00:00"]))
    check("«15/02 23:30 -05:00» se reporta el día 15", r.dt.day.iloc[0] == 15)
    check("y «16/02 04:30 UTC» también, porque en Colombia es la misma noche",
          r.dt.day.iloc[1] == 15)


def todo_queda_en_el_dia_colombiano_y_sin_hora():
    """Dos cosas a la vez: el día es el colombiano, y la hora se borra.

    La hora se quita a propósito —no se usa en ningún cálculo ni vista del
    panel— y quitarla es lo que impide que el error de zonas mezcladas
    vuelva por cualquier camino: sin hora no hay zona que reconciliar.
    Pero se borra DESPUÉS de convertir: los tres valores de abajo son el
    mismo instante, y en Colombia ese instante cae el día 15.
    """
    with _pandas_estricto():
        r = a_datetime(pd.Series(["2026-02-16 04:30:00+00:00",   # UTC
                                  "2026-02-15 23:30:00-05:00",   # ya colombiana
                                  "2026-02-16 06:30:00+02:00"]))  # otra zona
    check("tres desfases distintos caen en el mismo día colombiano",
          r.dt.strftime("%Y-%m-%d").tolist() == ["2026-02-15"] * 3)
    check("y ninguno conserva la hora", bool((r.dt.time.astype(str) == "00:00:00").all()))


def las_fechas_sin_zona_no_se_mueven():
    """El control más importante: la inmensa mayoría de los archivos NO trae
    zona horaria. Si se parsearan como UTC y se pasaran a Bogotá, cada fecha
    retrocedería cinco horas y se iría al día anterior."""
    with _pandas_estricto():
        for etiqueta, valores, esperado in [
            ("solo fecha", ["2026-01-15", "2026-02-20"], ["2026-01-15", "2026-02-20"]),
            ("fecha y hora", ["2026-01-15 08:30:00"], ["2026-01-15"]),
            ("formato español", ["15/01/2026"], ["2026-01-15"]),
            ("español con hora", ["20/02/2026 09:00"], ["2026-02-20"]),
        ]:
            r = a_datetime(pd.Series(valores))
            check(f"«{etiqueta}» se queda en su día", r.dt.strftime("%Y-%m-%d").tolist() == esperado)

    # Y en una columna MIXTA, cada fila se trata según lo que ella misma dice:
    # la de UTC se corrige a su día colombiano (el 15, no el 16) y la que no
    # trae zona se queda en el suyo.
    with _pandas_estricto():
        r = a_datetime(pd.Series(["2026-02-16 04:30:00+00:00", "2026-02-20 09:00:00", None]))
    check("en una columna mixta, la de UTC se corrige y la ingenua no se toca",
          r.dt.strftime("%Y-%m-%d").tolist()[:2] == ["2026-02-15", "2026-02-20"])
    check("y los vacíos siguen vacíos", bool(r.isna().iloc[2]))


def columnas_con_nombre_duplicado_tambien_se_normalizan():
    """La causa real del fallo que siguió apareciendo en producción.

    Con dos columnas que se llaman igual —dos "Fecha", o varias sin
    encabezado, de lo más común en estos informes— `df[nombre]` no devuelve
    una serie sino un DataFrame. `normalize_timezones` lanzaba AttributeError,
    su `except` se lo tragaba y la columna se saltaba ENTERA, sin avisar.
    Luego `clean()` renombraba los duplicados y las zonas horarias llegaban
    vivas a la clasificación semántica, que es donde reventaba
    (`semantic_engine._date_rate`).
    """
    from core.cleaner import clean, normalize_timezones

    df = pd.DataFrame([["2026-01-15 10:00:00+00:00", "2026-02-15 23:30:00-05:00", 1],
                       ["2026-03-15 08:00:00+02:00", "2026-04-15 10:00:00+00:00", 2]],
                      columns=["Fecha", "Fecha", "V"])
    check("con nombres duplicados, las DOS columnas se normalizan",
          len(normalize_timezones(df.copy())) == 2)

    limpio, _ = clean(df)
    con_zona = 0
    for col in limpio.columns:
        serie = limpio[col]
        if getattr(serie, "ndim", 1) != 1:
            continue
        for v in serie.dropna():
            try:
                t = pd.Timestamp(v)
                con_zona += (not pd.isna(t)) and t.tzinfo is not None
            except (ValueError, TypeError):
                pass
    check("tras limpiar no queda ningún valor con zona horaria", con_zona == 0)

    # Y el punto exacto donde reventaba: la clasificación semántica.
    with _pandas_estricto():
        for col in limpio.columns:
            serie = limpio[col]
            if getattr(serie, "ndim", 1) == 1:
                _date_rate(serie)
    check("la clasificación semántica ya no revienta con esas columnas", True)


def la_clasificacion_semantica_aguanta_los_formatos_raros():
    """`_date_rate` recortaba la zona con un patrón que reconocía "+00:00" y
    "Z" pero no "-05", " UTC" ni "GMT-5": con esos, el desfase sobrevivía al
    recorte y pandas se negaba a construir la columna."""
    with _pandas_estricto():
        for etiqueta, valores in {
            "-05 (dos dígitos)": ["2026-01-15 10:00:00-05", "2026-02-15 23:30:00+00:00"],
            "UTC escrito": ["2026-01-15 10:00:00 UTC", "2026-02-15 23:30:00-05:00"],
            "con zona y sin zona": ["2026-01-15 10:00:00+00:00", "2026-02-15 23:30:00"],
        }.items():
            tasa = _date_rate(pd.Series(valores))
            check(f"«{etiqueta}» se clasifica como fecha sin reventar", tasa == 1.0)


def una_columna_con_formatos_distintos_no_pierde_filas():
    """Una misma columna puede traer "2026-01-15" en una fila y
    "20/02/2026 09:00" en otra. pandas, por defecto, deduce el formato del
    primer valor y convierte en vacío TODO lo que no encaje — media columna
    desaparecía sin decir nada. Por eso se interpreta valor por valor."""
    with _pandas_estricto():
        r = a_datetime(pd.Series(["2026-01-15", "2026-02-20 09:00:00", "15/03/2026",
                                  "2026-04-16 04:30:00+00:00"]))
    check("las cuatro filas se leen, con formatos distintos", r.notna().all())
    check("cada una con su fecha correcta",
          r.dt.strftime("%Y-%m-%d").tolist() == ["2026-01-15", "2026-02-20", "2026-03-15", "2026-04-15"])


def el_resultado_es_siempre_una_columna_de_fechas():
    """La versión anterior partía la columna en trozos, los interpretaba por
    separado y los volvía a juntar con `.loc`. Cuando un trozo volvía como
    objetos con zonas distintas, esa asignación metía fechas con zona dentro
    de una columna sin zona y pandas reventaba por dentro con un "Something
    has gone wrong, please report a bug". El resultado debe ser siempre una
    columna de fechas de verdad, nunca una de objetos sueltos."""
    entradas = [
        ["2026-01-15 10:00:00+00:00", "2026-02-15 23:30:00-05:00"],       # desfases mezclados
        ["2026-01-15 10:00:00-05", "2026-01-15 15:00:00 UTC"],            # formatos raros
        ["2026-01-15 10:00:00+00:00", "2026-02-15 23:30:00", "no es"],    # con zona, sin zona y basura
        ["hola", "mundo"],                                                 # nada parseable
        [None, None],                                                      # todo vacío
    ]
    with _pandas_estricto():
        for valores in entradas:
            r = a_datetime(pd.Series(valores))
            check(f"«{str(valores[0])[:26]}…» devuelve una columna de fechas",
                  str(r.dtype) == "datetime64[ns]")


FORMATOS_DE_ZONA = {
    "ISO con +00:00 / -05:00": ["2026-01-15 10:00:00+00:00", "2026-02-15 23:30:00-05:00", "2026-03-15 08:00:00+02:00"],
    "con T y Z": ["2026-01-15T10:00:00Z", "2026-02-15T23:30:00-05:00", "2026-03-15T08:00:00+02:00"],
    "-05 de dos dígitos": ["2026-01-15 10:00:00-05", "2026-02-15 10:00:00+00:00", "2026-03-15 10:00:00-05"],
    "UTC / GMT-5 escritos": ["2026-01-15 10:00:00 UTC", "2026-02-15 10:00:00 GMT-5", "2026-03-15 10:00:00 UTC"],
    "desfase con segundos": ["2026-01-15 10:00:00+00:00:00", "2026-02-15 10:00:00-05:00:00", "2026-03-15 10:00:00+00:00:00"],
    "nombre de zona": ["2026-01-15 10:00:00 America/Bogota", "2026-02-15 10:00:00 UTC", "2026-03-15 10:00:00 EST"],
    "milisegundos": ["2026-01-15 10:00:00.123+00:00", "2026-02-15 23:30:00.456-05:00", "2026-03-15 08:00:00.7Z"],
    "con y sin zona": ["2026-01-15 10:00:00+00:00", "2026-02-15 09:00:00", "2026-03-15"],
    "español con zona": ["15/01/2026 14:30:00-05:00", "20/02/2026 09:00:00+00:00", "25/03/2026 18:00:00Z"],
    "con prefijo": ["Fecha: 2026-01-15 10:00Z", "Fecha: 2026-02-15 10:00-05:00", "Fecha: 2026-03-15 10:00Z"],
}


def cualquier_forma_de_escribir_la_zona_abre_el_archivo():
    """La batería que faltaba: el archivo COMPLETO, con la zona escrita de
    todas las formas que se han visto.

    Este error tumbó la carga cuatro veces seguidas. Cada arreglo cubría el
    formato de esa vez y fallaba con el siguiente, porque todos intentaban
    RECONOCER el final del valor ("+00:00", "Z", "-05", " UTC", "GMT-5",
    "+00:00:00", "America/Bogota"…). La solución que sí cierra el caso hace
    lo contrario: se queda con la FECHA (`solo_fecha`) y descarta todo lo
    que venga detrás sin mirarlo, y además interpreta siempre con
    `utc=True`, que es lo único que pandas garantiza que no lanza.

    Por eso aquí se prueban formatos deliberadamente absurdos: lo que se
    está verificando es que da igual cuál llegue.
    """
    with _pandas_estricto():
        for etiqueta, valores in FORMATOS_DE_ZONA.items():
            filas = [["Fecha", "Ciudad", "V"]]
            filas += [[v, c, i] for i, (v, c) in enumerate(zip(valores, ["B", "C", "M"]))]
            item = load_workbook(_upload_xlsx(f"tz.xlsx", filas))["sheets"]["Hoja1"]
            fechas = item["profile"]["schema"].get("dates")
            check(f"«{etiqueta}» abre y se reconoce como fecha", fechas == ["Fecha"])
            check(f"«{etiqueta}» sin zona y sin hora",
                  str(item["processed"]["Fecha"].dtype) == "datetime64[ns]")


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
    todo_queda_en_el_dia_colombiano_y_sin_hora()
    las_fechas_sin_zona_no_se_mueven()
    columnas_con_nombre_duplicado_tambien_se_normalizan()
    la_clasificacion_semantica_aguanta_los_formatos_raros()
    una_columna_con_formatos_distintos_no_pierde_filas()
    el_resultado_es_siempre_una_columna_de_fechas()
    cualquier_forma_de_escribir_la_zona_abre_el_archivo()
    columnas_ya_fechadas_y_casos_raros()
    el_archivo_completo_carga_y_se_puede_filtrar()
    print("\nFechas test completado sin errores.")
