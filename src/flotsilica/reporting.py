"""The task ``evaluate``, the summary and the results block of the README (RF18, RF19; AC19, AC22; D16, D18, D19; plan, sections 3 and 16).

``evaluate`` runs in every run after the launch. While the last analysis of the test has not arrived it says so and stores nothing. When the run's ``as_of`` reaches
``test_last + latency_hours`` it evaluates the test **once**, from what was issued (``evaluation.evaluate_test``): the figures, the criteria C01-C10, the variants
(after the launch part of the seal), all written to the test part of the seal (``registry.write_test_seal``) and to the sealed rows of the warehouse, which are never
written again. With another configuration than the sealed one, the seal already has its test part and everything is stored as ``post_seal``; with another configuration
and no test part, ``registry.check_test_evaluation`` refuses before anything is written (D18).

``build_summary`` says what is known: the test pending (with the reason, and the figures of V1 and V2 labelled as validation), the sealed criteria from the warehouse, or,
when the warehouse has no sealed rows but the seal has its test part (a rebuild from scratch), the criteria rebuilt from the seal, each checked against its entry (D19),
with the run's own analysis below as post-seal. ``write_summary`` writes ``evaluation_summary.json`` and ``.md``; ``sync_block`` copies the Markdown between two markers.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from flotsilica import texts, variants
from flotsilica.evalstore import store_result
from flotsilica.evaluation import Criterion, criteria_from_seal, evaluate_criteria, evaluate_test, figures
from flotsilica.features import HourTables
from flotsilica.files import write_atomic
from flotsilica.launch import hour_frame
from flotsilica.registry import (
    SealError,
    check_test_evaluation,
    config_fingerprint,
    load_registered_bundle,
    read_seal,
    seal_state,
    write_test_seal,
)
from flotsilica.scoring import RunMeta
from flotsilica.sensitivity import COMPARISON, sign_check
from flotsilica.texts import CRITERIA, METHODS_ES, es
from flotsilica.warehouse import apply_schema

logger = logging.getLogger(__name__)

SUMMARY_VERSION = 1
RESULTS_START, RESULTS_END = "<!-- results:start -->", "<!-- results:end -->"
STAMP = "%Y-%m-%d %H:%M:%S"


def ready_instant(view: Any) -> pd.Timestamp:
    """The instant the last analysis of the test arrives: ``test_last + latency_hours``. The test is evaluated at the first run whose ``as_of`` reaches it."""
    return pd.Timestamp(view.split.test_last) + pd.Timedelta(hours=view.lab.latency_hours)


def criterion_dict(c: Criterion) -> dict[str, Any]:
    return {"criterion_id": c.criterion_id, "name_es": c.name_es, "value": c.value, "baseline_value": c.baseline_value, "ci_low": c.ci_low, "ci_high": c.ci_high,
            "threshold_es": c.threshold_es, "passed": c.passed, "seen_by_research": c.seen_by_research, "seen_by_planner": c.seen_by_planner, "verdict_es": c.verdict_es}


# --- the task ----------------------------------------------------------------------------------------------------------------


def _has_sealed_criteria(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM eval_criteria WHERE seal_state = 'sealed' LIMIT 1").fetchone() is not None


def evaluate(conn: sqlite3.Connection, run: RunMeta, view: Any, *, seal_path: Path, models_dir: Path, sensitivity: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate what the run's ``as_of`` allows (see the module). Returns what the run records (JSON-ready): ``test`` is ``pending``, ``sealed_before``, ``written``,
    ``unchanged`` (a repetition that reproduces the seal) or ``post_seal``. `sensitivity` is what C09 reads (``evaluation.figures``); if it is not given it comes from the gate of the sealed launch and the
    sign check over the hours of the test (``sensitivity.sign_check``), and C09 says it cannot be computed only if the gate was not."""
    apply_schema(conn)
    config_sha256 = config_fingerprint(view)
    state = seal_state(seal_path, config_sha256)
    if state == "none":
        raise SealError("no hay sello: el lanzamiento escribe su parte antes de que se evalúe la prueba (docs/runbook.md, R7)")
    rows_state = "sealed" if state == "match" else "post_seal"
    ready = ready_instant(view)
    out: dict[str, Any] = {"seal_state": rows_state, "test": "pending", "ready_instant": ready.strftime(STAMP)}
    if pd.Timestamp(run.as_of) < ready:
        return out
    if rows_state == "sealed" and _has_sealed_criteria(conn):
        out["test"] = "sealed_before"
        return out
    mode = check_test_evaluation(seal_path, view)                      # refuses before anything is written if it must (D18)
    result = evaluate_test(conn, view)
    bundle = load_registered_bundle(conn, models_dir, view.model.model_version)       # M03
    found = variants.run(conn, bundle, view, as_of=run.as_of, seal_path=seal_path)
    checks, curves = [], {}
    gate = read_seal(seal_path)["launch"].get("gate") or {}
    if sensitivity is None and gate.get("computed"):
        # C09: the sensors that passed the sealed gate, and whether each keeps its sign over the hours of the test (after the launch part of the seal is written)
        checks, curves = sign_check(HourTables.from_hours(hour_frame(conn, run.as_of, view), view), bundle.comparisons[0][COMPARISON], view, gate)
        sensitivity = {"computed": True, "passing": list(gate["passing"]), "kept_sign": [c["sensor"] for c in checks if c["kept_sign"]]}
    criteria = evaluate_criteria(result, view, sensitivity)
    part = {"run_key": run.run_key, "as_of": pd.Timestamp(run.as_of).strftime(STAMP), "config_sha256": config_sha256, "criteria": [c.seal_entry() for c in criteria],
            "metrics": figures(result, sensitivity), "weekly": result.weekly, "variants": found, "sensitivity_test": checks}
    outcome = write_test_seal(seal_path, part) if mode in ("first", "repeat") else "post_seal"
    store_result(conn, result, criteria, found, rows_state, run.run_key, checks, curves)
    out.update(test=outcome, criteria={c.criterion_id: c.passed for c in criteria})
    logger.info("evaluate %s: test %s (%s), criteria met %s", run.run_key, outcome, rows_state, [c.criterion_id for c in criteria if c.passed])
    return out


