"""Source ingestion (RF01-RF04): the pinned file, the strict reader, the canonical rows and hours.

The ARFF is untrusted data (D02, D03). It is never executed, deserialized or taken for a path: it is read as text, line by line, and each
byte it holds is checked before it means anything.

* ``check_source`` (V01) compares the size and the SHA-256 of ``source.path`` with the accepted ones (the size first: a file of another size is
  never hashed), or, in quick mode, with the hash registered in ``source.lock.json`` next to the file. It never downloads anything.
* ``read_arff`` (V02-V07) reads the file under a cap of bytes before reading it (V03), line by line with strict UTF-8, no null byte and a cap on
  the bytes of a line and on the rows; the header must be the configured one exactly (V02); every data line has 24 fields, each between apostrophes or a bare integer (the real file writes a number without a fractional part that way),
  none empty or longer than ``MAX_FIELD_CHARS`` (V04), a date ``YYYY-MM-DD HH:00:00`` and numbers with a decimal comma (V05), dates that do not
  decrease (V06) and no hour with more than ``hours.rows_per_hour`` rows (V07). The lines are checked by chunks of ``CHUNK_ROWS``; inside a chunk
  V04 comes before V05, V05 before V06 and V06 before V07, and the first failing chunk ends the read. ``stop_before`` ends the read at the first row
  of a date from which the file is not to be looked at (the test months before U21, D18): neither that row nor any later one is parsed.
* ``canonical`` turns the rows into ``source_rows`` (no laboratory column) and ``source_hours`` (the four laboratory values of the first row of each
  hour, the aggregates of its sensors and the marks of D05; the other rows of the laboratory columns are not kept, D04).
* ``fetch_source`` is the first task: it runs all of it once per hash and writes the two Parquet files and, last, their manifest. A rejected
  source writes nothing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from flotsilica.config import PipelineConfig
from flotsilica.files import atomic_path, sha256_file, write_atomic
from flotsilica.hours import aggregate_rows, feed_age_hours, lab_states
from flotsilica.schema import (
    COLUMNS,
    LAB_COLUMNS,
    NUMERIC_COLUMNS,
    SENSORS,
    SOURCE_HOURS_SCHEMA,
    SOURCE_ROWS_SCHEMA,
    SourceError,
    hour_key,
)

MAX_FIELD_CHARS = 32               # the longest field of a data line (V04): a date has 19 characters and the longest number of the file fewer than 12
CHUNK_ROWS = 50_000
MAX_HEADER_LINES = 200             # a header that has not ended by here is not the file's (V02)
EXAMPLES = 5                       # how many failing lines a rule names
INTERIM_MANIFEST = "interim_manifest.json"
INTERIM_MANIFEST_VERSION = 1
LOCK_NAME = "source.lock.json"
LOCK_VERSION = 1
ROWS_NAME = "source_rows.parquet"
HOURS_NAME = "source_hours.parquet"
FINGERPRINT_KEY = b"flotsilica.source_sha256"
ATTRIBUTION_KEY = b"flotsilica.attribution"
ATTRIBUTION = "Quality Prediction in a Mining Process (Kaggle, Eduardo Magalhaes Oliveira, CC0), OpenML 43311."
RUNBOOK = "runbook R1 (docs/runbook.md)"

_ATTRIBUTE = re.compile(r'@ATTRIBUTE (?:"([^"]+)"|([^\s"]+)) STRING')
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:00:00")
_NUMBER = re.compile(r"-?[0-9]+(,[0-9]+)?")
# A field is between apostrophes (it may hold the decimal comma) or, as the real file writes a value that has no fractional part, a bare integer
# (``390``, not ``'390'``): 28,124 of the 560,333 rows before the test months have one to three of them. Nothing else is a field.
_FIELD = re.compile(r"'[^']*'|-?[0-9]+")
_LINE = re.compile(r"(?:'[^']*'|-?[0-9]+)(?:,(?:'[^']*'|-?[0-9]+)){23}")
_STOP = re.compile(r"'([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:00:00)','")
_HEX64 = re.compile(r"[0-9a-f]{64}")


class InterimError(ValueError):
    """The canonical tables are not the file their manifest names: missing, changed, from another source, or without a manifest."""


@dataclass(frozen=True)
class SourceReport:
    """What the reader saw (V02-V07 passed): rows, distinct hours, hours missing from the clock grid between the first and the last (I01), the
    bytes of the file and the date the read stopped before, if it was asked to."""

    rows: int
    hours: int
    missing_hours: int
    first_hour: datetime
    last_hour: datetime
    size_bytes: int
    stopped_before: datetime | None


def _rule(rule_id: str, message: str, **problem: Any) -> SourceError:
    return SourceError(rule_id, message, [{"rule_id": rule_id, **problem}])


def _runbook_error(message: str, **problem: Any) -> SourceError:
    return _rule("V01", f"{message} (runbook R1: docs/runbook.md)", **problem)


# --- V01: the pinned file -----------------------------------------------------------------------------------------------------


def read_source_lock(path: Path) -> dict[str, Any] | None:
    """The hash that quick mode registered, or None if none is. Anything else than the exact format is V01."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        valid = (isinstance(document, dict) and set(document) == {"version", "sha256", "size"} and document["version"] == LOCK_VERSION
                 and isinstance(document["sha256"], str) and _HEX64.fullmatch(document["sha256"]) is not None
                 and isinstance(document["size"], int) and not isinstance(document["size"], bool))
    except (OSError, ValueError):
        valid = False
    if not valid:
        raise _runbook_error(f"{path} no es un registro válido de la huella de la fuente (se esperaba {{version, sha256, size}})", path=str(path))
    return document


