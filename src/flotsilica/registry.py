"""The artifact of the frozen model, deserialized only when its bytes still have the registered SHA-256 (M03, RF13, D39), and the seal of the launch and
of the test (RF15, RF18, D18; M05; plan, section 15). Adapted from project 04's ``registry.py`` (its D40, D19 and D89).

``pickle`` runs code when it loads, so a file that someone replaced must never reach it. ``load_artifact`` looks at the size of the file first (a
file over ``MAX_ARTIFACT_BYTES``, or over the size the caller registered, is not even read), reads the bytes **once**, computes their SHA-256, compares it
with the registered one and only then hands *those same bytes* to ``pickle.loads``: there is no window between checking and loading, and nothing is
unpickled from a file whose fingerprint is not the registered one, whether it is another file, a truncated one, a damaged one or none. The
fingerprint protects against a file that was replaced or damaged; it does not make ``pickle`` safe against someone who can rewrite the file and the
registry together (D39).

The seal (``reports/model_seal.json``) has two parts, each written **once**: the launch (the configuration's ``config_sha256``, the whole sealed view,
the chosen candidates, half-widths and B* of each horizon, the gate and the fingerprint of the validation predictions) and the test (the criteria and
the numbers of the one evaluation of the test). ``config_sha256`` is the SHA-256 of the canonical JSON of the whole ``SealedConfig``: every key that can
change a sealed value is in it (D18). A repetition with the sealed configuration must reproduce the sealed values rounded to 6 decimals
(``SealMismatchError``); another configuration is ``post_seal`` (M05) and the seal stays as it is; and the test is never evaluated under another
configuration while the seal has no test part (``EvaluationRefusedError``).
"""

from __future__ import annotations

import dataclasses
import errno
import hashlib
import hmac
import json
import logging
import math
import os
import pickle
import re
import sqlite3
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from flotsilica.config import SealedConfig
from flotsilica.files import write_atomic
from flotsilica.model import Candidate, FittedCandidate, LaunchFit

logger = logging.getLogger(__name__)

PICKLE_PROTOCOL = 5
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024       # twelve forests of 300 trees are about 150 MB; a file over this is not the model of this project
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ArtifactError(RuntimeError):
    """The artifact cannot be loaded (M03); nothing of it was deserialized."""


class ArtifactMismatchError(ArtifactError):
    """M03: the artifact does not have the registered SHA-256 (or the registered size); it was not deserialized (docs/runbook.md, R6)."""


class ArtifactMissingError(ArtifactError):
    """M03: there is no artifact file at the registered path (docs/runbook.md, R6)."""


@dataclass(frozen=True, eq=False)
class HorizonModel:
    """What the launch freezes for a horizon: the selected candidate and its refit estimator, the columns of its set, the half-width of the 80 %
    range, B* (``b1_persistence`` or ``b2_rolling``) and the ``k`` of B2."""

    horizon: int
    candidate: Candidate
    estimator: FittedCandidate
    columns: tuple[str, ...]
    half_width: float
    b_star: str
    b2_k: int


@dataclass(frozen=True, eq=False)
class ModelBundle:
    """What the launch freezes (plan, section 15): the horizons' models, the comparison models of C07 and C08 by horizon (``comparisons``: horizon, then
    ``best_sensors_only``, ``best_lab_only`` and ``best_with_sensors``), the mean of B0 and the ridge of B3 by horizon."""

    version: str
    horizons: tuple[HorizonModel, ...]
    comparisons: dict[int, dict[str, FittedCandidate]]
    b0_mean: float
    b3: dict[int, Any]


def bundle_of(launch: LaunchFit, view: Any) -> ModelBundle:
    """The bundle of a launch's learning (``model.fit_launch``): one ``HorizonModel`` for each horizon of ``[evaluation] horizons``, in order."""
    horizons = tuple(
        HorizonModel(h, fit.chosen, fit.model, fit.model.columns, fit.calibration.half_width, launch.baselines.b_star[h], launch.baselines.b2_k[h])
        for h, fit in launch.horizons.items()
    )
    return ModelBundle(view.model.model_version, horizons, {h: dict(fit.comparisons) for h, fit in launch.horizons.items()}, launch.baselines.b0_mean,
                       dict(launch.baselines.b3))


