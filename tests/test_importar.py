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


class ImportarTest(unittest.TestCase):
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
