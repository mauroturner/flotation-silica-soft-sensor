"""Deliveries: the feed that stands in for the hourly lines of a plant over a static file (RF05, D21); adapted from project 04.

The canonical rows and hours are cut into a fixed plan that comes from the configuration: the launch ``L<yyyy-mm-dd>`` (every hour up to
``deliveries.launch_last_hour``), a delivery ``D<...>`` of ``deliveries.cadence_hours`` hours at a time up to ``hours.last_hour`` (the last one
shorter when the cadence does not divide the rest) and the close ``C<yyyy-mm-dd>``, which has no rows and whose ``as_of`` is the last hour plus
``lab.latency_hours``: the instant the last analysis arrives. The ``as_of`` of the others is the end of their last hour. A row, and the hour that
holds it, belong to the delivery of their hour, so an hour is never split.

Each delivery is two Parquet files, ``<id>.rows.parquet`` (the rows, no laboratory column: V15) and ``<id>.hours.parquet`` (one row per hour,
with the first row's laboratory values), listed in ``manifest.json`` (``{"version": 1, "entries": [...]}``, written to a temporary file and
renamed) with its period, rows, hours and SHA-256 and a status that moves from ``published`` to ``loaded`` (or ``rejected``). Publishing is
idempotent: the same rows give the same bytes and leave the manifest untouched; a loaded delivery is never replaced. The next pending delivery
is always the first of the plan that is not loaded (runbook R4).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from flotsilica.config import DeliveriesConfig, HoursConfig, LabConfig
from flotsilica.files import write_atomic
from flotsilica.ingest import ATTRIBUTION, ATTRIBUTION_KEY
from flotsilica.schema import SOURCE_HOURS_SCHEMA, SOURCE_ROWS_SCHEMA

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
DELIVERY_KINDS = ("launch", "daily", "close")
DELIVERY_STATUSES = ("published", "loaded", "rejected")
DELIVERY_ID_KEY = b"flotsilica.delivery_id"
PERIOD_KEY = b"flotsilica.period"
HOUR = timedelta(hours=1)
_DATETIME_FIELDS = ("first_hour", "last_hour", "as_of")
_NO_PERIOD = "none"


class _HasCalendar(Protocol):     # PipelineConfig and SealedConfig both have these sections
    hours: HoursConfig
    lab: LabConfig
    deliveries: DeliveriesConfig


@dataclass(frozen=True)
class DeliverySpec:
    """One delivery of the plan: the hours it holds (none for the close) and the instant the run that loads it has reached."""

    delivery_id: str
    kind: str
    first_hour: datetime | None
    last_hour: datetime | None
    as_of: datetime


@dataclass(frozen=True)
class ManifestEntry:
    delivery_id: str
    kind: str
    first_hour: datetime | None
    last_hour: datetime | None
    as_of: datetime
    rows: int
    hours: int
    rows_sha256: str
    hours_sha256: str
    sha256: str
    rows_file: str
    hours_file: str
    published_at: str
    status: str
    run_key: str | None


def delivery_plan(view: _HasCalendar) -> list[DeliverySpec]:
    """The fixed plan of D21: the launch, the deliveries of ``cadence_hours`` hours and the close, contiguous, each with its ``as_of``."""
    h, d, lab = view.hours, view.deliveries, view.lab
    cadence = timedelta(hours=d.cadence_hours)
    plan = [DeliverySpec(f"L{d.launch_last_hour:%Y-%m-%d}", "launch", h.first_hour, d.launch_last_hour, d.launch_last_hour + HOUR)]
    # the day if the delivery starts at midnight and every delivery is of whole days; otherwise the hour too, so that an id is never repeated
    by_day = d.cadence_hours % 24 == 0
    start = d.launch_last_hour + HOUR
    while start <= h.last_hour:
        end = min(start + cadence - HOUR, h.last_hour)
        stamp = f"{start:%Y-%m-%d}" if by_day and start.hour == 0 else f"{start:%Y-%m-%dT%H}"
        plan.append(DeliverySpec(f"D{stamp}", "daily", start, end, end + HOUR))
        start = end + HOUR
    plan.append(DeliverySpec(f"C{h.last_hour + HOUR:%Y-%m-%d}", "close", None, None, h.last_hour + timedelta(hours=lab.latency_hours)))
    return plan


# --- manifest ---------------------------------------------------------------------------------------------------


def _instant(value: Any) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _entry_from(raw: Any) -> ManifestEntry:
    names = {f.name for f in fields(ManifestEntry)}
    if not isinstance(raw, dict) or set(raw) != names:
        raise KeyError(f"claves distintas de las esperadas: {sorted(names ^ set(raw)) if isinstance(raw, dict) else raw!r}")
    values = dict(raw)
    values["as_of"] = datetime.fromisoformat(values["as_of"])
    for key in ("first_hour", "last_hour"):
        values[key] = _instant(values[key])
    for key in ("rows", "hours"):
        if not isinstance(values[key], int) or isinstance(values[key], bool) or values[key] < 0:
            raise TypeError(f"{key}: se esperaba un entero, se recibió {values[key]!r}")
    for key in ("delivery_id", "rows_sha256", "hours_sha256", "sha256", "rows_file", "hours_file", "published_at"):
        if not isinstance(values[key], str):
            raise TypeError(f"{key}: se esperaba un texto, se recibió {values[key]!r}")
    if values["kind"] not in DELIVERY_KINDS:
        raise ValueError(f"kind: {values['kind']!r} no es uno de {', '.join(DELIVERY_KINDS)}")
    if values["status"] not in DELIVERY_STATUSES:
        raise ValueError(f"status: {values['status']!r} no es uno de {', '.join(DELIVERY_STATUSES)}")
    if values["run_key"] is not None and not isinstance(values["run_key"], str):
        raise TypeError(f"run_key: se esperaba un texto o null, se recibió {values['run_key']!r}")
    return ManifestEntry(**values)


def read_manifest(path: Path) -> list[ManifestEntry]:
    """The entries in the order they were published; a missing manifest is an empty list."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("version") != MANIFEST_VERSION or set(document) != {"version", "entries"}:
            raise KeyError("versión o claves de primer nivel inesperadas")
        entries = [_entry_from(raw) for raw in document["entries"]]
        ids = [e.delivery_id for e in entries]
        if len(set(ids)) != len(ids):
            raise ValueError("hay entregas repetidas")
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError(f"{path} no es un manifiesto de entregas válido: {error}") from error
    return entries


