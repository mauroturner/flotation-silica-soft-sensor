"""No information after the issue instant (U07; RF09, RNF06 a-b; AC11): the features of every instant of the small fixture, from the warehouse
with everything loaded, are the ones from the warehouse truncated at that instant and are not moved by changing what the instant could not
know: the readings of the hours from it on, or the analyses that had not arrived. Exact equality, at every instant, the March gap included.

One pass over the instants (``probes``) builds the five warehouses of ``tests/fixtures/perturb.py`` instant by instant and the tests read its
results; the estimates and the range join the same comparison in U10, when they exist."""

from __future__ import annotations

import sqlite3
import types
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from flotsilica.features import HourTables, IssueInputs, design, feature_row, inputs_at
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
    out = types.SimpleNamespace(instants=0, usable=0, no_sensors=0, table=[], truncated=[], readings=[], analyses=[], rows_differ=[],
                                teeth_readings=0, teeth_analyses=0)
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
    """Today the estimate is its features (the models come with U09 and U10, which add the estimate and its range to this comparison)."""
    assert probes.analyses == [] and [r for r in probes.rows_differ if r[0] == "future_analyses"] == []


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
