"""The gate in the launch and the sign in the test (U12; RF20, C09; AC24): the launch seals the gate with its sensors, a sensor that passed keeps its sign in the test or not,
C09 follows from that, and a launch without the model with sensors says the gate was not computed."""

from __future__ import annotations

import dataclasses
import sqlite3

import numpy as np
import pandas as pd
from flotsilica.features import HourTables
from flotsilica.intervals import Calibration
from flotsilica.launch import hour_frame
from flotsilica.model import Candidate, FittedCandidate, HorizonFit, LaunchFit, fit_candidate
from flotsilica.registry import load_registered_bundle, read_seal
from flotsilica import sensitivity
from flotsilica.schema import SENSORS
from flotsilica.sensitivity import COMPARISON, launch_gate, sign_check
from flotsilica.warehouse import connect
from tests.fixtures.history import PLAN_A, build_history
from tests.fixtures.tiny_model import random_blocks, small_view


def forced_gate(sensors: dict[str, int]) -> dict:
    """A gate that says the sensors in `sensors` passed with their sign, to see what the test says about each."""
    return lambda launch, view: {"computed": True, "model": "forced", "passing": list(sensors), "curves": {}, "sensors": [
        {"sensor": s, "importance_v1": 0.5, "importance_v2": 0.5, "rho_min": 0.9 * sensors.get(s, 1), "rho_max": 0.6 * sensors.get(s, 1), "sign_stable": True, "passes": s in sensors, "sign": sensors.get(s, 0)} for s in SENSORS]}


def test_the_launch_seals_the_gate_with_its_sensors_and_stores_them(small_launched):
    h = small_launched
    gate = read_seal(h.paths.seal)["launch"]["gate"]
    assert gate["computed"] is True and gate["model"].startswith("rf-fSL") and "curves" not in gate
    assert [e["sensor"] for e in gate["sensors"]] == list(SENSORS) and gate["passing"] == [e["sensor"] for e in gate["sensors"] if e["passes"]]
    assert all((e["sign"] != 0) == e["passes"] and (e["rho_min"] is None) == (e["rho_max"] is None) for e in gate["sensors"])
    conn = sqlite3.connect(h.paths.db)
    try:
        stored = conn.execute("SELECT sensor, importance_v1, importance_v2, passes, sign FROM eval_sensitivity WHERE seal_state = 'sealed' ORDER BY rowid").fetchall()
        curves = conn.execute("SELECT DISTINCT sensor FROM eval_pd_curve WHERE scope = 'launch'").fetchall()
    finally:
        conn.close()
    assert [(r[0], r[1], r[2], bool(r[3]), r[4]) for r in stored] == [(e["sensor"], e["importance_v1"], e["importance_v2"], e["passes"], e["sign"]) for e in gate["sensors"]]
    assert sorted(r[0] for r in curves) == sorted(gate["passing"])


def test_a_launch_without_the_model_with_sensors_says_the_gate_was_not_computed(signal_launch):
    view, launch = signal_launch("lab_only")
    fit = launch.horizons[0]
    without = dataclasses.replace(launch, horizons={0: dataclasses.replace(fit, comparisons={k: v for k, v in fit.comparisons.items() if k != COMPARISON})})
    assert launch_gate(without, view) == {"computed": False, "model": None, "passing": [], "sensors": [], "curves": {}}
    assert launch_gate(dataclasses.replace(launch, horizons={}), view)["computed"] is False


