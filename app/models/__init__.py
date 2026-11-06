from datetime import date, datetime
from sqlalchemy import Boolean, String, Integer, Date, Float, ForeignKey, UniqueConstraint, DateTime, func
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
    prob_mas_2_5: Mapped[float | None] = mapped_column(Float)
    prob_ambos_anotan: Mapped[float | None] = mapped_column(Float)
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


class CuotaMercado(Base):
    __tablename__ = "cuotas_mercado"
    __table_args__ = (
        UniqueConstraint("evento_api_id", "casa", "mercado", "opcion", "linea", "actualizada_en",
                         name="uq_cuota_mercado_actualizacion"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    partido_id: Mapped[int] = mapped_column(ForeignKey("partidos.id"), index=True)
    evento_api_id: Mapped[str] = mapped_column(String(80))
    casa: Mapped[str] = mapped_column(String(80))
    mercado: Mapped[str] = mapped_column(String(20))
    opcion: Mapped[str] = mapped_column(String(10))
    linea: Mapped[float] = mapped_column(Float, default=0.0)
    cuota_decimal: Mapped[float] = mapped_column(Float)
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
    version_modelo: Mapped[str | None] = mapped_column(String(30))
    publicado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    monto: Mapped[float] = mapped_column(Float, default=100.0)
    estado_registro: Mapped[str] = mapped_column(String(12), default="simulada", index=True)


class ParlaySimulado(Base):
    __tablename__ = "parlays_simulados"

    id: Mapped[int] = mapped_column(primary_key=True)
    origen: Mapped[str] = mapped_column(String(12))  # modelo o personal
    casa: Mapped[str] = mapped_column(String(80))
    probabilidad: Mapped[float] = mapped_column(Float)
    cuota_decimal: Mapped[float] = mapped_column(Float)
    monto: Mapped[float] = mapped_column(Float)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    estado_registro: Mapped[str] = mapped_column(String(12), default="simulada", index=True)


class PiernaParlay(Base):
    __tablename__ = "piernas_parlay"
    __table_args__ = (UniqueConstraint("parlay_id", "partido_id", name="uq_pierna_parlay_partido"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    parlay_id: Mapped[int] = mapped_column(ForeignKey("parlays_simulados.id"), index=True)
    partido_id: Mapped[int] = mapped_column(ForeignKey("partidos.id"))
    pronostico_id: Mapped[int] = mapped_column(ForeignKey("pronosticos.id"))
    lado: Mapped[str] = mapped_column(String(10))
    mercado: Mapped[str] = mapped_column(String(20), default="h2h")
    probabilidad: Mapped[float] = mapped_column(Float)
    cuota_decimal: Mapped[float] = mapped_column(Float)
    version_modelo: Mapped[str | None] = mapped_column(String(30))
    publicado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EstrategiaSimulacion(Base):
    __tablename__ = "estrategias_simulacion"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), unique=True)
    liga: Mapped[str | None] = mapped_column(String(10))
    casa: Mapped[str | None] = mapped_column(String(80))
    min_probabilidad: Mapped[float] = mapped_column(Float, default=0.0)
    min_valor: Mapped[float] = mapped_column(Float, default=-1.0)
    cuota_min: Mapped[float | None] = mapped_column(Float)
    cuota_max: Mapped[float | None] = mapped_column(Float)
    monto: Mapped[float] = mapped_column(Float, default=100.0)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConfiguracionExposicion(Base):
    __tablename__ = "configuracion_exposicion"

    id: Mapped[int] = mapped_column(primary_key=True)
    banca_inicial: Mapped[float] = mapped_column(Float, default=1000.0)
    limite_partido: Mapped[float] = mapped_column(Float, default=0.10)
    limite_equipo: Mapped[float] = mapped_column(Float, default=0.20)
    bloquear_exceso: Mapped[bool] = mapped_column(Boolean, default=False)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
