"""A short history on the small fixture for the tests of the seal and of the estimates (U10): a launch and the deliveries after it loaded one by one, the
model fitted at the launch (``fit_model``) and the estimates of every run issued (``score_run``), as the pipeline does, in a folder of its own.

The small fixture is three weeks with the March gap in the middle: its data after the gap are 38 hours (2017-03-29 11:00 to 2017-03-31 00:00), so the launch
takes everything up to 2017-03-29 23:00 and the deliveries after it are of twelve hours (plan A) or one of twenty-five (plan B). The model learns from the
three blocks of ``small_view``, which are before the gap."""

from __future__ import annotations

import shutil
import types
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from flotsilica.deliveries import DeliverySpec
from flotsilica.launch import fit_model
from flotsilica.registry import load_registered_bundle, sealed_view
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


def build_history(folder: Path, canonical, quick_cfg, plan=PLAN_A, **model) -> types.SimpleNamespace:
    """Load `plan` into ``folder/warehouse.sqlite`` run by run (``r1``, ``r2``...), fit the model at the launch and issue each run's estimates."""
    view = small_view(quick_cfg, **model)
    sealed = sealed_view(view, SOURCE_SHA256)
    paths = types.SimpleNamespace(db=folder / "warehouse.sqlite", seal=folder / "reports" / "model_seal.json", models=folder / "models")
    results, fits, runs = [], [], []
    conn = connect(paths.db)
    try:
        previous = None
        for k, delivery in enumerate(plan, start=1):
            rows = canonical.rows[(canonical.rows["hour"] >= delivery.first_hour) & (canonical.rows["hour"] <= delivery.last_hour)]
            hours = canonical.hours[(canonical.hours["hour"] >= delivery.first_hour) & (canonical.hours["hour"] <= delivery.last_hour)]
            run = RunMeta(f"r{k}", delivery.delivery_id, delivery.kind, delivery.as_of, previous)
            load_delivery(conn, rows, hours, delivery, run.run_key, view, sha256="f" * 64)
            fits.append(fit_model(conn, run, sealed, models_dir=paths.models, seal_path=paths.seal))
            results.append(score_run(conn, run, load_registered_bundle(conn, paths.models, sealed.model.model_version), sealed))
            runs.append(run)
            previous = delivery.as_of
    finally:
        conn.close()
    return types.SimpleNamespace(paths=paths, view=view, sealed=sealed, runs=runs, fits=fits, results=results, plan=plan)


def copy_history(history, target: Path) -> types.SimpleNamespace:
    """A copy of a history's warehouse, seal and models in `target`, for a test that writes."""
    shutil.copytree(history.paths.db.parent, target)
    paths = types.SimpleNamespace(db=target / "warehouse.sqlite", seal=target / "reports" / "model_seal.json", models=target / "models")
    return types.SimpleNamespace(**{**vars(history), "paths": paths})


def stamp(value) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
