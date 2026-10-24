from datetime import date

from app.services.fixtures import sincronizar, temporada_actual
from app.services.importar import importar
from app.services.pronosticar import generar

LIGAS = ["E0"]


def actualizar_todo() -> None:
    anio = temporada_actual(date.today())
    for liga in LIGAS:
        print(f"== {liga} ==")
        importar(liga, anio - 1, anio)   # resultados recientes (actualiza marcadores)
        sincronizar(liga)                # próximos partidos
        generar(liga)                    # pronósticos


if __name__ == "__main__":
    actualizar_todo()