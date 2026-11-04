from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.ligas import LIGAS, nombre_liga
from app.models import Equipo, Partido, Pronostico
from app.services.cache import modelo_para
from app.services.consultas import forma, precision, proximos_partidos, versiones_pronostico

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
ZONA_MEXICO = ZoneInfo("America/Mexico_City")
ESTADOS = {
    "SCHEDULED": "Programado",
    "TIMED": "Hora confirmada",
    "POSTPONED": "Pospuesto",
    "CANCELLED": "Cancelado",
    "FINISHED": "Finalizado",
}


def fecha_es(f) -> str:
    return f"{DIAS[f.weekday()].capitalize()} {f.day} de {MESES[f.month - 1]}"


def hora_mexico(f) -> str:
    return f.astimezone(ZONA_MEXICO).strftime("%H:%M")


templates.env.filters["fecha_es"] = fecha_es
templates.env.filters["hora_mexico"] = hora_mexico
templates.env.filters["estado_es"] = lambda estado: ESTADOS.get(estado, estado)
templates.env.filters["pct"] = lambda x: f"{x * 100:.0f}%"


def _liga(liga: str) -> str:
    """'' significa todas las ligas."""
    return liga if liga in LIGAS else ""


@router.get("/")
def inicio(request: Request, liga: str = "", dias: int = 14, db: Session = Depends(get_db)):
    liga, dias = _liga(liga), min(max(dias, 1), 60)
    return templates.TemplateResponse(request, "index.html", {
        "partidos": proximos_partidos(db, liga or None, dias),
        "dias": dias, "liga": liga, "ligas": LIGAS,
    })


@router.get("/lista")
def lista(request: Request, liga: str = "", dias: int = 14, db: Session = Depends(get_db)):
    """Fragmento HTML que HTMX intercambia al cambiar el selector."""
    liga, dias = _liga(liga), min(max(dias, 1), 60)
    return templates.TemplateResponse(request, "_lista.html", {
        "partidos": proximos_partidos(db, liga or None, dias), "liga": liga,
    })


def analisis(modelo, local: str, visita: str) -> dict:
    m = modelo.matriz(local, visita)
    n = m.shape[0]
    top = sorted(
        ((f"{i}-{j}", float(m[i, j])) for i in range(n) for j in range(n)),
        key=lambda x: -x[1],
    )[:5]
    suma = np.add.outer(np.arange(n), np.arange(n))
    return {
        "top": top,
        "mas_2_5": float(m[suma >= 3].sum()),
        "ambos": float(m[1:, 1:].sum()),
    }


@router.get("/partido/{partido_id}")
def detalle(request: Request, partido_id: int, db: Session = Depends(get_db)):
    p = db.get(Partido, partido_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Partido no encontrado")
    local, visita = db.get(Equipo, p.local_id), db.get(Equipo, p.visitante_id)
    pron = db.scalars(
        select(Pronostico)
        .where(Pronostico.partido_id == p.id)
        .order_by(Pronostico.publicado_en.desc(), Pronostico.id.desc())
    ).first()

    extra = None
    if p.goles_local is None:
        try:
            extra = analisis(modelo_para(p.liga), local.nombre, visita.nombre)
        except ValueError:
            extra = None

    return templates.TemplateResponse(request, "partido.html", {
        "p": p, "local": local.nombre, "visita": visita.nombre, "pron": pron, "extra": extra,
        "nombre_liga": nombre_liga(p.liga),
        "forma_local": forma(db, local.id), "forma_visita": forma(db, visita.id),
    })


@router.get("/precision")
def pagina_precision(
    request: Request,
    liga: str = "",
    version: str = "",
    desde: date | None = None,
    hasta: date | None = None,
    db: Session = Depends(get_db),
):
    liga = _liga(liga)
    return templates.TemplateResponse(request, "precision.html", {
        "datos": precision(db, liga or None, version or None, desde, hasta),
        "liga": liga, "ligas": LIGAS, "version": version,
        "versiones": versiones_pronostico(db, liga or None), "desde": desde, "hasta": hasta,
    })
