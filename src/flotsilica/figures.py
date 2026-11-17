"""Figures of the documentation, drawn with matplotlib from the site files of a run (RF26, AC27; plan, sections 21 and 25). Adapted from project 04's ``figures.py``.

Seven PNG files, always from the verified site files (``data.json``, ``algorithms.json`` and ``operation.json``, read through ``site_export.read_site``, each checked against
``manifest.json``) and never from the warehouse, a Parquet file or a constant: the state of the analyses by block, the interpolated stretch drawn as the straight line it is, the error
of each method by horizon, three days of the test, the error by week, the latencies and the importance of each sensor against the line of the gate. A folder whose files are not one
export is refused with ``SiteSetError`` (project 03, D77).

The files are deterministic (no timestamp in the metadata), so a figure changes only when its data do. Nothing is written unless every figure was drawn and every file staged. Before the
test is sealed the figures that need its results say so instead of staying empty (the site publishes nothing of the test before the seal). Every sensitivity is shown as an
association of the model, never as a cause or an action (D20).
"""

from __future__ import annotations

import io
import logging
import textwrap
from contextlib import ExitStack
from pathlib import Path

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from flotsilica import texts
from flotsilica.files import atomic_path
from flotsilica.site_export import SITE_FILES, SiteFiles, SiteSetError, read_site

logger = logging.getLogger(__name__)

FIGURE_NAMES = ("lab_states_by_block.png", "interpolated_run.png", "horizons_mae.png", "test_day_example.png", "weekly_mae.png", "latency.png", "sensitivity_gate.png")
DPI = 130
INK, GRID, MUTED = "#1f2430", "#e4e6ea", "#5b6270"
ORANGE, BLUE, GREY, GOLD, GREEN = "#eb6834", "#2a78d6", "#8a8f98", "#eda100", "#1baf7a"
PENDING = "La prueba se evalúa una sola vez, cuando llega su último análisis: hasta entonces no se publica ninguna cifra suya"
NO_RUN = "No hay un tramo interpolado en el entrenamiento de esta corrida"
STATE_COLORS = {"fresh": GREEN, "held": GOLD, "interpolated": BLUE, "missing": GREY, "pending": GRID}
STATES = tuple(STATE_COLORS)
SHORT_ES = {"model": "Modelo", "b0_train_mean": "B0", "b1_persistence": "B1", "b2_rolling": "B2", "b3_ridge_sensors": "B3", "best_sensors_only": "Solo sensores",
            "best_lab_only": "Solo laboratorio", "best_with_sensors": "Con sensores"}
DAYS_ES = {"median": "Día de mediana", "worst": "El peor día", "best": "El mejor día"}


# --- data -------------------------------------------------------------------------------------------------------------------------


def load_site(site_dir: Path) -> SiteFiles:
    """The documents of the site files of a run, read through ``read_site``: a missing file says what to run, and a folder that is not one export is a ``SiteSetError`` (never
    figures drawn from two exports)."""
    for name in (*SITE_FILES, "manifest.json"):
        path = Path(site_dir) / name
        if not path.is_file():
            raise FileNotFoundError(f"No existe {path}: corra el flujo (python -m flotsilica run) antes de dibujar las figuras")
    try:
        return read_site(site_dir)
    except SiteSetError as error:
        raise SiteSetError(f"{error}. Corra el flujo (python -m flotsilica run) antes de dibujar las figuras") from None


# --- drawing helpers --------------------------------------------------------------------------------------------------------------


def _spanish(value: float | None, digits: int = 0) -> str:
    return texts.es(value, digits)


def _style(ax, y_label: str | None = None, grid: str = "y") -> None:
    ax.set_facecolor("white")
    ax.grid(axis=grid, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=9)
    if y_label:
        ax.set_ylabel(y_label, color=MUTED, fontsize=9)


def _figure(width: float = 10, height: float = 4.8) -> Figure:
    fig = Figure(figsize=(width, height), dpi=DPI, facecolor="white")
    FigureCanvasAgg(fig)
    return fig


def _title(fig: Figure, title: str, subtitle: str) -> None:
    fig.text(0.01, 0.975, title, fontsize=13, fontweight="bold", color=INK, va="top")
    fig.text(0.01, 0.925, textwrap.fill(subtitle, 135), fontsize=9, color=MUTED, va="top", linespacing=1.4)


def _pending(ax, text: str = PENDING, width: int = 70) -> None:
    ax.text(0.5, 0.5, textwrap.fill(text, width), ha="center", va="center", transform=ax.transAxes, color=MUTED, fontsize=11)
    ax.set_xticks([])
    ax.set_yticks([])


