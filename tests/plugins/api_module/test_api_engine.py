"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/api_module/test_api_engine.py
Description: The API engine against a fake provider (httpx.MockTransport):
    no network, a key that is obviously fake. What is pinned: the request
    that leaves (path, header, body), the stream read back in the shape the
    turn already understands, the reasoning mapped to `thinking`, every
    failure mapped to a curated error, and — the recurring one — that the key
    appears in nothing the server says or logs.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import base64
import inspect
import json
import logging
from typing import List

import httpx
import pytest
from fastapi import HTTPException

import core.endpoints.chat  # noqa: F401  (breaks a circular import when this file runs alone)
from core.turn.stream import Delta, Failed, Ready, StreamFlags, engine_events
from plugins.api_module.errors import ApiAuthError, ApiProviderError
from plugins.api_module.module import ApiModule

FAKE_KEY = "FAKE-KEY-for-tests-7f3a9c1e-not-a-secret"
PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16).decode()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("NEXE_ALLOW_CLOUD_ENGINES", "1")  # the module re-reads the switch at every request
    monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def _sse(*events, done: bool = True, comment: bool = False) -> bytes:
    lines = [": keep-alive\n\n"] if comment else []
    lines += [f"data: {json.dumps(e)}\n\n" for e in events]
    if done:
        lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


def _delta(content="", reasoning=None, finish=None):
    delta = {"content": content}
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    return {"choices": [{"delta": delta, "finish_reason": finish}]}


_NOTE = "Where you run in THIS conversation"


def _sent(body):
    """The request's messages as the caller wrote them: the closing note that
    says where the answer is produced (`where_you_run`) is taken off, and a
    system message that is only that note is dropped. Its own tests are in
    test_where_you_run.py."""
    out = []
    for m in body["messages"]:
        c = m["content"]
        if m["role"] == "system" and isinstance(c, str) and _NOTE in c:
            c = c.split("\n\n" + _NOTE)[0] if not c.startswith(_NOTE) else ""
            if not c:
                continue
            m = {**m, "content": c}
        out.append(m)
    return out


def _module(handler, seen: List[httpx.Request] | None = None) -> ApiModule:
    def wrapped(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return handler(request)
    return ApiModule(transport=httpx.MockTransport(wrapped))


def _stream_ok(*events, **kw):
    return lambda request: httpx.Response(200, content=_sse(*events, **kw),
                                          headers={"content-type": "text/event-stream"})


async def _drain(module, model="deepseek-chat", **kwargs):
    kwargs.setdefault("messages", [{"role": "user", "content": "hola"}])
    return [c async for c in module.chat(model=model, **kwargs)]


# ----------------------------------------------------------------- the request

async def test_the_request_goes_to_the_declared_chat_path_with_one_bearer_header():
    seen: List[httpx.Request] = []
    module = _module(_stream_ok(_delta("Hola", finish="stop")), seen)
    await _drain(module, stream=True)
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.deepseek.com/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
    body = json.loads(request.content)
    assert body["model"] == "deepseek-chat" and body["stream"] is True
    assert _sent(body) == [{"role": "user", "content": "hola"}]
    assert "max_tokens" not in body and "top_p" not in body


async def test_top_p_is_sent_only_when_given():
    seen: List[httpx.Request] = []
    module = _module(_stream_ok(_delta("x", finish="stop")), seen)
    await _drain(module, top_p=0.5)
    assert json.loads(seen[0].content)["top_p"] == 0.5


async def test_only_role_and_text_leave_the_server():
    seen: List[httpx.Request] = []
    module = _module(_stream_ok(_delta("x", finish="stop")), seen)
    await _drain(module, messages=[
        {"role": "system", "content": "s", "image_b64": "SECRET-IMAGE", "stats": {"a": 1}},
        {"role": "user", "content": "u", "timestamp": "now"},
    ])
    assert _sent(json.loads(seen[0].content)) == [
        {"role": "system", "content": "s"}, {"role": "user", "content": "u"},
    ]


async def test_a_vision_model_gets_the_image_as_a_content_part_with_its_real_mime(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    seen: List[httpx.Request] = []
    module = _module(_stream_ok(_delta("x", finish="stop")), seen)
    await _drain(module, model="gpt-4o", images=[PNG_B64],
                 messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "què veus?"}])
    assert str(seen[0].url) == "https://api.openai.com/v1/chat/completions"
    last = json.loads(seen[0].content)["messages"][-1]["content"]
    assert last[0] == {"type": "text", "text": "què veus?"}
    assert last[1] == {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG_B64}"}}


