"""What is said at an instant (U10; RF16, D07, D21; M02, M04; AC21 in part): the estimate with its range, the persistence, B* and the other methods from what
had arrived, the reason a horizon has no estimate, the hours each run issues at, and the numbers that stop a run."""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from flotsilica.features import HourTables
from flotsilica.intervals import interval
from flotsilica.registry import load_registered_bundle
from flotsilica.scoring import METHOD_NAMES, EstimateError, RunMeta, issue_instants, score_issue
from tests.fixtures.tiny_model import tiny_bundle

HOUR = timedelta(hours=1)
FULL_INSTANT = datetime(2017, 3, 15, 12)          # sensors, a long laboratory history and the feed: every input is there
IN_THE_GAP = datetime(2017, 3, 20, 12)             # no readings of the hour that closed (the March gap)


@pytest.fixture(scope="module")
def bundle(small_history):
    conn = sqlite3.connect(small_history.paths.db)
    try:
        return load_registered_bundle(conn, small_history.paths.models, "v1")
    finally:
        conn.close()


@pytest.fixture(scope="module")
def tables(small_canonical, small_history):
    return HourTables.from_hours(small_canonical.hours, small_history.sealed)


def test_each_horizon_estimates_its_own_hour_with_what_the_instant_knew(bundle, tables, small_history):
    view, t = small_history.sealed, FULL_INSTANT
    estimates = score_issue(bundle, tables.inputs(t, view), view)
    assert [e.horizon for e in estimates] == [0, 1, 2]
    assert [e.target_hour for e in estimates] == [t - HOUR, t, t + HOUR] and all(e.issue_at == t and e.status == "ok" and e.reason is None for e in estimates)
    _hours, silica = tables.fresh_known(t)                     # the analyses that had arrived at t, written out here and not taken from the code
    for e, hm in zip(estimates, bundle.horizons, strict=True):
        persistence, b2 = silica[-1], float(np.mean(silica[-hm.b2_k:]))
        assert e.persistence == persistence and e.methods["b1_persistence"] == persistence and e.methods["b2_rolling"] == pytest.approx(b2)
        assert e.b_star_method == hm.b_star and e.b_star == (persistence if hm.b_star == "b1_persistence" else pytest.approx(b2))
        assert e.methods["b0_train_mean"] == bundle.b0_mean and set(e.methods) == set(METHOD_NAMES)
        low, high = interval(e.estimate, hm.half_width)
        assert (e.low, e.high) == (low, high) and e.low <= e.estimate <= e.high and e.methods["model"] == e.estimate
        assert all(np.isfinite(v) for v in e.methods.values())
    assert [e.block for e in estimates] == ["valid_v2"] * 3            # the windows of small_view: V2 is 03-15 04:00 to 03-16 05:00


def test_a_horizon_without_its_inputs_says_why_and_carries_no_number(bundle, tables, small_history):
    view = small_history.sealed
    gap = score_issue(bundle, tables.inputs(IN_THE_GAP, view), view)
    assert [(e.status, e.reason) for e in gap] == [("missing_inputs", "no_sensor_rows")] * 3
    assert all(e.estimate is None and e.low is None and e.high is None and e.persistence is None and e.b_star is None and e.methods == {} for e in gap)
    assert [e.target_hour for e in gap] == [IN_THE_GAP - HOUR, IN_THE_GAP, IN_THE_GAP + HOUR]
    early = score_issue(bundle, tables.inputs(datetime(2017, 3, 10, 12), view), view)          # a day and a half into the data: fewer than 24 analyses have arrived
    assert {(e.status, e.reason) for e in early} == {("missing_inputs", "short_lab_history")}
    few_rows = dataclasses.replace(view, hours=dataclasses.replace(view.hours, min_rows_per_hour=view.hours.rows_per_hour + 1))
    assert {(e.status, e.reason) for e in score_issue(bundle, tables.inputs(FULL_INSTANT, few_rows), few_rows)} == {("missing_inputs", "partial_below_minimum")}


def test_an_analysis_that_has_not_arrived_is_not_the_persistence(bundle, tables, small_history):
    """At the instant ``t`` the analysis of the hour ``t - 2`` has just arrived and the one of ``t - 1`` has not: the persistence is the former."""
    view, t = small_history.sealed, FULL_INSTANT
    by_hour = tables.fresh_known(t)
    last_sample = pd.Timestamp(by_hour[0][-1])
    assert last_sample <= pd.Timestamp(t) - 2 * HOUR
    assert all(e.persistence == by_hour[1][-1] for e in score_issue(bundle, tables.inputs(t, view), view))
    next_instant = score_issue(bundle, tables.inputs(t + HOUR, view), view)[0]
    later = tables.fresh_known(t + HOUR)
    assert next_instant.persistence == later[1][-1]


