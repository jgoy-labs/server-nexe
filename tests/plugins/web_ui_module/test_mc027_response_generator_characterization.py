"""F0 characterization tests for the MC-027/026 response_generator flatten refactor.

These LOCK the OBSERVABLE behaviour of the streaming `response_generator` closure
(plugins/web_ui_module/api/routes_chat.py, inside `_handle_chat_engine`) BEFORE it is
flattened to a module-level `async def` + a `@dataclass` context. They must pass GREEN
against the CURRENT (un-refactored) code — they characterize, they do not assume — and
each is mutation-proven (break production -> RED), see the docstrings.

Vehicle: the existing `_Harness` (non-GPU, drains `body_iterator`, patches `session_mgr`).

Invariant coverage (see ref/informes/refactor-god-objects-analisi + the 2-lineage map):
  - INV-CRIT-03 / INV-HIGH-08  single-persist (stream persists once, _chat_inner does not)
  - INV-CRIT-04                NUL wire protocol: MODEL_READY once, strict order, no [DONE]
  - INV-HIGH-07                <think> wrapping + full_response carries raw, wire carries visible
  - INV-CRIT-03 (MC-116)       client interrupt persists a partial assistant turn
  - INV-MED-13 (B125)          think-only turn persists the placeholder, behaviourally
  - INV-EXTRA-A                mid-stream error: partial persisted, [Error:] shown not saved
  - INV-EXTRA-D                the SECOND streaming generator (_chat_inner generate(), memory intent)
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from starlette.datastructures import State
from starlette.requests import Request as StarletteRequest

from plugins.web_ui_module.api.routes_chat import _StreamThinkParser
from tests.plugins.web_ui_module.test_chat_inner_behavior import (
    _Harness,
    _make_server_state,
)


def _connected_request():
    """A mock Request whose receive channel SUSPENDS (instead of the harness's
    default empty_receive, which raises synchronously). Starlette's
    is_disconnected() wraps the receive in an immediately-cancelled CancelScope, so
    a suspending receive is cancelled cleanly and is_disconnected() returns False.

    This keeps the _disconnect_monitor_task polling without raising — essential for
    the interrupt test, where the monitor outlives the torn-down generator (the
    finally does NOT cancel it; only the clean-finish path does). Without this the
    monitor's empty_receive RuntimeError surfaces as background-task noise and makes
    the interrupt assertion flaky.
    """
    app_mock = MagicMock()
    app_mock.state = State()
    app_mock.state.i18n = None

    async def _receive():
        await asyncio.Event().wait()  # suspend; cancelled by is_disconnected's scope
        return {"type": "http.request"}  # pragma: no cover

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/ui/chat",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "app": app_mock,
        "state": State(),
    }
    return StarletteRequest(scope, receive=_receive)


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    """Same as the harness module's fixture: slowapi's 20/min limit on /chat is not
    under test here, and its in-memory window is shared across the session — without
    this, these tests 429 when they run after the rest of the subtree (pollution).
    """
    from core.dependencies import limiter
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


@pytest.fixture(autouse=True)
def _use_connected_request():
    """All streaming tests here run against a request with a clean (suspending)
    receive channel so the disconnect monitor never raises."""
    with patch(
        "tests.plugins.web_ui_module.test_chat_inner_behavior._mock_request",
        new=_connected_request,
    ):
        yield


# ─── Streaming engines (Ollama signature: has 'model' param) ──────────────────

class _ChunkStreamEngine:
    """Ollama-signature engine that streams the given content chunks verbatim."""

    def __init__(self, chunks):
        self._chunks = chunks

    def chat(self, model, messages, stream=False, images=None, thinking_enabled=False):
        if stream:
            return self._astream()
        return {"message": {"content": "".join(self._chunks)}, "done": True}

    async def _astream(self):
        for c in self._chunks:
            yield {"message": {"content": c}}

    async def is_model_loaded(self, model_name):
        return True


class _ThinkingThenContentEngine:
    """Streams one pure-thinking chunk, then one content chunk."""

    def chat(self, model, messages, stream=False, images=None, thinking_enabled=False):
        return self._astream()

    async def _astream(self):
        yield {"message": {"content": "", "thinking": "raonant pel meu compte"}}
        yield {"message": {"content": "Resposta visible"}}

    async def is_model_loaded(self, model_name):
        return True


class _ContentThinkOnlyEngine:
    """Streams a single content chunk that is entirely an embedded <think> block,
    so the response cleans down to empty (think-only turn -> B125 placeholder)."""

    def chat(self, model, messages, stream=False, images=None, thinking_enabled=False):
        return self._astream()

    async def _astream(self):
        yield {"message": {"content": "<think>nomes raonament intern</think>"}}

    async def is_model_loaded(self, model_name):
        return True


class _MidStreamErrorEngine:
    """Streams one content chunk, then raises mid-stream (generic, non-OOM)."""

    def chat(self, model, messages, stream=False, images=None, thinking_enabled=False):
        return self._astream()

    async def _astream(self):
        yield {"message": {"content": "Hola "}}
        raise ValueError("boom")
        yield  # pragma: no cover  (makes this an async generator)

    async def is_model_loaded(self, model_name):
        return True


class _SlowBlockingEngine:
    """Streams two content chunks, then blocks — used to interrupt mid-stream."""

    def chat(self, model, messages, stream=False, images=None, thinking_enabled=False):
        return self._astream()

    async def _astream(self):
        yield {"message": {"content": "Hola "}}
        yield {"message": {"content": "amic "}}
        await asyncio.sleep(3600)  # block until the client (test) interrupts
        yield {"message": {"content": "mai"}}  # pragma: no cover

    async def is_model_loaded(self, model_name):
        return True


def _assistant_messages(session):
    return [m for m in session.messages if m["role"] == "assistant"]


def _live_monitor_tasks():
    """Pending _disconnect_monitor_task instances still alive in the loop."""
    out = []
    for t in asyncio.all_tasks():
        if t.done():
            continue
        coro = t.get_coro()
        name = getattr(coro, "__qualname__", "") or getattr(coro, "__name__", "") or ""
        if "_monitor_disconnect" in name:
            out.append(t)
    return out


async def _join_stream(result) -> str:
    """Fully drain a StreamingResponse and return the concatenated body."""
    parts = []
    async for chunk in result.body_iterator:
        parts.append(chunk if isinstance(chunk, str) else chunk.decode())
    return "".join(parts)


# ═══════════════════════════════════════════════════════════════
# INV-CRIT-03 / INV-HIGH-08 — streaming persists the assistant turn EXACTLY once
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestStreamingSinglePersist:

    async def test_streaming_happy_path_persists_exactly_once(self):
        """A clean streamed turn persists exactly ONE assistant message with the
        cleaned text, and writes the session to disk.

        Mutation: if _chat_inner also persisted streams (fall-through past the
        StreamingResponse return), or the generator persisted twice, len == 2 -> RED.
        """
        engine = _ChunkStreamEngine(["Hola ", "Nexe"])
        h = _Harness(intent="chat")
        state = _make_server_state(engine=engine)

        result = await h.call({"message": "Hola", "stream": True}, server_state=state)
        assert isinstance(result, StreamingResponse)
        await _join_stream(result)

        msgs = _assistant_messages(h.session)
        assert len(msgs) == 1, "streamed turn must persist exactly one assistant message"
        assert msgs[0]["content"] == "Hola Nexe"
        assert h.session_mgr._save_session_to_disk.call_count >= 1


# ═══════════════════════════════════════════════════════════════
# INV-CRIT-04 — NUL wire protocol: MODEL_READY once, strict order, NO [DONE]
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestWireProtocol:

    async def test_model_ready_once_order_and_no_done_sentinel(self):
        """The wire is text/plain with NUL framing: [MODEL:..] header, then exactly
        one [MODEL_READY], then the visible content; never an SSE [DONE] sentinel.

        Mutation: emitting MODEL_READY before the async-for, or a terminal
        `data: [DONE]`, or reordering header vs content -> index/count assertion RED.
        """
        engine = _ChunkStreamEngine(["Hola ", "Nexe"])
        h = _Harness(intent="chat")
        state = _make_server_state(engine=engine)

        result = await h.call({"message": "Hola", "stream": True}, server_state=state)
        body = await _join_stream(result)

        assert "\x00[MODEL:" in body
        assert body.count("\x00[MODEL_READY]\x00") == 1, "MODEL_READY must appear exactly once"
        assert "[DONE]" not in body, "text/plain stream must NOT emit an SSE [DONE] sentinel"
        assert "data:" not in body, "stream must not be SSE-framed"

        assert body.index("\x00[MODEL:") < body.index("\x00[MODEL_READY]\x00")
        assert body.index("\x00[MODEL_READY]\x00") < body.index("Hola")

        assert result.media_type == "text/plain"
        assert result.headers.get("X-Accel-Buffering") == "no"
        assert "no-store" in result.headers.get("Cache-Control", "")


# ═══════════════════════════════════════════════════════════════
# INV-HIGH-07 — thinking tokens wrapped in <think>; full_response keeps raw,
#               wire shows visible; persisted text has <think> stripped
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestThinkWrapping:

    async def test_thinking_wrapped_and_stripped_from_persisted(self):
        """A thinking chunk is wrapped <think>..</think> on the wire (in order,
        before the visible content), and the persisted assistant message has the
        think block stripped.

        Mutation: dropping the </think> close-on-content-transition, or persisting
        full_response without _clean_full_response -> reasoning leaks into the saved
        message / order assertion RED.
        """
        engine = _ThinkingThenContentEngine()
        h = _Harness(intent="chat")
        state = _make_server_state(engine=engine)

        result = await h.call({"message": "Pensa", "stream": True}, server_state=state)
        body = await _join_stream(result)

        assert "<think>" in body and "</think>" in body
        assert "raonant pel meu compte" in body
        assert "Resposta visible" in body
        assert body.index("<think>") < body.index("raonant pel meu compte")
        assert body.index("raonant pel meu compte") < body.index("</think>")
        assert body.index("</think>") < body.index("Resposta visible")

        msgs = _assistant_messages(h.session)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "Resposta visible", "saved turn must not contain <think>"


# ═══════════════════════════════════════════════════════════════
# INV-CRIT-03 (MC-116) — client interrupt mid-stream persists a partial turn
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestInterruptPartialPersist:

    async def test_client_disconnect_persists_partial_assistant(self):
        """When the client tears down the stream (aclose -> GeneratorExit) before
        the engine finishes, the generator's finally persists a best-effort partial
        assistant turn marked interrupted, so the session is not left with an orphan
        user message (MC-116).

        Mutation: narrowing the try/finally scope, or deferring full_response init,
        leaves NO partial persisted -> RED.
        """
        engine = _SlowBlockingEngine()
        h = _Harness(intent="chat")
        state = _make_server_state(engine=engine)

        result = await h.call({"message": "Hola", "stream": True}, server_state=state)
        assert isinstance(result, StreamingResponse)

        it = result.body_iterator
        acc = ""
        # Pull early chunks until visible content has streamed, then tear down.
        for _ in range(20):
            try:
                chunk = await asyncio.wait_for(it.__anext__(), timeout=1.0)
            except (asyncio.TimeoutError, StopAsyncIteration):
                break
            acc += chunk if isinstance(chunk, str) else chunk.decode()
            if "Hola" in acc:
                break
        assert "Hola" in acc, "expected to receive streamed content before interrupting"
        await it.aclose()  # GeneratorExit into response_generator

        msgs = _assistant_messages(h.session)
        assert len(msgs) == 1, "interruption must persist exactly one partial assistant turn"
        assert msgs[0]["content"].startswith("Hola")
        assert msgs[0].get("stats", {}).get("interrupted") is True


# ═══════════════════════════════════════════════════════════════
# INV-MED-13 (B125) — think-only turn persists the placeholder (behavioural)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestThinkOnlyPlaceholderBehavioural:

    async def test_think_only_turn_persists_placeholder(self):
        """A turn that cleans down to empty (only <think> content) still persists a
        placeholder assistant message so get_context_messages() keeps the
        user/assistant alternation and the next user turn is not dropped (B125).

        This is the behavioural complement to the getsource sentinel in
        test_b125_think_only.py (kept as a cheap secondary).

        Mutation: skipping _think_only_placeholder, or gating the persist on a
        non-empty clean_response only -> no placeholder saved -> RED.
        """
        from plugins.web_ui_module.api.routes_chat import _THINK_ONLY_PLACEHOLDER

        engine = _ContentThinkOnlyEngine()
        h = _Harness(intent="chat")
        state = _make_server_state(engine=engine)

        result = await h.call({"message": "Pensa en silenci", "stream": True}, server_state=state)
        await _join_stream(result)

        msgs = _assistant_messages(h.session)
        assert len(msgs) == 1, "a think-only turn must still persist one assistant message"
        assert msgs[0]["content"] == _THINK_ONLY_PLACEHOLDER


# ═══════════════════════════════════════════════════════════════
# INV-EXTRA-A — mid-stream error: partial content persisted, [Error:] shown not saved
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestMidStreamError:

    async def test_midstream_error_shows_generic_notice_persists_partial_only(self):
        """A generic error mid-stream surfaces a curated ⚠️ notice to the client
        (MC-133) — NOT the raw exception text — and persists ONLY the partial
        content streamed before the error; the notice itself is never appended to
        full_response, so it is not saved.

        MC-133: the raw error string ('boom') must not leak into the chat body.
        Mutation: revert to `yield f"[Error: {err_msg}]"` → 'boom' reappears in the
        body and the ⚠️ notice disappears → RED.
        """
        engine = _MidStreamErrorEngine()
        h = _Harness(intent="chat")
        state = _make_server_state(engine=engine)

        result = await h.call({"message": "Hola", "stream": True}, server_state=state)
        body = await _join_stream(result)

        assert "boom" not in body, "MC-133: the raw exception text must not leak to the body"
        assert "[Error: boom]" not in body, "the old raw-error inline must be gone"
        assert "⚠️" in body, "a generic error notice must surface inline"

        msgs = _assistant_messages(h.session)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "Hola", "only the partial content is persisted"
        assert "⚠️" not in msgs[0]["content"], "the error notice must not be persisted"


# ═══════════════════════════════════════════════════════════════
# INV-EXTRA-D — the SECOND streaming generator (memory intent, _chat_inner generate())
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestMemoryIntentStreamPath:

    async def test_memory_intent_stream_persists_once_and_streams_text(self):
        """A memory intent with stream=True takes the OTHER streaming path
        (_chat_inner's char-by-char generate() over the pre-built response_text),
        NOT response_generator. It persists the assistant reply once and streams the
        same text. The module-level move + session_mgr threading touches this scope,
        so it is part of the F0 safety net (INV-EXTRA-D).

        Mutation: dropping/altering the 2333 add_message, or double-streaming,
        breaks the single-persist or the body==text assertion -> RED.
        """
        h = _Harness(intent="save", mem_content="Em dic Joan")
        result = await h.call({"message": "Recorda que em dic Joan", "stream": True})
        assert isinstance(result, StreamingResponse)
        body = await _join_stream(result)

        msgs = _assistant_messages(h.session)
        assert len(msgs) == 1, "memory-intent stream must persist exactly one assistant turn"
        # the streamed body is the persisted reply, char-by-char
        assert msgs[0]["content"] in body
        assert "memory" in body.lower() or "memòria" in body.lower()


# ═══════════════════════════════════════════════════════════════
# F1 — unit tests for the extracted _StreamThinkParser (no TestClient)
# ═══════════════════════════════════════════════════════════════

class TestStreamThinkParserUnit:
    """The FSM extracted in F1 must expose feed()/flush() -> (wire, full_delta) with
    the visible/raw split intact (INV-HIGH-07). Pure unit, no endpoint."""

    def test_thinking_opens_closes_and_full_delta_keeps_tags(self):
        p = _StreamThinkParser("llama3.2:3b")
        wire, full = p.feed("", "raonant")
        assert wire == ["<think>", "raonant"]
        assert full == "<think>raonant"
        assert p.has_any_thinking is True

        wire2, full2 = p.feed("resposta", "")  # content closes the open <think>
        assert wire2[0] == "</think>", "content after thinking must close the tag first"
        assert full2.startswith("</think>")
        assert "resposta" in full2, "full_delta keeps the raw content"
        visible = "".join(wire2[1:] + p.flush()[0])
        assert visible == "resposta", "wire shows only the visible content"

    def test_plain_content_visible_equals_full(self):
        p = _StreamThinkParser("llama3.2:3b")
        wire, full = p.feed("Hola amic", "")
        wire_f, full_f = p.flush()
        assert full == "Hola amic" and full_f == ""
        assert "".join(wire + wire_f) == "Hola amic"
        assert p.has_any_thinking is False

    def test_embedded_think_across_chunks_suppressed_from_visible_kept_in_full(self):
        """A <think> block whose tags are intact but whose body spans two chunks
        (qwq:32b style) is suppressed from the wire via carried _in_content_think,
        yet the raw text stays in full_response so _clean_full_response can strip it."""
        p = _StreamThinkParser("qwq:32b")  # non-gpt-oss -> _normalize_content path
        w1, f1 = p.feed("abans<think>ocult", "")
        w2, f2 = p.feed("amagat</think>despres", "")
        wf, ff = p.flush()
        full = f1 + f2 + ff
        visible = "".join(w1 + w2 + wf)
        assert "ocult" not in visible and "amagat" not in visible
        assert "abans" in visible and "despres" in visible
        assert "ocult" in full and "amagat" in full, "raw think text kept for persist-time strip"

    def test_harmony_routing_gpt_oss_vs_normalize(self):
        """gpt-oss models route content through HarmonyStreamFilter; others use
        _normalize_content. Mutually exclusive (INV-HIGH-07), case-insensitive."""
        assert _StreamThinkParser("gpt-oss:20b")._harmony_buf is not None
        assert _StreamThinkParser("GPT-OSS")._harmony_buf is not None
        assert _StreamThinkParser("llama3.2:3b")._harmony_buf is None
        assert _StreamThinkParser("qwq:32b")._harmony_buf is None

    def test_flush_returns_pair(self):
        p = _StreamThinkParser("llama3.2:3b")
        wire, full = p.flush()
        assert isinstance(wire, list) and isinstance(full, str)


# ═══════════════════════════════════════════════════════════════
# INV-CRIT-01 — HTTPException paths must cancel the disconnect monitor (no orphan)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestHttpExceptionNoOrphanMonitor:

    async def test_400_model_too_long_cancels_monitor(self):
        """The 400 (model name too long) raises AFTER the monitor task is created,
        inside the try; the outer `except HTTPException` must cancel it before
        re-raising. No _monitor_disconnect task may survive.

        Mutation: drop the cancel in the HTTPException handler (or narrow the try so
        the raise escapes it) -> an orphan monitor survives -> RED.
        """
        h = _Harness(intent="chat")
        state = _make_server_state()
        with pytest.raises(HTTPException) as exc:
            await h.call({"message": "Hola", "model": "a" * 101}, server_state=state)
        assert exc.value.status_code == 400
        await asyncio.sleep(0)  # let the cancellation settle
        assert _live_monitor_tasks() == [], "400 path left an orphan disconnect monitor"

    async def test_503_no_module_manager_cancels_monitor(self):
        """The 503 (module_manager is None) also raises inside the try after monitor
        creation and must be cancelled by the outer handler."""
        h = _Harness(intent="chat")
        state = MagicMock()
        state.module_manager = None
        with pytest.raises(HTTPException) as exc:
            await h.call({"message": "Hola"}, server_state=state)
        assert exc.value.status_code == 503
        await asyncio.sleep(0)
        assert _live_monitor_tasks() == [], "503 path left an orphan disconnect monitor"