async def test_an_image_sent_to_a_model_that_cannot_see_is_refused_before_any_request():
    seen: List[httpx.Request] = []
    module = _module(_stream_ok(_delta("x", finish="stop")), seen)
    with pytest.raises(ValueError, match="cannot read images"):
        await _drain(module, model="deepseek-chat", images=[PNG_B64])
    assert seen == []


@pytest.mark.parametrize("model", ["", "llama3.2:3b", "claude-3", None])
async def test_a_model_no_provider_owns_makes_no_request(model):
    seen: List[httpx.Request] = []
    module = _module(_stream_ok(), seen)
    with pytest.raises(ValueError):
        await _drain(module, model=model)
    assert seen == []


async def test_no_key_no_request():
    import os
    os.environ.pop("DEEPSEEK_API_KEY")
    seen: List[httpx.Request] = []
    module = _module(_stream_ok(), seen)
    with pytest.raises(ValueError, match="no key configured"):
        await _drain(module)
    assert seen == []


async def test_a_key_that_cannot_be_a_header_makes_no_request_and_is_not_in_the_error(monkeypatch):
    bad = "clau amb espai i accent é"
    monkeypatch.setenv("DEEPSEEK_API_KEY", bad)
    seen: List[httpx.Request] = []
    module = _module(_stream_ok(), seen)
    with pytest.raises(ValueError) as exc:
        await _drain(module)
    assert seen == [] and bad not in str(exc.value)


# ------------------------------------------------------------ SSE -> turn events

async def test_the_stream_arrives_as_the_chunks_engine_events_understands():
    module = _module(_stream_ok(_delta("Hola"), _delta(" món"), _delta("", finish="stop"), comment=True))
    flags = StreamFlags()
    events = [e async for e in engine_events(module.chat(model="deepseek-chat", messages=[{"role": "user", "content": "x"}]),
                                             "deepseek-chat", flags)]
    assert isinstance(events[0], Ready)
    assert "".join(e.full for e in events if isinstance(e, Delta)) == "Hola món"
    assert not any(isinstance(e, Failed) for e in events)
    assert flags.trunc is False and flags.error is None


async def test_reasoning_content_is_the_thinking_channel_not_the_answer():
    module = _module(_stream_ok(_delta("", reasoning="Pensant..."), _delta("Resposta", finish="stop")))
    chunks = await _drain(module, model="deepseek-reasoner")
    assert chunks[0]["message"]["thinking"] == "Pensant..." and chunks[0]["message"]["content"] == ""
    flags = StreamFlags()
    module = _module(_stream_ok(_delta("", reasoning="Pensant..."), _delta("Resposta", finish="stop")))
    events = [e async for e in engine_events(module.chat(model="deepseek-reasoner", messages=[]), "deepseek-reasoner", flags)]
    # The same shape every engine's reasoning takes on the wire: a think block, then the answer.
    assert "".join(w for e in events if isinstance(e, Delta) for w in e.wire) == "<think>Pensant...</think>Resposta"
    assert flags.has_any_thinking is True


async def test_a_reply_cut_by_the_provider_is_flagged_truncated_and_not_continuable():
    module = _module(_stream_ok(_delta("Tall"), _delta("", finish="length")))
    flags = StreamFlags()
    events = [e async for e in engine_events(module.chat(model="deepseek-chat", messages=[]), "deepseek-chat", flags)]
    assert flags.trunc is True and flags.trunc_continuable is False
    assert "".join(e.full for e in events if isinstance(e, Delta)) == "Tall"


async def test_a_non_streaming_request_yields_one_final_chunk():
    reply = {"choices": [{"message": {"content": "Sencera", "reasoning_content": "Raó"}, "finish_reason": "stop"}]}
    seen: List[httpx.Request] = []
    module = _module(lambda r: httpx.Response(200, json=reply), seen)
    chunks = await _drain(module, stream=False)
    assert json.loads(seen[0].content)["stream"] is False
    assert len(chunks) == 1 and chunks[0]["done"] is True
    assert chunks[0]["message"]["content"] == "Sencera" and chunks[0]["message"]["thinking"] == "Raó"
    assert chunks[0]["done_reason"] == "stop"


