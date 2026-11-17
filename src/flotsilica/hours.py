"""The hours of the source (plan, section 8; D04, D05, D08): the aggregates of an hour, the state of each analysis and the age of the feed.

Everything here is a function of the rows (or hours) it receives and of nothing later than them: the state of an hour depends only on that
hour and the one before it, which is what the plant knew when the result arrived (or did not arrive) and what lets a replay in deliveries give
the same marks as the whole file.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from flotsilica.schema import AGGREGATE_COLUMNS, SENSORS

HOUR = pd.Timedelta(hours=1)


def aggregate_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """One row per hour, sorted by hour: ``hour``, ``rows`` and, sensor by sensor, ``<sensor>_mean``, ``<sensor>_std`` (sample, ddof = 1; NaN with
    a single row) and ``<sensor>_last`` (the value of the last row of the hour in the order the rows come). `rows` needs ``hour`` and the 19
    sensors, in file order; it is not changed."""
    grouped = rows.groupby("hour", sort=True)[list(SENSORS)]
    mean, std, last = grouped.mean(), grouped.std(ddof=1), grouped.last()
    columns: dict[str, object] = {"hour": mean.index.to_numpy(), "rows": rows.groupby("hour", sort=True).size().to_numpy().astype("int64")}
    for sensor in SENSORS:
        columns[f"{sensor}_mean"] = mean[sensor].to_numpy()
        columns[f"{sensor}_std"] = std[sensor].to_numpy()
        columns[f"{sensor}_last"] = last[sensor].to_numpy()
    out = pd.DataFrame(columns)
    assert list(out.columns[2:]) == list(AGGREGATE_COLUMNS)
    return out


def _check_hours(hours: pd.Series, what: str) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(hours)
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError(f"{what}: hour must be unique and increasing (the order of the file)")
    return index


def lab_states(first_rows: pd.DataFrame, is_ramp: pd.Series) -> pd.Series:
    """The state of the analysis of each hour (D05), indexed like `first_rows` (``hour``, ``silica_pct``: the first row of each hour, in order).

    ``interpolated``: the hour is in a ramp (its value changes within the hour) and so is the hour before it; ``held``: its value equals the
    one of the hour before it and it is not interpolated; ``fresh``: the rest. The hour before is the one an hour earlier on the clock: after a
    gap the first hour is never held or interpolated. `is_ramp` is indexed by hour."""
    index = _check_hours(first_rows["hour"], "first_rows")
    if not isinstance(is_ramp.index, pd.DatetimeIndex) or not index.isin(is_ramp.index).all():
        raise ValueError("is_ramp: must be indexed by hour and have a flag for every hour of first_rows")
    ramp = is_ramp.reindex(index).to_numpy(dtype=bool)
    silica = first_rows["silica_pct"].to_numpy(dtype="float64")
    contiguous = np.zeros(len(index), dtype=bool)
    contiguous[1:] = (index[1:] - index[:-1]) == HOUR
    previous_ramp = np.zeros(len(index), dtype=bool)
    previous_ramp[1:] = ramp[:-1]
    previous_silica = np.full(len(index), np.nan)
    previous_silica[1:] = silica[:-1]
    interpolated = ramp & previous_ramp & contiguous
    held = ~interpolated & contiguous & (silica == previous_silica)
    states = np.where(interpolated, "interpolated", np.where(held, "held", "fresh"))
    return pd.Series(states, index=first_rows.index, dtype=object)


def feed_age_hours(first_rows: pd.DataFrame) -> pd.DataFrame:
    """``feed_silica_age_h`` and ``feed_iron_age_h``: clock hours from the first hour of the run of equal values the hour is in (the value has not
    changed since), for ``feed_silica_pct`` and ``feed_iron_pct`` of each hour of `first_rows`, indexed like it. A run goes on across a gap if
    the value is the same after it."""
    index = _check_hours(first_rows["hour"], "first_rows")
    out = pd.DataFrame(index=first_rows.index)
    for name, source in (("feed_silica_age_h", "feed_silica_pct"), ("feed_iron_age_h", "feed_iron_pct")):
        values = first_rows[source].to_numpy(dtype="float64")
        starts = np.zeros(len(values), dtype=bool)
        if len(values):
            starts[0] = True
            starts[1:] = values[1:] != values[:-1]
        origin = index.to_numpy()[np.maximum.accumulate(np.where(starts, np.arange(len(values)), 0))] if len(values) else index.to_numpy()
        out[name] = ((index.to_numpy() - origin) / np.timedelta64(1, "h")).astype("float64")
    return out
