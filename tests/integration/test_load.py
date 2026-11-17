"""The warehouse (U06, AC07 and AC08; RF08, D24): a delivery is added to SQLite in one transaction with the staging table rebuilt for its
instant and the controls of the load; a control with rows undoes everything, down to the bytes of the file; and every analysis carries the
instant it arrives."""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from flotsilica import warehouse
from flotsilica.deliveries import delivery_plan
from flotsilica.schema import AGGREGATE_COLUMNS, SENSORS
from flotsilica.validate import validate_delivery
from flotsilica.warehouse import (
    CheckFailedError,
    DeliveryAlreadyLoadedError,
    EmptyDeliveryError,
    SchemaDriftError,
    apply_schema,
    connect,
    load_delivery,
    rebuild_staging,
    run_checks,
    split_statements,
)

CHECKS = ["chk_aggregates_match_rows", "chk_available_at_is_hour_plus_latency", "chk_delivery_period", "chk_lab_state_rules", "chk_raw_row_unique",
          "chk_rows_per_hour_max"]
LAUNCH_SHA = "a" * 64


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).exists() else ""


def content(path: Path) -> dict[str, list[tuple]]:
    """Every row of every table, in key order: what a reload from scratch must give again."""
    conn = sqlite3.connect(path)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {t: conn.execute(f'SELECT * FROM "{t}" ORDER BY 1, 2').fetchall() for t in tables}
    finally:
        conn.close()


def stamp(hour) -> str:
    return pd.Timestamp(hour).strftime("%Y-%m-%d %H:%M:%S")


def failing(checks) -> list[str]:
    return [c.check_id for c in checks if c.violations]


# --- the RED of U06 ---------------------------------------------------------------------------------------------------


def test_failed_check_rolls_back_a_first_load(quick_cfg, published, tmp_path):
    entry, rows, hours = published.items["L2017-07-31"]
    hours = hours.copy()
    hours.loc[0, "amina_flow_mean"] += 1.0      # an aggregate that is not the rows' (V14's second line of defence)
    path = tmp_path / "warehouse.sqlite"
    conn = connect(path)
    before = sha(path)
    with pytest.raises(CheckFailedError) as error:
        load_delivery(conn, rows, hours, published.plan[0], "r1", quick_cfg, sha256=entry.sha256)
    assert failing(error.value.checks) == ["chk_aggregates_match_rows"]
    sample = next(c for c in error.value.checks if c.violations).sample
    assert sample[0][0] == "2017-03-10 01:00:00" and "amina_flow" in sample[0], "the hour and the sensor: never a row of the plant"
    assert str(error.value).startswith("La carga se deshizo; controles con filas que los violan: chk_aggregates_match_rows: 1 filas")
    assert not conn.in_transaction
    conn.close()
    assert sha(path) == before, "the warehouse keeps exactly what it had: here, nothing"
    assert content(path) == {}


def test_every_analysis_arrives_latency_hours_after_its_hour(quick_cfg, published, loaded_masters, copy_of, tmp_path):
    conn = connect(copy_of(loaded_masters(2)[0]))
    stored = pd.read_sql_query("SELECT hour, available_at FROM lab_hours", conn)
    assert len(stored) == published.entries["L2017-07-31"].hours + published.entries["D2017-08-01"].hours
    gap = pd.to_datetime(stored["available_at"]) - pd.to_datetime(stored["hour"])
    assert set(gap) == {timedelta(hours=2)} and stored["available_at"].str.endswith(":00:00").all()
    assert failing(run_checks(conn, "load", warehouse.sql_params(published.plan[1].as_of, quick_cfg))) == []
    # another latency is another arrival, and the control reads the latency of the configuration, not the data
    conn.execute("UPDATE lab_hours SET available_at = datetime(available_at, '+1 hour') WHERE hour = (SELECT MIN(hour) FROM lab_hours)")
    wrong = run_checks(conn, "load", warehouse.sql_params(published.plan[1].as_of, quick_cfg))
    assert failing(wrong) == ["chk_available_at_is_hour_plus_latency"] and wrong[1].sample[0][0] == "2017-03-10 01:00:00"
    conn.close()
    slower = dataclasses.replace(quick_cfg, lab=dataclasses.replace(quick_cfg.lab, latency_hours=3))
    entry, rows, hours = published.items["L2017-07-31"]
    conn = connect(tmp_path / "slow.sqlite")
    load_delivery(conn, rows, hours, published.plan[0], "r1", slower, sha256=entry.sha256)
    gap = pd.read_sql_query("SELECT hour, available_at FROM lab_hours", conn)
    assert set(pd.to_datetime(gap["available_at"]) - pd.to_datetime(gap["hour"])) == {timedelta(hours=3)}
    conn.close()


