"""The summary of the evaluation and the block of the README (U11; RF19, AC22; D16, D19): what the summary says about a model that loses, that the pending summary
says why it is pending, that every row has the cells of its header, and that the results block is copied between its markers."""

from __future__ import annotations

import json
import re

import pytest

from flotsilica.evaluation import criteria_of
from flotsilica.reporting import RESULTS_END, RESULTS_START, summary_markdown, sync_block, write_summary
from tests.fixtures import hand_cases as hc


def criterion_dict(c) -> dict:
    return {"criterion_id": c.criterion_id, "name_es": c.name_es, "value": c.value, "baseline_value": c.baseline_value, "ci_low": c.ci_low, "ci_high": c.ci_high,
            "threshold_es": c.threshold_es, "passed": c.passed, "seen_by_research": c.seen_by_research, "seen_by_planner": c.seen_by_planner,
            "verdict_es": c.verdict_es}


def sealed_summary(figures: dict) -> dict:
    criteria = criteria_of(figures, hc.SEALED_CRITERIA)
    return {"evaluation_status": "sealed", "run_key": "r9", "as_of": "2017-09-10 01:00:00", "pending_reason_es": None, "post_seal": None,
            "criteria": [criterion_dict(c) for c in criteria], "validation": {}}


def test_unfavourable_summary_says_no_supera(tmp_path):
    """A model that does not beat the persistence: the summary says «no supera» with its numbers, criterion by criterion, and says which criteria it meets."""
    summary = sealed_summary(hc.losing_figures())
    text = summary_markdown(summary)
    assert "El modelo no supera a la persistencia en la hora que cerró: MAE 0,54 frente a 0,53." in text
    assert "El modelo no supera a la base más fuerte en la hora que cerró fuera del ruido: MAE 0,54 frente a 0,53; la diferencia va de −0,03 a 0,04." in text
    rows = {line.split(" ")[1]: line for line in text.splitlines() if re.match(r"\| C\d\d ", line)}
    assert sorted(rows) == [f"C{i:02d}" for i in range(1, 11)]
    assert "| no |" in rows["C01"] and "| sí |" in rows["C05"] and "| sí |" in rows["C07"] and "| no |" in rows["C06"] and "| no |" in rows["C09"]
    assert "| informativo |" in rows["C10"]
    assert "El modelo supera a la persistencia" not in text
    json_path, md_path = write_summary(summary, tmp_path / "reports")
    assert json.loads(json_path.read_text(encoding="utf-8")) == summary and md_path.read_text(encoding="utf-8") == text
    assert [p.name for p in (tmp_path / "reports").iterdir()] == ["evaluation_summary.json", "evaluation_summary.md"]


def cells(line: str) -> int:
    """The cells of a Markdown table row: its pipes that are not escaped, minus one."""
    return len(re.findall(r"(?<!\\)\|", line)) - 1


def test_criterion_cells_escape_pipes_and_every_row_has_the_header_width():
    """C06's threshold says «|media(modelo − análisis)|»: its pipes would split the row into more cells than the header has, in the summary and in the block that
    is copied from it. Every pipe inside a cell is escaped; the data keep the text as it is."""
    summary = sealed_summary(hc.losing_figures())
    assert "|media" in next(c["threshold_es"] for c in summary["criteria"] if c["criterion_id"] == "C06")
    text = summary_markdown(summary)
    header = next(line for line in text.splitlines() if line.startswith("| Criterio |"))
    rows = [line for line in text.splitlines() if re.match(r"\| C\d\d ", line)]
    assert len(rows) == 10 and cells(header) == 5 and [cells(r) for r in rows] == [5] * 10, [r for r in rows if cells(r) != 5]
    assert r"\|media" in next(r for r in rows if r.startswith("| C06 "))


def test_the_pending_summary_says_why_the_test_is_not_evaluated(quick_cfg):
    from flotsilica.registry import sealed_view
    from flotsilica.reporting import pending_criteria
    from flotsilica.texts import pending_reason

    reason = pending_reason("2017-09-10 01:00:00", "2017-08-15 00:00:00")
    criteria = pending_criteria(sealed_view(quick_cfg, "ab" * 32), reason)
    assert [c["criterion_id"] for c in criteria] == [f"C{i:02d}" for i in range(1, 11)]
    assert all(c["passed"] is None and c["value"] is None and c["verdict_es"] == "Pendiente: " + reason for c in criteria)
    assert "entre 0,75 y 0,85" in next(c["threshold_es"] for c in criteria if c["criterion_id"] == "C05")      # the limits are the sealed ones
    text = summary_markdown({"evaluation_status": "pending", "run_key": "r2", "as_of": "2017-08-15 00:00:00", "pending_reason_es": reason, "criteria": criteria, "post_seal": None,
                             "validation": {"valid_v2": {"0": {"model": {"mae": 0.537}, "b1_persistence": {"mae": 0.533}}}}})
    assert "**Prueba pendiente.**" in text and "cuando llega el último análisis de la prueba (2017-09-10 01:00:00)" in text and "no la prueba" in text
    assert "| Modelo | 0,537 |" in text and "| Persistencia (B1) | 0,533 |" in text and "| C01" not in text and "Estado: pending." in text


