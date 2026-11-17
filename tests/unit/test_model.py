"""The grid, the selection, the refit and the comparison models (U09; RF13, D11, D14, D16; M01, M06; AC13 and AC15 in part): the 28 candidates in a fixed
order, a tie that goes to the simplest, the target in change, the refit that reads only training and V1, the groups of the comparison models, the guard
of the columns, M06 before any fit, and the blocks of the launch that never read the test."""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from flotsilica import model
from flotsilica.features import HourTables, LeakageError, design
from flotsilica.model import (
    BlockSizeError,
    Candidate,
    CandidateResult,
    build_blocks,
    candidates,
    check_block_sizes,
    check_tripwire,
    comparison_candidates,
    fit_candidate,
    fit_launch,
    make_estimator,
    refit,
    refit_blocks,
    select,
)
from tests.fixtures.tiny_model import fit_on_train, random_blocks, small_view

HOUR = timedelta(hours=1)


@pytest.fixture(scope="module")
def view(quick_cfg):
    return small_view(quick_cfg)


@pytest.fixture(scope="module")
def blocks():
    return random_blocks(seed=2)


def results(*specs) -> list[CandidateResult]:
    """``(family, set, target, leaf, mae)`` of each candidate."""
    return [CandidateResult(Candidate(*spec[:4]), spec[4]) for spec in specs]


def test_the_default_grid_has_28_candidates_per_horizon_in_a_fixed_order(cfg):
    grid = candidates(cfg)
    assert len(grid) == 28 and len(set(grid)) == 28 and grid == candidates(cfg)
    assert [c.family for c in grid].count("hgb") == 14 and [c.family for c in grid].count("rf") == 14
    assert sorted({c.feature_set for c in grid}) == ["fL", "fS", "fSL", "fSLF"]
    assert {c.target for c in grid if c.feature_set == "fS"} == {"level"}                      # fS has no last analysis to measure a change from
    assert all({c.target for c in grid if c.feature_set == s} == {"level", "change"} for s in ("fL", "fSL", "fSLF"))
    assert {c.min_samples_leaf for c in grid if c.family == "hgb"} == {20, 50} and {c.min_samples_leaf for c in grid if c.family == "rf"} == {5, 20}
    assert (grid[0].name, grid[-1].name) == ("hgb-fS-level-20", "rf-fSLF-change-20")


def test_the_quick_grid_is_the_five_candidates_of_the_quick_configuration(quick_cfg):
    assert [c.name for c in candidates(quick_cfg)] == ["rf-fS-level-20", "rf-fL-level-20", "rf-fL-change-20", "rf-fSL-level-20", "rf-fSL-change-20"]


def test_every_estimator_is_seeded_single_process_and_never_stops_early(cfg):
    for c in candidates(cfg):
        estimator = make_estimator(c, cfg)
        params = estimator.get_params()
        assert params["random_state"] == 0 and params["min_samples_leaf"] == c.min_samples_leaf
        if c.family == "rf":
            assert (type(estimator).__name__, params["n_estimators"], params["max_features"], params["n_jobs"]) == ("RandomForestRegressor", 300, 0.33, 1)
        else:
            assert type(estimator).__name__ == "HistGradientBoostingRegressor" and params["early_stopping"] is False
            assert (params["learning_rate"], params["max_iter"], params["max_leaf_nodes"], params["l2_regularization"]) == (0.05, 300, 15, 1.0)
    with pytest.raises(ValueError, match="familia"):
        make_estimator(Candidate("svm", "fL", "level", 5), cfg)


def test_a_tie_within_1e_6_goes_to_the_simplest_candidate_and_a_clear_win_does_not():
    tied = results(("rf", "fS", "level", 5, 0.5), ("rf", "fSLF", "level", 5, 0.5), ("rf", "fSL", "level", 5, 0.5), ("rf", "fL", "level", 5, 0.5 + 9e-7))
    assert select(tied) == Candidate("rf", "fL", "level", 5)                                    # fL < fSL < fSLF < fS
    assert select(results(("rf", "fSL", "level", 5, 0.5), ("rf", "fSL", "change", 5, 0.5))) == Candidate("rf", "fSL", "change", 5)    # change before level
    assert select(results(("rf", "fSL", "change", 5, 0.5), ("hgb", "fSL", "change", 20, 0.5))) == Candidate("hgb", "fSL", "change", 20)       # hgb before rf
    assert select(results(("hgb", "fL", "level", 20, 0.5), ("hgb", "fL", "level", 50, 0.5))) == Candidate("hgb", "fL", "level", 50)          # more samples per leaf
    clear = results(("rf", "fL", "level", 5, 0.5 + 2e-6), ("rf", "fS", "level", 5, 0.5))
    assert select(clear) == Candidate("rf", "fS", "level", 5)                                    # 2e-6 is not a tie: the lower error wins
    assert select(list(reversed(tied))) == select(tied)                                           # the order of the list does not matter


def test_the_selection_refuses_no_candidate_and_an_error_that_is_not_a_number():
    with pytest.raises(ValueError, match="no hay candidatos"):
        select([])
    with pytest.raises(ValueError, match="finito"):
        select(results(("rf", "fL", "level", 5, float("nan")), ("rf", "fS", "level", 5, 0.5)))


