from functools import lru_cache

from app.services.modelo import ModeloPoisson, cargar_partidos

XI = 0.003  # provisional; se afinará con comparar.py


def crear_modelo() -> ModeloPoisson:
    return ModeloPoisson(xi=XI, dixon_coles=True)


@lru_cache(maxsize=8)
def modelo_para(liga: str) -> ModeloPoisson:
    df = cargar_partidos(liga)
    if df.empty:
        raise ValueError(f"No hay datos para la liga {liga}")
    return crear_modelo().entrenar(df)