def _value(value: float | None) -> float:
    """What a bar is as high as: a value the site publishes as ``null`` is a gap (no bar), never a number."""
    return 0.0 if value is None else value


def _row_of_axes(fig: Figure, count: int, top: float = 0.76, bottom: float = 0.2) -> list:
    return list(fig.subplots(1, count, squeeze=False, gridspec_kw={"left": 0.07, "right": 0.98, "top": top, "bottom": bottom, "wspace": 0.22})[0])


# --- the figures --------------------------------------------------------------------------------------------------------------------


def draw_lab_states(site: SiteFiles) -> Figure:
    fig = _figure(8, 4.8)
    _title(fig, "Qué análisis hay en cada bloque", "Horas de cada bloque según su análisis de laboratorio: solo los nuevos son una medición; los interpolados y los repetidos "
           "no son objetivo ni rasgo (D05). Las horas «sin datos» son las que el archivo no trae.")
    ax = fig.add_axes([0.1, 0.12, 0.88, 0.68])
    _style(ax, "Horas")
    blocks = site.data["states_by_block"]
    bottoms = [0.0] * len(blocks)
    for state in STATES:
        heights = [float(b[state]) for b in blocks]
        ax.bar(range(len(blocks)), heights, 0.6, bottom=bottoms, color=STATE_COLORS[state], label=texts.LAB_STATES_ES[state])
        bottoms = [b + h for b, h in zip(bottoms, heights, strict=True)]
    ax.set_xticks(range(len(blocks)), [b["label_es"] for b in blocks], fontsize=9)
    for i, total in enumerate(bottoms):
        ax.text(i, total, f"{_spanish(total)} h", ha="center", va="bottom", fontsize=8, color=MUTED)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _spanish(v)))
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    return fig


def draw_interpolated_run(site: SiteFiles) -> Figure:
    fig = _figure(8, 4.8)
    _title(fig, "Un tramo interpolado es una recta, no una medición", "El tramo interpolado más largo del entrenamiento: entre dos análisis nuevos, las horas "
           "del medio son puntos de la recta que los une. Por eso no son objetivo ni rasgo.")
    ax = fig.add_axes([0.1, 0.14, 0.86, 0.66])
    _style(ax, "Sílice en el concentrado (%)")
    run = site.data["interpolated_run"]
    if run is None:
        _pending(ax, NO_RUN, 55)
        return fig
    n = len(run["values"])
    anchors = [(x, y) for x, y in ((0, run["start_value"]), (n + 1, run["end_value"])) if y is not None]
    ax.plot([x for x, _ in anchors], [y for _, y in anchors], color=GREY, linewidth=1.5, linestyle="--", marker="o", markersize=6, label="Análisis nuevos")
    ax.plot(range(1, n + 1), run["values"], color=BLUE, linewidth=0, marker="o", markersize=6, label="Horas interpoladas")
    ax.set_xticks(range(n + 2), ["análisis", *(h[11:16] for h in run["hours"]), "análisis"], fontsize=8)
    ax.margins(x=0.08)
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    if run["slope_per_hour"] is not None:
        ax.text(0.02, 0.05, f"Pendiente: {_spanish(run['slope_per_hour'], 2)} puntos por hora", transform=ax.transAxes, color=MUTED, fontsize=9)
    return fig


def draw_horizons(site: SiteFiles) -> Figure:
    fig = _figure(12, 5.2)
    _title(fig, "Error de cada método por horizonte", "MAE (puntos de sílice) de cada método en la validación V1, en V2 y en la prueba. B0: media del entrenamiento; B1: persistencia; "
           "B2: media de los últimos análisis; B3: ridge sobre sensores. Una barra ausente es una cifra que todavía no existe.")
    horizons = site.algorithms["horizons"]
    for ax, horizon in zip(_row_of_axes(fig, len(horizons), bottom=0.22), horizons, strict=True):
        _style(ax, "MAE (puntos de sílice)" if horizon["horizon"] == 0 else None)
        methods, x, width = horizon["methods"], list(range(len(horizon["methods"]))), 0.27
        for k, (key, color, label) in enumerate((("mae_v1", GREY, "V1"), ("mae_v2", GOLD, "V2"), ("mae_test", ORANGE, "Prueba"))):
            ax.bar([i + (k - 1) * width for i in x], [_value(m[key]) for m in methods], width, color=color, label=label)
        ax.set_xticks(x, [SHORT_ES[m["method"]] for m in methods], rotation=45, ha="right", fontsize=8)
        ax.set_title(f"{horizon['label_es']} (B*: {SHORT_ES[horizon['b_star']] if horizon['b_star'] in SHORT_ES else horizon['b_star']})", fontsize=9, color=INK)
        if horizon["horizon"] == 0:
            ax.legend(frameon=False, fontsize=8, loc="upper left")
    return fig


