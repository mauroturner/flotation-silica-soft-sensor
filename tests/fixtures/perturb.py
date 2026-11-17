"""Stores for the leak probes of U07 (AC11): the small fixture's warehouse as it was at an instant, and the same warehouse with what the
instant could not know changed.

``walk`` goes through every instant of the small fixture, hour by hour, and at each one has four connections ready:

* ``full``: everything loaded (the warehouse the pipeline reads);
* ``truncated``: only what existed at the instant ``t``: the aggregates and the rows of the hours before ``t`` and the analyses with
  ``available_at <= t`` (grown instant by instant, so no copy is made per instant; the hour that closed at ``t`` has its readings but not
  its analysis yet when the latency is more than one hour, so its row of ``lab_hours`` is not there: the foreign key is not enforced here);
* ``future_readings``: the full warehouse with the readings (aggregates and rows) of every hour from ``t`` on changed;
* ``future_analyses``: the full warehouse with every analysis that has not arrived by ``t`` changed (its value, its state, its feed and its count).

A change like these is visible to anything that reads it: the tests show it with two queries that do read what an instant must not (the hour
that is just starting, the analysis of the hour that just closed), which differ between ``full`` and the changed warehouses.

The changes are restored as the instants go by: at ``t`` the hour ``t - 1`` has closed and the analyses of the hours up to ``t - latency`` have arrived.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import timedelta

import pandas as pd

from flotsilica.schema import AGGREGATE_COLUMNS, SENSORS
from flotsilica.warehouse import apply_schema

HOUR = timedelta(hours=1)
LAB_VALUES = ("silica_pct", "iron_conc_pct", "feed_silica_pct", "feed_iron_pct", "feed_silica_age_h", "feed_iron_age_h")
HOUR_COLUMNS = ("hour", "delivery_id", "rows", "is_partial", *LAB_VALUES, "lab_state", "available_at")   # the order of the tuples of hour_values


def stamp(value) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def empty_memory() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    apply_schema(conn)
    conn.execute("INSERT INTO deliveries VALUES ('T', 'launch', NULL, NULL, '2999-01-01 00:00:00', 0, 0, 'x', 'loaded', 'r1')")
    return conn


def copy_of_store(path) -> sqlite3.Connection:
    source = sqlite3.connect(path)
    target = sqlite3.connect(":memory:", isolation_level=None)
    source.backup(target)
    source.close()
    return target


def _clean(value):
    return None if value != value else value


def hour_values(hours: pd.DataFrame, latency: int) -> dict[pd.Timestamp, dict]:
    """Per hour: the values of ``lab_hours``, of ``hour_aggregates`` and the arrival instant."""
    table = hours.set_index("hour")
    out = {}
    for hour, row in table.iterrows():
        out[hour] = {
            "lab": (stamp(hour), "T", int(row["rows"]), int(row["is_partial"]), *[_clean(row[c]) for c in LAB_VALUES], row["lab_state"], stamp(hour + latency * HOUR)),
            "aggregates": (stamp(hour), int(row["rows"]), *[_clean(row[c]) for c in AGGREGATE_COLUMNS]),
        }
    return out


def scramble_readings(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE hour_aggregates SET rows = rows + 3, " + ", ".join(f"{c} = -3 * {c} + 17" for c in AGGREGATE_COLUMNS))
    conn.execute("UPDATE raw_rows SET " + ", ".join(f"{c} = 2 * {c} + 5" for c in SENSORS))


def scramble_analyses(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE lab_hours SET rows = rows + 3, silica_pct = 2 * silica_pct + 1, iron_conc_pct = iron_conc_pct + 7, "
                 "feed_silica_pct = feed_silica_pct + 9, feed_iron_pct = feed_iron_pct + 11, feed_silica_age_h = feed_silica_age_h + 5, "
                 "feed_iron_age_h = feed_iron_age_h + 6, lab_state = CASE lab_state WHEN 'fresh' THEN 'held' ELSE 'fresh' END")


def _restore_readings(conn, true, rows_by_hour, hour) -> None:
    conn.execute("UPDATE hour_aggregates SET rows = ?, " + ", ".join(f"{c} = ?" for c in AGGREGATE_COLUMNS) + " WHERE hour = ?",
                 (*true["aggregates"][1:], true["aggregates"][0]))
    for row_id, _position, values in rows_by_hour.get(hour, []):
        conn.execute("UPDATE raw_rows SET " + ", ".join(f"{c} = ?" for c in SENSORS) + " WHERE row_id = ?", (*values, row_id))


def _restore_analysis(conn, true) -> None:
    values = true["lab"]
    conn.execute("UPDATE lab_hours SET rows = ?, is_partial = ?, " + ", ".join(f"{c} = ?" for c in LAB_VALUES) + ", lab_state = ? WHERE hour = ?",
                 (values[2], values[3], *values[4:10], values[10], values[0]))


def walk(path, rows: pd.DataFrame, hours: pd.DataFrame, latency: int) -> Iterator[tuple[pd.Timestamp, dict[str, sqlite3.Connection]]]:
    """Yield ``(t, connections)`` for every instant from the first hour to the one after the last (the March gap included)."""
    true = hour_values(hours, latency)
    rows_by_hour: dict[pd.Timestamp, list] = {}
    for record in rows[["row_id", "hour", "row_in_hour", *SENSORS]].itertuples(index=False):
        rows_by_hour.setdefault(record[1], []).append((int(record[0]), int(record[2]), tuple(record[3:])))
    full = copy_of_store(path)
    truncated = empty_memory()
    future_readings, future_analyses = copy_of_store(path), copy_of_store(path)
    scramble_readings(future_readings)
    scramble_analyses(future_analyses)
    first, last = hours["hour"].iloc[0], hours["hour"].iloc[-1]
    closed: set = set()
    arrived: set = set()
    t = first
    try:
        while t <= last + HOUR:
            for hour in true:                      # what the instant has just made known
                if hour < t and hour not in closed:
                    closed.add(hour)
                    truncated.execute("INSERT INTO hour_aggregates VALUES (" + ", ".join("?" * (2 + len(AGGREGATE_COLUMNS))) + ")", true[hour]["aggregates"])
                    for row_id, position, values in rows_by_hour.get(hour, []):
                        truncated.execute("INSERT INTO raw_rows VALUES (" + ", ".join("?" * (4 + len(SENSORS))) + ")", (row_id, "T", stamp(hour), position, *values))
                    _restore_readings(future_readings, true[hour], rows_by_hour, hour)
                if hour + latency * HOUR <= t and hour not in arrived:
                    arrived.add(hour)
                    truncated.execute(f"INSERT INTO lab_hours ({', '.join(HOUR_COLUMNS)}) VALUES ({', '.join('?' * len(HOUR_COLUMNS))})", true[hour]["lab"])
                    _restore_analysis(future_analyses, true[hour])
            yield t, {"full": full, "truncated": truncated, "future_readings": future_readings, "future_analyses": future_analyses}
            t += HOUR
    finally:
        for conn in (full, truncated, future_readings, future_analyses):
            conn.close()
