"""The features of an instant (U07; RF09, D12; AC10): what is known when an hour closes, the hand case with the laboratory's arrival, the
columns of each set and the guard that keeps a forbidden column out of the matrix."""

from __future__ import annotations

import ast
import dataclasses
import math
import re
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from flotsilica import features
from flotsilica.features import HourTables, IssueInputs, LeakageError, _known_arrays, build_matrix, design, feature_row, lab_known_at, missing_inputs
from flotsilica.schema import (
    AGGREGATE_COLUMNS,
    FEATURE_COLUMNS,
    FEATURE_SETS,
    FORBIDDEN_COLUMNS,
    LAB_FEATURE_COLUMNS,
    TARGET_COLUMNS,
)
from tests.fixtures import hand_cases as hc

HOUR = timedelta(hours=1)


@pytest.fixture(scope="module")
def view(quick_cfg):
    """The quick configuration with a history of one analysis enough (the hand case has twelve hours)."""
    return dataclasses.replace(quick_cfg, features=dataclasses.replace(quick_cfg.features, min_fresh_history=1))


@pytest.fixture(scope="module")
def tables(view) -> HourTables:
    return HourTables.from_hours(hc.case_hours(), view)


# --- the hand case: what the plant knows when an hour closes (D06, D12) ------------------------------------------------------


def test_the_features_of_an_instant_are_the_readings_of_the_hour_that_closed_and_the_analyses_that_arrived(tables, view):
    for issue_at, expected in hc.PERSISTENCE_AT.items():
        k = int((issue_at - hc.hour(0)) / HOUR)          # the hour that closed is k - 1
        row = feature_row(tables.inputs(issue_at, view), view)
        assert list(row.index) == list(FEATURE_COLUMNS) and len(row) == 67
        assert [row[f"{sensor}"] for sensor in AGGREGATE_COLUMNS] == [100.0 * j + (k - 1) for j in range(len(AGGREGATE_COLUMNS))]
        assert (row["lab_last1"], row["lab_last2"], row["lab_last3"]) == pytest.approx(expected.last)
        assert row["lab_age_h"] == expected.age_h
        assert math.isnan(row["lab_mean24"]), "a mean of 24 needs 24 analyses"
        if expected.known >= 6:
            fresh = hc.fresh_analyses()
            known = fresh[fresh["available_at"] <= issue_at]["silica_pct"].tolist()
            assert row["lab_mean6"] == pytest.approx(float(np.mean(known[-6:])))
        else:
            assert math.isnan(row["lab_mean6"])
        # the feed is the one of the latest hour whose analysis has arrived (any state: the feed is not the silica), here hour k - 2
        assert (row["feed_silica_pct"], row["feed_iron_pct"], row["feed_silica_age_h"], row["feed_iron_age_h"]) == pytest.approx(
            (16 + (k - 2) / 10, 55 + (k - 2) / 10, float(k - 2), k - 2 + 0.5))


def test_the_history_holds_only_fresh_analyses_in_the_order_of_their_samples(tables, view):
    inputs = tables.inputs(hc.hour(10), view)
    assert isinstance(inputs, IssueInputs) and inputs.issue_at == hc.hour(10)
    assert list(inputs.lab_history.columns) == ["sample_hour", "silica_pct", "available_at"]
    assert inputs.lab_history["sample_hour"].tolist() == [hc.hour(k) for k in (0, 1, 2, 5, 7)], "hours 3 and 4 are interpolated and 6 and 8 held"
    assert inputs.lab_history["available_at"].tolist() == [hc.hour(k + 2) for k in (0, 1, 2, 5, 7)]
    assert (inputs.feed.index.tolist() == ["feed_silica_pct", "feed_iron_pct", "feed_silica_age_h", "feed_iron_age_h"]) and inputs.feed["feed_silica_age_h"] == 8.0
    assert inputs.sensors["rows"] == 12 and inputs.sensors["amina_flow_mean"] == 100.0 * AGGREGATE_COLUMNS.index("amina_flow_mean") + 9


