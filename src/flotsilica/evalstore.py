"""The tables of the evaluation: what the launch stores (the selection, the baselines, the figures of V1 and V2 and the leak demonstration) and what the evaluation
of the test stores (D16, D18, D19; plan, sections 5 and 16).

Every group of rows carries the state of the seal it was made under. A group of ``sealed`` rows is written **once** (``store_group`` leaves it alone if it is there, and
the triggers of ``003_model.sql`` refuse to change it anyway); a group of ``post_seal`` rows is replaced when the run that made it repeats. Nothing here decides
what is sealed: the caller knows (``registry.seal_state`` and ``check_test_evaluation``).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from flotsilica.baselines import B2, lab_baselines
from flotsilica.evaluation import METRIC_NAMES, EvaluationResult, Criterion, metrics as compute_metrics
from flotsilica.features import HourTables
from flotsilica.intervals import interval
from flotsilica.leakage_demo import leakage_table
from flotsilica.model import LaunchFit
from flotsilica.schema import AGGREGATE_COLUMNS

STATES = ("sealed", "post_seal")


def _db(value: Any) -> Any:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (bool, np.bool_)):
        return int(value)
    return float(value) if isinstance(value, (float, np.floating)) else int(value)


def store_group(conn: sqlite3.Connection, table: str, columns: Sequence[str], rows: Sequence[Sequence[Any]], state: str, run_key: str, *,
                where: str = "1 = 1", args: tuple = ()) -> bool:
    """Write `rows` (values of `columns`) into `table` with `state` and `run_key`, as one group of the table (`where` and `args` say which rows are the group, for a table
    that holds several, like the scopes of ``eval_metrics``). A ``sealed`` group that is already there is left as it is (False); a ``post_seal`` one is replaced; in
    both cases in one transaction that is the caller's if it has one open. Returns whether the rows were written."""
    if state not in STATES:
        raise ValueError(f"seal_state: se esperaba uno de {STATES}, se recibió {state!r}")
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        exists = conn.execute(f"SELECT 1 FROM {table} WHERE seal_state = ? AND ({where}) LIMIT 1", (state, *args)).fetchone() is not None
        if state == "sealed" and exists:
            written = False
        else:
            conn.execute(f"DELETE FROM {table} WHERE seal_state = ? AND ({where})", (state, *args))
            if rows:
                every = (*columns, "seal_state", "run_key")
                conn.executemany(f"INSERT INTO {table} ({', '.join(every)}) VALUES ({', '.join('?' * len(every))})",
                                 [(*[_db(v) for v in row], state, run_key) for row in rows])
            written = True
        if own:
            conn.execute("COMMIT")
    except BaseException:
        if own and conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return written


# --- the launch -------------------------------------------------------------------------------------------------------------------


def validation_figures(tables: HourTables, launch: LaunchFit, view: Any) -> list[tuple]:
    """``(scope, horizon, method, metric, value)`` of every method on V1 and V2 for every horizon, from the launch's blocks. The model and the comparison models are
    the refit ones (they saw V1, so V1 is a fit figure and V2 the one a decision can read); the baselines are the ones of the launch. Labelled as validation wherever shown."""
    out = []
    for horizon, fit in launch.horizons.items():
        base = launch.baselines
        for scope in ("valid_v1", "valid_v2"):
            block = launch.blocks[horizon][scope]
            lab = lab_baselines(tables, block.hours, horizon, view)
            estimate = {
                "model": fit.model.predict(block.X, block.last1), "b0_train_mean": np.full(len(block.y), base.b0_mean), "b1_persistence": block.last1,
                B2: lab[f"b2_k{base.b2_k[horizon]}"].to_numpy(dtype="float64"), "b3_ridge_sensors": base.b3[horizon].predict(block.X[list(AGGREGATE_COLUMNS)]),
                **{name: model.predict(block.X, block.last1) for name, model in fit.comparisons.items()},
            }
            estimate["b_star"] = estimate["b1_persistence"] if base.b_star[horizon] == "b1_persistence" else estimate[B2]
            low_high = [interval(float(e), fit.calibration.half_width) for e in estimate["model"]]
            low, high = np.array([lh[0] for lh in low_high]), np.array([lh[1] for lh in low_high])
            for method, values in estimate.items():
                m = compute_metrics(block.y, values, *((low, high) if method == "model" else ()))
                out += [(scope, horizon, method, metric, getattr(m, metric)) for metric in METRIC_NAMES if getattr(m, metric) is not None]
    return out


