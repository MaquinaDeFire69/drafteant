from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from app.models import Equipo, Partido, Pronostico


def proximos_partidos(db: Session, liga: str = "E0", dias: int = 14) -> list[dict]:
    hoy = date.today()
    local, visita = aliased(Equipo), aliased(Equipo)
    filas = db.execute(
        select(Partido, local.nombre, visita.nombre)
        .join(local, local.id == Partido.local_id)
        .join(visita, visita.id == Partido.visitante_id)
        .where(
            Partido.liga == liga,
            Partido.goles_local.is_(None),
            Partido.fecha >= hoy,
            Partido.fecha <= hoy + timedelta(days=dias),
        )
        .order_by(Partido.fecha, Partido.id)
    ).all()

    pron = {}
    ids = [p.id for p, _, _ in filas]
    if ids:
        for pr in db.scalars(
            select(Pronostico).where(Pronostico.partido_id.in_(ids)).order_by(Pronostico.id)
        ):
            pron[pr.partido_id] = pr  # queda el más reciente

    return [
        {"id": p.id, "fecha": p.fecha, "local": l, "visitante": v, "pron": pron.get(p.id)}
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


def precision(db: Session, liga: str = "E0") -> dict | None:
    """Compara pronósticos guardados antes del partido con el resultado real."""
    import math

    filas = db.execute(
        select(Partido, Pronostico)
        .join(Pronostico, Pronostico.partido_id == Partido.id)
        .where(Partido.liga == liga, Partido.goles_local.is_not(None))
        .order_by(Pronostico.id)
    ).all()

    ultimo = {}
    for p, pr in filas:
        ultimo[p.id] = (p, pr)
    if not ultimo:
        return None

    n = aciertos = 0
    log_loss = brier = 0.0
    for p, pr in ultimo.values():
        probs = [pr.prob_local, pr.prob_empate, pr.prob_visitante]
        real = 0 if p.goles_local > p.goles_visitante else (1 if p.goles_local == p.goles_visitante else 2)
        y = [1.0 if i == real else 0.0 for i in range(3)]
        log_loss += -math.log(max(probs[real], 1e-12))
        brier += sum((a - b) ** 2 for a, b in zip(probs, y))
        aciertos += int(probs.index(max(probs)) == real)
        n += 1

    return {
        "n": n,
        "acierto": 100 * aciertos / n,
        "log_loss": log_loss / n,
        "brier": brier / n,
    }