def artifact_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bundle_bytes(bundle: ModelBundle) -> bytes:
    """The bytes ``save_artifact`` writes for `bundle`: the standard library's ``pickle``, protocol 5."""
    return pickle.dumps(bundle, protocol=PICKLE_PROTOCOL)


def save_artifact(bundle: ModelBundle, path: Path) -> str:
    """Serialize `bundle` with the standard library's ``pickle`` (protocol 5), write it atomically to `path` and return the SHA-256 of the bytes
    written. If it cannot be serialized, nothing is written and a file already at `path` is left as it was."""
    data = bundle_bytes(bundle)
    write_atomic(Path(path), data)
    digest = artifact_sha256(data)
    logger.info("artifact %s written: sha256 %s, %d bytes", Path(path).name, digest, len(data))
    return digest


def load_artifact(path: Path, expected_sha256: str, expected_bytes: int | None = None) -> ModelBundle:
    """The bundle saved at `path`, deserialized only if its bytes have the SHA-256 `expected_sha256` (M03) and, if given, the size `expected_bytes`.

    A fingerprint that is not 64 lower-case hexadecimal digits is a ``ValueError`` and the file is not even looked at. A file that is not there is an
    ``ArtifactMissingError``; one over ``MAX_ARTIFACT_BYTES`` or not of the registered size is not read. The file is read once; the fingerprint is
    computed over those bytes and, if equal, the same bytes are deserialized. Otherwise ``ArtifactMismatchError`` is raised before any byte reaches
    ``pickle``. Bytes with the registered fingerprint that are not a ``ModelBundle`` are a ``TypeError``."""
    if not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256):
        raise ValueError("la huella registrada del artefacto debe ser un SHA-256 de 64 dígitos hexadecimales en minúscula")
    path = Path(path)
    name = path.name
    try:
        size = path.stat().st_size
    except OSError as error:
        raise ArtifactMissingError(f"M03: no hay un artefacto legible en {name} ({error.__class__.__name__}); no se deserializó nada (docs/runbook.md, R6)") from error
    if size > MAX_ARTIFACT_BYTES or (expected_bytes is not None and size != expected_bytes):
        wanted = f"el registrado de {expected_bytes} bytes" if expected_bytes is not None and size <= MAX_ARTIFACT_BYTES else f"el tope de {MAX_ARTIFACT_BYTES} bytes"
        logger.error("M03: artifact %s has %d bytes, which is not %s; not read", name, size, wanted)
        raise ArtifactMismatchError(f"M03: el artefacto {name} pesa {size} bytes y no es {wanted}: no se leyó ni se deserializó (docs/runbook.md, R6)")
    data = path.read_bytes()
    actual = artifact_sha256(data)
    if not hmac.compare_digest(actual, expected_sha256):
        logger.error("M03: artifact %s has sha256 %s and %s was registered; not loaded", name, actual, expected_sha256)
        raise ArtifactMismatchError(
            f"M03: el artefacto {name} tiene la huella {actual} y la registrada es {expected_sha256}: no se deserializó. "
            "Se restaura el archivo registrado o se vuelve a entrenar desde el lanzamiento (docs/runbook.md, R6)"
        )
    bundle = pickle.loads(data)  # noqa: S301 - only bytes whose SHA-256 is the registered one (D39)
    if not isinstance(bundle, ModelBundle):
        raise TypeError(f"M03: el artefacto {name} tiene la huella registrada pero no es un ModelBundle, es {type(bundle).__name__}")
    return bundle


# --- the registry of the models (insert-only, 003_model.sql) ---------------------------------------------------------------------------


