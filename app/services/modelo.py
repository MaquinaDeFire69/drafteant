from collections import defaultdict

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy.optimize import minimize_scalar
from scipy.stats import poisson
from sklearn.linear_model import LogisticRegression
from sqlalchemy import text

from app.database import engine

VERSION = "poisson_v1"  # compatibilidad con código anterior
MAX_GOLES = 10

SQL = text("""
    SELECT p.fecha, p.liga, el.nombre AS local, ev.nombre AS visitante,
           p.goles_local AS gl, p.goles_visitante AS gv
    FROM partidos p
    JOIN equipos el ON el.id = p.local_id
    JOIN equipos ev ON ev.id = p.visitante_id
    WHERE p.goles_local IS NOT NULL
""")


def cargar_partidos(liga: str) -> pd.DataFrame:
    df = pd.read_sql(SQL, engine)
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df[df["liga"] == liga].reset_index(drop=True)


def _formato_largo(df: pd.DataFrame) -> pd.DataFrame:
    """Una fila por equipo y partido: goles que anotó, contra quién y si fue local."""
    local = pd.DataFrame({
        "fecha": df["fecha"], "equipo": df["local"], "rival": df["visitante"],
        "goles": df["gl"], "es_local": 1,
    })
    visita = pd.DataFrame({
        "fecha": df["fecha"], "equipo": df["visitante"], "rival": df["local"],
        "goles": df["gv"], "es_local": 0,
    })
    return pd.concat([local, visita], ignore_index=True)


def _salida(p_l, p_e, p_v, version, **extra) -> dict:
    s = p_l + p_e + p_v
    d = {
        "prob_local": float(p_l / s),
        "prob_empate": float(p_e / s),
        "prob_visitante": float(p_v / s),
        "goles_esperados_local": None,
        "goles_esperados_visitante": None,
        "marcador_mas_probable": None,
        "version_modelo": version,
    }
    d.update(extra)
    return d


# ---------------------------------------------------------------- Base
class ModeloBase:
    """Referencia: siempre las frecuencias históricas de local/empate/visitante."""
    version = "base_v1"

    def entrenar(self, df: pd.DataFrame, fecha_ref=None):
        self.p = np.array([
            (df["gl"] > df["gv"]).mean(),
            (df["gl"] == df["gv"]).mean(),
            (df["gl"] < df["gv"]).mean(),
        ])
        return self

    def probabilidades(self, local: str, visitante: str) -> dict:
        return _salida(*self.p, self.version)


# ------------------------------------------------- Poisson / Dixon-Coles
def _tau(gl, gv, mu_l, mu_v, rho):
    t = np.ones(len(gl))
    m00 = (gl == 0) & (gv == 0)
    m01 = (gl == 0) & (gv == 1)
    m10 = (gl == 1) & (gv == 0)
    m11 = (gl == 1) & (gv == 1)
    t[m00] = 1 - mu_l[m00] * mu_v[m00] * rho
    t[m01] = 1 + mu_l[m01] * rho
    t[m10] = 1 + mu_v[m10] * rho
    t[m11] = 1 - rho
    return t


class ModeloPoisson:
    """Ataque/defensa por equipo + ventaja de local, con peso decreciente por antigüedad.
    Con dixon_coles=True aplica la corrección de marcadores bajos (parámetro rho)."""

    def __init__(self, xi: float = 0.0019, dixon_coles: bool = False):
        self.xi = xi
        self.dc = dixon_coles
        self.rho = 0.0
        self.resultado = None
        self.equipos: set[str] = set()
        self.version = "dc_v1" if dixon_coles else "poisson_v1"

    def entrenar(self, df: pd.DataFrame, fecha_ref: pd.Timestamp | None = None):
        largo = _formato_largo(df)
        fecha_ref = fecha_ref or largo["fecha"].max()
        dias = (fecha_ref - largo["fecha"]).dt.days.clip(lower=0)
        pesos = np.exp(-self.xi * dias)

        self.resultado = smf.glm(
            "goles ~ es_local + C(equipo) + C(rival)",
            data=largo, family=sm.families.Poisson(), freq_weights=pesos,
        ).fit()
        self.equipos = set(largo["equipo"])
        if self.dc:
            self._ajustar_rho(df, fecha_ref)
        return self

    def _ajustar_rho(self, df: pd.DataFrame, fecha_ref: pd.Timestamp) -> None:
        loc = pd.DataFrame({"equipo": df["local"], "rival": df["visitante"], "es_local": 1})
        vis = pd.DataFrame({"equipo": df["visitante"], "rival": df["local"], "es_local": 0})
        mu_l = self.resultado.predict(loc).to_numpy()
        mu_v = self.resultado.predict(vis).to_numpy()
        gl, gv = df["gl"].to_numpy(), df["gv"].to_numpy()
        dias = (fecha_ref - df["fecha"]).dt.days.clip(lower=0).to_numpy()
        w = np.exp(-self.xi * dias)

        def nll(rho):
            t = _tau(gl, gv, mu_l, mu_v, rho)
            if np.any(t <= 0):
                return 1e9
            return -(w * np.log(t)).sum()

        self.rho = float(minimize_scalar(nll, bounds=(-0.3, 0.3), method="bounded").x)

    def goles_esperados(self, local: str, visitante: str) -> tuple[float, float]:
        for e in (local, visitante):
            if e not in self.equipos:
                raise ValueError(f"Equipo desconocido para el modelo: {e}")
        filas = pd.DataFrame([
            {"equipo": local, "rival": visitante, "es_local": 1},
            {"equipo": visitante, "rival": local, "es_local": 0},
        ])
        mu = self.resultado.predict(filas)
        return float(mu.iloc[0]), float(mu.iloc[1])

    def matriz(self, local: str, visitante: str) -> np.ndarray:
        """Probabilidad de cada marcador: matriz[i, j] = P(local i - visitante j)."""
        mu_l, mu_v = self.goles_esperados(local, visitante)
        g = np.arange(MAX_GOLES + 1)
        m = np.outer(poisson.pmf(g, mu_l), poisson.pmf(g, mu_v))
        if self.dc:
            r = self.rho
            m[0, 0] *= max(1 - mu_l * mu_v * r, 1e-9)
            m[0, 1] *= max(1 + mu_l * r, 1e-9)
            m[1, 0] *= max(1 + mu_v * r, 1e-9)
            m[1, 1] *= max(1 - r, 1e-9)
        return m / m.sum()

    def probabilidades(self, local: str, visitante: str) -> dict:
        mu_l, mu_v = self.goles_esperados(local, visitante)
        m = self.matriz(local, visitante)
        i, j = np.unravel_index(m.argmax(), m.shape)
        return _salida(
            np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum(), self.version,
            goles_esperados_local=round(mu_l, 2),
            goles_esperados_visitante=round(mu_v, 2),
            marcador_mas_probable=f"{i}-{j}",
        )


