"""The SQLite warehouse: connection, SQL runner, schema, the load of a delivery and the controls (RF08, D24); adapted from project 04.

Rules of the runner (plan, section 5), the same as in projects 01 to 04:

- autocommit connection (``isolation_level=None``); transactions are explicit ``BEGIN IMMEDIATE``;
- ``journal_mode=DELETE`` (WAL does not behave on Docker Desktop mounts), ``synchronous=FULL``, ``foreign_keys=ON``;
- never ``executescript()``: it commits the open transaction first. SQL files are split into statements with ``sqlite3.complete_statement`` and
  run one by one with named parameters, so a failure can roll the whole load back;
- the staging table is rebuilt inside the transaction (``DROP TABLE IF EXISTS`` and ``CREATE TABLE AS``), so SQLite rolls it back too.

A load is all or nothing: the rows and hours of the delivery, its row in ``deliveries``, ``hour_blocks`` and ``stg_hours`` rebuilt for its
instant and the controls of ``sql/checks/load/`` are one transaction. A delivery that is empty (but for the close), already loaded, repeats a
row or fails a control leaves the warehouse byte for byte as it was. Each control returns the rows that break its rule and names an hour or a
sensor, never a row of the plant. Every analysis is stored with its arrival, ``available_at = hour + latency_hours`` (D06).
"""

from __future__ import annotations

import functools
import logging
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

import pandas as pd

from flotsilica.config import HoursConfig, LabConfig, SplitConfig
from flotsilica.deliveries import DeliverySpec
from flotsilica.schema import AGGREGATE_COLUMNS, SENSORS, SOURCE_HOURS_SCHEMA, SOURCE_ROWS_SCHEMA

logger = logging.getLogger(__name__)

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
CHECK_GROUPS = ("load", "model")
MART_GROUPS = ("powerbi",)
SAMPLE_LIMIT = 5
BUSY_TIMEOUT_MS = 30_000   # an overlapping writer waits this long for the write lock before failing (runbook R8)
STAGING = ("staging/stg_hours.sql",)
SPLIT_KEYS = ("train_first", "train_last", "v1_first", "v1_last", "v2_first", "v2_last", "test_first", "test_last")
RAW_COLUMNS = ("row_id", "delivery_id", "hour", "row_in_hour", *SENSORS)
HOUR_COLUMNS = ("hour", "delivery_id", "rows", "is_partial", "silica_pct", "iron_conc_pct", "feed_silica_pct", "feed_iron_pct", "lab_state",
                "feed_silica_age_h", "feed_iron_age_h", "available_at")
AGGREGATE_TABLE_COLUMNS = ("hour", "rows", *AGGREGATE_COLUMNS)


class _HasCalendar(Protocol):     # PipelineConfig and SealedConfig both have these sections
    hours: HoursConfig
    lab: LabConfig
    split: SplitConfig


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    violations: int
    sample: list[tuple]


@dataclass(frozen=True)
class LoadResult:
    delivery_id: str
    as_of: datetime
    rows: int                  # rows of the delivery now in raw_rows
    hours: int                 # hours of the delivery now in lab_hours
    staged: int                # rows of stg_hours after the load: every hour that had closed at the delivery's instant
    checks: list[CheckResult]


class EmptyDeliveryError(RuntimeError):
    """The delivery has no rows (and is not the close): nothing was written and the warehouse keeps what it had."""

    def __init__(self, run_key: str, delivery_id: str) -> None:
        super().__init__(f"La carga {run_key} se rechazó: la entrega {delivery_id} no tiene filas y el almacén queda como estaba")


class DeliveryAlreadyLoadedError(RuntimeError):
    """The delivery is already in the warehouse: loading it again would duplicate its rows."""

    def __init__(self, delivery_id: str) -> None:
        super().__init__(f"La entrega {delivery_id} ya está cargada en el almacén; no se carga de nuevo")


class CheckFailedError(RuntimeError):
    """A control returned rows: the transaction was rolled back."""

    def __init__(self, checks: list[CheckResult], step: str = "La carga") -> None:
        self.checks, self.step = checks, step
        failing = [c for c in checks if c.violations]
        detail = "; ".join(f"{c.check_id}: {c.violations} filas, por ejemplo {c.sample[:2]}" for c in failing)
        super().__init__(f"{step} se deshizo; controles con filas que los violan: {detail}")


