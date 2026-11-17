"""The command line (U18, AC32; RF25; plan, section 22): every documented option changes the result (one case per option), an incompatible combination exits with 2 before
anything is written, and the exit codes 0, 1, 2 and 3.

The commands run in this process (``cli.main``) from another working directory, on copies of the session's quick projects that the commands themselves built: ``quick_replay``
(the launch and the delivery of 25 hours, the close pending) and ``quick_closed`` (that project after ``replay``, with nothing pending); see ``tests/conftest.py``. One test
runs ``python -m flotsilica --help`` in another process from another directory (the ``-m`` entry, plan 24.1).
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import json
import contextlib
import logging
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from flotsilica import pipeline
from flotsilica.cli import build_parser
from flotsilica.config import ENV_CONFIG, ENV_HOME
from flotsilica.deliveries import MANIFEST_NAME, read_manifest
from flotsilica.lock import sole_writer
from flotsilica.pipeline import TASK_IDS
from tests.e2e.cli_helpers import FIXTURE_NAME, PROJECT_ROOT, SMALL_CONFIG, cli, fingerprint, quick_project
from tests.fixtures.pipeline_state import DAILY_ID, LAUNCH_ID

Q = ("--config", SMALL_CONFIG)


@pytest.fixture
def project(request, tmp_path, monkeypatch):
    """``project(state)``: a quick project with ``FLOTSILICA_HOME`` on it and another working directory. `state` is ``"replay"`` (a copy of the project the session's
    ``quick_replay`` left: the launch, the delivery of 25 hours and the close pending), ``"closed"`` (the state of the pipeline fixtures that has delivered the whole plan, in the
    layout of ``data/quick/``) or none (a clean clone)."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.delenv(ENV_CONFIG, raising=False)
    monkeypatch.chdir(elsewhere)

    def make(state: str | None = None, name: str = "clone") -> Path:
        if state is None:
            home = quick_project(tmp_path / name)
        else:
            home = tmp_path / name
            if state == "replay":
                shutil.copytree(request.getfixturevalue("quick_replay").home, home)
            else:      # nothing pending reads only the plan and the manifest, which are the same in the code-built configuration of the fixtures and in the overlay
                quick_project(home)
                shutil.copytree(request.getfixturevalue("pipeline_replayed").root, home / "data" / "quick")
        monkeypatch.setenv(ENV_HOME, str(home))
        return home

    make.fixture = request.getfixturevalue      # the session states themselves, for a case that only reads them
    return make


def quick(home: Path) -> Path:
    return home / "data" / "quick"


def state_of(home: Path, run_key: str) -> dict:
    return json.loads((quick(home) / "interim" / "runs" / f"{run_key}.json").read_text(encoding="utf-8"))


def runs_of(home: Path) -> set[str]:
    return {p.stem for p in (quick(home) / "interim" / "runs").glob("*.json")}


def manifest_of(home: Path) -> dict[str, str]:
    return {e.delivery_id: e.status for e in read_manifest(quick(home) / "raw" / "deliveries" / MANIFEST_NAME)}


def ok(result) -> None:
    assert result.code == 0, (result.code, result.out, result.err)


# --- AC32: each documented option, given, changes what the command does -----------------------------------------------------------------------------------------


def only(project):
    home = project("replay")
    ok(cli("run", *Q, "--only", "fetch_source", "--run-key", "A1"))
    assert list(state_of(home, "A1")["tasks"]) == ["fetch_source"] and DAILY_ID not in manifest_of(home), "fetch_source alone delivers nothing"
    ok(cli("run", *Q, "--only", "fetch_source", "deliver", "--run-key", "A2"))
    assert list(state_of(home, "A2")["tasks"]) == ["fetch_source", "deliver"] and manifest_of(home)[DAILY_ID] == "published"


def start(project):
    """``run --from load --run-key M1`` (the session's ``quick_closed``) continued the run ``M1`` that ``--only fetch_source deliver validate`` had left, without running those
    three tasks again."""
    closed = project.fixture("quick_closed")
    ok(closed.first), ok(closed.result)
    assert list(closed.tasks_before) == ["fetch_source", "deliver", "validate"]
    after = state_of(closed.home, "M1")
    assert list(after["tasks"]) == list(TASK_IDS) and after["status"] == "ok" and manifest_of(closed.home)[DAILY_ID] == "loaded"
    assert {task: after["tasks"][task] for task in closed.tasks_before} == closed.tasks_before, "the tasks before --from were not run again"
    shown = [line.split()[0] for line in closed.result.out.splitlines() if line.split() and line.split()[0] in TASK_IDS]
    assert shown == list(TASK_IDS[TASK_IDS.index("load"):])