# --- the summary -------------------------------------------------------------------------------------------------------------


def _criteria_rows(conn: sqlite3.Connection, state: str) -> list[dict[str, Any]]:
    columns = ("criterion_id", "name_es", "value", "baseline_value", "ci_low", "ci_high", "threshold_es", "passed", "seen_by_research", "seen_by_planner", "verdict_es")
    out = []
    for row in conn.execute(f"SELECT {', '.join(columns)} FROM eval_criteria WHERE seal_state = ? ORDER BY criterion_id", (state,)).fetchall():
        entry = dict(zip(columns, row, strict=True))
        entry["passed"] = None if entry["passed"] is None else bool(entry["passed"])
        out.append(entry)
    return out


def _validation(conn: sqlite3.Connection, state: str) -> dict[str, dict[str, dict[str, dict[str, float | None]]]]:
    """``{scope: {horizon: {method: {metric: value}}}}`` of V1 and V2, as the launch stored them."""
    out: dict[str, Any] = {}
    for scope, horizon, method, metric, value in conn.execute(
            "SELECT scope, horizon, method, metric, value FROM eval_metrics WHERE scope IN ('valid_v1', 'valid_v2') AND seal_state = ? ORDER BY 1, 2, 3, 4", (state,)):
        out.setdefault(scope, {}).setdefault(str(horizon), {}).setdefault(method, {})[metric] = value
    return out


def pending_criteria(view: Any, reason: str) -> list[dict[str, Any]]:
    from flotsilica.registry import sealed_document

    document = sealed_document(view)["criteria"]
    thresholds = {"C05": texts.threshold_of("C05", low=document["c05_coverage_low"], high=document["c05_coverage_high"]),
                  "C06": texts.threshold_of("C06", max_bias=document["c06_max_bias"])}
    return [{"criterion_id": cid, "name_es": c.name_es, "value": None, "baseline_value": None, "ci_low": None, "ci_high": None, "threshold_es": thresholds.get(cid, c.threshold_es),
             "passed": None, "seen_by_research": c.seen_by_research, "seen_by_planner": c.seen_by_planner, "verdict_es": "Pendiente: " + reason} for cid, c in CRITERIA.items()]


def build_summary(conn: sqlite3.Connection, view: Any, *, run: RunMeta, seal_path: Path) -> dict[str, Any]:
    """What the summary says (see the module): ``evaluation_status`` is ``pending``, ``sealed`` or ``post_seal`` (this run's configuration is not the sealed one),
    ``sealed_from`` is ``seal`` when the criteria come from the seal."""
    apply_schema(conn)
    state = seal_state(seal_path, config_fingerprint(view))
    rows_state = "sealed" if state == "match" else "post_seal"
    seal = read_seal(seal_path)
    summary: dict[str, Any] = {
        "schema_version": SUMMARY_VERSION, "run_key": run.run_key, "as_of": pd.Timestamp(run.as_of).strftime(STAMP), "source_sha256": view.source_sha256,
        "validation": _validation(conn, "sealed" if seal is not None else rows_state), "test": None, "post_seal": None, "pending_reason_es": None,
    }
    sealed_rows = _criteria_rows(conn, "sealed")
    post_rows = _criteria_rows(conn, "post_seal") if rows_state == "post_seal" else []
    if sealed_rows:
        summary.update(evaluation_status="sealed", criteria=sealed_rows, test=(seal or {}).get("test", {}).get("metrics"))
    elif seal is not None and seal.get("test") is not None:
        summary.update(evaluation_status="sealed", criteria=[criterion_dict(c) for c in criteria_from_seal(seal)], test=seal["test"]["metrics"], sealed_from="seal")
    elif post_rows:
        summary.update(evaluation_status="post_seal", criteria=post_rows)
    else:
        reason = texts.pending_reason(ready_instant(view).strftime(STAMP), summary["as_of"])
        summary.update(evaluation_status="pending", pending_reason_es=reason, criteria=pending_criteria(view, reason))
    if post_rows and summary["evaluation_status"] == "sealed":
        summary["post_seal"] = {"criteria": post_rows}
    if seal is not None:
        summary["seal"] = {"config_sha256": seal["launch"]["config_sha256"], "launch_run_key": seal["launch"]["run_key"],
                           "test_run_key": (seal.get("test") or {}).get("run_key"), "test_as_of": (seal.get("test") or {}).get("as_of")}
    return summary


