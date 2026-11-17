"""The tasks of a run, their state, the ordered close and the refusals (U17; AC07, AC29, AC30, AC37; RF25, RNF16; plan, sections 3 and 22; D29; adapted from project 04's tests):
a closed run refuses every task and keeps its records, a run that did not load its own delivery writes nothing, a load needs a passed validation of its own run, the
failure handler never hides the task's error, a rejected run changes no published file, the close writes in its order, the commands hold the single-writer lock, and the flow
issues and evaluates what the functions it wraps do when called directly.

The flow runs over the small fixture (``tests/fixtures/pipeline_state.py``): the launch, one delivery of twenty-five hours and the close. A test that writes works on a copy of
the state a session fixture built."""

from __future__ import annotations

import dataclasses
import json
import logging
import sqlite3
import tempfile
import threading
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from flotsilica import lock, pipeline
from flotsilica.deliveries import MANIFEST_NAME, mark_delivery, read_manifest
from flotsilica.export import verify_star_schema
from flotsilica.pipeline import TASK_IDS, RunLockedError, RunRefusedError, RunStateError, UsageError
from flotsilica.site_export import SiteExportError
from flotsilica.validate import ValidationError
from tests.fixtures.pipeline_state import (
    CLOSE_ID,
    DAILY_ID,
    LAUNCH_ID,
    content_of,
    copy_state,
    published_digest,
    query,
    runs_of,
    state_of,
    tamper_delivery,
    tree_digest,
)


def advance(cfg, run_key: str, upto: str) -> None:
    """The tasks of a run from the first to `upto`, each as the DAG runs it."""
    for task_id in TASK_IDS[: TASK_IDS.index(upto) + 1]:
        pipeline.run_task(task_id, run_key, cfg)


def state_file(cfg, run_key: str) -> dict:
    return json.loads((Path(cfg.paths.interim_dir) / "runs" / f"{run_key}.json").read_text(encoding="utf-8"))


def from_another_thread(call):
    """The error `call` raises when another thread of this process holds the lock (the lock refuses a second thread of its own process), or None."""
    outcome: dict[str, BaseException] = {}

    def target() -> None:
        try:
            call()
        except BaseException as error:
            outcome["error"] = error

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout=120)
    return outcome.get("error")


# --- the RED of U17 ------------------------------------------------------------------------------------------------------