def register_model(conn: sqlite3.Connection, *, model_version: str, trained_as_of: str, artifact_name: str, artifact_sha256: str, config_sha256: str,
                   models: Any, selection: Any, valid_predictions_sha256: str) -> None:
    """Add the model to ``model_registry`` (in the caller's transaction, or its own if there is none). A version is registered once: the table refuses an
    update, a delete and a second insert of the same version. `artifact_name` is the file name inside ``[paths] models_dir``, never a path of this machine."""
    for what, value in (("artifact_sha256", artifact_sha256), ("config_sha256", config_sha256), ("valid_predictions_sha256", valid_predictions_sha256)):
        if not _is_sha256(value):
            raise ValueError(f"{what}: se esperaban 64 dígitos hexadecimales en minúscula")
    if Path(artifact_name).name != artifact_name:
        raise ValueError("artifact_name: un nombre de archivo, no una ruta")
    conn.execute(
        "INSERT INTO model_registry (model_version, trained_as_of, artifact_path, artifact_sha256, config_sha256, models_json, selection_json, "
        "valid_predictions_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (model_version, trained_as_of, artifact_name, artifact_sha256, config_sha256, json.dumps(_rounded(models), sort_keys=True),
         json.dumps(_rounded(selection), sort_keys=True), valid_predictions_sha256),
    )


def read_registry(conn: sqlite3.Connection, model_version: str) -> dict[str, Any] | None:
    """The row of ``model_registry`` of a version as a dict, or None."""
    cursor = conn.execute("SELECT * FROM model_registry WHERE model_version = ?", (model_version,))
    row = cursor.fetchone()
    return None if row is None else dict(zip([c[0] for c in cursor.description], row, strict=True))


def load_registered_bundle(conn: sqlite3.Connection, models_dir: Path, model_version: str) -> ModelBundle:
    """The bundle of a registered version, loaded through ``load_artifact`` with the SHA-256 of the registry (M03): the one way a run gets the model."""
    row = read_registry(conn, model_version)
    if row is None:
        raise ArtifactMissingError(f"M03: la versión {model_version} del modelo no está registrada; el lanzamiento no la ajustó (docs/runbook.md, R6)")
    return load_artifact(Path(models_dir) / row["artifact_path"], row["artifact_sha256"])


# --- the seal and its fingerprint (D18, M05) ------------------------------------------------------------------------------------------

SEAL_VERSION = 1
SEAL_DECIMALS = 6                     # a repetition must reproduce the sealed values rounded to this many decimals
SEAL_MODE = 0o600                     # owner only, where the mode is the access control (project 03, D64 and D78)
LAUNCH_KEYS = (
    "run_key", "as_of", "source_sha256", "config_sha256", "sealed_config", "model_version", "artifact_sha256", "horizons", "gate",
    "valid_predictions_sha256",
)
TEST_KEYS = ("run_key", "as_of", "config_sha256", "criteria", "metrics", "weekly", "variants", "sensitivity_test")
# what a repetition may change: the run that computed the values, its date and the bytes of the pickle (the values do not depend on them; M03 checks the
# artifact against the registry, and the predictions it makes are in valid_predictions_sha256)
_NOT_COMPARED = ("run_key", "as_of", "artifact_sha256")
_IDENTIFIERS = ("id", "horizon", "scope", "variant", "week", "sensor", "method", "metric")   # what names an entry of a list of objects
# what the system answers to a hard link on a file system that has none (FAT and exFAT, some network shares); any other error is a real one
_NO_HARD_LINKS = frozenset({errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV, errno.ENOSYS})
_WINDOWS_NO_HARD_LINKS = frozenset({1, 50})      # ERROR_INVALID_FUNCTION and ERROR_NOT_SUPPORTED
_ABSENT = object()


class SealError(RuntimeError):
    """The seal file cannot be read as a seal, or what is asked of it is not allowed."""


class SealMismatchError(SealError):
    """A repetition with the sealed configuration did not reproduce the sealed values (docs/runbook.md, R7)."""


class EvaluationRefusedError(SealError):
    """The test cannot be evaluated: another configuration than the sealed one while the seal has no test part (D18). The pipeline turns it into a
    refused run (exit code 2); nothing was written."""


def sealed_view(cfg: Any, source_sha256: str) -> SealedConfig:
    """The sealed view of the configuration `cfg` for a source file that hashed to `source_sha256`: what the sealed calculations receive."""
    return SealedConfig.of(cfg, source_sha256)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise SealError(f"un valor de la configuración sellada no es JSON: {type(value).__name__}")


