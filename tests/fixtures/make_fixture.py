"""The synthetic ARFF, its truth and its malformed variants (plan, section 24; decision D40).

``make_fixture(path, rows_per_hour=12, seed=0, signal="none", weeks=None)`` writes a file with the real one's header (the ``%`` comments,
``@RELATION``, 24 ``@ATTRIBUTE ... STRING``), its calendar (2017-03-10 01:00 to 2017-09-09 23:00 with the 318-hour gap of 2017-03-16 06:00 to
2017-03-29 11:00 in its place and the two partial hours), apostrophes around every field and the decimal comma, and returns what is in it
(``FixtureTruth``): the state of every hour, the counts each validation rule must find, and the sign of the planted signal.

The hourly silica is a process that is known: an autoregressive process of order 1 (phi = 0.76) around a level that goes from 2.6 to 2.0,
written with two decimals. On it are planted, as the real file has them (research.md; D05):

* ramp stretches: a ramp start (fresh), then 2 to 6 interpolated hours whose first value is on the line between the analysis at the start and
  the one at the end, which is a fresh hour; inside every ramp hour the rows go from the hour's value to the next hour's in equal steps;
* single-hour ramps (a fresh hour whose rows go to the next hour's value);
* held stretches: 2 to 10 hours equal to the fresh hour before them;
* a feed (``% Iron Feed`` and ``% Silica Feed``) that stays unchanged for hours or days and never changes within an hour;
* ``air_flow_04`` and ``air_flow_05`` fixed within some hours;
* ``% Iron Concentrate`` correlated with the silica at -0.8;
* a number with no fractional part (``390``) written without apostrophes, as the real file does with every one of them.

``signal="sensor_signal"`` adds ``beta x amina_flow`` of the same hour to the silica (the positive control: the model with sensors can beat
the persistence and the gate finds ``amina_flow`` with its sign); ``signal="lab_only"`` makes every sensor independent noise, hour to hour
too (the negative control). ``weeks=N`` keeps the hours before the N-th week: the file is the prefix of the full one.
"""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

RELATION = "Quality-Prediction-in-a-Mining-Process"
ATTRIBUTES = (
    "date", "%_Iron_Feed", "%_Silica_Feed", "Starch_Flow", "Amina_Flow", "Ore_Pulp_Flow", "Ore_Pulp_pH", "Ore_Pulp_Density",
    *(f"Flotation_Column_0{k}_Air_Flow" for k in range(1, 8)), *(f"Flotation_Column_0{k}_Level" for k in range(1, 8)),
    "%_Iron_Concentrate", "%_Silica_Concentrate",
)
SENSORS = (
    "starch_flow", "amina_flow", "ore_pulp_flow", "ore_pulp_ph", "ore_pulp_density",
    *(f"air_flow_0{k}" for k in range(1, 8)), *(f"level_0{k}" for k in range(1, 8)),
)
FIRST_HOUR = datetime(2017, 3, 10, 1)
LAST_HOUR = datetime(2017, 9, 9, 23)
GAP_FIRST = datetime(2017, 3, 16, 6)
GAP_LAST = datetime(2017, 3, 29, 11)                 # 318 hours without rows
PARTIAL_HOURS = (datetime(2017, 3, 10, 1), datetime(2017, 4, 10, 0))   # 174 and 179 rows of 180 in the real file
SIGNALS = ("none", "sensor_signal", "lab_only")
SIGNAL_SENSOR = "amina_flow"
SIGNAL_BETA = 0.7
MIN_ROWS_PER_HOUR = 4
FIXED_SENSORS = ("air_flow_04", "air_flow_05")
HOURS_PER_WEEK = 168
PHI_SILICA, SD_SILICA = 0.76, 0.5
PHI_SENSORS = 0.8
IRON_SILICA_CORR = -0.8
MIN_RAMP_JUMP, MIN_SINGLE_RAMP_JUMP = 0.3, 0.1       # the analyses at the two ends of a ramp differ by at least this much

# (mean, standard deviation of the hourly level, standard deviation of a row around it, decimals), in the order of SENSORS
_SENSOR_SHAPE = (
    (2900.0, 800.0, 40.0, 2), (580.0, 60.0, 6.0, 3), (400.0, 8.0, 2.0, 3), (9.8, 0.35, 0.02, 4), (1.68, 0.06, 0.004, 4),
    (250.0, 25.0, 3.0, 3), (252.0, 25.0, 3.0, 3), (250.0, 25.0, 3.0, 3), (295.0, 25.0, 3.0, 3), (306.0, 25.0, 3.0, 3),
    (250.0, 25.0, 3.0, 3), (250.0, 25.0, 3.0, 3),
    *((450.0, 40.0, 6.0, 3),) * 7,
)

