"""The 80 % range of an estimate: split-conformal on the residuals of V2 (RF14, D15; plan, section 13).

The half-width of a horizon is the conformal quantile of the absolute residuals that the **refit** model (training and V1) makes on the fresh hours
of V2: the block that was used neither to choose a candidate (V1) nor to fit the model that is frozen. ``calibrate`` refuses any other block and
any model that was not fitted exactly on the blocks of ``[model] refit_on`` or that saw V2, so a range can never be calibrated where it was chosen
or fitted (AC16). The range is ``[estimate - q, estimate + q]`` clipped to ``[0, 100]``, the limits of a percentage.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:      # model.py imports this module, so the types it provides are only named here
    from flotsilica.config import SealedConfig
    from flotsilica.model import BlockData, FittedCandidate

LOW_LIMIT, HIGH_LIMIT = 0.0, 100.0
_ROUND = 9      # (n + 1) * coverage is a product of floats: 10 * 0.7 is 7.000000000000001, and its ceiling must be 7


def conformal_half_width(abs_residuals: np.ndarray, coverage: float) -> float:
    """The quantile of order ``ceil((n + 1) * coverage) / n`` of `abs_residuals` with the method "higher": the ``ceil((n + 1) * coverage)``-th
    smallest. If that rank is more than ``n`` there is no data for that coverage and it is a ``ValueError``."""
    residuals = np.asarray(abs_residuals, dtype="float64").ravel()
    if not len(residuals):
        raise ValueError("rango: sin residuos con los que calibrar")
    if not np.isfinite(residuals).all() or (residuals < 0).any():
        raise ValueError("rango: los residuos deben ser valores absolutos finitos")
    if not (isinstance(coverage, (int, float)) and not isinstance(coverage, bool) and 0 < coverage < 1):
        raise ValueError(f"rango: la cobertura debe estar entre 0 y 1, se recibió {coverage!r}")
    n = len(residuals)
    rank = math.ceil(round((n + 1) * coverage, _ROUND))
    if rank > n:
        raise ValueError(f"rango: con {n} residuos no alcanza para una cobertura de {coverage}: haría falta el residuo número {rank}")
    return float(np.sort(residuals)[rank - 1])


def interval(estimate: float, half_width: float) -> tuple[float, float]:
    """``(low, high)`` = ``estimate -/+ half_width`` clipped to [0, 100]."""
    if not (math.isfinite(estimate) and math.isfinite(half_width) and half_width >= 0):
        raise ValueError(f"rango: la estimación ({estimate!r}) y el semiancho ({half_width!r}) deben ser finitos y el semiancho no negativo")
    return max(LOW_LIMIT, estimate - half_width), min(HIGH_LIMIT, estimate + half_width)


@dataclass(frozen=True)
class Calibration:
    """The half-width of a horizon, the number of residuals it comes from, the coverage it was asked for and the block it was calibrated on."""

    half_width: float
    n: int
    coverage: float
    block: str


def calibrate(model: FittedCandidate, block: BlockData, view: SealedConfig) -> Calibration:
    """The half-width of the range of `model` from its absolute residuals on `block`, which must be V2 (``[intervals] calibrate_on``).

    `model` must be the refit one: fitted on exactly the blocks of ``[model] refit_on`` and not on `block` itself, or it is a ``ValueError``."""
    expected = tuple(view.model.refit_on)
    if block.name != view.intervals.calibrate_on:
        raise ValueError(f"rango: se calibra solo con {view.intervals.calibrate_on!r} (D15), se recibió el bloque {block.name!r}")
    if model.fitted_on != expected:
        raise ValueError(f"rango: se calibra el modelo reajustado con {list(expected)}, pero este se ajustó con {list(model.fitted_on)}")
    if block.name in model.fitted_on:
        raise ValueError(f"rango: el modelo vio el bloque {block.name!r} al ajustarse; sus residuos ahí no dicen cuánto se equivoca")
    residuals = np.abs(model.predict(block.X, block.last1) - block.y)
    return Calibration(conformal_half_width(residuals, view.intervals.coverage), len(residuals), view.intervals.coverage, block.name)