# ------------------------------------------------------------------ Elo
class ModeloElo:
    """Ratings Elo actualizados partido a partido; una regresión logística
    convierte la diferencia de rating (con ventaja de local) en probabilidades 1X2."""

    def __init__(self, k: float = 20.0, ventaja: float = 65.0, base: float = 1500.0):
        self.k, self.ventaja, self.base = k, ventaja, base
        self.version = "elo_v1"
        self.elo: dict[str, float] = {}

    @staticmethod
    def _esperado(dif: float) -> float:
        return 1.0 / (1.0 + 10 ** (-dif / 400.0))

    def entrenar(self, df: pd.DataFrame, fecha_ref=None):
        elo = defaultdict(lambda: self.base)
        X, y = [], []
        for r in df.sort_values("fecha").itertuples():
            dif = elo[r.local] - elo[r.visitante] + self.ventaja
            if r.gl > r.gv:
                real, clase = 1.0, 0
            elif r.gl == r.gv:
                real, clase = 0.5, 1
            else:
                real, clase = 0.0, 2
            X.append([dif / 100.0])
            y.append(clase)
            mult = 1.0 + np.log(max(1, abs(r.gl - r.gv)))  # goleadas mueven más el rating
            delta = self.k * mult * (real - self._esperado(dif))
            elo[r.local] += delta
            elo[r.visitante] -= delta
        self.elo = dict(elo)
        self.clf = LogisticRegression(max_iter=1000).fit(np.array(X), np.array(y))
        return self

    def probabilidades(self, local: str, visitante: str) -> dict:
        for e in (local, visitante):
            if e not in self.elo:
                raise ValueError(f"Equipo desconocido para el modelo: {e}")
        dif = self.elo[local] - self.elo[visitante] + self.ventaja
        p = self.clf.predict_proba([[dif / 100.0]])[0]
        return _salida(p[0], p[1], p[2], self.version)


# --------------------------------------------------------------- Mezcla
class ModeloMezcla:
    """Promedio ponderado de las probabilidades de varios modelos."""

    def __init__(self, modelos: list, pesos: list[float] | None = None):
        self.modelos = modelos
        w = np.array(pesos if pesos else [1.0] * len(modelos), dtype=float)
        self.pesos = w / w.sum()
        self.version = "mezcla_v1"

    def entrenar(self, df: pd.DataFrame, fecha_ref=None):
        for m in self.modelos:
            m.entrenar(df, fecha_ref=fecha_ref)
        return self

    def probabilidades(self, local: str, visitante: str) -> dict:
        res = [m.probabilidades(local, visitante) for m in self.modelos]
        claves = ("prob_local", "prob_empate", "prob_visitante")
        mezcla = {k: float(sum(w * r[k] for w, r in zip(self.pesos, res))) for k in claves}
        ref = next((r for r in res if r.get("goles_esperados_local") is not None), {})
        return _salida(
            mezcla["prob_local"], mezcla["prob_empate"], mezcla["prob_visitante"], self.version,
            goles_esperados_local=ref.get("goles_esperados_local"),
            goles_esperados_visitante=ref.get("goles_esperados_visitante"),
            marcador_mas_probable=ref.get("marcador_mas_probable"),
        )