"""Metrics and intervals of the evaluation (D17, RF18; plan, section 16): the numbers of a set of hours and the interval of a difference of errors.

``metrics`` gives the mean absolute error, the root mean square error, the bias (estimate minus analysis) and, with a range, its coverage.
``day_bootstrap`` resamples **whole days** (the hours of a day are not independent: the autocorrelation at one hour is 0.76) with replacement, the
same days for both methods, and takes the 2.5 and 97.5 percentiles of the difference of the two MAE, each over the hours of the resample: a quotient
of sums, not a mean of daily means. The draws are ``numpy.random.default_rng(seed).integers(0, days, size=(n, days))``.

The evaluation of the test (U11) reads what was **issued** (``estimates`` and ``method_estimates``), never a new prediction: for each horizon the fresh hours of the
test block with every input, the metrics of each method, the interval of the differences the criteria ask for (whole days, the same days for both methods),
the error by week of the test and the criteria C01 to C10 with their verdicts (``texts.py``). ``figures`` is what the seal stores in its ``metrics``, and
``criteria_of`` rebuilds the criteria from those figures alone, so that a sealed result can be published again without the warehouse that made it (D19).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from flotsilica import texts
from flotsilica.baselines import eligible
from flotsilica.features import HourTables, design
from flotsilica.split import block_of
from flotsilica.texts import CRITERIA, es

PERCENTILES = (2.5, 97.5)
METRIC_NAMES = ("hours", "mae", "rmse", "bias", "coverage")


@dataclass(frozen=True)
class Metrics:
    hours: int
    mae: float
    rmse: float
    bias: float
    coverage: float | None          # the share of hours with low <= actual <= high; None without a range


@dataclass(frozen=True)
class Bootstrap:
    difference: float               # MAE(a) - MAE(b) over all the hours
    ci_low: float
    ci_high: float
    resamples: int
    differences: np.ndarray         # the difference of each resample


def _numbers(values: np.ndarray, what: str) -> np.ndarray:
    array = np.asarray(values, dtype="float64")
    if not np.isfinite(array).all():
        raise ValueError(f"{what}: se esperaban valores finitos")
    return array


def metrics(actual: np.ndarray, estimate: np.ndarray, low: np.ndarray | None = None, high: np.ndarray | None = None) -> Metrics:
    """The metrics of `estimate` against `actual` over the hours given, in points of silica; the coverage needs both ends of the range."""
    actual, estimate = _numbers(actual, "análisis"), _numbers(estimate, "estimaciones")
    if len(actual) != len(estimate):
        raise ValueError("el análisis y la estimación deben tener la misma cantidad de horas")
    if not len(actual):
        raise ValueError("sin horas que evaluar")
    if (low is None) != (high is None):
        raise ValueError("el rango necesita sus dos extremos, el bajo y el alto")
    error = estimate - actual
    coverage = None
    if low is not None:
        low, high = _numbers(low, "extremo bajo"), _numbers(high, "extremo alto")
        if len(low) != len(actual) or len(high) != len(actual):
            raise ValueError("el rango debe tener la misma cantidad de horas que el análisis")
        coverage = float(np.mean((low <= actual) & (actual <= high)))
    return Metrics(len(actual), float(np.mean(np.abs(error))), float(np.sqrt(np.mean(error ** 2))), float(np.mean(error)), coverage)


def day_bootstrap(err_a: np.ndarray, err_b: np.ndarray, days: np.ndarray, n: int = 2000, seed: int = 0) -> Bootstrap:
    """The interval of 95 % of MAE(a) - MAE(b) by resampling the days of `days` (one label per hour) `n` times with the generator of `seed`.

    `err_a` and `err_b` are the errors of the two methods on the same hours, with or without sign (only their size counts)."""
    if not isinstance(n, (int, np.integer)) or isinstance(n, bool) or n < 1:
        raise ValueError(f"remuestras: se esperaba un entero de 1 o más, se recibió {n!r}")
    abs_a, abs_b = np.abs(np.asarray(err_a, dtype="float64")), np.abs(np.asarray(err_b, dtype="float64"))
    labels = np.asarray(days)
    if not (len(abs_a) == len(abs_b) == len(labels)):
        raise ValueError("los errores de los dos métodos y los días deben tener la misma cantidad de horas")
    if not len(abs_a):
        raise ValueError("sin horas que remuestrear")
    if not (np.isfinite(abs_a).all() and np.isfinite(abs_b).all()):
        raise ValueError("los errores deben ser finitos")
    unique, codes = np.unique(labels, return_inverse=True)
    sum_a, sum_b = np.bincount(codes, weights=abs_a), np.bincount(codes, weights=abs_b)
    hours = np.bincount(codes).astype("float64")
    picks = np.random.default_rng(seed).integers(0, len(unique), size=(int(n), len(unique)))
    differences = (sum_a[picks].sum(axis=1) - sum_b[picks].sum(axis=1)) / hours[picks].sum(axis=1)
    low, high = np.percentile(differences, PERCENTILES)
    return Bootstrap(float(abs_a.mean() - abs_b.mean()), float(low), float(high), int(n), differences)




# --- the evaluation of the test: frames, metrics, intervals and weeks (U11) -------------------------------------------------------------------------------

B_STAR = "b_star"
METHODS = ("model", B_STAR, "b0_train_mean", "b1_persistence", "b2_rolling", "b3_ridge_sensors", "best_sensors_only", "best_lab_only", "best_with_sensors")
WEEKLY_METHODS = ("model", "b1_persistence", B_STAR)           # C10: the error of M_H, of B1_H and of B*_H by week of the test
FRAME_COLUMNS = ("actual", "low", "high", *METHODS)
# the differences the criteria ask for: (name, method a, method b, horizons); the interval is of MAE(a) - MAE(b), over the same days for both (D17)
COMPARISONS = (
    ("model_vs_b_star", "model", B_STAR, (0, 1, 2)),
    ("model_vs_b1_persistence", "model", "b1_persistence", (0, 1, 2)),
    ("best_sensors_only_vs_b0_train_mean", "best_sensors_only", "b0_train_mean", (0,)),
    ("best_with_sensors_vs_best_lab_only", "best_with_sensors", "best_lab_only", (0,)),
)
WEEK = timedelta(days=7)


def _comparison_key(name: str, horizon: int) -> str:
    return f"{name}.h{horizon}"


@dataclass(frozen=True, eq=False)
class EvaluationResult:
    """The test as it was issued: ``metrics`` (horizon, then method, to ``Metrics``), ``bootstraps`` (``<comparison>.h<horizon>`` to ``Bootstrap``), ``weekly``
    (one dict per week, horizon and method of ``WEEKLY_METHODS``) and the hours of each horizon."""

    hours: dict[int, int]
    metrics: dict[int, dict[str, Metrics]]
    bootstraps: dict[str, Bootstrap]
    weekly: list[dict[str, Any]]


def issued_frames(conn: sqlite3.Connection, view: Any) -> dict[int, pd.DataFrame]:
    """The hours of the test that have an analysis that is fresh and every input, by horizon (``view.evaluation.horizons``): what was issued for them
    (``estimates``, B* and the range, and ``method_estimates``) next to the analysis. A censored hour has no analysis and is not here."""
    frames = {}
    for horizon in view.evaluation.horizons:
        base = pd.read_sql_query(
            "SELECT e.target_hour, l.silica_pct AS actual, e.low, e.high, e.estimate AS model, e.b_star "
            "FROM estimates e JOIN lab_hours l ON l.hour = e.target_hour "
            "WHERE e.horizon = ? AND e.block = 'test' AND e.status = 'ok' AND e.is_censored = 0 AND l.lab_state = 'fresh' ORDER BY e.target_hour",
            conn, params=(horizon,), parse_dates={"target_hour": "%Y-%m-%d %H:%M:%S"})
        methods = pd.read_sql_query(
            "SELECT m.target_hour, m.method, m.estimate FROM method_estimates m JOIN estimates e USING (target_hour, horizon) "
            "WHERE m.horizon = ? AND e.block = 'test' AND e.status = 'ok'", conn, params=(horizon,), parse_dates={"target_hour": "%Y-%m-%d %H:%M:%S"})
        wide = methods.pivot(index="target_hour", columns="method", values="estimate") if len(methods) else pd.DataFrame()
        frame = base.set_index("target_hour").join(wide.drop(columns=["model"], errors="ignore"), how="left")
        frames[horizon] = frame.reindex(columns=list(FRAME_COLUMNS))
    return frames


def evaluate_frames(frames: Mapping[int, pd.DataFrame], view: Any) -> EvaluationResult:
    """The metrics of every method, the intervals of the comparisons and the error by week of `frames` (by horizon: the hours of the test with the analysis
    in ``actual``, the range in ``low`` and ``high`` and one column per method of ``METHODS``). A horizon with no hours has no metrics and the criteria
    that need it say they cannot be computed."""
    ev, test_first = view.evaluation, pd.Timestamp(view.split.test_first)
    hours, metrics_by, bootstraps, weekly = {}, {}, {}, []
    for horizon, frame in frames.items():
        hours[horizon] = len(frame)
        if not len(frame):
            metrics_by[horizon] = {}
            continue
        actual = frame["actual"].to_numpy(dtype="float64")
        metrics_by[horizon] = {
            m: metrics(actual, frame[m].to_numpy(dtype="float64"), *((frame["low"].to_numpy(dtype="float64"), frame["high"].to_numpy(dtype="float64")) if m == "model" else ()))
            for m in METHODS if frame[m].notna().all()
        }
        days = frame.index.normalize().to_numpy()
        for name, a, b, horizons in COMPARISONS:
            if horizon in horizons and a in metrics_by[horizon] and b in metrics_by[horizon]:
                bootstraps[_comparison_key(name, horizon)] = day_bootstrap(frame[a].to_numpy(dtype="float64") - actual, frame[b].to_numpy(dtype="float64") - actual,
                                                                          days, ev.bootstrap_resamples, ev.bootstrap_seed)
        weeks = ((frame.index - test_first) // WEEK).to_numpy()
        for week in np.unique(weeks):
            mask = weeks == week
            for m in WEEKLY_METHODS:
                if m in metrics_by[horizon]:
                    weekly.append({"week": (test_first + week * WEEK).strftime("%Y-%m-%d"), "horizon": horizon, "method": m,
                                   "mae": float(np.mean(np.abs(frame[m].to_numpy(dtype="float64")[mask] - actual[mask]))), "hours": int(mask.sum())})
    return EvaluationResult(hours, metrics_by, bootstraps, weekly)


def holdout_cohort(tables: HourTables, view: Any, horizon: int) -> tuple[pd.DatetimeIndex, pd.DataFrame, np.ndarray]:
    """The hours of the test with a fresh analysis and every input at `horizon`, their features at their issue instant and their analyses: the variants and the sign check
    of the sensitivities read the test through this, after the launch is sealed."""
    inside = tables.hours[(block_of(tables.hours, view) == "test").to_numpy()]
    hours = inside[eligible(tables, inside, horizon, view).to_numpy()]
    y, _fresh = tables.analysis_of(hours)
    return hours, design(tables, hours, horizon, view), y


def evaluate_test(conn: sqlite3.Connection, view: Any) -> EvaluationResult:
    """The evaluation of the test from what the warehouse issued (see the module)."""
    return evaluate_frames(issued_frames(conn, view), view)


def figures(result: EvaluationResult, sensitivity: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The numbers the criteria are made of, as the seal stores them in ``metrics`` (JSON-ready, ``None`` for a coverage that does not exist): by horizon the
    hours and each method's MAE, RMSE, bias and coverage; the intervals of the comparisons; and the sensitivity that C09 reads (``computed`` is false until
    the gate of the launch gives its result)."""
    def one(m: Metrics) -> dict[str, Any]:
        return {"mae": m.mae, "rmse": m.rmse, "bias": m.bias, "coverage": m.coverage}

    return {
        "horizons": {str(h): {"hours": result.hours[h], "methods": {m: one(v) for m, v in result.metrics[h].items()}} for h in result.hours},
        "bootstraps": {k: {"difference": b.difference, "ci_low": b.ci_low, "ci_high": b.ci_high, "resamples": b.resamples} for k, b in result.bootstraps.items()},
        "sensitivity": dict(sensitivity) if sensitivity is not None else {"computed": False, "passing": [], "kept_sign": []},
    }


