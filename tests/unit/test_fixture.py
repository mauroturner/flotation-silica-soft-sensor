"""The synthetic ARFF, its truth and its malformed variants (U03; D40; base of AC02-AC06 and AC15).

The file is read here with a few lines of the standard ``csv`` module, independently of the reader the pipeline will have (U04): the truth
must say what the bytes say, and the bytes must have the quirks of the real file that the plan names (the 318-hour gap, two partial hours,
ramped and held laboratory values, a frozen feed, a fixed sensor, the decimal comma and 24 STRING attributes)."""

from __future__ import annotations

import csv
import hashlib
import math
import re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from tests.fixtures.arff_reader import column, hours_of, number, parse
from tests.fixtures.make_fixture import (
    ATTRIBUTES,
    MALFORMED_KINDS,
    MALFORMED_RULE,
    SENSORS,
    FixtureTruth,
    make_fixture,
    make_malformed,
)

HOUR = timedelta(hours=1)
FIRST_HOUR, LAST_HOUR = datetime(2017, 3, 10, 1), datetime(2017, 9, 9, 23)
GAP_FIRST, GAP_LAST = datetime(2017, 3, 16, 6), datetime(2017, 3, 29, 11)


# --- the truth against the bytes -------------------------------------------------------------------------------------


def test_truth_counts_match_the_arff_and_every_planted_state_is_where_the_truth_says(fixture_truth: FixtureTruth):
    parsed = parse(fixture_truth.path)
    by_hour = hours_of(parsed)
    hours = sorted(by_hour)
    table = fixture_truth.hours
    counts = fixture_truth.counts
    # the file: its size, hash, rows and hours
    assert fixture_truth.sha256 == hashlib.sha256(fixture_truth.path.read_bytes()).hexdigest()
    assert fixture_truth.size_bytes == fixture_truth.path.stat().st_size
    assert counts["rows"] == len(parsed.rows) == fixture_truth.n_rows
    assert counts["hours"] == len(hours) == len(table) == 4097
    assert list(table.index) == hours
    # the calendar: the real one, with the 318-hour gap in its place and two partial hours (V20 and I01)
    assert hours[0] == FIRST_HOUR and hours[-1] == LAST_HOUR
    missing = [h for h in (FIRST_HOUR + HOUR * k for k in range(int((LAST_HOUR - FIRST_HOUR) / HOUR) + 1)) if h not in by_hour]
    assert counts["grid_hours"] == 4415 and counts["missing_hours"] == len(missing) == 318
    assert missing[0] == GAP_FIRST and missing[-1] == GAP_LAST and missing == [GAP_FIRST + HOUR * k for k in range(318)]
    rows_per_hour = {h: len(rows) for h, rows in by_hour.items()}
    full = fixture_truth.rows_per_hour
    partial = sorted(h for h, n in rows_per_hour.items() if n < full)
    assert partial == [datetime(2017, 3, 10, 1), datetime(2017, 4, 10, 0)] and counts["partial_hours"] == 2
    assert [rows_per_hour[h] for h in partial] == [full - 2, full - 1]
    assert counts["below_min_rows_hours"] == 0 and max(rows_per_hour.values()) == full
    assert counts["rows"] == sum(rows_per_hour.values()) == 4095 * full + (full - 2) + (full - 1)
    assert [int(n) for n in table["rows"]] == [rows_per_hour[h] for h in hours]
    assert list(table["partial"]) == [h in partial for h in hours]
    # the laboratory values: the first row of an hour is its analysis; a ramp changes within the hour, an ordinary hour does not
    first_silica = {h: column(by_hour[h], "silica")[0] for h in hours}
    ramp = {h: len(set(column(by_hour[h], "silica"))) > 1 for h in hours}
    assert [float(v) for v in table["silica"]] == pytest.approx([first_silica[h] for h in hours], abs=1e-9)
    assert list(table["is_ramp"]) == [ramp[h] for h in hours]
    assert [float(v) for v in table["iron_conc"]] == pytest.approx([column(by_hour[h], "iron_conc")[0] for h in hours], abs=1e-9)
    # the state of each hour, from the bytes with the rule of D05 (the hour and the one before it, when it is contiguous)
    expected_state = {}
    for h in hours:
        previous = h - HOUR
        if previous in by_hour and ramp[h] and ramp[previous]:
            expected_state[h] = "interpolated"
        elif previous in by_hour and first_silica[h] == first_silica[previous]:
            expected_state[h] = "held"
        else:
            expected_state[h] = "fresh"
    assert list(table["state"]) == [expected_state[h] for h in hours]
    assert counts["interpolated"] == sum(s == "interpolated" for s in expected_state.values()) > 100
    assert counts["held"] == sum(s == "held" for s in expected_state.values()) > 100
    assert counts["fresh"] == sum(s == "fresh" for s in expected_state.values())
    assert counts["ramp_hours"] == sum(ramp.values()) and counts["single_ramp_hours"] > 10
    assert counts["interpolated"] + counts["held"] + counts["fresh"] == counts["hours"]
    # V24: the feed never changes within an hour; I02: how long it stays frozen; I03: the sensors that stay fixed within an hour
    for h in hours:
        for name in ("feed_iron", "feed_silica"):
            assert len(set(column(by_hour[h], name))) == 1
    assert counts["feed_changes_within_hour"] == 0
    for name in ("feed_silica", "feed_iron"):
        values = [column(by_hour[h], name)[0] for h in hours]
        age, start, ages = 0, 0, []
        for i, h in enumerate(hours):
            if i and values[i] != values[i - 1]:
                start = i
            ages.append((h - hours[start]) / HOUR)
        assert [float(a) for a in table[f"{name}_age_h"]] == ages
        assert counts[f"{name}_unchanged_24h_hours"] == sum(a >= 24 for a in ages) > 100
    fixed = {name: sum(len(set(column(by_hour[h], name))) == 1 for h in hours) for name in SENSORS}
    assert {name: n for name, n in fixed.items() if n} == counts["fixed_sensor_hours"]
    assert set(counts["fixed_sensor_hours"]) == {"air_flow_04", "air_flow_05"} and min(counts["fixed_sensor_hours"].values()) > 100


