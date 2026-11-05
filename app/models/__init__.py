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
    # Los partidos históricos de CSV no tienen estos datos, por eso son opcionales.
    api_partido_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    inicio_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    estado: Mapped[str] = mapped_column(String(20), default="SCHEDULED", index=True)


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
    # Una predicción es un registro histórico: nunca se reemplaza por una posterior.
    publicado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class Cuota(Base):
    __tablename__ = "cuotas"
    __table_args__ = (
        UniqueConstraint("evento_api_id", "casa", "actualizada_en", name="uq_cuota_evento_casa_actualizacion"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    partido_id: Mapped[int] = mapped_column(ForeignKey("partidos.id"), index=True)
    pronostico_id: Mapped[int | None] = mapped_column(ForeignKey("pronosticos.id"))
    evento_api_id: Mapped[str] = mapped_column(String(80))
    casa: Mapped[str] = mapped_column(String(80))
    cuota_local: Mapped[float] = mapped_column(Float)
    cuota_empate: Mapped[float] = mapped_column(Float)
    cuota_visitante: Mapped[float] = mapped_column(Float)
    actualizada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    capturada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SeleccionSeguimiento(Base):
    __tablename__ = "selecciones_seguimiento"
    __table_args__ = (
        UniqueConstraint("pronostico_id", name="uq_seleccion_pronostico"),
        UniqueConstraint("cuota_id", name="uq_seleccion_cuota"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    partido_id: Mapped[int] = mapped_column(ForeignKey("partidos.id"), index=True)
    pronostico_id: Mapped[int] = mapped_column(ForeignKey("pronosticos.id"))
    cuota_id: Mapped[int] = mapped_column(ForeignKey("cuotas.id"))
    lado: Mapped[str] = mapped_column(String(10))
    probabilidad: Mapped[float] = mapped_column(Float)
    cuota_decimal: Mapped[float] = mapped_column(Float)
    casa: Mapped[str] = mapped_column(String(80))
    seleccionada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