def draw_test_day(site: SiteFiles) -> Figure:
    fig = _figure(12, 4.6)
    _title(fig, "Tres días de la prueba", "La estimación de la hora que cerró con su rango del 80 %, el análisis cuando llegó (solo si es nuevo) y la persistencia, el día de mediana, "
           "el peor y el mejor según el error del modelo.")
    hours, days, daily = site.operation["test_hours"], site.operation["example_days"], {d["date"]: d for d in site.operation["daily"]}
    if not hours["hour"] or not any(days.values()):
        _pending(_row_of_axes(fig, 1)[0])
        return fig
    for ax, key in zip(_row_of_axes(fig, 3, bottom=0.17), ("median", "worst", "best"), strict=True):
        date = days[key]["date"]
        wanted = [i for i, hour in enumerate(hours["hour"]) if hour.startswith(date)]
        x = [int(hours["hour"][i][11:13]) for i in wanted]
        _style(ax, "Sílice en el concentrado (%)" if key == "median" else None)
        ax.fill_between(x, [hours["low"][i] for i in wanted], [hours["high"][i] for i in wanted], color=ORANGE, alpha=0.18, linewidth=0)
        ax.plot(x, [hours["estimate"][i] for i in wanted], color=ORANGE, linewidth=2, label="Estimación y su rango")
        ax.plot(x, [hours["persistence"][i] for i in wanted], color=GREY, linewidth=1.5, linestyle="--", label="Persistencia")
        fresh = [i for i in wanted if hours["actual"][i] is not None]
        ax.scatter([int(hours["hour"][i][11:13]) for i in fresh], [hours["actual"][i] for i in fresh], color=BLUE, s=22, zorder=3, label="Análisis")
        ax.set_title(f"{DAYS_ES[key]}: {date} (MAE {_spanish(daily[date]['mae_model'], 2)})", fontsize=9, color=INK)
        ax.set_xlabel("Hora del día", color=MUTED, fontsize=9)
        if key == "median":
            ax.legend(frameon=False, fontsize=8, loc="upper left")
    return fig


def draw_weekly(site: SiteFiles) -> Figure:
    fig = _figure(12, 4.4)
    _title(fig, "Error por semana de la prueba", "MAE del modelo, de la persistencia y de la base más fuerte (B*) en cada semana de la prueba, para cada horizonte. "
           "La semana 1 empieza el primer día de la prueba.")
    weekly = site.operation["weekly"]
    if not weekly:
        _pending(_row_of_axes(fig, 1)[0])
        return fig
    horizons = sorted({w["horizon"] for w in weekly})
    for ax, horizon in zip(_row_of_axes(fig, len(horizons), bottom=0.16), horizons, strict=True):
        part = [w for w in weekly if w["horizon"] == horizon]
        _style(ax, "MAE (puntos de sílice)" if horizon == horizons[0] else None)
        for key, color, style, label in (("mae_model", ORANGE, "-", "Modelo"), ("mae_persistence", GREY, "-", "Persistencia"), ("mae_b_star", BLUE, "--", "Base más fuerte (B*)")):
            ax.plot([w["week"] for w in part], [w[key] for w in part], color=color, linewidth=2, linestyle=style, marker="o", markersize=4, label=label)
        ax.set_title(texts.HORIZON_LABELS_ES.get(horizon, f"Horizonte {horizon}"), fontsize=9, color=INK)
        ax.set_xlabel("Semana de la prueba", color=MUTED, fontsize=9)
        ax.set_xticks([w["week"] for w in part])
        if horizon == horizons[0]:
            ax.legend(frameon=False, fontsize=8, loc="upper left")
    return fig


