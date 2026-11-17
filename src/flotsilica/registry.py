"""The artifact of the frozen model, deserialized only when its bytes still have the registered SHA-256 (M03, RF13, D39; plan, section 15).
Adapted from project 04's ``registry.py`` (its D40). The seal comes with U10.

``pickle`` runs code when it loads, so a file that someone replaced must never reach it. ``load_artifact`` looks at the size of the file first (a
file over ``MAX_ARTIFACT_BYTES``, or over the size the caller registered, is not even read), reads the bytes **once**, computes their SHA-256, compares it
with the registered one and only then hands *those same bytes* to ``pickle.loads``: there is no window between checking and loading, and nothing is
unpickled from a file whose fingerprint is not the registered one, whether it is another file, a truncated one, a damaged one or none. The
fingerprint protects against a file that was replaced or damaged; it does not make ``pickle`` safe against someone who can rewrite the file and the
registry together (D39).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import pickle
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def save_artifact(bundle: ModelBundle, path: Path) -> str:
    """Serialize `bundle` with the standard library's ``pickle`` (protocol 5), write it atomically to `path` and return the SHA-256 of the bytes
    written. If it cannot be serialized, nothing is written and a file already at `path` is left as it was."""
    data = pickle.dumps(bundle, protocol=PICKLE_PROTOCOL)
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
