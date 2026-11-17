"""The star model that Power BI reads (U13; AC25, RF21; D25; plan, section 19): unique keys, every foreign key in its dimension, relationships one to many of single
direction and active, each Parquet file with the schema of the specification and the run's metadata, a set that carries its manifest, and the figures of the
tables equal to what the warehouse holds. What the tables show is what was known at the instant of the run: an analysis that had not arrived is not in them."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timedelta

import pyarrow.parquet as pq
import pytest

from flotsilica import export
from flotsilica.dashboard.semantic_model import MODEL, arrow_schema
from flotsilica.export import METADATA_KEYS, STAR_MANIFEST, export_star_schema, verify_star_schema
from flotsilica.ingest import ATTRIBUTION
from flotsilica.registry import sealed_view
from flotsilica.scoring import RunMeta
from flotsilica.tracking import track
from flotsilica.warehouse import CheckFailedError, connect, rebuild_marts
from tests.fixtures.history import copy_history, stamp


def read(star, name: str):
    return pq.read_table(star.out_dir / f"{name}.parquet")


def rows(star, name: str) -> list[dict]:
    return read(star, name).to_pylist()


def hour_text(hour_key: int) -> str:
    """An ``hour_key`` (YYYYMMDDHH) as the warehouse stores the hour."""
    return datetime.strptime(str(hour_key), "%Y%m%d%H").strftime("%Y-%m-%d %H:00:00")


def sql(star, query: str, *params) -> list[tuple]:
    conn = sqlite3.connect(star.history.paths.db)
    try:
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


# --- the RED of U13 --------------------------------------------------------------------------------------------------------


def test_every_relationship_is_one_to_many_single_and_keys_exist(star_files):
    """AC25: for each of the 15 relationships the dimension's key is unique and never empty, every key of the fact is in the dimension, and the relationship is one
    to many, single direction and active; every table's key is unique; each file has the schema of the specification and the run, the instant, the source and the
    attribution as metadata."""
    star = star_files
    assert [r.rel_id for r in MODEL.relationships] == [f"R{i:02d}" for i in range(1, 16)]
    for r in MODEL.relationships:
        assert (r.cardinality, r.cross_filter, r.active) == ("one_to_many", "single", True), r.rel_id
        keys = read(star, r.dim_table).column(r.dim_column).to_pylist()
        assert keys and None not in keys and len(set(keys)) == len(keys), f"{r.rel_id}: {r.dim_table}[{r.dim_column}] is not a unique key"
        values = read(star, r.fact_table).column(r.fact_column).to_pylist()
        assert None not in values and set(values) <= set(keys), f"{r.rel_id}: {r.fact_table}[{r.fact_column}] outside {r.dim_table}"
    assert [p.stem for p in star.paths] == [t.name for t in MODEL.tables] and len(MODEL.tables) == 20
    expected_metadata = dict(zip(METADATA_KEYS, (star.run.run_key, stamp(star.run.as_of), star.history.sealed.source_sha256, ATTRIBUTION), strict=True))
    for table in MODEL.tables:
        data = read(star, table.name)
        assert data.schema.remove_metadata() == arrow_schema(table), table.name
        assert {k.decode(): v.decode("utf-8") for k, v in data.schema.metadata.items() if k.decode() in METADATA_KEYS} == expected_metadata, table.name
        keys = list(zip(*(data.column(k).to_pylist() for k in table.key), strict=True))
        assert len(set(keys)) == len(keys) and all(None not in key for key in keys), f"{table.name}: its key is not unique"


# --- what the tables hold -------------------------------------------------------------------------------------------------


def test_the_dimensions_are_the_calendar_the_methods_the_sensors_and_the_frozen_models(star_files):
    star = star_files
    hours = rows(star, "dim_hour")
    stamps = [h["hour"] for h in hours]
    first, last = stamps[0], stamps[-1]
    assert [b - a for a, b in zip(stamps, stamps[1:], strict=False)] == [stamps[1] - stamps[0]] * (len(stamps) - 1) and (stamps[1] - stamps[0]).total_seconds() == 3600
    data_hours = {h for (h,) in sql(star, "SELECT hour FROM lab_hours")}
    targets = {t for (t,) in sql(star, "SELECT target_hour FROM estimates")}
    assert stamp(first) == min(data_hours) and stamp(last) == max(data_hours | targets)
    states = {}
    for h in hours:
        states.setdefault(h["lab_state"], []).append(stamp(h["hour"]))
    assert {"pending", "missing"} <= set(states) <= {"fresh", "held", "interpolated", "pending", "missing"}
    assert set(states["missing"]).isdisjoint(data_hours) and set(stamp(h["hour"]) for h in hours) >= data_hours
    assert sorted(states["pending"]) == sorted(h for (h,) in sql(star, "SELECT hour FROM lab_hours WHERE available_at > ?", stamp(star.run.as_of)))
    sample = next(h for h in hours if h["lab_state"] == "fresh")
    assert (sample["hour_key"], sample["date"], sample["hour_of_day"]) == (int(sample["hour"].strftime("%Y%m%d%H")), sample["hour"].date(), sample["hour"].hour)
    blocks = {stamp(h["hour"]): h["block"] for h in hours}
    assert dict(sql(star, "SELECT hour, block FROM hour_blocks")).items() <= blocks.items()
    assert {(h["block"], h["block_es"]) for h in hours} <= {("outside", "Fuera de los bloques"), ("train", "Entrenamiento"), ("purge_1", "Purga entre entrenamiento y V1"),
                                                           ("valid_v1", "Validación V1"), ("purge_v", "Purga entre V1 y V2"), ("valid_v2", "Validación V2"),
                                                           ("purge_2", "Purga entre V2 y la prueba"), ("test", "Prueba")}
    assert {b for h in hours if (b := h["block"]) == "test"} == {"test"} and {stamp(h["hour"]) for h in hours if h["block"] == "test"} == {
        f"2017-03-30 {k:02d}:00:00" for k in range(24)}
    dates = rows(star, "dim_date")
    assert [d["date"] for d in dates] == sorted({h["hour"].date() for h in hours}) and {d["test_week"] for d in dates} == {None, 1}
    assert [d["date_key"] for d in dates if d["test_week"] == 1] == [20170330] and (dates[0]["date_key"], dates[0]["month_name_es"], dates[0]["weekday_es"]) == (20170310, "marzo", "viernes")
    assert [(h["horizon_key"], h["hours_ahead"]) for h in rows(star, "dim_horizon")] == [(0, 0), (1, 1), (2, 2)]
    methods = {m["method_key"]: m for m in rows(star, "dim_method")}
    assert sorted(methods) == sorted(["model", "b0_train_mean", "b1_persistence", "b2_rolling", "b3_ridge_sensors", "best_sensors_only", "best_lab_only", "best_with_sensors"])
    assert {k: m["kind_es"] for k, m in methods.items()} == {
        "model": "modelo", "b0_train_mean": "regla", "b1_persistence": "regla", "b2_rolling": "regla", "b3_ridge_sensors": "comparación",
        "best_sensors_only": "comparación", "best_lab_only": "comparación", "best_with_sensors": "comparación"}
    sensors = rows(star, "dim_sensor")
    assert len(sensors) == 19 and {s["group_es"] for s in sensors} == {"reactivos", "pulpa", "aire", "nivel"} and {s["unit_es"] for s in sensors} == {"sin unidad en la fuente"}
    assert {s["sensor_key"] for s in sensors if s["group_es"] == "aire"} == {f"air_flow_0{k}" for k in range(1, 8)}
    models = {m["model_key"]: m for m in rows(star, "dim_model")}
    assert sorted(models) == ["v1-h0", "v1-h1", "v1-h2"] and {m["seal_state"] for m in models.values()} == {"sealed"}
    registry = json.loads(sql(star, "SELECT models_json FROM model_registry")[0][0])
    assert {f"v1-h{m['horizon']}": (m["family"], m["feature_set"], m["half_width"], m["b_star"], m["b2_k"]) for m in registry} == {
        k: (m["family"], m["feature_set"], pytest.approx(m["half_width"]), m["b_star"], m["b2_k"]) for k, m in models.items()}
    assert {m["config_sha256"] for m in models.values()} == {sql(star, "SELECT config_sha256 FROM model_registry")[0][0]}


def test_the_hours_and_their_estimates_hold_what_the_warehouse_holds(star_files):
    star = star_files
    lab_count, estimates = sql(star, "SELECT COUNT(*) FROM lab_hours")[0][0], sql(star, "SELECT COUNT(*) FROM estimates")[0][0]
    assert read(star, "fact_hour_process").num_rows == 19 * lab_count and read(star, "fact_hour_lab").num_rows == lab_count and read(star, "fact_estimate").num_rows == estimates
    aggregate = sql(star, "SELECT amina_flow_mean, amina_flow_std, amina_flow_last FROM hour_aggregates WHERE hour = '2017-03-12 05:00:00'")[0]
    process = {(p["hour_key"], p["sensor_key"]): p for p in rows(star, "fact_hour_process")}
    got = process[(2017031205, "amina_flow")]
    assert (got["mean"], got["std"], got["last"]) == pytest.approx(aggregate)
    for e in rows(star, "fact_estimate"):
        issued = sql(star, "SELECT estimate, low, high, persistence, b_star, status, issue_at, model_version, is_censored FROM estimates WHERE target_hour = ? AND horizon = ?",
                     hour_text(e["hour_key"]), e["horizon_key"])[0]
        assert (e["status"], stamp(e["issue_at"]), e["model_key"], e["is_censored"]) == (issued[5], issued[6], f"{issued[7]}-h{e['horizon_key']}", bool(issued[8]))
        if e["status"] == "ok":
            assert (e["estimate"], e["low"], e["high"], e["persistence"], e["b_star"]) == pytest.approx(issued[:5])
        else:
            assert all(e[c] is None for c in ("estimate", "low", "high", "persistence", "b_star", "actual", "abs_error", "covered"))
    tracked = {(hour_text(e["hour_key"]), e["horizon_key"]): e for e in rows(star, "fact_estimate") if e["actual"] is not None}
    wanted = sql(star, "SELECT target_hour, horizon, actual, abs_error, abs_error_persistence, abs_error_b_star, covered FROM tracking WHERE actual IS NOT NULL")
    assert len(tracked) == len(wanted) > 0
    for target, horizon, actual, error, persistence, b_star, covered in wanted:
        e = tracked[(target, horizon)]
        assert (e["actual"], e["abs_error"], e["abs_error_persistence"], e["abs_error_b_star"], e["covered"]) == (pytest.approx(actual), pytest.approx(error), pytest.approx(persistence),
                                                                                                                  pytest.approx(b_star), bool(covered))
        assert e["abs_error"] == pytest.approx(abs(e["estimate"] - e["actual"]))


def test_a_lab_value_is_shown_only_from_its_arrival(star_files):
    """D06, AC21: at the instant of the run an analysis that has not arrived is a ``pending`` hour with no value in the laboratory fact and no actual in the estimates;
    the ones that arrived carry the stored values."""
    star = star_files
    now = stamp(star.run.as_of)
    stored = {h: (s, i, fs, fi, state, a, b, c) for h, s, i, fs, fi, state, a, b, c in sql(
        star, "SELECT hour, silica_pct, iron_conc_pct, feed_silica_pct, feed_iron_pct, lab_state, feed_silica_age_h, feed_iron_age_h, available_at FROM lab_hours")}
    shown = {hour_text(r["hour_key"]): r for r in rows(star, "fact_hour_lab")}
    pending = [h for h, v in stored.items() if v[7] > now]
    assert pending and set(shown) == set(stored)
    for hour, row in shown.items():
        silica, iron, feed_silica, feed_iron, state, age_silica, age_iron, available = stored[hour]
        assert stamp(row["available_at"]) == available
        if available > now:
            assert row["lab_state"] == "pending" and all(row[c] is None for c in ("silica_pct", "iron_conc_pct", "feed_silica_pct", "feed_iron_pct", "feed_silica_age_h", "feed_iron_age_h"))
        else:
            assert row["lab_state"] == state and (row["silica_pct"], row["iron_conc_pct"], row["feed_silica_pct"], row["feed_iron_pct"]) == pytest.approx(
                (silica, iron, feed_silica, feed_iron)) and (row["feed_silica_age_h"], row["feed_iron_age_h"]) == pytest.approx((age_silica, age_iron))
    assert all(e["actual"] is None for e in rows(star, "fact_estimate") if hour_text(e["hour_key"]) in pending)


def test_the_evaluation_tables_hold_the_sealed_figures(star_files):
    star = star_files
    metrics = rows(star, "fact_method_metrics")
    assert {m["scope"] for m in metrics} == {"valid_v1", "valid_v2", "test"} and "b_star" not in {m["method_key"] for m in metrics}
    registry = json.loads(sql(star, "SELECT models_json FROM model_registry")[0][0])
    b_star = {m["horizon"]: m["b_star"] for m in registry}
    for scope in ("valid_v1", "valid_v2", "test"):
        for horizon in (0, 1, 2):
            part = [m for m in metrics if (m["scope"], m["horizon_key"]) == (scope, horizon)]
            assert [m["method_key"] for m in part if m["is_b_star"]] == [b_star[horizon]], (scope, horizon)
    model_test = [m for m in metrics if m["scope"] == "test" and m["method_key"] == "model"]
    for m in model_test:
        low, high = sql(star, "SELECT ci_low, ci_high FROM eval_bootstrap WHERE comparison = ? AND seal_state = 'sealed'", f"model_vs_b_star.h{m['horizon_key']}")[0]
        assert (m["ci_low_vs_b_star"], m["ci_high_vs_b_star"]) == pytest.approx((low, high))
        mae, hours = sql(star, "SELECT MAX(CASE WHEN metric = 'mae' THEN value END), MAX(CASE WHEN metric = 'hours' THEN value END) FROM eval_metrics "
                               "WHERE scope = 'test' AND horizon = ? AND method = 'model' AND seal_state = 'sealed'", m["horizon_key"])[0]
        assert (m["mae"], m["hours"]) == (pytest.approx(mae), int(hours))
    assert all(m["ci_low_vs_b_star"] is None for m in metrics if m["method_key"] != "model")
    weekly = rows(star, "fact_weekly_mae")
    assert {w["test_week"] for w in weekly} == {1} and {w["method_key"] for w in weekly} <= {"model", "b1_persistence", "b2_rolling"} and {w["seal_state"] for w in weekly} == {"sealed"}
    criteria = rows(star, "fact_evaluation_summary")
    assert [c["criterion_id"] for c in criteria] == [f"C{i:02d}" for i in range(1, 11)] and {c["seal_state"] for c in criteria} == {"sealed"}
    assert [c["verdict_es"] for c in criteria] == [v for (v,) in sql(star, "SELECT verdict_es FROM eval_criteria WHERE seal_state = 'sealed' ORDER BY criterion_id")]
    selection = rows(star, "fact_selection")
    assert len(selection) == sql(star, "SELECT COUNT(*) FROM eval_selection WHERE seal_state = 'sealed'")[0][0] and sum(s["chosen"] for s in selection) == 3
    sensitivity = rows(star, "fact_sensitivity")
    assert len(sensitivity) == 19 and {s["label_es"] for s in sensitivity if s["passes"]} <= {"asociación del modelo"}
    assert {s["label_es"] for s in sensitivity if not s["passes"]} <= {"sin asociación estable"}
    curves = rows(star, "fact_pd_curve")
    assert {c["sensor_key"] for c in curves} == {s["sensor_key"] for s in sensitivity if s["passes"]}
    variants = rows(star, "fact_variants")
    assert {v["variant"] for v in variants} and {v["method_key"] for v in variants} <= {"model", "b1_persistence"}
    assert len(rows(star, "fact_leakage")) == sql(star, "SELECT COUNT(*) FROM eval_leakage WHERE seal_state = 'sealed'")[0][0] > 0


def test_the_quality_of_the_data_is_counted_by_day(star_files):
    star = star_files
    days = rows(star, "fact_data_quality")
    lab = sql(star, "SELECT COUNT(*), SUM(is_partial) FROM lab_hours")[0]
    assert sum(d["hours"] for d in days) == lab[0] and sum(d["partial_hours"] for d in days) == lab[1]
    arrived = dict(sql(star, "SELECT lab_state, COUNT(*) FROM lab_hours WHERE available_at <= ? GROUP BY 1", stamp(star.run.as_of)))
    for state in ("fresh", "interpolated", "held"):
        assert sum(d[state] for d in days) == arrived.get(state, 0), state
    first, last = sql(star, "SELECT MIN(hour), MAX(hour) FROM lab_hours")[0]
    span = int((datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds() // 3600) + 1
    assert sum(d["hours"] + d["missing_hours"] for d in days) == span and sum(d["missing_hours"] for d in days) > 0, "the gap of March is counted as missing"
    constant = sql(star, "SELECT COUNT(*) FROM hour_aggregates WHERE " + " OR ".join(f"{s}_std = 0" for s in
                   [r["sensor_key"] for r in rows(star, "dim_sensor")]))[0][0]
    assert sum(d["stuck_sensor_hours"] for d in days) == constant
    unchanged = sql(star, "SELECT COUNT(*) FROM lab_hours WHERE available_at <= ? AND (feed_silica_age_h >= 24 OR feed_iron_age_h >= 24)", stamp(star.run.as_of))[0][0]
    assert sum(d["feed_unchanged_24h"] for d in days) == unchanged
    runs = rows(star, "dim_pipeline_run")
    assert [r["run_key"] for r in runs] == [r.run_key for r in star.history.runs] and {r["status"] for r in runs} == {"ok"}
    assert [(r["as_of"], r["estimates_issued"]) for r in runs] == [(r.as_of, issued) for r, issued in zip(star.history.runs, [r.issued for r in star.history.results], strict=True)]
    rules = {v["rule_id"]: v for v in rows(star, "fact_validation")}
    assert sorted(rules) == ["I02", "V10", "V11", "V22"] and {v["run_key"] for v in rules.values()} == {star.run.run_key}
    assert {k: (v["severity"], v["status"]) for k, v in rules.items()} == {
        "V10": ("bloqueante", "pasa"), "V11": ("bloqueante", "falla"), "V22": ("advertencia", "advierte"), "I02": ("informativa", "pasa")}
    assert (rules["V11"]["rows_affected"], rules["V11"]["hours_affected"], rules["I02"]["aggregation"], rules["V22"]["scope"]) == (5, 2, "latest", "hours")


# --- the controls, the set and the limits ---------------------------------------------------------------------------------


def test_a_control_that_fails_rolls_the_star_model_back(star_files, tmp_path):
    """A tracking row that shows an analysis that has not arrived (found by chk_actual_only_after_arrival, and by chk_tracking_totals, which recounts the rows that should be
    there): the build is undone, the marts keep what they had and no file is written."""
    star = star_files
    h = copy_history(star.history, tmp_path / "broken")
    conn = connect(h.paths.db)
    try:
        before = conn.execute("SELECT COUNT(*), SUM(actual IS NOT NULL) FROM star_fact_estimate").fetchone()
        target, horizon = conn.execute("SELECT e.target_hour, e.horizon FROM estimates e JOIN lab_hours l ON l.hour = e.target_hour "
                                       "WHERE e.status = 'ok' AND l.available_at > ? LIMIT 1", (stamp(star.run.as_of),)).fetchone()
        conn.execute("INSERT INTO tracking VALUES (?, ?, ?, 'r9', 2.5, 'fresh', 0.1, 0.1, 0.1, 1)", (target, horizon, stamp(star.run.as_of)))
        with pytest.raises(CheckFailedError) as error:
            export_star_schema(conn, tmp_path / "powerbi", MODEL, star.run, h.sealed, seal_path=h.paths.seal)
        failing = {c.check_id for c in error.value.checks if c.violations}
        assert failing == {"chk_actual_only_after_arrival", "chk_tracking_totals"}
        assert conn.execute("SELECT COUNT(*), SUM(actual IS NOT NULL) FROM star_fact_estimate").fetchone() == before and not conn.in_transaction
    finally:
        conn.close()
    assert not (tmp_path / "powerbi").exists(), "nothing is written when a control fails"


def test_a_foreign_key_outside_its_dimension_is_a_failing_control(star_files, tmp_path):
    """The control of each relationship names the fact rows whose key is not in the dimension: a validation result of a run that the table of runs does not have."""
    star = star_files
    h = copy_history(star.history, tmp_path / "orphan")
    conn = connect(h.paths.db)
    try:
        conn.execute("INSERT INTO validation_results VALUES ('ghost', 'V10', 'x', 'blocking', 'delivery', 'per_run', 1, 0, 0, '[]')")
        with pytest.raises(CheckFailedError) as error:
            export_star_schema(conn, tmp_path / "powerbi", MODEL, star.run, h.sealed, seal_path=h.paths.seal)
        assert {c.check_id for c in error.value.checks if c.violations} == {"chk_fk_r15_fact_validation_dim_pipeline_run"}
    finally:
        conn.close()


def test_a_set_with_a_missing_changed_or_unlisted_file_is_refused(star_files, copy_of):
    """RNF05: the manifest is written last with each file's bytes and SHA-256; ``verify_star_schema`` finds a file that is gone, one whose bytes changed, one the
    manifest does not list, and a folder with no manifest (a set left half written)."""
    star = star_files
    assert verify_star_schema(star.out_dir) == []
    manifest = json.loads((star.out_dir / STAR_MANIFEST).read_text(encoding="utf-8"))
    assert [f["name"] for f in manifest["files"]] == [f"{t.name}.parquet" for t in MODEL.tables]
    assert manifest["run_key"] == star.run.run_key and manifest["attribution"] == ATTRIBUTION
    for entry in manifest["files"]:
        data = (star.out_dir / entry["name"]).read_bytes()
        assert (entry["bytes"], entry["sha256"]) == (len(data), hashlib.sha256(data).hexdigest())
    folder = copy_of(star.out_dir)
    (folder / "dim_date.parquet").unlink()
    (folder / "dim_hour.parquet").write_bytes(b"changed")
    (folder / "stray.parquet").write_bytes(b"x")
    problems = verify_star_schema(folder)
    assert len(problems) == 3 and any("dim_date.parquet" in p for p in problems) and any("dim_hour.parquet" in p for p in problems) and any("stray.parquet" in p for p in problems)
    (folder / STAR_MANIFEST).unlink()
    assert len(verify_star_schema(folder)) == 1 and "manifiesto" in verify_star_schema(folder)[0]


def test_a_file_over_the_limit_is_refused_before_anything_is_written(star_files, tmp_path, monkeypatch):
    """RNF10: a Parquet file over the size limit is an error naming it, and neither a file nor a manifest of the new export exists afterwards."""
    star = star_files
    h = copy_history(star.history, tmp_path / "big")
    conn = connect(h.paths.db)
    try:
        monkeypatch.setattr(export, "MAX_PARQUET_BYTES", 1000)
        with pytest.raises(ValueError, match=r"^(dim|fact)_\w+\.parquet pesa \d+ bytes, más de 1000") as error:
            export_star_schema(conn, tmp_path / "powerbi", MODEL, star.run, h.sealed, seal_path=h.paths.seal)
        assert str(error.value).split(".parquet")[0] in [t.name for t in MODEL.tables]
    finally:
        conn.close()
    assert not list((tmp_path / "powerbi").glob("*"))


def test_exporting_again_gives_the_same_bytes_and_replaces_a_previous_set(star_files, tmp_path):
    """RNF01, RNF05: two exports of the same warehouse and run are identical byte by byte, and a set already there is replaced file by file with its manifest last."""
    star = star_files
    h = copy_history(star.history, tmp_path / "again")
    out = tmp_path / "powerbi"
    out.mkdir()
    (out / "dim_date.parquet").write_bytes(b"old")
    conn = connect(h.paths.db)
    try:
        export_star_schema(conn, out, MODEL, star.run, h.sealed, seal_path=h.paths.seal)
        export_star_schema(conn, out, MODEL, star.run, h.sealed, seal_path=h.paths.seal)
    finally:
        conn.close()
    assert verify_star_schema(out) == [] and sorted(p.name for p in out.iterdir()) == sorted([STAR_MANIFEST, *(f"{t.name}.parquet" for t in MODEL.tables)])
    for table in MODEL.tables:
        assert (out / f"{table.name}.parquet").read_bytes() == (star.out_dir / f"{table.name}.parquet").read_bytes(), table.name
    assert not [p for p in out.iterdir() if p.suffix == ".tmp"]


# --- the sensitivities, the seal, the instant and the refusals --------------------------------------------------------------


def exported(star, tmp_path, *, run=None, seal_path=None, prepare=None):
    """The star model exported again from a copy of the history (after `prepare(conn)` changed the copy) to its own folder: ``(out_dir, copy)``."""
    h = copy_history(star.history, tmp_path / "copy")
    conn = connect(h.paths.db)
    try:
        if prepare is not None:
            prepare(conn)
        export_star_schema(conn, tmp_path / "powerbi", MODEL, run or star.run, h.sealed, seal_path=seal_path or h.paths.seal)
    finally:
        conn.close()
    return tmp_path / "powerbi", h


def test_a_sensor_that_passed_the_gate_has_its_label_its_curve_and_its_sign_check(star_files, tmp_path):
    """D20: a sensor of the gate shows «asociación del modelo», the range of its curve and whether it kept its sign in the test; the others say «sin asociación estable» and have
    none of those. (The small history passes no sensor, so the copy is made to pass one by hand.)"""
    def prepare(conn):
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'eval_%'").fetchall():
            conn.execute(f"DROP TRIGGER {name}")
        conn.execute("UPDATE eval_sensitivity SET passes = 1, sign_stable = 1, rho_min = 0.6, rho_max = 0.9, sign = 1 WHERE sensor = 'amina_flow' AND seal_state = 'sealed'")
        conn.executemany("INSERT INTO eval_pd_curve VALUES ('amina_flow', 'launch', ?, ?, ?, 'sealed', 'r1')", [(0, 1.0, 2.0), (1, 2.0, 2.5), (2, 3.0, 2.25)])
        conn.execute("INSERT INTO eval_sensitivity_test VALUES ('amina_flow', 1, 0.7, 1, 'sealed', 'r4')")

    out, _h = exported(star_files, tmp_path, prepare=prepare)
    sensitivity = {s["sensor_key"]: s for s in pq.read_table(out / "fact_sensitivity.parquet").to_pylist()}
    passed = sensitivity.pop("amina_flow")
    assert (passed["passes"], passed["sign_stable"], passed["label_es"], passed["test_sign_kept"]) == (True, True, "asociación del modelo", True)
    assert (passed["rho_min"], passed["rho_max"], passed["pd_range"]) == pytest.approx((0.6, 0.9, 0.5))
    assert len(sensitivity) == 18 and {(s["passes"], s["label_es"], s["test_sign_kept"], s["pd_range"]) for s in sensitivity.values()} == {(False, "sin asociación estable", None, None)}
    curve = pq.read_table(out / "fact_pd_curve.parquet").to_pylist()
    assert [(c["sensor_key"], c["point"], c["grid_value"], c["mean_estimate"]) for c in curve] == [("amina_flow", 0, 1.0, 2.0), ("amina_flow", 1, 2.0, 2.5), ("amina_flow", 2, 3.0, 2.25)]


def test_the_variants_carry_the_interval_of_the_model_against_the_persistence(star_files):
    """C10: each variant row of the model has the interval of its difference with the persistence (the one the evaluation stored), and the persistence has none."""
    star = star_files
    stored = {(variant, horizon, metric): value for variant, horizon, metric, value in sql(
        star, "SELECT variant, horizon, metric, value FROM eval_variants WHERE seal_state = 'sealed' AND method = 'model_vs_b1_persistence' AND metric IN ('ci_low', 'ci_high')")}
    assert stored, "the small history has variants with an interval"
    shown = rows(star, "fact_variants")
    for row in shown:
        key = (row["variant"], row["horizon_key"])
        if row["method_key"] == "model" and (*key, "ci_low") in stored:
            assert (row["ci_low"], row["ci_high"]) == pytest.approx((stored[(*key, "ci_low")], stored[(*key, "ci_high")]))
        else:
            assert (row["ci_low"], row["ci_high"]) == (None, None)
    assert sum(row["ci_low"] is not None for row in shown) == len({(v, h) for v, h, _ in stored}) > 0
    assert all(row["variant_es"] != row["variant"] for row in shown)


def test_a_model_of_another_configuration_than_the_sealed_one_is_post_seal(star_files, tmp_path):
    """M05: the seal says which configuration it sealed; a model registered under another one is shown as ``post_seal`` in the dimension."""
    star = star_files
    document = json.loads(star.history.paths.seal.read_text(encoding="utf-8"))
    document["launch"]["config_sha256"] = "9" * 64
    seal = tmp_path / "other_seal.json"
    seal.write_text(json.dumps(document), encoding="utf-8")
    out, _h = exported(star, tmp_path, seal_path=seal)
    assert {m["seal_state"] for m in pq.read_table(out / "dim_model.parquet").to_pylist()} == {"post_seal"}


def test_the_star_model_of_an_earlier_instant_holds_only_what_was_known_then(star_files, tmp_path):
    """RNF06 (a): exported as of an earlier run, the hours that had not closed, the estimates not yet issued and the analyses not yet arrived are not in the tables, although the
    warehouse already holds them."""
    star = star_files
    earlier = star.history.runs[1]
    out, h = exported(star, tmp_path, run=earlier, prepare=lambda conn: track(conn, earlier, star.history.sealed))
    now = stamp(earlier.as_of)
    process_hours = {r["hour_key"] for r in pq.read_table(out / "fact_hour_process.parquet").to_pylist()}
    lab = {r["hour_key"]: r for r in pq.read_table(out / "fact_hour_lab.parquet").to_pylist()}
    conn = sqlite3.connect(h.paths.db)
    try:
        closed = {hour_key for (hour_key,) in conn.execute("SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) FROM lab_hours WHERE hour < ?", (now,))}
        late = {hour_key for (hour_key,) in conn.execute("SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) FROM lab_hours WHERE available_at > ?", (now,))}
        issued = conn.execute("SELECT COUNT(*) FROM estimates WHERE issue_at <= ?", (now,)).fetchone()[0]
        later = conn.execute("SELECT COUNT(*) FROM estimates WHERE issue_at > ?", (now,)).fetchone()[0]
    finally:
        conn.close()
    assert process_hours == closed and set(lab) == closed and later > 0
    assert {k for k, r in lab.items() if r["lab_state"] == "pending"} == late & closed and all(lab[k]["silica_pct"] is None for k in late & closed)
    estimates = pq.read_table(out / "fact_estimate.parquet").to_pylist()
    assert len(estimates) == issued and max(e["issue_at"] for e in estimates) <= earlier.as_of
    assert all(e["actual"] is None for e in estimates if e["hour_key"] in late)
    assert max(r["hour"] for r in pq.read_table(out / "dim_hour.parquet").to_pylist()) < earlier.as_of + timedelta(hours=3)


def test_the_star_model_is_not_exported_before_the_launch_has_registered_a_model(small_store, quick_cfg, tmp_path):
    """The model dimension reads the registry: a warehouse with hours and no registered model has nothing to export, and says so without writing a file."""
    view = sealed_view(quick_cfg, "ab" * 32)
    path = tmp_path / "unlaunched.sqlite"
    shutil.copy2(small_store, path)
    conn = connect(path)
    try:
        with pytest.raises(RuntimeError, match="no hay un modelo registrado"):
            export_star_schema(conn, tmp_path / "powerbi", MODEL, RunMeta("r1", "L-small", "launch", datetime(2017, 3, 31), None), view, seal_path=tmp_path / "none.json")
        assert not conn.in_transaction
    finally:
        conn.close()
    assert not (tmp_path / "powerbi").exists()


def test_the_marts_are_rebuilt_only_inside_a_transaction_and_for_a_known_group(small_store):
    conn = connect(small_store)
    try:
        with pytest.raises(RuntimeError, match="dentro de una transacción"):
            rebuild_marts(conn, "powerbi")
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="grupo de marts desconocido"):
            rebuild_marts(conn, "ops")
        conn.execute("ROLLBACK")
    finally:
        conn.close()