async def test_garbage_and_empty_events_are_skipped():
    body = b"data: not json\n\ndata: {\"choices\": []}\n\ndata: [1,2]\n\n" + _sse(_delta("ok", finish="stop"))
    module = _module(lambda r: httpx.Response(200, content=body))
    chunks = await _drain(module)
    assert "".join(c["message"]["content"] for c in chunks) == "ok"


async def test_an_error_event_inside_the_stream_is_a_curated_provider_error():
    module = _module(_stream_ok({"error": {"message": f"boom {FAKE_KEY}"}}, done=False))
    with pytest.raises(ApiProviderError) as exc:
        await _drain(module)
    assert FAKE_KEY not in str(exc.value) and FAKE_KEY not in exc.value.curated_text("en")


# -------------------------------------------------------------- errors, curated

@pytest.mark.parametrize("status", [401, 403])
async def test_a_refused_key_is_terminal_as_a_502_with_curated_text_and_no_key(status):
    # The provider's body even echoes the key: it must not travel anywhere.
    module = _module(lambda r: httpx.Response(status, json={"error": {"message": f"bad key {FAKE_KEY}"}}))
    with pytest.raises(ApiAuthError) as exc:
        await _drain(module)
    err = exc.value
    assert isinstance(err, HTTPException) and err.status_code == 502, "502, never 401: a 401 logs the user out of the UI"
    assert FAKE_KEY not in err.detail and FAKE_KEY not in str(err) and FAKE_KEY not in repr(err)
    assert ".env" in err.curated_text("ca") and ".env" in err.curated_text("es") and ".env" in err.curated_text("en")
    from core.endpoints.chat_engines.routing import raise_if_terminal
    with pytest.raises(HTTPException) as terminal:
        raise_if_terminal(err, "api", lang="ca")
    # terminal: the cascade does not move on; its status, and its own sentence in the turn's language
    assert terminal.value.status_code == 502 and terminal.value.__cause__ is err
    assert terminal.value.detail == err.curated_text("ca") and FAKE_KEY not in terminal.value.detail


@pytest.mark.parametrize("status,needle", [(402, "balance"), (429, "rate limiting"), (500, "not available"),
                                           (503, "not available"), (400, "rejected the request")])
async def test_limits_balance_and_5xx_are_provider_errors_the_cascade_may_report(status, needle):
    module = _module(lambda r: httpx.Response(status, text=f"body with {FAKE_KEY}"))
    with pytest.raises(ApiProviderError) as exc:
        await _drain(module)
    err = exc.value
    assert err.upstream_status == status and needle in err.curated_text("en")
    assert FAKE_KEY not in str(err) and FAKE_KEY not in err.curated_text("en")
    from core.endpoints.chat_engines.routing import should_try_next_engine
    assert should_try_next_engine(err) is True


async def test_a_timeout_is_an_engine_down_with_a_curated_text():
    """N5: too slow is the engine down; the API has no engine behind it, so the
    turn ends as a cascade with nobody left — a 503 with this sentence."""
    def slow(request):
        raise httpx.ReadTimeout(f"timed out talking with {FAKE_KEY}", request=request)
    with pytest.raises(TimeoutError) as exc:
        await _drain(_module(slow))
    assert FAKE_KEY not in str(exc.value) and exc.value.__cause__ is None and exc.value.__suppress_context__
    from core.endpoints.chat_engines.routing import engine_error_to_http, should_try_next_engine
    assert should_try_next_engine(exc.value) is True and engine_error_to_http(exc.value, "api") is None
    assert "DeepSeek" in exc.value.curated_text("ca") and FAKE_KEY not in exc.value.curated_text("en")


async def test_an_unreachable_provider_is_an_engine_down_without_the_cause():
    def down(request):
        raise httpx.ConnectError(f"cannot connect {FAKE_KEY}", request=request)
    with pytest.raises(ConnectionError) as exc:
        await _drain(_module(down))
    assert FAKE_KEY not in str(exc.value) and exc.value.__suppress_context__
    from core.endpoints.chat_engines.routing import engine_error_to_http, should_try_next_engine
    assert should_try_next_engine(exc.value) is True and engine_error_to_http(exc.value, "api") is None
    assert "DeepSeek" in exc.value.curated_text("es") and FAKE_KEY not in exc.value.curated_text("en")


