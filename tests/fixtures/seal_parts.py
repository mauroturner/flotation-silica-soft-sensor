"""The two parts of a seal as dicts, with the keys and the shapes the seal checks (``registry.LAUNCH_KEYS`` and ``TEST_KEYS``), for the tests of the seal."""

from __future__ import annotations

from flotsilica.registry import config_fingerprint, sealed_document, sealed_view

SOURCE = "ab" * 32


def launch_part(cfg, **changes) -> dict:
    view = sealed_view(cfg, SOURCE)
    part = {
        "run_key": "r1", "as_of": "2017-08-01 00:00:00", "source_sha256": SOURCE, "config_sha256": config_fingerprint(view), "sealed_config": sealed_document(view),
        "model_version": "v1", "artifact_sha256": "11" * 32,
        "horizons": [{"horizon": h, "family": "rf", "feature_set": "fSL", "target": "change", "min_samples_leaf": 5, "half_width": 0.7 + h / 10, "b_star": "b1_persistence",
                      "b2_k": 3, "mae_v1": 0.5} for h in range(3)],
        "gate": {"computed": False, "model": None, "passing": []}, "valid_predictions_sha256": "22" * 32,
    }
    part.update(changes)
    return part


def evaluation_part(cfg, **changes) -> dict:
    part = {"run_key": "r9", "as_of": "2017-09-10 01:00:00", "config_sha256": config_fingerprint(sealed_view(cfg, SOURCE)),
            "criteria": [{"id": f"C0{k}", "value": 0.5 + k, "passed": False} for k in range(1, 4)], "metrics": {"h0": {"mae": 0.5}}, "weekly": [], "variants": [],
            "sensitivity_test": []}
    part.update(changes)
    return part