def test_an_analysis_is_known_from_its_arrival_instant_on_and_not_a_moment_before():
    analyses = hc.fresh_analyses()
    arrival = hc.hour(9)                                  # the analysis of hour 7
    assert lab_known_at(analyses, arrival)["sample_hour"].tolist() == [hc.hour(k) for k in (0, 1, 2, 5, 7)]
    assert lab_known_at(analyses, arrival - timedelta(minutes=1))["sample_hour"].tolist() == [hc.hour(k) for k in (0, 1, 2, 5)]
    assert lab_known_at(analyses, hc.hour(1)).empty
    shuffled = analyses.sample(frac=1.0, random_state=1)
    assert lab_known_at(shuffled, hc.hour(12))["sample_hour"].tolist() == sorted(shuffled[shuffled["available_at"] <= hc.hour(12)]["sample_hour"])
    assert len(analyses) == 7, "the input is not changed"


def test_feature_row_ignores_an_analysis_that_has_not_arrived_even_if_the_caller_hands_it_over(tables, view):
    inputs = tables.inputs(hc.hour(10), view)
    future = pd.DataFrame({"sample_hour": [hc.hour(8)], "silica_pct": [99.0], "available_at": [hc.hour(10) + HOUR]})
    with_future = dataclasses.replace(inputs, lab_history=pd.concat([inputs.lab_history, future], ignore_index=True))
    pd.testing.assert_series_equal(feature_row(with_future, view), feature_row(inputs, view), check_exact=True)


def test_the_three_horizons_of_one_instant_share_its_features_and_the_target_hour_is_never_read(tables, view):
    """Hour 10 closes at 11:00 for H0 (target 10), H1 at 10:00 (target 10) ... the instant of (target, H) is target - H + 1 hour."""
    t = hc.hour(10)
    pairs = [(0, hc.hour(9)), (1, hc.hour(10)), (2, hc.hour(11))]          # (horizon, target) that are issued at 10:00
    rows = [design(tables, pd.DatetimeIndex([target]), horizon, view).iloc[0] for horizon, target in pairs]
    expected = feature_row(tables.inputs(t, view), view)
    for row in rows:
        pd.testing.assert_series_equal(row, expected, check_names=False, check_exact=True)
    frame = design(tables, pd.DatetimeIndex([hc.hour(9), hc.hour(11)]), 0, view)
    assert frame.index.tolist() == [hc.hour(9), hc.hour(11)] and list(frame.columns) == list(FEATURE_COLUMNS)
    assert frame.loc[hc.hour(9), "lab_last1"] == 2.35 and frame.loc[hc.hour(11), "lab_last1"] == 2.20, "issued at 10:00 and at 12:00"
    with pytest.raises(ValueError, match="horizon"):
        design(tables, pd.DatetimeIndex([hc.hour(9)]), -1, view)
    assert design(tables, pd.DatetimeIndex([]), 0, view).empty


def test_the_mean_of_six_is_of_the_latest_six_and_the_history_needed_is_inclusive(tables, view):
    """At 13:00 seven fresh analyses have arrived (hours 0, 1, 2, 5, 7, 10, 11): the mean of six leaves out the oldest. With a history of
    exactly the analyses that have arrived the features exist, and with one more they do not."""
    inputs = tables.inputs(hc.hour(13), view)
    arrived = [2.50, 2.61, 2.40, 2.10, 2.35, 2.20, 2.45]
    row = feature_row(inputs, view)
    assert len(inputs.lab_history) == 7 and row["lab_mean6"] == pytest.approx(sum(arrived[1:]) / 6) and row["lab_mean6"] != pytest.approx(sum(arrived[:6]) / 6)
    assert (row["lab_last1"], row["lab_last2"], row["lab_last3"]) == (2.45, 2.20, 2.35)
    enough = dataclasses.replace(view, features=dataclasses.replace(view.features, min_fresh_history=7))
    assert feature_row(inputs, enough)[[c for c in LAB_FEATURE_COLUMNS if c != "lab_mean24"]].notna().all() and missing_inputs(inputs, "fL", enough) is None
    more = dataclasses.replace(view, features=dataclasses.replace(view.features, min_fresh_history=8))
    assert feature_row(inputs, more)[list(LAB_FEATURE_COLUMNS)].isna().all() and missing_inputs(inputs, "fL", more) == "short_lab_history"


