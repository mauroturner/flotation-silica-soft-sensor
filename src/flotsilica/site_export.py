"""The five small JSON files that the personal site copies (RF23, AC27; plan, section 21; D26, D43). Adapted from project 04's ``site_export.py``, without its
suppression of small cells: nothing here names a person (D43).

``export_site`` writes ``summary.json``, ``data.json``, ``algorithms.json``, ``operation.json`` and ``validation_rules.json`` to the site folder from the star model
(the ``star_*`` tables that ``export.build_powerbi_marts`` built, the very rows the Parquet files hold, so a figure on the site is the figure in the report), from the summary of
the run (``reporting.build_summary``, which takes the sealed criteria and the figures of the test from the seal when the warehouse has none), from the seal's test part and from
the validation of each run. Until the test is sealed with this configuration every result of the test is empty or ``null``.

The files are a contract that another repository consumes (item 3 of the risk list): a change of shape is a change of ``tests/contract/test_site_export.py``. Floats are
rounded to what the site shows; every file is ``json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1)`` with a final newline, and the five together stay under
``max_total_bytes`` (``[site]``).

The five files are one export: each is replaced atomically and ``manifest.json``, written last, names each with its size and SHA-256. The old manifest is removed before the first
file is replaced, so a failure between two replacements leaves a folder with no manifest, which ``verify_site`` refuses; a reader takes the files through ``read_site``.
A rule that counts something cumulative (``source`` and ``latest``) is read once, from the latest loaded run that recorded it, and never summed over the runs (project 03, D94).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from flotsilica import texts
from flotsilica.export import metadata
from flotsilica.files import write_atomic
from flotsilica.registry import read_registry, read_seal
from flotsilica.reporting import build_summary
from flotsilica.schema import LAB_COLUMNS, SENSORS
from flotsilica.scoring import RunMeta
from flotsilica.validate import RULES, Aggregation, Severity

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
SITE_FILES = ("summary.json", "data.json", "algorithms.json", "operation.json", "validation_rules.json")
MANIFEST_FILE = "manifest.json"
ENVELOPE = ("schema_version", "run_key", "as_of", "source_sha256", "attribution")
# Every table of the star model the export reads: the one list ``_require_star`` checks before anything is built (a test compares it with the tables the queries of this module name).
REQUIRED_STAR = ("star_dim_hour", "star_fact_estimate", "star_fact_hour_lab", "star_fact_leakage", "star_fact_pd_curve", "star_fact_selection", "star_fact_sensitivity")
BLOCKS = ("train", "valid_v1", "valid_v2", "test")        # the blocks a reader sees; the purges are not one
STATES = ("fresh", "held", "interpolated", "missing", "pending")
HORIZON_KEYS = {0: "h0", 1: "h1", 2: "h2"}
ACF_LAGS = 24                                              # the autocorrelation of the target, hour by hour up to a day
EXAMPLE_DAYS = ("median", "worst", "best")
STATUS_WORST_FIRST = ("fail", "warn", "pass")
LATENCY_ROW = "model_vs_b1_persistence"


class SiteExportError(RuntimeError):
    """The site files cannot be written from this warehouse; nothing was replaced."""


class SiteSetError(FileNotFoundError):
    """The files of a site folder are not one export: one is missing or is not the file ``manifest.json`` names, or the manifest is."""


@dataclass(frozen=True)
class SiteFiles:
    """The five documents of a verified site folder and its manifest, parsed from the bytes that were checked against it."""

    summary: dict[str, Any]
    data: dict[str, Any]
    algorithms: dict[str, Any]
    operation: dict[str, Any]
    validation_rules: dict[str, Any]
    manifest: dict[str, Any]


# --- values -------------------------------------------------------------------------------------------------------------------------


def _num(value: Any, decimals: int) -> float | None:
    if value is None or pd.isna(value) or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return round(float(value), decimals)


def _query(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params)


def _require_star(conn: sqlite3.Connection) -> None:
    present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    missing = [t for t in REQUIRED_STAR if t not in present]
    if missing:
        raise SiteExportError(f"faltan las tablas del modelo estrella {missing}: la tarea export las construye antes de escribir el sitio")


def _header(run: RunMeta, view: Any) -> dict[str, Any]:
    meta = metadata(run, view)
    return {"schema_version": SCHEMA_VERSION, "run_key": meta["flotsilica.run_key"], "as_of": meta["flotsilica.as_of"], "source_sha256": meta["flotsilica.source_sha256"],
            "attribution": meta["flotsilica.attribution"]}


def _models(conn: sqlite3.Connection, view: Any) -> dict[int, dict[str, Any]]:
    """The frozen model of each horizon, from the registry (what ``dim_model`` is made from)."""
    registered = read_registry(conn, view.model.model_version)
    if registered is None:
        raise SiteExportError("no hay un modelo registrado: el sitio se escribe después del lanzamiento")
    return {m["horizon"]: m for m in json.loads(registered["models_json"])}


def _sealed_test(summary: dict[str, Any]) -> dict[str, Any] | None:
    """The figures of the test, only when it is sealed: they come from the summary (the warehouse's sealed rows or, in a rebuild, the seal's)."""
    return summary.get("test") if summary["evaluation_status"] == "sealed" else None


def _test_method(test: dict[str, Any] | None, horizon: int, method: str) -> dict[str, Any]:
    if test is None:
        return {}
    return test.get("horizons", {}).get(str(horizon), {}).get("methods", {}).get(method) or {}


# --- the hours: counts, runs and the shape of the data ----------------------------------------------------------------------------------


def _hours(conn: sqlite3.Connection) -> pd.DataFrame:
    """Every hour of the calendar of the star model with its block, the state of its analysis at the run's instant, its analysis and the age of its feed."""
    return _query(conn, "SELECT h.hour, h.date, h.block, h.lab_state, h.is_partial, h.rows, l.silica_pct, l.feed_silica_age_h, l.feed_iron_age_h FROM star_dim_hour AS h "
                        "LEFT JOIN star_fact_hour_lab AS l ON l.hour_key = h.hour_key ORDER BY h.hour")


