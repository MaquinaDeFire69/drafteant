import difflib
import re
import sys
import time
import unicodedata
from datetime import date, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.database import SessionLocal
from app.ligas import LIGAS, temporada_actual
from app.models import Equipo, Partido

API = "https://api.football-data.org/v4/competitions/{comp}/matches"
PAUSA = 7  # segundos entre ligas (el plan gratuito permite 10 consultas por minuto)

# Nombre que da la API -> nombre usado en los CSV.
# Es un punto de partida: el script avisa de los equipos sin coincidencia.
ALIAS = {
    # Inglaterra
    "Manchester City": "Man City", "Manchester United": "Man United",
    "Newcastle United": "Newcastle", "Tottenham Hotspur": "Tottenham",
    "Wolverhampton Wanderers": "Wolves", "Nottingham Forest": "Nott'm Forest",
    "West Ham United": "West Ham", "Brighton & Hove Albion": "Brighton",
    "Leeds United": "Leeds", "Leicester City": "Leicester",
    "Ipswich Town": "Ipswich", "Luton Town": "Luton",
    # España
    "Athletic Club": "Ath Bilbao", "Athletic": "Ath Bilbao",
    "Club Atlético de Madrid": "Ath Madrid", "Atlético Madrid": "Ath Madrid",
    "Atleti": "Ath Madrid", "Real Betis Balompié": "Betis", "Real Betis": "Betis",
    "RC Celta de Vigo": "Celta", "Celta Vigo": "Celta",
    "RCD Espanyol de Barcelona": "Espanol", "Espanyol": "Espanol",
    "Real Sociedad de Fútbol": "Sociedad", "Real Sociedad": "Sociedad",
    "Rayo Vallecano de Madrid": "Vallecano", "Rayo Vallecano": "Vallecano",
    "Deportivo Alavés": "Alaves", "Real Valladolid CF": "Valladolid",
    "Real Valladolid": "Valladolid", "Real Oviedo": "Oviedo",
    "RC Deportivo La Coruña": "La Coruna",
    # Italia
    "AC Milan": "Milan", "FC Internazionale Milano": "Inter",
    "Hellas Verona FC": "Verona", "Hellas Verona": "Verona",
    # Alemania
    "FC Bayern München": "Bayern Munich", "Bayern": "Bayern Munich",
    "Borussia Dortmund": "Dortmund", "Bayer 04 Leverkusen": "Leverkusen",
    "Borussia Mönchengladbach": "M'gladbach", "Gladbach": "M'gladbach",
    "Eintracht Frankfurt": "Ein Frankfurt", "Hamburger SV": "Hamburg",
    # Francia
    "Paris Saint-Germain FC": "Paris SG", "Paris Saint-Germain": "Paris SG", "PSG": "Paris SG",
    "Olympique Lyonnais": "Lyon", "Olympique de Marseille": "Marseille",
    "LOSC Lille": "Lille", "Stade Rennais FC": "Rennes",
    "RC Strasbourg Alsace": "Strasbourg", "Stade Brestois 29": "Brest",
    "Stade de Reims": "Reims", "AS Saint-Étienne": "St Etienne",
    "Angers SCO": "Angers", "Montpellier HSC": "Montpellier",
    # Países Bajos
    "PSV": "PSV Eindhoven", "Feyenoord Rotterdam": "Feyenoord",
    "AZ": "AZ Alkmaar", "NEC": "Nijmegen", "Fortuna Sittard": "For Sittard",
    "Heracles Almelo": "Heracles", "PEC Zwolle": "Zwolle",
    "Excelsior Rotterdam": "Excelsior", "RKC Waalwijk": "Waalwijk",
    # Portugal
    "SL Benfica": "Benfica", "Sporting CP": "Sp Lisbon",
    "Sporting Clube de Portugal": "Sp Lisbon", "SC Braga": "Sp Braga",
    "Sporting Clube de Braga": "Sp Braga", "Vitória SC": "Guimaraes",
    "Vitória Guimarães": "Guimaraes", "GD Estoril Praia": "Estoril",
    "Estrela da Amadora": "Estrela", "AVS Futebol SAD": "AVS",
}

