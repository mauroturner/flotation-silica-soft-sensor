"""The rules of validation as a contract (U05; RF06, D23; AC06): every rule of the plan's table with how it is published over runs, the
malformed deliveries and sources that each trip their rule, the counts of the warnings against the truth of the fixture, and the interface of
the rules of the model."""

from __future__ import annotations

import dataclasses
import json
import re
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from flotsilica.ingest import SourceReport, check_source, read_arff
from flotsilica.schema import AGGREGATE_COLUMNS, LAB_COLUMNS, SENSORS, SourceError
from flotsilica.validate import (
    EXAMPLE_LIMIT,
    RULES,
    Aggregation,
    RuleResult,
    Severity,
    ValidationError,
    ValidationReport,
    add_results,
    combine_reports,
    model_result,
    read_report,
    validate_delivery,
    validate_source,
    write_report,
)
from tests.fixtures import store
from tests.fixtures.make_fixture import MALFORMED_KINDS, MALFORMED_RULE

PLAN = Path(__file__).resolve().parents[2] / "docs" / "plan.md"
SEVERITIES = {"bloqueante": Severity.BLOCKING, "advertencia": Severity.WARNING, "informativa": Severity.INFO}
SCOPES = {"fuente": "source", "entrega": "delivery", "horas": "hours", "modelo": "model"}
ROW_LINE = re.compile(r"^\| ([VIM]\d\d) \| (bloqueante|advertencia|informativa) \| (fuente|entrega|horas|modelo) \| (source|per_run|latest) \|", re.M)
MODEL_RULES = ("M01", "M02", "M03", "M04", "M05", "M06", "I04", "I05")
LIMIT = 1 << 20


def failing(report: ValidationReport) -> set[str]:
    return {r.rule_id for r in report.results if r.status == "fail"}


def result(report: ValidationReport, rule_id: str) -> RuleResult:
    return next(r for r in report.results if r.rule_id == rule_id)


_MASTERS: dict[tuple[int, str], sqlite3.Connection] = {}      # the stores that were built, by delivery of the plan: every test gets a copy of one


def store_until(published, delivery_id: str):
    """A warehouse that holds every delivery of the plan before `delivery_id`: built once per delivery and handed over as a copy, so a test can break it."""
    key = (id(published), delivery_id)
    if key not in _MASTERS:
        master = store.empty_store()
        for spec in published.plan:
            if spec.delivery_id == delivery_id:
                break
            _entry, rows, hours = published.items[spec.delivery_id]
            store.load(master, spec.delivery_id, rows, hours)
        _MASTERS[key] = master
    conn = store.empty_store()
    _MASTERS[key].backup(conn)
    return conn


def validate(published, cfg, delivery_id: str, conn=None, *, rows=None, hours=None, spec=None, entry=None, folder=None, run_key="run-1"):
    """Validate a delivery of the published plan, with frames, spec, entry or folder replaced by the test."""
    own_entry, own_rows, own_hours = published.items[delivery_id]
    own_spec = next(s for s in published.plan if s.delivery_id == delivery_id)
    conn = store_until(published, delivery_id) if conn is None else conn
    return validate_delivery(own_rows if rows is None else rows, own_hours if hours is None else hours, own_spec if spec is None else spec, conn, cfg,
                             entry=own_entry if entry is None else entry, out_dir=published.folder if folder is None else folder, run_key=run_key)


# --- AC06: every rule says how it is published over runs ---------------------------------------------------------------------


def test_every_rule_declares_how_it_aggregates_over_runs():
    assert RULES, "the rules of the plan are declared"
    for rule_id, rule in RULES.items():
        assert isinstance(rule.aggregation, Aggregation), rule_id
        assert isinstance(rule.severity, Severity) and rule.scope in SCOPES.values() and rule.name_es.strip(), rule_id
    # what is counted once (the source), added up over the runs or read once from the last run: the three ways exist and none is empty
    assert {rule.aggregation for rule in RULES.values()} == set(Aggregation)
    assert RULES["I01"].aggregation is Aggregation.SOURCE and RULES["I02"].aggregation is Aggregation.LATEST
    assert RULES["V22"].aggregation is Aggregation.PER_RUN and RULES["M01"].aggregation is Aggregation.LATEST


