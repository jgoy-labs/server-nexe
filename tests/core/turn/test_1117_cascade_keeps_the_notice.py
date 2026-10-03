"""#1117: the web cascade must not cost the notice or the loading banner.

693df545 taught the streaming web door to read an engine's first event before
giving it the stream, so an engine that fails before a byte hands the turn to
the next one. It also cut three things that 32f9cbd0 did:

- one engine that fails before a byte raised a 503 inside a stream whose 200
  was already sent (the browser sees a dropped connection, not the notice);
- an out-of-memory while loading lost its own notice the same way;
- `MODEL_LOADING` was checked after that first event, when the model is
  always loaded, so the banner never went out again.

The wire for one engine is the one 32f9cbd0 sent; the cascade for several is
693df545's. Every engine here has the shape of a real one: Ollama's `chat`
returns a generator whose first read is where the server loads the model (and
fails), MLX's loads its weights inside `chat` (`MLXChatNode._get_model`).
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

from plugins.web_ui_module.api.wire import _stream_error_notice

OOM = RuntimeError("[METAL] Command buffer execution failed: Insufficient Memory")


class _OllamaShaped:
    """`chat(model, …)` returns a generator; the first read is the request.
    `is_model_loaded` is the real module's (`/api/ps`): `loaded` says what it
    answers — the real one says False when Ollama is down, too."""

    def __init__(self, exc: Exception | None = None, tokens=("ada",), loaded=True):
        self.exc = exc
        self.tokens = tokens
        self.loaded = loaded
        self.calls = 0

    async def is_model_loaded(self, model_name: str) -> bool:
        return self.loaded

    def chat(self, model, messages, stream=False, **kwargs):
        self.calls += 1
        exc, tokens = self.exc, self.tokens

        async def _gen():
            if exc is not None:
                raise exc
            for token in tokens:
                yield token

        return _gen()


class _MlxShaped:
    """Tokens through the callback; the weights load inside `chat`."""

    def __init__(self, *, fail: Exception | None = None, loaded=False, delay=0.0,
                 cancels=False, tokens=("ada", " i acabada."), model_path: str | None = None):
        self.loaded = loaded
        self.fail = fail
        self.delay = delay
        self.cancels = cancels
        self.tokens = tokens
        self.calls: list[dict] = []
        self.switched_to = None
        # A serviceable mlx module has a live node; its config names the model
        # it runs (what `resolve_loaded_model_name` reads, #1035).
        self._node = SimpleNamespace(config=SimpleNamespace(model_path=model_path)) if model_path else object()

    async def chat(self, messages, system="", session_id="default", stream_callback=None, **kwargs):
        self.calls.append(kwargs)
        if self.cancels:
            kwargs["cancel_event"].set()
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        self.loaded = True
        for token in self.tokens:
            stream_callback(token)
        return {"finish_reason": "stop"}

    async def is_model_loaded(self, model_name=""):
        return self.loaded

    def can_continue(self, model_name=None):
        return True

    def switch_model_by_path(self, local_path) -> bool:
        # What the real module does: the new weights are not in memory yet.
        self.switched_to = local_path
        self.loaded = False
        return True


def _wire(ctx) -> list:
    chunks = list(ctx.lab_wire_chunks)
    # Starlette encodes every chunk; anything but text would crash the stream.
    assert all(isinstance(c, str) for c in chunks), [type(c) for c in chunks]
    return chunks


def _at(chunks: list, marker: str) -> int:
    hits = [i for i, c in enumerate(chunks) if marker in c]
    assert hits, f"{marker!r} not on the wire: {chunks!r}"
    return hits[0]


def _count(chunks: list, marker: str) -> int:
    return sum(marker in c for c in chunks)


async def test_the_only_engine_failing_before_a_byte_writes_its_notice(turn_lab, app_state, caplog):
    """32f9cbd0's wire: the notice inside the open stream, the turn degraded.
    693df545 raised a 503 here, after the 200. The log keeps the traceback:
    the notice is written outside any `except`, where `exc_info=True` logged
    "NoneType: None"."""
    exc = RuntimeError("model 'nope' not found")
    app_state.modules = {"ollama_module": _OllamaShaped(exc)}
    with caplog.at_level(logging.ERROR, logger="plugins.web_ui_module.api.wire"):
        ctx = await turn_lab.ui(streaming=True, session_id="r1117-one", message="hola",
                                body_extra={"backend": "ollama"})
    chunks = _wire(ctx)
    notice = _stream_error_notice(exc, ctx.lang)
    assert _at(chunks, "\x00[MODEL:") < chunks.index(notice)
    assert ctx.outcomes["generate"] == "degraded"
    logged = [r for r in caplog.records if r.getMessage().startswith("Streaming error")]
    assert logged and logged[0].exc_info and logged[0].exc_info[1] is exc


async def test_an_out_of_memory_while_loading_keeps_its_own_notice(turn_lab, app_state):
    app_state.modules = {"mlx_module": _MlxShaped(fail=OOM)}
    ctx = await turn_lab.ui(streaming=True, session_id="r1117-oom", message="hola",
                            body_extra={"backend": "mlx"})
    chunks = _wire(ctx)
    notice = _stream_error_notice(OOM, ctx.lang)
    assert notice != _stream_error_notice(RuntimeError("x"), ctx.lang)  # it IS the OOM one
    assert notice in chunks
    assert ctx.outcomes["generate"] == "degraded"


async def test_a_model_that_loads_on_the_first_read_is_announced_before_it(turn_lab, app_state):
    app_state.modules = {"mlx_module": _MlxShaped()}
    ctx = await turn_lab.ui(streaming=True, session_id="r1117-load", message="hola",
                            body_extra={"backend": "mlx"})
    chunks = _wire(ctx)
    assert _at(chunks, "\x00[MODEL:") < _at(chunks, "MODEL_LOADING") < _at(chunks, "MODEL_READY")
    assert ctx.outcomes["generate"] == "ok"


async def test_an_error_every_engine_would_repeat_is_not_cascaded(turn_lab, app_state):
    """A bad request is bad for every engine (`should_try_next_engine`): no
    other engine is asked, and the notice is written in the open stream."""
    exc = ValueError("continue requires the last message to be an assistant turn")
    mlx = _MlxShaped(loaded=True)
    app_state.modules = {"ollama_module": _OllamaShaped(exc), "mlx_module": mlx}
    ctx = await turn_lab.ui(streaming=True, session_id="r1117-term", message="hola",
                            body_extra={"backend": "ollama"})
    chunks = _wire(ctx)
    assert mlx.calls == []
    assert _stream_error_notice(exc, ctx.lang) in chunks
    assert ctx.outcomes["generate"] == "degraded"


async def test_when_every_engine_fails_the_first_ones_notice_is_written(turn_lab, app_state):
    """The first failure is the engine the user picked — and an OOM must not be
    covered by a fallback's generic error."""
    ollama = _OllamaShaped(RuntimeError("connection reset"))
    app_state.modules = {"mlx_module": _MlxShaped(fail=OOM), "ollama_module": ollama}
    ctx = await turn_lab.ui(streaming=True, session_id="r1117-all", message="hola",
                            body_extra={"backend": "mlx"})
    chunks = _wire(ctx)
    assert ollama.calls == 1
    assert _stream_error_notice(OOM, ctx.lang) in chunks
    assert _stream_error_notice(RuntimeError("connection reset"), ctx.lang) not in chunks


