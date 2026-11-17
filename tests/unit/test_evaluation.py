"""The metrics and the resampling by days (U08; D17; AC22 in part): the numbers of a hand case of twelve hours, and the interval that
resamples whole days with a seed."""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from flotsilica.evaluation import day_bootstrap, metrics
from tests.fixtures import hand_cases as hc

HOUR = timedelta(hours=1)


def reference_difference(abs_a: np.ndarray, abs_b: np.ndarray, days: np.ndarray, pick: tuple) -> float:
    """MAE(a) - MAE(b) over the hours of the days in `pick` (a day twice counts twice), written with the hours selected one by one."""
    chosen = np.concatenate([np.flatnonzero(days == day) for day in pick])
    return float(abs_a[chosen].mean() - abs_b[chosen].mean())


def test_the_metrics_of_twelve_hours_are_the_hand_numbers():
    case = hc.metrics_case()
    actual, model = np.array(case.actual), np.array(case.model)
    result = metrics(actual, model, model - case.half_width, model + case.half_width)
    assert result.hours == 12 and result.mae == pytest.approx(case.mae_model) and result.bias == pytest.approx(case.bias_model)
    assert result.rmse == pytest.approx(np.sqrt(0.34 / 12)) and result.coverage == pytest.approx(case.coverage)
    persistence = metrics(actual, np.array(case.persistence))
    assert persistence.mae == pytest.approx(case.mae_persistence) and persistence.coverage is None
    assert persistence.mae - result.mae == pytest.approx(-case.mae_difference)


def test_the_metrics_refuse_what_is_not_a_set_of_hours_with_numbers():
    with pytest.raises(ValueError, match="sin horas"):
        metrics(np.array([]), np.array([]))
    with pytest.raises(ValueError, match="misma cantidad"):
        metrics(np.array([1.0, 2.0]), np.array([1.0]))
    with pytest.raises(ValueError, match="finitos"):
        metrics(np.array([1.0, np.nan]), np.array([1.0, 2.0]))
    with pytest.raises(ValueError, match="el rango"):
        metrics(np.array([1.0]), np.array([1.0]), np.array([0.0]), None)
    assert metrics(np.array([2.0]), np.array([2.0]), np.array([2.0]), np.array([2.0])).coverage == 1.0, "the ends of the range are inside it"


def test_bootstrap_resamples_whole_days_and_is_seeded():
    case = hc.metrics_case()
    actual, model, persistence = np.array(case.actual), np.array(case.model), np.array(case.persistence)
    days = np.array(case.day_of)
    abs_model, abs_persistence = np.abs(model - actual), np.abs(persistence - actual)
    assert reference_difference(abs_model, abs_persistence, days, case.day_pick) == pytest.approx(case.day_pick_difference), "the hand resample"
    result = day_bootstrap(model - actual, persistence - actual, days, n=300, seed=0)
    # the draws: days 0..2 with replacement, as many as there are days, by numpy's generator with the seed (D17)
    picks = np.random.default_rng(0).integers(0, 3, size=(300, 3))
    expected = np.array([reference_difference(abs_model, abs_persistence, days, tuple(p)) for p in picks])
    assert result.differences == pytest.approx(expected, abs=1e-12) and result.resamples == 300
    assert result.difference == pytest.approx(case.mae_difference)
    assert (result.ci_low, result.ci_high) == pytest.approx(tuple(np.percentile(expected, [2.5, 97.5])))
    # the same seed gives the same, another seed another; the order of the hours and the labels of the days do not matter
    again = day_bootstrap(model - actual, persistence - actual, days, n=300, seed=0)
    assert np.array_equal(again.differences, result.differences) and (again.ci_low, again.ci_high) == (result.ci_low, result.ci_high)
    assert not np.array_equal(day_bootstrap(model - actual, persistence - actual, days, n=300, seed=1).differences, result.differences)
    order = np.random.default_rng(5).permutation(12)
    shuffled = day_bootstrap((model - actual)[order], (persistence - actual)[order], days[order], n=300, seed=0)
    assert np.allclose(shuffled.differences, result.differences, atol=1e-12) and np.array_equal(
        day_bootstrap(model - actual, persistence - actual, days + 100, n=300, seed=0).differences, result.differences)
    # errors may come with their sign: only their size counts
    assert np.array_equal(day_bootstrap(np.abs(model - actual), -np.abs(persistence - actual), days, n=300, seed=0).differences, result.differences)


