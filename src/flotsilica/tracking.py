"""The tracking of the issued estimates (RF17, AC21; D22; plan, section 17): what the control room would see, hour by hour.

For every issued estimate with numbers whose target hour has an analysis that had **arrived** at the instant (``available_at <= as_of``, the arrival inclusive, D06),
the tracking joins it with that analysis: the ``actual`` (the analysis if it is fresh; none, with its ``lab_state``, if it is held or interpolated: D05, no measurement),
the absolute error of the model, of the persistence and of B* and whether the range held the actual. An estimate whose analysis has not arrived has no row: the join
reads ``lab_hours`` through its stored arrival and nothing later, so an analysis that arrives after the instant cannot change the tracking of the instant. The tracking
changes nothing of what was issued: the model, the range and B* are those of the estimate, which is insert-only (D22).

``track`` is the task: it rebuilds the table of the run (the tracking is derived, so every run replaces it whole; repeating an instant gives the same rows).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

import pandas as pd

from flotsilica.scoring import RunMeta

TRACKING_COLUMNS = ("target_hour", "horizon", "as_of", "actual", "lab_state", "abs_error", "abs_error_persistence", "abs_error_b_star", "covered")
STAMP = "%Y-%m-%d %H:%M:%S"
_JOIN = (
    "SELECT e.target_hour, e.horizon, e.estimate, e.low, e.high, e.persistence, e.b_star, l.silica_pct, l.lab_state "
    "FROM estimates AS e JOIN lab_hours AS l ON l.hour = e.target_hour "
    "WHERE e.status = 'ok' AND l.available_at <= :as_of ORDER BY e.target_hour, e.horizon"
)


def tracking_at(conn: sqlite3.Connection, as_of: datetime, view: Any) -> pd.DataFrame:
    """The tracking at `as_of` (see the module): one row per issued estimate with numbers whose analysis had arrived, in the order of the target hour and the horizon,
    with the columns of ``TRACKING_COLUMNS``. ``actual`` and the errors are NaN, and ``covered`` is missing, when the analysis is not fresh.

    `view` is the sealed view, which every calculation of an instant receives (D19); the join needs nothing of it, because the arrival is stored with each analysis."""
    del view
    instant = pd.Timestamp(as_of)
    frame = pd.read_sql_query(_JOIN, conn, params={"as_of": instant.strftime(STAMP)})
    fresh = frame["lab_state"].eq("fresh")
    actual = frame["silica_pct"].where(fresh)
    out = pd.DataFrame({
        "target_hour": pd.to_datetime(frame["target_hour"], format=STAMP), "horizon": frame["horizon"].astype("int64"), "as_of": instant, "actual": actual,
        "lab_state": frame["lab_state"], "abs_error": (frame["estimate"] - actual).abs(), "abs_error_persistence": (frame["persistence"] - actual).abs(),
        "abs_error_b_star": (frame["b_star"] - actual).abs(),
        "covered": ((frame["low"] <= actual) & (actual <= frame["high"])).where(fresh).astype("boolean"),
    })
    return out[list(TRACKING_COLUMNS)].reset_index(drop=True)


def track(conn: sqlite3.Connection, run: RunMeta, view: Any) -> dict[str, Any]:
    """The task: replace the table ``tracking`` with the tracking at the run's ``as_of``, in one transaction, and say what it holds: ``as_of``, ``tracked`` (rows),
    ``with_actual`` (rows with a fresh analysis) and ``without_actual`` (rows with a held or interpolated one)."""
    instant = pd.Timestamp(run.as_of).strftime(STAMP)
    conn.execute("BEGIN IMMEDIATE")
    try:
        table = tracking_at(conn, run.as_of, view)
        conn.execute("DELETE FROM tracking")
        conn.executemany(
            "INSERT INTO tracking (target_hour, horizon, as_of, run_key, actual, lab_state, abs_error, abs_error_persistence, abs_error_b_star, covered) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(r.target_hour.strftime(STAMP), int(r.horizon), instant, run.run_key, _number(r.actual), r.lab_state, _number(r.abs_error), _number(r.abs_error_persistence),
              _number(r.abs_error_b_star), None if pd.isna(r.covered) else int(r.covered)) for r in table.itertuples()])
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    with_actual = int(table["actual"].notna().sum())
    return {"as_of": instant, "tracked": len(table), "with_actual": with_actual, "without_actual": len(table) - with_actual}


def _number(value: float) -> float | None:
    return None if pd.isna(value) else float(value)