def test_a_change_target_is_fitted_on_the_difference_and_added_back_to_the_last_analysis(blocks, view):
    train = blocks["train"]
    X = train.X
    y = train.last1 + 0.3                                                                       # the analysis is always 0.3 above the last one
    change = fit_candidate(Candidate("rf", "fL", "change", 3), X, y, train.last1, view)
    probe = blocks["valid_v1"]
    assert np.allclose(change.predict(probe.X, probe.last1), probe.last1 + 0.3)               # the forest learned the constant 0.3 and the last analysis is added
    assert np.allclose(change.predict(probe.X, probe.last1 + 1.0), change.predict(probe.X, probe.last1) + 1.0)     # the last analysis given is what is added back
    assert np.allclose(change.predict(probe.X), change.predict(probe.X, probe.last1))         # without last1 it is taken from the lab_last1 of the rows
    assert (change.fitted_on, change.rows, change.columns[0]) == (("train",), len(y), "lab_last1")
    with pytest.raises(ValueError, match="último análisis"):
        fit_candidate(Candidate("rf", "fL", "change", 3), X, y, np.full(len(y), np.nan), view)


def test_refit_learns_from_the_blocks_of_refit_on_and_never_from_v2(blocks, view):
    c = Candidate("rf", "fSL", "change", 3)
    both = refit_blocks(c, blocks, view)
    assert both.fitted_on == ("train", "valid_v1") and both.rows == len(blocks["train"].y) + len(blocks["valid_v1"].y)
    changed_v2 = {**blocks, "valid_v2": dataclasses.replace(blocks["valid_v2"], y=blocks["valid_v2"].y + 9.0)}
    probe = blocks["valid_v2"]
    assert np.array_equal(refit_blocks(c, changed_v2, view).predict(probe.X, probe.last1), both.predict(probe.X, probe.last1))       # V2 is not read
    moved_v1 = {**blocks, "valid_v1": dataclasses.replace(blocks["valid_v1"], y=blocks["valid_v1"].y + 1.0)}
    assert not np.array_equal(refit_blocks(c, moved_v1, view).predict(probe.X, probe.last1), both.predict(probe.X, probe.last1))      # V1 is
    train = blocks["train"]
    assert refit(c, train.X, train.y, train.last1, view).fitted_on == ("train", "valid_v1")        # what refit records is the configuration's refit_on
    assert fit_on_train(blocks, c, view).fitted_on == ("train",)


def test_the_comparison_models_are_the_best_of_each_group_on_v1():
    grid = results(
        ("rf", "fS", "level", 5, 0.70), ("hgb", "fS", "level", 20, 0.65),
        ("rf", "fL", "level", 5, 0.50), ("rf", "fL", "change", 5, 0.48),
        ("rf", "fSL", "level", 5, 0.47), ("rf", "fSL", "change", 5, 0.49),
        ("rf", "fSLF", "level", 5, 0.45), ("rf", "fSLF", "change", 5, 0.51),
    )
    assert comparison_candidates(grid) == {
        "best_sensors_only": Candidate("hgb", "fS", "level", 20),
        "best_lab_only": Candidate("rf", "fL", "change", 5),
        "best_with_sensors": Candidate("rf", "fSLF", "level", 5),
    }
    assert comparison_candidates([r for r in grid if r.candidate.feature_set != "fS"]).keys() == {"best_lab_only", "best_with_sensors"}   # a group the grid lacks is left out
    assert comparison_candidates(results(("rf", "fSL", "level", 5, 0.4), ("rf", "fSLF", "level", 5, 0.4))) == {"best_with_sensors": Candidate("rf", "fSL", "level", 5)}


def test_a_forbidden_column_cannot_reach_a_fit_or_a_prediction(blocks, view):
    train = blocks["train"]
    c = Candidate("rf", "fSL", "level", 3)
    for column in ("iron_conc_pct", "silica_pct", "lab_state", "silica_pct_row_2", "hour_of_day", "not_in_the_schema"):
        with pytest.raises(LeakageError, match=column):
            fit_candidate(c, train.X.assign(**{column: 1.0}), train.y, train.last1, view)
    fitted = fit_on_train(blocks, c, view)
    with pytest.raises(LeakageError, match="iron_conc_pct"):
        fitted.predict(train.X.assign(iron_conc_pct=1.0))
    with pytest.raises(ValueError, match="faltan las columnas"):
        fitted.predict(train.X.drop(columns=["lab_mean6"]))
    with pytest.raises(ValueError, match="no finitos"):
        fit_candidate(c, train.X.assign(lab_mean6=np.nan), train.y, train.last1, view)       # an hour without its inputs is never a row of a fit


def test_fitting_the_same_data_twice_gives_identical_estimates(blocks, view):
    probe = blocks["valid_v1"]
    quick = dataclasses.replace(view, model=dataclasses.replace(view.model, hgb_max_iter=20))
    for c in (Candidate("rf", "fSL", "change", 3), Candidate("hgb", "fSL", "level", 20)):
        one, again = fit_on_train(blocks, c, quick), fit_on_train(blocks, c, quick)
        assert np.array_equal(one.predict(probe.X, probe.last1), again.predict(probe.X, probe.last1))


