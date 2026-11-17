"""The baselines (U08; RF11, RF12, D13; AC14 and AC17): persistence and means of the latest fresh analyses that have arrived, exact in the
hand case with held and interpolated hours, the cohort they are judged on, B0 and B3 from the training block only, and k and B* from V1 only."""

from __future__ import annotations

import dataclasses
import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from flotsilica.baselines import choose_k, eligible, fit_b0, fit_b3, fit_baselines, lab_baselines, strongest
from flotsilica.features import HourTables
from flotsilica.schema import AGGREGATE_COLUMNS
from flotsilica.split import block_of
from tests.fixtures import hand_cases as hc

HOUR = timedelta(hours=1)
RULING = ("b1_persistence", "b2_k3", "b2_k6", "b2_k12", "b2_k24")


@pytest.fixture(scope="module")
def view(quick_cfg):
    return dataclasses.replace(quick_cfg, features=dataclasses.replace(quick_cfg.features, min_fresh_history=1))


@pytest.fixture(scope="module")
def tables(view) -> HourTables:
    return HourTables.from_hours(hc.case_hours(), view)


# silica of the fresh hours of the hand case: 0 -> 2.50, 1 -> 2.61, 2 -> 2.40, 5 -> 2.10, 7 -> 2.35, 10 -> 2.20, 11 -> 2.45 (3 and 4 interpolated, 6, 8 and 9 held)
# instant t -> (the fresh analyses that have arrived, latest first): those with a sample hour <= t - 2
ARRIVED = {
    4: [2.40, 2.61, 2.50],                        # hours 0, 1, 2: the analysis of hour 2 arrives at 4
    5: [2.40, 2.61, 2.50],                        # hour 3 is interpolated: no new analysis
    6: [2.40, 2.61, 2.50],                        # hour 4 is interpolated too
    7: [2.10, 2.40, 2.61, 2.50],                  # hour 5 arrives: the persistence is 2.10, not the 2.30 or the 2.20 of the ramp
    8: [2.10, 2.40, 2.61, 2.50],                  # hour 6 is held: it is not a new analysis
    9: [2.35, 2.10, 2.40, 2.61, 2.50],            # hour 7
    10: [2.35, 2.10, 2.40, 2.61, 2.50],           # hour 8 is held
    11: [2.35, 2.10, 2.40, 2.61, 2.50],           # hour 9 is held
    12: [2.20, 2.35, 2.10, 2.40, 2.61, 2.50],     # hour 10
    13: [2.45, 2.20, 2.35, 2.10, 2.40, 2.61, 2.50],   # hour 11
}


def test_persistence_uses_the_last_fresh_analysis_not_a_held_or_interpolated_one(tables, view):
    instants = sorted(ARRIVED)
    targets = pd.DatetimeIndex([hc.hour(t - 1) for t in instants])          # H0: the hour that has just closed
    frame = lab_baselines(tables, targets, 0, view)
    assert list(frame.columns) == list(RULING) and frame.index.equals(targets)
    for t, row in zip(instants, frame.to_numpy(), strict=True):
        latest = ARRIVED[t]
        expected = {"b1_persistence": latest[0]}
        for k in (3, 6, 12, 24):
            expected[f"b2_k{k}"] = sum(latest[:k]) / k if len(latest) >= k else math.nan
        got = dict(zip(RULING, row, strict=True))
        for name, value in expected.items():
            assert got[name] == pytest.approx(value, nan_ok=True), (t, name)
    # the persistence of hour 9 at 10:00 is hour 7's 2.35 and at 7:00 hour 5's 2.10: never the held 2.10 of hour 6 nor the ramp's 2.30 and 2.20
    assert frame.loc[hc.hour(9), "b1_persistence"] == 2.35 and frame.loc[hc.hour(6), "b1_persistence"] == 2.10
    assert frame.loc[hc.hour(4), "b1_persistence"] == 2.40 != hc.freshness_case().first_rows["silica_pct"].iloc[4]


def test_a_horizon_moves_the_instant_of_a_target_not_the_rule(tables, view):
    h0 = lab_baselines(tables, pd.DatetimeIndex([hc.hour(9)]), 0, view)       # issued at 10:00
    h1 = lab_baselines(tables, pd.DatetimeIndex([hc.hour(10)]), 1, view)      # the hour that starts at 10:00: the same instant
    h2 = lab_baselines(tables, pd.DatetimeIndex([hc.hour(11)]), 2, view)
    for other in (h1, h2):
        assert other.iloc[0].to_numpy() == pytest.approx(h0.iloc[0].to_numpy(), nan_ok=True)
    assert h0.iloc[0]["b2_k3"] == pytest.approx((2.35 + 2.10 + 2.40) / 3) == pytest.approx(hc.PERSISTENCE_AT[hc.hour(10)].mean3)
    with pytest.raises(ValueError, match="horizon"):
        lab_baselines(tables, pd.DatetimeIndex([hc.hour(9)]), -1, view)


