"""The candidates, their selection on V1, the refit and the comparison models (RF13, D11, D14, D16; M01, M06; plan, section 12).

Per horizon, the grid of ``[model]`` gives the candidates (28 by default: two families, the sets ``fL``, ``fSL`` and ``fSLF`` with the target in level and
in change, ``fS`` in level only, and two leaf sizes for each family). Everything here learns from the **training block, V1 and V2** of the launch and
from nothing else (``build_blocks`` refuses the test block):

* M06 first: each block must hold ``min_fresh_hours_per_block`` fresh hours with their inputs, or ``BlockSizeError`` comes before any matrix is built
  or any model is fitted;
* every candidate is fitted on the **training** block; the one with the lowest MAE on **V1** is selected (a tie within 1e-6 goes to the simplest, D14);
  every V1 error is kept;
* M01: if the V1 error of the selected candidate is below ``leak_tripwire_ratio`` times the one of the persistence, ``LeakageError`` stops the launch;
* the selected candidate is **refit** on the blocks of ``[model] refit_on`` (training and V1) and so are the comparison models of C07 and C08: the best
  ``fS``, the best ``fL`` and the best of ``fSL`` and ``fSLF`` on V1 (D16); the half-width of the range is calibrated on V2 with the refit model
  (``intervals.calibrate``).

A target in ``change`` is fitted as ``analysis - lab_last1`` and predicted as ``lab_last1 + prediction`` (D11). Every matrix goes through
``features.build_matrix``, so a column that is forbidden, a target or outside the schema raises ``LeakageError``, and a model refuses a matrix whose
columns are not exactly the ones of its set (M02).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor

from flotsilica import intervals
from flotsilica.baselines import B1, BaselineFit, eligible, fit_baselines
from flotsilica.config import SealedConfig
from flotsilica.features import HourTables, LeakageError, build_matrix, design
from flotsilica.schema import FEATURE_SETS
from flotsilica.split import block_of

logger = logging.getLogger(__name__)

HOUR = timedelta(hours=1)
TIE = 1e-6                                           # candidates within this MAE of the best are a tie, and the simplest of them is selected
LAUNCH_BLOCKS = ("train", "valid_v1", "valid_v2")    # the only blocks the launch reads: the test is never one of them (D18)
# D14: the simplest first when two candidates tie: fL < fSL < fSLF < fS, change before level, hgb before rf, more samples per leaf
SET_RANK = {"fL": 0, "fSL": 1, "fSLF": 2, "fS": 3}
TARGET_RANK = {"change": 0, "level": 1}
FAMILY_RANK = {"hgb": 0, "rf": 1}
# the comparison models of C07 and C08 (D16): the best of each group of sets on V1
COMPARISONS = {"best_sensors_only": ("fS",), "best_lab_only": ("fL",), "best_with_sensors": ("fSL", "fSLF")}
LAST1 = "lab_last1"


class BlockSizeError(RuntimeError):
    """M06: a block of the launch has fewer fresh hours with their inputs than ``min_fresh_hours_per_block``, so a figure from it would say little."""


@dataclass(frozen=True)
class Candidate:
    """One point of the grid: a family, a feature set, the shape of the target and the leaf size."""

    family: str
    feature_set: str
    target: str
    min_samples_leaf: int

    def simplicity(self) -> tuple[int, int, int, int]:
        """Sorts the simplest first (D14)."""
        return (SET_RANK[self.feature_set], TARGET_RANK[self.target], FAMILY_RANK[self.family], -self.min_samples_leaf)

    @property
    def name(self) -> str:
        return f"{self.family}-{self.feature_set}-{self.target}-{self.min_samples_leaf}"


def candidates(view: SealedConfig) -> list[Candidate]:
    """The grid in a fixed order: by family, set, target and leaf size, in the order of ``[model]`` and ``[features]``. The target in ``change`` needs
    the last analysis, so ``fS`` (which has none) is only in level."""
    m = view.model
    leaves = {"hgb": m.hgb_min_samples_leaf, "rf": m.rf_min_samples_leaf}
    return [
        Candidate(family, feature_set, target, leaf)
        for family in m.families for feature_set in view.features.sets for target in m.targets
        if not (target == "change" and LAST1 not in FEATURE_SETS[feature_set])
        for leaf in leaves[family]
    ]


def make_estimator(c: Candidate, view: SealedConfig) -> Any:
    """The unfitted scikit-learn regressor of a candidate: no early stopping, one process, seeded (RNF01)."""
    m = view.model
    if c.family == "hgb":
        return HistGradientBoostingRegressor(
            learning_rate=m.hgb_learning_rate, max_iter=m.hgb_max_iter, max_leaf_nodes=m.hgb_max_leaf_nodes, min_samples_leaf=c.min_samples_leaf,
            l2_regularization=m.hgb_l2_regularization, early_stopping=False, random_state=m.random_state,
        )
    if c.family == "rf":
        return RandomForestRegressor(
            n_estimators=m.rf_n_estimators, max_features=m.rf_max_features, min_samples_leaf=c.min_samples_leaf, n_jobs=1, random_state=m.random_state,
        )
    raise ValueError(f"familia desconocida: {c.family!r}")


def _last1(c: Candidate, rows: pd.DataFrame, last1: np.ndarray | None) -> np.ndarray | None:
    """The last analysis a ``change`` target is measured from: `last1`, or the column of the rows if it is not given; None for ``level``."""
    if c.target != "change":
        return None
    values = rows[LAST1].to_numpy(dtype="float64") if last1 is None else np.asarray(last1, dtype="float64")
    if len(values) != len(rows) or not np.isfinite(values).all():
        raise ValueError("el objetivo en cambio necesita el último análisis (finito) de cada hora")
    return values


@dataclass(frozen=True, eq=False)
class FittedCandidate:
    """A fitted candidate: its estimator, the columns of its set (M02) and the blocks it learned from (``fitted_on``) with their number of rows."""

    candidate: Candidate
    estimator: Any
    columns: tuple[str, ...]
    fitted_on: tuple[str, ...]
    rows: int

    def predict(self, rows: pd.DataFrame, last1: np.ndarray | None = None) -> np.ndarray:
        """The estimate of each row of `rows` (the features of an instant, as ``design`` or ``feature_row`` make them): the columns of its set are
        taken by ``build_matrix``, which refuses a forbidden one (M02), and a ``change`` model adds the last analysis to what it predicts."""
        matrix = build_matrix(rows, self.candidate.feature_set)
        if tuple(matrix.columns) != self.columns:
            raise LeakageError(f"M02: las columnas de la matriz no son las del modelo ({self.candidate.feature_set})")
        out = np.asarray(self.estimator.predict(matrix.to_numpy(dtype="float64")), dtype="float64")
        base = _last1(self.candidate, rows, last1)
        return out if base is None else base + out


def fit_candidate(c: Candidate, X: pd.DataFrame, y: np.ndarray, last1: np.ndarray | None, view: SealedConfig,
                  fitted_on: tuple[str, ...] = ("train",)) -> FittedCandidate:
    """Fit `c` on `X` (the feature rows) and `y` (the analyses); in ``change`` the model learns ``y - last1``."""
    matrix = build_matrix(X, c.feature_set)
    target = np.asarray(y, dtype="float64")
    if len(target) != len(matrix) or not len(target) or not np.isfinite(target).all():
        raise ValueError("el ajuste necesita una fila por análisis, con valores finitos")
    base = _last1(c, X, last1)
    values = matrix.to_numpy(dtype="float64")
    if not np.isfinite(values).all():
        raise ValueError(f"la matriz del conjunto {c.feature_set} tiene valores no finitos: una hora sin todas sus entradas no entra al ajuste")
    estimator = make_estimator(c, view).fit(values, target if base is None else target - base)
    return FittedCandidate(c, estimator, tuple(matrix.columns), tuple(fitted_on), len(target))


def refit(c: Candidate, X: pd.DataFrame, y: np.ndarray, last1: np.ndarray | None, view: SealedConfig) -> FittedCandidate:
    """Fit `c` again with the data of the blocks of ``[model] refit_on`` (training and V1; D11): the model that is frozen. The caller hands over
    the rows of those blocks (``refit_blocks`` does it)."""
    return fit_candidate(c, X, y, last1, view, fitted_on=tuple(view.model.refit_on))


@dataclass(frozen=True)
class CandidateResult:
    """The error of a candidate, fitted on the training block, on V1 (over the fresh hours of the cohort)."""

    candidate: Candidate
    mae_v1: float


def select(results: Sequence[CandidateResult]) -> Candidate:
    """The candidate with the lowest error on V1; within ``TIE`` of the best, the simplest (D14)."""
    if not results:
        raise ValueError("no hay candidatos para elegir")
    errors = np.array([r.mae_v1 for r in results], dtype="float64")
    if not np.isfinite(errors).all():
        raise ValueError("el error en V1 de cada candidato debe ser finito")
    best = float(errors.min())
    tied = [r.candidate for r in results if r.mae_v1 <= best + TIE]
    return min(tied, key=Candidate.simplicity)


def comparison_candidates(results: Sequence[CandidateResult]) -> dict[str, Candidate]:
    """The best candidate of each group of ``COMPARISONS`` on V1, by the same rule as ``select``; a group with no candidate in the grid is left out."""
    out: dict[str, Candidate] = {}
    for name, sets in COMPARISONS.items():
        group = [r for r in results if r.candidate.feature_set in sets]
        if group:
            out[name] = select(group)
    return out


def check_block_sizes(counts: Mapping[str, int], view: SealedConfig) -> None:
    """M06: every block of the launch needs ``min_fresh_hours_per_block`` fresh hours with their inputs; raise ``BlockSizeError`` naming each one that
    does not (and how many it has) before anything is fitted."""
    minimum = view.split.min_fresh_hours_per_block
    short = [f"{name} tiene {counts.get(name, 0)}" for name in LAUNCH_BLOCKS if counts.get(name, 0) < minimum]
    if short:
        raise BlockSizeError(f"M06: cada bloque necesita al menos {minimum} horas frescas con sus entradas; " + "; ".join(short))


def check_tripwire(mae_selected: float, mae_persistence: float, view: SealedConfig) -> None:
    """M01: if the V1 error of the selected candidate is below ``leak_tripwire_ratio`` times the persistence's, the launch stops: an honest candidate
    stays near the persistence (D09). A value that is not finite stops it too."""
    ratio = view.criteria.leak_tripwire_ratio
    if not (np.isfinite(mae_selected) and np.isfinite(mae_persistence)) or mae_selected < ratio * mae_persistence:
        logger.error("M01: the V1 error of the selected candidate is %s against %s of the persistence (ratio %s): the launch stops", mae_selected, mae_persistence, ratio)
        raise LeakageError(
            f"M01: el MAE en V1 del candidato elegido ({mae_selected:.4f}) es menor que {ratio} × el de la persistencia ({mae_persistence:.4f}): "
            "posible fuga de información. El lanzamiento se detiene (docs/runbook.md, R5)"
        )


# --- the blocks of the launch ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class BlockData:
    """The fresh hours with their inputs of one block, for one horizon: the hours (``hours``), the 67 columns of features at each one's issue instant
    (``X``, indexed by the hours), the analyses (``y``) and the last analysis known at the instant (``last1``)."""

    name: str
    horizon: int
    hours: pd.DatetimeIndex
    X: pd.DataFrame
    y: np.ndarray
    last1: np.ndarray


def build_blocks(tables: HourTables, view: SealedConfig, horizons: Sequence[int]) -> dict[int, dict[str, BlockData]]:
    """``{horizon: {block: BlockData}}`` for the training block, V1 and V2: the hours of the cohort of the baselines (fresh, with their history and the
    readings of the hour that closed), after M06. Nothing of the test block is read.

    The features of an instant are the same for every horizon, and the horizon ``h`` of the target ``t`` is the instant ``t - h + 1 h``, which is the
    instant of the target ``t - h`` at horizon 0: they are made once, for the union of those targets, instead of once per horizon."""
    horizons = tuple(horizons)
    hours = tables.hours
    blocks = block_of(hours, view)
    targets: dict[int, dict[str, pd.DatetimeIndex]] = {}
    for horizon in horizons:
        targets[horizon] = {}
        for name in LAUNCH_BLOCKS:
            inside = hours[(blocks == name).to_numpy()]
            targets[horizon][name] = inside[eligible(tables, inside, horizon, view).to_numpy()]
        check_block_sizes({name: len(found) for name, found in targets[horizon].items()}, view)
    needed = sorted({t - horizon * HOUR for horizon in horizons for found in targets[horizon].values() for t in found})
    table = design(tables, pd.DatetimeIndex(needed), 0, view)
    out: dict[int, dict[str, BlockData]] = {}
    for horizon in horizons:
        out[horizon] = {}
        for name, found in targets[horizon].items():
            X = table.loc[found - horizon * HOUR]
            X.index = found
            y, fresh = tables.analysis_of(found)
            if not fresh.all():      # pragma: no cover - the cohort is the fresh hours
                raise ValueError("un bloque del lanzamiento tiene una hora sin análisis fresco")
            out[horizon][name] = BlockData(name, horizon, found, X, y, X[LAST1].to_numpy(dtype="float64"))
    return out


def stack(blocks: Mapping[str, BlockData], names: Sequence[str]) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """``(X, y, last1)`` of the blocks `names` one after the other, in that order."""
    parts = [blocks[name] for name in names]
    return pd.concat([p.X for p in parts]), np.concatenate([p.y for p in parts]), np.concatenate([p.last1 for p in parts])


def refit_blocks(c: Candidate, blocks: Mapping[str, BlockData], view: SealedConfig) -> FittedCandidate:
    """``refit`` with the blocks of ``[model] refit_on``."""
    X, y, last1 = stack(blocks, view.model.refit_on)
    return refit(c, X, y, last1, view)


# --- one horizon and the whole launch -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class HorizonFit:
    """What the launch learns for a horizon: the V1 error of every candidate (``results``), the selected one (``chosen``) and its refit
    (``model``), the comparison models (C07 and C08), the calibration of the range on V2 and the V1 error of the selected candidate."""

    horizon: int
    results: tuple[CandidateResult, ...]
    chosen: Candidate
    mae_v1: float
    model: FittedCandidate
    comparisons: dict[str, FittedCandidate]
    calibration: intervals.Calibration


def fit_horizon(horizon: int, blocks: Mapping[str, BlockData], mae_persistence_v1: float, view: SealedConfig) -> HorizonFit:
    """Fit the grid on the training block, select on V1, stop on M01, refit and calibrate on V2, for one horizon."""
    train, v1, v2 = blocks["train"], blocks["valid_v1"], blocks["valid_v2"]
    results = []
    for c in candidates(view):
        fitted = fit_candidate(c, train.X, train.y, train.last1, view)
        results.append(CandidateResult(c, float(np.mean(np.abs(fitted.predict(v1.X, v1.last1) - v1.y)))))
    chosen = select(results)
    mae_v1 = next(r.mae_v1 for r in results if r.candidate == chosen)
    check_tripwire(mae_v1, mae_persistence_v1, view)
    wanted = {"model": chosen, **comparison_candidates(results)}
    refits: dict[Candidate, FittedCandidate] = {}
    for c in wanted.values():
        if c not in refits:
            refits[c] = refit_blocks(c, blocks, view)
    model = refits[chosen]
    comparisons = {name: refits[c] for name, c in wanted.items() if name != "model"}
    return HorizonFit(horizon, tuple(results), chosen, mae_v1, model, comparisons, intervals.calibrate(model, v2, view))


@dataclass(frozen=True, eq=False)
class LaunchFit:
    """The launch's learning: the baselines (``BaselineFit``), the fit of each horizon and the blocks they were made from."""

    baselines: BaselineFit
    horizons: dict[int, HorizonFit]
    blocks: dict[int, dict[str, BlockData]]


def fit_launch(tables: HourTables, view: SealedConfig) -> LaunchFit:
    """The whole learning of the launch for the horizons of ``[evaluation] horizons`` (plan, section 3, step 5, without the sensitivities and the
    seal): the blocks (M06), the baselines, and each horizon's candidates, selection, M01, refit and calibration."""
    blocks = build_blocks(tables, view, view.evaluation.horizons)
    baselines = fit_baselines(tables, view)
    fits = {h: fit_horizon(h, blocks[h], baselines.mae_v1[h][B1], view) for h in view.evaluation.horizons}
    return LaunchFit(baselines, fits, blocks)

