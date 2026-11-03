from functools import lru_cache

from app.ligas import LIGAS
from app.services.modelo import ModeloPoisson, cargar_partidos

XI = 0.004  # ajustado con comparar.py para la Premier League


def crear_modelo() -> ModeloPoisson:
    return ModeloPoisson(xi=XI, dixon_coles=True)


@lru_cache(maxsize=10)
def modelo_para(liga: str) -> ModeloPoisson:
    if liga not in LIGAS:
        raise ValueError(f"Liga desconocida: {liga}")
    df = cargar_partidos(liga)
    if df.empty:
        raise ValueError(f"No hay datos para la liga {liga}")
    return crear_modelo().entrenar(df)