def draw_latency(site: SiteFiles) -> Figure:
    fig = _figure(8, 4.8)
    _title(fig, "Si el laboratorio tardara más", "MAE de la hora que cerró en la prueba, con el modelo reajustado a cada espera y la persistencia de esa espera; el texto de cada grupo "
           "es el intervalo del 95 % de la diferencia (modelo menos persistencia).")
    ax = fig.add_axes([0.1, 0.14, 0.86, 0.66])
    _style(ax, "MAE (puntos de sílice)")
    rows = site.algorithms["latency"]
    if not rows or all(r["mae_model"] is None and r["mae_persistence"] is None for r in rows):
        _pending(ax)
        return fig
    x, width = list(range(len(rows))), 0.36
    ax.bar([i - width / 2 for i in x], [_value(r["mae_model"]) for r in rows], width, color=ORANGE, label="Modelo")
    ax.bar([i + width / 2 for i in x], [_value(r["mae_persistence"]) for r in rows], width, color=GREY, label="Persistencia")
    ax.set_xticks(x, [f"{r['latency_hours']} h" for r in rows])
    for i, r in enumerate(rows):
        if r["ci_low"] is not None:
            ax.text(i, max(_value(r["mae_model"]), _value(r["mae_persistence"])), f"de {_spanish(r['ci_low'], 2)} a {_spanish(r['ci_high'], 2)}", ha="center", va="bottom", fontsize=8, color=MUTED)
    ax.set_xlabel("Espera del laboratorio", color=MUTED, fontsize=9)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    return fig


def draw_sensitivity_gate(site: SiteFiles) -> Figure:
    fig = _figure(10, 6.2)
    sensors, gate = site.algorithms["sensitivity"], site.algorithms["gate"]
    passing = [s["sensor"] for s in sensors if s["passes"]]
    _title(fig, "Importancia de cada sensor como asociación del modelo, no una receta",
           "Aumento medio del error al permutar el sensor, en V1 y en V2, contra el mínimo de la compuerta de estabilidad. " + texts.gate_summary(passing, bool(sensors)))
    ax = fig.add_axes([0.3, 0.09, 0.67, 0.74])
    _style(ax, grid="x")
    y, height = list(range(len(sensors))), 0.38
    ax.barh([i - height / 2 for i in y], [_value(s["importance_v1"]) for s in sensors], height, color=BLUE, label="V1")
    ax.barh([i + height / 2 for i in y], [_value(s["importance_v2"]) for s in sensors], height, color=ORANGE, label="V2")
    ax.set_yticks(y, [s["name_es"] for s in sensors], fontsize=8)
    ax.invert_yaxis()
    ax.axvline(gate["min_importance_mae"], color=INK, linewidth=1, linestyle=":")
    ax.text(gate["min_importance_mae"], -0.9, f" Compuerta: {_spanish(gate['min_importance_mae'], 2)}", fontsize=8, color=INK, va="bottom")
    ax.set_xlabel("Importancia por permutación (puntos de MAE)", color=MUTED, fontsize=9)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    return fig


def draw_all(site: SiteFiles) -> dict[str, Figure]:
    """The seven figures, by file name, from the site data; no file is touched."""
    return {
        "lab_states_by_block.png": draw_lab_states(site), "interpolated_run.png": draw_interpolated_run(site), "horizons_mae.png": draw_horizons(site),
        "test_day_example.png": draw_test_day(site), "weekly_mae.png": draw_weekly(site), "latency.png": draw_latency(site), "sensitivity_gate.png": draw_sensitivity_gate(site),
    }


# --- entry point --------------------------------------------------------------------------------------------------------------------


def _png(fig: Figure) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", metadata={"Software": None})
    return buffer.getvalue()


def write_figures(site_dir: Path, out_dir: Path) -> list[Path]:
    """Draw the seven figures from the verified site files of `site_dir` and write them to `out_dir`; returns the paths in ``FIGURE_NAMES`` order. Every figure is drawn and
    rendered, and every file is written to a temporary file of its own next to its target, before the first target is replaced: a missing or mixed site folder, a figure that
    fails or a write that fails (a full disk, a permission) replaces nothing, leaves no temporary file and no folder it created. Only a failure of the rename itself, after all the
    files were written, can leave some figures replaced."""
    drawn = draw_all(load_site(site_dir))
    rendered = {name: _png(drawn[name]) for name in FIGURE_NAMES}
    out_dir = Path(out_dir)
    created = not out_dir.exists()
    try:
        with ExitStack() as stack:   # the files are replaced when the block ends cleanly, in FIGURE_NAMES order; an error removes every temporary file
            staged = {name: stack.enter_context(atomic_path(out_dir / name)) for name in reversed(FIGURE_NAMES)}
            for name in FIGURE_NAMES:
                staged[name].write_bytes(rendered[name])
    except BaseException:
        if created:
            try:
                out_dir.rmdir()   # only while it is empty: a folder this call made for files it never got
            except OSError:
                pass
        raise
    paths = [out_dir / name for name in FIGURE_NAMES]
    for path in paths:
        logger.info("figure %s written", path)
    return paths


__all__ = ["FIGURE_NAMES", "NO_RUN", "PENDING", "draw_all", "load_site", "write_figures"]