def test_the_values_of_an_instant_made_without_frames_are_those_of_its_inputs_at_every_instant(small_canonical, quick_cfg):
    """``HourTables.row_values`` (what ``design`` calls) is ``feature_row(inputs(t))`` bit for bit: at the hours of the small fixture, the March gap and the margins
    included, at instants that are not an hour, and under other latencies and histories; ``design`` is the stack of those rows."""
    hours = small_canonical.hours
    first, last = hours["hour"].iloc[0], hours["hour"].iloc[-1]
    instants = list(pd.date_range(first - timedelta(hours=3), last + timedelta(hours=3), freq="h")) + [first + timedelta(hours=7, minutes=30), first + timedelta(minutes=5)]
    for latency, history in ((quick_cfg.lab.latency_hours, quick_cfg.features.min_fresh_history), (3, 1), (1, 6), (2, 24)):
        view = dataclasses.replace(quick_cfg, lab=dataclasses.replace(quick_cfg.lab, latency_hours=latency), features=dataclasses.replace(quick_cfg.features, min_fresh_history=history))
        tables = HourTables.from_hours(hours, view)
        made = 0
        for t in instants[::2 if latency == quick_cfg.lab.latency_hours else 5]:
            slow, fast = feature_row(tables.inputs(t.to_pydatetime(), view), view).to_numpy(), tables.row_values(t.to_pydatetime(), view)
            assert slow.tobytes() == fast.tobytes(), (latency, history, t)
            made += int(not np.isnan(fast).any())
        assert made > 100 // (2 if latency == quick_cfg.lab.latency_hours else 5), "most of the instants have every input, so the comparison is not of blank rows"
        targets = pd.DatetimeIndex(instants[::25])
        for horizon in (0, 1, 2):
            expected = np.vstack([feature_row(tables.inputs((target - (horizon - 1) * HOUR).to_pydatetime(), view), view).to_numpy() for target in targets])
            assert design(tables, targets, horizon, view).to_numpy().tobytes() == expected.tobytes()


def test_the_analyses_known_at_an_instant_are_the_ones_of_lab_known_at_in_its_order_whatever_the_frame_is():
    """``_known_arrays`` (what ``feature_row`` reads) is ``lab_known_at`` without its frame: shuffled rows, repeated sample hours, a missing instant, another
    resolution, an arrival that is exactly the instant and a time zone, which goes through ``lab_known_at`` itself."""
    base = pd.Timestamp("2017-03-10 00:00")
    hours = [base + timedelta(hours=k) for k in (5, 1, 3, 3, 0, 8, 2)]
    frame = pd.DataFrame({"sample_hour": hours, "silica_pct": [2.5, 2.1, 2.7, 2.6, 2.2, 2.9, 2.4], "available_at": [h + timedelta(hours=2) for h in hours]})
    variants = {"shuffled": frame, "seconds": frame.assign(sample_hour=frame["sample_hour"].astype("datetime64[s]"), available_at=frame["available_at"].astype("datetime64[s]")),
                "a missing sample hour": frame.assign(sample_hour=frame["sample_hour"].where(frame.index != 3)), "empty": frame.iloc[0:0],
                "zone": frame.assign(sample_hour=frame["sample_hour"].dt.tz_localize("UTC"), available_at=frame["available_at"].dt.tz_localize("UTC"))}
    for name, lab in variants.items():
        for t in [base + timedelta(hours=k) for k in range(-1, 14)] + [base + timedelta(hours=4, minutes=1)]:
            instant = t.tz_localize("UTC") if name == "zone" else t
            known = lab_known_at(lab, instant)
            sample, silica = _known_arrays(lab, instant)
            assert silica.tobytes() == known["silica_pct"].to_numpy(dtype="float64").tobytes(), (name, t)
            newest = known["sample_hour"].tolist()[-1:]
            assert [x.value if x is not pd.NaT else None for x in sample[-1:]] == [x.value if x is not pd.NaT else None for x in newest], (name, t)


