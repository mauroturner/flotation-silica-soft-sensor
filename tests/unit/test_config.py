"""Configuration (U02): paths against the project folder, the seal's two lists of keys, the source's guarantees and every key refused
by name (RNF04, AC09, AC18 in part, AC32, AC33; D10, D18, D31)."""

from __future__ import annotations

import dataclasses
import re
from datetime import datetime
from pathlib import Path

import pytest

from flotsilica.config import (
    DEFAULT_CONFIG,
    ENV_CONFIG,
    ENV_HOME,
    FINGERPRINT_KEYS,
    UNSEALED_KEYS,
    PipelineConfig,
    SealedConfig,
    config_leaves,
    load_config,
)

PROJECT = Path(__file__).resolve().parents[2]
ARFF_HASH = "a25122979ba8c5fb9c12e361db61032efc6892a24b5746cc8309da601d9639b2"


def variant(tmp_path: Path, snippet: str = "", replace: tuple[str, str] | None = None, name: str = "pipeline.toml") -> Path:
    """A configuration inside `tmp_path/config/`: the real file with one textual replacement, or an ``extends`` of it plus `snippet`."""
    folder = tmp_path / "config"
    folder.mkdir(exist_ok=True)
    target = folder / name
    if replace is not None:
        text = DEFAULT_CONFIG.read_text(encoding="utf-8")
        assert replace[0] in text, f"{replace[0]!r} is not in the default configuration"
        target.write_text(text.replace(*replace, 1), encoding="utf-8")
    else:
        target.write_text(f'extends = "{DEFAULT_CONFIG.as_posix()}"\n{snippet}', encoding="utf-8")
    return target


def refused(tmp_path: Path, match: str, snippet: str = "", replace: tuple[str, str] | None = None) -> None:
    with pytest.raises(ValueError, match=match):
        load_config(variant(tmp_path, snippet, replace))


# --- the default configuration -------------------------------------------------------------------------------------


def test_default_configuration_has_the_values_of_the_plan(cfg):
    assert isinstance(cfg, PipelineConfig) and cfg.project_root == PROJECT
    s = cfg.source
    assert s.path == PROJECT / "data" / "raw" / "openml-43311-quality-prediction-mining-process.arff"
    assert (s.accepted_bytes, s.accepted_sha256) == (185243565, ARFF_HASH)
    assert (s.max_bytes, s.max_rows, s.max_line_bytes) == (256 * 1024 * 1024, 1_000_000, 4096)
    assert s.relation == "Quality-Prediction-in-a-Mining-Process" and len(s.attributes) == 24
    assert s.attributes[:3] == ("date", "%_Iron_Feed", "%_Silica_Feed") and s.attributes[-2:] == ("%_Iron_Concentrate", "%_Silica_Concentrate")
    assert (cfg.hours.rows_per_hour, cfg.hours.min_rows_per_hour) == (180, 90)
    assert (cfg.hours.first_hour, cfg.hours.last_hour) == (datetime(2017, 3, 10, 1), datetime(2017, 9, 9, 23))
    assert cfg.lab.latency_hours == 2
    assert (cfg.deliveries.launch_last_hour, cfg.deliveries.cadence_hours) == (datetime(2017, 7, 31, 23), 24)
    assert dataclasses.astuple(cfg.split) == (
        datetime(2017, 3, 10, 1), datetime(2017, 5, 31, 23), datetime(2017, 6, 2), datetime(2017, 6, 30, 23), datetime(2017, 7, 2),
        datetime(2017, 7, 30, 23), datetime(2017, 8, 1), datetime(2017, 9, 9, 23), 24, 100)
    assert cfg.features.sets == ("fS", "fL", "fSL", "fSLF") and cfg.features.lab_means == (6, 24) and cfg.features.min_fresh_history == 24
    m = cfg.model
    assert (m.families, m.targets, m.hgb_min_samples_leaf, m.rf_min_samples_leaf) == (("hgb", "rf"), ("level", "change"), (20, 50), (5, 20))
    assert (m.hgb_learning_rate, m.hgb_max_iter, m.hgb_max_leaf_nodes, m.rf_n_estimators, m.rf_max_features) == (0.05, 300, 15, 300, 0.33)
    assert (m.random_state, m.refit_on, m.model_version) == (0, ("train", "valid_v1"), "v1")
    assert cfg.baselines.rolling_k == (3, 6, 12, 24) and cfg.baselines.strongest_candidates == ("b1_persistence", "b2_rolling")
    assert (cfg.intervals.coverage, cfg.intervals.calibrate_on) == (0.80, "valid_v2")
    assert (cfg.evaluation.horizons, cfg.evaluation.bootstrap_resamples, cfg.evaluation.bootstrap_seed) == ((0, 1, 2), 2000, 0)
    assert (cfg.sensitivity.permutation_repeats, cfg.sensitivity.refits, cfg.sensitivity.pd_grid_points) == (5, 5, 15)
    assert (cfg.sensitivity.min_importance_mae, cfg.sensitivity.min_abs_spearman) == (0.01, 0.5)
    assert cfg.variants.latencies == (3, 4) and cfg.variants.refit_all is True
    assert (cfg.criteria.c05_coverage_low, cfg.criteria.c05_coverage_high, cfg.criteria.c06_max_bias, cfg.criteria.leak_tripwire_ratio) == (
        0.75, 0.85, 0.10, 0.5)
    assert cfg.site.max_total_bytes == 204800
    assert (cfg.api.host, cfg.api.port, cfg.api.max_lab_history) == ("127.0.0.1", 8000, 48)


