"""The HTML design of the Power BI report, generated from the semantic model and the exported Parquet (RF22, AC26; plan, section 20; D25). Adapted from project 04's
``dashboard/render.py`` without its privacy layer (no masked column, no minimum cell, D43); it is not imported from it.

One self-contained page (inline CSS, inline SVG, no scripts, no fonts or images from the network) with the steps to build the report in Power BI Desktop, the diagram of the model, the
relationships, the Power Query code of each table, the DAX measures and the five pages placed on a 12 x 9 grid, each visual with a preview drawn from the exported tables. Nothing here is
typed by hand twice: change ``semantic_model.py`` and render again.

Rules for what a preview shows. Every text that comes from the data goes through ``html.escape``. The previews are the figures of the exported tables with no slicer applied: the document says
that no measure was run (there is no Power BI here), so a card is what the table says, not what the DAX would give. An evaluation shows the sealed rows of the test and, when there are none,
says that what it shows is validation and not the test. A sensitivity is an association of the model and the page never calls it anything else (D20). The file is written through
``files.write_atomic``.
"""

from __future__ import annotations

import logging
from html import escape
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from flotsilica.dashboard import svg
from flotsilica.dashboard.semantic_model import PAGE_COLUMNS, PAGE_ROWS, Page, SemanticModel, Visual, dax_measure_refs, validate_model
from flotsilica.files import write_atomic
from flotsilica.ingest import ATTRIBUTION
from flotsilica.scoring import RunMeta

logger = logging.getLogger(__name__)

PAGE_WIDTH_PX, PAGE_HEIGHT_PX = 1280, 720
CELL_W, CELL_H = PAGE_WIDTH_PX / PAGE_COLUMNS, PAGE_HEIGHT_PX / PAGE_ROWS
HEADER_PX = 26
WINDOW_HOURS = 72           # the hours of the line chart of page 1
MULTIPLES_COLUMNS = 4       # the small multiples of page 3
TABLE_ROWS = 9              # the most rows a table preview shows
DAYS_SHOWN = 14             # the most days the bars of page 5 show
TITLE = "Diseño del tablero de Power BI: la sílice del concentrado de flotación, estimada hora a hora"
SECTIONS = (
    ("armado", "Cómo armarlo en Power BI Desktop"),
    ("modelo", "El modelo en estrella"),
    ("relaciones", "Relaciones"),
    ("consultas", "Power Query: una consulta por tabla"),
    ("medidas", "Medidas DAX"),
    ("paginas", "Las cinco páginas"),
    ("fuente", "Fuente y licencia"),
)
KIND_ES = {"slicer": "Segmentador", "card": "Tarjeta", "lineChart": "Gráfico de líneas", "barChart": "Gráfico de barras", "table": "Tabla"}
SCOPE_ES = {"valid_v1": "V1", "valid_v2": "V2", "test": "Prueba"}
RULE_METHODS = ("model", "b0_train_mean", "b1_persistence", "b2_rolling")      # the methods the bars and the lines of page 2 draw: the model and the three rules
DASH = "—"
CSS = """
:root{color-scheme:light;--surface:#fcfcfb;--panel:#f3f2ef;--text:#0b0b0b;--text-2:#52514e;--muted:#6f6e69;--line:#d9d8d3;--accent:#256abf;
--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;--series-4:#eda100;--series-5:#e87ba4;--series-6:#008300;--series-7:#6250d6;--series-8:#e34948}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--surface:#1a1a19;--panel:#242422;--text:#f0efec;--text-2:#c3c2b7;--muted:#a3a299;--line:#3a3a37;--accent:#6da7ec;
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--series-4:#c98500;--series-5:#d55181;--series-6:#008300;--series-7:#9085e9;--series-8:#e66767}}
:root[data-theme="dark"]{color-scheme:dark;--surface:#1a1a19;--panel:#242422;--text:#f0efec;--text-2:#c3c2b7;--muted:#a3a299;--line:#3a3a37;--accent:#6da7ec;
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--series-4:#c98500;--series-5:#d55181;--series-6:#008300;--series-7:#9085e9;--series-8:#e66767}
*{box-sizing:border-box}
body{margin:0;background:var(--surface);color:var(--text);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;line-height:1.25;margin:0 0 4px}h2{font-size:1.3rem;margin:48px 0 8px;padding-top:8px;border-top:1px solid var(--line)}
h3{font-size:1.05rem;margin:28px 0 8px}p,li{max-width:78ch}a{color:var(--accent)}
.lead{color:var(--text-2);margin:0 0 16px}.meta{display:flex;flex-wrap:wrap;gap:8px 24px;color:var(--text-2);font-size:.9rem;margin:12px 0}
nav ul{display:flex;flex-wrap:wrap;gap:4px 16px;padding:0;list-style:none;margin:16px 0}
code,pre{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.85rem}
pre{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 12px;overflow-x:auto;margin:6px 0;white-space:pre}
table{border-collapse:collapse;width:100%;font-size:.88rem}th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{color:var(--text-2);font-weight:600;background:var(--surface)}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}.warn{border-left:3px solid var(--series-4);padding:4px 12px;background:var(--panel);margin:12px 0}
.model-svg{width:100%;height:auto;display:block}.model-svg .box{fill:var(--panel);stroke:var(--line)}.model-svg .dim{stroke:var(--series-1)}
.model-svg .fact{stroke:var(--series-2)}.model-svg text{fill:var(--text);font-size:12px}.model-svg .small{fill:var(--text-2);font-size:10px}
.model-svg .rel{stroke:var(--muted);stroke-width:1;fill:none;opacity:.55}.model-svg .card{font-weight:700;fill:var(--accent)}
.canvas-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:8px}
.canvas{display:grid;grid-template-columns:repeat(12,1fr);grid-template-rows:repeat(9,1fr);gap:6px;aspect-ratio:16/9;min-width:960px;max-width:1280px}
.visual{background:var(--surface);border:1px solid var(--line);border-radius:6px;overflow:hidden;display:flex;flex-direction:column;min-width:0;min-height:0}
.visual header{display:flex;justify-content:space-between;gap:6px;padding:2px 8px;font-size:.75rem;color:var(--text-2);height:26px;align-items:center}
.visual header b{color:var(--text);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.visual header span{white-space:nowrap;color:var(--muted)}
.visual .body{flex:1;min-height:0;padding:0 8px 3px;overflow:hidden;font-size:.75rem}.visual .body svg{max-width:100%;height:auto;display:block}
.big{font-size:1.2rem;font-weight:700;line-height:1.15;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sub{color:var(--muted);font-size:.65rem;line-height:1.1}
.chips{display:flex;flex-wrap:nowrap;gap:3px;overflow:hidden}.chip{white-space:nowrap;border:1px solid var(--line);border-radius:10px;padding:0 6px;font-size:.7rem;color:var(--text-2)}
.visual table{font-size:.7rem}.visual th,.visual td{padding:1px 5px}.rows p{margin:1px 0;font-size:.75rem}
.multiples{display:grid;grid-template-columns:repeat(4,1fr);gap:2px 6px}.multiples figure{margin:0;min-width:0}.multiples figcaption{font-size:.6rem;color:var(--text-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
svg .svg-grid{stroke:var(--line);stroke-width:1}svg .svg-axis{stroke:var(--muted);stroke-width:1}
svg .svg-tick,svg .svg-legend,svg .svg-note,svg .svg-value{fill:var(--text-2);font-size:10px}svg .svg-value{fill:var(--text)}
svg .svg-hit{fill:transparent}svg .svg-hit:hover{fill:var(--text);fill-opacity:.15}
.placement td:first-child{white-space:nowrap}
@media print{.canvas-wrap{break-inside:avoid}body{font-size:12px}}
"""