# --- AC08: the load -------------------------------------------------------------------------------------------------------


def test_loaded_rows_equal_the_delivery_rows_every_check_is_zero_and_what_a_delivery_holds_comes_back_as_it_went_in(published, loaded_masters, copy_of):
    path, result = loaded_masters(len(published.plan))
    conn = connect(copy_of(path))
    plan = published.plan
    for table, key in (("raw_rows", "rows"), ("lab_hours", "hours")):
        loaded = dict(conn.execute(f"SELECT delivery_id, COUNT(*) FROM {table} GROUP BY delivery_id").fetchall())
        assert loaded == {s.delivery_id: getattr(published.entries[s.delivery_id], key) for s in plan if getattr(published.entries[s.delivery_id], key)}
    last = published.entries["C2017-09-10"]
    assert (result.delivery_id, result.as_of, result.rows, result.hours) == ("C2017-09-10", plan[-1].as_of, 0, 0)
    assert result.staged == conn.execute("SELECT COUNT(*) FROM lab_hours").fetchone()[0] == sum(e.hours for e in published.entries.values())
    assert [c.check_id for c in result.checks] == CHECKS and all(c.violations == 0 for c in result.checks)
    stored = conn.execute("SELECT delivery_id, kind, first_hour, last_hour, as_of, rows, hours, sha256, status, run_key FROM deliveries ORDER BY as_of, delivery_id").fetchall()
    assert stored == [(s.delivery_id, s.kind, None if s.first_hour is None else stamp(s.first_hour), None if s.last_hour is None else stamp(s.last_hour),
                       stamp(s.as_of), published.entries[s.delivery_id].rows, published.entries[s.delivery_id].hours, published.entries[s.delivery_id].sha256,
                       "loaded", f"r{i}") for i, s in enumerate(plan, start=1)]
    assert last.rows == 0
    # a launch row, an hour and its aggregates come back as they went in
    _entry, rows, hours = published.items["L2017-07-31"]
    raw = pd.read_sql_query("SELECT * FROM raw_rows WHERE delivery_id = 'L2017-07-31' ORDER BY row_id", conn)
    assert raw["row_id"].tolist() == rows["row_id"].tolist() and raw["row_in_hour"].tolist() == rows["row_in_hour"].tolist()
    assert raw["hour"].tolist() == [stamp(h) for h in rows["hour"]]
    for sensor in SENSORS:
        assert raw[sensor].tolist() == rows[sensor].tolist(), sensor
    lab = pd.read_sql_query("SELECT * FROM lab_hours WHERE delivery_id = 'L2017-07-31' ORDER BY hour", conn)
    assert lab["hour"].tolist() == [stamp(h) for h in hours["hour"]] and lab["lab_state"].tolist() == hours["lab_state"].tolist()
    for column in ("rows", "silica_pct", "iron_conc_pct", "feed_silica_pct", "feed_iron_pct", "feed_silica_age_h", "feed_iron_age_h"):
        assert lab[column].tolist() == hours[column].tolist(), column
    assert lab["is_partial"].tolist() == hours["is_partial"].astype(int).tolist() and int(lab["is_partial"].sum()) == 2
    assert "feed_changes_in_hour" not in lab.columns and "hour_key" not in lab.columns, "what V24 needed is not stored, nor is a redundant key"
    aggregates = pd.read_sql_query("SELECT * FROM hour_aggregates WHERE hour IN (SELECT hour FROM lab_hours WHERE delivery_id = 'L2017-07-31') ORDER BY hour", conn)
    assert aggregates.columns.tolist() == ["hour", "rows", *AGGREGATE_COLUMNS]
    for column in ("rows", "amina_flow_mean", "amina_flow_last", "level_01_std"):
        assert aggregates[column].tolist() == pytest.approx(hours[column].tolist(), abs=1e-12, nan_ok=True), column
    conn.close()