def write_source_lock(path: Path, sha256: str, size: int) -> None:
    write_atomic(Path(path), json.dumps({"version": LOCK_VERSION, "sha256": sha256, "size": size}, indent=2, sort_keys=True) + "\n")


def check_source(cfg: PipelineConfig) -> str:
    """V01 (and the byte cap of V03): the file exists and is the accepted one, or, in quick mode, the registered one. Returns its SHA-256. Writes
    nothing, downloads nothing: a missing or different file is refused with the runbook R1 (D02)."""
    source = cfg.source
    path = Path(source.path)
    if not path.is_file():
        raise _runbook_error(f"no existe el archivo de la fuente {path}: hay que colocarlo ahí", path=str(path), reason="missing")
    size = path.stat().st_size
    pinned = bool(source.accepted_sha256)
    if pinned and size != source.accepted_bytes:
        raise _runbook_error(
            f"el archivo {path} pesa {size} bytes y se aceptan {source.accepted_bytes}; no se cambió nada",
            path=str(path), reason="size", expected=source.accepted_bytes, actual=size,
        )
    if size > source.max_bytes:     # the cap is held before the file is read or hashed
        raise _rule("V03", f"el archivo {path} pesa {size} bytes, por encima del límite de {source.max_bytes} ([source] max_bytes)", size=size, max_bytes=source.max_bytes)
    digest = sha256_file(path)
    if pinned:
        if digest != source.accepted_sha256:
            raise _runbook_error(
                f"el archivo {path} tiene la huella SHA-256 {digest} y la aceptada es {source.accepted_sha256}; no se cambió nada",
                path=str(path), reason="sha256", expected=source.accepted_sha256, actual=digest,
            )
        return digest
    registered = read_source_lock(path.parent / LOCK_NAME)
    if registered is not None and registered["sha256"] != digest:
        raise _runbook_error(
            f"el archivo {path} tiene la huella SHA-256 {digest} y la registrada es {registered['sha256']}; no se cambió nada",
            path=str(path), reason="sha256", expected=registered["sha256"], actual=digest,
        )
    return digest


# --- V02-V07: the strict reader ---------------------------------------------------------------------------------------------


def _decode(raw: bytes, number: int, cfg: PipelineConfig) -> str:
    """One line of the file as text (V03): within the bytes allowed for a line, without a null byte and in strict UTF-8; without its ``\\n``."""
    limit = cfg.source.max_line_bytes
    if len(raw) > limit + 1:
        raise _rule("V03", f"la línea {number} tiene más de {limit} bytes ([source] max_line_bytes)", line=number, max_line_bytes=limit)
    if b"\x00" in raw:
        raise _rule("V03", f"la línea {number} tiene un byte nulo", line=number)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _rule("V03", f"la línea {number} tiene UTF-8 inválido", line=number) from None
    return text[:-1] if text.endswith("\n") else text


