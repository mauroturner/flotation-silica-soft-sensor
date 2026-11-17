"""Small models for the tests of the model, the range and the artifact (U09): blocks of synthetic matrices written by hand, the small fixture split
into the three blocks of a launch, and a bundle that costs a fraction of a second.

Nothing here reads a file of the project or the real data: the numbers are drawn from a seeded generator or come from the small synthetic fixture.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

import numpy as np
import pandas as pd

from flotsilica.baselines import fit_b3
from flotsilica.model import BlockData, Candidate, fit_candidate, refit_blocks
from flotsilica.registry import HorizonModel, ModelBundle
from flotsilica.schema import AGGREGATE_COLUMNS, FEATURE_COLUMNS

LEVEL = 2.5


def random_block(name: str, n: int, seed: int, horizon: int = 0, first: str = "2017-05-01") -> BlockData:
    """`n` hours of features drawn from a seeded generator (all the 67 columns, a lab_last1 near 2.5) with the analysis the sensor ``amina_flow_mean``
    moves: ``y = lab_last1 + 0.5 * amina_flow_mean + noise``."""
    rng = np.random.default_rng(seed)
    hours = pd.date_range(first, periods=n, freq="h")
    X = pd.DataFrame(rng.normal(size=(n, len(FEATURE_COLUMNS))), index=hours, columns=list(FEATURE_COLUMNS))
    X["lab_last1"] = LEVEL + rng.normal(scale=0.3, size=n)
    y = X["lab_last1"].to_numpy() + 0.5 * X["amina_flow_mean"].to_numpy() + rng.normal(scale=0.1, size=n)
    return BlockData(name, horizon, hours, X, y, X["lab_last1"].to_numpy(dtype="float64"))


def random_blocks(seed: int = 0, sizes: tuple[int, int, int] = (200, 80, 80)) -> dict[str, BlockData]:
    """The three blocks of a launch, one after the other, from independent draws."""
    names = ("train", "valid_v1", "valid_v2")
    return {name: random_block(name, n, seed + k) for k, (name, n) in enumerate(zip(names, sizes, strict=True))}


def small_view(quick_cfg, **model):
    """The quick configuration with the three launch blocks inside the small fixture (three weeks, the first stretch before the March gap): the training block
    on 2017-03-10 to 03-13, V1 on 03-14 to 03-15 03:00 and V2 on 03-15 04:00 to 03-16 05:00, at least five fresh hours each, forests of 20 trees and leaves of 3.
    The windows are not a valid split (no purges): only ``block_of`` reads them, which is all the model code does."""
    def at(text: str) -> datetime:
        return pd.Timestamp(text).to_pydatetime()

    split = dataclasses.replace(quick_cfg.split, train_last=at("2017-03-13 23:00"), v1_first=at("2017-03-14 00:00"), v1_last=at("2017-03-15 03:00"),
                                v2_first=at("2017-03-15 04:00"), v2_last=at("2017-03-16 05:00"), min_fresh_hours_per_block=5)
    changes = {"rf_n_estimators": 20, "rf_min_samples_leaf": (3,), **model}
    return dataclasses.replace(quick_cfg, split=split, model=dataclasses.replace(quick_cfg.model, **changes))


def tiny_bundle(quick_cfg, seed: int = 0, feature_set: str = "fSL") -> ModelBundle:
    """A bundle with one horizon built from synthetic blocks: a forest of 20 trees on `feature_set` in level, its comparison models and a ridge (B3)."""
    view = small_view(quick_cfg)
    blocks = random_blocks(seed)
    candidate = Candidate("rf", feature_set, "level", 3)
    model = refit_blocks(candidate, blocks, view)
    comparison = {"best_lab_only": refit_blocks(Candidate("rf", "fL", "level", 3), blocks, view)}
    train = blocks["train"]
    b3 = fit_b3(train.X[list(AGGREGATE_COLUMNS)], train.y, view)
    horizon = HorizonModel(0, candidate, model, model.columns, 0.6, "b1_persistence", 3)
    return ModelBundle(view.model.model_version, (horizon,), {0: comparison}, float(train.y.mean()), {0: b3})


def fit_on_train(blocks: dict[str, BlockData], candidate: Candidate, view):
    """The candidate fitted on the training block."""
    train = blocks["train"]
    return fit_candidate(candidate, train.X, train.y, train.last1, view)
