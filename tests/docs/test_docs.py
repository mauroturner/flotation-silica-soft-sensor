"""The documentation is checked like code (AC22, AC39; RF28; RNF14; plan, sections 25 and 26).

U22: the README has the headings of plan section 25 in their order, its results block is the sealed summary that ``docs-sync`` copies (never one written
by hand), and it says the unfavourable verdicts («no supera») in «El problema», «La solución» and «Los resultados»; the model card has the contents the plan
lists, every verdict as the summary writes it, the memory counters and the suite's limit. These tests read the versioned Markdown and the versioned reports
and run nothing. The tests of the other documents (dictionary, runbook, step by step, advisories) are U23's and join this file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from flotsilica.reporting import RESULTS_END, RESULTS_START

README_TITLE = "# Sílice en el concentrado, sin esperar al laboratorio"
README_HEADINGS = [   # plan, section 25, in this order (AC39)
    "El problema", "La solución", "Los resultados", "En qué consiste", "Los datos", "Los algoritmos", "El producto", "La documentación",
    "Con IA, de punta a punta", "Para qué sirve", "Cómo correrlo de punta a punta", "Paso a paso", "Fuente y licencia",
]
MODEL_CARD_HEADINGS = [   # what plan section 25 lists for the model card, in this order
    "Uso previsto y no previsto", "Datos", "La frescura y por qué las cifras difieren de research.md", "Latencia supuesta", "Horizontes", "Partición",
    "Métodos", "Selección y reajuste", "Rango del 80 %", "Criterios y resultados", "Sensibilidades y su compuerta", "Limitaciones", "Tiempos y memoria",
    "La suite rápida",
]
FAILED = ["C01", "C02", "C03", "C04", "C06", "C08", "C09"]   # D47: what the sealed run says
PASSED = ["C05", "C07"]
RESULTS_HEADING = "## Resultados"   # the first line of the summary, copied as it is (D44, D48)


@pytest.fixture(scope="module")
def readme(project_root: Path) -> str:
    return (project_root / "README.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def model_card(project_root: Path) -> str:
    return (project_root / "docs" / "model-card.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def summary(project_root: Path) -> dict:
    return json.loads((project_root / "reports" / "evaluation_summary.json").read_text(encoding="utf-8"))


def section(text: str, title: str) -> str:
    """The body of the second-level section `title`, up to the next second-level heading."""
    return re.split(r"^## ", text.split(f"\n## {title}\n", 1)[1], flags=re.MULTILINE)[0]


def test_readme_headings_in_order_and_results_block_matches_summary(project_root: Path, readme: str, summary: dict) -> None:
    assert readme.startswith(README_TITLE + "\n")
    assert readme.count(RESULTS_START) == 1 and readme.count(RESULTS_END) == 1
    head, rest = readme.split(RESULTS_START)
    block, tail = rest.split(RESULTS_END)
    block = block.strip("\n")
    # the block carries its own «## Resultados» (D44): the headings of the plan are those outside it, in order (D48)
    assert re.findall(r"^## (.+)$", head + tail, flags=re.MULTILINE) == README_HEADINGS
    written = (project_root / "reports" / "evaluation_summary.md").read_text(encoding="utf-8")
    assert block == written.strip("\n")   # what docs-sync copies, byte for byte
    assert block.startswith(RESULTS_HEADING + "\n") and re.findall(r"^## (.+)$", block, flags=re.MULTILINE) == ["Resultados"]
    framing = section(head + "\n## ", "Los resultados")   # «Los resultados» frames the block before it and reads it after it (D48)
    assert len(framing.strip()) > 400 and "\n## En qué consiste\n" in tail
    # AC22: the sealed summary is unfavourable, and the README says «no supera» outside the block too, in the three sections that tell it
    assert summary["evaluation_status"] == "sealed" and summary["post_seal"] is None
    assert [c["criterion_id"] for c in summary["criteria"] if c["passed"] is False] == FAILED
    assert [c["criterion_id"] for c in summary["criteria"] if c["passed"] is True] == PASSED
    assert [c["criterion_id"] for c in summary["criteria"] if c["passed"] is None] == ["C10"]
    for criterion in summary["criteria"]:
        assert criterion["verdict_es"] in block, criterion["criterion_id"]
    reading = section(head + "\n## ", "Los resultados") + tail.split("\n## En qué consiste\n")[0]
    for title, text in (("El problema", section(readme, "El problema")), ("La solución", section(readme, "La solución")), ("Los resultados", reading)):
        assert "no supera" in text, title
    for criterion in FAILED + PASSED:
        assert re.search(rf"\b{criterion}\b", reading), criterion
    assert re.search(r"persistencia", reading) and "H0" in reading and "H1" in reading


def test_the_model_card_has_the_contents_of_the_plan_and_says_the_unfavourable_verdicts(model_card: str, summary: dict) -> None:
    assert re.findall(r"^## (.+)$", model_card, flags=re.MULTILINE) == MODEL_CARD_HEADINGS
    for criterion in summary["criteria"]:
        assert criterion["verdict_es"] in model_card, criterion["criterion_id"]   # every verdict as the summary writes it, «no supera» included
    for limit in (
        "OpenML", "no se comparó byte a byte", "una latencia supuesta", "unidades de los sensores", "una sola vez", "seis meses", "una sola planta",
        "PeakWorkingSetSize", "PeakPagefileUsage", "120 s", "90 s", "asociación del modelo", "sin asociación estable",
    ):
        assert limit.lower() in model_card.lower(), limit
    assert re.search(r"suite rápida[^\n]*\d{2,3},\d+ s", model_card)   # AC40: measured and written down


def test_the_readme_says_what_is_pending_and_gives_the_attribution(readme: str, model_card: str) -> None:
    """RNF14: the independent evaluation and the ``.pbix`` are not done and the README says so; the credit of the source is complete; nothing local is published."""
    text = readme.lower()
    assert "evaluación independiente" in text and "todavía no" in text and ".pbix" in text
    tail = section(readme, "Fuente y licencia")
    for piece in ("Quality Prediction in a Mining Process", "Eduardo Magalhães Oliveira", "CC0", "OpenML", "43311", "a25122979ba8c5fb9c12e361db61032efc6892a24b5746cc8309da601d9639b2"):
        assert piece in tail, piece
    for document in (readme, model_card):
        assert not re.search(r"[A-Za-z]:[\\/]+(Users|Documents and Settings)", document) and "mauro" not in document.lower() and "@gmail" not in document