def test_loading_from_scratch_again_gives_the_same_content(published, quick_cfg, loaded_masters, tmp_path):
    path, _result = loaded_masters(2)
    fresh = tmp_path / "fresh.sqlite"
    conn = connect(fresh)
    for i, spec in enumerate(published.plan[:2], start=1):
        entry, rows, hours = published.items[spec.delivery_id]
        load_delivery(conn, rows, hours, spec, f"r{i}", quick_cfg, sha256=entry.sha256)
    conn.close()
    assert content(fresh) == content(path)


def test_a_failed_control_after_an_earlier_load_leaves_the_warehouse_byte_for_byte_as_it_was(published, quick_cfg, loaded_masters, copy_of):
    path = copy_of(loaded_masters(1)[0])
    before = sha(path)
    spec = published.plan[1]
    entry, rows, hours = published.items[spec.delivery_id]
    rows = rows.copy()
    rows.loc[rows.index[0], "hour"] = pd.Timestamp("2017-09-15 00:00")     # a row dated outside the period of its delivery
    conn = connect(path)
    with pytest.raises(CheckFailedError, match="chk_delivery_period"):
        load_delivery(conn, rows, hours, spec, "r2", quick_cfg, sha256=entry.sha256)
    conn.close()
    assert sha(path) == before


def test_a_failure_after_the_inserts_rolls_back_the_whole_delivery(published, quick_cfg, loaded_masters, copy_of, monkeypatch):
    path = copy_of(loaded_masters(1)[0])
    before = sha(path)
    spec = published.plan[1]
    entry, rows, hours = published.items[spec.delivery_id]

    def broken(*args, **kwargs):
        raise OSError("the disk went away")

    monkeypatch.setattr(warehouse, "run_checks", broken)
    conn = connect(path)
    with pytest.raises(OSError, match="the disk went away"):
        load_delivery(conn, rows, hours, spec, "r2", quick_cfg, sha256=entry.sha256)
    assert not conn.in_transaction and conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0] == 1
    conn.close()
    assert sha(path) == before


def test_a_delivery_already_loaded_or_empty_is_refused_and_writes_nothing_and_the_close_loads_empty(published, quick_cfg, loaded_masters, copy_of):
    path = copy_of(loaded_masters(1)[0])
    before = sha(path)
    conn = connect(path)
    entry, rows, hours = published.items["L2017-07-31"]
    with pytest.raises(DeliveryAlreadyLoadedError, match="L2017-07-31 ya está cargada"):
        load_delivery(conn, rows, hours, published.plan[0], "r9", quick_cfg, sha256=LAUNCH_SHA)
    with pytest.raises(EmptyDeliveryError, match="no tiene filas"):
        load_delivery(conn, rows.iloc[:0], hours.iloc[:0], published.plan[1], "r9", quick_cfg, sha256="b" * 64)
    close_entry, close_rows, close_hours = published.items["C2017-09-10"]
    with pytest.raises(ValueError, match="el cierre no tiene filas"):
        load_delivery(conn, rows.iloc[:3], hours.iloc[:1], published.plan[-1], "r9", quick_cfg, sha256=close_entry.sha256)
    conn.close()
    assert sha(path) == before
    conn = connect(path)
    result = load_delivery(conn, close_rows, close_hours, published.plan[-1], "r9", quick_cfg, sha256=close_entry.sha256)
    assert (result.rows, result.hours, result.delivery_id) == (0, 0, "C2017-09-10") and failing(result.checks) == []
    assert conn.execute("SELECT kind, first_hour, last_hour, as_of, rows, hours, status, run_key FROM deliveries WHERE delivery_id = 'C2017-09-10'").fetchone() == (
        "close", None, None, "2017-09-10 01:00:00", 0, 0, "loaded", "r9")
    conn.close()