def test_the_header_is_the_real_one_and_the_numbers_are_text_with_a_decimal_comma(fixture_truth: FixtureTruth, cfg):
    parsed = parse(fixture_truth.path)
    assert parsed.relation == cfg.source.relation == "Quality-Prediction-in-a-Mining-Process"
    assert [name for name, _kind in parsed.attributes] == list(cfg.source.attributes) == list(ATTRIBUTES)
    assert len(parsed.attributes) == 24 and {kind for _name, kind in parsed.attributes} == {"STRING"}
    assert parsed.comments and all(line.startswith("% ") for line in parsed.comments)
    text = fixture_truth.path.read_text(encoding="utf-8")
    head = text.split("@DATA\n")[0]
    assert head.index("@RELATION") > max(head.index(line) for line in parsed.comments)       # comments only before @RELATION
    assert '@ATTRIBUTE "%_Iron_Feed" STRING' in head and "@ATTRIBUTE date STRING" in head and head.count("@ATTRIBUTE") == 24
    assert text.count("@DATA") == 1
    # there are 24 fields per line and none is empty; each is between apostrophes or, as the real file writes a number with no fractional part,
    # a bare integer; the date is YYYY-MM-DD HH:00:00
    bare = 0
    for line, row in zip(parsed.raw_lines, parsed.rows, strict=True):
        fields = re.findall(r"'[^']*'|-?[0-9]+", line)
        assert line.startswith("'") and len(row) == 24 and len(fields) == 24 and ",".join(fields) == line and all(row)
        bare += sum(not f.startswith("'") for f in fields)
    assert bare > 1000
    for row in parsed.rows[:2000]:
        assert datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").minute == 0 and row[0].endswith(":00:00")
    sample = [number(f) for row in parsed.rows[:500] for f in row[1:]]
    assert any(f.count(",") == 1 for row in parsed.rows[:50] for f in row[1:]) and not any("." in f for row in parsed.rows for f in row)
    assert all(math.isfinite(v) for v in sample)
    assert fixture_truth.path.read_bytes().count(b"\r") == 0