def test_the_baselines_need_the_history_the_features_need(tables, view):
    strict = dataclasses.replace(view, features=dataclasses.replace(view.features, min_fresh_history=4))
    frame = lab_baselines(tables, pd.DatetimeIndex([hc.hour(5), hc.hour(6)]), 0, strict)       # instants 6 (3 analyses) and 7 (4 analyses)
    assert frame.iloc[0].isna().all() and frame.iloc[1]["b1_persistence"] == 2.10 and frame.iloc[1]["b2_k3"] == pytest.approx((2.10 + 2.40 + 2.61) / 3)
    assert math.isnan(frame.iloc[1]["b2_k6"]), "six analyses have not arrived"


def test_the_cohort_is_a_fresh_target_with_the_history_and_the_readings_of_its_instant(tables, view):
    targets = pd.DatetimeIndex([hc.hour(k) for k in range(12)])
    fresh_hours = {0, 1, 2, 5, 7, 10, 11}
    mask = eligible(tables, targets, 0, view)
    assert mask.index.equals(targets) and mask.dtype == bool
    # the target hour k is issued at k + 1 and needs at least one analysis arrived (view: min_fresh_history = 1): sample hour <= k - 1
    assert [k for k in range(12) if mask.iloc[k]] == [k for k in range(12) if k in fresh_hours and k >= 1]
    strict = dataclasses.replace(view, features=dataclasses.replace(view.features, min_fresh_history=4))
    assert [k for k in range(12) if eligible(tables, targets, 0, strict).iloc[k]] == [k for k in range(12) if k in fresh_hours and k >= 6]
    thin = HourTables.from_hours(hc.case_hours(rows=5), view)       # the quick configuration asks for 6 rows in the hour of the readings
    assert not eligible(thin, targets, 0, view).any()
    gap = hc.case_hours().drop(index=[9]).reset_index(drop=True)    # no readings for hour 9: a target issued at 10:00 has none (H0 of hour 9... H1 of hour 10)
    holey = HourTables.from_hours(gap, view)
    assert not eligible(holey, pd.DatetimeIndex([hc.hour(10)]), 1, view).iloc[0] and eligible(holey, pd.DatetimeIndex([hc.hour(10)]), 0, view).iloc[0]


def test_the_analysis_and_the_readings_of_hours_are_given_by_the_tables(tables):
    hours = pd.DatetimeIndex([hc.hour(2), hc.hour(3), hc.hour(30)])
    values, fresh = tables.analysis_of(hours)
    assert values[0] == 2.40 and values[1] == 2.30 and math.isnan(values[2])
    assert fresh.tolist() == [True, False, False] and len(tables.hours) == 12 and tables.hours[0] == hc.hour(0)
    matrix, rows = tables.sensor_matrix(pd.DatetimeIndex([hc.hour(10), hc.hour(0), hc.hour(30)]))      # the hour before each instant
    assert matrix.shape == (3, 57) and rows.tolist()[0] == 12 and np.isnan(rows[1]) and np.isnan(matrix[1]).all() and np.isnan(matrix[2]).all()
    assert matrix[0].tolist() == [100.0 * j + 9 for j in range(57)]


# --- B0, B3, k and B* ----------------------------------------------------------------------------------------------------------------


def test_b0_is_the_mean_of_the_fresh_analyses_of_the_training_block():
    assert fit_b0(np.array([2.50, 2.61, 2.40, 2.10, 2.35, 2.20, 2.45])) == pytest.approx(hc.TRAINING_MEAN)
    with pytest.raises(ValueError, match="sin análisis"):
        fit_b0(np.array([]))


def test_b3_is_a_ridge_on_the_standardised_readings(view):
    rng = np.random.default_rng(7)
    x = pd.DataFrame(rng.normal(size=(40, 4)) * [1.0, 5.0, 0.1, 2.0] + [3.0, -2.0, 10.0, 0.0], columns=["a", "b", "c", "d"])
    y = 2.0 + 0.5 * x["a"] - 0.02 * x["b"] + rng.normal(size=40) * 0.05
    model = fit_b3(x, y.to_numpy(), dataclasses.replace(view, baselines=dataclasses.replace(view.baselines, ridge_alpha=3.0)))
    standardised = ((x - x.mean()) / x.std(ddof=0)).to_numpy()
    centred = y.to_numpy() - y.mean()
    coef = np.linalg.solve(standardised.T @ standardised + 3.0 * np.eye(4), standardised.T @ centred)
    assert model.predict(x) == pytest.approx(y.mean() + standardised @ coef)
    other = x.iloc[:5] * 2.0
    assert model.predict(other).shape == (5,) and list(model.columns) == ["a", "b", "c", "d"]
    with pytest.raises(ValueError, match="sin horas"):
        fit_b3(x.iloc[0:0], np.array([]), view)


