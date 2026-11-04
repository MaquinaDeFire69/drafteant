import math
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from app.ligas import nombre_liga
from app.models import Equipo, Partido, Pronostico

RESULTADOS = ("local", "empate", "visitante")
INTERVALOS_CALIBRACION = 10


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
            .order_by(Pronostico.partido_id, Pronostico.publicado_en, Pronostico.id)
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