def test_the_four_laboratory_columns_are_ramped_in_ramp_hours_and_the_rows_in_order(fixture_truth: FixtureTruth):
    """In a ramp hour the silica goes from the hour's analysis to the next hour's value, one equal step per row; the interior hours of
    a stretch are on the line between the analyses at its two ends (research.md; D05)."""
    parsed = parse(fixture_truth.path)
    by_hour = hours_of(parsed)
    table = fixture_truth.hours
    full = fixture_truth.rows_per_hour
    checked = 0
    for h, state in zip(table.index, table["state"], strict=True):
        if not table.at[h, "is_ramp"]:
            continue
        values = column(by_hour[h], "silica")
        following = column(by_hour[h + HOUR], "silica")[0]
        steps = np.diff(values + [following])
        assert len(values) == full and np.allclose(steps, steps[0], atol=2e-6) and abs(steps[0]) > 0.003
        checked += 1
    assert checked == fixture_truth.counts["ramp_hours"]
    # stretches: an interpolated stretch is a ramp start (fresh) followed by 2 to 6 interpolated hours, then the analysis that ends it
    states = list(table["state"])
    ramp = list(table["is_ramp"])
    lengths, i = [], 0
    while i < len(states):
        if states[i] == "interpolated":
            j = i
            while j < len(states) and states[j] == "interpolated":
                j += 1
            assert ramp[i - 1] and not ramp[j] and states[i - 1] == "fresh" and states[j] == "fresh"
            start, end = table["silica"].iloc[i - 1], table["silica"].iloc[j]
            line = [start + (end - start) * k / (j - i + 1) for k in range(1, j - i + 1)]
            assert list(table["silica"].iloc[i:j]) == pytest.approx(line, abs=2e-6)
            lengths.append(j - i)
            i = j
        else:
            i += 1
    assert lengths and set(lengths) <= set(range(2, 7)) and {2, 6} <= set(lengths)
    # held stretches: 2 to 10 hours equal to the fresh hour before them
    held, i = [], 0
    while i < len(states):
        if states[i] == "held":
            j = i
            while j < len(states) and states[j] == "held":
                j += 1
            assert states[i - 1] == "fresh" and not ramp[i - 1] and set(table["silica"].iloc[i:j]) == {table["silica"].iloc[i - 1]}
            held.append(j - i)
            i = j
        else:
            i += 1
    assert held and set(held) <= set(range(2, 11)) and {2, 10} <= set(held)


