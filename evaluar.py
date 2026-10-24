import numpy as np
import pandas as pd

from app.services.modelo import ModeloPoisson, cargar_partidos

df = cargar_partidos("E0").sort_values("fecha")
corte = df["fecha"].max() - pd.Timedelta(days=365)
train, test = df[df["fecha"] < corte], df[df["fecha"] >= corte]

modelo = ModeloPoisson().entrenar(train, fecha_ref=corte)

log_loss, brier, aciertos, n = 0.0, 0.0, 0, 0
for r in test.itertuples():
    try:
        p = modelo.probabilidades(r.local, r.visitante)
    except ValueError:
        continue  # equipo recién ascendido sin historial
    probs = np.array([p["prob_local"], p["prob_empate"], p["prob_visitante"]])
    real = 0 if r.gl > r.gv else (1 if r.gl == r.gv else 2)
    y = np.eye(3)[real]
    log_loss += -np.log(max(probs[real], 1e-12))
    brier += ((probs - y) ** 2).sum()
    aciertos += int(probs.argmax() == real)
    n += 1

print(f"Partidos evaluados: {n}")
print(f"Log-loss: {log_loss / n:.4f}   (referencia 'siempre 1/3': 1.0986)")
print(f"Brier:    {brier / n:.4f}   (referencia 'siempre 1/3': 0.6667)")
print(f"Acierto:  {aciertos / n:.1%}")