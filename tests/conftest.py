"""Shared fixtures (plan, section 24.1). U02 starts with the project folder and the default configuration; U03 adds the session
fixtures, the automatic skipping of the real_data and docker marks and the fast suite's time limit."""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def cfg():
    """The default configuration, loaded once (it is immutable)."""
    from flotsilica.config import load_config

    return load_config(PROJECT_ROOT / "config" / "pipeline.toml")