def run_key(project):
    home = project("replay")
    base = runs_of(home)
    ok(cli("run", *Q, "--only", "fetch_source", "--run-key", "K7"))
    assert runs_of(home) == base | {"K7"}
    ok(cli("run", *Q, "--only", "fetch_source", "--run-key", "K7"))
    assert runs_of(home) == base | {"K7"}, "the same key continues the same run"
    ok(cli("run", *Q, "--only", "fetch_source"))
    new = runs_of(home) - base - {"K7"}
    assert len(new) == 1 and next(iter(new)).endswith("Z"), "without --run-key a new run takes its key from the clock"


def config(project):
    """``--config`` names the configuration the command reads: ``docs-sync`` over a configuration whose reports and README are elsewhere changes that README, not the one of
    the default configuration."""
    home = project("replay")
    elsewhere = quick(home).parent / "elsewhere"
    shutil.copytree(quick(home) / "reports", elsewhere / "reports")
    (elsewhere / "README.md").write_text("# Otro\n\n<!-- results:start -->\nviejo\n<!-- results:end -->\n", encoding="utf-8", newline="\n")
    (home / "config" / "elsewhere.toml").write_text('extends = "pipeline.small.toml"\n\n[paths]\nreports_dir = "data/elsewhere/reports"\nreadme = "data/elsewhere/README.md"\n',
                                                    encoding="utf-8", newline="\n")
    ok(cli("docs-sync", "--config", "config/elsewhere.toml"))
    assert "viejo" not in (elsewhere / "README.md").read_text(encoding="utf-8")
    assert cli("docs-sync", *Q).code == 2, "the default configuration has no README: the other one was read"


def verbose(project):
    project("replay")
    quiet = cli("run", *Q, "--only", "fetch_source", "--run-key", "V1")
    loud = cli("run", *Q, "--only", "fetch_source", "--run-key", "V2", "-v")
    ok(quiet), ok(loud)
    assert " INFO " not in quiet.err and " INFO flotsilica." in loud.err, (quiet.err, loud.err)


def until(project):
    """``replay --until`` (the session's ``quick_replay``) ran the launch and stopped there: the two deliveries after it, pending, were not run."""
    replay = project.fixture("quick_replay")
    ok(replay.result)
    assert manifest_of(replay.home) == {LAUNCH_ID: "loaded"} and replay.result.out.rstrip().endswith("1 corrida")
    assert f"entrega {LAUNCH_ID}" in replay.result.out and f"entrega {DAILY_ID}" not in replay.result.out


def task(project):
    home = project("replay")
    ok(cli("task", "fetch_source", *Q, "--run-key", "T1"))
    assert list(state_of(home, "T1")["tasks"]) == ["fetch_source"]
    ok(cli("task", "deliver", *Q, "--run-key", "T1"))
    assert list(state_of(home, "T1")["tasks"]) == ["fetch_source", "deliver"]


def task_run_key(project):
    home = project("replay")
    base = runs_of(home)
    ok(cli("task", "fetch_source", *Q, "--run-key", "T2"))
    ok(cli("task", "fetch_source", *Q))
    assert "T2" in runs_of(home) and len(runs_of(home) - base - {"T2"}) == 1


def written(home: Path, *args: str):
    """``make-fixture`` of one week at the fewest rows per hour (the cases cost little; a later option wins over these two) to ``data/quick/<name>`` with `args`; the bytes it wrote."""
    name, *rest = args
    result = cli("make-fixture", f"data/quick/{name}", "--weeks", "1", "--rows-per-hour", "4", *rest)
    ok(result)
    return (quick(home) / name).read_bytes(), result


def make_fixture_output(project):
    home = project()
    data, result = written(home, "made.arff")
    assert data.startswith(b"%") and not (Path.cwd() / "data").exists() and list(Path.cwd().iterdir()) == [], "resolved against the project, not the working directory"
    assert "señal none" in result.out and str(quick(home) / "made.arff") in result.out


def make_fixture_rows_per_hour(project):
    home = project()
    default, _ = written(home, "a.arff")
    other, _ = written(home, "b.arff", "--rows-per-hour", "6")
    assert default != other and len(other) > len(default), "six rows an hour are more than four"


