"""The source as a contract (U04, item 2: the ARFF is untrusted data): the pinned file, the strict reader, the canonical tables and what
they leave out (AC01-AC04; RF01-RF04; V01-V07; D02-D05, D31)."""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import shutil
import types
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

import flotsilica
from flotsilica import ingest
from flotsilica.ingest import (
    INTERIM_MANIFEST,
    LOCK_NAME,
    ROWS_NAME,
    HOURS_NAME,
    InterimError,
    canonical_state,
    fetch_source,
    read_arff,
    read_canonical,
    read_header,
    write_source_lock,
)
from flotsilica.schema import LAB_COLUMNS, SENSORS, SOURCE_HOURS_SCHEMA, SOURCE_ROWS_SCHEMA, SourceError
from tests.fixtures.arff_reader import column, hours_of, parse
from tests.fixtures.make_fixture import MALFORMED_KINDS, MALFORMED_RULE, make_malformed

PACKAGE = Path(flotsilica.__file__).resolve().parent
LIMIT = 1 << 20          # the oversize variant is built for this many bytes (make_malformed's default) and the config below caps the file at it
WORDS = {                # what the message of each variant says: the check that refuses it is the one that reads what it damaged
    "wrong_hash": "R1", "bad_relation": "@RELATION", "missing_attribute": "atributos", "extra_attribute": "atributos", "renamed_attribute": "atributos",
    "numeric_attribute": "STRING", "field_count": "campos", "empty_field": "vacío", "bad_date": "fecha", "minute_not_zero": "fecha",
    "dot_decimal": "número", "text_number": "número", "unsorted": "orden", "hour_over_limit": "rows_per_hour", "long_line": "max_line_bytes",
    "nul_byte": "byte nulo", "bad_utf8": "UTF-8", "oversize": "max_bytes",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): sha(p.read_bytes()) for p in sorted(folder.rglob("*")) if p.is_file()}


def quick_ctx(cfg, tmp_path: Path, arff: Path, **source):
    """A quick-mode context whose source is a copy of `arff` at ``<tmp_path>/data/quick/`` (where its hash is registered) and whose interim
    and raw folders are in `tmp_path`: whatever a task writes is in `tmp_path`."""
    target = tmp_path / "data" / "quick" / "flotation_fixture.arff"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(arff, target)
    paths = dataclasses.replace(cfg.paths, raw_dir=tmp_path / "raw", interim_dir=tmp_path / "interim")
    options = {"path": target, "max_bytes": LIMIT, **source}
    return types.SimpleNamespace(cfg=dataclasses.replace(cfg, paths=paths, source=dataclasses.replace(cfg.source, **options)))


def pinned_ctx(cfg, tmp_path: Path, arff: Path, **source):
    """The same, in the real mode: the size and the hash of `arff` are the accepted ones (unless `source` says otherwise)."""
    pins = {"accepted_bytes": arff.stat().st_size, "accepted_sha256": sha(arff.read_bytes())}
    return quick_ctx(cfg, tmp_path, arff, **{**pins, **source})


# --- AC02: every malformed variant fails its rule and writes nothing ---------------------------------------------------


@pytest.mark.parametrize("kind", MALFORMED_KINDS)
def test_each_malformed_variant_fails_its_rule_and_writes_nothing(quick_cfg, tmp_path, malformed, small_arff, kind):
    ctx = quick_ctx(quick_cfg, tmp_path, malformed(kind))
    if kind == "wrong_hash":       # a quick source whose first hash was registered: another one is V01
        write_source_lock(ctx.cfg.source.path.parent / LOCK_NAME, sha(small_arff.read_bytes()), small_arff.stat().st_size)
    before = snapshot(tmp_path)
    with pytest.raises(SourceError) as error:
        fetch_source(ctx)
    assert error.value.rule_id == MALFORMED_RULE[kind], str(error.value)
    assert error.value.problems and all(p["rule_id"] == MALFORMED_RULE[kind] for p in error.value.problems)
    assert WORDS[kind] in str(error.value), str(error.value)
    assert snapshot(tmp_path) == before, "nothing written: no tables, no manifest, no lock"
    assert not (tmp_path / "interim").exists() and not (tmp_path / "raw").exists()
    assert SourceError.EXIT_CODE == 3