def _cell(text: Any) -> str:
    """A cell of a Markdown table: its pipes escaped, so «|media|» stays inside its cell."""
    return str(text).replace("|", r"\|")


def _validation_lines(validation: Mapping[str, Any]) -> list[str]:
    """The MAE of each method on V2 by horizon, labelled as validation (not the test)."""
    v2 = validation.get("valid_v2") or {}
    if not v2:
        return []
    horizons = sorted(v2)
    methods = [m for m in METHODS_ES if any(m in v2[h] for h in horizons)]
    lines = ["Validación (V2, no la prueba): MAE de cada método por horizonte.", "", "| Método | " + " | ".join(f"H{h}" for h in horizons) + " |",
             "| --- | " + " | ".join("---:" for _ in horizons) + " |"]
    lines += [f"| {METHODS_ES[m]} | " + " | ".join(es((v2[h].get(m) or {}).get("mae")) for h in horizons) + " |" for m in methods]
    return lines + [""]


def summary_markdown(summary: Mapping[str, Any]) -> str:
    """The Markdown of the summary, in Spanish: the state, each criterion with its number and its verdict (also «no supera»), and below, the post-seal analysis if there
    is one. A pending summary says why, and shows only the validation."""
    lines = ["## Resultados", ""]
    status = summary["evaluation_status"]
    if status == "pending":
        lines += [f"**Prueba pendiente.** {summary['pending_reason_es']}", ""]
        lines += _validation_lines(summary.get("validation") or {})
    else:
        origin = " (tomados del sello)" if summary.get("sealed_from") == "seal" else ""
        lines += [f"Criterios fijados antes de construir, evaluados una vez sobre la prueba{origin}.", "",
                  "| Criterio | Umbral | Valor | Cumple | Veredicto |", "| --- | --- | ---: | --- | --- |"]
        for c in summary["criteria"]:
            passed = "informativo" if c["passed"] is None else ("sí" if c["passed"] else "no")
            lines.append(f"| {c['criterion_id']} {_cell(c['name_es'])} | {_cell(c['threshold_es'])} | {es(c['value'])} | {passed} | {_cell(c['verdict_es'])} |")
        lines.append("")
        lines += _validation_lines(summary.get("validation") or {})
    post = summary.get("post_seal")
    if post and post.get("criteria"):
        lines += ["### Análisis posterior al sello", "", "Con otra configuración que la sellada: no reemplaza lo sellado.", ""]
        lines += [f"- {c['criterion_id']}: {c['verdict_es']}" for c in post["criteria"]]
        lines.append("")
    lines.append(f"Estado: {status}. Corrida {summary['run_key']} del {summary['as_of']}.")
    return "\n".join(lines) + "\n"


def write_summary(summary: Mapping[str, Any], reports_dir: Path) -> tuple[Path, Path]:
    """``evaluation_summary.json`` and ``evaluation_summary.md`` in `reports_dir`, each written atomically."""
    reports_dir = Path(reports_dir)
    json_path, md_path = reports_dir / "evaluation_summary.json", reports_dir / "evaluation_summary.md"
    write_atomic(json_path, json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False) + "\n")
    write_atomic(md_path, summary_markdown(summary))
    return json_path, md_path


def check_markers(path: Path, start_marker: str, end_marker: str) -> str:
    """The text of `path` if it has both markers, in order and once each; otherwise a ``ValueError`` and nothing else happens (``docs-sync`` checks every file before it writes any)."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if text.count(start_marker) != 1 or text.count(end_marker) != 1 or text.index(start_marker) > text.index(end_marker):
        raise ValueError(f"{path.name} debe tener una vez {start_marker} y después una vez {end_marker}")
    return text


def sync_block(path: Path, start_marker: str, end_marker: str, content: str) -> bool:
    """Replace what is between the two markers of `path` with `content` (the markers stay). True if the file changed. A file without both markers, in order and once
    each, is a ``ValueError`` and is not touched."""
    path = Path(path)
    text = check_markers(path, start_marker, end_marker)
    head, rest = text.split(start_marker)
    _old, tail = rest.split(end_marker)
    new = f"{head}{start_marker}\n{content.strip()}\n{end_marker}{tail}"
    if new == text:
        return False
    write_atomic(path, new)
    return True
