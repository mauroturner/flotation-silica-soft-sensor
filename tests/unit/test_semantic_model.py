"""The semantic model of the star schema (U13; AC25; D25; plan, section 19): the tables, their columns and their relationships are the contract that Power BI reads,
so they are written here once more by hand from the plan and the model must be exactly that; every incoherence the model can have is named; every table has the SQL
that builds it and every relationship its control.

The measures and the five pages of the report (U14; AC26; plan, section 20) are checked here as far as a project without Power BI can: no DAX runs anywhere in the suite (item 6 of
the risks), so every table, column and measure an expression names must exist, every function it calls must be one of the few the plan uses, every text it compares a column with must be
a value that column takes, no measure removes the filters of a slicer, and every slicer must reach, through the relationships, the visuals of its page that it does not say it leaves alone."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pyarrow as pa
import pytest

from flotsilica import texts
from flotsilica.dashboard.semantic_model import (
    ARROW_TYPES,
    DAX_FUNCTIONS,
    MEASURES,
    MODEL,
    PAGE_COLUMNS,
    PAGE_ROWS,
    PAGES,
    Column,
    Measure,
    Page,
    Relationship,
    SemanticModel,
    Table,
    Visual,
    arrow_schema,
    dax_column_refs,
    dax_measure_refs,
    validate_model,
)

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


# --- the measures of the report (U14; AC26; plan, section 20) ---------------------------------------------------------------------------------------------------------------------

MEASURE_NAMES = (
    "Horas con análisis", "MAE del modelo", "MAE de la persistencia", "MAE de la base más fuerte", "Modelo menos persistencia", "Sesgo del modelo", "Cobertura del rango",
    "Última estimación", "Último análisis llegado", "Horas sin estimación", "Análisis frescos (%)", "Horas interpoladas", "Horas repetidas", "Media del sensor", "MAE en la prueba",
    "Es la base más fuerte", "Sensores con asociación estable", "Veredicto", "Semiancho del rango", "Última fecha de cálculo", "Reglas bloqueantes fallidas",
)
REMOVES_FILTERS = re.compile(r"\b(ALL|ALLEXCEPT|ALLSELECTED|REMOVEFILTERS|CROSSFILTER|USERELATIONSHIP|KEEPFILTERS)\b")


def test_every_dax_reference_exists():
    """AC26 with no DAX engine (item 6): the measures are the plan's, in its order; each ``table[column]`` they name is a column of that table, each ``dim_`` or ``fact_`` word is a table, each
    ``[Measure]`` is a measure (never itself, never a cycle), each function is one the plan uses, and each text a column is compared with is a value that column takes (its description
    says it)."""
    assert tuple(m.name_es for m in MEASURES) == MEASURE_NAMES and MODEL.measures == MEASURES
    tables = {t.name: {c.name: c for c in t.columns} for t in MODEL.tables}
    names = set(MEASURE_NAMES)
    assert DAX_FUNCTIONS == {"CALCULATE", "COUNTROWS", "AVERAGE", "AVERAGEX", "DIVIDE", "MAX", "SELECTEDVALUE", "SUM", "NOT", "ISBLANK", "TRUE"}
    uses: dict[str, set[str]] = {}
    for m in MEASURES:
        label = f"[{m.name_es}]"
        for table, column in re.findall(r"\b([A-Za-z_]\w*)\[([^\]]+)\]", m.dax):
            assert table in tables and column in tables[table], f"{label} names {table}[{column}]"
        assert set(re.findall(r"\b(?:dim|fact)_\w+", m.dax)) <= set(tables), f"{label} names a table that does not exist"
        assert set(re.findall(r"\b[A-Z][A-Z0-9.]*(?=\s*\()", m.dax)) <= DAX_FUNCTIONS, f"{label} calls a function the plan does not use"
        assert dax_column_refs(m.dax) == {(t, c) for t, c in re.findall(r"\b([a-z_]\w*)\[([^\]]+)\]", m.dax)}
        uses[m.name_es] = dax_measure_refs(m.dax)
        assert uses[m.name_es] <= names - {m.name_es}, f"{label} names {uses[m.name_es] - names} or itself"
        assert m.dax.count("(") == m.dax.count(")") and m.dax.count('"') % 2 == 0, label
        assert m.format_string and m.description_es, label
        for table, column, literal in re.findall(r'\b([a-z_]\w*)\[([^\]]+)\]\s*=\s*"([^"]*)"', m.dax):
            assert literal in tables[table][column].description_es, f"{label} compares {table}[{column}] with {literal!r}, which the column does not take"
        assert not REMOVES_FILTERS.search(m.dax), f"{label} must keep the filters of the slicers"

    def depth(name: str, seen: tuple[str, ...] = ()) -> int:
        assert name not in seen, f"the measures {seen} call each other in a circle"
        return 1 + max((depth(n, (*seen, name)) for n in uses[name]), default=0)

    assert max(depth(n) for n in names) == 2          # Modelo menos persistencia and Cobertura del rango read one other each, no deeper
    assert dax_measure_refs(MODEL.measure("Modelo menos persistencia").dax) == {"MAE del modelo", "MAE de la persistencia"}
    assert dax_column_refs(MODEL.measure("Última estimación").dax) == {("fact_estimate", "hour_key"), ("fact_estimate", "status"), ("fact_estimate", "horizon_key"),
                                                                       ("fact_estimate", "estimate")}


def test_the_latest_measures_override_only_the_hour_and_horizon_of_their_fact_so_the_date_slicer_still_filters_them():
    """The plan asks to verify that «Última estimación» and «Último análisis llegado» respect the date slicer, ``dim_hour[date]``. A ``CALCULATE`` filter on ``fact[hour_key]`` replaces the
    filters on that column only: the slicer reaches the fact through R02 or R03 as a filter on the relationship, which it leaves alone, so the maximum is taken among the selected
    dates and the value is read at it. No other column of the dimension and no ``ALL`` is touched."""
    for name, fact in (("Última estimación", "fact_estimate"), ("Último análisis llegado", "fact_hour_lab")):
        dax = MODEL.measure(name).dax
        assert dax.count("VAR h =") == 1 and "RETURN" in dax and dax.index("VAR h =") < dax.index("RETURN")
        filtered = {c for t, c in re.findall(r"(\w+)\[(\w+)\]\s*(?:=|>=|<=)", dax) if t == fact}
        assert filtered <= {"hour_key", "horizon_key", "status", "lab_state"}, (name, filtered)
        assert "dim_hour" not in dax and "dim_date" not in dax and not REMOVES_FILTERS.search(dax)
    slicer = next(v for p in PAGES for v in p.visuals if v.kind == "slicer" and v.fields == ("dim_hour[date]",))
    assert slicer.title_es == "Fecha"
    assert {"fact_estimate", "fact_hour_lab"} <= {r.fact_table for r in MODEL.relationships if r.dim_table == "dim_hour"}


def test_a_test_figure_reads_the_sealed_rows_only_so_a_post_seal_row_cannot_hide_it():
    """A fact of the evaluation can hold a sealed and a post-seal row of one key, and ``SELECTEDVALUE`` of two different values is empty: the figures of the test read the sealed rows."""
    for name, fact in (("MAE en la prueba", "fact_method_metrics"), ("Es la base más fuerte", "fact_method_metrics"), ("Veredicto", "fact_evaluation_summary")):
        assert f'{fact}[seal_state] = "sealed"' in MODEL.measure(name).dax, name
    assert 'fact_method_metrics[scope] = "test"' in MODEL.measure("MAE en la prueba").dax


def test_the_measures_that_need_an_arrived_analysis_count_only_hours_that_have_one():
    for name in ("Horas con análisis", "MAE del modelo", "MAE de la persistencia", "MAE de la base más fuerte", "Sesgo del modelo"):
        assert "NOT ISBLANK ( fact_estimate[actual] )" in MODEL.measure(name).dax, name
    assert MODEL.measure("Cobertura del rango").dax.endswith("[Horas con análisis] )")


# --- the five pages ---------------------------------------------------------------------------------------------------------------------------------------------------------------

PAGE_NAMES = ("Sílice estimada y laboratorio", "Horizontes y reglas", "Variables de la planta", "Validación del modelo", "Calidad de datos y corridas")


def page(name: str) -> Page:
    return next(p for p in PAGES if p.name_es == name)


def visual(name: str, title: str) -> Visual:
    return next(v for v in page(name).visuals if v.title_es == title)


def test_there_are_five_pages_in_the_order_of_the_plan_inside_the_grid_without_overlaps():
    assert tuple(p.name_es for p in PAGES) == PAGE_NAMES and MODEL.pages == PAGES and (PAGE_COLUMNS, PAGE_ROWS) == (12, 9)
    for p in PAGES:
        taken: set[tuple[int, int]] = set()
        for v in p.visuals:
            cells = {(x, y) for x in range(v.x, v.x + v.w) for y in range(v.y, v.y + v.h)}
            assert v.w >= 1 and v.h >= 1 and v.x >= 0 and v.y >= 0 and v.x + v.w <= PAGE_COLUMNS and v.y + v.h <= PAGE_ROWS, (p.name_es, v.title_es)
            assert not taken & cells, (p.name_es, v.title_es)
            taken |= cells
            assert v.kind in {"slicer", "card", "table", "lineChart", "barChart"} and v.fields and v.title_es, (p.name_es, v.title_es)
        assert len({v.title_es for v in p.visuals}) == len(p.visuals), f"{p.name_es} repeats a title"


def test_each_page_has_the_visuals_of_the_plan():
    first = {v.title_es: v for v in page(PAGE_NAMES[0]).visuals}
    assert [v.fields[0] for v in first.values() if v.kind == "slicer"] == ["dim_hour[date]", "dim_horizon[horizon_es]"]
    assert [v.fields[0] for v in first.values() if v.kind == "card"] == ["[Última estimación]", "[Último análisis llegado]", "[MAE del modelo]", "[MAE de la persistencia]",
                                                                       "[Cobertura del rango]", "[Horas sin estimación]"]
    [line] = [v for v in first.values() if v.kind == "lineChart"]
    assert {"dim_hour[hour]", "fact_estimate[estimate]", "fact_estimate[low]", "fact_estimate[high]", "fact_hour_lab[silica_pct]", "fact_hour_lab[lab_state]",
            "fact_estimate[persistence]"} == set(line.fields)
    assert {"fact_method_metrics[mae]", "fact_method_metrics[ci_low_vs_b_star]", "fact_method_metrics[ci_high_vs_b_star]", "[MAE en la prueba]", "[Es la base más fuerte]",
            "fact_weekly_mae[mae]"} <= {f for v in page(PAGE_NAMES[1]).visuals for f in v.fields}
    third = page(PAGE_NAMES[2])
    assert [v.fields[0] for v in third.visuals if v.kind == "slicer"] == ["dim_hour[date]", "dim_sensor[name_es]"]
    assert any(v.title_es.startswith("Asociación del modelo, no una receta") and "fact_pd_curve[mean_estimate]" in v.fields for v in third.visuals)
    assert {"fact_sensitivity[importance_v1]", "fact_sensitivity[importance_v2]", "fact_sensitivity[sign_stable]", "fact_sensitivity[label_es]"} <= {f for v in third.visuals for f in v.fields}
    fourth = {f for v in page(PAGE_NAMES[3]).visuals for f in v.fields}
    assert {"fact_evaluation_summary[criterion_id]", "fact_evaluation_summary[threshold_es]", "[Veredicto]", "fact_selection[mae_v1]", "fact_variants[variant_es]", "fact_leakage[check_es]",
            "[Semiancho del rango]"} <= fourth
    fifth = page(PAGE_NAMES[4])
    assert [v.fields[0] for v in fifth.visuals if v.kind == "card"] == ["[Análisis frescos (%)]", "[Horas interpoladas]", "[Horas repetidas]", "[Reglas bloqueantes fallidas]",
                                                                      "[Última fecha de cálculo]"]
    assert {"fact_data_quality[fresh]", "fact_data_quality[held]", "fact_data_quality[interpolated]", "fact_data_quality[missing_hours]", "fact_validation[rule_id]",
            "dim_pipeline_run[run_key]"} <= {f for v in fifth.visuals for f in v.fields}


def _tables_of(v: Visual) -> set[str]:
    """The tables a visual reads: its columns' and, through the DAX of its measures (and of the measures they name), those the measures name by a column or whole."""
    tables, pending = set(), list(v.fields)
    while pending:
        field = pending.pop()
        if field.startswith("["):
            dax = MODEL.measure(field[1:-1]).dax
            tables |= set(re.findall(r"\b(?:dim|fact)_\w+", dax))
            pending += [f"[{name}]" for name in re.findall(r"(?<![\w\]])\[([^\[\]]+)\]", dax)]
        else:
            tables.add(field.split("[")[0])
    return tables


