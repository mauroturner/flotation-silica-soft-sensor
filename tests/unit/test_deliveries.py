"""Deliveries (U05; RF05, D21; AC05): the plan that comes from the configuration, the delivery of every row, publishing that never duplicates,
and the manifest that says which one is next."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from flotsilica import deliveries
from flotsilica.config import SealedConfig
from flotsilica.deliveries import (
    DeliverySpec,
    assert_covered,
    delivery_hours,
    delivery_plan,
    delivery_rows,
    mark_delivery,
    next_pending,
    publish,
    read_delivery,
    read_manifest,
)
from flotsilica.schema import LAB_COLUMNS, SOURCE_HOURS_SCHEMA, SOURCE_ROWS_SCHEMA

HOUR = timedelta(hours=1)


def with_deliveries(cfg, **changes):
    return dataclasses.replace(cfg, deliveries=dataclasses.replace(cfg.deliveries, **changes))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- the plan comes from the configuration (RF05, D21) ----------------------------------------------------------------------


def test_launch_forty_daily_deliveries_and_the_close_come_from_the_config(cfg):
    plan = delivery_plan(cfg)
    assert [s.kind for s in plan] == ["launch", *["daily"] * 40, "close"] and len({s.delivery_id for s in plan}) == 42
    launch, first, last, close = plan[0], plan[1], plan[-2], plan[-1]
    assert launch == DeliverySpec("L2017-07-31", "launch", datetime(2017, 3, 10, 1), datetime(2017, 7, 31, 23), datetime(2017, 8, 1, 0))
    assert first == DeliverySpec("D2017-08-01", "daily", datetime(2017, 8, 1, 0), datetime(2017, 8, 1, 23), datetime(2017, 8, 2, 0))
    assert last == DeliverySpec("D2017-09-09", "daily", datetime(2017, 9, 9, 0), datetime(2017, 9, 9, 23), datetime(2017, 9, 10, 0))
    # the close has no rows and lets the last analysis arrive: last hour + latency (D21)
    assert close == DeliverySpec("C2017-09-10", "close", None, None, datetime(2017, 9, 10, 1))
    assert [s.delivery_id for s in plan[1:4]] == ["D2017-08-01", "D2017-08-02", "D2017-08-03"]
    assert plan == delivery_plan(SealedConfig.of(cfg, "a" * 64)), "the plan is the same from the sealed view (the one the sealed calculations receive)"


def test_the_plan_follows_the_cadence_and_the_latency_of_the_config(cfg, quick_cfg):
    quick = delivery_plan(quick_cfg)
    assert [s.delivery_id for s in quick] == ["L2017-07-31", "D2017-08-01", "D2017-08-11", "D2017-08-21", "D2017-08-31", "C2017-09-10"]
    assert all(s.last_hour - s.first_hour == timedelta(hours=239) for s in quick[1:5]) and quick[-2].last_hour == datetime(2017, 9, 9, 23)
    later = delivery_plan(dataclasses.replace(cfg, lab=dataclasses.replace(cfg.lab, latency_hours=4)))
    assert later[-1].as_of == datetime(2017, 9, 10, 3) and later[:-1] == delivery_plan(cfg)[:-1]
    odd = delivery_plan(with_deliveries(cfg, cadence_hours=7))
    assert len(odd) == 2 + 138 and len({s.delivery_id for s in odd}) == len(odd), "an id never repeats, whatever the cadence"
    assert odd[-2].first_hour == odd[-2].last_hour == datetime(2017, 9, 9, 23) and odd[-2].delivery_id == "D2017-09-09T23"
    assert odd[1].delivery_id == "D2017-08-01T00" and odd[2].delivery_id == "D2017-08-01T07"


@pytest.mark.parametrize("cadence", [1, 5, 24, 100, 240, 960, 2000])
def test_every_period_starts_the_hour_after_the_previous_one_and_the_plan_covers_the_calendar(cfg, cadence):
    plan = delivery_plan(with_deliveries(cfg, cadence_hours=cadence))
    periods = [s for s in plan if s.kind != "close"]
    assert periods[0].first_hour == cfg.hours.first_hour and periods[-1].last_hour == cfg.hours.last_hour
    for before, after in zip(periods, periods[1:], strict=False):
        assert after.first_hour == before.last_hour + HOUR and after.as_of == after.last_hour + HOUR and before.as_of == before.last_hour + HOUR
    assert all(s.first_hour <= s.last_hour for s in periods) and plan[-1].kind == "close"
    assert sum((s.last_hour - s.first_hour) // HOUR + 1 for s in periods[1:]) == (cfg.hours.last_hour - cfg.deliveries.launch_last_hour) // HOUR


# --- every row belongs to the delivery of its hour (AC05) ---------------------------------------------------------------------


def test_every_row_and_every_hour_is_in_the_delivery_of_its_hour_and_in_no_other(canonical, quick_cfg):
    plan = delivery_plan(quick_cfg)
    rows, hours = canonical.rows, canonical.hours
    parts_rows = [delivery_rows(s, rows) for s in plan]
    parts_hours = [delivery_hours(s, hours) for s in plan]
    pd.testing.assert_frame_equal(pd.concat(parts_rows), rows)
    pd.testing.assert_frame_equal(pd.concat(parts_hours), hours)
    for spec, part in zip(plan[:-1], parts_rows[:-1], strict=True):
        assert part["hour"].between(spec.first_hour, spec.last_hour).all() and len(part)
    assert [len(p) for p in parts_rows][-1] == 0 and [len(p) for p in parts_hours][-1] == 0, "the close has no rows"
    assert list(parts_rows[-1].columns) == list(rows.columns) and list(parts_hours[-1].columns) == list(hours.columns)
    assert len(parts_rows[0]) == int((rows["hour"] <= quick_cfg.deliveries.launch_last_hour).sum())
    assert_covered(rows, plan)


def test_a_row_outside_every_period_is_refused_because_it_would_never_be_delivered(canonical, quick_cfg):
    plan = delivery_plan(quick_cfg)
    late = canonical.rows.copy()
    late.loc[late.index[-1], "hour"] = datetime(2017, 9, 10, 0)
    with pytest.raises(ValueError, match="1 filas.*fuera de todas las entregas"):
        assert_covered(late, plan)
    early = canonical.rows.copy()
    early.loc[early.index[0], "hour"] = datetime(2017, 3, 10, 0)
    with pytest.raises(ValueError, match="fuera de todas las entregas"):
        assert_covered(early, plan)


# --- publishing (idempotent, never replaces a loaded delivery) -----------------------------------------------------------------


def test_publish_writes_the_two_files_with_their_hashes_and_lists_them_once(canonical, quick_cfg, tmp_path):
    plan = delivery_plan(quick_cfg)
    entry = publish(plan[0], canonical.rows, canonical.hours, tmp_path)
    rows_path, hours_path = tmp_path / "L2017-07-31.rows.parquet", tmp_path / "L2017-07-31.hours.parquet"
    expected_rows, expected_hours = delivery_rows(plan[0], canonical.rows), delivery_hours(plan[0], canonical.hours)
    assert (entry.rows, entry.hours) == (len(expected_rows), len(expected_hours)) and entry.status == "published" and entry.run_key is None
    assert (entry.rows_file, entry.hours_file) == (rows_path.name, hours_path.name)
    assert entry.rows_sha256 == sha(rows_path.read_bytes()) and entry.hours_sha256 == sha(hours_path.read_bytes())
    assert entry.sha256 == sha(f"{entry.rows_sha256}\n{entry.hours_sha256}".encode())
    assert (entry.kind, entry.first_hour, entry.last_hour, entry.as_of) == ("launch", plan[0].first_hour, plan[0].last_hour, plan[0].as_of)
    assert read_manifest(tmp_path / "manifest.json") == [entry]
    document = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert document["version"] == 1 and list(document) == ["version", "entries"]
    assert document["entries"][0]["first_hour"] == "2017-03-10T01:00:00" and document["entries"][0]["as_of"] == "2017-08-01T00:00:00"
    # what is in the files is what the delivery selected, and it carries no laboratory value per row (V15)
    rows, hours = read_delivery(tmp_path, entry)
    pd.testing.assert_frame_equal(rows, expected_rows.reset_index(drop=True))
    pd.testing.assert_frame_equal(hours, expected_hours.reset_index(drop=True))
    assert pq.read_schema(rows_path).names == SOURCE_ROWS_SCHEMA.names and not set(pq.read_schema(rows_path).names) & set(LAB_COLUMNS)
    assert pq.read_schema(hours_path).names == SOURCE_HOURS_SCHEMA.names
    metadata = pq.read_schema(rows_path).metadata
    assert metadata[b"flotsilica.delivery_id"] == b"L2017-07-31" and b"CC0" in metadata[b"flotsilica.attribution"]
    assert metadata[b"flotsilica.period"] == b"2017-03-10T01:00:00/2017-07-31T23:00:00"


def test_publishing_again_changes_nothing_and_repairs_a_damaged_file(canonical, quick_cfg, tmp_path):
    spec = delivery_plan(quick_cfg)[1]
    first = publish(spec, canonical.rows, canonical.hours, tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    again = publish(spec, canonical.rows, canonical.hours, tmp_path)
    assert again == first and {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
    assert len(read_manifest(tmp_path / "manifest.json")) == 1
    (tmp_path / first.rows_file).write_bytes(b"damaged")
    (tmp_path / first.hours_file).unlink()
    assert publish(spec, canonical.rows, canonical.hours, tmp_path) == first
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_a_delivery_not_loaded_is_replaced_when_its_rows_change_and_a_loaded_one_never(canonical, quick_cfg, tmp_path):
    spec = delivery_plan(quick_cfg)[0]
    first = publish(spec, canonical.rows, canonical.hours, tmp_path)
    mark_delivery(tmp_path / "manifest.json", spec.delivery_id, "rejected")
    changed_rows, changed_hours = canonical.rows.iloc[1:], canonical.hours
    replaced = publish(spec, changed_rows, changed_hours, tmp_path)
    assert replaced.status == "published" and replaced.rows == first.rows - 1 and replaced.sha256 != first.sha256
    assert read_manifest(tmp_path / "manifest.json") == [replaced]
    mark_delivery(tmp_path / "manifest.json", spec.delivery_id, "loaded", "run-1")
    manifest_before = (tmp_path / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="ya está cargada en el almacén.*runbook R4"):
        publish(spec, canonical.rows, canonical.hours, tmp_path)
    assert (tmp_path / "manifest.json").read_bytes() == manifest_before


def test_the_close_is_published_with_empty_tables_that_keep_their_schema(canonical, quick_cfg, tmp_path):
    close = delivery_plan(quick_cfg)[-1]
    entry = publish(close, canonical.rows, canonical.hours, tmp_path)
    assert (entry.kind, entry.rows, entry.hours, entry.first_hour, entry.last_hour) == ("close", 0, 0, None, None)
    rows, hours = read_delivery(tmp_path, entry)
    assert rows.empty and hours.empty and rows.columns.tolist() == SOURCE_ROWS_SCHEMA.names and hours.columns.tolist() == SOURCE_HOURS_SCHEMA.names
    assert pq.read_schema(tmp_path / entry.rows_file).metadata[b"flotsilica.period"] == b"none"
    assert read_manifest(tmp_path / "manifest.json")[0].first_hour is None


def test_a_failed_manifest_write_lists_nothing_and_the_next_publish_completes_it(canonical, quick_cfg, tmp_path, monkeypatch):
    spec = delivery_plan(quick_cfg)[1]
    real = deliveries.write_atomic

    def only_the_manifest_fails(path, data):
        if Path(path).name == "manifest.json":
            raise OSError("disk full")
        return real(path, data)

    monkeypatch.setattr(deliveries, "write_atomic", only_the_manifest_fails)
    with pytest.raises(OSError, match="disk full"):
        publish(spec, canonical.rows, canonical.hours, tmp_path)
    assert read_manifest(tmp_path / "manifest.json") == []
    monkeypatch.setattr(deliveries, "write_atomic", real)
    entry = publish(spec, canonical.rows, canonical.hours, tmp_path)
    assert read_manifest(tmp_path / "manifest.json") == [entry]


# --- the manifest says which delivery is next (runbook R4) ------------------------------------------------------------------


def published_plan(canonical, cfg, folder: Path, count: int):
    plan = delivery_plan(cfg)
    for spec in plan[:count]:
        publish(spec, canonical.rows, canonical.hours, folder)
    return plan, folder / "manifest.json"


def test_the_next_pending_delivery_is_the_first_of_the_plan_that_is_not_loaded(canonical, quick_cfg, tmp_path):
    plan, manifest = published_plan(canonical, quick_cfg, tmp_path, 3)
    assert next_pending(tmp_path / "none.json", plan) == plan[0], "no manifest: the launch"
    assert next_pending(manifest, plan) == plan[0], "published is not loaded"
    mark_delivery(manifest, plan[0].delivery_id, "loaded", "run-1")
    assert next_pending(manifest, plan) == plan[1]
    mark_delivery(manifest, plan[1].delivery_id, "rejected")
    assert next_pending(manifest, plan) == plan[1], "a rejected delivery is repeated with the same delivery"
    mark_delivery(manifest, plan[1].delivery_id, "loaded", "run-2")
    mark_delivery(manifest, plan[2].delivery_id, "loaded", "run-3")
    assert next_pending(manifest, plan) == plan[3]


def test_a_complete_plan_has_no_pending_delivery(canonical, quick_cfg, tmp_path):
    plan, manifest = published_plan(canonical, quick_cfg, tmp_path, len(delivery_plan(quick_cfg)))
    for k, spec in enumerate(plan):
        mark_delivery(manifest, spec.delivery_id, "loaded", f"run-{k}")
    assert next_pending(manifest, plan) is None


def test_a_loaded_delivery_after_one_that_is_not_loaded_and_an_entry_off_the_plan_are_errors(canonical, quick_cfg, tmp_path):
    plan, manifest = published_plan(canonical, quick_cfg, tmp_path, 2)
    mark_delivery(manifest, plan[1].delivery_id, "loaded", "run-1")
    with pytest.raises(ValueError, match="D2017-08-01 está cargada pero la anterior, L2017-07-31, no lo está.*runbook R4"):
        next_pending(manifest, plan)
    other = delivery_plan(with_deliveries(quick_cfg, cadence_hours=120))
    with pytest.raises(ValueError, match="otro período.*runbook R4|no está en el plan"):
        next_pending(manifest, other)
    foreign = tmp_path / "foreign"
    publish(plan[1], canonical.rows, canonical.hours, foreign)
    with pytest.raises(ValueError, match="no está en el plan.*runbook R4"):
        next_pending(foreign / "manifest.json", plan[:1])


def test_a_loaded_delivery_stays_loaded_by_its_own_run(canonical, quick_cfg, tmp_path):
    plan, manifest = published_plan(canonical, quick_cfg, tmp_path, 1)
    mark_delivery(manifest, plan[0].delivery_id, "loaded", "run-1")
    mark_delivery(manifest, plan[0].delivery_id, "loaded", "run-1")
    entry = read_manifest(manifest)[0]
    assert (entry.status, entry.run_key) == ("loaded", "run-1")
    before = manifest.read_bytes()
    for status, run in (("rejected", None), ("published", None), ("loaded", "run-2")):
        with pytest.raises(ValueError, match="ya está cargada por la corrida 'run-1'.*runbook R4"):
            mark_delivery(manifest, plan[0].delivery_id, status, run)
    assert manifest.read_bytes() == before
    with pytest.raises(ValueError, match="no hay una entrega L2099"):
        mark_delivery(manifest, "L2099", "loaded", "run-1")
    with pytest.raises(ValueError, match="status: 'done'"):
        mark_delivery(manifest, plan[0].delivery_id, "done")


@pytest.mark.parametrize("damage", ["not json", "[]", '{"version": 2, "entries": []}', '{"version": 1}', '{"version": 1, "entries": [{"delivery_id": "x"}]}'])
def test_a_manifest_that_is_not_a_manifest_is_named_and_refused(tmp_path, damage):
    path = tmp_path / "manifest.json"
    path.write_text(damage, encoding="utf-8")
    with pytest.raises(ValueError, match="no es un manifiesto de entregas válido"):
        read_manifest(path)


def test_a_manifest_with_a_repeated_delivery_or_an_unknown_status_is_refused(canonical, quick_cfg, tmp_path):
    plan, manifest = published_plan(canonical, quick_cfg, tmp_path, 1)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    manifest.write_text(json.dumps({**document, "entries": document["entries"] * 2}), encoding="utf-8")
    with pytest.raises(ValueError, match="entregas repetidas"):
        read_manifest(manifest)
    document["entries"][0]["status"] = "done"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="status: 'done'"):
        read_manifest(manifest)
