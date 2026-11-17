"""Shared fixtures, the automatic skipping of the real_data and docker marks and the fast suite's time limit (plan, section 24.1).

Every expensive state is built once per session and reused (D33): the synthetic fixture in its standard (12 rows per hour, about 49,000
rows) and small (3 weeks) sizes, each signal variant and each malformed variant. A test that writes works on its own copy (``copy_of``).
The fixtures of the units that come later (the canonical lines, the loaded warehouses, the launch, the sealed history, the site files,
the rendered design and the figures) are added by the unit that writes the code they need.
"""

from __future__ import annotations

import gc
import json
import shutil
import types
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

from tests.fixtures.suite_budget import pytest_addoption, pytest_sessionfinish, pytest_sessionstart  # noqa: F401  (the time limit, D33)

pytest_plugins = ["pytester"]

# The session fixtures keep the fixture's frames, its warehouses and the fitted launches alive for the whole run, and every full collection of the garbage
# collector walks all of them again. The thresholds are raised so that it runs far less often; garbage in cycles is still freed, only later. It changes no
# value and no test (project 04, D93).
gc.set_threshold(200_000, 100, 100)

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


# --- the launch of each signal fixture (U09) ---------------------------------------------------------------------------------------------

# The planted signal of ``sensor_signal`` (beta 0.7 on the sensor of the same hour) is so strong that an honest model reaches 0.386 against the 0.824
# of the persistence, which is under the default tripwire of 0.5 x the persistence (M01): the tripwire is made for the real file, where an honest model stays
# near the persistence (D09). The positive control relaunches with a tripwire of 0.2, which a model that read the target (an error near 0) still crosses.
CONTROL_TRIPWIRE_RATIOS = {"sensor_signal": 0.2}


@pytest.fixture(scope="session")
def signal_tables(signal_arff, quick_cfg):
    """``signal_tables(signal)``: the ``HourTables`` of the signal fixture (read once per signal), for the controls."""
    from flotsilica.features import HourTables
    from flotsilica.ingest import canonical as build
    from flotsilica.ingest import read_arff

    built: dict[str, object] = {}

    def tables(signal: str):
        if signal not in built:
            read, _report = read_arff(signal_arff(signal), quick_cfg)
            _rows, hours = build(read, quick_cfg)
            built[signal] = HourTables.from_hours(hours, quick_cfg)
        return built[signal]

    return tables


@pytest.fixture(scope="session")
def signal_launch(signal_tables, quick_cfg):
    """``signal_launch(signal)``: ``(view, LaunchFit)`` of the learning of the launch (``model.fit_launch``) on the signal fixture at the horizon 0, built once
    per signal. Only the model part: the sensitivities and the seal come in later units."""
    import dataclasses

    from flotsilica.model import fit_launch

    built: dict[str, tuple[object, object]] = {}

    def launch(signal: str):
        if signal not in built:
            criteria = dataclasses.replace(quick_cfg.criteria, leak_tripwire_ratio=CONTROL_TRIPWIRE_RATIOS.get(signal, quick_cfg.criteria.leak_tripwire_ratio))
            view = dataclasses.replace(quick_cfg, evaluation=dataclasses.replace(quick_cfg.evaluation, horizons=(0,)), criteria=criteria)
            built[signal] = (view, fit_launch(signal_tables(signal), view))
        return built[signal]

    return launch


# --- a short history with its seal and its estimates (U10) --------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def small_launched(tmp_path_factory: pytest.TempPathFactory, small_canonical, quick_cfg):
    """The small fixture's launch loaded, fitted, sealed and scored (``tests/fixtures/history.py``): built once, and the histories below continue from copies of it."""
    from tests.fixtures.history import PLAN_A, build_history

    return build_history(tmp_path_factory.mktemp("history_launch"), small_canonical, quick_cfg, PLAN_A[:1])


@pytest.fixture(scope="session")
def small_history(tmp_path_factory: pytest.TempPathFactory, small_launched, small_canonical):
    """The launch and three deliveries of twelve hours, fitted, sealed and scored run by run: built once. A test that writes works on ``copy_history`` of it."""
    from tests.fixtures.history import PLAN_A, extend_history

    return extend_history(small_launched, tmp_path_factory.mktemp("history_a") / "h", small_canonical, PLAN_A[1:])


@pytest.fixture(scope="session")
def small_history_one_batch(tmp_path_factory: pytest.TempPathFactory, small_launched, small_canonical):
    """The same hours as ``small_history`` with one delivery of twenty-five hours after the launch instead of three (AC12): built once."""
    from tests.fixtures.history import PLAN_B, extend_history

    return extend_history(small_launched, tmp_path_factory.mktemp("history_b") / "h", small_canonical, PLAN_B[1:])


