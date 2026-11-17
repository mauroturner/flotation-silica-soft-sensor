"""The estimates of an issue instant and the run that stores them (RF16, D07, D21, D22, D24; M02, M04; plan, sections 3 and 15).

``score_issue`` is the one function that turns what is known at an instant into estimates (the pipeline and, in U19, the API call it): for each horizon of
the frozen bundle it makes the features of the instant, checks that the inputs its models need are there (otherwise the horizon is ``missing_inputs`` with
the reason, and nothing is estimated), and gives the estimate of the model with its 80 % range, the persistence, B* and the other methods, each from what had
arrived at the instant and nothing later. H0 estimates the hour that closed, H1 the one that starts and H2 the next (D07).

``score_run`` stores the estimates of the instants a delivery makes known. An estimate is **issued once**: ``estimates`` and ``method_estimates`` refuse,
in the database itself, an update, a delete and a second insert of a key (``sql/schema/003_model.sql``), and ``score_run`` reads inside its transaction what
was already issued and leaves it alone, so a later run, a repeated run or a retrained model never changes what was said (D22).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from flotsilica.baselines import B1, B2
from flotsilica.features import IssueInputs, feature_row, inputs_at, lab_known_at, missing_inputs
from flotsilica.intervals import interval
from flotsilica.registry import ModelBundle
from flotsilica.schema import AGGREGATE_COLUMNS
from flotsilica.split import block_of
from flotsilica.warehouse import apply_schema

logger = logging.getLogger(__name__)

HOUR = timedelta(hours=1)
METHOD_MODEL = "model"
METHOD_NAMES = ("model", "b0_train_mean", B1, B2, "b3_ridge_sensors", "best_sensors_only", "best_lab_only", "best_with_sensors")
LAUNCH_INSTANTS = 2          # the launch emits at the last two closes of its hours (plan, section 3)
OK, MISSING = "ok", "missing_inputs"


class EstimateError(RuntimeError):
    """M04: an estimate or its range is not finite, or the range does not hold the estimate. The task fails and nothing is stored."""


class ScoringError(RuntimeError):
    """A run asks to issue estimates over hours that are not in the warehouse yet, or that cannot be issued."""


@dataclass(frozen=True)
class RunMeta:
    """The run that issues estimates: its key, its delivery and the delivery's kind and ``as_of``, and the ``as_of`` of the delivery before it."""

    run_key: str
    delivery_id: str
    kind: str
    as_of: datetime
    previous_as_of: datetime | None = None


@dataclass(frozen=True, eq=False)
class Estimate:
    """What is said at an instant about one hour for one horizon: the estimate with its range, the persistence and B*, and the other methods; or the
    reason it could not be said (``status`` ``missing_inputs``), with no number."""

    horizon: int
    target_hour: datetime
    issue_at: datetime
    status: str
    reason: str | None
    block: str
    is_censored: bool
    estimate: float | None = None
    low: float | None = None
    high: float | None = None
    persistence: float | None = None
    b_star: float | None = None
    b_star_method: str | None = None
    methods: dict[str, float] = field(default_factory=dict)

    def same_as(self, other: Estimate) -> bool:
        """Whether two estimates say exactly the same (a missing number equals a missing number)."""
        return (self.horizon, self.target_hour, self.issue_at, self.status, self.reason, self.block, self.is_censored, self.b_star_method) == (
            other.horizon, other.target_hour, other.issue_at, other.status, other.reason, other.block, other.is_censored, other.b_star_method) and all(
            _same(a, b) for a, b in ((self.estimate, other.estimate), (self.low, other.low), (self.high, other.high),
                                     (self.persistence, other.persistence), (self.b_star, other.b_star))) and self.methods.keys() == other.methods.keys() and all(
            _same(v, other.methods[k]) for k, v in self.methods.items())


def _same(a: float | None, b: float | None) -> bool:
    return a is None and b is None or a is not None and b is not None and a == b


# --- the instants of a run --------------------------------------------------------------------------------------------------------------