async def test_a_non_json_whole_reply_is_a_provider_error():
    module = _module(lambda r: httpx.Response(200, text="<html>nope</html>"))
    with pytest.raises(ApiProviderError):
        await _drain(module, stream=False)


async def test_a_whole_reply_without_choices_is_a_provider_error():
    module = _module(lambda r: httpx.Response(200, json={"choices": []}))
    with pytest.raises(ApiProviderError):
        await _drain(module, stream=False)


async def test_redirects_are_not_followed_so_the_key_never_reaches_another_host():
    seen: List[httpx.Request] = []

    def handler(request):
        if request.url.host == "api.deepseek.com":
            return httpx.Response(307, headers={"location": "https://evil.example/steal"})
        raise AssertionError("the redirect was followed")
    with pytest.raises(ApiProviderError):
        await _drain(_module(handler, seen))
    assert [r.url.host for r in seen] == ["api.deepseek.com"]


async def test_the_failure_reaches_the_user_as_the_curated_text_through_the_turns_own_path():
    from core.turn.errors import curated_error_text
    module = _module(lambda r: httpx.Response(401, json={}))
    flags = StreamFlags()
    events = [e async for e in engine_events(module.chat(model="deepseek-chat", messages=[]), "deepseek-chat", flags)]
    failed = events[-1]
    assert isinstance(failed, Failed)
    text = curated_error_text(failed.exc, "ca")
    assert "DeepSeek" in text and ".env" in text and FAKE_KEY not in text


async def test_the_key_is_in_no_log_record_whatever_happens(caplog):
    caplog.set_level(logging.DEBUG)
    for handler in (lambda r: httpx.Response(401, json={"k": FAKE_KEY}),
                    lambda r: httpx.Response(500, text=FAKE_KEY),
                    _stream_ok(_delta("ok", finish="stop"))):
        try:
            await _drain(_module(handler))
        except Exception:  # noqa: BLE001 — only the logs matter here
            pass
    assert caplog.records, "the run logged nothing: the assertion below would prove nothing"
    assert FAKE_KEY not in caplog.text
    assert all(FAKE_KEY not in str(r.args) and FAKE_KEY not in r.getMessage() for r in caplog.records)


async def test_the_module_holds_no_key_and_does_not_show_one(monkeypatch):
    module = _module(_stream_ok(_delta("ok", finish="stop")))
    await _drain(module)
    assert FAKE_KEY not in repr(module) and FAKE_KEY not in repr(vars(module))
    health = await module.health_check()
    assert FAKE_KEY not in json.dumps(health.to_dict())
    assert health.details["configured_providers"] == ["deepseek"]


async def test_cancelling_the_consumer_closes_the_stream_without_error():
    import asyncio

    def endless(request):
        return httpx.Response(200, content=_sse(*[_delta("x") for _ in range(50)], done=False))
    gen = _module(endless).chat(model="deepseek-chat", messages=[])
    first = await gen.__anext__()
    assert first["message"]["content"] == "x"
    await gen.aclose()  # a client disconnect: close, no exception
    task = asyncio.ensure_future(_drain(_module(endless)))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ------------------------------------------------ contract with the rest of the server

def test_chat_has_the_ollama_style_signature_the_turn_looks_for():
    params = inspect.signature(ApiModule.chat).parameters
    assert "model" in params and "messages" in params
    assert {"stream", "images", "thinking_enabled", "top_p"} <= set(params)
    # no resume, no loaded-model probe: a provider can do neither
    assert not hasattr(ApiModule, "can_continue") and not hasattr(ApiModule, "is_model_loaded")
    assert "continue_final" not in params


def test_sight_and_window_follow_the_model_they_are_asked_for(monkeypatch):
    module = ApiModule()
    assert module.can_see_images() is False and module.get_context_window() is None
    assert module.can_see_images("deepseek-chat") is False and module.get_context_window("deepseek-chat") == 64000
    assert module.can_see_images("gpt-4o") is True and module.get_context_window("gpt-4o") == 128000
    assert module.can_see_images("gpt-3.5-turbo") is False
    assert module.can_see_images("llama3.2:3b") is False and module.get_context_window("llama3.2:3b") is None