def test_the_variants_that_change_one_row_say_which_line_and_which_column_but_never_show_a_row(quick_cfg, tmp_path, malformed):
    for kind, column_name in (("dot_decimal", "Starch_Flow"), ("text_number", "Starch_Flow"), ("empty_field", "Flotation_Column_01_Level")):
        with pytest.raises(SourceError) as error:
            read_arff(quick_ctx(quick_cfg, tmp_path / kind, malformed(kind)).cfg.source.path, quick_cfg)
        problem = error.value.problems[0]
        assert problem["column"] == column_name or kind == "empty_field", problem
        assert isinstance(problem["line"], int) and problem["line"] > 12
        assert len(json.dumps(error.value.problems)) < 2000 and "'2017-03-10" not in str(error.value)


# --- AC01: the pinned file ---------------------------------------------------------------------------------------------------


def test_a_missing_or_different_file_is_refused_with_v01_and_names_the_runbook_without_writing(quick_cfg, tmp_path, small_arff):
    ctx = pinned_ctx(quick_cfg, tmp_path / "a", small_arff)
    assert fetch_source(ctx)["built"] is True
    for changed in (
        {"accepted_bytes": small_arff.stat().st_size + 1},                       # another size
        {"accepted_sha256": "0" * 64},                                            # another hash
    ):
        run = tmp_path / ("b" + str(len(changed)) + next(iter(changed)))
        ctx = pinned_ctx(quick_cfg, run, small_arff, **changed)
        with pytest.raises(SourceError) as error:
            fetch_source(ctx)
        assert error.value.rule_id == "V01" and "R1" in str(error.value)
        assert snapshot(run) == {"data/quick/flotation_fixture.arff": sha(small_arff.read_bytes())}, "nothing written"
    absent = tmp_path / "c"
    ctx = pinned_ctx(quick_cfg, absent, small_arff)
    ctx.cfg.source.path.unlink()
    with pytest.raises(SourceError) as error:
        fetch_source(ctx)
    assert error.value.rule_id == "V01" and "R1" in str(error.value) and "no existe" in str(error.value)
    assert not (absent / "interim").exists()


