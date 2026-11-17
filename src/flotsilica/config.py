"""Pipeline configuration: one TOML file, typed, immutable and checked key by key (plan, section 4).

``config/pipeline.toml`` holds every default. A file may start from another one with a top-level ``extends = "<path>"``
(``config/pipeline.quick.toml`` does). Every relative path is resolved against the project folder, never against the working
directory (decision D31): the paths inside the configuration (``[source] path`` and ``[paths]``) against ``$FLOTSILICA_HOME`` when it
is set, otherwise the parent of the folder that holds the main configuration file; a relative configuration file
(``$FLOTSILICA_CONFIG`` or the ``path`` argument, which ``--config`` passes) against ``$FLOTSILICA_HOME`` or, without it, the folder of
this package's project.

Anything unknown, missing, mistyped or inconsistent is a ``ValueError`` that names the key: an option that is accepted and silently
not used is the defect projects 01 and 02 both had.

Every leaf of the configuration is either in ``FINGERPRINT_KEYS`` (it can change a sealed value, so it enters the seal's
``config_sha256``) or in ``UNSEALED_KEYS`` (it cannot), never both and never neither (decision D18). The sealed calculations
receive ``SealedConfig``, which holds only the fingerprinted keys and the observed hash of the source file.
"""

from __future__ import annotations

import dataclasses
import math
import os
import re
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = DEFAULT_PROJECT_ROOT / "config" / "pipeline.toml"

ENV_CONFIG = "FLOTSILICA_CONFIG"
ENV_HOME = "FLOTSILICA_HOME"
FEATURE_SET_NAMES = ("fS", "fL", "fSL", "fSLF")
MODEL_FAMILY_NAMES = ("hgb", "rf")
MODEL_TARGET_NAMES = ("level", "change")
REFIT_BLOCK_NAMES = ("train", "valid_v1", "valid_v2")
STRONGEST_CANDIDATE_NAMES = ("b1_persistence", "b2_rolling")
ATTRIBUTE_COUNT = 24
LOOPBACK_HOST = "127.0.0.1"

_SHA256 = re.compile(r"[0-9a-f]{64}")
# a folder name that is the same on every system: it starts with a letter, a digit, "_" or "-" (so "." and ".." are not names, and nothing is
# hidden), has dots only between other characters, and does not end in a dot (Windows drops it, so "v1." and "v1" would be one folder)
_FOLDER_NAME = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*")
MAX_SEED = 2**32 - 1   # the largest seed that numpy's legacy generators and scikit-learn accept
_TYPE_NAMES = {
    bool: "verdadero o falso", int: "un entero", float: "un número", str: "un texto", datetime: "una fecha y hora (AAAA-MM-DDTHH:MM:SS)",
    Path: "una ruta",
}


@dataclass(frozen=True)
class SourceConfig:
    path: Path
    accepted_bytes: int
    accepted_sha256: str
    max_bytes: int
    max_rows: int
    max_line_bytes: int
    relation: str
    attributes: tuple[str, ...]


@dataclass(frozen=True)
class HoursConfig:
    rows_per_hour: int
    min_rows_per_hour: int
    first_hour: datetime
    last_hour: datetime


@dataclass(frozen=True)
class LabConfig:
    latency_hours: int


@dataclass(frozen=True)
class DeliveriesConfig:
    launch_last_hour: datetime
    cadence_hours: int


@dataclass(frozen=True)
class SplitConfig:
    train_first: datetime
    train_last: datetime
    v1_first: datetime
    v1_last: datetime
    v2_first: datetime
    v2_last: datetime
    test_first: datetime
    test_last: datetime
    purge_hours: int
    min_fresh_hours_per_block: int


@dataclass(frozen=True)
class FeaturesConfig:
    sets: tuple[str, ...]
    lab_last: int
    lab_means: tuple[int, ...]
    min_fresh_history: int