def test_b2_picks_its_k_by_the_error_on_the_block_it_is_given_and_a_tie_goes_to_the_first_of_the_list(view):
    y = np.array([1.0, 2.0, 3.0, 4.0])
    frame = pd.DataFrame({"b2_k3": [1.0, 2.0, 3.0, 5.0], "b2_k6": [1.0, 2.0, 4.0, 4.0], "b2_k12": [1.0, 2.0, 3.0, 6.0], "b2_k24": [9.0, 9.0, 9.0, 9.0]})
    assert choose_k(frame, y, view) == 3, "k = 3 and k = 6 tie with an error of 0.25 each: the first of the list"
    better = frame.assign(b2_k12=[1.0, 2.0, 3.0, 4.0])
    assert choose_k(better, y, view) == 12
    near = frame.assign(b2_k6=[1.0, 2.0, 3.0, 5.0 - 4 * 4e-7])                    # an error of 4e-7 less than k = 3 over the four hours: inside the tie of 1e-6
    assert choose_k(near, y, view) == 3
    clear = frame.assign(b2_k6=[1.0, 2.0, 3.0, 5.0 - 4 * 4e-6])                   # 4e-6 less: not a tie
    assert choose_k(clear, y, view) == 6
    with pytest.raises(ValueError, match="sin horas"):
        choose_k(frame.iloc[0:0], np.array([]), view)


def test_the_strongest_baseline_is_the_one_with_the_lowest_error_on_v1_and_a_tie_goes_to_the_first_candidate(view):
    assert strongest(0.50, 0.49, view) == "b2_rolling" and strongest(0.49, 0.50, view) == "b1_persistence"
    assert strongest(0.5, 0.5 - 0.9e-6, view) == "b1_persistence", "a difference of less than 1e-6 is a tie and the persistence wins it"
    assert strongest(0.5, 0.5 - 2e-6, view) == "b2_rolling"
    flipped = dataclasses.replace(view, baselines=dataclasses.replace(view.baselines, strongest_candidates=("b2_rolling", "b1_persistence")))
    assert strongest(0.5, 0.5 - 0.9e-6, flipped) == "b2_rolling", "the tie is the order of the configuration"
    only = dataclasses.replace(view, baselines=dataclasses.replace(view.baselines, strongest_candidates=("b2_rolling",)))
    assert strongest(0.1, 0.9, only) == "b2_rolling"


# --- the fit on the fixture: what each parameter may learn from (AC14, AC17) -----------------------------------------------------------


@pytest.fixture(scope="module")
def fixture_tables(canonical, quick_cfg) -> HourTables:
    return HourTables.from_hours(canonical.hours, quick_cfg)


@pytest.fixture(scope="module")
def fit(fixture_tables, quick_cfg):
    return fit_baselines(fixture_tables, quick_cfg)


def mutated(canonical, cfg, blocks: set[str], seed: int) -> HourTables:
    """The fixture's hours with the silica, the feed and the aggregates of every hour of `blocks` replaced by other numbers."""
    hours = canonical.hours.copy()
    where = block_of(pd.DatetimeIndex(hours["hour"]), cfg).isin(blocks).to_numpy()
    rng = np.random.default_rng(seed)
    numeric = ["silica_pct", "feed_silica_pct", "feed_iron_pct", *AGGREGATE_COLUMNS]
    hours.loc[where, numeric] = hours.loc[where, numeric].to_numpy() * rng.uniform(0.5, 1.5, size=(int(where.sum()), len(numeric))) + rng.normal(size=(int(where.sum()), len(numeric)))
    return HourTables.from_hours(hours, cfg)


def test_the_fit_reports_each_horizon_with_its_k_its_strongest_and_its_errors_on_v1(fit, quick_cfg):
    assert sorted(fit.b2_k) == sorted(fit.b_star) == sorted(fit.b3) == sorted(fit.mae_v1) == list(quick_cfg.evaluation.horizons) == [0, 1, 2]
    for horizon in (0, 1, 2):
        assert fit.b2_k[horizon] in quick_cfg.baselines.rolling_k and fit.b_star[horizon] in quick_cfg.baselines.strongest_candidates
        errors = fit.mae_v1[horizon]
        assert set(errors) == {"b0_train_mean", "b1_persistence", "b2_rolling", "b3_ridge_sensors"} and all(v > 0 for v in errors.values())
        assert fit.b_star[horizon] == strongest(errors["b1_persistence"], errors["b2_rolling"], quick_cfg)
        assert fit.cohort_v1[horizon] > 100
    assert 1.0 < fit.b0_mean < 4.0


