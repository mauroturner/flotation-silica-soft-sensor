"""The evaluation of the test and the tables of the launch (U11; RF18, AC19, AC22; D16, D18): the test is evaluated once, from what was issued, with the figures in the seal
and in the sealed rows of the warehouse; a repetition reproduces it and writes nothing; the database refuses to change a sealed row; and the launch stored what the
summary shows before the test."""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from flotsilica.evalstore import store_group
from flotsilica.registry import EvaluationRefusedError, read_seal, sealed_view
from flotsilica.reporting import evaluate
from flotsilica.warehouse import connect
from tests.fixtures.history import SOURCE_SHA256, copy_history, without_sealed_rows


def rows(db, sql: str, *args) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def test_the_test_is_evaluated_once_from_what_was_issued_and_written_to_the_seal_and_the_warehouse(small_history):
    h = small_history
    seal = read_seal(h.paths.seal)["test"]
    assert [e["test"] for e in h.evals] == ["pending", "pending", "pending", "written"] and seal["run_key"] == "r4" and seal["as_of"] == "2017-03-31 01:00:00"
    assert rows(h.paths.db, "SELECT COUNT(*) FROM eval_criteria WHERE seal_state = 'sealed'")[0][0] == 10 and not rows(h.paths.db, "SELECT 1 FROM eval_criteria WHERE seal_state = 'post_seal'")
    # the hours of each horizon are the fresh hours of the test with an estimate that has numbers, counted here from the tables
    for horizon in (0, 1, 2):
        expected = rows(h.paths.db, "SELECT COUNT(*) FROM estimates e JOIN lab_hours l ON l.hour = e.target_hour WHERE e.horizon = ? AND e.block = 'test' AND e.status = 'ok' "
                        "AND l.lab_state = 'fresh'", horizon)[0][0]
        assert 10 < expected <= 24 and seal["metrics"]["horizons"][str(horizon)]["hours"] == expected
        stored = dict(rows(h.paths.db, "SELECT method, value FROM eval_metrics WHERE scope = 'test' AND horizon = ? AND metric = 'hours' AND seal_state = 'sealed'", horizon))
        assert set(stored) == {"model", "b_star", "b0_train_mean", "b1_persistence", "b2_rolling", "b3_ridge_sensors", "best_sensors_only", "best_lab_only", "best_with_sensors"}
        assert set(stored.values()) == {float(expected)}
    # the MAE of the model is the mean of |estimate - analysis| over those hours, written out here from the issued estimates
    actual = pd.Series(dict(rows(h.paths.db, "SELECT e.target_hour, e.estimate - l.silica_pct FROM estimates e JOIN lab_hours l ON l.hour = e.target_hour "
                                 "WHERE e.horizon = 0 AND e.block = 'test' AND e.status = 'ok' AND l.lab_state = 'fresh'")))
    figures = seal["metrics"]["horizons"]["0"]["methods"]["model"]
    assert figures["mae"] == pytest.approx(actual.abs().mean()) and figures["bias"] == pytest.approx(actual.mean())
    assert rows(h.paths.db, "SELECT value FROM eval_metrics WHERE scope = 'test' AND horizon = 0 AND method = 'model' AND metric = 'mae'")[0][0] == figures["mae"]
    # the criteria of the seal are those of the warehouse, value by value, and C01 is the two errors it compares
    stored = {r[0]: r[1:] for r in rows(h.paths.db, "SELECT criterion_id, value, baseline_value, ci_low, ci_high, passed, verdict_es FROM eval_criteria WHERE seal_state = 'sealed'")}
    for entry in seal["criteria"]:
        value, baseline, low, high, passed, verdict = stored[entry["id"]]
        assert (value, baseline, low, high, verdict) == (entry["value"], entry["baseline_value"], entry["ci_low"], entry["ci_high"], entry["verdict_es"])
        assert passed == (None if entry["passed"] is None else int(entry["passed"]))
    c01 = next(e for e in seal["criteria"] if e["id"] == "C01")
    assert (c01["value"], c01["baseline_value"]) == (figures["mae"], seal["metrics"]["horizons"]["0"]["methods"]["b1_persistence"]["mae"])
    assert c01["passed"] == (c01["value"] < c01["baseline_value"]) and [e["id"] for e in seal["criteria"]] == [f"C{i:02d}" for i in range(1, 11)]
    assert {(w["horizon"], w["method"]) for w in seal["weekly"]} == {(h_, m) for h_ in (0, 1, 2) for m in ("model", "b1_persistence", "b_star")} and {w["week"] for w in seal["weekly"]} == {"2017-03-30"}
    gate = read_seal(h.paths.seal)["launch"]["gate"]
    sensitivity = seal["metrics"]["sensitivity"]
    assert gate["computed"] is True and sensitivity["computed"] is True and sensitivity["passing"] == gate["passing"]
    assert [c["sensor"] for c in seal["sensitivity_test"]] == gate["passing"] and set(sensitivity["kept_sign"]) == {c["sensor"] for c in seal["sensitivity_test"] if c["kept_sign"]}
    c09 = next(e for e in seal["criteria"] if e["id"] == "C09")
    assert (c09["value"], c09["baseline_value"], c09["passed"]) == (float(len(sensitivity["kept_sign"])), float(len(gate["passing"])), len(sensitivity["kept_sign"]) > 0)
    assert rows(h.paths.db, "SELECT COUNT(*) FROM eval_sensitivity WHERE seal_state = 'sealed'")[0][0] == 19 and rows(h.paths.db, "SELECT COUNT(*) FROM eval_sensitivity_test")[0][0] == len(gate["passing"])


