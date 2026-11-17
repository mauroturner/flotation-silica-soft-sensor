"""The features of an instant and the guards against leakage (RF09, D07, D12; plan, section 10).

An **issue instant** ``t`` is the close of an hour: the readings of the hour ``t - 1`` are complete and the analyses that have arrived are
those with ``available_at <= t`` (``available_at = hour + latency_hours``, D06). Everything here is a function of those two things and of
nothing later: the three horizons of an instant share its features, and the target hour of H1 and H2 (``t`` and ``t + 1``) is never read.

* ``lab_known_at`` is the one place that says which analyses are known at an instant; ``HourTables.inputs`` (frames) and ``inputs_at``
  (the warehouse) build ``IssueInputs`` through it, and ``feature_row`` filters by it again, so an analysis a caller hands over that has not
  arrived changes nothing.
* The history of the laboratory is the sequence of **fresh** analyses (D05): a held or interpolated hour is not a measurement.
* ``feature_row`` makes the 67 columns of the schema, with the block of a missing input in NaN; ``missing_inputs`` says why (the reasons
  of the plan: ``no_sensor_rows``, ``partial_below_minimum``, ``short_lab_history``, and ``no_feed_hour``).
* ``build_matrix`` is the guard (AC10, M02): a column that is forbidden, a target or outside the schema raises ``LeakageError``, and the
  matrix has exactly the columns of its set, in order.
* ``design`` makes the features of every hour of a block and a horizon, the instant of a target being ``target - horizon + 1 h``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from flotsilica.schema import (
    AGGREGATE_COLUMNS,
    FEATURE_COLUMNS,
    FEATURE_SETS,
    FEED_FEATURE_COLUMNS,
    LAB_FEATURE_COLUMNS,
    TARGET_COLUMNS,
    is_forbidden,
)

HOUR = timedelta(hours=1)
SENSOR_COLUMNS = ("rows", *AGGREGATE_COLUMNS)           # what ``IssueInputs.sensors`` holds: the hour's rows and its 57 aggregates
HISTORY_COLUMNS = ("sample_hour", "silica_pct", "available_at")
assert FEATURE_COLUMNS[: len(AGGREGATE_COLUMNS)] == AGGREGATE_COLUMNS and FEATURE_COLUMNS[-len(FEED_FEATURE_COLUMNS):] == FEED_FEATURE_COLUMNS


class LeakageError(RuntimeError):
    """A column that must never reach a model matrix (a forbidden one, a target or one outside the schema) was received or produced (AC10)."""


@dataclass(frozen=True, eq=False)
class IssueInputs:
    """What is known at an instant: the aggregates of the hour that closed (``sensors``: ``rows`` and the 57 aggregates; None if the hour has no
    rows), the fresh analyses (``lab_history``: ``sample_hour``, ``silica_pct``, ``available_at``, the most recent last) and the feed of the latest
    hour whose analysis has arrived (``feed``: the four columns of ``FEED_FEATURE_COLUMNS``; None if there is none)."""

    issue_at: datetime
    sensors: pd.Series | None
    lab_history: pd.DataFrame
    feed: pd.Series | None


def _history_needed(view: Any) -> int:
    f = view.features
    return max(f.min_fresh_history, f.lab_last, max(f.lab_means))


def _lab_names(view: Any) -> tuple[str, ...]:
    f = view.features
    names = (*(f"lab_last{k}" for k in range(1, f.lab_last + 1)), *(f"lab_mean{m}" for m in f.lab_means), "lab_age_h")
    if names != LAB_FEATURE_COLUMNS:
        raise ValueError(f"[features] lab_last y lab_means dan las columnas {list(names)}, y el esquema tiene {list(LAB_FEATURE_COLUMNS)}")
    return names


def lab_known_at(lab: pd.DataFrame, t: datetime) -> pd.DataFrame:
    """The analyses of `lab` (``sample_hour``, ``silica_pct``, ``available_at``) that have arrived at the instant `t`, in order of their samples:
    those with ``available_at <= t``. The arrival instant itself counts. A new frame; `lab` is not changed."""
    arrived = lab[lab["available_at"] <= pd.Timestamp(t)]
    return arrived.sort_values("sample_hour", kind="stable").reset_index(drop=True)


# --- the inputs of an instant ---------------------------------------------------------------------------------------------------


class HourTables:
    """The hours of the warehouse as arrays (``from_hours``), to make the inputs of any instant without a query: the same ones ``inputs_at``
    reads from SQLite, which a test compares at every instant."""

    def __init__(self, hours: pd.DataFrame) -> None:
        table = hours.sort_values("hour", kind="stable").reset_index(drop=True)
        if table["hour"].duplicated().any():
            raise ValueError("hours: cada hora una sola vez")
        self._hours = table["hour"].to_numpy(dtype="datetime64[ns]")
        self._available = table["available_at"].to_numpy(dtype="datetime64[ns]")
        if (np.diff(self._available.astype("int64")) < 0).any():
            raise ValueError("hours: el instante de llegada no puede decrecer con la hora")
        self._position = {int(h): i for i, h in enumerate(self._hours.astype("int64"))}
        self._aggregates = table[list(SENSOR_COLUMNS)].to_numpy(dtype="float64")
        self._feed = table[list(FEED_FEATURE_COLUMNS)].to_numpy(dtype="float64")
        fresh = (table["lab_state"] == "fresh").to_numpy()
        self._fresh_hours = self._hours[fresh]
        self._fresh_available = self._available[fresh]
        self._fresh_silica = table["silica_pct"].to_numpy(dtype="float64")[fresh]

    @classmethod
    def from_hours(cls, hours: pd.DataFrame, view: Any) -> HourTables:
        """The tables of `hours` (the canonical hours, or ``stg_hours``): ``available_at`` is ``hour + latency_hours`` if the frame has none."""
        if "available_at" not in hours.columns:
            hours = hours.assign(available_at=hours["hour"] + timedelta(hours=view.lab.latency_hours))
        return cls(hours)

    def fresh_known(self, t: datetime) -> tuple[np.ndarray, np.ndarray]:
        """``(sample hours, silica)`` of every fresh analysis that has arrived at `t`, in order of their samples (a view: not to be changed)."""
        count = int(np.searchsorted(self._fresh_available, np.datetime64(pd.Timestamp(t), "ns"), side="right"))
        return self._fresh_hours[:count], self._fresh_silica[:count]

    def inputs(self, t: datetime, view: Any) -> IssueInputs:
        """The ``IssueInputs`` of the instant `t`: the aggregates of the hour ``t - 1``, the last fresh analyses that have arrived and the feed
        of the latest hour whose analysis has arrived."""
        instant = np.datetime64(pd.Timestamp(t), "ns")
        place = self._position.get(int((instant - np.timedelta64(1, "h")).astype("int64")))
        sensors = None if place is None else pd.Series(self._aggregates[place], index=list(SENSOR_COLUMNS))
        hours, silica = self.fresh_known(t)
        keep = _history_needed(view)
        hours, silica = hours[-keep:], silica[-keep:]
        history = pd.DataFrame({"sample_hour": hours, "silica_pct": silica, "available_at": hours + np.timedelta64(view.lab.latency_hours, "h")})
        count = int(np.searchsorted(self._available, instant, side="right"))
        feed = None if count == 0 else pd.Series(self._feed[count - 1], index=list(FEED_FEATURE_COLUMNS))
        return IssueInputs(t, sensors, history, feed)


def _times(texts: list[str]) -> np.ndarray:
    """``YYYY-MM-DD HH:MM:SS`` texts as datetime64[ns] (numpy reads them without guessing a format, which pandas does for each call)."""
    return np.array([text.replace(" ", "T") for text in texts], dtype="datetime64[s]").astype("datetime64[ns]")


def _stamp(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def inputs_at(conn: sqlite3.Connection, t: datetime, view: Any) -> IssueInputs:
    """The ``IssueInputs`` of the instant `t` read from the warehouse: the aggregates of the hour ``t - 1`` and, of ``lab_hours``, only the rows
    with ``available_at <= t`` (the last fresh analyses, and the feed of the latest). Nothing later than `t` is selected."""
    now, before = _stamp(t), _stamp(pd.Timestamp(t) - HOUR)
    columns = ", ".join(SENSOR_COLUMNS)
    row = conn.execute(f"SELECT {columns} FROM hour_aggregates WHERE hour = ?", (before,)).fetchone()
    sensors = None if row is None else pd.Series([np.nan if v is None else float(v) for v in row], index=list(SENSOR_COLUMNS))
    keep = _history_needed(view)
    found = conn.execute("SELECT hour, silica_pct, available_at FROM lab_hours WHERE lab_state = 'fresh' AND available_at <= ? ORDER BY hour DESC LIMIT ?", (now, keep)).fetchall()
    found.reverse()
    history = pd.DataFrame({"sample_hour": _times([r[0] for r in found]), "silica_pct": [float(r[1]) for r in found],
                            "available_at": _times([r[2] for r in found])}, columns=list(HISTORY_COLUMNS))
    feed_columns = ", ".join(FEED_FEATURE_COLUMNS)
    latest = conn.execute(f"SELECT {feed_columns} FROM lab_hours WHERE available_at <= ? ORDER BY available_at DESC LIMIT 1", (now,)).fetchone()
    feed = None if latest is None else pd.Series([float(v) for v in latest], index=list(FEED_FEATURE_COLUMNS))
    return IssueInputs(t, sensors, history, feed)


# --- the row of features -----------------------------------------------------------------------------------------------------------


def feature_row(inputs: IssueInputs, view: Any) -> pd.Series:
    """The 67 columns of ``FEATURE_COLUMNS`` at the instant of `inputs`; the block of an input that is missing is NaN (see ``missing_inputs``).

    The sensor block is the 57 aggregates of the hour that closed, if it has ``min_rows_per_hour`` rows; the laboratory block is the three latest
    fresh analyses that have arrived, the means of the latest 6 and 24 and the age of the latest, ``(issue_at - latency) - sample hour``, in hours,
    if at least ``min_fresh_history`` have arrived; the feed block is the feed of the latest hour whose analysis has arrived."""
    lab_names = _lab_names(view)
    values = pd.Series(np.nan, index=list(FEATURE_COLUMNS), dtype="float64")
    sensors = inputs.sensors
    if sensors is not None and sensors["rows"] >= view.hours.min_rows_per_hour:
        values[list(AGGREGATE_COLUMNS)] = sensors[list(AGGREGATE_COLUMNS)].to_numpy(dtype="float64")
    known = lab_known_at(inputs.lab_history, inputs.issue_at)
    if len(known) >= view.features.min_fresh_history:
        silica = known["silica_pct"].to_numpy(dtype="float64")
        for k in range(1, view.features.lab_last + 1):
            if len(silica) >= k:
                values[f"lab_last{k}"] = silica[-k]
        for m in view.features.lab_means:
            if len(silica) >= m:
                values[f"lab_mean{m}"] = float(np.mean(silica[-m:]))
        newest = known["sample_hour"].iloc[-1]
        values[lab_names[-1]] = (pd.Timestamp(inputs.issue_at) - timedelta(hours=view.lab.latency_hours) - newest) / HOUR
    if inputs.feed is not None:
        values[list(FEED_FEATURE_COLUMNS)] = inputs.feed[list(FEED_FEATURE_COLUMNS)].to_numpy(dtype="float64")
    return values


def missing_inputs(inputs: IssueInputs, feature_set: str, view: Any) -> str | None:
    """Why the set `feature_set` cannot be computed at this instant, or None: the readings of the hour that closed are missing
    (``no_sensor_rows``) or too few (``partial_below_minimum``), fewer than ``min_fresh_history`` analyses have arrived (``short_lab_history``)
    or there is no hour whose analysis has arrived to take the feed from (``no_feed_hour``), in that order, for the blocks the set has."""
    if feature_set not in FEATURE_SETS:
        raise ValueError(f"conjunto desconocido: {feature_set!r}")
    columns = set(FEATURE_SETS[feature_set])
    if columns & set(AGGREGATE_COLUMNS):
        if inputs.sensors is None:
            return "no_sensor_rows"
        if inputs.sensors["rows"] < view.hours.min_rows_per_hour:
            return "partial_below_minimum"
    if columns & set(LAB_FEATURE_COLUMNS) and len(lab_known_at(inputs.lab_history, inputs.issue_at)) < view.features.min_fresh_history:
        return "short_lab_history"
    if columns & set(FEED_FEATURE_COLUMNS) and inputs.feed is None:
        return "no_feed_hour"
    return None


# --- the matrix and its guard ---------------------------------------------------------------------------------------------------------


def build_matrix(rows: pd.DataFrame, feature_set: str) -> pd.DataFrame:
    """The matrix of `feature_set` from `rows` (features by instant): exactly its columns, in its order (M02).

    Any column of `rows` that is forbidden (``schema.FORBIDDEN_COLUMNS``, a laboratory value of a row), a target or outside the schema's feature
    columns raises ``LeakageError`` naming it, whatever the set; a column of the set that `rows` lacks is a ``ValueError``."""
    if feature_set not in FEATURE_SETS:
        raise ValueError(f"conjunto desconocido: {feature_set!r}")
    allowed = set(FEATURE_COLUMNS)
    for name in rows.columns:
        if is_forbidden(name) or name in TARGET_COLUMNS or name not in allowed:
            raise LeakageError(f"la columna {name!r} no puede llegar a la matriz del conjunto {feature_set}: es una columna prohibida, un objetivo o está fuera del esquema")
    columns = list(FEATURE_SETS[feature_set])
    missing = [name for name in columns if name not in rows.columns]
    if missing:
        raise ValueError(f"a la matriz del conjunto {feature_set} le faltan las columnas {missing}")
    matrix = rows[columns].copy()
    if list(matrix.columns) != columns:      # pragma: no cover - the selection above makes it so; M02 states it
        raise LeakageError(f"las columnas de la matriz no son las del conjunto {feature_set}")
    return matrix


def design(tables: HourTables, targets: pd.DatetimeIndex, horizon: int, view: Any) -> pd.DataFrame:
    """The features of every target hour for a horizon: one row per hour of `targets` (the index), the 67 columns, taken at the instant
    ``target - horizon + 1 hour`` (H0 estimates the hour that just closed, H1 the one that starts, H2 the next)."""
    if not isinstance(horizon, (int, np.integer)) or isinstance(horizon, bool) or horizon < 0:
        raise ValueError(f"horizon: se esperaba un entero de 0 o más, se recibió {horizon!r}")
    targets = pd.DatetimeIndex(targets)
    rows = [feature_row(tables.inputs((target - (int(horizon) - 1) * HOUR).to_pydatetime(), view), view).to_numpy() for target in targets]
    matrix = np.vstack(rows) if rows else np.empty((0, len(FEATURE_COLUMNS)))
    return pd.DataFrame(matrix, index=targets, columns=list(FEATURE_COLUMNS))
