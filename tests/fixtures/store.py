"""The least of a warehouse that the validation reads: ``deliveries``, ``raw_rows`` and ``lab_hours``, with the columns of the plan's section 5 that the
rules look at, so that a test of ``validate`` can load a delivery with one line and break one thing by hand. The real schema and
``load_delivery`` are U06's; ``tests/integration/test_load.py::test_the_rules_of_the_validation_read_what_this_warehouse_holds`` runs the rules over
a warehouse loaded by them, which pins that every column this stand-in has is one the real tables have."""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

SCHEMA = (
    "CREATE TABLE deliveries (delivery_id TEXT PRIMARY KEY, status TEXT NOT NULL)",
    "CREATE TABLE raw_rows (row_id INTEGER PRIMARY KEY, hour TEXT NOT NULL)",
    "CREATE TABLE lab_hours (hour TEXT PRIMARY KEY, rows INTEGER NOT NULL, feed_silica_age_h REAL, feed_iron_age_h REAL)",
)


def iso(hour) -> str:
    return pd.Timestamp(hour).strftime("%Y-%m-%d %H:00:00")


def empty_store() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    for statement in SCHEMA:
        conn.execute(statement)
    return conn


def iso_hours(values) -> list[str]:
    """The hours of a column as the warehouse stores them, ``YYYY-MM-DD HH:00:00``, in one pass over the array (the hours are on the hour)."""
    if not len(values):
        return []
    stamps = np.datetime_as_string(pd.DatetimeIndex(values).to_numpy().astype("datetime64[s]"), unit="s")
    return np.char.replace(stamps, "T", " ").tolist()


def load(conn: sqlite3.Connection, delivery_id: str, rows: pd.DataFrame, hours: pd.DataFrame) -> None:
    """Record a delivery as loaded, with its rows and hours."""
    conn.execute("INSERT INTO deliveries VALUES (?, 'loaded')", (delivery_id,))
    row_hours = iso_hours(rows["hour"])               # one pass over the array, not one Timestamp per row (1.3 million calls before)
    conn.executemany("INSERT INTO raw_rows VALUES (?, ?)", zip(rows["row_id"].astype(int).tolist(), row_hours, strict=True))
    conn.executemany("INSERT INTO lab_hours VALUES (?, ?, ?, ?)", zip(
        iso_hours(hours["hour"]), hours["rows"].astype(int).tolist(),
        hours["feed_silica_age_h"].astype(float).tolist(), hours["feed_iron_age_h"].astype(float).tolist(), strict=True))
