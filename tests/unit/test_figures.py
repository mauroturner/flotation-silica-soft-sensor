"""The figures of the documentation (U15, AC27; RF26; plan, sections 21 and 25), drawn with matplotlib from the verified site files of the small history (``site_files``): the seven
files, the data behind each one, nothing drawn from another source, the figures of the test saying so before the seal, and nothing written when a file is not the one its manifest
names. Adapted from project 04's ``tests/unit/test_figures.py``."""

from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import json
import shutil
from pathlib import Path

import matplotlib.image as mpimg
import pytest

from flotsilica import figures, texts
from flotsilica.site_export import SiteFiles, SiteSetError

EXPECTED = ["lab_states_by_block.png", "interpolated_run.png", "horizons_mae.png", "test_day_example.png", "weekly_mae.png", "latency.png", "sensitivity_gate.png"]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FIGURES_PY = Path(figures.__file__)
STATES = ("fresh", "held", "interpolated", "missing", "pending")


def refresh_manifest(folder: Path) -> None:
    """The manifest of `folder` rewritten for the bytes its files hold now: a test that edits a site file keeps the folder one export."""
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    for name in manifest["files"]:
        data = (folder / name).read_bytes()
        manifest["files"][name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture(scope="module")
def site(site_files) -> SiteFiles:
    return figures.load_site(site_files.out_dir)


@pytest.fixture(scope="module")
def drawn(site) -> dict:
    return figures.draw_all(site)


def edited(site: SiteFiles, **documents) -> SiteFiles:
    """A copy of the site documents with the given ones replaced (a deep copy, so no test changes what another one reads)."""
    return dataclasses.replace(copy.deepcopy(site), **documents)


# --- the RED of U15 ---------------------------------------------------------------------------------------------------------------------


def test_figures_are_drawn_only_from_the_verified_site_files(figures_written, site_files, tmp_path):
    """AC27 (project 03, D77): the seven PNG files come from the site files read through ``read_site`` (each checked against ``manifest.json``), the module reads nothing else (no
    warehouse, no Parquet), and a folder whose file is not the one its manifest names is refused with nothing written."""
    out, paths, _bytes = figures_written
    assert [p.name for p in paths] == EXPECTED == list(figures.FIGURE_NAMES)
    assert sorted(p.name for p in out.iterdir()) == sorted(EXPECTED), "the figure of an earlier run is replaced and nothing else is left, not even a temporary file"
    for path in paths:
        assert path.read_bytes()[:8] == PNG_SIGNATURE
        height, width = mpimg.imread(path).shape[:2]
        assert width >= 900 and height >= 450, "readable at the full width of a README"
    tree = ast.parse(FIGURES_PY.read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not imported & {"sqlite3", "pandas", "pyarrow", "flotsilica.warehouse", "flotsilica.export", "flotsilica.pipeline", "flotsilica.registry"}, imported
    assert "read_site" in {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "flotsilica.site_export" for a in n.names}
    mixed = tmp_path / "mixed"
    shutil.copytree(site_files.out_dir, mixed)
    document = json.loads((mixed / "algorithms.json").read_text(encoding="utf-8"))
    document["sensitivity"][0]["importance_v1"] = 0.999
    (mixed / "algorithms.json").write_text(json.dumps(document), encoding="utf-8")       # the manifest still names the old bytes
    with pytest.raises(SiteSetError, match="algorithms.json"):
        figures.write_figures(mixed, tmp_path / "out")
    assert not (tmp_path / "out").exists()


# --- the files ----------------------------------------------------------------------------------------------------------------------


def test_drawing_twice_gives_the_same_files_and_a_figure_changes_only_with_its_data(site_files, drawn, figures_written, tmp_path):
    names = ("lab_states_by_block.png", "latency.png", "sensitivity_gate.png")
    again = {name: figures._png(drawn[name]) for name in names}      # the module's second rendering of the same files
    assert again == {name: figures_written[2][name] for name in names}, "a versioned figure changes only when its data do"
    changed = tmp_path / "site"
    shutil.copytree(site_files.out_dir, changed)
    document = json.loads((changed / "algorithms.json").read_text(encoding="utf-8"))
    document["sensitivity"][0]["importance_v2"] += 0.05
    (changed / "algorithms.json").write_text(json.dumps(document), encoding="utf-8")
    refresh_manifest(changed)
    made = figures.draw_all(figures.load_site(changed))
    assert {name for name in names if figures._png(made[name]) != figures_written[2][name]} == {"sensitivity_gate.png"}


def test_nothing_is_written_if_a_figure_fails_or_a_site_file_is_missing(site_files, tmp_path, monkeypatch):
    out = tmp_path / "figures"
    monkeypatch.setattr(figures, "draw_latency", lambda _site: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        figures.write_figures(site_files.out_dir, out)
    assert not out.exists()
    monkeypatch.undo()
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(FileNotFoundError, match=r"summary\.json.*python -m flotsilica run"):
        figures.write_figures(bare, out)
    assert not out.exists()


def test_nothing_is_written_if_one_of_the_files_cannot_be_written(site_files, drawn, tmp_path, monkeypatch):
    """A write that fails halfway (a full disk, a permission) replaces no figure of an earlier run, leaves no temporary file and no new folder behind: the files are all staged first
    and replaced only when every one was written."""
    out = tmp_path / "figures"
    out.mkdir()
    (out / "latency.png").write_bytes(b"old")
    monkeypatch.setattr(figures, "draw_all", lambda _site: drawn)                # what is under test is the staging of the files, not the drawing
    monkeypatch.setattr(figures, "_png", lambda _figure: b"a figure")
    real, calls = Path.write_bytes, []

    def write_bytes(self, data):
        if self.name.endswith(".tmp") and ".png." in self.name:
            calls.append(self.name)
            if len(calls) == 4:
                raise OSError(28, "No space left on device")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", write_bytes)
    with pytest.raises(OSError, match="No space left"):
        figures.write_figures(site_files.out_dir, out)
    assert len(calls) == 4, "the fourth file was the one that failed"
    assert {p.name: p.read_bytes() for p in out.iterdir()} == {"latency.png": b"old"}, "no figure replaced and no temporary file left"
    fresh = tmp_path / "fresh"
    calls.clear()
    with pytest.raises(OSError, match="No space left"):
        figures.write_figures(site_files.out_dir, fresh)
    assert not fresh.exists(), "a folder the call created is removed with the files it never got"


# --- the data behind each figure -------------------------------------------------------------------------------------------------------------


def test_the_states_figure_draws_the_hours_of_each_state_in_each_block(drawn, site):
    [ax] = drawn["lab_states_by_block.png"].axes
    blocks = site.data["states_by_block"]
    assert [p.get_height() for p in ax.patches] == [float(b[state]) for state in STATES for b in blocks]
    assert [t.get_text() for t in ax.get_xticklabels()] == [b["label_es"] for b in blocks]


def test_the_interpolated_run_is_drawn_as_a_straight_line_between_the_two_analyses(drawn, site):
    [ax] = drawn["interpolated_run.png"].axes
    run = site.data["interpolated_run"]
    line, points = ax.lines
    assert list(line.get_xdata()) == [0, len(run["values"]) + 1] and list(line.get_ydata()) == [run["start_value"], run["end_value"]]
    assert list(points.get_xdata()) == list(range(1, len(run["values"]) + 1)) and list(points.get_ydata()) == run["values"]


def test_the_horizons_figure_draws_the_error_of_each_method_in_v1_v2_and_the_test(drawn, site):
    axes = drawn["horizons_mae.png"].axes
    assert len(axes) == len(site.algorithms["horizons"]) == 3
    for ax, horizon in zip(axes, site.algorithms["horizons"], strict=True):
        methods = horizon["methods"]
        assert [p.get_height() for p in ax.patches] == [0.0 if m[k] is None else m[k] for k in ("mae_v1", "mae_v2", "mae_test") for m in methods]
        assert [t.get_text() for t in ax.get_xticklabels()] == [figures.SHORT_ES[m["method"]] for m in methods]


def test_the_day_figure_draws_the_estimate_with_its_range_the_analyses_and_the_persistence_of_each_example_day(drawn, site):
    axes = drawn["test_day_example.png"].axes
    hours, days = site.operation["test_hours"], site.operation["example_days"]
    assert len(axes) == 3
    for ax, key in zip(axes, ("median", "worst", "best"), strict=True):
        wanted = [i for i, h in enumerate(hours["hour"]) if h.startswith(days[key]["date"])]
        estimate, persistence = ax.lines
        assert list(estimate.get_ydata()) == [hours["estimate"][i] for i in wanted] and list(persistence.get_ydata()) == [hours["persistence"][i] for i in wanted]
        assert list(estimate.get_xdata()) == [int(hours["hour"][i][11:13]) for i in wanted]
        [actual] = [c for c in ax.collections if c.get_label() == "Análisis"]
        assert len(actual.get_offsets()) == sum(hours["actual"][i] is not None for i in wanted)


def test_the_weekly_figure_draws_the_error_of_the_model_the_persistence_and_b_star_by_week(drawn, site):
    axes = drawn["weekly_mae.png"].axes
    assert len(axes) == 3
    for ax, horizon in zip(axes, range(3), strict=True):
        weeks = [w for w in site.operation["weekly"] if w["horizon"] == horizon]
        model, persistence, b_star = ax.lines
        assert list(model.get_xdata()) == [w["week"] for w in weeks]
        assert list(model.get_ydata()) == [w["mae_model"] for w in weeks] and list(persistence.get_ydata()) == [w["mae_persistence"] for w in weeks]
        assert list(b_star.get_ydata()) == [w["mae_b_star"] for w in weeks]


def test_the_latency_figure_draws_the_error_of_the_model_and_of_the_persistence_for_each_latency(drawn, site):
    [ax] = drawn["latency.png"].axes
    rows = site.algorithms["latency"]
    assert [p.get_height() for p in ax.patches] == [0.0 if r[k] is None else r[k] for k in ("mae_model", "mae_persistence") for r in rows]
    assert [t.get_text() for t in ax.get_xticklabels()] == [f"{r['latency_hours']} h" for r in rows]


def test_the_gate_figure_draws_the_importance_of_each_sensor_against_the_line_of_the_gate(drawn, site):
    [ax] = drawn["sensitivity_gate.png"].axes
    sensors = site.algorithms["sensitivity"]
    assert [p.get_width() for p in ax.patches] == [s["importance_v1"] for s in sensors] + [s["importance_v2"] for s in sensors]
    assert [t.get_text() for t in ax.get_yticklabels()] == [s["name_es"] for s in sensors]
    [gate] = ax.lines
    assert list(gate.get_xdata()) == [site.algorithms["gate"]["min_importance_mae"]] * 2
    title = " ".join(t.get_text() for t in drawn["sensitivity_gate.png"].texts)
    assert texts.ASSOCIATION_ES in title and texts.sensitivity_problems(title) == []


# --- before the seal, without data and the words -------------------------------------------------------------------------------------------


def test_before_the_seal_the_figures_of_the_test_say_so_instead_of_staying_empty(site):
    early = edited(site)
    early.operation["test_hours"] = {k: [] for k in early.operation["test_hours"]}
    early.operation.update(daily=[], weekly=[], example_days={"median": None, "worst": None, "best": None})
    for horizon in early.algorithms["horizons"]:
        for method in horizon["methods"]:
            method["mae_test"] = None
    for row in early.algorithms["latency"]:
        row.update(mae_model=None, mae_persistence=None, ci_low=None, ci_high=None)
    made = figures.draw_all(early)
    for name in ("test_day_example.png", "weekly_mae.png", "latency.png"):
        assert figures.PENDING in {" ".join(t.get_text().split()) for ax in made[name].axes for t in ax.texts}, name
    assert made["lab_states_by_block.png"].axes[0].patches and made["sensitivity_gate.png"].axes[0].patches, "what exists is still drawn"


def test_a_site_without_an_interpolated_run_says_so(site):
    bare = edited(site)
    bare.data["interpolated_run"] = None
    made = figures.draw_all(bare)
    assert {" ".join(t.get_text().split()) for t in made["interpolated_run.png"].axes[0].texts} == {figures.NO_RUN}


def test_every_text_of_every_figure_passes_the_review_of_the_words_about_a_sensitivity(drawn):
    strings = [t.get_text() for fig in drawn.values() for t in [*fig.texts, *(t for ax in fig.axes for t in [ax.title, ax.xaxis.label, ax.yaxis.label, *ax.texts])]]
    assert len(strings) > 20 and [(s, texts.sensitivity_problems(s)) for s in strings if texts.sensitivity_problems(s)] == []