def test_v1_errors_of_the_persistence_are_those_of_a_plain_loop_over_the_truth(fit, fixture_truth, quick_cfg):
    """An independent computation of the persistence of H0 on V1: for each fresh hour of V1 with enough history and readings, the latest fresh
    analysis whose sample hour is at most the target hour minus the latency (the target hour closes at ``target + 1``)."""
    table = fixture_truth.hours
    s, latency, history = quick_cfg.split, quick_cfg.lab.latency_hours, quick_cfg.features.min_fresh_history
    fresh_hours = table.index[table["state"] == "fresh"]
    fresh_silica = table.loc[fresh_hours, "silica"].to_numpy()
    arrival = (fresh_hours + latency * HOUR).to_numpy()                 # sorted: the analysis of a sample hour arrives latency hours after it
    errors = []
    for target in table.index[(table.index >= s.v1_first) & (table.index <= s.v1_last) & (table["state"] == "fresh")]:
        known = int(np.searchsorted(arrival, np.datetime64(target + HOUR), side="right"))       # the target hour closes at target + 1 hour
        if known < history or table.at[target, "rows"] < quick_cfg.hours.min_rows_per_hour:
            continue
        errors.append(abs(fresh_silica[known - 1] - table.at[target, "silica"]))
    assert len(errors) == fit.cohort_v1[0] and fit.mae_v1[0]["b1_persistence"] == pytest.approx(float(np.mean(errors)), abs=1e-9)


def same_b3(a, b) -> bool:
    return (a.columns == b.columns and np.array_equal(a.pipeline[0].mean_, b.pipeline[0].mean_) and np.array_equal(a.pipeline[0].scale_, b.pipeline[0].scale_)
            and np.array_equal(a.pipeline[1].coef_, b.pipeline[1].coef_) and a.pipeline[1].intercept_ == b.pipeline[1].intercept_)


def test_b0_and_b3_learn_from_the_training_block_only(fit, canonical, quick_cfg):
    changed = fit_baselines(mutated(canonical, quick_cfg, {"valid_v1", "valid_v2", "test", "purge_1", "purge_v", "purge_2"}, seed=1), quick_cfg)
    assert changed.b0_mean == fit.b0_mean and all(same_b3(changed.b3[h], fit.b3[h]) for h in (0, 1, 2)), "nothing after the training block moves B0 or B3"
    assert changed.mae_v1 != fit.mae_v1, "the probe has teeth: V1's values are read by the errors that choose k and B*"
    training = fit_baselines(mutated(canonical, quick_cfg, {"train"}, seed=2), quick_cfg)
    assert training.b0_mean != fit.b0_mean and not same_b3(training.b3[0], fit.b3[0]), "and they do move with the training block"


def test_k_and_the_strongest_come_from_v1_only(fit, canonical, quick_cfg):
    later = fit_baselines(mutated(canonical, quick_cfg, {"valid_v2", "test", "purge_v", "purge_2"}, seed=3), quick_cfg)
    assert later.b2_k == fit.b2_k and later.b_star == fit.b_star and later.mae_v1 == fit.mae_v1 and later.cohort_v1 == fit.cohort_v1
    v1 = fit_baselines(mutated(canonical, quick_cfg, {"valid_v1"}, seed=4), quick_cfg)
    assert v1.mae_v1 != fit.mae_v1 and v1.b0_mean == fit.b0_mean, "V1's own values are what k and B* are chosen on"


def test_a_history_shorter_than_the_largest_k_is_refused_before_anything_is_fitted(fixture_tables, quick_cfg):
    """B2 is judged on the hours of the models, which need ``min_fresh_history`` analyses: a history shorter than the largest k would leave B2's cohort
    different from theirs, so ``fit_baselines`` stops at the configuration, naming both keys and both numbers, before it reads an hour."""
    largest = max(quick_cfg.baselines.rolling_k)
    short = dataclasses.replace(quick_cfg, features=dataclasses.replace(quick_cfg.features, min_fresh_history=largest - 1))
    with pytest.raises(ValueError, match=r"min_fresh_history \(23\).*rolling_k \(24\)") as caught:
        fit_baselines(fixture_tables, short)
    assert "[features]" in str(caught.value) and "[baselines]" in str(caught.value) and "mismas horas" in str(caught.value)
    assert fit_baselines(fixture_tables, dataclasses.replace(quick_cfg, features=dataclasses.replace(quick_cfg.features, min_fresh_history=largest))).b0_mean > 0