def test_a_delivery_without_the_columns_of_the_canonical_tables_is_a_wrong_delivery(published, quick_cfg, tmp_path):
    entry, rows, hours = published.items["L2017-07-31"]
    conn = connect(tmp_path / "w.sqlite")
    with pytest.raises(ValueError, match="no tiene las columnas.*amina_flow"):
        load_delivery(conn, rows.drop(columns=["amina_flow"]), hours, published.plan[0], "r1", quick_cfg, sha256=entry.sha256)
    with pytest.raises(ValueError, match="no tiene las columnas.*feed_iron_age_h"):
        load_delivery(conn, rows, hours.drop(columns=["feed_iron_age_h"]), published.plan[0], "r1", quick_cfg, sha256=entry.sha256)
    conn.close()


# --- the staging: what is known at an instant, and the block of each hour -----------------------------------------------------


def test_the_staging_holds_only_the_hours_that_had_closed_at_the_instant_it_is_built_for(published, quick_cfg, loaded_masters, copy_of):
    conn = connect(copy_of(loaded_masters(2)[0]))
    every = pd.concat([published.items[i][2] for i in ("L2017-07-31", "D2017-08-01")])
    for as_of in (datetime(2017, 8, 11), datetime(2017, 8, 1), datetime(2017, 6, 1), datetime(2017, 3, 10, 2), datetime(2017, 3, 10, 1), datetime(2017, 3, 1)):
        checks = rebuild_staging(conn, as_of, quick_cfg)
        known = every[every["hour"] < pd.Timestamp(as_of)]
        assert conn.execute("SELECT COUNT(*) FROM stg_hours").fetchone()[0] == len(known), as_of
        assert conn.execute("SELECT MAX(hour) FROM stg_hours").fetchone()[0] == (stamp(known["hour"].max()) if len(known) else None)
        assert failing(checks) == [] and [c.check_id for c in checks] == CHECKS
    rebuild_staging(conn, datetime(2017, 8, 11), quick_cfg)
    columns = [r[1] for r in conn.execute("PRAGMA table_info(stg_hours)")]
    assert columns[:2] == ["hour", "delivery_id"] and "block" in columns and "available_at" in columns and "lab_state" in columns
    assert set(AGGREGATE_COLUMNS) <= set(columns) and not set(SENSORS) & set(columns), "the hours with their aggregates: no raw row"
    conn.close()


def test_the_block_of_each_hour_is_the_one_of_the_split_with_its_purges(published, quick_cfg, loaded_masters, copy_of):
    conn = connect(copy_of(loaded_masters(2)[0]))
    rebuild_staging(conn, datetime(2017, 8, 11), quick_cfg)
    block = dict(conn.execute("SELECT hour, block FROM stg_hours"))
    expected = {"2017-03-10 01:00:00": "train", "2017-05-31 23:00:00": "train", "2017-06-01 00:00:00": "purge_1", "2017-06-01 23:00:00": "purge_1",
                "2017-06-02 00:00:00": "valid_v1", "2017-06-30 23:00:00": "valid_v1", "2017-07-01 00:00:00": "purge_v", "2017-07-01 23:00:00": "purge_v",
                "2017-07-02 00:00:00": "valid_v2", "2017-07-30 23:00:00": "valid_v2", "2017-07-31 00:00:00": "purge_2", "2017-07-31 23:00:00": "purge_2",
                "2017-08-01 00:00:00": "test", "2017-08-10 23:00:00": "test"}
    assert {hour: block[hour] for hour in expected} == expected
    counts = dict(conn.execute("SELECT block, COUNT(*) FROM stg_hours GROUP BY block"))
    assert set(counts) == {"train", "purge_1", "valid_v1", "purge_v", "valid_v2", "purge_2", "test"} and counts["purge_1"] == counts["purge_v"] == counts["purge_2"] == 24
    assert sum(counts.values()) == conn.execute("SELECT COUNT(*) FROM lab_hours").fetchone()[0]
    # the blocks are the ones of the view that is given, so a view with another split gives other blocks (and hours before the first are outside)
    other = dataclasses.replace(quick_cfg, split=dataclasses.replace(quick_cfg.split, train_first=datetime(2017, 3, 11), test_first=datetime(2017, 8, 5)))
    rebuild_staging(conn, datetime(2017, 8, 11), other)
    block = dict(conn.execute("SELECT hour, block FROM stg_hours"))
    assert block["2017-03-10 01:00:00"] == "outside" and block["2017-03-11 00:00:00"] == "train" and block["2017-08-03 12:00:00"] == "purge_2"
    assert block["2017-08-05 00:00:00"] == "test"
    assert [r[0] for r in conn.execute("SELECT DISTINCT block FROM hour_blocks ORDER BY 1")] == sorted(set(block.values()))
    conn.close()


