import math
from itertools import combinations
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import inspect, or_, select
from sqlalchemy.orm import Session, aliased

from app.ligas import nombre_liga
from app.models import Cuota, CuotaMercado, Equipo, Partido, Pronostico

RESULTADOS = ("local", "empate", "visitante")
INTERVALOS_CALIBRACION = 10


def _utc(valor: datetime) -> datetime:
    return valor.replace(tzinfo=timezone.utc) if valor.tzinfo is None else valor.astimezone(timezone.utc)


def proximos_partidos(db: Session, liga: str | None = None, dias: int = 14) -> list[dict]:
    hoy = date.today()
    local, visita = aliased(Equipo), aliased(Equipo)
    consulta = (
        select(Partido, local.nombre, visita.nombre)
        .join(local, local.id == Partido.local_id)
        .join(visita, visita.id == Partido.visitante_id)
        .where(
            Partido.goles_local.is_(None),
            Partido.estado.in_(("SCHEDULED", "TIMED")),
            Partido.fecha >= hoy,
            Partido.fecha <= hoy + timedelta(days=dias),
        )
    )
    if liga:
        consulta = consulta.where(Partido.liga == liga)
    filas = db.execute(consulta.order_by(Partido.fecha, Partido.liga, Partido.id)).all()

    pron = {}
    ids = [p.id for p, _, _ in filas]
    if ids:
        for pr in db.scalars(
            select(Pronostico)
            .where(Pronostico.partido_id.in_(ids))
            .order_by(Pronostico.partido_id, Pronostico.publicado_en.asc().nulls_first(), Pronostico.id)
        ):
            pron[pr.partido_id] = pr  # queda el más reciente

    return [
        {
            "id": p.id, "fecha": p.fecha, "liga": p.liga, "nombre_liga": nombre_liga(p.liga),
            "local": l, "visitante": v, "inicio_utc": p.inicio_utc, "estado": p.estado,
            "pron": pron.get(p.id),
        }
        for p, l, v in filas
    ]


def selecciones_destacadas(
    partidos: list[dict],
    limite: int = 10,
    ahora: datetime | None = None,
) -> list[dict]:
    """Ordena victorias 1X2 futuras por probabilidad del pronóstico guardado."""
    ahora = ahora or datetime.now(timezone.utc)
    selecciones = []
    for partido in partidos:
        inicio = partido["inicio_utc"]
        pron = partido["pron"]
        if inicio is None or inicio <= ahora or pron is None:
            continue
        if pron.publicado_en is None or pron.publicado_en >= inicio or pron.publicado_en > ahora:
            continue

        probabilidades = (pron.prob_local, pron.prob_empate, pron.prob_visitante)
        if any(not math.isfinite(p) or not 0 <= p <= 1 for p in probabilidades):
            continue

        lado, probabilidad = max(
            (("local", pron.prob_local), ("visitante", pron.prob_visitante)),
            key=lambda item: item[1],
        )
        selecciones.append({
            **partido,
            "seleccion": partido["local"] if lado == "local" else partido["visitante"],
            "lado": lado,
            "probabilidad": probabilidad,
            "version_modelo": pron.version_modelo,
            "publicado_en": pron.publicado_en,
        })

    return sorted(
        selecciones,
        key=lambda item: (-item["probabilidad"], item["inicio_utc"], item["id"]),
    )[:limite]


def agregar_cuotas(db: Session, selecciones: list[dict]) -> list[dict]:
    """Añade la mejor cuota vigente capturada para la versión mostrada del pronóstico."""
    if not selecciones or not inspect(db.get_bind()).has_table("cuotas"):
        return selecciones
    ids = [s["id"] for s in selecciones]
    por_partido_casa = {}
    for cuota in db.scalars(
        select(Cuota).where(Cuota.partido_id.in_(ids))
        .order_by(Cuota.capturada_en, Cuota.id)
    ):
        por_partido_casa[(cuota.partido_id, cuota.casa)] = cuota

    for seleccion in selecciones:
        candidatas = [
            c for (partido_id, _), c in por_partido_casa.items()
            if partido_id == seleccion["id"]
            and c.pronostico_id == seleccion["pron"].id
            and c.capturada_en < seleccion["inicio_utc"]
        ]
        if not candidatas:
            continue
        campo = "cuota_local" if seleccion["lado"] == "local" else "cuota_visitante"
        por_casa = {c.casa: c for c in candidatas}
        seleccion["cuotas_por_casa"] = {
            casa: {
                "cuota": getattr(cuota, campo),
                "capturada_en": cuota.capturada_en,
                "probabilidad_mercado": 1 / getattr(cuota, campo),
                "diferencia_modelo_mercado": seleccion["probabilidad"] - (1 / getattr(cuota, campo)),
            }
            for casa, cuota in por_casa.items()
        }
        mejor = max(por_casa.values(), key=lambda c: getattr(c, campo))
        cuota_decimal = getattr(mejor, campo)
        seleccion["cuota"] = cuota_decimal
        seleccion["casa"] = mejor.casa
        seleccion["cuota_capturada_en"] = mejor.capturada_en
        seleccion["valor_esperado"] = seleccion["probabilidad"] * cuota_decimal - 1
        seleccion["probabilidad_mercado"] = 1 / cuota_decimal
        seleccion["diferencia_modelo_mercado"] = seleccion["probabilidad"] - seleccion["probabilidad_mercado"]
    return selecciones