def test_a_signal_is_planted_only_where_the_truth_says(fixture_truth: FixtureTruth, signal_truth):
    none, positive, negative = fixture_truth, signal_truth("sensor_signal"), signal_truth("lab_only")
    assert (none.signal, none.signal_sensor, none.signal_sign) == ("none", None, 0)
    assert (positive.signal, positive.signal_sensor, positive.signal_sign) == ("sensor_signal", "amina_flow", 1) and positive.signal_beta > 0
    assert (negative.signal, negative.signal_sensor, negative.signal_sign) == ("lab_only", None, 0)

    def hourly(truth: FixtureTruth, name: str) -> tuple[np.ndarray, np.ndarray]:
        by_hour = hours_of(parse(truth.path))
        hours = list(truth.hours.index)
        return np.array([np.mean(column(by_hour[h], name)) for h in hours]), truth.hours["silica"].to_numpy()

    for truth, name in ((none, "amina_flow"), (positive, "amina_flow"), (negative, "amina_flow")):
        sensor, silica = hourly(truth, name)
        r = float(np.corrcoef(sensor, silica)[0, 1])
        lag = float(np.corrcoef(sensor[1:], sensor[:-1])[0, 1])
        if truth is positive:
            assert r > 0.4 and lag < 0.15, (r, lag)       # the sign is planted and the sensor is white noise hour to hour
        else:
            assert abs(r) < 0.1, (truth.signal, r)
            assert (lag > 0.5) is (truth is none), (truth.signal, lag)    # a sensor with its own dynamics, or independent noise
    # the other sensors of the positive control carry no effect
    for name in ("starch_flow", "level_03", "air_flow_01"):
        sensor, silica = hourly(positive, name)
        assert abs(float(np.corrcoef(sensor, silica)[0, 1])) < 0.1, name
    # the silica is an autoregressive process around a level that goes from 2.6 to 2.0
    fresh = none.hours[none.hours["state"] == "fresh"]["silica"]
    assert 2.0 < float(fresh.iloc[:300].mean()) < 3.2 and 1.6 < float(fresh.iloc[-300:].mean()) < 2.4
    assert float(fresh.iloc[-300:].mean()) < float(fresh.iloc[:300].mean())
    assert 0.55 < float(np.corrcoef(fresh.iloc[1:], fresh.iloc[:-1])[0, 1]) < 0.9
    # % Iron Concentrate is correlated with the silica at -0.8 (D09)
    iron = none.hours["iron_conc"].to_numpy()
    assert -0.88 < float(np.corrcoef(iron, none.hours["silica"].to_numpy())[0, 1]) < -0.72
    assert -0.88 < none.iron_silica_corr < -0.72 and positive.iron_silica_corr < -0.6


def test_the_feed_stays_frozen_for_days_and_its_age_counts_clock_hours(fixture_truth: FixtureTruth):
    table = fixture_truth.hours
    for name in ("feed_silica", "feed_iron"):
        values, ages = table[name].to_numpy(), table[f"{name}_age_h"].to_numpy()
        changes = int((np.diff(values) != 0).sum())
        assert 20 < changes < 1500 and ages.max() >= 72, (name, changes, ages.max())
        assert values.min() > 5 and values.max() < 80
        assert (np.diff(table[name]) != 0).sum() == (ages[1:] == 0).sum()


# --- determinism, sizes and arguments ---------------------------------------------------------------------------------------


def test_the_same_seed_gives_the_same_bytes_and_another_seed_another_file(tmp_path, small_truth: FixtureTruth):
    again = make_fixture(tmp_path / "again.arff", rows_per_hour=12, seed=0, weeks=3)
    assert again.path.read_bytes() == small_truth.path.read_bytes() and again.sha256 == small_truth.sha256
    other = make_fixture(tmp_path / "other.arff", rows_per_hour=12, seed=1, weeks=3)
    assert other.sha256 != small_truth.sha256 and other.hours.index.equals(small_truth.hours.index)


def test_weeks_cuts_the_file_to_the_first_weeks_of_the_same_file(small_truth: FixtureTruth, fixture_truth: FixtureTruth):
    small, full = parse(small_truth.path), parse(fixture_truth.path)
    assert small.rows == full.rows[:len(small.rows)] and small.attributes == full.attributes
    hours = small_truth.hours.index
    assert hours[0] == FIRST_HOUR and hours[-1] < FIRST_HOUR + timedelta(weeks=3) and hours[-1] >= FIRST_HOUR + timedelta(weeks=3) - 2 * HOUR
    assert small_truth.counts["missing_hours"] == 318 and small_truth.counts["partial_hours"] == 1
    assert 150 < small_truth.counts["hours"] < 250 and small_truth.counts["interpolated"] >= 2 and small_truth.counts["held"] >= 2
    assert small_truth.counts["single_ramp_hours"] >= 1
    assert (small_truth.hours.loc[hours, "state"].tolist()) == fixture_truth.hours.loc[hours, "state"].tolist()
    assert small_truth.weeks == 3 and fixture_truth.weeks is None