@dataclass(frozen=True)
class ModelConfig:
    families: tuple[str, ...]
    targets: tuple[str, ...]
    hgb_learning_rate: float
    hgb_max_iter: int
    hgb_max_leaf_nodes: int
    hgb_min_samples_leaf: tuple[int, ...]
    hgb_l2_regularization: float
    rf_n_estimators: int
    rf_max_features: float
    rf_min_samples_leaf: tuple[int, ...]
    random_state: int
    refit_on: tuple[str, ...]
    model_version: str


@dataclass(frozen=True)
class BaselinesConfig:
    rolling_k: tuple[int, ...]
    ridge_alpha: float
    strongest_candidates: tuple[str, ...]


@dataclass(frozen=True)
class IntervalsConfig:
    coverage: float
    calibrate_on: str


@dataclass(frozen=True)
class EvaluationConfig:
    horizons: tuple[int, ...]
    bootstrap_resamples: int
    bootstrap_seed: int


@dataclass(frozen=True)
class SensitivityConfig:
    permutation_repeats: int
    refits: int
    pd_grid_points: int
    pd_low_quantile: float
    pd_high_quantile: float
    min_importance_mae: float
    min_abs_spearman: float
    seed: int


@dataclass(frozen=True)
class VariantsConfig:
    latencies: tuple[int, ...]
    refit_all: bool


@dataclass(frozen=True)
class CriteriaConfig:
    c05_coverage_low: float
    c05_coverage_high: float
    c06_max_bias: float
    leak_tripwire_ratio: float


@dataclass(frozen=True)
class SiteConfig:
    max_total_bytes: int


@dataclass(frozen=True)
class ApiConfig:
    host: str
    port: int
    max_lab_history: int


@dataclass(frozen=True)
class PathsConfig:
    raw_dir: Path
    interim_dir: Path
    warehouse: Path
    models_dir: Path
    outputs_dir: Path
    site_dir: Path
    reports_dir: Path
    seal: Path
    dashboard_html: Path
    readme: Path
    figures_dir: Path


@dataclass(frozen=True)
class PipelineConfig:
    source: SourceConfig
    hours: HoursConfig
    lab: LabConfig
    deliveries: DeliveriesConfig
    split: SplitConfig
    features: FeaturesConfig
    model: ModelConfig
    baselines: BaselinesConfig
    intervals: IntervalsConfig
    evaluation: EvaluationConfig
    sensitivity: SensitivityConfig
    variants: VariantsConfig
    criteria: CriteriaConfig
    site: SiteConfig
    api: ApiConfig
    paths: PathsConfig
    project_root: Path


# --- the seal's view of the configuration (D18) ------------------------------------------------------------------------


@dataclass(frozen=True)
class SealedSourceConfig:
    """The two keys of ``[source]`` that can change a sealed value: the relation and the attributes that are read. The path, the accepted
    size and hash and the limits cannot; the hash of the file that was actually read enters as ``SealedConfig.source_sha256``."""

    relation: str
    attributes: tuple[str, ...]


@dataclass(frozen=True)
class SealedConfig:
    """What the sealed calculations receive (hours, split, features, baselines, models, intervals, sensitivities, evaluation and
    variants): only the keys of ``FINGERPRINT_KEYS`` and the observed hash of the source. A key outside it cannot reach a sealed value."""

    source: SealedSourceConfig
    hours: HoursConfig
    lab: LabConfig
    deliveries: DeliveriesConfig
    split: SplitConfig
    features: FeaturesConfig
    model: ModelConfig
    baselines: BaselinesConfig
    intervals: IntervalsConfig
    evaluation: EvaluationConfig
    sensitivity: SensitivityConfig
    variants: VariantsConfig
    criteria: CriteriaConfig
    source_sha256: str

    @classmethod
    def of(cls, cfg: PipelineConfig, source_sha256: str) -> SealedConfig:
        """The sealed view of `cfg` for a source file that hashed to `source_sha256`."""
        if not _SHA256.fullmatch(source_sha256):
            raise ValueError(f"source_sha256: se esperaban 64 caracteres hexadecimales en minúscula, se recibió {source_sha256!r}")
        sections = {f.name: getattr(cfg, f.name) for f in dataclasses.fields(cls) if f.name not in ("source", "source_sha256")}
        source = SealedSourceConfig(relation=cfg.source.relation, attributes=cfg.source.attributes)
        return cls(source=source, **sections, source_sha256=source_sha256)