def _parse_header(handle, cfg: PipelineConfig) -> int:
    """Read the header up to ``@DATA`` (V02) and return the number of lines it took."""
    relation = f"@RELATION {cfg.source.relation}"
    expected = list(cfg.source.attributes)
    before_relation, attributes, number = True, [], 0
    for raw in handle:
        number += 1
        if number > MAX_HEADER_LINES:
            raise _rule("V02", f"la cabecera no termina en @DATA en las primeras {MAX_HEADER_LINES} líneas", line=number)
        text = _decode(raw, number, cfg)
        if before_relation:
            if text == "" or text.startswith("%"):
                continue
            if text != relation:
                raise _rule("V02", f"línea {number}: se esperaba '{relation}' (los comentarios % solo van antes de @RELATION)", line=number)
            before_relation = False
            continue
        if text == "":
            continue
        match = _ATTRIBUTE.fullmatch(text)
        if match:
            attributes.append(match.group(1) or match.group(2))
            continue
        if text == "@DATA":
            if attributes != expected:
                raise _rule(
                    "V02", f"los atributos de la cabecera ({len(attributes)}) no son los de [source] attributes ({len(expected)}), en orden y todos STRING",
                    declared=len(attributes), expected=len(expected), first_difference=next(
                        (k + 1 for k, (a, b) in enumerate(zip(attributes, expected, strict=False)) if a != b), min(len(attributes), len(expected)) + 1),
                )
            return number
        raise _rule("V02", f"línea {number}: se esperaba '@ATTRIBUTE <nombre> STRING' o '@DATA'", line=number)
    raise _rule("V02", "la cabecera no tiene @DATA" if not before_relation else f"la cabecera no tiene '{relation}'", line=number)


def read_header(path: Path, cfg: PipelineConfig) -> int:
    """Check the header of the file (V02, V03) and return its number of lines, ``@DATA`` included. No row is read."""
    with Path(path).open("rb") as handle:
        return _parse_header(handle, cfg)


def _fields(text: str) -> list[str] | None:
    """The 24 fields of a data line without their apostrophes, or None if the line is not 24 fields of the two forms above. A line with every
    field between apostrophes (48 of them, 23 separators) takes the fast path; any other goes through the exact pattern."""
    if text[:1] == "'" and text[-1:] == "'" and text.count("'") == 2 * len(COLUMNS) and text.count("','") == len(COLUMNS) - 1:
        return text[1:-1].split("','")
    if _LINE.fullmatch(text) is None:
        return None
    return [field[1:-1] if field[0] == "'" else field for field in _FIELD.findall(text)]


@dataclass
class _State:
    """What a chunk needs to know about the ones before it."""

    rows: int = 0
    last_hour: np.datetime64 | None = None
    carry_hour: np.datetime64 | None = None
    carry_count: int = 0


