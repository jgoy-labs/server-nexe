"""B254: the validation error handler must not leak the offending value.

Pydantic v2 echoes the rejected input in ``errors()[*]['input']``. For an
oversized HF-token paste that field is the secret itself, and the handler used
to both log it and return it in the 422 body. ``_sanitize_validation_errors``
strips ``input`` while keeping type/loc/msg/ctx/url (none carry the value).

Each test asserts a behaviour a control mutation breaks (returning the raw
``exc.errors()`` re-leaks the secret → red).
"""
from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, field_validator

from core.endpoints.installer import HfTokenBody
from core.server.exception_handlers import (
    _sanitize_validation_errors,
    register_exception_handlers,
)

# A value over the 200-char cap so Pydantic raises string_too_long (whose
# `input` echoes the whole value), with a recognisable secret marker.
SECRET = "hf_" + "S" * 250


class _Body(BaseModel):
    token: str = Field(..., min_length=1, max_length=200)


class _PolicyBody(BaseModel):
    """A model whose custom validator always raises — Pydantic packs the live
    exception into ``ctx={'error': ValueError(...)}`` (the B256 landmine).
    Module-level so FastAPI treats it as a request body, not a query param."""

    name: str

    @field_validator("name")
    @classmethod
    def _reject(cls, v: str) -> str:
        raise ValueError("rejected by policy")  # static msg, no user value


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app, i18n=None)

    @app.post("/echo")
    async def echo(body: _Body):  # noqa: ANN202
        return {"ok": True}

    return app


# ── unit: the helper ──────────────────────────────────────────────────────────


def test_sanitize_strips_input_keeps_diagnostics():
    errs = [{
        "type": "string_too_long",
        "loc": ("body", "token"),
        "msg": "String should have at most 200 characters",
        "input": SECRET,
        "ctx": {"max_length": 200},
        "url": "https://errors.pydantic.dev/x",
    }]
    out = _sanitize_validation_errors(errs)
    assert "input" not in out[0], "input (the secret) must be stripped"
    assert SECRET not in str(out)
    # diagnostics preserved
    assert out[0]["type"] == "string_too_long"
    assert out[0]["loc"] == ("body", "token")
    assert out[0]["ctx"] == {"max_length": 200}


def test_sanitize_handles_mixed_and_inputless_errors():
    errs = [
        {"type": "missing", "loc": ("body", "x"), "msg": "Field required"},  # no input key
        {"type": "string_too_long", "loc": ("body", "token"), "msg": "too long", "input": SECRET},
    ]
    out = _sanitize_validation_errors(errs)
    assert len(out) == 2
    assert all("input" not in e for e in out)
    assert SECRET not in str(out)


# ── e2e: the global handler over a real validated endpoint ─────────────────────


def test_oversized_token_not_leaked_in_422_body():
    client = TestClient(_app())
    r = client.post("/echo", json={"token": SECRET})
    assert r.status_code == 422
    assert SECRET not in r.text, "token leaked in 422 response body"
    detail = r.json()["detail"]
    assert detail and detail[0]["type"] == "string_too_long"
    assert "input" not in detail[0]
    assert detail[0]["loc"][-1] == "token"


def test_oversized_token_not_leaked_in_log(caplog):
    client = TestClient(_app())
    with caplog.at_level(logging.ERROR, logger="core.server.exception_handlers"):
        r = client.post("/echo", json={"token": SECRET})
    assert r.status_code == 422
    assert SECRET not in caplog.text, "token leaked in error log"


def test_normal_validation_still_reports_useful_detail():
    """No-regression: a plain missing-field error still yields a usable 422
    (type/loc/msg present) so clients can act on it."""
    client = TestClient(_app())
    r = client.post("/echo", json={})  # missing 'token'
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail and detail[0]["type"] == "missing"
    assert detail[0]["loc"][-1] == "token"
    assert "input" not in detail[0]


def test_real_hftokenbody_oversized_not_leaked():
    """Exercise the REAL endpoint model (HfTokenBody, the B254 path) — not just a
    toy model — so the coverage is not 'correct by accident'."""
    app = FastAPI()
    register_exception_handlers(app, i18n=None)

    @app.post("/real")
    async def real(body: HfTokenBody):  # noqa: ANN202
        return {"ok": True}

    r = TestClient(app).post("/real", json={"token": SECRET})
    assert r.status_code == 422
    assert SECRET not in r.text, "real HfTokenBody path leaked the token"
    detail = r.json()["detail"]
    assert detail[0]["type"] == "string_too_long"
    assert "input" not in detail[0]