# Palabras que no ayudan a distinguir un club de otro
RUIDO = {
    "fc", "afc", "cf", "sc", "ac", "as", "ss", "rc", "sv", "vfl", "vfb", "tsg", "fsv",
    "rcd", "ud", "cd", "sd", "ca", "ogc", "aj", "sk", "bv", "fk", "ssc", "us", "sl",
    "gd", "bc", "cfc", "acf", "calcio", "de", "da", "club",
}


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    palabras = [w for w in t.split() if w not in RUIDO and not w.isdigit()]
    return " ".join(palabras)


ALIAS_NORM = {_norm(k): v for k, v in ALIAS.items()}


def emparejar(equipo_api: dict, conocidos: dict[str, int], por_norm: dict[str, str]) -> int | None:
    """Devuelve el id de nuestro equipo o None si no hay coincidencia confiable."""
    claves = [_norm(c) for c in (equipo_api.get("shortName"), equipo_api.get("name")) if c]
    claves = [k for k in claves if k]

    # 1) alias o coincidencia exacta
    for k in claves:
        alias = ALIAS_NORM.get(k)
        if alias in conocidos:
            return conocidos[alias]
        if k in por_norm:
            return conocidos[por_norm[k]]

    # 2) un nombre empieza por el otro ("coventry city" / "coventry"), solo si es único
    for k in claves:
        candidatos = {n for n in por_norm if k.startswith(n + " ") or n.startswith(k + " ")}
        if len(candidatos) == 1:
            return conocidos[por_norm[candidatos.pop()]]

    # 3) parecido aproximado
    for k in claves:
        cercano = difflib.get_close_matches(k, por_norm.keys(), n=1, cutoff=0.8)
        if cercano:
            return conocidos[por_norm[cercano[0]]]
    return None


def sincronizar(liga: str, dias: int = 14) -> None:
    if not settings.football_data_api_key:
        raise RuntimeError("Falta FOOTBALL_DATA_API_KEY en el archivo .env")

    hoy = date.today()
    r = httpx.get(
        API.format(comp=LIGAS[liga]["api"]),
        headers={"X-Auth-Token": settings.football_data_api_key},
        params={
            "status": "SCHEDULED,TIMED",
            "dateFrom": hoy.isoformat(),
            "dateTo": (hoy + timedelta(days=dias)).isoformat(),
        },
        timeout=30,
    )
    if r.status_code in (401, 403):
        print(f"  {liga}: la API rechazó la consulta ({r.status_code}). Revisa el token o el plan.")
        return
    if r.status_code == 429:
        print(f"  {liga}: límite de consultas por minuto alcanzado; se intentará en la próxima ejecución.")
        return
    r.raise_for_status()
    partidos_api = r.json().get("matches", [])

    anio = temporada_actual(hoy)
    temporada = f"{anio}-{str(anio + 1)[-2:]}"

    with SessionLocal() as db:
        # Solo equipos que ya jugaron en ESTA liga (evita coincidencias entre países)
        ids = set(db.scalars(select(Partido.local_id).where(Partido.liga == liga)))
        ids |= set(db.scalars(select(Partido.visitante_id).where(Partido.liga == liga)))
        if not ids:
            print(f"  {liga}: no hay histórico. Importa primero los resultados.")
            return
        conocidos = {e.nombre: e.id for e in db.scalars(select(Equipo).where(Equipo.id.in_(list(ids))))}
        por_norm = {_norm(n): n for n in conocidos}

        filas, sin_pareja = [], set()
        for m in partidos_api:
            local = emparejar(m["homeTeam"], conocidos, por_norm)
            visita = emparejar(m["awayTeam"], conocidos, por_norm)
            if local is None:
                sin_pareja.add(m["homeTeam"].get("name"))
            if visita is None:
                sin_pareja.add(m["awayTeam"].get("name"))
            if local is None or visita is None:
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

        print(f"  {liga}: {len(filas)} partidos próximos guardados de {len(partidos_api)} recibidos")
        if sin_pareja:
            print(f"  Sin coincidencia en {liga} (agrégalos a ALIAS):", sorted(sin_pareja))


def sincronizar_todas(ligas: list[str] | None = None, dias: int = 14) -> None:
    ligas = ligas or list(LIGAS)
    for i, liga in enumerate(ligas):
        try:
            sincronizar(liga, dias)
        except Exception as e:  # una liga fallida no debe detener las demás
            print(f"  [error] {liga}: {e}")
        if i < len(ligas) - 1:
            time.sleep(PAUSA)


if __name__ == "__main__":
    codigos = [a.upper() for a in sys.argv[1:]] or list(LIGAS)
    sincronizar_todas([c for c in codigos if c in LIGAS])