def test_the_configuration_is_immutable(cfg):
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.lab.latency_hours = 3  # type: ignore[misc]


# --- paths (D31, RNF04, AC33) --------------------------------------------------------------------------------------


def test_relative_paths_resolve_against_project_root_from_another_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_HOME, raising=False)
    monkeypatch.delenv(ENV_CONFIG, raising=False)
    for load in (lambda: load_config(PROJECT / "config" / "pipeline.toml"), lambda: load_config(Path("config") / "pipeline.toml"), load_config):
        cfg = load()
        assert cfg.project_root == PROJECT
        for field in dataclasses.fields(cfg.paths):
            path = getattr(cfg.paths, field.name)
            assert path.is_absolute() and PROJECT in path.parents, field.name
        assert cfg.source.path.is_absolute() and PROJECT in cfg.source.path.parents
        assert cfg.paths.warehouse == PROJECT / "data" / "warehouse" / "flotsilica.sqlite"
        assert cfg.paths.seal == PROJECT / "reports" / "model_seal.json"
    # the working directory holds another copy's configuration: it is never read in silence
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipeline.toml").write_text("this is not the project's configuration", encoding="utf-8")
    assert load_config(Path("config") / "pipeline.toml").project_root == PROJECT


def test_a_relative_flotsilica_config_is_taken_from_the_project_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_HOME, raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipeline.quick.toml").write_text("[hours]\nrows_per_hour = 999\n", encoding="utf-8")
    monkeypatch.setenv(ENV_CONFIG, "config/pipeline.quick.toml")
    cfg = load_config()
    assert cfg.hours.rows_per_hour == 12 and cfg.paths.warehouse == PROJECT / "data" / "quick" / "flotsilica.sqlite"