# --- the controls: each one fires on its own violation ------------------------------------------------------------------------

INSERT_ROW = ("INSERT INTO raw_rows (row_id, delivery_id, hour, row_in_hour, {sensors}) "
              "SELECT 900000000, delivery_id, hour, {position}, {sensors} FROM raw_rows WHERE hour = datetime((SELECT MIN(hour) FROM raw_rows), '+1 hour') AND row_in_hour = 1")
FIRST_HOUR = "(SELECT MIN(hour) FROM lab_hours)"
TAMPERS = {
    "chk_raw_row_unique": (INSERT_ROW.format(sensors=", ".join(SENSORS), position="row_in_hour"), {"chk_raw_row_unique", "chk_rows_per_hour_max", "chk_aggregates_match_rows"}),
    "chk_rows_per_hour_max": (INSERT_ROW.format(sensors=", ".join(SENSORS), position="99"), {"chk_rows_per_hour_max", "chk_aggregates_match_rows"}),
    "chk_aggregates_match_rows": (f"UPDATE hour_aggregates SET amina_flow_mean = amina_flow_mean + 1 WHERE hour = {FIRST_HOUR}", {"chk_aggregates_match_rows"}),
    "chk_available_at_is_hour_plus_latency": (f"UPDATE lab_hours SET available_at = datetime(available_at, '-1 hour') WHERE hour = {FIRST_HOUR}",
                                              {"chk_available_at_is_hour_plus_latency"}),
    "chk_delivery_period": ("UPDATE deliveries SET last_hour = '2017-03-11 00:00:00' WHERE delivery_id = 'L2017-07-31'", {"chk_delivery_period"}),
    "chk_lab_state_rules": (f"UPDATE lab_hours SET lab_state = 'held' WHERE hour = datetime({FIRST_HOUR}, '+1 hour')", {"chk_lab_state_rules"}),
}


@pytest.mark.parametrize("check", sorted(TAMPERS))
def test_each_control_of_the_load_fires_on_its_own_violation(published, quick_cfg, loaded_masters, copy_of, check):
    conn = connect(copy_of(loaded_masters(1)[0]))
    params = warehouse.sql_params(published.plan[0].as_of, quick_cfg)
    assert failing(run_checks(conn, "load", params)) == []
    statement, expected = TAMPERS[check]
    conn.execute(statement)
    results = run_checks(conn, "load", params)
    assert set(failing(results)) == expected and check in failing(results)
    for result in results:
        assert result.violations == 0 or 0 < len(result.sample) <= warehouse.SAMPLE_LIMIT
    conn.close()