def test_the_rules_are_the_table_of_the_plan_in_its_order():
    table = ROW_LINE.findall(PLAN.read_text(encoding="utf-8"))
    assert [row[0] for row in table] == list(RULES) and len(table) == 29
    for rule_id, severity, scope, aggregation in table:
        rule = RULES[rule_id]
        assert (rule.severity, rule.scope, rule.aggregation.value) == (SEVERITIES[severity], SCOPES[scope], aggregation), rule_id
    assert [r for r in RULES if r.startswith("V") and RULES[r].severity is Severity.BLOCKING and RULES[r].scope == "source"] == [f"V0{k}" for k in range(1, 8)]


# --- the valid fixture: no blocking rule fails and the warnings are what the truth says -------------------------------------------


def test_the_valid_fixture_passes_every_blocking_rule_and_its_counts_are_those_of_the_truth(published, quick_cfg, fixture_truth, canonical):
    conn = store.empty_store()
    reports = []
    for spec in published.plan:
        entry, rows, hours = published.items[spec.delivery_id]
        report = validate(published, quick_cfg, spec.delivery_id, conn)
        assert not report.blocking_failed and failing(report) == set() and report.not_evaluated == (), spec.delivery_id
        assert (report.run_key, report.delivery_id, report.rows_delivery, report.hours_delivery) == ("run-1", spec.delivery_id, entry.rows, entry.hours)
        assert [r.rule_id for r in report.results] == [r for r in RULES if r in {x.rule_id for x in report.results}], "in the order of the plan"
        store.load(conn, spec.delivery_id, rows, hours)
        reports.append(report)
    counts = fixture_truth.counts
    total = lambda rule_id: sum(result(r, rule_id).hours_affected for r in reports)  # noqa: E731
    assert (total("V20"), total("V21"), total("V22"), total("V23"), total("V24")) == (
        counts["partial_hours"], counts["below_min_rows_hours"], counts["interpolated"], counts["held"], counts["feed_changes_within_hour"])
    assert [result(r, "V20").status for r in reports].count("warn") == 1 and result(reports[0], "V20").hours_affected == 2 and result(reports[-1], "V22").status == "pass"
    assert sum(result(r, "V22").rows_affected for r in reports) == int(canonical.hours.loc[canonical.hours["lab_state"] == "interpolated", "rows"].sum())
    fixed = {sensor: sum(next((e["hours"] for e in result(r, "I03").examples if e["sensor"] == sensor), 0) for r in reports) for sensor in SENSORS}
    assert {k: v for k, v in fixed.items() if v} == counts["fixed_sensor_hours"]
    assert sum(result(r, "I03").hours_affected for r in reports) >= max(counts["fixed_sensor_hours"].values())
    # the feed that has not changed for 24 hours or more is read once, from the last run, which already holds the earlier ones
    last = result(reports[-1], "I02")
    assert last.aggregation is Aggregation.LATEST and last.passed and last.severity is Severity.INFO
    assert last.examples == [{"feed_silica_unchanged_hours": counts["feed_silica_unchanged_24h_hours"],
                              "feed_iron_unchanged_hours": counts["feed_iron_unchanged_24h_hours"], "threshold_hours": 24}]
    truth_hours = fixture_truth.hours
    assert last.hours_affected == int(((truth_hours["feed_silica_age_h"] >= 24) | (truth_hours["feed_iron_age_h"] >= 24)).sum())
    assert result(reports[0], "I02").hours_affected < last.hours_affected


def test_the_inputs_of_a_validation_are_not_changed(published, quick_cfg):
    entry, rows, hours = published.items["D2017-08-11"]
    before = (rows.copy(), hours.copy())
    conn = store_until(published, "D2017-08-11")
    validate(published, quick_cfg, "D2017-08-11", conn)
    pd.testing.assert_frame_equal(rows, before[0])
    pd.testing.assert_frame_equal(hours, before[1])


