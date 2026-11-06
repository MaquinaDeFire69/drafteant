from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlencode
from zoneinfo import ZoneInfo

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.ligas import LIGAS, nombre_liga
from app.models import Equipo, ParlaySimulado, Partido, Pronostico, SeleccionSeguimiento
from app.services.cache import modelo_para
from app.services.consultas import (
    agregar_cuotas, forma, limitar_candidatas, parlays, precision, proximos_partidos, selecciones_destacadas,
    selecciones_1x2, selecciones_mercados, versiones_pronostico,
)
from app.services.seguimiento import (
    candidatas_parlay, casas_disponibles, configuracion_exposicion, crear_parlay_simulado, curva_banca,
    crear_estrategia, estrategias, exposicion_activa, guardar_configuracion_exposicion,
    parlays_modelo_disponibles, rendimiento_parlays, rendimiento_selecciones, validar_exposicion_parlay,
)

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
        .order_by(Pronostico.publicado_en.desc().nulls_last(), Pronostico.id.desc())
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


@router.get("/analisis")
def pagina_analisis(
    request: Request,
    liga: str = "",
    dias: int = 14,
    cantidad: int = 2,
    mercado: str = "h2h",
    db: Session = Depends(get_db),
):
    liga, dias = _liga(liga), min(max(dias, 1), 30)
    cantidad = min(max(cantidad, 2), 5)
    mercado = mercado if mercado in {"h2h", "total_25", "btts", "mixto"} else "h2h"
    proximos = proximos_partidos(db, liga or None, dias)
    # El top 10 sirve para explorar, pero los parlays deben considerar todos
    # los próximos partidos con cuota, incluso si una liga sin cuotas ocupa el top.
    destacados = selecciones_1x2(db, proximos)
    if mercado == "h2h":
        candidatas = destacados
    else:
        adicionales = (selecciones_mercados(db, proximos, "total_25") if mercado in {"total_25", "mixto"} else [])
        adicionales += (selecciones_mercados(db, proximos, "btts") if mercado in {"btts", "mixto"} else [])
        if mercado == "mixto":
            por_partido = {}
            for seleccion in destacados + adicionales:
                if seleccion.get("cuotas_por_casa"):
                    actual = por_partido.get(seleccion["id"])
                    if actual is None or seleccion.get("valor_esperado", -1) > actual.get("valor_esperado", -1):
                        por_partido[seleccion["id"]] = seleccion
            candidatas = list(por_partido.values())
        else:
            candidatas = adicionales
    candidatas = limitar_candidatas(candidatas)
    return templates.TemplateResponse(request, "analisis.html", {
        "parlays": parlays(candidatas, cantidad=cantidad),
        "liga": liga, "ligas": LIGAS, "dias": dias, "cantidad": cantidad, "mercado": mercado,
    })