def _flush(chunk: list[str], first_line: int, state: _State, cfg: PipelineConfig) -> pd.DataFrame:
    names = cfg.source.attributes
    fields_per_line = len(COLUMNS)
    parts: list[list[str]] = []
    problems: list[dict[str, Any]] = []
    for offset, text in enumerate(chunk):
        line = first_line + offset
        fields = _fields(text)
        if fields is None:
            found = len(_FIELD.findall(text))
            problems.append({"rule_id": "V04", "line": line, "message": (
                f"la línea {line} tiene {found} campos válidos y se esperaban {fields_per_line}, cada uno entre apóstrofos o un entero sin apóstrofos")})
        elif "" in fields:
            column = names[fields.index("")]
            problems.append({"rule_id": "V04", "line": line, "column": column, "message": f"la línea {line}: el campo de {column} está vacío"})
        elif max(map(len, fields)) > MAX_FIELD_CHARS:
            column = next(names[k] for k, f in enumerate(fields) if len(f) > MAX_FIELD_CHARS)
            problems.append({"rule_id": "V04", "line": line, "column": column, "message": f"la línea {line}: el campo de {column} tiene más de {MAX_FIELD_CHARS} caracteres"})
        else:
            parts.append(fields)
        if len(problems) >= EXAMPLES:
            break
    if problems:
        raise SourceError("V04", problems[0]["message"], problems)

    frame = pd.DataFrame(parts, columns=list(COLUMNS))
    numbers = frame[list(NUMERIC_COLUMNS)]
    invalid_numbers = ~numbers.apply(lambda column: column.str.fullmatch(_NUMBER)).fillna(False).astype(bool)
    date_shape = frame["hour"].str.fullmatch(_DATE).fillna(False).astype(bool)
    hours = pd.to_datetime(frame["hour"].where(date_shape), format="%Y-%m-%d %H:%M:%S", errors="coerce")
    invalid_date = hours.isna()
    if invalid_date.any() or invalid_numbers.to_numpy().any():
        wrong = pd.concat([invalid_date.rename("hour"), invalid_numbers], axis=1)
        positions = np.argwhere(wrong.to_numpy())
        positions = positions[np.lexsort((positions[:, 1], positions[:, 0]))][:EXAMPLES]
        problems = []
        for r, c in positions:
            column = COLUMNS[int(c)]
            kind = "fecha" if column == "hour" else "número"
            shown = parts[int(r)][int(c)]
            problems.append({"rule_id": "V05", "line": first_line + int(r), "column": names[int(c)], "reason": kind,
                             "value": shown if len(shown) <= 24 and shown.isprintable() else shown[:24].encode("unicode_escape").decode("ascii")})
        first = problems[0]
        form = "AAAA-MM-DD HH:00:00 de una fecha que existe" if first["reason"] == "fecha" else "-?[0-9]+(,[0-9]+)? (coma decimal)"
        article = "la" if first["reason"] == "fecha" else "el"
        raise SourceError("V05", f"la línea {first['line']}, columna {first['column']}: {article} {first['reason']} no tiene la forma {form}", problems)

    stamps = hours.to_numpy()
    backwards = np.flatnonzero(stamps[1:] < stamps[:-1]) + 1
    if state.last_hour is not None and stamps[0] < state.last_hour:
        backwards = np.concatenate(([0], backwards))
    if len(backwards):
        lines = [first_line + int(k) for k in backwards[:EXAMPLES]]
        raise SourceError("V06", f"las fechas no están en orden: la línea {lines[0]} retrocede", [{"rule_id": "V06", "line": n} for n in lines])
    unique, counts = np.unique(stamps, return_counts=True)
    if state.carry_hour is not None and unique[0] == state.carry_hour:
        counts[0] += state.carry_count
    over = np.flatnonzero(counts > cfg.hours.rows_per_hour)
    if len(over):
        examples = [{"rule_id": "V07", "hour": pd.Timestamp(unique[k]).strftime("%Y-%m-%d %H:%M:%S"), "rows": int(counts[k])} for k in over[:EXAMPLES]]
        raise SourceError("V07", f"la hora {examples[0]['hour']} tiene {examples[0]['rows']} filas, más que rows_per_hour ({cfg.hours.rows_per_hour})", examples)
    state.last_hour, state.carry_hour, state.carry_count = stamps[-1], unique[-1], int(counts[-1])

    out = pd.DataFrame({"row_id": np.arange(state.rows + 1, state.rows + 1 + len(frame), dtype="int64"), "hour": hours.to_numpy()})
    for column in NUMERIC_COLUMNS:
        out[column] = numbers[column].str.replace(",", ".", regex=False).astype("float64").to_numpy()
    state.rows += len(frame)
    return out