# --- data ---------------------------------------------------------------------------------------------------------------------


class _Data:
    """The exported tables the previews are drawn from (a missing file is an empty table with its columns) and what their files say about the run."""

    def __init__(self, parquet_dir: Path, model: SemanticModel) -> None:
        self.t: dict[str, pd.DataFrame] = {}
        for table in model.tables:
            path = Path(parquet_dir) / f"{table.name}.parquet"
            self.t[table.name] = pd.read_parquet(path) if path.is_file() else pd.DataFrame(columns=list(table.column_names))
        path = Path(parquet_dir) / "dim_pipeline_run.parquet"
        metadata = pq.read_schema(path).metadata or {} if path.is_file() else {}
        self.source_sha256 = metadata.get(b"flotsilica.source_sha256", DASH.encode()).decode("utf-8", "replace")
        method = self.t["dim_method"]
        self.method_es = dict(zip(method["method_key"], method["method_es"], strict=True))
        horizon = self.t["dim_horizon"]
        self.horizon_es = {int(k): v for k, v in zip(horizon["horizon_key"], horizon["horizon_es"], strict=True)}
        est = self.t["fact_estimate"]
        self.arrived = est[est["actual"].notna()]

    def scope(self, name: str) -> tuple[pd.DataFrame, str]:
        """The rows of an evaluation fact: the sealed ones when there are any, for the test or else for V2 or V1, with what is shown in Spanish (never the test unless it is)."""
        frame = self.t[name]
        if "seal_state" in frame.columns and (frame["seal_state"] == "sealed").any():
            frame = frame[frame["seal_state"] == "sealed"]
        for scope, label in (("test", "prueba"), ("valid_v2", "validación (V2), no es la prueba"), ("valid_v1", "validación (V1), no es la prueba")):
            part = frame[frame["scope"] == scope] if "scope" in frame.columns else frame.iloc[0:0]
            if len(part):
                return part, label
        return frame.iloc[0:0], "sin evaluar"

    def sealed(self, name: str) -> pd.DataFrame:
        frame = self.t[name]
        return frame[frame["seal_state"] == "sealed"] if "seal_state" in frame.columns and (frame["seal_state"] == "sealed").any() else frame

    def horizon(self, key) -> str:
        return self.horizon_es.get(int(key), str(key)) if pd.notna(key) else DASH

    def method(self, key) -> str:
        return self.method_es.get(key, str(key))


def _missing(value) -> bool:
    return value is None or bool(pd.isna(value))


def _fmt(value, digits: int = 3) -> str:
    return DASH if _missing(value) else f"{float(value):.{digits}f}".replace(".", ",")


def _int(value) -> str:
    return DASH if _missing(value) else f"{int(value):,}".replace(",", ".")


def _pct(value, digits: int = 1) -> str:
    return DASH if _missing(value) else f"{float(value) * 100:.{digits}f} %".replace(".", ",")


def _hour(hour_key) -> str:
    text = str(int(hour_key))
    return f"{text[:4]}-{text[4:6]}-{text[6:8]} {text[8:10]}:00"


def _when(value) -> str:
    return DASH if _missing(value) else pd.Timestamp(value).strftime("%Y-%m-%d %H:%M")