def test_a_repetition_reproduces_the_seal_and_the_sealed_rows_are_never_written_again(small_history, tmp_path):
    h = copy_history(small_history, tmp_path / "repeat")
    then = h.paths.seal.read_bytes()
    before = rows(h.paths.db, "SELECT * FROM eval_criteria ORDER BY criterion_id")
    conn = connect(h.paths.db)
    try:
        assert evaluate(conn, h.runs[-1], h.sealed, seal_path=h.paths.seal, models_dir=h.paths.models)["test"] == "sealed_before"      # the warehouse has the sealed rows
    finally:
        conn.close()
    assert h.paths.seal.read_bytes() == then and rows(h.paths.db, "SELECT * FROM eval_criteria ORDER BY criterion_id") == before
    # a warehouse that was rebuilt (no sealed rows) evaluates again under the sealed configuration: the result is the sealed one, to the 6 decimals of the seal
    rebuilt = without_sealed_rows(small_history, tmp_path / "rebuilt")
    conn = connect(rebuilt.paths.db)
    try:
        outcome = evaluate(conn, rebuilt.runs[-1], rebuilt.sealed, seal_path=rebuilt.paths.seal, models_dir=rebuilt.paths.models)
    finally:
        conn.close()
    assert outcome["test"] == "unchanged" and rebuilt.paths.seal.read_bytes() == then
    assert rows(rebuilt.paths.db, "SELECT * FROM eval_criteria ORDER BY criterion_id") == before, "the sealed rows are written again, the same"


