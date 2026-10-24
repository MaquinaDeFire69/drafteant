import io

import httpx
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.models import Equipo, Partido

URL = "https://www.football-data.co.uk/mmz4281/{codigo}/{liga}.csv"
COLUMNAS = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]


def codigo_temporada(anio: int) -> str:
    """2024 -> '2425'"""
    return f"{anio % 100:02d}{(anio + 1) % 100:02d}"


def descargar(liga: str, anio: int) -> pd.DataFrame | None:
    url = URL.format(codigo=codigo_temporada(anio), liga=liga)
    try:
        r = httpx.get(url, timeout=30, follow_redirects=True)
    except httpx.HTTPError as e:
        print(f"  [error de red] {liga} {anio}: {e}")
        return None

    if r.status_code != 200 or len(r.content) < 100:
        print(f"  [omitida] {liga} {anio}: no disponible")
        return None

    df = pd.read_csv(io.BytesIO(r.content), encoding="latin-1")
    if not all(c in df.columns for c in COLUMNAS):
        print(f"  [omitida] {liga} {anio}: faltan columnas")
        return None

    df = df[COLUMNAS].dropna()
    if df.empty:
        print(f"  [omitida] {liga} {anio}: sin partidos jugados")
        return None

    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, format="mixed").dt.date
    df["FTHG"] = df["FTHG"].astype(int)
    df["FTAG"] = df["FTAG"].astype(int)
    return df


def importar(liga: str, anio_inicio: int, anio_fin: int) -> None:
    with SessionLocal() as db:
        for anio in range(anio_inicio, anio_fin + 1):
            df = descargar(liga, anio)
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
            temporada = f"{anio}-{str(anio + 1)[-2:]}"
            filas = [
                {
                    "fecha": r.Date,
                    "liga": liga,
                    "temporada": temporada,
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
                },
            )
            db.execute(stmt)
            db.commit()
            print(f"  {liga} {temporada}: {len(filas)} partidos procesados")


if __name__ == "__main__":
    # Códigos de liga: E0 Premier League, SP1 La Liga, I1 Serie A,
    # D1 Bundesliga, F1 Ligue 1
    for liga in ["E0"]:
        print(f"Importando {liga}...")
        importar(liga, 2018, 2026)