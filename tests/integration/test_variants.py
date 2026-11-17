"""The variants after the launch seal (U11; RF18, AC23): they are computed only when the seal has its launch part, they are the ones of ``[variants]``, they land in the test
part of the seal and in ``eval_variants``, and what they read of the test never reaches a choice."""

from __future__ import annotations

import dataclasses
import sqlite3

import numpy as np
import pytest

from flotsilica import variants
from flotsilica.baselines import eligible
from flotsilica.features import HourTables, design
from flotsilica.launch import hour_frame
from flotsilica.model import LAUNCH_BLOCKS, build_blocks, fit_candidate, stack
from flotsilica.split import block_of
from flotsilica.registry import SealError, load_registered_bundle, read_seal
from flotsilica.warehouse import connect


def test_variants_run_after_the_launch_seal_and_land_in_the_test_part(small_history, tmp_path):
    h = small_history
    seal = read_seal(h.paths.seal)
    found = seal["test"]["variants"]
    assert {v["variant"] for v in found} == {"latency_3", "latency_4", "refit_all", "all_hours"}
    methods = {(v["variant"], v["horizon"], v["method"], v["metric"]) for v in found}
    for variant, horizons in (("latency_3", (0,)), ("latency_4", (0,)), ("refit_all", (0, 1, 2)), ("all_hours", (0,))):
        for horizon in horizons:
            for method in ("model", "b1_persistence"):
                assert (variant, horizon, method, "mae") in methods and (variant, horizon, method, "hours") in methods, (variant, horizon, method)
    assert ("latency_3", 0, "model_vs_b1_persistence", "ci_high") in methods and all(isinstance(v["value"], float) for v in found)
    # a latency that is longer leaves fewer hours with every input: the cohort of the test shrinks with it
    hours = {v["variant"]: v["value"] for v in found if v["horizon"] == 0 and v["method"] == "model" and v["metric"] == "hours"}
    assert hours["latency_4"] <= hours["latency_3"] <= hours["all_hours"]
    by = {(v["variant"], v["method"], v["metric"]): v["value"] for v in found if v["horizon"] == 0}
    assert (by["latency_3", "model", "mae"], by["latency_3", "b1_persistence", "mae"]) != (by["latency_4", "model", "mae"], by["latency_4", "b1_persistence", "mae"]), "each latency is its own"
    conn = sqlite3.connect(h.paths.db)
    try:
        stored = conn.execute("SELECT variant, horizon, method, metric, value FROM eval_variants WHERE seal_state = 'sealed'").fetchall()
    finally:
        conn.close()
    assert sorted(stored) == sorted((v["variant"], v["horizon"], v["method"], v["metric"], v["value"]) for v in found)


def test_the_variants_are_not_computed_without_the_launch_part_of_the_seal(small_history, tmp_path):
    h = small_history
    conn = connect(h.paths.db)
    try:
        bundle = load_registered_bundle(conn, h.paths.models, "v1")
        with pytest.raises(SealError, match="después de la parte del lanzamiento"):
            variants.run(conn, bundle, h.sealed, as_of=h.runs[-1].as_of, seal_path=tmp_path / "no_seal.json")
        again = variants.run(conn, bundle, h.sealed, as_of=h.runs[-1].as_of, seal_path=h.paths.seal)
    finally:
        conn.close()
    assert again == read_seal(h.paths.seal)["test"]["variants"], "the same variants again: nothing in them depends on when they are computed"


def test_refit_all_is_the_candidate_refit_on_the_three_blocks_and_each_latency_is_its_own_cohort(small_history):
    """Both are written out here with the public functions: the candidate of H0 fitted on training, V1 and V2 and measured on the hours of the test; and the
    persistence of a latency, which is the analysis that had arrived with that latency."""
    h = small_history
    conn = connect(h.paths.db)
    try:
        frame = hour_frame(conn, h.runs[-1].as_of, h.sealed)
        candidate = load_registered_bundle(conn, h.paths.models, "v1").horizons[0].candidate
    finally:
        conn.close()
    found = {(v["variant"], v["horizon"], v["method"], v["metric"]): v["value"] for v in read_seal(h.paths.seal)["test"]["variants"]}
    tables = HourTables.from_hours(frame, h.sealed)
    x_fit, y_fit, last_fit = stack(build_blocks(tables, h.sealed, (0,))[0], LAUNCH_BLOCKS)
    fitted = fit_candidate(candidate, x_fit, y_fit, last_fit, h.sealed, fitted_on=LAUNCH_BLOCKS)
    inside = tables.hours[(block_of(tables.hours, h.sealed) == "test").to_numpy()]
    hours = inside[eligible(tables, inside, 0, h.sealed).to_numpy()]
    x, (y, _fresh) = design(tables, hours, 0, h.sealed), tables.analysis_of(hours)
    assert found["refit_all", 0, "model", "mae"] == pytest.approx(float(np.mean(np.abs(fitted.predict(x, x["lab_last1"].to_numpy()) - y))))
    assert found["refit_all", 0, "b1_persistence", "mae"] == pytest.approx(float(np.mean(np.abs(x["lab_last1"].to_numpy() - y)))) and found["refit_all", 0, "model", "hours"] == len(hours)
    # the persistence of latency 4 is the last analysis that had arrived four hours after its sample: older than the one of latency 2, so it is another number
    view_4 = dataclasses.replace(h.sealed, lab=dataclasses.replace(h.sealed.lab, latency_hours=4))
    tables_4 = HourTables.from_hours(frame.drop(columns=["available_at"]), view_4)
    hours_4 = inside[eligible(tables_4, inside, 0, view_4).to_numpy()]
    x4, (y4, _f) = design(tables_4, hours_4, 0, view_4), tables_4.analysis_of(hours_4)
    assert found["latency_4", 0, "b1_persistence", "mae"] == pytest.approx(float(np.mean(np.abs(x4["lab_last1"].to_numpy() - y4)))) and found["latency_4", 0, "model", "hours"] == len(hours_4)