def _runs(mask: pd.Series) -> list[tuple[int, int]]:
    """The (first, last) positions of each stretch of consecutive true values of `mask`, which is on a calendar with every hour."""
    runs, start = [], None
    for i, value in enumerate(mask.to_numpy(dtype=bool)):
        if value and start is None:
            start = i
        elif not value and start is not None:
            runs.append((start, i - 1))
            start = None
    return runs + ([(start, len(mask) - 1)] if start is not None else [])


def _longest(runs: list[tuple[int, int]]) -> tuple[int, int] | None:
    return max(runs, key=lambda r: (r[1] - r[0], -r[0]), default=None)       # the first of the longest


def _counts(hours: pd.DataFrame) -> dict[str, Any]:
    """The figures of the data as the star model holds them: rows, hours with data, the hours of the grid that are missing and the period."""
    has_data = hours["rows"] > 0
    first, last = (hours.loc[has_data, "hour"].min(), hours.loc[has_data, "hour"].max()) if has_data.any() else (None, None)
    inside = has_data.copy()
    if first is not None:
        inside = (hours["hour"] >= first) & (hours["hour"] <= last)
    arrived = hours["lab_state"].isin(("fresh", "held", "interpolated"))
    return {"rows": int(hours["rows"].sum()), "hours": int(has_data.sum()), "missing_hours": int((inside & (hours["lab_state"] == "missing")).sum()),
            "partial_hours": int(hours["is_partial"].sum()), "period_start": first, "period_end": last, "arrived": int(arrived.sum()),
            "fresh": int((hours["lab_state"] == "fresh").sum()), "interpolated": int((hours["lab_state"] == "interpolated").sum()), "held": int((hours["lab_state"] == "held").sum())}


# --- summary.json -------------------------------------------------------------------------------------------------------------------


