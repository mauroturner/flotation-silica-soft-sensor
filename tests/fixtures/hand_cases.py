"""Small frames with the result written by hand (plan, section 24): the freshness of twelve hours, the persistence and the means, the
features of an instant with the laboratory's arrival, the conformal quantile, the metrics of twelve hours, the resampling of whole days
and the tracking join. The expected values are numbers written here, not computed by the code that will be tested; ``test_hand_cases.py``
checks each one against a separate piece of arithmetic so that a slip in this file is found before it is trusted.

The hours are those of 2017-05-01 (inside the training block). The laboratory latency of the cases is two hours (D06): the analysis of
the sample hour ``k`` arrives at ``k + 2``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from flotsilica.schema import AGGREGATE_COLUMNS

DAY = datetime(2017, 5, 1)
LATENCY_HOURS = 2


def hour(k: int) -> datetime:
    """The hour number `k` of the cases: 2017-05-01 00:00 plus `k` hours."""
    return DAY + timedelta(hours=k)


# --- freshness (D05): twelve hours with an interpolated stretch and repetitions ---------------------------------------------


@dataclass(frozen=True)
class FreshnessCase:
    first_rows: pd.DataFrame          # hour, silica_pct: the first row of each hour
    is_ramp: pd.Series                # indexed by hour: the silica changes within the hour
    expected_states: list[str]        # fresh, interpolated or held, in the order of the hours


def freshness_case() -> FreshnessCase:
    """Hours 0-11. Hour 2 starts a ramp that ends at hour 5's analysis (2.40, 2.30, 2.20, then 2.10): hour 2 is fresh (the start), hours 3 and
    4 are interpolated and hour 5 is fresh again. Hour 6 repeats hour 5 and hours 8 and 9 repeat hour 7: held. Hour 11 does not repeat."""
    values = [2.50, 2.61, 2.40, 2.30, 2.20, 2.10, 2.10, 2.35, 2.35, 2.35, 2.20, 2.45]
    ramp = [False, False, True, True, True, False, False, False, False, False, False, False]
    states = ["fresh", "fresh", "fresh", "interpolated", "interpolated", "fresh", "held", "fresh", "held", "held", "fresh", "fresh"]
    hours = [hour(k) for k in range(12)]
    return FreshnessCase(pd.DataFrame({"hour": hours, "silica_pct": values}), pd.Series(ramp, index=pd.DatetimeIndex(hours, name="hour")), states)


def fresh_analyses() -> pd.DataFrame:
    """The fresh analyses of ``freshness_case`` as the laboratory history has them: ``sample_hour``, ``silica_pct`` and ``available_at``."""
    case = freshness_case()
    fresh = case.first_rows[[state == "fresh" for state in case.expected_states]].reset_index(drop=True)
    return pd.DataFrame({
        "sample_hour": fresh["hour"], "silica_pct": fresh["silica_pct"], "available_at": fresh["hour"] + timedelta(hours=LATENCY_HOURS),
    })


def case_hours(rows: int = 12) -> pd.DataFrame:
    """The twelve hours of the freshness case (the canonical hours of a warehouse: ``hour``, ``rows``, ``lab_state``, ``silica_pct``, the feed and its ages and the 57 aggregates) with their states and, per hour k, a value that says which hour it came from: the aggregate j
    is ``100 * j + k``, the feed of silica ``16 + k / 10`` and of iron ``55 + k / 10``, their ages ``k`` and ``k + 0.5``."""
    case = freshness_case()
    hours = pd.DataFrame({
        "hour": case.first_rows["hour"], "rows": rows, "lab_state": case.expected_states, "silica_pct": case.first_rows["silica_pct"],
        "feed_silica_pct": [16 + k / 10 for k in range(12)], "feed_iron_pct": [55 + k / 10 for k in range(12)],
        "feed_silica_age_h": [float(k) for k in range(12)], "feed_iron_age_h": [k + 0.5 for k in range(12)],
    })
    for j, column in enumerate(AGGREGATE_COLUMNS):
        hours[column] = [100.0 * j + k for k in range(12)]
    return hours


# --- persistence, the means and the lab features of an instant (D07, D12, D13) --------------------------------------------


@dataclass(frozen=True)
class InstantExpectation:
    last: tuple[float, float, float]      # lab_last1, lab_last2, lab_last3: the three latest fresh analyses that have arrived
    mean3: float                          # B2 with k = 3: their mean
    age_h: float                          # lab_age_h: hours between the sample of the latest and issue_at - latency
    known: int                            # how many fresh analyses have arrived by the instant


# At the instant t = the close of hour t - 1, the analyses that have arrived are those with available_at <= t, that is, sample hours <= t - 2
PERSISTENCE_AT: dict[datetime, InstantExpectation] = {
    # 10:00: hours 0, 1, 2, 5 and 7 (hours 3 and 4 are interpolated, 6 is held): 2.50, 2.61, 2.40, 2.10, 2.35. The persistence of H0 for hour 9
    # is 2.35 (hour 7), not hour 8, which is held
    hour(10): InstantExpectation(last=(2.35, 2.10, 2.40), mean3=(2.35 + 2.10 + 2.40) / 3, age_h=1.0, known=5),
    # 12:00: hour 10 has arrived too: 2.20
    hour(12): InstantExpectation(last=(2.20, 2.35, 2.10), mean3=(2.20 + 2.35 + 2.10) / 3, age_h=0.0, known=6),
}
# B0 is the mean of every fresh analysis of the training block (here the seven fresh hours)
TRAINING_MEAN = (2.50 + 2.61 + 2.40 + 2.10 + 2.35 + 2.20 + 2.45) / 7


# --- the conformal half-width (D15): the quantile of order ceil((n + 1) * coverage) / n, "higher" --------------------------


@dataclass(frozen=True)
class ConformalCase:
    residuals: tuple[float, ...]     # absolute residuals, in no order
    coverage: float
    rank: int                        # the position, counted from the smallest, of the half-width
    half_width: float


CONFORMAL_CASES = (
    ConformalCase((0.5, 0.1, 0.9, 0.3, 0.7, 0.2, 0.8, 0.4, 0.6), 0.8, 8, 0.8),                     # n = 9: ceil(10 * 0.8) = 8
    ConformalCase((0.6, 1.0, 0.2, 0.8, 0.4, 0.1, 0.9, 0.3, 0.7, 0.5), 0.8, 9, 0.9),                 # n = 10: ceil(11 * 0.8) = ceil(8.8) = 9
    ConformalCase((0.3, 0.1, 0.4, 0.2), 0.5, 3, 0.3),                                                # n = 4: ceil(5 * 0.5) = ceil(2.5) = 3
)


# --- the metrics of twelve hours, with the persistence and an 80 % range of half-width 0.25 ---------------------------


@dataclass(frozen=True)
class MetricsCase:
    hours: tuple[datetime, ...]
    actual: tuple[float, ...]
    model: tuple[float, ...]
    persistence: tuple[float, ...]
    half_width: float
    day_of: tuple[int, ...]           # which of three days of four hours each every hour belongs to
    mae_model: float
    mae_persistence: float
    bias_model: float
    coverage: float
    mae_difference: float             # model minus persistence
    day_pick: tuple[int, ...]         # one resample of days: day 0 twice and day 2 once
    day_pick_difference: float        # the difference of MAE with the days of day_pick, as a quotient of sums


def metrics_case() -> MetricsCase:
    """Errors of the model: 0.1, -0.2, 0.1, 0.2, 0.0, -0.1, -0.1, 0.3, 0.0, 0.3, 0.0, -0.2 (sum of absolute values 1.6, sum 0.4); of the
    persistence: 0.1, -0.2, -0.2, 0.4, 0.2, -0.3, -0.4, 0.2, 0.3, 0.1, -0.3, -0.4 (sum of absolute values 3.1). Ten of the twelve errors
    of the model are within 0.25. Per day, the sums of absolute errors are 0.6, 0.5, 0.5 (model) and 0.9, 1.1, 1.1 (persistence); with
    days 0, 0, 2 the model has 1.7 and the persistence 2.9 over 12 hours."""
    return MetricsCase(
        hours=tuple(hour(k) for k in range(12)),
        actual=(2.0, 2.2, 2.4, 2.0, 1.8, 2.1, 2.5, 2.3, 2.0, 1.9, 2.2, 2.6),
        model=(2.1, 2.0, 2.5, 2.2, 1.8, 2.0, 2.4, 2.6, 2.0, 2.2, 2.2, 2.4),
        persistence=(2.1, 2.0, 2.2, 2.4, 2.0, 1.8, 2.1, 2.5, 2.3, 2.0, 1.9, 2.2),
        half_width=0.25,
        day_of=(0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2),
        mae_model=1.6 / 12, mae_persistence=3.1 / 12, bias_model=0.4 / 12, coverage=10 / 12, mae_difference=1.6 / 12 - 3.1 / 12,
        day_pick=(0, 0, 2), day_pick_difference=(1.7 - 2.9) / 12,
    )


# --- tracking (D22): an estimate is joined with its analysis only once the analysis has arrived ---------------------------


@dataclass(frozen=True)
class TrackingCase:
    estimates: pd.DataFrame           # target_hour, horizon, estimate
    analyses: pd.DataFrame            # sample_hour, silica_pct, available_at (latency two hours)
    as_of: dict[datetime, int]        # an as_of instant -> how many of the three estimates have their analysis joined


def tracking_case() -> TrackingCase:
    """Three H0 estimates for hours 10, 11 and 12 whose analyses arrive at 12:00, 13:00 and 14:00 (the arrival is inclusive)."""
    estimates = pd.DataFrame({"target_hour": [hour(10), hour(11), hour(12)], "horizon": [0, 0, 0], "estimate": [2.1, 2.3, 2.2]})
    analyses = pd.DataFrame({
        "sample_hour": [hour(10), hour(11), hour(12)], "silica_pct": [2.0, 2.2, 2.4],
        "available_at": [hour(12), hour(13), hour(14)],
    })
    return TrackingCase(estimates, analyses, {hour(11): 0, hour(12): 1, hour(12) + timedelta(minutes=30): 1, hour(13): 2, hour(14): 3, hour(20): 3})
