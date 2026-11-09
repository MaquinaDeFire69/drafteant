import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.ligas import LIGAS
from app.services.importar import _limpiar
from app.models import Equipo, Partido
from app.services.fixtures import sincronizar_desde_cuotas
from app.services.escudos import sincronizar_escudos, sincronizar_escudos_secundario


class ImportarTest(unittest.TestCase):
    def test_importar_sincroniza_escudos_al_finalizar(self):
        with patch("app.services.importar.SessionLocal"), \
             patch("app.services.importar.descargar", return_value=None), \
             patch("app.services.importar.sincronizar_todos") as sincronizar:
            from app.services.importar import importar

            importar("E0", 2024, 2025)

        sincronizar.assert_called_once_with(["E0"])

    def test_segundo_proveedor_completa_solo_escudos_faltantes(self):
        motor = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False},
                             poolclass=StaticPool)
        Base.metadata.create_all(motor)
        Sesion = sessionmaker(bind=motor)
        with Sesion() as db:
            a = Equipo(nombre="Arsenal", escudo_url="https://crests.football-data.org/arsenal.png")
            b = Equipo(nombre="Chelsea")
            db.add_all((a, b))
            db.flush()
            db.add(Partido(fecha=date(2025, 1, 1), liga="E0", temporada="2025-26",
                           local_id=a.id, visitante_id=b.id, goles_local=1, goles_visitante=0,
                           estado="FINISHED"))
            db.commit()

        class Respuesta:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"teams": [
                    {"strTeam": "Arsenal", "strBadge": "https://r2.thesportsdb.com/arsenal.png"},
                    {"strTeam": "Chelsea", "strBadge": "https://r2.thesportsdb.com/chelsea.png"},
                ]}

        with patch("app.services.escudos.SessionLocal", Sesion), \
             patch("app.services.escudos.httpx.get", return_value=Respuesta()), \
             patch("app.services.escudos.settings.thesportsdb_api_key", "123"):
            self.assertEqual(sincronizar_escudos_secundario("E0"), 1)

        with Sesion() as db:
            escudos = {equipo.nombre: equipo.escudo_url for equipo in db.scalars(select(Equipo))}
            self.assertEqual(escudos["Arsenal"], "https://crests.football-data.org/arsenal.png")
            self.assertEqual(escudos["Chelsea"], "https://r2.thesportsdb.com/chelsea.png")
        motor.dispose()

    def test_sincroniza_escudos_de_equipos_con_historial(self):
        motor = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False},
                             poolclass=StaticPool)
        Base.metadata.create_all(motor)
        Sesion = sessionmaker(bind=motor)
        with Sesion() as db:
            a, b = Equipo(nombre="Club A"), Equipo(nombre="Club B")
            db.add_all((a, b))
            db.flush()
            db.add(Partido(fecha=date(2025, 1, 1), liga="E0", temporada="2025-26",
                           local_id=a.id, visitante_id=b.id, goles_local=1, goles_visitante=0,
                           estado="FINISHED"))
            db.commit()

        class Respuesta:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"teams": [
                    {"name": "Club A", "shortName": "Club A",
                     "crest": "https://crests.football-data.org/club-a.png"},
                    {"name": "Club B", "shortName": "Club B",
                     "crest": "https://crests.football-data.org/club-b.png"},
                ]}

        with patch("app.services.escudos.SessionLocal", Sesion), \
             patch("app.services.escudos.httpx.get", return_value=Respuesta()), \
             patch("app.services.escudos.settings.football_data_api_key", "clave_prueba"):
            self.assertEqual(sincronizar_escudos("E0", anio=2025), 2)

        with Sesion() as db:
            escudos = {equipo.nombre: equipo.escudo_url for equipo in db.scalars(select(Equipo))}
            self.assertEqual(escudos["Club A"], "https://crests.football-data.org/club-a.png")
            self.assertEqual(escudos["Club B"], "https://crests.football-data.org/club-b.png")
        motor.dispose()

    def test_sincroniza_fixture_desde_cuotas_solo_para_equipo_con_historial(self):
        motor = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False},
                             poolclass=StaticPool)
        Base.metadata.create_all(motor)
        Sesion = sessionmaker(bind=motor)
        inicio = datetime.now(timezone.utc) + timedelta(days=2)
        with Sesion() as db:
            a, b = Equipo(nombre="Club A"), Equipo(nombre="Club B")
            db.add_all((a, b))
            db.flush()
            db.add(Partido(fecha=date(2025, 1, 1), liga="MX1", temporada="2025-26",
                           local_id=a.id, visitante_id=b.id, goles_local=1, goles_visitante=0,
                           estado="FINISHED"))
            db.commit()

        class Respuesta:
            status_code = 200
            headers = {"x-requests-last": "1", "x-requests-remaining": "499"}

            def json(self):
                return [{"home_team": "Club A", "away_team": "Club B",
                         "commence_time": inicio.isoformat()}]

        with patch("app.services.fixtures.SessionLocal", Sesion), \
             patch("app.services.fixtures.httpx.get", return_value=Respuesta()), \
             patch("app.services.fixtures.settings.odds_api_key", "clave_prueba"):
            sincronizar_desde_cuotas("MX1")
        with Sesion() as db:
            futuros = list(db.scalars(select(Partido).where(Partido.goles_local.is_(None))))
            self.assertEqual(len(futuros), 1)
            self.assertEqual(futuros[0].estado, "TIMED")
        motor.dispose()

    def test_ligas_nuevas_tienen_fuente_historica_definida(self):
        self.assertEqual(LIGAS["MX1"]["historico"], "mundial")
        self.assertEqual(LIGAS["MLS"]["historico"], "mundial")
        self.assertEqual(LIGAS["CL"]["historico"], "api")
        self.assertEqual(LIGAS["EL"]["historico"], "api")

    def test_limpia_archivo_mundial_con_temporada(self):
        df = pd.DataFrame({
            "Country": ["Mexico"], "League": ["Liga MX"], "Season": ["2025/2026"],
            "Date": ["25/07/2025"], "Home": ["Equipo A"], "Away": ["Equipo B"],
            "HG": [2], "AG": [1],
        })
        limpio = _limpiar(df, "MX1")
        self.assertEqual(limpio.loc[0, "Season"], "2025/2026")
        self.assertEqual(limpio.loc[0, "Date"].isoformat(), "2025-07-25")


if __name__ == "__main__":
    unittest.main()