# --- AC06: every malformed delivery fails at least its rule --------------------------------------------------------------------


def case_v10_out_of_order(published, cfg):
    return {"delivery_id": "D2017-08-11", "conn": store.empty_store()}, {"V10"}, "previous_not_loaded"


def case_v10_other_period(published, cfg):
    spec = dataclasses.replace(next(s for s in published.plan if s.delivery_id == "D2017-08-01"), as_of=pd.Timestamp("2017-08-11 01:00").to_pydatetime())
    return {"delivery_id": "D2017-08-01", "spec": spec}, {"V10"}, "other_period"


def case_v10_not_in_plan(published, cfg):
    spec = dataclasses.replace(next(s for s in published.plan if s.delivery_id == "D2017-08-01"), delivery_id="D2099-01-01")
    return {"delivery_id": "D2017-08-01", "spec": spec}, {"V10"}, "not_in_plan"


def case_v10_already_loaded(published, cfg):
    conn = store_until(published, "D2017-08-01")
    conn.execute("INSERT INTO deliveries VALUES ('D2017-08-01', 'loaded')")
    return {"delivery_id": "D2017-08-01", "conn": conn}, {"V10"}, "already_loaded"


def case_v11_a_row_after_the_period(published, cfg):
    _entry, rows, hours = published.items["D2017-08-01"]
    rows = rows.copy()
    rows.loc[0, "hour"] = pd.Timestamp("2017-08-11 00:00")
    return {"delivery_id": "D2017-08-01", "rows": rows}, {"V11", "V14"}, None


def case_v11_an_hour_after_the_period(published, cfg):
    _entry, rows, hours = published.items["D2017-08-01"]
    hours = hours.copy()
    hours.loc[hours.index[-1], "hour"] = pd.Timestamp("2017-08-11 00:00")
    return {"delivery_id": "D2017-08-01", "hours": hours}, {"V11", "V14"}, None


def case_v12_a_row_already_loaded(published, cfg):
    _entry, rows, _hours = published.items["D2017-08-01"]
    rows = rows.copy()
    rows.loc[0, "row_id"] = int(published.items["L2017-07-31"][1]["row_id"].iloc[5])
    return {"delivery_id": "D2017-08-01", "rows": rows}, {"V12"}, "loaded"


def case_v12_a_row_repeated_inside(published, cfg):
    _entry, rows, _hours = published.items["D2017-08-01"]
    rows = rows.copy()
    rows.loc[1, "row_id"] = rows.loc[0, "row_id"]
    return {"delivery_id": "D2017-08-01", "rows": rows}, {"V12"}, "repeated"


def case_v12_an_hour_already_loaded(published, cfg):
    conn = store_until(published, "D2017-08-01")
    first = published.items["D2017-08-01"][2]["hour"].iloc[0]
    conn.execute("INSERT INTO lab_hours VALUES (?, 12, 0, 0)", (store.iso(first),))
    return {"delivery_id": "D2017-08-01", "conn": conn}, {"V12"}, "loaded"


def case_v12_an_hour_repeated_inside(published, cfg):
    _entry, _rows, hours = published.items["D2017-08-01"]
    return {"delivery_id": "D2017-08-01", "hours": pd.concat([hours, hours.iloc[[3]]], ignore_index=True)}, {"V12", "V13"}, "repeated"


def case_v13_rows_differ_from_the_manifest(published, cfg):
    entry = dataclasses.replace(published.items["D2017-08-01"][0], rows=published.items["D2017-08-01"][0].rows + 1)
    return {"delivery_id": "D2017-08-01", "entry": entry}, {"V13"}, "rows_differ_from_manifest"


def case_v13_hours_differ_from_the_manifest(published, cfg):
    entry = dataclasses.replace(published.items["D2017-08-01"][0], hours=published.items["D2017-08-01"][0].hours - 1)
    return {"delivery_id": "D2017-08-01", "entry": entry}, {"V13"}, "hours_differ_from_manifest"


