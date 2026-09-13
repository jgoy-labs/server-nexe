"""The fakes an I1 contract test needs to drive a REAL turn (ADR-007, C4.0).

The point of `test_i1_one_sequence.py` is that the three entries of the chat
— `/ui/chat` streaming, `/ui/chat` JSON and `/v1/chat/completions` — walk the
SAME `TURN_STEPS`, through the REAL adapter tables (`ui_adapters`,
`api_adapters`), not through hand-written fake adapters. So everything below
is scaffolding around real code: a real `SessionManager` over `tmp_path`, a
real `EngineGate`, a real `TurnContext`, and one fake where a real thing would
cost an LLM call or a network hop.

**Own fakes, on purpose.** The UI door's test file builds an equivalent
harness (`tests/plugins/web_ui_module/test_chat_inner_behavior.py:163`
`_Harness`, imported by `test_turn_adapters_ui.py`). This conftest deliberately
does NOT import it: a test of the core must not depend on a test of a plugin,
for the same reason `scripts/check_layering.py` keeps `core → plugins` at zero.
The shapes below were copied by reading that harness, not by importing it.

**No conditional mocks.** Every patch here behaves the same way whatever it is
called with (the anti-pattern the BUS prompt names): `_forward_to_ollama`
always answers with the same text `_FakeEngine` streams, `build_rag_context`
always retrieves nothing. Nothing branches on its arguments, so no code path
is hidden behind a mock that only fires for some of them.
"""
from __future__ import annotations

import contextlib
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.datastructures import State
from starlette.requests import Request as StarletteRequest

from core.sessions.session_manager import SessionManager
from core.turn.gate import EngineGate

#: The principal the doors record on the request (C4.1): both `require_api_key`
#: and `require_ui_auth` keep the key they authenticated, and the door copies it
#: onto the turn. The lab presents `x-api-key: test-key` below, so this is what
#: a real door would have put there — a turn without it is refused by the
#: `authorize` step, which is what `test_authorize_fail_closed.py` measures.
LAB_PRINCIPAL: str = "test-key"

#: What the model "says", in two chunks — the same two at both doors, so a
#: difference between the three entries is never the fake's fault.
FAKE_CHUNKS: tuple[str, ...] = ("Hola, ", "Aran.")
FAKE_ANSWER: str = "".join(FAKE_CHUNKS)


class _FakeEngine:
    """A generic-shaped engine: `chat(messages, system=…)`, no `model` param.

    `routes_chat._start_engine_call` picks its branch off this signature —
    a `model` parameter means the Ollama shape, `mlx`/`llama_cpp` mean the
    in-process queue, and anything else is this generic call. `stream_callback`
    and `images` are declared because the generic branch may pass them; the
    engine ignores them and always yields the same two chunks, streaming or
    not (`_accumulate_nonstreaming_response` drains an async generator just as
    happily as `_yield_engine_chunks` does).
    """

    def __init__(self, chunks: tuple[str, ...] = FAKE_CHUNKS) -> None:
        self.chunks = chunks
        self.calls = 0

    async def chat(
        self, messages, system=None, stream_callback=None, session_id=None,
        images=None, thinking_enabled=False, **_kwargs,
    ):
        self.calls += 1
        for chunk in self.chunks:
            yield chunk

    async def is_model_loaded(self, model_name) -> bool:
        return True


