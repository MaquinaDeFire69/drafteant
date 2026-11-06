"""Captura opcional de over/under 2.5 y ambos anotan por evento.

Ejemplo: python -m app.services.mercados E0 --limite 3
"""

import argparse
import math
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import Cuota, CuotaMercado, Partido
from app.services.cuotas import ODDS_DEPORTES, _fecha, _utc

API_EVENTO = "https://api.the-odds-api.com/v4/sports/{sport}/events/{evento}/odds"


def interpretar_mercado(mercado: dict, actualizada: datetime, captura: datetime, inicio: datetime):
    """Acepta únicamente líneas exactas de 2.5 y respuestas válidas de BTTS."""
    if actualizada > captura or actualizada >= inicio:
        return []
    key = mercado.get("key")
    if key not in {"totals", "alternate_totals", "btts"}:
        return []
    salida = []
    for item in mercado.get("outcomes", []):
        nombre = str(item.get("name", "")).lower()
        if key == "btts":
            if nombre not in {"yes", "no"}:
                continue
            tipo, opcion, linea = "btts", "si" if nombre == "yes" else "no", 0.0
        else:
            if nombre not in {"over", "under"} or item.get("point") != 2.5:
                continue
            tipo, opcion, linea = "total_25", "mas" if nombre == "over" else "menos", 2.5
        try:
            precio = float(item["price"])
        except (TypeError, ValueError, KeyError):
            continue
        if math.isfinite(precio) and precio > 1:
            salida.append((tipo, opcion, linea, precio))
    return salida


def capturar_mercados(liga: str, limite: int = 3) -> dict:
    liga = liga.upper()
    if liga not in ODDS_DEPORTES:
        raise ValueError(f"Liga no configurada: {liga}")
    if not 1 <= limite <= 20:
        raise ValueError("El límite debe estar entre 1 y 20 partidos")
    if not settings.odds_api_key:
        raise RuntimeError("Falta ODDS_API_KEY en .env")

    ahora = datetime.now(timezone.utc)
    with SessionLocal() as db:
        eventos = db.execute(
            select(Cuota.evento_api_id, Cuota.partido_id, Partido.inicio_utc)
            .join(Partido, Partido.id == Cuota.partido_id)
            .where(Partido.liga == liga, Partido.inicio_utc > ahora,
                   Partido.estado.in_(("SCHEDULED", "TIMED")))
            .distinct().order_by(Partido.inicio_utc)
        ).all()
        elegidos = []
        ids = set()
        for evento, partido_id, inicio in eventos:
            if partido_id not in ids:
                elegidos.append((evento, partido_id, inicio))
                ids.add(partido_id)
            if len(elegidos) == limite:
                break

    resumen = {"eventos": 0, "cuotas_nuevas": 0, "creditos_usados": 0,
               "creditos_restantes": None, "sin_mercados": []}
    with SessionLocal() as db:
        for evento_id, partido_id, inicio in elegidos:
            try:
                respuesta = httpx.get(
                    API_EVENTO.format(sport=ODDS_DEPORTES[liga], evento=evento_id),
                    params={"apiKey": settings.odds_api_key, "regions": "uk",
                            "markets": "totals,alternate_totals,btts", "oddsFormat": "decimal"},
                    timeout=30,
                )
            except httpx.RequestError as exc:
                raise RuntimeError(f"Fallo de red al consultar {evento_id}: {exc}") from exc
            if respuesta.status_code != 200:
                raise RuntimeError(f"The Odds API respondió HTTP {respuesta.status_code} para {evento_id}")
            resumen["eventos"] += 1
            resumen["creditos_usados"] += int(respuesta.headers.get("x-requests-last", 0))
            resumen["creditos_restantes"] = respuesta.headers.get("x-requests-remaining")
            captura = datetime.now(timezone.utc)
            guardadas = 0
            vistos = set()
            for casa in respuesta.json().get("bookmakers", []):
                for mercado in casa.get("markets", []):
                    try:
                        actualizada = _fecha(mercado["last_update"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    for tipo, opcion, linea, precio in interpretar_mercado(
                        mercado, actualizada, captura, _utc(inicio)
                    ):
                        clave = (str(casa.get("key", "")), tipo, opcion, linea, actualizada)
                        if not clave[0] or clave in vistos:
                            continue
                        vistos.add(clave)
                        existe = db.scalar(select(CuotaMercado.id).where(
                            CuotaMercado.evento_api_id == evento_id,
                            CuotaMercado.casa == clave[0],
                            CuotaMercado.mercado == tipo, CuotaMercado.opcion == opcion,
                            CuotaMercado.linea == linea,
                            CuotaMercado.actualizada_en == actualizada,
                        ))
                        if existe is None:
                            db.add(CuotaMercado(
                                partido_id=partido_id, evento_api_id=evento_id,
                                casa=clave[0], mercado=tipo, opcion=opcion,
                                linea=linea, cuota_decimal=precio,
                                actualizada_en=actualizada, capturada_en=captura,
                            ))
                            guardadas += 1
            if guardadas == 0:
                resumen["sin_mercados"].append(evento_id)
            db.commit()
            resumen["cuotas_nuevas"] += guardadas
    return resumen


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Captura cuotas de goles y ambos anotan por evento")
    parser.add_argument("liga", choices=ODDS_DEPORTES)
    parser.add_argument("--limite", type=int, default=3)
    args = parser.parse_args()
    print(capturar_mercados(args.liga, args.limite))
