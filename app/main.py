from datetime import date

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session, aliased

from app.database import get_db
from app.models import Equipo, Partido, Pronostico
from app.routers import web
from app.services.cache import modelo_para

app = FastAPI(title="Pronósticos de Fútbol")
app.include_router(web.router)


@app.get("/salud")
def salud(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"estado": "ok", "base_de_datos": "conectada"}


@app.get("/equipos")
def equipos(liga: str = "E0"):
    try:
        return sorted(modelo_para(liga).equipos)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/pronostico")
def pronostico(local: str, visitante: str, liga: str = "E0"):
    try:
        return modelo_para(liga).probabilidades(local, visitante)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/proximos")
def proximos(liga: str = "E0", db: Session = Depends(get_db)):
    local = aliased(Equipo)
    visita = aliased(Equipo)
    consulta = (
        select(Partido, local.nombre, visita.nombre, Pronostico)
        .join(local, local.id == Partido.local_id)
        .join(visita, visita.id == Partido.visitante_id)
        .outerjoin(Pronostico, Pronostico.partido_id == Partido.id)
        .where(Partido.liga == liga, Partido.goles_local.is_(None), Partido.fecha >= date.today())
        .order_by(Partido.fecha)
    )
    return [
        {
            "fecha": p.fecha, "local": nl, "visitante": nv,
            "prob_local": round(pr.prob_local, 3) if pr else None,
            "prob_empate": round(pr.prob_empate, 3) if pr else None,
            "prob_visitante": round(pr.prob_visitante, 3) if pr else None,
        }
        for p, nl, nv, pr in db.execute(consulta).all()
    ]