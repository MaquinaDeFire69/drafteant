import numpy as np
import pandas as pd

from app.services.modelo import (
    ModeloBase, ModeloElo, ModeloMezcla, ModeloPoisson, cargar_partidos,
)

LIGA = "E0"
DIAS_PRUEBA = 730   # últimos 2 años como periodo de prueba
PASO = 60           # reentrenar cada 60 días

FABRICAS = {
    "Poisson": lambda: ModeloPoisson(),
    "DC xi=0.0019": lambda: ModeloPoisson(xi=0.0019, dixon_coles=True),
    "DC xi=0.003": lambda: ModeloPoisson(xi=0.003, dixon_coles=True),
    "DC xi=0.004": lambda: ModeloPoisson(xi=0.004, dixon_coles=True),
    "DC xi=0.006": lambda: ModeloPoisson(xi=0.006, dixon_coles=True),
    "DC xi=0.008": lambda: ModeloPoisson(xi=0.008, dixon_coles=True),
    "DC xi=0.012": lambda: ModeloPoisson(xi=0.012, dixon_coles=True),
}


def vector(p: dict) -> np.ndarray:
    return np.array([p["prob_local"], p["prob_empate"], p["prob_visitante"]])


def rps(probs: np.ndarray, y: np.ndarray) -> float:
    return 0.5 * float(((np.cumsum(probs) - np.cumsum(y))[:2] ** 2).sum())


df = cargar_partidos(LIGA).sort_values("fecha").reset_index(drop=True)
fin = df["fecha"].max()
cortes = list(pd.date_range(fin - pd.Timedelta(days=DIAS_PRUEBA), fin, freq=f"{PASO}D"))
limites = cortes[1:] + [fin + pd.Timedelta(days=1)]

reg = {nombre: [] for nombre in FABRICAS}   # (log_loss, brier, rps, acierto) por partido

for corte, limite in zip(cortes, limites):
    train = df[df["fecha"] < corte]
    test = df[(df["fecha"] >= corte) & (df["fecha"] < limite)]
    if test.empty:
        continue
    print(f"Entrenando con datos hasta {corte.date()} ({len(test)} partidos a evaluar)...")
    modelos = {n: f().entrenar(train, fecha_ref=corte) for n, f in FABRICAS.items()}

    for r in test.itertuples():
        try:
            preds = {n: vector(m.probabilidades(r.local, r.visitante)) for n, m in modelos.items()}
        except ValueError:
            continue  # equipo sin historial: se omite para todos los modelos
        real = 0 if r.gl > r.gv else (1 if r.gl == r.gv else 2)
        y = np.eye(3)[real]
        for n, p in preds.items():
            reg[n].append((
                -np.log(max(p[real], 1e-12)),
                float(((p - y) ** 2).sum()),
                rps(p, y),
                float(p.argmax() == real),
            ))

ref = np.array(reg["Poisson"])[:, 0]
filas = []
for n, v in reg.items():
    a = np.array(v)
    dif = a[:, 0] - ref
    filas.append({
        "Modelo": n,
        "Partidos": len(a),
        "Log-loss": a[:, 0].mean(),
        "Brier": a[:, 1].mean(),
        "RPS": a[:, 2].mean(),
        "Acierto %": 100 * a[:, 3].mean(),
        "Dif. vs Poisson": dif.mean(),
        "± EE": dif.std(ddof=1) / np.sqrt(len(dif)),
    })

tabla = pd.DataFrame(filas).set_index("Modelo")
pd.set_option("display.width", 200)
print()
print(tabla.round(4).to_string())