def test_a_block_with_too_few_fresh_hours_is_its_own_error_before_any_fit(small_canonical, quick_cfg, monkeypatch):
    view = small_view(quick_cfg)
    strict = dataclasses.replace(view, split=dataclasses.replace(view.split, min_fresh_hours_per_block=100))
    check_block_sizes({"train": 100, "valid_v1": 100, "valid_v2": 100}, strict)           # exactly the minimum is enough
    with pytest.raises(BlockSizeError, match="M06") as caught:
        check_block_sizes({"train": 100, "valid_v1": 99, "valid_v2": 7}, strict)
    assert "valid_v1 tiene 99" in str(caught.value) and "valid_v2 tiene 7" in str(caught.value) and "train" not in str(caught.value)
    with pytest.raises(BlockSizeError, match="valid_v2 tiene 0"):
        check_block_sizes({"train": 100, "valid_v1": 100}, strict)

    # the whole launch stops at M06: no feature matrix is built, no baseline and no candidate is fitted
    def forbidden(name):
        def refuse(*_args, **_kwargs):
            raise AssertionError(f"{name} was called")
        return refuse

    for name in ("design", "fit_baselines", "fit_candidate", "refit", "make_estimator"):
        monkeypatch.setattr(model, name, forbidden(name))
    tables = HourTables.from_hours(small_canonical.hours, strict)
    with pytest.raises(BlockSizeError, match="M06"):
        fit_launch(tables, strict)


def test_the_tripwire_stops_a_candidate_below_the_ratio_of_the_persistence(cfg):
    assert cfg.criteria.leak_tripwire_ratio == 0.5
    check_tripwire(0.40, 0.80, cfg)                                  # exactly the ratio: not below it, so it does not stop
    check_tripwire(0.99 * 0.5, 0.99, cfg)
    with pytest.raises(LeakageError, match="M01") as caught:
        check_tripwire(0.39, 0.80, cfg)
    assert "R5" in str(caught.value) and "0.3900" in str(caught.value) and "0.8000" in str(caught.value)
    for selected, persistence in ((float("nan"), 0.8), (0.4, float("nan")), (float("inf"), float("inf"))):
        with pytest.raises(LeakageError, match="M01"):
            check_tripwire(selected, persistence, cfg)
    looser = dataclasses.replace(cfg, criteria=dataclasses.replace(cfg.criteria, leak_tripwire_ratio=0.2))
    check_tripwire(0.39, 0.80, looser)


@pytest.fixture(scope="module")
def small_tables(small_canonical, view):
    return HourTables.from_hours(small_canonical.hours, view)


def test_the_blocks_of_the_launch_are_the_design_of_each_horizon_for_the_hours_of_the_cohort(small_tables, view):
    from flotsilica.baselines import eligible
    from flotsilica.split import block_of

    built = build_blocks(small_tables, view, (0, 1, 2))
    assert set(built) == {0, 1, 2} and all(set(per) == {"train", "valid_v1", "valid_v2"} for per in built.values())
    blocks_of = block_of(small_tables.hours, view)
    for horizon, per in built.items():
        for name, block in per.items():
            inside = small_tables.hours[(blocks_of == name).to_numpy()]
            hours = inside[eligible(small_tables, inside, horizon, view).to_numpy()]
            assert block.hours.equals(hours) and block.X.index.equals(hours) and (block.name, block.horizon) == (name, horizon)
            expected = design(small_tables, hours, horizon, view)            # the features of each hour made one horizon at a time
            pd.testing.assert_frame_equal(block.X, expected, check_exact=True)
            silica, fresh = small_tables.analysis_of(hours)
            assert fresh.all() and np.array_equal(block.y, silica) and np.array_equal(block.last1, expected["lab_last1"].to_numpy())
            assert not block.X.isna().any().any()


def test_the_blocks_of_the_launch_never_read_what_is_after_v2_and_refuse_the_test_block(small_tables, small_canonical, view):
    reference = build_blocks(small_tables, view, (0, 1, 2))
    later = small_canonical.hours["hour"] > pd.Timestamp(view.split.v2_last) + 3 * HOUR
    assert later.sum() > 20
    changed = small_canonical.hours.copy()
    for column in ("silica_pct", "feed_silica_pct", "amina_flow_mean", "starch_flow_mean"):
        changed.loc[later, column] = 999.0
    again = build_blocks(HourTables.from_hours(changed, view), view, (0, 1, 2))
    for horizon in reference:
        for name in reference[horizon]:
            pd.testing.assert_frame_equal(again[horizon][name].X, reference[horizon][name].X, check_exact=True)
            assert np.array_equal(again[horizon][name].y, reference[horizon][name].y)
    assert tuple(model.LAUNCH_BLOCKS) == ("train", "valid_v1", "valid_v2") and "test" not in model.LAUNCH_BLOCKS
