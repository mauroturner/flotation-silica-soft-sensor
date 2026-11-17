"""The split in time (RF10, D10; plan, section 9): the block of each hour, by the hour of the target, and the check of the boundaries.

Training, V1 (where the candidates, k and B* are chosen), V2 (where the range is calibrated) and the test follow one another in time, and at every
boundary between two of them there are ``purge_hours`` whole hours that belong to no block (``purge_1``, ``purge_v`` and ``purge_2``): the
features of an hour read the hours before it, and the purge keeps the first hours of a block from reading the end of the one before as if it
were the same period. Before ``train_first`` and after ``test_last`` an hour is ``outside``. ``sql/staging/stg_hours.sql`` assigns the same blocks in
SQL; a test compares the two.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

BLOCKS = ("train", "purge_1", "valid_v1", "purge_v", "valid_v2", "purge_2", "test", "outside")
MODEL_BLOCKS = ("train", "valid_v1", "valid_v2", "test")
HOUR = timedelta(hours=1)


class SplitError(ValueError):
    """The split of the configuration breaks a rule of D10; the message names the block or the boundary."""


def block_of(hours: pd.DatetimeIndex, view: Any) -> pd.Series:
    """The block of each hour of `hours` (the hour of the target), as a Series indexed by `hours` in the order given: one of ``BLOCKS``.

    Each model block holds its window from its first hour to its last, both included; the hours between two windows are the purge of that boundary,
    and an hour before the first window or after the last one is ``outside``."""
    s = view.split
    index = pd.DatetimeIndex(hours)
    # an hour before a first hour belongs to what precedes it (the purge, or outside before the training block); an hour up to a last hour is its block
    conditions = [index < s.train_first, index <= s.train_last, index < s.v1_first, index <= s.v1_last, index < s.v2_first, index <= s.v2_last,
                  index < s.test_first, index <= s.test_last]
    names = ["outside", "train", "purge_1", "valid_v1", "purge_v", "valid_v2", "purge_2", "test"]
    values = np.select(conditions, names, default="outside")
    return pd.Series(values, index=index, dtype=object)


def check_split(view: Any) -> None:
    """Raise ``SplitError`` naming the block or the boundary if the split of `view` (``[hours]`` and ``[split]``) breaks D10: a block that ends
    before it starts, a training block before the first hour of the data or a test block after the last one, or two consecutive blocks with fewer
    than ``purge_hours`` whole hours between them (AC09)."""
    h, s = view.hours, view.split
    blocks = (("train", s.train_first, s.train_last), ("valid_v1", s.v1_first, s.v1_last), ("valid_v2", s.v2_first, s.v2_last),
              ("test", s.test_first, s.test_last))
    for name, first, last in blocks:
        if first > last:
            raise SplitError(f"[split] {name}: la primera hora ({first}) es posterior a la última ({last})")
    if s.train_first < h.first_hour:
        raise SplitError(f"[split] train_first: no puede ser anterior a first_hour de [hours] ({h.first_hour}), se recibió {s.train_first}")
    # The last analysis of the test arrives at test_last + latency_hours and the close waits until last_hour + latency_hours (D10, D21). The same
    # shift on both sides cancels, so the check is the one of the calendar, whatever the latency.
    if s.test_last > h.last_hour:
        raise SplitError(
            f"[split] test_last: no puede ser posterior a last_hour ({h.last_hour}), se recibió {s.test_last}: el último análisis de la prueba "
            f"llega en test_last + latency_hours y el cierre espera hasta last_hour + latency_hours ({view.lab.latency_hours} h), el mismo desfase "
            f"en los dos lados, de modo que el último análisis debe llegar dentro del cierre"
        )
    # every edge between two consecutive blocks keeps purge_hours whole hours that belong to neither block (AC09)
    edges = (("train", "valid_v1", s.train_last, s.v1_first), ("valid_v1", "valid_v2", s.v1_last, s.v2_first),
             ("valid_v2", "test", s.v2_last, s.test_first))
    for before, after, last, first in edges:
        between = (first - last) // HOUR - 1
        if between < s.purge_hours:
            raise SplitError(f"borde {before} → {after}: se esperaba una purga de {s.purge_hours} h entre {last} y {first}, hay {max(between, 0)} h")