def issue_instants(run: RunMeta) -> list[datetime]:
    """The instants a run issues at (plan, section 3): the launch, its last two closes (``as_of - 1 h`` and ``as_of``); a daily delivery, every hour of
    ``(previous as_of, as_of]``; the close, none."""
    if run.kind == "close":
        return []
    if run.kind == "launch":
        return [run.as_of - HOUR * (LAUNCH_INSTANTS - 1 - k) for k in range(LAUNCH_INSTANTS)]
    if run.kind != "daily":
        raise ValueError(f"tipo de entrega desconocido: {run.kind!r}")
    if run.previous_as_of is None:
        raise ValueError("una entrega diaria necesita el as_of de la entrega anterior")
    if run.as_of <= run.previous_as_of:
        raise ValueError(f"el as_of ({run.as_of}) debe ser posterior al de la entrega anterior ({run.previous_as_of})")
    count = int((run.as_of - run.previous_as_of) / HOUR)
    return [run.previous_as_of + HOUR * (k + 1) for k in range(count)]


# --- one instant ---------------------------------------------------------------------------------------------------------------------


def _needed_set(bundle_horizon: Any, comparisons: dict[str, Any]) -> str:
    """The set whose blocks the estimate needs: the cohort of the models (sensors and laboratory, ``fSL``), or ``fSLF`` if any of its models reads the feed."""
    sets = {bundle_horizon.candidate.feature_set, *(m.candidate.feature_set for m in comparisons.values())}
    return "fSLF" if "fSLF" in sets else "fSL"


def _checked(value: float, what: str) -> float:
    if not np.isfinite(value):
        raise EstimateError(f"M04: {what} no es un número finito")
    return float(value)


def score_issue(bundle: ModelBundle, inputs: IssueInputs, view: Any) -> list[Estimate]:
    """The estimates of the instant ``inputs.issue_at`` for each horizon of `bundle`, from `inputs` alone (``features.inputs_at`` or ``HourTables.inputs``).

    A horizon whose inputs are not all there is ``missing_inputs`` with the reason (``no_sensor_rows``, ``partial_below_minimum``, ``short_lab_history``
    or ``no_feed_hour``); the others carry the estimate of the model, its range ``[estimate - q, estimate + q]`` clipped to [0, 100], the persistence, B*
    and the eight methods of the comparison (``METHOD_NAMES``; one the bundle lacks is left out). The columns of every model come through
    ``build_matrix`` (M02), and a number that is not finite or a range that does not hold its estimate is an ``EstimateError`` (M04)."""
    issue_at = pd.Timestamp(inputs.issue_at).to_pydatetime()
    row = feature_row(inputs, view)
    frame = pd.DataFrame([row.to_numpy()], columns=list(row.index))
    silica = lab_known_at(inputs.lab_history, inputs.issue_at)["silica_pct"].to_numpy(dtype="float64")
    out = []
    for hm in bundle.horizons:
        target = issue_at + (hm.horizon - 1) * HOUR
        comparisons = bundle.comparisons.get(hm.horizon, {})
        block = str(block_of(pd.DatetimeIndex([target]), view).iloc[0])
        censored = bool(target > view.hours.last_hour)
        base = dict(horizon=hm.horizon, target_hour=target, issue_at=issue_at, block=block, is_censored=censored)
        reason = missing_inputs(inputs, _needed_set(hm, comparisons), view)
        if reason is not None:
            out.append(Estimate(status=MISSING, reason=reason, **base))
            continue
        model = _checked(hm.estimator.predict(frame)[0], "la estimación del modelo")
        low, high = interval(model, _checked(hm.half_width, "el semiancho"))
        if not low <= model <= high:
            raise EstimateError(f"M04: el rango [{low:.4f}, {high:.4f}] no contiene la estimación {model:.4f}")
        persistence = _checked(frame["lab_last1"].iloc[0], "la persistencia")
        b2 = _checked(float(np.mean(silica[-hm.b2_k:])), "B2")
        methods = {
            METHOD_MODEL: model, "b0_train_mean": _checked(bundle.b0_mean, "B0"), B1: persistence, B2: b2,
            "b3_ridge_sensors": _checked(bundle.b3[hm.horizon].predict(frame[list(AGGREGATE_COLUMNS)])[0], "B3"),
            **{name: _checked(comparisons[name].predict(frame)[0], name) for name in ("best_sensors_only", "best_lab_only", "best_with_sensors") if name in comparisons},
        }
        b_star = persistence if hm.b_star == B1 else b2
        out.append(Estimate(status=OK, reason=None, estimate=model, low=low, high=high, persistence=persistence, b_star=b_star, b_star_method=hm.b_star,
                            methods=methods, **base))
    return out


