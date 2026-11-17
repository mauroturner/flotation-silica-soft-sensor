"""Helpers of the command-line and quick-mode tests (U18): a command of the CLI run in this process, a clean quick clone and the fingerprint of a folder.

A clean quick clone is a folder with a copy of ``config/`` (what a clone has that the commands read; the SQL comes with the package) and the overlay
``config/pipeline.small.toml``: the quick configuration over the windows of the small fixture (three weeks), which the fast suite can afford where the whole calendar of the quick
configuration cannot (plan, section 24.1). With ``FLOTSILICA_HOME`` on the clone the command line writes under its ``data/quick/``.
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

from flotsilica.config import ENV_CONFIG, ENV_HOME

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUICK_CONFIG = "config/pipeline.quick.toml"
SMALL_CONFIG = "config/pipeline.small.toml"
FIXTURE_NAME = "flotation_fixture.arff"
SKIPPED = {".venv", ".git", "__pycache__", ".pytest_cache"}

# The windows of ``tests/fixtures/tiny_model.small_view`` and of ``pipeline_state.pipeline_config`` (the small fixture: the launch up to 2017-03-29 23:00, a delivery of
# 25 hours and the close) as a configuration file over the quick one. Those fixtures build their configuration in code, past the checks of ``load_config``, with blocks that
# touch; a file goes through them, so the purge between blocks is 0 hours (``purge_hours`` accepts 0) and the blocks are the same.
SMALL_OVERLAY = """extends = "pipeline.quick.toml"

[hours]
last_hour = 2017-03-31T00:00:00

[deliveries]
launch_last_hour = 2017-03-29T23:00:00
cadence_hours = 25

[split]
train_last = 2017-03-13T23:00:00
v1_first = 2017-03-14T00:00:00
v1_last = 2017-03-15T03:00:00
v2_first = 2017-03-15T04:00:00
v2_last = 2017-03-16T05:00:00
test_first = 2017-03-30T00:00:00
test_last = 2017-03-30T23:00:00
purge_hours = 0
min_fresh_hours_per_block = 5

[model]
rf_min_samples_leaf = [3]
rf_n_estimators = 5
"""


def cli(*args: str) -> SimpleNamespace:
    """``python -m flotsilica <args>`` in this process (``cli.main``): its exit code and what it wrote to stdout and stderr."""
    from flotsilica.cli import main

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(args))
    return SimpleNamespace(code=code, out=out.getvalue(), err=err.getvalue())


def quick_project(dest: Path) -> Path:
    """A clean quick clone at `dest`: ``config/`` and the small overlay, and nothing else."""
    dest = Path(dest)
    shutil.copytree(PROJECT_ROOT / "config", dest / "config")
    (dest / SMALL_CONFIG).write_text(SMALL_OVERLAY, encoding="utf-8", newline="\n")
    return dest


def fingerprint(root: Path, skipped: set[str] = SKIPPED) -> dict[str, tuple[int, int]]:
    """Size and modification time of every file under `root` (the environment and the caches left out)."""
    found = {}
    for folder, names, files in os.walk(root):
        names[:] = [n for n in names if n not in skipped]
        for name in files:
            path = Path(folder) / name
            stat = path.stat()
            found[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return found


@contextlib.contextmanager
def at_home(home: Path, cwd: Path):
    """``FLOTSILICA_HOME`` on `home`, no ``FLOTSILICA_CONFIG`` and `cwd` as the working directory, all restored afterwards (for a session fixture, where ``monkeypatch`` is
    not available)."""
    saved = {k: os.environ.get(k) for k in (ENV_HOME, ENV_CONFIG)}
    before = Path.cwd()
    os.environ[ENV_HOME] = str(home)
    os.environ.pop(ENV_CONFIG, None)
    os.chdir(cwd)
    try:
        yield
    finally:
        os.chdir(before)
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