def config_leaves(cls: type, prefix: str = "") -> Iterator[str]:
    """The full name of every leaf of a configuration dataclass, ``section.key``, in declaration order."""
    hints = get_type_hints(cls)
    for f in dataclasses.fields(cls):
        name = f"{prefix}{f.name}"
        if dataclasses.is_dataclass(hints[f.name]):
            yield from config_leaves(hints[f.name], f"{name}.")
        else:
            yield name


# Every key that can change a sealed value, named one by one so that a new key fails tests/unit/test_config.py until it is classified.
# Including one too many only turns a cosmetic change into a post_seal run; one too few is project 03's defect B4 (D18). The observed
# hash of the source file (source_sha256) is not configured: SealedConfig adds it.
FINGERPRINT_KEYS: tuple[str, ...] = (
    "source.relation", "source.attributes",
    "hours.rows_per_hour", "hours.min_rows_per_hour", "hours.first_hour", "hours.last_hour",
    "lab.latency_hours",
    "deliveries.launch_last_hour", "deliveries.cadence_hours",
    "split.train_first", "split.train_last", "split.v1_first", "split.v1_last", "split.v2_first", "split.v2_last", "split.test_first",
    "split.test_last", "split.purge_hours", "split.min_fresh_hours_per_block",
    "features.sets", "features.lab_last", "features.lab_means", "features.min_fresh_history",
    "model.families", "model.targets", "model.hgb_learning_rate", "model.hgb_max_iter", "model.hgb_max_leaf_nodes",
    "model.hgb_min_samples_leaf", "model.hgb_l2_regularization", "model.rf_n_estimators", "model.rf_max_features",
    "model.rf_min_samples_leaf", "model.random_state", "model.refit_on", "model.model_version",
    "baselines.rolling_k", "baselines.ridge_alpha", "baselines.strongest_candidates",
    "intervals.coverage", "intervals.calibrate_on",
    "evaluation.horizons", "evaluation.bootstrap_resamples", "evaluation.bootstrap_seed",
    "sensitivity.permutation_repeats", "sensitivity.refits", "sensitivity.pd_grid_points", "sensitivity.pd_low_quantile",
    "sensitivity.pd_high_quantile", "sensitivity.min_importance_mae", "sensitivity.min_abs_spearman", "sensitivity.seed",
    "variants.latencies", "variants.refit_all",
    "criteria.c05_coverage_low", "criteria.c05_coverage_high", "criteria.c06_max_bias", "criteria.leak_tripwire_ratio",
)
# Every key that cannot: where the source is and its accepted size, hash and limits (the hash of the file that was read enters instead),
# the site's limit, the API and where the files go.
UNSEALED_KEYS: tuple[str, ...] = (
    "source.path", "source.accepted_bytes", "source.accepted_sha256", "source.max_bytes", "source.max_rows", "source.max_line_bytes",
    "site.max_total_bytes",
    "api.host", "api.port", "api.max_lab_history",
    "paths.raw_dir", "paths.interim_dir", "paths.warehouse", "paths.models_dir", "paths.outputs_dir", "paths.site_dir", "paths.reports_dir",
    "paths.seal", "paths.dashboard_html", "paths.readme", "paths.figures_dir",
)


# --- loading --------------------------------------------------------------------------------------------------------


def _resolve(value: str, root: Path, where: str) -> Path:
    if not value.strip():
        raise ValueError(f"{where}: se esperaba una ruta, se recibió un texto vacío")
    path = Path(value)
    if path.is_absolute():
        return path  # an absolute path is explicit: it may point anywhere on purpose
    joined = Path(os.path.normpath(root / path))
    base = Path(os.path.normpath(root))
    if joined != base and base not in joined.parents:
        raise ValueError(
            f"{where}: la ruta relativa {value!r} sale de la carpeta del proyecto ({base}); "
            "use una ruta absoluta si el destino está fuera a propósito"
        )
    return joined


