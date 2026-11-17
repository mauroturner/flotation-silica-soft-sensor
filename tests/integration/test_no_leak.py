"""No information after the issue instant (U07; RF09, RNF06 a-b; AC11): the features of every instant of the small fixture, from the warehouse
with everything loaded, are the ones from the warehouse truncated at that instant and are not moved by changing what the instant could not
know: the readings of the hours from it on, or the analyses that had not arrived. Exact equality, at every instant, the March gap included.

One pass over the instants (``probes``) builds the five warehouses of ``tests/fixtures/perturb.py`` instant by instant and the tests read its
results. U10 adds the estimates and their range to the same comparison: at one in three of the instants where every input is there and at one in twenty of the others, the
estimates of each horizon (with the range, the persistence, B* and the other methods) made from each changed warehouse are exactly those of the full one."""

from __future__ import annotations

import sqlite3
import types
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from flotsilica.features import HourTables, IssueInputs, design, feature_row, inputs_at
from flotsilica.scoring import score_issue
from tests.fixtures.tiny_model import tiny_bundle
from tests.fixtures.perturb import stamp, walk

HOUR = timedelta(hours=1)


def vector(series: pd.Series | None) -> np.ndarray | None:
    return None if series is None else series.to_numpy(dtype="float64")


def same_inputs(a: IssueInputs, b: IssueInputs) -> bool:
    def same_series(x, y) -> bool:
        return (x is None and y is None) or (x is not None and y is not None and list(x.index) == list(y.index) and np.array_equal(vector(x), vector(y), equal_nan=True))

    lab_a, lab_b = a.lab_history, b.lab_history
    return (a.issue_at == b.issue_at and same_series(a.sensors, b.sensors) and same_series(a.feed, b.feed) and list(lab_a.columns) == list(lab_b.columns)
            and len(lab_a) == len(lab_b) and lab_a["sample_hour"].tolist() == lab_b["sample_hour"].tolist()
            and np.array_equal(lab_a["silica_pct"].to_numpy(), lab_b["silica_pct"].to_numpy()) and lab_a["available_at"].tolist() == lab_b["available_at"].tolist())


def leaky_reading(conn: sqlite3.Connection, t: pd.Timestamp):
    """What a feature that read the hour that is just starting (instead of the one that closed) would see."""
    return conn.execute("SELECT amina_flow_mean FROM hour_aggregates WHERE hour = ?", (stamp(t),)).fetchone()


def leaky_analysis(conn: sqlite3.Connection, t: pd.Timestamp):
    """What a feature that read the analysis of the hour that just closed (which arrives later, with a latency of two hours) would see."""
    return conn.execute("SELECT silica_pct, lab_state FROM lab_hours WHERE hour = ?", (stamp(t - HOUR),)).fetchone()


@pytest.fixture(scope="module")
def probes(small_store, small_canonical, quick_cfg):
    tables = HourTables.from_hours(small_canonical.hours, quick_cfg)
    bundle = tiny_bundle(quick_cfg)          # a frozen model of one horizon, with its comparison models and B3: what the estimates are made with
    out = types.SimpleNamespace(instants=0, usable=0, no_sensors=0, table=[], truncated=[], readings=[], analyses=[], rows_differ=[],
                                teeth_readings=0, teeth_analyses=0, estimated_ok=0, estimated_missing=0, estimates_truncated=[], estimates_readings=[],
                                estimates_analyses=[], estimates_vary=set())
    for t, conns in walk(small_store, small_canonical.rows, small_canonical.hours, quick_cfg.lab.latency_hours):
        issue_at = t.to_pydatetime()
        base = inputs_at(conns["full"], issue_at, quick_cfg)
        base_row = feature_row(base, quick_cfg).to_numpy()
        out.instants += 1
        out.usable += int(not np.isnan(base_row).any())
        out.no_sensors += int(base.sensors is None)
        if not same_inputs(base, tables.inputs(issue_at, quick_cfg)):
            out.table.append(t)
        for name, bucket in (("truncated", out.truncated), ("future_readings", out.readings), ("future_analyses", out.analyses)):
            other = inputs_at(conns[name], issue_at, quick_cfg)
            if not same_inputs(base, other):
                bucket.append(t)
            elif name == "truncated" and not np.array_equal(base_row, feature_row(other, quick_cfg).to_numpy(), equal_nan=True):
                out.rows_differ.append((name, t))
        if (not np.isnan(base_row).any() and out.usable % 3 == 0) or out.instants % 20 == 0:
            base_estimates = score_issue(bundle, base, quick_cfg)
            out.estimated_ok += sum(e.status == "ok" for e in base_estimates)
            out.estimated_missing += sum(e.status != "ok" for e in base_estimates)
            out.estimates_vary.update(round(e.estimate, 6) for e in base_estimates if e.estimate is not None)
            for name, bucket in (("truncated", out.estimates_truncated), ("future_readings", out.estimates_readings), ("future_analyses", out.estimates_analyses)):
                other_estimates = score_issue(bundle, inputs_at(conns[name], issue_at, quick_cfg), quick_cfg)
                if not all(a.same_as(b) for a, b in zip(base_estimates, other_estimates, strict=True)):
                    bucket.append(t)
        # the probes have teeth: a feature that read what they change would see a difference
        out.teeth_readings += int(leaky_reading(conns["full"], t) != leaky_reading(conns["future_readings"], t))
        out.teeth_analyses += int(leaky_analysis(conns["full"], t) != leaky_analysis(conns["future_analyses"], t))
    return out