def _summary(conn: sqlite3.Connection, run: RunMeta, view: Any, summary: dict[str, Any], hours: pd.DataFrame) -> dict[str, Any]:
    test = _sealed_test(summary)
    models = _models(conn, view)
    counts = _counts(hours)
    in_test = hours["block"] == "test"
    passing = _query(conn, "SELECT COALESCE(SUM(passes), 0) AS n FROM star_fact_sensitivity")["n"].iloc[0]
    horizons = sorted(models)

    def mae(horizon: int, method: str) -> float | None:
        return _num(_test_method(test, horizon, method).get("mae"), 3)

    first_test, last_test = pd.Timestamp(view.split.test_first), pd.Timestamp(view.split.test_last)
    h0 = _test_method(test, 0, "model")
    headline = {
        "rows": counts["rows"], "hours": counts["hours"], "missing_hours": counts["missing_hours"], "partial_hours": counts["partial_hours"],
        "period_start": counts["period_start"], "period_end": counts["period_end"],
        "fresh_share": _num(counts["fresh"] / counts["arrived"], 3) if counts["arrived"] else None, "interpolated_hours": counts["interpolated"], "held_hours": counts["held"],
        "latency_hours": int(view.lab.latency_hours), "test_hours": int((last_test - first_test) / pd.Timedelta(hours=1)) + 1,
        "test_fresh_hours": int((in_test & (hours["lab_state"] == "fresh")).sum()),
        "mae": {HORIZON_KEYS[h]: {"model": mae(h, "model"), "persistence": mae(h, "b1_persistence"), "b_star": mae(h, "b_star")} for h in horizons},
        "b_star": {HORIZON_KEYS[h]: models[h]["b_star"] for h in horizons},
        "chosen": {HORIZON_KEYS[h]: {"family": models[h]["family"], "feature_set": models[h]["feature_set"], "target": models[h]["target"]} for h in horizons},
        "coverage_h0": _num(h0.get("coverage"), 3), "bias_h0": _num(h0.get("bias"), 3), "sensors_passing_gate": None if test is None else int(passing),
    }
    criteria = [{"id": c["criterion_id"], "name_es": c["name_es"], "passed": c["passed"], "value": _num(c["value"], 4), "baseline_value": _num(c["baseline_value"], 4),
                 "ci_low": _num(c["ci_low"], 4), "ci_high": _num(c["ci_high"], 4), "threshold_es": c["threshold_es"], "seen_by_research": c["seen_by_research"],
                 "seen_by_planner": c["seen_by_planner"], "verdict_es": c["verdict_es"]} for c in summary["criteria"]]
    status = conn.execute("SELECT status FROM pipeline_runs WHERE run_key = ?", (run.run_key,)).fetchone()
    if summary.get("seal") is None:
        raise SiteExportError("no hay sello: el lanzamiento lo escribe antes de que se exporte el sitio")
    out = {"status": "running" if status is None else status[0], "evaluation_status": summary["evaluation_status"], "headline": headline, "criteria": criteria, "seal": summary["seal"]}
    if summary.get("sealed_from"):
        out["sealed_from"] = summary["sealed_from"]
    return out


# --- validation_rules.json ----------------------------------------------------------------------------------------------------------


def _loaded_rule_rows(conn: sqlite3.Connection) -> pd.DataFrame:
    """The rule results of the runs whose delivery is loaded, with each run's instant."""
    return _query(conn, "SELECT v.rule_id, v.passed, v.severity, v.rows_affected, v.hours_affected, d.as_of FROM validation_results AS v "
                        "JOIN deliveries AS d ON d.run_key = v.run_key AND d.status = 'loaded' ORDER BY d.as_of, v.rule_id")


def _aggregated(rows: pd.DataFrame, rule_id: str) -> pd.DataFrame:
    """The rows of `rule_id` that its ``aggregation`` counts (plan, section 6): ``source`` and ``latest`` read once, from the latest loaded run that recorded the rule (a cumulative
    count summed over the runs would count the earlier hours again; project 03, D94), ``per_run`` every loaded run."""
    mine = rows[rows["rule_id"] == rule_id]
    if RULES[rule_id].aggregation in (Aggregation.SOURCE, Aggregation.LATEST) and len(mine):
        mine = mine[mine["as_of"] == mine["as_of"].max()]
    return mine


