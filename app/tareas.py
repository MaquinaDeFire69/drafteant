import sys
from datetime import date

from app.config import settings
from app.ligas import LIGAS, temporada_actual
from app.services.fixtures import sincronizar_todas
from app.services.importar import importar
from app.services.pronosticar import generar


def actualizar_todo(ligas: list[str] | None = None) -> None:
    ligas = ligas or list(LIGAS)
    anio = temporada_actual(date.today())

    print("== 1) Resultados recientes ==")
    for liga in ligas:
        print(f"{LIGAS[liga]['nombre']} ({liga})")
        try:
            importar(liga, anio - 1, anio)
        except Exception as e:
            print(f"  [error importando {liga}] {e}")

    print("== 2) Próximos partidos ==")
    if settings.football_data_api_key:
        sincronizar_todas(ligas)
    else:
        print("  Sin FOOTBALL_DATA_API_KEY: se omiten los partidos próximos.")

    print("== 3) Pronósticos ==")
    for liga in ligas:
        try:
            generar(liga)
        except Exception as e:
            print(f"  [error pronosticando {liga}] {e}")


if __name__ == "__main__":
    codigos = [a.upper() for a in sys.argv[1:] if a.upper() in LIGAS]
    actualizar_todo(codigos or None)