def _coerce(value: Any, annotation: Any, where: str, root: Path) -> Any:
    """Convert a TOML value to the annotated type or raise ValueError naming `where`."""
    origin = get_origin(annotation)
    if origin is tuple:
        (element, _ellipsis) = get_args(annotation)
        if not isinstance(value, list):
            raise ValueError(f"{where}: se esperaba una lista, se recibió {type(value).__name__}")
        return tuple(_coerce(v, element, where, root) for v in value)
    if annotation is bool:
        ok = isinstance(value, bool)
    elif annotation is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif annotation is float:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        value = float(value) if ok else value
    elif annotation is str:
        ok = isinstance(value, str)
    elif annotation is datetime:
        ok = isinstance(value, datetime) and value.tzinfo is None   # a local date-time: no date alone, no offset
    elif annotation is Path:
        if isinstance(value, str):
            return _resolve(value, root, where)
        ok = False
    else:  # pragma: no cover - only reachable by adding an unsupported annotation
        raise TypeError(f"{where}: unsupported annotation {annotation!r}")
    if not ok:
        raise ValueError(f"{where}: se esperaba {_TYPE_NAMES.get(annotation, annotation)}, se recibió {value!r}")
    return value


def _build_section(cls: type, data: Any, name: str, root: Path) -> Any:
    if not isinstance(data, dict):
        raise ValueError(f"[{name}]: se esperaba una tabla, se recibió {type(data).__name__}")
    hints = get_type_hints(cls)
    fields = [f.name for f in dataclasses.fields(cls)]
    unknown = sorted(set(data) - set(fields))
    if unknown:
        raise ValueError(f"[{name}]: clave desconocida {unknown[0]!r}")
    missing = [f for f in fields if f not in data]
    if missing:
        raise ValueError(f"[{name}]: falta la clave {missing[0]!r}")
    return cls(**{f: _coerce(data[f], hints[f], f"[{name}] {f}", root) for f in fields})


# --- consistency checks ---------------------------------------------------------------------------------------------


def _positive(value: float, where: str) -> None:
    if not (math.isfinite(value) and value > 0):
        raise ValueError(f"{where}: se esperaba un valor finito mayor que 0, se recibió {value!r}")


def _at_least(value: int, minimum: int, where: str) -> None:
    if value < minimum:
        raise ValueError(f"{where}: se esperaba {minimum} o más, se recibió {value!r}")


def _seed(value: int, where: str) -> None:
    if not 0 <= value <= MAX_SEED:
        raise ValueError(f"{where}: se esperaba un entero de 0 a {MAX_SEED}, se recibió {value!r}")


def _fraction(value: float, where: str, *, closed_high: bool = False) -> None:
    if not (math.isfinite(value) and (0 < value <= 1 if closed_high else 0 < value < 1)):
        interval = "(0, 1]" if closed_high else "(0, 1)"
        raise ValueError(f"{where}: se esperaba un valor en {interval}, se recibió {value!r}")


def _names(values: tuple[str, ...], allowed: tuple[str, ...], where: str) -> None:
    if not values or len(set(values)) != len(values):
        raise ValueError(f"{where}: se esperaba una lista no vacía y sin repetidos, se recibió {list(values)}")
    for value in values:
        if value not in allowed:
            raise ValueError(f"{where}: {value!r} no es un valor conocido ({', '.join(allowed)})")


def _positive_ints(values: tuple[int, ...], where: str) -> None:
    if not values or len(set(values)) != len(values):
        raise ValueError(f"{where}: se esperaba una lista no vacía y sin repetidos, se recibió {list(values)}")
    for value in values:
        _at_least(value, 1, where)


def _on_the_hour(value: datetime, where: str) -> None:
    if value.minute or value.second or value.microsecond:
        raise ValueError(f"{where}: se esperaba una hora en punto (minutos y segundos en cero), se recibió {value}")


