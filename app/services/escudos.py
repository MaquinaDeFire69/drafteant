import sys
import time
from datetime import date
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.ligas import LIGAS, temporada_actual
from app.models import Equipo, Partido
from app.services.fixtures import PAUSA, _norm, emparejar

API_EQUIPOS = "https://api.football-data.org/v4/competitions/{comp}/teams"
ORIGEN_ESCUDOS = "https://crests.football-data.org/"
API_THESPORTSDB = "https://www.thesportsdb.com/api/v1/json/{key}/search_all_teams.php"
LIGAS_THESPORTSDB = {
    "E0": ("English Premier League",),
    "SP1": ("Spanish La Liga",),
    "I1": ("Italian Serie A",),
    "D1": ("German Bundesliga",),
    "F1": ("French Ligue 1",),
    "N1": ("Dutch Eredivisie",),
    "P1": ("Portuguese Primeira Liga",),
    "MX1": ("Mexican Primera League",),
    "MLS": ("American Major League Soccer",),
    "CL": (
        "English Premier League", "Spanish La Liga", "Italian Serie A",
        "German Bundesliga", "French Ligue 1", "Dutch Eredivisie", "Portuguese Primeira Liga",
    ),
    "EL": (
        "English Premier League", "Spanish La Liga", "Italian Serie A",
        "German Bundesliga", "French Ligue 1", "Dutch Eredivisie", "Portuguese Primeira Liga",
    ),
}
PAUSA_THESPORTSDB = 2.1


def sincronizar_escudos(liga: str, anio: int | None = None) -> int:
    liga = liga.upper()
    if liga not in LIGAS:
        raise ValueError(f"Liga desconocida: {liga}")
    if not LIGAS[liga].get("api"):
        print(f"  {liga}: football-data.org no ofrece esta competición; se omiten los escudos.")
        return 0
    if not settings.football_data_api_key:
        raise RuntimeError("Falta FOOTBALL_DATA_API_KEY en el archivo .env")

    with SessionLocal() as db:
        ids = set(db.scalars(select(Partido.local_id).where(Partido.liga == liga)))
        ids |= set(db.scalars(select(Partido.visitante_id).where(Partido.liga == liga)))
        conocidos = {
            equipo.nombre: equipo.id
            for equipo in db.scalars(select(Equipo).where(Equipo.id.in_(ids)))
        } if ids else {}

    if not conocidos:
        print(f"  {liga}: no hay equipos con historial para asociar escudos.")
        return 0

    temporada = anio if anio is not None else temporada_actual(date.today())
    try:
        respuesta = httpx.get(
            API_EQUIPOS.format(comp=LIGAS[liga]["api"]),
            headers={"X-Auth-Token": settings.football_data_api_key},
            params={"season": temporada},
            timeout=30,
        )
    except httpx.HTTPError as error:
        raise RuntimeError(f"No se pudo consultar football-data.org para {liga}: {error}") from error
    if respuesta.status_code in (401, 403):
        raise RuntimeError(
            f"football-data.org rechazó la consulta de equipos para {liga} "
            f"({respuesta.status_code}); revisa el token o el plan."
        )
    respuesta.raise_for_status()

    payload = respuesta.json()
    equipos_api = payload.get("teams") if isinstance(payload, dict) else None
    if not isinstance(equipos_api, list):
        raise RuntimeError(f"football-data.org devolvió una lista de equipos inválida para {liga}.")

    por_norm = {_norm(nombre): nombre for nombre in conocidos}
    actualizados = 0
    sin_pareja = set()
    with SessionLocal() as db:
        for datos in equipos_api:
            if not isinstance(datos, dict):
                continue
            escudo = datos.get("crest")
            if not isinstance(escudo, str) or not escudo.startswith(ORIGEN_ESCUDOS):
                continue
            equipo_id = emparejar(datos, conocidos, por_norm)
            if equipo_id is None:
                sin_pareja.add(datos.get("name", "equipo sin nombre"))
                continue
            equipo = db.get(Equipo, equipo_id)
            if equipo.escudo_url != escudo:
                equipo.escudo_url = escudo
                actualizados += 1
        if actualizados:
            db.commit()

    print(f"  {liga}: {actualizados} escudos actualizados de {len(equipos_api)} equipos recibidos.")
    if sin_pareja:
        print(f"  Sin coincidencia en {liga} (revisa ALIAS en fixtures.py):", sorted(sin_pareja))
    return actualizados