CLOSE_ROW = "INSERT INTO deliveries VALUES ('C2017-09-10', 'close', NULL, NULL, '2017-09-10 01:00:00', 0, 0, 'cc', 'loaded', 'r3')"
PERIOD_CASES = {      # (table, statement that gives one row or hour a delivery whose period does not hold it) -> the violation it must show
    "a row after its delivery": ("raw_rows", "UPDATE raw_rows SET delivery_id = 'L2017-07-31' WHERE hour = '2017-08-01 00:00:00' AND row_in_hour = 1",
                                 ("raw_rows", "2017-08-01 00:00:00", "L2017-07-31")),
    "an hour after its delivery": ("lab_hours", "UPDATE lab_hours SET delivery_id = 'L2017-07-31' WHERE hour = '2017-08-01 00:00:00'",
                                   ("lab_hours", "2017-08-01 00:00:00", "L2017-07-31")),
    "a row before its delivery": ("raw_rows", "UPDATE raw_rows SET delivery_id = 'D2017-08-01' WHERE hour = '2017-06-01 00:00:00' AND row_in_hour = 1",
                                  ("raw_rows", "2017-06-01 00:00:00", "D2017-08-01")),
    "an hour before its delivery": ("lab_hours", "UPDATE lab_hours SET delivery_id = 'D2017-08-01' WHERE hour = '2017-06-01 00:00:00'",
                                    ("lab_hours", "2017-06-01 00:00:00", "D2017-08-01")),
    "a row of the close": ("raw_rows", "UPDATE raw_rows SET delivery_id = 'C2017-09-10' WHERE hour = '2017-06-01 00:00:00' AND row_in_hour = 1",
                           ("raw_rows", "2017-06-01 00:00:00", "C2017-09-10")),
    "an hour of the close": ("lab_hours", "UPDATE lab_hours SET delivery_id = 'C2017-09-10' WHERE hour = '2017-06-01 00:00:00'",
                             ("lab_hours", "2017-06-01 00:00:00", "C2017-09-10")),
}


@pytest.mark.parametrize("case", sorted(PERIOD_CASES))
def test_a_row_or_an_hour_with_the_delivery_of_another_period_is_found_in_its_own_table(published, quick_cfg, loaded_masters, copy_of, case):
    """chk_delivery_period looks at both tables, at both ends of the period and at the close, which holds nothing: each case breaks one."""
    conn = connect(copy_of(loaded_masters(2)[0]))
    conn.execute(CLOSE_ROW)
    _table, statement, violation = PERIOD_CASES[case]
    conn.execute(statement)
    results = run_checks(conn, "load", warehouse.sql_params(published.plan[1].as_of, quick_cfg))
    assert failing(results) == ["chk_delivery_period"] and next(c for c in results if c.violations).sample == [violation]
    conn.close()


def test_the_state_of_an_analysis_must_follow_its_neighbour_in_all_three_ways(published, quick_cfg, loaded_masters, copy_of):
    """chk_lab_state_rules: a held hour repeats the one before it, an interpolated hour has an hour before it and differs from it, and a fresh
    hour is not equal to it; the first hour after a gap can be none of the first two. (Whether the hour before is a ramp hour is not stored.)"""
    conn = connect(copy_of(loaded_masters(1)[0]))
    params = warehouse.sql_params(published.plan[0].as_of, quick_cfg)
    rows = conn.execute("SELECT hour, lab_state, silica_pct FROM lab_hours ORDER BY hour").fetchall()
    held = next(r[0] for r in rows if r[1] == "held")
    interpolated = next(r[0] for r in rows if r[1] == "interpolated")
    after_gap = "2017-03-29 12:00:00"
    assert conn.execute("SELECT lab_state FROM lab_hours WHERE hour = ?", (after_gap,)).fetchone() == ("fresh",)
    changes = [
        (f"UPDATE lab_hours SET silica_pct = silica_pct + 0.5 WHERE hour = '{held}'", "a held hour that no longer repeats the previous one"),
        (f"UPDATE lab_hours SET lab_state = 'fresh' WHERE hour = '{held}'", "a fresh hour equal to the previous one"),
        (f"UPDATE lab_hours SET lab_state = 'held' WHERE hour = '{after_gap}'", "a held hour after a gap"),
        (f"UPDATE lab_hours SET lab_state = 'interpolated' WHERE hour = '{after_gap}'", "an interpolated hour after a gap"),
        (f"UPDATE lab_hours SET silica_pct = (SELECT p.silica_pct FROM lab_hours AS p WHERE p.hour = datetime('{interpolated}', '-1 hour')) "
         f"WHERE hour = '{interpolated}'", "an interpolated hour equal to the previous one"),
    ]
    for statement, why in changes:
        conn.execute("SAVEPOINT s")
        conn.execute(statement)
        assert failing(run_checks(conn, "load", params)) == ["chk_lab_state_rules"], why
        conn.execute("ROLLBACK TO s")
        conn.execute("RELEASE s")
    assert failing(run_checks(conn, "load", params)) == []
    conn.close()