# --- what is missing: a blank block and its reason ----------------------------------------------------------------------------


def test_a_missing_input_blanks_its_block_and_names_its_reason(tables, view, quick_cfg):
    lab_columns, sensor_columns, feed_columns = list(LAB_FEATURE_COLUMNS), list(AGGREGATE_COLUMNS), ["feed_silica_pct", "feed_iron_pct", "feed_silica_age_h", "feed_iron_age_h"]
    inputs = tables.inputs(hc.hour(10), view)
    assert all(missing_inputs(inputs, name, view) is None for name in FEATURE_SETS)
    no_sensors = dataclasses.replace(inputs, sensors=None)
    row = feature_row(no_sensors, view)
    assert row[sensor_columns].isna().all() and row[lab_columns[:3]].notna().all()
    assert [missing_inputs(no_sensors, name, view) for name in ("fS", "fL", "fSL", "fSLF")] == ["no_sensor_rows", None, "no_sensor_rows", "no_sensor_rows"]
    thin = dataclasses.replace(inputs, sensors=inputs.sensors.copy())
    thin.sensors["rows"] = quick_cfg.hours.min_rows_per_hour - 1
    assert feature_row(thin, view)[sensor_columns].isna().all() and missing_inputs(thin, "fS", view) == "partial_below_minimum"
    thin.sensors["rows"] = quick_cfg.hours.min_rows_per_hour
    assert feature_row(thin, view)[sensor_columns].notna().all() and missing_inputs(thin, "fS", view) is None, "the minimum itself is enough"
    strict = dataclasses.replace(view, features=dataclasses.replace(view.features, min_fresh_history=6))
    row = feature_row(inputs, strict)
    assert row[lab_columns].isna().all() and row[sensor_columns].notna().all(), "five analyses are not the six that this view asks for"
    assert [missing_inputs(inputs, name, strict) for name in ("fS", "fL", "fSL", "fSLF")] == [None, "short_lab_history", "short_lab_history", "short_lab_history"]
    no_feed = dataclasses.replace(inputs, feed=None)
    assert feature_row(no_feed, view)[feed_columns].isna().all() and missing_inputs(no_feed, "fSLF", view) == "no_feed_hour"
    assert [missing_inputs(no_feed, name, view) for name in ("fS", "fL", "fSL")] == [None, None, None]
    early = tables.inputs(hc.hour(1), view)       # nothing has arrived and no feed: the history comes first in the reasons
    assert early.lab_history.empty and early.feed is None and missing_inputs(early, "fSLF", view) == "short_lab_history"


# --- the matrix and its guards (AC10) ----------------------------------------------------------------------------------------


def full_frame(rows: int = 3) -> pd.DataFrame:
    return pd.DataFrame(np.arange(rows * len(FEATURE_COLUMNS), dtype=float).reshape(rows, -1), columns=list(FEATURE_COLUMNS))


@pytest.mark.parametrize("name", [*FORBIDDEN_COLUMNS, *TARGET_COLUMNS, "silica_pct_row_2", "feed_iron_pct_row_179", "iron_conc_pct_row_5", "unknown_column"])
def test_forbidden_columns_cannot_reach_the_matrix(name):
    for feature_set in FEATURE_SETS:
        with pytest.raises(LeakageError, match=re.escape(name)):
            build_matrix(full_frame().assign(**{name: 1.0}), feature_set)
    with pytest.raises(LeakageError, match=re.escape(name)):
        build_matrix(full_frame().rename(columns={"lab_last1": name}), "fS")


