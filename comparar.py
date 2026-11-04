"""Backtest temporal de modelos 1X2 para las ligas configuradas.

Ejemplo rápido:
    python comparar.py --ligas E0 --dias-prueba 180 --paso 60 --modelos base dc

Ejemplo completo:
    python comparar.py --ligas E0 SP1 I1 D1 F1 N1 P1
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from app.ligas import LIGAS
from app.services.modelo import ModeloBase, ModeloElo, ModeloPoisson, cargar_partidos

XI_PREDETERMINADOS = (0.0019, 0.003, 0.004, 0.006, 0.008, 0.012)


def vector(prediccion: dict) -> np.ndarray:
    return np.array([
        prediccion["prob_local"],
        prediccion["prob_empate"],
        prediccion["prob_visitante"],
    ])


def rps(probs: np.ndarray, y: np.ndarray) -> float:
    """Ranked Probability Score: menor es mejor."""
    return 0.5 * float(((np.cumsum(probs) - np.cumsum(y))[:2] ** 2).sum())


def crear_fabricas(modelos: list[str], xis: list[float]) -> dict[str, tuple[str, float | None, object]]:
    """Nombre mostrado -> (familia, xi, fábrica sin entrenar)."""
    fabricas = {}
    if "base" in modelos:
        fabricas["Base histórica"] = ("base", None, ModeloBase)
    if "poisson" in modelos:
        fabricas["Poisson xi=0.004"] = ("poisson", 0.004, lambda: ModeloPoisson(xi=0.004))
    if "dc" in modelos:
        for xi in xis:
            fabricas[f"Dixon-Coles xi={xi:g}"] = (
                "dixon_coles", xi, lambda xi=xi: ModeloPoisson(xi=xi, dixon_coles=True),
            )
    if "elo" in modelos:
        fabricas["Elo"] = ("elo", None, ModeloElo)
    return fabricas


def evaluar_liga(
    liga: str,
    dias_prueba: int,
    paso: int,
    modelos: list[str],
    xis: list[float],
) -> list[dict]:
    """Entrena antes de cada corte y evalúa exclusivamente la ventana siguiente."""
    df = cargar_partidos(liga).sort_values("fecha").reset_index(drop=True)
    if df.empty:
        return []

    fin = df["fecha"].max()
    inicio_prueba = fin - pd.Timedelta(days=dias_prueba)
    cortes = list(pd.date_range(inicio_prueba, fin, freq=f"{paso}D"))
    limites = cortes[1:] + [fin + pd.Timedelta(days=1)]
    fabricas = crear_fabricas(modelos, xis)
    registros = {nombre: [] for nombre in fabricas}
    omitidos = defaultdict(int)
    fallos_entrenamiento = defaultdict(int)
    partidos_prueba = 0
    cortes_usados = 0

    for corte, limite in zip(cortes, limites):
        train = df[df["fecha"] < corte]
        test = df[(df["fecha"] >= corte) & (df["fecha"] < limite)]
        if test.empty or train.empty:
            continue
        partidos_prueba += len(test)
        cortes_usados += 1
        print(f"  {liga}: corte {corte.date()} · entrenamiento {len(train)} · prueba {len(test)}")

        entrenados = {}
        for nombre, (_, _, fabrica) in fabricas.items():
            try:
                entrenados[nombre] = fabrica().entrenar(train, fecha_ref=corte)
            except Exception as error:
                fallos_entrenamiento[nombre] += len(test)
                print(f"    {nombre}: no entrenó ({error})")

        for partido in test.itertuples():
            real = 0 if partido.gl > partido.gv else (1 if partido.gl == partido.gv else 2)
            y = np.eye(3)[real]
            for nombre, modelo in entrenados.items():
                try:
                    probs = vector(modelo.probabilidades(partido.local, partido.visitante))
                except ValueError:
                    # Por ejemplo, un ascendido que todavía no tenía encuentros en el entrenamiento.
                    omitidos[nombre] += 1
                    continue
                registros[nombre].append({
                    "log_loss": -np.log(max(probs[real], 1e-12)),
                    "brier": float(((probs - y) ** 2).sum()),
                    "rps": rps(probs, y),
                    "acierto": float(probs.argmax() == real),
                })

    filas = []
    for nombre, (familia, xi, _) in fabricas.items():
        datos = registros[nombre]
        evaluados = len(datos)
        if evaluados:
            metricas = pd.DataFrame(datos)
            log_loss = float(metricas["log_loss"].mean())
            brier = float(metricas["brier"].mean())
            puntaje_rps = float(metricas["rps"].mean())
            acierto = float(metricas["acierto"].mean() * 100)
        else:
            log_loss = brier = puntaje_rps = acierto = None
        filas.append({
            "Liga": liga,
            "Nombre liga": LIGAS[liga]["nombre"],
            "Modelo": nombre,
            "Familia": familia,
            "xi": xi,
            "Cortes": cortes_usados,
            "Partidos prueba": partidos_prueba,
            "Evaluados": evaluados,
            "Omitidos sin historial": omitidos[nombre],
            "Fallos de entrenamiento": fallos_entrenamiento[nombre],
            "Cobertura %": 100 * evaluados / partidos_prueba if partidos_prueba else 0.0,
            "Log-loss": log_loss,
            "Brier": brier,
            "RPS": puntaje_rps,
            "Acierto %": acierto,
        })
    return filas


def configuracion_recomendada(resultados: pd.DataFrame) -> dict:
    """Sugiere el mejor Dixon-Coles por liga; no modifica el modelo activo."""
    salida = {}
    evaluables = resultados.dropna(subset=["Log-loss"])
    for liga, filas in evaluables.groupby("Liga"):
        candidatos = filas[filas["Familia"] == "dixon_coles"]
        if candidatos.empty:
            continue
        mejor = candidatos.sort_values(["Log-loss", "RPS"]).iloc[0]
        salida[liga] = {
            "modelo": "dixon_coles",
            "xi": float(mejor["xi"]),
            "log_loss": float(mejor["Log-loss"]),
            "brier": float(mejor["Brier"]),
            "rps": float(mejor["RPS"]),
            "cobertura": float(mejor["Cobertura %"]),
            "omitidos_sin_historial": int(mejor["Omitidos sin historial"]),
        }
    return salida


def argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest temporal por liga de modelos de fútbol.")
    parser.add_argument("--ligas", nargs="+", choices=list(LIGAS), default=list(LIGAS))
    parser.add_argument("--dias-prueba", type=int, default=730)
    parser.add_argument("--paso", type=int, default=60, help="Días entre cada reentrenamiento.")
    parser.add_argument("--modelos", nargs="+", choices=("base", "poisson", "dc", "elo"), default=("base", "poisson", "dc", "elo"))
    parser.add_argument("--xis", nargs="+", type=float, default=XI_PREDETERMINADOS)
    parser.add_argument("--salida", type=Path, default=Path("backtest_resultados.csv"))
    parser.add_argument("--configuracion", type=Path, default=Path("backtest_configuracion_recomendada.json"))
    return parser.parse_args()


def main() -> None:
    args = argumentos()
    if args.dias_prueba <= 0 or args.paso <= 0 or any(xi <= 0 for xi in args.xis):
        raise SystemExit("--dias-prueba, --paso y todos los valores de --xis deben ser positivos.")

    filas = []
    for liga in args.ligas:
        print(f"\n== {LIGAS[liga]['nombre']} ({liga}) ==")
        filas.extend(evaluar_liga(liga, args.dias_prueba, args.paso, list(args.modelos), args.xis))
    if not filas:
        raise SystemExit("No hubo partidos históricos suficientes para ejecutar el backtest.")

    resultados = pd.DataFrame(filas).sort_values(["Liga", "Log-loss"], na_position="last")
    resultados.to_csv(args.salida, index=False, encoding="utf-8-sig")
    recomendada = configuracion_recomendada(resultados)
    args.configuracion.write_text(json.dumps(recomendada, indent=2, ensure_ascii=False), encoding="utf-8")

    columnas = ["Liga", "Modelo", "Evaluados", "Omitidos sin historial", "Cobertura %", "Log-loss", "Brier", "RPS", "Acierto %"]
    pd.set_option("display.width", 220)
    print("\n" + resultados[columnas].round(4).to_string(index=False))
    print(f"\nResultados: {args.salida}")
    print(f"Configuración Dixon-Coles sugerida: {args.configuracion}")


if __name__ == "__main__":
    main()