# --- the runner and the schema --------------------------------------------------------------------------------------------------


def connection_keeps_a_page_cache_big_enough_for_the_rows_a_control_reads(small_store, small_canonical, quick_cfg, copy_of):
    """Pinned by ``test_connect_sets_the_pragmas_of_the_project_and_the_runner_never_runs_a_script`` (speed unit, D33): ``connect`` sets a 64 MiB page cache
    (the 2 MiB default made each control re-read the raw rows of the load). It is memory only: the controls answer the same with the default cache."""
    conn = connect(copy_of(small_store))
    assert conn.execute("PRAGMA cache_size").fetchone() == (-warehouse.CACHE_KIB,) and warehouse.CACHE_KIB == 65_536
    params = warehouse.sql_params(small_canonical.hours["hour"].iloc[-1].to_pydatetime() + timedelta(hours=1), quick_cfg)
    cached = [(c.check_id, c.violations, c.sample) for c in run_checks(conn, "load", params)]
    conn.execute("PRAGMA cache_size=-2000")
    assert [(c.check_id, c.violations, c.sample) for c in run_checks(conn, "load", params)] == cached and [c[0] for c in cached] == CHECKS
    conn.close()


def test_connect_sets_the_pragmas_of_the_project_and_the_runner_never_runs_a_script(tmp_path, small_store, small_canonical, quick_cfg, copy_of):
    connection_keeps_a_page_cache_big_enough_for_the_rows_a_control_reads(small_store, small_canonical, quick_cfg, copy_of)
    conn = connect(tmp_path / "sub" / "w.sqlite")
    assert conn.isolation_level is None
    assert conn.execute("PRAGMA journal_mode").fetchone() == ("delete",) and conn.execute("PRAGMA synchronous").fetchone() == (2,)
    assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,) and conn.execute("PRAGMA busy_timeout").fetchone() == (warehouse.BUSY_TIMEOUT_MS,)
    conn.close()
    tree = ast.parse(Path(warehouse.__file__).read_text(encoding="utf-8"))
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "executescript"]


def test_a_sql_file_is_split_into_statements_that_keep_their_semicolons_in_strings_comments_and_triggers():
    text = ("-- a; comment\nCREATE TABLE a (x TEXT DEFAULT ';');\n/* b; */ CREATE TRIGGER t BEFORE UPDATE ON a BEGIN SELECT RAISE(ABORT, 'no;'); END;\n"
            "INSERT INTO a VALUES ('x;y')")
    parts = split_statements(text)
    assert len(parts) == 3 and "CREATE TABLE a (x TEXT DEFAULT ';');" in parts[0] and parts[1].endswith("END;") and parts[2] == "INSERT INTO a VALUES ('x;y')"
    assert split_statements("-- only a comment;\n;") == []