def test_a_sensor_that_passed_keeps_its_sign_in_the_test_only_if_the_correlation_of_the_test_has_it(tmp_path_factory, small_canonical, quick_cfg):
    """The sign check and C09 end to end: a launch whose gate says two sensors passed, with opposite signs, and the test that follows. What the test says about each is the sign
    of the Spearman correlation of its curve over the hours of the test, and C09 is met if and only if one of them keeps its sign."""
    gate = forced_gate({"ore_pulp_ph": 1, "starch_flow": -1})
    h = build_history(tmp_path_factory.mktemp("history_gate"), small_canonical, quick_cfg, PLAN_A, gate=gate)
    seal = read_seal(h.paths.seal)
    checks = {c["sensor"]: c for c in seal["test"]["sensitivity_test"]}
    assert set(checks) == {"ore_pulp_ph", "starch_flow"} and seal["launch"]["gate"]["passing"] == ["ore_pulp_ph", "starch_flow"]
    for sensor, c in checks.items():
        assert c["kept_sign"] == bool(c["rho_test"] != 0 and np.sign(c["rho_test"]) == c["sealed_sign"]) and c["sealed_sign"] == (1 if sensor == "ore_pulp_ph" else -1)
    assert checks["ore_pulp_ph"]["rho_test"] > 0 and checks["ore_pulp_ph"]["kept_sign"] is True, "the model moves with this sensor in the test, with the sign it was sealed with"
    assert checks["starch_flow"]["rho_test"] == 0.0 and checks["starch_flow"]["kept_sign"] is False, "a curve that is flat has no sign to keep"
    kept = [s for s, c in checks.items() if c["kept_sign"]]
    sensitivity = seal["test"]["metrics"]["sensitivity"]
    assert sensitivity == {"computed": True, "passing": ["ore_pulp_ph", "starch_flow"], "kept_sign": kept} and kept == ["ore_pulp_ph"]
    c09 = next(e for e in seal["test"]["criteria"] if e["id"] == "C09")
    assert (c09["value"], c09["baseline_value"], c09["passed"]) == (float(len(kept)), 2.0, bool(kept))
    assert ("conservan el signo" if kept else "ninguno conserva el signo") in c09["verdict_es"]
    # the sensor checked here is the one the sealed model of the launch says, and the curve of the test is stored for each
    conn = connect(h.paths.db)
    try:
        bundle = load_registered_bundle(conn, h.paths.models, "v1")
        stored = {r[0] for r in conn.execute("SELECT DISTINCT sensor FROM eval_pd_curve WHERE scope = 'test' AND seal_state = 'sealed'")}
        kept_rows = {r[0]: r[1] for r in conn.execute("SELECT sensor, kept_sign FROM eval_sensitivity_test WHERE seal_state = 'sealed'")}
        assert stored == {"ore_pulp_ph", "starch_flow"} == set(kept_rows) and {s for s, k in kept_rows.items() if k} == set(kept) and bundle.comparisons[0][COMPARISON] is not None
    # the same sensor with the opposite sealed sign does not keep it, and a sensor the sealed gate did not pass is not checked
        frame = hour_frame(conn, h.runs[-1].as_of, h.sealed)
    finally:
        conn.close()
    model = bundle.comparisons[0][COMPARISON]
    opposite = {"sensors": [{"sensor": "ore_pulp_ph", "passes": True, "sign": -1}]}
    rows, curves = sign_check(HourTables.from_hours(frame, h.sealed), model, h.sealed, opposite)
    assert rows == [{"sensor": "ore_pulp_ph", "sealed_sign": -1, "rho_test": checks["ore_pulp_ph"]["rho_test"], "kept_sign": False}] and list(curves) == ["ore_pulp_ph"]
    assert sign_check(None, model, h.sealed, {"sensors": [{"sensor": "amina_flow", "passes": False, "sign": 0}]}) == ([], {})


# --- the launch gate on a model whose answer is known ------------------------------------------------------------------------------------------------------