class _FakeMemoryHelper(MagicMock):
    """The memory port both doors ask for. A MagicMock with the async methods
    pinned: `helper_for()` returns a live port in production, and every call
    the `intent`/`memory.write` steps make on it must be awaitable."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.detect_intent = MagicMock(return_value=("chat", None))
        self.matches_clear_all_confirm = MagicMock(return_value=False)
        self.save_to_memory = AsyncMock(return_value={"success": True, "document_id": "doc-1"})
        self.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
        self.list_memories = AsyncMock(return_value={
            "success": True, "facts": [], "total": 0, "message": "No memories stored.",
        })
        self.clear_memory = AsyncMock(return_value={"success": True})
        self.delete_from_memory = AsyncMock(return_value={"success": True, "deleted": 0, "deleted_facts": []})
        self.preview_delete_from_memory = AsyncMock(return_value={"success": True, "candidates": []})
        self.delete_memory_entries = AsyncMock(return_value={"success": True, "deleted": 0, "deleted_facts": []})


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    """slowapi validates the Request type when enabled; these turns are driven
    through the adapters, not through a routed endpoint."""
    from core.dependencies import limiter
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


@pytest.fixture
def fake_engine() -> _FakeEngine:
    return _FakeEngine()


@pytest.fixture
def memory_helper() -> _FakeMemoryHelper:
    return _FakeMemoryHelper()


@pytest.fixture
def session_manager(tmp_path, monkeypatch) -> SessionManager:
    """A real SessionManager over a temp dir: `persist_user_turn` and
    `persist_assistant_turn` really write, which is what makes the sequence
    observed by the contract test the production one."""
    monkeypatch.setenv("NEXE_ENV", "development")
    return SessionManager(storage_path=str(tmp_path / "sessions"), crypto_provider=None)


@pytest.fixture
def app_state(session_manager, memory_helper, fake_engine, monkeypatch) -> State:
    """`request.app.state` as the plugin loader would have left it.

    `modules` is what `core.endpoints.chat_engines.routing` reads to decide
    what is live — one entry, so both doors resolve the same engine and the
    cascade is deterministic. `post_commit_queue` is None on purpose:
    `memory.write` and `compact` then run INLINE, so every step of
    `TURN_STEPS` records an outcome in this turn instead of being handed to a
    background queue (which is what `run.py` does with a real queue, and what
    `test_c2_done_gate.py` is about).
    """
    # Determinism: `resolve_engine_cascade` reads this before the config, and
    # a developer machine may well have another engine named in the env.
    monkeypatch.setenv("NEXE_MODEL_ENGINE", "ollama")
    # Determinism (T1, finding 1057): `ui["model_name"]` falls back to this
    # var when the body has none (`turn_adapters.py:347`), and a developer
    # machine may well have it set to whatever it is running locally — which
    # is exactly what made `usage_llm_models` an accidental value instead of
    # a known one before this line existed.
    monkeypatch.setenv("NEXE_DEFAULT_MODEL", "llama3.2:3b")
    state = State()
    state.config = {}
    state.i18n = None
    state.session_manager = session_manager
    state.memory_helper = memory_helper
    state.modules = {"ollama_module": fake_engine}
    state.engine_gate = EngineGate(slots=100)
    state.post_commit_queue = None
    return state


def make_request(app_state: State) -> StarletteRequest:
    """A minimal starlette Request: `isinstance` checks pass, `is_disconnected()`
    answers False, and `request.app.state` is the one built above."""
    app_mock = MagicMock()
    app_mock.state = app_state
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/chat",
        "query_string": b"",
        "headers": [(b"x-api-key", b"test-key")],
        "client": ("127.0.0.1", 12345),
        "app": app_mock,
        # C4.1 (#1044): the trace `require_ui_auth` leaves behind — the principal
        # it authenticated. The door copies it onto the turn and `authorize`
        # refuses a turn without one, so a harness that stubs the auth
        # dependency has to leave the same trace. A plain dict is what
        # Starlette's `request.state` wraps.
        "state": {"principal": LAB_PRINCIPAL},
    }
    return StarletteRequest(scope)


@pytest.fixture
def server_state() -> MagicMock:
    """What `core.lifespan.get_server_state()` returns.

    Two things are read off it and both must be deterministic ACROSS TURNS,
    which is why this is a fixture built once and not a helper called per turn:

    * `module_manager` — the UI's `engine` step refuses to run without one. It
      does not read it further: what is live comes from `app_state.modules`,
      through the core resolver.
    * `config` — a REAL dict, not a MagicMock. `_build_system_prompt_with_time`
      (`routes_chat.py:962`) resolves the base system prompt through
      `_get_system_prompt(get_server_state(), lang)`, and a MagicMock config
      makes that prompt a `<MagicMock … id=0x…>` string whose id differs on
      every instance — two turns would then legitimately differ in
      `ctx.system_prompt` for a reason that has nothing to do with the turn.
      An empty dict resolves to `EMERGENCY_SYSTEM_PROMPT`, which is stable.
    """
    state = MagicMock()
    state.config = {}
    state.module_manager = MagicMock()
    state.module_manager.registry.list_modules.return_value = []
    state.project_root = "/tmp"
    return state


@contextlib.contextmanager
def door_patches(server_state: Any, memory_helper: Any, answer: str = FAKE_ANSWER):
    """The four things a turn must not really do in a unit test, patched the
    same way for every caller and every argument.

    * `core.lifespan.get_server_state` — the UI's `engine` step refuses to run
      without a module manager.
    * `core.memory_facts.helper_for` — the UI's `intent` step asks for the
      memory port through the module (the API's reads `app_state.memory_helper`
      directly, which the `app_state` fixture already provides).
    * `build_rag_context`, at both doors' import sites — retrieval would hit a
      vector store. Always returns "nothing retrieved", never argument-dependent.
    * `core.endpoints.chat._forward_to_ollama` — the API door's generate step
      dispatches over HTTP to a real Ollama. It answers with exactly the text
      `_FakeEngine` streams at the other door, so the two doors' `ctx.response`
      are comparable and any difference is the pipeline's, not the fake's.
    """
    ollama_reply = {"choices": [{"message": {"role": "assistant", "content": answer}}]}

    async def _no_rag(*_args, **_kwargs):
        return "", []

    with patch("core.lifespan.get_server_state", return_value=server_state), \
         patch("core.memory_facts.helper_for", return_value=memory_helper), \
         patch("core.endpoints.chat_rag.build_rag_context", new=_no_rag), \
         patch("core.endpoints.chat.build_rag_context", new=_no_rag), \
         patch("core.endpoints.chat._forward_to_ollama",
               new=AsyncMock(return_value=ollama_reply)):
        yield


class TurnLab:
    """Drives REAL turns through the REAL adapter tables, one method per entry.

    The three methods differ only in which door's table they hand to the turn
    engine and how they build the body — which is the point: if a test had to
    do anything else differently per door, I1 would already be broken here in
    the test file.
    """

    def __init__(self, app_state: State, session_manager: SessionManager,
                 memory_helper: Any, server_state: Any) -> None:
        self.app_state = app_state
        self.session_manager = session_manager
        self.memory_helper = memory_helper
        self.server_state = server_state

    def _patches(self):
        return door_patches(self.server_state, self.memory_helper)

    async def ui(self, *, streaming: bool, session_id: str, entry: str = "ui",
                 message: str = "hola", body_extra: Optional[dict] = None):
        """One real `/ui/chat` turn through `ui_adapters`, returning its context.

        Streaming turns are DRAINED here: the steps from `generate` on live
        inside the generator `stream_turn` returns, so a caller that never
        iterates it would be comparing half a turn. `entry` is a parameter
        because the contract test runs the same table twice with it flipped.
        """
        from core.turn.context import TurnContext
        from core.turn.run import run_turn, stream_turn
        from plugins.web_ui_module.api.turn_adapters import ui_adapters

        body = {"message": message, "session_id": session_id, "stream": streaming}
        body.update(body_extra or {})
        ctx = TurnContext(
            turn_id=f"turn-{session_id}", entry=entry, streaming=streaming,
            principal=LAB_PRINCIPAL,
            body=body, request=make_request(self.app_state), app_state=self.app_state,
        )
        adapters = ui_adapters(self.session_manager, streaming=streaming)
        # What the door actually put on the wire. On the streaming path
        # `ctx.wire` stays None — the answer IS this sequence of chunks, and
        # dropping them (which draining with `pass` used to do) leaves
        # `emit_stream` with no observable output at all. Attached to the
        # returned context, and named so nobody mistakes it for a production
        # field: `TurnContext` has no such attribute.
        chunks: list = []
        with self._patches():
            if streaming:
                async for chunk in await stream_turn(ctx, adapters):
                    chunks.append(chunk)
            else:
                await run_turn(ctx, adapters)
        ctx.lab_wire_chunks = chunks
        return ctx

    async def api(self, *, session_id: str, entry: str = "api", message: str = "hola"):
        """One real `/v1/chat/completions` turn through `api_adapters`.

        `body.stream` is False: this door's `generate` is opaque with respect
        to streaming (the SSE generator lives inside the engine forwarder — see
        `adapters_api.py`'s docstring), so its streaming shape is not a
        different walk of TURN_STEPS; it is the same walk with another object
        in `ctx.wire`.
        """
        from fastapi import BackgroundTasks

        from core.endpoints.chat_schemas import ChatCompletionRequest, Message
        from core.turn.adapters_api import api_adapters
        from core.turn.context import TurnContext
        from core.turn.run import run_turn

        body = ChatCompletionRequest(
            messages=[Message(role="user", content=message)],
            use_rag=True, stream=False, engine="ollama",
        )
        request = make_request(self.app_state)
        request.scope["headers"] = [
            (b"x-api-key", b"test-key"), (b"x-session-id", session_id.encode()),
        ]
        ctx = TurnContext(
            turn_id=f"turn-{session_id}", entry=entry, streaming=False,
            principal=LAB_PRINCIPAL,
            body=body, request=request, app_state=self.app_state,
        )
        with self._patches():
            await run_turn(ctx, api_adapters(BackgroundTasks()))
        return ctx


@pytest.fixture
def turn_lab(app_state, session_manager, memory_helper, server_state) -> TurnLab:
    """The whole machinery in one place: real sessions on disk, a real gate, a
    real turn engine, fake only where an LLM call or a network hop would be."""
    return TurnLab(app_state, session_manager, memory_helper, server_state)
