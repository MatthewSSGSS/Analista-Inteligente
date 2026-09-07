"""Pronóstico de una métrica a futuro, a partir del histórico del propio
archivo.

Principio de diseño, y es el que manda sobre todo lo demás: **una predicción
con pocos datos es un número inventado con cara de certeza**. Un panel que
dice "el próximo mes venderás 412.350" cuando solo tiene tres meses de
historia no está ayudando, está mintiendo con precisión decimal. Así que
este módulo:

1. Se niega a predecir cuando el histórico no da (y explica por qué).
2. Elige el método según cuántos datos hay, no al revés.
3. Se AUTOEVALÚA: reserva los últimos periodos, los predice como si no los
   conociera y mide cuánto se equivocó. Ese error medido —no una fórmula
   teórica— es el que define el rango que se muestra.
4. Entrega siempre un rango, nunca un número solo.

El resultado incluye el texto en español que explica el método y la
confianza, para que quien lo lee sepa cuánto puede apoyarse en él.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

# Mínimo de periodos para intentar cualquier pronóstico. Con menos que esto
# no hay forma de distinguir una tendencia de una casualidad.
MINIMO_PERIODOS = 4

# A partir de aquí se puede usar suavizado exponencial (nivel + tendencia);
# por debajo, solo una recta.
MINIMO_SUAVIZADO = 8

# Estacionalidad anual: hacen falta dos ciclos completos para estimarla.
MINIMO_ESTACIONAL = 24

# Por encima de este error medio en la autoevaluación, los datos son
# demasiado volátiles: se sigue mostrando el rango, pero avisando de que el
# valor central no es fiable.
ERROR_ALTO = 0.30


def serie_periodica(df: pd.DataFrame, schema: dict, metric: str, grain: str = "Mes") -> pd.Series:
    """Histórico agregado por periodo, listo para pronosticar."""
    from .universal_analysis import period_series

    tabla = period_series(df, schema, metric, grain=grain, agg="Suma")
    if tabla is None or tabla.empty or metric not in tabla.columns:
        return pd.Series(dtype="float64")
    serie = (tabla.set_index("period")[metric]
             .astype("float64").sort_index().dropna())
    return serie[~serie.index.duplicated(keep="last")]


def diagnosticar(serie: pd.Series) -> dict:
    """¿Se puede pronosticar esta serie? Y si no, por qué no.

    Se responde ANTES de calcular nada: es preferible decir "tu archivo no
    alcanza para esto" que producir un número que nadie puede cuestionar
    porque viene con dos decimales.
    """
    n = int(len(serie))
    if n == 0:
        return {"viable": False, "periodos": 0,
                "motivo": "No se encontró una columna de fecha con datos suficientes para construir un histórico."}
    if n < MINIMO_PERIODOS:
        return {"viable": False, "periodos": n,
                "motivo": (f"Solo hay {n} periodo(s) de historia. Hacen falta al menos {MINIMO_PERIODOS} "
                           "para distinguir una tendencia real de una casualidad.")}
    if float(serie.std()) == 0:
        return {"viable": False, "periodos": n,
                "motivo": "El indicador no varía entre periodos: no hay una tendencia que proyectar."}
    return {"viable": True, "periodos": n, "motivo": ""}


def _ajustar_lineal(valores: np.ndarray, pasos: int) -> np.ndarray:
    """Recta de tendencia. Es el método más simple y el más difícil de
    hacer decir tonterías, así que es el que se usa con poca historia y el
    respaldo cuando cualquier otro falla."""
    x = np.arange(len(valores), dtype="float64")
    pendiente, corte = np.polyfit(x, valores, 1)
    futuro = np.arange(len(valores), len(valores) + pasos, dtype="float64")
    return pendiente * futuro + corte


def _ajustar_suavizado(valores: np.ndarray, pasos: int, estacional: bool) -> np.ndarray:
    """Suavizado exponencial: da más peso a lo reciente, que es lo que
    normalmente importa en un negocio. Con dos años de historia además
    estima el patrón estacional (diciembre no se parece a febrero)."""
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        modelo = ExponentialSmoothing(
            valores,
            trend="add",
            seasonal="add" if estacional else None,
            seasonal_periods=12 if estacional else None,
            initialization_method="estimated",
        ).fit()
        return np.asarray(modelo.forecast(pasos), dtype="float64")


def _metodos_disponibles(n: int) -> list[tuple[str, object]]:
    """Métodos que la cantidad de datos permite intentar. La recta siempre
    entra: es el respaldo cuando ninguna otra converge."""
    metodos = [("tendencia", lambda v, h: _ajustar_lineal(v, h))]
    if n >= MINIMO_SUAVIZADO:
        metodos.append(("suavizado", lambda v, h: _ajustar_suavizado(v, h, estacional=False)))
    if n >= MINIMO_ESTACIONAL:
        metodos.append(("estacional", lambda v, h: _ajustar_suavizado(v, h, estacional=True)))
    return metodos


def _error_al_plazo(valores: np.ndarray, horizonte: int, ajustar) -> float | None:
    """Cuánto se equivoca este método al predecir `horizonte` periodos.

    Dos cosas que la versión anterior hacía mal y aquí se corrigen:

    1. Medía siempre a UN periodo, aunque el pronóstico mostrado fuera a
       tres. Predecir el mes que viene es mucho más fácil que predecir el
       trimestre: el error reportado salía optimista y la confianza mentía.
       Ahora se mide exactamente al plazo que se va a mostrar.

    2. Probaba en un solo punto de corte. Ahora prueba en varios (origen
       móvil), para que un acierto de casualidad no se confunda con un
       método que de verdad funciona.
    """
    n = len(valores)
    errores = []
    # Se prueba en tantos puntos de corte como la serie permita (hasta 6, no
    # 3): con pocos cortes es fácil que todos caigan en un tramo tranquilo y
    # el método nunca se enfrente a la parte difícil. Fue justo lo que pasó
    # con una serie de fuerte estacionalidad: declaró 6% de error porque los
    # cortes evitaron el pico de fin de año, y luego falló un 42%.
    for atras in range(6):
        fin = n - horizonte - atras
        if fin < MINIMO_PERIODOS:
            break
        entrenamiento, reales = valores[:fin], valores[fin:fin + horizonte]
        try:
            estimados = ajustar(entrenamiento, horizonte)
        except Exception:
            continue
        for est, real in zip(estimados, reales):
            if real != 0:
                errores.append(abs(float(est) - float(real)) / abs(float(real)))
    return float(np.mean(errores)) if errores else None


def _error_peor_caso(valores: np.ndarray, horizonte: int, ajustar) -> float | None:
    """El PEOR error observado en las pruebas, no el promedio.

    El rango se dimensiona con esto y no con la media: la función del rango
    es contener lo que pueda pasar, y un promedio lo deja corto justo en los
    casos que importan. El promedio se sigue reportando como "error típico",
    porque es lo que responde "¿cuánto suele fallar?".
    """
    n = len(valores)
    peores = []
    for atras in range(6):
        fin = n - horizonte - atras
        if fin < MINIMO_PERIODOS:
            break
        entrenamiento, reales = valores[:fin], valores[fin:fin + horizonte]
        try:
            estimados = ajustar(entrenamiento, horizonte)
        except Exception:
            continue
        for est, real in zip(estimados, reales):
            if real != 0:
                peores.append(abs(float(est) - float(real)) / abs(float(real)))
    return float(np.max(peores)) if peores else None


def _elegir_metodo(valores: np.ndarray, horizonte: int) -> tuple[str, object, float | None]:
    """Elige el método PROBÁNDOLOS, no por cuántos datos hay.

    Antes se asumía que más historia = mejor método, y con 24 periodos se
    usaba el modelo estacional aunque en esa serie concreta fallara. Se
    detectó comparando contra meses reales ocultos: declaraba 6% de error y
    se equivocaba 42%. Ahora cada método se mide sobre la propia serie y
    gana el que menos se equivoca — si el estacional no aporta, no se usa.
    """
    mejor = (None, None, None)
    for nombre, ajustar in _metodos_disponibles(len(valores)):
        error = _error_al_plazo(valores, horizonte, ajustar)
        if error is None:
            continue
        if mejor[2] is None or error < mejor[2]:
            mejor = (nombre, ajustar, error)
    if mejor[0] is not None:
        return mejor
    # Sin historia suficiente para medir: se usa el método más simple y se
    # devuelve None como error, que la interfaz traduce en "no se pudo
    # comprobar qué tan acertado es".
    return "tendencia", (lambda v, h: _ajustar_lineal(v, h)), None


def pronosticar(df: pd.DataFrame, schema: dict, metric: str, horizonte: int = 3,
                grain: str = "Mes") -> dict:
    """Pronóstico completo: valores, rango, método y qué tan fiable es.

    Devuelve siempre un diccionario con `viable`; si es False, `motivo`
    explica en español por qué no se puede pronosticar con este archivo.
    """
    serie = serie_periodica(df, schema, metric, grain=grain)
    diag = diagnosticar(serie)
    if not diag["viable"]:
        return {**diag, "metric": metric, "historico": serie}

    valores = serie.to_numpy(dtype="float64")
    metodo, ajustar, error = _elegir_metodo(valores, horizonte)
    peor = _error_peor_caso(valores, horizonte, ajustar)
    try:
        estimados = np.asarray(ajustar(valores, horizonte), dtype="float64")
    except Exception:
        estimados, metodo = _ajustar_lineal(valores, horizonte), "tendencia"

    # ¿Puede haber estacionalidad que no se alcanza a ver? Con menos de dos
    # años no hay forma de saberlo: un pico de diciembre no se puede
    # aprender si solo se ha visto una vez, o ninguna. Se detecta si la
    # serie ya viene dando saltos grandes y, en ese caso, ni se declara
    # confianza alta ni se muestra un rango estrecho — porque el modelo
    # está proyectando una curva suave sobre un negocio que no lo es.
    variacion = float(np.std(np.diff(valores)) / abs(np.mean(valores))) if len(valores) > 1 and np.mean(valores) else 0.0
    estacionalidad_no_verificable = bool(len(valores) < MINIMO_ESTACIONAL and variacion > 0.10)

    # El rango se dimensiona con el PEOR error observado, no con el
    # promedio: su trabajo es contener lo que pueda pasar. Si no se pudo
    # medir (serie muy corta), se usa la dispersión del propio histórico.
    error_medido = error
    if error is None:
        margen_rel = float(np.std(valores) / abs(np.mean(valores))) if np.mean(valores) else 0.25
    else:
        margen_rel = max(peor if peor is not None else error, 0.05)
    # Si la serie da saltos y no hay dos años para descartar estacionalidad,
    # el rango se ensancha: el modelo está dibujando una curva suave sobre
    # algo que no lo es, y estrecharlo sería fingir una precisión que no hay.
    if estacionalidad_no_verificable:
        margen_rel = max(margen_rel, variacion * 2.0)

    # El margen se abre a futuro: predecir el mes que viene es más seguro
    # que predecir dentro de tres.
    margenes = np.array([margen_rel * (1 + 0.35 * i) for i in range(horizonte)])

    # El rango se calcula como "estimado ± amplitud", NO multiplicando por
    # (1±margen). Con una serie en caída el estimado puede ser negativo, y
    # multiplicar invierte los extremos: salía mínimo 86 y máximo -116, un
    # rango imposible. Restar y sumar una amplitud siempre da un intervalo
    # coherente, suba o baje la serie.
    #
    # La amplitud no puede depender solo del estimado: si el pronóstico cae
    # cerca de cero, el rango se cerraría a un punto y aparentaría una
    # certeza total justo donde menos la hay. Por eso se toma también el
    # nivel típico del histórico como piso.
    nivel = float(np.abs(valores).mean())
    amplitud = np.maximum(np.abs(estimados), nivel * 0.10) * margenes
    minimos = estimados - amplitud
    maximos = estimados + amplitud

    # Un indicador que nunca fue negativo en el histórico no debería
    # proyectarse en negativo por el ancho del rango.
    if float(valores.min()) >= 0:
        estimados = np.maximum(estimados, 0.0)
        minimos = np.maximum(minimos, 0.0)
        maximos = np.maximum(maximos, 0.0)
    # Último cierre de coherencia, pase lo que pase con los recortes:
    # mínimo <= estimado <= máximo, siempre.
    minimos = np.minimum(minimos, estimados)
    maximos = np.maximum(maximos, estimados)

    paso = pd.tseries.frequencies.to_offset("MS") if grain == "Mes" else None
    ultima = serie.index[-1]
    if grain == "Mes":
        fechas = pd.date_range(ultima, periods=horizonte + 1, freq="MS")[1:]
    else:
        delta = serie.index[-1] - serie.index[-2] if len(serie) > 1 else pd.Timedelta(days=30)
        fechas = pd.DatetimeIndex([ultima + delta * (i + 1) for i in range(horizonte)])

    prediccion = pd.DataFrame({
        "periodo": fechas,
        "estimado": estimados,
        "minimo": minimos,
        "maximo": maximos,
    })

    # La confianza se juzga por el PEOR error observado, no por el promedio:
    # un método que suele acertar pero falla feo cuando importa no merece
    # llamarse "confianza alta".
    referencia = peor if peor is not None else error_medido
    confianza = "baja"
    if referencia is not None:
        confianza = "alta" if referencia <= 0.10 else "media" if referencia <= ERROR_ALTO else "baja"
    # Y nunca se declara confianza alta si no se pudo descartar que el
    # negocio tenga estacionalidad: sin dos años de historia, el modelo no
    # ha visto siquiera un diciembre repetido.
    if estacionalidad_no_verificable and confianza == "alta":
        confianza = "media"

    # De dónde salió el número: qué columna de fecha se usó, qué se sumó y
    # entre qué periodos. Sin esto, quien presenta el pronóstico no puede
    # responder "¿y esto de dónde sale?" — que es la primera pregunta que
    # le van a hacer.
    columnas_fecha = [d for d in schema.get("dates", []) if d in df.columns]
    return {
        "viable": True,
        "motivo": "",
        "metric": metric,
        "periodos": diag["periodos"],
        "historico": serie,
        "prediccion": prediccion,
        "metodo": metodo,
        "error_tipico": error_medido,
        "error_peor_caso": peor,
        "estacionalidad_no_verificable": estacionalidad_no_verificable,
        "confianza": confianza,
        "grain": grain,
        "columna_fecha": columnas_fecha[0] if columnas_fecha else None,
        "desde": serie.index[0],
        "hasta": serie.index[-1],
        "filas_usadas": int(len(df)),
    }


NOMBRES_METODO = {
    "tendencia": "recta de tendencia",
    "suavizado": "suavizado exponencial (da más peso a lo reciente)",
    "estacional": "suavizado exponencial con estacionalidad anual",
}


def explicar(resultado: dict) -> str:
    """Una frase honesta sobre cuánto vale este pronóstico."""
    if not resultado.get("viable"):
        return resultado.get("motivo", "No hay datos suficientes para pronosticar.")
    metodo = NOMBRES_METODO.get(resultado["metodo"], resultado["metodo"])
    partes = [f"Calculado con {metodo}, sobre {resultado['periodos']} periodos de historia."]
    error = resultado.get("error_tipico")
    if error is None:
        partes.append("No hubo historia suficiente para medir qué tan acertado es: "
                      "el rango se basa en la variación del propio indicador, tómalo como una referencia amplia.")
    else:
        partes.append(f"Puesto a prueba sobre tus propios datos, se equivocó en promedio un {error * 100:.0f}%.")
        peor = resultado.get("error_peor_caso")
        if peor is not None and peor > error * 1.5:
            partes.append(f"En su peor prueba se desvió un {peor * 100:.0f}%, y el rango se dimensionó con ese peor caso.")
        if error > ERROR_ALTO:
            partes.append("Es un margen alto: el indicador varía demasiado entre periodos, "
                          "así que conviene leer el rango y no el valor central.")
    if resultado.get("estacionalidad_no_verificable"):
        partes.append("Ojo: hay menos de dos años de historia y el indicador da saltos entre periodos, "
                      "así que no se puede descartar un efecto de temporada (un diciembre fuerte, "
                      "una temporada baja). El rango se amplió por eso.")
    return " ".join(partes)