def test_the_size_is_checked_before_the_file_is_hashed_and_the_byte_cap_before_it_is_read(quick_cfg, tmp_path, small_arff, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("the file was read before its size was checked")

    monkeypatch.setattr(ingest, "sha256_file", forbidden)
    monkeypatch.setattr(ingest, "_decode", forbidden)
    ctx = pinned_ctx(quick_cfg, tmp_path / "size", small_arff, accepted_bytes=small_arff.stat().st_size + 5)
    with pytest.raises(SourceError, match="V01"):
        fetch_source(ctx)
    ctx = quick_ctx(quick_cfg, tmp_path / "cap", small_arff, max_bytes=small_arff.stat().st_size - 1)
    with pytest.raises(SourceError, match="V03.*max_bytes"):
        fetch_source(ctx)


def test_a_quick_source_registers_its_first_hash_only_after_a_clean_read_and_refuses_any_other(quick_cfg, tmp_path, small_arff, malformed):
    ctx = quick_ctx(quick_cfg, tmp_path, small_arff)
    lock = ctx.cfg.source.path.parent / LOCK_NAME
    assert not lock.exists()
    fetch_source(ctx)
    assert json.loads(lock.read_text(encoding="utf-8")) == {"version": 1, "sha256": sha(small_arff.read_bytes()), "size": small_arff.stat().st_size}
    shutil.copyfile(malformed("dot_decimal"), ctx.cfg.source.path)          # another file at the same place, whose content is also wrong
    before = snapshot(tmp_path)
    with pytest.raises(SourceError, match="V01"):
        fetch_source(ctx)
    assert snapshot(tmp_path) == before
    # a rejected first source registers nothing
    other = quick_ctx(quick_cfg, tmp_path / "other", malformed("dot_decimal"))
    with pytest.raises(SourceError, match="V05"):
        fetch_source(other)
    assert not (other.cfg.source.path.parent / LOCK_NAME).exists()


# --- the canonical tables ---------------------------------------------------------------------------------------------------


def test_source_rows_carry_no_lab_column(quick_cfg, tmp_path, small_arff, small_truth):
    ctx = quick_ctx(quick_cfg, tmp_path, small_arff)
    result = fetch_source(ctx)
    interim = ctx.cfg.paths.interim_dir
    rows = pq.read_table(interim / ROWS_NAME)
    assert rows.schema.equals(SOURCE_ROWS_SCHEMA, check_metadata=False)
    assert rows.column_names == ["row_id", "hour", "row_in_hour", *SENSORS] and not set(rows.column_names) & set(LAB_COLUMNS)
    assert not any("_row_" in name or name in ("is_ramp", "lab_state") for name in rows.column_names)
    assert rows.num_rows == result["rows"] == small_truth.counts["rows"]
    # the laboratory values of the hours are the first row's: the file's silica of rows 2 to n of a ramp hour is nowhere in the tables
    parsed = hours_of(parse(small_arff))
    hours = pq.read_table(interim / HOURS_NAME).to_pandas()
    for name, field in (("silica_pct", "silica"), ("iron_conc_pct", "iron_conc"), ("feed_silica_pct", "feed_silica"), ("feed_iron_pct", "feed_iron")):
        assert list(hours[name]) == pytest.approx([column(parsed[h], field)[0] for h in hours["hour"]], abs=1e-9)
    ramp_hours = [h for h in hours["hour"] if len(set(column(parsed[h], "silica"))) > 1]
    assert len(ramp_hours) >= 3
    later = {v for h in ramp_hours for v in column(parsed[h], "silica")[1:]} - set(hours["silica_pct"])
    stored = set(pd.concat([hours[c] for c in hours.columns if hours[c].dtype == "float64"]).round(9))
    assert later and not (later & stored), "no value of rows 2 to n of the laboratory columns is stored"
    # the files and the manifest: the manifest is written last and names both
    manifest = json.loads((interim / INTERIM_MANIFEST).read_text(encoding="utf-8"))
    assert set(manifest["files"]) == {ROWS_NAME, HOURS_NAME} and manifest["source_sha256"] == sha(small_arff.read_bytes())
    assert {name: sha((interim / name).read_bytes()) for name in manifest["files"]} == manifest["files"]
    assert (interim / INTERIM_MANIFEST).stat().st_mtime_ns >= max((interim / n).stat().st_mtime_ns for n in manifest["files"])


def test_the_canonical_tables_of_the_fixture_have_the_counts_and_values_of_its_truth(canonical, fixture_truth):
    counts, hours, rows = fixture_truth.counts, canonical.hours, canonical.rows
    assert len(rows) == canonical.report.rows == counts["rows"] and len(hours) == canonical.report.hours == counts["hours"]
    assert canonical.report.missing_hours == counts["missing_hours"] == 318 and int(hours["is_partial"].sum()) == counts["partial_hours"] == 2
    assert canonical.report.first_hour == datetime(2017, 3, 10, 1) and canonical.report.last_hour == datetime(2017, 9, 9, 23)
    assert list(hours["hour"]) == list(fixture_truth.hours.index) and list(hours["rows"]) == list(fixture_truth.hours["rows"])
    for name, truth in (("silica_pct", "silica"), ("iron_conc_pct", "iron_conc"), ("feed_silica_pct", "feed_silica"), ("feed_iron_pct", "feed_iron")):
        assert list(hours[name]) == pytest.approx(list(fixture_truth.hours[truth]), abs=1e-9)
    assert hours["hour_key"].iloc[0] == 2017031001 and hours["hour_key"].iloc[-1] == 2017090923
    assert list(rows["row_id"]) == list(range(1, len(rows) + 1)) and rows["row_in_hour"].min() == 1 and rows["row_in_hour"].max() == 12
    assert list(rows.groupby("hour")["row_in_hour"].max()) == list(hours["rows"])
    assert rows.columns.tolist() == SOURCE_ROWS_SCHEMA.names and hours.columns.tolist() == SOURCE_HOURS_SCHEMA.names
    # the aggregates are those of the rows: a sensor's mean over an hour of the file as read
    sample = canonical.read.groupby("hour")["amina_flow"].agg(["mean", "std", "last"])
    assert list(hours["amina_flow_mean"]) == pytest.approx(list(sample["mean"])) and list(hours["amina_flow_std"]) == pytest.approx(list(sample["std"]))
    assert list(hours["amina_flow_last"]) == list(sample["last"])


def test_fetch_source_builds_once_and_repeating_it_changes_nothing(quick_cfg, tmp_path, small_arff):
    ctx = quick_ctx(quick_cfg, tmp_path, small_arff)
    first = fetch_source(ctx)
    interim = ctx.cfg.paths.interim_dir
    before = snapshot(tmp_path)
    stamps = {p.name: p.stat().st_mtime_ns for p in interim.iterdir()}
    second = fetch_source(ctx)
    assert first["built"] is True and second["built"] is False and first["sha256"] == second["sha256"] == sha(small_arff.read_bytes())
    assert (first["rows"], first["hours"]) == (second["rows"], second["hours"])
    assert snapshot(tmp_path) == before and {p.name: p.stat().st_mtime_ns for p in interim.iterdir()} == stamps
    assert canonical_state(interim) == sha(small_arff.read_bytes())


def test_tables_that_do_not_match_their_manifest_are_rebuilt_and_refused_by_the_reader(quick_cfg, tmp_path, small_arff):
    ctx = quick_ctx(quick_cfg, tmp_path, small_arff)
    fetch_source(ctx)
    interim = ctx.cfg.paths.interim_dir
    good_rows, good_hours = read_canonical(interim)
    (interim / HOURS_NAME).write_bytes((interim / HOURS_NAME).read_bytes() + b"x")
    assert canonical_state(interim) is None
    with pytest.raises(InterimError, match=HOURS_NAME):
        read_canonical(interim)
    assert fetch_source(ctx)["built"] is True
    again_rows, again_hours = read_canonical(interim)
    pd.testing.assert_frame_equal(again_rows, good_rows)
    pd.testing.assert_frame_equal(again_hours, good_hours)
    (interim / INTERIM_MANIFEST).unlink()
    assert canonical_state(interim) is None
    with pytest.raises(InterimError, match=INTERIM_MANIFEST):
        read_canonical(interim)
    (interim / INTERIM_MANIFEST).write_text("not json", encoding="utf-8")
    assert canonical_state(interim) is None


def test_a_failure_between_the_tables_and_the_manifest_leaves_tables_that_every_reader_refuses(quick_cfg, tmp_path, small_arff, monkeypatch):
    ctx = quick_ctx(quick_cfg, tmp_path, small_arff)
    interim = ctx.cfg.paths.interim_dir

    def broken(*args, **kwargs):
        raise OSError("disk full")

    real = ingest.write_atomic
    monkeypatch.setattr(ingest, "write_atomic", broken)
    with pytest.raises(OSError, match="disk full"):
        fetch_source(ctx)
    assert (interim / ROWS_NAME).exists() and not (interim / INTERIM_MANIFEST).exists() and canonical_state(interim) is None
    assert not (ctx.cfg.source.path.parent / LOCK_NAME).exists(), "the hash is registered only after the tables are complete"
    monkeypatch.setattr(ingest, "write_atomic", real)
    assert fetch_source(ctx)["built"] is True and canonical_state(interim) == sha(small_arff.read_bytes())


def test_tables_built_from_another_source_are_rebuilt_not_reused(quick_cfg, tmp_path, small_arff, malformed):
    ctx = quick_ctx(quick_cfg, tmp_path, small_arff)
    fetch_source(ctx)
    interim = ctx.cfg.paths.interim_dir
    before = read_canonical(interim)[1]
    changed = malformed("wrong_hash")                 # the same file with one digit changed: another hash, the same hours
    other = quick_ctx(quick_cfg, tmp_path / "other", changed)
    other = types.SimpleNamespace(cfg=dataclasses.replace(other.cfg, paths=dataclasses.replace(other.cfg.paths, interim_dir=interim)))
    result = fetch_source(other)
    assert result["built"] is True and canonical_state(interim) == sha(changed.read_bytes()) != sha(small_arff.read_bytes())
    after = read_canonical(interim)[1]
    assert len(after) == len(before) and not after["starch_flow_mean"].equals(before["starch_flow_mean"]), "the tables are those of the second file"


# --- what the reader never does with the file -----------------------------------------------------------------------------


FORBIDDEN_NAME_CALLS = {"eval", "exec", "compile", "__import__", "input"}         # builtins called by name (``re.compile`` is not one of them)
FORBIDDEN_ATTRIBUTE_CALLS = {"system", "popen", "Popen", "urlopen", "run", "call", "check_output"}
FORBIDDEN_MODULES = {"pickle", "marshal", "shelve", "subprocess", "socket", "urllib", "http", "requests", "ctypes", "importlib", "runpy", "dill",
                     "cloudpickle", "joblib", "yaml", "xml", "zipfile", "tarfile"}


def called_name(node: ast.Call) -> str:
    """``eval`` for ``eval(x)`` and ``.system`` for ``os.system(x)``: a builtin by name, or the attribute of anything."""
    return "." + node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")


@pytest.mark.parametrize("module", ["ingest", "schema", "hours", "files"])
def test_the_reader_never_executes_deserializes_or_downloads_what_it_reads(module):
    """No ``eval``/``exec``, no pickle, no subprocess, no network, no archive: the file is read as text, line by line (D02, D03)."""
    tree = ast.parse((PACKAGE / f"{module}.py").read_text(encoding="utf-8"))
    imported, calls = set(), []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            calls.append(called_name(node))
    assert not imported & FORBIDDEN_MODULES, imported & FORBIDDEN_MODULES
    assert not set(calls) & (FORBIDDEN_NAME_CALLS | {"." + name for name in FORBIDDEN_ATTRIBUTE_CALLS}), set(calls)


def test_the_security_check_finds_what_it_forbids(tmp_path):
    """The check above on a module that has each of the three: a forbidden import, ``eval`` and ``pickle.loads``."""
    source = "import pickle\nimport re\nimport numpy\n\ndef f(text):\n    return eval(text), os.system(text), re.compile(text), numpy.sum([1])\n"
    tree = ast.parse(source)
    calls = {called_name(n) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert calls & (FORBIDDEN_NAME_CALLS | {"." + name for name in FORBIDDEN_ATTRIBUTE_CALLS}) == {"eval", ".system"}
    assert modules & FORBIDDEN_MODULES == {"pickle"}


def test_a_header_that_names_paths_or_commands_changes_nothing_outside_the_interim_folder(quick_cfg, tmp_path, small_arff):
    """Nothing the file says is a path, a command or an include: its comments and its relation are text (D03: no path from the file)."""
    text = small_arff.read_bytes().decode("utf-8")
    first_comment = next(line for line in text.split("\n") if line.startswith("% "))
    crafted = text.replace(first_comment, "% @INCLUDE ../../outside.arff ; rm -rf / ; $(touch ../evil) ${HOME} \\\\server\\share\\x C:\\Windows\\evil.txt", 1)
    source = tmp_path / "crafted.arff"
    source.write_bytes(crafted.encode("utf-8"))
    ctx = quick_ctx(quick_cfg, tmp_path / "run", source)
    fetch_source(ctx)
    written = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    assert written == {"crafted.arff", "run/data/quick/flotation_fixture.arff", "run/data/quick/source.lock.json", "run/interim/" + ROWS_NAME,
                       "run/interim/" + HOURS_NAME, "run/interim/" + INTERIM_MANIFEST}
    assert not (tmp_path.parent / "outside.arff").exists() and not (tmp_path / "evil").exists() and not (tmp_path.parent / "evil").exists()


# --- the real file (marked: only with data/raw/ in place; the test months are not read before U21, D18) -----------------------------


@pytest.mark.real_data
def test_the_real_file_is_the_pinned_one_and_its_rows_before_the_test_months_have_the_counts_of_the_plan(cfg):
    """The size and the SHA-256 of the whole file (hashing reads bytes, not rows); the header; and the rows up to the first one dated
    2017-07-31, never past it (requirements.md, section 4): 560,333 rows, 3,113 hours, the 318-hour gap and the states of each block."""
    digest = ingest.check_source(cfg)
    assert digest == cfg.source.accepted_sha256
    assert read_header(cfg.source.path, cfg) > 25
    rows, report = read_arff(cfg.source.path, cfg, stop_before=datetime(2017, 7, 31))
    built_rows, hours = ingest.canonical(rows, cfg)
    assert report.rows == len(rows) == len(built_rows) == 560_333 and len(hours) == 3_113 and report.stopped_before == datetime(2017, 7, 31)
    assert hours["hour"].max() < datetime(2017, 7, 31) and hours["hour"].max() == datetime(2017, 7, 30, 23)
    assert report.missing_hours == 318 and int(hours["is_partial"].sum()) == 2 and int((hours["rows"] > cfg.hours.rows_per_hour).sum()) == 0
    split = cfg.split
    for name, first, last, interpolated, held in (("train", split.train_first, split.train_last, 139, 165), ("v1", split.v1_first, split.v1_last, 8, 58),
                                                    ("v2", split.v2_first, split.v2_last, 12, 87)):
        block = hours[(hours["hour"] >= first) & (hours["hour"] <= last)]
        assert (block["lab_state"] == "interpolated").sum() == interpolated, name
        assert (block["lab_state"] == "held").sum() == held, name


# --- the manifest vouches for the tables ----------------------------------------------------------------------------------------


def rewrite_table(path: Path, change=None, fingerprint: bytes | None = None) -> None:
    """The same Parquet file with a value changed (`change` takes the table), or with another source fingerprint in its metadata, still readable."""
    import pyarrow as pa

    table = pq.read_table(path)
    metadata = dict(table.schema.metadata or {})
    if fingerprint is not None:
        metadata[ingest.FINGERPRINT_KEY] = fingerprint
    if change is not None:
        table = change(table)
    pq.write_table(table.replace_schema_metadata(metadata), path)
    assert isinstance(table, pa.Table)


def test_a_readable_table_with_other_values_is_refused_because_its_hash_is_not_the_manifests(quick_cfg, tmp_path, small_arff):
    import pyarrow.compute as pc

    ctx = quick_ctx(quick_cfg, tmp_path, small_arff)
    fetch_source(ctx)
    interim = ctx.cfg.paths.interim_dir
    rewrite_table(interim / HOURS_NAME, change=lambda table: table.set_column(
        table.schema.get_field_index("silica_pct"), "silica_pct", pc.add(table.column("silica_pct"), 1.0)))
    assert pq.read_table(interim / HOURS_NAME).num_rows > 0 and canonical_state(interim) is None
    with pytest.raises(InterimError, match=f"{HOURS_NAME}.*huella"):
        read_canonical(interim)
    assert fetch_source(ctx)["built"] is True and canonical_state(interim) == sha(small_arff.read_bytes())


def test_tables_of_another_source_with_a_manifest_that_matches_their_files_are_still_refused(quick_cfg, tmp_path, small_arff):
    ctx = quick_ctx(quick_cfg, tmp_path, small_arff)
    fetch_source(ctx)
    interim = ctx.cfg.paths.interim_dir
    for name in (ROWS_NAME, HOURS_NAME):
        rewrite_table(interim / name, fingerprint=b"f" * 64)
    manifest = json.loads((interim / INTERIM_MANIFEST).read_text(encoding="utf-8"))
    manifest["files"] = {name: sha((interim / name).read_bytes()) for name in manifest["files"]}
    (interim / INTERIM_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")          # the manifest agrees with the bytes of the files...
    assert canonical_state(interim) is None                                                  # ...but they were not built from the source it names
    with pytest.raises(InterimError, match="otra fuente|de la fuente"):
        read_canonical(interim)


def test_the_reader_itself_holds_the_byte_cap_before_reading_a_line(quick_cfg, tmp_path, malformed, monkeypatch):
    path = malformed("oversize")
    small_cap = dataclasses.replace(quick_cfg, source=dataclasses.replace(quick_cfg.source, max_bytes=LIMIT))
    monkeypatch.setattr(ingest, "_decode", lambda *args: (_ for _ in ()).throw(AssertionError("a line was read before the cap was checked")))
    with pytest.raises(SourceError, match="V03.*max_bytes"):
        read_arff(path, small_cap)
