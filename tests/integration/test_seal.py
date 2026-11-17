"""The seal of a real launch (U10; RF15, RF18, D18; M05; AC18, AC20): the launch of the small history writes its part once; a repetition with the sealed
configuration reproduces it; another configuration is ``post_seal`` and leaves the seal and the artifact alone; and the test is never evaluated under another
configuration while the seal has no test part, with nothing written."""

from __future__ import annotations

import dataclasses
import json
import sqlite3

import pytest

from flotsilica.launch import fit_model
from flotsilica.registry import (
    ArtifactError,
    EvaluationRefusedError,
    SealMismatchError,
    check_test_evaluation,
    config_fingerprint,
    read_registry,
    read_seal,
    sealed_view,
    write_test_seal,
)
from flotsilica.warehouse import connect
from tests.fixtures.history import SOURCE_SHA256, copy_history
from tests.fixtures.seal_parts import evaluation_part


def rows_of(db, sql, *args):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, args).fetchone()[0]
    finally:
        conn.close()


def as_other(history, **changes):
    """The sealed view of the history's configuration with a key of ``[evaluation]`` and, if given, of ``[model]`` changed."""
    view = history.view
    evaluation = dataclasses.replace(view.evaluation, bootstrap_resamples=view.evaluation.bootstrap_resamples + 1)
    return sealed_view(dataclasses.replace(view, evaluation=evaluation, model=dataclasses.replace(view.model, **changes)), SOURCE_SHA256)


def test_the_launch_of_the_history_wrote_its_part_with_what_the_model_and_the_registry_say(small_history):
    h = small_history
    seal = read_seal(h.paths.seal)
    launch = seal["launch"]
    assert h.fits[0]["seal"] == "written" and [f["mode"] for f in h.fits] == ["launch", "verify", "verify", "verify"]
    assert [e["test"] for e in h.evals] == ["pending", "pending", "pending", "written"] and seal["test"]["run_key"] == "r4"
    assert launch["config_sha256"] == config_fingerprint(h.sealed) and launch["source_sha256"] == SOURCE_SHA256 and launch["run_key"] == "r1"
    assert [x["horizon"] for x in launch["horizons"]] == [0, 1, 2] and all(x["half_width"] > 0 and x["b_star"] in ("b1_persistence", "b2_rolling") for x in launch["horizons"])
    conn = sqlite3.connect(h.paths.db)
    try:
        row = read_registry(conn, "v1")
    finally:
        conn.close()
    assert row["artifact_sha256"] == launch["artifact_sha256"] == h.fits[0]["artifact_sha256"] and row["config_sha256"] == launch["config_sha256"]
    assert row["valid_predictions_sha256"] == launch["valid_predictions_sha256"] and row["artifact_path"] == "v1.pkl"
    assert set(json.loads(row["selection_json"])) == {"0", "1", "2"} and len(json.loads(row["selection_json"])["0"]) == 5
    assert [f["seal"] for f in h.fits[1:]] == ["match"] * 3


def test_a_repetition_of_the_launch_with_the_sealed_configuration_reproduces_the_sealed_values(small_launched, tmp_path):
    h = copy_history(small_launched, tmp_path / "again")
    then = h.paths.seal.read_bytes()
    conn = connect(h.paths.db)
    try:
        again = fit_model(conn, dataclasses.replace(h.runs[0], run_key="r1-again"), h.sealed, models_dir=h.paths.models, seal_path=h.paths.seal)
    finally:
        conn.close()
    assert again["seal"] == "unchanged" and h.paths.seal.read_bytes() == then


def test_another_config_after_the_seal_is_post_seal_and_the_seal_stays(small_launched, tmp_path):
    h = copy_history(small_launched, tmp_path / "other")
    then, artifact = h.paths.seal.read_bytes(), (h.paths.models / "v1.pkl").read_bytes()
    other = as_other(h, model_version="v2", random_state=1)
    assert config_fingerprint(other) != config_fingerprint(h.sealed)
    conn = connect(h.paths.db)
    try:
        result = fit_model(conn, dataclasses.replace(h.runs[0], run_key="r1-other"), other, models_dir=h.paths.models, seal_path=h.paths.seal)
        assert read_registry(conn, "v2")["config_sha256"] == config_fingerprint(other) and read_registry(conn, "v1")["config_sha256"] == config_fingerprint(h.sealed)
    finally:
        conn.close()
    assert result["seal"] == "post_seal" and h.paths.seal.read_bytes() == then
    # the tables of the other launch are post-seal rows next to the sealed ones, which are as they were
    stored = {state: rows_of(h.paths.db, "SELECT COUNT(*) FROM eval_selection WHERE seal_state = ?", state) for state in ("sealed", "post_seal")}
    assert stored == {"sealed": 15, "post_seal": 15} and set(result["stored"]) == {"selection", "baselines", "validation", "leakage", "sensitivity", "curves"} and all(result["stored"].values())
    assert (h.paths.models / "v1.pkl").read_bytes() == artifact and (h.paths.models / "v2.pkl").exists()
    # the same version with another model never takes the file of the registered one
    conn = connect(h.paths.db)
    try:
        with pytest.raises(ArtifactError, match="otra huella"):
            fit_model(conn, dataclasses.replace(h.runs[0], run_key="r1-clash"), as_other(h, random_state=1), models_dir=h.paths.models, seal_path=h.paths.seal)
    finally:
        conn.close()
    assert (h.paths.models / "v1.pkl").read_bytes() == artifact


def test_evaluating_the_test_under_another_config_before_the_test_seal_is_refused(small_launched, tmp_path):
    h = copy_history(small_launched, tmp_path / "refuse")
    other = as_other(h)
    before = sorted(p.relative_to(tmp_path).as_posix() for p in (tmp_path / "refuse").rglob("*"))
    seal_bytes = h.paths.seal.read_bytes()
    with pytest.raises(EvaluationRefusedError, match=r"evaluation\.bootstrap_resamples") as caught:
        check_test_evaluation(h.paths.seal, other)
    assert "sello" in str(caught.value)
    assert h.paths.seal.read_bytes() == seal_bytes and sorted(p.relative_to(tmp_path).as_posix() for p in (tmp_path / "refuse").rglob("*")) == before   # nothing was written
    assert check_test_evaluation(h.paths.seal, h.sealed) == "first"                       # with the sealed configuration it is the evaluation that is sealed
    # once the seal has its test part, another configuration is computed apart, never refused and never written over it
    assert write_test_seal(h.paths.seal, evaluation_part(h.view, config_sha256=config_fingerprint(h.sealed))) == "written"
    sealed_now = h.paths.seal.read_bytes()
    assert check_test_evaluation(h.paths.seal, other) == "post_seal" and check_test_evaluation(h.paths.seal, h.sealed) == "repeat"
    assert write_test_seal(h.paths.seal, evaluation_part(h.view, config_sha256=config_fingerprint(other))) == "post_seal" and h.paths.seal.read_bytes() == sealed_now
    with pytest.raises(SealMismatchError):
        write_test_seal(h.paths.seal, evaluation_part(h.view, config_sha256=config_fingerprint(h.sealed), metrics={"h0": {"mae": 9.0}}))