def _check_source(cfg: PipelineConfig) -> None:
    s = cfg.source
    for key in ("max_bytes", "max_rows", "max_line_bytes"):
        _positive(getattr(s, key), f"[source] {key}")
    _at_least(s.accepted_bytes, 0, "[source] accepted_bytes")
    if s.accepted_sha256:
        if not _SHA256.fullmatch(s.accepted_sha256):
            raise ValueError(f"[source] accepted_sha256: se esperaban 64 caracteres hexadecimales en minúscula, se recibió {s.accepted_sha256!r}")
        if s.accepted_bytes == 0:
            raise ValueError("[source] accepted_bytes: con una huella aceptada se esperaba un tamaño mayor que 0")
        if s.accepted_bytes > s.max_bytes:
            raise ValueError(f"[source] accepted_bytes: el tamaño aceptado ({s.accepted_bytes}) supera max_bytes ({s.max_bytes})")
    else:
        quick = Path(os.path.normpath(cfg.project_root / "data" / "quick"))
        if quick not in Path(os.path.normpath(s.path)).parents:
            raise ValueError(
                f"[source] accepted_sha256: vacía solo se admite en el modo rápido, con la fuente bajo data/quick/ ({quick}); "
                f"la fuente real exige los 64 caracteres de su huella (se recibió la ruta {s.path})"
            )
        if s.accepted_bytes != 0:
            raise ValueError(f"[source] accepted_bytes: con accepted_sha256 vacía (modo rápido) se esperaba 0, se recibió {s.accepted_bytes}")
    if not s.relation.strip():
        raise ValueError("[source] relation: se esperaba un texto no vacío")
    names = s.attributes
    if len(names) != ATTRIBUTE_COUNT or len(set(names)) != len(names) or not all(name.strip() for name in names):
        raise ValueError(f"[source] attributes: se esperaban {ATTRIBUTE_COUNT} nombres distintos y no vacíos, se recibió {list(names)}")


def _check_calendar(cfg: PipelineConfig) -> None:
    """The hours, the launch and the blocks of D10, with a purge of at least ``purge_hours`` whole hours at every boundary between blocks."""
    h, d, s, lab = cfg.hours, cfg.deliveries, cfg.split, cfg.lab
    _positive(h.rows_per_hour, "[hours] rows_per_hour")
    if not 1 <= h.min_rows_per_hour <= h.rows_per_hour:
        raise ValueError(f"[hours] min_rows_per_hour: se esperaba un valor de 1 a rows_per_hour ({h.rows_per_hour}), se recibió {h.min_rows_per_hour!r}")
    _at_least(lab.latency_hours, 1, "[lab] latency_hours")
    _at_least(d.cadence_hours, 1, "[deliveries] cadence_hours")
    _at_least(s.purge_hours, 0, "[split] purge_hours")
    _at_least(s.min_fresh_hours_per_block, 1, "[split] min_fresh_hours_per_block")
    for section, obj in (("hours", h), ("deliveries", d), ("split", s)):
        for field in dataclasses.fields(obj):
            if field.type == "datetime":
                _on_the_hour(getattr(obj, field.name), f"[{section}] {field.name}")
    if not h.first_hour < d.launch_last_hour < h.last_hour:
        raise ValueError(
            f"[hours] first_hour: se esperaba first_hour < launch_last_hour < last_hour, se recibió {h.first_hour}, {d.launch_last_hour} y {h.last_hour}"
        )
    from flotsilica.split import check_split

    check_split(cfg)      # the blocks, the first and the last hour of the data and a purge at every boundary (AC09): split.py is their one home
    if d.launch_last_hour < s.v2_last:
        raise ValueError(f"[deliveries] launch_last_hour: el lanzamiento debe incluir todo V2 (v2_last = {s.v2_last}), se recibió {d.launch_last_hour}")
    if d.launch_last_hour >= s.test_first:
        raise ValueError(
            f"[deliveries] launch_last_hour: debe ser anterior a test_first ({s.test_first}): la prueba no se entrega con el lanzamiento, "
            f"se recibió {d.launch_last_hour}"
        )


