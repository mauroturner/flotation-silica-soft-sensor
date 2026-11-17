"""The estimates of the small history (U10; RF16, D21, D22; M04; AC21 in part): an estimate is issued once and nothing changes it later, the database itself
refuses to change one, every instant gives one estimate per horizon or a ``missing_inputs`` row with its reason, and the model that scores is the one the
registry holds with the hash it has."""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import datetime

import pandas as pd
import pytest

from flotsilica.launch import fit_model
from flotsilica.model import fit_launch
from flotsilica.launch import fit_model, hour_tables
from flotsilica.registry import (
    ArtifactMismatchError,
    ArtifactMissingError,
    ModelBundle,
    SealError,
    bundle_of,
    load_artifact,
    load_registered_bundle,
    read_seal,
    register_model,
    save_artifact,
)
from flotsilica.scoring import (
    METHOD_NAMES,
    EstimateError,
    RunMeta,
    ScoringError,
    issue_instants,
    score_issue,
    score_run,
)
from flotsilica.warehouse import apply_schema, connect
from tests.fixtures.history import HOUR, copy_history, stamp

TABLES = ("estimates", "method_estimates")


def dump(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2, 3").fetchall() for t in TABLES}


def test_estimates_never_change_in_later_runs(small_history, tmp_path):
    h = copy_history(small_history, tmp_path / "later")
    conn = connect(h.paths.db)
    try:
        issued = dump(conn)
        assert len(issued["estimates"]) == 3 * (2 + 12 + 12 + 1) and len(issued["method_estimates"]) == 8 * len(issued["estimates"])
        bundle = load_registered_bundle(conn, h.paths.models, "v1")
        # a later run that reaches the same instants again, with a model that says something else, leaves every row as it was and says it skipped them
        other = dataclasses.replace(bundle, b0_mean=bundle.b0_mean + 1.0, horizons=tuple(
            dataclasses.replace(m, half_width=m.half_width + 1.0, b_star="b1_persistence") for m in bundle.horizons))
        again = score_run(conn, dataclasses.replace(h.runs[1], run_key="r2-again"), other, h.sealed)
        assert (again.issued, again.missing, again.skipped, again.methods) == (0, 0, 36, 0)
        assert dump(conn) == issued
        # every run of the history, scored again, finds all of its estimates and adds none
        for run in h.runs:
            assert score_run(conn, run, bundle, h.sealed).skipped == 3 * len(issue_instants(run))
        assert dump(conn) == issued
    finally:
        conn.close()


def test_the_database_itself_refuses_to_change_or_remove_an_estimate(small_history, tmp_path):
    h = copy_history(small_history, tmp_path / "raw")
    conn = connect(h.paths.db)
    try:
        before = dump(conn)
        estimate = conn.execute("SELECT * FROM estimates ORDER BY target_hour, horizon LIMIT 1").fetchone()
        method = conn.execute("SELECT * FROM method_estimates ORDER BY target_hour, horizon, method LIMIT 1").fetchone()
        registry_row = conn.execute("SELECT model_version FROM model_registry").fetchone()
        attempts = [
            "UPDATE estimates SET estimate = estimate + 1",
            "UPDATE estimates SET status = 'missing_inputs' WHERE horizon = 0",
            "UPDATE estimates SET run_key = 'x'",
            "DELETE FROM estimates WHERE horizon = 1",
            "DELETE FROM estimates",
            "UPDATE method_estimates SET estimate = 0",
            "DELETE FROM method_estimates WHERE method = 'model'",
            "UPDATE model_registry SET artifact_sha256 = 'x'",
            "DELETE FROM model_registry",
        ]
        for statement in attempts:
            with pytest.raises(sqlite3.IntegrityError, match="solo inserción|insert-only|inserción"):
                conn.execute(statement)
        # a second insert of an issued key, in every spelling that would replace it
        marks = ", ".join("?" * len(estimate))
        for verb in ("INSERT", "INSERT OR REPLACE", "INSERT OR IGNORE"):
            with pytest.raises(sqlite3.IntegrityError, match="solo inserción|insert-only|inserción"):
                conn.execute(f"{verb} INTO estimates VALUES ({marks})", estimate)
            with pytest.raises(sqlite3.IntegrityError, match="solo inserción|insert-only|inserción"):
                conn.execute(f"{verb} INTO method_estimates VALUES (?, ?, ?, ?)", method)
        with pytest.raises(sqlite3.IntegrityError, match="solo inserción|insert-only|inserción"):
            conn.execute("INSERT INTO estimates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (target_hour, horizon) DO UPDATE SET estimate = 0",
                         estimate)
        with pytest.raises(sqlite3.IntegrityError, match="solo inserción|insert-only|inserción"):
            conn.execute("INSERT OR REPLACE INTO model_registry SELECT * FROM model_registry")
        assert dump(conn) == before and registry_row == conn.execute("SELECT model_version FROM model_registry").fetchone()
    finally:
        conn.close()


def test_every_instant_of_every_run_has_one_estimate_per_horizon_and_the_rows_hold_their_rules(small_history):
    h = small_history
    conn = sqlite3.connect(h.paths.db)
    try:
        rows = conn.execute("SELECT target_hour, horizon, issue_at, run_key, model_version, status, reason, estimate, low, high, block, is_censored "
                            "FROM estimates ORDER BY issue_at, horizon").fetchall()
        assert [result.issued + result.missing for result in h.results] == [3 * len(issue_instants(run)) for run in h.runs]
        for run in h.runs:
            mine = [r for r in rows if r[3] == run.run_key]
            assert sorted({r[2] for r in mine}) == [stamp(t) for t in issue_instants(run)] and all(sum(1 for r in mine if r[2] == stamp(t)) == 3 for t in issue_instants(run))
        for target, horizon, issue_at, _run, version, status, reason, estimate, low, high, block, censored in rows:
            assert pd.Timestamp(issue_at) == pd.Timestamp(target) + HOUR * (1 - horizon) and version == "v1" and censored == 0
            assert status == "ok" and reason is None and low <= estimate <= high and block in {"purge_2", "outside", "test", "valid_v2"}
        counts = dict(conn.execute("SELECT horizon, COUNT(*) FROM estimates GROUP BY horizon").fetchall())
        assert counts == {0: 27, 1: 27, 2: 27}
        per_method = dict(conn.execute("SELECT method, COUNT(*) FROM method_estimates GROUP BY method").fetchall())
        assert per_method == {name: 81 for name in METHOD_NAMES}
        assert conn.execute("SELECT COUNT(*) FROM method_estimates m JOIN estimates e USING (target_hour, horizon) WHERE m.method = 'model' AND m.estimate != e.estimate").fetchone()[0] == 0
    finally:
        conn.close()


def test_an_instant_without_its_readings_is_a_row_with_its_reason_and_no_number(small_history, tmp_path):
    h = copy_history(small_history, tmp_path / "gap")
    conn = connect(h.paths.db)
    try:
        before = conn.execute("SELECT COUNT(*) FROM estimates").fetchone()[0], conn.execute("SELECT COUNT(*) FROM method_estimates").fetchone()[0]
        in_the_gap = RunMeta("r9", "D-gap", "daily", datetime(2017, 3, 20, 12), datetime(2017, 3, 20, 11))
        result = score_run(conn, in_the_gap, load_registered_bundle(conn, h.paths.models, "v1"), h.sealed)
        assert (result.issued, result.missing, result.skipped, result.methods) == (0, 3, 0, 0)
        rows = conn.execute("SELECT horizon, status, reason, estimate, low, high, persistence, b_star, b_star_method FROM estimates WHERE run_key = 'r9' ORDER BY horizon").fetchall()
        assert rows == [(k, "missing_inputs", "no_sensor_rows", None, None, None, None, None, None) for k in range(3)]
        assert (conn.execute("SELECT COUNT(*) FROM estimates").fetchone()[0], conn.execute("SELECT COUNT(*) FROM method_estimates").fetchone()[0]) == (before[0] + 3, before[1])
    finally:
        conn.close()


def test_a_run_that_fails_midway_stores_nothing_and_one_past_what_was_loaded_is_refused(small_history, tmp_path):
    h = copy_history(small_history, tmp_path / "fail")
    conn = connect(h.paths.db)
    try:
        before = dump(conn)
        bundle = load_registered_bundle(conn, h.paths.models, "v1")
        # three instants of the history that were not issued: the second one fails (M04) after the first has been stored in the transaction
        broken = dataclasses.replace(bundle, horizons=(*bundle.horizons[:2], dataclasses.replace(bundle.horizons[2], half_width=float("nan"))))
        run = RunMeta("r9", "D-early", "daily", datetime(2017, 3, 15, 14), datetime(2017, 3, 15, 11))
        with pytest.raises(EstimateError, match="M04"):
            score_run(conn, run, broken, h.sealed)
        assert dump(conn) == before and not conn.in_transaction
        ok = score_run(conn, run, bundle, h.sealed)
        assert (ok.issued, ok.skipped) == (9, 0)
        later = RunMeta("r10", "D-future", "daily", datetime(2017, 4, 5), datetime(2017, 3, 31, 1))
        with pytest.raises(ScoringError, match="no se pueden declarar"):
            score_run(conn, later, bundle, h.sealed)
        assert conn.execute("SELECT COUNT(*) FROM estimates WHERE run_key = 'r10'").fetchone()[0] == 0
        with pytest.raises(ScoringError, match="nada"):
            score_run(sqlite3.connect(":memory:", isolation_level=None), later, bundle, h.sealed)
    finally:
        conn.close()


def test_the_model_that_scores_is_the_one_the_launch_fitted_and_the_registry_holds_with_its_hash(small_history, tmp_path):
    """The launch goes through ``bundle_of``, ``save_artifact`` and ``load_artifact``, and what comes back scores exactly like the model in memory."""
    h = copy_history(small_history, tmp_path / "bundle")
    conn = connect(h.paths.db)
    try:
        tables = hour_tables(conn, h.runs[0].as_of, h.sealed)
        in_memory = bundle_of(fit_launch(tables, h.sealed), h.sealed)
        digest = save_artifact(in_memory, tmp_path / "again.pkl")
        loaded = load_artifact(tmp_path / "again.pkl", digest)
        registered = load_registered_bundle(conn, h.paths.models, "v1")
    finally:
        conn.close()
    assert isinstance(loaded, ModelBundle) and loaded.version == in_memory.version and [m.horizon for m in loaded.horizons] == [0, 1, 2]
    assert digest == read_registry_sha(h) == fit_digest(h)       # the same fit gives the same bytes, the registry holds them and the seal says them
    compared = 0
    for t in pd.date_range("2017-03-15 06:00", "2017-03-16 05:00", freq="h").to_pydatetime():
        inputs = tables.inputs(t, h.sealed)
        for a, b, c in zip(score_issue(in_memory, inputs, h.sealed), score_issue(loaded, inputs, h.sealed), score_issue(registered, inputs, h.sealed), strict=True):
            assert a.same_as(b) and a.same_as(c)
            compared += a.status == "ok"
    assert compared >= 3 * 24


def read_registry_sha(h) -> str:
    conn = sqlite3.connect(h.paths.db)
    try:
        return conn.execute("SELECT artifact_sha256 FROM model_registry").fetchone()[0]
    finally:
        conn.close()


def fit_digest(h) -> str:
    return read_seal(h.paths.seal)["launch"]["artifact_sha256"]


def test_a_run_after_the_launch_loads_the_model_only_if_the_artifact_has_the_registered_hash(small_history, tmp_path):
    h = copy_history(small_history, tmp_path / "m03")
    artifact = h.paths.models / "v1.pkl"
    good = artifact.read_bytes()
    conn = connect(h.paths.db)
    try:
        assert fit_model(conn, h.runs[1], h.sealed, models_dir=h.paths.models, seal_path=h.paths.seal)["mode"] == "verify"
        artifact.write_bytes(good[:-1] + bytes([good[-1] ^ 1]))
        with pytest.raises(ArtifactMismatchError, match="M03"):
            fit_model(conn, h.runs[1], h.sealed, models_dir=h.paths.models, seal_path=h.paths.seal)
        with pytest.raises(ArtifactMismatchError, match="M03"):
            load_registered_bundle(conn, h.paths.models, "v1")
        artifact.write_bytes(good)
        assert fit_model(conn, h.runs[1], h.sealed, models_dir=h.paths.models, seal_path=h.paths.seal)["seal"] == "match"
        with pytest.raises(ArtifactMissingError, match="no está registrada"):
            load_registered_bundle(conn, h.paths.models, "v9")
        h.paths.seal.unlink()
        with pytest.raises(SealError, match="no hay sello"):
            fit_model(conn, h.runs[1], h.sealed, models_dir=h.paths.models, seal_path=h.paths.seal)
        with pytest.raises(ValueError, match="nombre de archivo"):
            register_model(conn, model_version="v7", trained_as_of="x", artifact_name="../v7.pkl", artifact_sha256="a" * 64, config_sha256="b" * 64, models=[],
                           selection={}, valid_predictions_sha256="c" * 64)
        with pytest.raises(ValueError, match="64 dígitos"):
            register_model(conn, model_version="v7", trained_as_of="x", artifact_name="v7.pkl", artifact_sha256="a", config_sha256="b" * 64, models=[],
                           selection={}, valid_predictions_sha256="c" * 64)
    finally:
        conn.close()


def test_the_table_refuses_a_row_that_breaks_its_own_rules(small_history, tmp_path):
    h = copy_history(small_history, tmp_path / "rules")
    conn = connect(h.paths.db)
    try:
        before = dump(conn)
        base = {"target_hour": "2017-03-12 10:00:00", "horizon": 0, "issue_at": "2017-03-12 11:00:00", "run_key": "r9", "model_version": "v1", "status": "ok",
                "reason": None, "estimate": 2.5, "low": 2.0, "high": 3.0, "persistence": 2.4, "b_star": 2.4, "b_star_method": "b1_persistence", "block": "train",
                "is_censored": 0}
        insert = "INSERT INTO estimates ({}) VALUES ({})"

        def put(**changes):
            row = {**base, **changes}
            conn.execute(insert.format(", ".join(row), ", ".join(f":{k}" for k in row)), row)

        broken = {
            "the issue instant is not the target minus the horizon plus one hour": {"issue_at": "2017-03-12 12:00:00"},
            "the range does not hold the estimate": {"low": 2.6},
            "the range does not hold the estimate (high)": {"high": 2.4},
            "an ok row without its persistence": {"persistence": None},
            "an ok row with a reason": {"reason": "no_sensor_rows"},
            "a missing row with a number": {"status": "missing_inputs", "reason": "no_sensor_rows"},
            "a missing row without its reason": {"status": "missing_inputs", "estimate": None, "low": None, "high": None, "persistence": None, "b_star": None,
                                                  "b_star_method": None},
            "a status that is not one": {"status": "maybe"},
            "a block that is not one": {"block": "validation"},
            "a model that is not registered": {"model_version": "v9"},
            "a B* that is not one of the two": {"b_star_method": "b3"},
        }
        for what, changes in broken.items():
            with pytest.raises(sqlite3.IntegrityError):
                put(**changes)
            assert dump(conn) == before, what
        put()                                                                    # and a row that follows the rules goes in (the table is not closed)
        put(target_hour="2017-03-12 11:00:00", horizon=1, issue_at="2017-03-12 11:00:00")
        put(target_hour="2017-03-12 12:00:00", horizon=0, issue_at="2017-03-12 13:00:00", status="missing_inputs", reason="no_sensor_rows", estimate=None, low=None,
            high=None, persistence=None, b_star=None, b_star_method=None)
        assert len(dump(conn)["estimates"]) == len(before["estimates"]) + 3
        with pytest.raises(sqlite3.IntegrityError):             # a method without the estimate it belongs to
            conn.execute("INSERT INTO method_estimates VALUES ('2017-03-12 09:00:00', 0, 'model', 2.5)")
        with pytest.raises(sqlite3.IntegrityError):             # a method that is not one of the eight
            conn.execute("INSERT INTO method_estimates VALUES ('2017-03-12 10:00:00', 0, 'oracle', 2.5)")
    finally:
        conn.close()


def test_applying_the_schema_again_keeps_the_estimates_and_gives_an_older_warehouse_its_model_tables(small_history, tmp_path):
    h = copy_history(small_history, tmp_path / "schema")
    conn = connect(h.paths.db)
    try:
        before = dump(conn)
        triggers = lambda: sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND name NOT LIKE 'eval_%'"))   # noqa: E731
        assert len(triggers()) == 9
        apply_schema(conn)
        assert dump(conn) == before and len(triggers()) == 9
        # a warehouse made before the model tables existed (U06's) gets them, empty, and its hours are as they were
        hours = conn.execute("SELECT COUNT(*), MIN(hour), MAX(hour) FROM lab_hours").fetchone()
        for name in triggers():
            conn.execute(f"DROP TRIGGER {name}")
        for table in ("method_estimates", "estimates", "model_registry"):
            conn.execute(f"DROP TABLE {table}")
        apply_schema(conn)
        assert dump(conn) == {"estimates": [], "method_estimates": []} and len(triggers()) == 9
        assert conn.execute("SELECT COUNT(*), MIN(hour), MAX(hour) FROM lab_hours").fetchone() == hours
    finally:
        conn.close()