def test_an_hour_after_the_last_hour_of_the_data_is_censored_and_the_block_is_the_one_of_its_hour(bundle, tables, small_history):
    view = small_history.sealed
    ends = dataclasses.replace(view, hours=dataclasses.replace(view.hours, last_hour=datetime(2017, 3, 15, 12)))
    estimates = score_issue(bundle, tables.inputs(FULL_INSTANT, view), ends)
    assert [e.is_censored for e in estimates] == [False, False, True]            # the targets are the hours 11:00, 12:00 (the last one) and 13:00
    edge = score_issue(bundle, tables.inputs(datetime(2017, 3, 15, 4), view), view)          # the targets are 03:00 (V1) and 04:00, 05:00 (V2 starts at 04:00)
    assert [e.block for e in edge] == ["valid_v1", "valid_v2", "valid_v2"]


def test_an_estimate_or_a_range_that_is_not_a_number_stops_the_run_with_m04(bundle, tables, small_history):
    view = small_history.sealed
    broken = dataclasses.replace(bundle, horizons=(dataclasses.replace(bundle.horizons[0], half_width=float("nan")), *bundle.horizons[1:]))
    with pytest.raises(EstimateError, match="M04"):
        score_issue(broken, tables.inputs(FULL_INSTANT, view), view)
    with pytest.raises(EstimateError, match="M04"):
        score_issue(dataclasses.replace(bundle, b0_mean=float("inf")), tables.inputs(FULL_INSTANT, view), view)


def test_the_instants_a_run_issues_at_come_from_its_delivery():
    start = datetime(2017, 8, 1)
    launch = RunMeta("r1", "L2017-07-31", "launch", start)
    assert issue_instants(launch) == [datetime(2017, 7, 31, 23), start]
    daily = RunMeta("r2", "D2017-08-01", "daily", datetime(2017, 8, 2), start)
    instants = issue_instants(daily)
    assert len(instants) == 24 and instants[0] == datetime(2017, 8, 1, 1) and instants[-1] == datetime(2017, 8, 2) and len(set(instants)) == 24
    assert issue_instants(RunMeta("r3", "D2017-08-02T00", "daily", datetime(2017, 8, 2, 1), datetime(2017, 8, 2))) == [datetime(2017, 8, 2, 1)]
    assert issue_instants(RunMeta("r4", "C2017-09-10", "close", datetime(2017, 9, 10, 1), datetime(2017, 9, 10))) == []
    with pytest.raises(ValueError, match="entrega anterior"):
        issue_instants(RunMeta("r5", "D", "daily", start))
    with pytest.raises(ValueError, match="posterior"):
        issue_instants(RunMeta("r5", "D", "daily", start, start))
    with pytest.raises(ValueError, match="desconocido"):
        issue_instants(RunMeta("r5", "D", "weekly", start, start))


def test_a_model_that_reads_the_feed_needs_an_hour_whose_analysis_has_arrived(tables, small_history, quick_cfg):
    view = small_history.sealed
    inputs = tables.inputs(FULL_INSTANT, view)
    without_feed = dataclasses.replace(inputs, feed=None)
    with_feed_model, plain = tiny_bundle(quick_cfg, feature_set="fSLF"), tiny_bundle(quick_cfg)
    assert [e.status for e in score_issue(with_feed_model, inputs, view)] == ["ok"]
    assert [(e.status, e.reason) for e in score_issue(with_feed_model, without_feed, view)] == [("missing_inputs", "no_feed_hour")]
    assert [e.status for e in score_issue(plain, without_feed, view)] == ["ok"]            # the sets of the plain bundle do not read the feed


class Constant:
    """An estimator that always says `value` (what a fitted model would say for a case at the edge of the scale)."""

    def __init__(self, value: float) -> None:
        self.value = value

    def predict(self, matrix):
        return np.full(len(matrix), self.value)


def with_constant_model(bundle, value: float, half_width: float):
    hm = bundle.horizons[0]
    stub = dataclasses.replace(hm.estimator, estimator=Constant(value))
    return dataclasses.replace(bundle, horizons=(dataclasses.replace(hm, estimator=stub, half_width=half_width),))


def test_the_range_is_clipped_to_a_percentage_and_an_estimate_off_the_scale_is_m04(tables, small_history, quick_cfg):
    view = small_history.sealed
    inputs = tables.inputs(FULL_INSTANT, view)
    plain = tiny_bundle(quick_cfg)
    low_edge = score_issue(with_constant_model(plain, 1.0, 2.0), inputs, view)[0]
    assert (low_edge.estimate, low_edge.low, low_edge.high) == (1.0, 0.0, 3.0)
    high_edge = score_issue(with_constant_model(plain, 99.0, 2.0), inputs, view)[0]
    assert (high_edge.low, high_edge.high) == (97.0, 100.0)
    for off_the_scale in (-3.0, 101.0):                    # a percentage cannot be below 0 or above 100: the range could not hold the estimate
        with pytest.raises(EstimateError, match="M04.*no contiene"):
            score_issue(with_constant_model(plain, off_the_scale, 0.5), inputs, view)
