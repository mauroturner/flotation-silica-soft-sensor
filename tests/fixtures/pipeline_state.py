"""The flow of the small fixture, task by task, for the tests of the run state, the close and the refusals (U17): a configuration whose plan is the launch, one delivery of
twenty-five hours and the close, every folder under one root, and the states built once per session (a launched one and a replayed one) that each test copies.

The small fixture is three weeks with the March gap in the middle; its hours after the gap run to 2017-03-31 00:00. The launch takes everything up to 2017-03-29 23:00, the
only daily delivery the 25 hours of 2017-03-30 and the close ends at 2017-03-31 02:00 (the model learns from the blocks of ``small_view``, whose test is the 30th). A copy of a
state is a plain ``copytree``: nothing the flow writes holds a path of this machine (the registry keeps only the artifact's name), so a copy at another root is the same state."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import sqlite3
import types
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from tests.fixtures.tiny_model import small_view

LAUNCH_LAST = datetime(2017, 3, 29, 23)
LAST_HOUR = datetime(2017, 3, 31, 0)
CADENCE_HOURS = 25
LAYOUT = {
    "raw_dir": "raw", "interim_dir": "interim", "warehouse": "flotsilica.sqlite", "models_dir": "models", "outputs_dir": "outputs/powerbi", "site_dir": "outputs/site",
    "reports_dir": "reports", "seal": "reports/model_seal.json", "dashboard_html": "dashboard/powerbi-design.html", "readme": "README.md", "figures_dir": "figures",
}
LAUNCH_ID, DAILY_ID, CLOSE_ID = "L2017-03-29", "D2017-03-30T00", "C2017-03-31"


def pipeline_config(root: Path, quick_cfg: Any, small_arff: Path | None = None) -> Any:
    """The configuration of the small fixture's flow with every folder under `root`; the ARFF is copied to ``root/source`` when `small_arff` is given."""
    root = Path(root)
    source = root / "source" / "small.arff"
    if small_arff is not None:
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(small_arff, source)
    view = small_view(quick_cfg)
    return dataclasses.replace(
        view, source=dataclasses.replace(view.source, path=source), hours=dataclasses.replace(view.hours, last_hour=LAST_HOUR),
        deliveries=dataclasses.replace(view.deliveries, launch_last_hour=LAUNCH_LAST, cadence_hours=CADENCE_HOURS),
        paths=dataclasses.replace(view.paths, **{name: root / relative for name, relative in LAYOUT.items()}), project_root=root)


def state_of(root: Path, quick_cfg: Any, small_arff: Path | None = None) -> types.SimpleNamespace:
    return types.SimpleNamespace(root=Path(root), cfg=pipeline_config(root, quick_cfg, small_arff))


def copy_state(state: types.SimpleNamespace, target: Path, quick_cfg: Any) -> types.SimpleNamespace:
    """A copy of a state at `target` with its own configuration, for a test that writes."""
    shutil.copytree(state.root, target)
    return state_of(target, quick_cfg)


def tree_digest(root: Path) -> dict[str, str]:
    """The SHA-256 of every file under `root`, by its path relative to it: two equal digests are the same bytes everywhere."""
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(Path(root).rglob("*")) if path.is_file()}


def published_digest(cfg: Any) -> dict[str, str]:
    """What AC07 compares, by its path under the root: the SQLite file, the star model (every Parquet and its manifest), the HTML, every JSON of the site and the seal."""
    paths = [Path(cfg.paths.warehouse), Path(cfg.paths.dashboard_html), Path(cfg.paths.seal), *sorted(Path(cfg.paths.outputs_dir).glob("*")),
             *sorted(Path(cfg.paths.site_dir).glob("*.json"))]
    return {path.relative_to(cfg.project_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def tamper_delivery(cfg: Any, delivery_id: str) -> None:
    """Drop the last hour from the hours file of a published delivery: its hours and its SHA-256 are no longer the manifest's (V13)."""
    path = Path(cfg.paths.raw_dir) / "deliveries" / f"{delivery_id}.hours.parquet"
    table = pq.read_table(path)
    pq.write_table(table.slice(0, table.num_rows - 1), path)


def query(cfg: Any, sql: str, params: tuple = ()) -> list[tuple]:
    """Rows of a read-only query on the warehouse of a state."""
    conn = sqlite3.connect(f"{Path(cfg.paths.warehouse).resolve().as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def runs_of(cfg: Any) -> dict[str, str]:
    """``{run_key: status}`` of the runs of a state, in the order they started."""
    return dict(query(cfg, "SELECT run_key, status FROM pipeline_runs ORDER BY started_at, run_key"))


RUN_KEYS = ("run_key", "launch_run_key", "test_run_key")


def _without_run(value: Any) -> Any:
    """A JSON document without the keys that name the run that wrote it (and the artifact's bytes, which are not a value: D18)."""
    if isinstance(value, dict):
        return {k: _without_run(v) for k, v in value.items() if k not in (*RUN_KEYS, "artifact_sha256")}
    if isinstance(value, list):
        return [_without_run(v) for v in value]
    return value


def content_of(cfg: Any) -> dict[str, Any]:
    """What a replay published, without the columns of the run (AC37): the rows of every Parquet of the star model but the run table (each without its ``run_key`` column,
    in a fixed order), every JSON of the site but its manifest, the summary and the seal."""
    out: dict[str, Any] = {}
    for path in sorted(Path(cfg.paths.outputs_dir).glob("*.parquet")):
        if path.stem == "dim_pipeline_run":
            continue
        rows = [{k: v for k, v in row.items() if k != "run_key"} for row in pq.read_table(path).to_pylist()]
        out[path.name] = sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, default=str))
    for path in sorted(Path(cfg.paths.site_dir).glob("*.json")):
        if path.name != "manifest.json":
            out[f"site/{path.name}"] = _without_run(json.loads(path.read_text(encoding="utf-8")))
    for path in (Path(cfg.paths.reports_dir) / "evaluation_summary.json", Path(cfg.paths.seal)):
        out[path.name] = _without_run(json.loads(path.read_text(encoding="utf-8")))
    return out
