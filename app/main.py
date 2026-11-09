from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers import web
from app.services.cache import modelo_para
from app.services.consultas import proximos_partidos

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
def proximos(liga: str = "E0", dias: int = 14, db: Session = Depends(get_db)):
    """Una fila por partido, con el último pronóstico publicado."""
    return [
        {
            "id": m["id"], "fecha": m["fecha"], "inicio_utc": m["inicio_utc"], "estado": m["estado"],
            "local": m["local"], "visitante": m["visitante"],
            "local_escudo": m["local_escudo"], "visitante_escudo": m["visitante_escudo"],
            "posicion_local": m["posicion_local"],
            "posicion_visitante": m["posicion_visitante"],
            "prob_local": round(m["pron"].prob_local, 3) if m["pron"] else None,
            "prob_empate": round(m["pron"].prob_empate, 3) if m["pron"] else None,
            "prob_visitante": round(m["pron"].prob_visitante, 3) if m["pron"] else None,
        }
        for m in proximos_partidos(db, liga, min(max(dias, 1), 60))
    ]
