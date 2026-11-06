"""Captura manual de cuotas 1X2 para las ligas configuradas."""

import math
import sys
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import inspect, select
from sqlalchemy.orm import aliased

from app.config import settings
from app.database import SessionLocal
from app.ligas import nombre_liga
from app.models import Cuota, Equipo, Partido, Pronostico
from app.services.fixtures import ALIAS_NORM, _norm
from app.services.seguimiento import crear_selecciones


API = "https://api.the-odds-api.com/v4/sports/{sport}/odds"
ODDS_DEPORTES = {
    "E0": "soccer_epl",
    "SP1": "soccer_spain_la_liga",
    "I1": "soccer_italy_serie_a",
    "D1": "soccer_germany_bundesliga",
    "F1": "soccer_france_ligue_one",
    "N1": "soccer_netherlands_eredivisie",
    "P1": "soccer_portugal_primeira_liga",
    "MX1": "soccer_mexico_ligamx",
    "MLS": "soccer_usa_mls",
    "CL": "soccer_uefa_champs_league",
    "EL": "soccer_uefa_europa_league",
}
ALIAS_CUOTAS = {
    "brighton and hove albion": "Brighton",
    "coventry city": "Coventry",
    "hull city": "Hull",
    "inter milan": "Inter",
    "sporting lisbon": "Sp Lisbon",
    "wolverhampton": "Wolves",
}


def _fecha(valor: str) -> datetime:
    return datetime.fromisoformat(valor.replace("Z", "+00:00"))


def _utc(valor: datetime) -> datetime:
    return valor.replace(tzinfo=timezone.utc) if valor.tzinfo is None else valor.astimezone(timezone.utc)


def _equipo(nombre: str, conocidos: dict[str, int]) -> int | None:
    normalizado = _norm(nombre)
    alias = ALIAS_CUOTAS.get(normalizado) or ALIAS_NORM.get(normalizado)
    if alias:
        normalizado = _norm(alias)
    return conocidos.get(normalizado)


