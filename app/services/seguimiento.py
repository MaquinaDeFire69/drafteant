"""Selecciones simuladas y su rendimiento una vez que termina el partido."""

from datetime import datetime, timezone

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session, aliased

from app.ligas import nombre_liga
from app.models import Cuota, Equipo, Partido, Pronostico, SeleccionSeguimiento


UNIDAD = 100.0


def _utc(valor: datetime) -> datetime:
    return valor.replace(tzinfo=timezone.utc) if valor.tzinfo is None else valor.astimezone(timezone.utc)


def crear_selecciones(db: Session, partido_ids: list[int] | None = None) -> int:
    """Fija una selección por pronóstico usando la primera captura válida de cuotas."""
    consulta = (
        select(Partido, Pronostico)
        .join(Pronostico, Pronostico.partido_id == Partido.id)
        .where(
            Partido.inicio_utc.is_not(None),
            Pronostico.publicado_en.is_not(None),
        )
    )
    if partido_ids is not None:
        if not partido_ids:
            return 0
        consulta = consulta.where(Partido.id.in_(partido_ids))

    creadas = 0
    for partido, pronostico in db.execute(consulta).all():
        if _utc(pronostico.publicado_en) >= _utc(partido.inicio_utc):
            continue
        existe = db.scalar(select(SeleccionSeguimiento.id).where(
            SeleccionSeguimiento.pronostico_id == pronostico.id,
        ))
        if existe is not None:
            continue
        lado, probabilidad = max(
            (("local", pronostico.prob_local), ("visitante", pronostico.prob_visitante)),
            key=lambda item: item[1],
        )
        cuotas = list(db.scalars(
            select(Cuota)
            .where(
                Cuota.partido_id == partido.id,
                Cuota.pronostico_id == pronostico.id,
            )
            .order_by(Cuota.capturada_en, Cuota.id)
        ))
        cuotas = [c for c in cuotas if _utc(c.capturada_en) < _utc(partido.inicio_utc)]
        if not cuotas:
            continue
        primera_captura = cuotas[0].capturada_en
        candidatas = [c for c in cuotas if c.capturada_en == primera_captura]
        campo = "cuota_local" if lado == "local" else "cuota_visitante"
        cuota = max(candidatas, key=lambda c: getattr(c, campo))
        db.add(SeleccionSeguimiento(
            partido_id=partido.id, pronostico_id=pronostico.id, cuota_id=cuota.id,
            lado=lado, probabilidad=probabilidad, cuota_decimal=getattr(cuota, campo),
            casa=cuota.casa, seleccionada_en=primera_captura,
        ))
        creadas += 1
    return creadas


def casas_disponibles(db: Session) -> list[str]:
    """Casas presentes en las selecciones ya fijadas."""
    if not inspect(db.get_bind()).has_table("selecciones_seguimiento"):
        return []
    return list(db.scalars(
        select(SeleccionSeguimiento.casa).distinct().order_by(SeleccionSeguimiento.casa)
    ))


def rendimiento_selecciones(
    db: Session,
    liga: str | None = None,
    casa: str | None = None,
    min_probabilidad: float = 0.0,
    min_valor: float = -1.0,
    limite: int = 50,
) -> dict:
    """Devuelve las selecciones fijadas y sus resultados simulados a una unidad de 100."""
    vacio = {"total": 0, "evaluadas": 0, "pendientes": 0, "aciertos": 0,
             "inversion": 0.0, "retorno": 0.0, "ganancia": 0.0, "roi": None,
             "filas": [], "unidad": UNIDAD}
    if not inspect(db.get_bind()).has_table("selecciones_seguimiento"):
        return vacio
    local, visita = aliased(Equipo), aliased(Equipo)
    consulta = (
        select(SeleccionSeguimiento, Partido, local.nombre, visita.nombre)
        .join(Partido, Partido.id == SeleccionSeguimiento.partido_id)
        .join(local, local.id == Partido.local_id)
        .join(visita, visita.id == Partido.visitante_id)
    )
    if liga:
        consulta = consulta.where(Partido.liga == liga)
    if casa:
        consulta = consulta.where(SeleccionSeguimiento.casa == casa)
    filas = db.execute(
        consulta.order_by(SeleccionSeguimiento.seleccionada_en.desc(), SeleccionSeguimiento.id.desc())
    ).all()
    salida = []
    evaluadas = aciertos = 0
    retorno = 0.0
    for seleccion, partido, nombre_local, nombre_visita in filas:
        valor_esperado = seleccion.probabilidad * seleccion.cuota_decimal - 1
        if seleccion.probabilidad < min_probabilidad or valor_esperado < min_valor:
            continue
        terminada = partido.goles_local is not None and partido.goles_visitante is not None
        ganada = None
        if terminada:
            resultado = "local" if partido.goles_local > partido.goles_visitante else (
                "visitante" if partido.goles_visitante > partido.goles_local else "empate"
            )
            ganada = seleccion.lado == resultado
            evaluadas += 1
            aciertos += int(ganada)
            retorno += UNIDAD * seleccion.cuota_decimal if ganada else 0.0
        salida.append({
            "id": seleccion.id, "partido_id": partido.id, "local": nombre_local,
            "visitante": nombre_visita, "liga": nombre_liga(partido.liga),
            "lado": seleccion.lado, "seleccion": nombre_local if seleccion.lado == "local" else nombre_visita,
            "probabilidad": seleccion.probabilidad, "cuota": seleccion.cuota_decimal,
            "casa": seleccion.casa, "seleccionada_en": seleccion.seleccionada_en,
            "valor_esperado": valor_esperado,
            "terminada": terminada, "ganada": ganada,
            "marcador": f"{partido.goles_local}-{partido.goles_visitante}" if terminada else None,
            "ganancia": (UNIDAD * (seleccion.cuota_decimal - 1) if ganada else -UNIDAD) if terminada else None,
        })
    inversion = evaluadas * UNIDAD
    return {
        "total": len(salida), "evaluadas": evaluadas, "pendientes": len(salida) - evaluadas,
        "aciertos": aciertos, "inversion": inversion, "retorno": retorno,
        "ganancia": retorno - inversion, "roi": (retorno - inversion) / inversion if inversion else None,
        "filas": salida[:limite], "unidad": UNIDAD,
    }