def sealed_document(view: SealedConfig) -> dict[str, Any]:
    """The whole sealed view as JSON: one object per section with its keys (instants as ISO text, lists for tuples) and ``source_sha256``."""
    return _json_ready(dataclasses.asdict(view))


def canonical_sha256(document: Any) -> str:
    """SHA-256 of the canonical JSON of `document` (sorted keys, fixed separators, ASCII)."""
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def config_fingerprint(view: SealedConfig) -> str:
    """``config_sha256``: the SHA-256 of the canonical JSON of the whole sealed view, so every key that can change a sealed value changes it."""
    return canonical_sha256(sealed_document(view))


def _flat(document: Any, prefix: str = "") -> dict[str, Any]:
    """``{dotted path: value}`` of the leaves of nested objects. A list of objects is entered entry by entry, each named by its identifiers
    (``criteria.C01.value``, ``horizons.0.half_width``) or by its position; any other list is one leaf."""
    if isinstance(document, Mapping):
        out: dict[str, Any] = {}
        for key, value in document.items():
            out.update(_flat(value, f"{prefix}.{key}" if prefix else str(key)))
        return out if out else {prefix: {}}
    if isinstance(document, (list, tuple)) and document and all(isinstance(item, Mapping) for item in document):
        out = {}
        for position, item in enumerate(document):
            name = "|".join(str(item[k]) for k in _IDENTIFIERS if k in item) or str(position)
            out.update({f"{prefix}.{name}.{key}": value for key, value in _flat(item).items()})
        return out
    return {prefix: document}