def _table_html(headers: list[str], rows: list[list[str]], numeric: set[int] = frozenset()) -> str:
    """A table; every cell is escaped."""
    head = "".join(f'<th{" class=num" if i in numeric else ""}>{escape(h)}</th>' for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f'<td{" class=num" if i in numeric else ""}>{escape(str(c))}</td>' for i, c in enumerate(row)) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body or '<tr><td>Sin datos</td></tr>'}</tbody></table>"


def _size(v: Visual) -> tuple[int, int]:
    return max(int(v.w * CELL_W - 22), 60), max(int(v.h * CELL_H - HEADER_PX - 12), 40)


def _card(big: str, sub: str = "") -> str:
    return f'<div class="big">{escape(big)}</div><div class="sub">{escape(sub)}</div>'


def _note(text: str) -> str:
    return f'<div class="rows"><p>{escape(text)}</p></div>'


def _caption(text: str) -> str:
    return f'<div class="sub">{escape(text)}</div>'


# --- previews ---------------------------------------------------------------------------------------------------------------------


def _slicer(data: _Data, field: str) -> str:
    table, column = field.split("[")[0], field.split("[")[1].rstrip("]")
    values = data.t[table][column].dropna() if column in data.t[table].columns else pd.Series(dtype=object)
    shown = sorted({str(x) for x in values})
    if column in ("date", "hour") and shown:
        chips = f'<span class="chip">{escape(shown[0])}</span><span class="chip">a</span><span class="chip">{escape(shown[-1])}</span><span class="chip">{len(shown)} días</span>'
        return f'<div class="chips">{chips}</div>'
    chips = "".join(f'<span class="chip">{escape(x)}</span>' for x in shown[:3])
    more = f'<span class="chip">+{len(shown) - 3}</span>' if len(shown) > 3 else ""
    return f'<div class="chips">{chips or "Sin datos"}{more}</div>'


def _cards(data: _Data) -> dict:
    est, lab, arrived = data.t["fact_estimate"], data.t["fact_hour_lab"], data.arrived
    runs, rules, quality = data.t["dim_pipeline_run"], data.t["fact_validation"], data.t["fact_data_quality"]
    every = "todas las fechas y horizontes, sin segmentadores"
    last = est[(est["status"] == "ok") & (est["horizon_key"] == 0)].sort_values("hour_key")
    fresh = lab[(lab["lab_state"] == "fresh") & lab["silica_pct"].notna()].sort_values("hour_key")
    arrived_lab = lab[lab["silica_pct"].notna()]
    ok_runs = runs[runs["status"] == "ok"]
    blocking = rules[(rules["severity"] == "bloqueante") & (rules["status"] == "falla")]
    n = len(arrived)

    def mean(column: str):
        return arrived[column].mean() if n else None

    bias = (arrived["estimate"] - arrived["actual"]).mean() if n else None
    return {
        "[Última estimación]": lambda: _card(_fmt(last.iloc[-1]["estimate"], 2) if len(last) else DASH, f"hora {_hour(last.iloc[-1]['hour_key'])}, horizonte 0" if len(last) else "sin estimaciones"),
        "[Último análisis llegado]": lambda: _card(_fmt(fresh.iloc[-1]["silica_pct"], 2) if len(fresh) else DASH, f"hora {_hour(fresh.iloc[-1]['hour_key'])}, análisis nuevo" if len(fresh) else "sin análisis"),
        "[MAE del modelo]": lambda: _card(_fmt(mean("abs_error")), f"{_int(n)} estimaciones con análisis; {every}"),
        "[MAE de la persistencia]": lambda: _card(_fmt(mean("abs_error_persistence")), f"las mismas {_int(n)} estimaciones"),
        "[Cobertura del rango]": lambda: _card(_pct((arrived["covered"] == True).sum() / n if n else None), "análisis dentro del rango del 80 %"),  # noqa: E712
        "[Horas sin estimación]": lambda: _card(_int((est["status"] == "missing_inputs").sum()), "estimaciones sin las entradas necesarias"),
        "[MAE de la base más fuerte]": lambda: _card(_fmt(mean("abs_error_b_star")), "B* de cada horizonte; las mismas estimaciones"),
        "[Modelo menos persistencia]": lambda: _card(_fmt(mean("abs_error") - mean("abs_error_persistence") if n else None), "negativo: el modelo se equivoca menos"),
        "[Sesgo del modelo]": lambda: _card(_fmt(bias), "estimación menos análisis, en promedio"),
        "[Sensores con asociación estable]": lambda: _card(_int(int((data.t["fact_sensitivity"]["passes"] == True).sum())), "pasan la compuerta; asociación del modelo"),  # noqa: E712
        "[Análisis frescos (%)]": lambda: _card(_pct((arrived_lab["lab_state"] == "fresh").mean() if len(arrived_lab) else None), "de los análisis que llegaron"),
        "[Horas interpoladas]": lambda: _card(_int(quality["interpolated"].sum()), "análisis interpolados que llegaron"),
        "[Horas repetidas]": lambda: _card(_int(quality["held"].sum()), "análisis repetidos que llegaron"),
        "[Reglas bloqueantes fallidas]": lambda: _card(_int(len(blocking)), "en las corridas cargadas"),
        "[Última fecha de cálculo]": lambda: _card(_when(ok_runs["as_of"].max()) if len(ok_runs) else DASH, "corridas terminadas bien"),
    }