class SchemaDriftError(RuntimeError):
    """A table of the warehouse does not have the columns its SQL definition declares (runbook R11)."""

    def __init__(self, table: str, source: str, missing: tuple[str, ...], unexpected: tuple[str, ...], retyped: tuple[str, ...]) -> None:
        self.table, self.missing, self.unexpected, self.retyped = table, missing, unexpected, retyped
        parts = [text for text, columns in ((f"faltan las columnas {list(missing)}", missing), (f"sobran las columnas {list(unexpected)}", unexpected),
                                            (f"tienen otro tipo las columnas {list(retyped)}", retyped)) if columns]
        super().__init__(f"La tabla {table} no coincide con su definición en sql/schema/{source}: {'; '.join(parts)}. "
                         "El almacén lo creó una versión anterior: se reconstruye desde cero (docs/runbook.md, R11).")


# --- connection and SQL files -------------------------------------------------------------------------------------------


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating the folder and the file) the warehouse in autocommit mode with the project's pragmas."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _has_sql(text: str) -> bool:
    """True if `text` has anything besides whitespace, semicolons and comments."""
    i, n = 0, len(text)
    while i < n:
        if text.startswith("--", i):
            end = text.find("\n", i)
            i = n if end == -1 else end + 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        elif text[i].isspace() or text[i] == ";":
            i += 1
        else:
            return True
    return False


def split_statements(sql_text: str) -> list[str]:
    """Split a SQL file into statements, keeping semicolons inside strings, comments and triggers (a new list: the split is cached by text)."""
    return list(_split_statements(sql_text))


@functools.lru_cache(maxsize=256)
def _split_statements(sql_text: str) -> tuple[str, ...]:
    statements: list[str] = []
    start = 0
    for position, character in enumerate(sql_text):
        if character == ";" and sqlite3.complete_statement(sql_text[start : position + 1]):
            chunk = sql_text[start : position + 1]
            if _has_sql(chunk):
                statements.append(chunk.strip())
            start = position + 1
    if _has_sql(sql_text[start:]):   # a last statement without its semicolon
        statements.append(sql_text[start:].strip())
    return tuple(statements)


def run_sql_file(conn: sqlite3.Connection, path: Path, params: Mapping[str, object] | None = None) -> None:
    """Execute the statements of a SQL file one by one, binding the named parameters each uses."""
    for statement in split_statements(Path(path).read_text(encoding="utf-8")):
        conn.execute(statement, dict(params or {}))


def _stamp(value: datetime | pd.Timestamp) -> str:
    """An instant as the warehouse stores it: ``YYYY-MM-DD HH:MM:SS``."""
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def sql_params(as_of: datetime, view: _HasCalendar) -> dict[str, object]:
    """The named parameters the SQL files may use: the instant the staging is built for, the latency and the size of an hour, and the blocks."""
    return {"as_of": _stamp(as_of), "latency_hours": int(view.lab.latency_hours), "rows_per_hour": int(view.hours.rows_per_hour),
            **{key: _stamp(getattr(view.split, key)) for key in SPLIT_KEYS}}


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _declared_tables(path: Path) -> dict[str, dict[str, str]]:
    """``{table: {column: declared type}}`` of a schema file, read by creating its tables in memory (cached by the file's size and time)."""
    stat = Path(path).stat()
    return _declared_tables_cached(str(path), stat.st_size, stat.st_mtime_ns)


