"""A short history on the small fixture for the tests of the seal and of the estimates (U10): a launch and the deliveries after it loaded one by one, the
model fitted at the launch (``fit_model``) and the estimates of every run issued (``score_run``), as the pipeline does, in a folder of its own.

The small fixture is three weeks with the March gap in the middle: its data after the gap are 38 hours (2017-03-29 11:00 to 2017-03-31 00:00), so the launch
takes everything up to 2017-03-29 23:00 and the deliveries after it are of twelve hours (plan A) or one of twenty-five (plan B). The model learns from the
three blocks of ``small_view``, which are before the gap."""

from __future__ import annotations

import shutil
import sqlite3
import types
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from flotsilica.deliveries import DeliverySpec
from flotsilica.launch import fit_model
from flotsilica.registry import load_registered_bundle, sealed_view
from flotsilica.reporting import evaluate
from flotsilica.scoring import RunMeta, score_run
from flotsilica.warehouse import connect, load_delivery
from tests.fixtures.tiny_model import small_view

HOUR = timedelta(hours=1)
LAUNCH_LAST = datetime(2017, 3, 29, 23)
SOURCE_SHA256 = "ab" * 32


def spec(delivery_id: str, kind: str, first: datetime, last: datetime) -> DeliverySpec:
    return DeliverySpec(delivery_id, kind, first, last, last + HOUR)


PLAN_A = (
    spec("L-small", "launch", datetime(2017, 3, 10, 1), LAUNCH_LAST),
    spec("D-a1", "daily", datetime(2017, 3, 30, 0), datetime(2017, 3, 30, 11)),
    spec("D-a2", "daily", datetime(2017, 3, 30, 12), datetime(2017, 3, 30, 23)),
    spec("D-a3", "daily", datetime(2017, 3, 31, 0), datetime(2017, 3, 31, 0)),
)
PLAN_B = (PLAN_A[0], spec("D-b1", "daily", datetime(2017, 3, 30, 0), datetime(2017, 3, 31, 0)))


def build_history(folder: Path, canonical, quick_cfg, plan=PLAN_A, *, gate=None, **model) -> types.SimpleNamespace:
    """Load `plan` into ``folder/warehouse.sqlite`` run by run (``r1``, ``r2``...), fit the model at the launch and issue each run's estimates."""
    view = small_view(quick_cfg, **model)
    sealed = sealed_view(view, SOURCE_SHA256)
    paths = types.SimpleNamespace(db=folder / "warehouse.sqlite", seal=folder / "reports" / "model_seal.json", models=folder / "models")
    history = types.SimpleNamespace(paths=paths, view=view, sealed=sealed, runs=[], fits=[], results=[], evals=[], plan=(), gate=gate)
    return _continue(history, canonical, plan)


def extend_history(history, folder: Path, canonical, rest) -> types.SimpleNamespace:
    """A copy of `history` in `folder` that goes on with the deliveries `rest`: the launch is fitted once and several histories share it."""
    return _continue(copy_history(history, folder), canonical, rest)


def _continue(history, canonical, plan) -> types.SimpleNamespace:
    paths, sealed = history.paths, history.sealed
    conn = connect(paths.db)
    try:
        previous = history.runs[-1].as_of if history.runs else None
        for delivery in plan:
            rows = canonical.rows[(canonical.rows["hour"] >= delivery.first_hour) & (canonical.rows["hour"] <= delivery.last_hour)]
            hours = canonical.hours[(canonical.hours["hour"] >= delivery.first_hour) & (canonical.hours["hour"] <= delivery.last_hour)]
            run = RunMeta(f"r{len(history.runs) + 1}", delivery.delivery_id, delivery.kind, delivery.as_of, previous)
            load_delivery(conn, rows, hours, delivery, run.run_key, history.view, sha256="f" * 64)
            history.fits.append(fit_model(conn, run, sealed, models_dir=paths.models, seal_path=paths.seal, gate=history.gate))
            history.results.append(score_run(conn, run, load_registered_bundle(conn, paths.models, sealed.model.model_version), sealed))
            history.evals.append(evaluate(conn, run, sealed, seal_path=paths.seal, models_dir=paths.models))
            history.runs.append(run)
            previous = delivery.as_of
    finally:
        conn.close()
    history.plan = (*history.plan, *plan)
    return history


def copy_history(history, target: Path) -> types.SimpleNamespace:
    """A copy of a history's warehouse, seal and models in `target`, for a test that writes."""
    shutil.copytree(history.paths.db.parent, target)
    paths = types.SimpleNamespace(db=target / "warehouse.sqlite", seal=target / "reports" / "model_seal.json", models=target / "models")
    return types.SimpleNamespace(**{**vars(history), "paths": paths, "runs": list(history.runs), "fits": list(history.fits), "results": list(history.results), "evals": list(history.evals)})


def without_sealed_rows(history, target):
    """A copy of the history whose warehouse has no sealed row of the evaluation (what a rebuild from scratch has): the triggers that keep them are dropped in the
    copy, and the rows of the test and of the criteria are deleted. The seal, with its test part, is the one of the history."""
    h = copy_history(history, target)
    conn = sqlite3.connect(h.paths.db)
    try:
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'eval_%'").fetchall():
            conn.execute(f"DROP TRIGGER {name}")
        for table in ("eval_criteria", "eval_bootstrap", "eval_weekly", "eval_variants"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM eval_metrics WHERE scope = 'test'")
        conn.commit()
    finally:
        conn.close()
    return h


def stamp(value) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
