"""Metrics and intervals of the evaluation (D17, RF18; plan, section 16): the numbers of a set of hours and the interval of a difference of errors.

``metrics`` gives the mean absolute error, the root mean square error, the bias (estimate minus analysis) and, with a range, its coverage.
``day_bootstrap`` resamples **whole days** (the hours of a day are not independent: the autocorrelation at one hour is 0.76) with replacement, the
same days for both methods, and takes the 2.5 and 97.5 percentiles of the difference of the two MAE, each over the hours of the resample: a quotient
of sums, not a mean of daily means. The draws are ``numpy.random.default_rng(seed).integers(0, days, size=(n, days))``.
The criteria, the variants and the summary come with U11.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

PERCENTILES = (2.5, 97.5)


@dataclass(frozen=True)
class Metrics:
    hours: int
    mae: float
    rmse: float
    bias: float
    coverage: float | None          # the share of hours with low <= actual <= high; None without a range


@dataclass(frozen=True)
class Bootstrap:
    difference: float               # MAE(a) - MAE(b) over all the hours
    ci_low: float
    ci_high: float
    resamples: int
    differences: np.ndarray         # the difference of each resample


def _numbers(values: np.ndarray, what: str) -> np.ndarray:
    array = np.asarray(values, dtype="float64")
    if not np.isfinite(array).all():
        raise ValueError(f"{what}: se esperaban valores finitos")
    return array


def metrics(actual: np.ndarray, estimate: np.ndarray, low: np.ndarray | None = None, high: np.ndarray | None = None) -> Metrics:
    """The metrics of `estimate` against `actual` over the hours given, in points of silica; the coverage needs both ends of the range."""
    actual, estimate = _numbers(actual, "análisis"), _numbers(estimate, "estimaciones")
    if len(actual) != len(estimate):
        raise ValueError("el análisis y la estimación deben tener la misma cantidad de horas")
    if not len(actual):
        raise ValueError("sin horas que evaluar")
    if (low is None) != (high is None):
        raise ValueError("el rango necesita sus dos extremos, el bajo y el alto")
    error = estimate - actual
    coverage = None
    if low is not None:
        low, high = _numbers(low, "extremo bajo"), _numbers(high, "extremo alto")
        if len(low) != len(actual) or len(high) != len(actual):
            raise ValueError("el rango debe tener la misma cantidad de horas que el análisis")
        coverage = float(np.mean((low <= actual) & (actual <= high)))
    return Metrics(len(actual), float(np.mean(np.abs(error))), float(np.sqrt(np.mean(error ** 2))), float(np.mean(error)), coverage)


def day_bootstrap(err_a: np.ndarray, err_b: np.ndarray, days: np.ndarray, n: int = 2000, seed: int = 0) -> Bootstrap:
    """The interval of 95 % of MAE(a) - MAE(b) by resampling the days of `days` (one label per hour) `n` times with the generator of `seed`.

    `err_a` and `err_b` are the errors of the two methods on the same hours, with or without sign (only their size counts)."""
    if not isinstance(n, (int, np.integer)) or isinstance(n, bool) or n < 1:
        raise ValueError(f"remuestras: se esperaba un entero de 1 o más, se recibió {n!r}")
    abs_a, abs_b = np.abs(np.asarray(err_a, dtype="float64")), np.abs(np.asarray(err_b, dtype="float64"))
    labels = np.asarray(days)
    if not (len(abs_a) == len(abs_b) == len(labels)):
        raise ValueError("los errores de los dos métodos y los días deben tener la misma cantidad de horas")
    if not len(abs_a):
        raise ValueError("sin horas que remuestrear")
    if not (np.isfinite(abs_a).all() and np.isfinite(abs_b).all()):
        raise ValueError("los errores deben ser finitos")
    unique, codes = np.unique(labels, return_inverse=True)
    sum_a, sum_b = np.bincount(codes, weights=abs_a), np.bincount(codes, weights=abs_b)
    hours = np.bincount(codes).astype("float64")
    picks = np.random.default_rng(seed).integers(0, len(unique), size=(int(n), len(unique)))
    differences = (sum_a[picks].sum(axis=1) - sum_b[picks].sum(axis=1)) / hours[picks].sum(axis=1)
    low, high = np.percentile(differences, PERCENTILES)
    return Bootstrap(float(abs_a.mean() - abs_b.mean()), float(low), float(high), int(n), differences)