@functools.lru_cache(maxsize=16)
def _declared_tables_cached(path: str, size: int, mtime_ns: int) -> dict[str, dict[str, str]]:
    del size, mtime_ns   # only part of the cache key
    scratch = sqlite3.connect(":memory:")
    try:
        for statement in split_statements(Path(path).read_text(encoding="utf-8")):
            scratch.execute(statement)
        names = [r[0] for r in scratch.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        return {t: {r[1]: (r[2] or "").upper() for r in scratch.execute(f'PRAGMA table_info("{t}")')} for t in names}
    finally:
        scratch.close()


def _check_no_drift(conn: sqlite3.Connection, path: Path) -> None:
    for table, declared in _declared_tables(path).items():
        if not _table_exists(conn, table):
            continue
        actual = {r[1]: (r[2] or "").upper() for r in conn.execute(f'PRAGMA table_info("{table}")')}
        missing = tuple(c for c in declared if c not in actual)
        unexpected = tuple(c for c in actual if c not in declared)
        retyped = tuple(c for c in declared if c in actual and declared[c] != actual[c])
        if missing or unexpected or retyped:
            raise SchemaDriftError(table, Path(path).name, missing, unexpected, retyped)


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create the tables of ``sql/schema`` that do not exist yet (idempotent; keeps the data). A table that exists with other columns than its
    file declares is not migrated: ``SchemaDriftError`` names it and its columns."""
    for path in sorted((SQL_DIR / "schema").glob("*.sql")):
        _check_no_drift(conn, path)
        run_sql_file(conn, path)


# --- marts -----------------------------------------------------------------------------------------------------------------


def rebuild_marts(conn: sqlite3.Connection, group: Literal["powerbi"], params: Mapping[str, object] | None = None) -> list[str]:
    """Rebuild the marts of a group (``sql/marts/<group>/mart_*.sql``, in file-name order) inside the caller's transaction: each file drops its table and creates it
    again from the tables it reads, so a rollback undoes it too. Returns the names of the files run."""
    if group not in MART_GROUPS:
        raise ValueError(f"grupo de marts desconocido: {group!r}; se esperaba uno de {', '.join(MART_GROUPS)}")
    if not conn.in_transaction:
        raise RuntimeError("los marts se reconstruyen dentro de una transacción abierta, para que una falla los deshaga")
    paths = sorted((SQL_DIR / "marts" / group).glob("mart_*.sql"))
    for path in paths:
        run_sql_file(conn, path, params)
    return [path.stem for path in paths]


# --- controls --------------------------------------------------------------------------------------------------------------


def run_checks(conn: sqlite3.Connection, group: Literal["load", "model"], params: Mapping[str, object] | None = None) -> list[CheckResult]:
    """Run the controls of a group, in file-name order; each file selects the rows that break its rule (none: it passes)."""
    if group not in CHECK_GROUPS:
        raise ValueError(f"grupo de controles desconocido: {group!r}; se esperaba uno de {', '.join(CHECK_GROUPS)}")
    bound = dict(params or {})
    results = []
    for path in sorted((SQL_DIR / "checks" / group).glob("chk_*.sql")):
        statements = split_statements(path.read_text(encoding="utf-8"))
        if len(statements) != 1:
            raise ValueError(f"{path.name} debe tener exactamente un SELECT y tiene {len(statements)} sentencias")
        select = statements[0].rstrip().rstrip(";")
        violations = conn.execute(f"SELECT COUNT(*) FROM ({select})", bound).fetchone()[0]
        sample = conn.execute(f"SELECT * FROM ({select}) LIMIT {SAMPLE_LIMIT}", bound).fetchall() if violations else []
        results.append(CheckResult(path.stem, int(violations), sample))
    return results


def _fail_on(checks: list[CheckResult], what: str, step: str = "La carga") -> None:
    """``CheckFailedError`` if a control has rows. It is raised inside the caller's open transaction, so the log says which control failed;
    the caller logs «rolled back» only once its ROLLBACK has run."""
    failing = [c for c in checks if c.violations]
    for c in failing:
        logger.error("%s: control %s failed, violations=%d sample=%s", what, c.check_id, c.violations, c.sample)
    if failing:
        raise CheckFailedError(checks, step)


# --- load ------------------------------------------------------------------------------------------------------------------


def _column(series: pd.Series) -> list[Any]:
    """The values of a column as SQLite stores them: instants as text, booleans as 0 or 1 and a NaN as NULL."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return series.dt.strftime("%Y-%m-%d %H:%M:%S").tolist()
    if pd.api.types.is_bool_dtype(series):
        return series.astype(int).tolist()
    return [None if value != value else value for value in series.tolist()]


def _values(frame: pd.DataFrame, columns: tuple[str, ...], fixed: Mapping[str, Any]) -> list[tuple]:
    """The rows of `frame` for an INSERT of `columns`; a column that is not in `frame` takes its value from `fixed`."""
    data = [[fixed[name]] * len(frame) if name in fixed else _column(frame[name]) for name in columns]
    return list(zip(*data, strict=True))


def _insert(conn: sqlite3.Connection, table: str, columns: tuple[str, ...], values: list[tuple]) -> None:
    conn.executemany(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})", values)


def _rebuild(conn: sqlite3.Connection, as_of: datetime, view: _HasCalendar) -> None:
    for name in STAGING:
        run_sql_file(conn, SQL_DIR / name, sql_params(as_of, view))