def test_the_rows_per_hour_scale_the_file_and_the_truth_follows(tmp_path):
    truth = make_fixture(tmp_path / "six.arff", rows_per_hour=6, seed=3, weeks=2)
    parsed = parse(truth.path)
    assert truth.rows_per_hour == 6 and len(parsed.rows) == truth.counts["rows"]
    assert max(len(rows) for rows in hours_of(parsed).values()) == 6
    assert sorted(set(truth.hours["rows"])) == [4, 6]


@pytest.mark.parametrize(("kwargs", "match"), [
    ({"signal": "strong"}, "signal"), ({"weeks": 0}, "weeks"), ({"weeks": -3}, "weeks"), ({"weeks": 2.5}, "weeks"),
    ({"rows_per_hour": 3}, "rows_per_hour"), ({"rows_per_hour": 0}, "rows_per_hour"), ({"seed": -1}, "seed"),
])
def test_invalid_arguments_are_refused_and_write_nothing(tmp_path, kwargs, match):
    with pytest.raises(ValueError, match=match):
        make_fixture(tmp_path / "x.arff", **kwargs)
    assert not (tmp_path / "x.arff").exists()


# --- the malformed variants: one per blocking rule of the plan -------------------------------------------------------------


def test_every_blocking_rule_has_a_variant_and_the_list_is_the_plans():
    assert MALFORMED_KINDS == (
        "wrong_hash", "bad_relation", "missing_attribute", "extra_attribute", "renamed_attribute", "numeric_attribute", "field_count",
        "empty_field", "bad_date", "minute_not_zero", "dot_decimal", "text_number", "unsorted", "hour_over_limit", "long_line", "nul_byte",
        "bad_utf8", "oversize")
    assert set(MALFORMED_RULE) == set(MALFORMED_KINDS)
    assert {rule for rule in MALFORMED_RULE.values()} == {"V01", "V02", "V03", "V04", "V05", "V06", "V07"}


def test_an_unknown_malformed_kind_is_refused(tmp_path, small_arff):
    with pytest.raises(ValueError, match="kind"):
        make_malformed(small_arff, "other", tmp_path / "x.arff")
    assert not (tmp_path / "x.arff").exists()


def changed_lines(base: Path, variant: Path) -> list[tuple[int, bytes, bytes]]:
    a, b = base.read_bytes().split(b"\n"), variant.read_bytes().split(b"\n")
    assert len(a) == len(b), (len(a), len(b))
    return [(i, x, y) for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y]


@pytest.mark.parametrize("kind", [k for k in MALFORMED_KINDS if k not in ("missing_attribute", "extra_attribute", "unsorted", "hour_over_limit", "oversize")])
def test_a_variant_that_changes_one_line_changes_exactly_the_one_the_rule_reads(kind, malformed, small_arff):
    variant = malformed(kind)
    base_parsed = parse(small_arff)
    changed = changed_lines(small_arff, variant)
    assert len(changed) == 1 or kind == "wrong_hash", (kind, len(changed))
    (index, old, new), *_ = changed
    if kind == "wrong_hash":                       # the same valid file with one digit changed: only its hash differs (V01)
        assert hashlib.sha256(variant.read_bytes()).hexdigest() != hashlib.sha256(small_arff.read_bytes()).hexdigest()
        parsed = parse(variant)
        assert [number(f) for f in parsed.rows[4][1:]] != [number(f) for f in base_parsed.rows[4][1:]] and len(parsed.rows) == len(base_parsed.rows)
    elif kind == "bad_relation":
        assert old.startswith(b"@RELATION Quality") and new == b"@RELATION Some-Other-Relation"
    elif kind == "renamed_attribute":
        assert b"Amina_Flow" in old and b"Amina_Flux" in new
    elif kind == "numeric_attribute":
        assert old.endswith(b"STRING") and new.endswith(b"NUMERIC")
    elif kind == "long_line":
        assert len(new) > 4096 and new.startswith(b"% ")
    elif kind == "nul_byte":
        assert b"\x00" in new and new.startswith(b"% ")
    elif kind == "bad_utf8":
        assert b"\xff" in new and new.startswith(b"% ")
        with pytest.raises(UnicodeDecodeError):
            variant.read_bytes().decode("utf-8")
    else:                                          # the data-row variants
        old_fields = next(csv.reader([old.decode()], quotechar="'"))
        new_fields = next(csv.reader([new.decode()], quotechar="'"))
        if kind == "field_count":
            assert len(old_fields) == 24 and len(new_fields) == 23
        elif kind == "empty_field":
            assert new_fields.count("") == 1 and len(new_fields) == 24
        elif kind == "bad_date":
            assert new_fields[0] == "10/03/2017 01:00" and new_fields[1:] == old_fields[1:]
        elif kind == "minute_not_zero":
            assert new_fields[0].endswith(":20:00") and old_fields[0].endswith(":00:00") and new_fields[1:] == old_fields[1:]
        elif kind == "dot_decimal":
            assert "." in new_fields[3] and number(old_fields[3]) == pytest.approx(float(new_fields[3]))
        elif kind == "text_number":
            assert new_fields[3] == "abc" and new_fields[:3] == old_fields[:3]