def test_applying_the_schema_again_keeps_the_data_and_a_table_with_other_columns_is_refused_naming_it(tmp_path):
    conn = connect(tmp_path / "w.sqlite")
    apply_schema(conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"deliveries", "raw_rows", "lab_hours", "hour_aggregates", "pipeline_runs", "validation_results", "hour_blocks"} <= tables
    conn.execute("INSERT INTO deliveries VALUES ('L1', 'launch', NULL, NULL, '2017-08-01 00:00:00', 0, 0, ?, 'loaded', 'r1')", ("a" * 64,))
    apply_schema(conn)
    assert conn.execute("SELECT COUNT(*) FROM deliveries").fetchone() == (1,) and not conn.in_transaction
    conn.execute("BEGIN")          # speed unit (D33): inside the caller's transaction it joins it: it neither commits nor ends it
    apply_schema(conn)
    assert conn.in_transaction
    conn.execute("ROLLBACK")
    with pytest.raises(ValueError, match="grupo de controles desconocido"):
        run_checks(conn, "nonsense")
    conn.close()
    old = connect(tmp_path / "old.sqlite")
    old.execute("CREATE TABLE deliveries (delivery_id TEXT PRIMARY KEY, status TEXT)")
    with pytest.raises(SchemaDriftError, match=r"deliveries.*faltan las columnas \['kind'"):
        apply_schema(old)
    old.close()


def test_a_table_with_an_unexpected_or_a_retyped_column_is_refused_naming_it(tmp_path):
    conn = connect(tmp_path / "w.sqlite")
    conn.execute("CREATE TABLE lab_hours (hour TEXT PRIMARY KEY, extra INTEGER)")
    with pytest.raises(SchemaDriftError, match=r"sobran las columnas \['extra'\]"):
        apply_schema(conn)
    conn.close()
    other = connect(tmp_path / "other.sqlite")
    apply_schema(other)
    other.execute("DROP TABLE hour_blocks")
    other.execute("CREATE TABLE hour_blocks (hour TEXT PRIMARY KEY, block INTEGER)")
    with pytest.raises(SchemaDriftError, match=r"tienen otro tipo las columnas \['block'\]"):
        apply_schema(other)
    assert not other.in_transaction        # speed unit (D33): the error ends the transaction apply_schema opened
    other.close()
    partial = connect(tmp_path / "partial.sqlite")
    partial.execute("CREATE TABLE hour_blocks (hour TEXT PRIMARY KEY, block INTEGER)")      # the drift is in the second file: the tables of the first are created, as in autocommit
    with pytest.raises(SchemaDriftError):
        apply_schema(partial)
    assert not partial.in_transaction and {r[0] for r in partial.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} >= {"deliveries", "hour_blocks"}
    partial.close()


def test_the_aggregate_control_names_every_sensor_with_its_three_columns():
    text = (Path(warehouse.SQL_DIR) / "checks" / "load" / "chk_aggregates_match_rows.sql").read_text(encoding="utf-8")
    for column in AGGREGATE_COLUMNS:
        if column.endswith("_mean"):
            assert column in text, column
    assert text.count("amina_flow") >= 2


def test_the_rules_of_the_validation_read_what_this_warehouse_holds(published, quick_cfg, loaded_masters, copy_of):
    """validate reads ``deliveries``, ``raw_rows`` and ``lab_hours`` of the real schema: a delivery that is loaded cannot be validated again."""
    conn = connect(copy_of(loaded_masters(2)[0]))
    entry, rows, hours = published.items["D2017-08-01"]
    report = validate_delivery(rows, hours, published.plan[1], conn, quick_cfg, entry=entry, out_dir=published.folder, run_key="r9")
    broken = {r.rule_id for r in report.results if r.status == "fail"}
    assert broken == {"V10", "V12"} and report.results[0].examples[0]["reason"] == "already_loaded"
    next_entry, next_rows, next_hours = published.items["D2017-08-11"]
    fresh = validate_delivery(next_rows, next_hours, published.plan[2], conn, quick_cfg, entry=next_entry, out_dir=published.folder, run_key="r3")
    assert not fresh.blocking_failed
    i02 = next(r for r in fresh.results if r.rule_id == "I02")
    assert i02.hours_affected > 0 and i02.examples[0]["threshold_hours"] == 24, "the feed's ages of the loaded hours are read"
    conn.close()