@router.get("/simulacion")
def pagina_simulacion(
    request: Request,
    liga: str = "",
    casa: str = "",
    min_probabilidad: int = 0,
    min_valor: int = -100,
    cuota_min: float | None = None,
    cuota_max: float | None = None,
    banca_inicial: float | None = None,
    casa_parlay: str = "",
    mensaje: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    liga = _liga(liga)
    casas = casas_disponibles(db)
    casa = casa if casa in casas else ""
    min_probabilidad = min(max(min_probabilidad, 0), 100)
    min_valor = min(max(min_valor, -100), 100)
    configuracion = configuracion_exposicion(db)
    banca_inicial = configuracion["banca_inicial"] if banca_inicial is None else min(max(banca_inicial, 1.0), 100_000.0)
    seguimiento = rendimiento_selecciones(
        db, liga or None, casa or None, min_probabilidad / 100, min_valor / 100, cuota_min, cuota_max,
    )
    curva = curva_banca(seguimiento["filas_para_curva"], banca_inicial)
    estrategias_con_rendimiento = []
    for estrategia in estrategias(db):
        estrategias_con_rendimiento.append({
            "estrategia": estrategia,
            "rendimiento": rendimiento_selecciones(
                db, estrategia.liga, estrategia.casa, estrategia.min_probabilidad,
                estrategia.min_valor, estrategia.cuota_min, estrategia.cuota_max,
                monto=estrategia.monto,
            ),
        })
    candidatas = (candidatas_parlay(db, mercado="h2h") +
                  candidatas_parlay(db, mercado="total_25") +
                  candidatas_parlay(db, mercado="btts"))
    casas_parlay = sorted({casa for s in candidatas for casa in s.get("cuotas_por_casa", {})})
    casa_parlay = casa_parlay if casa_parlay in casas_parlay else (casas_parlay[0] if casas_parlay else "")
    seleccionables = [s for s in candidatas if casa_parlay in s.get("cuotas_por_casa", {})]
    parlays_guardados = rendimiento_parlays(db)
    rendimiento_por_tipo = [{
        "tipo": "Individuales", "total": seguimiento["total"],
        "evaluados": seguimiento["evaluadas"], "ganados": seguimiento["aciertos"],
        "ganancia": seguimiento["ganancia"], "roi": seguimiento["roi"],
    }, *parlays_guardados["por_tipo"]]
    return templates.TemplateResponse(request, "simulacion.html", {
        "seguimiento": seguimiento, "liga": liga, "ligas": LIGAS,
        "casa": casa, "casas": casas, "min_probabilidad": min_probabilidad,
        "min_valor": min_valor, "parlays_modelo": parlays_modelo_disponibles(db),
        "parlays_guardados": parlays_guardados, "rendimiento_por_tipo": rendimiento_por_tipo,
        "casa_parlay": casa_parlay,
        "casas_parlay": casas_parlay, "seleccionables": seleccionables,
        "mensaje": mensaje, "error": error,
        "cuota_min": cuota_min, "cuota_max": cuota_max,
        "estrategias": estrategias_con_rendimiento, "curva": curva,
        "exposicion": exposicion_activa(db),
    })


async def _formulario(request: Request) -> dict[str, list[str]]:
    cuerpo = (await request.body()).decode("utf-8")
    return parse_qs(cuerpo, keep_blank_values=True)


def _redireccion_simulacion(campo: str, texto: str) -> RedirectResponse:
    return RedirectResponse(f"/simulacion?{urlencode({campo: texto})}", status_code=303)


@router.post("/simulacion/parlays/modelo")
async def guardar_parlay_modelo(request: Request, db: Session = Depends(get_db)):
    datos = await _formulario(request)
    clave = datos.get("clave", [""])[0]
    try:
        candidato = next(p for p in parlays_modelo_disponibles(db) if p["clave"] == clave)
        avisos = validar_exposicion_parlay(
            db, [s["id"] for s in candidato["selecciones"]], datos.get("monto", ["100"])[0],
            [(s["id"], s["mercado"], s["lado"]) for s in candidato["selecciones"]],
        )
        if avisos and configuracion_exposicion(db)["bloquear_exceso"]:
            raise ValueError("No se guardó: " + "; ".join(avisos))
        crear_parlay_simulado(
            db, "modelo", candidato["casa"],
            [s["id"] for s in candidato["selecciones"]], datos.get("monto", ["100"])[0],
            elecciones=[(s["id"], s["mercado"], s["lado"]) for s in candidato["selecciones"]],
        )
        db.commit()
    except (StopIteration, ValueError) as exc:
        db.rollback()
        return _redireccion_simulacion("error", str(exc) or "El parlay ya no está disponible")
    texto = "Parlay del modelo agregado a la simulación"
    if avisos:
        texto += ". Advertencia: " + "; ".join(avisos)
    return _redireccion_simulacion("mensaje", texto)


@router.post("/simulacion/exposicion")
async def guardar_exposicion(request: Request, db: Session = Depends(get_db)):
    datos = await _formulario(request)
    try:
        guardar_configuracion_exposicion(
            db, datos.get("banca_inicial", ["1000"])[0],
            datos.get("limite_partido", ["10"])[0], datos.get("limite_equipo", ["20"])[0],
            datos.get("bloquear_exceso", [""])[0] == "on",
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _redireccion_simulacion("error", str(exc))
    return _redireccion_simulacion("mensaje", "Límites de exposición actualizados")


@router.post("/simulacion/estrategias")
async def guardar_estrategia(request: Request, db: Session = Depends(get_db)):
    datos = await _formulario(request)
    try:
        crear_estrategia(
            db, datos.get("nombre", [""])[0], datos.get("liga", [""])[0], datos.get("casa", [""])[0],
            float(datos.get("min_probabilidad", ["0"])[0]) / 100,
            float(datos.get("min_valor", ["-100"])[0]) / 100,
            float(datos["cuota_min"][0]) if datos.get("cuota_min", [""])[0] else None,
            float(datos["cuota_max"][0]) if datos.get("cuota_max", [""])[0] else None,
            datos.get("monto", ["100"])[0],
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _redireccion_simulacion("error", str(exc))
    return _redireccion_simulacion("mensaje", "Estrategia guardada; usa sus reglas para comparar el histórico")


async def _cambiar_estado(request: Request, registro, db: Session) -> RedirectResponse:
    datos = await _formulario(request)
    estado = datos.get("estado_registro", [""])[0]
    if estado not in {"simulada", "apostada", "descartada"}:
        return _redireccion_simulacion("error", "Estado de seguimiento inválido")
    registro.estado_registro = estado
    db.commit()
    return _redireccion_simulacion("mensaje", "Estado de seguimiento actualizado")


@router.post("/simulacion/selecciones/{seleccion_id}/estado")
async def cambiar_estado_seleccion(seleccion_id: int, request: Request, db: Session = Depends(get_db)):
    seleccion = db.get(SeleccionSeguimiento, seleccion_id)
    if seleccion is None:
        raise HTTPException(status_code=404, detail="Selección no encontrada")
    return await _cambiar_estado(request, seleccion, db)


@router.post("/simulacion/parlays/{parlay_id}/estado")
async def cambiar_estado_parlay(parlay_id: int, request: Request, db: Session = Depends(get_db)):
    parlay = db.get(ParlaySimulado, parlay_id)
    if parlay is None:
        raise HTTPException(status_code=404, detail="Parlay no encontrado")
    return await _cambiar_estado(request, parlay, db)


@router.post("/simulacion/parlays/personal")
async def guardar_parlay_personal(request: Request, db: Session = Depends(get_db)):
    datos = await _formulario(request)
    try:
        elecciones = []
        for valor in datos.get("seleccion", []):
            partido_id, mercado, lado = valor.split(":", 2)
            elecciones.append((int(partido_id), mercado, lado))
        ids = [item[0] for item in elecciones]
        avisos = validar_exposicion_parlay(db, ids, datos.get("monto", ["100"])[0], elecciones)
        if avisos and configuracion_exposicion(db)["bloquear_exceso"]:
            raise ValueError("No se guardó: " + "; ".join(avisos))
        crear_parlay_simulado(
            db, "personal", datos.get("casa_parlay", [""])[0], ids,
            datos.get("monto", ["100"])[0],
            elecciones=elecciones,
        )
        db.commit()
    except (TypeError, ValueError) as exc:
        db.rollback()
        return _redireccion_simulacion("error", str(exc) or "No se pudo crear el parlay")
    texto = "Parlay personal agregado a la simulación"
    if avisos:
        texto += ". Advertencia: " + "; ".join(avisos)
    return _redireccion_simulacion("mensaje", texto)
