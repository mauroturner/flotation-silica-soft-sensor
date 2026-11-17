"""The hand-written cases (U03): each expected value is checked here against a separate piece of arithmetic, so that a slip in
``tests/fixtures/hand_cases.py`` is found before the cases are trusted by the units that use them."""

from __future__ import annotations

import math
from datetime import timedelta

import numpy as np
import pytest

from tests.fixtures import hand_cases as hc


def test_the_freshness_case_follows_the_rule_of_d05_hour_by_hour():
    case = hc.freshness_case()
    hours, silica = list(case.first_rows["hour"]), list(case.first_rows["silica_pct"])
    assert len(hours) == 12 and list(case.is_ramp.index) == hours
    states = []
    for k in range(12):
        if k and case.is_ramp.iloc[k] and case.is_ramp.iloc[k - 1]:
            states.append("interpolated")
        elif k and silica[k] == silica[k - 1]:
            states.append("held")
        else:
            states.append("fresh")
    assert states == case.expected_states
    # the interpolated hours are on the line between the analyses at the two ends of the stretch: 2.40, 2.30, 2.20, 2.10
    assert silica[2:6] == pytest.approx([2.40 + (2.10 - 2.40) * j / 3 for j in range(4)])
    assert case.expected_states.count("fresh") == 7 and case.expected_states.count("held") == 3 and case.expected_states.count("interpolated") == 2


def test_the_fresh_analyses_arrive_two_hours_after_their_sample_hour():
    analyses = hc.fresh_analyses()
    assert list(analyses["sample_hour"]) == [hc.hour(k) for k in (0, 1, 2, 5, 7, 10, 11)]
    assert list(analyses["silica_pct"]) == [2.50, 2.61, 2.40, 2.10, 2.35, 2.20, 2.45]
    assert list(analyses["available_at"] - analyses["sample_hour"]) == [timedelta(hours=2)] * 7
    assert hc.TRAINING_MEAN == pytest.approx(float(analyses["silica_pct"].mean()))


def test_the_expected_features_of_an_instant_come_from_the_analyses_that_arrived():
    analyses = hc.fresh_analyses()
    for issue_at, expected in hc.PERSISTENCE_AT.items():
        arrived = analyses[analyses["available_at"] <= issue_at].sort_values("sample_hour")
        values = list(arrived["silica_pct"])[::-1]
        assert tuple(values[:3]) == pytest.approx(expected.last) and len(values) == expected.known
        assert expected.mean3 == pytest.approx(float(np.mean(values[:3])))
        newest = arrived["sample_hour"].iloc[-1]
        assert expected.age_h == (issue_at - timedelta(hours=hc.LATENCY_HOURS) - newest) / timedelta(hours=1)
    # the persistence of the instant 10:00 skips the held hour 8 and the interpolated ones
    assert hc.PERSISTENCE_AT[hc.hour(10)].last[0] == hc.freshness_case().first_rows["silica_pct"].iloc[7]


@pytest.mark.parametrize("case", hc.CONFORMAL_CASES)
def test_the_conformal_half_width_is_the_ceil_n_plus_1_times_coverage_smallest_residual(case):
    n = len(case.residuals)
    rank = math.ceil(round((n + 1) * case.coverage, 9))
    assert rank == case.rank and 1 <= rank <= n
    assert sorted(case.residuals)[rank - 1] == pytest.approx(case.half_width)


def test_the_metrics_case_numbers_are_the_arithmetic_of_its_twelve_hours():
    case = hc.metrics_case()
    actual, model, persistence = (np.array(v) for v in (case.actual, case.model, case.persistence))
    assert len(case.hours) == 12 and persistence[1:] == pytest.approx(actual[:-1])      # the persistence is the previous actual
    error, base_error = model - actual, persistence - actual
    assert np.abs(error).mean() == pytest.approx(case.mae_model) and np.abs(base_error).mean() == pytest.approx(case.mae_persistence)
    assert error.mean() == pytest.approx(case.bias_model)
    assert (np.abs(error) <= case.half_width + 1e-12).mean() == pytest.approx(case.coverage)
    assert case.mae_model - case.mae_persistence == pytest.approx(case.mae_difference) == pytest.approx(-0.125)
    days = np.array(case.day_of)
    picked = np.concatenate([np.flatnonzero(days == d) for d in case.day_pick])
    assert len(picked) == 12
    ratio = (np.abs(error[picked]).sum() - np.abs(base_error[picked]).sum()) / len(picked)
    assert ratio == pytest.approx(case.day_pick_difference) == pytest.approx(-0.1)
    per_day = [(round(float(np.abs(error[days == d]).sum()), 9), round(float(np.abs(base_error[days == d]).sum()), 9)) for d in range(3)]
    assert per_day == [(0.6, 0.9), (0.5, 1.1), (0.5, 1.1)]


def test_the_tracking_case_joins_an_analysis_only_from_its_arrival_instant():
    case = hc.tracking_case()
    assert len(case.estimates) == len(case.analyses) == 3
    for as_of, joined in case.as_of.items():
        arrived = case.analyses[case.analyses["available_at"] <= as_of]
        assert len(arrived) == joined, as_of
    assert list(case.analyses["available_at"] - case.analyses["sample_hour"]) == [timedelta(hours=hc.LATENCY_HOURS)] * 3
