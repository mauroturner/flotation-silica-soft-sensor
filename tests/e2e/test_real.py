"""The complete real replay (U21; AC03, AC04, AC36, AC40): what ``python -m flotsilica replay`` left from the real ARFF is consistent, sealed and inside the limits.

Mark ``real_data``: not in the default selection, and skipped unless the file is in ``data/raw/``. It reads outputs; it computes nothing on the test hours and starts no
run: the first evaluation of the test period is the replay itself (D18), made once, and this test only checks what that replay wrote. Without those outputs it fails (it does not
skip): it says which file is missing.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from flotsilica import registry
from flotsilica.evaluation import criteria_from_seal
from flotsilica.site_export import read_site, verify_site
from flotsilica.export import verify_star_schema
from flotsilica.sysinfo import POSIX_COUNTER, WINDOWS_COUNTER
import sys

pytestmark = pytest.mark.real_data

ROWS, HOURS, MISSING_HOURS, PARTIAL_HOURS, TEST_HOURS = 737_453, 4_097, 318, 2, 960
STATES = {"train": (139, 165), "valid_v1": (8, 58), "valid_v2": (12, 87)}    # interpolated and held hours, the counts of the plan (requirements.md, section 4)
DAILY_RUNS = 40
MAX_PEAK_WORKING_SET_MB, MAX_TOTAL_S, MAX_LAUNCH_S, MAX_DAILY_S, MAX_PARQUET_BYTES = 2048, 15 * 60, 6 * 60, 30, 25 * 1024 * 1024   # RNF02, RNF03, AC36


def require(path: Path) -> Path:
    assert path.is_file(), f"falta {path.name}: la repetición real completa no corrió (python -m flotsilica replay)"
    return path


def seconds(started: str, finished: str) -> float:
    return (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()


@pytest.fixture(scope="module")
def outputs(cfg):
    paths = cfg.paths
    seal_path, summary_path = require(Path(paths.seal)), require(Path(paths.reports_dir) / "evaluation_summary.json")
    warehouse = require(Path(paths.warehouse))
    conn = sqlite3.connect(f"{warehouse.as_uri()}?mode=ro", uri=True)
    yield {
        "conn": conn, "seal": json.loads(seal_path.read_text(encoding="utf-8")), "summary": json.loads(summary_path.read_text(encoding="utf-8")),
        "site": read_site(Path(paths.site_dir)), "seal_path": seal_path, "powerbi": Path(paths.outputs_dir),
    }
    conn.close()


def test_real_counts_seal_and_summary_consistency(cfg, outputs):
    conn, seal, summary, site = outputs["conn"], outputs["seal"], outputs["summary"], outputs["site"]

    # AC03: the rows and the hours of the file, in the warehouse and in what the site shows
    assert conn.execute("SELECT COUNT(*) FROM raw_rows").fetchone()[0] == ROWS
    assert conn.execute("SELECT COUNT(*), SUM(is_partial), MIN(rows) > 0 FROM lab_hours").fetchone() == (HOURS, PARTIAL_HOURS, 1)   # the missing hours have no row at all
    first, last = conn.execute("SELECT MIN(hour), MAX(hour) FROM lab_hours").fetchone()
    assert int((datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds() // 3600) + 1 == HOURS + MISSING_HOURS, "the calendar is the hours plus the gap"
    assert conn.execute("SELECT SUM(rows) FROM lab_hours").fetchone()[0] == ROWS
    headline = site.summary["headline"]
    assert (headline["rows"], headline["hours"], headline["missing_hours"], headline["partial_hours"]) == (ROWS, HOURS, MISSING_HOURS, PARTIAL_HOURS)
    assert headline["test_hours"] == TEST_HOURS

    # AC04: the states of the lab by block, the plan's counts before the test and a complete account of the test; the site says what the warehouse says
    states = {}
    for block, state, hours in conn.execute("SELECT b.block, l.lab_state, COUNT(*) FROM lab_hours l JOIN hour_blocks b USING (hour) GROUP BY 1, 2"):
        states.setdefault(block, {})[state] = hours
    for block, (interpolated, held) in STATES.items():
        assert (states[block].get("interpolated", 0), states[block].get("held", 0)) == (interpolated, held), block
    assert sum(states["test"].values()) == TEST_HOURS and set(states["test"]) <= {"fresh", "held", "interpolated"}
    shown = {entry["block"]: entry for entry in site.data["states_by_block"]}
    for block in ("train", "valid_v1", "valid_v2", "test"):
        assert {state: shown[block][state] for state in ("fresh", "held", "interpolated") if shown[block][state]} == states[block], block
    assert headline["test_fresh_hours"] == states["test"].get("fresh", 0)

    # The seal: both parts, one configuration, the pinned file, and the same ten criteria in the summary and on the site (D18, D19)
    assert set(seal) == {"version", "launch", "test"} and seal["test"] is not None
    launch, test = seal["launch"], seal["test"]
    fingerprint = registry.config_fingerprint(registry.sealed_view(cfg, cfg.source.accepted_sha256))
    assert launch["config_sha256"] == test["config_sha256"] == fingerprint == summary["seal"]["config_sha256"] == site.summary["seal"]["config_sha256"]
    assert launch["source_sha256"] == cfg.source.accepted_sha256 == summary["source_sha256"] == site.summary["source_sha256"]
    assert registry.seal_state(outputs["seal_path"], fingerprint) == "match"
    assert launch["as_of"] == "2017-08-01 00:00:00" and test["as_of"] == "2017-09-10 01:00:00"
    sealed = criteria_from_seal(seal)
    assert [c.criterion_id for c in sealed] == [f"C{n:02d}" for n in range(1, 11)] == [c["id"] for c in test["criteria"]]
    assert summary["evaluation_status"] == site.summary["evaluation_status"] == "sealed" and summary["post_seal"] is None
    assert [c["criterion_id"] for c in summary["criteria"]] == [c["id"] for c in site.summary["criteria"]] == [c.criterion_id for c in sealed]
    for criterion, in_summary, on_site, in_seal in zip(sealed, summary["criteria"], site.summary["criteria"], test["criteria"]):
        assert in_summary["verdict_es"] == on_site["verdict_es"] == in_seal["verdict_es"] == criterion.verdict_es, criterion.criterion_id
        assert in_summary["passed"] == on_site["passed"] == in_seal["passed"] == criterion.passed, criterion.criterion_id
        assert on_site["value"] == (None if criterion.value is None else round(criterion.value, 4)), criterion.criterion_id
    assert [site.summary["seal"][key] for key in ("launch_run_key", "test_run_key")] == [launch["run_key"], test["run_key"]]

    # The runs: the launch, the forty daily deliveries and the close, each loaded, ordered, and the same run keys in the sets of files
    runs = conn.execute("SELECT p.run_key, p.started_at, p.finished_at, p.status, p.peak_working_set_mb, p.memory_counter, d.kind "
                        "FROM pipeline_runs p JOIN deliveries d ON d.delivery_id = p.delivery_id ORDER BY p.started_at").fetchall()
    assert [r[6] for r in runs] == ["launch"] + ["daily"] * DAILY_RUNS + ["close"] and {r[3] for r in runs} == {"ok"}
    assert runs[0][0] == launch["run_key"] and runs[-1][0] == test["run_key"] == summary["run_key"] == site.summary["run_key"]
    assert conn.execute("SELECT COUNT(*) FROM deliveries WHERE status != 'loaded'").fetchone()[0] == 0

    # AC36 (RNF02, RNF03): times from the records of the runs, and the peak of the working set with its counter named
    assert not verify_site(Path(cfg.paths.site_dir)) and not verify_star_schema(outputs["powerbi"])
    assert seconds(runs[0][1], runs[-1][2]) <= MAX_TOTAL_S, "la repetición completa pasa de 15 min (RNF02)"
    assert seconds(runs[0][1], runs[0][2]) <= MAX_LAUNCH_S, "la lectura del ARFF y el lanzamiento pasan de 6 min (RNF02)"
    assert max(seconds(r[1], r[2]) for r in runs[1:-1]) <= MAX_DAILY_S, "una corrida diaria pasa de 30 s (RNF02)"
    counter = WINDOWS_COUNTER if sys.platform == "win32" else POSIX_COUNTER
    assert {r[5] for r in runs} == {counter} and max(r[4] for r in runs) <= MAX_PEAK_WORKING_SET_MB, f"el pico de {counter} pasa de 2 GB (RNF03)"
    parquets = sorted(outputs["powerbi"].glob("*.parquet"))
    assert len(parquets) == 20 and max(p.stat().st_size for p in parquets) <= MAX_PARQUET_BYTES
