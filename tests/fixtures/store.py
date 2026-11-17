"""The least of a warehouse that the validation reads (U05): ``deliveries``, ``raw_rows`` and ``lab_hours``, with the columns of the plan's
section 5 that the rules look at. U06 writes the real schema and ``load_delivery``; this stands in only for the tests of ``validate``, which
only reads what is loaded, and is dropped when those tests move to the real warehouse."""

from __future__ import annotations

import sqlite3

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


def load(conn: sqlite3.Connection, delivery_id: str, rows: pd.DataFrame, hours: pd.DataFrame) -> None:
    """Record a delivery as loaded, with its rows and hours."""
    conn.execute("INSERT INTO deliveries VALUES (?, 'loaded')", (delivery_id,))
    conn.executemany("INSERT INTO raw_rows VALUES (?, ?)", [(int(r), iso(h)) for r, h in zip(rows["row_id"], rows["hour"], strict=True)])
    conn.executemany("INSERT INTO lab_hours VALUES (?, ?, ?, ?)", [
        (iso(h), int(n), float(s), float(i)) for h, n, s, i in zip(hours["hour"], hours["rows"], hours["feed_silica_age_h"], hours["feed_iron_age_h"], strict=True)])