# The variants of ``make_malformed`` and the rule of the plan (section 6) each one must trip
MALFORMED_RULE = {
    "wrong_hash": "V01", "bad_relation": "V02", "missing_attribute": "V02", "extra_attribute": "V02", "renamed_attribute": "V02",
    "numeric_attribute": "V02", "field_count": "V04", "empty_field": "V04", "bad_date": "V05", "minute_not_zero": "V05",
    "dot_decimal": "V05", "text_number": "V05", "unsorted": "V06", "hour_over_limit": "V07", "long_line": "V03", "nul_byte": "V03",
    "bad_utf8": "V03", "oversize": "V03",
}
MALFORMED_KINDS = tuple(MALFORMED_RULE)
MALFORMED_ROW = 4                                    # the data line that the variants of one row change (the first hour has more)
OVERSIZE_DEFAULT_BYTES = 1 << 20


@dataclass
class FixtureTruth:
    """What the file written by ``make_fixture`` holds.

    ``hours`` has one row per hour of the file (index ``hour``): ``rows``, ``partial``, ``silica`` and ``iron_conc`` (the first row, which is
    the hour's analysis), ``is_ramp`` (the silica changes within the hour), ``state`` (``fresh``, ``interpolated`` or ``held``: the rule of
    D05, planted), ``feed_silica``, ``feed_iron`` and their ages in clock hours since the value last changed (the first hour of the file, or
    the first one after the gap when it changed there, is age 0). ``counts`` has what each validation rule must find.
    """

    path: Path
    sha256: str
    size_bytes: int
    n_rows: int
    rows_per_hour: int
    seed: int
    signal: str
    weeks: int | None
    signal_sensor: str | None
    signal_sign: int
    signal_beta: float
    iron_silica_corr: float
    hours: pd.DataFrame = field(repr=False)
    counts: dict = field(default_factory=dict)


def _check_arguments(rows_per_hour, seed, signal, weeks) -> None:
    if signal not in SIGNALS:
        raise ValueError(f"signal: expected one of {SIGNALS}, got {signal!r}")
    if not isinstance(rows_per_hour, int) or isinstance(rows_per_hour, bool) or rows_per_hour < MIN_ROWS_PER_HOUR:
        raise ValueError(f"rows_per_hour: expected an integer of {MIN_ROWS_PER_HOUR} or more, got {rows_per_hour!r}")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError(f"seed: expected a non-negative integer, got {seed!r}")
    if weeks is not None and (not isinstance(weeks, int) or isinstance(weeks, bool) or weeks < 1):
        raise ValueError(f"weeks: expected a positive integer or None, got {weeks!r}")


def _ar1(noise: np.ndarray, phi: float) -> np.ndarray:
    """Unit-variance AR(1) along the last axis from standard normal `noise`."""
    out = np.empty_like(noise)
    out[..., 0] = noise[..., 0]
    scale = np.sqrt(1.0 - phi * phi)
    for t in range(1, noise.shape[-1]):
        out[..., t] = phi * out[..., t - 1] + scale * noise[..., t]
    return out


def _runs(rng: np.random.Generator, n: int, spacing: tuple[int, int], length: tuple[int, int]) -> np.ndarray:
    """A boolean array of `n` hours with runs of True of `length` hours separated by `spacing` hours."""
    flag, t = np.zeros(n, dtype=bool), 0
    while t < n:
        t += int(rng.integers(*spacing))
        size = int(rng.integers(*length))
        flag[t:t + size] = True
        t += size
    return flag


def _feed(rng: np.random.Generator, n: int, start: float, step: float, low: float, high: float) -> np.ndarray:
    """A feed analysis that stays the same for hours or days: short runs of 2 to 17 hours or long ones of 24 to 199, two decimals, and every
    change is a different value."""
    values, t, current = np.empty(n), 0, start
    while t < n:
        size = int(rng.integers(2, 18)) if rng.random() < 0.65 else int(rng.integers(24, 200))
        values[t:t + size] = current
        t += size
        nxt = round(float(np.clip(current + rng.normal(0.0, step), low, high)), 2)
        current = nxt if nxt != current else round(nxt + 0.01, 2)
    return values