def selecciones_1x2(db: Session, partidos: list[dict]) -> list[dict]:
    """Tres resultados 1X2 por partido, sujetos a cuotas reales disponibles."""
    if not partidos or not inspect(db.get_bind()).has_table("cuotas"):
        return []
    ahora = datetime.now(timezone.utc)
    ultimas = {}
    for cuota in db.scalars(
        select(Cuota).where(Cuota.partido_id.in_([p["id"] for p in partidos]))
        .order_by(Cuota.capturada_en, Cuota.id)
    ):
        ultimas[(cuota.partido_id, cuota.casa)] = cuota
    salida = []
    for partido in partidos:
        pron, inicio = partido["pron"], partido["inicio_utc"]
        if not pron or not inicio or _utc(inicio) <= ahora or not pron.publicado_en:
            continue
        if _utc(pron.publicado_en) >= _utc(inicio) or _utc(pron.publicado_en) > ahora:
            continue
        for lado, campo_prob, campo_cuota, etiqueta in (
            ("local", "prob_local", "cuota_local", partido["local"] + " gana"),
            ("empate", "prob_empate", "cuota_empate", "Empate"),
            ("visitante", "prob_visitante", "cuota_visitante", partido["visitante"] + " gana"),
        ):
            prob = getattr(pron, campo_prob)
            if not math.isfinite(prob) or not 0 <= prob <= 1:
                continue
            por_casa = {}
            for (partido_id, casa), cuota in ultimas.items():
                if partido_id != partido["id"] or _utc(cuota.capturada_en) >= _utc(inicio):
                    continue
                precio = getattr(cuota, campo_cuota)
                if precio and math.isfinite(precio) and precio > 1:
                    por_casa[casa] = {"cuota": precio, "capturada_en": cuota.capturada_en}
            if not por_casa:
                continue
            casa = max(por_casa, key=lambda c: por_casa[c]["cuota"])
            salida.append({**partido, "mercado": "h2h", "lado": lado,
                           "seleccion": etiqueta, "probabilidad": prob,
                           "cuotas_por_casa": por_casa, "casa": casa,
                           "cuota": por_casa[casa]["cuota"],
                           "valor_esperado": prob * por_casa[casa]["cuota"] - 1})
    return salida


def selecciones_mercados(db: Session, partidos: list[dict], mercado: str) -> list[dict]:
    """Construye selecciones de goles/BTTS con probabilidades publicadas antes del inicio."""
    if mercado not in {"total_25", "btts"} or not partidos:
        return []
    if not inspect(db.get_bind()).has_table("cuotas_mercado"):
        return []
    ahora = datetime.now(timezone.utc)
    ids = [p["id"] for p in partidos]
    ultimas = {}
    for cuota in db.scalars(
        select(CuotaMercado).where(CuotaMercado.partido_id.in_(ids), CuotaMercado.mercado == mercado)
        .order_by(CuotaMercado.capturada_en, CuotaMercado.id)
    ):
        ultimas[(cuota.partido_id, cuota.opcion, cuota.casa)] = cuota
    salida = []
    for partido in partidos:
        pron = partido["pron"]
        inicio = partido["inicio_utc"]
        if not pron or not inicio or _utc(inicio) <= ahora or not pron.publicado_en:
            continue
        if _utc(pron.publicado_en) >= _utc(inicio) or _utc(pron.publicado_en) > ahora:
            continue
        base = pron.prob_mas_2_5 if mercado == "total_25" else pron.prob_ambos_anotan
        if base is None or not math.isfinite(base) or not 0 <= base <= 1:
            continue
        opciones = ("mas", "menos") if mercado == "total_25" else ("si", "no")
        for opcion in opciones:
            prob = base if opcion in {"mas", "si"} else 1 - base
            por_casa = {}
            for (partido_id, cuota_opcion, casa), cuota in ultimas.items():
                if partido_id != partido["id"] or cuota_opcion != opcion:
                    continue
                if _utc(cuota.capturada_en) >= _utc(inicio) or _utc(cuota.capturada_en) > ahora:
                    continue
                por_casa[casa] = {"cuota": cuota.cuota_decimal, "capturada_en": cuota.capturada_en,
                                 "probabilidad_mercado": 1 / cuota.cuota_decimal,
                                 "diferencia_modelo_mercado": prob - 1 / cuota.cuota_decimal}
            if not por_casa:
                continue
            mejor_casa = max(por_casa, key=lambda casa: por_casa[casa]["cuota"])
            etiqueta = ("Más de 2.5 goles" if opcion == "mas" else "Menos de 2.5 goles") \
                if mercado == "total_25" else ("Ambos anotan: Sí" if opcion == "si" else "Ambos anotan: No")
            salida.append({
                **partido, "mercado": mercado, "lado": opcion, "seleccion": etiqueta,
                "probabilidad": prob, "cuotas_por_casa": por_casa,
                "casa": mejor_casa, "cuota": por_casa[mejor_casa]["cuota"],
                "valor_esperado": prob * por_casa[mejor_casa]["cuota"] - 1,
            })
    return salida