def test_the_database_refuses_to_change_remove_or_rewrite_a_sealed_row_of_the_evaluation(small_history, tmp_path):
    h = copy_history(small_history, tmp_path / "refuse")
    conn = connect(h.paths.db)
    try:
        before = {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2, 3, 4").fetchall() for t in ("eval_criteria", "eval_metrics", "eval_bootstrap", "eval_weekly", "eval_variants",
                                                                                                "eval_selection", "eval_baselines", "eval_leakage")}
        for table in before:
            assert before[table], table
            with pytest.raises(sqlite3.IntegrityError, match="solo inserción"):
                conn.execute(f"UPDATE {table} SET run_key = 'x'")
            with pytest.raises(sqlite3.IntegrityError, match="solo inserción"):
                conn.execute(f"DELETE FROM {table}")
            with pytest.raises(sqlite3.IntegrityError, match="solo inserción"):
                conn.execute(f"INSERT OR REPLACE INTO {table} SELECT * FROM {table} LIMIT 1")
        conn.execute("INSERT INTO eval_leakage VALUES ('x', 'x', 0, 0, 0, 'x', 'post_seal', 'r9')")           # a post-seal row can be written, changed and removed
        conn.execute("UPDATE eval_leakage SET mae = 1 WHERE check_id = 'x'")
        with pytest.raises(sqlite3.IntegrityError, match="solo inserción"):                                    # but it cannot become a sealed one
            conn.execute("UPDATE eval_leakage SET seal_state = 'sealed' WHERE check_id = 'x'")
        conn.execute("DELETE FROM eval_leakage WHERE check_id = 'x'")
        assert {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2, 3, 4").fetchall() for t in before} == before
    finally:
        conn.close()


def test_the_launch_stored_what_the_summary_shows_before_the_test(small_launched):
    h = small_launched
    launch = read_seal(h.paths.seal)["launch"]
    conn = sqlite3.connect(h.paths.db)
    try:
        selection = conn.execute("SELECT horizon, candidate, chosen, mae_v1, feature_set, target FROM eval_selection WHERE seal_state = 'sealed' ORDER BY 1, 2").fetchall()
        baselines = conn.execute("SELECT horizon, method, k, mae_v1, cohort_v1 FROM eval_baselines ORDER BY 1, 2").fetchall()
        validation = conn.execute("SELECT scope, horizon, method, metric, value FROM eval_metrics WHERE seal_state = 'sealed'").fetchall()
        leakage = {r[0]: r for r in conn.execute("SELECT check_id, mae, r2, rows, note_es FROM eval_leakage WHERE seal_state = 'sealed'")}
    finally:
        conn.close()
    assert [sum(1 for s in selection if s[0] == k) for k in (0, 1, 2)] == [5, 5, 5], "every candidate of the grid, with its error on V1 (D14)"
    for entry in launch["horizons"]:
        chosen = [s for s in selection if s[0] == entry["horizon"] and s[2] == 1]
        assert len(chosen) == 1 and chosen[0][3] == pytest.approx(entry["mae_v1"]) == min(s[3] for s in selection if s[0] == entry["horizon"])
        assert (chosen[0][4], chosen[0][5]) == (entry["feature_set"], entry["target"])
    assert [(b[0], b[1]) for b in baselines] == [(k, m) for k in (0, 1, 2) for m in ("b0_train_mean", "b1_persistence", "b2_rolling", "b3_ridge_sensors")]
    assert {b[2] for b in baselines if b[1] == "b2_rolling"} <= {3, 6, 12, 24} and all(b[2] is None for b in baselines if b[1] != "b2_rolling") and all(b[4] > 0 for b in baselines)
    methods = {(v[0], v[1]) for v in validation}
    assert methods == {(s, k) for s in ("valid_v1", "valid_v2") for k in (0, 1, 2)} and not any(v[0] == "test" for v in validation)
    assert {v[2] for v in validation} >= {"model", "b_star", "b1_persistence", "b2_rolling", "b3_ridge_sensors", "b0_train_mean", "best_lab_only"}
    assert [v[4] for v in validation if v[2] == "model" and v[3] == "coverage" and v[0] == "valid_v2"] and all(v[4] is None or np.isfinite(v[4]) for v in validation)
    assert set(leakage) == {"blocks", "random_split", "iron_conc"} and all(r[3] > 5 for r in leakage.values())
    assert leakage["iron_conc"][1] < leakage["blocks"][1], "the iron of the concentrate of the target hour is a leak: the error falls"
    assert leakage["iron_conc"][2] > leakage["blocks"][2], "and the R² rises"


def test_another_configuration_is_refused_before_the_test_seal_and_nothing_is_written(small_launched, tmp_path):
    """The evaluation under another configuration than the sealed one, while the seal has no test part, stops before it reads or writes anything."""
    h = copy_history(small_launched, tmp_path / "refused")
    other = sealed_view(dataclasses.replace(h.view, evaluation=dataclasses.replace(h.view.evaluation, bootstrap_resamples=h.view.evaluation.bootstrap_resamples + 1)), SOURCE_SHA256)
    ready = dataclasses.replace(h.runs[0], as_of=datetime(2017, 3, 31, 1))
    seal, tables = h.paths.seal.read_bytes(), {t: rows(h.paths.db, f"SELECT * FROM {t} ORDER BY 1, 2, 3, 4") for t in ("eval_criteria", "eval_metrics", "eval_variants", "estimates")}
    conn = connect(h.paths.db)
    try:
        with pytest.raises(EvaluationRefusedError, match=r"evaluation\.bootstrap_resamples"):
            evaluate(conn, ready, other, seal_path=h.paths.seal, models_dir=h.paths.models)
        assert evaluate(conn, dataclasses.replace(ready, as_of=datetime(2017, 3, 30, 12)), other, seal_path=h.paths.seal, models_dir=h.paths.models)["test"] == "pending"
    finally:
        conn.close()
    assert h.paths.seal.read_bytes() == seal and {t: rows(h.paths.db, f"SELECT * FROM {t} ORDER BY 1, 2, 3, 4") for t in tables} == tables


def test_a_sealed_group_is_written_once_and_a_post_seal_group_is_replaced(small_launched, tmp_path):
    h = copy_history(small_launched, tmp_path / "groups")
    conn = connect(h.paths.db)
    columns = ("check_id", "description_es", "mae", "r2", "rows", "note_es")
    try:
        conn.execute("DELETE FROM eval_leakage WHERE seal_state = 'post_seal'")
        for state in ("post_seal", "sealed"):
            where = "check_id LIKE 'g%'"
            assert store_group(conn, "eval_leakage", columns, [("g1", "d", 1.0, 0.5, 10, "n")], state, "r1", where=where) is True
            first = conn.execute("SELECT mae, run_key FROM eval_leakage WHERE check_id = 'g1' AND seal_state = ?", (state,)).fetchall()
            again = store_group(conn, "eval_leakage", columns, [("g1", "d", 2.0, 0.6, 20, "n"), ("g2", "d", 3.0, 0.7, 30, "n")], state, "r2", where=where)
            kept = conn.execute("SELECT check_id, mae, run_key FROM eval_leakage WHERE check_id LIKE 'g%' AND seal_state = ? ORDER BY 1", (state,)).fetchall()
            if state == "sealed":
                assert again is False and kept == [("g1", 1.0, "r1")] and first == [(1.0, "r1")], "a sealed group is left as it was"
            else:
                assert again is True and kept == [("g1", 2.0, "r2"), ("g2", 3.0, "r2")], "a post-seal group is replaced by the repetition"
        with pytest.raises(ValueError, match="seal_state"):
            store_group(conn, "eval_leakage", columns, [], "maybe", "r3")
    finally:
        conn.close()
    assert rows(h.paths.db, "SELECT COUNT(*) FROM eval_leakage WHERE seal_state = 'sealed' AND check_id IN ('blocks', 'random_split', 'iron_conc')")[0][0] == 3
