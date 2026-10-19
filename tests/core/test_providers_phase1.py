"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_providers_phase1.py
Description: External API providers, phase 1 (configuration + connection
    test). Every test talks to a fake endpoint (httpx.MockTransport) or to
    none at all: no real network, no real key. The recurring guarantee is
    that the key never shows up in a result, a log record or an HTTP body
    served by the admin endpoint, and that no request is made without a key.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
from typing import List

import httpx
import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from core.providers.registry import provider_for_model
from core.providers import (
    PROVIDERS,
    Provider,
    check_connection,
    get_provider,
    is_configured,
    provider_status,
)

# Obviously fake, unique, and distinctive so a substring search cannot match by accident.
FAKE_KEY = "FAKE-KEY-for-tests-7f3a9c1e-not-a-secret"
GOOD_BODY = {"object": "list", "data": [{"id": "m1"}]}


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch):
    for p in PROVIDERS:
        monkeypatch.delenv(p.env_var, raising=False)


def _must_not_be_called(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected request to {request.url}")


def _recording(response_factory, seen: List[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response_factory(request)
    return httpx.MockTransport(handler)


def _answer(status: int = 200, **kwargs):
    return lambda request: httpx.Response(status, **kwargs)


# --------------------------------------------------------------------- registry

class TestRegistry:
    def test_deepseek_entry(self):
        p = get_provider("deepseek")
        # Phase 2 added chat fields to the entry (chat path, selector models,
        # vision, windows); what phase 1 declared is unchanged.
        assert (p.key, p.name, p.endpoint, p.env_var, p.models, p.models_path) == (
            "deepseek", "DeepSeek", "https://api.deepseek.com",
            "DEEPSEEK_API_KEY", ("deepseek-chat", "deepseek-reasoner"), "/v1/models",
        )

    def test_openai_entry(self):
        p = get_provider("openai")
        assert p.endpoint == "https://api.openai.com"
        assert p.env_var == "OPENAI_API_KEY"
        assert p.models == ("gpt-*",)

    def test_anthropic_entry(self):
        p = get_provider("anthropic")
        assert (p.name, p.endpoint, p.env_var, p.models) == (
            "Claude", "https://api.anthropic.com", "ANTHROPIC_API_KEY", ("claude-*",))
        assert (p.models_path, p.chat_path) == ("/v1/models", "/v1/chat/completions")

    def test_the_listing_sends_the_version_header_claude_demands(self, monkeypatch):
        # Live 13/10: without it GET /v1/models answers 400 «anthropic-version: header is required».
        monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
        seen: List[httpx.Request] = []
        res = check_connection("anthropic", transport=_recording(_answer(200, json=GOOD_BODY), seen))
        assert res["ok"] is True
        assert seen[0].headers["anthropic-version"] == "2023-06-01"
        assert seen[0].headers["authorization"] == f"Bearer {FAKE_KEY}"

    def test_other_providers_send_no_extra_header(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
        seen: List[httpx.Request] = []
        check_connection("openai", transport=_recording(_answer(200, json=GOOD_BODY), seen))
        assert "anthropic-version" not in seen[0].headers

    def test_the_selector_offers_the_current_claude_models(self):
        p = get_provider("anthropic")
        assert set(p.suggested_models) == {
            "claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "claude-fable-5-1"}
        # What the selector lists must also pass the allowlist a request is checked against.
        assert all(provider_for_model(m) is p for m in p.suggested_models)
        assert provider_for_model("gpt-4o").key == "openai"

    def test_registry_has_exactly_the_known_providers(self):
        assert [p.key for p in PROVIDERS] == ["deepseek", "openai", "anthropic"]

    def test_unknown_provider_is_none(self):
        assert get_provider("nope") is None
        assert get_provider("") is None

    def test_entries_declare_where_the_key_is_never_the_value(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
        assert FAKE_KEY not in repr(PROVIDERS)
        assert FAKE_KEY not in repr(get_provider("deepseek"))

    def test_adding_a_provider_is_one_entry(self, monkeypatch):
        extra = Provider(key="acme", name="Acme", endpoint="https://api.acme.test",
                         env_var="ACME_API_KEY", models=("acme-1",))
        monkeypatch.setattr("core.providers.registry.PROVIDERS", PROVIDERS + (extra,))
        assert get_provider("acme") == extra
        monkeypatch.setenv("ACME_API_KEY", FAKE_KEY)
        status = provider_status()
        assert [p["key"] for p in status["providers"]] == ["deepseek", "openai", "anthropic", "acme"]
        assert status["providers"][3]["configured"] is True
        seen: List[httpx.Request] = []
        res = check_connection("acme", transport=_recording(_answer(200, json=GOOD_BODY), seen))
        assert res["ok"] is True
        assert str(seen[0].url) == "https://api.acme.test/v1/models"


# ----------------------------------------------------------------------- status

class TestStatus:
    def test_not_configured_by_default(self):
        status = provider_status()
        assert [p["configured"] for p in status["providers"]] == [False, False, False]
        assert all(is_configured(p) is False for p in PROVIDERS)

    def test_configured_when_key_present(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
        by_key = {p["key"]: p["configured"] for p in provider_status()["providers"]}
        assert by_key == {"deepseek": False, "openai": True, "anthropic": False}

    @pytest.mark.parametrize("blank", ["", "   ", "\n"])
    def test_blank_key_is_not_configured(self, monkeypatch, blank):
        monkeypatch.setenv("DEEPSEEK_API_KEY", blank)
        assert is_configured(get_provider("deepseek")) is False

    def test_status_never_exposes_value_or_length(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
        status = provider_status()
        blob = json.dumps(status)
        assert FAKE_KEY not in blob
        assert FAKE_KEY[:6] not in blob and FAKE_KEY[-6:] not in blob
        # only these fields, so a length/hash/prefix field cannot sneak in
        for entry in status["providers"]:
            assert set(entry) == {"key", "name", "endpoint", "env_var", "models", "configured"}
        assert isinstance(status["providers"][0]["configured"], bool)

    def test_status_makes_no_request(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)

        def boom(*a, **k):
            raise AssertionError("status must not touch the network")
        monkeypatch.setattr(httpx, "Client", boom)
        monkeypatch.setattr("core.providers.connection.check_connection", boom)
        provider_status()


# ------------------------------------------------------------- check_connection

class TestCheckConnection:
    def test_ok_sends_one_minimal_authenticated_get(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
        seen: List[httpx.Request] = []
        res = check_connection("deepseek", transport=_recording(_answer(200, json=GOOD_BODY), seen))
        assert res == {"provider": "deepseek", "ok": True, "reason": "ok", "status_code": 200}
        assert len(seen) == 1
        req = seen[0]
        assert req.method == "GET"
        assert str(req.url) == "https://api.deepseek.com/v1/models"
        assert req.headers["authorization"] == f"Bearer {FAKE_KEY}"
        assert req.content == b""  # no user message, no context

    def test_openai_uses_its_own_endpoint_and_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "FAKE-OTHER-KEY-should-not-be-sent")
        seen: List[httpx.Request] = []
        check_connection("openai", transport=_recording(_answer(200, json=GOOD_BODY), seen))
        assert str(seen[0].url) == "https://api.openai.com/v1/models"
        assert seen[0].headers["authorization"] == f"Bearer {FAKE_KEY}"

    @pytest.mark.parametrize("status", [401, 403])
    def test_unauthorized(self, monkeypatch, status):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
        res = check_connection("deepseek", transport=_recording(_answer(status, json={"error": "x"}), []))
        assert (res["ok"], res["reason"], res["status_code"]) == (False, "unauthorized", status)

    @pytest.mark.parametrize("status", [404, 429, 500, 503])
    def test_http_status_reason(self, monkeypatch, status):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
        res = check_connection("deepseek", transport=_recording(_answer(status, text="boom"), []))
        assert (res["ok"], res["reason"], res["status_code"]) == (False, f"http_{status}", status)

    @pytest.mark.parametrize("status,reason", [(299, "ok"), (300, "http_300"), (199, "http_199")])
    def test_success_range_edges(self, monkeypatch, status, reason):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
        res = check_connection("deepseek", transport=_recording(_answer(status, json=GOOD_BODY), []))
        assert res["reason"] == reason

    def test_redirect_is_not_followed(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
        seen: List[httpx.Request] = []
        res = check_connection(
            "deepseek",
            transport=_recording(_answer(302, headers={"location": "https://evil.test/"}), seen),
        )
        assert res["reason"] == "http_302"
        assert len(seen) == 1  # the key was not forwarded to the redirect target

    def test_bad_response_not_json(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
        res = check_connection("deepseek", transport=_recording(_answer(200, text="<html>hi</html>"), []))
        assert (res["ok"], res["reason"]) == (False, "bad_response")

    @pytest.mark.parametrize("body", [{"nope": 1}, [1, 2], {"data": "x"}, "str", None])
    def test_bad_response_wrong_shape(self, monkeypatch, body):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
        res = check_connection("deepseek", transport=_recording(_answer(200, json=body), []))
        assert (res["ok"], res["reason"]) == (False, "bad_response")

    @pytest.mark.parametrize("exc", [httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError])
    def test_unreachable(self, monkeypatch, exc):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)

        def fail(request):
            raise exc("connection refused")
        res = check_connection("deepseek", transport=httpx.MockTransport(fail))
        assert (res["ok"], res["reason"], res["status_code"]) == (False, "unreachable", None)

    @pytest.mark.parametrize("exc", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout])
    def test_timeout(self, monkeypatch, exc):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)

        def fail(request):
            raise exc("timed out")
        res = check_connection("deepseek", transport=httpx.MockTransport(fail))
        assert (res["ok"], res["reason"], res["status_code"]) == (False, "timeout", None)

    def test_timeout_value_is_short_by_default_and_overridable(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
        seen: List[httpx.Request] = []
        check_connection("deepseek", transport=_recording(_answer(200, json=GOOD_BODY), seen))
        assert seen[0].extensions["timeout"]["read"] == 5.0
        seen.clear()
        check_connection("deepseek", timeout=1.5, transport=_recording(_answer(200, json=GOOD_BODY), seen))
        assert seen[0].extensions["timeout"]["connect"] == 1.5

    def test_no_key_makes_no_request(self):
        res = check_connection("deepseek", transport=httpx.MockTransport(_must_not_be_called))
        assert res == {"provider": "deepseek", "ok": False, "reason": "no_key", "status_code": None}

    @pytest.mark.parametrize("blank", ["", "  "])
    def test_blank_key_makes_no_request(self, monkeypatch, blank):
        monkeypatch.setenv("OPENAI_API_KEY", blank)
        res = check_connection("openai", transport=httpx.MockTransport(_must_not_be_called))
        assert res["reason"] == "no_key"

    def test_no_key_does_not_even_build_a_client(self, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("an HTTP client was built without a key")
        monkeypatch.setattr(httpx, "Client", boom)
        assert check_connection("deepseek")["reason"] == "no_key"

    def test_unknown_provider_makes_no_request(self):
        res = check_connection("nope", transport=httpx.MockTransport(_must_not_be_called))
        assert (res["ok"], res["reason"]) == (False, "unknown_provider")


# ------------------------------------------------------------------ key leakage

class TestNoKeyLeak:
    """The key must not surface in any result, message or log, whatever the provider answers."""

    @pytest.fixture
    def key_set(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)

    def _assert_clean(self, res, caplog):
        assert FAKE_KEY not in json.dumps(res)
        assert FAKE_KEY not in repr(res)
        for record in caplog.records:
            assert FAKE_KEY not in record.getMessage()
            assert FAKE_KEY not in str(record.args)
            assert record.exc_info is None
        assert FAKE_KEY not in caplog.text

    @pytest.mark.parametrize("status", [200, 401, 500])
    def test_provider_echoing_the_key_in_the_body(self, key_set, caplog, status):
        body = {"error": {"message": f"Incorrect API key provided: {FAKE_KEY}"}, "data": []}
        with caplog.at_level(logging.DEBUG):
            res = check_connection("deepseek", transport=_recording(_answer(status, json=body), []))
        self._assert_clean(res, caplog)

    def test_provider_echoing_the_key_in_a_non_json_body(self, key_set, caplog):
        with caplog.at_level(logging.DEBUG):
            res = check_connection("deepseek", transport=_recording(_answer(200, text=f"hello {FAKE_KEY}"), []))
        assert res["reason"] == "bad_response"
        self._assert_clean(res, caplog)

    def test_exception_message_containing_the_key(self, key_set, caplog):
        def fail(request):
            raise httpx.ConnectError(f"cannot connect with Bearer {FAKE_KEY}")
        with caplog.at_level(logging.DEBUG):
            res = check_connection("deepseek", transport=httpx.MockTransport(fail))
        assert res["reason"] == "unreachable"
        self._assert_clean(res, caplog)

    def test_timeout_exception_containing_the_key(self, key_set, caplog):
        def fail(request):
            raise httpx.ReadTimeout(f"timeout for {FAKE_KEY}")
        with caplog.at_level(logging.DEBUG):
            res = check_connection("deepseek", transport=httpx.MockTransport(fail))
        assert res["reason"] == "timeout"
        self._assert_clean(res, caplog)

    def test_error_response_headers_containing_the_key(self, key_set, caplog):
        with caplog.at_level(logging.DEBUG):
            res = check_connection(
                "deepseek",
                transport=_recording(_answer(500, headers={"x-debug": FAKE_KEY}, text="x"), []),
            )
        self._assert_clean(res, caplog)

    @pytest.mark.parametrize("suffix", ["\n", "\x01", " x", "\u00e9", "\t"])
    def test_key_not_safe_for_a_header_is_rejected_before_any_request(self, monkeypatch, caplog, suffix):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "AA" + suffix + FAKE_KEY)  # inner: strip() would eat a trailing one
        with caplog.at_level(logging.DEBUG):
            res = check_connection("deepseek", transport=httpx.MockTransport(_must_not_be_called))
        assert (res["ok"], res["reason"], res["status_code"]) == (False, "invalid_key", None)
        assert FAKE_KEY not in json.dumps(res)
        assert FAKE_KEY not in caplog.text

    def test_non_ascii_key_does_not_raise(self, monkeypatch):
        # httpx raises UnicodeEncodeError (not an httpx.HTTPError) for this value.
        monkeypatch.setenv("DEEPSEEK_API_KEY", "caf\u00e9-" + FAKE_KEY)
        assert check_connection("deepseek", transport=_recording(_answer(200, json=GOOD_BODY), []))["reason"] == "invalid_key"

    def test_failure_log_names_provider_and_reason_only(self, key_set, caplog):
        with caplog.at_level(logging.WARNING, logger="core.providers.connection"):
            check_connection("deepseek", transport=_recording(_answer(401), []))
        msgs = [r.getMessage() for r in caplog.records if r.name == "core.providers.connection"]
        assert msgs == ["Provider connection check failed: provider=deepseek reason=unauthorized"]

    def test_no_key_failure_is_logged_by_name_and_reason(self, caplog):
        with caplog.at_level(logging.WARNING, logger="core.providers.connection"):
            check_connection("openai")
        assert [r.getMessage() for r in caplog.records] == [
            "Provider connection check failed: provider=openai reason=no_key"
        ]

    def test_success_logs_nothing(self, key_set, caplog):
        with caplog.at_level(logging.DEBUG, logger="core.providers.connection"):
            check_connection("deepseek", transport=_recording(_answer(200, json=GOOD_BODY), []))
        assert caplog.records == []


# ----------------------------------------------------------- admin endpoints

@pytest.fixture
def admin_client(app, monkeypatch, admin_api_key):
    monkeypatch.setenv("NEXE_DEV_MODE", "false")
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", admin_api_key)
    with TestClient(app, base_url="http://localhost") as client:
        yield client


class TestAdminEndpoints:
    @pytest.mark.parametrize("method,path", [
        ("get", "/admin/providers/status"),
        ("post", "/admin/providers/deepseek/check"),
    ])
    def test_requires_authentication(self, admin_client, monkeypatch, method, path):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
        monkeypatch.setattr("core.endpoints.providers.check_connection", _must_not_be_called)
        resp = getattr(admin_client, method)(path)
        assert resp.status_code in (401, 403)
        resp = getattr(admin_client, method)(path, headers={"X-API-Key": "wrong"})
        assert resp.status_code in (401, 403)

    def test_status_reports_presence_not_value(self, admin_client, auth_headers, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
        resp = admin_client.get("/admin/providers/status", headers=auth_headers)
        assert resp.status_code == 200
        assert FAKE_KEY not in resp.text
        by_key = {p["key"]: p["configured"] for p in resp.json()["providers"]}
        assert by_key == {"deepseek": False, "openai": True, "anthropic": False}

    def test_check_without_key_is_no_key_and_makes_no_request(self, admin_client, auth_headers, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("no key -> no HTTP client")
        monkeypatch.setattr(httpx, "Client", boom)
        resp = admin_client.post("/admin/providers/deepseek/check", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"provider": "deepseek", "ok": False, "reason": "no_key", "status_code": None}

    def test_check_unknown_provider_is_404(self, admin_client, auth_headers):
        resp = admin_client.post("/admin/providers/nope/check", headers=auth_headers)
        assert resp.status_code == 404

    def test_check_returns_the_structured_result_without_the_key(self, admin_client, auth_headers, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
        real_check = check_connection
        transport = _recording(_answer(401, json={"error": FAKE_KEY}), [])
        monkeypatch.setattr(
            "core.endpoints.providers.check_connection",
            lambda key: real_check(key, transport=transport),
        )
        resp = admin_client.post("/admin/providers/deepseek/check", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"provider": "deepseek", "ok": False, "reason": "unauthorized", "status_code": 401}
        assert FAKE_KEY not in resp.text


# ------------------------------------------------------------------------ CLI

class TestCli:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def _app(self):
        from core.cli.cli import app
        return app

    def test_status_lists_presence_only(self, runner, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
        payload = provider_status()
        monkeypatch.setattr("core.cli.client.NexeClient.get_providers_status", lambda self: payload)
        result = runner.invoke(self._app(), ["--no-banner", "providers", "status"])
        assert result.exit_code == 0, result.output
        lines = {ln.split()[0]: ln for ln in result.output.splitlines() if ln.strip()}
        assert "not configured" not in lines["deepseek"] and "configured" in lines["deepseek"]
        assert "not configured" in lines["openai"]
        assert "DEEPSEEK_API_KEY" in lines["deepseek"]
        assert FAKE_KEY not in result.output

    def test_check_ok_exits_zero(self, runner, monkeypatch):
        monkeypatch.setattr("core.cli.client.NexeClient.check_provider",
                            lambda self, k: {"provider": k, "ok": True, "reason": "ok", "status_code": 200})
        result = runner.invoke(self._app(), ["--no-banner", "providers", "check", "deepseek"])
        assert result.exit_code == 0
        assert "deepseek: ok" in result.output

    def test_check_failure_prints_reason_and_exits_nonzero(self, runner, monkeypatch):
        monkeypatch.setattr("core.cli.client.NexeClient.check_provider",
                            lambda self, k: {"provider": k, "ok": False, "reason": "unauthorized", "status_code": 401})
        result = runner.invoke(self._app(), ["--no-banner", "providers", "check", "openai"])
        assert result.exit_code == 1
        assert "openai: failed (unauthorized)" in result.output

    def test_server_error_exits_nonzero(self, runner, monkeypatch):
        monkeypatch.setattr("core.cli.client.NexeClient.check_provider",
                            lambda self, k: {"error": True, "status_code": 401, "message": "Unauthorized"})
        result = runner.invoke(self._app(), ["--no-banner", "providers", "check", "openai"])
        assert result.exit_code == 1
        assert "Server error (401)" in result.output
        assert "failed" not in result.output  # stops at the error, no second verdict

    def test_status_server_error_exits_nonzero(self, runner, monkeypatch):
        monkeypatch.setattr("core.cli.client.NexeClient.get_providers_status",
                            lambda self: {"error": True, "status_code": 0, "message": "offline"})
        result = runner.invoke(self._app(), ["--no-banner", "providers", "status"])
        assert result.exit_code == 1

    def test_client_calls_the_authenticated_admin_paths(self, monkeypatch):
        from core.cli.client import NexeClient
        calls = []
        monkeypatch.setattr(NexeClient, "_request",
                            lambda self, method, endpoint, data=None: calls.append((method, endpoint)) or {})
        client = NexeClient()
        client.get_providers_status()
        client.check_provider("deepseek")
        client.check_provider("../x")
        assert calls == [
            ("GET", "/admin/providers/status"),
            ("POST", "/admin/providers/deepseek/check"),
            ("POST", "/admin/providers/..%2Fx/check"),
        ]


class TestEnvExample:
    def test_variables_declared_empty(self):
        from pathlib import Path
        text = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
        lines = [ln.strip() for ln in text.splitlines()]
        for p in PROVIDERS:
            assert f"{p.env_var}=" in lines  # present and empty