def limitar_candidatas(selecciones: list[dict], mitad: int = 16) -> list[dict]:
    """Mantiene favoritas y opciones con mejor precio sin repetir la misma selección."""
    disponibles = [s for s in selecciones if s.get("cuotas_por_casa")]
    probables = sorted(disponibles, key=lambda s: -s["probabilidad"])[:mitad]
    valor = sorted(disponibles, key=lambda s: -s.get("valor_esperado", -1))[:mitad]
    unicas = {(s["id"], s.get("mercado", "h2h"), s.get("lado", "")): s for s in probables + valor}
    return list(unicas.values())


def parlays(
    selecciones: list[dict], limite_por_grupo: int = 5, cantidad: int = 2,
) -> dict[str, list[dict]]:
    """Forma parlays de 2 a 5 partidos con cuotas de una misma casa.

    La probabilidad conjunta es el producto de ambas probabilidades, por lo que
    se usa como aproximación bajo independencia entre partidos distintos.
    """
    cantidad = min(max(cantidad, 2), 5)
    grupos = {"seguras": [], "analizar": [], "riesgosas": [], "regalar_dinero": []}
    candidatas = [s for s in selecciones if s.get("cuotas_por_casa")]
    # Evita que combinaciones de 4–5 partidos crezcan de forma explosiva.
    if cantidad >= 4:
        candidatas = limitar_candidatas(candidatas, mitad=8)
    for combinacion in combinations(candidatas, cantidad):
        if len({s["id"] for s in combinacion}) != cantidad:
            continue
        casas_comunes = set.intersection(*(set(s["cuotas_por_casa"]) for s in combinacion))
        if not casas_comunes:
            continue
        casa = max(
            casas_comunes,
            key=lambda c: math.prod(s["cuotas_por_casa"][c]["cuota"] for s in combinacion),
        )
        cuota = math.prod(s["cuotas_por_casa"][casa]["cuota"] for s in combinacion)
        probabilidad = math.prod(s["probabilidad"] for s in combinacion)
        if probabilidad >= 0.70:
            grupo = "seguras"
        elif probabilidad >= 0.60:
            grupo = "analizar"
        elif probabilidad >= 0.40:
            grupo = "riesgosas"
        elif probabilidad >= 0.20:
            grupo = "regalar_dinero"
        else:
            continue
        grupos[grupo].append({
            "selecciones": combinacion, "probabilidad": probabilidad,
            "cuota": cuota, "casa": casa, "valor_esperado": probabilidad * cuota - 1,
            "probabilidad_mercado": 1 / cuota,
            "diferencia_modelo_mercado": probabilidad - (1 / cuota),
        })
    for grupo in grupos.values():
        grupo.sort(key=lambda p: (-p["probabilidad"], -p["valor_esperado"], -p["cuota"]))
        del grupo[limite_por_grupo:]
    return grupos


def forma(db: Session, equipo_id: int, n: int = 5) -> list[dict]:
    """Últimos n partidos jugados del equipo."""
    local, visita = aliased(Equipo), aliased(Equipo)
    filas = db.execute(
        select(Partido, local.nombre, visita.nombre)
        .join(local, local.id == Partido.local_id)
        .join(visita, visita.id == Partido.visitante_id)
        .where(
            or_(Partido.local_id == equipo_id, Partido.visitante_id == equipo_id),
            Partido.goles_local.is_not(None),
        )
        .order_by(Partido.fecha.desc())
        .limit(n)
    ).all()

    salida = []
    for p, l, v in filas:
        es_local = p.local_id == equipo_id
        gf, gc = (p.goles_local, p.goles_visitante) if es_local else (p.goles_visitante, p.goles_local)
        salida.append({
            "fecha": p.fecha,
            "rival": v if es_local else l,
            "condicion": "L" if es_local else "V",
            "marcador": f"{p.goles_local}-{p.goles_visitante}",
            "resultado": "G" if gf > gc else ("E" if gf == gc else "P"),
        })
    return salida