def case_v13_the_sha256_differs_from_the_manifest(published, cfg):
    entry = dataclasses.replace(published.items["D2017-08-01"][0], sha256="0" * 64)
    return {"delivery_id": "D2017-08-01", "entry": entry}, {"V13"}, "sha256_differs_from_manifest"


def case_v13_an_empty_delivery(published, cfg):
    _entry, rows, hours = published.items["D2017-08-01"]
    return {"delivery_id": "D2017-08-01", "rows": rows.iloc[0:0], "hours": hours.iloc[0:0]}, {"V13"}, "empty"


def case_v13_a_close_with_rows(published, cfg):
    _entry, rows, hours = published.items["D2017-08-01"]
    return {"delivery_id": "C2017-09-10", "rows": rows, "hours": hours}, {"V11", "V12", "V13"}, "close_with_rows"


def case_v14_an_aggregate_that_is_not_the_rows(published, cfg):
    _entry, _rows, hours = published.items["D2017-08-01"]
    hours = hours.copy()
    hours.loc[2, "amina_flow_mean"] += 1.0
    return {"delivery_id": "D2017-08-01", "hours": hours}, {"V14"}, "aggregate_differs"


def case_v14_a_row_count_that_is_not_the_rows(published, cfg):
    _entry, _rows, hours = published.items["D2017-08-01"]
    hours = hours.copy()
    hours.loc[2, "rows"] += 1
    return {"delivery_id": "D2017-08-01", "hours": hours}, {"V14"}, "aggregate_differs"


def case_v14_rows_of_an_hour_without_its_hour(published, cfg):
    _entry, rows, hours = published.items["D2017-08-01"]
    return {"delivery_id": "D2017-08-01", "hours": hours.drop(index=4).reset_index(drop=True)}, {"V13", "V14"}, "rows_without_hour"


def case_v15_a_laboratory_column_per_row(published, cfg):
    _entry, rows, _hours = published.items["D2017-08-01"]
    return {"delivery_id": "D2017-08-01", "rows": rows.assign(silica_pct=2.0)}, {"V15"}, None


def case_v15_a_laboratory_value_of_a_later_row(published, cfg):
    _entry, rows, _hours = published.items["D2017-08-01"]
    return {"delivery_id": "D2017-08-01", "rows": rows.assign(silica_pct_row_7=2.0)}, {"V15"}, None


CASES = [v for name, v in sorted(globals().items()) if name.startswith("case_")]


@pytest.mark.parametrize("case", CASES, ids=[c.__name__.removeprefix("case_") for c in CASES])
def test_each_malformed_delivery_fails_its_rule_and_only_the_rules_it_breaks(published, quick_cfg, case):
    arguments, expected, reason = case(published, quick_cfg)
    report = validate(published, quick_cfg, **arguments)
    assert failing(report) == expected, [(r.rule_id, r.examples) for r in report.results if r.status == "fail"]
    assert report.blocking_failed
    rule_id = case.__name__.split("_")[1].upper()     # case_v12_...: the rule that the case is about
    assert rule_id in expected
    broken = result(report, rule_id)
    assert not broken.passed and broken.severity is Severity.BLOCKING and broken.examples and len(broken.examples) <= EXAMPLE_LIMIT
    if reason is not None:
        assert reason in json.dumps(broken.examples), (reason, broken.examples)
    assert json.loads(json.dumps(broken.examples)) == broken.examples, "examples are plain JSON"
    for example in broken.examples:
        assert not set(example) & (set(SENSORS) | set(LAB_COLUMNS) | set(AGGREGATE_COLUMNS)), "an example names hours and rows, never what they measured"


def test_a_sha256_that_changed_on_disk_fails_v13_alone(published, quick_cfg, copy_of):
    folder = copy_of(published.folder)
    entry = published.items["D2017-08-01"][0]
    (folder / entry.rows_file).write_bytes((folder / entry.rows_file).read_bytes() + b"x")
    report = validate(published, quick_cfg, "D2017-08-01", folder=folder)
    assert failing(report) == {"V13"} and "sha256_differs_from_manifest" in json.dumps(result(report, "V13").examples)


