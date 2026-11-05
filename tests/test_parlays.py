import unittest
from app.services.consultas import parlays


def seleccion(identificador, probabilidad, cuota=1.5):
    return {
        "id": identificador, "probabilidad": probabilidad,
        "cuotas_por_casa": {"casa_prueba": {"cuota": cuota}},
    }


class ParlaysTest(unittest.TestCase):
    def test_clasifica_por_probabilidad_conjunta_y_descarta_menos_de_20(self):
        grupos = parlays([
            seleccion(1, 0.90), seleccion(2, 0.80), seleccion(3, 0.75),
            seleccion(4, 0.60), seleccion(5, 0.30),
        ])
        self.assertTrue(any(p["probabilidad"] >= 0.70 for p in grupos["seguras"]))
        self.assertTrue(any(0.60 <= p["probabilidad"] < 0.70 for p in grupos["analizar"]))
        self.assertTrue(any(0.40 <= p["probabilidad"] < 0.60 for p in grupos["riesgosas"]))
        self.assertTrue(any(0.20 <= p["probabilidad"] < 0.40 for p in grupos["regalar_dinero"]))
        self.assertTrue(all(
            p["probabilidad"] >= 0.20
            for grupo in grupos.values() for p in grupo
        ))

    def test_requiere_una_casa_en_comun(self):
        primera = seleccion(1, 0.9)
        segunda = seleccion(2, 0.9)
        segunda["cuotas_por_casa"] = {"otra_casa": {"cuota": 1.5}}
        self.assertEqual(parlays([primera, segunda]), {
            "seguras": [], "analizar": [], "riesgosas": [], "regalar_dinero": [],
        })

    def test_respeta_cantidad_de_selecciones(self):
        grupos = parlays([
            seleccion(1, 0.9), seleccion(2, 0.85), seleccion(3, 0.8),
            seleccion(4, 0.75),
        ], cantidad=3)
        encontrados = [parlay for grupo in grupos.values() for parlay in grupo]
        self.assertTrue(encontrados)
        self.assertTrue(all(len(parlay["selecciones"]) == 3 for parlay in encontrados))


if __name__ == "__main__":
    unittest.main()
