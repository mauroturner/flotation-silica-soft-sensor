"""The small charts of the design (U14): numbers as the Spanish text writes them, round ticks, escaped labels, a line that breaks where a value is missing, and a figure that says «sin
datos» when there is nothing to draw."""

from __future__ import annotations

import re

import pytest

from flotsilica.dashboard import svg

EVIL = '<b onmouseover="x">&'


@pytest.mark.parametrize(("value", "digits", "text"), [(1234.6, 1, "1.235"), (12.34, 1, "12,3"), (0.5, 1, "0,5"), (3.0, 1, "3"), (25_000.0, 1, "25 mil"),
                                                       (2_500_000.0, 1, "2,5 M"), (float("nan"), 1, "—"), (None, 1, "—"), (-0.04, 2, "-0,04")])
def test_a_number_is_written_as_spanish_text(value, digits, text):
    assert svg.format_number(value, digits) == text


def test_ticks_are_round_cover_the_range_and_survive_a_flat_or_infinite_one():
    ticks = svg.nice_ticks(0.0, 7.3)
    assert ticks[0] <= 0.0 and ticks[-1] >= 7.3 and len(ticks) >= 2 and all(abs(round(t * 2) / 2 - t) < 1e-9 for t in ticks)
    assert svg.nice_ticks(5.0, 5.0)[0] <= 5.0 <= svg.nice_ticks(5.0, 5.0)[-1] and svg.nice_ticks(float("nan"), 1.0) == [0.0, 1.0]


def _no_markup_from_text(chart: str) -> None:
    assert "<b onmouseover" not in chart and "&lt;b onmouseover" in chart and "&amp;" in chart


def test_every_label_is_escaped_in_every_chart():
    _no_markup_from_text(svg.line_chart({EVIL: [(0.0, 1.0), (1.0, 2.0)], "otra": [(0.0, 2.0), (1.0, 1.0)]}, 400, 200, EVIL, x_ticks=[(0.0, EVIL)], unit=EVIL))
    _no_markup_from_text(svg.bar_chart([(EVIL, 3.0)], 300, 100, EVIL, unit=EVIL))
    _no_markup_from_text(svg.grouped_bar_chart([(EVIL, {EVIL: 2.0, "b": 1.0})], 300, 150, EVIL))
    _no_markup_from_text(svg.sparkline([(0.0, 1.0), (1.0, 2.0)], 120, 40, EVIL))


def test_a_chart_without_values_says_there_is_no_data_and_a_missing_value_breaks_the_line():
    for chart in (svg.line_chart({}, 300, 100, "t"), svg.bar_chart([("a", float("nan"))], 300, 100, "t"), svg.grouped_bar_chart([], 300, 100, "t"), svg.sparkline([], 100, 30, "t")):
        assert "Sin datos" in chart and chart.startswith("<svg") and chart.endswith("</svg>")
    broken = svg.line_chart({"a": [(0.0, 1.0), (1.0, 2.0), (2.0, float("nan")), (3.0, 3.0), (4.0, 4.0)]}, 300, 100, "t")
    assert len(re.findall(r"<polyline", broken)) == 2


def test_a_band_and_markers_are_drawn_and_the_grey_ones_are_labelled():
    chart = svg.line_chart({"Estimación": [(0.0, 5.0), (1.0, 6.0)]}, 400, 200, "t", band=("Rango del 80 %", [(0.0, 4.0, 6.0), (1.0, 5.0, 7.0)]),
                           markers={"Análisis nuevo": [(0.0, 5.2)], "sin análisis nuevo": [(1.0, 5.9)]}, muted=("sin análisis nuevo",))
    assert chart.count("<polygon") == 1 and "Rango del 80 %" in chart and chart.count("<circle") >= 2
    assert re.search(r'fill="var\(--muted\)"[^>]*>(?:<title>)?', chart) and "sin análisis nuevo" in chart
    assert 'role="img"' in chart and "<script" not in chart


def test_the_bars_are_scaled_to_the_largest_value_and_each_carries_its_value():
    chart = svg.bar_chart([("a", 2.0), ("b", 4.0)], 300, 100, "t")
    assert chart.count("<path") == 2 and "a: 2" in chart and "b: 4" in chart


def test_a_chart_is_an_inline_fragment_with_no_address_and_standalone_gives_it_its_namespace():
    chart = svg.bar_chart([("a", 1.0)], 200, 60, "t")
    assert "http" not in chart and "xmlns" not in chart
    assert svg.standalone(chart).startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox=') and svg.standalone(chart).count("xmlns") == 1
