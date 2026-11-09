import io
import sys
import time
from datetime import date

import httpx
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.config import settings
from app.ligas import LIGAS, temporada_actual
from app.models import Equipo, Partido
from app.services.escudos import sincronizar_todos

URL = "https://www.football-data.co.uk/mmz4281/{codigo}/{liga}.csv"
URL_MUNDIAL = "https://www.football-data.co.uk/new/{liga}.csv"
API_COMPETICION = "https://api.football-data.org/v4/competitions/{competicion}/matches"
COLUMNAS = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]
ANIO_INICIO = 2018


def codigo_temporada(anio: int) -> str:
    """2024 -> '2425'"""
    return f"{anio % 100:02d}{(anio + 1) % 100:02d}"


def _limpiar(df: pd.DataFrame, etiqueta: str) -> pd.DataFrame | None:
    # Los archivos mundiales usan Home/Away/HG/AG; los europeos, HomeTeam/AwayTeam/FTHG/FTAG.
    df = df.rename(columns={"Home": "HomeTeam", "Away": "AwayTeam", "HG": "FTHG", "AG": "FTAG"})
    if not all(c in df.columns for c in COLUMNAS):
        print(f"  [omitida] {etiqueta}: faltan columnas")
        return None
    df = df[COLUMNAS + (["Season"] if "Season" in df.columns else [])].dropna(subset=COLUMNAS)
    if df.empty:
        print(f"  [omitida] {etiqueta}: sin partidos jugados")
        return None
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, format="mixed").dt.date
    df["FTHG"] = df["FTHG"].astype(int)
    df["FTAG"] = df["FTAG"].astype(int)
    return df


def descargar(liga: str, anio: int | None = None) -> pd.DataFrame | None:
    datos_liga = LIGAS[liga]
    if datos_liga["historico"] == "mundial":
        url = URL_MUNDIAL.format(liga=datos_liga["csv"])
        etiqueta = liga
    else:
        if anio is None:
            raise ValueError("Falta año para esta fuente histórica")
        url = URL.format(codigo=codigo_temporada(anio), liga=datos_liga.get("csv", liga))
        etiqueta = f"{liga} {anio}"
    try:
        r = httpx.get(url, timeout=30, follow_redirects=True)
    except httpx.HTTPError as e:
        print(f"  [error de red] {etiqueta}: {e}")
        return None
    time.sleep(0.3)  # cortesía con el servidor

    if r.status_code != 200 or len(r.content) < 100:
        print(f"  [omitida] {etiqueta}: no disponible")
        return None

    df = pd.read_csv(io.BytesIO(r.content), encoding="latin-1")
    return _limpiar(df, etiqueta)


def descargar_api(liga: str, anio: int) -> pd.DataFrame | None:
    """Resultados históricos de una competición que football-data.org autorice."""
    codigo = LIGAS[liga].get("api")
    if not codigo or not settings.football_data_api_key:
        print(f"  [omitida] {liga} {anio}: falta acceso a football-data.org")
        return None
    try:
        respuesta = httpx.get(API_COMPETICION.format(competicion=codigo),
                              headers={"X-Auth-Token": settings.football_data_api_key},
                              params={"season": anio, "status": "FINISHED"}, timeout=30)
    except httpx.HTTPError as error:
        print(f"  [error de red] {liga} {anio}: {error}")
        return None
    if respuesta.status_code in (401, 403):
        print(f"  [omitida] {liga} {anio}: tu plan de football-data.org no autoriza esta competición")
        return None
    if respuesta.status_code != 200:
        print(f"  [omitida] {liga} {anio}: football-data.org respondió HTTP {respuesta.status_code}")
        return None
    filas = []
    for partido in respuesta.json().get("matches", []):
        marcador = partido.get("score", {}).get("fullTime", {})
        if marcador.get("home") is None or marcador.get("away") is None:
            continue
        filas.append({"Date": partido["utcDate"], "HomeTeam": partido["homeTeam"]["name"],
                      "AwayTeam": partido["awayTeam"]["name"], "FTHG": marcador["home"],
                      "FTAG": marcador["away"], "Season": f"{anio}-{str(anio + 1)[-2:]}"})
    if not filas:
        print(f"  [omitida] {liga} {anio}: sin partidos finalizados")
        return None
    df = pd.DataFrame(filas)
    df["Date"] = pd.to_datetime(df["Date"], utc=True).dt.date
    return df


def importar(liga: str, anio_inicio: int, anio_fin: int) -> None:
    with SessionLocal() as db:
        fuente = LIGAS[liga]["historico"]
        periodos = [None] if fuente == "mundial" else range(anio_inicio, anio_fin + 1)
        for anio in periodos:
            df = descargar_api(liga, anio) if fuente == "api" else descargar(liga, anio)
            if df is None:
                continue

            # 1) Equipos nuevos
            nombres = set(df["HomeTeam"]) | set(df["AwayTeam"])
            existentes = {e.nombre for e in db.scalars(select(Equipo))}
            for nombre in nombres - existentes:
                db.add(Equipo(nombre=nombre))
            db.flush()
            ids = {e.nombre: e.id for e in db.scalars(select(Equipo))}

            # 2) Partidos: inserta o actualiza el marcador si ya existían
            filas = [
                {
                    "fecha": r.Date,
                    "liga": liga, "temporada": str(getattr(r, "Season", "")).replace("/", "-")
                    or f"{r.Date.year}-{str(r.Date.year + 1)[-2:]}",
                    "local_id": ids[r.HomeTeam],
                    "visitante_id": ids[r.AwayTeam],
                    "goles_local": r.FTHG,
                    "goles_visitante": r.FTAG,
                }
                for r in df.itertuples()
            ]
            stmt = insert(Partido).values(filas)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_partido",
                set_={
                    "goles_local": stmt.excluded.goles_local,
                    "goles_visitante": stmt.excluded.goles_visitante,
                    "temporada": stmt.excluded.temporada,
                    "estado": "FINISHED",
                },
            )
            db.execute(stmt)
            db.commit()
            print(f"  {liga} {anio or 'histórico mundial'}: {len(filas)} partidos procesados")

    sincronizar_todos([liga])


if __name__ == "__main__":
    # Sin argumentos: todas las ligas.  Con argumentos: solo esas (ej. N1 P1)
    codigos = [a.upper() for a in sys.argv[1:]] or list(LIGAS)
    for liga in codigos:
        if liga not in LIGAS:
            print(f"Liga desconocida: {liga}. Opciones: {', '.join(LIGAS)}")
            continue
        print(f"Importando {LIGAS[liga]['nombre']} ({liga})...")
        inicio = LIGAS[liga].get("inicio_historico", ANIO_INICIO)
        importar(liga, inicio, temporada_actual(date.today()))