def test_each_verdict_says_where_the_model_passes_and_where_it_fails():
    losing = {c.criterion_id: c for c in criteria_of(hc.losing_figures(), hc.SEALED_CRITERIA)}
    winning = {c.criterion_id: c for c in criteria_of(hc.winning_figures(), hc.SEALED_CRITERIA)}
    assert [cid for cid, c in losing.items() if c.passed] == ["C05", "C07"] and [cid for cid, c in losing.items() if c.passed is False] == ["C01", "C02", "C03", "C04", "C06", "C08", "C09"]
    assert [cid for cid, c in winning.items() if c.passed is False] == [] and winning["C10"].passed is None and losing["C10"].passed is None
    assert losing["C05"].verdict_es == "El rango del 80 % cumple en la hora que cerró: cubre 0,762 de las horas, y se pedía entre 0,75 y 0,85."
    assert losing["C06"].verdict_es == "El sesgo en la hora que cerró no cumple: el modelo estima 0,104 de más en promedio, y se pedía a lo sumo 0,10."
    assert losing["C07"].verdict_es.startswith("Los sensores solos superan a la media del entrenamiento: MAE 0,78 frente a 0,92; la diferencia va de −0,24 a −0,04.")
    assert losing["C08"].verdict_es == ("Con sensores, el modelo no agrega a la historia del laboratorio: MAE 0,54 frente a 0,53; la diferencia va de 0,00 a 0,02.")
    assert losing["C09"].verdict_es == "Ningún sensor pasa la compuerta de estabilidad: sin asociación estable."
    assert winning["C01"].verdict_es.startswith("El modelo supera a la persistencia en la hora que cerró: MAE 0,24 frente a 0,53.")
    assert winning["C03"].verdict_es.startswith("El modelo supera a la base más fuerte en la hora que empieza fuera del ruido")
    assert winning["C09"].verdict_es == "1 de 1 sensores que pasan la compuerta conservan el signo de su dependencia parcial en la prueba: amina_flow."
    assert all("pasa" not in w.verdict_es or w.passed for w in winning.values())


def test_a_tie_never_passes_and_a_criterion_that_cannot_be_computed_is_never_passed():
    tie = hc.losing_figures()
    tie["horizons"]["0"]["methods"]["model"]["mae"] = tie["horizons"]["0"]["methods"]["b1_persistence"]["mae"]
    assert next(c for c in criteria_of(tie, hc.SEALED_CRITERIA) if c.criterion_id == "C01").passed is False
    zero = hc.losing_figures()
    zero["bootstraps"]["model_vs_b_star.h0"]["ci_high"] = 0.0                    # an interval whose upper end is zero does not pass either
    assert next(c for c in criteria_of(zero, hc.SEALED_CRITERIA) if c.criterion_id == "C02").passed is False
    for name, cid in (("best_sensors_only_vs_b0_train_mean.h0", "C07"), ("best_with_sensors_vs_best_lab_only.h0", "C08")):
        flat = hc.winning_figures()
        flat["bootstraps"][name]["ci_high"] = 0.0
        assert next(c for c in criteria_of(flat, hc.SEALED_CRITERIA) if c.criterion_id == cid).passed is False
        assert next(c for c in criteria_of(hc.winning_figures(), hc.SEALED_CRITERIA) if c.criterion_id == cid).passed is True
    unstable = hc.winning_figures()
    unstable["sensitivity"] = {"computed": True, "passing": ["amina_flow", "starch_flow"], "kept_sign": []}      # two pass the gate and none keeps its sign in the test
    c09 = next(c for c in criteria_of(unstable, hc.SEALED_CRITERIA) if c.criterion_id == "C09")
    assert c09.passed is False and c09.verdict_es == "2 sensores pasan la compuerta, pero ninguno conserva el signo de su dependencia parcial en la prueba."
    edge = hc.losing_figures()
    for coverage, ok in ((0.75, True), (0.85, True), (0.7499, False), (0.8501, False)):
        edge["horizons"]["0"]["methods"]["model"]["coverage"] = coverage
        assert next(c for c in criteria_of(edge, hc.SEALED_CRITERIA) if c.criterion_id == "C05").passed is ok
    for bias, ok in ((0.10, True), (-0.10, True), (0.1001, False), (-0.1001, False)):
        edge["horizons"]["0"]["methods"]["model"]["bias"] = bias
        assert next(c for c in criteria_of(edge, hc.SEALED_CRITERIA) if c.criterion_id == "C06").passed is ok
    empty = {"horizons": {"0": {"hours": 0, "methods": {}}, "1": {"hours": 0, "methods": {}}, "2": {"hours": 0, "methods": {}}}, "bootstraps": {},
             "sensitivity": {"computed": False, "passing": [], "kept_sign": []}}
    cannot = {c.criterion_id: c for c in criteria_of(empty, hc.SEALED_CRITERIA)}
    assert [cid for cid, c in cannot.items() if c.passed is False] == [f"C0{k}" for k in range(1, 10)] and cannot["C10"].passed is None
    assert all(c.verdict_es.startswith("No se puede calcular:") and c.value is None for cid, c in cannot.items() if cid != "C10")


def test_the_results_block_is_copied_between_its_markers_and_nothing_else_changes(tmp_path):
    path = tmp_path / "README.md"
    path.write_text(f"# Title\n\ntext before\n\n{RESULTS_START}\nold\n{RESULTS_END}\n\ntext after\n", encoding="utf-8")
    assert sync_block(path, RESULTS_START, RESULTS_END, "## Resultados\n\nnew\n") is True
    assert path.read_text(encoding="utf-8") == f"# Title\n\ntext before\n\n{RESULTS_START}\n## Resultados\n\nnew\n{RESULTS_END}\n\ntext after\n"
    assert sync_block(path, RESULTS_START, RESULTS_END, "## Resultados\n\nnew\n") is False
    for broken in (f"{RESULTS_END}\n{RESULTS_START}\n", f"{RESULTS_START}\n", f"{RESULTS_START}\n{RESULTS_END}\n{RESULTS_START}\n{RESULTS_END}\n", "none\n"):
        path.write_text(broken, encoding="utf-8")
        with pytest.raises(ValueError, match="debe tener una vez"):
            sync_block(path, RESULTS_START, RESULTS_END, "x")
        assert path.read_text(encoding="utf-8") == broken