def make_fixture_seed(project):
    home = project()
    first, _ = written(home, "a.arff", "--seed", "0")
    second, _ = written(home, "b.arff", "--seed", "1")
    again, _ = written(home, "c.arff", "--seed", "0")
    assert first != second and first == again, "the seed is the only difference, and the same seed is the same file"


def make_fixture_signal(project):
    home = project()
    plain, _ = written(home, "a.arff")
    signal, result = written(home, "b.arff", "--signal", "sensor_signal")
    lab_only, _ = written(home, "c.arff", "--signal", "lab_only")
    assert len({plain, signal, lab_only}) == 3 and "señal sensor_signal" in result.out


def make_fixture_weeks(project):
    home = project()
    one, _ = written(home, "a.arff")
    ok(cli("make-fixture", "data/quick/b.arff", "--weeks", "3", "--rows-per-hour", "4"))
    assert len((quick(home) / "b.arff").read_bytes()) > len(one), "three weeks are more than one (the second is the plant gap)"


def figures(project):
    home = project("replay")
    from flotsilica.figures import FIGURE_NAMES

    result = cli("figures", *Q)
    ok(result)
    assert sorted(p.name for p in (quick(home) / "figures").iterdir()) == sorted(FIGURE_NAMES) and result.out.count("escribí") == len(FIGURE_NAMES)


def docs_sync(project):
    home = project("replay")
    readme = quick(home) / "README.md"
    readme.write_text("# Proyecto\n\n<!-- results:start -->\nviejo\n<!-- results:end -->\n\nFin.\n", encoding="utf-8", newline="\n")
    result = cli("docs-sync", *Q)
    ok(result)
    text = readme.read_text(encoding="utf-8")
    summary = (quick(home) / "reports" / "evaluation_summary.md").read_text(encoding="utf-8").strip()
    assert "viejo" not in text and text == f"# Proyecto\n\n<!-- results:start -->\n{summary}\n<!-- results:end -->\n\nFin.\n" and "actualizado" in result.out
    again = cli("docs-sync", *Q)
    ok(again)
    assert "ya estaba al día" in again.out and readme.read_text(encoding="utf-8") == text


@contextlib.contextmanager
def uvicorn_calls():
    """``uvicorn.run`` replaced by a recorder of ``(app, options)``: ``serve`` runs the real app of the project, only the server that would block is left out."""
    calls = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("uvicorn.run", lambda app, **options: calls.append((app, options)))
        yield calls


def serve_port(project):
    from fastapi import testclient

    project("replay")
    with uvicorn_calls() as calls:
        ok(cli("serve", *Q))
        ok(cli("serve", *Q, "--port", "8123"))
    assert [(options["host"], options["port"]) for _app, options in calls] == [("127.0.0.1", 8000), ("127.0.0.1", 8123)], "the default is the [api] port of the configuration"
    health = testclient.TestClient(calls[0][0]).get("/health")
    assert health.status_code == 200 and health.json()["status"] == "ok" and health.json()["seal"] == "launch", "the app that was handed to the server is the one of the sealed model"


def serve_host(project):
    project("replay")
    with uvicorn_calls() as calls:
        ok(cli("serve", *Q, "--host", "127.0.0.1"))
        refused = cli("serve", *Q, "--host", "0.0.0.0")
    assert [options["host"] for _app, options in calls] == ["127.0.0.1"], "the loopback address is accepted, any other one never reaches the server"
    assert refused.code == 2 and "127.0.0.1" in refused.err and refused.out == ""


OPTIONS = {
    "--config": config, "-v": verbose, "run --only": only, "run --from": start, "run --run-key": run_key, "replay --until": until, "task TAREA": task,
    "task --run-key": task_run_key, "make-fixture SALIDA.arff": make_fixture_output, "make-fixture --rows-per-hour": make_fixture_rows_per_hour,
    "make-fixture --seed": make_fixture_seed, "make-fixture --signal": make_fixture_signal, "make-fixture --weeks": make_fixture_weeks, "figures": figures,
    "docs-sync": docs_sync, "serve --host": serve_host, "serve --port": serve_port,
}


def documented() -> set[str]:
    """What the parser documents, in the names of ``OPTIONS``: the options both ``--config`` and ``-v`` stand for, the options and positionals of each command and, for a
    command that has only those shared ones, the command itself."""
    found: set[str] = set()
    commands = next(a for a in build_parser(TASK_IDS)._actions if a.dest == "command").choices
    for name, sub in commands.items():
        own = [a for a in sub._actions if a.dest not in ("help", "config", "verbose")]
        found |= {f"{name} {a.option_strings[-1] if a.option_strings else a.metavar}" for a in own}
        found |= {"--config", "-v"} if any(a.dest == "config" for a in sub._actions) else set()
        found |= {name} if not own else set()
    return found