def versiones_pronostico(db: Session, liga: str | None = None) -> list[str]:
    consulta = select(Pronostico.version_modelo).join(Partido).distinct()
    if liga:
        consulta = consulta.where(Partido.liga == liga)
    return list(db.scalars(consulta.order_by(Pronostico.version_modelo)))


def _calibracion(observaciones: list[tuple[list[float], int]]) -> tuple[dict, dict]:
    """Agrupa cada probabilidad 1X2 y el resultado observado en diez intervalos."""
    acumulados = {
        resultado: [dict(n=0, previsto=0.0, ocurridos=0) for _ in range(INTERVALOS_CALIBRACION)]
        for resultado in RESULTADOS
    }
    for probs, real in observaciones:
        for indice, resultado in enumerate(RESULTADOS):
            intervalo = min(int(probs[indice] * INTERVALOS_CALIBRACION), INTERVALOS_CALIBRACION - 1)
            grupo = acumulados[resultado][intervalo]
            grupo["n"] += 1
            grupo["previsto"] += probs[indice]
            grupo["ocurridos"] += int(real == indice)

    series, resumen = {}, {}
    for resultado, grupos in acumulados.items():
        filas, suma_error, mayor_error, suma_sesgo, total = [], 0.0, 0.0, 0.0, 0
        for indice, grupo in enumerate(grupos):
            if not grupo["n"]:
                continue
            previsto = grupo["previsto"] / grupo["n"]
            observado = grupo["ocurridos"] / grupo["n"]
            error = observado - previsto
            filas.append({
                "desde": indice / INTERVALOS_CALIBRACION,
                "hasta": (indice + 1) / INTERVALOS_CALIBRACION,
                "n": grupo["n"], "previsto": previsto, "observado": observado, "error": error,
            })
            total += grupo["n"]
            suma_error += grupo["n"] * abs(error)
            suma_sesgo += grupo["n"] * error
            mayor_error = max(mayor_error, abs(error))
        series[resultado] = filas
        resumen[resultado] = {
            "ece": suma_error / total if total else 0.0,
            "sesgo": suma_sesgo / total if total else 0.0,
            "max_error": mayor_error,
        }
    return series, resumen


def precision(
    db: Session,
    liga: str | None = None,
    version: str | None = None,
    desde: date | None = None,
    hasta: date | None = None,
) -> dict | None:
    """Compara pronósticos guardados antes del partido con el resultado real."""
    consulta = (
        select(Partido, Pronostico)
        .join(Pronostico, Pronostico.partido_id == Partido.id)
        .where(
            Partido.goles_local.is_not(None),
            Partido.inicio_utc.is_not(None),
            Pronostico.publicado_en.is_not(None),
            Pronostico.publicado_en < Partido.inicio_utc,
        )
        .order_by(Partido.id, Pronostico.publicado_en, Pronostico.id)
    )
    if liga:
        consulta = consulta.where(Partido.liga == liga)
    if desde:
        consulta = consulta.where(Partido.fecha >= desde)
    if hasta:
        consulta = consulta.where(Partido.fecha <= hasta)

    ultimo = {}
    for p, pr in db.execute(consulta).all():
        # La consulta está ordenada: queda el último pronóstico publicado antes del inicio.
        ultimo[p.id] = (p, pr)
    evaluables = [par for par in ultimo.values() if not version or par[1].version_modelo == version]
    if not evaluables:
        return None

    n = aciertos = 0
    log_loss = brier = 0.0
    observaciones = []
    for p, pr in evaluables:
        probs = [pr.prob_local, pr.prob_empate, pr.prob_visitante]
        real = 0 if p.goles_local > p.goles_visitante else (1 if p.goles_local == p.goles_visitante else 2)
        y = [1.0 if i == real else 0.0 for i in range(3)]
        log_loss += -math.log(max(probs[real], 1e-12))
        brier += sum((a - b) ** 2 for a, b in zip(probs, y))
        aciertos += int(probs.index(max(probs)) == real)
        observaciones.append((probs, real))
        n += 1

    calibracion, calibracion_resumen = _calibracion(observaciones)
    ece = sum(item["ece"] for item in calibracion_resumen.values()) / len(RESULTADOS)
    max_error = max(item["max_error"] for item in calibracion_resumen.values())
    return {
        "n": n, "acierto": 100 * aciertos / n, "log_loss": log_loss / n, "brier": brier / n,
        "calibracion": calibracion, "calibracion_resumen": calibracion_resumen,
        "ece": ece, "max_error_calibracion": max_error,
    }
