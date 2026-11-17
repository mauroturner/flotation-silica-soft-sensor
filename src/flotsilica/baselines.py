"""The baselines of an operator (RF11, RF12, D13; plan, section 11): what the model has to beat.

* **B0**, the mean of the fresh analyses of the training block: the floor.
* **B1**, persistence: the latest fresh analysis that has arrived at the issue instant (a held or interpolated hour is not one, D05).
* **B2**, the mean of the latest ``k`` fresh analyses that have arrived, with ``k`` chosen on V1 among ``[baselines] rolling_k``.
* **B3**, a ridge on the standardised aggregates of the hour that closed, fitted on the training block: what the sensors say without the laboratory.
* **B\\***, the stronger of B1 and B2 on V1 (a difference of less than 1e-6 is a tie, which goes to the first of ``strongest_candidates``).

Everything is judged on the same **cohort**: a target hour that is fresh, with at least ``min_fresh_history`` analyses arrived at its issue instant
and the readings of the hour that closed at it (``eligible``). B0 and B3 learn from the training block only; k and B\\* from V1 only: nothing that
is later than the block they are chosen on can move them (AC14, AC17), which tests change the later blocks to prove.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from flotsilica.features import HourTables
from flotsilica.schema import AGGREGATE_COLUMNS
from flotsilica.split import block_of

HOUR = timedelta(hours=1)
TIE = 1e-6
B1, B2 = "b1_persistence", "b2_rolling"
METHODS = ("b0_train_mean", B1, B2, "b3_ridge_sensors")


def _instants(targets: pd.DatetimeIndex, horizon: int) -> pd.DatetimeIndex:
    if not isinstance(horizon, (int, np.integer)) or isinstance(horizon, bool) or horizon < 0:
        raise ValueError(f"horizon: se esperaba un entero de 0 o más, se recibió {horizon!r}")
    return pd.DatetimeIndex(targets) + HOUR * (1 - int(horizon))


def lab_baselines(tables: HourTables, targets: pd.DatetimeIndex, horizon: int, view: Any) -> pd.DataFrame:
    """B1 and B2 for each target hour: ``b1_persistence`` and ``b2_k<k>`` for each ``k`` of ``rolling_k``, from the fresh analyses that have arrived at
    the instant ``target - horizon + 1 h``. A value is NaN if fewer than ``min_fresh_history`` (or than ``k``) analyses have arrived."""
    instants = _instants(targets, horizon)
    ks, history = tuple(view.baselines.rolling_k), view.features.min_fresh_history
    out = np.full((len(instants), 1 + len(ks)), np.nan)
    for row, instant in enumerate(instants):
        _hours, silica = tables.fresh_known(instant.to_pydatetime())
        count = len(silica)
        if count >= max(1, history):
            out[row, 0] = silica[-1]
        for column, k in enumerate(ks, start=1):
            if count >= max(k, history):
                out[row, column] = float(np.mean(silica[-k:]))
    return pd.DataFrame(out, index=pd.DatetimeIndex(targets), columns=[B1, *(f"b2_k{k}" for k in ks)])


def eligible(tables: HourTables, targets: pd.DatetimeIndex, horizon: int, view: Any) -> pd.Series:
    """Which of the target hours are in the cohort: fresh, with ``min_fresh_history`` analyses arrived at their issue instant and the readings of
    the hour that closed at it (at least ``min_rows_per_hour`` rows)."""
    targets = pd.DatetimeIndex(targets)
    instants = _instants(targets, horizon)
    _silica, fresh = tables.analysis_of(targets)
    _matrix, rows = tables.sensor_matrix(instants)
    known = tables.known_count(instants)
    keep = fresh & (known >= view.features.min_fresh_history) & (np.nan_to_num(rows, nan=-1.0) >= view.hours.min_rows_per_hour)
    return pd.Series(keep, index=targets, dtype=bool)


def mae(estimate: np.ndarray, actual: np.ndarray) -> float:
    """The mean absolute error."""
    return float(np.mean(np.abs(np.asarray(estimate, dtype="float64") - np.asarray(actual, dtype="float64"))))


def fit_b0(train_silica: np.ndarray) -> float:
    """B0: the mean of the fresh analyses of the training block."""
    values = np.asarray(train_silica, dtype="float64")
    if not len(values):
        raise ValueError("B0: sin análisis frescos en el entrenamiento")
    return float(np.mean(values))


@dataclass(frozen=True)
class B3Model:
    """A ridge on standardised readings: ``pipeline`` (``StandardScaler`` then ``Ridge``) and the ``columns`` it takes."""

    pipeline: Any
    columns: tuple[str, ...]

    def predict(self, readings: pd.DataFrame) -> np.ndarray:
        return self.pipeline.predict(readings[list(self.columns)].to_numpy(dtype="float64"))


def fit_b3(readings: pd.DataFrame, silica: np.ndarray, view: Any) -> B3Model:
    """B3: ``Ridge(alpha)`` on the standardised columns of `readings` (the aggregates of the hour that closed), fitted on `silica`."""
    if not len(readings):
        raise ValueError("B3: sin horas con lecturas y análisis en el entrenamiento")
    pipeline = make_pipeline(StandardScaler(), Ridge(alpha=view.baselines.ridge_alpha))
    pipeline.fit(readings.to_numpy(dtype="float64"), np.asarray(silica, dtype="float64"))
    return B3Model(pipeline, tuple(readings.columns))


def choose_k(frame: pd.DataFrame, actual: np.ndarray, view: Any) -> int:
    """The ``k`` of B2 with the lowest error on `frame` (the ``b2_k<k>`` columns of ``lab_baselines`` on V1) against `actual`; a difference of less
    than 1e-6 is a tie that goes to the first ``k`` of ``rolling_k``."""
    if not len(frame):
        raise ValueError("B2: sin horas en V1 para elegir k")
    best_k, best = None, np.inf
    for k in view.baselines.rolling_k:
        error = mae(frame[f"b2_k{k}"].to_numpy(), actual)
        if not np.isfinite(error):
            raise ValueError(f"B2: la columna b2_k{k} no tiene valores finitos en V1")
        if error < best - TIE:
            best_k, best = k, error
    return int(best_k)


def strongest(mae_b1: float, mae_b2: float, view: Any) -> str:
    """B*: the candidate of ``strongest_candidates`` with the lower error on V1; a difference of less than 1e-6 is a tie that goes to the first of them."""
    errors = {B1: mae_b1, B2: mae_b2}
    best_name, best = None, np.inf
    for name in view.baselines.strongest_candidates:
        if errors[name] < best - TIE:
            best_name, best = name, errors[name]
    return best_name


@dataclass(frozen=True)
class BaselineFit:
    """What is learned, by horizon: ``b0_mean`` (one for all), ``b3`` (a ridge), ``b2_k`` (chosen on V1), ``b_star`` (the stronger of B1 and B2 on V1),
    ``mae_v1`` (the V1 error of each method) and ``cohort_v1`` (the hours of V1 those errors are over)."""

    b0_mean: float
    b3: dict[int, B3Model]
    b2_k: dict[int, int]
    b_star: dict[int, str]
    mae_v1: dict[int, dict[str, float]]
    cohort_v1: dict[int, int]


def fit_baselines(tables: HourTables, view: Any) -> BaselineFit:
    """Fit B0 and B3 on the training block and choose k and B\\* on V1, for each horizon of ``[evaluation] horizons``. Only the hours of those two
    blocks are read, and a hour of V1 or later is not read to fit B0 or B3."""
    if view.features.min_fresh_history < max(view.baselines.rolling_k):
        raise ValueError(f"[features] min_fresh_history ({view.features.min_fresh_history}) debe alcanzar al mayor k de [baselines] rolling_k "
                         f"({max(view.baselines.rolling_k)}): B2 se juzga sobre las mismas horas que los modelos")
    blocks = block_of(tables.hours, view)
    train, v1 = tables.hours[(blocks == "train").to_numpy()], tables.hours[(blocks == "valid_v1").to_numpy()]
    silica, fresh = tables.analysis_of(train)
    b0 = fit_b0(silica[fresh])
    b3, b2_k, b_star, errors, cohort = {}, {}, {}, {}, {}
    for horizon in view.evaluation.horizons:
        keep = eligible(tables, train, horizon, view).to_numpy()
        matrix, _rows = tables.sensor_matrix(_instants(train, horizon))
        y_train, _ = tables.analysis_of(train)
        b3[horizon] = fit_b3(pd.DataFrame(matrix[keep], columns=list(AGGREGATE_COLUMNS)), y_train[keep], view)
        mask = eligible(tables, v1, horizon, view).to_numpy()
        targets = v1[mask]
        if not len(targets):
            raise ValueError(f"V1 no tiene horas para el horizonte {horizon}: ninguna cumple la cohorte")
        y, _ = tables.analysis_of(targets)
        lab = lab_baselines(tables, targets, horizon, view)
        k = choose_k(lab, y, view)
        sensors, _ = tables.sensor_matrix(_instants(targets, horizon))
        errors[horizon] = {
            "b0_train_mean": mae(np.full(len(y), b0), y), B1: mae(lab[B1].to_numpy(), y), B2: mae(lab[f"b2_k{k}"].to_numpy(), y),
            "b3_ridge_sensors": mae(b3[horizon].predict(pd.DataFrame(sensors, columns=list(AGGREGATE_COLUMNS))), y),
        }
        b2_k[horizon], b_star[horizon], cohort[horizon] = k, strongest(errors[horizon][B1], errors[horizon][B2], view), len(y)
    return BaselineFit(b0, b3, b2_k, b_star, errors, cohort)