def test_closed_run_refuses_every_task_and_keeps_its_records(pipeline_replayed, tmp_path, quick_cfg):
    """AC30: every task of a run that ended, ``ok`` or ``no_delivery``, is refused before anything is written (exit 2): the state files, the warehouse, the exported files
    and the reports are the same bytes afterwards, and so are the rows of ``pipeline_runs``."""
    state = copy_state(pipeline_replayed, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    closed = [key for key, status in runs_of(cfg).items() if status in ("ok", "no_delivery")]
    assert sorted(runs_of(cfg).values()) == ["no_delivery", "ok", "ok", "ok"] and len(closed) == 4
    before, rows = tree_digest(state.root), query(cfg, "SELECT * FROM pipeline_runs ORDER BY run_key")
    for run_key in closed:
        for task_id in TASK_IDS:
            with pytest.raises(RunRefusedError, match="está cerrada") as refused:
                pipeline.run_task(task_id, run_key, cfg)
            assert refused.value.exit_code == 2
        with pytest.raises(RunRefusedError, match="está cerrada"):
            pipeline.run_all(cfg, only=["report"], run_key=run_key)
    assert tree_digest(state.root) == before and query(cfg, "SELECT * FROM pipeline_runs ORDER BY run_key") == rows


def test_a_task_of_a_run_that_did_not_load_its_own_delivery_is_refused_and_writes_nothing(pipeline_launched, tmp_path, quick_cfg):
    """AC30: after ``load`` every task works on the delivery its own run loaded. A run that holds a delivery nobody loaded is refused, and so is one whose delivery another
    run loaded (it names the run that did); neither writes a byte."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    advance(cfg, "holder", "deliver")
    assert read_state_delivery(cfg, "holder") == DAILY_ID
    before = tree_digest(state.root)
    for task_id in TASK_IDS[TASK_IDS.index("fit_model"):]:
        with pytest.raises(RunRefusedError, match="no la cargó") as refused:
            pipeline.run_task(task_id, "holder", cfg)
        assert refused.value.exit_code == 2
    assert tree_digest(state.root) == before
    advance(cfg, "owner", "load")
    assert query(cfg, "SELECT run_key FROM deliveries WHERE delivery_id = ?", (DAILY_ID,)) == [("owner",)]
    before = tree_digest(state.root)
    for task_id in TASK_IDS[TASK_IDS.index("load"):]:
        with pytest.raises(RunRefusedError, match="la cargó la corrida owner") as refused:
            pipeline.run_task(task_id, "holder", cfg)
        assert refused.value.exit_code == 2
    assert tree_digest(state.root) == before


def read_state_delivery(cfg, run_key: str) -> str:
    return state_file(cfg, run_key)["tasks"]["deliver"]["delivery_id"]


def test_load_is_refused_without_a_passed_validation_of_this_run(pipeline_launched, tmp_path, quick_cfg):
    """AC30, D93: ``load`` needs the validation report of its own run, and the last run's ``latest.json`` does not stand in for it; a report with a blocking rule that fails refuses
    it too. Nothing is written by the refusals: the delivery is not in the warehouse and the run has no row."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    advance(cfg, "a", "deliver")
    assert (Path(cfg.paths.reports_dir) / "validation" / "latest.json").is_file()      # the launch run's, not this one's
    before = tree_digest(state.root)
    with pytest.raises(RunRefusedError, match="no validó su entrega") as refused:
        pipeline.run_task("load", "a", cfg)
    assert refused.value.exit_code == 2 and tree_digest(state.root) == before
    tamper_delivery(cfg, DAILY_ID)
    with pytest.raises(ValidationError, match="V13"):
        pipeline.run_task("validate", "a", cfg)
    before = tree_digest(state.root)
    with pytest.raises(RunRefusedError, match="rechazó su entrega") as refused:
        pipeline.run_task("load", "a", cfg)
    assert refused.value.exit_code == 2 and tree_digest(state.root) == before
    assert query(cfg, "SELECT COUNT(*) FROM raw_rows WHERE delivery_id = ?", (DAILY_ID,)) == [(0,)] and "a" not in runs_of(cfg)


def test_failure_handler_write_errors_do_not_mask_the_task_error(pipeline_launched, tmp_path, quick_cfg, monkeypatch, caplog):
    """AC29, D79: when a task fails after ``load``, the handler tries each of its writes on its own (the state file, the run's row, the run table, the summary, the HTML), and
    when every one of them fails too the caller sees the task's error, and each failure is in the log."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    advance(cfg, "a", "load")
    attempts: list[str] = []

    def fails(step: str, error: Exception):
        def write(*args, **kwargs):
            attempts.append(step)
            raise error

        return write

    def scoring_blew_up(*args, **kwargs):
        raise RuntimeError("scoring blew up")

    monkeypatch.setattr(pipeline, "score_run", scoring_blew_up)
    monkeypatch.setattr(pipeline, "write_atomic", fails("state", PermissionError(13, "denied")))
    monkeypatch.setattr(pipeline, "record_run", fails("sqlite", sqlite3.OperationalError("database is locked")))
    monkeypatch.setattr(pipeline, "export_run_table", fails("run_table", OSError("disk full")))
    monkeypatch.setattr(pipeline, "export_summary", fails("summary", OSError("disk full")))
    monkeypatch.setattr(pipeline, "render_design", fails("html", OSError("disk full")))
    with caplog.at_level(logging.WARNING, logger="flotsilica.pipeline"):
        with pytest.raises(RuntimeError, match="^scoring blew up$"):
            pipeline.run_task("score", "a", cfg)
    assert attempts == ["state", "sqlite", "run_table", "summary", "html"]
    warned = [r for r in caplog.records if r.levelno == logging.WARNING]
    errors = [str(r.exc_info[1]) for r in warned if r.exc_info]
    assert len(warned) == 5 and all("run a" in r.getMessage() for r in warned)
    assert errors == ["[Errno 13] denied", "database is locked", "disk full", "disk full", "disk full"]


def test_closing_never_creates_a_run_row(pipeline_launched, tmp_path, quick_cfg):
    """AC30: the row of ``pipeline_runs`` is ``load``'s. A run whose row is not there is not closed by ``report``, which says so, and the failure it records creates no row either."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    advance(cfg, "a", "load")
    conn = sqlite3.connect(cfg.paths.warehouse)
    try:
        conn.execute("DELETE FROM pipeline_runs WHERE run_key = 'a'")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(RunStateError, match="no tiene su fila en pipeline_runs"):
        pipeline.run_task("report", "a", cfg)
    assert query(cfg, "SELECT COUNT(*) FROM pipeline_runs WHERE run_key = 'a'") == [(0,)]
    assert state_file(cfg, "a")["status"] == "failed"


def test_report_leaves_the_validation_report_of_its_own_run_as_the_latest(pipeline_launched, tmp_path, quick_cfg):
    """Plan section 3, step 11: ``reports/validation/latest.*`` is the report of the run that closes, whatever another run wrote there while this one was open (a run that holds
    the same pending delivery validates it too). ``report`` writes it before it closes anything; here it stops at the summary, which belongs to another run's export."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    advance(cfg, "a", "load")
    validation = Path(cfg.paths.reports_dir) / "validation"
    (validation / "latest.json").write_text((validation / "history" / "launch.json").read_text(encoding="utf-8"), encoding="utf-8")
    assert json.loads((validation / "latest.json").read_text(encoding="utf-8"))["run_key"] == "launch"
    with pytest.raises(SiteExportError, match="otra corrida"):
        pipeline.run_task("report", "a", cfg)
    assert (validation / "latest.json").read_bytes() == (validation / "history" / "a.json").read_bytes()
    assert (validation / "latest.md").read_bytes() == (validation / "history" / "a.md").read_bytes()


# --- AC07: a rejected run --------------------------------------------------------------------------------------------------


def test_a_rejected_run_leaves_every_published_file_and_the_warehouse_byte_identical(pipeline_launched, tmp_path, quick_cfg):
    """AC07, RF07: a delivery that fails a blocking rule is rejected (the manifest says so, the report names the rule), and the SQLite file, every Parquet of the star model, the
    HTML, every JSON of the site and the seal are the same bytes as before; so is a source that is not the pinned one."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    before = published_digest(cfg)
    assert len(before) == 1 + 1 + 1 + 21 + 6 and runs_of(cfg) == {"launch": "ok"}
    advance(cfg, "bad", "deliver")
    tamper_delivery(cfg, DAILY_ID)
    with pytest.raises(ValidationError, match="V13"):
        pipeline.run_task("validate", "bad", cfg)
    assert published_digest(cfg) == before and runs_of(cfg) == {"launch": "ok"}
    assert state_file(cfg, "bad")["status"] == "rejected" and state_file(cfg, "bad")["tasks"]["validate"]["rules"]
    assert {e.delivery_id: e.status for e in read_manifest(Path(cfg.paths.raw_dir) / "deliveries" / MANIFEST_NAME)}[DAILY_ID] == "rejected"
    report = json.loads((Path(cfg.paths.reports_dir) / "validation" / "history" / "bad.json").read_text(encoding="utf-8"))
    assert report["blocking_failed"] is True
    Path(cfg.source.path).write_bytes(Path(cfg.source.path).read_bytes() + b"\n% changed after the hash was registered\n")
    with pytest.raises(ValidationError, match="V01"):
        pipeline.run_task("fetch_source", "bad-source", cfg)
    assert published_digest(cfg) == before and state_file(cfg, "bad-source")["status"] == "rejected"


def test_a_v01_rejection_writes_only_the_validation_report_and_the_run_state(pipeline_launched, tmp_path, quick_cfg):
    """Plan section 6, V01, as corrected after the evaluation (L66): a source that is not the pinned one changes neither the warehouse, nor the model, nor the seal, nor any
    file of ``outputs/`` or the dashboard; what it writes is the validation report (``latest`` and the run's copy in ``history/``, both versioned in the real configuration),
    which records the rejection, and the state of the rejected run."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    source = Path(cfg.source.path)
    source.write_bytes(source.read_bytes() + b"\n% changed after the hash was registered\n")
    before = tree_digest(state.root)
    with pytest.raises(ValidationError, match="V01"):
        pipeline.run_task("fetch_source", "v01", cfg)
    after = tree_digest(state.root)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    assert changed == ["interim/runs/v01.json", "reports/validation/history/v01.json", "reports/validation/history/v01.md",
                       "reports/validation/latest.json", "reports/validation/latest.md"]
    latest = json.loads((Path(cfg.paths.reports_dir) / "validation" / "latest.json").read_text(encoding="utf-8"))
    assert latest["blocking_failed"] is True and latest["run_key"] == "v01"
    kept = [Path(cfg.paths.warehouse), Path(cfg.paths.models_dir), Path(cfg.paths.seal), Path(cfg.paths.outputs_dir).parent, Path(cfg.paths.dashboard_html)]
    assert all(path.exists() for path in kept)   # the comparison above covers each: they are there and did not change
    assert state_file(cfg, "v01")["status"] == "rejected"


# --- the close ------------------------------------------------------------------------------------------------------------------


def test_a_run_closes_in_order_sqlite_the_run_table_the_summary_the_html_and_only_then_the_delivery(pipeline_replayed):
    """AC29, plan section 3: ``report`` closes the run in SQLite, rewrites the run table alone, then ``summary.json`` with the manifest, then the HTML, and only then does the
    delivery become ``loaded`` in the manifest of deliveries: the events the closing of each run wrote, with the state of the run and of its delivery at each one."""
    state, cfg = pipeline_replayed, pipeline_replayed.cfg
    runs = [key for key in state.runs if key not in ("launch", "idle")]
    assert len(runs) == 2 and runs[0] == state.failed_key
    whole = lambda key: [("run_table", "ok", "published", key), ("summary", "ok", "published", key), ("html", "ok", "published", key), ("delivery_marked", "ok", "published", key)]  # noqa: E731
    for key in runs:
        closing = [e for e in state.events if e[3] == key and e[1] == "ok"]
        if key == state.failed_key:        # its first closing stopped at the HTML (the next test); the repeat closed it
            assert closing[:3] == whole(key)[:3]
            closing = closing[3:]
        assert closing == whole(key)
        assert len([e for e in state.events if e[3] == key and e[0] == "html" and e[1] == "running"]) == 1       # render_dashboard's own
    assert [e[0] for e in state.events if e[3] == state.failed_key and e[1] == "failed"] == ["run_table", "summary", "html"]       # what the failure handler refreshed
    owners = {e.delivery_id: (e.status, e.run_key) for e in read_manifest(Path(cfg.paths.raw_dir) / "deliveries" / MANIFEST_NAME)}
    assert owners == {LAUNCH_ID: ("loaded", "launch"), DAILY_ID: ("loaded", runs[0]), CLOSE_ID: ("loaded", runs[1])}


def test_a_failure_at_the_html_leaves_the_run_failed_and_its_delivery_published_until_the_task_is_repeated(pipeline_replayed):
    """AC29, D72: the delivery is marked ``loaded`` last, so a close that stopped at the HTML left the run ``failed`` (in the state file, in SQLite and in the run table, whose set
    still verified) and the delivery ``published``; repeating ``report`` with the same run key closed it."""
    state = pipeline_replayed
    stopped = state.stopped
    assert (stopped.state_status, stopped.sqlite_status, stopped.table_status, stopped.delivery_status) == ("failed", "failed", "failed", "published") and stopped.star_problems == []
    assert state.runs[state.failed_key] == "ok" and state_file(state.cfg, state.failed_key)["status"] == "ok"
    assert {e.delivery_id: e.status for e in read_manifest(Path(state.cfg.paths.raw_dir) / "deliveries" / MANIFEST_NAME)}[DAILY_ID] == "loaded"


def test_a_failure_after_load_marks_the_run_failed_everywhere_without_a_path_and_a_repeat_reopens_it(pipeline_launched, tmp_path, quick_cfg, monkeypatch):
    """AC29, RNF12: a failure after ``load`` leaves ``failed`` in the state file (with the traceback), in SQLite and in the run table, and rewrites no other exported file; the message
    of the run says the task and the kind of error and carries no path of this machine (the run table is published); repeating the task reopens the run as ``running``."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    advance(cfg, "a", "load")
    exported = {name: digest for name, digest in published_digest(cfg).items() if name.startswith(("outputs/", "dashboard/", "reports/"))}
    real = pipeline.score_run

    def blew_up(*args, **kwargs):
        raise ValueError(f"cannot read {Path(cfg.paths.warehouse)} or {tmp_path / 'elsewhere' / 'file.bin'}")

    monkeypatch.setattr(pipeline, "score_run", blew_up)
    with pytest.raises(ValueError, match="cannot read"):
        pipeline.run_task("score", "a", cfg)
    saved = state_file(cfg, "a")
    assert saved["status"] == "failed" and saved["tasks"]["score"]["status"] == "failed" and "cannot read" in saved["tasks"]["score"]["traceback"]
    [(status, finished, message)] = query(cfg, "SELECT status, finished_at, message FROM pipeline_runs WHERE run_key = 'a'")
    assert status == "failed" and finished is not None and message.startswith("score: ValueError: cannot read ")
    assert message == "score: ValueError: cannot read <path> or <path>"
    table = pq.read_table(Path(cfg.paths.outputs_dir) / "dim_pipeline_run.parquet").to_pylist()
    assert {r["run_key"]: r["status"] for r in table}["a"] == "failed" and verify_star_schema(cfg.paths.outputs_dir) == []
    assert str(tmp_path).encode() not in (Path(cfg.paths.outputs_dir) / "dim_pipeline_run.parquet").read_bytes()
    after = published_digest(cfg)
    changed = {name for name, digest in exported.items() if after[name] != digest}
    assert changed <= {"outputs/powerbi/dim_pipeline_run.parquet", "outputs/powerbi/manifest.json", "dashboard/powerbi-design.html"}
    monkeypatch.setattr(pipeline, "score_run", real)
    pipeline.run_task("track", "a", cfg)
    assert state_file(cfg, "a")["status"] == "running" and query(cfg, "SELECT status, finished_at, message FROM pipeline_runs WHERE run_key = 'a'") == [("running", None, "")]


def test_repeating_a_task_of_a_run_replaces_its_rule_results_and_does_not_fail_on_them(pipeline_launched, tmp_path, quick_cfg):
    """A task that adds rule results to the run's report (``fit_model`` adds M03 and M05) can be run again by the same run (a retry, ``--from fit_model``): its results replace the
    earlier ones, in the report and in ``validation_results``, and the report keeps the rules of the validation."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    advance(cfg, "a", "fit_model")
    first = query(cfg, "SELECT rule_id, passed FROM validation_results WHERE run_key = 'a' ORDER BY rule_id")
    assert {"M03", "M05", "V10", "V13"} <= {rule for rule, _ in first}
    pipeline.run_task("fit_model", "a", cfg)
    assert query(cfg, "SELECT rule_id, passed FROM validation_results WHERE run_key = 'a' ORDER BY rule_id") == first
    report = json.loads((Path(cfg.paths.reports_dir) / "validation" / "history" / "a.json").read_text(encoding="utf-8"))
    assert sorted(r["rule_id"] for r in report["results"]) == [rule for rule, _ in first]


def test_a_run_with_no_delivery_records_no_delivery_and_refreshes_only_the_run_table_and_the_design(pipeline_replayed):
    """AC29, plan section 3, step 2: with nothing pending the run is ``no_delivery`` (its row, its state), the flow stops after ``deliver``, and what was exported is refreshed:
    the run table and the HTML, nothing else (the summary and the site are those of the run that loaded the last delivery)."""
    state, cfg = pipeline_replayed, pipeline_replayed.cfg
    assert [t["task"] for t in state.idle] == ["fetch_source", "deliver"] and state.idle[-1]["result"]["delivered"] is False
    [(status, delivery, finished, message)] = query(cfg, "SELECT status, delivery_id, finished_at, message FROM pipeline_runs WHERE run_key = 'idle'")
    assert (status, delivery) == ("no_delivery", None) and finished is not None and "no hay entregas pendientes" in message
    assert state_file(cfg, "idle")["status"] == "no_delivery"
    table = {r["run_key"]: r["status"] for r in pq.read_table(Path(cfg.paths.outputs_dir) / "dim_pipeline_run.parquet").to_pylist()}
    assert table["idle"] == "no_delivery" and verify_star_schema(cfg.paths.outputs_dir) == []
    after = published_digest(cfg)
    assert {name for name in after if after[name] != state.before_idle[name]} == {
        "flotsilica.sqlite", "outputs/powerbi/dim_pipeline_run.parquet", "outputs/powerbi/manifest.json", "dashboard/powerbi-design.html"}


# --- the refusals that depend on the other runs ----------------------------------------------------------------------------------


def test_a_run_whose_delivery_is_not_the_latest_loaded_refuses_the_model_tasks(pipeline_launched, tmp_path, quick_cfg):
    """AC30, plan section 22: ``fit_model``, ``score``, ``track`` and ``evaluate`` work on the latest loaded delivery; a run whose delivery another run has since followed is
    refused (and writes nothing) in those, and not in the tasks that only export what it holds."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    advance(cfg, "old", "load")
    mark_delivery(Path(cfg.paths.raw_dir) / "deliveries" / MANIFEST_NAME, DAILY_ID, "loaded", "old")       # what the close of "old" does last
    advance(cfg, "new", "load")
    assert query(cfg, "SELECT delivery_id FROM deliveries WHERE run_key = 'new'") == [(CLOSE_ID,)]
    before = tree_digest(state.root)
    for task_id in ("fit_model", "score", "track", "evaluate"):
        with pytest.raises(RunRefusedError, match="calcula la última") as refused:
            pipeline.run_task(task_id, "old", cfg)
        assert refused.value.exit_code == 2
    assert tree_digest(state.root) == before


def test_a_run_that_holds_a_delivery_cannot_deliver_another_one(pipeline_launched, tmp_path, quick_cfg):
    """Plan section 22: ``deliver`` in a run that already holds another delivery is refused; repeating it while that delivery is still the pending one is the same delivery."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    advance(cfg, "a", "deliver")
    assert pipeline.run_task("deliver", "a", cfg)["delivery_id"] == DAILY_ID
    advance(cfg, "b", "load")
    mark_delivery(Path(cfg.paths.raw_dir) / "deliveries" / MANIFEST_NAME, DAILY_ID, "loaded", "b")         # what the close of "b" does last
    before = tree_digest(state.root)
    with pytest.raises(RunRefusedError, match="una corrida no cambia de entrega") as refused:
        pipeline.run_task("deliver", "a", cfg)
    assert refused.value.exit_code == 2 and tree_digest(state.root) == before


def test_the_test_is_not_evaluated_under_another_configuration_before_its_seal_and_the_refusal_exits_2(pipeline_launched, tmp_path, quick_cfg):
    """AC18, D18, D89: while the seal has no test part, a run that reaches the instant the last analysis of the test arrives with a configuration that is not the sealed one is
    refused in every task before it writes (exit 2, ``EvaluationRefusedError`` turned into a ``RunRefusedError``), naming the key that differs; with the sealed one it runs."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    other = dataclasses.replace(cfg, model=dataclasses.replace(cfg.model, rf_n_estimators=cfg.model.rf_n_estimators + 1))
    before = tree_digest(state.root)
    for task_id in TASK_IDS:
        with pytest.raises(RunRefusedError, match=r"model\.rf_n_estimators") as refused:
            pipeline.run_task(task_id, "other", other)
        assert refused.value.exit_code == 2
    with pytest.raises(RunRefusedError, match=r"model\.rf_n_estimators"):
        pipeline.run_all(other, run_key="other")
    assert tree_digest(state.root) == before
    assert pipeline.run_task("fetch_source", "same", cfg)["sha256"]


# --- one writer ------------------------------------------------------------------------------------------------------------------


def test_every_writing_command_holds_the_writer_lock_and_a_second_writer_writes_nothing(pipeline_launched, tmp_path, quick_cfg, monkeypatch):
    """AC31, RNF16, D30: ``run_task``, ``run_all`` and ``replay`` take the lock before the state file is touched: while another holder has it each is refused with exit 2 and the
    folder is the same bytes afterwards; while a task runs the file names the command and the run, and it is gone after (also after a task that failed)."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    before = tree_digest(state.root)
    calls = (lambda: pipeline.run_task("fetch_source", "x", cfg), lambda: pipeline.run_all(cfg, run_key="x"), lambda: pipeline.replay(cfg))
    with lock.sole_writer(cfg.paths.interim_dir, "another command", "other"):
        for call in calls:
            error = from_another_thread(call)
            assert isinstance(error, RunLockedError) and error.state == "thread" and error.exit_code == 2
    assert tree_digest(state.root) == before
    seen: list[dict | None] = []

    def spy(ctx):
        seen.append(lock.read_holder(cfg.paths.interim_dir))
        if len(seen) == 3:
            raise RuntimeError("the third task failed")
        return {"spied": True}

    only = dataclasses.replace(pipeline.TASKS[0], func=spy)
    monkeypatch.setattr(pipeline, "TASKS", (only, *pipeline.TASKS[1:]))
    pipeline.run_task("fetch_source", "x", cfg)
    pipeline.run_all(cfg, only=["fetch_source"], run_key="y")
    assert [(h["command"], h["run_key"]) for h in seen] == [("task fetch_source", "x"), ("run", "y")]
    with pytest.raises(RuntimeError, match="third task failed"):
        pipeline.run_task("fetch_source", "z", cfg)
    assert lock.read_holder(cfg.paths.interim_dir) is None and not (Path(cfg.paths.interim_dir) / lock.LOCK_NAME).exists()
    between: list[dict | None] = []

    def stop_between_runs(*args, **kwargs):
        between.append(lock.read_holder(cfg.paths.interim_dir))      # replay holds the lock from before its first run: no other writer fits between two of them
        raise RuntimeError("stopped before the first run")

    monkeypatch.setattr(pipeline, "run_all", stop_between_runs)
    with pytest.raises(RuntimeError, match="stopped before the first run"):
        pipeline.replay(cfg)
    assert [h["command"] for h in between] == ["replay"] and lock.read_holder(cfg.paths.interim_dir) is None


def test_replay_with_nothing_pending_does_not_take_the_lock(pipeline_replayed, tmp_path, quick_cfg):
    """Plan section 22: a ``replay`` with no pending delivery returns at once and does not take the lock (so it runs while another process writes), and writes nothing."""
    state = copy_state(pipeline_replayed, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    before = tree_digest(state.root)
    with lock.sole_writer(cfg.paths.interim_dir, "another command", "other"):
        outcome: dict = {}
        error = from_another_thread(lambda: outcome.update(runs=pipeline.replay(cfg)))
    assert error is None and outcome["runs"] == [] and tree_digest(state.root) == before


def test_unknown_tasks_and_incompatible_selections_are_usage_errors_before_writing(pipeline_launched, tmp_path, quick_cfg):
    """A task that does not exist, ``only`` with ``start``, an empty ``only`` and an ``until`` that is not a delivery of the plan or is earlier than the next pending one are
    ``UsageError``, and nothing is written."""
    state = copy_state(pipeline_launched, tmp_path / "state", quick_cfg)
    cfg = state.cfg
    before = tree_digest(state.root)
    for call, message in (
        (lambda: pipeline.run_task("nope", "x", cfg), "tarea desconocida"), (lambda: pipeline.run_all(cfg, only=["report"], start="load"), "no se combinan"),
        (lambda: pipeline.run_all(cfg, only=[]), "al menos una tarea"), (lambda: pipeline.replay(cfg, until="D2017-01-01"), "no es una entrega del plan"),
        (lambda: pipeline.replay(cfg, until=LAUNCH_ID), "es anterior a la siguiente entrega pendiente"),
    ):
        with pytest.raises(UsageError, match=message):
            call()
    assert tree_digest(state.root) == before


# --- AC37 and what the flow wraps -----------------------------------------------------------------------------------------------


def test_two_runs_of_the_launch_from_nothing_give_the_same_content_in_every_parquet_and_json_without_the_run_columns(pipeline_launched, tmp_path, quick_cfg, small_arff):
    """AC37, RNF01: the launch run, repeated from nothing, gives the same rows in every Parquet of the star model, the same site files, summary and seal, apart from what names the
    run. (The launch is where the model is fitted, the gate computed and the seal written; the whole synthetic replay twice is the real one of U21.)"""
    second = state_of(tmp_path / "second", quick_cfg, small_arff)
    pipeline.run_all(second.cfg, run_key="again")
    first, again = content_of(pipeline_launched.cfg), content_of(second.cfg)
    assert sorted(first) == sorted(again) and len(first) >= 25
    assert {name for name in first if first[name] != again[name]} == set()


def test_the_files_a_replay_publishes_carry_no_path_of_this_machine(pipeline_replayed):
    """RNF12, D43: nothing the flow publishes (the star model, the site, the reports, the HTML) holds the folder of the run, the temporary folder or the user's, in either spelling
    (the failed run's message went through the run table, whose file was rewritten while it was ``failed``)."""
    cfg = pipeline_replayed.cfg
    files = [p for folder in (cfg.paths.outputs_dir, cfg.paths.site_dir, cfg.paths.reports_dir) for p in Path(folder).rglob("*") if p.is_file()] + [Path(cfg.paths.dashboard_html)]
    assert len(files) >= 30
    needles = {str(pipeline_replayed.root), pipeline_replayed.root.as_posix(), str(Path.home()), Path.home().as_posix(), tempfile.gettempdir(), Path(tempfile.gettempdir()).as_posix()}
    for path in files:
        data = path.read_bytes()
        assert not [n for n in needles if n.encode() in data], path.name


def test_the_flow_issues_and_evaluates_what_calling_the_functions_directly_does(pipeline_replayed, small_history_one_batch):
    """The tasks wrap ``fit_model``, ``score_run`` and ``evaluate`` and change nothing they do: the estimates, the other methods and the sealed figures of the flow are those
    of the same hours run through the functions directly (``tests/fixtures/history.py``), apart from the censoring (the flow's calendar ends where the data end)."""
    cfg, direct = pipeline_replayed.cfg, small_history_one_batch.paths.db
    queries = {
        "estimates": "SELECT target_hour, horizon, issue_at, model_version, status, reason, estimate, low, high, persistence, b_star, b_star_method, block FROM estimates ORDER BY 1, 2",
        "methods": "SELECT target_hour, horizon, method, estimate FROM method_estimates ORDER BY 1, 2, 3",
        "metrics": "SELECT scope, horizon, method, metric, value FROM eval_metrics WHERE seal_state = 'sealed' ORDER BY 1, 2, 3, 4",
        "criteria": "SELECT criterion_id, value, baseline_value, ci_low, ci_high, passed FROM eval_criteria WHERE seal_state = 'sealed' ORDER BY 1",
    }
    conn = sqlite3.connect(direct)
    try:
        for name, sql in queries.items():
            flow, other = query(cfg, sql), conn.execute(sql).fetchall()
            assert flow and flow == other, name
    finally:
        conn.close()
    censored = query(cfg, "SELECT COUNT(*) FROM estimates WHERE is_censored = 1")[0][0]
    assert censored == query(cfg, "SELECT COUNT(*) FROM estimates WHERE target_hour > ?", (cfg.hours.last_hour.strftime("%Y-%m-%d %H:%M:%S"),))[0][0] > 0