def test_flotsilica_home_moves_the_project_folder_and_must_exist(tmp_path, monkeypatch):
    home = tmp_path / "elsewhere"
    (home / "config").mkdir(parents=True)
    (home / "config" / "pipeline.toml").write_text(DEFAULT_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv(ENV_HOME, str(home))
    assert load_config(DEFAULT_CONFIG).paths.warehouse == home.resolve() / "data" / "warehouse" / "flotsilica.sqlite"
    monkeypatch.setenv(ENV_CONFIG, "config/pipeline.toml")
    assert load_config().project_root == home.resolve()
    monkeypatch.setenv(ENV_HOME, str(tmp_path / "does-not-exist"))
    with pytest.raises(ValueError, match=ENV_HOME):
        load_config(DEFAULT_CONFIG)


def test_quick_configuration_keeps_every_output_under_data_quick(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_HOME, raising=False)
    cfg = load_config(PROJECT / "config" / "pipeline.quick.toml")
    quick = PROJECT / "data" / "quick"
    assert cfg.source.path == quick / "flotation_fixture.arff" and (cfg.source.accepted_bytes, cfg.source.accepted_sha256) == (0, "")
    for field in dataclasses.fields(cfg.paths):
        assert quick in getattr(cfg.paths, field.name).parents, field.name
    assert (cfg.hours.rows_per_hour, cfg.hours.min_rows_per_hour, cfg.deliveries.cadence_hours) == (12, 6, 240)
    assert cfg.model.families == ("rf",) and cfg.model.rf_n_estimators == 20 and cfg.model.rf_min_samples_leaf == (20,)
    assert cfg.features.sets == ("fS", "fL", "fSL") and cfg.evaluation.bootstrap_resamples == 200
    assert (cfg.sensitivity.refits, cfg.sensitivity.permutation_repeats) == (2, 2)
    default = load_config(DEFAULT_CONFIG)
    assert (cfg.hours.first_hour, cfg.hours.last_hour, cfg.deliveries.launch_last_hour, cfg.split) == (
        default.hours.first_hour, default.hours.last_hour, default.deliveries.launch_last_hour, default.split), "the quick run replays the same calendar"


def test_a_relative_path_cannot_leave_the_project_folder(tmp_path):
    refused(tmp_path, r"\[paths\] raw_dir.*sale de la carpeta del proyecto", replace=('raw_dir = "data/raw"', 'raw_dir = "../elsewhere"'))
    refused(tmp_path, r"\[paths\] seal.*sale de la carpeta", replace=('seal = "reports/model_seal.json"', 'seal = "data/../../x.json"'))
    refused(tmp_path, r"\[source\] path.*sale de la carpeta", snippet='[source]\npath = "../x.arff"\n')


def test_a_dotdot_that_stays_inside_the_project_is_normalised_and_an_absolute_path_is_kept(tmp_path):
    path = variant(tmp_path, replace=('raw_dir = "data/raw"', 'raw_dir = "data/quick/../raw"'))
    assert load_config(path).paths.raw_dir == tmp_path / "data" / "raw"
    outside = (tmp_path / "outside").as_posix()
    path = variant(tmp_path, replace=('raw_dir = "data/raw"', f'raw_dir = "{outside}"'))
    assert load_config(path).paths.raw_dir == Path(outside)


def test_an_empty_path_is_refused(tmp_path):
    refused(tmp_path, r"\[paths\] figures_dir.*texto vacío", replace=('figures_dir = "docs/figures"', 'figures_dir = ""'))


# --- the seal's keys (D18, AC18) -----------------------------------------------------------------------------------


def test_every_config_key_is_fingerprinted_or_declared_unsealed():
    leaves = [leaf for leaf in config_leaves(PipelineConfig) if leaf != "project_root"]
    assert len(leaves) == len(set(leaves))
    fingerprinted, unsealed = set(FINGERPRINT_KEYS), set(UNSEALED_KEYS)
    assert len(FINGERPRINT_KEYS) == len(fingerprinted) and len(UNSEALED_KEYS) == len(unsealed), "a key is listed twice"
    assert fingerprinted & unsealed == set(), "a key is both fingerprinted and declared unsealed"
    assert sorted(set(leaves) - fingerprinted - unsealed) == [], "a key is neither fingerprinted nor declared unsealed"
    assert sorted((fingerprinted | unsealed) - set(leaves)) == [], "a listed key is not in the configuration"
    # the plan, section 4: [source] enters only with its relation and attributes; every key of these sections enters; [site], [api] and
    # [paths] stay out
    for section in ("hours", "lab", "deliveries", "split", "features", "model", "baselines", "intervals", "evaluation", "sensitivity",
                    "variants", "criteria"):
        assert {leaf for leaf in leaves if leaf.startswith(f"{section}.")} <= fingerprinted, section
    assert {leaf for leaf in fingerprinted if leaf.startswith("source.")} == {"source.relation", "source.attributes"}
    assert {leaf for leaf in leaves if leaf.startswith(("site.", "api.", "paths."))} <= unsealed
    assert {"source.path", "source.accepted_bytes", "source.accepted_sha256", "source.max_bytes", "source.max_rows",
            "source.max_line_bytes"} <= unsealed


def test_the_sealed_view_holds_exactly_the_fingerprinted_keys_and_the_observed_hash(cfg):
    assert set(config_leaves(SealedConfig)) == set(FINGERPRINT_KEYS) | {"source_sha256"}
    view = SealedConfig.of(cfg, ARFF_HASH)
    for key in FINGERPRINT_KEYS:
        section, name = key.split(".")
        assert getattr(getattr(view, section), name) == getattr(getattr(cfg, section), name), key
    assert view.source_sha256 == ARFF_HASH
    assert not any(hasattr(view, name) for name in ("paths", "site", "api")) and not hasattr(view.source, "path")
    with pytest.raises(ValueError, match="source_sha256"):
        SealedConfig.of(cfg, ARFF_HASH.upper())


# --- the source (RF01, V01-V03) ------------------------------------------------------------------------------------


def test_an_empty_accepted_hash_is_allowed_only_for_a_source_under_data_quick(tmp_path):
    empty = '[source]\naccepted_sha256 = ""\naccepted_bytes = 0\n'
    refused(tmp_path, r"\[source\] accepted_sha256.*data/quick", snippet=empty)
    quick = tmp_path / "data" / "quick" / "x.arff"
    assert load_config(variant(tmp_path, snippet=empty + f'path = "{quick.as_posix()}"\n')).source.accepted_sha256 == ""
    assert load_config(variant(tmp_path, snippet=empty + 'path = "data/quick/x.arff"\n')).source.path == quick
    refused(tmp_path, r"\[source\] accepted_sha256.*data/quick", snippet=empty + 'path = "data/quick_not/x.arff"\n')


@pytest.mark.parametrize("bad", [ARFF_HASH.upper(), ARFF_HASH[:-1], ARFF_HASH + "0", "z" * 64, " " + ARFF_HASH])
def test_the_accepted_hash_is_64_lower_case_hex_characters(tmp_path, bad):
    refused(tmp_path, r"\[source\] accepted_sha256.*64 caracteres", snippet=f'[source]\naccepted_sha256 = "{bad}"\n')


def test_the_accepted_size_and_hash_go_together(tmp_path):
    refused(tmp_path, r"\[source\] accepted_bytes.*0", snippet='[source]\naccepted_sha256 = ""\naccepted_bytes = 5\npath = "data/quick/x.arff"\n')
    refused(tmp_path, r"\[source\] accepted_bytes.*mayor que 0", snippet="[source]\naccepted_bytes = 0\n")
    refused(tmp_path, r"\[source\] accepted_bytes.*max_bytes", snippet="[source]\naccepted_bytes = 268435457\n")


@pytest.mark.parametrize("snippet", [
    '[source]\nattributes = []\n',
    '[source]\nattributes = ["date"]\n',
    '[source]\nattributes = ["a", "a", "b"]\n',
    '[source]\nrelation = ""\n',
    '[source]\nrelation = " "\n',
])
def test_the_relation_and_the_attributes_are_checked(tmp_path, snippet):
    refused(tmp_path, r"\[source\] (relation|attributes)", snippet=snippet)


def test_the_attribute_list_must_have_24_distinct_names(tmp_path):
    names = ", ".join(f'"c{i}"' for i in range(24))
    assert len(load_config(variant(tmp_path, snippet=f"[source]\nattributes = [{names}]\n")).source.attributes) == 24
    names = ", ".join(f'"c{i}"' for i in range(23)) + ', ""'
    refused(tmp_path, r"\[source\] attributes", snippet=f"[source]\nattributes = [{names}]\n")


# --- mistakes in the file are named (AC32) ---------------------------------------------------------------------------


def test_unknown_key_is_rejected_with_its_name(tmp_path):
    refused(tmp_path, r"\[lab\].*'latency'", snippet="[lab]\nlatency = 2\n")
    refused(tmp_path, r"\[hours\].*'rows_per_hours'", snippet="[hours]\nrows_per_hours = 180\n")
    refused(tmp_path, r"\[api\].*'cors'", snippet='[api]\ncors = "*"\n')


def test_unknown_section_missing_section_and_missing_key_are_named(tmp_path):
    refused(tmp_path, r"sección desconocida \[extras\]", snippet="[extras]\nx = 1\n")
    text = DEFAULT_CONFIG.read_text(encoding="utf-8")
    without_site = re.sub(r"\[site\].*?(?=\[api\])", "", text, flags=re.S)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "a.toml").write_text(without_site, encoding="utf-8")
    with pytest.raises(ValueError, match=r"falta la sección \[site\]"):
        load_config(tmp_path / "config" / "a.toml")
    refused(tmp_path, r"\[lab\]: falta la clave 'latency_hours'", replace=("latency_hours = 2", ""))