def _estimate_line(data: _Data, v: Visual) -> str:
    """Page 1: the estimate of the hour that closed with its 80 % range, the persistence and the analyses once they arrived (the ones with nothing new in grey)."""
    w, h = _size(v)
    est = data.t["fact_estimate"]
    window = est[(est["horizon_key"] == 0) & (est["status"] == "ok")].sort_values("hour_key").tail(WINDOW_HOURS)
    title = f"{v.title_es} (horizonte 0, últimas {len(window)} horas)"
    if window.empty:
        return svg.line_chart({}, w, h, title)
    stamps = pd.to_datetime(window["hour_key"].astype(str), format="%Y%m%d%H")
    x_of = {int(k): float((s - stamps.iloc[0]).total_seconds() / 3600) for k, s in zip(window["hour_key"], stamps, strict=True)}
    pairs = list(zip(window["hour_key"], window["estimate"], window["persistence"], window["low"], window["high"], strict=True))
    lab = data.t["fact_hour_lab"]
    lab = lab[lab["hour_key"].isin(list(x_of)) & lab["silica_pct"].notna()]
    markers = {"Análisis nuevo": [(x_of[int(k)], float(s)) for k, s, state in zip(lab["hour_key"], lab["silica_pct"], lab["lab_state"], strict=True) if state == "fresh"],
               "sin análisis nuevo": [(x_of[int(k)], float(s)) for k, s, state in zip(lab["hour_key"], lab["silica_pct"], lab["lab_state"], strict=True) if state != "fresh"]}
    ticks = [(x_of[int(window.iloc[i]["hour_key"])], _hour(window.iloc[i]["hour_key"])[5:]) for i in sorted({0, len(window) // 3, 2 * len(window) // 3, len(window) - 1})]
    return svg.line_chart({"Estimación": [(x_of[int(k)], e) for k, e, _p, _l, _h in pairs], "Persistencia": [(x_of[int(k)], p) for k, _e, p, _l, _h in pairs]}, w, h, title,
                          x_ticks=ticks, unit="%", band=("Rango del 80 %", [(x_of[int(k)], lo, hi) for k, _e, _p, lo, hi in pairs]),
                          markers={k: pts for k, pts in markers.items() if pts}, muted=("sin análisis nuevo",))


def _horizon_bars(data: _Data, v: Visual) -> str:
    w, h = _size(v)
    frame, label = data.scope("fact_method_metrics")
    groups = []
    for key in sorted(frame["horizon_key"].unique()) if len(frame) else []:
        part = frame[frame["horizon_key"] == key]
        groups.append((data.horizon(key), {data.method(m): float(x) for m, x in zip(part["method_key"], part["mae"], strict=True) if m in RULE_METHODS and pd.notna(x)}))
    return _caption(f"Muestra: {label}; el modelo y las reglas B0 a B2, los modelos de comparación van en la tabla") + svg.grouped_bar_chart(groups, w, h - 14, f"{v.title_es} ({label})")


def _scope_table(data: _Data) -> str:
    """MAE of the model, the persistence and the rolling mean in V1, V2 and the test, one row per horizon and method."""
    frame = data.sealed("fact_method_metrics")
    rows = []
    for key in sorted(frame["horizon_key"].unique()) if len(frame) else []:
        for method in ("model", "b1_persistence", "b2_rolling"):
            cells = [frame[(frame["horizon_key"] == key) & (frame["method_key"] == method) & (frame["scope"] == s)]["mae"] for s in ("valid_v1", "valid_v2", "test")]
            rows.append([data.horizon(key), data.method(method), *(_fmt(c.iloc[0]) if len(c) else DASH for c in cells)])
    return _table_html(["Horizonte", "Método", "V1", "V2", "Prueba"], rows[:TABLE_ROWS], {2, 3, 4})


def _interval_table(data: _Data) -> str:
    frame, label = data.scope("fact_method_metrics")
    rows = []
    for key in sorted(frame["horizon_key"].unique()) if len(frame) else []:
        for method in ("model", "b1_persistence", "b2_rolling"):
            part = frame[(frame["horizon_key"] == key) & (frame["method_key"] == method)]
            if len(part):
                r = part.iloc[0]
                rows.append([data.horizon(key), data.method(method), _fmt(r["mae"]), "sí" if bool(r["is_b_star"]) else "no", _fmt(r["ci_low_vs_b_star"]), _fmt(r["ci_high_vs_b_star"])])
    return _caption(f"Muestra: {label}") + _table_html(["Horizonte", "Método", "MAE", "B*", "IC inferior", "IC superior"], rows[:TABLE_ROWS], {2, 4, 5})


def _weekly(data: _Data, v: Visual) -> str:
    w, h = _size(v)
    weekly = data.sealed("fact_weekly_mae")
    weekly = weekly[weekly["horizon_key"] == (weekly["horizon_key"].min() if len(weekly) else 0)]
    series = {data.method(m): [(float(wk), float(x)) for wk, x in zip(part["test_week"], part["mae"], strict=True) if pd.notna(x)]
              for m in RULE_METHODS if len(part := weekly[weekly["method_key"] == m].sort_values("test_week"))}
    return _caption("Muestra: prueba, horizonte 0") + svg.line_chart(series, w, h - 14, f"{v.title_es} (horizonte 0)", x_ticks=[(float(k), f"S{int(k)}") for k in sorted({wk for s in series.values() for wk, _ in s})])


def _multiples(data: _Data) -> str:
    """Page 3: the hourly means of every sensor on the last day that has any, one small line each."""
    process, hours = data.t["fact_hour_process"], data.t["dim_hour"]
    if process.empty or hours.empty:
        return _note("Sin medias horarias.")
    day = hours[hours["hour_key"].isin(process["hour_key"])]["date"].max()
    keys = set(hours[hours["date"] == day]["hour_key"])
    part = process[process["hour_key"].isin(keys)]
    names = data.t["dim_sensor"].set_index("sensor_key")["name_es"]
    figures = []
    for sensor in sorted(part["sensor_key"].unique()):
        rows = part[part["sensor_key"] == sensor].sort_values("hour_key")
        points = [(float(i), float(m)) for i, m in enumerate(rows["mean"]) if pd.notna(m)]
        name = str(names.get(sensor, sensor))
        figures.append(f"<figure>{svg.sparkline(points, 130, 34, f'{name}, {day}')}<figcaption>{escape(name)}</figcaption></figure>")
    return f'<div class="sub">Medias horarias del {escape(str(day))}</div><div class="multiples">{"".join(figures)}</div>'


def _gate(data: _Data) -> str:
    frame = data.t["fact_sensitivity"].sort_values("importance_v1", ascending=False)
    names = data.t["dim_sensor"].set_index("sensor_key")["name_es"]
    rows = [[str(names.get(r.sensor_key, r.sensor_key)), _fmt(r.importance_v1), _fmt(r.importance_v2), "sí" if r.sign_stable is True else "no" if r.sign_stable is False else DASH,
             "sí" if r.passes is True else "no", str(r.label_es)] for r in frame.head(TABLE_ROWS - 1).itertuples()]
    note = f"Los primeros {len(rows)} de {len(frame)} sensores, por importancia en V1." if len(frame) > len(rows) else ""
    return _caption(note or "Todos los sensores.") + _table_html(["Sensor", "Imp. V1", "Imp. V2", "Signo estable", "Pasa", "Qué dice"], rows, {1, 2})


def _curves(data: _Data, v: Visual) -> str:
    w, h = _size(v)
    curves = data.sealed("fact_pd_curve")
    if curves.empty:
        return _note("Ningún sensor pasó la compuerta de estabilidad: sin curvas que dibujar.") + svg.line_chart({}, w, h - 24, v.title_es)
    names = data.t["dim_sensor"].set_index("sensor_key")["name_es"]
    series = {str(names.get(k, k)): [(float(p), float(y)) for p, y in zip(part["point"], part["mean_estimate"], strict=True) if pd.notna(y)]
              for k, part in ((k, curves[curves["sensor_key"] == k].sort_values("point")) for k in sorted(curves["sensor_key"].unique())[:4])}
    return _caption("Los sensores que pasaron la compuerta; el eje es el punto de la grilla.") + svg.line_chart(series, w, h - 14, v.title_es, unit="%")


def _criteria(data: _Data) -> str:
    frame = data.sealed("fact_evaluation_summary").sort_values("criterion_id")
    rows = [[r.criterion_id, r.name_es, _fmt(r.value), r.threshold_es, r.verdict_es] for r in frame.itertuples()]
    return _table_html(["Criterio", "Nombre", "Valor", "Umbral", "Veredicto"], rows, {2})


def _half_widths(data: _Data) -> str:
    frame = data.t["dim_model"].sort_values("horizon_key") if len(data.t["dim_model"]) else data.t["dim_model"]
    return _table_html(["Modelo", "Horizonte", "Semiancho", "B*", "Sello"], [[r.model_key, data.horizon(r.horizon_key), _fmt(r.half_width), r.b_star, r.seal_state] for r in frame.itertuples()], {2})


def _selection(data: _Data) -> str:
    frame = data.sealed("fact_selection")
    frame = frame.assign(_first=~frame["chosen"].fillna(False).astype(bool)).sort_values(["_first", "horizon_key", "mae_v1"]) if len(frame) else frame
    rows = [[data.horizon(r.horizon_key), r.family, r.feature_set, r.target, _int(r.min_samples_leaf), _fmt(r.mae_v1), "sí" if r.chosen is True else "no"] for r in frame.head(TABLE_ROWS).itertuples()]
    return _table_html(["Horizonte", "Familia", "Rasgos", "Objetivo", "Hoja", "MAE V1", "Elegido"], rows, {4, 5})


def _variants(data: _Data) -> str:
    frame = data.sealed("fact_variants")
    rows = [[r.variant_es, data.horizon(r.horizon_key), data.method(r.method_key), _fmt(r.mae), _int(r.hours), _fmt(r.ci_low), _fmt(r.ci_high)] for r in frame.head(TABLE_ROWS).itertuples()]
    return _table_html(["Variante", "Horizonte", "Método", "MAE", "Horas", "IC inferior", "IC superior"], rows, {3, 4, 5, 6})


def _leakage(data: _Data) -> str:
    frame = data.sealed("fact_leakage")
    return _table_html(["Comprobación", "MAE", "R²", "Qué enseña"], [[r.check_es, _fmt(r.mae), _fmt(r.r2), r.note_es] for r in frame.itertuples()], {1, 2})


def _quality_bars(data: _Data, v: Visual) -> str:
    w, h = _size(v)
    frame = data.t["fact_data_quality"].sort_values("date_key").tail(DAYS_SHOWN)
    groups = [(str(r.date_key)[4:6] + "-" + str(r.date_key)[6:8], {"Nuevos": float(r.fresh), "Repetidos": float(r.held), "Interpolados": float(r.interpolated)}) for r in frame.itertuples()]
    return _caption(f"Los últimos {len(groups)} días con horas.") + svg.grouped_bar_chart(groups, w, h - 14, v.title_es)


def _gaps(data: _Data) -> str:
    frame = data.t["fact_data_quality"].sort_values("date_key")
    frame = frame[(frame["missing_hours"] > 0) | (frame["partial_hours"] > 0)]
    rows = [[f"{str(r.date_key)[:4]}-{str(r.date_key)[4:6]}-{str(r.date_key)[6:8]}", _int(r.missing_hours), _int(r.partial_hours), _int(r.stuck_sensor_hours)] for r in frame.head(TABLE_ROWS).itertuples()]
    return _table_html(["Día", "Sin datos", "Parciales", "Sensor fijo"], rows, {1, 2, 3})


def _rules(data: _Data) -> str:
    frame = data.t["fact_validation"]
    latest = frame[frame["run_key"] == frame["run_key"].max()].sort_values("rule_id") if len(frame) else frame
    return _table_html(["Regla", "Nombre", "Severidad", "Filas", "Horas", "Estado"], [[r.rule_id, r.name_es, r.severity, _int(r.rows_affected), _int(r.hours_affected), r.status] for r in latest.itertuples()], {3, 4})


def _runs(data: _Data) -> str:
    frame = data.t["dim_pipeline_run"].sort_values("as_of")
    return _table_html(["Corrida", "Entrega", "Cálculo", "Estado", "Emitidas", "Mensaje"], [[r.run_key, r.delivery_id, _when(r.as_of), r.status, _int(r.estimates_issued), r.message or ""] for r in frame.itertuples()], {4})


def _preview(data: _Data, v: Visual) -> str:
    """The body of a visual: its drawing or figure from the exported tables."""
    if v.kind == "slicer":
        return _slicer(data, v.fields[0])
    if v.kind == "card":
        maker = _cards(data).get(v.fields[0])
        return maker() if maker else _note("Se calcula en Power BI.")
    makers = {
        "Sílice estimada con su rango, análisis y persistencia": lambda: _estimate_line(data, v),
        "MAE por horizonte": lambda: _horizon_bars(data, v),
        "MAE en V1, V2 y la prueba": lambda: _scope_table(data),
        "En la prueba: el intervalo de la diferencia con B*": lambda: _interval_table(data),
        "MAE por semana de la prueba": lambda: _weekly(data, v),
        "Medias horarias de cada sensor en el día elegido": lambda: _multiples(data),
        "Criterios C01-C10": lambda: _criteria(data),
        "Semiancho del rango del 80 % por horizonte": lambda: _half_widths(data),
        "Candidatos de cada horizonte, con su error en V1": lambda: _selection(data),
        "Latencias, reajuste y todas las horas (informativo)": lambda: _variants(data),
        "Demostración de la fuga: bloques, partición aleatoria y hierro del concentrado": lambda: _leakage(data),
        "Análisis llegados por día: nuevos, repetidos e interpolados": lambda: _quality_bars(data, v),
        "Horas sin datos por día (el hueco de marzo)": lambda: _gaps(data),
        "Reglas de validación": lambda: _rules(data),
        "Corridas": lambda: _runs(data),
    }
    if v.title_es.startswith("Compuerta de estabilidad"):
        return _gate(data)
    if v.title_es.startswith("Asociación del modelo, no una receta"):
        return _curves(data, v)
    maker = makers.get(v.title_es)
    return maker() if maker else _note("Se calcula en Power BI.")


# --- sections -----------------------------------------------------------------------------------------------------------------


def _steps(model: SemanticModel) -> str:
    steps = [
        "Instale Power BI Desktop (gratuito, solo para Windows) y abra un informe en blanco.",
        "Cree un parámetro de texto llamado <code>CarpetaSalidas</code> con la ruta de <code>outputs\\powerbi</code>.",
        f"Cree una consulta por tabla ({len(model.tables)}) con el código de la sección «Power Query»; deje el nombre de la consulta igual al de la tabla.",
        f"En la vista de modelo, cree las {len(model.relationships)} relaciones de la tabla «Relaciones»: uno a varios (1:*), filtro único de la dimensión al hecho, todas activas. "
        "Los hechos de la evaluación (<code>fact_evaluation_summary</code>, <code>fact_variants</code> y <code>fact_leakage</code>) no tienen relación de clave: alimentan sus propios visuales.",
        "Marque <code>dim_date</code> como tabla de fechas con la columna <code>date</code>; ordene <code>month_name_es</code> por <code>month</code> y <code>horizon_es</code> por <code>horizon_key</code>.",
        "Cree una tabla vacía llamada <code>_Medidas</code> y agregue en ella las medidas de la sección «Medidas DAX», con su formato.",
        f"Cree las {len(model.pages)} páginas a 1280 × 720 px y ubique cada visual según la grilla de {PAGE_COLUMNS} columnas por {PAGE_ROWS} filas.",
        "Guarde el informe como <code>.pbix</code>. Cuando corra el flujo, «Actualizar» vuelve a leer los mismos archivos.",
    ]
    return "<ol>" + "".join(f"<li>{s}</li>" for s in steps) + "</ol>"


def _diagram(model: SemanticModel) -> str:
    """Related dimensions above, the facts with relationships in the middle, the run table below, and the tables without relationships last."""
    width, height = 1500, 700
    related = {r.dim_table for r in model.relationships} | {r.fact_table for r in model.relationships}
    top = [t.name for t in model.tables if t.kind == "dimension" and t.name in related and t.name != "dim_pipeline_run"]
    bottom = [t.name for t in model.tables if t.name == "dim_pipeline_run" and t.name in related]
    facts = [t.name for t in model.tables if t.kind == "fact" and t.name in related]
    alone = [t.name for t in model.tables if t.name not in related]
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for names, y, w, h in ((top, 24, 150, 46), (facts, 250, 150, 56), (bottom, 420, 170, 46), (alone, 590, 150, 46)):
        w = min(w, (width - 16 * (len(names) + 1)) / max(len(names), 1))
        gap = (width - w * len(names)) / (len(names) + 1) if names else 0
        for i, name in enumerate(names):
            boxes[name] = (gap + i * (w + gap), y, w, h)
    dims = sum(1 for t in model.tables if t.kind == "dimension")
    nfacts = sum(1 for t in model.tables if t.kind == "fact")
    out = [f'<svg class="model-svg" viewBox="0 0 {width} {height}" role="img" aria-label="Diagrama del modelo en estrella: {dims} dimensiones y {nfacts} hechos">',
           '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--muted)"/></marker></defs>']
    for r in model.relationships:
        dx, dy, dw, dh = boxes[r.dim_table]
        fx, fy, fw, fh = boxes[r.fact_table]
        up = r.dim_table in top
        x1, y1 = dx + dw / 2, (dy + dh if up else dy)
        x2, y2 = fx + fw / 2, (fy if up else fy + fh)
        out.append(f'<line class="rel" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" marker-end="url(#arrow)">'
                   f'<title>{escape(r.rel_id)}: {escape(r.dim_table)}[{escape(r.dim_column)}] 1 → * {escape(r.fact_table)}[{escape(r.fact_column)}]</title></line>')
        sign = 1 if up else -1
        out.append(f'<text class="card" x="{x1 + 3:.1f}" y="{y1 + sign * 13:.1f}">1</text><text class="card" x="{x2 + 3:.1f}" y="{y2 - sign * 6:.1f}">*</text>')
    for name, (x, y, w, h) in boxes.items():
        table = model.table(name)
        size = ' font-size="9"' if len(name) > 15 else ""
        key = ", ".join(table.key) if table.kind == "dimension" else f"{len(table.columns)} columnas"
        out.append(f'<rect class="box {"dim" if table.kind == "dimension" else "fact"}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h}" rx="6"/>'
                   f'<text x="{x + w / 2:.1f}" y="{y + h / 2 - 2:.1f}" text-anchor="middle"{size}>{escape(name)}</text>'
                   f'<text class="small" x="{x + w / 2:.1f}" y="{y + h / 2 + 12:.1f}" text-anchor="middle">{escape(key)}</text>')
    out.append('<text class="small" x="8" y="570">Sin relaciones: alimentan sus propios visuales.</text>')
    out.append(f'<text class="small" x="8" y="{height - 6}">Cada línea va de la dimensión («1») al hecho («*»); la flecha es la dirección del filtro, única y activa.</text></svg>')
    return "".join(out)


def _relationships(model: SemanticModel) -> str:
    rows = [[r.rel_id, f"{r.dim_table}[{r.dim_column}]", "1", f"{r.fact_table}[{r.fact_column}]", "*", "Uno a varios (1:*)",
             "Única: de la dimensión al hecho" if r.cross_filter == "single" else r.cross_filter, "Sí" if r.active else "No"] for r in model.relationships]
    return _table_html(["ID", "Dimensión", "", "Hecho", "", "Cardinalidad", "Dirección del filtro", "Activa"], rows)


def _queries(model: SemanticModel) -> str:
    parts = []
    for t in model.tables:
        steps = f'    Origen = Parquet.Document(File.Contents(CarpetaSalidas & "\\{t.name}.parquet"))'
        last = "Origen"
        dates = [c.name for c in t.columns if c.dtype == "date"]
        if dates:
            casts = ", ".join(f'{{"{d}", type date}}' for d in dates)
            steps += f",\n    Tipos = Table.TransformColumnTypes(Origen, {{{casts}}})"
            last = "Tipos"
        parts.append(f"<h3>{escape(t.name)}</h3><p>{escape(t.description_es)}</p><pre><code>{escape(f'let{chr(10)}{steps}{chr(10)}in{chr(10)}    {last}')}</code></pre>")
    return "".join(parts)


def _measures(model: SemanticModel) -> str:
    parts = []
    for m in model.measures:
        uses = sorted(dax_measure_refs(m.dax))
        used = f" Usa: {', '.join('[' + u + ']' for u in uses)}." if uses else ""
        parts.append(f"<h3>{escape(m.name_es)}</h3><p>{escape(m.description_es)}{escape(used)} Formato: <code>{escape(m.format_string)}</code>.</p>"
                     f"<pre><code>{escape(m.name_es)} =\n{escape(m.dax)}</code></pre>")
    return "".join(parts)


def _page_section(data: _Data, page: Page, number: int) -> str:
    visuals = []
    for v in page.visuals:
        style = f"grid-column:{v.x + 1} / span {v.w};grid-row:{v.y + 1} / span {v.h}"
        visuals.append(f'<section class="visual" style="{style}" aria-label="{escape(v.title_es)}"><header><b>{escape(v.title_es)}</b>'
                       f'<span>{escape(KIND_ES.get(v.kind, v.kind))}</span></header><div class="body">{_preview(data, v)}</div></section>')
    rows = [[KIND_ES.get(v.kind, v.kind), v.title_es, ", ".join(v.fields), f"x {v.x}, y {v.y}, ancho {v.w}, alto {v.h}"] for v in page.visuals]
    return (f'<h3 id="pagina-{number}">Página {number}: {escape(page.name_es)}</h3>'
            f'<div class="canvas-wrap"><div class="canvas" role="group" aria-label="Página {escape(page.name_es)}">{"".join(visuals)}</div></div>'
            f'<details><summary>Posición, tipo y campos de cada visual</summary><div class="scroll placement">'
            f'{_table_html(["Visual", "Título", "Campos", "Posición (celdas)"], rows)}</div></details>')


def _page_html(model: SemanticModel, data: _Data, run: RunMeta) -> str:
    nav = "".join(f'<li><a href="#{key}">{escape(title)}</a></li>' for key, title in SECTIONS)
    pages = "".join(_page_section(data, p, i) for i, p in enumerate(model.pages, start=1))
    dims = sum(1 for t in model.tables if t.kind == "dimension")
    facts = sum(1 for t in model.tables if t.kind == "fact")
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(TITLE)}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>{escape(TITLE)}</h1>
<p class="lead">Guía para armar el informe en Power BI Desktop a partir de los archivos Parquet de <code>outputs/powerbi</code>: modelo, relaciones, consultas, medidas y las cinco páginas con una vista previa de cada visual dibujada con las cifras exportadas.</p>
<div class="meta"><span>Fecha de cálculo <b>{escape(run.as_of.isoformat(sep=" "))}</b></span><span>Corrida <code>{escape(run.run_key)}</code></span><span>SHA-256 de la fuente <code>{escape(data.source_sha256[:12])}</code></span></div>
<nav aria-label="Secciones"><ul>{nav}</ul></nav>
<h2 id="armado">{escape(SECTIONS[0][1])}</h2>
{_steps(model)}
<div class="warn"><b>Qué se probó y qué no.</b> Las pruebas del proyecto comprueban que los archivos cumplen el modelo (claves únicas, claves foráneas en su dimensión, relaciones de uno a varios con filtro único) y que cada tabla, columna, medida y función que nombra el DAX existe, que cada segmentador llega, por las relaciones, a los visuales de su página (o el título dice que no los filtra) y que todo texto de los datos está escapado. <b>Ninguna medida se ejecutó</b>: no hay Power BI en el proyecto, así que ninguna expresión DAX se evaluó. Las vistas previas se calculan con pandas sobre los mismos archivos, sin segmentadores; al armar el informe, compare cada tarjeta con su vista previa.</div>
<div class="warn"><b>Una sensibilidad es una asociación del modelo, no una receta.</b> Los sensores que pasan la compuerta de estabilidad se muestran con su signo; los demás dicen «sin asociación estable». Ninguna página dice qué hacer con un sensor.</div>
<h2 id="modelo">{escape(SECTIONS[1][1])}</h2>
<p>{dims} dimensiones y {facts} hechos. <code>dim_hour</code> filtra los hechos por hora; <code>dim_date</code>, solo la calidad de los datos por día. Los hechos de la evaluación sin clave de hora ni de sensor no tienen relación de clave.</p>
{_diagram(model)}
<h2 id="relaciones">{escape(SECTIONS[2][1])}</h2>
<div class="scroll">{_relationships(model)}</div>
<h2 id="consultas">{escape(SECTIONS[3][1])}</h2>
{_queries(model)}
<h2 id="medidas">{escape(SECTIONS[4][1])}</h2>
<p>Todas van en la tabla <code>_Medidas</code>. Los nombres de las medidas y los textos están en español; las tablas y las columnas, en inglés. Las cuatro medidas de las evaluaciones leen solo las filas selladas de la prueba: si no, una fila posterior al sello dejaría la cifra vacía.</p>
<div class="warn"><b>Las dos medidas «de la última hora».</b> «Última estimación» y «Último análisis llegado» toman el máximo de <code>hour_key</code> con <code>CALCULATE</code> y leen el valor en esa hora; solo reemplazan los filtros de las columnas de su hecho (<code>hour_key</code>, <code>horizon_key</code>), así que el segmentador de fecha, que filtra por la relación desde <code>dim_hour</code>, sigue valiendo: el máximo se toma entre las fechas elegidas. Se leyó el DAX; no se ejecutó. «Última estimación» es el horizonte 0: queda vacía si el segmentador de horizonte lo excluye.</div>
{_measures(model)}
<h2 id="paginas">{escape(SECTIONS[5][1])}</h2>
<p>Cada página es un lienzo de 1280 × 720 px (16:9) sobre una grilla de {PAGE_COLUMNS} columnas por {PAGE_ROWS} filas; la posición de cada visual está en celdas. Las vistas previas de la evaluación muestran la prueba sellada si existe y, si no, la validación, y lo dicen. Un visual que un segmentador no filtra lo dice en su título.</p>
{pages}
<h2 id="fuente">{escape(SECTIONS[6][1])}</h2>
<p>{escape(ATTRIBUTION)}</p>
<p>Datos de la corrida <code>{escape(run.run_key)}</code>, con fecha de cálculo {escape(run.as_of.isoformat(sep=" "))}. Este documento se genera desde <code>dashboard/semantic_model.py</code>; no se edita a mano.</p>
</main>
</body>
</html>
"""


def render_design(model: SemanticModel, parquet_dir: Path, html_path: Path, run_meta: RunMeta) -> Path:
    """Write the HTML design of the report to `html_path` (atomically, through ``files.write_atomic``) from the Parquet files of `parquet_dir` and return the path. The model is checked
    first: an incoherent one writes nothing."""
    problems = validate_model(model)
    if problems:
        raise ValueError(f"el modelo semántico es incoherente: {problems[0]}")
    html = _page_html(model, _Data(Path(parquet_dir), model), run_meta)
    path = write_atomic(Path(html_path), html)
    logger.info("dashboard design written to %s (%d bytes)", path.name, len(html.encode("utf-8")))
    return path