def _filtered_by(table: str) -> set[str]:
    """The tables a selection on `table` reaches: itself and, one to many and single direction, the facts its relationships name."""
    return {table} | {r.fact_table for r in MODEL.relationships if r.dim_table == table}


NOT_FILTERED = re.compile(r"no lo filtran? (.+?)\)?$")


def _says_it_is_not_filtered_by(v: Visual, slicer: Visual) -> bool:
    """Whether the title of `v` says that `slicer` does not filter it («… (no lo filtra la fecha)»), by the slicer's first word."""
    found = NOT_FILTERED.search(v.title_es)
    return found is not None and slicer.title_es.split()[0].lower() in found.group(1).lower()


def test_every_slicer_reaches_the_visuals_of_its_page_through_a_relationship():
    """A slicer on a table with no path to a visual selects without filtering it, in silence (the correction A10 of project 04). Every slicer of every page reaches every visual of its page
    through the relationships of the model, or the visual's title says that this slicer does not filter it, and a title says so only when it is true."""
    slicers = 0
    for p in PAGES:
        for slicer in (v for v in p.visuals if v.kind == "slicer"):
            slicers += 1
            reached = _filtered_by(slicer.fields[0].split("[")[0])
            assert len(slicer.fields) == 1 and not slicer.fields[0].startswith("["), slicer.title_es
            for v in (v for v in p.visuals if v.kind != "slicer"):
                filtered = bool(reached & _tables_of(v))
                assert filtered != _says_it_is_not_filtered_by(v, slicer), (p.name_es, slicer.title_es, v.title_es, filtered)
    assert slicers == 4
    # the two ways it can fail are seen: a slicer that reaches nothing of the page, and a title that says what is not so
    horizon = visual(PAGE_NAMES[0], "Horizonte")
    lab = next(v for v in page(PAGE_NAMES[0]).visuals if v.fields == ("[Último análisis llegado]",))
    assert not _filtered_by("dim_horizon") & _tables_of(lab) and _says_it_is_not_filtered_by(lab, horizon)
    assert not _says_it_is_not_filtered_by(dataclasses.replace(lab, title_es="Último análisis llegado"), horizon)
    assert _filtered_by("dim_date") & _tables_of(lab) == set()