def test_every_option_the_parser_documents_has_its_case():
    assert set(OPTIONS) == documented()


@pytest.mark.parametrize("option", list(OPTIONS))
def test_every_documented_option_changes_the_result(option, project):
    """AC32 (project 01, B2; project 02, B1): no option is ignored in silence; each one, given, changes what the command does."""
    OPTIONS[option](project)


# --- refusals before writing and the exit codes ------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("args", "says"), [
    (("run", *Q, "--only", "load", "--from", "load"), "--only y --from no se combinan"),
    (("run", *Q, "--run-key", "X1"), "--run-key necesita --only o --from"),
    (("run", *Q, "--only", "load"), "una corrida nueva empieza por fetch_source"),
    (("run", *Q, "--from", "validate"), "una corrida nueva empieza por fetch_source"),
    (("run", *Q, "--only", "nope"), "invalid choice"),
    (("task", "nope", *Q), "invalid choice"),
    (("replay", *Q, "--until", "Z2099-01"), "no es una entrega del plan"),
    (("replay", *Q, "--until", LAUNCH_ID), f"es anterior a la siguiente entrega pendiente, {DAILY_ID}"),
    (("docs-sync", *Q), "el modo rápido no tiene README"),
    (("run", "--config", "config/missing.toml", "--only", "fetch_source", "--run-key", "X2"), "missing.toml"),
    (("make-fixture", "../outside.arff"), "sale de la carpeta del proyecto"),
    (("make-fixture", "data/quick/x.arff", "--rows-per-hour", "1"), "rows_per_hour"),
    (("make-fixture", "data/quick/x.arff", "--weeks", "0"), "weeks"),
    (("make-fixture", "data/quick/x.arff", "--signal", "loud"), "invalid choice"),
])
def test_incompatible_options_exit_2_before_writing(project, tmp_path, args, says):
    home = project("replay" if LAUNCH_ID in args else None)      # only the refusal that reads the manifest needs a project that has delivered
    before, folders = fingerprint(tmp_path), sorted(p for p in tmp_path.rglob("*") if p.is_dir())
    result = cli(*args)
    assert result.code == 2 and says in result.err and result.out == "", (result.code, result.out, result.err)
    assert fingerprint(tmp_path) == before and list(Path.cwd().iterdir()) == [], "nothing written, in the project, beside it or in the working directory"
    assert sorted(p for p in tmp_path.rglob("*") if p.is_dir()) == folders, "and no folder made for it"
    assert not (home.parent / "outside.arff").exists()


@pytest.mark.parametrize("host", ["0.0.0.0", "localhost", "::1", "192.168.0.7", "127.0.0.2", ""])
def test_serve_refuses_a_host_other_than_loopback_before_loading(project, monkeypatch, tmp_path, host):
    """AC28, D27: the service never listens outside this machine, and the refusal comes before the configuration is read, the API is imported or a model is loaded."""
    project("replay")

    def loaded(*args, **kwargs):
        raise AssertionError("something was loaded before the host was refused")

    monkeypatch.setattr("flotsilica.cli.load_config", loaded)
    monkeypatch.setattr("flotsilica.api.create_app", loaded)
    monkeypatch.setattr("uvicorn.run", loaded)
    monkeypatch.delitem(sys.modules, "flotsilica.api")      # an import of the API in the refusal would bring it back
    before = fingerprint(tmp_path)
    result = cli("serve", "--host", host)
    assert result.code == 2 and "127.0.0.1" in result.err and result.out == "", (result.code, result.out, result.err)
    assert "flotsilica.api" not in sys.modules and fingerprint(tmp_path) == before and list(Path.cwd().iterdir()) == []


@pytest.mark.parametrize("port", ["0", "-1", "65536"])
def test_serve_refuses_a_port_outside_1_to_65535_before_loading(project, monkeypatch, tmp_path, port):
    project("replay")
    monkeypatch.setattr("flotsilica.cli.load_config", lambda *args: pytest.fail("the configuration was read before the port was refused"))
    before = fingerprint(tmp_path)
    result = cli("serve", "--port", port)
    assert result.code == 2 and "1 a 65535" in result.err and result.out == "" and fingerprint(tmp_path) == before


