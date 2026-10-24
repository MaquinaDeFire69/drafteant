from datetime import date

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import Equipo, Partido, Pronostico
from app.services.cache import crear_modelo
from app.services.modelo import cargar_partidos


def generar(liga: str = "E0") -> None:
    historico = cargar_partidos(liga)
    if historico.empty:
        raise RuntimeError(f"No hay datos históricos para {liga}. Ejecuta primero la importación.")
    modelo = crear_modelo().entrenar(historico)

    with SessionLocal() as db:
        nombres = {e.id: e.nombre for e in db.scalars(select(Equipo))}
        pendientes = db.scalars(
            select(Partido).where(
                Partido.liga == liga,
                Partido.goles_local.is_(None),
                Partido.fecha >= date.today(),
            )
        ).all()

        guardados = 0
        for p in pendientes:
            local, visita = nombres[p.local_id], nombres[p.visitante_id]
            try:
                r = modelo.probabilidades(local, visita)
            except ValueError as e:
                print(f"  [omitido] {local} vs {visita}: {e}")
                continue

            db.execute(delete(Pronostico).where(Pronostico.partido_id == p.id))
            db.add(Pronostico(
                partido_id=p.id,
                prob_local=r["prob_local"],
                prob_empate=r["prob_empate"],
                prob_visitante=r["prob_visitante"],
                goles_esperados_local=r["goles_esperados_local"],
                goles_esperados_visitante=r["goles_esperados_visitante"],
                version_modelo=r["version_modelo"],
            ))
            guardados += 1

        db.commit()
        print(f"{liga}: {guardados} pronósticos guardados")


if __name__ == "__main__":
    generar("E0")