def test_a_missing_column_is_a_wrong_delivery_not_a_rule(published, quick_cfg):
    _entry, rows, hours = published.items["D2017-08-01"]
    with pytest.raises(ValueError, match="no tiene las columnas.*amina_flow"):
        validate(published, quick_cfg, "D2017-08-01", rows=rows.drop(columns=["amina_flow"]))
    with pytest.raises(ValueError, match="no tiene las columnas.*lab_state"):
        validate(published, quick_cfg, "D2017-08-01", hours=hours.drop(columns=["lab_state"]))


# --- the warnings count the hours they name -----------------------------------------------------------------------------------


def test_each_warning_names_the_hours_of_its_rule_and_never_blocks(published, quick_cfg):
    _entry, rows, hours = published.items["D2017-08-01"]
    hours = hours.copy()
    hours["lab_state"] = "fresh"      # the hours of the fixture that are interpolated or held are not the ones this test plants
    for index, changes in {3: {"rows": 11}, 4: {"rows": 5}, 5: {"lab_state": "interpolated"}, 6: {"lab_state": "held"}, 7: {"feed_changes_in_hour": True},
                           8: {"lab_state": "held"}}.items():
        for column, value in changes.items():
            hours.loc[index, column] = value
    report = validate(published, quick_cfg, "D2017-08-01", hours=hours)
    stamp = lambda *indices: [pd.Timestamp(hours.loc[i, "hour"]).isoformat() for i in indices]  # noqa: E731
    expected = {"V20": ([3, 4], 16), "V21": ([4], 5), "V22": ([5], 12), "V23": ([6, 8], 24), "V24": ([7], 12)}
    for rule_id, (indices, row_count) in expected.items():
        found = result(report, rule_id)
        assert (found.hours_affected, found.rows_affected, found.status) == (len(indices), row_count, "warn"), rule_id
        assert [e["hour"] for e in found.examples] == stamp(*indices) and found.severity is Severity.WARNING
    assert "V14" in failing(report) and not {"V20", "V21", "V22", "V23", "V24"} & failing(report)
    untouched = published.items["D2017-08-11"][2]
    clean = validate(published, quick_cfg, "D2017-08-11")
    assert result(clean, "V22").hours_affected == int((untouched["lab_state"] == "interpolated").sum()) > 0
    assert result(clean, "V23").hours_affected == int((untouched["lab_state"] == "held").sum()) > 0
    assert all(result(clean, r).status == "pass" for r in ("V20", "V21", "V24")), "a delivery of complete hours with a steady feed has no such warning"


def test_a_warning_names_at_most_five_hours_but_counts_them_all(published, quick_cfg):
    _entry, _rows, hours = published.items["D2017-08-01"]
    many = hours.copy()
    many["lab_state"] = "held"
    found = result(validate(published, quick_cfg, "D2017-08-01", hours=many), "V23")
    assert found.hours_affected == len(hours) and len(found.examples) == EXAMPLE_LIMIT
    assert [e["hour"] for e in found.examples] == [pd.Timestamp(h).isoformat() for h in hours["hour"].iloc[:EXAMPLE_LIMIT]], "the first hours"


def test_a_sensor_fixed_within_the_hour_is_counted_by_sensor_and_hour(published, quick_cfg):
    _entry, rows, hours = published.items["D2017-08-01"]
    hours = hours.copy()
    hours[["air_flow_04_std", "air_flow_05_std"]] = 1.0       # the two fixed sensors of the fixture are not the ones this test plants
    for column in ("amina_flow_std", "level_03_std"):
        hours.loc[[10, 11], column] = 0.0
    hours.loc[[11, 12], "level_03_std"] = 0.0
    found = result(validate(published, quick_cfg, "D2017-08-01", hours=hours), "I03")
    by_sensor = {e["sensor"]: e["hours"] for e in found.examples}
    assert by_sensor["amina_flow"] == 2 and by_sensor["level_03"] == 3
    assert found.hours_affected == 3 and found.rows_affected == int(hours.loc[[10, 11, 12], "rows"].sum()) and found.passed and found.severity is Severity.INFO


