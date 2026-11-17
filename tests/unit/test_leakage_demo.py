"""The leak demonstration (U11; D09): it adds the iron of the concentrate past the guard on purpose, and it can write nothing that a model or an estimate is made of."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from flotsilica.features import LeakageError, build_matrix
from flotsilica.leakage_demo import CHECKS_ES, leakage_table
from flotsilica.model import Candidate
from tests.fixtures.tiny_model import random_blocks, small_view

SOURCE = (Path(__file__).resolve().parents[2] / "src" / "flotsilica" / "leakage_demo.py").read_text(encoding="utf-8")


def test_the_demonstration_has_its_three_checks_and_the_iron_helps_only_because_it_looks_at_the_target(quick_cfg):
    view, blocks = small_view(quick_cfg), random_blocks(seed=4)
    rng = np.random.default_rng(7)
    iron = pd.concat([pd.Series(65 - 3 * b.y + rng.normal(scale=0.2, size=len(b.y)), index=b.hours) for b in blocks.values()])      # correlated with the analysis of its own hour
    table = leakage_table(blocks, iron, Candidate("rf", "fSL", "change", 3), view)
    assert list(table["check_id"]) == list(CHECKS_ES) == ["blocks", "random_split", "iron_conc"] and list(table.columns) == ["check_id", "description_es", "mae", "r2", "rows", "note_es"]
    by = table.set_index("check_id")
    pooled = sum(len(b.y) for b in blocks.values())
    assert by.loc["blocks", "rows"] == len(blocks["valid_v2"].y) and by.loc["random_split", "rows"] == pooled - int(round(pooled * 0.8)) and by.loc["iron_conc", "rows"] == by.loc["blocks", "rows"]
    assert by.loc["iron_conc", "mae"] < by.loc["blocks", "mae"] and by.loc["iron_conc", "r2"] > by.loc["blocks", "r2"], "the leaked variable makes the error fall"
    # the random split written out: the hours are shuffled with the generator of seed 0 and the last fifth is measured; an ordered split is another number
    from flotsilica.model import make_estimator

    candidate = Candidate("rf", "fSL", "change", 3)
    cols = list(build_matrix(blocks["train"].X, "fSL").columns)
    x = np.vstack([b.X[cols].to_numpy() for b in blocks.values()])
    y, last = np.concatenate([b.y for b in blocks.values()]), np.concatenate([b.last1 for b in blocks.values()])
    order = np.random.default_rng(0).permutation(len(y))
    fit, test = order[: int(round(len(y) * 0.8))], order[int(round(len(y) * 0.8)):]
    estimate = last[test] + make_estimator(candidate, view).fit(x[fit], y[fit] - last[fit]).predict(x[test])
    assert by.loc["random_split", "mae"] == pytest.approx(float(np.mean(np.abs(estimate - y[test]))))
    ordered = last[len(y) - len(test):] + make_estimator(candidate, view).fit(x[: len(fit)], y[: len(fit)] - last[: len(fit)]).predict(x[len(y) - len(test):])
    assert by.loc["random_split", "mae"] != pytest.approx(float(np.mean(np.abs(ordered - y[len(y) - len(test):]))))
    assert table.equals(leakage_table(blocks, iron, Candidate("rf", "fSL", "change", 3), view)), "seeded: the same table again"
    with pytest.raises(ValueError, match="hierro"):
        leakage_table(blocks, iron.iloc[:-5], Candidate("rf", "fSL", "change", 3), view)
    # the guard that the demonstration goes around is there: the iron cannot be a column of a matrix
    with pytest.raises(LeakageError, match="iron_conc_pct"):
        build_matrix(blocks["train"].X.assign(iron_conc_pct=iron.to_numpy()[: len(blocks["train"].y)]), "fSL")


def test_the_demonstration_never_writes_the_registry_the_estimates_or_a_file():
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|executemany|write_text|write_bytes|write_atomic|open\()", SOURCE)
    assert "sqlite3" not in SOURCE and "model_registry" not in SOURCE and "method_estimates" not in SOURCE and "estimates" not in SOURCE.replace("the estimates", "")