def load_delivery(conn: sqlite3.Connection, rows: pd.DataFrame, hours: pd.DataFrame, spec: DeliverySpec, run_key: str, view: _HasCalendar, *,
                  sha256: str) -> LoadResult:
    """Add a validated delivery to the warehouse and rebuild ``stg_hours`` for its instant, in one transaction (RF08).

    `rows` and `hours` are the canonical tables of the delivery; `sha256` is its fingerprint in the manifest, recorded in ``deliveries``. Every
    hour is stored with ``available_at = hour + view.lab.latency_hours``. A delivery with no rows is refused, except the close, which loads
    empty and must be empty; one already loaded is refused too. If anything fails, a row that repeats or a control included, the transaction is
    rolled back and the warehouse keeps exactly what it had.
    """
    for what, frame, schema in (("las filas", rows, SOURCE_ROWS_SCHEMA), ("las horas", hours, SOURCE_HOURS_SCHEMA)):
        missing = [c for c in schema.names if c not in frame.columns]
        if missing:
            raise ValueError(f"la entrega no tiene las columnas del esquema canónico en {what}: faltan {', '.join(missing)}")
    if spec.kind == "close":
        if len(rows) or len(hours):
            raise ValueError(f"el cierre no tiene filas, y la entrega {spec.delivery_id} trae {len(rows)} filas y {len(hours)} horas")
    elif rows.empty or hours.empty:
        raise EmptyDeliveryError(run_key, spec.delivery_id)
    hours = hours.assign(delivery_id=spec.delivery_id, available_at=hours["hour"] + timedelta(hours=view.lab.latency_hours))
    conn.execute("BEGIN IMMEDIATE")
    try:
        apply_schema(conn)
        existing = conn.execute("SELECT status FROM deliveries WHERE delivery_id = ?", (spec.delivery_id,)).fetchone()
        if existing is not None and existing[0] == "loaded":
            raise DeliveryAlreadyLoadedError(spec.delivery_id)
        conn.execute(
            "INSERT INTO deliveries (delivery_id, kind, first_hour, last_hour, as_of, rows, hours, sha256, status, run_key) "
            "VALUES (:delivery_id, :kind, :first_hour, :last_hour, :as_of, :rows, :hours, :sha256, 'loaded', :run_key) "
            "ON CONFLICT (delivery_id) DO UPDATE SET kind = excluded.kind, first_hour = excluded.first_hour, last_hour = excluded.last_hour, "
            "as_of = excluded.as_of, rows = excluded.rows, hours = excluded.hours, sha256 = excluded.sha256, status = 'loaded', run_key = excluded.run_key",
            {"delivery_id": spec.delivery_id, "kind": spec.kind, "first_hour": None if spec.first_hour is None else _stamp(spec.first_hour),
             "last_hour": None if spec.last_hour is None else _stamp(spec.last_hour), "as_of": _stamp(spec.as_of), "rows": len(rows), "hours": len(hours),
             "sha256": sha256, "run_key": run_key},
        )
        fixed = {"delivery_id": spec.delivery_id}
        _insert(conn, "lab_hours", HOUR_COLUMNS, _values(hours, HOUR_COLUMNS, fixed))
        _insert(conn, "hour_aggregates", AGGREGATE_TABLE_COLUMNS, _values(hours, AGGREGATE_TABLE_COLUMNS, fixed))
        _insert(conn, "raw_rows", RAW_COLUMNS, _values(rows, RAW_COLUMNS, fixed))
        _rebuild(conn, spec.as_of, view)
        checks = run_checks(conn, "load", sql_params(spec.as_of, view))
        _fail_on(checks, f"load {run_key}")
        loaded_rows = int(conn.execute("SELECT COUNT(*) FROM raw_rows WHERE delivery_id = ?", (spec.delivery_id,)).fetchone()[0])
        loaded_hours = int(conn.execute("SELECT COUNT(*) FROM lab_hours WHERE delivery_id = ?", (spec.delivery_id,)).fetchone()[0])
        if (loaded_rows, loaded_hours) != (len(rows), len(hours)):
            raise RuntimeError(f"La carga {run_key} se deshizo: se esperaban {len(rows)} filas y {len(hours)} horas de {spec.delivery_id} y hay "
                               f"{loaded_rows} y {loaded_hours}")
        staged = int(conn.execute("SELECT COUNT(*) FROM stg_hours").fetchone()[0])
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        logger.warning("load %s rolled back: the warehouse keeps what it had", run_key)
        raise
    logger.info("load %s: delivery=%s rows=%d hours=%d staged=%d controls=%d", run_key, spec.delivery_id, loaded_rows, loaded_hours, staged, len(checks))
    return LoadResult(spec.delivery_id, spec.as_of, loaded_rows, loaded_hours, staged, checks)


def rebuild_staging(conn: sqlite3.Connection, as_of: datetime, view: _HasCalendar) -> list[CheckResult]:
    """Rebuild ``hour_blocks`` and ``stg_hours`` for the instant `as_of` from ``lab_hours`` and ``hour_aggregates``, which are not touched:
    whatever the warehouse holds since, a calculation for an instant gets what had closed at it (RNF06 a). One transaction with the controls
    of the load; a control with rows undoes it."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        apply_schema(conn)
        _rebuild(conn, as_of, view)
        checks = run_checks(conn, "load", sql_params(as_of, view))
        _fail_on(checks, f"staging at {as_of}", "La preparación de las horas (staging)")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        logger.warning("staging at %s rolled back: the warehouse keeps what it had", as_of)
        raise
    return checks