# --- the source -------------------------------------------------------------------------------------------------------------


def source_cfg(cfg, arff: Path, **source):
    return dataclasses.replace(cfg, source=dataclasses.replace(cfg.source, path=arff, max_bytes=LIMIT, **source))


@pytest.mark.parametrize("kind", MALFORMED_KINDS)
def test_each_malformed_source_names_its_rule_and_leaves_every_other_rule_not_evaluated(quick_cfg, malformed, small_arff, kind):
    arff = malformed(kind)
    try:
        if kind == "wrong_hash":
            check_source(source_cfg(quick_cfg, small_arff, accepted_bytes=small_arff.stat().st_size, accepted_sha256="0" * 64))
        else:
            read_arff(arff, source_cfg(quick_cfg, arff))
    except SourceError as error:
        outcome = error
    else:  # pragma: no cover - every variant breaks its rule (tests/contract/test_source.py)
        pytest.fail(f"{kind} did not fail")
    report = validate_source(outcome, run_key="run-1", source_sha256="")
    rule_id = MALFORMED_RULE[kind]
    assert failing(report) == {rule_id} and report.blocking_failed and result(report, rule_id).examples
    before = [r for r in RULES if r.startswith("V0") and r < rule_id]
    assert all(result(report, r).passed for r in before) and [r.rule_id for r in report.results] == [*before, rule_id]
    assert set(report.not_evaluated) == set(RULES) - {r.rule_id for r in report.results} and "V10" in report.not_evaluated
    for example in result(report, rule_id).examples:
        assert "path" not in example and str(arff.parent) not in json.dumps(example), "no path of this machine"


def test_a_clean_read_passes_the_source_rules_and_counts_the_missing_hours(canonical, fixture_truth):
    report = validate_source(canonical.report, run_key="run-1", source_sha256="a" * 64)
    assert not report.blocking_failed and report.not_evaluated == () and report.source_sha256 == "a" * 64
    assert [r.rule_id for r in report.results] == ["V01", "V02", "V03", "V04", "V05", "V06", "V07", "I01"]
    missing = result(report, "I01")
    assert (missing.hours_affected, missing.passed, missing.aggregation, missing.scope) == (fixture_truth.counts["missing_hours"], True, Aggregation.SOURCE, "source")
    assert missing.hours_affected == 318 and all(r.status == "pass" for r in report.results)


def test_a_rule_that_is_not_a_blocking_rule_of_the_source_is_refused(quick_cfg):
    with pytest.raises(ValueError, match="V10 no es una regla bloqueante de la fuente"):
        validate_source(SourceError("V10", "x"), run_key="run-1")


# --- the rules of the model: the interface their tasks use -------------------------------------------------------------------------


def test_the_rules_of_the_model_are_added_in_order_and_once(published, quick_cfg):
    report = validate(published, quick_cfg, "D2017-08-01")
    results = [model_result("M02", passed=True), model_result("I04", passed=False, rows=3, examples=[{"horizon": 0, "count": 3}]),
               model_result("M01", passed=False, examples=[{"horizon": 0, "mae_v1": 0.2, "persistence_mae_v1": 0.5}])]
    added = add_results(report, results)
    assert [r.rule_id for r in added.results][-3:] == ["I04", "M01", "M02"] and not report.blocking_failed and added.blocking_failed
    i04 = result(added, "I04")
    assert i04.passed and i04.severity is Severity.INFO, "an informative rule always passes"
    assert result(added, "M01").aggregation is Aggregation.LATEST and result(added, "M02").aggregation is Aggregation.PER_RUN
    with pytest.raises(ValueError, match="ya está en el reporte"):
        add_results(added, [model_result("M02", passed=True)])
    with pytest.raises(ValueError, match="no es una regla del modelo"):
        model_result("V10", passed=True)
    assert tuple(RULES[r].scope for r in MODEL_RULES) == ("model",) * len(MODEL_RULES)