# --- the star model of the small history (U13) --------------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def star_files(tmp_path_factory: pytest.TempPathFactory, small_history):
    """The star model exported once from a copy of the small history at the instant of its last run (``track`` first, as the pipeline does): ``history`` (the copy, with
    the ``star_*`` tables), ``run``, ``out_dir`` and ``paths``. A test that writes works on ``copy_history`` of ``history`` or ``copy_of(out_dir)``."""
    from flotsilica.dashboard.semantic_model import MODEL
    from flotsilica.export import export_star_schema
    from flotsilica.tracking import track
    from flotsilica.warehouse import connect
    from tests.fixtures.history import copy_history, stamp

    folder = tmp_path_factory.mktemp("star")
    history = copy_history(small_history, folder / "history")
    run = history.runs[-1]
    out_dir = folder / "powerbi"
    conn = connect(history.paths.db)
    try:
        # what the pipeline writes about its runs and their validation (U17), by hand: the runs of the history and four results of the last one, one of each severity and status
        for meta, issued in zip(history.runs, history.results, strict=True):
            conn.execute("INSERT INTO pipeline_runs (run_key, started_at, finished_at, status, delivery_id, as_of, source_sha256, rows_delivery, estimates_issued, estimates_missing) "
                         "VALUES (?, ?, ?, 'ok', ?, ?, ?, 0, ?, 0)", (meta.run_key, stamp(meta.as_of), stamp(meta.as_of), meta.delivery_id, stamp(meta.as_of),
                                                                    history.sealed.source_sha256, issued.issued))
        conn.executemany("INSERT INTO validation_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '[]')", [
            (run.run_key, "V10", "Regla bloqueante que pasa", "blocking", "delivery", "per_run", 1, 0, 0), (run.run_key, "V11", "Regla bloqueante que falla", "blocking", "delivery", "per_run", 0, 5, 2),
            (run.run_key, "V22", "Advertencia que advierte", "warning", "hours", "per_run", 0, 3, 1), (run.run_key, "I02", "Informativa", "info", "hours", "latest", 1, 10, 4)])
        track(conn, run, history.sealed)
        paths = export_star_schema(conn, out_dir, MODEL, run, history.sealed, seal_path=history.paths.seal)
    finally:
        conn.close()
    return types.SimpleNamespace(history=history, run=run, out_dir=out_dir, paths=paths)


@pytest.fixture(scope="session")
def rendered_html(tmp_path_factory: pytest.TempPathFactory, star_files):
    """The design of the report rendered once from the star model (U14, plan section 24.1): ``path`` (a file of its own) and ``html``."""
    from flotsilica.dashboard.render import render_design
    from flotsilica.dashboard.semantic_model import MODEL

    path = render_design(MODEL, star_files.out_dir, tmp_path_factory.mktemp("design") / "dashboard" / "powerbi-design.html", star_files.run)
    return types.SimpleNamespace(path=path, html=path.read_text(encoding="utf-8"))


# --- the site files and the figures of the small history (U15) ----------------------------------------------------------------------------


@pytest.fixture(scope="session")
def site_files(tmp_path_factory: pytest.TempPathFactory, star_files, quick_cfg):
    """The five site files exported once from the star model of ``star_files`` (U15, plan section 24.1): ``out_dir``, ``paths``, ``history``, ``run``, ``cap`` and the
    keyword arguments of the export (``kwargs``). A test that writes works on ``copy_of(out_dir)`` and on a copy of the warehouse."""
    from flotsilica.site_export import export_site
    from flotsilica.warehouse import connect

    history, cap = star_files.history, quick_cfg.site.max_total_bytes
    kwargs = {"seal_path": history.paths.seal, "max_total_bytes": cap}
    out_dir = tmp_path_factory.mktemp("site") / "site"
    conn = connect(history.paths.db)
    try:
        paths = export_site(conn, out_dir, star_files.run, history.sealed, **kwargs)
    finally:
        conn.close()
    return types.SimpleNamespace(out_dir=out_dir, paths=paths, history=history, run=star_files.run, cap=cap, kwargs=kwargs)


@pytest.fixture(scope="session")
def figures_written(tmp_path_factory: pytest.TempPathFactory, site_files):
    """The figures written once from the verified site files into a folder that held a figure of an earlier run: ``(folder, paths, {name: bytes})``."""
    from flotsilica.figures import write_figures

    folder = tmp_path_factory.mktemp("figures") / "figures"
    folder.mkdir()
    (folder / "latency.png").write_bytes(b"an earlier figure")
    paths = write_figures(site_files.out_dir, folder)
    return folder, paths, {p.name: p.read_bytes() for p in paths}


