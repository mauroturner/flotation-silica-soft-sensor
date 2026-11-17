"""The launch stops at M01 (U09; RF13, D09; AC13): a control feature that looks at the target of the same hour gives a V1 error under the ratio of the
persistence, ``LeakageError`` ends the launch before anything is refit or calibrated, and the same launch without that feature goes through.

The small fixture is split into the three blocks of a launch (``small_view``): the leak is a column of the schema that holds the analysis of the target hour,
put into the features by wrapping ``design`` (the guard of ``build_matrix`` cannot see a column that has a permitted name)."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from flotsilica import model
from flotsilica.features import HourTables, LeakageError
from flotsilica.model import fit_launch
from tests.fixtures.tiny_model import small_view

LEAKY_COLUMN = "amina_flow_mean"


@pytest.fixture(scope="module")
def view(quick_cfg):
    base = small_view(quick_cfg, rf_max_features=1.0)       # every column is a candidate of every split, so a leaked one is found at once
    return dataclasses.replace(base, evaluation=dataclasses.replace(base.evaluation, horizons=(0,)))


@pytest.fixture(scope="module")
def tables(small_canonical, view) -> HourTables:
    return HourTables.from_hours(small_canonical.hours, view)


def test_a_target_looking_control_feature_trips_m01_and_stops_the_launch(tables, view, monkeypatch):
    honest = fit_launch(tables, view)                                            # without the leak, the launch goes through at the default tripwire
    assert view.criteria.leak_tripwire_ratio == 0.5
    assert honest.horizons[0].mae_v1 >= 0.5 * honest.baselines.mae_v1[0]["b1_persistence"]

    real_design = model.design

    def leaking_design(tables_, targets, horizon, view_):
        rows = real_design(tables_, targets, horizon, view_)
        silica, _fresh = tables_.analysis_of(rows.index)          # at horizon 0 the target of the row of ``u`` is the hour ``u``: the hour of the instant minus one
        rows[LEAKY_COLUMN] = silica
        return rows

    calls: list[str] = []
    for owner, name in ((model, "refit_blocks"), (model, "refit"), (model.intervals, "calibrate")):
        real = getattr(owner, name)
        monkeypatch.setattr(owner, name, lambda *a, _real=real, _name=name, **k: (calls.append(_name), _real(*a, **k))[1])
    monkeypatch.setattr(model, "design", leaking_design)
    with pytest.raises(LeakageError, match="M01") as caught:
        fit_launch(tables, view)
    assert "R5" in str(caught.value) and "persistencia" in str(caught.value)
    assert calls == []                                                          # the launch stopped before the refit and before the range

    # the tripwire is the only thing that stood in the way: with it off, the same leaky launch fits and calibrates a model that is nearly exact
    off = dataclasses.replace(view, criteria=dataclasses.replace(view.criteria, leak_tripwire_ratio=0.0))
    leaked = fit_launch(tables, off)
    assert leaked.horizons[0].mae_v1 < 0.5 * leaked.baselines.mae_v1[0]["b1_persistence"]
    assert np.isfinite(leaked.horizons[0].calibration.half_width) and "calibrate" in calls