def capturar(liga: str) -> dict:
    """Una llamada para una liga; persiste cada casa/partido solo si el cruce es inequívoco."""
    liga = liga.upper()
    if liga not in ODDS_DEPORTES:
        raise RuntimeError(f"La liga {liga} no está configurada para cuotas")
    if not settings.odds_api_key:
        raise RuntimeError("Falta ODDS_API_KEY en .env")
    with SessionLocal() as db:
        if not inspect(db.get_bind()).has_table("cuotas"):
            raise RuntimeError("Falta aplicar la migración de cuotas (alembic upgrade head)")
        if db.scalar(select(Partido.id).where(
            Partido.liga == liga, Partido.inicio_utc > datetime.now(timezone.utc),
            Partido.estado.in_(("SCHEDULED", "TIMED")),
        ).limit(1)) is None:
            raise RuntimeError(f"No hay partidos futuros de {nombre_liga(liga)} en la base de datos")

    try:
        respuesta = httpx.get(API.format(sport=ODDS_DEPORTES[liga]), params={
            "apiKey": settings.odds_api_key,
            "regions": "uk",
            "markets": "h2h",
            "oddsFormat": "decimal",
        }, timeout=30)
    except httpx.RequestError:
        raise RuntimeError("No se pudo conectar con The Odds API") from None
    if respuesta.status_code != 200:
        raise RuntimeError(f"The Odds API respondió HTTP {respuesta.status_code}; revisa la clave, el plan o el límite")

    eventos = respuesta.json()
    if not isinstance(eventos, list):
        raise RuntimeError("The Odds API devolvió un formato inesperado")
    captura = datetime.now(timezone.utc)
    resumen = {
        "eventos": len(eventos), "cruzados": 0, "sin_cruce": [], "cuotas_nuevas": 0,
        "creditos_usados": respuesta.headers.get("x-requests-last", "?"),
        "creditos_restantes": respuesta.headers.get("x-requests-remaining", "?"),
    }

    with SessionLocal() as db:
        local, visita = aliased(Equipo), aliased(Equipo)
        partidos = db.execute(
            select(Partido, local.nombre, visita.nombre)
            .join(local, local.id == Partido.local_id)
            .join(visita, visita.id == Partido.visitante_id)
            .where(
                Partido.liga == liga, Partido.inicio_utc > captura,
                Partido.estado.in_(("SCHEDULED", "TIMED")),
            )
        ).all()
        conocidos = {}
        for partido, nombre_local, nombre_visita in partidos:
            conocidos[_norm(nombre_local)] = partido.local_id
            conocidos[_norm(nombre_visita)] = partido.visitante_id

        for evento in eventos:
            try:
                inicio = _fecha(evento["commence_time"])
                id_local = _equipo(evento["home_team"], conocidos)
                id_visita = _equipo(evento["away_team"], conocidos)
                candidatos = [p for p, _, _ in partidos if p.local_id == id_local
                              and p.visitante_id == id_visita
                              and abs(_utc(p.inicio_utc) - inicio) <= timedelta(hours=3)]
            except (KeyError, TypeError, ValueError):
                candidatos = []
            if len(candidatos) != 1 or inicio <= captura:
                resumen["sin_cruce"].append(
                    f"{evento.get('home_team', '?')} vs {evento.get('away_team', '?')}"
                )
                continue

            partido = candidatos[0]
            resumen["cruzados"] += 1
            pronosticos = db.scalars(
                select(Pronostico)
                .where(Pronostico.partido_id == partido.id,
                       Pronostico.publicado_en.is_not(None))
                .order_by(Pronostico.publicado_en.desc(), Pronostico.id.desc())
            ).all()
            pronostico = next(
                (pr for pr in pronosticos if _utc(pr.publicado_en) <= captura
                 and _utc(pr.publicado_en) < _utc(partido.inicio_utc)),
                None,
            )

            for casa in evento.get("bookmakers", []):
                for mercado in casa.get("markets", []):
                    if mercado.get("key") != "h2h":
                        continue
                    try:
                        actualizada = _fecha(mercado["last_update"])
                        precios = {o["name"]: float(o["price"]) for o in mercado["outcomes"]}
                        cuotas = (precios[evento["home_team"]], precios["Draw"],
                                  precios[evento["away_team"]])
                        if (actualizada > captura or actualizada >= inicio or
                                any(not math.isfinite(c) or c <= 1 for c in cuotas)):
                            continue
                        casa_id = str(casa["key"])
                        evento_id = str(evento["id"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    existe = db.scalar(select(Cuota.id).where(
                        Cuota.evento_api_id == evento_id, Cuota.casa == casa_id,
                        Cuota.actualizada_en == actualizada,
                    ))
                    if existe is not None:
                        continue
                    db.add(Cuota(
                        partido_id=partido.id,
                        pronostico_id=pronostico.id if pronostico else None,
                        evento_api_id=evento_id, casa=casa_id,
                        cuota_local=cuotas[0], cuota_empate=cuotas[1], cuota_visitante=cuotas[2],
                        actualizada_en=actualizada, capturada_en=captura,
                    ))
                    resumen["cuotas_nuevas"] += 1
        db.flush()
        resumen["selecciones_nuevas"] = crear_selecciones(db)
        db.commit()
    return resumen


def capturar_premier() -> dict:
    """Compatibilidad con el primer comando de captura de Premier League."""
    return capturar("E0")


def capturar_todas(ligas: list[str] | None = None) -> dict[str, dict]:
    """Captura cuotas de las ligas indicadas; una falla no detiene las demás."""
    resultados = {}
    for liga in (ligas or list(ODDS_DEPORTES)):
        liga = liga.upper()
        try:
            resultados[liga] = capturar(liga)
        except RuntimeError as error:
            resultados[liga] = {"error": str(error)}
    return resultados


if __name__ == "__main__":
    argumentos = [a.upper() for a in sys.argv[1:]]
    codigos = list(ODDS_DEPORTES) if argumentos == ["TODAS"] else (argumentos or ["E0"])
    resultados = capturar_todas(codigos)
    hubo_error = False
    for liga, resultado in resultados.items():
        if "error" in resultado:
            print(f"{nombre_liga(liga)}: {resultado['error']}", file=sys.stderr)
            hubo_error = True
            continue
        print(
            f"{nombre_liga(liga)}: {resultado['eventos']} eventos, {resultado['cruzados']} cruzados, "
            f"{resultado['cuotas_nuevas']} cuotas y {resultado['selecciones_nuevas']} selecciones nuevas. "
            f"Créditos: {resultado['creditos_usados']}; restantes: {resultado['creditos_restantes']}"
        )
        if resultado["sin_cruce"]:
            print("  Sin cruce confiable:", ", ".join(resultado["sin_cruce"]))
    if hubo_error:
        sys.exit(1)