@dataclass(frozen=True)
class _Plant:
    kind: str          # "interp", "single" or "held"
    start: int         # grid index of the first hour of the stretch
    size: int          # interpolated hours (interp) or held hours (held); 0 for single


def _plan_plants(rng: np.random.Generator, n: int, usable: np.ndarray) -> list[_Plant]:
    """Where the stretches go: never across the gap or a partial hour, with a normal fresh hour on each side. The first three are one of
    each kind, so that even three weeks hold them."""
    used = np.zeros(n, dtype=bool)
    plants: list[_Plant] = []
    kinds = ["interp", "held", "single"]
    cursor = 3
    while cursor < n - 14:
        cursor += int(rng.integers(6, 30))
        kind = kinds[len(plants)] if len(plants) < len(kinds) else str(rng.choice(["interp", "held", "single"], p=[0.4, 0.4, 0.2]))
        size = int(rng.integers(2, 7)) if kind == "interp" else int(rng.integers(2, 11)) if kind == "held" else 0
        end = cursor + size + 1 if kind == "interp" else cursor + size if kind == "held" else cursor + 1    # the hour after the stretch
        low, high = cursor - 1, end + 1
        if high < n and usable[low:high + 1].all() and not used[low:high + 1].any():
            plants.append(_Plant(kind, cursor, size))
            used[low:high + 1] = True
            cursor = high + 1
        else:
            cursor += 1
    return plants


def _lab_series(raw_silica: np.ndarray, raw_iron: np.ndarray, observed: np.ndarray, plants: list[_Plant]):
    """The silica and iron analyses of every hour with the stretches planted, their states and which hours are ramps. A fresh hour never
    repeats the hour before it (so no repetition is an accident); a ramp end is at least ``MIN_RAMP_JUMP`` from its start."""
    n = len(raw_silica)
    silica, iron = raw_silica.copy(), raw_iron.copy()
    state = np.array(["fresh"] * n, dtype=object)
    ramp = np.zeros(n, dtype=bool)
    plant_at = {p.start: p for p in plants}
    t = 0
    while t < n:
        if not observed[t]:
            t += 1
            continue
        plant = plant_at.get(t)
        if plant is not None and plant.kind == "held":
            silica[t:t + plant.size], iron[t:t + plant.size] = silica[t - 1], iron[t - 1]
            state[t:t + plant.size] = "held"
            t += plant.size
            continue
        if t > 0 and observed[t - 1]:
            while silica[t] == silica[t - 1]:
                silica[t] = round(float(silica[t]) + 0.01, 2)
        if plant is None:
            t += 1
            continue
        size = plant.size if plant.kind == "interp" else 0
        end = t + size + 1
        jump = MIN_RAMP_JUMP if plant.kind == "interp" else MIN_SINGLE_RAMP_JUMP
        start_silica, end_silica = float(silica[t]), float(silica[end])
        while abs(end_silica - start_silica) < jump:
            end_silica = round(end_silica + (jump if end_silica >= start_silica else -jump), 2)
        silica[end] = end_silica
        for j in range(1, size + 1):
            silica[t + j] = round(start_silica + (end_silica - start_silica) * j / (size + 1), 6)
            iron[t + j] = round(float(iron[t]) + (float(iron[end]) - float(iron[t])) * j / (size + 1), 6)
        state[t + 1:t + size + 1] = "interpolated"
        ramp[t:t + size + 1] = True
        t = end
    return silica, iron, state, ramp


_BARE_INTEGER = re.compile(r"(?<![^," + chr(10) + r"])'(-?[0-9]+)'(?![^," + chr(10) + r"])")


def _cell(text: str) -> str:
    """One field of a data line: between apostrophes, or bare if it is an integer, as the real file writes a number with no fractional part."""
    return text if text.lstrip("-").isdigit() else f"'{text}'"


def _csv_body(frame: pd.DataFrame) -> str:
    """The data lines of `frame`: what ``frame.to_csv(header=False, index=False, quoting=csv.QUOTE_ALL, quotechar="'", decimal=",", float_format="%.6g",
    lineterminator="\n")`` gives with every integer field unquoted by ``_BARE_INTEGER`` (``tests/unit/test_fixture.py`` compares the two), written without
    pandas' formatter, which took a second for the 49,000 lines of the standard fixture."""
    columns = []
    for name in frame.columns:
        values = frame[name].tolist()
        if frame[name].dtype.kind == "f":
            assert not frame[name].isna().any(), f"{name}: the fixture has no missing values"
            columns.append([_cell(("%.6g" % v).replace(".", ",")) for v in values])
        else:
            columns.append([_cell(str(v)) for v in values])
    return "".join(",".join(cells) + "\n" for cells in zip(*columns, strict=True))