def test_header_variants_declare_one_attribute_too_few_or_too_many(malformed, small_arff):
    base = parse(small_arff)
    fewer, more = parse(malformed("missing_attribute")), parse(malformed("extra_attribute"))
    assert len(fewer.attributes) == 23 and fewer.attributes == base.attributes[:23] and fewer.rows == base.rows
    assert len(more.attributes) == 25 and more.attributes[:24] == base.attributes and more.attributes[24] == ("Extra_Column", "STRING")


def test_the_unsorted_variant_has_a_date_that_goes_back(malformed, small_arff):
    dates = [datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S") for r in parse(malformed("unsorted")).rows]
    base = [datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S") for r in parse(small_arff).rows]
    assert base == sorted(base) and len(dates) == len(base)
    backwards = [i for i in range(1, len(dates)) if dates[i] < dates[i - 1]]
    assert len(backwards) == 1 and sum(a != b for a, b in zip(dates, base, strict=True)) == 1


def test_the_hour_over_limit_variant_has_one_hour_with_one_row_more(malformed, small_arff, small_truth):
    parsed = parse(malformed("hour_over_limit"))
    counts = sorted((len(rows), h) for h, rows in hours_of(parsed).items())
    assert counts[-1][0] == small_truth.rows_per_hour + 1 and counts[-2][0] == small_truth.rows_per_hour
    assert len(parsed.rows) == len(parse(small_arff).rows) + 1
    assert [row[0] for row in parsed.rows] == sorted(row[0] for row in parsed.rows)


def test_the_oversize_variant_is_a_valid_file_larger_than_the_limit_it_is_built_for(tmp_path, small_arff):
    out = make_malformed(small_arff, "oversize", tmp_path / "big.arff", max_bytes=1_500_000)
    assert out.stat().st_size > 1_500_000 and out.stat().st_size < 1_500_000 + 5000
    assert parse(out).rows == parse(small_arff).rows and parse(out).attributes == parse(small_arff).attributes
    default = make_malformed(small_arff, "oversize", tmp_path / "default.arff")
    assert default.stat().st_size > 1 << 20


def test_a_variant_never_overwrites_its_base_and_writes_nothing_when_refused(tmp_path, small_arff, small_truth):
    before = small_arff.read_bytes()
    out = make_malformed(small_arff, "bad_date", tmp_path / "bad.arff")
    assert out != small_arff and small_arff.read_bytes() == before
    with pytest.raises(ValueError, match="out"):
        make_malformed(small_arff, "bad_date", small_arff)
    assert small_arff.read_bytes() == before