def test_the_probes_walk_every_instant_of_the_small_fixture_and_see_what_they_change(probes, small_canonical, quick_cfg):
    hours = small_canonical.hours["hour"]
    assert probes.instants == int((hours.iloc[-1] - hours.iloc[0]) / HOUR) + 2 > 400, "from the first hour to the one after the last"
    assert probes.no_sensors > 300, "the March gap and the hours around it have no readings to take, and the probes still run there"
    assert probes.usable > 100, "and there are instants with every one of the 67 features"
    assert probes.teeth_readings > 100 and probes.teeth_analyses > 100, "a feature that read the new hour or the analysis that has not arrived would differ"


def test_the_frame_and_the_warehouse_give_the_same_inputs_at_every_instant(probes):
    assert probes.table == []


def test_features_at_an_instant_equal_those_from_data_truncated_at_that_instant(probes):
    assert probes.truncated == [] and [r for r in probes.rows_differ if r[0] == "truncated"] == []


def test_readings_from_the_issue_hour_on_change_nothing_issued_at_that_instant(probes):
    assert probes.readings == [] and [r for r in probes.rows_differ if r[0] == "future_readings"] == []


def test_an_analysis_not_yet_arrived_changes_no_estimate(probes):
    """The features, and now the estimate with its range, the persistence, B* and the other methods of every horizon, are the same with the analyses that had
    not arrived changed; the same comparison is made with the warehouse cut at the instant and with the readings from the issue hour on changed."""
    assert probes.analyses == [] and [r for r in probes.rows_differ if r[0] == "future_analyses"] == []
    assert probes.estimates_analyses == [] and probes.estimates_readings == [] and probes.estimates_truncated == []
    assert probes.estimated_ok > 40 and probes.estimated_missing > 10 and len(probes.estimates_vary) > 10, "the comparison saw estimates, missing ones and many values"


def test_design_takes_each_target_at_the_instant_target_minus_horizon_plus_one_hour(small_store, small_canonical, quick_cfg):
    """The instant of a (target, horizon) is written out here, not taken from the code; the frame and the warehouse give the same inputs at every
    instant (``probes``), so comparing with the frame at every hour and horizon and with the warehouse at a sample covers both."""
    tables = HourTables.from_hours(small_canonical.hours, quick_cfg)
    conn = sqlite3.connect(small_store)
    try:
        hours = pd.DatetimeIndex(small_canonical.hours["hour"])[::3]       # a third of the hours: every kind of neighbourhood, a third of the time
        for horizon in (0, 1, 2):
            frame = design(tables, hours, horizon, quick_cfg)
            assert frame.index.equals(hours)
            for k, (target, row) in enumerate(zip(hours, frame.to_numpy(), strict=True)):
                issue_at = target + HOUR * (1 - horizon)
                expected = feature_row(tables.inputs(issue_at.to_pydatetime(), quick_cfg), quick_cfg).to_numpy()
                assert np.array_equal(row, expected, equal_nan=True), (horizon, target)
                if k % 5 == 0:
                    assert np.array_equal(row, feature_row(inputs_at(conn, issue_at.to_pydatetime(), quick_cfg), quick_cfg).to_numpy(), equal_nan=True), (horizon, target)
    finally:
        conn.close()


def test_estimates_are_identical_with_daily_and_ten_day_deliveries(small_history, small_history_one_batch):
    """The size of the deliveries changes no estimate (AC12, RNF06 g): the history in three deliveries of twelve hours and the one in a single delivery of
    twenty-five hours (the small fixture holds 38 hours after the gap, not ten days) issue exactly the same estimates, row for row and number for number,
    and so do the methods; only the run that issued them differs."""
    def table(history):
        conn = sqlite3.connect(history.paths.db)
        try:
            estimates = conn.execute("SELECT target_hour, horizon, issue_at, model_version, status, reason, estimate, low, high, persistence, b_star, b_star_method, "
                                     "block, is_censored FROM estimates ORDER BY target_hour, horizon").fetchall()
            methods = conn.execute("SELECT * FROM method_estimates ORDER BY target_hour, horizon, method").fetchall()
            return estimates, methods, [r[0] for r in conn.execute("SELECT DISTINCT run_key FROM estimates ORDER BY 1")]
        finally:
            conn.close()

    (est_a, methods_a, runs_a), (est_b, methods_b, runs_b) = table(small_history), table(small_history_one_batch)
    assert runs_a == ["r1", "r2", "r3", "r4"] and runs_b == ["r1", "r2"]
    assert len(est_a) == len(est_b) == 3 * (2 + 25) and est_a == est_b and methods_a == methods_b and len(methods_a) == 8 * len(est_a)
