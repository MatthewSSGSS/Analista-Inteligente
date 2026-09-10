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


def _tablas_por_segmento(df: pd.DataFrame, schema: dict, metric: str, dim: str,
                         grain: str, periodos) -> tuple:
    """Dos matrices periodo × segmento: cuánto sumó y cuántos registros hubo.

    La segunda es la que permite responder POR QUÉ cae un punto: no es lo
    mismo que atienda menos operaciones a que cada operación valga menos. Sin
    separarlas, la única respuesta posible es "cae", que es la pregunta.
    """
    fechas = [d for d in schema.get("dates", []) if d in df.columns]
    if not fechas or metric not in df.columns or dim not in df.columns:
        return None, None
    columna = fechas[0]
    x = pd.DataFrame({
        "_fecha": pd.to_datetime(df[columna], errors="coerce"),
        "_segmento": df[dim].astype(str).str.strip(),
        "_valor": pd.to_numeric(df[metric], errors="coerce"),
    }).dropna(subset=["_fecha", "_valor"])
    x = x[x["_segmento"].ne("") & x["_segmento"].str.lower().ne("nan")]
    if x.empty:
        return None, None
    if grain == "Día":
        x["_periodo"] = x["_fecha"].dt.floor("D")
    elif grain == "Semana":
        x["_periodo"] = x["_fecha"].dt.to_period("W").dt.start_time
    elif grain == "Trimestre":
        x["_periodo"] = x["_fecha"].dt.to_period("Q").dt.start_time
    elif grain == "Año":
        x["_periodo"] = x["_fecha"].dt.to_period("Y").dt.start_time
    else:
        x["_periodo"] = x["_fecha"].dt.to_period("M").dt.start_time

    valores = x.pivot_table(index="_periodo", columns="_segmento", values="_valor", aggfunc="sum")
    conteos = x.pivot_table(index="_periodo", columns="_segmento", values="_valor", aggfunc="count")
    # Se alinean con los mismos periodos del pronóstico: un segmento que no
    # aparece en un periodo aportó cero, y ese cero es información.
    valores = valores.reindex(periodos).fillna(0.0)
    conteos = conteos.reindex(periodos).fillna(0)
    return valores, conteos


def _pendiente(valores: np.ndarray) -> float:
    if len(valores) < 2:
        return 0.0
    x = np.arange(len(valores), dtype="float64")
    return float(np.polyfit(x, valores, 1)[0])