def read_arff(path: Path, cfg: PipelineConfig, *, stop_before: datetime | None = None) -> tuple[pd.DataFrame, SourceReport]:
    """Read the ARFF under V02-V07 (see the module's docstring). Returns the rows in file order, with ``row_id`` (from 1), ``hour``,
    ``row_in_hour`` (from 1) and the 23 numeric columns under the names of ``schema.COLUMNS``, and the report. Nothing is written and nothing
    the file says is executed."""
    path = Path(path)
    source = cfg.source
    size = path.stat().st_size
    if size > source.max_bytes:
        raise _rule("V03", f"el archivo {path} pesa {size} bytes, por encima del límite de {source.max_bytes} ([source] max_bytes)", size=size, max_bytes=source.max_bytes)
    stop_text = stop_before.strftime("%Y-%m-%d %H:%M:%S") if stop_before is not None else None
    state, frames, chunk = _State(), [], []
    with path.open("rb") as handle:
        number = _parse_header(handle, cfg)
        first_line = number + 1
        for raw in handle:
            number += 1
            text = _decode(raw, number, cfg)
            if stop_text is not None:
                match = _STOP.match(text)
                if match and match.group(1) >= stop_text:
                    break
            chunk.append(text)
            if state.rows + len(chunk) > source.max_rows:
                raise _rule("V03", f"el archivo tiene más de {source.max_rows} filas ([source] max_rows)", max_rows=source.max_rows)
            if len(chunk) >= CHUNK_ROWS:
                frames.append(_flush(chunk, first_line, state, cfg))
                first_line, chunk = number + 1, []
        if chunk:
            frames.append(_flush(chunk, first_line, state, cfg))
    if not frames:
        raise _rule("V04", "el archivo no tiene filas después de @DATA: sin filas que leer")
    rows = pd.concat(frames, ignore_index=True)
    rows.insert(2, "row_in_hour", (rows.groupby("hour").cumcount() + 1).astype("int64"))
    first_hour, last_hour = rows["hour"].iloc[0].to_pydatetime(), rows["hour"].iloc[-1].to_pydatetime()
    hours = int(rows["hour"].nunique())
    grid = int((rows["hour"].iloc[-1] - rows["hour"].iloc[0]) / pd.Timedelta(hours=1)) + 1
    return rows, SourceReport(len(rows), hours, grid - hours, first_hour, last_hour, size, stop_before)


# --- the canonical tables ----------------------------------------------------------------------------------------------------


