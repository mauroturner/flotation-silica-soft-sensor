"""The variants of the evaluation (RF18, D06, D11; C10; plan, section 16): what the test says if one assumption is changed, informed and never used to choose.

``run`` is called only inside the evaluation of the test and only after the launch part of the seal is written (``SealError`` otherwise): the variants read the test, so
nothing that chooses (``model.select``, ``model.refit``, ``baselines.strongest``, ``intervals``) may read their table or import this module (a static test reads those files).

* ``latency_3`` and ``latency_4``: the configured candidate of H0 refit with the training block and V1 with the features of that latency, and the persistence of that
  latency, over the hours of the test that have every input at it, with the interval of the difference of MAE;
* ``refit_all``: the three configured candidates refit with the training block, V1 and V2, against the persistence, over the same hours as the criteria;
* ``all_hours``: what was issued for H0 and the persistence over **every** hour of the test with an analysis, fresh, held or interpolated.

Each result is a dict ``variant``, ``horizon``, ``method``, ``metric`` and ``value``, which the seal stores in its test part and ``eval_variants`` holds.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from flotsilica.baselines import eligible
from flotsilica.evaluation import day_bootstrap
from flotsilica.features import HourTables, design
from flotsilica.launch import hour_frame
from flotsilica.model import LAUNCH_BLOCKS, build_blocks, fit_candidate, refit_blocks, stack
from flotsilica.registry import ModelBundle, SealError, read_seal
from flotsilica.split import block_of

PERSISTENCE = "b1_persistence"


def _row(variant: str, horizon: int, method: str, metric: str, value: float) -> dict[str, Any]:
    return {"variant": variant, "horizon": horizon, "method": method, "metric": metric, "value": float(value)}


def _comparison(variant: str, horizon: int, hours: pd.DatetimeIndex, y: np.ndarray, model: np.ndarray, persistence: np.ndarray, view: Any) -> list[dict[str, Any]]:
    """MAE and hours of the model and of the persistence, and the interval of the difference of MAE over whole days."""
    boot = day_bootstrap(model - y, persistence - y, hours.normalize().to_numpy(), view.evaluation.bootstrap_resamples, view.evaluation.bootstrap_seed)
    out = []
    for method, estimate in (("model", model), (PERSISTENCE, persistence)):
        out += [_row(variant, horizon, method, "mae", np.mean(np.abs(estimate - y))), _row(variant, horizon, method, "hours", len(y))]
    out += [_row(variant, horizon, f"model_vs_{PERSISTENCE}", "difference", boot.difference), _row(variant, horizon, f"model_vs_{PERSISTENCE}", "ci_low", boot.ci_low),
            _row(variant, horizon, f"model_vs_{PERSISTENCE}", "ci_high", boot.ci_high)]
    return out


def _test_cohort(tables: HourTables, view: Any, horizon: int) -> tuple[pd.DatetimeIndex, pd.DataFrame, np.ndarray]:
    """The hours of the test with a fresh analysis and every input at `horizon`, their features and their analyses."""
    inside = tables.hours[(block_of(tables.hours, view) == "test").to_numpy()]
    hours = inside[eligible(tables, inside, horizon, view).to_numpy()]
    y, _fresh = tables.analysis_of(hours)
    return hours, design(tables, hours, horizon, view), y


def _latency(frame: pd.DataFrame, bundle: ModelBundle, view: Any, latency: int) -> list[dict[str, Any]]:
    variant = f"latency_{latency}"
    view_l = dataclasses.replace(view, lab=dataclasses.replace(view.lab, latency_hours=latency))
    tables = HourTables.from_hours(frame.drop(columns=["available_at"]), view_l)          # the arrival is the hour plus the latency of the variant
    candidate = bundle.horizons[0].candidate
    model = refit_blocks(candidate, build_blocks(tables, view_l, (0,))[0], view_l)
    hours, x, y = _test_cohort(tables, view_l, 0)
    if not len(hours):
        return []
    last1 = x["lab_last1"].to_numpy(dtype="float64")
    return _comparison(variant, 0, hours, y, model.predict(x, last1), last1, view_l)


def _refit_all(frame: pd.DataFrame, bundle: ModelBundle, view: Any) -> list[dict[str, Any]]:
    tables = HourTables.from_hours(frame, view)
    blocks = build_blocks(tables, view, [m.horizon for m in bundle.horizons])
    out = []
    for hm in bundle.horizons:
        x_fit, y_fit, last_fit = stack(blocks[hm.horizon], LAUNCH_BLOCKS)
        fitted = fit_candidate(hm.candidate, x_fit, y_fit, last_fit, view, fitted_on=LAUNCH_BLOCKS)
        hours, x, y = _test_cohort(tables, view, hm.horizon)
        if len(hours):
            last1 = x["lab_last1"].to_numpy(dtype="float64")
            out += _comparison("refit_all", hm.horizon, hours, y, fitted.predict(x, last1), last1, view)
    return out


def _all_hours(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT e.estimate, e.persistence, l.silica_pct FROM estimates e JOIN lab_hours l ON l.hour = e.target_hour "
        "WHERE e.horizon = 0 AND e.block = 'test' AND e.status = 'ok' AND e.is_censored = 0").fetchall()
    if not rows:
        return []
    estimate, persistence, actual = (np.array(column, dtype="float64") for column in zip(*rows, strict=True))
    out = []
    for method, values in (("model", estimate), (PERSISTENCE, persistence)):
        out += [_row("all_hours", 0, method, "mae", np.mean(np.abs(values - actual))), _row("all_hours", 0, method, "hours", len(actual))]
    return out


def run(conn: sqlite3.Connection, bundle: ModelBundle, view: Any, *, as_of: datetime, seal_path: Path) -> list[dict[str, Any]]:
    """The variants of ``[variants]`` for the test (see the module). Only after the launch part of the seal is written."""
    if read_seal(Path(seal_path)) is None:
        raise SealError("las variantes se calculan después de la parte del lanzamiento del sello, que no está escrita (docs/runbook.md, R7)")
    frame = hour_frame(conn, as_of, view)
    out: list[dict[str, Any]] = []
    for latency in view.variants.latencies:
        out += _latency(frame, bundle, view, latency)
    if view.variants.refit_all:
        out += _refit_all(frame, bundle, view)
    return out + _all_hours(conn)
