"""The semantic model of the star schema (U13; AC25; D25; plan, section 19): the tables, their columns and their relationships are the contract that Power BI reads,
so they are written here once more by hand from the plan and the model must be exactly that; every incoherence the model can have is named; every table has the SQL
that builds it and every relationship its control. The measures and the pages arrive with U14."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pyarrow as pa

from flotsilica.dashboard.semantic_model import ARROW_TYPES, MODEL, Column, Relationship, Table, arrow_schema, validate_model

SQL = Path(__file__).resolve().parents[2] / "sql"

# plan, section 19: table -> (key, columns); the order of the columns is the order of the file
DIMENSIONS = {
    "dim_date": (("date_key",), ("date_key", "date", "year", "month", "month_name_es", "weekday_es", "test_week")),
    "dim_hour": (("hour_key",), ("hour_key", "hour", "date", "hour_of_day", "block", "block_es", "lab_state", "lab_state_es", "is_partial", "rows")),
    "dim_horizon": (("horizon_key",), ("horizon_key", "horizon_es", "hours_ahead")),
    "dim_method": (("method_key",), ("method_key", "method_es", "kind_es")),
    "dim_sensor": (("sensor_key",), ("sensor_key", "column", "name_es", "group_es", "unit_es")),
    "dim_model": (("model_key",), ("model_key", "model_version", "horizon_key", "family", "feature_set", "target_es", "min_samples_leaf", "half_width", "b_star", "b2_k",
                                   "trained_on_es", "config_sha256", "seal_state")),
    "dim_pipeline_run": (("run_key",), ("run_key", "started_at", "finished_at", "status", "delivery_id", "as_of", "source_sha256", "rows_delivery", "estimates_issued",
                                        "estimates_missing", "peak_working_set_mb", "peak_commit_mb", "memory_counter", "message")),
}
FACTS = {
    "fact_hour_process": (("hour_key", "sensor_key"), ("hour_key", "sensor_key", "mean", "std", "last")),
    "fact_hour_lab": (("hour_key",), ("hour_key", "silica_pct", "iron_conc_pct", "feed_silica_pct", "feed_iron_pct", "lab_state", "feed_silica_age_h", "feed_iron_age_h",
                                     "available_at")),
    "fact_estimate": (("hour_key", "horizon_key"), ("hour_key", "horizon_key", "model_key", "issue_at", "status", "estimate", "low", "high", "persistence", "b_star", "actual",
                                                    "abs_error", "abs_error_persistence", "abs_error_b_star", "covered", "is_censored", "run_key")),
    "fact_method_metrics": (("scope", "horizon_key", "method_key", "seal_state"), ("scope", "horizon_key", "method_key", "mae", "rmse", "bias", "hours", "coverage",
                                                                                    "is_b_star", "ci_low_vs_b_star", "ci_high_vs_b_star", "seal_state")),
    "fact_weekly_mae": (("test_week", "horizon_key", "method_key", "seal_state"), ("test_week", "horizon_key", "method_key", "mae", "hours", "seal_state")),
    "fact_evaluation_summary": (("criterion_id", "seal_state"), ("criterion_id", "name_es", "value", "baseline_value", "ci_low", "ci_high", "threshold_es", "passed",
                                                                 "seen_by_research", "seen_by_planner", "verdict_es", "seal_state")),
    "fact_selection": (("horizon_key", "family", "feature_set", "target", "min_samples_leaf"), ("horizon_key", "family", "feature_set", "target", "min_samples_leaf",
                                                                                              "mae_v1", "chosen")),
    "fact_sensitivity": (("sensor_key",), ("sensor_key", "importance_v1", "importance_v2", "rho_min", "rho_max", "sign_stable", "pd_range", "passes", "test_sign_kept",
                                          "label_es")),
    "fact_pd_curve": (("sensor_key", "point"), ("sensor_key", "point", "grid_value", "mean_estimate")),
    "fact_variants": (("variant", "horizon_key", "method_key"), ("variant", "variant_es", "horizon_key", "method_key", "mae", "hours", "ci_low", "ci_high")),
    "fact_leakage": (("check",), ("check", "check_es", "mae", "r2", "note_es")),
    "fact_data_quality": (("date_key",), ("date_key", "hours", "missing_hours", "partial_hours", "fresh", "interpolated", "held", "stuck_sensor_hours", "feed_unchanged_24h")),
    "fact_validation": (("run_key", "rule_id"), ("run_key", "rule_id", "name_es", "severity", "scope", "aggregation", "status", "rows_affected", "hours_affected")),
}
RELATIONSHIPS = (
    ("R01", "dim_hour", "hour_key", "fact_hour_process"), ("R02", "dim_hour", "hour_key", "fact_hour_lab"), ("R03", "dim_hour", "hour_key", "fact_estimate"),
    ("R04", "dim_date", "date_key", "fact_data_quality"),
    ("R05", "dim_horizon", "horizon_key", "fact_estimate"), ("R06", "dim_horizon", "horizon_key", "fact_method_metrics"),
    ("R07", "dim_horizon", "horizon_key", "fact_weekly_mae"), ("R08", "dim_horizon", "horizon_key", "fact_selection"),
    ("R09", "dim_method", "method_key", "fact_method_metrics"), ("R10", "dim_method", "method_key", "fact_weekly_mae"),
    ("R11", "dim_sensor", "sensor_key", "fact_hour_process"), ("R12", "dim_sensor", "sensor_key", "fact_sensitivity"), ("R13", "dim_sensor", "sensor_key", "fact_pd_curve"),
    ("R14", "dim_model", "model_key", "fact_estimate"), ("R15", "dim_pipeline_run", "run_key", "fact_validation"),
)


def test_the_tables_and_relationships_are_the_ones_of_the_plan():
    """Item 3 of the risks: the model is what the plan says, table by table and column by column, and nothing else; changing it is changing a contract on purpose."""
    expected = {**DIMENSIONS, **FACTS}
    assert [t.name for t in MODEL.tables] == list(expected)
    for table in MODEL.tables:
        key, columns = expected[table.name]
        assert (table.key, table.column_names) == (key, columns), table.name
        assert table.kind == ("dimension" if table.name.startswith("dim_") else "fact") and table.description_es
        assert all(c.description_es for c in table.columns), table.name
    assert [(r.rel_id, r.dim_table, r.dim_column, r.fact_table) for r in MODEL.relationships] == list(RELATIONSHIPS)
    assert all(r.fact_column == r.dim_column for r in MODEL.relationships)


def test_the_arrow_schema_of_a_table_has_its_columns_in_order_and_each_type():
    schema = arrow_schema(MODEL.table("fact_estimate"))
    assert schema.names == list(MODEL.table("fact_estimate").column_names)
    assert [schema.field(c.name).type for c in MODEL.table("fact_estimate").columns] == [ARROW_TYPES[c.dtype] for c in MODEL.table("fact_estimate").columns]
    assert schema.field("hour_key").type == pa.int64() and schema.field("horizon_key").type == pa.int8() and schema.field("issue_at").type == pa.timestamp("us")
    assert schema.field("covered").type == pa.bool_() and MODEL.table("dim_hour").columns[2].dtype == "date"


def test_the_model_is_coherent_and_each_incoherence_is_named():
    """A model with nothing wrong has no problem; each way to break one is found and says which table or relationship."""
    assert validate_model(MODEL) == []
    first = MODEL.tables[0]

    def broken(**changes):
        return validate_model(dataclasses.replace(MODEL, **changes))

    assert any("repetidas" in p for p in broken(tables=(*MODEL.tables, first)))
    assert any("dim_date" in p and "clave" in p for p in broken(tables=(dataclasses.replace(first, key=("nope",)), *MODEL.tables[1:])))
    typed = dataclasses.replace(first, columns=(*first.columns[:-1], Column("test_week", "decimal", "x")))
    assert any("tipo desconocido" in p for p in broken(tables=(typed, *MODEL.tables[1:])))
    for change, text in ((dict(cardinality="many_to_many"), "uno a varios"), (dict(cross_filter="both"), "uno a varios"), (dict(active=False), "uno a varios"),
                         (dict(fact_column="model_key"), "no es una columna"), (dict(dim_table="fact_estimate"), "no une una dimensión")):
        relationships = (dataclasses.replace(MODEL.relationships[2], **change), *MODEL.relationships[3:])
        assert any("R03" in p and text in p for p in broken(relationships=relationships)), change
    wide = Relationship("R99", "dim_hour", "date", "fact_hour_lab", "date")
    assert any("R99" in p and "clave entera" in p for p in broken(relationships=(*MODEL.relationships, wide)))


def test_every_table_has_the_sql_that_builds_it_and_every_relationship_its_control():
    """Each table is built by ``sql/marts/powerbi/mart_NN_<table>.sql`` in the model's order, and each relationship is checked by ``chk_fk_rNN_<fact>_<dim>.sql``; the
    other controls of ``sql/checks/model`` are the ones that guard the instant and the totals."""
    marts = sorted(p.name for p in (SQL / "marts" / "powerbi").glob("mart_*.sql"))
    assert marts == [f"mart_{i:02d}_{t.name}.sql" for i, t in enumerate(MODEL.tables, start=1)]
    checks = {p.name for p in (SQL / "checks" / "model").glob("chk_*.sql")}
    assert {c for c in checks if c.startswith("chk_fk_")} == {f"chk_fk_{r.rel_id.lower()}_{r.fact_table}_{r.dim_table}.sql" for r in MODEL.relationships}
    assert {c for c in checks if not c.startswith("chk_fk_")} == {
        "chk_actual_only_after_arrival.sql", "chk_estimates_complete.sql", "chk_hour_block_matches_staging.sql", "chk_lab_masked_until_arrival.sql",
        "chk_at_most_one_b_star_per_scope_and_horizon.sql", "chk_star_keys_unique.sql", "chk_tracking_totals.sql"}


def test_a_table_is_a_dataclass_with_its_columns_by_name():
    table = Table("dim_x", "dimension", ("k",), (Column("k", "int32", "Clave."),), "Una dimensión.")
    assert table.column_names == ("k",) and MODEL.table("dim_hour").name == "dim_hour"