def synthetic_launch(quick_cfg, slope: float):
    """Three blocks in which the analysis falls (``slope`` < 0) or rises with ``amina_flow_mean``, a model fitted on them and a launch made of them; the model that the launch
    chose is a different one (a forest of the laboratory alone), so that the gate must take the comparison model with sensors, not that one."""
    view = small_view(quick_cfg, rf_n_estimators=30)
    blocks = random_blocks(seed=8, sizes=(240, 90, 90))
    for block in blocks.values():
        block.y[:] = block.last1 + slope * block.X["amina_flow_mean"].to_numpy() + np.random.default_rng(1).normal(scale=0.05, size=len(block.y))
    candidate = Candidate("rf", "fSL", "change", 3)
    train, v1 = blocks["train"], blocks["valid_v1"]
    both = (np.vstack([train.X.to_numpy(), v1.X.to_numpy()]), np.concatenate([train.y, v1.y]), np.concatenate([train.last1, v1.last1]))
    model = fit_candidate(candidate, pd.DataFrame(both[0], columns=train.X.columns), both[1], both[2], view, fitted_on=("train", "valid_v1"))
    lab_only = fit_candidate(Candidate("rf", "fL", "change", 3), train.X, train.y, train.last1, view)
    fit = HorizonFit(0, (), lab_only.candidate, 0.3, lab_only, {COMPARISON: model}, Calibration(0.5, 90, 0.8, "valid_v2"))
    return view, LaunchFit(None, {0: fit}, {0: blocks}), model


def test_the_gate_takes_the_comparison_model_with_sensors_and_gives_the_sign_the_data_have(quick_cfg):
    for slope in (-0.8, 0.8):
        view, launch, model = synthetic_launch(quick_cfg, slope)
        document = launch_gate(launch, view)
        by = {e["sensor"]: e for e in document["sensors"]}
        assert document["passing"] == ["amina_flow"] and document["model"] == model.candidate.name == "rf-fSL-change-3"
        assert by["amina_flow"]["sign"] == (1 if slope > 0 else -1) and by["amina_flow"]["rho_min" if slope > 0 else "rho_max"] * slope > 0 and by["amina_flow"]["sign_stable"]
        assert all(e["sign"] == 0 for s, e in by.items() if s != "amina_flow") and list(document["curves"]) == ["amina_flow"]
        values = [p["estimate"] for p in document["curves"]["amina_flow"]]
        assert values[-1] - values[0] > 0.3 if slope > 0 else values[0] - values[-1] > 0.3


def test_a_sign_that_changes_in_a_refit_stops_the_sensor_and_each_refit_is_a_resample_of_whole_days(quick_cfg, monkeypatch):
    view, launch, model = synthetic_launch(quick_cfg, 0.8)
    assert launch_gate(launch, view)["passing"] == ["amina_flow"]
    train, seen = launch.blocks[0]["train"], []
    real = sensitivity.fit_candidate

    def flipped(candidate, X, y, last1, view_, **kwargs):
        seen.append((X.index, y.copy()))
        fitted = real(candidate, X, -y + 2 * last1, last1, view_, **kwargs)      # the refit learns the opposite relation: its dependence has the other sign
        return fitted

    monkeypatch.setattr(sensitivity, "fit_candidate", flipped)
    document = launch_gate(launch, view)
    assert document["passing"] == [] and {e["sensor"]: e for e in document["sensors"]}["amina_flow"]["sign_stable"] is False
    assert {e["sensor"]: e for e in document["sensors"]}["amina_flow"]["rho_min"] < 0 < {e["sensor"]: e for e in document["sensors"]}["amina_flow"]["rho_max"]
    # one refit per [sensitivity] refits, each with the hours of as many days as the block has, drawn with replacement: whole days, some repeated, some left out
    assert len(seen) == view.sensitivity.refits
    per_day = train.hours.normalize().value_counts()
    repeated = left_out = 0
    for index, _y in seen:
        taken = index.normalize().value_counts()
        draws = {day: count // per_day[day] for day, count in taken.items()}
        assert all(count % per_day[day] == 0 for day, count in taken.items()), "every hour of a day that was drawn is there, as many times as the day was drawn"
        assert sum(draws.values()) == len(per_day), "as many days as the block has"
        repeated += sum(n > 1 for n in draws.values())
        left_out += len(per_day) - len(draws)
    assert repeated > 0 and left_out > 0 and not seen[0][0].equals(seen[1][0]), "with replacement, and each refit is its own resample"