# --- the criteria (requirements.md, 8.1) ------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Criterion:
    criterion_id: str
    name_es: str
    value: float | None
    baseline_value: float | None
    ci_low: float | None
    ci_high: float | None
    threshold_es: str
    passed: bool | None
    seen_by_research: str
    seen_by_planner: str
    verdict_es: str

    def seal_entry(self) -> dict[str, Any]:
        return {"id": self.criterion_id, "value": self.value, "baseline_value": self.baseline_value, "ci_low": self.ci_low, "ci_high": self.ci_high,
                "passed": self.passed, "verdict_es": self.verdict_es}


def _criterion(cid: str, value, baseline, passed: bool | None, verdict: str, threshold: str, ci=(None, None)) -> Criterion:
    text = CRITERIA[cid]
    return Criterion(cid, text.name_es, value, baseline, ci[0], ci[1], threshold, passed, text.seen_by_research, text.seen_by_planner, verdict)


def _cannot(cid: str, why: str, threshold: str) -> Criterion:
    """A criterion that cannot be computed is never passed (requirements.md, 8.1)."""
    return _criterion(cid, None, None, False, f"No se puede calcular: {why}.", threshold)


def _method(figs: Mapping[str, Any], horizon: int, method: str) -> Mapping[str, Any] | None:
    return figs["horizons"].get(str(horizon), {}).get("methods", {}).get(method)


