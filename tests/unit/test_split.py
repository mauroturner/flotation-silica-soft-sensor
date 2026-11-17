"""The split in time (U08; RF10, D10; AC09): the blocks by the hour of the target, the purges between them that belong to no block, a
configuration that breaks a boundary refused by the boundary's name, and the same rule as the SQL staging."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

import pandas as pd
import pytest

from flotsilica.config import SealedConfig
from flotsilica.split import BLOCKS, MODEL_BLOCKS, SplitError, block_of, check_split
from flotsilica.warehouse import rebuild_staging
from tests.fixtures.perturb import copy_of_store

HOUR = timedelta(hours=1)


def resplit(cfg, **changes):
    return dataclasses.replace(cfg, split=dataclasses.replace(cfg.split, **changes))


def test_every_block_boundary_has_its_purge_and_purge_hours_belong_to_no_block(cfg):
    s = cfg.split
    hours = pd.date_range(datetime(2017, 3, 8), datetime(2017, 9, 13, 23), freq="h")
    blocks = block_of(hours, cfg)
    assert list(blocks.index) == list(hours) and set(blocks) == set(BLOCKS)
    real = {"train": (s.train_first, s.train_last), "valid_v1": (s.v1_first, s.v1_last), "valid_v2": (s.v2_first, s.v2_last), "test": (s.test_first, s.test_last)}
    for name, (first, last) in real.items():
        inside = blocks[(hours >= first) & (hours <= last)]
        assert set(inside) == {name} and len(inside) == int((last - first) / HOUR) + 1, name
        assert set(blocks[blocks == name].index) == set(inside.index), f"{name} holds no hour outside its window"
    edges = (("train", "valid_v1", "purge_1"), ("valid_v1", "valid_v2", "purge_v"), ("valid_v2", "test", "purge_2"))
    for before, after, purge in edges:
        last, first = real[before][1], real[after][0]
        between = blocks[(hours > last) & (hours < first)]
        assert set(between) == {purge} and len(between) == s.purge_hours == 24, (before, after)
        assert not set(between) & set(MODEL_BLOCKS), "a purge hour belongs to no block of the model"
        assert blocks[last] == before and blocks[first] == after, "the hours on each side of the purge belong to their block"
    assert set(blocks[hours < s.train_first]) == {"outside"} and set(blocks[hours > s.test_last]) == {"outside"}
    assert set(blocks[blocks.isin(["purge_1", "purge_v", "purge_2"])].index).isdisjoint(blocks[blocks.isin(MODEL_BLOCKS)].index)
    assert blocks["2017-06-01 00:00"] == "purge_1" and blocks["2017-07-01 23:00"] == "purge_v" and blocks["2017-07-31 12:00"] == "purge_2"
    check_split(cfg)
    check_split(SealedConfig.of(cfg, "a" * 64))


def test_block_of_follows_the_order_and_the_index_it_is_given_and_changes_nothing(cfg):
    hours = pd.DatetimeIndex(["2017-08-01 00:00", "2017-03-10 01:00", "2017-06-02 00:00", "2017-06-01 12:00", "2017-03-10 01:00"])
    blocks = block_of(hours, cfg)
    assert blocks.tolist() == ["test", "train", "valid_v1", "purge_1", "train"] and list(blocks.index) == list(hours)
    assert block_of(pd.DatetimeIndex([]), cfg).empty and len(hours) == 5


def test_a_boundary_without_its_purge_is_refused_with_the_name_of_the_boundary(cfg):
    cases = [
        (dict(train_last=datetime(2017, 6, 1, 12)), r"borde train → valid_v1.*24 h"),
        (dict(v1_first=datetime(2017, 6, 1, 23)), r"borde train → valid_v1"),
        (dict(v1_last=datetime(2017, 7, 1, 10)), r"borde valid_v1 → valid_v2.*24 h"),
        (dict(v2_first=datetime(2017, 7, 1)), r"borde valid_v1 → valid_v2"),
        (dict(v2_last=datetime(2017, 8, 1)), r"borde valid_v2 → test"),
        (dict(test_first=datetime(2017, 7, 31)), r"borde valid_v2 → test"),
        (dict(purge_hours=48), r"borde train → valid_v1.*48 h"),
        (dict(train_first=datetime(2017, 6, 1)), r"\[split\] train.*posterior"),
        (dict(test_first=datetime(2017, 9, 10)), r"\[split\] test.*posterior"),
        (dict(train_first=datetime(2017, 3, 10)), r"\[split\] train_first.*first_hour"),
        (dict(test_last=datetime(2017, 9, 10)), r"\[split\] test_last.*last_hour"),
    ]
    for changes, match in cases:
        for view in (resplit(cfg, **changes), SealedConfig.of(resplit(cfg, **changes), "a" * 64)):
            with pytest.raises(SplitError, match=match):
                check_split(view)
    assert issubclass(SplitError, ValueError)
    one_hour = resplit(cfg, v1_first=datetime(2017, 6, 15), v1_last=datetime(2017, 6, 15))
    check_split(one_hour)                    # a block of one hour is a block
    assert block_of(pd.DatetimeIndex(["2017-06-15 00:00"]), one_hour).tolist() == ["valid_v1"]
    exact = resplit(cfg, v1_first=datetime(2017, 6, 2, 0), train_last=datetime(2017, 5, 31, 23))
    check_split(exact)       # 24 whole hours between: the purge is met exactly
    with pytest.raises(SplitError, match=r"borde train → valid_v1.*hay 23 h"):
        check_split(resplit(cfg, train_last=datetime(2017, 6, 1, 0)))
    with pytest.raises(SplitError, match=r"hay 0 h"):
        check_split(resplit(cfg, v1_first=datetime(2017, 5, 31, 23, 0), train_last=datetime(2017, 6, 1)))


def test_block_of_is_the_rule_of_the_sql_staging_for_the_split_it_is_given(cfg, small_store, quick_cfg):
    """The staging assigns blocks in SQL (U06) and ``block_of`` is the same rule in Python: every hour of the small fixture, under a split that
    puts a part of the fixture in each block (and one that moves every edge)."""
    first_view = resplit(quick_cfg, train_first=datetime(2017, 3, 10, 1), train_last=datetime(2017, 3, 11, 23), v1_first=datetime(2017, 3, 13),
                         v1_last=datetime(2017, 3, 13, 23), v2_first=datetime(2017, 3, 15), v2_last=datetime(2017, 3, 15, 23),
                         test_first=datetime(2017, 3, 29, 12), test_last=datetime(2017, 3, 30, 12))
    second_view = resplit(first_view, train_first=datetime(2017, 3, 10, 5), train_last=datetime(2017, 3, 12, 0), v2_first=datetime(2017, 3, 14, 7),
                          test_first=datetime(2017, 3, 29, 13))
    conn = copy_of_store(small_store)
    try:
        for view in (first_view, second_view):
            rebuild_staging(conn, datetime(2017, 4, 1), view)
            stored = pd.read_sql_query("SELECT hour, block FROM stg_hours ORDER BY hour", conn)
            python = block_of(pd.DatetimeIndex(pd.to_datetime(stored["hour"])), view)
            assert python.tolist() == stored["block"].tolist() and len(stored) > 150
            assert set(stored["block"]) == set(BLOCKS), "the fixture has hours in every block, the purges and the outside included"
    finally:
        conn.close()
