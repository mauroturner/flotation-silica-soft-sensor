"""The star model for Power BI: the marts in SQLite and one Parquet file per table (RF21, AC25; D25; plan, section 19). Adapted from project 04's ``export.py`` without the
private fact: nothing here names a person (D43).

``build_powerbi_marts`` loads the reference tables that come from the code, the registry and the seal (``ref_*``: the methods with their kind, the sensors, the horizons, the blocks,
the states of an analysis, the frozen model of each horizon and which state of the seal a reader shows of each evaluation table), rebuilds the tables of ``sql/marts/powerbi``
(``star_<name>``) and runs the controls of ``sql/checks/model``, all in one transaction: a control with rows undoes it. Everything is **as of the run's instant**: an hour that had
not closed is not in the marts, and an analysis that had not arrived has no value in them (D06); the marts take it from ``:as_of``.

``export_star_schema`` writes every table of the semantic model with its Arrow schema and the run, the instant, the source and the attribution as file metadata, to ``outputs/powerbi``.
A file over ``MAX_PARQUET_BYTES`` is an error before anything is written; each file is replaced atomically. The folder's ``manifest.json`` is removed before its first file is
written and written again after its last one, with the run and each file's name, bytes and SHA-256 (RNF05): ``verify_star_schema`` checks a folder against it, so a set left half
written by a failure has no manifest and is refused.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from flotsilica import texts
from flotsilica.dashboard.semantic_model import SemanticModel, Table, arrow_schema, validate_model
from flotsilica.files import write_atomic
from flotsilica.ingest import ATTRIBUTION
from flotsilica.registry import read_registry, read_seal
from flotsilica.schema import ATTRIBUTES, SENSORS
from flotsilica.scoring import RunMeta
from flotsilica.warehouse import SQL_DIR, _fail_on, apply_schema, rebuild_marts, run_checks, run_sql_file, sql_params

logger = logging.getLogger(__name__)

MAX_PARQUET_BYTES = 25 * 1024 * 1024        # a versioned file stays under GitHub's limits (RNF10)
STAR_PREFIX = "star_"
METADATA_KEYS = ("flotsilica.run_key", "flotsilica.as_of", "flotsilica.source_sha256", "flotsilica.attribution")
STAR_MANIFEST = "manifest.json"
MANIFEST_VERSION = 1
STAMP = "%Y-%m-%d %H:%M:%S"
# the evaluation tables that hold a sealed and a post-seal version of the same rows, and from which a table of the star model shows one of them (``ref_shown``)
SHOWN_TABLES = ("eval_selection", "eval_sensitivity", "eval_pd_curve", "eval_variants", "eval_leakage")


def metadata(run: RunMeta, view: Any) -> dict[str, str]:
    """What every Parquet file says about the run that wrote it (RNF07, RNF09)."""
    return dict(zip(METADATA_KEYS, (run.run_key, run.as_of.strftime(STAMP), view.source_sha256, ATTRIBUTION), strict=True))


def _replace(conn: sqlite3.Connection, name: str, columns: str, rows: list[tuple]) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {name}")
    conn.execute(f"CREATE TABLE {name} ({columns})")
    if rows:
        conn.executemany(f"INSERT INTO {name} VALUES ({', '.join('?' for _ in rows[0])})", rows)


def _registered_models(conn: sqlite3.Connection, view: Any, seal_path: Path) -> list[tuple]:
    """The rows of ``ref_model``: the frozen model of each horizon, from the registry, with the state of the seal of the configuration that made it."""
    registered = read_registry(conn, view.model.model_version)
    if registered is None:
        raise RuntimeError(f"no hay un modelo registrado con la versión {view.model.model_version}: el modelo estrella se exporta después del lanzamiento")
    seal = read_seal(seal_path)
    state = "sealed" if seal is not None and registered["config_sha256"] == seal["launch"]["config_sha256"] else "post_seal"
    models = sorted(json.loads(registered["models_json"]), key=lambda m: m["horizon"])
    return [(f"{registered['model_version']}-h{m['horizon']}", registered["model_version"], m["horizon"], m["family"], m["feature_set"],
             texts.TARGETS_ES.get(m["target"], m["target"]), m["min_samples_leaf"], m["half_width"], m["b_star"], m["b2_k"], texts.TRAINED_ON_ES, registered["config_sha256"], state)
            for m in models]


def _load_references(conn: sqlite3.Connection, view: Any, seal_path: Path) -> None:
    """The ``ref_*`` tables the marts read."""
    columns = {value: key for key, value in ATTRIBUTES.items()}
    group_of = {sensor: group for group, sensors in texts.SENSOR_GROUPS_ES.items() for sensor in sensors}
    _replace(conn, "ref_method", "method_key TEXT PRIMARY KEY, method_es TEXT, kind_es TEXT, sort_order INTEGER",
             [(m, texts.METHODS_ES[m], kind, i) for i, (m, kind) in enumerate(texts.METHOD_KINDS_ES.items(), start=1)])
    _replace(conn, "ref_sensor", 'sensor_key TEXT PRIMARY KEY, "column" TEXT, name_es TEXT, group_es TEXT, unit_es TEXT, sort_order INTEGER',
             [(s, columns[s], texts.SENSORS_ES[s], group_of[s], texts.SENSOR_UNIT_ES, i) for i, s in enumerate(SENSORS, start=1)])
    _replace(conn, "ref_horizon", "horizon_key INTEGER PRIMARY KEY, horizon_es TEXT, hours_ahead INTEGER",
             [(h, texts.HORIZON_LABELS_ES.get(h, f"Horizonte {h}"), h) for h in sorted(view.evaluation.horizons)])
    _replace(conn, "ref_block", "block TEXT PRIMARY KEY, block_es TEXT", list(texts.BLOCKS_ES.items()))
    _replace(conn, "ref_lab_state", "lab_state TEXT PRIMARY KEY, lab_state_es TEXT", list(texts.LAB_STATES_ES.items()))
    _replace(conn, "ref_month", "month INTEGER PRIMARY KEY, month_es TEXT", list(enumerate(texts.MONTHS_ES, start=1)))
    _replace(conn, "ref_weekday", "weekday INTEGER PRIMARY KEY, weekday_es TEXT", list(enumerate(texts.WEEKDAYS_ES, start=1)))
    _replace(conn, "ref_variant", "variant TEXT PRIMARY KEY, variant_es TEXT", list(texts.VARIANTS_ES.items()))
    _replace(conn, "ref_model", "model_key TEXT PRIMARY KEY, model_version TEXT, horizon_key INTEGER, family TEXT, feature_set TEXT, target_es TEXT, min_samples_leaf INTEGER, "
             "half_width REAL, b_star TEXT, b2_k INTEGER, trained_on_es TEXT, config_sha256 TEXT, seal_state TEXT", _registered_models(conn, view, seal_path))
    shown = [(table, "sealed" if conn.execute(f"SELECT 1 FROM {table} WHERE seal_state = 'sealed' LIMIT 1").fetchone() else "post_seal") for table in SHOWN_TABLES]
    _replace(conn, "ref_shown", "table_name TEXT PRIMARY KEY, seal_state TEXT", shown)


def build_powerbi_marts(conn: sqlite3.Connection, run: RunMeta, view: Any, *, seal_path: Path) -> None:
    """Rebuild the reference tables and the star model as of ``run.as_of`` and run its controls in one transaction; a control with rows undoes it all (``CheckFailedError``)
    and the marts keep what they had."""
    apply_schema(conn)
    params = {**sql_params(run.as_of, view), "association_es": texts.ASSOCIATION_ES, "no_association_es": texts.NO_ASSOCIATION_ES}
    conn.execute("BEGIN IMMEDIATE")
    try:
        _load_references(conn, view, seal_path)
        rebuild_marts(conn, "powerbi", params)
        _fail_on(run_checks(conn, "model", params), f"star model at {run.as_of}", "La exportación del modelo estrella")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        logger.warning("star model at %s rolled back: the marts keep what they had", run.as_of)
        raise


_CONVERT = {
    "int8": lambda v: int(v), "int32": lambda v: int(v), "int64": lambda v: int(v), "float64": lambda v: float(v), "bool": lambda v: bool(v), "string": lambda v: str(v),
    "date": lambda v: date.fromisoformat(str(v)[:10]), "datetime": lambda v: datetime.fromisoformat(str(v)),
}


def _arrow_table(columns: list[tuple], table: Table) -> pa.Table:
    """The values of the columns (one tuple of values per column) as an Arrow table with the model's schema; a key with a missing value is an error."""
    arrays = []
    for column, values in zip(table.columns, columns, strict=True):
        if column.name in table.key and any(v is None for v in values):
            raise ValueError(f"{table.name}[{column.name}] tiene valores vacíos: una clave no puede")
        convert = _CONVERT[column.dtype]
        arrays.append(pa.array([None if v is None else convert(v) for v in values], type=arrow_schema(table).field(column.name).type))
    return pa.Table.from_arrays(arrays, schema=arrow_schema(table))