# --- a run -------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreResult:
    """What a run did: the instants it went through, the estimates it stored (``issued`` with their numbers, ``missing`` without), the ones that were already
    in the warehouse and were left alone (``skipped``) and the rows it added to ``method_estimates``."""

    instants: int
    issued: int
    missing: int
    skipped: int
    methods: int


def _stamp(value: datetime | pd.Timestamp) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


ESTIMATE_COLUMNS = ("target_hour", "horizon", "issue_at", "run_key", "model_version", "status", "reason", "estimate", "low", "high", "persistence", "b_star",
                    "b_star_method", "block", "is_censored")


def _loaded_until(conn: sqlite3.Connection) -> datetime | None:
    value = conn.execute("SELECT MAX(as_of) FROM deliveries WHERE status = 'loaded'").fetchone()[0]
    return None if value is None else pd.Timestamp(value).to_pydatetime()


def score_run(conn: sqlite3.Connection, run: RunMeta, bundle: ModelBundle, view: Any) -> ScoreResult:
    """Issue the estimates of every instant of `run` (``issue_instants``) in one transaction, from what the warehouse holds at each instant (``inputs_at``).

    What is already issued is read inside the transaction and left alone, whatever the bundle says now: an estimate is issued once (D22), so a repeated
    run, a later run or another model never changes it, and those that were there are counted as ``skipped``. A run that asks for instants after the
    last delivery that was loaded is a ``ScoringError``: an hour that is not there yet would be stored as missing for good. If anything fails, M04
    included, nothing is stored."""
    instants = issue_instants(run)
    conn.execute("BEGIN IMMEDIATE")
    issued = missing = skipped = methods = 0
    try:
        apply_schema(conn)
        loaded = _loaded_until(conn)
        if instants and (loaded is None or instants[-1] > loaded):
            raise ScoringError(f"la corrida {run.run_key} emite hasta {_stamp(instants[-1])} y lo cargado llega hasta "
                               f"{'nada' if loaded is None else _stamp(loaded)}: las horas que faltan no se pueden declarar sin entradas")
        for t in instants:
            known = {(r[0], r[1]) for r in conn.execute("SELECT target_hour, horizon FROM estimates WHERE issue_at = ?", (_stamp(t),))}
            for e in score_issue(bundle, inputs_at(conn, t, view), view):
                if (_stamp(e.target_hour), e.horizon) in known:
                    skipped += 1
                    continue
                conn.execute(f"INSERT INTO estimates ({', '.join(ESTIMATE_COLUMNS)}) VALUES ({', '.join('?' * len(ESTIMATE_COLUMNS))})", (
                    _stamp(e.target_hour), e.horizon, _stamp(e.issue_at), run.run_key, bundle.version, e.status, e.reason, e.estimate, e.low, e.high,
                    e.persistence, e.b_star, e.b_star_method, e.block, int(e.is_censored)))
                conn.executemany("INSERT INTO method_estimates (target_hour, horizon, method, estimate) VALUES (?, ?, ?, ?)",
                                 [(_stamp(e.target_hour), e.horizon, name, e.methods[name]) for name in METHOD_NAMES if name in e.methods])
                methods += len(e.methods)
                issued += e.status == OK
                missing += e.status == MISSING
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        logger.warning("score %s rolled back: nothing was stored", run.run_key)
        raise
    logger.info("score %s: instants=%d issued=%d missing=%d skipped=%d", run.run_key, len(instants), issued, missing, skipped)
    return ScoreResult(len(instants), issued, missing, skipped, methods)