def differing_keys(sealed: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    """The keys (``section.key``) whose values differ between two sealed documents of the configuration, sorted."""
    a, b = _flat(sealed), _flat(current)
    return sorted(key for key in set(a) | set(b) if a.get(key, _ABSENT) != b.get(key, _ABSENT))


def _rounded(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SealError("un valor del sello no es un número finito")
        return round(value, SEAL_DECIMALS)
    if isinstance(value, Mapping):
        return {str(key): _rounded(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(item) for item in value]
    raise SealError(f"un valor del sello no es JSON: {type(value).__name__}")


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def read_seal(seal_path: Path) -> dict | None:
    """The seal at `seal_path`, or None if there is no file. A file that is not a seal is a ``SealError``: it is never taken for an absent one."""
    path = Path(seal_path)
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SealError(f"el sello {path.name} no se puede leer: {error}") from error
    if not isinstance(document, dict) or document.get("version") != SEAL_VERSION or not set(document) <= {"version", "launch", "test"}:
        raise SealError(f"el sello {path.name} no tiene la forma de la versión {SEAL_VERSION}")
    launch = document.get("launch")
    if not isinstance(launch, dict) or set(launch) != set(LAUNCH_KEYS) or not _is_sha256(launch.get("config_sha256")):
        raise SealError(f"la parte del lanzamiento del sello {path.name} no tiene sus claves o su huella")
    test = document.get("test")
    if test is not None and (not isinstance(test, dict) or set(test) != set(TEST_KEYS) or not _is_sha256(test.get("config_sha256"))):
        raise SealError(f"la parte de la prueba del sello {path.name} no tiene sus claves o su huella")
    return document


def seal_state(seal_path: Path, config_sha256: str) -> Literal["none", "match", "post_seal"]:
    """``none`` if there is no seal, ``match`` if its configuration is `config_sha256` and ``post_seal`` if it is another one (M05)."""
    document = read_seal(seal_path)
    if document is None:
        return "none"
    return "match" if document["launch"]["config_sha256"] == config_sha256 else "post_seal"


def check_test_evaluation(seal_path: Path, view: SealedConfig) -> Literal["first", "repeat", "post_seal"]:
    """What evaluating the test with the configuration `view` means, decided **before** anything is written (D18).

    ``first``: the seal has the launch part with this configuration and no test part, so this evaluation is the one that is sealed. ``repeat``: the
    seal already has its test part with this configuration: the evaluation must reproduce it. ``post_seal``: the test is sealed and this is another
    configuration: it is computed apart and never replaces the sealed one. With another configuration and **no** test part the evaluation is refused
    (``EvaluationRefusedError`` naming the keys that differ), and so it is without a seal."""
    document = read_seal(seal_path)
    if document is None:
        raise EvaluationRefusedError("no hay sello: el lanzamiento lo escribe antes de que se evalúe la prueba, y no se evalúa sin él (docs/runbook.md, R7)")
    config_sha256 = config_fingerprint(view)
    sealed = document["launch"]["config_sha256"]
    if document.get("test") is not None:
        return "repeat" if sealed == config_sha256 else "post_seal"
    if sealed != config_sha256:
        keys = differing_keys(document["launch"]["sealed_config"], sealed_document(view))
        raise EvaluationRefusedError(
            "la prueba no se evalúa con otra configuración que la sellada mientras el sello no tiene su parte de la prueba: la primera evaluación es la que "
            f"se sella (D18); las claves que difieren: {', '.join(keys) or '(ninguna que se pueda nombrar)'}. No se escribió nada (docs/runbook.md, R7)")
    return "first"


def _dump(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, sort_keys=True, indent=1, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _lacks_hard_links(error: OSError) -> bool:
    return error.errno in _NO_HARD_LINKS or getattr(error, "winerror", None) in _WINDOWS_NO_HARD_LINKS


def _say_who_can_read(path: Path) -> None:
    """Where the mode bits are not the access control (Windows), the creation of a seal says so, with the folder whose access list decides."""
    if os.name != "posix":
        logger.warning("seal %s: the owner-only mode 0o%o is not enforced on this system (os.name %s); who can read it is decided by the access "
                       "list of the folder %s (runbook R7)", path.name, SEAL_MODE, os.name, path.parent)


def _create_without_link(path: Path, data: bytes) -> bool:
    """The creation for a file system without hard links: the exclusive create is the check; a half file is removed if the write fails."""
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), SEAL_MODE)
    except FileExistsError:
        return False
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    os.close(descriptor)
    return True


def _create_exclusive(path: Path, data: bytes) -> bool:
    """Create `path` with `data` only if it does not exist, all or nothing: True if created, False if a file was already there. The data goes
    to a temporary file that is hard-linked to `path`, which fails if `path` exists and never shows half a file; without hard links, an
    exclusive create is the check (project 03, D64 and D78)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())         # the bytes reach the disk before the seal's name points at them, as in _create_without_link
        try:
            os.link(name, path)
            created = True
        except FileExistsError:
            return False
        except OSError as error:
            if not _lacks_hard_links(error):
                raise
            created = _create_without_link(path, data)
        if created:
            _say_who_can_read(path)
        return created
    finally:
        Path(name).unlink(missing_ok=True)


def _check_part(part: Mapping[str, Any], keys: tuple[str, ...], what: str) -> None:
    missing, extra = [k for k in keys if k not in part], sorted(set(part) - set(keys))
    if missing or extra:
        raise SealError(f"la parte {what} debe tener exactamente las claves {list(keys)}; faltan {missing}, sobran {extra}")
    if not _is_sha256(part["config_sha256"]):
        raise SealError(f"config_sha256 de la parte {what} debe ser un SHA-256 de 64 dígitos hexadecimales")
    _rounded(dict(part))                 # refuses a value that is not JSON, or not finite, before anything is compared or written


def _differences(sealed: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    a = _flat(_rounded({k: v for k, v in sealed.items() if k not in _NOT_COMPARED}))
    b = _flat(_rounded({k: v for k, v in current.items() if k not in _NOT_COMPARED}))
    return sorted(key for key in set(a) | set(b) if a.get(key, _ABSENT) != b.get(key, _ABSENT))


def write_launch_seal(seal_path: Path, launch: Mapping[str, Any]) -> Literal["written", "unchanged", "post_seal"]:
    """Write the launch part of the seal once (an exclusive creation or a hard link). Returns what happened.

    ``written``: there was no seal and now it has `launch`. ``unchanged``: the seal has this configuration and every sealed value of the launch,
    rounded to 6 decimals, is this one (nothing is rewritten). ``post_seal``: the seal has another configuration and is left as it is; the
    warning names the keys that differ (M05). The same configuration with another sealed value is a ``SealMismatchError`` that names each one
    (runbook R7)."""
    _check_part(launch, LAUNCH_KEYS, "del lanzamiento")
    if canonical_sha256(launch["sealed_config"]) != launch["config_sha256"]:
        raise SealError("config_sha256 no es la huella de la configuración sellada de la parte del lanzamiento")
    path = Path(seal_path)
    if read_seal(path) is None and _create_exclusive(path, _dump({"version": SEAL_VERSION, "launch": dict(launch)})):
        logger.info("seal: launch part written to %s (config %s)", path.name, launch["config_sha256"][:12])
        return "written"
    sealed = read_seal(path)["launch"]
    if sealed["config_sha256"] != launch["config_sha256"]:
        logger.warning("seal: this configuration (%s) is not the sealed one (%s): post_seal; the keys that differ: %s", launch["config_sha256"][:12],
                       sealed["config_sha256"][:12], ", ".join(differing_keys(sealed["sealed_config"], launch["sealed_config"])))
        return "post_seal"
    differ = _differences(sealed, launch)
    if differ:
        then, now = _flat(_rounded(sealed)), _flat(_rounded(dict(launch)))
        named = "; ".join(f"{key}: {then.get(key)!r} sellado, {now.get(key)!r} en esta corrida" for key in differ[:6])
        raise SealMismatchError(f"M05: la configuración es la sellada pero el lanzamiento no la reproduce: {named}"
                                f"{' y otros' if len(differ) > 6 else ''} (docs/runbook.md, R7)")
    return "unchanged"


def write_test_seal(seal_path: Path, test: Mapping[str, Any]) -> Literal["written", "unchanged", "post_seal"]:
    """Add the test part to the seal once. Returns what happened.

    ``written``: the seal had only its launch part, which is kept as it was, and now has `test` too; the file is read back and must say what was
    written. ``unchanged``: it already has a test part whose values, rounded to 6 decimals, are these. ``post_seal``: `test` was evaluated with
    another configuration than the sealed one; the seal is left as it is. Any other difference is a ``SealMismatchError`` that names the values:
    every key that can change a sealed value is in ``config_sha256``, so there is no third case (plan, section 15)."""
    _check_part(test, TEST_KEYS, "de la prueba")
    path = Path(seal_path)
    document = read_seal(path)
    if document is None:
        raise SealError("no hay sello: la parte de la prueba se escribe después de la del lanzamiento")
    if test["config_sha256"] != document["launch"]["config_sha256"]:
        logger.warning("seal: the test was evaluated with another configuration than the sealed one: post_seal; the seal is left as it is")
        return "post_seal"
    if document.get("test") is not None:
        differ = _differences(document["test"], test)
        if not differ:
            return "unchanged"
        raise SealMismatchError("la evaluación de la prueba con la configuración sellada no reproduce los valores sellados, redondeados a 6 "
                                f"decimales: {', '.join(differ[:6])}{' y otros' if len(differ) > 6 else ''} (docs/runbook.md, R7)")
    write_atomic(path, _dump({**document, "test": dict(test)}))
    # one writer at a time (D31), but the read, the decision and the write are not one step: read it back, and say so if it is not what was written
    kept = read_seal(path) or {}
    if kept.get("launch") != document["launch"] or _rounded(kept.get("test")) != _rounded(dict(test)):
        logger.error("seal: the test part written by run %s is not what the file says (runbook R7)", test["run_key"])
        raise SealMismatchError("lo que consta en el sello no es lo que esta corrida escribió: otra escritura lo cambió (docs/runbook.md, R7)")
    logger.info("seal: test part written to %s", path.name)
    return "written"


def predictions_fingerprint(predictions: Sequence[tuple[Any, int, float]]) -> str:
    """``valid_predictions_sha256``: the SHA-256 of the predictions of V1 and V2 rounded to 6 decimals, one ``hour|horizon|value`` line each, ordered by
    (hour, horizon). `predictions` are ``(hour, horizon, value)``; no value of the plant enters, only what the models say."""
    ordered = sorted((_stamp(hour), int(horizon), float(value)) for hour, horizon, value in predictions)
    text = "".join(f"{hour}|{horizon}|{value:.6f}\n" for hour, horizon, value in ordered)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _stamp(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
