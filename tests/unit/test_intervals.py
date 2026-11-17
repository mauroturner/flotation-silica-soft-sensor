"""The 80 % range (U09; RF14, D15; AC16): the conformal half-width exact in the hand cases, computed only from the residuals that the refit model makes on V2,
the guards that refuse any other block or model, the clip to a percentage and the coverage the quantile promises."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from flotsilica.intervals import calibrate, conformal_half_width, interval
from flotsilica.model import Candidate, refit_blocks
from tests.fixtures import hand_cases as hc
from tests.fixtures.tiny_model import fit_on_train, random_blocks, small_view

CANDIDATE = Candidate("rf", "fSL", "change", 3)


@pytest.fixture(scope="module")
def view(quick_cfg):
    return small_view(quick_cfg)


@pytest.fixture(scope="module")
def blocks():
    return random_blocks(seed=11)


@pytest.fixture(scope="module")
def refit_model(blocks, view):
    return refit_blocks(CANDIDATE, blocks, view)


def hand_half_width(model, block, coverage: float) -> float:
    """The half-width written out by hand: sort the absolute residuals and take the rank ceil((n + 1) * coverage)."""
    residuals = sorted(abs(float(p) - float(a)) for p, a in zip(model.predict(block.X, block.last1), block.y, strict=True))
    return residuals[math.ceil(round((len(residuals) + 1) * coverage, 9)) - 1]


def test_the_half_width_comes_only_from_v2_residuals_of_the_refit_model(blocks, view, refit_model):
    v2 = blocks["valid_v2"]
    calibration = calibrate(refit_model, v2, view)
    assert calibration.half_width == hand_half_width(refit_model, v2, 0.8)
    assert (calibration.n, calibration.coverage, calibration.block) == (len(v2.y), 0.8, "valid_v2")

    # it does not move with what is not V2: not with the other blocks of the launch, whatever they hold ...
    moved = dict(blocks)
    for name in ("train", "valid_v1"):
        moved[name] = dataclasses.replace(blocks[name], y=blocks[name].y + 5.0)
    assert calibrate(refit_model, moved["valid_v2"], view).half_width == calibration.half_width
    # ... and it does move with the V2 analyses and with the model it measures (the one fitted on the training block alone is another model)
    assert calibrate(refit_model, dataclasses.replace(v2, y=v2.y + np.linspace(0, 3, len(v2.y))), view).half_width != calibration.half_width
    other = refit_blocks(CANDIDATE, {**blocks, "valid_v1": dataclasses.replace(blocks["valid_v1"], y=blocks["valid_v1"].y + 2.0)}, view)
    assert calibrate(other, v2, view).half_width != calibration.half_width


def test_a_range_is_not_calibrated_on_a_block_that_chose_or_fitted_the_model(blocks, view, refit_model):
    with pytest.raises(ValueError, match="valid_v2"):
        calibrate(refit_model, blocks["valid_v1"], view)
    with pytest.raises(ValueError, match="valid_v2"):
        calibrate(refit_model, blocks["train"], view)
    only_train = fit_on_train(blocks, CANDIDATE, view)
    with pytest.raises(ValueError, match="reajustado"):
        calibrate(only_train, blocks["valid_v2"], view)
    saw_v2 = dataclasses.replace(refit_model, fitted_on=("train", "valid_v1", "valid_v2"))
    seeing_view = dataclasses.replace(view, model=dataclasses.replace(view.model, refit_on=("train", "valid_v1", "valid_v2")))
    with pytest.raises(ValueError, match="vio el bloque"):
        calibrate(saw_v2, blocks["valid_v2"], seeing_view)


def test_the_coverage_asked_for_changes_the_half_width(blocks, view, refit_model):
    wider = dataclasses.replace(view, intervals=dataclasses.replace(view.intervals, coverage=0.95))
    assert calibrate(refit_model, blocks["valid_v2"], wider).half_width >= calibrate(refit_model, blocks["valid_v2"], view).half_width
    assert calibrate(refit_model, blocks["valid_v2"], wider).half_width == hand_half_width(refit_model, blocks["valid_v2"], 0.95)


@pytest.mark.parametrize("case", hc.CONFORMAL_CASES, ids=lambda c: f"n{len(c.residuals)}-coverage{c.coverage}")
def test_the_conformal_half_width_is_the_hand_quantile(case):
    assert conformal_half_width(np.array(case.residuals), case.coverage) == case.half_width
    assert sorted(case.residuals)[case.rank - 1] == case.half_width           # the rank the case states is the one that was taken
    assert conformal_half_width(np.array(sorted(case.residuals, reverse=True)), case.coverage) == case.half_width      # the order does not matter


def test_a_product_of_floats_does_not_move_the_rank():
    residuals = np.arange(1, 100) / 100              # n = 99, coverage 0.55: 100 * 0.55 is 55.00000000000001 in floats, and the rank is 55, not 56
    assert 100 * 0.55 > 55 and conformal_half_width(residuals, 0.55) == pytest.approx(0.55)


def test_too_few_residuals_for_the_coverage_is_an_error_and_so_is_no_residual():
    with pytest.raises(ValueError, match="no alcanza"):
        conformal_half_width(np.array([0.1, 0.2, 0.3]), 0.8)       # ceil(4 * 0.8) = 4 > 3
    assert conformal_half_width(np.array([0.1, 0.2, 0.3, 0.4]), 0.8) == 0.4       # ceil(5 * 0.8) = 4 = n
    with pytest.raises(ValueError, match="sin residuos"):
        conformal_half_width(np.array([]), 0.8)
    for bad in (np.array([0.1, np.nan, 0.3, 0.4, 0.5]), np.array([0.1, -0.2, 0.3, 0.4, 0.5])):
        with pytest.raises(ValueError, match="absolutos finitos"):
            conformal_half_width(bad, 0.8)
    for coverage in (0.0, 1.0, 1.5, True):
        with pytest.raises(ValueError, match="cobertura"):
            conformal_half_width(np.arange(10.0), coverage)


@pytest.mark.parametrize("n", [20, 57, 200])
def test_the_range_calibrated_on_a_block_covers_at_least_the_coverage_on_that_block(n):
    residuals = np.abs(np.random.default_rng(n).normal(size=n))
    q = conformal_half_width(residuals, 0.8)
    assert np.mean(residuals <= q) >= 0.8


def test_the_range_is_the_estimate_plus_and_minus_the_half_width_clipped_to_a_percentage():
    assert interval(2.5, 0.6) == pytest.approx((1.9, 3.1))
    assert interval(0.2, 0.6) == (0.0, pytest.approx(0.8))
    assert interval(99.8, 0.6) == (pytest.approx(99.2), 100.0)
    assert interval(2.0, 0.0) == (2.0, 2.0)
    for estimate, half_width in ((math.nan, 0.5), (2.0, math.inf), (2.0, -0.1)):
        with pytest.raises(ValueError, match="finitos"):
            interval(estimate, half_width)


def test_the_model_that_is_calibrated_is_the_one_that_predicts_the_hand_residuals(blocks, view, refit_model):
    """The residual is the analysis minus what the model estimates with its last analysis added back (``change``): the refit model of the test is
    a ``change`` one, so a half-width computed on the raw output of the forest (without the last analysis) would not be the hand one."""
    v2 = blocks["valid_v2"]
    raw = refit_model.estimator.predict(v2.X[list(refit_model.columns)].to_numpy())
    assert not np.allclose(raw, refit_model.predict(v2.X, v2.last1))
    assert calibrate(refit_model, v2, view).half_width == hand_half_width(refit_model, v2, 0.8)
