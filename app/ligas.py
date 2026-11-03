from datetime import date

LIGAS = {
    "E0":  {"nombre": "Premier League", "pais": "Inglaterra",   "api": "PL"},
    "SP1": {"nombre": "La Liga",        "pais": "España",       "api": "PD"},
    "I1":  {"nombre": "Serie A",        "pais": "Italia",       "api": "SA"},
    "D1":  {"nombre": "Bundesliga",     "pais": "Alemania",     "api": "BL1"},
    "F1":  {"nombre": "Ligue 1",        "pais": "Francia",      "api": "FL1"},
    "N1":  {"nombre": "Eredivisie",     "pais": "Países Bajos", "api": "DED"},
    "P1":  {"nombre": "Primeira Liga",  "pais": "Portugal",     "api": "PPL"},
}


def nombre_liga(codigo: str) -> str:
    return LIGAS.get(codigo, {}).get("nombre", codigo)


def temporada_actual(hoy: date) -> int:
    """Año en que empezó la temporada en curso (agosto 2026 -> 2026, marzo 2027 -> 2026)."""
    return hoy.year if hoy.month >= 7 else hoy.year - 1