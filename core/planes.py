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
        # Siempre se dice contra qué se mide y cuánto vale la referencia: "por
        # debajo de la mediana" a secas no dice ni de qué ni de cuánto.
        etiqueta_base = "cumplimiento de meta" if base.get("clave") == "meta" else str(base.get("etiqueta", ""))
        mediana_txt = f"{mediana:,.0f}%" if base.get("sufijo") == "%" else f"{mediana:,.1f}"
        justa = bool(base.get("justo")) and base.get("clave") not in {"total", "total_parejo"}
        rezagados = [f for f in ranking if f["valor"] < mediana]
        if rezagados:
            nombres = [f["nombre"] for f in rezagados[-3:]]
            planes.append({
                "titulo": MEJORAS["brecha"]["titulo"], "estado": "mejora",
                "situacion": (f"{len(rezagados)} de {len(ranking)} están por debajo de la mediana del grupo en "
                              f"{etiqueta_base} ({mediana_txt}). Los más lejanos son {_lista(nombres)}."),
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
            "situacion": (f"{lider['nombre']} es el mejor en {etiqueta_base}: {lider['texto']} ({lider['detalle']})."
                          if justa else
                          f"{lider['nombre']} encabeza en {etiqueta_base}: {lider['texto']} ({lider['detalle']}). "
                          f"Ojo: eso mide tamaño, no desempeño."),
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


# Qué oportunidad de la lectura gerencial corresponde a cada plan: así el
# plan hereda su cifra ("vale 16M al mes") en vez de repetirse como frente
# aparte.
_OPORTUNIDAD_DE = {
    "Dónde se concentra la caída": "recuperar",
    "Caída generalizada": "recuperar",
    "Cumplimiento de meta": "meta",
    "Rezago frente a la mediana": "nivelar",
    MEJORAS["brecha"]["titulo"]: "nivelar",
}
_ESTADO_OPORTUNIDAD = {"recuperar": "critico", "meta": "atencion", "nivelar": "mejora"}


def _meta_de_caso(c: dict, mes: str) -> str:
    """Una línea de meta con cifras: de dónde parte, a dónde va y cuánto por semana."""
    texto = (f"{c['nombre']}: pasar de {_fmt(c['actual'])} a {_fmt(c['objetivo'])} en {mes} ({c['referencia']}) "
             f"— +{_fmt(c['brecha'])}, unos {_fmt(c['semanal'])} por semana")
    if c.get("operaciones"):
        texto += f", o {c['operaciones']:,} {c['unidad']} más al ticket actual de {_fmt(c['ticket'])}"
    return texto + "."


def _plan_cuantitativo(clave: str, o: dict, g: dict) -> Optional[dict]:
    """Pasos, medida, control y alarma calculados con la historia de cada caso.

    Reemplaza los pasos de plantilla ("fijar una meta de recuperación") por
    los números de esa meta: objetivo, brecha, ritmo semanal, operaciones
    necesarias, si es alcanzable y cuándo escalar. Los casos que están
    dentro de su variación normal no se intervienen: se vigilan."""
    casos = [c for c in (o.get("casos") or []) if c.get("brecha", 0) > 0]
    if not casos:
        return None
    mes = g.get("mes_siguiente") or "el próximo mes"
    actuar = [c for c in casos if not (clave == "recuperar" and c.get("tipo") == "normal")]
    vigilar = [c for c in casos if c not in actuar]
    if not actuar:
        return None
    pasos = []
    if clave == "recuperar":
        puntuales = [c["nombre"] for c in actuar if c.get("tipo") == "puntual"]
        sostenidos = [c for c in actuar if c.get("tipo") == "sostenida"]
        if puntuales:
            pasos.append(f"Averiguar qué pasó este mes en {_lista(puntuales)}: la caída es puntual (el mes anterior "
                         "estaba en su nivel normal). Revisar clientes que dejaron de comprar, quiebres de inventario "
                         "y cambios de ruta o de personal de ese mes.")
        for c in sostenidos:
            pasos.append(f"En {c['nombre']} la caída no es de un mes: lleva {c['racha']} meses seguidos bajando "
                         f"(≈{_fmt(abs(c['pendiente']))} por mes) y sin acción cerraría {mes} en {_fmt(c['proyeccion'])}. "
                         "Revisar cobertura y cartera desde que empezó, no solo el último mes.")
    elif clave == "meta":
        dificiles = [c["nombre"] for c in actuar if c.get("factibilidad") == "baja"]
        if dificiles:
            pasos.append(f"Revisar con datos la meta de {_lista(dificiles)}: exige superar su mejor mes en más de 10%. "
                         "O se cambia el plan (clientes nuevos, canal, precio) o se ajusta la meta.")
    elif clave == "nivelar" and o.get("lider"):
        pasos.append(f"Tomar como referencia a {o['lider']}, el de mejor resultado en {g.get('mes_b', 'el último mes')}: "
                     "documentar qué hace distinto (ruta, clientes, argumento, surtido) y copiar una práctica concreta.")
    pasos += [_meta_de_caso(c, mes) for c in actuar[:4]]
    if vigilar:
        pasos.append(f"{_lista([c['nombre'] for c in vigilar])}: está dentro de su variación normal; no intervenir, "
                     "solo confirmar el próximo mes.")
    primero = actuar[0]
    hitos = " · ".join(f"semana {i}: {_fmt(h)}" for i, h in enumerate(primero["hitos"], 1))
    control = f"Cada viernes, comparar el acumulado de {primero['nombre']} con su línea de objetivo ({hitos})."
    alarma = (f"Si a mitad de {mes} {primero['nombre']} lleva menos de {_fmt(primero['objetivo'] * 0.4)} "
              "(40% del objetivo), escalar: reasignar apoyo, revisar la ruta o ajustar el objetivo con datos.")
    total = sum(c["brecha"] for c in actuar)
    medir = (f"Que {primero['nombre']} cierre {mes} en al menos {_fmt(primero['objetivo'])}"
             + (f", y entre los {len(actuar)} se sumen {_fmt(total)}." if len(actuar) > 1 else "."))
    return {"pasos": pasos, "medir": medir, "control": control, "alarma": alarma, "casos": actuar}


def _con_gerencia(planes: list, g: dict) -> list:
    """Cruza los planes con la lectura gerencial.

    - Cada plan que corresponde a una oportunidad hereda su valor en dinero.
    - El plan de la caída se abre con la causa raíz (dónde entrar) y con la
      acción de la palanca (volumen o ticket), que cambia lo que hay que hacer.
    - Si una oportunidad con cifra no tiene plan, se agrega como frente nuevo.
    - Dentro de cada nivel de urgencia, va primero lo que más vale.
    """
    oportunidades = {o["clave"]: o for o in g.get("oportunidades") or []}
    usadas = set()
    for plan in planes:
        clave = _OPORTUNIDAD_DE.get(plan["titulo"])
        o = oportunidades.get(clave)
        if o and clave not in usadas:
            usadas.add(clave)
            plan["impacto"] = o["monto"]
            plan["impacto_txt"] = f"Vale {_fmt(o['monto'])} al mes"
            cuant = _plan_cuantitativo(clave, o, g)
            if cuant:
                plan.update({k: cuant[k] for k in ("pasos", "medir", "control", "alarma", "casos")})
        if clave == "recuperar" and g.get("causas"):
            extra = _pasos_de_causa(g)
            if extra:
                plan["pasos"] = extra[:1] + plan["pasos"] + extra[1:]
            plan["causa"] = g["causas"]
            plan["palanca"] = g.get("palanca")
            sig = g.get("significancia")
            if sig:
                plan["diagnostico"] = sig["texto"]
                # Si el total se movió dentro de su variación normal, no es
                # una urgencia: se vigila y se confirma antes de mover gente.
                if sig["nivel"] == "ruido" and plan["estado"] == "critico":
                    plan["estado"] = "atencion"
    for clave, o in oportunidades.items():
        if clave in usadas:
            continue
        # Recuperar solo es un frente si el total de verdad empeoró.
        if clave == "recuperar" and not g.get("empeoro"):
            continue
        # Una mejora sin cifra relevante no compite con lo urgente.
        cuant = _plan_cuantitativo(clave, o, g) or {}
        planes.append({
            "titulo": o["titulo"], "estado": _ESTADO_OPORTUNIDAD.get(clave, "mejora"),
            "situacion": o["texto"],
            "por_que": "Es donde más valor hay en juego con los datos de este archivo.",
            "pasos": cuant.get("pasos") or [o["accion"], f"Asignar un responsable por cada uno de {_lista([q['nombre'] for q in o['quienes']])}.",
                                            "Revisar el avance cada semana, no al cierre del mes."],
            "medir": cuant.get("medir") or o["medir"],
            "control": cuant.get("control"), "alarma": cuant.get("alarma"), "casos": cuant.get("casos") or [],
            "evidencia": [{"nombre": q["nombre"], "valor": _fmt(q["monto"]), "detalle": q["detalle"]}
                          for q in o["quienes"]],
            "objetivo": {},
            "impacto": o["monto"], "impacto_txt": f"Vale {_fmt(o['monto'])} al mes",
        })
    orden = {"critico": 0, "atencion": 1, "mejora": 2}
    # Estable: a igual urgencia e igual valor se respeta el orden del análisis.
    planes.sort(key=lambda p: (orden.get(p["estado"], 3), -(p.get("impacto") or 0)))
    return planes


def _pasos_de_causa(g: dict) -> list[str]:
    """Pasos que dependen de la causa y la palanca, en palabras de gerente."""
    pasos = []
    causas = g.get("causas") or {}
    nodos = causas.get("nodos") or []
    if nodos:
        n0 = nodos[0]
        donde = n0["nombre"]
        if n0.get("detalle") and n0["detalle"]["segmentos"]:
            s0 = n0["detalle"]["segmentos"][0]
            donde += f" ({n0['detalle']['etiqueta'].lower()} {s0['nombre']})"
        peso = f": ahí está el {n0['peso']:.0f}% del cambio" if n0.get("peso") is not None and 0 < abs(n0["peso"]) <= 300 else ""
        pasos.append(f"Entrar primero por {donde}{peso}.")
    if g.get("accion_palanca"):
        pasos.append(g["accion_palanca"])
    return pasos


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

    # La lectura gerencial —causa, palanca y cuánto vale cada frente— se
    # cruza con los planes: sin eso, un plan dice QUÉ hacer pero no cuánto
    # mueve el número ni por dónde entrarle.
    gerencia = (dashboard or {}).get("gerencia")
    if gerencia is None and "gerencia" not in (dashboard or {}):
        try:
            from .gerencia import analisis_gerencial
            gerencia = analisis_gerencial(df, schema, dashboard or {})
        except Exception:
            gerencia = None
    if gerencia:
        planes = _con_gerencia(planes, gerencia)
        criticos = sum(1 for p in planes if p["estado"] == "critico")
        atencion = sum(1 for p in planes if p["estado"] == "atencion")

    if criticos:
        resumen = (f"{criticos} frente(s) crítico(s) y {atencion} en observación. "
                   f"El orden de abajo es el orden de atención: lo primero es lo que más pesa.")
    elif atencion:
        resumen = (f"Nada crítico. {atencion} frente(s) en observación y "
                   f"{sum(1 for p in planes if p['estado'] == 'mejora')} oportunidad(es) de mejora.")
    else:
        resumen = ("No hay ningún frente en rojo con los datos visibles. Lo de abajo son mejoras: "
                   "dónde está el margen que el archivo sí permite ver.")
    if gerencia and gerencia.get("se_movio"):
        resumen = f"{gerencia['titular']} {resumen}"
    return {"planes": planes, "criticos": criticos, "atencion": atencion, "resumen": resumen,
            "gerencia": gerencia}