def _check(cfg: PipelineConfig) -> None:
    _check_source(cfg)
    _check_calendar(cfg)

    f = cfg.features
    _names(f.sets, FEATURE_SET_NAMES, "[features] sets")
    _at_least(f.lab_last, 1, "[features] lab_last")
    _positive_ints(f.lab_means, "[features] lab_means")
    _at_least(f.min_fresh_history, 1, "[features] min_fresh_history")

    m = cfg.model
    _names(m.families, MODEL_FAMILY_NAMES, "[model] families")
    _names(m.targets, MODEL_TARGET_NAMES, "[model] targets")
    _positive(m.hgb_learning_rate, "[model] hgb_learning_rate")
    _positive(m.hgb_max_iter, "[model] hgb_max_iter")
    _at_least(m.hgb_max_leaf_nodes, 2, "[model] hgb_max_leaf_nodes")
    _positive_ints(m.hgb_min_samples_leaf, "[model] hgb_min_samples_leaf")
    if not (math.isfinite(m.hgb_l2_regularization) and m.hgb_l2_regularization >= 0):
        raise ValueError(f"[model] hgb_l2_regularization: se esperaba 0 o más, se recibió {m.hgb_l2_regularization!r}")
    _positive(m.rf_n_estimators, "[model] rf_n_estimators")
    _fraction(m.rf_max_features, "[model] rf_max_features", closed_high=True)
    _positive_ints(m.rf_min_samples_leaf, "[model] rf_min_samples_leaf")
    _seed(m.random_state, "[model] random_state")
    _names(m.refit_on, REFIT_BLOCK_NAMES, "[model] refit_on")
    if not _FOLDER_NAME.fullmatch(m.model_version) or m.model_version.endswith("."):
        raise ValueError(
            f"[model] model_version: se esperaba un nombre de carpeta simple (letras, números, «_», «-» y puntos entre otros caracteres; sin "
            f"espacios, separadores de ruta ni punto al empezar o al terminar, y distinto de «.» y «..»), se recibió {m.model_version!r}"
        )

    b = cfg.baselines
    _positive_ints(b.rolling_k, "[baselines] rolling_k")
    _positive(b.ridge_alpha, "[baselines] ridge_alpha")
    _names(b.strongest_candidates, STRONGEST_CANDIDATE_NAMES, "[baselines] strongest_candidates")

    i = cfg.intervals
    _fraction(i.coverage, "[intervals] coverage")
    if i.calibrate_on != "valid_v2":
        raise ValueError(f"[intervals] calibrate_on: el único bloque de calibración es 'valid_v2' (D15), se recibió {i.calibrate_on!r}")

    e = cfg.evaluation
    if not e.horizons:
        raise ValueError("[evaluation] horizons: se esperaba una lista no vacía")
    if any(horizon < 0 for horizon in e.horizons):
        raise ValueError(f"[evaluation] horizons: hay un horizonte negativo en {list(e.horizons)}")
    if len(set(e.horizons)) != len(e.horizons):
        raise ValueError(f"[evaluation] horizons: hay un horizonte repetido en {list(e.horizons)}")
    _positive(e.bootstrap_resamples, "[evaluation] bootstrap_resamples")
    _seed(e.bootstrap_seed, "[evaluation] bootstrap_seed")

    v = cfg.sensitivity
    _positive(v.permutation_repeats, "[sensitivity] permutation_repeats")
    _positive(v.refits, "[sensitivity] refits")
    _at_least(v.pd_grid_points, 2, "[sensitivity] pd_grid_points")
    _fraction(v.pd_low_quantile, "[sensitivity] pd_low_quantile")
    _fraction(v.pd_high_quantile, "[sensitivity] pd_high_quantile")
    if not v.pd_low_quantile < v.pd_high_quantile:
        raise ValueError(f"[sensitivity] pd_low_quantile: se esperaba pd_low_quantile < pd_high_quantile, se recibió {v.pd_low_quantile!r} y {v.pd_high_quantile!r}")
    if not (math.isfinite(v.min_importance_mae) and v.min_importance_mae >= 0):
        raise ValueError(f"[sensitivity] min_importance_mae: se esperaba 0 o más, se recibió {v.min_importance_mae!r}")
    _fraction(v.min_abs_spearman, "[sensitivity] min_abs_spearman", closed_high=True)
    _seed(v.seed, "[sensitivity] seed")

    _positive_ints(cfg.variants.latencies, "[variants] latencies")

    k = cfg.criteria
    _fraction(k.c05_coverage_low, "[criteria] c05_coverage_low")
    _fraction(k.c05_coverage_high, "[criteria] c05_coverage_high")
    if not k.c05_coverage_low < k.c05_coverage_high:
        raise ValueError(f"[criteria] c05_coverage_low: se esperaba c05_coverage_low < c05_coverage_high, se recibió {k.c05_coverage_low!r} y {k.c05_coverage_high!r}")
    _positive(k.c06_max_bias, "[criteria] c06_max_bias")
    _fraction(k.leak_tripwire_ratio, "[criteria] leak_tripwire_ratio", closed_high=True)

    _positive(cfg.site.max_total_bytes, "[site] max_total_bytes")

    a = cfg.api
    if a.host != LOOPBACK_HOST:
        raise ValueError(f"[api] host: el servicio solo escucha en la interfaz local {LOOPBACK_HOST} (D27), se recibió {a.host!r}")
    if not 1 <= a.port <= 65535:
        raise ValueError(f"[api] port: se esperaba un puerto de 1 a 65535, se recibió {a.port!r}")
    _positive(a.max_lab_history, "[api] max_lab_history")


