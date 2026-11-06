import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Cuota, Equipo, Partido, Pronostico, SeleccionSeguimiento
from app.services.cuotas import ODDS_DEPORTES, _equipo, capturar_premier
from app.services.seguimiento import curva_banca, rendimiento_selecciones


class Respuesta:
    status_code = 200
    headers = {"x-requests-last": "1", "x-requests-remaining": "499"}

    def __init__(self, eventos):
        self.eventos = eventos

    def json(self):
        return self.eventos


class CuotasTest(unittest.TestCase):
    def test_curva_banca_acumula_y_mide_drawdown(self):
        curva = curva_banca([
            {"fecha": "2026-01-01", "terminada": True, "monto": 100, "cuota": 2.0, "ganada": True},
            {"fecha": "2026-01-02", "terminada": True, "monto": 100, "cuota": 2.0, "ganada": False},
            {"fecha": "2026-01-03", "terminada": False, "monto": 100, "cuota": 2.0, "ganada": None},
        ], banca_inicial=1000)
        self.assertEqual(len(curva["puntos"]), 2)
        self.assertEqual(curva["puntos"][0]["banca"], 1100)
        self.assertEqual(curva["puntos"][1]["banca"], 1000)
        self.assertEqual(curva["peor_drawdown"], -100)

    def test_ligas_configuradas_tienen_un_deporte_de_cuotas(self):
        self.assertEqual(set(ODDS_DEPORTES), {
            "E0", "SP1", "I1", "D1", "F1", "N1", "P1", "MX1", "MLS", "CL", "EL",
        })

    def test_alias_de_equipos_de_premier(self):
        conocidos = {"coventry": 1, "hull": 2, "brighton": 3}
        self.assertEqual(_equipo("Coventry City", conocidos), 1)
        self.assertEqual(_equipo("Hull City", conocidos), 2)
        self.assertEqual(_equipo("Brighton and Hove Albion", conocidos), 3)

    def test_cruce_estricto_y_captura_sin_duplicados(self):
        engine = create_engine(
            "sqlite+pysqlite://", connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        sesiones = sessionmaker(bind=engine)
        inicio = datetime.now(timezone.utc) + timedelta(days=2)
        actualizada = datetime.now(timezone.utc) - timedelta(minutes=10)
        with sesiones() as db:
            local = Equipo(nombre="Man City")
            visita = Equipo(nombre="Brighton")
            db.add_all([local, visita])
            db.flush()
            partido = Partido(
                fecha=inicio.date(), liga="E0", temporada="2026-27",
                local_id=local.id, visitante_id=visita.id,
                inicio_utc=inicio, estado="TIMED",
            )
            db.add(partido)
            db.flush()
            db.add(Pronostico(
                partido_id=partido.id, prob_local=0.6, prob_empate=0.25,
                prob_visitante=0.15, version_modelo="test",
                publicado_en=actualizada - timedelta(minutes=5),
            ))
            db.commit()

        def evento(identificador, visita, desfase=0):
            return {
                "id": identificador,
                "home_team": "Manchester City", "away_team": visita,
                "commence_time": (inicio + timedelta(hours=desfase)).isoformat(),
                "bookmakers": [{"key": "casa_prueba", "markets": [{
                    "key": "h2h", "last_update": actualizada.isoformat(),
                    "outcomes": [
                        {"name": "Manchester City", "price": 1.8},
                        {"name": "Draw", "price": 3.5},
                        {"name": visita, "price": 4.5},
                    ],
                }]}],
            }

        respuesta = Respuesta([
            evento("correcto", "Brighton and Hove Albion"),
            evento("otro_horario", "Brighton and Hove Albion", desfase=8),
            evento("otro_equipo", "Liverpool"),
        ])
        with patch("app.services.cuotas.SessionLocal", sesiones), \
             patch("app.services.cuotas.httpx.get", return_value=respuesta), \
             patch("app.services.cuotas.settings.odds_api_key", "clave_prueba"):
            primero = capturar_premier()
            segundo = capturar_premier()
        self.assertEqual((primero["eventos"], primero["cruzados"], primero["cuotas_nuevas"]), (3, 1, 1))
        self.assertEqual(primero["selecciones_nuevas"], 1)
        self.assertEqual(segundo["cuotas_nuevas"], 0)
        self.assertEqual(segundo["selecciones_nuevas"], 0)
        self.assertEqual(len(primero["sin_cruce"]), 2)
        with sesiones() as db:
            cuotas = list(db.scalars(select(Cuota)))
            self.assertEqual(len(cuotas), 1)
            self.assertIsNotNone(cuotas[0].pronostico_id)
            self.assertEqual(cuotas[0].cuota_empate, 3.5)
            seguimiento = list(db.scalars(select(SeleccionSeguimiento)))
            self.assertEqual(len(seguimiento), 1)
            self.assertEqual(seguimiento[0].lado, "local")
            self.assertEqual(seguimiento[0].cuota_decimal, 1.8)
            partido = db.get(Partido, seguimiento[0].partido_id)
            db.add(Cuota(
                partido_id=partido.id, pronostico_id=seguimiento[0].pronostico_id,
                evento_api_id="correcto", casa="casa_prueba",
                cuota_local=1.6, cuota_empate=3.6, cuota_visitante=5.0,
                actualizada_en=actualizada + timedelta(minutes=1),
                capturada_en=actualizada + timedelta(minutes=1),
            ))
            partido.goles_local, partido.goles_visitante, partido.estado = 2, 0, "FINISHED"
            db.commit()
        with sesiones() as db:
            rendimiento = rendimiento_selecciones(db)
            self.assertEqual((rendimiento["evaluadas"], rendimiento["aciertos"]), (1, 1))
            self.assertEqual(rendimiento["inversion"], 100.0)
            self.assertEqual(rendimiento["ganancia"], 80.0)
            self.assertAlmostEqual(rendimiento["filas"][0]["probabilidad_mercado"], 1 / 1.8)
            self.assertAlmostEqual(rendimiento["filas"][0]["diferencia_modelo_mercado"], 0.6 - (1 / 1.8))
            self.assertAlmostEqual(rendimiento["filas"][0]["cuota_cierre"], 1.6)
            self.assertAlmostEqual(rendimiento["filas"][0]["clv"], 1.8 / 1.6 - 1)
            self.assertEqual(rendimiento["clv"]["con_multiples_capturas"], 1)
            self.assertEqual(rendimiento_selecciones(db, liga="E0", casa="casa_prueba")["total"], 1)
            self.assertEqual(rendimiento_selecciones(db, min_probabilidad=0.7)["total"], 0)
            self.assertEqual(rendimiento_selecciones(db, min_valor=0.05)["total"], 1)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
