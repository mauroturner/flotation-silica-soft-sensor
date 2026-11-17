"""The quick mode, isolated (U18, AC33; RNF04; D31): from another working directory, with ``FLOTSILICA_HOME`` on a clean clone of the project's configuration, the documented
commands write only under ``data/quick/``: not a byte and not a modification time anywhere else of the clone, nothing in the working directory, and nothing in this
repository's project.

Project 01 wrote its quick run over the versioned outputs and resolved a relative path against the directory of the command. The replay is the session's ``quick_replay``
(``tests/conftest.py``): ``make-fixture`` and ``replay --until`` (the launch) of the small fixture over a clone that has only ``config/`` and the small overlay of the quick configuration
(three weeks instead of the whole calendar, which the fast suite cannot afford: plan, section 24.1).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flotsilica.config import ENV_HOME, load_config
from flotsilica.pipeline import TASK_IDS
from tests.e2e.cli_helpers import FIXTURE_NAME, PROJECT_ROOT, SMALL_CONFIG
from tests.fixtures.pipeline_state import LAUNCH_ID

QUICK = "data/quick/"


def changed(before: dict, after: dict) -> set[str]:
    return {name for name in set(before) | set(after) if before.get(name) != after.get(name)}


@pytest.mark.slow
def test_quick_replay_from_other_cwd_touches_only_data_quick(quick_replay, small_truth):
    """AC33: the fixture and the replay end with 0, every file they created or changed is under ``data/quick/`` of the clone, the working directory stays empty and this
    repository's project is as it was."""
    assert quick_replay.made.code == 0 and quick_replay.result.code == 0, (quick_replay.made.err, quick_replay.result.err)
    assert set(quick_replay.before) == {f"config/{p.name}" for p in (PROJECT_ROOT / "config").iterdir()} | {SMALL_CONFIG}, "the clone was clean: only its configuration"
    touched = changed(quick_replay.before, quick_replay.after)
    assert touched and all(name.startswith(QUICK) for name in touched), sorted(n for n in touched if not n.startswith(QUICK))
    assert list(Path(quick_replay.elsewhere).iterdir()) == [], "nothing in the directory the commands were started from"
    assert changed(quick_replay.real_before, quick_replay.real_after) == set(), "the repository's project was not touched"
    quick = Path(quick_replay.home) / "data" / "quick"
    for name in (FIXTURE_NAME, "source.lock.json", "flotsilica.sqlite", "outputs/powerbi/manifest.json", "outputs/site/manifest.json", "dashboard/powerbi-design.html",
                 "reports/evaluation_summary.json", "reports/model_seal.json"):
        assert (quick / name).is_file(), name
    assert (quick / FIXTURE_NAME).read_bytes() == Path(small_truth.path).read_bytes(), "make-fixture --weeks 3 writes the small fixture of the session"
    assert {"flotsilica.sqlite", "dashboard/powerbi-design.html", "outputs/site/summary.json"} <= {n[len(QUICK):] for n in touched}, "the run wrote its outputs"


def test_the_quick_replay_ran_every_task_of_its_run(quick_replay):
    shown = [line.split()[0] for line in quick_replay.result.out.splitlines() if line.strip() and line.split()[0] in TASK_IDS]
    assert shown == list(TASK_IDS), quick_replay.result.out
    assert f"entrega {LAUNCH_ID}" in quick_replay.result.out and quick_replay.result.out.rstrip().endswith("1 corrida")
    assert "escribí" in quick_replay.made.out and "señal none" in quick_replay.made.out


def test_the_runs_after_the_launch_write_only_under_data_quick_too(quick_closed):
    """The delivery of 25 hours runs the model in verify mode, scores every hour and evaluates the test: other writes than the launch's, from another working directory too."""
    assert quick_closed.first.code == 0 and quick_closed.result.code == 0, (quick_closed.first.err, quick_closed.result.err)
    touched = changed(quick_closed.before, quick_closed.after)
    assert touched and all(name.startswith(QUICK) for name in touched), sorted(n for n in touched if not n.startswith(QUICK))
    assert list(Path(quick_closed.elsewhere).iterdir()) == []


def test_every_path_of_the_quick_configuration_is_under_data_quick(monkeypatch):
    monkeypatch.delenv(ENV_HOME, raising=False)
    cfg = load_config(Path("config/pipeline.quick.toml"))
    quick = (PROJECT_ROOT / "data" / "quick").resolve()
    paths = [cfg.source.path, *vars(cfg.paths).values()]
    assert all(Path(p).resolve().is_relative_to(quick) for p in paths), [str(p) for p in paths]