def canonical(rows: pd.DataFrame, cfg: PipelineConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``(source_rows, source_hours)`` of the rows ``read_arff`` returned.

    ``source_rows`` has ``row_id``, ``hour``, ``row_in_hour`` and the 19 sensors: **no laboratory column** (D04). ``source_hours`` has one row
    per hour with the four laboratory values of its first row, whether it is partial, the mark of D05 and the age of the feed, and the
    aggregates of the sensors. Whether an hour is a ramp is worked out here, used for its mark and dropped."""
    source_rows = rows[["row_id", "hour", "row_in_hour", *SENSORS]].reset_index(drop=True)
    aggregates = aggregate_rows(rows)
    first = rows.loc[rows["row_in_hour"] == 1, ["hour", *LAB_COLUMNS]].set_index("hour").loc[aggregates["hour"]].reset_index()
    is_ramp = rows.groupby("hour")["silica_pct"].nunique().gt(1)
    states = lab_states(first[["hour", "silica_pct"]], is_ramp)
    ages = feed_age_hours(first[["hour", "feed_silica_pct", "feed_iron_pct"]])
    hours = pd.DataFrame({
        "hour": aggregates["hour"], "hour_key": hour_key(aggregates["hour"]), "rows": aggregates["rows"],
        "is_partial": (aggregates["rows"] < cfg.hours.rows_per_hour).to_numpy(), "silica_pct": first["silica_pct"], "iron_conc_pct": first["iron_conc_pct"],
        "feed_silica_pct": first["feed_silica_pct"], "feed_iron_pct": first["feed_iron_pct"], "lab_state": states.to_numpy(),
        "feed_silica_age_h": ages["feed_silica_age_h"], "feed_iron_age_h": ages["feed_iron_age_h"],
    })
    hours = pd.concat([hours, aggregates.drop(columns=["hour", "rows"])], axis=1)
    assert list(hours.columns) == SOURCE_HOURS_SCHEMA.names and list(source_rows.columns) == SOURCE_ROWS_SCHEMA.names
    return source_rows, hours


def write_canonical(source_rows: pd.DataFrame, source_hours: pd.DataFrame, interim_dir: Path, source_sha256: str, source_bytes: int,
                    counts: dict[str, int]) -> None:
    """Write the two Parquet files atomically and then ``interim_manifest.json`` with their hashes and the source's: a failure between the tables
    and the manifest leaves tables that do not match their manifest, which every reader refuses and the task rebuilds."""
    interim_dir = Path(interim_dir)
    files = {}
    for name, frame, schema in ((ROWS_NAME, source_rows, SOURCE_ROWS_SCHEMA), (HOURS_NAME, source_hours, SOURCE_HOURS_SCHEMA)):
        table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False)
        metadata = {**(table.schema.metadata or {}), FINGERPRINT_KEY: source_sha256.encode("ascii"), ATTRIBUTION_KEY: ATTRIBUTION.encode("utf-8")}
        with atomic_path(interim_dir / name) as temporary:
            pq.write_table(table.replace_schema_metadata(metadata), temporary)
        files[name] = sha256_file(interim_dir / name)
    manifest = {"version": INTERIM_MANIFEST_VERSION, "source_sha256": source_sha256, "source_bytes": source_bytes, "counts": counts, "files": files}
    write_atomic(interim_dir / INTERIM_MANIFEST, json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def _manifest_problem(interim_dir: Path) -> tuple[str | None, dict[str, Any]]:
    folder = Path(interim_dir)
    path = folder / INTERIM_MANIFEST
    if not path.is_file():
        return f"falta {INTERIM_MANIFEST} en {folder}: las tablas canónicas no tienen su manifiesto", {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        valid = (isinstance(document, dict) and set(document) == {"version", "source_sha256", "source_bytes", "counts", "files"}
                 and document["version"] == INTERIM_MANIFEST_VERSION and isinstance(document["source_sha256"], str)
                 and _HEX64.fullmatch(document["source_sha256"]) is not None and isinstance(document["files"], dict)
                 and set(document["files"]) == {ROWS_NAME, HOURS_NAME} and isinstance(document["counts"], dict)
                 and all(isinstance(v, str) and _HEX64.fullmatch(v) for v in document["files"].values()))
    except (OSError, ValueError):
        valid = False
    if not valid:
        return f"{INTERIM_MANIFEST} no es un manifiesto válido de las tablas canónicas", {}
    for name, expected in document["files"].items():
        target = folder / name
        if not target.is_file():
            return f"falta {name}, que el manifiesto nombra", {}
        if sha256_file(target) != expected:
            return f"{name} no coincide con la huella que dice el manifiesto: es de otra escritura", {}
        try:
            metadata = pq.read_schema(target).metadata or {}
        except (OSError, pa.ArrowException):
            return f"{name} no se puede leer", {}
        if metadata.get(FINGERPRINT_KEY) != document["source_sha256"].encode("ascii"):
            return f"{name} no es de la fuente que dice el manifiesto", {}
    return None, document


def canonical_state(interim_dir: Path) -> str | None:
    """The SHA-256 of the source the tables were built from, or None if they are not the files their manifest names."""
    problem, document = _manifest_problem(interim_dir)
    return None if problem is not None else document["source_sha256"]


def read_canonical(interim_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``(source_rows, source_hours)``; ``InterimError`` if the files are not the ones their manifest names."""
    problem, _document = _manifest_problem(interim_dir)
    if problem is not None:
        raise InterimError(problem)
    return (pq.read_table(Path(interim_dir) / ROWS_NAME).to_pandas(), pq.read_table(Path(interim_dir) / HOURS_NAME).to_pandas())


# --- the first task ----------------------------------------------------------------------------------------------------------


class _HasConfig(Protocol):
    cfg: PipelineConfig


def fetch_source(ctx: _HasConfig) -> dict[str, Any]:
    """Task 1: make sure the file is the pinned one (V01), and that the canonical tables are built from it.

    The tables are rebuilt only when they are missing, do not match their manifest or come from another hash, so repeating the task changes
    nothing. A rejected source writes nothing; in quick mode the hash is registered only after the file was read without a failing rule."""
    cfg = ctx.cfg
    source, interim_dir = cfg.source, cfg.paths.interim_dir
    digest = check_source(cfg)
    size = Path(source.path).stat().st_size
    lock = Path(source.path).parent / LOCK_NAME
    result: dict[str, Any] = {"sha256": digest, "size": size}
    if canonical_state(interim_dir) == digest:
        document = _manifest_problem(interim_dir)[1]
        if not source.accepted_sha256 and read_source_lock(lock) is None:
            write_source_lock(lock, digest, size)
        return result | {"built": False, **document["counts"]}
    rows, report = read_arff(source.path, cfg)
    source_rows, source_hours = canonical(rows, cfg)
    counts = {"rows": report.rows, "hours": report.hours, "missing_hours": report.missing_hours}
    write_canonical(source_rows, source_hours, interim_dir, digest, size, counts)
    if not source.accepted_sha256:
        write_source_lock(lock, digest, size)
    return result | {"built": True, **counts}