async def test_the_loading_banner_goes_out_once(turn_lab, app_state):
    """nexe-chat.js keeps a second MODEL_LOADING spinning for ever."""
    second = _MlxShaped()
    first = _MlxShaped(fail=OOM)
    app_state.modules = {"mlx_module": first, "llama_cpp_module": second}
    ctx = await turn_lab.ui(streaming=True, session_id="r1117-once", message="hola",
                            body_extra={"backend": "mlx"})
    chunks = _wire(ctx)
    assert first.calls and second.calls
    assert _count(chunks, "MODEL_LOADING") == 1
    assert "ada" in "".join(c for c in chunks if not c.startswith("\x00"))


async def test_the_call_time_counts_up_to_the_first_token(turn_lab, app_state):
    """`record_llm_call` and the stored `elapsed` start before the first read,
    where the model loads — not after it."""
    app_state.modules = {"mlx_module": _MlxShaped(delay=0.2)}
    ctx = await turn_lab.ui(streaming=True, session_id="r1117-ms", message="hola",
                            body_extra={"backend": "mlx"})
    _wire(ctx)
    call = ctx.usage["llm"]["calls"][-1]
    assert call["engine"] == "mlx"
    assert call["ms"] >= 190


async def test_a_fallback_whose_model_is_not_in_memory_is_announced(turn_lab, app_state):
    """The banner asks about, and names, the model the fallback runs: its own
    (#1035), not the one picked for the engine that failed."""
    mlx = _MlxShaped(loaded=False, model_path="/models/Qwen3.5-4B-MLX-4bit")
    # Ollama is up with its model in memory (`/api/ps` says loaded) and the
    # chat itself fails: the only banner this turn can send is MLX's. (An
    # Ollama that is down says "not loaded" and would take the turn's one
    # banner — the label limit noted on #1117.)
    ollama = _OllamaShaped(RuntimeError("500 Internal Server Error"), loaded=True)
    app_state.modules = {"ollama_module": ollama, "mlx_module": mlx}
    ctx = await turn_lab.ui(streaming=True, session_id="r1117-switch", message="hola",
                            body_extra={"backend": "ollama", "model": "qwen3.5:4b"})
    chunks = _wire(ctx)
    assert ollama.calls == 1
    assert mlx.switched_to is None
    assert _count(chunks, "MODEL_LOADING") == 1
    assert "MODEL_LOADING:Qwen3.5-4B-MLX-4bit|mlx]" in chunks[_at(chunks, "MODEL_LOADING")]
    assert _at(chunks, "MODEL_LOADING") < _at(chunks, "MODEL_READY")