def store_launch(conn: sqlite3.Connection, tables: HourTables, launch: LaunchFit, iron: pd.Series, view: Any, state: str, run_key: str) -> dict[str, bool]:
    """Store the tables of the launch with `state`: the 28 errors of V1 of each horizon (D14), the baselines, the figures of V1 and V2 and the leak demonstration."""
    selection, baselines = [], []
    for horizon, fit in launch.horizons.items():
        selection += [(horizon, r.candidate.name, r.candidate.family, r.candidate.feature_set, r.candidate.target, r.candidate.min_samples_leaf, r.mae_v1,
                       r.candidate == fit.chosen) for r in fit.results]
        b = launch.baselines
        baselines += [(horizon, "b0_train_mean", None, b.mae_v1[horizon]["b0_train_mean"], b.cohort_v1[horizon]),
                      (horizon, "b1_persistence", None, b.mae_v1[horizon]["b1_persistence"], b.cohort_v1[horizon]),
                      (horizon, "b2_rolling", b.b2_k[horizon], b.mae_v1[horizon]["b2_rolling"], b.cohort_v1[horizon]),
                      (horizon, "b3_ridge_sensors", None, b.mae_v1[horizon]["b3_ridge_sensors"], b.cohort_v1[horizon])]
    zero = launch.horizons.get(0)
    leak = (leakage_table(launch.blocks[0], iron, zero.chosen, view) if zero is not None else pd.DataFrame())
    figures = validation_figures(tables, launch, view)
    conn.execute("BEGIN IMMEDIATE")
    try:
        written = {
            "selection": store_group(conn, "eval_selection", ("horizon", "candidate", "family", "feature_set", "target", "min_samples_leaf", "mae_v1", "chosen"),
                                     selection, state, run_key),
            "baselines": store_group(conn, "eval_baselines", ("horizon", "method", "k", "mae_v1", "cohort_v1"), baselines, state, run_key),
            "validation": store_group(conn, "eval_metrics", ("scope", "horizon", "method", "metric", "value"), figures, state, run_key,
                                      where="scope IN ('valid_v1', 'valid_v2')"),
            "leakage": store_group(conn, "eval_leakage", ("check_id", "description_es", "mae", "r2", "rows", "note_es"),
                                   [tuple(r) for r in leak[["check_id", "description_es", "mae", "r2", "rows", "note_es"]].itertuples(index=False)] if len(leak) else [],
                                   state, run_key),
        }
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return written


# --- the test ---------------------------------------------------------------------------------------------------------------------


def store_result(conn: sqlite3.Connection, result: EvaluationResult, criteria: Sequence[Criterion], variants: Sequence[Mapping[str, Any]], state: str, run_key: str) -> bool:
    """Store the evaluation of the test with `state`: its figures, the intervals, the weeks, the criteria and the variants. All or nothing; a sealed group already
    there is left alone, so the criteria of the one evaluation are written once. Returns whether the criteria were written."""
    metric_rows = [("test", h, method, metric, getattr(m, metric)) for h, per in result.metrics.items() for method, m in per.items()
                   for metric in METRIC_NAMES if getattr(m, metric) is not None]
    boot_rows = [(key, int(key.rsplit(".h", 1)[1]), b.difference, b.ci_low, b.ci_high, b.resamples) for key, b in result.bootstraps.items()]
    weekly_rows = [(w["week"], w["horizon"], w["method"], w["mae"], w["hours"]) for w in result.weekly]
    criteria_rows = [(c.criterion_id, c.name_es, c.value, c.baseline_value, c.ci_low, c.ci_high, c.threshold_es, c.passed, c.seen_by_research, c.seen_by_planner,
                      c.verdict_es) for c in criteria]
    variant_rows = [(v["variant"], v["horizon"], v["method"], v["metric"], v["value"]) for v in variants]
    conn.execute("BEGIN IMMEDIATE")
    try:
        written = store_group(conn, "eval_criteria", ("criterion_id", "name_es", "value", "baseline_value", "ci_low", "ci_high", "threshold_es", "passed",
                                                       "seen_by_research", "seen_by_planner", "verdict_es"), criteria_rows, state, run_key)
        store_group(conn, "eval_metrics", ("scope", "horizon", "method", "metric", "value"), metric_rows, state, run_key, where="scope = 'test'")
        store_group(conn, "eval_bootstrap", ("comparison", "horizon", "difference", "ci_low", "ci_high", "resamples"), boot_rows, state, run_key)
        store_group(conn, "eval_weekly", ("week", "horizon", "method", "mae", "hours"), weekly_rows, state, run_key)
        store_group(conn, "eval_variants", ("variant", "horizon", "method", "metric", "value"), variant_rows, state, run_key)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return written
