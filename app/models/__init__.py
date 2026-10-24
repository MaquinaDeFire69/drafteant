from datetime import date, datetime
from sqlalchemy import String, Integer, Date, Float, ForeignKey, UniqueConstraint, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Equipo(Base):
    __tablename__ = "equipos"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True)


class Partido(Base):
    __tablename__ = "partidos"
    __table_args__ = (UniqueConstraint("fecha", "local_id", "visitante_id", name="uq_partido"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, index=True)
    liga: Mapped[str] = mapped_column(String(10), index=True)   # código: E0, SP1, D1...
    temporada: Mapped[str] = mapped_column(String(9))            # "2024-25"
    local_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"))
    visitante_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"))
    goles_local: Mapped[int | None] = mapped_column(Integer)
    goles_visitante: Mapped[int | None] = mapped_column(Integer)


class Pronostico(Base):
    __tablename__ = "pronosticos"
    id: Mapped[int] = mapped_column(primary_key=True)
    partido_id: Mapped[int] = mapped_column(ForeignKey("partidos.id"))
    prob_local: Mapped[float] = mapped_column(Float)
    prob_empate: Mapped[float] = mapped_column(Float)
    prob_visitante: Mapped[float] = mapped_column(Float)
    goles_esperados_local: Mapped[float | None] = mapped_column(Float)
    goles_esperados_visitante: Mapped[float | None] = mapped_column(Float)
    version_modelo: Mapped[str] = mapped_column(String(30))
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())