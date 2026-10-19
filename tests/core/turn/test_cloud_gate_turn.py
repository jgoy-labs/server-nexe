"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/test_cloud_gate_turn.py
Description: API providers, phase 2 — REAL web-door turns (the same lab the
    rest of the turn tests use) against a fake provider. What is pinned is
    Jordi's rule, end to end: the API answers only when it was chosen, the
    global switch is on, the key is configured AND this session consented;
    until then nothing leaves (the fake provider records every request, and a
    refused turn leaves it with none); the API is never a fallback of a local
    engine, nor a local engine a fallback of the API; the key is in nothing
    the user, the session on disk or the logs ever see.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import re
from typing import List
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from core.providers.cloud import ALLOW_CLOUD_ENV
from plugins.api_module.module import ApiModule

FAKE_KEY = "FAKE-KEY-for-tests-7f3a9c1e-not-a-secret"
MODEL = "deepseek-chat"


class Provider:
    """The fake provider: records every request it receives."""

    def __init__(self, status: int = 200, text=("Hola ", "des del núvol")):
        self.status, self.text = status, text
        self.seen: List[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": f"nope {FAKE_KEY}"}})
        if not json.loads(request.content).get("stream"):
            whole = {"choices": [{"message": {"content": "".join(self.text)}, "finish_reason": "stop"}]}
            return httpx.Response(200, json=whole)
        events = [{"choices": [{"delta": {"content": t}, "finish_reason": None}]} for t in self.text]
        events.append({"choices": [{"delta": {"content": ""}, "finish_reason": "stop"}]})
        body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(200, content=body.encode())

    def module(self) -> ApiModule:
        return ApiModule(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def provider() -> Provider:
    return Provider()


@pytest.fixture
def cloud(monkeypatch, app_state, fake_engine, provider):
    """Switch on, key configured, both a local engine and the API loaded."""
    from core import runtime_state
    runtime_state.reset()
    monkeypatch.setenv(ALLOW_CLOUD_ENV, "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app_state.modules = {"ollama_module": fake_engine, "api_module": provider.module()}
    yield
    runtime_state.reset()


def _wire(ctx) -> str:
    return "".join(c for c in ctx.lab_wire_chunks if isinstance(c, str))


def _tag(ctx, name):
    return re.findall(rf"\x00\[{name}:([^\]]*)\]\x00", _wire(ctx))


def _body(**extra):
    return {"backend": "api", "model": MODEL, **extra}


async def _refused(turn_lab, sid, body_extra, streaming=True):
    with pytest.raises(HTTPException) as raised:
        await turn_lab.ui(streaming=streaming, session_id=sid, message="secret message", body_extra=body_extra)
    return raised.value


# ------------------------------------------------------------------- refusals

@pytest.mark.parametrize("streaming", [True, False])
async def test_without_consent_the_turn_is_refused_and_nothing_leaves(turn_lab, cloud, provider, session_manager, streaming):
    err = await _refused(turn_lab, f"cg-nc-{int(streaming)}", _body(), streaming)
    assert err.status_code == 403
    assert err.detail["code"] == "cloud_consent_required"
    assert err.detail["provider"] == "deepseek" and err.detail["provider_name"] == "DeepSeek"
    assert provider.seen == [], "no consent, no request: nothing left the machine"
    # Refused before anything was stored: the retry after the dialog cannot duplicate the message.
    assert session_manager.get_session(f"cg-nc-{int(streaming)}").messages == []


async def test_with_the_switch_off_even_a_consenting_request_is_refused(turn_lab, cloud, provider, monkeypatch):
    monkeypatch.setenv(ALLOW_CLOUD_ENV, "0")
    err = await _refused(turn_lab, "cg-off", _body(cloud_consent="deepseek"))
    assert (err.status_code, err.detail["code"]) == (403, "cloud_engines_disabled")
    assert provider.seen == []


async def test_a_provider_without_a_key_is_refused(turn_lab, cloud, provider, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    err = await _refused(turn_lab, "cg-nokey", _body(cloud_consent="deepseek"))
    assert (err.status_code, err.detail["code"]) == (400, "cloud_provider_not_configured")
    assert provider.seen == []


async def test_the_api_needs_an_explicit_model_the_local_default_is_never_sent_to_a_provider(turn_lab, cloud, provider, monkeypatch):
    monkeypatch.setenv("NEXE_DEFAULT_MODEL", "llama3.2:3b")
    err = await _refused(turn_lab, "cg-nomodel", {"backend": "api", "cloud_consent": "deepseek"})
    assert (err.status_code, err.detail["code"]) == (400, "cloud_model_not_allowed")
    err = await _refused(turn_lab, "cg-localmodel", {"backend": "api", "model": "llama3.2:3b", "cloud_consent": "deepseek"})
    assert err.detail["code"] == "cloud_model_not_allowed"
    assert provider.seen == []


async def test_the_default_local_model_name_is_never_borrowed_even_if_it_names_a_provider_model(turn_lab, cloud, provider, monkeypatch):
    monkeypatch.setenv("NEXE_DEFAULT_MODEL", MODEL)
    err = await _refused(turn_lab, "cg-envmodel", {"backend": "api", "cloud_consent": "deepseek"})
    assert err.detail["code"] == "cloud_model_not_allowed" and provider.seen == []


@pytest.mark.parametrize("spelling", ["API", " api ", "Api"])
async def test_the_engine_name_is_read_the_way_the_cascade_reads_it(turn_lab, cloud, provider, spelling):
    err = await _refused(turn_lab, "cg-spell", {"backend": spelling, "model": MODEL})
    assert err.detail["code"] == "cloud_consent_required", "the gate and the cascade must agree on what 'api' is"
    assert provider.seen == []


async def test_a_consent_for_another_provider_does_not_count(turn_lab, cloud, provider):
    err = await _refused(turn_lab, "cg-other", _body(cloud_consent="openai"))
    assert err.detail["code"] == "cloud_consent_required"
    assert provider.seen == []


async def test_the_engine_step_asks_the_gate_itself_not_only_the_session_step(turn_lab, cloud, provider, app_state,
                                                                             session_manager, server_state):
    """The step that opens the way to a provider must not rely on an earlier one."""
    from core.turn.context import TurnContext
    from plugins.web_ui_module.api.turn_adapters import ui_adapters
    from tests.core.turn.conftest import LAB_PRINCIPAL, make_request

    ctx = TurnContext(turn_id="t", entry="ui", streaming=False, principal=LAB_PRINCIPAL, resume=False,
                      body={"message": "x", **_body()}, request=make_request(app_state), app_state=app_state,
                      model_follows_request=True)
    ctx.session = session_manager.get_or_create_session("cg-engine-only")
    ctx.attachments = {}
    engine_step = ui_adapters(session_manager, streaming=False)["engine"]
    with patch("core.lifespan.get_server_state", return_value=server_state):
        with pytest.raises(HTTPException) as raised:
            await engine_step(ctx)
        assert raised.value.detail["code"] == "cloud_consent_required"
        ctx.body["cloud_consent"] = "deepseek"
        await engine_step(ctx)
    assert [name for name, _ in ctx.usage["ui"]["candidates"]] == ["api"], "alone: no local engine behind it"
    assert ctx.usage["ui"]["engine_name"] == "api"
    assert provider.seen == []


# ----------------------------------------------------------------- the happy turn

@pytest.mark.parametrize("streaming", [True, False])
async def test_a_consented_turn_is_answered_by_the_provider_and_says_so(turn_lab, cloud, provider, session_manager, streaming):
    sid = f"cg-ok-{int(streaming)}"
    ctx = await turn_lab.ui(streaming=streaming, session_id=sid, message="hola", body_extra=_body(cloud_consent="deepseek"))
    assert len(provider.seen) >= 1
    sent = json.loads(provider.seen[0].content)
    assert sent["model"] == MODEL and [m["role"] for m in sent["messages"]][0] == "system"
    assert sent["messages"][-1]["role"] == "user" and "hola" in sent["messages"][-1]["content"]
    assert provider.seen[0].headers["authorization"] == f"Bearer {FAKE_KEY}"
    assistant = [m for m in session_manager.get_session(sid).messages if m["role"] == "assistant"][-1]
    assert assistant["content"].strip() == "Hola des del núvol"
    # The footer: «API · model», live (the two sentinels) and saved (stats).
    assert assistant["stats"]["engine"] == "api" and assistant["stats"]["model"] == MODEL
    if streaming:
        assert _tag(ctx, "ENGINE") == ["api"] and _tag(ctx, "MODEL")[-1] == MODEL
        assert "Hola des del núvol" in _wire(ctx)
    else:
        assert ctx.response.strip() == "Hola des del núvol"


async def test_the_consent_lives_in_the_session_the_next_turn_needs_not_send_it_again(turn_lab, cloud, provider, session_manager):
    await turn_lab.ui(streaming=True, session_id="cg-sess", message="u1", body_extra=_body(cloud_consent="deepseek"))
    assert session_manager.get_session("cg-sess").cloud_consent == "deepseek"
    before = len(provider.seen)
    ctx = await turn_lab.ui(streaming=True, session_id="cg-sess", message="u2", body_extra=_body())
    assert len(provider.seen) > before and _tag(ctx, "ENGINE") == ["api"]


async def test_the_consent_is_per_session_another_conversation_is_asked_again(turn_lab, cloud, provider):
    await turn_lab.ui(streaming=True, session_id="cg-a", message="u1", body_extra=_body(cloud_consent="deepseek"))
    sent = len(provider.seen)
    err = await _refused(turn_lab, "cg-b", _body())
    assert err.detail["code"] == "cloud_consent_required" and len(provider.seen) == sent


async def test_the_consent_is_never_written_to_disk(turn_lab, cloud, session_manager, tmp_path):
    await turn_lab.ui(streaming=False, session_id="cg-disk", message="u1", body_extra=_body(cloud_consent="deepseek"))
    session = session_manager.get_session("cg-disk")
    assert "cloud_consent" not in session.to_dict()
    reloaded = type(session).from_dict(session.to_dict())
    assert reloaded.cloud_consent is None, "a reload asks again"


async def test_a_session_file_cannot_grant_consent(session_manager):
    from core.sessions.session_manager import ChatSession
    forged = ChatSession.from_dict({"id": "cg-forged", "cloud_consent": "deepseek", "messages": []})
    assert forged.cloud_consent is None


async def test_going_through_a_local_engine_takes_the_consent_away(turn_lab, cloud, provider, fake_engine, session_manager):
    await turn_lab.ui(streaming=True, session_id="cg-lose", message="u1", body_extra=_body(cloud_consent="deepseek"))
    sent = len(provider.seen)
    local = await turn_lab.ui(streaming=True, session_id="cg-lose", message="u2",
                              body_extra={"backend": "ollama", "model": "llama3.2:3b"})
    assert _tag(local, "ENGINE") == ["ollama"] and len(provider.seen) == sent
    assert session_manager.get_session("cg-lose").cloud_consent is None
    err = await _refused(turn_lab, "cg-lose", _body())
    assert err.detail["code"] == "cloud_consent_required", "back to the API: the dialog again"


# ----------------------------------------------- never a fallback, in either direction

async def test_a_local_turn_never_touches_the_provider_even_with_everything_open(turn_lab, cloud, provider, fake_engine):
    ctx = await turn_lab.ui(streaming=True, session_id="cg-local", message="hola",
                            body_extra={"backend": "ollama", "model": "llama3.2:3b", "cloud_consent": "deepseek"})
    assert fake_engine.calls > 0 and _tag(ctx, "ENGINE") == ["ollama"]
    assert provider.seen == []


async def test_a_turn_without_backend_follows_the_local_default_never_the_api(turn_lab, cloud, provider, fake_engine):
    ctx = await turn_lab.ui(streaming=True, session_id="cg-default", message="hola",
                            body_extra={"model": "llama3.2:3b", "cloud_consent": "deepseek"})
    assert _tag(ctx, "ENGINE") == ["ollama"] and provider.seen == []


async def test_when_the_local_engine_fails_the_api_does_not_answer_in_its_place(turn_lab, cloud, provider, app_state):
    class Broken:
        async def chat(self, model, messages, stream=True, images=None, thinking_enabled=False, **_):
            raise RuntimeError("the local model crashed")
            yield  # pragma: no cover

    app_state.modules = {"ollama_module": Broken(), "api_module": provider.module()}
    ctx = await turn_lab.ui(streaming=True, session_id="cg-nofallback", message="hola",
                            body_extra={"backend": "ollama", "model": "llama3.2:3b", "cloud_consent": "deepseek"})
    assert provider.seen == [], "a failing local engine must not send the conversation to the cloud"
    assert "Hola des del núvol" not in _wire(ctx)


async def test_when_the_provider_fails_a_local_engine_does_not_answer_in_its_place(turn_lab, cloud, app_state, fake_engine):
    failing = Provider(status=500)
    app_state.modules = {"ollama_module": fake_engine, "api_module": failing.module()}
    ctx = await turn_lab.ui(streaming=True, session_id="cg-nolocal", message="hola",
                            body_extra=_body(cloud_consent="deepseek"))
    assert fake_engine.calls == 0, "the user asked for the provider: a local model answering would be another answer"
    assert failing.seen and "DeepSeek" in _wire(ctx)


async def test_an_unloaded_api_module_is_a_503_not_a_local_answer(turn_lab, cloud, app_state, fake_engine):
    app_state.modules = {"ollama_module": fake_engine}
    err = await _refused(turn_lab, "cg-noapimodule", _body(cloud_consent="deepseek"))
    assert err.status_code == 503 and fake_engine.calls == 0


# ------------------------------------------------------ failures, curated, no key

async def test_a_refused_key_reaches_the_user_as_the_curated_text(turn_lab, cloud, app_state, fake_engine, session_manager):
    refused = Provider(status=401)
    app_state.modules = {"ollama_module": fake_engine, "api_module": refused.module()}
    ctx = await turn_lab.ui(streaming=True, session_id="cg-401", message="hola", body_extra=_body(cloud_consent="deepseek"))
    wire = _wire(ctx)
    assert "DeepSeek" in wire and ".env" in wire
    assert FAKE_KEY not in wire


async def test_a_refused_key_on_the_json_door_is_a_502_with_curated_text(turn_lab, cloud, app_state, fake_engine):
    refused = Provider(status=403)
    app_state.modules = {"ollama_module": fake_engine, "api_module": refused.module()}
    err = await _refused(turn_lab, "cg-403", _body(cloud_consent="deepseek"), streaming=False)
    assert err.status_code == 502 and "DeepSeek" in err.detail and FAKE_KEY not in err.detail


async def test_the_key_is_in_nothing_the_turn_leaves_behind(turn_lab, cloud, session_manager, caplog, tmp_path):
    caplog.set_level(logging.DEBUG)
    ctx = await turn_lab.ui(streaming=True, session_id="cg-key", message="hola", body_extra=_body(cloud_consent="deepseek"))
    session = session_manager.get_session("cg-key")
    haystacks = [_wire(ctx), json.dumps(session.to_dict()), caplog.text, repr(ctx.usage.get("llm")),
                 json.dumps(ctx.usage.get("ui", {}).get("model_name")), repr(session_manager.__dict__)]
    assert caplog.records, "nothing was logged: the assertion would prove nothing"
    assert all(FAKE_KEY not in h for h in haystacks)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert FAKE_KEY not in path.read_text(errors="ignore"), path


# ---------------------------------------------------------- the turn's own steps

async def test_the_api_turn_is_recorded_under_its_own_engine_name(turn_lab, cloud, provider):
    ctx = await turn_lab.ui(streaming=False, session_id="cg-metric", message="hola", body_extra=_body(cloud_consent="deepseek"))
    calls = ctx.usage["llm"]["calls"]
    assert calls and {c["engine"] for c in calls} == {"api"}
    assert {c["model"] for c in calls} == {MODEL}


async def test_continue_is_refused_for_the_api_instead_of_starting_a_new_answer(turn_lab, cloud, provider):
    await turn_lab.ui(streaming=False, session_id="cg-cont", message="hola", body_extra=_body(cloud_consent="deepseek"))
    sent = len(provider.seen)
    with pytest.raises(HTTPException) as raised:
        await turn_lab.ui(streaming=False, session_id="cg-cont", message="",
                          body_extra={**_body(), "continue": True})
    assert raised.value.status_code == 400 and len(provider.seen) == sent
