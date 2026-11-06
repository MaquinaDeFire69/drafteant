from datetime import date

LIGAS = {
    "E0":  {"nombre": "Premier League", "pais": "Inglaterra",   "api": "PL",  "historico": "temporada"},
    "SP1": {"nombre": "La Liga",        "pais": "España",       "api": "PD",  "historico": "temporada"},
    "I1":  {"nombre": "Serie A",        "pais": "Italia",       "api": "SA",  "historico": "temporada"},
    "D1":  {"nombre": "Bundesliga",     "pais": "Alemania",     "api": "BL1", "historico": "temporada"},
    "F1":  {"nombre": "Ligue 1",        "pais": "Francia",      "api": "FL1", "historico": "temporada"},
    "N1":  {"nombre": "Eredivisie",     "pais": "Países Bajos", "api": "DED", "historico": "temporada"},
    "P1":  {"nombre": "Primeira Liga",  "pais": "Portugal",     "api": "PPL", "historico": "temporada"},
    "MX1": {"nombre": "Liga MX",        "pais": "México",       "api": None,  "historico": "mundial", "csv": "MEX", "inicio_historico": 2012},
    "MLS": {"nombre": "MLS",            "pais": "Estados Unidos", "api": None, "historico": "mundial", "csv": "USA", "inicio_historico": 2012},
    "CL":  {"nombre": "Champions League", "pais": "Europa",      "api": "CL",  "historico": "api", "inicio_historico": 2020},
    "EL":  {"nombre": "Europa League",  "pais": "Europa",       "api": "EL",  "historico": "api", "inicio_historico": 2020},
}


def nombre_liga(codigo: str) -> str:
    return LIGAS.get(codigo, {}).get("nombre", codigo)


def temporada_actual(hoy: date) -> int:
    """Año en que empezó la temporada en curso (agosto 2026 -> 2026, marzo 2027 -> 2026)."""
    return hoy.year if hoy.month >= 7 else hoy.year - 1