def test_serve_without_a_model_to_serve_exits_2_says_why_and_starts_no_server(project, tmp_path):
    """No seal (a clean clone), and a model file that is not the registered one: each is a refusal of the start with 2, not a server that cannot answer."""
    home = project()
    before = fingerprint(home)
    with uvicorn_calls() as calls:
        clean = cli("serve", *Q)
        replayed = project("replay", name="replayed")
        artifact = next((quick(replayed) / "models").rglob("*.pkl"))
        artifact.write_bytes(artifact.read_bytes() + b"\0")
        altered = cli("serve", *Q)
    assert (clean.code, clean.out, "no hay sello" in clean.err) == (2, "", True) and fingerprint(home) == before
    assert (altered.code, altered.out, "M03" in altered.err) == (2, "", True) and calls == []


def test_docs_sync_without_the_summary_or_without_its_markers_exits_2_and_leaves_the_readme_as_it_was(project):
    home = project("replay")
    readme = quick(home) / "README.md"
    readme.write_text("# Proyecto\n\n<!-- results:start -->\nviejo\n<!-- results:end -->\n", encoding="utf-8", newline="\n")
    summary = quick(home) / "reports" / "evaluation_summary.md"
    kept = summary.read_bytes()
    summary.unlink()
    before = fingerprint(home)
    result = cli("docs-sync", *Q)
    assert result.code == 2 and "evaluation_summary.md" in result.err and "corra la tarea report" in result.err and result.out == "", (result.code, result.err)
    assert fingerprint(home) == before
    summary.write_bytes(kept)
    readme.write_text("# Proyecto\n\nsin marcadores\n", encoding="utf-8", newline="\n")
    before = fingerprint(home)
    result = cli("docs-sync", *Q)
    assert result.code == 2 and "debe tener una vez" in result.err and result.out == "" and fingerprint(home) == before


def test_a_task_that_fails_exits_1_and_says_why(project, monkeypatch):
    home = project("replay")

    def broken(*args, **kwargs):
        raise ValueError("the task's own error")

    ok(cli("run", *Q, "--only", "fetch_source", "deliver", "--run-key", "F1"))
    monkeypatch.setattr(pipeline, "validate_delivery", broken)
    result = cli("run", *Q, "--only", "validate", "--run-key", "F1")
    assert result.code == 1 and "falló: ValueError: the task's own error" in result.err and "Traceback" not in result.err, (result.code, result.err)
    assert state_of(home, "F1")["status"] == "failed" and state_of(home, "F1")["tasks"]["validate"]["status"] == "failed"
    verbose_run = cli("task", "validate", *Q, "--run-key", "F1", "-v")
    assert verbose_run.code == 1 and "Traceback" in verbose_run.err, "-v adds the traceback"


def test_a_rejected_delivery_or_source_exits_3_and_writes_nothing_to_the_warehouse(project):
    home = project("replay")
    warehouse = quick(home) / "flotsilica.sqlite"
    ok(cli("run", *Q, "--only", "fetch_source", "deliver", "--run-key", "R1"))
    deliveries = quick(home) / "raw" / "deliveries"
    shutil.copy2(deliveries / f"{LAUNCH_ID}.hours.parquet", deliveries / f"{DAILY_ID}.hours.parquet")      # the published file is no longer the one the manifest hashed (V13)
    before = warehouse.read_bytes()
    delivery = cli("task", "validate", *Q, "--run-key", "R1")
    assert delivery.code == 3 and "rechazada" in delivery.err and "V13" in delivery.err, (delivery.code, delivery.err)
    assert state_of(home, "R1")["status"] == "rejected" and warehouse.read_bytes() == before and manifest_of(home)[DAILY_ID] == "rejected"
    source = quick(home) / FIXTURE_NAME
    source.write_bytes(source.read_bytes() + b"\n")                           # another file than the one registered: V01
    rejected = cli("run", *Q, "--only", "fetch_source", "--run-key", "R2")
    assert rejected.code == 3 and "rechazada" in rejected.err and "V01" in rejected.err, (rejected.code, rejected.err)
    assert warehouse.read_bytes() == before


