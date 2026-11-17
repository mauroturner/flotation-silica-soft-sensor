"""The five JSON files the personal site copies (U15, AC27; RF23; plan, section 21; D26): their schema (written here as dataclasses of their own), the cumulative rules read once, the
manifest written last, a set mixed by a failure refused, nothing of the test before the seal and every figure the one of the Parquet files or of the summary of the same run.
Changing their shape after publication is item 3 of the risk list."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
import types
import typing
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from flotsilica import site_export, texts
from flotsilica.dashboard.semantic_model import MODEL
from flotsilica.export import export_star_schema
from flotsilica.ingest import ATTRIBUTION
from flotsilica.site_export import (
    MANIFEST_FILE,
    REQUIRED_STAR,
    SITE_FILES,
    SiteExportError,
    SiteSetError,
    export_site,
    export_summary,
    read_site,
    verify_site,
)
from flotsilica.tracking import track
from flotsilica.validate import RULES
from flotsilica.warehouse import connect
from tests.fixtures.history import copy_history, without_sealed_rows


# --- the schema of the plan, section 21, as dataclasses: a field with a default may be missing, every other is exact ---------------------------------------


@dataclasses.dataclass(frozen=True)
class Envelope:
    schema_version: int
    run_key: str
    as_of: str
    source_sha256: str
    attribution: str


@dataclasses.dataclass(frozen=True)
class MaeSet:
    model: float | None
    persistence: float | None
    b_star: float | None


@dataclasses.dataclass(frozen=True)
class Chosen:
    family: str
    feature_set: str
    target: str


@dataclasses.dataclass(frozen=True)
class Headline:
    rows: int
    hours: int
    missing_hours: int
    partial_hours: int
    period_start: str | None
    period_end: str | None
    fresh_share: float | None
    interpolated_hours: int
    held_hours: int
    latency_hours: int
    test_hours: int
    test_fresh_hours: int
    mae: dict[str, MaeSet]
    b_star: dict[str, str]
    chosen: dict[str, Chosen]
    coverage_h0: float | None
    bias_h0: float | None
    sensors_passing_gate: int | None


@dataclasses.dataclass(frozen=True)
class Criterion:
    id: str
    name_es: str
    passed: bool | None
    value: float | None
    baseline_value: float | None
    ci_low: float | None
    ci_high: float | None
    threshold_es: str
    seen_by_research: str
    seen_by_planner: str
    verdict_es: str


@dataclasses.dataclass(frozen=True)
class SealInfo:
    config_sha256: str
    launch_run_key: str
    test_run_key: str | None
    test_as_of: str | None


@dataclasses.dataclass(frozen=True)
class Summary(Envelope):
    status: str
    evaluation_status: str
    headline: Headline
    criteria: list[Criterion]
    seal: SealInfo
    sealed_from: str = ""


@dataclasses.dataclass(frozen=True)
class Sampling:
    rows_per_hour: int
    sensors: int
    lab_columns: int
    seconds_per_row: int


@dataclasses.dataclass(frozen=True)
class BlockStates:
    block: str
    label_es: str
    fresh: int
    held: int
    interpolated: int
    missing: int
    pending: int


@dataclasses.dataclass(frozen=True)
class InterpolatedRun:
    hours: list[str]
    values: list[float | None]
    start_value: float | None
    end_value: float | None
    slope_per_hour: float | None


@dataclasses.dataclass(frozen=True)
class HeldRuns:
    longest_hours: int
    runs_3h_or_more: int
    hours_in_them: int


@dataclasses.dataclass(frozen=True)
class Gap:
    first: str
    last: str
    hours: int


@dataclasses.dataclass(frozen=True)
class Feed:
    median_unchanged_hours: float | None
    max_unchanged_hours: float | None


@dataclasses.dataclass(frozen=True)
class Acf:
    lag: int
    r: float | None


@dataclasses.dataclass(frozen=True)
class Target:
    mean: float | None
    sd: float | None
    p05: float | None
    p50: float | None
    p95: float | None
    acf: list[Acf]


@dataclasses.dataclass(frozen=True)
class SplitBlock:
    block: str
    label_es: str
    first: str
    last: str
    hours: int
    fresh: int


@dataclasses.dataclass(frozen=True)
class Data(Envelope):
    sampling: Sampling
    states_by_block: list[BlockStates]
    interpolated_run: InterpolatedRun | None
    held_runs: HeldRuns
    gap: Gap | None
    feed: Feed
    target: Target
    split: list[SplitBlock]


@dataclasses.dataclass(frozen=True)
class Method:
    method: str
    label_es: str
    mae_v1: float | None
    mae_v2: float | None
    mae_test: float | None
    ci_low_vs_b_star: float | None
    ci_high_vs_b_star: float | None


@dataclasses.dataclass(frozen=True)
class Horizon:
    horizon: int
    label_es: str
    chosen: Chosen
    b_star: str
    b2_k: int
    methods: list[Method]


@dataclasses.dataclass(frozen=True)
class Candidate:
    horizon: int
    family: str
    feature_set: str
    target: str
    min_samples_leaf: int
    mae_v1: float | None
    chosen: bool


@dataclasses.dataclass(frozen=True)
class Latency:
    latency_hours: int
    mae_model: float | None
    mae_persistence: float | None
    ci_low: float | None
    ci_high: float | None


@dataclasses.dataclass(frozen=True)
class Leakage:
    random_split_r2: float | None
    block_r2: float | None
    random_split_mae: float | None
    block_mae: float | None
    iron_control_mae_v2: float | None
    sealed_mae_v2: float | None


@dataclasses.dataclass(frozen=True)
class Gate:
    min_importance_mae: float | None
    min_abs_spearman: float | None


@dataclasses.dataclass(frozen=True)
class Sensor:
    sensor: str
    name_es: str
    importance_v1: float | None
    importance_v2: float | None
    sign_stable: bool
    passes: bool
    test_sign_kept: bool | None
    label_es: str


@dataclasses.dataclass(frozen=True)
class Curve:
    sensor: str
    grid: list[float | None]
    estimate: list[float | None]


@dataclasses.dataclass(frozen=True)
class Interval:
    coverage_target: float | None
    half_width: dict[str, float | None]
    coverage_test: float | None


@dataclasses.dataclass(frozen=True)
class Algorithms(Envelope):
    horizons: list[Horizon]
    selection: list[Candidate]
    latency: list[Latency]
    leakage: Leakage
    gate: Gate
    sensitivity: list[Sensor]
    pd_curves: list[Curve]
    interval: Interval


@dataclasses.dataclass(frozen=True)
class HourColumns:
    hour: list[str]
    estimate: list[float | None]
    low: list[float | None]
    high: list[float | None]
    persistence: list[float | None]
    actual: list[float | None]
    state: list[str]


@dataclasses.dataclass(frozen=True)
class Day:
    date: str
    mae_model: float | None
    mae_persistence: float | None
    fresh_hours: int


@dataclasses.dataclass(frozen=True)
class Week:
    week: int
    horizon: int
    mae_model: float | None
    mae_persistence: float | None
    mae_b_star: float | None


@dataclasses.dataclass(frozen=True)
class ExampleDay:
    date: str


@dataclasses.dataclass(frozen=True)
class ExampleDays:
    median: ExampleDay | None
    worst: ExampleDay | None
    best: ExampleDay | None


@dataclasses.dataclass(frozen=True)
class Api:
    endpoint: str
    inputs_es: str
    outputs_es: str


@dataclasses.dataclass(frozen=True)
class Operation(Envelope):
    test_hours: HourColumns
    daily: list[Day]
    weekly: list[Week]
    example_days: ExampleDays
    api: Api


@dataclasses.dataclass(frozen=True)
class RuleRow:
    rule_id: str
    name_es: str
    severity: str
    scope: str
    aggregation: str
    status: str
    rows: int
    hours: int


@dataclasses.dataclass(frozen=True)
class Totals:
    rows: int
    hours: int
    missing_hours: int
    deliveries_loaded: int
    deliveries_rejected: int


@dataclasses.dataclass(frozen=True)
class ValidationRules(Envelope):
    rules: list[RuleRow]
    totals: Totals


@dataclasses.dataclass(frozen=True)
class FileEntry:
    bytes: int
    sha256: str


@dataclasses.dataclass(frozen=True)
class Manifest(Envelope):
    files: dict[str, FileEntry]


SCHEMAS = {"summary.json": Summary, "data.json": Data, "algorithms.json": Algorithms, "operation.json": Operation, "validation_rules.json": ValidationRules, "manifest.json": Manifest}


def conforms(value: Any, tp: Any, where: str = "$") -> list[str]:
    """What is wrong in `value` against the type `tp` (empty if nothing): the keys of a dataclass are exactly its fields (those with a default may be missing)."""
    origin, args = typing.get_origin(tp), typing.get_args(tp)
    if origin in (typing.Union, types.UnionType):
        if value is None:
            return [] if type(None) in args else [f"{where}: null"]
        options = [conforms(value, option, where) for option in args if option is not type(None)]
        return [] if any(not found for found in options) else options[0]
    if dataclasses.is_dataclass(tp):
        if not isinstance(value, dict):
            return [f"{where}: not an object"]
        hints, fields = typing.get_type_hints(tp), {f.name: f for f in dataclasses.fields(tp)}
        required = {n for n, f in fields.items() if f.default is dataclasses.MISSING}
        problems = [f"{where}: missing {sorted(required - set(value))}"] if required - set(value) else []
        problems += [f"{where}: unexpected {sorted(set(value) - set(fields))}"] if set(value) - set(fields) else []
        return problems + [p for n in set(value) & set(fields) for p in conforms(value[n], hints[n], f"{where}.{n}")]
    if origin is list:
        return [f"{where}: not a list"] if not isinstance(value, list) else [p for i, v in enumerate(value) for p in conforms(v, args[0], f"{where}[{i}]")]
    if origin is dict:
        if not isinstance(value, dict):
            return [f"{where}: not an object"]
        return [p for k, v in value.items() for p in conforms(v, args[1], f"{where}.{k}")]
    ok = {int: lambda v: isinstance(v, int) and not isinstance(v, bool), float: lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
          str: lambda v: isinstance(v, str), bool: lambda v: isinstance(v, bool)}[tp](value)
    return [] if ok else [f"{where}: {value!r} is not {tp.__name__}"]


# --- helpers ---------------------------------------------------------------------------------------------------------------------------


def docs_of(folder: Path) -> dict[str, dict]:
    return {name: json.loads((folder / name).read_text(encoding="utf-8")) for name in (*SITE_FILES, MANIFEST_FILE)}


@pytest.fixture(scope="module")
def docs(site_files) -> dict[str, dict]:
    return docs_of(site_files.out_dir)


def warehouse_copy(site_files, folder: Path):
    """An open connection to a copy of the warehouse of the small history (which holds the star tables)."""
    folder.mkdir(parents=True, exist_ok=True)
    copy = folder / "warehouse.sqlite"
    shutil.copy2(site_files.history.paths.db, copy)
    return connect(copy)


def every_string(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in every_string(v)]
    if isinstance(value, list):
        return [s for v in value for s in every_string(v)]
    return []


# --- the RED of U15 --------------------------------------------------------------------------------------------------------------------


def test_cumulative_rules_are_read_once_from_the_latest_loaded_run(site_files, tmp_path):
    """Project 03, D94: a rule whose aggregation is ``latest`` (or ``source``) is read once, from the latest loaded run that recorded it; a ``per_run`` rule is summed over the
    loaded runs; a rule no loaded run recorded is ``not_evaluated``; a run whose delivery is not loaded does not count."""
    conn = warehouse_copy(site_files, tmp_path)
    try:
        loaded = [r[0] for r in conn.execute("SELECT run_key FROM deliveries WHERE status = 'loaded' ORDER BY as_of")][:3]
        assert len(loaded) == 3
        conn.execute("DELETE FROM validation_results")
        conn.execute("INSERT INTO deliveries (delivery_id, kind, first_hour, last_hour, as_of, rows, hours, sha256, status, run_key) "
                     "VALUES ('D-late', 'daily', '2099-01-01 00:00:00', '2099-01-01 23:00:00', '2099-01-02 00:00:00', 1, 1, 'x', 'rejected', 'r99')")
        rows = []
        for i, run in enumerate([*loaded, "r99"], start=1):
            for rule_id, count in (("I02", 100 * i), ("V20", i), ("V01", 7), ("I01", 1000 + i)):
                rule = RULES[rule_id]
                rows.append((run, rule_id, rule.name_es, rule.severity.value, rule.scope, rule.aggregation.value, 1, count, count + 1, "[]"))
        conn.executemany("INSERT INTO validation_results (run_key, rule_id, name_es, severity, scope, aggregation, passed, rows_affected, hours_affected, examples_json) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        export_site(conn, tmp_path / "site", site_files.run, site_files.history.sealed, **site_files.kwargs)
    finally:
        conn.close()
    doc = docs_of(tmp_path / "site")["validation_rules.json"]
    by_id = {r["rule_id"]: r for r in doc["rules"]}
    assert [r["rule_id"] for r in doc["rules"]] == list(RULES)
    assert (by_id["I02"]["aggregation"], by_id["I02"]["rows"], by_id["I02"]["hours"]) == ("latest", 300, 301), "the count of the latest loaded run, read once"
    assert (by_id["V20"]["aggregation"], by_id["V20"]["rows"]) == ("per_run", 1 + 2 + 3), "summed over the loaded runs only"
    assert (by_id["V01"]["aggregation"], by_id["V01"]["rows"]) == ("source", 7)
    assert (by_id["I01"]["aggregation"], by_id["I01"]["rows"]) == ("source", 1003)
    assert by_id["V10"]["status"] == "not_evaluated" and by_id["I02"]["status"] == "pass"
    assert (doc["totals"]["deliveries_loaded"], doc["totals"]["deliveries_rejected"]) == (4, 1)


def test_a_failure_in_the_middle_of_the_writes_leaves_a_set_that_is_refused(site_files, tmp_path, monkeypatch):
    """The five files are replaced one by one and the manifest last, the old one removed before the first: a failure after two of them leaves two files of one export and three
    of the other, with no manifest, which ``verify_site`` names and ``read_site`` refuses; the next complete export makes it one set again."""
    folder = tmp_path / "site"
    shutil.copytree(site_files.out_dir, folder)
    other = dataclasses.replace(site_files.run, run_key="r-other")            # another export: other bytes in every file
    real, written = site_export.write_atomic, []

    def failing(path, data):
        if len(written) == 2:
            raise OSError("disk full, by the test")
        written.append(Path(path).name)
        return real(path, data)

    conn = connect(site_files.history.paths.db)
    try:
        monkeypatch.setattr(site_export, "write_atomic", failing)
        with pytest.raises(OSError, match="disk full"):
            export_site(conn, folder, other, site_files.history.sealed, **site_files.kwargs)
        assert written == list(SITE_FILES[:2])
        assert [json.loads((folder / name).read_text(encoding="utf-8"))["run_key"] for name in SITE_FILES] == ["r-other"] * 2 + [site_files.run.run_key] * 3, "a real mix"
        assert not (folder / MANIFEST_FILE).exists()
        assert any(MANIFEST_FILE in problem for problem in verify_site(folder))
        with pytest.raises(SiteSetError, match=MANIFEST_FILE):
            read_site(folder)
        monkeypatch.setattr(site_export, "write_atomic", real)
        export_site(conn, folder, other, site_files.history.sealed, **site_files.kwargs)
    finally:
        conn.close()
    assert verify_site(folder) == [] and read_site(folder).manifest["run_key"] == "r-other"


# --- the schema ------------------------------------------------------------------------------------------------------------------------


def test_each_file_has_the_envelope_and_the_schema_of_the_plan_and_all_five_fit_in_200_kb(site_files, docs):
    total = 0
    for name in SITE_FILES:
        data = (site_files.out_dir / name).read_bytes()
        total += len(data)
        assert data.endswith(b"\n") and data.decode("utf-8") == json.dumps(docs[name], ensure_ascii=False, sort_keys=True, indent=1) + "\n", name
        assert conforms(docs[name], SCHEMAS[name]) == [], name
        assert "CC0" in docs[name]["attribution"] and docs[name]["attribution"] == ATTRIBUTION
        assert (docs[name]["run_key"], docs[name]["as_of"]) == (site_files.run.run_key, site_files.run.as_of.strftime("%Y-%m-%d %H:%M:%S"))
        assert docs[name]["source_sha256"] == site_files.history.sealed.source_sha256 and docs[name]["schema_version"] == 1
    assert conforms(docs[MANIFEST_FILE], Manifest) == []
    assert total <= site_files.cap == 204800
    summary = docs["summary.json"]
    assert [c["id"] for c in summary["criteria"]] == [f"C{i:02d}" for i in range(1, 11)] and list(summary["headline"]["mae"]) == ["h0", "h1", "h2"]
    assert len(docs["algorithms.json"]["sensitivity"]) == 19 and len(docs["algorithms.json"]["horizons"]) == 3
    assert len(docs["data.json"]["target"]["acf"]) == site_export.ACF_LAGS and [b["block"] for b in docs["data.json"]["split"]] == ["train", "valid_v1", "valid_v2", "test"]
    assert conforms({**docs["summary.json"], "extra": 1}, Summary) and conforms({k: v for k, v in docs["summary.json"].items() if k != "seal"}, Summary), "the schema is exact"


def test_every_figure_is_the_one_of_the_parquet_files_and_of_the_summary_of_the_same_run(site_files, docs, star_files):
    out = star_files.out_dir
    metrics = pd.read_parquet(out / "fact_method_metrics.parquet")
    test = metrics[(metrics["scope"] == "test") & (metrics["seal_state"] == "sealed")].set_index(["horizon_key", "method_key"])
    model = pd.read_parquet(out / "dim_model.parquet").set_index("horizon_key")
    headline, algorithms = docs["summary.json"]["headline"], docs["algorithms.json"]
    assert docs["summary.json"]["evaluation_status"] == "sealed"
    for h in range(3):
        b_star = model.loc[h, "b_star"]
        assert headline["mae"][f"h{h}"] == {"model": round(test.loc[(h, "model"), "mae"], 3), "persistence": round(test.loc[(h, "b1_persistence"), "mae"], 3),
                                            "b_star": round(test.loc[(h, b_star), "mae"], 3)}
        assert headline["b_star"][f"h{h}"] == b_star and algorithms["interval"]["half_width"][f"h{h}"] == round(model.loc[h, "half_width"], 3)
        assert headline["chosen"][f"h{h}"]["family"] == model.loc[h, "family"]
        shown = {m["method"]: m for m in algorithms["horizons"][h]["methods"]}
        assert {m: v["mae_test"] for m, v in shown.items()} == {m: round(test.loc[(h, m), "mae"], 3) for m in shown if (h, m) in test.index}
    assert headline["coverage_h0"] == round(test.loc[(0, "model"), "coverage"], 3) == algorithms["interval"]["coverage_test"]
    assert headline["bias_h0"] == round(test.loc[(0, "model"), "bias"], 3)
    sensitivity = pd.read_parquet(out / "fact_sensitivity.parquet").set_index("sensor_key")
    assert headline["sensors_passing_gate"] == int(sensitivity["passes"].sum())
    assert {s["sensor"]: s["importance_v1"] for s in algorithms["sensitivity"]} == {k: round(v, 4) for k, v in sensitivity["importance_v1"].items()}
    selection = pd.read_parquet(out / "fact_selection.parquet")
    assert sorted((s["horizon"], s["family"], s["feature_set"], s["target"], s["min_samples_leaf"], s["mae_v1"]) for s in algorithms["selection"]) == \
        sorted((int(r.horizon_key), r.family, r.feature_set, r.target, int(r.min_samples_leaf), round(r.mae_v1, 4)) for r in selection.itertuples())
    weekly = pd.read_parquet(out / "fact_weekly_mae.parquet")
    weekly = weekly[weekly["seal_state"] == "sealed"].set_index(["test_week", "horizon_key", "method_key"])
    for w in docs["operation.json"]["weekly"]:
        assert w["mae_model"] == round(weekly.loc[(w["week"], w["horizon"], "model"), "mae"], 3)
        assert w["mae_persistence"] == round(weekly.loc[(w["week"], w["horizon"], "b1_persistence"), "mae"], 3)
    estimate = pd.read_parquet(out / "fact_estimate.parquet")
    hours = pd.read_parquet(out / "dim_hour.parquet").set_index("hour_key")
    mine = estimate[(estimate["horizon_key"] == 0) & (estimate["status"] == "ok") & (estimate["hour_key"].map(hours["block"]) == "test")].sort_values("hour_key")
    th = docs["operation.json"]["test_hours"]
    assert th["estimate"] == [round(v, 2) for v in mine["estimate"]] and th["actual"] == [None if pd.isna(v) else round(v, 2) for v in mine["actual"]]
    assert th["state"] == list(mine["hour_key"].map(hours["lab_state"])) and len(th["hour"]) == len(mine) > 0
    states = hours[hours["block"] == "train"]["lab_state"].value_counts()
    train = next(b for b in docs["data.json"]["states_by_block"] if b["block"] == "train")
    assert {k: train[k] for k in ("fresh", "held", "interpolated")} == {k: int(states.get(k, 0)) for k in ("fresh", "held", "interpolated")}
    assert docs["data.json"]["split"][0]["fresh"] == train["fresh"]
    assert headline["rows"] == int(hours["rows"].sum()) and headline["interpolated_hours"] == int((hours["lab_state"] == "interpolated").sum())
    criteria = pd.read_parquet(out / "fact_evaluation_summary.parquet").set_index("criterion_id")
    sealed = criteria[criteria["seal_state"] == "sealed"]
    assert [c["verdict_es"] for c in docs["summary.json"]["criteria"]] == list(sealed.loc[[f"C{i:02d}" for i in range(1, 11)], "verdict_es"])


def test_the_data_file_says_what_the_fixture_planted(docs):
    data = docs["data.json"]
    assert data["sampling"] == {"rows_per_hour": 12, "sensors": 19, "lab_columns": 4, "seconds_per_row": 300}
    run = data["interpolated_run"]
    assert len(run["hours"]) == len(run["values"]) >= 2 and run["slope_per_hour"] == round((run["end_value"] - run["start_value"]) / (len(run["hours"]) + 1), 4)
    assert all(abs(v - (run["start_value"] + run["slope_per_hour"] * (i + 1))) <= 0.05 for i, v in enumerate(run["values"])), "a straight line between two analyses (D05)"
    assert data["gap"] == {"first": "2017-03-16 06:00:00", "last": "2017-03-29 11:00:00", "hours": 318}, "the 318 hours of March that the file lacks"
    assert data["held_runs"]["longest_hours"] >= 3 and data["held_runs"]["runs_3h_or_more"] >= 1 and data["held_runs"]["hours_in_them"] >= 3
    assert data["feed"]["max_unchanged_hours"] >= data["feed"]["median_unchanged_hours"] >= 0 and data["target"]["p05"] <= data["target"]["p50"] <= data["target"]["p95"]
    assert all(-1 <= a["r"] <= 1 for a in data["target"]["acf"] if a["r"] is not None) and data["target"]["acf"][0]["r"] > 0.3, "the target is autoregressive"
    for block in data["states_by_block"]:
        assert block["label_es"] == texts.BLOCKS_ES[block["block"]]


def test_the_operation_file_holds_the_test_hours_the_days_and_the_rule_of_the_example_days(docs):
    operation = docs["operation.json"]
    hours = operation["test_hours"]
    assert {len(v) for v in hours.values()} == {len(hours["hour"])} and hours["state"] and set(hours["state"]) <= {"fresh", "held", "interpolated"}
    assert all((a is None) == (s != "fresh") for a, s in zip(hours["actual"], hours["state"], strict=True)), "an analysis that is not new is no measurement (D05)"
    assert all(lo <= e <= hi for lo, e, hi in zip(hours["low"], hours["estimate"], hours["high"], strict=True))
    [day] = operation["daily"]                                       # the test of the small history is one day
    fresh = [(e, p, a) for e, p, a in zip(hours["estimate"], hours["persistence"], hours["actual"], strict=True) if a is not None]
    assert day["fresh_hours"] == len(fresh) and day["mae_model"] == pytest.approx(sum(abs(e - a) for e, _p, a in fresh) / len(fresh), abs=0.01)
    ranked = sorted((d for d in operation["daily"] if d["mae_model"] is not None), key=lambda d: (d["mae_model"], d["date"]))
    assert operation["example_days"] == {"median": {"date": ranked[(len(ranked) - 1) // 2]["date"]}, "worst": {"date": ranked[-1]["date"]}, "best": {"date": ranked[0]["date"]}}
    assert operation["api"] == {"endpoint": texts.API_ENDPOINT, "inputs_es": texts.API_INPUTS_ES, "outputs_es": texts.API_OUTPUTS_ES}
    assert [w["week"] for w in operation["weekly"]] == [1, 1, 1] and [w["horizon"] for w in operation["weekly"]] == [0, 1, 2]


def test_the_example_days_follow_their_fixed_rule():
    days = [{"date": f"2017-08-0{i}", "mae_model": m, "mae_persistence": 0.0, "fresh_hours": 1} for i, m in zip(range(1, 6), (0.5, 0.2, 0.9, None, 0.2), strict=True)]
    assert site_export._example_days(days) == {"median": {"date": "2017-08-05"}, "worst": {"date": "2017-08-03"}, "best": {"date": "2017-08-02"}}
    assert site_export._example_days([]) == {"median": None, "worst": None, "best": None}


# --- the manifest ----------------------------------------------------------------------------------------------------------------------


def test_the_manifest_is_written_last_and_names_the_five_files_with_their_bytes_and_sha256(site_files, docs, tmp_path, monkeypatch):
    manifest = docs[MANIFEST_FILE]
    assert sorted(manifest["files"]) == sorted(SITE_FILES) and verify_site(site_files.out_dir) == []
    for name, entry in manifest["files"].items():
        data = (site_files.out_dir / name).read_bytes()
        assert entry == {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    assert {k: manifest[k] for k in ("run_key", "as_of", "source_sha256", "attribution")} == {k: docs["summary.json"][k] for k in ("run_key", "as_of", "source_sha256", "attribution")}
    order, real = [], site_export.write_atomic
    monkeypatch.setattr(site_export, "write_atomic", lambda path, data: (order.append(Path(path).name), real(path, data))[1])
    conn = connect(site_files.history.paths.db)
    try:
        export_site(conn, tmp_path / "again", site_files.run, site_files.history.sealed, **site_files.kwargs)
    finally:
        conn.close()
    assert order == [*SITE_FILES, MANIFEST_FILE], "the manifest is the last write"
    assert {n: (tmp_path / "again" / n).read_bytes() for n in SITE_FILES} == {n: (site_files.out_dir / n).read_bytes() for n in SITE_FILES}, "the same run, the same bytes"
    reading = read_site(site_files.out_dir)
    assert reading.summary == docs["summary.json"] and reading.validation_rules == docs["validation_rules.json"] and reading.manifest == manifest


def test_verify_site_names_each_way_a_folder_is_not_one_export(site_files, tmp_path):
    def broken(change) -> list[str]:
        folder = tmp_path / f"case{len(list(tmp_path.iterdir()))}"
        shutil.copytree(site_files.out_dir, folder)
        change(folder)
        return verify_site(folder)

    assert any("falta data.json" in p for p in broken(lambda f: (f / "data.json").unlink()))
    assert any("operation.json no es el que nombra" in p for p in broken(lambda f: (f / "operation.json").write_bytes((f / "operation.json").read_bytes() + b" ")))
    assert any("no se puede leer" in p and MANIFEST_FILE in p for p in broken(lambda f: (f / MANIFEST_FILE).write_text("{", encoding="utf-8")))

    def drop_one(folder: Path) -> None:
        manifest = json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))
        del manifest["files"]["data.json"]
        (folder / MANIFEST_FILE).write_text(json.dumps(manifest), encoding="utf-8")

    assert any("no los cinco archivos" in p for p in broken(drop_one))

    def other_envelope(folder: Path) -> None:
        manifest = json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))
        manifest["run_key"] = "r-other"
        (folder / MANIFEST_FILE).write_text(json.dumps(manifest), encoding="utf-8")

    assert any("no lleva el envoltorio" in p for p in broken(other_envelope))
    with pytest.raises(SiteSetError, match="falta"):
        read_site(tmp_path / "nothing-here")


def test_rewriting_the_summary_keeps_one_export_and_is_refused_over_a_mixed_folder_or_another_run(site_files, tmp_path):
    folder = tmp_path / "site"
    shutil.copytree(site_files.out_dir, folder)
    before = {n: (folder / n).read_bytes() for n in SITE_FILES}
    conn = connect(site_files.history.paths.db)
    try:
        export_summary(conn, folder, site_files.run, site_files.history.sealed, **site_files.kwargs)
        assert verify_site(folder) == [] and {n: (folder / n).read_bytes() for n in SITE_FILES} == before, "the same run rewrites the same summary"
        with pytest.raises(SiteExportError, match="otra corrida"):
            export_summary(conn, folder, dataclasses.replace(site_files.run, run_key="r-other"), site_files.history.sealed, **site_files.kwargs)
        (folder / "data.json").write_text("{}\n", encoding="utf-8")
        with pytest.raises(SiteExportError, match="no se reescribe el resumen"):
            export_summary(conn, folder, site_files.run, site_files.history.sealed, **site_files.kwargs)
    finally:
        conn.close()
    with pytest.raises(SiteSetError, match="data.json"):
        read_site(folder)


def test_a_set_over_the_size_cap_writes_nothing(site_files, tmp_path):
    conn = connect(site_files.history.paths.db)
    try:
        with pytest.raises(SiteExportError, match="el tope es 10000: no se escribió ninguno"):
            export_site(conn, tmp_path / "site", site_files.run, site_files.history.sealed, seal_path=site_files.kwargs["seal_path"], max_total_bytes=10_000)
    finally:
        conn.close()
    assert not (tmp_path / "site").exists()


# --- before the seal and what the export reads -----------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pending(small_launched, tmp_path_factory, quick_cfg):
    """The site files of the launch run, when the test has not arrived (the seal has no test part): the star model exported from a copy first."""
    folder = tmp_path_factory.mktemp("pending")
    history = copy_history(small_launched, folder / "history")
    run = history.runs[-1]
    conn = connect(history.paths.db)
    try:
        track(conn, run, history.sealed)
        export_star_schema(conn, folder / "powerbi", MODEL, run, history.sealed, seal_path=history.paths.seal)
        export_site(conn, folder / "site", run, history.sealed, seal_path=history.paths.seal, max_total_bytes=quick_cfg.site.max_total_bytes)
    finally:
        conn.close()
    return types.SimpleNamespace(history=history, run=run, folder=folder, docs=docs_of(folder / "site"))


def assert_nothing_of_the_test(docs: dict[str, dict]) -> None:
    """Every figure of the test is null or empty in the five files; what the launch measured (V1 and V2) is there."""
    summary, algorithms, operation = docs["summary.json"], docs["algorithms.json"], docs["operation.json"]
    assert summary["evaluation_status"] == "pending" and all(conforms(docs[n], SCHEMAS[n]) == [] for n in SITE_FILES)
    assert all(c["passed"] is None and c["value"] is None for c in summary["criteria"]) and summary["seal"]["test_run_key"] is None
    headline = summary["headline"]
    assert {v for h in headline["mae"].values() for v in h.values()} == {None} and (headline["coverage_h0"], headline["bias_h0"], headline["sensors_passing_gate"]) == (None, None, None)
    assert set(operation["test_hours"]) == {"hour", "estimate", "low", "high", "persistence", "actual", "state"} and not any(operation["test_hours"].values())
    assert (operation["daily"], operation["weekly"], operation["example_days"]) == ([], [], {"median": None, "worst": None, "best": None})
    methods = [m for h in algorithms["horizons"] for m in h["methods"]]
    assert methods and all(m["mae_test"] is None and m["ci_low_vs_b_star"] is None for m in methods) and any(m["mae_v1"] is not None and m["mae_v2"] is not None for m in methods)
    assert [row["latency_hours"] for row in algorithms["latency"]] == [2, 3, 4] and all(set(row.values()) <= {None, 2, 3, 4} for row in algorithms["latency"])
    assert algorithms["interval"]["coverage_test"] is None and all(s["test_sign_kept"] is None for s in algorithms["sensitivity"]) and algorithms["leakage"]["sealed_mae_v2"] is not None


def test_before_the_seal_no_result_of_the_test_is_published(pending):
    """Until the test is sealed with this configuration, every figure of the test is null or empty (here the launch's own run, before the test arrives)."""
    assert_nothing_of_the_test(pending.docs)
    assert pending.docs["summary.json"]["headline"]["test_hours"] == 24 and pending.docs["summary.json"]["headline"]["test_fresh_hours"] == 0


def test_a_test_that_is_not_evaluated_yet_publishes_none_of_it_even_if_its_hours_were_estimated(site_files, tmp_path):
    """The hours of the test have their estimates and their analyses here, but the seal has no test part and the warehouse no sealed row: nothing of the test is in the files."""
    history = without_sealed_rows(site_files.history, tmp_path / "unevaluated")
    seal = json.loads(history.paths.seal.read_text(encoding="utf-8"))
    del seal["test"]
    history.paths.seal.write_text(json.dumps(seal), encoding="utf-8")
    conn = connect(history.paths.db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM star_fact_estimate AS e JOIN star_dim_hour AS h ON h.hour_key = e.hour_key WHERE h.block = 'test'").fetchone()[0] > 0
        export_site(conn, tmp_path / "site", site_files.run, history.sealed, seal_path=history.paths.seal, max_total_bytes=site_files.cap)
    finally:
        conn.close()
    assert_nothing_of_the_test(docs_of(tmp_path / "site"))


def test_the_export_checks_every_star_table_its_queries_read_from_one_list():
    source = Path(site_export.__file__).read_text(encoding="utf-8")
    assert set(re.findall(r"\bstar_[a-z_]+", source)) == set(REQUIRED_STAR)


@pytest.mark.parametrize("table", REQUIRED_STAR)
def test_a_missing_star_table_is_refused_by_name_before_any_file_is_written(site_files, tmp_path, table):
    conn = warehouse_copy(site_files, tmp_path)
    try:
        conn.execute(f"DROP TABLE {table}")
        with pytest.raises(SiteExportError, match=table):
            export_site(conn, tmp_path / "site", site_files.run, site_files.history.sealed, **site_files.kwargs)
    finally:
        conn.close()
    assert not (tmp_path / "site").exists()


def test_an_export_before_the_launch_has_no_model_and_writes_nothing(site_files, tmp_path):
    view = site_files.history.sealed
    unregistered = dataclasses.replace(view, model=dataclasses.replace(view.model, model_version="v-not-registered"))
    conn = connect(site_files.history.paths.db)
    try:
        with pytest.raises(SiteExportError, match="no hay un modelo registrado"):
            export_site(conn, tmp_path / "site", site_files.run, unregistered, **site_files.kwargs)
    finally:
        conn.close()
    assert not (tmp_path / "site").exists()


def test_no_published_text_calls_a_sensitivity_a_cause_or_an_action(docs, pending):
    """AC24: every string of the five files, the sealed ones and the pending ones, goes through the review of the words about a sensitivity."""
    strings = [s for doc in (*docs.values(), *pending.docs.values()) for s in every_string(doc)]
    assert len(strings) > 100 and {texts.ASSOCIATION_ES, texts.NO_ASSOCIATION_ES} & set(strings)
    assert [(s, texts.sensitivity_problems(s)) for s in strings if texts.sensitivity_problems(s)] == []