def test_the_module_holds_no_model_so_one_turn_cannot_read_anothers():
    """Phase 2 remembered the turn's model on the module (shared state). Phase 3: each turn is handed a view
    bound to its own model, and the module itself answers for nobody in particular."""
    module = ApiModule()
    small, big = module.for_model("deepseek-chat"), module.for_model("gpt-4o")
    assert (small.get_context_window(), small.can_see_images()) == (64000, False)
    assert (big.get_context_window(), big.can_see_images()) == (128000, True)
    assert (small.model_in_use, big.model_in_use) == ("deepseek-chat", "gpt-4o")
    # the later view did not change the earlier one, and the module answers for no model
    assert small.get_context_window() == 64000
    assert (module.get_context_window(), module.can_see_images()) == (None, False)
    assert not hasattr(module, "select_model") and not hasattr(module, "model_in_use")
    assert not any(isinstance(v, str) and v in ("deepseek-chat", "gpt-4o") for v in vars(module).values())


def test_a_turns_view_declares_what_the_core_reads_off_an_engine():
    from core.endpoints.chat_engines.routing import engine_is_cloud, engine_takes_model
    view = ApiModule().for_model("gpt-4o")
    assert engine_takes_model(view) is True and engine_is_cloud(view) is True
    assert engine_is_cloud(ApiModule()) is True
    params = inspect.signature(view.chat).parameters
    assert list(params) == list(inspect.signature(ApiModule.chat).parameters)[1:], "same signature: the core reads it"
    assert "cancel_event" in params and not hasattr(view, "can_continue") and not hasattr(view, "is_model_loaded")


def test_the_core_asks_the_window_and_the_sight_through_the_existing_contract():
    from core.context_window import ask_engine_window
    from core.endpoints.chat_engines.routing import engine_can_see_images
    view = ApiModule().for_model("gpt-4o")
    assert ask_engine_window(view) == 128000
    assert engine_can_see_images(view) is True


async def test_switch_engine_model_swaps_nothing_and_never_looks_for_a_local_path(monkeypatch):
    """A hosted engine loads nothing: the requested name is the model, and no models directory is resolved."""
    from core.endpoints.chat_engines import model_switch

    def boom(_name):
        raise AssertionError("a hosted model has no path under the models directory")

    monkeypatch.setattr(model_switch, "resolve_local_model_path", boom)
    view = ApiModule().for_model("deepseek-reasoner")
    assert await model_switch.switch_engine_model(view, "api", "deepseek-reasoner") is False


def test_start_engine_call_uses_the_ollama_style_for_this_engine():
    from core.turn.engine_start import start_engine_call
    seen = {}

    class Spy(ApiModule):
        def chat(self, model, messages, stream=True, images=None, thinking_enabled=False, top_p=None,
                 cancel_event=None):
            seen.update(model=model, messages=messages, stream=stream, cancel_event=cancel_event)
            return super().chat(model, messages, stream, images, thinking_enabled, top_p, cancel_event)

    engine = Spy()
    result = start_engine_call(engine, "api", inspect.signature(engine.chat), "deepseek-chat", "SYS",
                               [{"role": "user", "content": "u"}], stream=True, image_b64=None,
                               thinking_enabled=False, cancel_event=None, sampling_kwargs={},
                               session_id="s", _continue=False)
    assert inspect.isasyncgen(result)
    assert seen["model"] == "deepseek-chat" and seen["messages"][0] == {"role": "system", "content": "SYS"}


# ------------------------------------------------------------ how it is loaded

async def test_the_lazy_manifest_hands_out_one_module_the_loader_can_initialise():
    from plugins.api_module import manifest
    manifest._module = None  # the manifest wrapper allows a reset, as every plugin's does
    instance = manifest.get_module_instance()
    assert isinstance(instance, ApiModule) and manifest.get_module_instance() is instance
    assert instance.metadata.name == "api_module" and instance.metadata.module_type == "cloud_llm_option"
    assert manifest.get_router() is not None and instance.get_router().routes == []
    assert await instance.initialize({}) is True
    await instance.shutdown()


def test_the_plugin_pulls_no_core_at_import_time():
    """The layering gate's rule, checked on this package directly: every `core`
    import in it sits inside a function."""
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[3] / "plugins" / "api_module"
    offenders = []
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    break
            else:
                if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in {"core", "memory"}:
                    offenders.append(f"{path.name}:{node.lineno}")
                if isinstance(node, ast.Import) and any(a.name.split(".")[0] in {"core", "memory"} for a in node.names):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