# --- reading --------------------------------------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], top: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in top.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_toml(path: Path, _seen: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Read a TOML file, following ``extends`` (relative to the file) and merging over its base."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"no se encontró el archivo de configuración: {path}")
    resolved = path.resolve()
    if resolved in _seen:
        raise ValueError(f"los archivos de configuración se extienden entre sí en un ciclo en {path}")
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    parent = data.pop("extends", None)
    if parent is None:
        return data
    if not isinstance(parent, str):
        raise ValueError(f"{path}: extends debe ser una ruta escrita como texto")
    parent_path = Path(parent)
    if not parent_path.is_absolute():
        parent_path = path.parent / parent_path
    return _deep_merge(_read_toml(parent_path, (*_seen, resolved)), data)


def _home() -> Path | None:
    home = os.environ.get(ENV_HOME)
    if not home:
        return None
    root = Path(home).resolve()
    if not root.is_dir():
        raise ValueError(f"{ENV_HOME}: {home!r} no es una carpeta existente")
    return root


def load_config(path: Path | None = None) -> PipelineConfig:
    """Load the configuration.

    `path` is the main file; without it, ``$FLOTSILICA_CONFIG`` and then ``config/pipeline.toml`` of the project. A relative `path` or
    ``$FLOTSILICA_CONFIG`` is taken from ``$FLOTSILICA_HOME`` or, without it, from this package's project: the working directory may be
    another copy's folder, and its configuration is never read in silence. The paths inside are resolved against ``$FLOTSILICA_HOME`` or
    the parent of the folder that holds the main file. Anything unknown, missing, mistyped or inconsistent is a ``ValueError`` naming the key.
    """
    home = _home()
    if path is None:
        env = os.environ.get(ENV_CONFIG)
        path = Path(env) if env else DEFAULT_CONFIG
    path = Path(path)
    if not path.is_absolute():
        path = (home or DEFAULT_PROJECT_ROOT) / path
    data = _read_toml(path)
    root = home or path.resolve().parent.parent

    sections = [f.name for f in dataclasses.fields(PipelineConfig) if f.name != "project_root"]
    unknown = sorted(set(data) - set(sections))
    if unknown:
        raise ValueError(f"sección desconocida [{unknown[0]}]")
    missing = [s for s in sections if s not in data]
    if missing:
        raise ValueError(f"falta la sección [{missing[0]}]")
    hints = get_type_hints(PipelineConfig)
    built = {name: _build_section(hints[name], data[name], name, root) for name in sections}
    cfg = PipelineConfig(**built, project_root=root)
    _check(cfg)
    return cfg
