"""Validation of the source, of every delivery and of its hours, and the validation report (RF06, D23; plan, section 6); adapted from project 04.

The rules are the table of the plan, section 6, in its order (``RULES``). Each declares its severity, its scope (``source``, ``delivery``,
``hours`` or ``model``) and how it is published over runs (``aggregation``: ``source`` once, from the report of the source; ``per_run`` summed
over the loaded runs; ``latest`` read once from the last loaded run, because it already holds the earlier ones: project 03's D94).

- The rules of the source (V01-V07, I01) are not evaluated again here: the first task ran them while it fetched and read the file, so
  ``validate_source`` turns its outcome (a ``SourceError`` naming the failing rule, or the ``SourceReport`` of a clean read) into results.
- The rules of the delivery and of its hours (V10-V15, V20-V24, I02, I03) read the delivery, the plan, its manifest entry and what the warehouse
  already holds (``deliveries``, ``raw_rows`` and ``lab_hours``, plan section 5), which they only read.
- The rules of the model (M01-M06, I04, I05) are evaluated by their tasks, which add them with ``model_result`` and ``add_results``.

A rule that cannot be evaluated because an earlier blocking rule failed is listed in ``not_evaluated``; it is never reported as passed.
``rows_affected`` counts rows (for a rule about hours, the rows of those hours) and ``hours_affected`` the distinct hours. An example names an
hour or a row id and never what was measured in it (nothing that identifies a value of the plant, D43 aside, and no row of the source).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from flotsilica.deliveries import DeliverySpec, ManifestEntry, delivery_digest, delivery_plan
from flotsilica.files import sha256_file, write_atomic
from flotsilica.hours import aggregate_rows
from flotsilica.ingest import SourceReport
from flotsilica.schema import AGGREGATE_COLUMNS, SENSORS, SOURCE_HOURS_SCHEMA, SOURCE_ROWS_SCHEMA, SourceError

logger = logging.getLogger(__name__)

EXAMPLE_LIMIT = 5
UNCHANGED_FEED_HOURS = 24            # I02: a feed that has not changed for this many hours or more
AGGREGATE_TOLERANCE = 1e-9          # V14: the aggregates of the hours against the ones recomputed from the rows
_IN_CHUNK = 900                      # the ids of a query by chunks, under every limit of SQLite's variables
_SAFE_RUN_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_PATH_KEYS = ("path",)               # keys of a SourceError problem that hold a path of this machine


class Severity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


class Aggregation(StrEnum):
    SOURCE = "source"
    PER_RUN = "per_run"
    LATEST = "latest"


SEVERITY_ES = {Severity.BLOCKING: "bloqueante", Severity.WARNING: "advertencia", Severity.INFO: "informativa"}
STATUS_ES = {"pass": "pasa", "fail": "falla", "warn": "advierte", "not_evaluated": "no evaluada"}


@dataclass(frozen=True)
class Rule:
    name_es: str
    severity: Severity
    scope: str               # "source", "delivery", "hours" or "model"
    aggregation: Aggregation


_B, _W, _I = Severity.BLOCKING, Severity.WARNING, Severity.INFO
_S, _P, _L = Aggregation.SOURCE, Aggregation.PER_RUN, Aggregation.LATEST

# rule id -> rule, in the order of the table of the plan (section 6): the report's order; tests/contract/test_validate.py compares it with the table
RULES: dict[str, Rule] = {
    "V01": Rule("El archivo existe y tiene el tamaño y la huella aceptados (o la registrada, en modo rápido)", _B, "source", _S),
    "V02": Rule("Cabecera exacta: @RELATION, los 24 @ATTRIBUTE en orden y todos STRING, @DATA una vez", _B, "source", _S),
    "V03": Rule("UTF-8 estricto, sin byte nulo, líneas dentro del tope, archivo y filas dentro de sus topes", _B, "source", _S),
    "V04": Rule("Cada fila con 24 campos, cada uno entre apóstrofos o un entero sin apóstrofos, y ninguno vacío", _B, "source", _S),
    "V05": Rule("Fecha AAAA-MM-DD HH:00:00 y números con coma decimal", _B, "source", _S),
    "V06": Rule("Fechas no decrecientes", _B, "source", _S),
    "V07": Rule("Ninguna hora con más filas que las de una hora completa", _B, "source", _S),
    "V10": Rule("La entrega es la siguiente del plan y su período empieza en la hora siguiente al fin de la anterior", _B, "delivery", _P),
    "V11": Rule("Cada hora de la entrega está dentro de su período", _B, "delivery", _P),
    "V12": Rule("Ninguna hora ni identificador de fila de la entrega está ya en el almacén ni repetido dentro de ella", _B, "delivery", _P),
    "V13": Rule("Filas, horas y SHA-256 son los del manifiesto; solo el cierre puede no tener filas", _B, "delivery", _P),
    "V14": Rule("Los agregados de cada hora son los de sus filas", _B, "delivery", _P),
    "V15": Rule("Las filas de la entrega no traen columnas de laboratorio (solo la hora trae su primera fila)", _B, "delivery", _P),
    "V20": Rule("Hora incompleta (se marca y se usa)", _W, "hours", _P),
    "V21": Rule("Hora con menos filas que el mínimo (no se estima)", _W, "hours", _P),
    "V22": Rule("Análisis interpolado (no es objetivo ni rasgo)", _W, "hours", _P),
    "V23": Rule("Análisis repetido (no es objetivo ni rasgo)", _W, "hours", _P),
    "V24": Rule("Alimentación que cambia dentro de la hora (se usa la primera fila)", _W, "hours", _P),
    "I01": Rule("Horas faltantes en la grilla", _I, "source", _S),
    "I02": Rule("Horas con la alimentación sin cambio desde hace 24 h o más", _I, "hours", _L),
    "I03": Rule("Sensor constante dentro de la hora", _I, "hours", _P),
    "I04": Rule("Estimaciones emitidas", _I, "model", _P),
    "I05": Rule("Estimaciones sin las entradas necesarias, con el motivo", _I, "model", _P),
    "M01": Rule("Trampa de fuga: el MAE en V1 del elegido es menor que el umbral de alarma por el de la persistencia", _B, "model", _L),
    "M02": Rule("Las columnas de la matriz son exactamente las del conjunto elegido y ninguna está prohibida", _B, "model", _P),
    "M03": Rule("El artefacto del modelo tiene la huella registrada, antes de deserializarlo", _B, "model", _P),
    "M04": Rule("Estimación y rango finitos, con el rango alrededor de la estimación", _B, "model", _P),
    "M05": Rule("La configuración es la sellada (si no, todo lo calculado es posterior al sello)", _W, "model", _L),
    "M06": Rule("Entrenamiento, V1 y V2 con las horas frescas mínimas", _B, "model", _L),
}
SOURCE_BLOCKING = tuple(rule_id for rule_id, rule in RULES.items() if rule.scope == "source" and rule.severity is Severity.BLOCKING)
DELIVERY_RULES = tuple(rule_id for rule_id, rule in RULES.items() if rule.scope in ("delivery", "hours"))
MODEL_RULES = tuple(rule_id for rule_id, rule in RULES.items() if rule.scope == "model")


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    name_es: str
    severity: Severity
    scope: str
    aggregation: Aggregation
    passed: bool
    rows_affected: int
    hours_affected: int
    examples: list[dict]

    @property
    def status(self) -> str:
        """``pass``, ``fail`` (a blocking rule) or ``warn`` (a warning); an informative rule always passes."""
        if self.passed:
            return "pass"
        return "fail" if self.severity is Severity.BLOCKING else "warn"


@dataclass(frozen=True)
class ValidationReport:
    run_key: str
    source_sha256: str
    delivery_id: str | None
    rows_delivery: int
    hours_delivery: int
    results: list[RuleResult]
    not_evaluated: tuple[str, ...] = field(default=())

    @property
    def blocking_failed(self) -> bool:
        return any(r.severity is Severity.BLOCKING and not r.passed for r in self.results)


class ValidationError(RuntimeError):
    """The run was rejected: at least one blocking rule failed (raised by the ``validate`` task)."""

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        failing = ", ".join(r.rule_id for r in report.results if r.severity is Severity.BLOCKING and not r.passed)
        super().__init__(f"la validación de {report.run_key} rechazó la corrida: fallan las reglas bloqueantes {failing}")


# --- helpers ------------------------------------------------------------------------------------------------------------


def _py(value: Any) -> Any:
    """A JSON-friendly Python value from a pandas or numpy scalar (instants as ISO text)."""
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _iso(value: Any) -> str:
    return pd.Timestamp(value).isoformat()


def _store_hour(value: Any) -> str:
    """An hour as the warehouse stores it (plan, section 5): ``YYYY-MM-DD HH:00:00``."""
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:00:00")


def _stored(hours: pd.Series) -> pd.Series:
    """The hours of a series as the warehouse stores them, always text (also when the series is empty)."""
    return pd.Series([_store_hour(h) for h in hours], index=hours.index, dtype=object)


def _result(rule_id: str, passed: bool, rows: int = 0, hours: int = 0, examples: list[dict] | None = None) -> RuleResult:
    rule = RULES[rule_id]
    return RuleResult(rule_id, rule.name_es, rule.severity, rule.scope, rule.aggregation, True if rule.severity is Severity.INFO else bool(passed),
                      int(rows), int(hours), examples or [])


def _ordered(results: dict[str, RuleResult]) -> list[RuleResult]:
    return [results[rule_id] for rule_id in RULES if rule_id in results]


def _log_verdict(report: ValidationReport) -> None:
    blocking = [r.rule_id for r in report.results if r.status == "fail"]
    warnings = [r.rule_id for r in report.results if r.status == "warn"]
    logger.log(logging.WARNING if blocking else logging.INFO, "validation of %s (%s): %s; rows=%d; hours=%d; blocking failed: %s; warnings: %s; not evaluated: %s",
               report.run_key, report.delivery_id or "source", "rejected" if blocking else "accepted", report.rows_delivery, report.hours_delivery,
               ", ".join(blocking) or "none", ", ".join(warnings) or "none", ", ".join(report.not_evaluated) or "none")


# --- the rules of the source --------------------------------------------------------------------------------------------


def _source_problem(problem: dict[str, Any]) -> dict[str, Any]:
    """A problem of a ``SourceError`` as an example: JSON-safe and without a path of this machine."""
    return {key: _py(value) if not isinstance(value, (list, dict)) else value for key, value in problem.items() if key not in _PATH_KEYS}


def validate_source(outcome: SourceError | SourceReport, *, run_key: str, source_sha256: str = "") -> ValidationReport:
    """The report of rules V01-V07 and I01 from what the first task found.

    A ``SourceError`` fails its rule (V01 to V07, nothing else), the blocking rules before it pass and every other rule is ``not_evaluated``.
    A ``SourceReport`` (the canonical reading's report) means the whole source was read: V01-V07 pass and I01 counts the hours missing from the grid.
    """
    results: dict[str, RuleResult] = {}
    if isinstance(outcome, SourceError):
        if outcome.rule_id not in SOURCE_BLOCKING:
            raise ValueError(f"{outcome.rule_id} no es una regla bloqueante de la fuente ({', '.join(SOURCE_BLOCKING)})")
        for rule_id in SOURCE_BLOCKING[: SOURCE_BLOCKING.index(outcome.rule_id)]:
            results[rule_id] = _result(rule_id, True)
        examples = [_source_problem(p) for p in outcome.problems[:EXAMPLE_LIMIT]] or [{"message": str(outcome)}]
        results[outcome.rule_id] = _result(outcome.rule_id, False, examples=examples)
        not_evaluated = tuple(r for r in RULES if r not in results)
    else:
        for rule_id in SOURCE_BLOCKING:
            results[rule_id] = _result(rule_id, True)
        results["I01"] = _result("I01", True, hours=outcome.missing_hours)
        not_evaluated = ()
    report = ValidationReport(run_key, source_sha256, None, 0, 0, _ordered(results), not_evaluated)
    _log_verdict(report)
    return report


# --- what the warehouse already holds (read only) -------------------------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def loaded_deliveries(conn: sqlite3.Connection) -> set[str]:
    """The deliveries the warehouse holds as loaded (none before the first load)."""
    if not _table_exists(conn, "deliveries"):
        return set()
    return {row[0] for row in conn.execute("SELECT delivery_id FROM deliveries WHERE status = 'loaded'")}


def known_row_ids(conn: sqlite3.Connection, ids: Iterable[int]) -> set[int]:
    """Which of `ids` are already in ``raw_rows``."""
    if not _table_exists(conn, "raw_rows"):
        return set()
    wanted, found = [int(i) for i in ids], set()
    for start in range(0, len(wanted), _IN_CHUNK):
        chunk = wanted[start:start + _IN_CHUNK]
        found.update(row[0] for row in conn.execute(f"SELECT row_id FROM raw_rows WHERE row_id IN ({','.join('?' * len(chunk))})", chunk))
    return found


def known_hours(conn: sqlite3.Connection) -> pd.DataFrame:
    """The hours already loaded (``lab_hours``): ``hour`` as stored (text), ``rows`` and the two ages of the feed."""
    columns = ("hour", "rows", "feed_silica_age_h", "feed_iron_age_h")
    rows = conn.execute(f"SELECT {', '.join(columns)} FROM lab_hours ORDER BY hour").fetchall() if _table_exists(conn, "lab_hours") else []
    return pd.DataFrame(rows, columns=list(columns))


# --- the rules of the delivery ------------------------------------------------------------------------------------------


def _require_columns(rows: pd.DataFrame, hours: pd.DataFrame) -> None:
    for what, frame, schema in (("las filas", rows, SOURCE_ROWS_SCHEMA), ("las horas", hours, SOURCE_HOURS_SCHEMA)):
        missing = [name for name in schema.names if name not in frame.columns]
        if missing:
            raise ValueError(f"la entrega no tiene las columnas del esquema canónico en {what}: faltan {', '.join(missing)}")


def _hour_examples(rows: pd.DataFrame, hours: pd.Series | None = None) -> list[dict]:
    """Examples by row id and hour, or by hour: never a value."""
    if hours is not None:
        return [{"hour": _iso(h)} for h in hours.head(EXAMPLE_LIMIT)]
    return [{"row_id": int(r), "hour": _iso(h)} for r, h in zip(rows["row_id"].head(EXAMPLE_LIMIT), rows["hour"].head(EXAMPLE_LIMIT), strict=True)]


def _rule_v10(rows: pd.DataFrame, hours: pd.DataFrame, spec: DeliverySpec, loaded: set[str], view: Any) -> RuleResult:
    plan = delivery_plan(view)
    index = next((i for i, planned in enumerate(plan) if planned.delivery_id == spec.delivery_id), None)
    problem: dict[str, Any] | None = None
    if index is None:
        problem = {"reason": "not_in_plan", "plan": [p.delivery_id for p in plan]}
    elif plan[index] != spec:
        planned = plan[index]
        problem = {"reason": "other_period", "period": [_iso(spec.first_hour) if spec.first_hour else None, _iso(spec.last_hour) if spec.last_hour else None],
                   "expected_period": [_iso(planned.first_hour) if planned.first_hour else None, _iso(planned.last_hour) if planned.last_hour else None]}
    elif spec.delivery_id in loaded:
        problem = {"reason": "already_loaded"}
    else:
        missing = [p.delivery_id for p in plan[:index] if p.delivery_id not in loaded]
        if missing:
            problem = {"reason": "previous_not_loaded", "missing": missing}
    if problem is None:
        return _result("V10", True)
    return _result("V10", False, len(rows), len(hours), [{"delivery_id": spec.delivery_id, **problem}])


def _outside(frame: pd.DataFrame, spec: DeliverySpec) -> pd.Series:
    """The rows (or hours) of `frame` outside the period of `spec`; the close, which has no period, holds nothing."""
    if spec.first_hour is None or spec.last_hour is None:
        return pd.Series(True, index=frame.index)
    return (frame["hour"] < pd.Timestamp(spec.first_hour)) | (frame["hour"] > pd.Timestamp(spec.last_hour))


def _rule_v11(rows: pd.DataFrame, hours: pd.DataFrame, spec: DeliverySpec) -> RuleResult:
    bad_rows, bad_hours = rows[_outside(rows, spec)], hours[_outside(hours, spec)]
    examples = ([{"table": "rows", **e} for e in _hour_examples(bad_rows)] + [{"table": "hours", **e} for e in _hour_examples(bad_rows.iloc[0:0], bad_hours["hour"])])
    distinct = pd.concat([bad_rows["hour"], bad_hours["hour"]]).nunique()
    return _result("V11", bad_rows.empty and bad_hours.empty, len(bad_rows), distinct, examples[:EXAMPLE_LIMIT])


def _rule_v12(rows: pd.DataFrame, hours: pd.DataFrame, conn: sqlite3.Connection) -> RuleResult:
    """A row id or an hour that is already loaded, or that comes twice in the delivery."""
    ids = rows["row_id"].astype("int64")
    loaded_ids = known_row_ids(conn, ids)
    row_loaded = ids.isin(loaded_ids).to_numpy()
    row_repeated = ids.duplicated(keep="first").to_numpy() & ~row_loaded
    stored = _stored(hours["hour"])
    known = set(known_hours(conn)["hour"])
    hour_loaded = stored.isin(known).to_numpy()
    hour_repeated = stored.duplicated(keep="first").to_numpy() & ~hour_loaded
    bad_rows, bad_hours = rows[row_loaded | row_repeated], hours[hour_loaded | hour_repeated]
    row_reason = np.where(row_loaded[row_loaded | row_repeated], "loaded", "repeated")
    hour_reason = np.where(hour_loaded[hour_loaded | hour_repeated], "loaded", "repeated")
    examples = [{"table": "rows", "row_id": int(r), "hour": _iso(h), "reason": why}
                for r, h, why in zip(bad_rows["row_id"].head(EXAMPLE_LIMIT), bad_rows["hour"].head(EXAMPLE_LIMIT), row_reason[:EXAMPLE_LIMIT], strict=True)]
    examples += [{"table": "hours", "hour": _iso(h), "reason": why} for h, why in zip(bad_hours["hour"].head(EXAMPLE_LIMIT), hour_reason[:EXAMPLE_LIMIT], strict=True)]
    return _result("V12", bad_rows.empty and bad_hours.empty, len(bad_rows), bad_hours["hour"].nunique(), examples[:EXAMPLE_LIMIT])


def _rule_v13(rows: pd.DataFrame, hours: pd.DataFrame, spec: DeliverySpec, entry: ManifestEntry, out_dir: Path) -> RuleResult:
    reasons = []
    if spec.kind == "close":
        if len(rows) or len(hours):
            reasons.append("close_with_rows")
    elif rows.empty or hours.empty:
        reasons.append("empty")
    if len(rows) != entry.rows:
        reasons.append("rows_differ_from_manifest")
    if len(hours) != entry.hours:
        reasons.append("hours_differ_from_manifest")
    actual: dict[str, str | None] = {}
    for key, name, expected in (("rows", entry.rows_file, entry.rows_sha256), ("hours", entry.hours_file, entry.hours_sha256)):
        path = Path(out_dir) / name
        actual[key] = sha256_file(path) if path.is_file() else None
        if actual[key] is None:
            reasons.append(f"{key}_file_missing")
        elif actual[key] != expected:
            reasons.append(f"{key}_file_differs_from_manifest")
    if actual["rows"] is not None and actual["hours"] is not None and delivery_digest(actual["rows"], actual["hours"]) != entry.sha256:
        reasons.append("sha256_differs_from_manifest")
    if not reasons:
        return _result("V13", True)
    example = {"delivery_id": entry.delivery_id, "reasons": reasons, "rows": len(rows), "manifest_rows": entry.rows, "hours": len(hours), "manifest_hours": entry.hours}
    return _result("V13", False, len(rows), len(hours), [example])


def _rule_v14(rows: pd.DataFrame, hours: pd.DataFrame) -> RuleResult:
    """The aggregates of each hour are those of its rows, recomputed with the same function that built them (``hours.aggregate_rows``); an hour
    of one table that the other lacks fails too."""
    columns = ["rows", *AGGREGATE_COLUMNS]
    if len(rows):
        expected = aggregate_rows(rows[["hour", *SENSORS]])
    else:
        expected = pd.DataFrame({"hour": pd.Series([], dtype="datetime64[ns]"), **{c: pd.Series([], dtype="float64") for c in columns}})
    expected = expected.rename(columns={c: f"expected_{c}" for c in columns})
    merged = hours[["hour", *columns]].merge(expected, on="hour", how="outer", indicator=True).sort_values("hour", kind="stable").reset_index(drop=True)
    both = (merged["_merge"] == "both").to_numpy()
    differs = np.zeros((len(merged), len(columns)), dtype=bool)
    for k, column in enumerate(columns):
        stated, recomputed = merged[column].to_numpy(dtype="float64"), merged[f"expected_{column}"].to_numpy(dtype="float64")
        differs[:, k] = both & ~np.isclose(stated, recomputed, rtol=AGGREGATE_TOLERANCE, atol=AGGREGATE_TOLERANCE, equal_nan=True)
    reason = np.where(merged["_merge"] == "left_only", "hour_without_rows", np.where(merged["_merge"] == "right_only", "rows_without_hour",
                                                                                     np.where(differs.any(axis=1), "aggregate_differs", "")))
    bad = np.flatnonzero(reason != "")
    if not len(bad):
        return _result("V14", True)
    examples = [{"hour": _iso(merged.loc[i, "hour"]), "reason": str(reason[i]), **({"column": columns[int(np.argmax(differs[i]))]} if reason[i] == "aggregate_differs" else {})}
                for i in bad[:EXAMPLE_LIMIT]]
    bad_hours = set(merged.loc[bad, "hour"])
    return _result("V14", False, int(rows["hour"].isin(bad_hours).sum()) if len(rows) else 0, len(bad_hours), examples)


def _rule_v15(rows: pd.DataFrame) -> RuleResult:
    """No laboratory column in the rows: anything that is not a column of the canonical rows (a laboratory value, or a ``<lab>_row_<n>``)."""
    extra = [name for name in rows.columns if name not in SOURCE_ROWS_SCHEMA.names]
    if not extra:
        return _result("V15", True)
    return _result("V15", False, len(rows), rows["hour"].nunique(), [{"columns": extra[:EXAMPLE_LIMIT], "count": len(extra)}])


def _hours_flag(rule_id: str, hours: pd.DataFrame, mask: pd.Series) -> RuleResult:
    """A warning over the hours that match its rule: it warns when there are any."""
    chosen = hours.loc[mask.to_numpy(dtype=bool)]
    examples = [{"hour": _iso(h), "rows": int(n)} for h, n in zip(chosen["hour"].head(EXAMPLE_LIMIT), chosen["rows"].head(EXAMPLE_LIMIT), strict=True)]
    return _result(rule_id, chosen.empty, int(chosen["rows"].sum()), len(chosen), examples)


def _rule_i02(hours: pd.DataFrame, conn: sqlite3.Connection) -> RuleResult:
    """Hours (this delivery's and the loaded ones) whose feed has not changed for ``UNCHANGED_FEED_HOURS`` or more; read once, from the last run."""
    known = known_hours(conn)
    known = known[~known["hour"].isin(set(_stored(hours["hour"])))]
    columns = ["hour", "rows", "feed_silica_age_h", "feed_iron_age_h"]
    this = pd.DataFrame({"hour": _stored(hours["hour"]), "rows": hours["rows"], "feed_silica_age_h": hours["feed_silica_age_h"],
                         "feed_iron_age_h": hours["feed_iron_age_h"]})
    ages = this if known.empty else pd.concat([known[columns], this], ignore_index=True)
    silica, iron = ages["feed_silica_age_h"] >= UNCHANGED_FEED_HOURS, ages["feed_iron_age_h"] >= UNCHANGED_FEED_HOURS
    either = silica | iron
    summary = {"feed_silica_unchanged_hours": int(silica.sum()), "feed_iron_unchanged_hours": int(iron.sum()), "threshold_hours": UNCHANGED_FEED_HOURS}
    return _result("I02", True, int(ages.loc[either, "rows"].sum()), int(either.sum()), [summary])


def _rule_i03(hours: pd.DataFrame) -> RuleResult:
    """Hours in which a sensor did not move: its sample standard deviation is exactly 0 (an hour of one row has none and is not counted)."""
    fixed = pd.DataFrame({sensor: hours[f"{sensor}_std"].eq(0.0) for sensor in SENSORS})
    either = fixed.any(axis=1)
    examples = [{"sensor": sensor, "hours": int(count)} for sensor, count in fixed.sum().items() if count]
    return _result("I03", True, int(hours.loc[either, "rows"].sum()), int(either.sum()), examples)


def validate_delivery(rows: pd.DataFrame, hours: pd.DataFrame, spec: DeliverySpec, conn: sqlite3.Connection, view: Any, *, entry: ManifestEntry,
                      out_dir: Path, run_key: str) -> ValidationReport:
    """Validate one delivery against the plan, its manifest entry and what the warehouse holds; every rule of the delivery and its hours is evaluated.

    `view` has ``[hours]``, ``[lab]`` and ``[deliveries]`` (the plan of V10 and the sizes of an hour); `entry` and `out_dir` are the manifest line
    of the delivery and the folder of its two files, whose rows, hours and SHA-256 V13 compares. The warehouse is only read, and the frames are
    not changed.
    """
    _require_columns(rows, hours)
    rows_per_hour, minimum = view.hours.rows_per_hour, view.hours.min_rows_per_hour
    results = {
        "V10": _rule_v10(rows, hours, spec, loaded_deliveries(conn), view), "V11": _rule_v11(rows, hours, spec), "V12": _rule_v12(rows, hours, conn),
        "V13": _rule_v13(rows, hours, spec, entry, Path(out_dir)), "V14": _rule_v14(rows, hours), "V15": _rule_v15(rows),
        "V20": _hours_flag("V20", hours, hours["rows"] < rows_per_hour), "V21": _hours_flag("V21", hours, hours["rows"] < minimum),
        "V22": _hours_flag("V22", hours, hours["lab_state"] == "interpolated"), "V23": _hours_flag("V23", hours, hours["lab_state"] == "held"),
        "V24": _hours_flag("V24", hours, hours["feed_changes_in_hour"].astype(bool)),
        "I02": _rule_i02(hours, conn), "I03": _rule_i03(hours),
    }
    report = ValidationReport(run_key, "", spec.delivery_id, len(rows), len(hours), _ordered(results), ())
    _log_verdict(report)
    return report


# --- the rules of the model (their tasks evaluate them) ---------------------------------------------------------------------


def model_result(rule_id: str, *, passed: bool, rows: int = 0, hours: int = 0, examples: list[dict] | None = None) -> RuleResult:
    """The result of a rule of the model (M01-M06, I04, I05), with the severity, scope and aggregation of its rule."""
    if rule_id not in MODEL_RULES:
        raise ValueError(f"{rule_id} no es una regla del modelo ({', '.join(MODEL_RULES)})")
    return _result(rule_id, passed, rows, hours, examples)


def add_results(report: ValidationReport, results: Iterable[RuleResult]) -> ValidationReport:
    """The report with `results` added in the order of ``RULES``; a rule already in the report is refused (a result is written once)."""
    current = {r.rule_id: r for r in report.results}
    for result in results:
        if result.rule_id in current:
            raise ValueError(f"la regla {result.rule_id} ya está en el reporte de {report.run_key}")
        current[result.rule_id] = result
    return replace(report, results=_ordered(current), not_evaluated=tuple(r for r in report.not_evaluated if r not in current))


def combine_reports(source: ValidationReport, delivery: ValidationReport) -> ValidationReport:
    """The report of a run: the rules of the source and then those of the delivery, in the order of ``RULES``."""
    results = {r.rule_id: r for r in [*source.results, *delivery.results]}
    return replace(delivery, source_sha256=source.source_sha256 or delivery.source_sha256, run_key=delivery.run_key or source.run_key,
                   results=_ordered(results), not_evaluated=tuple(r for r in source.not_evaluated if r not in results))


# --- report files ----------------------------------------------------------------------------------------------------


def _cell(text: str) -> str:
    """A table cell: a pipe or a newline would split the row."""
    return text.replace("|", "\\|").replace("\n", " ")


def _report_document(report: ValidationReport) -> dict[str, Any]:
    return {
        "run_key": report.run_key, "source_sha256": report.source_sha256, "delivery_id": report.delivery_id, "rows_delivery": report.rows_delivery,
        "hours_delivery": report.hours_delivery, "blocking_failed": report.blocking_failed, "not_evaluated": list(report.not_evaluated),
        "results": [{"rule_id": r.rule_id, "name_es": r.name_es, "severity": r.severity.value, "scope": r.scope, "aggregation": r.aggregation.value,
                     "status": r.status, "rows_affected": r.rows_affected, "hours_affected": r.hours_affected, "examples": r.examples}
                    for r in report.results],
    }


def _report_markdown(report: ValidationReport) -> str:
    verdict = "Rechazado: hay reglas bloqueantes que fallan." if report.blocking_failed else "Aceptado: ninguna regla bloqueante falla."
    lines = [
        "# Reporte de validación", "", f"- Corrida: `{report.run_key}`", f"- Resultado: **{verdict}**",
        f"- SHA-256 del archivo de origen: `{report.source_sha256 or 'no disponible'}`",
        f"- Entrega: {report.delivery_id or 'ninguna'}; filas de la entrega: {report.rows_delivery}; horas: {report.hours_delivery}", "", "## Reglas", "",
        "| ID | Regla | Severidad | Agregación | Estado | Filas | Horas |", "| --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for r in report.results:
        lines.append(f"| {r.rule_id} | {_cell(r.name_es)} | {SEVERITY_ES[r.severity]} | {r.aggregation.value} | {STATUS_ES[r.status]} | "
                     f"{r.rows_affected} | {r.hours_affected} |")
    if report.not_evaluated:
        lines += ["", "## No evaluadas", "", "No se pudieron evaluar porque una regla bloqueante anterior falló o porque las evalúa otra tarea: "
                  + ", ".join(report.not_evaluated) + "."]
    shown = [r for r in report.results if r.examples and (not r.passed or r.severity is Severity.INFO)]
    if shown:
        lines += ["", "## Ejemplos", ""]
        for r in shown:
            lines += [f"### {r.rule_id}: {r.name_es}", ""] + [f"- `{json.dumps(example, ensure_ascii=False)}`" for example in r.examples] + [""]
    return "\n".join(lines).rstrip("\n") + "\n"


def write_report(report: ValidationReport, out_dir: Path) -> tuple[Path, Path]:
    """Write ``latest.json`` and ``latest.md`` and a copy per run in ``history/``; return the latest pair."""
    if not _SAFE_RUN_KEY.fullmatch(report.run_key):
        raise ValueError(f"run_key {report.run_key!r} no sirve como nombre de archivo")
    out_dir = Path(out_dir)
    text_json = json.dumps(_report_document(report), indent=2, ensure_ascii=False) + "\n"
    text_md = _report_markdown(report)
    for directory, stem in ((out_dir / "history", report.run_key), (out_dir, "latest")):
        write_atomic(directory / f"{stem}.json", text_json)
        write_atomic(directory / f"{stem}.md", text_md)
    return out_dir / "latest.json", out_dir / "latest.md"


def read_report(path: Path) -> ValidationReport:
    """The report written by ``write_report`` (``latest.json`` or a copy in ``history/``)."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    results = [RuleResult(r["rule_id"], r["name_es"], Severity(r["severity"]), r["scope"], Aggregation(r["aggregation"]), r["status"] == "pass",
                          r["rows_affected"], r["hours_affected"], r["examples"]) for r in document["results"]]
    return ValidationReport(document["run_key"], document["source_sha256"], document["delivery_id"], document["rows_delivery"], document["hours_delivery"],
                            results, tuple(document["not_evaluated"]))
