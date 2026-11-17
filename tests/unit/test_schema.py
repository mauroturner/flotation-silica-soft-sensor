"""The names of the source and of the canonical tables (U04; plan, section 6): one place, with lists that never share a name."""

from __future__ import annotations

import pytest

from flotsilica import schema
from flotsilica.schema import (
    AGGREGATE_COLUMNS,
    ATTRIBUTES,
    COLUMNS,
    FEATURE_COLUMNS,
    FEATURE_SETS,
    FORBIDDEN_COLUMNS,
    LAB_COLUMNS,
    SENSORS,
    SOURCE_HOURS_SCHEMA,
    SOURCE_ROWS_SCHEMA,
    TARGET_COLUMNS,
    SourceError,
    is_forbidden,
)


def test_the_24_attributes_map_to_the_names_of_the_plan_in_file_order(cfg):
    assert list(ATTRIBUTES) == list(cfg.source.attributes) and len(COLUMNS) == 24 and len(set(COLUMNS)) == 24
    assert ATTRIBUTES["date"] == "hour" and ATTRIBUTES["%_Iron_Feed"] == "feed_iron_pct" and ATTRIBUTES["%_Silica_Feed"] == "feed_silica_pct"
    assert ATTRIBUTES["Ore_Pulp_pH"] == "ore_pulp_ph" and ATTRIBUTES["Flotation_Column_04_Air_Flow"] == "air_flow_04"
    assert ATTRIBUTES["Flotation_Column_07_Level"] == "level_07" and ATTRIBUTES["%_Silica_Concentrate"] == "silica_pct"
    assert LAB_COLUMNS == ("feed_iron_pct", "feed_silica_pct", "iron_conc_pct", "silica_pct")
    assert len(SENSORS) == 19 and not set(SENSORS) & set(LAB_COLUMNS) and set(SENSORS) | set(LAB_COLUMNS) | {"hour"} == set(COLUMNS)


def test_the_feature_sets_have_the_sizes_of_d12_and_never_share_a_name_with_what_is_forbidden_or_the_target():
    assert {name: len(columns) for name, columns in FEATURE_SETS.items()} == {"fS": 57, "fL": 6, "fSL": 63, "fSLF": 67}
    assert len(AGGREGATE_COLUMNS) == 57 and AGGREGATE_COLUMNS[:3] == ("starch_flow_mean", "starch_flow_std", "starch_flow_last")
    assert len(set(FEATURE_COLUMNS)) == 67
    assert not set(FEATURE_COLUMNS) & set(FORBIDDEN_COLUMNS) and not set(FEATURE_COLUMNS) & set(TARGET_COLUMNS)
    assert not set(FORBIDDEN_COLUMNS) & set(TARGET_COLUMNS)
    assert not any(is_forbidden(name) for name in FEATURE_COLUMNS)
    # the feed enters only in fSLF
    assert {"feed_silica_pct", "feed_iron_pct"} <= set(FEATURE_SETS["fSLF"]) and not {"feed_silica_pct"} & set(FEATURE_SETS["fSL"])


@pytest.mark.parametrize(("name", "forbidden"), [
    ("iron_conc_pct", True), ("row_id", True), ("row_in_hour", True), ("lab_state", True), ("is_ramp", True), ("hour", True), ("hour_key", True),
    ("month", True), ("weekday", True), ("hour_of_day", True), ("block", True), ("silica_pct_row_2", True), ("feed_iron_pct_row_180", True),
    ("iron_conc_pct_row_1", True), ("silica_pct_row_", False), ("silica_pct_rows", False), ("amina_flow_mean", False), ("lab_last1", False),
])
def test_forbidden_names_include_every_laboratory_value_of_a_row(name, forbidden):
    assert is_forbidden(name) is forbidden


def test_the_arrow_schemas_name_the_canonical_columns_and_hold_no_laboratory_value_per_row():
    assert SOURCE_ROWS_SCHEMA.names == ["row_id", "hour", "row_in_hour", *SENSORS]
    assert not set(SOURCE_ROWS_SCHEMA.names) & set(LAB_COLUMNS)
    assert SOURCE_HOURS_SCHEMA.names[:12] == [
        "hour", "hour_key", "rows", "is_partial", "silica_pct", "iron_conc_pct", "feed_silica_pct", "feed_iron_pct", "lab_state",
        "feed_silica_age_h", "feed_iron_age_h", "feed_changes_in_hour"]
    assert SOURCE_HOURS_SCHEMA.names[12:] == list(AGGREGATE_COLUMNS) and "is_ramp" not in SOURCE_HOURS_SCHEMA.names
    assert str(SOURCE_ROWS_SCHEMA.field("hour").type) == "timestamp[ns]" and str(SOURCE_ROWS_SCHEMA.field("row_id").type) == "int64"


def test_a_source_error_carries_its_rule_and_the_exit_code_3():
    error = SourceError("V05", "a number does not convert", [{"rule_id": "V05", "line": 12}])
    assert (error.rule_id, error.problems, SourceError.EXIT_CODE) == ("V05", [{"rule_id": "V05", "line": 12}], 3)
    assert str(error) == "V05: a number does not convert" and SourceError("V01", "x").problems == []
    assert schema.LAB_STATES == ("fresh", "interpolated", "held")