def _lower(a: float | None, b: float | None) -> bool:
    """A strict win of the lower error: a tie, or a number that is not there, never passes."""
    return a is not None and b is not None and a < b


def criteria_of(figs: Mapping[str, Any], criteria_document: Mapping[str, Any]) -> list[Criterion]:
    """C01 to C10 from the figures of the test (``figures``) and the sealed limits of ``[criteria]`` (``c05_coverage_low``, ``c05_coverage_high``,
    ``c06_max_bias``): nothing else, so the same function rebuilds a sealed criterion from the seal (``criteria_from_seal``)."""
    out: list[Criterion] = []
    boots = figs["bootstraps"]
    model0, persistence0 = _method(figs, 0, "model"), _method(figs, 0, "b1_persistence")
    if model0 is None or persistence0 is None:
        out.append(_cannot("C01", "la prueba no tiene horas con análisis fresco en la hora que cerró", CRITERIA["C01"].threshold_es))
    else:
        a, b = model0["mae"], persistence0["mae"]
        ok = _lower(a, b)
        out.append(_criterion("C01", a, b, ok, texts.versus("C01", ok, a=a, b=b, horizon=0), CRITERIA["C01"].threshold_es))
    for cid, horizon in (("C02", 0), ("C03", 1), ("C04", 2)):
        model, base, boot = _method(figs, horizon, "model"), _method(figs, horizon, B_STAR), boots.get(_comparison_key("model_vs_b_star", horizon))
        if model is None or base is None or boot is None:
            out.append(_cannot(cid, f"la prueba no tiene horas con análisis fresco para el horizonte {horizon}", CRITERIA[cid].threshold_es))
            continue
        ok = boot["ci_high"] is not None and boot["ci_high"] < 0
        out.append(_criterion(cid, model["mae"], base["mae"], ok, texts.versus(cid, ok, a=model["mae"], b=base["mae"], low=boot["ci_low"], high=boot["ci_high"],
                                                                         who="la base más fuerte", horizon=horizon), CRITERIA[cid].threshold_es, (boot["ci_low"], boot["ci_high"])))
    low, high, max_bias = criteria_document["c05_coverage_low"], criteria_document["c05_coverage_high"], criteria_document["c06_max_bias"]
    if model0 is None:
        out.append(_cannot("C05", "la prueba no tiene horas con análisis fresco en la hora que cerró", texts.threshold_of("C05", low=low, high=high)))
        out.append(_cannot("C06", "la prueba no tiene horas con análisis fresco en la hora que cerró", texts.threshold_of("C06", max_bias=max_bias)))
    else:
        coverage, bias = model0["coverage"], model0["bias"]
        ok = coverage is not None and low <= coverage <= high
        out.append(_criterion("C05", coverage, None, ok, texts.coverage_verdict(ok, coverage, low, high), texts.threshold_of("C05", low=low, high=high)))
        ok = bias is not None and abs(bias) <= max_bias
        out.append(_criterion("C06", bias, None, ok, texts.bias_verdict(ok, bias, max_bias), texts.threshold_of("C06", max_bias=max_bias)))
    for cid, key, a_name, b_name in (("C07", "best_sensors_only_vs_b0_train_mean", "best_sensors_only", "b0_train_mean"),
                                     ("C08", "best_with_sensors_vs_best_lab_only", "best_with_sensors", "best_lab_only")):
        a, b, boot = _method(figs, 0, a_name), _method(figs, 0, b_name), boots.get(_comparison_key(key, 0))
        if a is None or b is None or boot is None:
            out.append(_cannot(cid, "falta uno de los modelos de comparación o las horas de la prueba", CRITERIA[cid].threshold_es))
            continue
        ok = boot["ci_high"] is not None and boot["ci_high"] < 0
        out.append(_criterion(cid, a["mae"], b["mae"], ok, texts.versus(cid, ok, a=a["mae"], b=b["mae"], low=boot["ci_low"], high=boot["ci_high"]),
                              CRITERIA[cid].threshold_es, (boot["ci_low"], boot["ci_high"])))
    sens = figs.get("sensitivity") or {"computed": False, "passing": [], "kept_sign": []}
    if not sens["computed"]:
        out.append(_cannot("C09", "la compuerta de sensibilidades no se calculó en el lanzamiento", CRITERIA["C09"].threshold_es))
    else:
        ok = len(sens["kept_sign"]) > 0
        out.append(_criterion("C09", float(len(sens["kept_sign"])), float(len(sens["passing"])), ok,
                              texts.stability_verdict(ok, sens["passing"], sens["kept_sign"], True), CRITERIA["C09"].threshold_es))
    hours = sum(h["hours"] for h in figs["horizons"].values())
    out.append(_criterion("C10", None, None, None, texts.informative_verdict(hours), CRITERIA["C10"].threshold_es))
    return out