def _serialize(conn: sqlite3.Connection, table: Table, meta: dict[str, str]) -> bytes:
    names, order = (", ".join(f'"{name}"' for name in names) for names in (table.column_names, table.key))
    rows = conn.execute(f"SELECT {names} FROM {STAR_PREFIX}{table.name} ORDER BY {order}").fetchall()
    arrow = _arrow_table(list(zip(*rows, strict=True)) if rows else [()] * len(table.columns), table)
    arrow = arrow.replace_schema_metadata({**(arrow.schema.metadata or {}), **{k.encode(): v.encode("utf-8") for k, v in meta.items()}})
    sink = pa.BufferOutputStream()
    pq.write_table(arrow, sink, compression="snappy")
    return sink.getvalue().to_pybytes()


def _manifest_text(meta: dict[str, str], files: list[dict]) -> str:
    document = {"version": MANIFEST_VERSION, **{key.removeprefix("flotsilica."): value for key, value in meta.items()}, "files": files}
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def verify_star_schema(folder: Path) -> list[str]:
    """What does not match in `folder` against its ``manifest.json`` (empty when everything does): a missing or unreadable manifest, a listed file that is missing or whose bytes
    or SHA-256 differ, and a Parquet file the manifest does not list."""
    folder = Path(folder)
    try:
        manifest = json.loads((folder / STAR_MANIFEST).read_text(encoding="utf-8"))
        listed = {entry["name"]: entry for entry in manifest["files"]}
    except (OSError, ValueError, KeyError, TypeError) as error:
        return [f"{STAR_MANIFEST}: no hay un manifiesto legible ({type(error).__name__}); el conjunto no se usa"]
    problems = []
    for name, entry in listed.items():
        path = folder / name
        if not path.is_file():
            problems.append(f"{name}: falta el archivo que lista el manifiesto")
            continue
        data = path.read_bytes()
        if len(data) != entry.get("bytes") or hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            problems.append(f"{name}: los bytes no son los del manifiesto")
    problems += [f"{path.name}: el manifiesto no lo lista" for path in sorted(folder.glob("*.parquet")) if path.name not in listed]
    return problems


