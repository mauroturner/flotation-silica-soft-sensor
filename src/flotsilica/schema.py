"""The contract of the source and of the canonical tables: the one place that names them (plan, section 6).

``ATTRIBUTES`` maps the 24 attributes of the ARFF, in file order, to the names the code uses; ``SENSORS`` are the 19 process variables
sampled every 20 s; ``LAB_COLUMNS`` the four laboratory values that are hourly (the real file repeats them on every row of an hour, and in a
ramp hour they move: only the first row of an hour is an analysis, D04). ``FEATURE_COLUMNS`` are the 67 columns a model matrix may take
(section 10; D12); ``FORBIDDEN_COLUMNS`` and ``TARGET_COLUMNS`` are what must never reach it. The lists never share a name.
"""

from __future__ import annotations

import re

import pandas as pd
import pyarrow as pa

# the 24 attributes in file order -> the name the code uses (``date`` is the hour of the row)
ATTRIBUTES: dict[str, str] = {
    "date": "hour",
    "%_Iron_Feed": "feed_iron_pct",
    "%_Silica_Feed": "feed_silica_pct",
    "Starch_Flow": "starch_flow",
    "Amina_Flow": "amina_flow",
    "Ore_Pulp_Flow": "ore_pulp_flow",
    "Ore_Pulp_pH": "ore_pulp_ph",
    "Ore_Pulp_Density": "ore_pulp_density",
    **{f"Flotation_Column_0{k}_Air_Flow": f"air_flow_0{k}" for k in range(1, 8)},
    **{f"Flotation_Column_0{k}_Level": f"level_0{k}" for k in range(1, 8)},
    "%_Iron_Concentrate": "iron_conc_pct",
    "%_Silica_Concentrate": "silica_pct",
}
COLUMNS: tuple[str, ...] = tuple(ATTRIBUTES.values())
LAB_COLUMNS: tuple[str, ...] = ("feed_iron_pct", "feed_silica_pct", "iron_conc_pct", "silica_pct")
SENSORS: tuple[str, ...] = tuple(name for name in COLUMNS if name != "hour" and name not in LAB_COLUMNS)

# the lab columns of a row, as the reader returns them: the first column and the numbers
NUMERIC_COLUMNS: tuple[str, ...] = tuple(name for name in COLUMNS if name != "hour")

# the columns of the aggregates of an hour: mean, standard deviation (ddof = 1) and last value of each sensor, sensor by sensor
AGGREGATE_COLUMNS: tuple[str, ...] = tuple(f"{sensor}_{statistic}" for sensor in SENSORS for statistic in ("mean", "std", "last"))
LAB_FEATURE_COLUMNS: tuple[str, ...] = ("lab_last1", "lab_last2", "lab_last3", "lab_mean6", "lab_mean24", "lab_age_h")
FEED_FEATURE_COLUMNS: tuple[str, ...] = ("feed_silica_pct", "feed_iron_pct", "feed_silica_age_h", "feed_iron_age_h")
FEATURE_SETS: dict[str, tuple[str, ...]] = {
    "fS": AGGREGATE_COLUMNS,
    "fL": LAB_FEATURE_COLUMNS,
    "fSL": AGGREGATE_COLUMNS + LAB_FEATURE_COLUMNS,
    "fSLF": AGGREGATE_COLUMNS + LAB_FEATURE_COLUMNS + FEED_FEATURE_COLUMNS,
}
FEATURE_COLUMNS: tuple[str, ...] = FEATURE_SETS["fSLF"]

# What looks at the target hour, or is the target: never a feature (D09, AC10). ``<lab>_row_<n>`` is a pattern: any laboratory value of a row
# that is not the first one.
FORBIDDEN_COLUMNS: tuple[str, ...] = (
    "iron_conc_pct", "row_id", "row_in_hour", "lab_state", "is_ramp", "hour", "hour_key", "month", "weekday", "hour_of_day", "block",
)
FORBIDDEN_PATTERN = re.compile(r"(?:feed_iron_pct|feed_silica_pct|iron_conc_pct|silica_pct)_row_\d+")
TARGET_COLUMNS: tuple[str, ...] = ("silica_pct", "actual", "abs_error")

# Arrow schemas of the two canonical tables (data/interim/source_rows.parquet and source_hours.parquet)
SOURCE_ROWS_SCHEMA = pa.schema([
    ("row_id", pa.int64()), ("hour", pa.timestamp("ns")), ("row_in_hour", pa.int64()), *[(name, pa.float64()) for name in SENSORS],
])
SOURCE_HOURS_SCHEMA = pa.schema([
    ("hour", pa.timestamp("ns")), ("hour_key", pa.int64()), ("rows", pa.int64()), ("is_partial", pa.bool_()),
    ("silica_pct", pa.float64()), ("iron_conc_pct", pa.float64()), ("feed_silica_pct", pa.float64()), ("feed_iron_pct", pa.float64()),
    ("lab_state", pa.string()), ("feed_silica_age_h", pa.float64()), ("feed_iron_age_h", pa.float64()), ("feed_changes_in_hour", pa.bool_()),
    *[(name, pa.float64()) for name in AGGREGATE_COLUMNS],
])
LAB_STATES: tuple[str, ...] = ("fresh", "interpolated", "held")


def is_forbidden(name: str) -> bool:
    """Whether a column name is one of ``FORBIDDEN_COLUMNS`` or a laboratory value of a row (``silica_pct_row_7``)."""
    return name in FORBIDDEN_COLUMNS or FORBIDDEN_PATTERN.fullmatch(name) is not None


class SourceError(RuntimeError):
    """A rule of the source (V01 to V07) failed; the exit code of the command line is 3. ``problems`` says what, one dict per failing item
    (a rule, a line number, a column: never a row)."""

    EXIT_CODE = 3

    def __init__(self, rule_id: str, message: str, problems: list[dict] | None = None) -> None:
        super().__init__(f"{rule_id}: {message}")
        self.rule_id = rule_id
        self.problems = problems if problems is not None else []


def hour_key(hours: pd.Series) -> pd.Series:
    """``YYYYMMDDHH`` as int64 of a datetime series."""
    return hours.dt.year.astype("int64") * 1_000_000 + hours.dt.month.astype("int64") * 10_000 + hours.dt.day.astype("int64") * 100 + hours.dt.hour.astype("int64")