def evaluate_criteria(result: EvaluationResult, view: Any, sensitivity: Mapping[str, Any] | None = None) -> list[Criterion]:
    from flotsilica.registry import sealed_document

    return criteria_of(figures(result, sensitivity), sealed_document(view)["criteria"])


def _rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, Mapping):
        return {k: _rounded(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(v) for v in value]
    return value


def criteria_from_seal(seal: Mapping[str, Any]) -> list[Criterion]:
    """C01 to C10 rebuilt from the test part of the seal with ``criteria_of``; each must give back its own entry of the seal to 6 decimals, or the seal is
    not taken (``SealError``): a seal that the code no longer knows how to rebuild is never published (D19)."""
    from flotsilica.registry import SealError

    test, launch = seal.get("test"), seal.get("launch")
    if not test or not launch:
        raise SealError("el sello no tiene la parte de la prueba: no hay criterios sellados")
    rebuilt = criteria_of(test["metrics"], launch["sealed_config"]["criteria"])
    sealed = {entry["id"]: entry for entry in test["criteria"]}
    for criterion in rebuilt:
        if _rounded(criterion.seal_entry()) != _rounded(sealed.get(criterion.criterion_id)):
            raise SealError(f"el criterio {criterion.criterion_id} del sello no se reconstruye desde sus cifras: lo sellado no se toma (docs/runbook.md, R7)")
    return rebuilt