def export_star_schema(conn: sqlite3.Connection, out_dir: Path, model: SemanticModel, run: RunMeta, view: Any, *, seal_path: Path) -> list[Path]:
    """Rebuild the marts as of the run and write one Parquet file per table of `model` to `out_dir`, with the manifest last. Returns the paths in the model's order. The model is
    checked first and every file is serialized and measured before any is written."""
    problems = validate_model(model)
    if problems:
        raise ValueError(f"el modelo semántico es incoherente: {problems[0]}")
    meta = metadata(run, view)
    build_powerbi_marts(conn, run, view, seal_path=seal_path)
    payloads = {}
    for table in model.tables:
        data = _serialize(conn, table, meta)
        if len(data) > MAX_PARQUET_BYTES:
            raise ValueError(f"{table.name}.parquet pesa {len(data)} bytes, más de {MAX_PARQUET_BYTES}: no se escribe nada")
        payloads[table.name] = data
    out_dir = Path(out_dir)
    (out_dir / STAR_MANIFEST).unlink(missing_ok=True)         # a set being rewritten has no manifest until its last file is written
    paths = [write_atomic(out_dir / f"{table.name}.parquet", payloads[table.name]) for table in model.tables]
    files = [{"name": f"{t.name}.parquet", "bytes": len(payloads[t.name]), "sha256": hashlib.sha256(payloads[t.name]).hexdigest()} for t in model.tables]
    write_atomic(out_dir / STAR_MANIFEST, _manifest_text(meta, files))
    logger.info("star model at %s: %d files in %s", run.as_of, len(paths), out_dir)
    return paths


RUN_TABLE = "dim_pipeline_run"
RUN_TABLE_MART = "mart_07_dim_pipeline_run.sql"


def export_run_table(conn: sqlite3.Connection, out_dir: Path, model: SemanticModel, run: RunMeta, view: Any) -> Path | None:
    """Rewrite only ``dim_pipeline_run.parquet`` from ``pipeline_runs`` and its line of the folder's manifest: what closing a run, a failure or a run with no delivery changes
    (plan, sections 3 and 22). Nothing is created that was not there: without an exported set that verifies against its manifest it logs a warning naming the run and the
    reason and returns None, and every file keeps its bytes (a set with a file of another export would otherwise look whole). The other files, and the manifest's own header, are
    not touched."""
    out_dir = Path(out_dir)
    manifest_path = out_dir / STAR_MANIFEST
    problems = ["there is no manifest.json: nothing was exported here"] if not manifest_path.is_file() else verify_star_schema(out_dir)
    if problems:
        logger.warning("run table of run %s not rewritten: the exported set does not match its manifest, so every file is kept as it is: %s", run.run_key, "; ".join(problems))
        return None
    table = model.table(RUN_TABLE)
    conn.execute("BEGIN IMMEDIATE")
    try:
        run_sql_file(conn, SQL_DIR / "marts" / "powerbi" / RUN_TABLE_MART)
        data = _serialize(conn, table, metadata(run, view))
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    path = write_atomic(out_dir / f"{RUN_TABLE}.parquet", data)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["name"] == path.name:
            entry.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    write_atomic(manifest_path, json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    logger.info("run table rewritten: %s (%d bytes)", path.name, len(data))
    return path