# --- the flow of the small fixture, task by task (U17) ----------------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pipeline_launched(tmp_path_factory: pytest.TempPathFactory, quick_cfg, small_arff):
    """The launch run of the flow over the small fixture, every task of it (``tests/fixtures/pipeline_state.py``): built once; a test that writes works on ``copy_state`` of it."""
    from flotsilica import pipeline
    from tests.fixtures.pipeline_state import state_of

    state = state_of(tmp_path_factory.mktemp("pipeline_launched") / "state", quick_cfg, small_arff)
    state.results = pipeline.run_all(state.cfg, run_key="launch")
    return state


@pytest.fixture(scope="session")
def pipeline_replayed(tmp_path_factory: pytest.TempPathFactory, pipeline_launched, quick_cfg):
    """The rest of the plan after the launch, built once from a copy of ``pipeline_launched``: the daily delivery, whose close stops at the HTML the first time (``failed``) and is
    repeated from ``report``; then the close of the plan, by ``replay``; then a run with no delivery left. ``events`` is what the closing of each run wrote, in order, with the state
    of the run in SQLite and of its delivery at that moment: ``(step, run_status, delivery_status, run_key)``; ``stopped`` is what the run that failed left (its status in the state
    file, in SQLite and in the run table, the status of its delivery and the checks of the star set); ``before_idle`` is ``published_digest`` before the run with no delivery."""
    import pyarrow.parquet as pq

    from flotsilica import pipeline
    from flotsilica.deliveries import MANIFEST_NAME, read_manifest
    from flotsilica.export import verify_star_schema
    from tests.fixtures.pipeline_state import DAILY_ID, copy_state, published_digest, query, runs_of

    state = copy_state(pipeline_launched, tmp_path_factory.mktemp("pipeline_replayed") / "state", quick_cfg)
    cfg, events = state.cfg, []
    manifest = Path(cfg.paths.raw_dir) / "deliveries" / MANIFEST_NAME

    def watch(name: str, step: str, run_of, delivery_of):
        real = getattr(pipeline, name)

        def spy(*args, **kwargs):
            run_key, delivery_id = run_of(*args), delivery_of(*args)
            status = query(cfg, "SELECT status FROM pipeline_runs WHERE run_key = ?", (run_key,))
            delivery = [e.status for e in read_manifest(manifest) if e.delivery_id == delivery_id]
            events.append((step, status[0][0] if status else None, delivery[0] if delivery else None, run_key))
            if name == "render_design" and failing and status == [("ok",)]:
                failing.pop()
                raise OSError("no space left on the device")
            return real(*args, **kwargs)

        return spy

    failing = [True]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(pipeline, "export_run_table", watch("export_run_table", "run_table", lambda *a: a[3].run_key, lambda *a: a[3].delivery_id))
        patch.setattr(pipeline, "export_summary", watch("export_summary", "summary", lambda *a: a[2].run_key, lambda *a: a[2].delivery_id))
        patch.setattr(pipeline, "render_design", watch("render_design", "html", lambda *a: a[3].run_key, lambda *a: a[3].delivery_id))
        patch.setattr(pipeline, "mark_delivery", watch("mark_delivery", "delivery_marked", lambda *a: a[3], lambda *a: a[1]))
        with pytest.raises(OSError, match="no space left"):
            pipeline.replay(cfg, until=DAILY_ID)
        [(failed_key, _status)] = [(k, s) for k, s in runs_of(cfg).items() if k != "launch"]
        state.failed_key = failed_key
        state.stopped = types.SimpleNamespace(
            state_status=json.loads((Path(cfg.paths.interim_dir) / "runs" / f"{failed_key}.json").read_text(encoding="utf-8"))["status"], sqlite_status=runs_of(cfg)[failed_key],
            table_status={r["run_key"]: r["status"] for r in pq.read_table(Path(cfg.paths.outputs_dir) / "dim_pipeline_run.parquet").to_pylist()}[failed_key],
            delivery_status={e.delivery_id: e.status for e in read_manifest(manifest)}[DAILY_ID], star_problems=verify_star_schema(cfg.paths.outputs_dir))
        pipeline.run_all(cfg, start="report", run_key=failed_key)
        pipeline.replay(cfg)
    state.events, state.before_idle = events, published_digest(cfg)
    state.idle = pipeline.run_all(cfg, run_key="idle")
    state.runs = runs_of(cfg)
    return state