@pytest.mark.parametrize(("snippet", "match"), [
    ('[hours]\nrows_per_hour = "180"\n', r"\[hours\] rows_per_hour.*un entero"),
    ("[hours]\nrows_per_hour = true\n", r"\[hours\] rows_per_hour.*un entero"),
    ("[model]\nhgb_max_iter = 300.5\n", r"\[model\] hgb_max_iter.*un entero"),
    ("[model]\nhgb_learning_rate = 'fast'\n", r"\[model\] hgb_learning_rate.*un número"),
    ("[model]\nhgb_min_samples_leaf = 20\n", r"\[model\] hgb_min_samples_leaf.*una lista"),
    ('[model]\nhgb_min_samples_leaf = ["a"]\n', r"\[model\] hgb_min_samples_leaf.*un entero"),
    ('[hours]\nfirst_hour = "2017-03-10T01:00:00"\n', r"\[hours\] first_hour.*una fecha y hora"),
    ("[hours]\nlast_hour = 2017-09-09\n", r"\[hours\] last_hour.*una fecha y hora"),
    ("[hours]\nlast_hour = 2017-09-09T23:00:00Z\n", r"\[hours\] last_hour.*una fecha y hora"),
    ("[paths]\nraw_dir = 3\n", r"\[paths\] raw_dir.*ruta"),
    ('[variants]\nrefit_all = "yes"\n', r"\[variants\] refit_all.*verdadero o falso"),
    ('[source]\nattributes = "date"\n', r"\[source\] attributes.*una lista"),
    ("[api]\nport = 8000.5\n", r"\[api\] port.*un entero"),
])
def test_a_value_of_the_wrong_type_is_named(tmp_path, snippet, match):
    refused(tmp_path, match, snippet=snippet)


