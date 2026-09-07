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


def _predecir(valores: np.ndarray, pasos: int) -> tuple[np.ndarray, str]:
    """Aplica el mejor método que la cantidad de datos permita, con
    respaldo a la recta si el modelo no converge."""
    n = len(valores)
    if n >= MINIMO_ESTACIONAL:
        try:
            return _ajustar_suavizado(valores, pasos, estacional=True), "estacional"
        except Exception:
            pass
    if n >= MINIMO_SUAVIZADO:
        try:
            return _ajustar_suavizado(valores, pasos, estacional=False), "suavizado"
        except Exception:
            pass
    return _ajustar_lineal(valores, pasos), "tendencia"


def _autoevaluar(valores: np.ndarray) -> float | None:
    """Error típico del método sobre ESTA serie, medido de verdad.

    Se ocultan los últimos periodos, se predicen como si no se conocieran y
    se compara con lo que realmente pasó. Es la única forma honesta de
    decirle a alguien cuánto puede confiar: no "el modelo asume errores
    normales", sino "con tus datos, se equivocó un 12% en promedio".
    """
    n = len(valores)
    reservados = min(3, max(1, n // 4))
    if n - reservados < MINIMO_PERIODOS - 1:
        return None
    errores = []
    for i in range(reservados, 0, -1):
        entrenamiento = valores[: n - i]
        real = valores[n - i]
        try:
            estimado = float(_predecir(entrenamiento, 1)[0][0])
        except Exception:
            continue
        if real != 0:
            errores.append(abs(estimado - real) / abs(real))
    return float(np.mean(errores)) if errores else None


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
    estimados, metodo = _predecir(valores, horizonte)
    error = _autoevaluar(valores)

    # El rango sale del error medido en la autoevaluación. Si no se pudo
    # medir (serie muy corta), se usa la dispersión del propio histórico,
    # que es una cota prudente.
    if error is None:
        margen_rel = float(np.std(valores) / abs(np.mean(valores))) if np.mean(valores) else 0.25
        error_medido = None
    else:
        margen_rel = max(error, 0.05)
        error_medido = error

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

    confianza = "baja"
    if error_medido is not None:
        confianza = "alta" if error_medido <= 0.10 else "media" if error_medido <= ERROR_ALTO else "baja"

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
        if error > ERROR_ALTO:
            partes.append("Es un margen alto: el indicador varía demasiado entre periodos, "
                          "así que conviene leer el rango y no el valor central.")
    return " ".join(partes)
