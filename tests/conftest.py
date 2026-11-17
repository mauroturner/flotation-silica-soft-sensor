"""Shared fixtures, the automatic skipping of the real_data and docker marks and the fast suite's time limit (plan, section 24.1).

Every expensive state is built once per session and reused (D33): the synthetic fixture in its standard (12 rows per hour, about 49,000
rows) and small (3 weeks) sizes, each signal variant and each malformed variant. A test that writes works on its own copy (``copy_of``).
The fixtures of the units that come later (the canonical lines, the loaded warehouses, the launch, the sealed history, the site files,
the rendered design and the figures) are added by the unit that writes the code they need.
"""

from __future__ import annotations

import shutil
import types
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

from tests.fixtures.suite_budget import pytest_addoption, pytest_sessionfinish, pytest_sessionstart  # noqa: F401  (the time limit, D33)

pytest_plugins = ["pytester"]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_ARFF = PROJECT_ROOT / "data" / "raw" / "openml-43311-quality-prediction-mining-process.arff"
SMALL_WEEKS = 3


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip, instead of failing, the tests whose external requirement is missing (they are not selected by default either)."""
    skips = {
        "real_data": (not REAL_ARFF.exists(), "the real ARFF file is not in data/raw/"),
        "docker": (shutil.which("docker") is None, "docker is not installed"),
    }
    for item in items:
        for mark, (missing, reason) in skips.items():
            if mark in item.keywords and missing:
                item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def cfg():
    """The default configuration, loaded once (it is immutable)."""
    from flotsilica.config import load_config

    return load_config(PROJECT_ROOT / "config" / "pipeline.toml")


@pytest.fixture(scope="session")
def quick_cfg():
    """The quick-mode configuration (12 rows per hour, the fixture's), loaded once."""
    from flotsilica.config import load_config

    return load_config(PROJECT_ROOT / "config" / "pipeline.quick.toml")


# --- the synthetic fixture, its sizes and its variants ---------------------------------------------------------------


@pytest.fixture(scope="session")
def fixture_truth(tmp_path_factory: pytest.TempPathFactory):
    """The standard synthetic ARFF (12 rows per hour, seed 0, no planted signal) and what it holds."""
    from tests.fixtures.make_fixture import make_fixture

    return make_fixture(tmp_path_factory.mktemp("fixture") / "flotation_fixture.arff", rows_per_hour=12, seed=0)


@pytest.fixture(scope="session")
def fixture_arff(fixture_truth) -> Path:
    return fixture_truth.path


@pytest.fixture(scope="session")
def small_truth(tmp_path_factory: pytest.TempPathFactory):
    """The first three weeks of the standard fixture, for the tests whose subject is one row, one rule or one error: a defect in one row is
    found by the same code whatever the size of the rest, and the standard file costs more to write and to read."""
    from tests.fixtures.make_fixture import make_fixture

    return make_fixture(tmp_path_factory.mktemp("small_fixture") / "small_fixture.arff", rows_per_hour=12, seed=0, weeks=SMALL_WEEKS)


@pytest.fixture(scope="session")
def small_arff(small_truth) -> Path:
    return small_truth.path


@pytest.fixture(scope="session")
def signal_truth(tmp_path_factory: pytest.TempPathFactory) -> Callable[[str], object]:
    """``signal_truth(signal)``: the standard fixture with a planted signal (``sensor_signal``, the positive control, or ``lab_only``, the
    negative one), each built once per session."""
    from tests.fixtures.make_fixture import make_fixture

    folder = tmp_path_factory.mktemp("signals")
    built: dict[str, object] = {}

    def build(signal: str):
        if signal not in built:
            built[signal] = make_fixture(folder / f"{signal}.arff", rows_per_hour=12, seed=0, signal=signal)
        return built[signal]

    return build


@pytest.fixture(scope="session")
def signal_arff(signal_truth: Callable[[str], object]) -> Callable[[str], Path]:
    """``signal_arff(signal)``: the path of ``signal_truth(signal)``."""
    return lambda signal: signal_truth(signal).path


@pytest.fixture(scope="session")
def malformed(tmp_path_factory: pytest.TempPathFactory, small_arff: Path) -> Callable[[str], Path]:
    """``malformed(kind)``: the small fixture damaged in one documented way, each kind built once per session."""
    from tests.fixtures.make_fixture import make_malformed

    folder = tmp_path_factory.mktemp("malformed")
    built: dict[str, Path] = {}

    def build(kind: str) -> Path:
        if kind not in built:
            built[kind] = make_malformed(small_arff, kind, folder / f"{kind}.arff")
        return built[kind]

    return build


@pytest.fixture
def copy_of(tmp_path: Path) -> Callable[[Path], Path]:
    """``copy_of(path)``: a copy of a file or a folder inside this test's ``tmp_path``, for a test that writes."""

    def copy(path: Path) -> Path:
        target = tmp_path / "copies" / Path(path).name
        target.parent.mkdir(parents=True, exist_ok=True)
        if Path(path).is_dir():
            shutil.copytree(path, target)
        else:
            shutil.copy2(path, target)
        return target

    return copy


@pytest.fixture(scope="session")
def canonical(fixture_arff: Path, quick_cfg):
    """The standard fixture read once into its canonical tables (plan, section 24.1): ``read`` (the 24 columns of every row, as the reader
    returns them), ``report`` (its ``SourceReport``), ``rows`` (``source_rows``, without a laboratory column) and ``hours`` (``source_hours``)."""
    from flotsilica.ingest import canonical as build
    from flotsilica.ingest import read_arff

    read, report = read_arff(fixture_arff, quick_cfg)
    rows, hours = build(read, quick_cfg)
    return types.SimpleNamespace(read=read, report=report, rows=rows, hours=hours)


@pytest.fixture(scope="session")
def published(tmp_path_factory: pytest.TempPathFactory, canonical, quick_cfg):
    """The whole quick plan of the standard fixture published once (plan, section 24.1): ``folder`` (with ``manifest.json``), ``plan`` and, by
    delivery id, ``entry``, ``rows`` and ``hours`` as read back from its files. A test that writes copies the folder (``copy_of``)."""
    from flotsilica.deliveries import delivery_plan, publish, read_delivery

    folder = tmp_path_factory.mktemp("deliveries")
    plan = delivery_plan(quick_cfg)
    entries = {spec.delivery_id: publish(spec, canonical.rows, canonical.hours, folder) for spec in plan}
    items = {delivery_id: (entry, *read_delivery(folder, entry)) for delivery_id, entry in entries.items()}
    return types.SimpleNamespace(folder=folder, plan=plan, entries=entries, items=items)


@pytest.fixture(scope="session")
def loaded_masters(tmp_path_factory: pytest.TempPathFactory, published, quick_cfg) -> Callable[[int], tuple[Path, object]]:
    """``loaded_masters(upto)``: ``(path, LoadResult of its last load)`` of a warehouse with the first `upto` deliveries of the quick plan,
    loaded by runs ``r1``, ``r2``... with the SHA-256 of their published files. Each is a copy of the largest one already built below it with
    the missing deliveries loaded (project 03, D76). A test that writes works on ``copy_of(path)``."""
    from flotsilica.warehouse import connect, load_delivery

    folder = tmp_path_factory.mktemp("masters")
    plan = published.plan
    built: dict[int, tuple[Path, object]] = {}

    def build(upto: int) -> tuple[Path, object]:
        if not 1 <= upto <= len(plan):
            raise ValueError(f"upto: from 1 to {len(plan)}, got {upto}")
        if upto not in built:
            below = max((k for k in built if k < upto), default=0)
            path = folder / f"master_{upto}.sqlite"
            if below:
                shutil.copy2(built[below][0], path)
            conn = connect(path)
            try:
                for index in range(below, upto):
                    spec = plan[index]
                    entry, rows, hours = published.items[spec.delivery_id]
                    result = load_delivery(conn, rows, hours, spec, f"r{index + 1}", quick_cfg, sha256=entry.sha256)
            finally:
                conn.close()
            built[upto] = (path, result)
        return built[upto]

    return build


@pytest.fixture(scope="session")
def small_canonical(small_arff: Path, quick_cfg):
    """The small fixture (three weeks, 186 hours, the March gap inside) read once into its canonical tables, like ``canonical``."""
    from flotsilica.ingest import canonical as build
    from flotsilica.ingest import read_arff

    read, report = read_arff(small_arff, quick_cfg)
    rows, hours = build(read, quick_cfg)
    return types.SimpleNamespace(read=read, report=report, rows=rows, hours=hours)


@pytest.fixture(scope="session")
def small_store(tmp_path_factory: pytest.TempPathFactory, small_canonical, quick_cfg) -> Path:
    """A warehouse that holds the whole small fixture as one delivery (the features read ``lab_hours`` and ``hour_aggregates``): built once;
    a test that writes opens ``sqlite3`` on a copy of it (``Connection.backup``) or on ``copy_of(path)``."""
    from flotsilica.deliveries import DeliverySpec
    from flotsilica.warehouse import connect, load_delivery

    hours = small_canonical.hours
    spec = DeliverySpec("L-small", "launch", hours["hour"].iloc[0].to_pydatetime(), hours["hour"].iloc[-1].to_pydatetime(),
                        (hours["hour"].iloc[-1] + pd.Timedelta(hours=1)).to_pydatetime())
    path = tmp_path_factory.mktemp("small_store") / "small.sqlite"
    conn = connect(path)
    try:
        load_delivery(conn, small_canonical.rows, hours, spec, "r1", quick_cfg, sha256="f" * 64)
    finally:
        conn.close()
    return path