async def test_a_client_that_left_is_not_offered_to_another_engine(turn_lab, app_state):
    ollama = _OllamaShaped()
    app_state.modules = {"mlx_module": _MlxShaped(fail=RuntimeError("worker died"), cancels=True),
                         "ollama_module": ollama}
    ctx = await turn_lab.ui(streaming=True, session_id="r1117-gone", message="hola",
                            body_extra={"backend": "mlx"})
    _wire(ctx)
    assert ollama.calls == 0


class _StartRefusesTheRequest:
    """An engine whose `chat(model, …)` rejects the request as it is called,
    before any generator exists: a ValueError, final for the cascade policy.
    (Until #1035 the real case was a fallback asked to load a model that was
    not its own; a fallback no longer switches, so this stands in for it.)"""

    def __init__(self):
        self.calls = 0
        self._node = object()

    def chat(self, model, messages, stream=False, **kwargs):
        self.calls += 1
        raise ValueError("bad request: this engine cannot take it")


async def test_a_fallback_that_cannot_start_keeps_the_notice_in_hand(turn_lab, app_state, caplog):
    """The first engine failed before a byte; the fallback's start then fails
    with an error the cascade policy treats as final. Raising that as HTTP
    would cut a stream whose 200 is already out: the notice in hand is
    written instead. Neither error is lost from the log — the user sees the
    first one, and the second would otherwise leave no trace at all."""
    down = RuntimeError("connection reset")
    mlx = _StartRefusesTheRequest()
    app_state.modules = {"ollama_module": _OllamaShaped(down), "mlx_module": mlx}
    with caplog.at_level(logging.DEBUG, logger="plugins.web_ui_module.api.turn_adapters"):
        ctx = await turn_lab.ui(streaming=True, session_id="r1117-start", message="hola",
                                body_extra={"backend": "ollama", "model": "qwen3.5:4b"})
    chunks = _wire(ctx)
    assert mlx.calls == 1
    assert _stream_error_notice(down, ctx.lang) in chunks
    assert ctx.outcomes["generate"] == "degraded"
    mine = [r for r in caplog.records if r.name == "plugins.web_ui_module.api.turn_adapters"]
    assert any("mlx failed" in r.getMessage() and "cannot take it" in r.getMessage() for r in mine)
    assert any(r.exc_info and r.exc_info[1] is down for r in mine)


async def test_stop_while_the_model_loads_saves_no_empty_answer(app_state, session_manager, memory_helper,
                                                                server_state):
    """The user clicks Stop on the loading banner. The engine has not said a
    word: nothing is stored as the assistant's answer, the way 32f9cbd0 left
    it (its stream context existed before the load; the claim's does not)."""
    import json
    from pathlib import Path

    from core.turn.context import TurnContext
    from core.turn.run import stream_turn
    from plugins.web_ui_module.api.turn_adapters import ui_adapters

    from .conftest import LAB_PRINCIPAL, door_patches, make_request

    app_state.modules = {"mlx_module": _MlxShaped()}
    ctx = TurnContext(
        turn_id="turn-r1117-stop", entry="ui", principal=LAB_PRINCIPAL,
        body={"message": "hola", "session_id": "r1117-stop", "stream": True, "backend": "mlx"},
        request=make_request(app_state), app_state=app_state,
    )
    seen: list = []
    with door_patches(server_state, memory_helper):
        body = await stream_turn(ctx, ui_adapters(session_manager, streaming=True))
        async for chunk in body:
            seen.append(chunk)
            if isinstance(chunk, str) and "MODEL_LOADING" in chunk:
                break  # Stop, while the weights load
        await body.aclose()

    assert any("MODEL_LOADING" in c for c in seen if isinstance(c, str))
    stored = json.loads((Path(session_manager._storage_path) / "r1117-stop.json").read_text(encoding="utf-8"))
    assert [m["role"] for m in stored["messages"]] == ["user"]
    assert ctx.outcomes["generate"] == "cancelled"