def test_a_closed_run_or_a_held_lock_exits_2_and_writes_nothing(project):
    home = project("replay")
    before = fingerprint(home)
    closed = cli("task", "report", *Q, "--run-key", min(runs_of(home)))      # the first run: the launch, closed
    assert closed.code == 2 and "está cerrada" in closed.err and fingerprint(home) == before
    taken, done = threading.Event(), threading.Event()

    def holder():
        with sole_writer(quick(home) / "interim", "run", "other"):
            taken.set()
            done.wait(timeout=60)

    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert taken.wait(timeout=60)
        locked = cli("run", *Q, "--only", "fetch_source", "--run-key", "Z1")
    finally:
        done.set()
        thread.join(timeout=60)
    assert locked.code == 2 and "escribe esta carpeta de datos" in locked.err and "Z1" not in runs_of(home), locked.err


def test_a_replay_with_nothing_pending_exits_0_without_the_lock(project, monkeypatch):
    home = project("closed")
    taken = []
    monkeypatch.setattr(pipeline, "sole_writer", lambda *a, **k: taken.append(a) or (_ for _ in ()).throw(AssertionError("the lock was taken")))
    before = fingerprint(home)
    result = cli("replay", *Q)
    assert result.code == 0 and "No hay entregas pendientes" in result.out and taken == [] and fingerprint(home) == before, (result.code, result.err)


def test_figures_over_a_folder_that_is_not_one_export_exits_2_and_writes_nothing(project):
    home = project("replay")
    (quick(home) / "outputs" / "site" / "summary.json").write_text("{}\n", encoding="utf-8", newline="\n")
    refused = cli("figures", *Q)
    assert refused.code == 2 and "summary.json" in refused.err and "No se escribió ninguna figura" in refused.err and not (quick(home) / "figures").exists(), refused.err


@pytest.mark.slow
def test_module_entry_point_runs_from_another_directory(tmp_path):
    """The ``-m`` entry, in another process from another directory: the help lists every command and nothing is written."""
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
    env.pop(ENV_CONFIG, None)
    env.pop(ENV_HOME, None)
    done = subprocess.run([sys.executable, "-m", "flotsilica", "--help"], cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert done.returncode == 0, done.stderr
    for command in ("run", "replay", "task", "make-fixture", "figures", "docs-sync", "serve"):
        assert command in done.stdout, command
    assert list(tmp_path.iterdir()) == []


class _Blocked(importlib.abc.MetaPathFinder):
    """A finder that makes ``tests.fixtures.make_fixture`` fail to import with the error of `name` (a missing ``tests`` tree, or a module the generator needs)."""

    def __init__(self, name: str) -> None:
        self.name = name

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "tests.fixtures.make_fixture":
            raise ModuleNotFoundError(f"No module named {self.name!r}", name=self.name)
        return None


def test_make_fixture_without_the_tests_tree_says_so_and_exits_2(project, monkeypatch):
    """The generator lives with the tests, so a project folder that holds only ``src/`` (as the Airflow image's does) cannot run ``make-fixture``: it exits 2 with a message that
    says where the generator is, not with a traceback, and writes nothing."""
    home = project()
    monkeypatch.delitem(sys.modules, "tests.fixtures.make_fixture", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_Blocked("tests"), *sys.meta_path])
    before = fingerprint(home)
    result = cli("make-fixture", "data/quick/out.arff")
    assert result.code == 2 and result.out == "" and result.err.startswith("error: ") and "tests/fixtures/make_fixture.py" in result.err and "Traceback" not in result.err
    assert fingerprint(home) == before


def test_make_fixture_does_not_hide_a_missing_dependency_of_the_generator_as_a_missing_tests_tree(project, monkeypatch):
    """The message about the absent ``tests`` folder is only for that: a module the generator itself imports that is not installed stays the ``ModuleNotFoundError`` it is."""
    project()
    monkeypatch.delitem(sys.modules, "tests.fixtures.make_fixture", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_Blocked("numpy"), *sys.meta_path])
    with pytest.raises(ModuleNotFoundError, match="numpy"):
        cli("make-fixture", "data/quick/out.arff")


def test_the_logging_of_a_second_call_replaces_the_first(project):
    """Two calls in one process (as the tests make): ``-v`` takes effect each time and a handler is not added twice."""
    project("replay")
    cli("run", *Q, "--only", "fetch_source", "--run-key", "H1", "-v")
    cli("run", *Q, "--only", "fetch_source", "--run-key", "H2")
    handlers = [h for h in logging.getLogger("flotsilica").handlers if getattr(h, "_flotsilica_cli", False)]
    assert len(handlers) == 1 and logging.getLogger("flotsilica").level == logging.WARNING
