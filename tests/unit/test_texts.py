"""The words of the results (U11; AC22): a number is written as the Spanish text shows it, and every criterion has its name, its threshold and what was seen before."""

from __future__ import annotations

import html as html_lib
import re

import pytest

from flotsilica.texts import CRITERIA, METHODS_ES, es, threshold_of


@pytest.mark.parametrize("value, digits, text", [
    (0.5374, 3, "0,537"), (-0.0213, 2, "−0,02"), (-0.0004, 2, "0,00"), (1234567.891, 1, "1.234.567,9"), (0.0, 3, "0,000"), (100.0, 0, "100"),
    (None, 3, "sin dato"), (float("nan"), 3, "sin dato"), (float("inf"), 2, "sin dato"),
])
def test_a_number_is_written_with_a_decimal_comma_a_thousands_point_and_the_typographic_minus(value, digits, text):
    assert es(value, digits) == text


def test_every_criterion_has_its_texts_and_the_two_that_carry_a_limit_say_it():
    assert list(CRITERIA) == [f"C{i:02d}" for i in range(1, 11)]
    assert all(c.name_es and c.threshold_es and c.seen_by_research and c.seen_by_planner for c in CRITERIA.values())
    assert threshold_of("C05", low=0.75, high=0.85) == "proporción de horas con el análisis dentro del rango del 80 % entre 0,75 y 0,85"
    assert threshold_of("C06", max_bias=0.1) == "|media(modelo − análisis)| ≤ 0,10"
    assert set(METHODS_ES) >= {"model", "b_star", "b0_train_mean", "b1_persistence", "b2_rolling", "b3_ridge_sensors", "best_sensors_only", "best_lab_only", "best_with_sensors"}


# --- a sensitivity is an association of the model: never a cause and never an action (U12; D20; AC24) --------------------------------------------------------------------


def generated_texts() -> list[str]:
    """Every text the code writes about a sensitivity: the sentence of each sensor in each state, the verdicts of C09 in each state and the summary that carries them."""
    from flotsilica import texts
    from flotsilica.evaluation import criteria_of
    from flotsilica.reporting import summary_markdown
    from flotsilica.schema import SENSORS
    from tests.fixtures import hand_cases as hc

    out = []
    for sensor in SENSORS:
        out += [texts.sensor_line(sensor, passes=True, sign=1, kept=True), texts.sensor_line(sensor, passes=True, sign=-1, kept=False), texts.sensor_line(sensor, passes=False, sign=0, kept=None)]
    out += [texts.stability_verdict(False, [], [], True), texts.stability_verdict(False, ["amina_flow"], [], True), texts.stability_verdict(True, ["amina_flow", "starch_flow"], ["amina_flow"], True),
            texts.stability_verdict(False, [], [], False), texts.gate_summary([], True), texts.gate_summary(["amina_flow", "ore_pulp_ph"], True), texts.gate_summary([], False)]
    for figures in (hc.losing_figures(), hc.winning_figures()):
        criteria = [{"criterion_id": c.criterion_id, "name_es": c.name_es, "value": c.value, "baseline_value": c.baseline_value, "ci_low": c.ci_low, "ci_high": c.ci_high,
                     "threshold_es": c.threshold_es, "passed": c.passed, "seen_by_research": c.seen_by_research, "seen_by_planner": c.seen_by_planner, "verdict_es": c.verdict_es}
                    for c in criteria_of(figures, hc.SEALED_CRITERIA)]
        out.append(summary_markdown({"evaluation_status": "sealed", "run_key": "r9", "as_of": "2017-09-10 01:00:00", "pending_reason_es": None, "post_seal": None,
                                     "criteria": criteria, "validation": {}}))
    return out


def test_no_generated_text_calls_a_sensitivity_a_cause_or_an_action():
    from flotsilica import texts

    found = generated_texts()
    assert len(found) > 60 and any("asociación del modelo" in t for t in found) and any("sin asociación estable" in t for t in found)
    for text in found:
        assert texts.sensitivity_problems(text) == [], text
    # the check has teeth: each of these says a sensitivity is a cause or tells someone to act, and is found
    for bad in ("El amina_flow provoca la sílice.", "La causa de la sílice es starch_flow.", "Para bajar la sílice, subir el flujo de amina_flow.", "El sensor ore_pulp_ph controla la sílice.",
                "Ajustar el flujo de aire (air_flow_03) baja la sílice.", "La sensibilidad de level_02 es la causa del aumento."):
        assert texts.sensitivity_problems(bad), bad
    # and a text with those words far from any sensor or sensitivity is not flagged: the verdicts of the other criteria are not about one
    assert texts.sensitivity_problems("El modelo no supera a la persistencia en la hora que cerró: MAE 0,54 frente a 0,53.") == []
    far = "La causa del cambio de nivel entre los bloques no se conoce, y no hay acción que lo corrija." + " " * 150 + "El sensor amina_flow: sin asociación estable."
    assert texts.sensitivity_problems(far) == [] and texts.sensitivity_problems("La causa de la diferencia de nivel es el calendario, no un sensor.") != []
    assert texts.sensitivity_problems("Acción: subir el amina_flow.") and texts.sensitivity_problems("Las ACCIONES sobre starch_flow") and texts.sensitivity_problems("provoca amina_flow")


def test_the_design_of_the_report_never_calls_a_sensitivity_a_cause_or_an_action(rendered_html):
    """U14: the HTML joins the texts that the check of D20 reads (plan, section 14): every text node and every label of the design, one by one, with the word of a cause or an action near the
    name of a sensor, «sensor», «sensibilidad» or «dependencia parcial» as the only thing that fails."""
    from flotsilica import texts

    html = rendered_html.html
    found = [html_lib.unescape(node).strip() for node in re.split(r"<[^>]+>", html)] + [html_lib.unescape(m) for m in re.findall(r'aria-label="([^"]*)"', html)]
    found = [t for t in found if t]
    assert len(found) > 300 and any("Una sensibilidad es una asociación del modelo, no una receta" in t for t in found) and any("sin asociación estable" in t for t in found)
    assert any("Asociación del modelo, no una receta" in t for t in found)
    for text in found:
        assert texts.sensitivity_problems(text) == [], text
    # the check reads the design: a title that said it would be found
    assert texts.sensitivity_problems("Asociación del modelo, no una causa: dependencia parcial")
