"""The artifact of the frozen model (U09; RF13, D39; M03, AC20; risk item 2): it is deserialized only when its bytes have the registered SHA-256.

``pickle`` runs what a file tells it to run, so the one thing these tests must be able to see is a load that happened. Their witness is a file whose
unpickling creates a folder inside the test's own ``tmp_path`` (``os.mkdir`` is what the bytes call): if the folder is there, the bytes were
deserialized. A control in the first test shows the witness works: the same bytes, with their own fingerprint registered, do leave it."""

from __future__ import annotations

import os
import pickle
from pathlib import Path

import numpy as np
import pytest

from flotsilica import registry
from flotsilica.registry import (
    MAX_ARTIFACT_BYTES,
    ArtifactError,
    ArtifactMismatchError,
    ArtifactMissingError,
    ModelBundle,
    artifact_sha256,
    load_artifact,
    save_artifact,
)
from tests.fixtures.tiny_model import random_block, tiny_bundle

BAD = "0" * 64


class MakesAFolder:
    """What an attacker's bytes would do on loading: call ``os.mkdir`` with a path of the test."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def __reduce__(self):
        return (os.mkdir, (str(self.folder),))


def evil_bytes(folder: Path) -> bytes:
    return pickle.dumps(MakesAFolder(folder), protocol=registry.PICKLE_PROTOCOL)


@pytest.fixture(scope="module")
def bundle(quick_cfg) -> ModelBundle:
    return tiny_bundle(quick_cfg)


@pytest.fixture
def saved(tmp_path, bundle) -> tuple[Path, str]:
    path = tmp_path / "models" / "v1.pkl"
    return path, save_artifact(bundle, path)


@pytest.fixture
def never_unpickles(monkeypatch):
    """Make any call of ``pickle.loads`` by the registry fail the test, so a refusal that came after a load cannot pass."""
    def refuse(*_args, **_kwargs):
        raise AssertionError("pickle.loads was called")

    monkeypatch.setattr(registry.pickle, "loads", refuse)


def test_artifact_with_other_hash_is_refused_before_loading(tmp_path, saved, never_unpickles, monkeypatch):
    path, good = saved
    mark = tmp_path / "ran"
    path.write_bytes(evil_bytes(mark))                       # the registered file was replaced by bytes that do something when loaded
    with pytest.raises(ArtifactMismatchError, match="M03") as caught:
        load_artifact(path, good)
    assert artifact_sha256(path.read_bytes()) in str(caught.value) and good in str(caught.value)
    assert not mark.exists()                                  # nothing of it ran
    assert path.read_bytes() == evil_bytes(mark)              # and the refusal did not touch the file (R6 decides what to do with it)

    # the witness works: with the fingerprint of those very bytes, the loader does unpickle them, and the folder appears (then it is not a bundle)
    monkeypatch.undo()
    with pytest.raises(TypeError, match="no es un ModelBundle"):
        load_artifact(path, artifact_sha256(path.read_bytes()))
    assert mark.is_dir()


@pytest.mark.parametrize("damage", ["missing", "truncated", "one_byte", "swapped", "empty"])
def test_a_missing_truncated_damaged_or_swapped_artifact_is_refused_with_no_load(tmp_path, saved, never_unpickles, quick_cfg, damage):
    path, good = saved
    data = path.read_bytes()
    if damage == "missing":
        path.unlink()
    elif damage == "truncated":
        path.write_bytes(data[: len(data) // 2])
    elif damage == "one_byte":
        path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    elif damage == "empty":
        path.write_bytes(b"")
    else:
        other = save_artifact(tiny_bundle(quick_cfg, seed=5), tmp_path / "other.pkl")        # a perfectly good artifact: of another launch
        assert other != good
        path.write_bytes((tmp_path / "other.pkl").read_bytes())
    expected = ArtifactMissingError if damage == "missing" else ArtifactMismatchError
    with pytest.raises(expected, match="M03") as caught:
        load_artifact(path, good)
    assert isinstance(caught.value, ArtifactError)
    assert path.exists() == (damage != "missing")


def test_the_size_is_checked_before_the_file_is_read(saved, monkeypatch):
    path, good = saved
    size = path.stat().st_size

    def not_read(*_args, **_kwargs):
        raise AssertionError("the file was read")

    monkeypatch.setattr(Path, "read_bytes", not_read)
    with pytest.raises(ArtifactMismatchError, match=f"pesa {size} bytes"):
        load_artifact(path, good, expected_bytes=size + 1)
    monkeypatch.setattr(registry, "MAX_ARTIFACT_BYTES", size - 1)
    with pytest.raises(ArtifactMismatchError, match="tope"):
        load_artifact(path, good)
    assert MAX_ARTIFACT_BYTES == 512 * 1024 * 1024


def test_a_fingerprint_that_is_not_a_sha256_is_refused_before_the_file_is_looked_at(tmp_path):
    for bad in ("", "abc", BAD[:-1], BAD.upper().replace("0", "A"), None, 7):
        with pytest.raises(ValueError, match="SHA-256"):
            load_artifact(tmp_path / "does-not-exist.pkl", bad)       # a ValueError, not a missing-file error: the fingerprint came first


def test_the_bytes_that_are_hashed_are_the_bytes_that_are_loaded(tmp_path, saved, bundle, monkeypatch):
    """The file is read once: if it is replaced after it was hashed, what is loaded is still what was hashed, never the new file."""
    path, good = saved
    mark = tmp_path / "ran"
    real = registry.artifact_sha256

    def hash_then_replace(data: bytes) -> str:
        digest = real(data)
        path.write_bytes(evil_bytes(mark))
        return digest

    monkeypatch.setattr(registry, "artifact_sha256", hash_then_replace)
    loaded = load_artifact(path, good)
    assert not mark.exists() and isinstance(loaded, ModelBundle) and loaded.version == bundle.version


def test_a_saved_artifact_loads_back_to_the_same_estimates(saved, bundle):
    path, digest = saved
    assert digest == artifact_sha256(path.read_bytes()) and len(digest) == 64
    loaded = load_artifact(path, digest, expected_bytes=path.stat().st_size)
    rows = random_block("valid_v2", 30, seed=3).X
    for before, after in zip(bundle.horizons, loaded.horizons, strict=True):
        assert (before.horizon, before.candidate, before.columns, before.half_width, before.b_star, before.b2_k) == (
            after.horizon, after.candidate, after.columns, after.half_width, after.b_star, after.b2_k)
        assert np.array_equal(before.estimator.predict(rows), after.estimator.predict(rows))
    assert loaded.b0_mean == bundle.b0_mean and loaded.version == bundle.version
    assert set(loaded.comparisons[0]) == set(bundle.comparisons[0])
    assert np.array_equal(loaded.comparisons[0]["best_lab_only"].predict(rows), bundle.comparisons[0]["best_lab_only"].predict(rows))


def test_saving_an_unserializable_bundle_writes_nothing_and_keeps_the_file_that_was_there(tmp_path, saved, bundle):
    path, digest = saved
    broken = ModelBundle(bundle.version, bundle.horizons, bundle.comparisons, bundle.b0_mean, {0: lambda x: x})
    with pytest.raises((pickle.PicklingError, AttributeError, TypeError)):
        save_artifact(broken, path)
    assert artifact_sha256(path.read_bytes()) == digest
    assert [p.name for p in path.parent.iterdir()] == ["v1.pkl"]         # no temporary left behind


def test_bytes_with_the_registered_fingerprint_that_are_not_a_bundle_are_a_type_error(tmp_path):
    path = tmp_path / "not_a_bundle.pkl"
    path.write_bytes(pickle.dumps({"a": 1}))
    with pytest.raises(TypeError, match="dict"):
        load_artifact(path, artifact_sha256(path.read_bytes()))