def test_the_report_of_a_run_is_the_source_then_the_delivery_in_the_order_of_the_plan(published, quick_cfg, canonical):
    source = validate_source(canonical.report, run_key="run-1", source_sha256="b" * 64)
    delivery = validate(published, quick_cfg, "D2017-08-01")
    combined = combine_reports(source, delivery)
    assert [r.rule_id for r in combined.results] == [r for r in RULES if r in {x.rule_id for x in [*source.results, *delivery.results]}]
    assert combined.source_sha256 == "b" * 64 and combined.delivery_id == "D2017-08-01" and combined.rows_delivery == delivery.rows_delivery
    assert combined.not_evaluated == ()
    failed_source = validate_source(SourceError("V04", "campos", [{"rule_id": "V04", "line": 9}]), run_key="run-1")
    assert set(combine_reports(failed_source, delivery).not_evaluated) == set(failed_source.not_evaluated) - {r.rule_id for r in delivery.results}


def test_a_rejected_run_names_the_blocking_rules_that_failed(published, quick_cfg):
    arguments, _expected, _reason = case_v10_out_of_order(published, quick_cfg)
    report = validate(published, quick_cfg, **arguments)
    error = ValidationError(report)
    assert error.report is report and "run-1" in str(error) and "V10" in str(error) and "V12" not in str(error)


# --- the report files ------------------------------------------------------------------------------------------------------------


def test_the_report_is_written_as_json_and_markdown_with_a_copy_per_run_and_read_back(published, quick_cfg, canonical, tmp_path):
    report = combine_reports(validate_source(canonical.report, run_key="run-1", source_sha256="c" * 64), validate(published, quick_cfg, "D2017-08-01"))
    latest_json, latest_md = write_report(report, tmp_path)
    assert (latest_json, latest_md) == (tmp_path / "latest.json", tmp_path / "latest.md")
    assert (tmp_path / "history" / "run-1.json").read_bytes() == latest_json.read_bytes() and (tmp_path / "history" / "run-1.md").read_bytes() == latest_md.read_bytes()
    document = json.loads(latest_json.read_text(encoding="utf-8"))
    assert list(document) == ["run_key", "source_sha256", "delivery_id", "rows_delivery", "hours_delivery", "blocking_failed", "not_evaluated", "results"]
    assert {r["rule_id"]: r["aggregation"] for r in document["results"]} == {r.rule_id: r.aggregation.value for r in report.results}
    assert set(document["results"][0]) == {"rule_id", "name_es", "severity", "scope", "aggregation", "status", "rows_affected", "hours_affected", "examples"}
    assert read_report(latest_json) == report == read_report(tmp_path / "history" / "run-1.json")
    text = latest_md.read_text(encoding="utf-8")
    assert text.startswith("# Reporte de validación") and "Aceptado: ninguna regla bloqueante falla." in text
    assert "| V10 |" in text and "| I01 |" in text and "horas" in text and text.endswith("\n") and "\r" not in text


def test_a_rejected_report_says_so_and_lists_what_was_not_evaluated(tmp_path):
    report = validate_source(SourceError("V05", "fecha", [{"rule_id": "V05", "line": 12, "column": "hour"}]), run_key="run-2")
    write_report(report, tmp_path)
    text = (tmp_path / "latest.md").read_text(encoding="utf-8")
    assert "Rechazado: hay reglas bloqueantes que fallan." in text and "## No evaluadas" in text and "V10" in text and "## Ejemplos" in text
    assert "| V05 |" in text and "falla" in text
    assert read_report(tmp_path / "latest.json") == report


def test_a_run_key_that_is_not_a_file_name_is_refused_before_writing(tmp_path):
    report = dataclasses.replace(validate_source(SourceError("V04", "x"), run_key="ok"), run_key="../escape")
    with pytest.raises(ValueError, match="no sirve como nombre de archivo"):
        write_report(report, tmp_path)
    assert not any(tmp_path.iterdir())