def test_extends_cycle_and_missing_base_are_refused(tmp_path):
    folder = tmp_path / "config"
    folder.mkdir()
    (folder / "a.toml").write_text('extends = "b.toml"\n', encoding="utf-8")
    (folder / "b.toml").write_text('extends = "a.toml"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="ciclo"):
        load_config(folder / "a.toml")
    (folder / "c.toml").write_text('extends = "nothing.toml"\n', encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        load_config(folder / "c.toml")
    with pytest.raises(FileNotFoundError):
        load_config(folder / "absent.toml")


# --- numeric bounds, names and lists: every limit has a test with its invalid values -----------------------------------


@pytest.mark.parametrize(("section", "key", "bad"), [
    ("source", "max_bytes", 0), ("source", "max_rows", 0), ("source", "max_line_bytes", 0), ("source", "accepted_bytes", -1),
    ("hours", "rows_per_hour", 0), ("hours", "min_rows_per_hour", 0), ("hours", "min_rows_per_hour", 181),
    ("lab", "latency_hours", 0), ("lab", "latency_hours", -2),
    ("deliveries", "cadence_hours", 0), ("deliveries", "cadence_hours", -24),
    ("split", "purge_hours", -1), ("split", "min_fresh_hours_per_block", 0),
    ("features", "lab_last", 0), ("features", "min_fresh_history", 0),
    ("model", "hgb_learning_rate", 0.0), ("model", "hgb_learning_rate", -0.05), ("model", "hgb_max_iter", 0), ("model", "hgb_max_leaf_nodes", 1),
    ("model", "hgb_l2_regularization", -1.0), ("model", "rf_n_estimators", 0), ("model", "rf_max_features", 0.0), ("model", "rf_max_features", 1.5),
    ("model", "random_state", -1), ("model", "random_state", 2**32),
    ("baselines", "ridge_alpha", 0.0), ("baselines", "ridge_alpha", -1.0),
    ("intervals", "coverage", 0.0), ("intervals", "coverage", 1.0), ("intervals", "coverage", 1.5),
    ("evaluation", "bootstrap_resamples", 0), ("evaluation", "bootstrap_seed", -1),
    ("sensitivity", "permutation_repeats", 0), ("sensitivity", "refits", 0), ("sensitivity", "pd_grid_points", 1),
    ("sensitivity", "pd_low_quantile", 0.0), ("sensitivity", "pd_low_quantile", 0.96), ("sensitivity", "pd_high_quantile", 1.0),
    ("sensitivity", "min_importance_mae", -0.01), ("sensitivity", "min_abs_spearman", 0.0), ("sensitivity", "min_abs_spearman", 1.5),
    ("sensitivity", "seed", -1),
    ("criteria", "c05_coverage_low", 0.0), ("criteria", "c05_coverage_high", 1.0), ("criteria", "c06_max_bias", 0.0),
    ("criteria", "leak_tripwire_ratio", 0.0), ("criteria", "leak_tripwire_ratio", 1.5),
    ("site", "max_total_bytes", 0),
    ("api", "port", 0), ("api", "port", 65536), ("api", "max_lab_history", 0),
])
def test_numeric_bounds_reject_their_invalid_values_naming_the_key(tmp_path, section, key, bad):
    refused(tmp_path, rf"\[{section}\] {key}", snippet=f"[{section}]\n{key} = {bad}\n")


def test_the_edges_of_the_valid_ranges_are_accepted(tmp_path):
    ok = ("[intervals]\ncoverage = 0.999\n[model]\nhgb_l2_regularization = 0.0\nrf_max_features = 1.0\n[split]\npurge_hours = 0\n"
          "[api]\nport = 65535\n[criteria]\nleak_tripwire_ratio = 1.0\n[sensitivity]\nmin_importance_mae = 0.0\nmin_abs_spearman = 1.0\n")
    cfg = load_config(variant(tmp_path, snippet=ok))
    assert cfg.model.rf_max_features == 1.0 and cfg.split.purge_hours == 0 and cfg.api.port == 65535 and cfg.criteria.leak_tripwire_ratio == 1.0


def test_the_api_listens_only_on_the_loopback_interface(tmp_path):
    for host in ("0.0.0.0", "localhost", "::1", "", "127.0.0.2"):
        refused(tmp_path, r"\[api\] host.*127\.0\.0\.1", snippet=f'[api]\nhost = "{host}"\n')


@pytest.mark.parametrize(("snippet", "match"), [
    ('[features]\nsets = []\n', r"\[features\] sets"),
    ('[features]\nsets = ["fS", "fX"]\n', r"\[features\] sets.*fX"),
    ('[features]\nsets = ["fS", "fS"]\n', r"\[features\] sets"),
    ("[features]\nlab_means = []\n", r"\[features\] lab_means"),
    ("[features]\nlab_means = [6, 6]\n", r"\[features\] lab_means"),
    ("[features]\nlab_means = [0]\n", r"\[features\] lab_means"),
    ('[model]\nfamilies = []\n', r"\[model\] families"),
    ('[model]\nfamilies = ["rf", "svm"]\n', r"\[model\] families.*svm"),
    ('[model]\ntargets = ["level", "level"]\n', r"\[model\] targets"),
    ('[model]\ntargets = ["ratio"]\n', r"\[model\] targets.*ratio"),
    ("[model]\nhgb_min_samples_leaf = []\n", r"\[model\] hgb_min_samples_leaf.*no vacía"),
    ("[model]\nrf_min_samples_leaf = [5, 5]\n", r"\[model\] rf_min_samples_leaf.*sin repetidos"),
    ("[model]\nrf_min_samples_leaf = [0]\n", r"\[model\] rf_min_samples_leaf"),
    ('[model]\nrefit_on = ["train", "test"]\n', r"\[model\] refit_on.*test"),
    ('[model]\nrefit_on = []\n', r"\[model\] refit_on"),
    ('[model]\nmodel_version = "v 1"\n', r"\[model\] model_version"),
    ('[model]\nmodel_version = "../v1"\n', r"\[model\] model_version"),
    ("[baselines]\nrolling_k = []\n", r"\[baselines\] rolling_k"),
    ("[baselines]\nrolling_k = [3, 3]\n", r"\[baselines\] rolling_k"),
    ("[baselines]\nrolling_k = [0, 3]\n", r"\[baselines\] rolling_k"),
    ('[baselines]\nstrongest_candidates = ["b1_persistence", "b3_ridge_sensors"]\n', r"\[baselines\] strongest_candidates.*b3_ridge_sensors"),
    ('[baselines]\nstrongest_candidates = ["b1_persistence", "b1_persistence"]\n', r"\[baselines\] strongest_candidates"),
    ("[baselines]\nstrongest_candidates = []\n", r"\[baselines\] strongest_candidates"),
    ('[intervals]\ncalibrate_on = "valid_v1"\n', r"\[intervals\] calibrate_on.*valid_v2"),
    ("[evaluation]\nhorizons = []\n", r"\[evaluation\] horizons"),
    ("[evaluation]\nhorizons = [0, -1]\n", r"\[evaluation\] horizons.*negativo"),
    ("[evaluation]\nhorizons = [0, 1, 1]\n", r"\[evaluation\] horizons.*repetido"),
    ("[variants]\nlatencies = []\n", r"\[variants\] latencies"),
    ("[variants]\nlatencies = [3, 3]\n", r"\[variants\] latencies"),
    ("[variants]\nlatencies = [0]\n", r"\[variants\] latencies"),
    ("[criteria]\nc05_coverage_low = 0.9\nc05_coverage_high = 0.8\n", r"\[criteria\] c05_coverage_low"),
    ("[sensitivity]\npd_low_quantile = 0.9\npd_high_quantile = 0.8\n", r"\[sensitivity\] pd_low_quantile"),
])
def test_grids_names_and_lists_are_checked(tmp_path, snippet, match):
    refused(tmp_path, match, snippet=snippet)


# --- the calendar: hours on the hour, the blocks of D10 and their purges (RF09, AC09) -------------------------------------


@pytest.mark.parametrize(("section", "key"), [
    ("hours", "first_hour"), ("hours", "last_hour"), ("deliveries", "launch_last_hour"), ("split", "train_first"), ("split", "train_last"),
    ("split", "v1_first"), ("split", "v1_last"), ("split", "v2_first"), ("split", "v2_last"), ("split", "test_first"), ("split", "test_last"),
])
def test_every_hour_of_the_calendar_is_on_the_hour(tmp_path, section, key):
    for off in ("2017-06-15T10:30:00", "2017-06-15T10:00:30"):
        refused(tmp_path, rf"\[{section}\] {key}.*en punto", snippet=f"[{section}]\n{key} = {off}\n")


@pytest.mark.parametrize(("snippet", "match"), [
    ("[split]\ntrain_last = 2017-06-01T12:00:00\n", r"borde train → valid_v1.*24 h"),
    ("[split]\nv1_first = 2017-06-01T00:00:00\n", r"borde train → valid_v1"),
    ("[split]\nv1_last = 2017-07-01T10:00:00\n", r"borde valid_v1 → valid_v2.*24 h"),
    ("[split]\nv2_first = 2017-07-01T00:00:00\n", r"borde valid_v1 → valid_v2"),
    ("[split]\nv2_last = 2017-08-01T00:00:00\n", r"borde valid_v2 → test"),
    ("[split]\ntest_first = 2017-07-31T00:00:00\n", r"borde valid_v2 → test"),
    ("[split]\npurge_hours = 48\n", r"borde train → valid_v1.*48 h"),
    ("[split]\ntrain_first = 2017-06-01T00:00:00\n", r"\[split\] train.*posterior"),
    ("[split]\ntest_first = 2017-09-10T00:00:00\n", r"\[split\] test.*posterior"),
    ("[split]\ntrain_first = 2017-03-10T00:00:00\n", r"\[split\] train_first.*first_hour"),
    ("[split]\ntest_last = 2017-09-10T00:00:00\n", r"\[split\] test_last.*last_hour"),
    ("[hours]\nlast_hour = 2017-09-09T22:00:00\n", r"\[split\] test_last.*last_hour"),
    ("[hours]\nfirst_hour = 2017-09-10T00:00:00\n", r"\[hours\] first_hour"),
    ("[deliveries]\nlaunch_last_hour = 2017-07-30T22:00:00\n", r"\[deliveries\] launch_last_hour.*v2_last"),
    ("[deliveries]\nlaunch_last_hour = 2017-08-01T00:00:00\n", r"\[deliveries\] launch_last_hour.*test_first"),
])
def test_the_calendar_is_checked_with_the_name_of_the_boundary(tmp_path, snippet, match):
    refused(tmp_path, match, snippet=snippet)


def test_every_split_hour_is_used_by_the_check(tmp_path):
    """Moving any one hour of [split] outside its place is refused: none is accepted and then ignored."""
    moved = {
        "train_first": "2017-02-01T00:00:00", "train_last": "2017-06-01T23:00:00", "v1_first": "2017-05-31T23:00:00",
        "v1_last": "2017-07-01T23:00:00", "v2_first": "2017-06-30T23:00:00", "v2_last": "2017-07-31T23:00:00",
        "test_first": "2017-07-31T23:00:00", "test_last": "2017-09-10T23:00:00",
    }
    for key, value in moved.items():
        with pytest.raises(ValueError, match=r"\[split\]|borde"):
            load_config(variant(tmp_path, snippet=f"[split]\n{key} = {value}\n"))
    assert load_config(variant(tmp_path, snippet="[split]\nv1_last = 2017-06-15T23:00:00\n")).split.v1_last == datetime(2017, 6, 15, 23)