def sincronizar_escudos_secundario(liga: str) -> int:
    """Completa escudos faltantes usando TheSportsDB y equipos por liga."""
    liga = liga.upper()
    if liga not in LIGAS:
        raise ValueError(f"Liga desconocida: {liga}")
    if not settings.thesportsdb_api_key:
        raise RuntimeError("Falta THESPORTSDB_API_KEY en el archivo .env")

    with SessionLocal() as db:
        ids = set(db.scalars(select(Partido.local_id).where(Partido.liga == liga)))
        ids |= set(db.scalars(select(Partido.visitante_id).where(Partido.liga == liga)))
        conocidos = {
            equipo.nombre: equipo.id
            for equipo in db.scalars(select(Equipo).where(Equipo.id.in_(ids)))
        } if ids else {}
        faltantes = {
            equipo.nombre: equipo.id
            for equipo in db.scalars(select(Equipo).where(
                Equipo.id.in_(list(ids)), Equipo.escudo_url.is_(None)
            ))
        } if ids else {}

    if not faltantes:
        print(f"  {liga}: todos los equipos con historial ya tienen escudo.")
        return 0

    por_norm = {_norm(nombre): nombre for nombre in conocidos}
    por_norm_faltantes = {_norm(nombre): nombre for nombre in faltantes}
    actualizados = 0
    sin_pareja = set()
    ligas_api = LIGAS_THESPORTSDB[liga]
    with SessionLocal() as db:
        for indice, nombre_liga in enumerate(ligas_api):
            if indice:
                time.sleep(PAUSA_THESPORTSDB)
            try:
                respuesta = httpx.get(
                    API_THESPORTSDB.format(key=settings.thesportsdb_api_key),
                    params={"l": nombre_liga},
                    timeout=30,
                )
            except httpx.HTTPError as error:
                raise RuntimeError(
                    f"No se pudo consultar TheSportsDB para {liga} ({nombre_liga}): {error}"
                ) from error
            if respuesta.status_code == 429:
                raise RuntimeError("TheSportsDB alcanzó su límite de consultas; inténtalo más tarde.")
            respuesta.raise_for_status()

            payload = respuesta.json()
            equipos_api = payload.get("teams") if isinstance(payload, dict) else None
            if equipos_api is None:
                continue
            if not isinstance(equipos_api, list):
                raise RuntimeError(f"TheSportsDB devolvió una lista de equipos inválida para {nombre_liga}.")

            for datos in equipos_api:
                if not isinstance(datos, dict):
                    continue
                escudo = datos.get("strBadge")
                if not isinstance(escudo, str):
                    continue
                imagen = urlparse(escudo)
                if imagen.scheme != "https" or imagen.hostname not in {
                    "r2.thesportsdb.com", "www.thesportsdb.com",
                }:
                    continue

                nombres_api = [
                    datos.get("strTeam", ""),
                    datos.get("strTeamShort", ""),
                    *datos.get("strTeamAlternate", "").split(","),
                ]
                coincidencia = next(
                    (por_norm[_norm(nombre)] for nombre in nombres_api if _norm(nombre) in por_norm),
                    None,
                )
                if coincidencia is not None and coincidencia not in faltantes:
                    continue
                equipo_nombre = coincidencia
                if coincidencia is None:
                    equipo_id = emparejar(
                        {"name": datos.get("strTeam"), "shortName": datos.get("strTeamShort")},
                        faltantes,
                        por_norm_faltantes,
                    )
                    equipo_nombre = next(
                        (nombre for nombre in faltantes if faltantes[nombre] == equipo_id),
                        None,
                    )
                if equipo_nombre is None:
                    if datos.get("strTeam"):
                        sin_pareja.add(datos["strTeam"])
                    continue

                equipo = db.get(Equipo, faltantes[equipo_nombre])
                if equipo.escudo_url is None:
                    equipo.escudo_url = escudo
                    faltantes.pop(equipo_nombre)
                    actualizados += 1
            if not faltantes:
                break
        if actualizados:
            db.commit()

    print(f"  {liga}: TheSportsDB agregó {actualizados} escudos faltantes.")
    if faltantes:
        print(f"  Sin escudo en TheSportsDB para {liga}:", sorted(faltantes))
    if sin_pareja:
        print(f"  Sin coincidencia en {liga}:", sorted(sin_pareja))
    return actualizados


def sincronizar_todos(ligas: list[str] | None = None) -> None:
    ligas = ligas or list(LIGAS)
    for indice, liga in enumerate(ligas):
        try:
            sincronizar_escudos(liga)
        except Exception as error:
            print(f"  [error football-data.org] {liga}: {error}")
        try:
            sincronizar_escudos_secundario(liga)
        except Exception as error:
            print(f"  [error TheSportsDB] {liga}: {error}")
        if indice < len(ligas) - 1:
            time.sleep(PAUSA)


if __name__ == "__main__":
    codigos = [argumento.upper() for argumento in sys.argv[1:]]
    sincronizar_todos(codigos or None)