def _validation(conn: sqlite3.Connection, counts: dict[str, Any]) -> dict[str, Any]:
    rows = _loaded_rule_rows(conn)
    rules = []
    for rule_id, rule in RULES.items():
        mine = _aggregated(rows, rule_id)
        found = ["pass" if bool(p) else ("fail" if s == Severity.BLOCKING.value else "warn") for p, s in zip(mine["passed"], mine["severity"], strict=True)]
        status = "not_evaluated" if mine.empty else next(s for s in STATUS_WORST_FIRST if s in found)
        rules.append({"rule_id": rule_id, "name_es": rule.name_es, "severity": rule.severity.value, "scope": rule.scope, "aggregation": rule.aggregation.value, "status": status,
                      "rows": int(mine["rows_affected"].sum()), "hours": int(mine["hours_affected"].sum())})
    loaded, rejected = conn.execute("SELECT COALESCE(SUM(status = 'loaded'), 0), COALESCE(SUM(status = 'rejected'), 0) FROM deliveries").fetchone()
    totals = {"rows": counts["rows"], "hours": counts["hours"], "missing_hours": counts["missing_hours"], "deliveries_loaded": int(loaded), "deliveries_rejected": int(rejected)}
    return {"rules": rules, "totals": totals}


# --- data.json ----------------------------------------------------------------------------------------------------------------------


def _interpolated_run(hours: pd.DataFrame) -> dict[str, Any] | None:
    """The longest stretch of interpolated hours of the training block (the first of the longest) with the two analyses it lies between: a straight line (D05)."""
    found = _longest(_runs((hours["block"] == "train") & (hours["lab_state"] == "interpolated")))
    if found is None:
        return None
    first, last = found
    start = hours["silica_pct"].iloc[first - 1] if first > 0 else None
    end = hours["silica_pct"].iloc[last + 1] if last + 1 < len(hours) else None
    slope = _num((end - start) / (last - first + 2), 4) if _num(start, 2) is not None and _num(end, 2) is not None else None
    return {"hours": list(hours["hour"].iloc[first:last + 1]), "values": [_num(v, 2) for v in hours["silica_pct"].iloc[first:last + 1]], "start_value": _num(start, 2),
            "end_value": _num(end, 2), "slope_per_hour": slope}


def _held_runs(hours: pd.DataFrame) -> dict[str, int]:
    """The stretches of repeated hours of the blocks the model learns from (training, V1 and V2), the purges between them cutting a stretch."""
    runs = [last - first + 1 for first, last in _runs(hours["block"].isin(("train", "valid_v1", "valid_v2")) & (hours["lab_state"] == "held"))]
    long = [n for n in runs if n >= 3]
    return {"longest_hours": max(runs, default=0), "runs_3h_or_more": len(long), "hours_in_them": sum(long)}


def _gap(hours: pd.DataFrame, counts: dict[str, Any]) -> dict[str, Any] | None:
    """The longest stretch with no hour in the grid between the first hour with data and the last."""
    if counts["period_start"] is None:
        return None
    inside = (hours["hour"] >= counts["period_start"]) & (hours["hour"] <= counts["period_end"])
    found = _longest(_runs(inside & (hours["lab_state"] == "missing")))
    return None if found is None else {"first": hours["hour"].iloc[found[0]], "last": hours["hour"].iloc[found[1]], "hours": found[1] - found[0] + 1}


def _autocorrelation(hours: pd.DataFrame) -> list[dict[str, Any]]:
    """The correlation of the fresh analyses of training, V1 and V2 with those `lag` hours later, over the pairs where both are fresh."""
    x = hours["silica_pct"].where(hours["block"].isin(("train", "valid_v1", "valid_v2")) & (hours["lab_state"] == "fresh")).to_numpy(dtype="float64")
    out = []
    for lag in range(1, ACF_LAGS + 1):
        a, b = x[:-lag], x[lag:]
        both = np.isfinite(a) & np.isfinite(b)
        r = float(np.corrcoef(a[both], b[both])[0, 1]) if both.sum() >= 3 and a[both].std() > 0 and b[both].std() > 0 else None
        out.append({"lag": lag, "r": _num(r, 3)})
    return out


