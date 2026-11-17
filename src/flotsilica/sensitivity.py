"""The sensitivities of the model and the gate that decides which of them are published (RF20, D20; C09; plan, section 14).

What a sensor does to the estimate is an **association of the model**, never a cause and never a lever: the file has seven months of one plant, and the importance by
permutation that research.md measured was under 0.007 with a partial dependence whose sign changed between models. So every sensor is computed and a sensor is published
as a stable association only if it passes a gate fixed before anything was measured (D20):

1. the increase of the MAE when its three columns (mean, standard deviation and last value of the hour) are permuted together is at least ``min_importance_mae`` in V1
   **and** in V2 (the mean of ``permutation_repeats`` permutations);
2. the partial dependence of its hourly mean, on a grid of ``pd_grid_points`` from the percentile ``pd_low_quantile`` to ``pd_high_quantile`` over the hours of V1 and V2,
   has a Spearman correlation with the grid of the same sign and at least ``min_abs_spearman`` in size, in the sealed model **and** in each of ``refits`` refits with
   the days of the training block resampled with replacement (seed ``seed``).

The model is the best with sensors of H0 (the comparison model ``best_with_sensors``), even if the one chosen does not use sensors. The curve is computed only for the
sensors that pass the importance of the first condition (a sensor that fails it fails the gate whatever its curve says), and the Spearman correlation is the correlation
of the ranks that pandas gives, without SciPy (D36). At the evaluation of the test, a sensor that passed keeps its sign if the correlation of its curve over the hours of
the test has the sealed sign (C09).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from flotsilica.evaluation import holdout_cohort
from flotsilica.features import HourTables
from flotsilica.model import BlockData, FittedCandidate, LaunchFit, fit_candidate
from flotsilica.schema import SENSORS

SENSOR_GROUPS: dict[str, list[str]] = {sensor: [f"{sensor}_mean", f"{sensor}_std", f"{sensor}_last"] for sensor in SENSORS}
COMPARISON = "best_with_sensors"
FLAT = 1e-9              # a curve that moves less than this, in points of silica, is flat
GATE_COLUMNS = ["sensor", "importance_v1", "importance_v2", "rho_min", "rho_max", "sign_stable", "passes"]


def _mae(estimate: np.ndarray, actual: np.ndarray) -> float:
    return float(np.mean(np.abs(estimate - actual)))


def grouped_permutation(model: FittedCandidate, X: pd.DataFrame, y: np.ndarray, last1: np.ndarray, groups: Mapping[str, Sequence[str]], repeats: int,
                        rng: np.random.Generator) -> pd.DataFrame:
    """``group``, ``increase_mean`` and ``increase_std`` of the MAE of `model` on (`X`, `y`) when the columns of each group are permuted together, over `repeats`
    permutations: one draw of `rng` for each group and repeat, in the order of `groups`. `X` is not changed. A group the model does not use has an increase of 0."""
    base = _mae(model.predict(X, last1), y)
    rows = []
    for name, columns in groups.items():
        increases = []
        for _repeat in range(repeats):
            order = rng.permutation(len(X))
            shuffled = X.copy()
            shuffled[list(columns)] = X[list(columns)].to_numpy()[order]
            increases.append(_mae(model.predict(shuffled, last1), y) - base)
        rows.append((name, float(np.mean(increases)), float(np.std(increases))))
    return pd.DataFrame(rows, columns=["group", "increase_mean", "increase_std"])


def partial_dependence_curve(model: FittedCandidate, X: pd.DataFrame, last1: np.ndarray, column: str, points: int, q_low: float, q_high: float) -> pd.DataFrame:
    """``value`` and ``estimate`` of the partial dependence of `column`: the mean estimate of `model` over the rows of `X` with the column set to each of `points` values
    from the percentile `q_low` to `q_high` of the column, the other columns as they are."""
    values = X[column].to_numpy(dtype="float64")
    grid = np.linspace(np.quantile(values, q_low), np.quantile(values, q_high), points)
    estimates = []
    for value in grid:
        moved = X.copy()
        moved[column] = value
        estimates.append(float(np.mean(model.predict(moved, last1))))
    return pd.DataFrame({"value": grid, "estimate": estimates})


def spearman_sign(curve: pd.DataFrame) -> float:
    """The Spearman correlation of ``estimate`` with ``value``: the Pearson correlation of their ranks, as pandas ranks them. A flat curve has no correlation and no sign (0)."""
    if float(curve["estimate"].max() - curve["estimate"].min()) <= FLAT:         # the rounding noise of a curve that does not move would be ranked as if it were a trend
        return 0.0
    rho = curve["value"].rank().corr(curve["estimate"].rank())
    return 0.0 if rho is None or not np.isfinite(rho) else float(rho)


def gate(results: pd.DataFrame, view: Any) -> pd.DataFrame:
    """``sensor``, ``importance_v1``, ``importance_v2``, ``rho_min``, ``rho_max``, ``sign_stable`` and ``passes`` of each row of `results` (``sensor``,
    ``importance_v1``, ``importance_v2`` and ``rhos``: the Spearman correlation of the sealed model and of each refit, an empty sequence for a sensor whose curve was not
    computed). A sensor passes if both importances reach ``min_importance_mae``, the correlations all have the same sign (not zero) and the smallest in size reaches
    ``min_abs_spearman`` (D20)."""
    s = view.sensitivity
    rows = []
    for r in results.itertuples(index=False):
        rhos = [float(x) for x in r.rhos if x is not None and np.isfinite(x)]
        stable = bool(rhos) and (all(x > 0 for x in rhos) or all(x < 0 for x in rhos))
        strong = stable and min(abs(x) for x in rhos) >= s.min_abs_spearman
        enough = r.importance_v1 >= s.min_importance_mae and r.importance_v2 >= s.min_importance_mae
        rows.append((r.sensor, float(r.importance_v1), float(r.importance_v2), min(rhos) if rhos else None, max(rhos) if rhos else None, stable, bool(enough and strong)))
    return pd.DataFrame(rows, columns=GATE_COLUMNS)


def _resampled_days(block: BlockData, rng: np.random.Generator) -> np.ndarray:
    """The positions of the rows of `block` of as many days as it has, drawn with replacement, every row of a day it holds."""
    days = block.hours.normalize()
    unique = days.unique()
    by_day = {day: np.flatnonzero(days == day) for day in unique}
    return np.concatenate([by_day[unique[k]] for k in rng.integers(0, len(unique), size=len(unique))])


def launch_gate(launch: LaunchFit, view: Any) -> dict[str, Any]:
    """The gate of the launch for the best model with sensors of H0 (see the module), as the seal stores it: ``computed``, ``model`` (the name of the candidate),
    ``passing`` (the sensors that pass), ``sensors`` (every sensor with its two importances, the range of its correlations, whether the sign is stable, whether it
    passes and its sign, 0 if it does not pass) and ``curves`` (the partial dependence of the model for each sensor that passes). Without H0 or without that model in the
    grid the gate is not computed, and says so."""
    fit = launch.horizons.get(0)
    model = None if fit is None else fit.comparisons.get(COMPARISON)
    if model is None:
        return {"computed": False, "model": None, "passing": [], "sensors": [], "curves": {}}
    s, blocks = view.sensitivity, launch.blocks[0]
    rng = np.random.default_rng(s.seed)
    importance = {scope: grouped_permutation(model, blocks[scope].X, blocks[scope].y, blocks[scope].last1, SENSOR_GROUPS, s.permutation_repeats, rng).set_index("group")["increase_mean"]
                  for scope in ("valid_v1", "valid_v2")}
    train = blocks["train"]
    refits = []
    for _ in range(s.refits):
        take = _resampled_days(train, rng)
        refits.append(fit_candidate(model.candidate, train.X.iloc[take], train.y[take], train.last1[take], view))
    pd_x = pd.concat([blocks["valid_v1"].X, blocks["valid_v2"].X])
    pd_last = np.concatenate([blocks["valid_v1"].last1, blocks["valid_v2"].last1])
    rows, curves = [], {}
    for sensor in SENSOR_GROUPS:
        v1, v2 = float(importance["valid_v1"][sensor]), float(importance["valid_v2"][sensor])
        rhos: list[float] = []
        if v1 >= s.min_importance_mae and v2 >= s.min_importance_mae:      # only a sensor that moves the error enough can pass: the curve of any other is not needed
            made = [partial_dependence_curve(m, pd_x, pd_last, f"{sensor}_mean", s.pd_grid_points, s.pd_low_quantile, s.pd_high_quantile) for m in (model, *refits)]
            rhos = [spearman_sign(c) for c in made]
            curves[sensor] = made[0]
        rows.append({"sensor": sensor, "importance_v1": v1, "importance_v2": v2, "rhos": rhos})
    table = gate(pd.DataFrame(rows), view)
    passing = [r.sensor for r in table.itertuples() if r.passes]
    signs = {r["sensor"]: (1 if r["rhos"][0] > 0 else -1) for r in rows if r["sensor"] in passing}
    return {
        "computed": True, "model": model.candidate.name, "passing": passing,
        "sensors": [{"sensor": r.sensor, "importance_v1": r.importance_v1, "importance_v2": r.importance_v2, "rho_min": r.rho_min, "rho_max": r.rho_max,
                     "sign_stable": bool(r.sign_stable), "passes": bool(r.passes), "sign": signs.get(r.sensor, 0)} for r in table.itertuples()],
        "curves": {sensor: [{"value": float(v), "estimate": float(e)} for v, e in zip(curves[sensor]["value"], curves[sensor]["estimate"], strict=True)] for sensor in passing},
    }


def sign_check(tables: HourTables, model: FittedCandidate, view: Any, document: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, float]]]]:
    """For each sensor that passed the gate of the launch (`document`, the gate part of the seal), the Spearman correlation of its partial dependence over the hours of the
    test of H0 and whether it has the sealed sign (C09), and the curves. Nothing here chooses anything: it reads the test after the gate was sealed."""
    passing = [e for e in document.get("sensors", []) if e["passes"]]
    if not passing:
        return [], {}
    hours, x, _y = holdout_cohort(tables, view, 0)
    s, rows, curves = view.sensitivity, [], {}
    last1 = x["lab_last1"].to_numpy(dtype="float64")
    for entry in passing:
        curve = partial_dependence_curve(model, x, last1, f"{entry['sensor']}_mean", s.pd_grid_points, s.pd_low_quantile, s.pd_high_quantile) if len(hours) else None
        rho = spearman_sign(curve) if curve is not None else 0.0
        rows.append({"sensor": entry["sensor"], "sealed_sign": entry["sign"], "rho_test": rho, "kept_sign": bool(rho != 0.0 and np.sign(rho) == entry["sign"])})
        if curve is not None:
            curves[entry["sensor"]] = [{"value": float(v), "estimate": float(e)} for v, e in zip(curve["value"], curve["estimate"], strict=True)]
    return rows, curves