def test_the_matrix_has_exactly_the_columns_of_the_set_in_its_order():
    frame = full_frame()
    for name, columns in FEATURE_SETS.items():
        matrix = build_matrix(frame[list(reversed(FEATURE_COLUMNS))], name)       # the order of the input does not matter
        assert list(matrix.columns) == list(columns) and matrix.shape == (3, len(columns)) and name in ("fS", "fL", "fSL", "fSLF")
        assert matrix.to_numpy().tolist() == frame[list(columns)].to_numpy().tolist()
    assert [len(FEATURE_SETS[name]) for name in ("fS", "fL", "fSL", "fSLF")] == [57, 6, 63, 67]
    assert not build_matrix(frame.iloc[0:0], "fL").shape[0] and frame.shape == (3, 67), "the input is not changed"
    with pytest.raises(ValueError, match="lab_age_h"):
        build_matrix(frame.drop(columns=["lab_age_h"]), "fL")
    with pytest.raises(ValueError, match="conjunto desconocido"):
        build_matrix(frame, "fX")


# --- the code of the features reads nothing it must not read (AC10, static) ----------------------------------------------------

NEVER = ("iron_conc_pct", "is_ramp", "tracking", "method_estimates", "row_id", "row_in_hour", "hour_key", "block", "month", "weekday", "hour_of_day")
PATTERN = re.compile(r"(?:feed_iron_pct|feed_silica_pct|iron_conc_pct|silica_pct)_row_\d+")


def named_things(tree: ast.AST) -> list[tuple[str, str]]:
    """Every identifier, attribute and string (docstrings left out) of the code, with the qualified name of the function that holds it."""
    found: list[tuple[str, str]] = []

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = f"{scope}.{child.name}" if scope else child.name
                found.append((inner, child.name))
            if isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant) and isinstance(child.value.value, str):
                continue                                           # a docstring
            if isinstance(child, ast.Name):
                found.append((scope, child.id))
            elif isinstance(child, ast.Attribute):
                found.append((scope, child.attr))
            elif isinstance(child, ast.keyword) and child.arg:
                found.append((scope, child.arg))
            elif isinstance(child, ast.arg):
                found.append((scope, child.arg))
            elif isinstance(child, ast.Constant) and isinstance(child.value, str):
                found.append((scope, child.value))
            visit(child, inner)

    visit(tree, "")
    return found


def test_feature_code_never_reads_iron_concentrate_lab_rows_or_ramp_marks():
    tree = ast.parse(Path(features.__file__).read_text(encoding="utf-8"))
    things = named_things(tree)
    assert len(things) > 100, "the scan sees the code"
    for scope, text in things:
        for word in NEVER:
            assert re.search(rf"\b{word}\b", text) is None, f"{word!r} in {scope}: {text!r}"
        assert PATTERN.search(text) is None, f"a laboratory value of a row in {scope}: {text!r}"
    # the label of a target hour is read by the fit and the evaluation, never by the code that makes features
    assert {scope for scope, text in things if text == "analysis_of"} <= {"HourTables.analysis_of", "HourTables"}
    # the state of an hour is read only to keep the fresh analyses of the history (D05), in the two places that build it
    holders = {scope for scope, text in things if re.search(r"\blab_state\b", text)}
    assert holders and holders <= {"HourTables.__init__", "inputs_at"}, holders
    for scope in holders:
        assert any(text == "fresh" or re.search(r"lab_state = 'fresh'", text) for s, text in things if s == scope), scope


def test_the_static_scan_would_find_a_forbidden_name_in_a_string_an_attribute_or_an_argument():
    for source in ("x = df['iron_conc_pct']", "x = df.is_ramp", "def f(row_id): pass", "q = 'SELECT silica_pct_row_7 FROM t'", "y = f(block=1)"):
        things = named_things(ast.parse(source))
        assert any(re.search(rf"\b(?:{'|'.join(NEVER)})\b", text) or PATTERN.search(text) for _scope, text in things), source
