"""The words of the results (U11; AC22): a number is written as the Spanish text shows it, and every criterion has its name, its threshold and what was seen before."""

from __future__ import annotations

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