def test_oversized_query_param_not_leaked():
    """The global handler covers query params too (not only JSON bodies)."""
    from fastapi import Query

    app = FastAPI()
    register_exception_handlers(app, i18n=None)

    @app.get("/q")
    async def q(v: str = Query(..., max_length=10)):  # noqa: ANN202
        return {"ok": True}

    long = "Q" * 60
    r = TestClient(app).get("/q", params={"v": long})
    assert r.status_code == 422
    assert long not in r.text, "oversized query param echoed in 422 body"
    assert "input" not in r.json()["detail"][0]


# ── B256: custom-validator ctx must not crash the 422 into a 500 ───────────────


def test_sanitize_drops_nonserializable_ctx_keeps_primitives():
    """Unit: a custom validator's ``ctx={'error': ValueError(...)}`` is dropped
    (it would crash JSONResponse), while flat primitive ctx survives. Mutation:
    revert to the old comprehension (keeps ctx) → ``json.dumps`` raises."""
    import json

    errs = [{
        "type": "value_error",
        "loc": ("body", "name"),
        "msg": "Value error, rejected",
        "ctx": {"error": ValueError("boom"), "limit": 5},
    }]
    out = _sanitize_validation_errors(errs)
    assert "error" not in (out[0].get("ctx") or {}), "non-serialisable ctx['error'] must be dropped"
    assert out[0]["ctx"] == {"limit": 5}, "primitive ctx entries must survive"
    json.dumps(out)  # must not raise — the whole point of B256


def test_custom_validator_ctx_does_not_500():
    """A custom ``@field_validator`` that raises packs the live exception into
    ``ctx={'error': ValueError(...)}``. Before B256 the global handler returned
    that ctx verbatim and ``JSONResponse.render()`` raised ``TypeError: ... not
    JSON serializable`` → the 422 collapsed into a 500. The sanitiser now drops
    the non-primitive ctx, so the error stays a clean 422.

    Control mutation: revert ``_sanitize_validation_errors`` to keep ``ctx`` →
    this returns 500 (red)."""
    app = FastAPI()
    register_exception_handlers(app, i18n=None)

    @app.post("/policy")
    async def policy(body: _PolicyBody):  # noqa: ANN202
        return {"ok": True}

    # raise_server_exceptions=False so a 500 surfaces as a response, not a raise.
    r = TestClient(app, raise_server_exceptions=False).post("/policy", json={"name": "x"})
    assert r.status_code == 422, "custom-validator ctx must not collapse the 422 into a 500"
    detail = r.json()["detail"]
    assert detail and detail[0]["type"] == "value_error"
    assert "error" not in (detail[0].get("ctx") or {})


def test_ollama_allowlist_msg_does_not_echo_model_name(monkeypatch):
    """The one HTTP-exposed custom validator that interpolated a user value
    (PullModelRequest, ``f"model {v!r} not in ... allowlist"``) now uses a static
    message. The rejected model name must appear in neither ``str(exc)`` nor the
    sanitised structured errors the handler serialises.

    Control mutation: restore the ``f"... {v!r} ..."`` message → the sentinel
    reappears (red)."""
    from pydantic import ValidationError

    from plugins.ollama_module.api.routes import PullModelRequest

    monkeypatch.setenv("NEXE_OLLAMA_ALLOWED_MODELS", "qwen3*,llama3*")
    sentinel = "evilmodel-SENTINEL-xyz"  # valid format, outside the allowlist
    with pytest.raises(ValidationError) as ei:
        PullModelRequest(name=sentinel)
    # NB: ``str(ValidationError)`` always echoes the value via Pydantic's own
    # ``input_value=`` repr — but the handler never serialises that; it serialises
    # ``_sanitize_validation_errors(exc.errors())``, where ``input`` is stripped
    # and (after the source fix) ``msg`` no longer interpolates the value.
    safe = _sanitize_validation_errors(ei.value.errors())
    assert sentinel not in str(safe), "rejected model name leaked in the structured errors"
