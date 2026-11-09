import difflib
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.database import SessionLocal
from app.ligas import LIGAS, temporada_actual
from app.models import Equipo, Partido

API = "https://api.football-data.org/v4/competitions/{comp}/matches"
API_CUOTAS = "https://api.the-odds-api.com/v4/sports/{sport}/odds"
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
    # México
    "Pumas": "UNAM Pumas", "América": "Club America", "Club América": "Club America",
    "Atlético San Luis": "Atl. San Luis", "FC Juárez": "Juarez", "Tigres": "Tigres UANL",
    "León": "Club Leon", "Guadalajara": "Guadalajara Chivas",
    # MLS
    "LA Galaxy": "Los Angeles Galaxy", "Atlanta United FC": "Atlanta Utd",
    "D.C. United": "DC United", "New York City FC": "New York City",
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
    if not LIGAS[liga].get("api"):
        print(f"  {liga}: el plan actual no ofrece calendario en football-data.org para esta liga. "
              "Importa su histórico y captura cuotas cuando esté disponible.")
        return

    hoy = date.today()
    r = httpx.get(
        API.format(comp=LIGAS[liga]["api"]),
        headers={"X-Auth-Token": settings.football_data_api_key},
        params={
            "status": "SCHEDULED,TIMED,POSTPONED,CANCELLED",
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
            for equipo_id, datos_equipo in (
                (local, m["homeTeam"]),
                (visita, m["awayTeam"]),
            ):
                escudo = datos_equipo.get("crest")
                if isinstance(escudo, str) and escudo.startswith("https://crests.football-data.org/"):
                    db.get(Equipo, equipo_id).escudo_url = escudo
            inicio_utc = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
            filas.append({
                "api_partido_id": m["id"],
                "fecha": inicio_utc.date(),
                "inicio_utc": inicio_utc,
                "estado": m["status"],
                "liga": liga, "temporada": temporada,
                "local_id": local, "visitante_id": visita,
            })

        actualizados = creados = 0
        for fila in filas:
            # El ID de la API persiste aunque el partido cambie de fecha u hora.
            partido = db.scalar(select(Partido).where(Partido.api_partido_id == fila["api_partido_id"]))
            if partido is None:
                # Asociar los partidos guardados antes de esta migración en la primera sincronización.
                partido = db.scalar(
                    select(Partido).where(
                        Partido.api_partido_id.is_(None),
                        Partido.liga == liga,
                        Partido.local_id == fila["local_id"],
                        Partido.visitante_id == fila["visitante_id"],
                        Partido.fecha == fila["fecha"],
                    )
                )
            if partido is None:
                db.add(Partido(goles_local=None, goles_visitante=None, **fila))
                creados += 1
                continue

            for campo, valor in fila.items():
                setattr(partido, campo, valor)
            actualizados += 1
        if filas:
            db.commit()

        print(
            f"  {liga}: {creados} creados y {actualizados} actualizados "
            f"de {len(partidos_api)} partidos recibidos"
        )
        if sin_pareja:
            print(f"  Sin coincidencia en {liga} (agrégalos a ALIAS):", sorted(sin_pareja))


def sincronizar_desde_cuotas(liga: str, dias: int = 14) -> None:
    """Crea/actualiza próximos partidos desde The Odds API para ligas sin calendario FD.

    Es explícito porque la consulta de cuotas consume créditos. Solo incorpora
    equipos que ya tienen historial en esa liga, para no crear predicciones sin base.
    """
    from app.services.cuotas import ODDS_DEPORTES

    liga = liga.upper()
    if liga not in ODDS_DEPORTES:
        raise RuntimeError(f"La liga {liga} no está configurada para The Odds API")
    if not settings.odds_api_key:
        raise RuntimeError("Falta ODDS_API_KEY en el archivo .env")
    ahora = datetime.now(timezone.utc)
    try:
        respuesta = httpx.get(
            API_CUOTAS.format(sport=ODDS_DEPORTES[liga]),
            params={"apiKey": settings.odds_api_key, "regions": "uk", "markets": "h2h",
                    "oddsFormat": "decimal"}, timeout=30,
        )
    except httpx.HTTPError as error:
        raise RuntimeError(f"No se pudo conectar con The Odds API: {error}") from None
    if respuesta.status_code != 200:
        raise RuntimeError(f"The Odds API respondió HTTP {respuesta.status_code}")

    fecha_limite = (ahora + timedelta(days=dias)).date()
    creados = actualizados = 0
    sin_pareja = set()
    with SessionLocal() as db:
        ids = set(db.scalars(select(Partido.local_id).where(Partido.liga == liga)))
        ids |= set(db.scalars(select(Partido.visitante_id).where(Partido.liga == liga)))
        conocidos = {e.nombre: e.id for e in db.scalars(select(Equipo).where(Equipo.id.in_(ids)))}
        por_norm = {_norm(nombre): nombre for nombre in conocidos}
        for evento in respuesta.json():
            try:
                inicio = datetime.fromisoformat(evento["commence_time"].replace("Z", "+00:00"))
                local = emparejar({"name": evento["home_team"], "shortName": evento["home_team"]}, conocidos, por_norm)
                visita = emparejar({"name": evento["away_team"], "shortName": evento["away_team"]}, conocidos, por_norm)
            except (KeyError, TypeError, ValueError):
                continue
            if inicio <= ahora or inicio.date() > fecha_limite:
                continue
            if local is None or visita is None:
                sin_pareja.add(f"{evento.get('home_team', '?')} vs {evento.get('away_team', '?')}")
                continue
            partido = db.scalar(select(Partido).where(
                Partido.liga == liga, Partido.local_id == local, Partido.visitante_id == visita,
                Partido.fecha == inicio.date(),
            ))
            if partido is None:
                db.add(Partido(fecha=inicio.date(), inicio_utc=inicio, estado="TIMED", liga=liga,
                               temporada=f"{inicio.year}-{str(inicio.year + 1)[-2:]}",
                               local_id=local, visitante_id=visita, goles_local=None, goles_visitante=None))
                creados += 1
            else:
                partido.inicio_utc, partido.estado = inicio, "TIMED"
                actualizados += 1
        db.commit()
    print(f"  {liga}: {creados} creados y {actualizados} actualizados desde cuotas. "
          f"Créditos: {respuesta.headers.get('x-requests-last', '?')}; "
          f"restantes: {respuesta.headers.get('x-requests-remaining', '?')}")
    if sin_pareja:
        print(f"  Sin coincidencia en {liga} (agrega alias):", sorted(sin_pareja))


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
    usar_cuotas = "--cuotas" in sys.argv[1:]
    codigos = [a.upper() for a in sys.argv[1:] if a != "--cuotas"] or list(LIGAS)
    codigos = [c for c in codigos if c in LIGAS]
    if usar_cuotas:
        for codigo in codigos:
            sincronizar_desde_cuotas(codigo)
    else:
        sincronizar_todas(codigos)
