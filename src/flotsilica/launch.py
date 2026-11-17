"""The ``fit_model`` task: the launch freezes the model, and every later run checks that it is still the frozen one (RF13, RF15, D18, D39; M03, M05; plan,
section 3, step 5). Its hours come from the warehouse as it stood at the launch instant, and its result is four things that are written once: the artifact
(``<models_dir>/<model_version>.pkl``), its row in ``model_registry``, the launch part of the seal and, with them, the estimates the run issues (``score``).

* At the **launch**: ``model.fit_launch`` (M06, the baselines, the grid on the training block, the choice on V1, M01, the refit and the range on V2), the
  bundle saved with its SHA-256 and registered, and ``write_launch_seal``: ``written`` the first time, ``unchanged`` if a repetition with the sealed
  configuration reproduces the sealed values, ``post_seal`` (M05) with another configuration, and a ``SealMismatchError`` if the same configuration
  gives other values (runbook R7).
* In **every other run**: nothing is fitted. The bundle is loaded from the registry only if the artifact has the registered SHA-256 (M03) and the state of the
  seal is read (M05).

``fit_model`` takes the warehouse, the run and the paths instead of the pipeline's context (U17 wraps it in the task); the gate of the sensitivities (U12) is
a function the caller passes: until then the seal says it was not computed.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from flotsilica.features import HourTables
from flotsilica.files import sha256_file
from flotsilica.model import LaunchFit, fit_launch
from flotsilica.registry import (
    ArtifactError,
    SealError,
    artifact_sha256,
    bundle_bytes,
    bundle_of,
    config_fingerprint,
    load_registered_bundle,
    predictions_fingerprint,
    read_registry,
    register_model,
    save_artifact,
    sealed_document,
    seal_state,
    write_launch_seal,
)
from flotsilica.scoring import RunMeta
from flotsilica.warehouse import rebuild_staging

logger = logging.getLogger(__name__)

NOT_COMPUTED_GATE = {"computed": False, "model": None, "passing": []}      # until U12 puts the gate of the sensitivities in the launch
GateFn = Callable[[LaunchFit, Any], dict[str, Any]]


def hour_tables(conn: sqlite3.Connection, as_of: Any, view: Any) -> HourTables:
    """The ``HourTables`` of the hours that had closed at `as_of` (``stg_hours`` rebuilt for that instant, which reads ``lab_hours`` and ``hour_aggregates``
    and nothing that arrived later)."""
    rebuild_staging(conn, pd.Timestamp(as_of).to_pydatetime(), view)
    frame = pd.read_sql_query("SELECT * FROM stg_hours ORDER BY hour", conn, parse_dates={"hour": "%Y-%m-%d %H:%M:%S", "available_at": "%Y-%m-%d %H:%M:%S"})
    return HourTables.from_hours(frame, view)


def validation_predictions(launch: LaunchFit) -> list[tuple[Any, int, float]]:
    """What the frozen model of each horizon says about the hours of V1 and V2: ``(hour, horizon, estimate)``."""
    out = []
    for horizon, fit in launch.horizons.items():
        for name in ("valid_v1", "valid_v2"):
            block = launch.blocks[horizon][name]
            out.extend(zip(block.hours, [horizon] * len(block.hours), fit.model.predict(block.X, block.last1), strict=True))
    return out


def launch_document(run: RunMeta, view: Any, launch: LaunchFit, artifact_sha256: str, gate: dict[str, Any]) -> dict[str, Any]:
    """The launch part of the seal (plan, section 15)."""
    horizons = [
        {"horizon": h, "family": fit.chosen.family, "feature_set": fit.chosen.feature_set, "target": fit.chosen.target,
         "min_samples_leaf": fit.chosen.min_samples_leaf, "half_width": fit.calibration.half_width, "b_star": launch.baselines.b_star[h],
         "b2_k": launch.baselines.b2_k[h], "mae_v1": fit.mae_v1}
        for h, fit in launch.horizons.items()
    ]
    document = sealed_document(view)
    return {
        "run_key": run.run_key, "as_of": pd.Timestamp(run.as_of).strftime("%Y-%m-%d %H:%M:%S"), "source_sha256": view.source_sha256,
        "config_sha256": config_fingerprint(view), "sealed_config": document, "model_version": view.model.model_version, "artifact_sha256": artifact_sha256,
        "horizons": horizons, "gate": gate, "valid_predictions_sha256": predictions_fingerprint(validation_predictions(launch)),
    }


def _selection(launch: LaunchFit) -> dict[str, Any]:
    """Every candidate's error on V1, by horizon (D14: all of them are kept)."""
    return {str(h): {r.candidate.name: r.mae_v1 for r in fit.results} for h, fit in launch.horizons.items()}


def fit_model(conn: sqlite3.Connection, run: RunMeta, view: Any, *, models_dir: Path, seal_path: Path, gate: GateFn | None = None) -> dict[str, Any]:
    """The task of the launch and of the runs after it (see the module). `view` is the ``SealedConfig`` of the run; the result is what the task reports.

    At the launch it returns ``{"mode": "launch", "seal": written|unchanged|post_seal, ...}``; in any other run, ``{"mode": "verify", "seal": match|post_seal}``
    after loading the artifact with its registered SHA-256 (M03)."""
    models_dir, seal_path = Path(models_dir), Path(seal_path)
    version, config_sha256 = view.model.model_version, config_fingerprint(view)
    if run.kind != "launch":
        bundle = load_registered_bundle(conn, models_dir, version)
        state = seal_state(seal_path, config_sha256)
        if state == "none":
            raise SealError("no hay sello: el lanzamiento lo escribe y esta corrida no es el lanzamiento (docs/runbook.md, R7)")
        return {"mode": "verify", "seal": state, "model_version": version, "config_sha256": config_sha256, "horizons": len(bundle.horizons)}
    tables = hour_tables(conn, run.as_of, view)
    launch = fit_launch(tables, view)
    bundle = bundle_of(launch, view)
    artifact = models_dir / f"{version}.pkl"
    # a registered version has one artifact: another model never takes its name (the registry refuses a second row, and the file must not be replaced first)
    digest = artifact_sha256(bundle_bytes(bundle))
    if not artifact.exists():
        save_artifact(bundle, artifact)
    elif sha256_file(artifact) != digest:
        raise ArtifactError(f"el artefacto {artifact.name} ya existe con otra huella: una versión registrada tiene un solo artefacto; cambie "
                            "[model] model_version para otro modelo (docs/runbook.md, R9)")
    document = launch_document(run, view, launch, digest, (gate or (lambda *_: NOT_COMPUTED_GATE))(launch, view))
    if read_registry(conn, version) is None:
        register_model(conn, model_version=version, trained_as_of=document["as_of"], artifact_name=artifact.name, artifact_sha256=digest,
                       config_sha256=config_sha256, models=document["horizons"], selection=_selection(launch),
                       valid_predictions_sha256=document["valid_predictions_sha256"])
    state = write_launch_seal(seal_path, document)
    logger.info("fit_model %s: version %s, artifact %s, seal %s", run.run_key, version, digest[:12], state)
    return {"mode": "launch", "seal": state, "model_version": version, "artifact_sha256": digest, "config_sha256": config_sha256,
            "horizons": [h["horizon"] for h in document["horizons"]], "valid_predictions_sha256": document["valid_predictions_sha256"]}

