"""The estimation API (U19, AC28; RF24; D27, D45; plan, section 18), in this process with FastAPI's test client over the small history of ``tests/fixtures/history.py`` (its
launch, its three deliveries and its seal, which ``create_app`` reads and never writes).

What the tests pin: ``POST /estimate`` gives for every instant of the test block exactly the estimates the pipeline stored (the same ``score_issue`` over inputs the API builds
from the readings and the analyses of the body), an input the service cannot trust is a 422 with its code before anything is estimated, and the API writes no file.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import testclient

from flotsilica import api
from flotsilica.api import ApiStartError, create_app
from flotsilica.features import inputs_at
from flotsilica.registry import ArtifactMismatchError, load_registered_bundle, read_seal
from flotsilica.schema import SENSORS
from flotsilica.scoring import EstimateError
from tests.e2e.cli_helpers import fingerprint
from tests.fixtures.history import HOUR, copy_history, stamp

PROJECT = Path(__file__).resolve().parents[2]
LEAKS = ("Traceback", "site-packages", str(PROJECT), "File \"", "pydantic")      # nothing of the machine or of the libraries in the body of a refusal


def config_of(history):
    view = history.view
    return dataclasses.replace(view, paths=dataclasses.replace(view.paths, warehouse=history.paths.db, models_dir=history.paths.models, seal=history.paths.seal))


@pytest.fixture(scope="module")
def served(small_history, small_canonical):
    cfg = config_of(small_history)
    app = create_app(cfg)
    return SimpleNamespace(cfg=cfg, app=app, client=testclient.TestClient(app, raise_server_exceptions=False), history=small_history, canonical=small_canonical)


@pytest.fixture
def scored(monkeypatch):
    """The calls of ``score_issue`` the API makes (the real function still runs)."""
    calls = []
    real = api.score_issue

    def spy(*args, **kwargs):
        calls.append(args[1].issue_at)
        return real(*args, **kwargs)

    monkeypatch.setattr(api, "score_issue", spy)
    return calls


def instants_of_the_test(served) -> list[datetime]:
    """The issue instants of the estimates of the hours of the test block that the history stored."""
    split = served.cfg.split
    conn = sqlite3.connect(f"{served.history.paths.db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        found = conn.execute("SELECT DISTINCT issue_at FROM estimates WHERE target_hour BETWEEN ? AND ? ORDER BY issue_at", (stamp(split.test_first), stamp(split.test_last))).fetchall()
    finally:
        conn.close()
    return [pd.Timestamp(row[0]).to_pydatetime() for row in found]


def stored_at(served, instant: datetime) -> dict[int, tuple]:
    conn = sqlite3.connect(f"{served.history.paths.db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT horizon, status, reason, estimate, low, high, persistence, b_star, b_star_method, block, is_censored, model_version FROM estimates "
                            "WHERE issue_at = ? ORDER BY horizon", (stamp(instant),)).fetchall()
    finally:
        conn.close()
    return {row[0]: row[1:] for row in rows}


def body_at(served, instant: datetime) -> dict:
    """The request of an instant, built from what the warehouse holds at it (``inputs_at``) and from the rows of the hour that closed (the canonical table of the fixture)."""
    conn = sqlite3.connect(f"{served.history.paths.db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        inputs = inputs_at(conn, instant, served.cfg)
    finally:
        conn.close()
    rows = served.canonical.rows
    hour = rows[rows["hour"] == pd.Timestamp(instant) - HOUR].sort_values("row_in_hour")
    return {
        "issue_at": pd.Timestamp(instant).isoformat(),
        "readings": hour[list(SENSORS)].to_dict("records"),
        "lab_history": [{"sample_hour": pd.Timestamp(row.sample_hour).isoformat(), "silica_pct": float(row.silica_pct)} for row in inputs.lab_history.itertuples()],
        "feed": None if inputs.feed is None else {name: float(value) for name, value in inputs.feed.items()},
    }


@pytest.fixture(scope="module")
def valid(served):
    """A request of the middle of the test block that the API answers with numbers."""
    instants = instants_of_the_test(served)
    return body_at(served, instants[len(instants) // 2])


def post(served, body, **kwargs):
    return served.client.post("/estimate", json=body, **kwargs)


def assert_refused(response, error: str, *, field: str | None = None, kind: str | None = None) -> dict:
    """A 422 whose body names its code, says where and carries nothing of the machine or of the libraries."""
    assert response.status_code == 422, (response.status_code, response.text)
    document = response.json()
    assert document["error"] == error and isinstance(document["message"], str) and document["message"]
    if field is not None or kind is not None:
        assert {"field": field, "type": kind} in [{"field": item["field"], "type": item["type"]} for item in document["fields"]], document
    assert not [leak for leak in LEAKS if leak in response.text], response.text
    return document


# --- AC28: the same estimates as the pipeline -------------------------------------------------------------------------------------------------------------------


@pytest.mark.slow
def test_estimate_matches_the_pipeline_for_every_test_hour(served):
    split = served.cfg.split
    test_hours = int((split.test_last - split.test_first) / HOUR) + 1
    instants = instants_of_the_test(served)
    seal = read_seal(served.history.paths.seal)["launch"]
    compared, numbers = 0, 0
    for instant in instants:
        response = post(served, body_at(served, instant))
        assert response.status_code == 200, response.text
        document = response.json()
        assert (document["model_version"], document["config_sha256"], document["issue_at"]) == (seal["model_version"], seal["config_sha256"], pd.Timestamp(instant).isoformat())
        stored = stored_at(served, instant)
        assert [e["horizon"] for e in document["estimates"]] == sorted(stored)
        for e in document["estimates"]:
            status, reason, estimate, low, high, persistence, b_star, b_star_method, block, censored, version = stored[e["horizon"]]
            assert (e["status"], e["reason"], e["estimate"], e["low"], e["high"], e["b_star"], e["b_star_method"], e["block"], e["is_censored"]) == (
                status, reason, estimate, low, high, b_star, b_star_method, block, bool(censored)), (instant, e)      # exact float equality, as AC28 says
            assert document["model_version"] == version
            assert document["persistence"] == persistence or status != "ok"
            compared += pd.Timestamp(split.test_first) <= pd.Timestamp(e["target_hour"]) <= pd.Timestamp(split.test_last)
            numbers += status == "ok"
    assert compared == 3 * test_hours and numbers > 0, "all three horizons of every hour of the test were compared, and some of them are numbers"
    # the readings are what the estimate comes from: another amine flow gives another estimate (a service that ignored them would still pass the loop above)
    body = body_at(served, instants[len(instants) // 2])
    changed = {**body, "readings": [{**row, "amina_flow": row["amina_flow"] * 2 + 50} for row in body["readings"]]}
    assert post(served, changed).json()["estimates"] != post(served, body).json()["estimates"]


def test_the_inputs_the_response_says_it_used_are_the_ones_of_the_body(served, valid):
    document = post(served, valid).json()
    history = pd.DataFrame(valid["lab_history"])
    assert document["inputs"] == {"sensor_rows": len(valid["readings"]), "fresh_analyses": len(history), "newest_sample_hour": history["sample_hour"].max(), "feed": True}
    without_feed = post(served, {**valid, "feed": None}).json()
    assert without_feed["inputs"]["feed"] is False and without_feed["persistence"] == document["persistence"] == valid["lab_history"][-1]["silica_pct"]


def test_a_partial_hour_gets_the_reason_the_pipeline_gives_and_no_number(served, valid, scored):
    few = valid["readings"][: served.cfg.hours.min_rows_per_hour - 1]
    response = post(served, {**valid, "readings": few})
    assert response.status_code == 200 and len(scored) == 1
    document = response.json()
    assert document["inputs"]["sensor_rows"] == len(few)
    assert [(e["status"], e["reason"], e["estimate"], e["low"], e["high"], e["b_star"]) for e in document["estimates"]] == [("missing_inputs", "partial_below_minimum", None, None, None, None)] * 3


# --- the refusals: 422 before estimating -------------------------------------------------------------------------------------------------------------------------


def with_(body: dict, **changes) -> dict:
    return {**body, **changes}


def nan_reading(body):
    row = dict(body["readings"][0], amina_flow=float("nan"))
    return json.dumps(with_(body, readings=[row, *body["readings"][1:]]))


def infinite_silica(body):
    return json.dumps(with_(body, lab_history=[dict(body["lab_history"][0], silica_pct=float("inf")), *body["lab_history"][1:]]))


REFUSED = {
    "a NaN reading": (nan_reading, "invalid_request", "readings.0.amina_flow", "finite_number"),
    "an infinite analysis": (infinite_silica, "invalid_request", "lab_history.0.silica_pct", "finite_number"),
    "a reading as text": (lambda b: with_(b, readings=[dict(b["readings"][0], amina_flow="1.5"), *b["readings"][1:]]), "invalid_request", "readings.0.amina_flow", "float_type"),
    "a reading that is a boolean": (lambda b: with_(b, readings=[dict(b["readings"][0], amina_flow=True), *b["readings"][1:]]), "invalid_request", "readings.0.amina_flow", "float_type"),
    "a reading without a sensor": (lambda b: with_(b, readings=[{k: v for k, v in b["readings"][0].items() if k != "amina_flow"}, *b["readings"][1:]]), "invalid_request",
                                   "readings.0.amina_flow", "missing"),
    "an unknown field": (lambda b: with_(b, extra=1), "invalid_request", "extra", "extra_forbidden"),
    "a held analysis": (lambda b: with_(b, lab_history=[dict(b["lab_history"][0], state="held"), *b["lab_history"][1:]]), "invalid_request", "lab_history.0.state", "literal_error"),
    "silica over 100": (lambda b: with_(b, lab_history=[dict(b["lab_history"][0], silica_pct=100.5), *b["lab_history"][1:]]), "invalid_request", "lab_history.0.silica_pct", "less_than_equal"),
    "silica under 0": (lambda b: with_(b, lab_history=[dict(b["lab_history"][0], silica_pct=-0.1), *b["lab_history"][1:]]), "invalid_request", "lab_history.0.silica_pct", "greater_than_equal"),
    "an instant with a zone": (lambda b: with_(b, issue_at=b["issue_at"] + "Z"), "invalid_request", "issue_at", "timezone_naive"),
    "an instant as a number": (lambda b: with_(b, issue_at=1_490_000_000), "invalid_request", "issue_at", "value_error"),
    "an instant that is not on the hour": (lambda b: with_(b, issue_at=(pd.Timestamp(b["issue_at"]) + timedelta(minutes=30)).isoformat()), "not_on_the_hour", "issue_at", None),
    "a sample hour that is not on the hour": (lambda b: with_(b, lab_history=[dict(b["lab_history"][0], sample_hour=(pd.Timestamp(b["lab_history"][0]["sample_hour"]) + timedelta(seconds=1)).isoformat()),
                                                                              *b["lab_history"][1:]]), "not_on_the_hour", "lab_history.0.sample_hour", None),
    "no readings": (lambda b: with_(b, readings=[]), "invalid_request", "readings", "too_short"),
    "no analyses": (lambda b: with_(b, lab_history=[]), "invalid_request", "lab_history", "too_short"),
    "a repeated sample hour": (lambda b: with_(b, lab_history=[*b["lab_history"], b["lab_history"][-1]]), "duplicate_sample_hour", f"lab_history.{{last}}.sample_hour", None),
    "a feed over 100 %": (lambda b: with_(b, feed=dict(b["feed"], feed_silica_pct=100.5)), "invalid_request", "feed.feed_silica_pct", "less_than_equal"),
    "a feed without its age": (lambda b: with_(b, feed={k: v for k, v in b["feed"].items() if k != "feed_iron_age_h"}), "invalid_request", "feed.feed_iron_age_h", "missing"),
    "too few analyses": (lambda b: with_(b, lab_history=b["lab_history"][-3:]), "short_lab_history", "lab_history", None),
    "a body that is not JSON": (lambda b: "{not json", "invalid_request", "", "json_invalid"),
}


@pytest.mark.parametrize("name", list(REFUSED))
def test_every_input_the_service_cannot_trust_is_a_422_with_its_code_and_estimates_nothing(name, served, valid, scored):
    make, error, field, kind = REFUSED[name]
    body = make(valid)
    response = served.client.post("/estimate", content=body if isinstance(body, str) else json.dumps(body), headers={"content-type": "application/json"})
    field = field.format(last=len(valid["lab_history"]))
    assert_refused(response, error, field=field if kind else None, kind=kind)
    if not kind:
        assert response.json()["field"] == field
    assert scored == [], "nothing was estimated"


def test_an_analysis_after_the_issue_instant_is_refused_with_422(served, valid, scored):
    latency = served.cfg.lab.latency_hours
    issue_at = pd.Timestamp(valid["issue_at"])
    late = {"sample_hour": (issue_at - timedelta(hours=latency - 1)).isoformat(), "silica_pct": 2.0, "state": "fresh"}      # arrives one hour after the instant
    response = post(served, with_(valid, lab_history=[*valid["lab_history"], late]))
    document = assert_refused(response, "analysis_after_issue")
    assert document["field"] == f"lab_history.{len(valid['lab_history'])}.sample_hour"
    # the same rule from the other side: the newest analysis of the body is not known one hour before it arrives, and is known at the very instant it does
    newest = pd.Timestamp(valid["lab_history"][-1]["sample_hour"]) + timedelta(hours=latency)
    before = post(served, with_(valid, issue_at=(newest - HOUR).isoformat()))
    assert_refused(before, "analysis_after_issue")
    assert before.json()["field"] == f"lab_history.{len(valid['lab_history']) - 1}.sample_hour"
    assert scored == []
    arrival = post(served, with_(valid, issue_at=newest.isoformat()))
    assert arrival.status_code == 200 and scored == [newest.to_pydatetime()], "an analysis counts at the instant it arrives"


@pytest.mark.parametrize(("what", "make", "field"), [
    ("readings", lambda b, cfg: with_(b, readings=[b["readings"][0]] * (cfg.hours.rows_per_hour + 1)), "readings"),
    ("lab_history", lambda b, cfg: with_(b, lab_history=[{"sample_hour": (pd.Timestamp(b["lab_history"][-1]["sample_hour"]) - timedelta(hours=k)).isoformat(), "silica_pct": 2.0}
                                                         for k in range(cfg.api.max_lab_history + 1)]), "lab_history"),
])
def test_lists_over_their_limits_are_refused_with_422(what, make, field, served, valid, scored):
    assert_refused(post(served, make(valid, served.cfg)), "invalid_request", field=field, kind="too_long")
    assert scored == []
    at_the_limit = make(valid, served.cfg)
    at_the_limit[what] = at_the_limit[what][:-1]
    assert post(served, at_the_limit).status_code == 200, "the limit itself is accepted"


def test_a_failure_inside_the_estimate_never_leaks_a_path_or_a_trace(served, valid, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError(f"no puedo abrir {PROJECT / 'data' / 'models' / 'v1' / 'model.pkl'}")

    monkeypatch.setattr(api, "score_issue", broken)
    response = post(served, valid)
    assert response.status_code == 500 and response.text == "Internal Server Error", response.text

    def not_finite(*args, **kwargs):
        raise EstimateError(f"M04: la estimación del modelo no es un número finito ({PROJECT})")

    monkeypatch.setattr(api, "score_issue", not_finite)
    assert_refused(post(served, valid), "estimate_refused")


# --- what the service serves ---------------------------------------------------------------------------------------------------------------------------------------


def test_health_says_which_model_and_configuration_it_serves(served):
    response = served.client.get("/health")
    seal = read_seal(served.history.paths.seal)
    assert response.status_code == 200
    document = response.json()
    assert document["status"] == "ok" and document["model_version"] == seal["launch"]["model_version"] == served.history.sealed.model.model_version
    assert document["config_sha256"] == seal["launch"]["config_sha256"]
    assert document["seal"] == ("launch_and_test" if seal.get("test") is not None else "launch")
    assert [item["horizon"] for item in document["half_widths"]] == list(served.cfg.evaluation.horizons)
    assert set(document) == {"status", "model_version", "config_sha256", "seal", "half_widths"}
    conn = sqlite3.connect(f"{served.history.paths.db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        bundle = load_registered_bundle(conn, served.cfg.paths.models_dir, document["model_version"])
    finally:
        conn.close()
    assert [(item["horizon"], item["half_width"]) for item in document["half_widths"]] == [(hm.horizon, hm.half_width) for hm in bundle.horizons]
    assert all(item["half_width"] > 0 for item in document["half_widths"])


def test_only_health_and_estimate_are_served_and_there_are_no_documentation_pages(served):
    assert {route.path for route in served.app.routes} == {"/health", "/estimate"}
    for path in ("/docs", "/redoc", "/openapi.json", "/", "/metrics"):
        assert served.client.get(path).status_code == 404, path
    assert served.client.get("/estimate").status_code == 405 and served.client.post("/health").status_code == 405


def test_the_api_writes_no_file(served, valid, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    watched = (PROJECT, served.history.paths.db.parent, tmp_path)
    before = [fingerprint(root) for root in watched]
    valid_body = json.dumps(valid)
    refusals = [make(valid) for make, *_ in list(REFUSED.values())[:15]]
    for k in range(50):
        if k % 5 == 0:
            assert post(served, valid).status_code == 200
        elif k % 5 == 1:
            assert served.client.get("/health").status_code == 200
        else:
            body = refusals[k % len(refusals)]
            assert served.client.post("/estimate", content=body if isinstance(body, str) else json.dumps(body), headers={"content-type": "application/json"}).status_code == 422
    assert served.client.post("/estimate", content=valid_body, headers={"content-type": "application/json"}).status_code == 200
    assert [fingerprint(root) for root in watched] == before and list(tmp_path.iterdir()) == []


# --- create_app: what it refuses to serve --------------------------------------------------------------------------------------------------------------------


def test_create_app_refuses_a_missing_seal_a_changed_configuration_and_an_altered_artifact_and_writes_nothing(small_history, tmp_path):
    def refused(make_cfg, error, says):
        copy = copy_history(small_history, tmp_path / says.replace(" ", "_"))
        cfg = make_cfg(config_of(copy), copy)
        before = fingerprint(copy.paths.db.parent)
        with pytest.raises(error, match=says) as caught:
            create_app(cfg)
        assert str(tmp_path) not in str(caught.value) or error is ArtifactMismatchError      # the start-up refusals of this module name no path
        assert fingerprint(copy.paths.db.parent) == before

    refused(lambda cfg, h: (h.paths.seal.unlink(), cfg)[1], ApiStartError, "no hay sello")
    refused(lambda cfg, h: dataclasses.replace(cfg, model=dataclasses.replace(cfg.model, random_state=cfg.model.random_state + 1)), ApiStartError, "otra configuración")

    def altered(cfg, h):
        artifact = next(h.paths.models.rglob("*.pkl"))
        artifact.write_bytes(artifact.read_bytes() + b"\0")
        return cfg

    refused(altered, ArtifactMismatchError, "M03")