def _fmt(values: np.ndarray) -> list[str]:
    """Decimal-comma text with up to six decimals and no trailing zeros, as the real file writes the laboratory columns."""
    return [f"{v:.6f}".rstrip("0").rstrip(".").replace(".", ",") for v in values]


def _header(rows_per_hour: int, seed: int, signal: str) -> bytes:
    comments = [
        "% Context",
        "% Synthetic stand-in for the OpenML 43311 file (a flotation plant of an iron ore mining process), written by "
        "tests/fixtures/make_fixture.py with a known truth: nothing in it was measured",
        "% Content",
        "% The first column shows time and date range (from march of 2017 until september of 2017). The rows of an hour share its date",
        "% Columns 2 and 3 are the laboratory quality of the pulp that is fed; columns 4 to 22 are process variables; the last two are the "
        "laboratory quality of the concentrate",
        f"% Parameters: rows_per_hour={rows_per_hour}, seed={seed}, signal={signal}",
    ]
    lines = [*comments, f"@RELATION {RELATION}", ""]
    lines += [f'@ATTRIBUTE {name if "%" not in name else chr(34) + name + chr(34)} STRING' for name in ATTRIBUTES]
    return ("\n".join([*lines, "", "@DATA"]) + "\n").encode("utf-8")


def make_fixture(path: Path | str, rows_per_hour: int = 12, seed: int = 0, signal: str = "none", weeks: int | None = None) -> FixtureTruth:
    """Write the synthetic ARFF at `path` and return what it holds (see the module's docstring)."""
    _check_arguments(rows_per_hour, seed, signal, weeks)
    path = Path(path)
    rng = np.random.default_rng(seed)
    grid = pd.date_range(FIRST_HOUR, LAST_HOUR, freq="h")
    n = len(grid)
    observed = ~np.asarray((grid >= GAP_FIRST) & (grid <= GAP_LAST))
    rows_of = np.full(n, rows_per_hour)
    partial_index = [int((p - FIRST_HOUR) / timedelta(hours=1)) for p in PARTIAL_HOURS]
    rows_of[partial_index[0]], rows_of[partial_index[1]] = rows_per_hour - 2, rows_per_hour - 1
    usable = observed.copy()
    for k in partial_index:
        usable[k] = False
    usable[:3] = usable[-3:] = False
    gap_edges = np.flatnonzero(np.diff(observed.astype(int)) != 0)
    for k in gap_edges:                       # two hours of margin on each side of the gap
        usable[max(k - 1, 0):k + 4] = False

    # the silica: an AR(1) around a level that falls from 2.6 to 2.0, and the sensors' hourly levels
    t = np.arange(n)
    ar = _ar1(rng.normal(size=n), PHI_SILICA)
    eps = rng.normal(size=(len(SENSORS), n))
    amina = SENSORS.index(SIGNAL_SENSOR)
    z = eps.copy() if signal == "lab_only" else _ar1(eps, PHI_SENSORS)
    if signal == "sensor_signal":
        z[amina] = eps[amina]                 # white noise hour to hour: the effect on the silica is the same hour's
    level = 2.6 - 0.6 * t / (n - 1) + SD_SILICA * ar + (SIGNAL_BETA * z[amina] if signal == "sensor_signal" else 0.0)
    raw_silica = np.round(np.maximum(level, 0.3), 2)
    zs = (raw_silica - raw_silica.mean()) / raw_silica.std()
    raw_iron = np.round(65.0 + 1.1 * (IRON_SILICA_CORR * zs + np.sqrt(1 - IRON_SILICA_CORR ** 2) * rng.normal(size=n)), 2)
    feed_iron, feed_silica = _feed(rng, n, 55.2, 1.5, 45.0, 66.0), _feed(rng, n, 16.98, 2.0, 8.0, 30.0)
    fixed = {name: _runs(rng, n, (10, 60), (1, 20)) for name in FIXED_SENSORS}
    plants = _plan_plants(rng, n, usable)
    silica, iron, state, ramp = _lab_series(raw_silica, raw_iron, observed, plants)

    # the rows, for every hour of the file; the noise of the whole grid is drawn so that a cut file is the prefix of the full one
    keep = observed & (t < weeks * HOURS_PER_WEEK) if weeks else observed
    all_hours = np.flatnonzero(observed)
    all_rows = rows_of[all_hours]
    noise = rng.normal(size=(int(all_rows.sum()), len(SENSORS)))
    obs = np.flatnonzero(keep)
    reps = rows_of[obs]
    total = int(reps.sum())
    hour_of_row = np.repeat(obs, reps)
    in_hour = np.arange(total) - np.repeat(np.cumsum(reps) - reps, reps)
    shape = np.array(_SENSOR_SHAPE)
    levels = (shape[:, 0:1] + shape[:, 1:2] * z)[:, hour_of_row].T
    noisy = np.ones((total, len(SENSORS)))
    for name in FIXED_SENSORS:
        noisy[:, SENSORS.index(name)] = ~fixed[name][hour_of_row]
    sensors = levels + noise[:total] * shape[:, 2] * noisy
    sensors = np.column_stack([np.round(sensors[:, k], int(shape[k, 3])) for k in range(len(SENSORS))])
    nxt = np.minimum(hour_of_row + 1, n - 1)
    ramping = ramp[hour_of_row]
    fraction = in_hour / rows_of[hour_of_row]
    silica_rows = np.round(np.where(ramping, silica[hour_of_row] + (silica[nxt] - silica[hour_of_row]) * fraction, silica[hour_of_row]), 6)
    iron_rows = np.round(np.where(ramping, iron[hour_of_row] + (iron[nxt] - iron[hour_of_row]) * fraction, iron[hour_of_row]), 6)

    frame = pd.DataFrame({
        "hour": np.asarray(grid.strftime("%Y-%m-%d %H:%M:%S"))[hour_of_row], "feed_iron": feed_iron[hour_of_row], "feed_silica": feed_silica[hour_of_row],
        **{name: sensors[:, k] for k, name in enumerate(SENSORS)}, "iron_conc": _fmt(iron_rows), "silica": _fmt(silica_rows),
    })
    content = _header(rows_per_hour, seed, signal) + _csv_body(frame).encode("utf-8")
    path.write_bytes(content)

    # the truth
    index = pd.DatetimeIndex(grid[obs], name="hour")
    table = pd.DataFrame({
        "rows": reps, "partial": reps < rows_per_hour, "silica": np.round(silica[obs], 6), "iron_conc": np.round(iron[obs], 6),
        "is_ramp": ramp[obs], "state": state[obs], "feed_silica": feed_silica[obs], "feed_iron": feed_iron[obs],
    }, index=index)
    for name in ("feed_silica", "feed_iron"):
        values, ages, start = table[name].to_numpy(), [], 0
        for i in range(len(table)):
            if i and values[i] != values[i - 1]:
                start = i
            ages.append(float((index[i] - index[start]) / timedelta(hours=1)))
        table[f"{name}_age_h"] = ages
    counts = {
        "rows": total, "hours": len(table), "grid_hours": int((index[-1] - index[0]) / timedelta(hours=1)) + 1,
        "partial_hours": int(table["partial"].sum()), "below_min_rows_hours": int((table["rows"] < max(1, rows_per_hour // 2)).sum()),
        "interpolated": int((table["state"] == "interpolated").sum()), "held": int((table["state"] == "held").sum()),
        "fresh": int((table["state"] == "fresh").sum()), "ramp_hours": int(table["is_ramp"].sum()),
        "single_ramp_hours": sum(1 for p in plants if p.kind == "single" and keep[p.start]),
        "feed_changes_within_hour": 0,
        "feed_silica_unchanged_24h_hours": int((table["feed_silica_age_h"] >= 24).sum()),
        "feed_iron_unchanged_24h_hours": int((table["feed_iron_age_h"] >= 24).sum()),
        "fixed_sensor_hours": {name: int(fixed[name][obs].sum()) for name in FIXED_SENSORS if fixed[name][obs].any()},
    }
    counts["missing_hours"] = counts["grid_hours"] - counts["hours"]
    return FixtureTruth(
        path=path, sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content), n_rows=total, rows_per_hour=rows_per_hour, seed=seed,
        signal=signal, weeks=weeks, signal_sensor=SIGNAL_SENSOR if signal == "sensor_signal" else None,
        signal_sign=1 if signal == "sensor_signal" else 0, signal_beta=SIGNAL_BETA if signal == "sensor_signal" else 0.0,
        iron_silica_corr=float(np.corrcoef(table["silica"], table["iron_conc"])[0, 1]), hours=table, counts=counts,
    )


# --- the malformed variants ---------------------------------------------------------------------------------------------------


def make_malformed(base: Path | str, kind: str, out: Path | str, *, max_bytes: int | None = None) -> Path:
    """Write at `out` the file `base` damaged in one documented way and return `out`; ``MALFORMED_RULE[kind]`` is the rule it trips.

    A variant changes one line, except ``missing_attribute`` and ``extra_attribute`` (one header line less or more), ``hour_over_limit`` (one
    row more) and ``oversize`` (comment lines before ``@RELATION`` until the file is larger than `max_bytes`, 1 MiB by default, and still
    valid). The data-row variants change the data line number ``MALFORMED_ROW`` (the first hour's), ``unsorted`` a row of the third hour.
    """
    base, out = Path(base), Path(out)
    if kind not in MALFORMED_RULE:
        raise ValueError(f"kind: expected one of {MALFORMED_KINDS}, got {kind!r}")
    if out.resolve() == base.resolve():
        raise ValueError("out: a variant is never written over its base")
    lines = base.read_bytes().split(b"\n")
    at = lines.index(b"@DATA") + 1
    row_fields = lambda i: next(csv.reader([lines[i].decode("utf-8")], quotechar="'"))   # noqa: E731
    as_line = lambda fields: ",".join(f"'{f}'" for f in fields).encode("utf-8")           # noqa: E731
    i = at + MALFORMED_ROW
    comment = next(k for k, line in enumerate(lines) if line.startswith(b"% "))
    attribute = lambda name: next(k for k, line in enumerate(lines) if name.encode() in line and line.startswith(b"@ATTRIBUTE"))   # noqa: E731

    def change(position: int, text: str) -> None:
        fields = row_fields(i)
        fields[position] = text
        lines[i] = as_line(fields)

    if kind == "wrong_hash":
        change(3, row_fields(i)[3] + "1")
    elif kind == "bad_relation":
        lines[next(k for k, line in enumerate(lines) if line.startswith(b"@RELATION"))] = b"@RELATION Some-Other-Relation"
    elif kind == "missing_attribute":
        del lines[max(k for k, line in enumerate(lines) if line.startswith(b"@ATTRIBUTE"))]
    elif kind == "extra_attribute":
        lines.insert(max(k for k, line in enumerate(lines) if line.startswith(b"@ATTRIBUTE")) + 1, b"@ATTRIBUTE Extra_Column STRING")
    elif kind == "renamed_attribute":
        lines[attribute("Amina_Flow")] = b"@ATTRIBUTE Amina_Flux STRING"
    elif kind == "numeric_attribute":
        lines[attribute("Starch_Flow")] = b"@ATTRIBUTE Starch_Flow NUMERIC"
    elif kind == "field_count":
        lines[i] = as_line(row_fields(i)[:-1])
    elif kind == "empty_field":
        change(6, "")
    elif kind == "bad_date":
        change(0, "10/03/2017 01:00")
    elif kind == "minute_not_zero":
        change(0, row_fields(i)[0].replace(":00:00", ":20:00"))
    elif kind == "dot_decimal":
        change(3, row_fields(i)[3].replace(",", "."))
    elif kind == "text_number":
        change(3, "abc")
    elif kind == "unsorted":
        dates = [row_fields(k)[0] for k in range(at, len(lines) - 1)]
        distinct = sorted(set(dates))
        target = at + dates.index(distinct[2]) + 1
        fields = row_fields(target)
        fields[0] = distinct[1]
        lines[target] = as_line(fields)
    elif kind == "hour_over_limit":
        dates = [row_fields(k)[0] for k in range(at, len(lines) - 1)]
        second = sorted(set(dates))[1]
        last = at + max(k for k, d in enumerate(dates) if d == second)
        lines.insert(last + 1, lines[last])
    elif kind == "long_line":
        lines[comment] = b"% " + b"x" * 5000
    elif kind == "nul_byte":
        lines[comment] = b"% header with a null byte \x00 inside"
    elif kind == "bad_utf8":
        lines[comment] = b"% header with a byte that is not UTF-8: \xff\xfe"
    elif kind == "oversize":
        limit = OVERSIZE_DEFAULT_BYTES if max_bytes is None else max_bytes
        padding = b"% " + b"padding " * 100
        size = sum(len(line) + 1 for line in lines) - 1
        extra = max(0, (limit + 1 - size + len(padding)) // (len(padding) + 1))
        lines[comment:comment] = [padding] * extra
    out.write_bytes(b"\n".join(lines))
    return out