def test_the_visuals_that_the_sensor_and_the_date_do_not_both_filter_say_so_in_their_title():
    third = page(PAGE_NAMES[2])
    sensor, date = (next(v for v in third.visuals if v.kind == "slicer" and v.title_es == t) for t in ("Sensor", "Fecha"))
    said = {v.title_es: (_says_it_is_not_filtered_by(v, date), _says_it_is_not_filtered_by(v, sensor)) for v in third.visuals if v.kind != "slicer"}
    assert [t for t, (d, s) in said.items() if d] and not any(s for d, s in said.values())
    assert all(_filtered_by("dim_sensor") & _tables_of(v) for v in third.visuals if v.kind != "slicer")


def test_a_visual_reads_only_tables_that_the_relationships_join():
    """A column of a dimension next to a measure of a fact it has no relationship with would show the same number in every row; two facts need a dimension that joins them."""
    for p in PAGES:
        for v in p.visuals:
            tables = {MODEL.table(t) for t in _tables_of(v)}
            dims, facts = [t.name for t in tables if t.kind == "dimension"], [t.name for t in tables if t.kind == "fact"]
            assert not (len(facts) >= 2 and not dims) and not (len(dims) >= 2 and not facts), (p.name_es, v.title_es)
            for d in dims:
                for f in facts:
                    assert f in _filtered_by(d), (p.name_es, v.title_es, d, f)