def _write_manifest(path: Path, entries: list[ManifestEntry]) -> None:
    def encode(entry: ManifestEntry) -> dict[str, Any]:
        document = asdict(entry)
        for key in _DATETIME_FIELDS:
            document[key] = None if document[key] is None else document[key].isoformat()
        return document

    write_atomic(Path(path), json.dumps({"version": MANIFEST_VERSION, "entries": [encode(e) for e in entries]}, indent=2, ensure_ascii=False) + "\n")


def next_pending(manifest: Path, plan: list[DeliverySpec]) -> DeliverySpec | None:
    """The first delivery of the plan that is not loaded: the next one to run, or None when the plan is complete.

    A delivery that is ``published`` or ``rejected`` stays the pending one (a failed run is repeated with the same delivery). An entry that is
    not in the plan, has another period, or is loaded after one that is not is an error (runbook R4): the plan is never skipped.
    """
    entries = {e.delivery_id: e for e in read_manifest(manifest)}
    by_id = {spec.delivery_id: spec for spec in plan}
    for delivery_id, entry in entries.items():
        spec = by_id.get(delivery_id)
        if spec is None:
            raise ValueError(f"el manifiesto trae la entrega {delivery_id}, que no está en el plan (runbook R4)")
        if (entry.kind, entry.first_hour, entry.last_hour, entry.as_of) != (spec.kind, spec.first_hour, spec.last_hour, spec.as_of):
            raise ValueError(f"la entrega {delivery_id} tiene otro período en el manifiesto ({entry.first_hour} a {entry.last_hour}) que en el plan "
                             f"({spec.first_hour} a {spec.last_hour}) (runbook R4)")
    pending: DeliverySpec | None = None
    for spec in plan:
        entry = entries.get(spec.delivery_id)
        loaded = entry is not None and entry.status == "loaded"
        if pending is None:
            if not loaded:
                pending = spec
        elif loaded:
            raise ValueError(f"la entrega {spec.delivery_id} está cargada pero la anterior, {pending.delivery_id}, no lo está (runbook R4)")
    return pending


