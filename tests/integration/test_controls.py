"""The controls of the model (U09; D40, AC15 in part): with a signal planted in a sensor the model has to beat the persistence outside the noise; the part of
the gate that finds the sensor and its sign, and the negative control, come with U12 and U13.

The planted signal is ``amina_flow`` of the same hour with beta 0.7 (``sensor_signal``): the launch is the one of the pipeline (``model.fit_launch``) on the
standard fixture at the horizon 0, the interval is the one of the criteria (whole days of V2, 2,000 resamples, seed 0) and V2 is the block that no choice
read."""

from __future__ import annotations

import numpy as np
import pytest

from flotsilica.evaluation import day_bootstrap
from flotsilica.schema import FEATURE_SETS, SENSORS
from flotsilica.sensitivity import launch_gate


@pytest.mark.slow
def test_positive_control_beats_persistence_and_the_gate_finds_amina_flow(signal_launch):
    """The model part (U09), and the gate (U12): the stability gate finds ``amina_flow`` with its sign and finds no other sensor."""
    view, launch = signal_launch("sensor_signal")
    horizon = launch.horizons[0]
    v2 = launch.blocks[0]["valid_v2"]

    # the selection found the sensors: the chosen candidate reads a set with them, and so does the best "with sensors" comparison
    assert horizon.chosen.feature_set in ("fS", "fSL", "fSLF")
    assert any(column.startswith("amina_flow_") for column in horizon.model.columns)
    assert set(FEATURE_SETS[horizon.chosen.feature_set]) >= {f"{s}_mean" for s in SENSORS}
    assert horizon.mae_v1 < launch.baselines.mae_v1[0]["b1_persistence"]

    # outside the noise on the block no choice read: the upper end of the interval of MAE(model) - MAE(persistence) on V2 is below zero
    estimate = horizon.model.predict(v2.X, v2.last1)
    days = v2.hours.normalize().to_numpy()
    interval = day_bootstrap(estimate - v2.y, v2.last1 - v2.y, days, view.evaluation.bootstrap_resamples, view.evaluation.bootstrap_seed)
    assert interval.ci_high < 0 and interval.difference < 0
    assert float(np.mean(np.abs(estimate - v2.y))) < 0.6 * float(np.mean(np.abs(v2.last1 - v2.y)))

    # the range is the one calibrated on V2 and its coverage there is at least the one asked for
    low, high = estimate - horizon.calibration.half_width, estimate + horizon.calibration.half_width
    assert float(np.mean((low <= v2.y) & (v2.y <= high))) >= view.intervals.coverage

    # the gate of the launch, on the model with sensors that the comparison keeps: only the planted sensor passes, it passes in V1 and in V2 and its sign is the planted one
    document = launch_gate(launch, view)
    by = {entry["sensor"]: entry for entry in document["sensors"]}
    assert document["computed"] is True and document["passing"] == ["amina_flow"] and document["model"] == launch.horizons[0].comparisons["best_with_sensors"].candidate.name
    assert by["amina_flow"]["sign"] == 1 and by["amina_flow"]["importance_v1"] >= view.sensitivity.min_importance_mae and by["amina_flow"]["importance_v2"] >= view.sensitivity.min_importance_mae
    assert by["amina_flow"]["rho_min"] >= view.sensitivity.min_abs_spearman and by["amina_flow"]["sign_stable"] is True
    assert sum(entry["passes"] for entry in by.values()) == 1 and set(by) == set(SENSORS)
    assert [p["value"] for p in document["curves"]["amina_flow"]] == sorted(p["value"] for p in document["curves"]["amina_flow"]) and list(document["curves"]) == ["amina_flow"]


@pytest.mark.slow
def test_negative_control_finds_no_sensor_and_sensors_add_nothing(signal_launch):
    """A silica that does not depend on the sensors (``lab_only``): no sensor passes the gate, and the interval of the difference of MAE between the best model with sensors and
    the best with the laboratory alone, on V2, holds zero."""
    view, launch = signal_launch("lab_only")
    document = launch_gate(launch, view)
    assert document["computed"] is True and document["passing"] == [] and not any(entry["passes"] for entry in document["sensors"]) and document["curves"] == {}
    assert len(document["sensors"]) == len(SENSORS) and all(entry["sign"] == 0 for entry in document["sensors"])
    v2 = launch.blocks[0]["valid_v2"]
    fit = launch.horizons[0]
    with_sensors, lab_only = fit.comparisons["best_with_sensors"], fit.comparisons["best_lab_only"]
    boot = day_bootstrap(with_sensors.predict(v2.X, v2.last1) - v2.y, lab_only.predict(v2.X, v2.last1) - v2.y, v2.hours.normalize().to_numpy(),
                         view.evaluation.bootstrap_resamples, view.evaluation.bootstrap_seed)
    assert boot.ci_low <= 0 <= boot.ci_high, (boot.ci_low, boot.ci_high)