def _por_que_cae(serie_valor: np.ndarray, serie_conteo: np.ndarray) -> dict:
    """Separa el cambio en dos causas: menos operaciones, o de menor valor.

    Se comparan las dos mitades del histórico en vez de dos periodos
    sueltos: un mes flojo no es una causa, y con dos puntos cualquier ruido
    parece un motivo.
    """
    mitad = max(len(serie_valor) // 2, 1)
    antes_valor, despues_valor = serie_valor[:mitad], serie_valor[mitad:]
    antes_conteo, despues_conteo = serie_conteo[:mitad], serie_conteo[mitad:]
    n_antes, n_despues = float(antes_conteo.sum()), float(despues_conteo.sum())
    v_antes, v_despues = float(antes_valor.sum()), float(despues_valor.sum())
    ticket_antes = v_antes / n_antes if n_antes else 0.0
    ticket_despues = v_despues / n_despues if n_despues else 0.0

    volumen_pct = ((n_despues - n_antes) / n_antes * 100) if n_antes else None
    ticket_pct = ((ticket_despues - ticket_antes) / ticket_antes * 100) if ticket_antes else None

    motivo = None
    if volumen_pct is not None and ticket_pct is not None:
        cae_volumen, cae_ticket = volumen_pct <= -8, ticket_pct <= -8
        if cae_volumen and cae_ticket:
            motivo = (f"hace {abs(volumen_pct):.0f}% menos operaciones y cada una vale "
                      f"{abs(ticket_pct):.0f}% menos")
        elif cae_volumen:
            motivo = (f"hace {abs(volumen_pct):.0f}% menos operaciones; el valor por operación "
                      f"se mantiene ({ticket_pct:+.0f}%)")
        elif cae_ticket:
            motivo = (f"cada operación vale {abs(ticket_pct):.0f}% menos; el número de operaciones "
                      f"se mantiene ({volumen_pct:+.0f}%)")
    return {"volumen_pct": volumen_pct, "ticket_pct": ticket_pct, "motivo": motivo,
            "operaciones": int(serie_conteo.sum())}


def _conc_periodos(n: int) -> str:
    return "periodo" if n == 1 else "periodos"


def _periodos_bajando(valores: np.ndarray) -> int:
    """Cuántos periodos seguidos lleva cayendo, contando desde el final."""
    seguidos = 0
    for i in range(len(valores) - 1, 0, -1):
        if valores[i] < valores[i - 1]:
            seguidos += 1
        else:
            break
    return seguidos


def atribuir(df: pd.DataFrame, schema: dict, resultado: dict, dim: str | None = None,
             top: int = 3) -> dict | None:
    """De dónde sale la tendencia que se está proyectando, con nombre propio.

    Un pronóstico que solo dice "va a bajar" deja al que lo lee sin nada que
    hacer. Este desglose responde la pregunta siguiente —¿bajar por culpa de
    quién, y por qué?— abriendo la misma tendencia por punto de venta, agente
    o producto, según lo que tenga el archivo.

    Se apoya en una propiedad que hace el reparto exacto y no una estimación:
    la recta de mínimos cuadrados de una suma es la suma de las rectas de sus
    partes. Como el histórico del pronóstico es una SUMA por periodo, la
    tendencia del total es exactamente la suma de las tendencias de cada
    segmento, y repartir el descenso entre ellos no aproxima nada.
    """
    from .diagnostics import dimensiones_candidatas

    if not resultado.get("viable"):
        return None
    historico = resultado.get("historico")
    prediccion = resultado.get("prediccion")
    if historico is None or prediccion is None or len(historico) < MINIMO_PERIODOS:
        return None
    metric = resultado["metric"]
    if dim:
        candidatas = [dim]
    else:
        # Se prueban varias agrupaciones y gana la que de verdad explica la
        # tendencia. La más detallada no siempre es la más útil: si el
        # descenso está repartido entre 400 puntos, señalar a tres que
        # aportan el 1% cada uno no dice nada, mientras que abrirlo por
        # ciudad o por zona puede señalar una causa común.
        candidatas = dimensiones_candidatas(df, schema, metric)[:4]
    mejor = None
    for candidata in candidatas:
        intento = _atribuir_por(df, schema, resultado, candidata, top)
        if intento is None:
            continue
        if mejor is None or intento["concentracion"] > mejor["concentracion"] + 10:
            mejor = intento
    return mejor


def _atribuir_por(df: pd.DataFrame, schema: dict, resultado: dict, dim: str, top: int) -> dict | None:
    """El reparto de la tendencia usando una agrupación concreta."""
    historico = resultado["historico"]
    prediccion = resultado["prediccion"]
    metric = resultado["metric"]
    horizonte = int(len(prediccion))
    valores, conteos = _tablas_por_segmento(df, schema, metric, dim,
                                            resultado.get("grain", "Mes"), historico.index)
    if valores is None or valores.shape[1] < 2:
        return None

    segmentos = []
    for nombre in valores.columns:
        serie = valores[nombre].to_numpy(dtype="float64")
        if not np.any(serie):
            continue
        pendiente = _pendiente(serie)
        # Adónde llega este segmento al final del horizonte si sigue igual.
        delta = float(pendiente * horizonte)
        segmentos.append({
            "nombre": str(nombre), "delta": delta, "pendiente": pendiente,
            "ultimo": float(serie[-1]), "serie": serie,
            "conteo": conteos[nombre].to_numpy(dtype="float64"),
        })
    if len(segmentos) < 2:
        return None

    delta_total = float(sum(s["delta"] for s in segmentos))
    nivel = float(np.abs(historico.to_numpy()).mean())
    if nivel <= 0 or abs(delta_total) < nivel * 0.01:
        return None  # la tendencia es plana: no hay nada que atribuir

    direccion = "baja" if delta_total < 0 else "sube"
    signo = -1 if delta_total < 0 else 1
    mismos = sorted([s for s in segmentos if s["delta"] * signo > 0],
                    key=lambda s: abs(s["delta"]), reverse=True)
    contrarios = sorted([s for s in segmentos if s["delta"] * signo < 0],
                        key=lambda s: abs(s["delta"]), reverse=True)
    if not mismos:
        return None
    empuje_total = float(sum(abs(s["delta"]) for s in mismos))

    # Solo se muestran los que aportan algo. Con un responsable claro al 86%,
    # acompañarlo de dos que aportan 11% y 3% diluye el mensaje y manda a
    # revisar casos que no mueven la aguja.
    relevantes = [s for s in mismos[:top] if empuje_total and abs(s["delta"]) / empuje_total >= 0.10]
    impulsores = []
    for s in (relevantes or mismos[:1]):
        causa = _por_que_cae(s["serie"], s["conteo"])
        base = float(s["serie"].sum())
        # El nivel proyectado dice más que un porcentaje. Cuando un segmento
        # ya casi no registra, "cae 104%" es matemáticamente correcto y no
        # significa nada; "de 1.2K a 0.4K" se entiende de una.
        proyectado = float(s["ultimo"] + s["delta"])
        if float(s["serie"].min()) >= 0:
            proyectado = max(proyectado, 0.0)
        sin_actividad = 0
        for valor in s["serie"][::-1]:
            if valor == 0:
                sin_actividad += 1
            else:
                break
        if sin_actividad:
            # Quien ya no registra no "hace menos operaciones": no hace
            # ninguna. Descomponer volumen y ticket ahí describe el pasado, no
            # la causa, y la causa es que dejó de aparecer.
            causa["motivo"] = (f"no registra nada desde hace {sin_actividad} "
                               f"{_conc_periodos(sin_actividad)}")
        impulsores.append({
            "nombre": s["nombre"],
            "delta": s["delta"],
            "peso": abs(s["delta"]) / empuje_total * 100 if empuje_total else 0.0,
            "ultimo": float(s["ultimo"]),
            "proyectado": proyectado,
            "caida_pct": ((proyectado - s["ultimo"]) / abs(s["ultimo"]) * 100) if s["ultimo"] else None,
            "periodos_bajando": _periodos_bajando(s["serie"]),
            "periodos_sin_actividad": sin_actividad,
            "inactivo": bool(sin_actividad > 0 and base > 0),
            "aporte_historico": base,
            **causa,
        })

    compensan = [{"nombre": s["nombre"], "delta": s["delta"]} for s in contrarios[:2]]
    concentracion = float(sum(abs(s["delta"]) for s in mismos[:top]) / empuje_total * 100) if empuje_total else 0.0
    return {
        "dimension": dim,
        "direccion": direccion,
        "delta_total": delta_total,
        "horizonte": horizonte,
        "segmentos": len(segmentos),
        "impulsores": impulsores,
        "concentracion": concentracion,
        # Cuántos segmentos cubre esa concentración. No es len(impulsores):
        # arriba se filtran los que aportan menos del 10%, y la frase debe
        # decir sobre cuántos se calculó el porcentaje, no cuántos se pintan.
        "explicados": len(mismos[:top]),
        # Por debajo de este umbral, los nombres de arriba son los mayores de
        # un montón, no los responsables. La interfaz tiene que decirlo así:
        # presentarlos como culpables mandaría a revisar tres casos cuando el
        # problema es de todos.
        "disperso": bool(concentracion < 25),
        "cuantos_empujan": len(mismos),
        "compensan": compensan,
        # El reparto es exacto sobre la RECTA de tendencia. Si el pronóstico
        # se calculó con otro método, el total proyectado no tiene por qué
        # coincidir al peso, y la interfaz debe decirlo en vez de dar a
        # entender que estos números suman exactamente la línea del gráfico.
        "metodo_lineal": resultado.get("metodo") == "tendencia",
    }


def explicar_atribucion(atribucion: dict | None) -> str:
    """Una frase que responde "¿por qué va a bajar?" antes del detalle.

    No nombra la dimensión: la sección que la muestra ya dice sobre qué
    columna se abrió, y repetirlo dentro de la frase producía cosas como
    "3 de 5 de PUNTO aportan", que no se lee.
    """
    if not atribucion or not atribucion.get("impulsores"):
        return ""
    nombres = [i["nombre"] for i in atribucion["impulsores"]]
    verbo = "El descenso" if atribucion["direccion"] == "baja" else "El crecimiento"
    if atribucion.get("disperso"):
        return (f"{verbo} proyectado está repartido entre {atribucion['cuantos_empujan']}, "
                f"y los {atribucion.get('explicados', len(nombres))} mayores apenas aportan el "
                f"{atribucion['concentracion']:.0f}%. No hay unos pocos responsables: "
                f"la causa es común y hay que buscarla en el proceso, no en los nombres.")
    if atribucion["concentracion"] >= 50:
        return (f"{verbo} proyectado no es general: {atribucion.get('explicados', len(nombres))} de "
                f"{atribucion['cuantos_empujan']} aportan el "
                f"{atribucion['concentracion']:.0f}% de la tendencia.")
    return (f"{verbo} proyectado está repartido entre {atribucion['cuantos_empujan']}; "
            f"los {atribucion.get('explicados', len(nombres))} primeros aportan el "
            f"{atribucion['concentracion']:.0f}%.")


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
