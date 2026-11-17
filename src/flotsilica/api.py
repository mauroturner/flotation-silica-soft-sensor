"""The estimation API (RF24, AC28; D27, D45; plan, section 18): ``GET /health`` and ``POST /estimate``, local, read-only and with the same function as the flow.

``create_app(cfg)`` serves the sealed model of the project: it reads the seal, refuses a configuration other than the sealed one (the estimates would not be the flow's), opens the
warehouse only to read the registry and loads the artifact through ``registry.load_registered_bundle`` (its SHA-256 is checked before a byte is deserialized, M03). The app takes
no path, writes nothing and has no documentation pages.

``POST /estimate`` turns the body into ``features.IssueInputs`` with the code the flow uses (``hours.aggregate_rows`` for the readings, the arrival rule ``features.lab_known_at``
for the analyses, ``features.missing_inputs`` for the history) and calls ``scoring.score_issue``: for the readings and the analyses the warehouse holds at an instant, the answer is
exactly the estimates the flow stored (AC28). A body the service cannot trust is a 422 with a code and the field, before anything is estimated; no message carries a path or a trace.

The request models are built from the configuration (the readings of an hour and the analyses it takes are limits of the configuration), so this module has no ``from __future__
import annotations``: FastAPI reads the annotations of the handlers when it defines them, and the classes are local to ``create_app``.
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, NaiveDatetime, create_model

from flotsilica import texts
from flotsilica.config import PipelineConfig
from flotsilica.features import HISTORY_COLUMNS, SENSOR_COLUMNS, IssueInputs, lab_known_at, missing_inputs
from flotsilica.hours import aggregate_rows
from flotsilica.registry import config_fingerprint, load_registered_bundle, read_seal, seal_state, sealed_view
from flotsilica.schema import FEED_FEATURE_COLUMNS, SENSORS
from flotsilica.scoring import EstimateError, score_issue

logger = logging.getLogger(__name__)

HOUR = timedelta(hours=1)
Finite = Annotated[float, Field(strict=True, allow_inf_nan=False)]      # a JSON number: not a text, not a boolean, not NaN or an infinity
Percent = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0, le=100)]
Age = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0)]


def _text_only(value: object) -> object:
    """An instant comes as an ISO text: a number would be read as a Unix time, which is not the plant time the flow keeps."""
    if not isinstance(value, str):
        raise ValueError("an instant is an ISO text")
    return value


Instant = Annotated[NaiveDatetime, BeforeValidator(_text_only)]                # plant time as the flow keeps it: an ISO text without a zone


class ApiStartError(RuntimeError):
    """The API cannot serve: there is no seal or the configuration is not the sealed one, or the warehouse cannot be read (``serve`` exits with 2)."""


class _Refusal(Exception):
    """A request that is well formed and still cannot be answered: a 422 with its code and the field."""

    def __init__(self, code: str, message: str, field: str | None = None) -> None:
        super().__init__(code)
        self.code, self.message, self.field = code, message, field


class HorizonEstimate(BaseModel):
    horizon: int
    target_hour: datetime
    status: str
    reason: str | None
    estimate: float | None
    low: float | None
    high: float | None
    b_star: float | None
    b_star_method: str | None
    block: str
    is_censored: bool


class InputsUsed(BaseModel):
    sensor_rows: int
    fresh_analyses: int
    newest_sample_hour: datetime
    feed: bool


class EstimateResponse(BaseModel):
    model_version: str
    config_sha256: str
    issue_at: datetime
    estimates: list[HorizonEstimate]
    persistence: float
    inputs: InputsUsed


class HalfWidth(BaseModel):
    horizon: int
    half_width: float


class HealthResponse(BaseModel):
    status: Literal["ok"]
    model_version: str
    config_sha256: str
    seal: Literal["launch", "launch_and_test"]
    half_widths: list[HalfWidth]


def _request_model(cfg: PipelineConfig) -> type[BaseModel]:
    """``EstimateRequest`` with the limits of `cfg`: at most ``rows_per_hour`` readings, at most ``max_lab_history`` analyses."""
    strict = ConfigDict(extra="forbid")
    reading_model = create_model("Reading", __config__=strict, **{name: (Finite, ...) for name in SENSORS})
    feed_model = create_model("FeedLab", __config__=strict, feed_silica_pct=(Percent, ...), feed_iron_pct=(Percent, ...), feed_silica_age_h=(Age, ...), feed_iron_age_h=(Age, ...))
    assert tuple(feed_model.model_fields) == FEED_FEATURE_COLUMNS

    class LabAnalysis(BaseModel):
        model_config = strict
        sample_hour: Instant
        silica_pct: Percent
        state: Literal["fresh"] = "fresh"

    class EstimateRequest(BaseModel):
        model_config = strict
        issue_at: Instant
        readings: list[reading_model] = Field(min_length=1, max_length=cfg.hours.rows_per_hour)
        lab_history: list[LabAnalysis] = Field(min_length=1, max_length=cfg.api.max_lab_history)
        feed: feed_model | None = None

    return EstimateRequest


def _on_the_hour(instant: datetime, field: str) -> None:
    if (instant.minute, instant.second, instant.microsecond) != (0, 0, 0):
        raise _Refusal("not_on_the_hour", texts.api_refusal("not_on_the_hour", field=field), field)


def _inputs(body, cfg: PipelineConfig) -> tuple[IssueInputs, pd.DataFrame]:
    """The ``IssueInputs`` of a request and the analyses that had arrived at its instant, or the ``_Refusal`` that says why the body cannot be answered."""
    issue_at = body.issue_at
    _on_the_hour(issue_at, "issue_at")
    hours = pd.DatetimeIndex([a.sample_hour for a in body.lab_history]).as_unit("ns")
    for k, instant in enumerate(hours):
        _on_the_hour(instant.to_pydatetime(), f"lab_history.{k}.sample_hour")
    repeated = np.flatnonzero(hours.duplicated())
    if len(repeated):
        field = f"lab_history.{int(repeated[0])}.sample_hour"
        raise _Refusal("duplicate_sample_hour", texts.api_refusal("duplicate_sample_hour", field=field), field)
    history = pd.DataFrame({"sample_hour": hours, "silica_pct": np.array([a.silica_pct for a in body.lab_history], dtype="float64"),
                            "available_at": hours + pd.Timedelta(hours=cfg.lab.latency_hours)}, columns=list(HISTORY_COLUMNS))
    arrived = lab_known_at(history, issue_at)        # the rule of the flow: ``available_at <= issue_at``, the instant of arrival included
    if len(arrived) != len(history):
        late = int(np.flatnonzero(~history["sample_hour"].isin(arrived["sample_hour"]).to_numpy())[0])
        field = f"lab_history.{late}.sample_hour"
        raise _Refusal("analysis_after_issue", texts.api_refusal("analysis_after_issue", field=field, issue_at=issue_at.isoformat()), field)
    readings = pd.DataFrame([row.model_dump() for row in body.readings], columns=list(SENSORS))
    readings.insert(0, "hour", pd.Timestamp(issue_at) - HOUR)
    aggregated = aggregate_rows(readings).iloc[0]
    sensors = pd.Series(aggregated[list(SENSOR_COLUMNS)].to_numpy(dtype="float64"), index=list(SENSOR_COLUMNS))
    feed = None if body.feed is None else pd.Series([getattr(body.feed, name) for name in FEED_FEATURE_COLUMNS], index=list(FEED_FEATURE_COLUMNS), dtype="float64")
    inputs = IssueInputs(issue_at, sensors, history, feed)
    if missing_inputs(inputs, "fL", cfg) == "short_lab_history":
        raise _Refusal("short_lab_history", texts.api_refusal("short_lab_history", issue_at=issue_at.isoformat(), found=len(arrived), minimum=cfg.features.min_fresh_history), "lab_history")
    return inputs, arrived


def create_app(cfg: PipelineConfig) -> FastAPI:
    """The app that serves the sealed model of `cfg`, loaded and checked now. Raises ``ApiStartError`` (no seal, another configuration, an unreadable warehouse) or the registry's
    errors (``ArtifactMismatchError``, ``ArtifactMissingError``, ``SealError``) when the model cannot be served; nothing is written."""
    seal = read_seal(Path(cfg.paths.seal))
    if seal is None:
        raise ApiStartError(texts.api_without_seal())
    view = sealed_view(cfg, seal["launch"]["source_sha256"])
    config_sha256 = config_fingerprint(view)
    if seal_state(Path(cfg.paths.seal), config_sha256) != "match":
        raise ApiStartError(texts.api_other_configuration())
    warehouse = Path(cfg.paths.warehouse)
    try:
        conn = sqlite3.connect(f"{warehouse.resolve().as_uri()}?mode=ro", uri=True)      # read only: the app opens the warehouse to read the registry and nothing else
        try:
            bundle = load_registered_bundle(conn, Path(cfg.paths.models_dir), view.model.model_version)
        finally:
            conn.close()
    except sqlite3.OperationalError as error:
        raise ApiStartError(texts.api_warehouse_unreadable(warehouse.name)) from error
    health = HealthResponse(status="ok", model_version=bundle.version, config_sha256=config_sha256, seal="launch_and_test" if seal.get("test") is not None else "launch",
                            half_widths=[HalfWidth(horizon=hm.horizon, half_width=hm.half_width) for hm in bundle.horizons])
    request_model = _request_model(cfg)

    app = FastAPI(title="flotsilica", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, error: RequestValidationError) -> JSONResponse:
        # the type and the place of every failure, never the value that came in (a NaN cannot even be written back as JSON) or what pydantic says about it
        fields = [{"field": "" if item["type"] == "json_invalid" else ".".join(str(part) for part in item["loc"][1:]), "type": item["type"]} for item in error.errors()]
        return JSONResponse(status_code=422, content={"error": "invalid_request", "message": texts.api_refusal("invalid_request"), "fields": fields})

    @app.exception_handler(_Refusal)
    async def refusal(_request, error: _Refusal) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": error.code, "message": error.message, "field": error.field})

    @app.get("/health")
    def get_health() -> HealthResponse:
        return health

    @app.post("/estimate")
    def post_estimate(body: request_model) -> EstimateResponse:
        inputs, arrived = _inputs(body, cfg)
        try:
            estimates = score_issue(bundle, inputs, view)
        except EstimateError as error:
            logger.warning("estimate refused for %s: %s", inputs.issue_at, error)
            raise _Refusal("estimate_refused", texts.api_refusal("estimate_refused")) from error
        return EstimateResponse(
            model_version=bundle.version, config_sha256=config_sha256, issue_at=inputs.issue_at, persistence=float(arrived["silica_pct"].iloc[-1]),
            inputs=InputsUsed(sensor_rows=len(body.readings), fresh_analyses=len(arrived), newest_sample_hour=pd.Timestamp(arrived["sample_hour"].iloc[-1]).to_pydatetime(),
                              feed=body.feed is not None),
            estimates=[HorizonEstimate(horizon=e.horizon, target_hour=e.target_hour, status=e.status, reason=e.reason, estimate=e.estimate, low=e.low, high=e.high, b_star=e.b_star,
                                       b_star_method=e.b_star_method, block=e.block, is_censored=e.is_censored) for e in estimates])

    return app