def test_the_model_check_names_every_way_a_measure_or_a_page_can_be_wrong():
    assert validate_model(MODEL) == []
    good = MEASURES[1]

    def with_(**changes) -> SemanticModel:
        return dataclasses.replace(MODEL, **changes)

    def measure(dax: str, **changes) -> SemanticModel:
        return with_(measures=(*MEASURES, dataclasses.replace(good, name_es="Nueva", dax=dax, **changes)))

    first = PAGES[0].visuals[0]
    cases = [
        (measure("AVERAGE ( fact_estimate[abs_erorr] )"), "fact_estimate[abs_erorr]"), (measure("AVERAGE ( fact_estimat[abs_error] )"), "fact_estimat"),
        (measure("COUNTROWS ( fact_estimat )"), "fact_estimat"), (measure("[No existe] + 1"), "[No existe]"), (measure("[Nueva] + 1"), "[Nueva]"),
        (measure("AVERAGE ( fact_estimate[abs_error]"), "paréntesis"), (measure('CALCULATE ( COUNTROWS ( fact_estimate ), fact_estimate[status] = "ok )'), "comillas"),
        (measure("MEDIAN ( fact_estimate[abs_error] )"), "MEDIAN"), (measure('CALCULATE ( COUNTROWS ( fact_estimate ), fact_estimate[status] = "okey" )'), "'okey'"),
        (measure("CALCULATE ( COUNTROWS ( fact_estimate ), ALL ( fact_estimate ) )"), "ALL"), (measure("SUM ( fact_data_quality[held] )", format_string=""), "formato"),
        (measure("SUM ( fact_data_quality[held] )", description_es=""), "descripción"), (with_(measures=(*MEASURES, MEASURES[0])), "repetida"),
        (with_(measures=(*MEASURES[:5], dataclasses.replace(MEASURES[4], dax="[Modelo menos persistencia]"), *MEASURES[5:])), "repetida"),
        (with_(measures=(*MEASURES, Measure("A", "[B] + 1", "0", "x"), Measure("B", "[A] + 1", "0", "x"))), "en círculo"),
        (with_(pages=(*PAGES, PAGES[0])), "página repetida"), (with_(pages=(*PAGES, Page("Vacía", ()))), "sin visuales"),
        (with_(pages=(Page("P", (dataclasses.replace(first, fields=("dim_hour[nope]",)),)),)), "dim_hour[nope]"),
        (with_(pages=(Page("P", (dataclasses.replace(first, fields=("[Nope]",)),)),)), "[Nope]"),
        (with_(pages=(Page("P", (dataclasses.replace(first, fields=("sin corchetes",)),)),)), "sin corchetes"),
        (with_(pages=(Page("P", (dataclasses.replace(first, w=13),)),)), "grilla"), (with_(pages=(Page("P", (first, dataclasses.replace(first, title_es="Otro"))),)), "se superpone"),
        (with_(pages=(Page("P", (dataclasses.replace(first, kind="slicer", fields=("[MAE del modelo]",)),)),)), "segmentador"),
        (with_(pages=(Page("P", (dataclasses.replace(first, kind="table", fields=("dim_sensor[name_es]", "[MAE del modelo]")),)),)), "no se unen"),
        (with_(pages=(Page("P", (dataclasses.replace(first, kind="table", fields=("fact_estimate[estimate]", "fact_hour_lab[silica_pct]")),)),)), "dos hechos"),
    ]
    for model, text in cases:
        problems = validate_model(model)
        assert any(text in p for p in problems), (text, problems)


def test_a_model_without_measures_or_pages_is_still_checked_as_before():
    """The previous form of the model, tables and relationships alone, has no problem and is checked as it was (``validate_model`` named the same problems before U14)."""
    bare = SemanticModel(MODEL.tables, MODEL.relationships)
    assert bare.measures == () and bare.pages == () and validate_model(bare) == []
    broken = dataclasses.replace(bare, relationships=(dataclasses.replace(bare.relationships[0], cardinality="many_to_many"), *bare.relationships[1:]))
    assert any("R01" in p and "uno a varios" in p for p in validate_model(broken))


def test_no_text_of_the_report_calls_a_sensitivity_a_cause_or_an_action():
    """D20: the titles of the visuals, the names of the pages and the descriptions of the measures are about sensors and sensitivities in places, and none says cause or action."""
    found = [*(m.description_es for m in MEASURES), *(m.name_es for m in MEASURES), *(p.name_es for p in PAGES), *(v.title_es for p in PAGES for v in p.visuals)]
    assert any("asociación" in t for t in found) and any("Sensor" in t for t in found)
    for text in found:
        assert texts.sensitivity_problems(text) == [], text
