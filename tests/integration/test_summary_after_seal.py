"""The summary after the seal (U11; RF19, AC19, AC22; D19; project 03's B3): a warehouse that does not hold the sealed rows of the test (a rebuild from scratch) takes the
criteria and the test figures from the seal, each rebuilt from its figures and compared with its entry, and shows its own analysis below as post-seal; a seal entry that
does not rebuild is refused; and before the test the summary is pending and says why."""

from __future__ import annotations

import dataclasses
import json

import pytest

from flotsilica.registry import SealError, config_fingerprint, read_seal, sealed_view
from flotsilica.reporting import build_summary, evaluate, summary_markdown
from flotsilica.scoring import RunMeta
from flotsilica.warehouse import connect
from tests.fixtures.history import SOURCE_SHA256, without_sealed_rows

CRITERION_KEYS = ("value", "baseline_value", "ci_low", "ci_high", "passed", "verdict_es")


def sealed_criteria(h) -> list[dict]:
    return [{"id": e["id"], **{k: e[k] for k in CRITERION_KEYS}} for e in read_seal(h.paths.seal)["test"]["criteria"]]


def other_view(h):
    view = dataclasses.replace(h.view, evaluation=dataclasses.replace(h.view.evaluation, bootstrap_resamples=h.view.evaluation.bootstrap_resamples + 1))
    return sealed_view(view, SOURCE_SHA256)


def test_a_warehouse_without_sealed_rows_takes_the_sealed_result_from_the_seal(small_history, tmp_path):
    h = without_sealed_rows(small_history, tmp_path / "rebuilt")
    last, seal_before = h.runs[-1], h.paths.seal.read_bytes()
    conn = connect(h.paths.db)
    try:
        outcome = evaluate(conn, last, other_view(h), seal_path=h.paths.seal, models_dir=h.paths.models)
        summary = build_summary(conn, other_view(h), run=last, seal_path=h.paths.seal)
        same_config = build_summary(conn, h.sealed, run=last, seal_path=h.paths.seal)
    finally:
        conn.close()
    assert (outcome["seal_state"], outcome["test"]) == ("post_seal", "post_seal")
    assert h.paths.seal.read_bytes() == seal_before, "the post-seal evaluation leaves the seal as it was"
    assert (summary["evaluation_status"], summary["sealed_from"]) == ("sealed", "seal")
    got = [{"id": c["criterion_id"], **{k: c[k] for k in CRITERION_KEYS}} for c in summary["criteria"]]
    assert got == sealed_criteria(h), "each sealed criterion, rebuilt from the seal, is its entry"
    assert summary["test"] == read_seal(h.paths.seal)["test"]["metrics"] and same_config["sealed_from"] == "seal"
    post = summary["post_seal"]
    assert [c["criterion_id"] for c in post["criteria"]] == [f"C{i:02d}" for i in range(1, 11)] and same_config["post_seal"] is None
    text = summary_markdown(summary)
    assert "Criterios fijados antes de construir, evaluados una vez sobre la prueba (tomados del sello)." in text
    assert "### Análisis posterior al sello" in text and text.index("| C01") < text.index("### Análisis posterior al sello"), "the run's analysis goes below what was sealed"


def test_a_seal_entry_that_does_not_rebuild_is_refused(small_history, tmp_path):
    """A seal whose criterion says another value than its own figures give (here C01, edited by hand) is never published: ``SealError``."""
    h = without_sealed_rows(small_history, tmp_path / "edited")
    document = json.loads(h.paths.seal.read_text(encoding="utf-8"))
    entry = next(e for e in document["test"]["criteria"] if e["id"] == "C01")
    entry["value"] = round(entry["value"] + 0.01, 6)
    h.paths.seal.write_text(json.dumps(document), encoding="utf-8")
    conn = connect(h.paths.db)
    try:
        with pytest.raises(SealError, match="el criterio C01 del sello no se reconstruye desde sus cifras"):
            build_summary(conn, h.sealed, run=h.runs[-1], seal_path=h.paths.seal)
    finally:
        conn.close()


def test_the_summary_of_a_run_before_the_test_is_pending_and_says_why(small_history, small_launched):
    conn = connect(small_launched.paths.db)
    try:
        summary = build_summary(conn, small_launched.sealed, run=small_launched.runs[0], seal_path=small_launched.paths.seal)
    finally:
        conn.close()
    assert summary["evaluation_status"] == "pending" and "2017-03-31 01:00:00" in summary["pending_reason_es"] and "validación" in summary["pending_reason_es"]
    assert [c["criterion_id"] for c in summary["criteria"]] == [f"C{i:02d}" for i in range(1, 11)]
    assert all(c["passed"] is None and c["value"] is None and c["verdict_es"].startswith("Pendiente: ") for c in summary["criteria"])
    assert summary["validation"]["valid_v2"]["0"]["model"]["mae"] > 0 and set(summary["validation"]) == {"valid_v1", "valid_v2"}
    text = summary_markdown(summary)
    assert "**Prueba pendiente.**" in text and "Validación (V2, no la prueba)" in text and "| C01" not in text
    assert config_fingerprint(small_launched.sealed) == read_seal(small_launched.paths.seal)["launch"]["config_sha256"] and small_history is not None


def test_a_seal_entry_is_compared_to_six_decimals(small_history, tmp_path):
    """What the seal holds is compared rounded: a value that differs in the seventh decimal is the same, one that differs in the fifth is another."""
    h = without_sealed_rows(small_history, tmp_path / "rounded")
    document = json.loads(h.paths.seal.read_text(encoding="utf-8"))
    entry = next(e for e in document["test"]["criteria"] if e["id"] == "C01")
    exact = entry["value"]
    for shift, ok in ((3e-7, True), (3e-5, False)):
        entry["value"] = exact + shift
        h.paths.seal.write_text(json.dumps(document), encoding="utf-8")
        conn = connect(h.paths.db)
        try:
            if ok:
                assert build_summary(conn, h.sealed, run=h.runs[-1], seal_path=h.paths.seal)["sealed_from"] == "seal"
            else:
                with pytest.raises(SealError, match="C01"):
                    build_summary(conn, h.sealed, run=h.runs[-1], seal_path=h.paths.seal)
        finally:
            conn.close()