def mark_delivery(manifest: Path, delivery_id: str, status: str, run_key: str | None = None) -> None:
    """Set the status of a delivery (and its run, if given); everything else in the manifest is kept.

    A loaded delivery stays loaded by the run that loaded it: marking it rejected or published, or loaded by another run, is refused and the
    manifest is not touched, because ``next_pending`` would offer it again and its rows would load twice (project 03, D86 and D93). Out of
    ``published`` and ``rejected`` every status is allowed: a rejected delivery is published again and loaded by a later run."""
    if status not in DELIVERY_STATUSES:
        raise ValueError(f"status: {status!r} no es uno de {', '.join(DELIVERY_STATUSES)}")
    entries = read_manifest(manifest)
    entry = next((e for e in entries if e.delivery_id == delivery_id), None)
    if entry is None:
        raise ValueError(f"no hay una entrega {delivery_id} en el manifiesto {manifest}")
    if entry.status == "loaded" and (status != "loaded" or (run_key is not None and run_key != entry.run_key)):
        raise ValueError(f"la entrega {delivery_id} ya está cargada por la corrida {entry.run_key!r} y no pasa a {status!r}"
                         f"{'' if run_key is None else f' de la corrida {run_key!r}'}: sus filas ya están en el almacén (runbook R4)")
    _write_manifest(Path(manifest), [
        replace(e, status=status, run_key=run_key if run_key is not None else e.run_key) if e.delivery_id == delivery_id else e for e in entries
    ])
    logger.info("manifest %s: delivery %s marked %s", manifest, delivery_id, status)


# --- publishing ---------------------------------------------------------------------------------------------------


def _within(spec: DeliverySpec, hours: pd.Series) -> pd.Series:
    if spec.first_hour is None or spec.last_hour is None:     # the close holds nothing
        return pd.Series(False, index=hours.index)
    return (hours >= pd.Timestamp(spec.first_hour)) & (hours <= pd.Timestamp(spec.last_hour))


def delivery_rows(spec: DeliverySpec, rows: pd.DataFrame) -> pd.DataFrame:
    """The rows whose hour falls in the period of `spec` (a selection; `rows` is not touched)."""
    return rows.loc[_within(spec, rows["hour"])]


def delivery_hours(spec: DeliverySpec, hours: pd.DataFrame) -> pd.DataFrame:
    """The hours of `hours` that fall in the period of `spec` (a selection; `hours` is not touched)."""
    return hours.loc[_within(spec, hours["hour"])]


def assert_covered(rows: pd.DataFrame, plan: list[DeliverySpec]) -> None:
    """Every row must fall in some period of the plan; otherwise it would never be delivered."""
    periods = [s for s in plan if s.first_hour is not None]
    first, last = pd.Timestamp(periods[0].first_hour), pd.Timestamp(periods[-1].last_hour)
    outside = int(((rows["hour"] < first) | (rows["hour"] > last)).sum())
    if outside:
        raise ValueError(f"{outside} filas tienen una hora fuera de todas las entregas del plan ({first} a {last}) y no se entregarían nunca")


def _read(path: Path) -> pd.DataFrame:
    return pq.read_table(Path(path)).to_pandas()


