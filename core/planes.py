"""De los hallazgos a un plan que alguien pueda ejecutar el lunes.

La pestaña de trabajo listaba los hallazgos y su línea de "qué hacer". Está
bien, pero un hallazgo no es un plan: dice qué pasa y a lo sumo por dónde
empezar, no quién, en qué orden, ni cómo se va a saber si funcionó. Quien
tiene que actuar todavía tenía que traducirlo.

Aquí cada hallazgo se convierte en un plan con cuatro partes:

- **Situación**: qué está pasando, con los nombres y las cifras del hallazgo.
- **Por qué importa**: qué se pierde si no se hace nada.
- **Pasos**: acciones concretas, en orden, sobre los casos que el análisis ya
  identificó por nombre.
- **Cómo se mide**: el indicador y el plazo, para que el plan se pueda cerrar
  o revisar en vez de quedar abierto para siempre.

Y cuando no hay nada roto no se calla ni se inventa un problema: propone
mejoras sobre lo que el archivo sí muestra —cerrar la brecha con el líder,
subir a los rezagados a la mediana, sostener lo que está creciendo—.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .diagnostics import _fmt, _lista

# Cada hallazgo tiene su plan. La clave es el título que produce
# `core/diagnostics.py`; el valor dice por qué importa y qué pasos dar.
# Los pasos se completan con los nombres reales de la evidencia, para que el
# plan hable de "RIOHACHA" y no de "los segmentos afectados".
PLANTILLAS = {
    "Dónde se concentra la caída": {
        "estado": "critico",
        "por_que": "El daño está concentrado: si no se atiende a esos pocos, el total no se recupera aunque todo lo demás mejore.",
        "pasos": [
            "Confirmar con {nombres} que la caída es real y no un problema de registro.",
            "Identificar qué cambió en el último periodo para cada uno: operación, precio, inventario o competencia.",
            "Fijar una meta de recuperación por caso y un responsable por nombre.",
            "Revisar el avance en el siguiente corte, sin esperar al cierre del trimestre.",
        ],
        "medir": "Que {primero} recupere al menos la mitad de lo que perdió en el próximo periodo.",
    },
    "Caída generalizada": {
        "estado": "critico",
        "por_que": "La caída está repartida, así que no hay culpables: la causa es del proceso y perseguir casos uno por uno no la corrige.",
        "pasos": [
            "Descartar primero lo transversal: cambio de precio, de disponibilidad, de proceso o del calendario.",
            "Comparar contra el mismo periodo del año anterior antes de concluir que es un problema nuevo.",
            "Si la causa es externa, ajustar las metas en vez de exigir a cada área lo que no depende de ella.",
        ],
        "medir": "Que el total deje de caer en el próximo periodo, medido contra el mismo mes del año pasado.",
    },
    "Deterioro sostenido": {
        "estado": "critico",
        "por_que": "Tres periodos seguidos a la baja ya es una tendencia. Cada periodo que pasa, la recuperación cuesta más.",
        "pasos": [
            "Revisar {nombres} empezando por el primer periodo de la caída, que es donde está la causa.",
            "Decidir explícitamente si se interviene o se acepta la salida: dejarlo correr es la peor de las dos.",
            "Si se interviene, definir qué cambia concretamente y para cuándo.",
        ],
        "medir": "Que {primero} rompa la racha: un solo periodo al alza ya confirma que la intervención sirvió.",
    },
    "Dejaron de registrar": {
        "estado": "critico",
        "por_que": "Una ausencia total no es una caída: o dejó de operar, o dejó de reportar. Las dos cosas se corrigen, pero distinto.",
        "pasos": [
            "Contactar {nombres} y confirmar si es cierre, pausa o falla de captura.",
            "Si es falla de captura, recuperar los datos del periodo antes de que se pierdan.",
            "Si es cierre, sacarlos de la base comparable para que no ensucien las tendencias futuras.",
        ],
        "medir": "Que en el próximo corte no quede ningún caso sin clasificar entre cierre, pausa o error de registro.",
    },
    "Cumplimiento de meta": {
        "estado": "atencion",
        "por_que": "La meta es el compromiso que ya existía. No llegar tiene dos lecturas —meta mal puesta o desempeño corto— y hay que separarlas.",
        "pasos": [
            "Revisar con {nombres} si la meta era alcanzable con los recursos que tenían.",
            "Donde la meta era razonable, acordar un plan de recuperación con cifra y fecha.",
            "Donde la meta no lo era, corregirla ahora: una meta imposible deja de orientar a nadie.",
        ],
        "medir": "Que {primero} suba su cumplimiento en el próximo corte, aunque no llegue al 100%.",
    },
    "Rezago frente a la mediana": {
        "estado": "atencion",
        "por_que": "La brecha contra la mediana es el potencial más barato que hay: no requiere crecer el mercado, solo igualar lo que ya hace la mitad del grupo.",
        "pasos": [
            "Mirar qué tienen en común {nombres}: puede ser tamaño, zona o surtido, y no desempeño.",
            "Si la causa es estructural, ajustar la expectativa; si no, definir un plan de nivelación.",
            "Emparejar cada rezagado con alguien del grupo que sí llega, y copiar la práctica concreta.",
        ],
        "medir": "Que la mitad de los rezagados alcance la mediana del grupo en dos periodos.",
    },
    "Exceso": {
        "estado": "atencion",
        "por_que": "En esta métrica el problema es tener más, no menos, y el exceso está concentrado en pocos casos.",
        "pasos": [
            "Aislar los casos de {nombres} y revisar cuánto lleva cada uno en esa situación.",
            "Definir el límite aceptable y qué pasa cuando se cruza.",
            "Atacar primero el caso más grande: es donde una corrección tiene más recorrido.",
        ],
        "medir": "Que {primero} baje al nivel normal del archivo en el próximo corte.",
    },
    "Estado": {
        "estado": "atencion",
        "por_que": "La tasa dice si el problema es del proceso o de unos pocos. Confundirlos hace que se corrija donde no duele.",
        "pasos": [
            "Revisar los casos de {primero}, que tiene la tasa más alta y no solo más casos.",
            "Comparar su forma de trabajar con la de quien tiene la tasa más baja.",
            "Ajustar el proceso donde se vea la diferencia, y volver a medir la tasa, no el conteo.",
        ],
        "medir": "Que la tasa de {primero} baje hasta el promedio del archivo.",
    },
    "Registros en cero": {
        "estado": "atencion",
        "por_que": "Un cero no es un valor bajo, es una ausencia. Mezclado con el resto, arrastra hacia abajo cualquier promedio y esconde el problema real.",
        "pasos": [
            "Separar los ceros del análisis y confirmar si son reales o falta el dato.",
            "Empezar por {primero}, que es donde más se concentran.",
            "Si son reales, tratarlos como casos sin actividad y no como bajo desempeño.",
        ],
        "medir": "Que la proporción de registros en cero baje, o que quede documentado por qué son legítimos.",
    },
    "Concentración de riesgo": {
        "estado": "atencion",
        "por_que": "Depender de unos pocos es una fortaleza mientras dure. El riesgo no es que vayan mal, es que se caiga uno.",
        "pasos": [
            "Verificar qué tan estable es la relación con {nombres}.",
            "Calcular qué pasaría con el total si el primero se cae, y decidir si ese riesgo es aceptable.",
            "Definir un plan de diversificación con plazo, aunque sea gradual.",
        ],
        "medir": "Que el peso del primero baje, o que exista un plan de contingencia escrito por si se cae.",
    },
    "Valores atípicos": {
        "estado": "atencion",
        "por_que": "Si son errores están inflando promedios y rankings; si son reales son los casos que más enseñan. Lo que no se puede es dejarlos sin clasificar.",
        "pasos": [
            "Revisar los registros de {nombres}, que concentran los atípicos.",
            "Marcar cada uno como error de captura o como caso real.",
            "Corregir los errores y estudiar los casos reales: ahí suele estar la mejor práctica o el peor fallo.",
        ],
        "medir": "Que no quede ningún atípico sin clasificar antes del próximo corte.",
    },
    "Datos que faltan": {
        "estado": "atencion",
        "por_que": "Cada corte que use esa columna deja fuera esas filas sin avisar, así que los totales por segmento no cuadran con el total del archivo.",
        "pasos": [
            "Decidir qué se hace con las filas incompletas: completarlas, excluirlas o reportarlas aparte.",
            "Corregir el punto de captura para que dejen de llegar vacías.",
            "Volver a leer los indicadores afectados una vez completada la información.",
        ],
        "medir": "Que el porcentaje de vacíos baje por debajo del 10% en la columna más afectada.",
    },
    "Errores de captura": {
        "estado": "atencion",
        "por_que": "No son casos límite, son datos que no deberían existir: mientras estén ahí, cualquier total que los incluya está mal.",
        "pasos": [
            "Corregir los registros señalados en el origen, no en la copia.",
            "Revisar por qué el sistema los permitió, para que no vuelvan.",
        ],
        "medir": "Que el próximo archivo llegue sin ninguno de estos errores.",
    },
    "Identificador repetido": {
        "estado": "atencion",
        "por_que": "Un identificador repetido cuenta dos veces lo mismo: infla totales, rankings y participaciones sin que se note en ningún indicador.",
        "pasos": [
            "Confirmar si es un cruce repetido o si el identificador no es único de verdad.",
            "Si es lo primero, rehacer el cruce y volver a leer los totales.",
        ],
        "medir": "Que el identificador no se repita en el próximo archivo.",
    },
}

# Cuando el archivo no tiene nada roto, igual hay margen. Estas son las
# mejoras que se pueden proponer con lo que el propio archivo muestra.
MEJORAS = {
    "brecha": {
        "titulo": "Subir a los rezagados hasta la mediana",
        "por_que": "Es el crecimiento más barato disponible: no exige ganar mercado nuevo, solo igualar lo que ya hace la mitad del grupo.",
        "pasos": [
            "Emparejar a {nombres} con alguien del grupo que sí llega a la mediana.",
            "Copiar una práctica concreta y medible, no un objetivo general.",
            "Revisar la brecha en dos periodos.",
        ],
    },
    "lider": {
        "titulo": "Replicar lo que hace el líder",
        "por_que": "El mejor del grupo ya demostró que el resultado es alcanzable con las mismas condiciones del archivo.",
        "pasos": [
            "Documentar qué hace {primero} distinto del resto.",
            "Probarlo en dos casos del tercio inferior antes de extenderlo.",
            "Medir el efecto antes de convertirlo en norma.",
        ],
    },
    "sostener": {
        "titulo": "Sostener lo que está creciendo",
        "por_que": "Un crecimiento sin explicación se apaga solo. Entender por qué sube es lo que permite repetirlo.",
        "pasos": [
            "Identificar qué explica el avance reciente y si depende de algo puntual.",
            "Asegurar los recursos que lo sostienen antes de que se caiga por falta de apoyo.",
        ],
    },
    "meta": {
        "titulo": "Poner metas al archivo",
        "por_que": "Sin meta, cualquier comparación entre grupos mide tamaño y no desempeño: el grande siempre gana por serlo.",
        "pasos": [
            "Agregar una columna de meta por grupo y periodo al archivo.",
            "Con eso, el panel compara cumplimiento y el ranking pasa a medir mérito.",
        ],
    },
}


def _plantilla_para(titulo: str) -> Optional[dict]:
    """La plantilla del hallazgo. Algunos títulos llevan datos pegados
    ("Exceso en DiasMora", "Estado Vencido: quién concentra"), así que se
    busca también por prefijo en vez de exigir coincidencia exacta."""
    if titulo in PLANTILLAS:
        return PLANTILLAS[titulo]
    for clave, plantilla in PLANTILLAS.items():
        if titulo.startswith(clave):
            return plantilla
    return None


def _nombres_de(hallazgo) -> list[str]:
    """Los nombres concretos que el hallazgo ya identificó."""
    fuera = {"Valor más extremo", "Filas repetidas", "Su resultado", "Mediana del grupo"}
    return [str(e.get("nombre")) for e in (hallazgo.get("evidence") or [])
            if e.get("nombre") and str(e["nombre"]) not in fuera][:3]


def _rellenar(texto: str, nombres: list[str]) -> str:
    if not nombres:
        return texto.replace("{nombres}", "los casos señalados").replace("{primero}", "el primero de la lista")
    return texto.replace("{nombres}", _lista(nombres)).replace("{primero}", nombres[0])


def _plan_desde_hallazgo(hallazgo: dict) -> Optional[dict]:
    plantilla = _plantilla_para(str(hallazgo.get("title", "")))
    if not plantilla:
        return None
    nombres = _nombres_de(hallazgo)
    return {
        "titulo": str(hallazgo.get("title")),
        "estado": plantilla["estado"],
        "situacion": str(hallazgo.get("finding", "")),
        "por_que": plantilla["por_que"],
        "pasos": [_rellenar(p, nombres) for p in plantilla["pasos"]],
        "medir": _rellenar(plantilla["medir"], nombres),
        "evidencia": hallazgo.get("evidence") or [],
        "objetivo": hallazgo.get("target") or {},
    }


def _mejoras_disponibles(df, schema, dashboard) -> list[dict]:
    """Qué se puede mejorar cuando no hay nada roto."""
    from .performance import analyze, columna_meta

    planes = []
    resultado = dashboard.get("performance") or {}
    base = resultado.get("base") if isinstance(resultado, dict) else None
    if not base:
        try:
            resultado = analyze(df, schema) or {}
            base = resultado.get("base")
        except Exception:
            base = None

    if base and len(base.get("ranking", [])) >= 4:
        ranking = base["ranking"]
        mediana = float(pd.Series([f["valor"] for f in ranking]).median())
        rezagados = [f for f in ranking if f["valor"] < mediana]
        if rezagados:
            nombres = [f["nombre"] for f in rezagados[-3:]]
            planes.append({
                "titulo": MEJORAS["brecha"]["titulo"], "estado": "mejora",
                "situacion": (f"{len(rezagados)} de {len(ranking)} están por debajo de la mediana "
                              f"({base['etiqueta'].lower()}). Los más lejanos son {_lista(nombres)}."),
                "por_que": MEJORAS["brecha"]["por_que"],
                "pasos": [_rellenar(p, nombres) for p in MEJORAS["brecha"]["pasos"]],
                "medir": f"Que la mitad de esos {len(rezagados)} alcance la mediana en dos periodos.",
                "evidencia": [{"nombre": f["nombre"], "valor": f["texto"], "detalle": f["detalle"]}
                              for f in rezagados[-3:]],
                "objetivo": {},
            })
        lider = ranking[0]
        planes.append({
            "titulo": MEJORAS["lider"]["titulo"], "estado": "mejora",
            "situacion": f"{lider['nombre']} lidera con {lider['texto']} ({lider['detalle']}).",
            "por_que": MEJORAS["lider"]["por_que"],
            "pasos": [_rellenar(p, [lider["nombre"]]) for p in MEJORAS["lider"]["pasos"]],
            "medir": f"Que al menos dos casos del tercio inferior se acerquen a {lider['texto']}.",
            "evidencia": [{"nombre": lider["nombre"], "valor": lider["texto"], "detalle": lider["detalle"]}],
            "objetivo": {},
        })

    ejecutivo = dashboard.get("executive") or {}
    if ejecutivo.get("status") == "positive":
        planes.append({
            "titulo": MEJORAS["sostener"]["titulo"], "estado": "mejora",
            "situacion": str(ejecutivo.get("headline", "")),
            "por_que": MEJORAS["sostener"]["por_que"],
            "pasos": MEJORAS["sostener"]["pasos"],
            "medir": "Que el próximo periodo confirme la mejora en vez de devolverla.",
            "evidencia": [], "objetivo": {},
        })

    try:
        sin_meta = columna_meta(df, schema) is None
    except Exception:
        sin_meta = False
    if sin_meta:
        planes.append({
            "titulo": MEJORAS["meta"]["titulo"], "estado": "mejora",
            "situacion": "El archivo no trae una columna de meta, así que las comparaciones entre grupos se apoyan en lo que haya.",
            "por_que": MEJORAS["meta"]["por_que"],
            "pasos": MEJORAS["meta"]["pasos"],
            "medir": "Que el próximo archivo incluya la meta de cada grupo.",
            "evidencia": [], "objetivo": {},
        })
    return planes


def generar(df: pd.DataFrame, schema: dict, dashboard: dict) -> dict:
    """Los planes que salen del análisis, y el estado general del archivo.

    Devuelve `{"planes": [...], "criticos": n, "atencion": n, "resumen": str}`.
    Siempre trae algo: si no hay nada roto, propone mejoras en vez de dejar
    la pestaña vacía, que es la forma más rápida de que nadie la vuelva a
    abrir.
    """
    hallazgos = (dashboard or {}).get("insights") or []
    planes = []
    for hallazgo in hallazgos:
        plan = _plan_desde_hallazgo(hallazgo)
        if plan:
            planes.append(plan)

    orden = {"critico": 0, "atencion": 1, "mejora": 2}
    planes.sort(key=lambda p: orden.get(p["estado"], 3))
    criticos = sum(1 for p in planes if p["estado"] == "critico")
    atencion = sum(1 for p in planes if p["estado"] == "atencion")

    # Las mejoras se agregan siempre, no solo cuando no hay problemas: aun
    # con incendios encendidos, saber dónde está el margen barato ayuda a
    # decidir. Van al final porque no compiten con lo urgente.
    try:
        planes += _mejoras_disponibles(df, schema, dashboard or {})
    except Exception:
        pass

    if criticos:
        resumen = (f"{criticos} frente(s) crítico(s) y {atencion} en observación. "
                   f"El orden de abajo es el orden de atención: lo primero es lo que más pesa.")
    elif atencion:
        resumen = (f"Nada crítico. {atencion} frente(s) en observación y "
                   f"{sum(1 for p in planes if p['estado'] == 'mejora')} oportunidad(es) de mejora.")
    else:
        resumen = ("No hay ningún frente en rojo con los datos visibles. Lo de abajo son mejoras: "
                   "dónde está el margen que el archivo sí permite ver.")
    return {"planes": planes, "criticos": criticos, "atencion": atencion, "resumen": resumen}
