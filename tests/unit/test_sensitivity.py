"""The sensitivities and their gate (U12; RF20, D20; AC24): the importance by permutation and the partial dependence exact on a model whose answer is known, the sign by
Spearman without SciPy, and the gate of three conditions fixed before anything is measured."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LinearRegression

from flotsilica.model import Candidate, FittedCandidate
from flotsilica.schema import FEATURE_SETS, SENSORS
from flotsilica.sensitivity import gate, grouped_permutation, partial_dependence_curve, spearman_sign
from tests.fixtures.tiny_model import random_block

COLUMNS = FEATURE_SETS["fSL"]


@pytest.fixture(scope="module")
def known():
    """A linear model whose answer is known: 2 times the mean of ``amina_flow`` minus 3 times the last analysis, and nothing from any other column."""
    block = random_block("valid_v1", 120, seed=21)
    weights = np.zeros(len(COLUMNS))
    weights[COLUMNS.index("amina_flow_mean")], weights[COLUMNS.index("lab_last1")], weights[COLUMNS.index("ore_pulp_ph_std")] = 2.0, -3.0, 1.5
    estimator = LinearRegression().fit(block.X[list(COLUMNS)].to_numpy(), block.X[list(COLUMNS)].to_numpy() @ weights)
    model = FittedCandidate(Candidate("rf", "fSL", "level", 3), estimator, tuple(COLUMNS), ("train", "valid_v1"), len(block.y))
    y = block.X[list(COLUMNS)].to_numpy() @ weights + 0.05 * np.random.default_rng(3).normal(size=len(block.y))
    return block, model, y


def test_the_gate_applies_its_three_conditions(quick_cfg):
    """The importance in V1, the importance in V2 and the stability of the sign of the partial dependence in the model and in the refits: each condition fails alone."""
    view = dataclasses.replace(quick_cfg, sensitivity=dataclasses.replace(quick_cfg.sensitivity, min_importance_mae=0.01, min_abs_spearman=0.5))
    rows = {
        "passes": (0.02, 0.03, (0.9, 0.8, 0.95, 0.7, 0.85, 0.9)),
        "importance_v1_too_low": (0.0099, 0.03, (0.9, 0.8, 0.95, 0.7, 0.85, 0.9)),
        "importance_v2_too_low": (0.02, 0.0099, (0.9, 0.8, 0.95, 0.7, 0.85, 0.9)),
        "sign_changes_in_a_refit": (0.02, 0.03, (0.9, 0.8, -0.6, 0.7, 0.85, 0.9)),
        "a_correlation_below_the_minimum": (0.02, 0.03, (0.9, 0.8, 0.49, 0.7, 0.85, 0.9)),
        "negative_and_stable": (0.5, 0.5, (-0.9, -0.8, -0.95, -0.7, -0.85, -0.5)),
        "exactly_the_limits": (0.01, 0.01, (0.5, 0.5, 0.5, 0.5, 0.5, 0.5)),
        "no_sign_at_all": (0.5, 0.5, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
    }
    results = pd.DataFrame([{"sensor": name, "importance_v1": a, "importance_v2": b, "rhos": rhos} for name, (a, b, rhos) in rows.items()])
    table = gate(results, view).set_index("sensor")
    assert list(gate(results, view).columns) == ["sensor", "importance_v1", "importance_v2", "rho_min", "rho_max", "sign_stable", "passes"]
    assert table["passes"].to_dict() == {"passes": True, "importance_v1_too_low": False, "importance_v2_too_low": False, "sign_changes_in_a_refit": False,
                                         "a_correlation_below_the_minimum": False, "negative_and_stable": True, "exactly_the_limits": True, "no_sign_at_all": False}
    assert table["sign_stable"].to_dict() == {"passes": True, "importance_v1_too_low": True, "importance_v2_too_low": True, "sign_changes_in_a_refit": False,
                                              "a_correlation_below_the_minimum": True, "negative_and_stable": True, "exactly_the_limits": True, "no_sign_at_all": False}
    assert (table.loc["negative_and_stable", "rho_min"], table.loc["negative_and_stable", "rho_max"]) == (-0.95, -0.5)
    assert (table.loc["sign_changes_in_a_refit", "rho_min"], table.loc["sign_changes_in_a_refit", "rho_max"]) == (-0.6, 0.9)
    stricter = dataclasses.replace(view, sensitivity=dataclasses.replace(view.sensitivity, min_importance_mae=0.025, min_abs_spearman=0.8))
    assert gate(results, stricter).set_index("sensor")["passes"].to_dict()["passes"] is False         # the limits are the sealed ones, not constants


def test_the_importance_is_exact_on_a_linear_model_and_a_column_the_model_does_not_use_has_none(known, quick_cfg):
    block, model, y = known
    groups = {"amina_flow": ["amina_flow_mean", "amina_flow_std", "amina_flow_last"], "starch_flow": ["starch_flow_mean", "starch_flow_std", "starch_flow_last"],
              "ore_pulp_ph": ["ore_pulp_ph_mean", "ore_pulp_ph_std", "ore_pulp_ph_last"]}
    table = grouped_permutation(model, block.X, y, block.last1, groups, 3, np.random.default_rng(5)).set_index("group")
    assert list(table.columns) == ["increase_mean", "increase_std"] and list(table.index) == ["amina_flow", "starch_flow", "ore_pulp_ph"]
    assert table.loc["starch_flow", "increase_mean"] == pytest.approx(0.0, abs=1e-12) and table.loc["starch_flow", "increase_std"] == pytest.approx(0.0, abs=1e-12)
    # by hand: the permutations of the generator of seed 5, one for each group and repeat in order; the model is linear, so the error after is |2 (x[perm] - x) + e|
    rng = np.random.default_rng(5)
    base = np.mean(np.abs(model.predict(block.X) - y))
    steps = []
    for _group in groups:
        for _repeat in range(3):
            perm = rng.permutation(len(y))
            if _group == "amina_flow":
                x = block.X["amina_flow_mean"].to_numpy()
                steps.append(np.mean(np.abs(2.0 * (x[perm] - x) + (model.predict(block.X) - y))) - base)
    assert table.loc["amina_flow", "increase_mean"] == pytest.approx(np.mean(steps)) and table.loc["amina_flow", "increase_std"] == pytest.approx(np.std(steps, ddof=0))
    assert table.loc["amina_flow", "increase_mean"] > 0.5
    assert table.loc["ore_pulp_ph", "increase_mean"] > 0.3, "a model that uses only the standard deviation of a sensor has the importance of the sensor: its three columns are permuted together"
    # the same seed, the same table; the data are not changed
    before = block.X.copy()
    again = grouped_permutation(model, block.X, y, block.last1, groups, 3, np.random.default_rng(5)).set_index("group")
    assert again.equals(table) and block.X.equals(before)


def test_the_partial_dependence_of_a_linear_model_is_its_slope_and_its_sign_is_the_rank_correlation(known):
    block, model, _y = known
    curve = partial_dependence_curve(model, block.X, block.last1, "amina_flow_mean", 15, 0.05, 0.95)
    values = block.X["amina_flow_mean"].to_numpy()
    grid = np.linspace(np.quantile(values, 0.05), np.quantile(values, 0.95), 15)
    assert list(curve.columns) == ["value", "estimate"] and curve["value"].to_numpy() == pytest.approx(grid)
    mean_estimate = float(np.mean(model.predict(block.X)))
    assert curve["estimate"].to_numpy() == pytest.approx(mean_estimate + 2.0 * (grid - values.mean()))      # the estimate moves 2 for every unit of the column
    assert spearman_sign(curve) == pytest.approx(1.0)
    assert spearman_sign(partial_dependence_curve(model, block.X, block.last1, "lab_last1", 15, 0.05, 0.95)) == pytest.approx(-1.0)     # a falling dependence
    flat = partial_dependence_curve(model, block.X, block.last1, "starch_flow_mean", 15, 0.05, 0.95)
    assert np.ptp(flat["estimate"]) < 1e-9 and spearman_sign(flat) == 0.0, "a flat curve (up to rounding noise) has no sign"
    assert spearman_sign(pd.DataFrame({"value": [1, 2, 3, 4], "estimate": [1, 3, 2, 4]})) == pytest.approx(0.8), "Spearman is the correlation of the ranks"
    assert spearman_sign(pd.DataFrame({"value": [1, 2, 3, 100], "estimate": [1, 3, 2, 4]})) == pytest.approx(0.8), "an outlier in the values does not move a correlation of ranks"