async def test_every_request_is_counted_under_its_provider_and_outcome():
    from core.metrics.registry import API_ENGINE_REQUESTS

    def value(status):
        return API_ENGINE_REQUESTS.labels(provider="deepseek", status=status)._value.get()

    ok0, err0 = value("ok"), value("error")
    await _drain(_module(_stream_ok(_delta("x", finish="stop"))))
    assert (value("ok"), value("error")) == (ok0 + 1, err0)
    with pytest.raises(ApiProviderError):
        await _drain(_module(lambda r: httpx.Response(500)))
    assert (value("ok"), value("error")) == (ok0 + 1, err0 + 1)


# ------------------------------------------------------------- edges of the client

def test_only_2xx_is_success_and_the_edges_are_exact():
    from plugins.api_module.chat import raise_for_status
    for ok in (200, 204, 299):
        raise_for_status(ok, "X")
    for bad in (199, 300, 302):
        with pytest.raises(ApiProviderError):
            raise_for_status(bad, "X")


def test_the_read_timeout_follows_the_env_and_never_goes_below_a_sane_default(monkeypatch):
    from plugins.api_module.chat import DEFAULT_TIMEOUT_SECONDS, request_timeout
    monkeypatch.setenv("NEXE_API_TIMEOUT", "42")
    assert request_timeout().read == 42.0
    for bad in ("0", "-5", "soon", ""):
        monkeypatch.setenv("NEXE_API_TIMEOUT", bad)
        assert request_timeout().read == DEFAULT_TIMEOUT_SECONDS, bad


async def test_the_image_goes_on_the_last_user_message_not_the_first():
    seen: List[httpx.Request] = []
    module = _module(_stream_ok(_delta("x", finish="stop")), seen)
    import os
    os.environ["OPENAI_API_KEY"] = FAKE_KEY
    try:
        await _drain(module, model="gpt-4o", images=[PNG_B64], messages=[
            {"role": "user", "content": "primer"}, {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "segon"},
        ])
    finally:
        os.environ.pop("OPENAI_API_KEY")
    sent = _sent(json.loads(seen[0].content))
    assert sent[0]["content"] == "primer" and isinstance(sent[2]["content"], list)


