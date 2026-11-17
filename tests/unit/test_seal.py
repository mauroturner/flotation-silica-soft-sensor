"""The seal and its fingerprint (U10; RF15, RF18, D18; M05; AC18): every key that can change a sealed value changes ``config_sha256``, the two parts of the
seal are written once, a repetition must reproduce the sealed values and another configuration is ``post_seal``, the file is never taken for an absent one,
and the sealed calculations never receive the whole configuration."""

from __future__ import annotations

import ast
import dataclasses
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from flotsilica import registry
from flotsilica.config import FINGERPRINT_KEYS, UNSEALED_KEYS
from flotsilica.registry import (
    TEST_KEYS,
    EvaluationRefusedError,
    SealError,
    SealMismatchError,
    canonical_sha256,
    check_test_evaluation,
    config_fingerprint,
    predictions_fingerprint,
    read_seal,
    seal_state,
    sealed_document,
    sealed_view,
    write_launch_seal,
    write_test_seal,
)
from tests.fixtures.seal_parts import SOURCE, evaluation_part, launch_part

SRC = Path(__file__).resolve().parents[2] / "src" / "flotsilica"


def altered(value):
    """Another value of the same type, for any leaf of the configuration."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, datetime):
        return value + timedelta(hours=1)
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 0.001
    if isinstance(value, str):
        return value + "x"
    if isinstance(value, Path):
        return value / "elsewhere"
    if isinstance(value, tuple):
        return (*value, max(value) + 1 if value and all(isinstance(v, int) for v in value) else "x")
    raise AssertionError(f"no change is defined for {type(value).__name__}")


def with_key(cfg, key: str, value):
    section, name = key.split(".")
    return dataclasses.replace(cfg, **{section: dataclasses.replace(getattr(cfg, section), **{name: value})})


def get_key(cfg, key: str):
    section, name = key.split(".")
    return getattr(getattr(cfg, section), name)


def leaves(document, prefix=""):
    if isinstance(document, dict):
        for key, value in document.items():
            yield from leaves(value, f"{prefix}.{key}" if prefix else key)
    else:
        yield prefix


def test_changing_any_fingerprinted_key_changes_config_sha256(cfg):
    base = config_fingerprint(sealed_view(cfg, SOURCE))
    assert base == config_fingerprint(sealed_view(cfg, SOURCE)) and len(base) == 64
    unchanged = []
    for key in FINGERPRINT_KEYS:
        other = with_key(cfg, key, altered(get_key(cfg, key)))
        if config_fingerprint(sealed_view(other, SOURCE)) == base:
            unchanged.append(key)
    assert unchanged == [], f"these keys can change a sealed value and do not change the fingerprint: {unchanged}"
    assert config_fingerprint(sealed_view(cfg, "cd" * 32)) != base              # the hash of the source that was read is part of it too


def test_a_key_that_cannot_change_a_sealed_value_does_not_change_the_fingerprint(cfg):
    base = config_fingerprint(sealed_view(cfg, SOURCE))
    for key in UNSEALED_KEYS:
        other = with_key(cfg, key, altered(get_key(cfg, key)))
        assert config_fingerprint(sealed_view(other, SOURCE)) == base, key


def test_the_sealed_document_has_exactly_the_fingerprinted_keys_and_the_source_hash(cfg):
    names = set(leaves(sealed_document(sealed_view(cfg, SOURCE))))
    assert names == set(FINGERPRINT_KEYS) | {"source_sha256"}


def test_sealed_calculations_receive_only_the_sealed_view():
    sealed = ("hours", "split", "features", "baselines", "model", "intervals", "scoring", "evaluation", "variants", "sensitivity", "launch")
    for name in sealed:
        path = SRC / f"{name}.py"
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        named = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
            a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        assert "PipelineConfig" not in named, f"{name}.py names PipelineConfig: a sealed calculation takes the SealedConfig"


# --- the parts of the seal -----------------------------------------------------------------------------------------------------------------


@pytest.fixture
def other_cfg(cfg):
    return with_key(cfg, "evaluation.bootstrap_resamples", cfg.evaluation.bootstrap_resamples + 1)


def test_the_launch_part_is_written_once_and_a_repetition_with_the_same_values_changes_nothing(cfg, tmp_path):
    seal = tmp_path / "reports" / "model_seal.json"
    assert seal_state(seal, config_fingerprint(sealed_view(cfg, SOURCE))) == "none" and read_seal(seal) is None
    first = launch_part(cfg)
    assert write_launch_seal(seal, first) == "written"
    bytes_then = seal.read_bytes()
    assert json.loads(bytes_then) == {"version": 1, "launch": first}
    assert seal_state(seal, first["config_sha256"]) == "match"
    # a repetition: another run, its date, the bytes of the pickle and a rounding below 6 decimals are not differences
    again = launch_part(cfg, run_key="r7", as_of="2017-08-01 00:00:05", artifact_sha256="33" * 32,
                        horizons=[{**h, "half_width": h["half_width"] + 4e-7} for h in first["horizons"]])
    assert write_launch_seal(seal, again) == "unchanged" and seal.read_bytes() == bytes_then
    assert not [p for p in seal.parent.iterdir() if p.name != seal.name]               # no temporary file is left next to it
    if os.name == "posix":
        assert seal.stat().st_mode & 0o777 == 0o600


def test_the_same_configuration_with_another_sealed_value_is_a_mismatch_that_names_it(cfg, tmp_path):
    seal = tmp_path / "model_seal.json"
    write_launch_seal(seal, launch_part(cfg))
    then = seal.read_bytes()
    first = launch_part(cfg)["horizons"]
    for name, changes in {
        "horizons.1.half_width": {"horizons": [first[0], {**first[1], "half_width": first[1]["half_width"] + 1e-5}, first[2]]},
        "horizons.2.feature_set": {"horizons": [*first[:2], {**first[2], "feature_set": "fL"}]},
        "horizons.0.b_star": {"horizons": [{**first[0], "b_star": "b2_rolling"}, *first[1:]]},
        "valid_predictions_sha256": {"valid_predictions_sha256": "44" * 32},
        "gate.passing": {"gate": {"computed": False, "model": None, "passing": ["amina_flow"]}},
        "model_version": {"model_version": "v2"},
    }.items():
        with pytest.raises(SealMismatchError, match="M05") as caught:
            write_launch_seal(seal, launch_part(cfg, **changes))
        assert name in str(caught.value), name
        assert seal.read_bytes() == then


def test_another_configuration_is_post_seal_and_the_seal_stays(cfg, other_cfg, tmp_path):
    seal = tmp_path / "model_seal.json"
    write_launch_seal(seal, launch_part(cfg))
    then = seal.read_bytes()
    other = launch_part(other_cfg, horizons=[])
    assert write_launch_seal(seal, other) == "post_seal" and seal.read_bytes() == then
    assert seal_state(seal, other["config_sha256"]) == "post_seal"
    assert write_test_seal(seal, evaluation_part(other_cfg)) == "post_seal" and seal.read_bytes() == then


def test_the_launch_part_is_created_exclusively_whatever_was_read_before(cfg, tmp_path, monkeypatch):
    """Another writer could create the seal between the read that found none and the creation: the creation must not replace it."""
    seal = tmp_path / "model_seal.json"
    write_launch_seal(seal, launch_part(cfg))
    then = seal.read_bytes()
    real, seen = registry.read_seal, []

    def blind_once(path):
        seen.append(path)
        return None if len(seen) == 1 else real(path)

    monkeypatch.setattr(registry, "read_seal", blind_once)
    with pytest.raises(SealMismatchError, match="valid_predictions_sha256"):       # the creation found the file and went on to compare: it did not replace it
        write_launch_seal(seal, launch_part(cfg, valid_predictions_sha256="55" * 32))
    assert seal.read_bytes() == then and len(seen) >= 2


def test_the_test_part_is_added_once_and_the_launch_part_stays_as_it_was(cfg, tmp_path):
    seal = tmp_path / "model_seal.json"
    launch = launch_part(cfg)
    write_launch_seal(seal, launch)
    assert write_test_seal(seal, evaluation_part(cfg)) == "written"
    document = read_seal(seal)
    assert document["launch"] == launch and document["test"] == evaluation_part(cfg) and set(document["test"]) == set(TEST_KEYS)
    then = seal.read_bytes()
    assert write_test_seal(seal, evaluation_part(cfg, run_key="r10", as_of="2017-09-10 01:00:09")) == "unchanged" and seal.read_bytes() == then
    with pytest.raises(SealMismatchError, match="criteria.C02.value"):
        write_test_seal(seal, evaluation_part(cfg, criteria=[{"id": "C01", "value": 1.5, "passed": False}, {"id": "C02", "value": 9.0, "passed": False},
                                                       {"id": "C03", "value": 3.5, "passed": False}]))
    assert seal.read_bytes() == then
    assert write_launch_seal(seal, launch) == "unchanged" and seal.read_bytes() == then


def test_the_test_part_needs_the_launch_part_first(cfg, tmp_path):
    with pytest.raises(SealError, match="no hay sello"):
        write_test_seal(tmp_path / "model_seal.json", evaluation_part(cfg))
    assert not (tmp_path / "model_seal.json").exists()


def test_a_part_with_other_keys_or_a_value_that_is_not_json_is_refused_before_anything_is_written(cfg, tmp_path):
    seal = tmp_path / "model_seal.json"
    part = launch_part(cfg)
    for broken in ({k: v for k, v in part.items() if k != "gate"}, {**part, "extra": 1}, {**part, "config_sha256": "abc"},
                   {**part, "horizons": [{"horizon": 0, "half_width": float("nan")}]}, {**part, "gate": {"model": object()}},
                   {**part, "sealed_config": {**part["sealed_config"], "lab": {"latency_hours": 3}}}):
        with pytest.raises(SealError):
            write_launch_seal(seal, broken)
    assert not seal.exists()
    write_launch_seal(seal, part)
    for broken in ({k: v for k, v in evaluation_part(cfg).items() if k != "weekly"}, {**evaluation_part(cfg), "metrics": {"h0": float("inf")}}):
        with pytest.raises(SealError):
            write_test_seal(seal, broken)
    assert "test" not in read_seal(seal)


def test_a_file_that_is_not_a_seal_is_never_taken_for_an_absent_one(cfg, tmp_path):
    seal = tmp_path / "model_seal.json"
    good = launch_part(cfg)
    for text in ("", "not json", "[]", json.dumps({"version": 2, "launch": good}), json.dumps({"version": 1}),
                 json.dumps({"version": 1, "launch": {**good, "extra": 1}}), json.dumps({"version": 1, "launch": {**good, "config_sha256": "zz"}}),
                 json.dumps({"version": 1, "launch": good, "test": {"run_key": "r"}}), json.dumps({"version": 1, "launch": good, "other": 1})):
        seal.write_text(text, encoding="utf-8")
        with pytest.raises(SealError):
            read_seal(seal)
        with pytest.raises(SealError):
            write_launch_seal(seal, good)
        with pytest.raises(SealError):
            seal_state(seal, good["config_sha256"])
        assert seal.read_text(encoding="utf-8") == text


def test_the_test_is_evaluated_only_under_the_sealed_configuration_until_it_is_sealed(cfg, other_cfg, tmp_path):
    seal = tmp_path / "model_seal.json"
    view, other = sealed_view(cfg, SOURCE), sealed_view(other_cfg, SOURCE)
    with pytest.raises(EvaluationRefusedError, match="no hay sello"):
        check_test_evaluation(seal, view)
    write_launch_seal(seal, launch_part(cfg))
    assert check_test_evaluation(seal, view) == "first"
    with pytest.raises(EvaluationRefusedError, match=r"evaluation\.bootstrap_resamples") as caught:
        check_test_evaluation(seal, other)
    assert "R7" in str(caught.value) or "sello" in str(caught.value)
    write_test_seal(seal, evaluation_part(cfg))
    assert check_test_evaluation(seal, view) == "repeat" and check_test_evaluation(seal, other) == "post_seal"
    assert not [p for p in tmp_path.iterdir() if p.name != seal.name]


def test_the_fingerprint_of_the_predictions_ignores_the_order_and_what_is_below_six_decimals():
    base = [("2017-06-02 00:00:00", 0, 2.5), ("2017-06-02 00:00:00", 1, 2.6), ("2017-06-02 01:00:00", 0, 2.7), ("2017-06-02 00:00:00", 10, 2.8)]
    digest = predictions_fingerprint(base)
    assert digest == predictions_fingerprint(list(reversed(base))) and len(digest) == 64
    assert digest == predictions_fingerprint([(h, k, v + 4e-8) for h, k, v in base])
    assert digest != predictions_fingerprint([(h, k, v + 2e-6) for h, k, v in base])
    assert digest != predictions_fingerprint([*base[:3], ("2017-06-02 00:00:00", 10, 2.9)])
    assert predictions_fingerprint([("2017-06-02 00:00:00", 2, 1.0), ("2017-06-02 00:00:00", 10, 1.0)]) == predictions_fingerprint(
        [("2017-06-02 00:00:00", 10, 1.0), ("2017-06-02 00:00:00", 2, 1.0)])
    assert canonical_sha256({"a": 1, "b": [2]}) == canonical_sha256({"b": [2], "a": 1})
