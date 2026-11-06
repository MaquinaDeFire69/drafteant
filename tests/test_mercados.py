import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Cuota, CuotaMercado, Equipo, Partido, PiernaParlay, Pronostico
from app.services.consultas import parlays, proximos_partidos, selecciones_1x2, selecciones_mercados
from app.services.mercados import capturar_mercados, interpretar_mercado
from app.services.seguimiento import crear_parlay_simulado, rendimiento_parlays


class MercadosTest(unittest.TestCase):
    def test_captura_evento_sin_duplicar_mercados(self):
        motor = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False},
                             poolclass=StaticPool)
        Base.metadata.create_all(motor)
        Sesion = sessionmaker(bind=motor)
        ahora = datetime.now(timezone.utc)
        inicio = ahora + timedelta(days=1)
        with Sesion() as db:
            local, visita = Equipo(nombre="Uno"), Equipo(nombre="Dos")
            db.add_all((local, visita))
            db.flush()
            partido = Partido(fecha=inicio.date(), liga="E0", temporada="2026-27",
                              local_id=local.id, visitante_id=visita.id,
                              inicio_utc=inicio, estado="TIMED")
            db.add(partido)
            db.flush()
            db.add(Cuota(partido_id=partido.id, evento_api_id="ev-1", casa="casa",
                         cuota_local=1.7, cuota_empate=3.5, cuota_visitante=5.0,
                         actualizada_en=ahora, capturada_en=ahora))
            db.commit()

        class Respuesta:
            status_code = 200
            headers = {"x-requests-last": "2", "x-requests-remaining": "498"}

            def json(self):
                base = {"last_update": ahora.isoformat(), "outcomes": [
                    {"name": "Over", "point": 2.5, "price": 1.9},
                    {"name": "Under", "point": 2.5, "price": 1.95},
                ]}
                return {"bookmakers": [{"key": "casa", "markets": [
                    {**base, "key": "totals"}, {**base, "key": "alternate_totals"},
                    {"key": "btts", "last_update": ahora.isoformat(), "outcomes": [
                        {"name": "Yes", "price": 1.8}, {"name": "No", "price": 2.0},
                    ]},
                ]}]}

        with patch("app.services.mercados.SessionLocal", Sesion), \
             patch("app.services.mercados.httpx.get", return_value=Respuesta()), \
             patch("app.services.mercados.settings.odds_api_key", "clave_prueba"):
            primero = capturar_mercados("E0", limite=1)
            segundo = capturar_mercados("E0", limite=1)
        self.assertEqual((primero["cuotas_nuevas"], primero["creditos_usados"]), (4, 2))
        self.assertEqual(segundo["cuotas_nuevas"], 0)
        with Sesion() as db:
            self.assertEqual(len(list(db.scalars(select(CuotaMercado)))), 4)
        motor.dispose()

    def test_solo_guarda_linea_25_y_opciones_btts_validas(self):
        ahora = datetime.now(timezone.utc)
        inicio = ahora + timedelta(days=1)
        totales = {"key": "totals", "outcomes": [
            {"name": "Over", "point": 2.5, "price": 1.9},
            {"name": "Under", "point": 3.5, "price": 1.4},
        ]}
        self.assertEqual(interpretar_mercado(totales, ahora, ahora, inicio),
                         [("total_25", "mas", 2.5, 1.9)])
        self.assertEqual(interpretar_mercado(
            {"key": "btts", "outcomes": [{"name": "Yes", "price": 2.0},
                                         {"name": "No", "price": 1.8}]},
            ahora, ahora, inicio),
            [("btts", "si", 0.0, 2.0), ("btts", "no", 0.0, 1.8)])

    def test_parlay_mixto_fija_mercados_y_liquida_con_marcadores(self):
        motor = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False},
                             poolclass=StaticPool)
        Base.metadata.create_all(motor)
        Sesion = sessionmaker(bind=motor)
        ahora = datetime.now(timezone.utc)
        inicio = ahora + timedelta(days=2)
        with Sesion() as db:
            equipos = [Equipo(nombre=nombre) for nombre in ("A", "B", "C", "D")]
            db.add_all(equipos)
            db.flush()
            for indice, (local, visita) in enumerate(((equipos[0], equipos[1]), (equipos[2], equipos[3]))):
                partido = Partido(fecha=inicio.date(), liga="E0", temporada="2026-27",
                                  local_id=local.id, visitante_id=visita.id,
                                  inicio_utc=inicio + timedelta(hours=indice), estado="TIMED")
                db.add(partido)
                db.flush()
                pron = Pronostico(partido_id=partido.id, prob_local=0.5,
                                  prob_empate=0.25, prob_visitante=0.25,
                                  prob_mas_2_5=0.6, prob_ambos_anotan=0.55,
                                  version_modelo="test", publicado_en=ahora - timedelta(hours=1))
                db.add(pron)
                db.flush()
                db.add(Cuota(partido_id=partido.id, pronostico_id=None,
                             evento_api_id=str(indice), casa="casa", cuota_local=2.0,
                             cuota_empate=3.0, cuota_visitante=4.0,
                             actualizada_en=ahora, capturada_en=ahora))
                mercado = "total_25" if indice == 0 else "btts"
                opcion = "mas" if indice == 0 else "no"
                db.add(CuotaMercado(partido_id=partido.id, evento_api_id=str(indice),
                                    casa="casa", mercado=mercado, opcion=opcion,
                                    linea=2.5 if indice == 0 else 0.0, cuota_decimal=2.0,
                                    actualizada_en=ahora, capturada_en=ahora))
            db.commit()
            partidos = proximos_partidos(db, liga="E0")
            self.assertEqual(len(selecciones_1x2(db, partidos)), 6)
            goles = selecciones_mercados(db, partidos, "total_25")
            ambos = selecciones_mercados(db, partidos, "btts")
            opciones = goles + ambos
            self.assertEqual(len(opciones), 2)
            repetidas = parlays([goles[0], {**goles[0], "lado": "menos"}], cantidad=2)
            self.assertTrue(all(not lista for lista in repetidas.values()))
            ids = [s["id"] for s in opciones]
            crear_parlay_simulado(db, "modelo", "casa", ids, 100,
                                 elecciones=[(s["id"], s["mercado"], s["lado"]) for s in opciones])
            db.commit()
            piernas = list(db.scalars(select(PiernaParlay).order_by(PiernaParlay.id)))
            self.assertEqual([p.mercado for p in piernas], ["total_25", "btts"])
            por_id = {p.id: p for p in db.scalars(select(Partido))}
            por_id[ids[0]].goles_local, por_id[ids[0]].goles_visitante = 3, 0
            por_id[ids[1]].goles_local, por_id[ids[1]].goles_visitante = 1, 0
            db.commit()
            resultado = rendimiento_parlays(db)
            self.assertEqual((resultado["ganados"], resultado["retorno"]), (1, 400.0))
        motor.dispose()


if __name__ == "__main__":
    unittest.main()
