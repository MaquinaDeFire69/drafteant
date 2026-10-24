import difflib
from datetime import date, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.database import SessionLocal
from app.models import Equipo, Partido

API = "https://api.football-data.org/v4/competitions/{comp}/matches"

# Código de nuestra liga -> código en football-data.org
COMPETICIONES = {"E0": "PL", "SP1": "PD", "I1": "SA", "D1": "BL1", "F1": "FL1"}

# Nombre de la API -> nombre usado en los CSV (agrega los que te falten)
ALIAS = {
    "Manchester City": "Man City",
    "Manchester United": "Man United",
    "Newcastle United": "Newcastle",
    "Tottenham Hotspur": "Tottenham",
    "Wolverhampton Wanderers": "Wolves",
    "Nottingham Forest": "Nott'm Forest",
    "West Ham United": "West Ham",
    "Brighton & Hove Albion": "Brighton",
    "Leeds United": "Leeds",
    "Leicester City": "Leicester",
    "Sheffield United": "Sheffield United",
    "Luton Town": "Luton",
    "Ipswich Town": "Ipswich",
    "Coventry City FC": "Coventry",
    "Hull City AFC": "Hull"
}


def _limpiar(nombre: str) -> str:
    for sufijo in (" FC", " AFC"):
        if nombre.endswith(sufijo):
            nombre = nombre[: -len(sufijo)]
    return nombre.strip()


def emparejar(equipo_api: dict, conocidos: dict[str, int]) -> int | None:
    """Devuelve el id de nuestro equipo o None si no hay coincidencia confiable."""
    candidatos = [equipo_api.get("shortName"), equipo_api.get("name")]
    candidatos = [c for c in candidatos if c]
    candidatos += [_limpiar(c) for c in candidatos]
    for c in candidatos:
        c = ALIAS.get(c, c)
        if c in conocidos:
            return conocidos[c]
    for c in candidatos:
        cercano = difflib.get_close_matches(c, conocidos.keys(), n=1, cutoff=0.8)
        if cercano:
            return conocidos[cercano[0]]
    return None


def temporada_actual(hoy: date) -> int:
    return hoy.year if hoy.month >= 7 else hoy.year - 1


def sincronizar(liga: str = "E0", dias: int = 14) -> None:
    if not settings.football_data_api_key:
        raise RuntimeError("Falta FOOTBALL_DATA_API_KEY en el archivo .env")

    hoy = date.today()
    r = httpx.get(
        API.format(comp=COMPETICIONES[liga]),
        headers={"X-Auth-Token": settings.football_data_api_key},
        params={
            "status": "SCHEDULED,TIMED",
            "dateFrom": hoy.isoformat(),
            "dateTo": (hoy + timedelta(days=dias)).isoformat(),
        },
        timeout=30,
    )
    r.raise_for_status()
    partidos_api = r.json().get("matches", [])

    anio = temporada_actual(hoy)
    temporada = f"{anio}-{str(anio + 1)[-2:]}"

    with SessionLocal() as db:
        conocidos = {e.nombre: e.id for e in db.scalars(select(Equipo))}
        filas, sin_pareja = [], set()

        for m in partidos_api:
            local = emparejar(m["homeTeam"], conocidos)
            visita = emparejar(m["awayTeam"], conocidos)
            if local is None or visita is None:
                if local is None:
                    sin_pareja.add(m["homeTeam"].get("name"))
                if visita is None:
                    sin_pareja.add(m["awayTeam"].get("name"))
                continue
            filas.append({
                "fecha": date.fromisoformat(m["utcDate"][:10]),
                "liga": liga, "temporada": temporada,
                "local_id": local, "visitante_id": visita,
                "goles_local": None, "goles_visitante": None,
            })

        if filas:
            db.execute(insert(Partido).values(filas).on_conflict_do_nothing(constraint="uq_partido"))
            db.commit()

        print(f"{liga}: {len(filas)} partidos próximos guardados de {len(partidos_api)} recibidos")
        if sin_pareja:
            print("Sin coincidencia (agrégalos a ALIAS):", sorted(sin_pareja))


if __name__ == "__main__":
    sincronizar("E0")