async def test_the_accept_header_follows_the_mode():
    seen: List[httpx.Request] = []
    await _drain(_module(_stream_ok(_delta("x", finish="stop")), seen), stream=True)
    assert seen[0].headers["accept"] == "text/event-stream"
    whole = {"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}]}
    await _drain(_module(lambda r: httpx.Response(200, json=whole), seen), stream=False)
    assert seen[1].headers["accept"] == "application/json"


async def test_nothing_after_done_is_read():
    body = _sse(_delta("abans", finish=None)) + _sse(_delta("DESPRÉS", finish="stop"), done=False)
    chunks = await _drain(_module(lambda r: httpx.Response(200, content=body)))
    assert "".join(c["message"]["content"] for c in chunks) == "abans"


async def test_a_whole_reply_that_is_an_error_object_is_a_provider_error():
    module = _module(lambda r: httpx.Response(200, json={"error": {"message": "x"}, "choices": [
        {"message": {"content": "looks fine"}, "finish_reason": "stop"}]}))
    with pytest.raises(ApiProviderError):
        await _drain(module, stream=False)


async def test_the_url_is_joined_without_a_double_slash():
    from types import SimpleNamespace
    from plugins.api_module.chat import run_chat
    seen: List[httpx.Request] = []
    provider = SimpleNamespace(endpoint="https://x.example/", chat_path="/v1/chat/completions", name="X", key="x")
    transport = httpx.MockTransport(lambda r: (seen.append(r), httpx.Response(200, content=_sse(_delta("a", finish="stop"))))[1])
    async for _ in run_chat(provider, FAKE_KEY, "m", [], True, None, None, transport):
        pass
    assert str(seen[0].url) == "https://x.example/v1/chat/completions"


def test_the_curated_text_defaults_to_catalan_and_follows_the_language():
    assert "clau" in ApiAuthError("DeepSeek", 401).curated_text(None)
    assert "key" in ApiAuthError("DeepSeek", 401).curated_text("en")
    assert "clave" in ApiAuthError("DeepSeek", 401).curated_text("es")
    assert "saldo" in ApiProviderError("DeepSeek", 402).curated_text("ca")
    assert ApiProviderError("DeepSeek", 429).curated_text(None).startswith("DeepSeek ha limitat")


def test_the_read_timeout_refuses_nan_and_inf(monkeypatch):
    from plugins.api_module.chat import DEFAULT_TIMEOUT_SECONDS, request_timeout
    for bad in ("nan", "inf", "-inf"):
        monkeypatch.setenv("NEXE_API_TIMEOUT", bad)
        assert request_timeout().read == DEFAULT_TIMEOUT_SECONDS, bad


async def test_a_message_without_text_is_empty_not_the_word_none():
    seen: List[httpx.Request] = []
    await _drain(_module(_stream_ok(_delta("x", finish="stop")), seen),
                 messages=[{"role": "user", "content": None}, {"role": "user", "content": 7}])
    assert [m["content"] for m in _sent(json.loads(seen[0].content))] == ["", "7"]


async def test_a_consumer_that_closes_early_is_not_counted_as_an_error():
    from core.metrics.registry import API_ENGINE_REQUESTS

    def value(status):
        return API_ENGINE_REQUESTS.labels(provider="deepseek", status=status)._value.get()

    err0 = value("error")
    gen = _module(lambda r: httpx.Response(200, content=_sse(*[_delta("x") for _ in range(5)], done=False))).chat(
        model="deepseek-chat", messages=[])
    await gen.__anext__()
    await gen.aclose()
    assert value("error") == err0


# --------------------------------------- the turn's internal steps on this engine

async def test_compaction_asks_the_selected_model_with_the_ollama_style_call_not_the_local_default(monkeypatch):
    from core.sessions import compactor
    monkeypatch.setenv("NEXE_DEFAULT_MODEL", "llama3.2:3b")
    seen: List[httpx.Request] = []
    whole = {"choices": [{"message": {"content": "Resum de la conversa"}, "finish_reason": "stop"}]}
    module = _module(lambda r: httpx.Response(200, json=whole), seen)  # compaction asks for a whole reply
    module = module.for_model("deepseek-chat")
    assert compactor._is_ollama_engine(module) is True
    summary = await compactor._call_engine(module, [{"role": "user", "content": "resumeix"}], "SYS")
    assert summary == "Resum de la conversa"
    body = json.loads(seen[0].content)
    assert body["model"] == "deepseek-chat", "the local default name must never be sent to a provider"
    assert _sent(body)[0] == {"role": "system", "content": "SYS"}


async def test_compaction_still_calls_an_in_process_engine_with_system():
    from core.sessions import compactor

    class InProcess:
        async def chat(self, messages, system=None, **_):
            return {"response": f"{system}|{messages[0]['content']}"}

    assert compactor._is_ollama_engine(InProcess()) is False
    assert await compactor._call_engine(InProcess(), [{"role": "user", "content": "u"}], "S") == "S|u"


async def test_image_description_goes_through_the_ollama_style_call_for_a_vision_model(monkeypatch):
    from core.turn import image_memory
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    seen: List[httpx.Request] = []
    module = _module(_stream_ok(_delta("Un quadrat blau", finish="stop")), seen)
    module = module.for_model("gpt-4o")
    text = await image_memory.describe(module, "gpt-4o", PNG_B64, "ca")
    assert "quadrat blau" in text
    body = json.loads(seen[0].content)
    assert body["model"] == "gpt-4o" and body["messages"][-1]["content"][1]["type"] == "image_url"


async def test_image_description_is_not_asked_of_a_model_that_cannot_see():
    from core.turn import image_memory
    seen: List[httpx.Request] = []
    module = _module(_stream_ok(_delta("inventat", finish="stop")), seen)
    module = module.for_model("deepseek-chat")
    assert await image_memory.describe(module, "deepseek-chat", PNG_B64, "ca") == ""
    assert seen == []


# ---------------------------------------- the switch is read at the moment of every request

async def test_the_global_switch_is_read_at_every_request_not_once_per_turn(monkeypatch):
    """Turning "Allow cloud engines" off stops the NEXT call of a turn that is already running (its compaction,
    its image description, its re-prompt), not only the next turn."""
    seen: List[httpx.Request] = []
    module = _module(_stream_ok(_delta("Hola", finish="stop")), seen)
    assert len(await _drain(module)) == 1 and len(seen) == 1
    monkeypatch.setenv("NEXE_ALLOW_CLOUD_ENGINES", "0")
    with pytest.raises(ValueError, match="turned off"):
        await _drain(module)
    assert len(seen) == 1, "no second request left the machine"
    monkeypatch.setenv("NEXE_ALLOW_CLOUD_ENGINES", "1")
    assert len(await _drain(module)) == 1 and len(seen) == 2


@pytest.mark.parametrize("value", ["", "0", "false", "maybe"])
async def test_a_switch_that_is_not_an_explicit_yes_sends_nothing(monkeypatch, value):
    seen: List[httpx.Request] = []
    monkeypatch.setenv("NEXE_ALLOW_CLOUD_ENGINES", value)
    with pytest.raises(ValueError):
        await _drain(_module(_stream_ok(_delta("x", finish="stop")), seen))
    assert seen == []


async def test_the_runtime_override_of_the_switch_wins_for_the_module_too(monkeypatch):
    from core import runtime_state
    seen: List[httpx.Request] = []
    runtime_state.set_override("NEXE_ALLOW_CLOUD_ENGINES", "0")
    try:
        with pytest.raises(ValueError):
            await _drain(_module(_stream_ok(_delta("x", finish="stop")), seen))
    finally:
        runtime_state.reset()
    assert seen == []


async def test_the_switch_is_checked_before_the_key_is_even_read(monkeypatch):
    """A server with the switch off must not touch its key at all."""
    from core.providers import registry
    monkeypatch.setenv("NEXE_ALLOW_CLOUD_ENGINES", "0")
    monkeypatch.setattr(registry, "read_api_key", lambda provider: (_ for _ in ()).throw(AssertionError("key read")))
    with pytest.raises(ValueError, match="turned off"):
        await _drain(_module(_stream_ok(_delta("x", finish="stop"))))


def test_the_cancel_poll_is_short_enough_for_a_deadline_to_matter():
    """Read here, in a file that does not shorten it for its own tests."""
    from plugins.api_module import chat as chat_module
    assert 0 < chat_module.CANCEL_POLL_SECONDS <= 0.5


async def test_the_switch_message_is_exactly_what_the_client_is_told():
    import os
    os.environ["NEXE_ALLOW_CLOUD_ENGINES"] = "0"
    try:
        with pytest.raises(ValueError) as refused:
            await _drain(_module(_stream_ok(_delta("x", finish="stop"))))
    finally:
        os.environ["NEXE_ALLOW_CLOUD_ENGINES"] = "1"
    assert str(refused.value) == "Cloud engines are turned off"


async def test_the_client_is_built_with_the_declared_timeout_and_never_follows_a_redirect(monkeypatch):
    """A redirect would carry the Authorization header to another host; no timeout would wait for ever."""
    from plugins.api_module import chat as chat_module

    built: list = []
    real = httpx.AsyncClient

    def spy(**kwargs):
        built.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(chat_module.httpx, "AsyncClient", spy)
    monkeypatch.setenv("NEXE_API_TIMEOUT", "33")
    await _drain(_module(_stream_ok(_delta("x", finish="stop"))))
    (kwargs,) = built
    assert kwargs["follow_redirects"] is False
    assert kwargs["timeout"] == httpx.Timeout(connect=10.0, read=33.0, write=30.0, pool=10.0)


async def test_a_redirect_is_an_error_and_the_second_host_is_never_asked():
    seen: List[httpx.Request] = []

    def redirect(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "https://elsewhere.example/steal"})

    with pytest.raises(ApiProviderError):
        await _drain(_module(redirect))
    assert len(seen) == 1 and "elsewhere" not in str(seen[0].url)


def test_the_view_of_a_turn_has_the_same_signature_and_defaults_as_the_module_it_wraps():
    module, view = inspect.signature(ApiModule.chat).parameters, inspect.signature(ApiModule().for_model("m").chat).parameters
    assert list(view) == list(module)[1:]
    for name in view:
        assert view[name].default == module[name].default, name


async def test_a_consumer_that_walks_away_is_counted_as_cancelled_not_as_a_request_that_succeeded():
    from core.metrics.registry import API_ENGINE_REQUESTS

    def value(status):
        return API_ENGINE_REQUESTS.labels(provider="deepseek", status=status)._value.get()

    cancelled0, ok0, error0 = value("cancelled"), value("ok"), value("error")
    gen = _module(lambda r: httpx.Response(200, content=_sse(*[_delta("x") for _ in range(5)], done=False))).chat(
        model="deepseek-chat", messages=[])
    await gen.__anext__()
    await gen.aclose()
    assert (value("cancelled"), value("ok"), value("error")) == (cancelled0 + 1, ok0, error0)
