"""The tracking of the issued estimates (U13; RF17, D22; AC21): what the control room would see, hour by hour. An estimate is joined with its analysis only once the
analysis has arrived (``available_at <= as_of``, the arrival inclusive), and never before; the error of the model, of the persistence and of B* and whether the range
held it are computed from that join; nothing that was issued changes. The hand case is ``tests/fixtures/hand_cases.tracking_case``: three estimates of H0 whose
analyses arrive at 12:00, 13:00 and 14:00, with the numbers of the errors written here by hand."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from flotsilica.registry import register_model, sealed_view
from flotsilica.scoring import RunMeta
from flotsilica.tracking import TRACKING_COLUMNS, track, tracking_at
from flotsilica.warehouse import apply_schema, connect
from tests.fixtures import hand_cases as hc
from tests.fixtures.history import SOURCE_SHA256, copy_history, stamp

HASH = "cd" * 32

# (low, high, persistence, B*) of the three estimates of the hand case, and what each error is by hand: the estimate of hour k and the analysis that arrives two hours later
#   h10: estimate 2.1, analysis 2.0 -> error 0.1; persistence 2.0 -> 0.0; B* 2.05 -> 0.05; the range 1.9 to 2.4 holds 2.0
#   h11: estimate 2.3, analysis 2.2 -> error 0.1; persistence 2.4 -> 0.2; B* 2.2  -> 0.0;  the range 2.0 to 2.6 holds 2.2
#   h12: estimate 2.2, analysis 2.4 -> error 0.2; persistence 2.1 -> 0.3; B* 2.3  -> 0.1;  the range 2.0 to 2.35 does not hold 2.4
EXTRA = {10: (1.9, 2.4, 2.0, 2.05), 11: (2.0, 2.6, 2.4, 2.2), 12: (2.0, 2.35, 2.1, 2.3)}
BY_HAND = {  # k -> (actual, abs_error, abs_error_persistence, abs_error_b_star, covered)
    10: (2.0, 0.1, 0.0, 0.05, True), 11: (2.2, 0.1, 0.2, 0.0, True), 12: (2.4, 0.2, 0.3, 0.1, False)}


@pytest.fixture(scope="module")
def view(quick_cfg):
    return sealed_view(quick_cfg, SOURCE_SHA256)


def at(k: int) -> str:
    return stamp(hc.hour(k))


def open_warehouse(path: Path) -> sqlite3.Connection:
    """An empty warehouse with one registered model and one delivery, for the rows a test writes by hand."""
    conn = connect(path)
    apply_schema(conn)
    register_model(conn, model_version="v1", trained_as_of=at(0), artifact_name="v1.pkl", artifact_sha256=HASH, config_sha256=HASH, models=[], selection={},
                   valid_predictions_sha256=HASH)
    conn.execute("INSERT INTO deliveries VALUES ('D', 'daily', ?, ?, ?, 0, 0, ?, 'loaded', 'r1')", (at(0), at(30), at(31), HASH))
    return conn


def add_analysis(conn: sqlite3.Connection, k: int, silica: float, state: str = "fresh") -> None:
    conn.execute("INSERT INTO lab_hours VALUES (?, 'D', 12, 0, ?, 55.0, 4.0, 60.0, ?, 3.0, 3.0, ?)", (at(k), silica, state, stamp(hc.hour(k + hc.LATENCY_HOURS))))


def add_estimate(conn: sqlite3.Connection, k: int, horizon: int = 0, *, estimate: float | None = 2.0, low: float = 1.0, high: float = 3.0, persistence: float = 2.0,
                 b_star: float = 2.0, status: str = "ok") -> None:
    issue_at = hc.hour(k) + timedelta(hours=1 - horizon)
    numbers = (estimate, low, high, persistence, b_star, "b1_persistence") if status == "ok" else (None,) * 6
    reason = None if status == "ok" else "sin análisis"
    conn.execute("INSERT INTO estimates VALUES (?, ?, ?, 'r1', 'v1', ?, ?, ?, ?, ?, ?, ?, ?, 'test', 0)",
                 (at(k), horizon, stamp(issue_at), status, reason, *numbers))


@pytest.fixture
def hand(tmp_path):
    """The hand case in a warehouse: the three estimates (with their ranges, persistence and B*) and the three analyses, all already stored."""
    case = hc.tracking_case()
    conn = open_warehouse(tmp_path / "hand.sqlite")
    for estimate in case.estimates.itertuples():
        k = int((estimate.target_hour - hc.DAY) / timedelta(hours=1))
        low, high, persistence, b_star = EXTRA[k]
        add_estimate(conn, k, estimate=estimate.estimate, low=low, high=high, persistence=persistence, b_star=b_star)
    for analysis in case.analyses.itertuples():
        add_analysis(conn, int((analysis.sample_hour - hc.DAY) / timedelta(hours=1)), analysis.silica_pct)
    yield conn, case
    conn.close()


# --- the RED of U13 --------------------------------------------------------------------------------------------------------


def test_an_error_is_joined_only_once_its_analysis_has_arrived(hand, view):
    """D22, AC21: at each instant the rows are those whose analysis has arrived (the arrival inclusive), with the errors written by hand, although the warehouse
    already holds every analysis; before its arrival an estimate has no row, no actual and no error."""
    conn, case = hand
    for as_of, joined in case.as_of.items():
        table = tracking_at(conn, as_of, view)
        assert list(table.columns) == list(TRACKING_COLUMNS) and len(table) == joined, as_of
        assert table["actual"].notna().sum() == joined
        assert set(table["target_hour"]) == {pd.Timestamp(h) for h in case.analyses[case.analyses["available_at"] <= as_of]["sample_hour"]}
    final = tracking_at(conn, hc.hour(14), view).set_index("target_hour")
    assert list(final["horizon"]) == [0, 0, 0] and set(final["as_of"]) == {pd.Timestamp(hc.hour(14))} and set(final["lab_state"]) == {"fresh"}
    for k, (actual, error, persistence, b_star, covered) in BY_HAND.items():
        row = final.loc[pd.Timestamp(hc.hour(k))]
        assert row["actual"] == pytest.approx(actual) and row["abs_error"] == pytest.approx(error)
        assert row["abs_error_persistence"] == pytest.approx(persistence) and row["abs_error_b_star"] == pytest.approx(b_star)
        assert bool(row["covered"]) is covered
    # the first analysis arrives at 12:00 and not a minute before: a tracking at 11:59:59 has nothing, one at 12:00:00 has the hour 10
    assert tracking_at(conn, hc.hour(12) - timedelta(seconds=1), view).empty
    assert list(tracking_at(conn, hc.hour(12), view)["target_hour"]) == [pd.Timestamp(hc.hour(10))]


def test_a_held_or_interpolated_analysis_arrives_without_an_error(tmp_path, view):
    """D05: an analysis that is not fresh is no measurement: its estimate is tracked once it arrives, with its state and with no actual, no error and no coverage."""
    conn = open_warehouse(tmp_path / "states.sqlite")
    try:
        for k, state in ((10, "fresh"), (11, "held"), (12, "interpolated")):
            add_estimate(conn, k)
            add_analysis(conn, k, 2.0, state)
        table = tracking_at(conn, hc.hour(20), view).set_index("target_hour")
        assert list(table["lab_state"]) == ["fresh", "held", "interpolated"]
        assert list(table["actual"].notna()) == [True, False, False]
        for column in ("abs_error", "abs_error_persistence", "abs_error_b_star", "covered"):
            assert list(table[column].notna()) == [True, False, False], column
    finally:
        conn.close()


def test_an_estimate_without_numbers_and_a_hour_without_analysis_are_never_tracked(tmp_path, view):
    """A ``missing_inputs`` estimate has nothing to compare, and a target hour that has no analysis in the warehouse (outside the data) has nothing to join."""
    conn = open_warehouse(tmp_path / "gaps.sqlite")
    try:
        add_estimate(conn, 10)
        add_analysis(conn, 10, 2.0)
        add_estimate(conn, 11, status="missing_inputs")
        add_analysis(conn, 11, 2.2)
        add_estimate(conn, 12)                                     # no analysis of hour 12 is stored: a censored hour
        assert list(tracking_at(conn, hc.hour(20), view)["target_hour"]) == [pd.Timestamp(hc.hour(10))]
    finally:
        conn.close()


# --- the task ----------------------------------------------------------------------------------------------------------------


def rows_of(conn: sqlite3.Connection, table: str) -> list[tuple]:
    return conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()


def test_track_rebuilds_the_table_of_each_run_and_changes_nothing_that_was_issued(hand, view):
    """D22: ``track`` replaces the rows of the previous run with those of its instant (repeating an instant gives the same rows), reports its counts and leaves the
    estimates, which are insert-only, exactly as they were."""
    conn, _case = hand
    issued = rows_of(conn, "estimates")
    run = RunMeta("r2", "D", "daily", hc.hour(12), hc.hour(11))
    first = track(conn, run, view)
    assert rows_of(conn, "tracking") == [(at(10), 0, at(12), "r2", 2.0, "fresh", pytest.approx(0.1), pytest.approx(0.0), pytest.approx(0.05), 1)]
    assert first == {"as_of": at(12), "tracked": 1, "with_actual": 1, "without_actual": 0}
    later = track(conn, RunMeta("r3", "D", "daily", hc.hour(14), hc.hour(12)), view)
    assert later == {"as_of": at(14), "tracked": 3, "with_actual": 3, "without_actual": 0}
    stored = rows_of(conn, "tracking")
    assert [(r[0], r[3]) for r in stored] == [(at(10), "r3"), (at(11), "r3"), (at(12), "r3")] and [r[9] for r in stored] == [1, 1, 0]
    assert track(conn, RunMeta("r3", "D", "daily", hc.hour(14), hc.hour(12)), view) == later and rows_of(conn, "tracking") == stored
    assert rows_of(conn, "estimates") == issued and not conn.in_transaction


def test_the_tracking_table_refuses_a_row_that_says_something_inconsistent(hand):
    """The table itself keeps a fresh analysis with its actual and the errors with it: a row with an error and no actual is refused."""
    conn, _case = hand
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO tracking VALUES (?, 0, ?, 'r1', NULL, 'fresh', 0.1, 0.1, 0.1, 1)", (at(10), at(14)))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO tracking VALUES (?, 0, ?, 'r1', 2.0, 'held', 0.1, 0.1, 0.1, 1)", (at(10), at(14)))


def test_an_existing_warehouse_gets_the_tracking_table_and_keeps_its_rows(hand):
    """``apply_schema`` is what creates the table: a warehouse that was made before it has the other tables with their rows, and gets it without losing one."""
    conn, _case = hand
    before = {t: rows_of(conn, t) for t in ("estimates", "lab_hours", "model_registry")}
    conn.execute("DROP TABLE tracking")
    apply_schema(conn)
    assert conn.execute("SELECT COUNT(*) FROM tracking").fetchone()[0] == 0
    assert {t: rows_of(conn, t) for t in before} == before
    apply_schema(conn)                                              # idempotent


# --- the history ---------------------------------------------------------------------------------------------------------


def expected_keys(conn: sqlite3.Connection, as_of: datetime) -> dict[tuple[str, int], tuple[float | None, str]]:
    """What the tracking of `as_of` must hold, worked out in plain Python from the stored rows: ``(target hour, horizon) -> (actual, lab state)``."""
    now = stamp(as_of)
    labs = {hour: (silica, state, available) for hour, silica, state, available in conn.execute("SELECT hour, silica_pct, lab_state, available_at FROM lab_hours")}
    out = {}
    for target, horizon, issue_at in conn.execute("SELECT target_hour, horizon, issue_at FROM estimates WHERE status = 'ok'"):
        if target in labs and issue_at <= now and labs[target][2] <= now:
            silica, state, _available = labs[target]
            out[(target, horizon)] = (silica if state == "fresh" else None, state)
    return out


def test_the_tracking_of_every_run_of_the_history_is_the_join_of_what_had_arrived(small_history, view):
    """AC21 on the small history: at the instant of each run the tracking has exactly the issued estimates whose analysis had arrived, with its actual, and it grows
    as the runs go on; the last run's error is the absolute difference of the stored numbers."""
    conn = connect(small_history.paths.db)
    try:
        counts = []
        for run in small_history.runs:
            table = tracking_at(conn, run.as_of, small_history.sealed)
            wanted = expected_keys(conn, run.as_of)
            got = {(stamp(r.target_hour), r.horizon): (None if pd.isna(r.actual) else r.actual, r.lab_state) for r in table.itertuples()}
            assert got == wanted, run.run_key
            counts.append(len(table))
        assert counts == sorted(counts) and counts[0] < counts[-1] and counts[-1] > 0
        last = tracking_at(conn, small_history.runs[-1].as_of, small_history.sealed)
        stored = {(h, k): (e, p, b) for h, k, e, p, b in conn.execute("SELECT target_hour, horizon, estimate, persistence, b_star FROM estimates WHERE status = 'ok'")}
        for r in last.dropna(subset=["actual"]).itertuples():
            estimate, persistence, b_star = stored[(stamp(r.target_hour), r.horizon)]
            assert r.abs_error == pytest.approx(abs(estimate - r.actual)) and r.abs_error_persistence == pytest.approx(abs(persistence - r.actual))
            assert r.abs_error_b_star == pytest.approx(abs(b_star - r.actual))
    finally:
        conn.close()


def test_an_analysis_that_has_not_arrived_changes_nothing_of_the_tracking(small_history, view, tmp_path):
    """RNF06 (a), D06: the tracking of an instant reads nothing that arrives after it: changing the analyses that arrive later leaves the tracking of the earlier
    instant exactly as it was, and changing one that has arrived changes it."""
    h = copy_history(small_history, tmp_path / "perturbed")
    as_of = h.runs[1].as_of
    conn = connect(h.paths.db)
    try:
        before = tracking_at(conn, as_of, view)
        assert len(before) > 0
        conn.execute("UPDATE lab_hours SET silica_pct = silica_pct + 5.0, lab_state = 'fresh' WHERE available_at > ?", (stamp(as_of),))
        pd.testing.assert_frame_equal(tracking_at(conn, as_of, view), before)
        conn.execute("UPDATE lab_hours SET silica_pct = silica_pct + 5.0 WHERE available_at <= ?", (stamp(as_of),))
        assert not tracking_at(conn, as_of, view).equals(before)
    finally:
        conn.close()