def test_a_bootstrap_of_one_day_at_a_time_has_only_the_values_of_whole_days():
    """Four hours a day with an error that is different on each hour: the resample difference is always built from entire days, never from hours."""
    abs_a = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
    abs_b = np.array([0.4, 0.3, 0.2, 0.1, 0.8, 0.7, 0.6, 0.5])
    days = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    result = day_bootstrap(abs_a, abs_b, days, n=200, seed=3)
    possible = {round(reference_difference(abs_a, abs_b, days, pick), 12) for pick in ((0, 0), (0, 1), (1, 0), (1, 1))}
    assert set(np.round(result.differences, 12)) <= possible and len(set(np.round(result.differences, 12))) == len(possible)


def test_the_difference_of_a_resample_is_a_quotient_of_sums_over_the_hours_it_holds_when_the_days_have_different_sizes():
    abs_a = np.array([0.1, 0.9, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
    abs_b = np.array([0.5, 0.1, 0.3, 0.2, 0.9, 0.4, 0.1, 0.2, 0.3, 0.6])
    days = np.array([0, 0, 1, 1, 1, 2, 2, 2, 2, 2])          # 2, 3 and 5 hours
    result = day_bootstrap(abs_a, abs_b, days, n=100, seed=9)
    picks = np.random.default_rng(9).integers(0, 3, size=(100, 3))
    expected = np.array([reference_difference(abs_a, abs_b, days, tuple(p)) for p in picks])
    assert result.differences == pytest.approx(expected, abs=1e-12)
    daily_means = np.array([(abs_a[days == d] - abs_b[days == d]).mean() for d in range(3)])
    assert not np.allclose(result.differences, np.array([daily_means[list(p)].mean() for p in picks])), "it is not the mean of the daily means"


def test_the_interval_refuses_what_cannot_be_resampled():
    with pytest.raises(ValueError, match="misma cantidad"):
        day_bootstrap(np.array([1.0, 2.0]), np.array([1.0]), np.array([0, 1]), n=10, seed=0)
    with pytest.raises(ValueError, match="sin horas"):
        day_bootstrap(np.array([]), np.array([]), np.array([]), n=10, seed=0)
    with pytest.raises(ValueError, match="finitos"):
        day_bootstrap(np.array([np.nan]), np.array([1.0]), np.array([0]), n=10, seed=0)
    with pytest.raises(ValueError, match="remuestras"):
        day_bootstrap(np.array([1.0]), np.array([1.0]), np.array([0]), n=0, seed=0)
    one = day_bootstrap(np.array([0.5, 0.5]), np.array([0.25, 0.25]), np.array([0, 0]), n=20, seed=0)
    assert set(one.differences) == {0.25} and (one.ci_low, one.ci_high) == (0.25, 0.25), "one day: every resample is that day"


# --- the evaluation of the test: frames in, figures and criteria out (U11; AC22) ------------------------------------------------------------------------


def test_twelve_hour_hand_case(quick_cfg):
    """The twelve hours of the hand case go through the evaluation as the three hours of H0 would: the numbers written by hand are the ones it gives."""
    from flotsilica.evaluation import evaluate_frames, figures

    case = hc.metrics_case()
    frame = hc.metrics_frame()
    view = dataclasses.replace(quick_cfg, evaluation=dataclasses.replace(quick_cfg.evaluation, bootstrap_resamples=300, horizons=(0,)),
                               split=dataclasses.replace(quick_cfg.split, test_first=hc.DAY))
    result = evaluate_frames({0: frame}, view)
    figs = figures(result)["horizons"]["0"]
    assert figs["hours"] == 12
    model, persistence = figs["methods"]["model"], figs["methods"]["b1_persistence"]
    assert model["mae"] == pytest.approx(case.mae_model) and model["bias"] == pytest.approx(case.bias_model) and model["rmse"] == pytest.approx(np.sqrt(0.34 / 12))
    assert model["coverage"] == pytest.approx(case.coverage) and persistence["mae"] == pytest.approx(case.mae_persistence) and persistence["coverage"] is None
    assert figs["methods"]["b_star"] == persistence and figs["methods"]["b0_train_mean"]["mae"] == pytest.approx(np.mean(np.abs(np.array(case.actual) - 2.3)))
    boot = figures(result)["bootstraps"]["model_vs_b_star.h0"]
    expected = day_bootstrap(np.array(case.model) - np.array(case.actual), np.array(case.persistence) - np.array(case.actual), frame.index.normalize().to_numpy(), n=300, seed=0)
    assert boot["difference"] == pytest.approx(case.mae_difference) and boot["resamples"] == 300
    assert boot["ci_low"] == pytest.approx(expected.ci_low) and boot["ci_high"] == pytest.approx(expected.ci_high)
    assert [w["week"] for w in result.weekly if w["method"] == "model"] == ["2017-05-01"] and result.weekly[0]["hours"] == 12


def test_the_error_by_week_counts_weeks_of_seven_days_from_the_first_hour_of_the_test_and_a_horizon_without_hours_has_no_figures(quick_cfg):
    from flotsilica.evaluation import evaluate_frames, figures

    start = quick_cfg.split.test_first
    hours = pd.date_range(start, periods=24 * 10, freq="h", name="target_hour")          # ten days: a week of seven and a last one of three
    rng = np.random.default_rng(1)
    actual = 2.0 + rng.normal(scale=0.3, size=len(hours))
    frame = pd.DataFrame({"actual": actual, "low": actual - 1, "high": actual + 1, **{m: actual + {"model": 0.1, "b1_persistence": 0.5}.get(m, 0.3) for m in (
        "model", "b_star", "b0_train_mean", "b1_persistence", "b2_rolling", "b3_ridge_sensors", "best_sensors_only", "best_lab_only", "best_with_sensors")}}, index=hours)
    result = evaluate_frames({0: frame, 1: frame.iloc[:0]}, dataclasses.replace(quick_cfg, evaluation=dataclasses.replace(quick_cfg.evaluation, bootstrap_resamples=50)))
    model = [w for w in result.weekly if w["method"] == "model"]
    assert [(w["week"], w["hours"]) for w in model] == [(start.strftime("%Y-%m-%d"), 168), ((start + timedelta(days=7)).strftime("%Y-%m-%d"), 72)]
    assert all(w["mae"] == pytest.approx(0.1) for w in model) and {w["horizon"] for w in result.weekly} == {0} and {w["method"] for w in result.weekly} == {"model", "b1_persistence", "b_star"}
    figs = figures(result)
    assert figs["horizons"]["1"] == {"hours": 0, "methods": {}} and "model_vs_b_star.h1" not in figs["bootstraps"] and "model_vs_b_star.h0" in figs["bootstraps"]
    assert figs["bootstraps"]["model_vs_b_star.h0"]["difference"] == pytest.approx(0.1 - 0.3) and figs["bootstraps"]["model_vs_b_star.h0"]["ci_high"] < 0
    assert figs["bootstraps"]["model_vs_b1_persistence.h0"]["difference"] == pytest.approx(0.1 - 0.5), "B* and the persistence are two methods: each has its own comparison"
    assert set(figs["bootstraps"]) == {"model_vs_b_star.h0", "model_vs_b1_persistence.h0", "best_sensors_only_vs_b0_train_mean.h0", "best_with_sensors_vs_best_lab_only.h0"}


def test_a_criterion_is_made_of_the_figures_alone_so_the_same_figures_give_the_same_criteria():
    from flotsilica.evaluation import criteria_of

    again = [c.seal_entry() for c in criteria_of(hc.losing_figures(), hc.SEALED_CRITERIA)]
    assert again == [c.seal_entry() for c in criteria_of(hc.losing_figures(), hc.SEALED_CRITERIA)] and [e["id"] for e in again] == [f"C{i:02d}" for i in range(1, 11)]
    c02 = next(e for e in again if e["id"] == "C02")
    assert (c02["value"], c02["baseline_value"], c02["ci_low"], c02["ci_high"], c02["passed"]) == (0.537, 0.533, -0.03, 0.04, False)
    assert next(e for e in again if e["id"] == "C07")["passed"] is True
