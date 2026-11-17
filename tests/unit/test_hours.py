"""The hours of the source (U04; D04, D05, D08; AC04): the aggregates of an hour, the state of each analysis and the age of the feed."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from flotsilica.hours import aggregate_rows, feed_age_hours, lab_states
from flotsilica.schema import AGGREGATE_COLUMNS, SENSORS
from tests.fixtures import hand_cases as hc

T0 = datetime(2017, 5, 1)


def frame(values, ramp, start=0, step=1):
    hours = [T0 + timedelta(hours=start + step * k) for k in range(len(values))]
    first = pd.DataFrame({"hour": hours, "silica_pct": values})
    return first, pd.Series(ramp, index=pd.DatetimeIndex(hours, name="hour"))


# --- AC04: the state of each hour -------------------------------------------------------------------------------------


def test_interpolated_and_held_hours_are_marked_and_never_fresh(canonical, fixture_truth):
    case = hc.freshness_case()
    states = lab_states(case.first_rows, case.is_ramp)
    assert list(states) == case.expected_states and states.index.equals(case.first_rows.index)
    assert set(states) == {"fresh", "interpolated", "held"}
    # an analysis that is a ramp start is fresh; the hours inside the stretch and the repetitions are not; only fresh hours are analyses
    assert states.iloc[2] == "fresh" and states.iloc[3] == states.iloc[4] == "interpolated" and states.iloc[5] == "fresh"
    assert list(case.first_rows["silica_pct"][states == "fresh"]) == [2.50, 2.61, 2.40, 2.10, 2.35, 2.20, 2.45]
    assert not (states[case.is_ramp.to_numpy() & (np.arange(12) > 2) & (np.arange(12) < 5)] == "fresh").any()
    # the synthetic fixture: every planted hour is marked as the truth says (AC04), and no interpolated or held hour is fresh
    assert list(canonical.hours["lab_state"]) == list(fixture_truth.hours["state"])
    assert list(canonical.hours["hour"]) == list(fixture_truth.hours.index)
    assert (canonical.hours["lab_state"] == "fresh").sum() == fixture_truth.counts["fresh"]
    assert not set(canonical.hours.loc[canonical.hours["lab_state"] != "fresh", "hour"]) & set(
        fixture_truth.hours.index[fixture_truth.hours["state"] == "fresh"])


def test_a_lab_state_depends_only_on_its_hour_and_the_previous_one(canonical):
    hours = canonical.hours
    first = hours[["hour", "silica_pct"]].reset_index(drop=True)
    ramp = pd.Series(canonical.read.groupby("hour")["silica_pct"].nunique().gt(1))
    full = lab_states(first, ramp)
    assert (full == "interpolated").sum() > 100 and (full == "held").sum() > 100
    rng = np.random.default_rng(0)
    for k in rng.choice(np.arange(1, len(first)), size=60, replace=False):
        pair = first.iloc[k - 1:k + 1].reset_index(drop=True)
        assert lab_states(pair, ramp).iloc[-1] == full.iloc[k], k              # the hour and the one before it
        cut = first.iloc[:k + 1].reset_index(drop=True)
        assert list(lab_states(cut, ramp)) == list(full.iloc[:k + 1]), k       # nothing after the hour is looked at
    altered = first.copy()
    altered.loc[altered.index > 1500, "silica_pct"] += 7.0
    assert list(lab_states(altered, ramp).iloc[:1500]) == list(full.iloc[:1500])


def test_the_first_hour_after_a_gap_is_neither_held_nor_interpolated_and_a_ramp_before_a_gap_does_not_reach_it():
    first, ramp = frame([2.0, 2.0, 2.0, 2.0, 2.0], [False, True, True, True, False], step=1)
    first.loc[3:, "hour"] += timedelta(hours=10)         # a gap of 10 hours before hour index 3
    ramp.index = pd.DatetimeIndex(first["hour"], name="hour")
    assert list(lab_states(first, ramp)) == ["fresh", "held", "interpolated", "fresh", "held"]
    # index 3 has a ramp hour before it (index 2) but not an adjacent one, and an equal value that is not the previous hour's: it is fresh
    first, ramp = frame([1.0, 1.0], [False, False], step=5)
    assert list(lab_states(first, ramp)) == ["fresh", "fresh"]


def test_the_state_of_a_ramp_start_the_end_of_a_stretch_and_a_single_ramp():
    first, ramp = frame([3.0, 2.0, 1.0, 0.5, 0.5, 4.0, 3.5], [True, True, True, False, False, True, False])
    assert list(lab_states(first, ramp)) == ["fresh", "interpolated", "interpolated", "fresh", "held", "fresh", "fresh"]


def test_lab_states_refuses_hours_that_are_repeated_or_out_of_order_and_a_ramp_flag_that_misses_an_hour():
    first, ramp = frame([1.0, 2.0, 3.0], [False, False, False])
    shuffled = first.iloc[[1, 0, 2]].reset_index(drop=True)
    with pytest.raises(ValueError, match="hour"):
        lab_states(shuffled, ramp)
    repeated = pd.concat([first, first.iloc[[2]]]).reset_index(drop=True)
    with pytest.raises(ValueError, match="hour"):
        lab_states(repeated, ramp)
    with pytest.raises(ValueError, match="is_ramp"):
        lab_states(first, ramp.iloc[:2])


# --- the aggregates of an hour --------------------------------------------------------------------------------------------


def rows_frame(per_hour: dict[datetime, list[float]]) -> pd.DataFrame:
    records = []
    for hour, values in per_hour.items():
        for k, value in enumerate(values):
            records.append({"hour": hour, **{sensor: value * (j + 1) for j, sensor in enumerate(SENSORS)}, "silica_pct": 9.0 + k})
    return pd.DataFrame(records)


def test_aggregate_rows_gives_mean_sample_std_and_last_row_in_file_order():
    rows = rows_frame({T0 + timedelta(hours=1): [5.0, 1.0], T0: [1.0, 4.0, 2.0], T0 + timedelta(hours=2): [7.0]})
    rows = rows.iloc[[2, 3, 4, 0, 1, 5]].reset_index(drop=True)        # the hours in file order; the last row of 00:00 is 2.0, not its maximum
    out = aggregate_rows(rows)
    assert list(out.columns) == ["hour", "rows", *AGGREGATE_COLUMNS]
    assert list(out["hour"]) == [T0, T0 + timedelta(hours=1), T0 + timedelta(hours=2)] and list(out["rows"]) == [3, 2, 1]
    first, second, third = out.iloc[0], out.iloc[1], out.iloc[2]
    assert first["starch_flow_mean"] == pytest.approx(7 / 3) and first["starch_flow_std"] == pytest.approx(math.sqrt(((1 - 7 / 3) ** 2 + (2 - 7 / 3) ** 2 + (4 - 7 / 3) ** 2) / 2))
    assert first["starch_flow_last"] == 2.0 and first["level_07_last"] == 2.0 * 19
    assert second["amina_flow_mean"] == pytest.approx(3.0 * 2) and second["amina_flow_std"] == pytest.approx(math.sqrt(8.0) * 2)   # ddof = 1
    assert second["amina_flow_last"] == 1.0 * 2
    assert third["starch_flow_mean"] == 7.0 and math.isnan(third["starch_flow_std"]) and third["starch_flow_last"] == 7.0   # one row: no deviation
    assert "silica_pct" not in out.columns


def test_aggregate_rows_leaves_its_input_alone():
    rows = rows_frame({T0: [1.0, 2.0]})
    before = rows.copy()
    aggregate_rows(rows)
    pd.testing.assert_frame_equal(rows, before)


# --- the age of the feed ----------------------------------------------------------------------------------------------------


def test_feed_age_counts_clock_hours_since_the_last_change_across_a_gap():
    hours = [T0 + timedelta(hours=h) for h in (0, 1, 2, 3, 4, 10)]
    first = pd.DataFrame({"hour": hours, "feed_silica_pct": [10.0, 10.0, 10.0, 12.0, 12.0, 12.0], "feed_iron_pct": [5.0, 6.0, 6.0, 6.0, 6.0, 7.0]})
    ages = feed_age_hours(first)
    assert list(ages.columns) == ["feed_silica_age_h", "feed_iron_age_h"] and ages.index.equals(first.index)
    assert list(ages["feed_silica_age_h"]) == [0.0, 1.0, 2.0, 0.0, 1.0, 7.0]    # the value did not change across the gap: the age goes on
    assert list(ages["feed_iron_age_h"]) == [0.0, 0.0, 1.0, 2.0, 3.0, 0.0]
    assert feed_age_hours(first.iloc[:0]).shape == (0, 2)


def test_the_feed_ages_of_the_fixture_are_those_of_its_truth(canonical, fixture_truth):
    for name in ("feed_silica", "feed_iron"):
        assert list(canonical.hours[f"{name}_age_h"]) == list(fixture_truth.hours[f"{name}_age_h"])
        assert list(canonical.hours[f"{name}_pct"]) == pytest.approx(list(fixture_truth.hours[name]))


def test_an_hour_with_two_distinct_values_in_its_rows_is_a_ramp_hour_for_the_marks(quick_cfg):
    """canonical() decides which hours are ramps (more than one distinct silica value among the rows of the hour) and drops the flag."""
    from flotsilica.ingest import canonical as build

    records = []
    for k, values in enumerate(([1.0, 1.0, 1.0], [2.0, 2.0, 3.0], [3.0, 3.5, 4.0], [4.0, 4.0, 4.0])):
        for j, silica in enumerate(values):
            records.append({"row_id": len(records) + 1, "hour": T0 + timedelta(hours=k), "row_in_hour": j + 1, "feed_iron_pct": 55.0, "feed_silica_pct": 16.0,
                            **{sensor: 1.0 for sensor in SENSORS}, "iron_conc_pct": 66.0, "silica_pct": silica})
    rows, hours = build(pd.DataFrame(records), quick_cfg)
    assert list(hours["lab_state"]) == ["fresh", "fresh", "interpolated", "fresh"] and list(hours["silica_pct"]) == [1.0, 2.0, 3.0, 4.0]
    assert "is_ramp" not in hours.columns and "is_ramp" not in rows.columns and len(rows) == 12


def test_an_hour_whose_feed_changes_between_its_rows_is_flagged_for_v24_and_keeps_its_first_row(quick_cfg, canonical):
    """V24 is judged on the delivered hours, whose rows carry no laboratory column (V15), so ``canonical`` records, per hour, that the feed
    (either of its two values) has more than one distinct value among the rows; the hour keeps the value of its first row (D04)."""
    from flotsilica.ingest import canonical as build

    records = []
    plan = {0: ([55.0, 55.0, 55.0], [16.0, 16.0, 16.0]), 1: ([55.0, 55.5, 55.5], [16.0, 16.0, 16.0]),
            2: ([55.0, 55.0, 55.0], [16.0, 16.5, 16.0]), 3: ([55.5, 55.5, 55.5], [16.0, 16.0, 16.0])}
    for k, (iron, silica) in plan.items():
        for j in range(3):
            records.append({"row_id": len(records) + 1, "hour": T0 + timedelta(hours=k), "row_in_hour": j + 1, "feed_iron_pct": iron[j], "feed_silica_pct": silica[j],
                            **{sensor: 1.0 for sensor in SENSORS}, "iron_conc_pct": 66.0, "silica_pct": 2.0 + k})
    _rows, hours = build(pd.DataFrame(records), quick_cfg)
    assert list(hours["feed_changes_in_hour"]) == [False, True, True, False]
    assert list(hours["feed_iron_pct"]) == [55.0, 55.0, 55.0, 55.5] and list(hours["feed_silica_pct"]) == [16.0] * 4
    assert hours["feed_changes_in_hour"].dtype == bool
    assert not canonical.hours["feed_changes_in_hour"].any()   # the fixture's feed never changes within an hour (its truth: 0)