def _data(view: Any, hours: pd.DataFrame, counts: dict[str, Any]) -> dict[str, Any]:
    by_block = {block: Counter(hours.loc[hours["block"] == block, "lab_state"]) for block in BLOCKS}
    train = hours.loc[(hours["block"] == "train") & (hours["lab_state"] == "fresh"), "silica_pct"]
    has_data = hours[hours["rows"] > 0]
    unchanged = has_data[["feed_silica_age_h", "feed_iron_age_h"]].max(axis=1)         # a feed that is frozen: either of its two values has not changed (I02)
    split = {"train": (view.split.train_first, view.split.train_last), "valid_v1": (view.split.v1_first, view.split.v1_last),
             "valid_v2": (view.split.v2_first, view.split.v2_last), "test": (view.split.test_first, view.split.test_last)}
    stamp = "%Y-%m-%d %H:%M:%S"
    return {
        "sampling": {"rows_per_hour": int(view.hours.rows_per_hour), "sensors": len(SENSORS), "lab_columns": len(LAB_COLUMNS), "seconds_per_row": 3600 // int(view.hours.rows_per_hour)},
        "states_by_block": [{"block": b, "label_es": texts.BLOCKS_ES[b], **{state: int(by_block[b][state]) for state in STATES}} for b in BLOCKS],
        "interpolated_run": _interpolated_run(hours), "held_runs": _held_runs(hours), "gap": _gap(hours, counts),
        "feed": {"median_unchanged_hours": _num(unchanged.median(), 1), "max_unchanged_hours": _num(unchanged.max(), 0)},
        "target": {"mean": _num(train.mean(), 2), "sd": _num(train.std(), 2), "p05": _num(train.quantile(0.05), 2), "p50": _num(train.quantile(0.5), 2),
                   "p95": _num(train.quantile(0.95), 2), "acf": _autocorrelation(hours)},
        "split": [{"block": b, "label_es": texts.BLOCKS_ES[b], "first": pd.Timestamp(split[b][0]).strftime(stamp), "last": pd.Timestamp(split[b][1]).strftime(stamp),
                   "hours": int(sum(n for s, n in by_block[b].items() if s != "missing")), "fresh": int(by_block[b]["fresh"])} for b in BLOCKS],
    }


# --- algorithms.json ----------------------------------------------------------------------------------------------------------------


def _latency(view: Any, summary: dict[str, Any], seal: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The error of the model and of the persistence in H0 for each latency: the test's own (from the summary) and the variants (from the seal's test part)."""
    test = _sealed_test(summary)
    variants = {(v["variant"], v["method"], v["metric"]): v["value"] for v in ((seal or {}).get("test") or {}).get("variants", []) if v["horizon"] == 0} if test else {}
    out = []
    for latency in sorted({int(view.lab.latency_hours), *map(int, view.variants.latencies)}):
        if latency == view.lab.latency_hours:
            boot = (test or {}).get("bootstraps", {}).get(f"{LATENCY_ROW}.h0") or {}
            values = (_test_method(test, 0, "model").get("mae"), _test_method(test, 0, "b1_persistence").get("mae"), boot.get("ci_low"), boot.get("ci_high"))
        else:
            name = f"latency_{latency}"
            values = (variants.get((name, "model", "mae")), variants.get((name, "b1_persistence", "mae")), variants.get((name, LATENCY_ROW, "ci_low")),
                      variants.get((name, LATENCY_ROW, "ci_high")))
        out.append({"latency_hours": latency, **dict(zip(("mae_model", "mae_persistence", "ci_low", "ci_high"), (_num(v, 3) for v in values), strict=True))})
    return out


def _algorithms(conn: sqlite3.Connection, view: Any, summary: dict[str, Any], seal: dict[str, Any] | None) -> dict[str, Any]:
    test, models = _sealed_test(summary), _models(conn, view)
    validation = summary.get("validation") or {}

    def valid(scope: str, horizon: int, method: str) -> float | None:
        return _num((((validation.get(scope) or {}).get(str(horizon)) or {}).get(method) or {}).get("mae"), 3)

    horizons = []
    for h in sorted(models):
        found = [m for m in texts.METHOD_KINDS_ES if any(v is not None for v in (valid("valid_v1", h, m), valid("valid_v2", h, m), _test_method(test, h, m).get("mae")))]
        boot = (test or {}).get("bootstraps", {}).get(f"model_vs_b_star.h{h}") or {}
        horizons.append({
            "horizon": h, "label_es": texts.HORIZON_LABELS_ES[h], "chosen": {"family": models[h]["family"], "feature_set": models[h]["feature_set"], "target": models[h]["target"]},
            "b_star": models[h]["b_star"], "b2_k": int(models[h]["b2_k"]),
            "methods": [{"method": m, "label_es": texts.METHODS_ES[m], "mae_v1": valid("valid_v1", h, m), "mae_v2": valid("valid_v2", h, m), "mae_test": _num(_test_method(test, h, m).get("mae"), 3),
                         "ci_low_vs_b_star": _num(boot.get("ci_low"), 3) if m == "model" else None, "ci_high_vs_b_star": _num(boot.get("ci_high"), 3) if m == "model" else None}
                        for m in found]})
    selection = [{"horizon": int(r.horizon_key), "family": r.family, "feature_set": r.feature_set, "target": r.target, "min_samples_leaf": int(r.min_samples_leaf),
                  "mae_v1": _num(r.mae_v1, 4), "chosen": bool(r.chosen)} for r in _query(conn, "SELECT * FROM star_fact_selection").itertuples()]
    leaks = _query(conn, "SELECT \"check\", mae, r2 FROM star_fact_leakage").set_index("check")

    def leak(check: str, column: str) -> float | None:
        return _num(leaks[column].get(check), 3) if check in leaks.index else None

    sensitivity = _query(conn, "SELECT * FROM star_fact_sensitivity").set_index("sensor_key")
    kept = test is not None
    sensors = [{"sensor": s, "name_es": texts.SENSORS_ES[s], "importance_v1": _num(sensitivity.at[s, "importance_v1"], 4), "importance_v2": _num(sensitivity.at[s, "importance_v2"], 4),
                "sign_stable": bool(sensitivity.at[s, "sign_stable"]), "passes": bool(sensitivity.at[s, "passes"]),
                "test_sign_kept": bool(sensitivity.at[s, "test_sign_kept"]) if kept and pd.notna(sensitivity.at[s, "test_sign_kept"]) else None, "label_es": sensitivity.at[s, "label_es"]}
               for s in SENSORS if s in sensitivity.index]
    curves = _query(conn, "SELECT sensor_key, grid_value, mean_estimate FROM star_fact_pd_curve ORDER BY sensor_key, point")
    pd_curves = [{"sensor": s, "grid": [_num(v, 3) for v in part["grid_value"]], "estimate": [_num(v, 3) for v in part["mean_estimate"]]}
                 for s in SENSORS for part in [curves[curves["sensor_key"] == s]] if len(part)]
    return {
        "horizons": horizons, "selection": selection, "latency": _latency(view, summary, seal),
        "leakage": {"random_split_r2": leak("random_split", "r2"), "block_r2": leak("blocks", "r2"), "random_split_mae": leak("random_split", "mae"), "block_mae": leak("blocks", "mae"),
                    "iron_control_mae_v2": leak("iron_conc", "mae"), "sealed_mae_v2": valid("valid_v2", 0, "model")},
        "gate": {"min_importance_mae": _num(view.sensitivity.min_importance_mae, 4), "min_abs_spearman": _num(view.sensitivity.min_abs_spearman, 2)},
        "sensitivity": sensors, "pd_curves": pd_curves,
        "interval": {"coverage_target": _num(view.intervals.coverage, 2), "half_width": {HORIZON_KEYS[h]: _num(models[h]["half_width"], 3) for h in sorted(models)},
                     "coverage_test": _num(_test_method(test, 0, "model").get("coverage"), 3)},
    }


# --- operation.json -----------------------------------------------------------------------------------------------------------------


def _example_days(daily: list[dict[str, Any]]) -> dict[str, Any]:
    """The fixed rule: the day with the lower median of the H0 error of the model, the worst and the best (the earlier date breaks a tie)."""
    ranked = sorted((d for d in daily if d["mae_model"] is not None), key=lambda d: (d["mae_model"], d["date"]))
    if not ranked:
        return dict.fromkeys(EXAMPLE_DAYS)
    return {"median": {"date": ranked[(len(ranked) - 1) // 2]["date"]}, "worst": {"date": ranked[-1]["date"]}, "best": {"date": ranked[0]["date"]}}


def _operation(conn: sqlite3.Connection, view: Any, summary: dict[str, Any], seal: dict[str, Any] | None) -> dict[str, Any]:
    columns = ("hour", "estimate", "low", "high", "persistence", "actual", "state")
    test_hours: dict[str, list] = {c: [] for c in columns}
    daily, weekly = [], []
    if _sealed_test(summary) is not None:
        frame = _query(conn, "SELECT h.hour, h.date, e.estimate, e.low, e.high, e.persistence, e.actual, e.abs_error, e.abs_error_persistence, h.lab_state AS state "
                             "FROM star_fact_estimate AS e JOIN star_dim_hour AS h ON h.hour_key = e.hour_key "
                             "WHERE e.horizon_key = 0 AND e.status = 'ok' AND h.block = 'test' ORDER BY h.hour")
        for column in columns:
            test_hours[column] = [(v if column in ("hour", "state") else _num(v, 2)) for v in frame[column]]
        for date, part in frame.groupby("date", sort=True):
            fresh = part["actual"].notna()
            daily.append({"date": date, "mae_model": _num(part.loc[fresh, "abs_error"].mean(), 3) if fresh.any() else None,
                          "mae_persistence": _num(part.loc[fresh, "abs_error_persistence"].mean(), 3) if fresh.any() else None, "fresh_hours": int(fresh.sum())})
        first = pd.Timestamp(view.split.test_first).normalize()
        found = {(w["week"], w["horizon"], w["method"]): w["mae"] for w in ((seal or {}).get("test") or {}).get("weekly", [])}
        for week, horizon in sorted({(w, h) for w, h, _m in found}, key=lambda k: (k[0], k[1])):
            weekly.append({"week": int((pd.Timestamp(week) - first).days // 7) + 1, "horizon": horizon, "mae_model": _num(found.get((week, horizon, "model")), 3),
                           "mae_persistence": _num(found.get((week, horizon, "b1_persistence")), 3), "mae_b_star": _num(found.get((week, horizon, "b_star")), 3)})
    return {"test_hours": test_hours, "daily": daily, "weekly": weekly, "example_days": _example_days(daily),
            "api": {"endpoint": texts.API_ENDPOINT, "inputs_es": texts.API_INPUTS_ES, "outputs_es": texts.API_OUTPUTS_ES}}


# --- reading ------------------------------------------------------------------------------------------------------------------------


def _text(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False) + "\n"


def _read_checked(out_dir: Path) -> tuple[dict[str, bytes], dict[str, Any], list[str]]:
    out_dir = Path(out_dir)
    try:
        manifest = json.loads((out_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
        files = manifest["files"]
        if not isinstance(files, dict) or not all(isinstance(e, dict) for e in files.values()):
            raise TypeError(MANIFEST_FILE)
    except FileNotFoundError:
        return {}, {}, [f"falta {MANIFEST_FILE} en {out_dir}: el conjunto no es una exportación completa"]
    except (ValueError, KeyError, TypeError):
        return {}, {}, [f"{MANIFEST_FILE} de {out_dir} no se puede leer"]
    problems = [] if sorted(files) == sorted(SITE_FILES) else [f"{MANIFEST_FILE} nombra {sorted(files)} y no los cinco archivos del sitio"]
    out: dict[str, bytes] = {}
    for name in SITE_FILES:
        path = out_dir / name
        if not path.is_file():
            problems.append(f"falta {name} en {out_dir}")
            continue
        data = path.read_bytes()
        entry = files.get(name, {})
        if len(data) != entry.get("bytes") or hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            problems.append(f"{name} no es el que nombra {MANIFEST_FILE} (otro tamaño o SHA-256): los archivos no son de una misma exportación")
            continue
        try:
            document = json.loads(data.decode("utf-8"))
        except ValueError:
            problems.append(f"{name} no es un JSON legible")
            continue
        if any(document.get(key) != manifest.get(key) for key in ENVELOPE):
            problems.append(f"{name} no lleva el envoltorio de {MANIFEST_FILE} (la corrida, el instante o la fuente son otros)")
        out[name] = data
    return out, manifest, problems


def read_site(out_dir: Path) -> SiteFiles:
    """The five documents of `out_dir`, each read once and checked against ``manifest.json``; ``SiteSetError`` if they are not one export."""
    data, manifest, problems = _read_checked(out_dir)
    if problems:
        raise SiteSetError("; ".join(problems))
    documents = {name.removesuffix(".json"): json.loads(data[name].decode("utf-8")) for name in SITE_FILES}
    return SiteFiles(**documents, manifest=manifest)


def verify_site(out_dir: Path) -> list[str]:
    """What keeps the files of `out_dir` from being one export (``[]`` when the manifest names the five with their size and SHA-256 and each carries its envelope)."""
    return _read_checked(out_dir)[2]


# --- writing ------------------------------------------------------------------------------------------------------------------------


def _write(texts_by_name: dict[str, str], out_dir: Path, cap: int, header: dict[str, Any]) -> list[Path]:
    out_dir = Path(out_dir)
    payloads = {name: texts_by_name[name].encode("utf-8") if name in texts_by_name else (out_dir / name).read_bytes() for name in SITE_FILES}
    total = sum(len(p) for p in payloads.values())
    if total > cap:
        raise SiteExportError(f"los archivos del sitio pesan {total} bytes y el tope es {cap}: no se escribió ninguno")
    manifest = _text({**header, "files": {n: {"bytes": len(p), "sha256": hashlib.sha256(p).hexdigest()} for n, p in payloads.items()}})
    (out_dir / MANIFEST_FILE).unlink(missing_ok=True)         # a set being rewritten has no manifest until its last file is written
    paths = [write_atomic(out_dir / name, texts_by_name[name]) for name in SITE_FILES if name in texts_by_name]
    write_atomic(out_dir / MANIFEST_FILE, manifest)
    logger.info("site export %s: %d files, %d bytes", header["run_key"], len(paths), total)
    return paths


def _documents(conn: sqlite3.Connection, run: RunMeta, view: Any, seal_path: Path) -> dict[str, dict[str, Any]]:
    _require_star(conn)
    summary = build_summary(conn, view, run=run, seal_path=seal_path)
    seal = read_seal(seal_path)
    hours = _hours(conn)
    counts = _counts(hours)
    return {"summary.json": _summary(conn, run, view, summary, hours), "data.json": _data(view, hours, counts), "algorithms.json": _algorithms(conn, view, summary, seal),
            "operation.json": _operation(conn, view, summary, seal), "validation_rules.json": _validation(conn, counts)}


def export_site(conn: sqlite3.Connection, out_dir: Path, run: RunMeta, view: Any, *, seal_path: Path, max_total_bytes: int) -> list[Path]:
    """Write the five site files from the star model of `conn`, then ``manifest.json``; returns the five paths (``SITE_FILES`` order). Every document is built before the first
    file is replaced, and nothing is written if together they would pass `max_total_bytes` (``[site]``). `view` is the sealed view, as for ``export_star_schema``."""
    header = _header(run, view)
    documents = _documents(conn, run, view, seal_path)
    return _write({name: _text({**header, **documents[name]}) for name in SITE_FILES}, out_dir, max_total_bytes, header)


def export_summary(conn: sqlite3.Connection, out_dir: Path, run: RunMeta, view: Any, *, seal_path: Path, max_total_bytes: int) -> Path:
    """Rewrite only ``summary.json`` (what closing a run changes) and the manifest with it. The other four must be one export of this same run: over a folder that is not
    one, or is of another run, nothing is written (``SiteExportError``)."""
    _require_star(conn)
    header = _header(run, view)
    problems = verify_site(out_dir)
    if not problems and json.loads((Path(out_dir) / MANIFEST_FILE).read_text(encoding="utf-8"))["run_key"] != header["run_key"]:
        problems = ["el conjunto es de otra corrida"]
    if problems:
        raise SiteExportError(f"no se reescribe el resumen: {'; '.join(problems)}; la tarea export escribe los cinco archivos de nuevo")
    summary = build_summary(conn, view, run=run, seal_path=seal_path)
    document = _summary(conn, run, view, summary, _hours(conn))
    [path] = _write({"summary.json": _text({**header, **document})}, out_dir, max_total_bytes, header)
    return path


__all__ = ["MANIFEST_FILE", "SITE_FILES", "SiteExportError", "SiteFiles", "SiteSetError", "export_site", "export_summary", "read_site", "verify_site"]