def read_delivery(out_dir: Path, entry: ManifestEntry) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``(rows, hours)`` of a published delivery, as the canonical tables have them."""
    return _read(Path(out_dir) / entry.rows_file), _read(Path(out_dir) / entry.hours_file)


def _serialise(spec: DeliverySpec, frame: pd.DataFrame, schema: pa.Schema) -> bytes:
    table = pa.Table.from_pandas(frame.reset_index(drop=True)[schema.names], schema=schema, preserve_index=False)
    period = _NO_PERIOD if spec.first_hour is None or spec.last_hour is None else f"{spec.first_hour.isoformat()}/{spec.last_hour.isoformat()}"
    metadata = {**(table.schema.metadata or {}), DELIVERY_ID_KEY: spec.delivery_id.encode("ascii"), PERIOD_KEY: period.encode("ascii"),
                ATTRIBUTION_KEY: ATTRIBUTION.encode("utf-8")}
    sink = io.BytesIO()
    pq.write_table(table.replace_schema_metadata(metadata), sink)
    return sink.getvalue()


def delivery_digest(rows_sha256: str, hours_sha256: str) -> str:
    """The SHA-256 of a delivery: of the two file hashes, in the order rows, hours (V13 compares it with the manifest's)."""
    return hashlib.sha256(f"{rows_sha256}\n{hours_sha256}".encode("ascii")).hexdigest()


def publish(spec: DeliverySpec, rows: pd.DataFrame, hours: pd.DataFrame, out_dir: Path) -> ManifestEntry:
    """Write the rows and the hours of `spec`'s period as ``<out_dir>/<delivery_id>.rows.parquet`` and ``.hours.parquet`` and list them in
    ``<out_dir>/manifest.json``. `rows` and `hours` are the canonical tables; the period is selected here.

    The same rows give the same bytes, so publishing again changes nothing (not even the entry), and a file that went missing or was damaged is
    written again. If the rows changed, a delivery that is not loaded is replaced (and goes back to ``published``); a loaded one is never
    replaced: its rows are already in the warehouse. The files are written before the manifest, so a failure in between lists nothing.
    """
    out_dir = Path(out_dir)
    manifest_path = out_dir / MANIFEST_NAME
    selected_rows, selected_hours = delivery_rows(spec, rows), delivery_hours(spec, hours)
    payloads = {"rows": _serialise(spec, selected_rows, SOURCE_ROWS_SCHEMA), "hours": _serialise(spec, selected_hours, SOURCE_HOURS_SCHEMA)}
    rows_digest, hours_digest = (hashlib.sha256(payloads[k]).hexdigest() for k in ("rows", "hours"))
    digest = delivery_digest(rows_digest, hours_digest)
    files = {"rows": out_dir / f"{spec.delivery_id}.rows.parquet", "hours": out_dir / f"{spec.delivery_id}.hours.parquet"}
    entries = read_manifest(manifest_path)
    existing = next((e for e in entries if e.delivery_id == spec.delivery_id), None)

    def write_files() -> None:
        for key, path in files.items():
            if not path.exists() or path.read_bytes() != payloads[key]:
                write_atomic(path, payloads[key])

    if existing is not None and existing.sha256 == digest:
        write_files()
        return existing
    if existing is not None and existing.status == "loaded":
        raise ValueError(f"la entrega {spec.delivery_id} ya está cargada en el almacén y sus filas cambiaron en la fuente "
                         f"({existing.sha256[:12]} → {digest[:12]}); no se publica de nuevo (runbook R4)")
    write_files()
    entry = ManifestEntry(spec.delivery_id, spec.kind, spec.first_hour, spec.last_hour, spec.as_of, len(selected_rows), len(selected_hours),
                          rows_digest, hours_digest, digest, files["rows"].name, files["hours"].name, datetime.now(UTC).isoformat(timespec="seconds"),
                          "published", None)
    _write_manifest(manifest_path, [entry if e.delivery_id == spec.delivery_id else e for e in entries] if existing else [*entries, entry])
    logger.info("published %s: %d rows, %d hours, sha256 %s", spec.delivery_id, entry.rows, entry.hours, digest)
    return entry
