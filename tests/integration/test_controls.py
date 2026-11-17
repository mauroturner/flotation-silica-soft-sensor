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


@pytest.mark.slow
def test_positive_control_beats_persistence_and_the_gate_finds_amina_flow(signal_launch):
    """The model part: the gate that finds ``amina_flow`` with its sign is U12's, and the test grows there."""
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
