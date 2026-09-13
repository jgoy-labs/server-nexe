"""C1.2 (ADR-007): the API door walks TURN_STEPS through `run_turn`.

Two things the 20 existing API test files cannot say, because they never
needed to:

* I3, by BEHAVIOUR: the client's messages reach the session on disk BEFORE
  retrieval touches memory. Today that order is a sequence of lines in
  `chat_completions`; now it is the order of `TURN_STEPS`, and this test
  observes it — a real `SessionManager` over a tmp dir records when it saves,
  a patched `build_rag_context` records when it is asked.
* The adapter table is complete and honest: one coroutine per step, and the
  steps whose behaviour is folded into another function say where.

Mutation (exercised by hand before merging, see the diari): moving the
`mirror_v1_conversation` call from `persist_user_turn` into `emit` turns
`test_user_turn_is_on_disk_before_memory_is_asked` red.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks

from core.dependencies import limiter as _limiter
from core.endpoints.chat import chat_completions
from core.endpoints.chat_schemas import ChatCompletionRequest, Message
from core.sessions.session_manager import SessionManager
from core.turn.adapters_api import api_adapters
from core.turn.context import TurnContext
from core.turn.folded import FOLDED_BASELINE
from core.turn.gate import EngineGate
from core.turn.steps import TURN_STEPS


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    _limiter.enabled = False
    yield
    _limiter.enabled = True


@pytest.fixture
def session_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXE_ENV", "development")
    return SessionManager(storage_path=str(tmp_path / "sessions"), crypto_provider=None)


def _request(session_manager):
    req = MagicMock()
    req.app.state.config = {}
    req.app.state.modules = {}
    req.app.state.session_manager = session_manager
    # C2.1: the `generate` adapter reads ctx.app_state.engine_gate — a real
    # gate (not a MagicMock, which is not awaitable) so `await gate.acquire`
    # works; a high slot count so this test never waits on it.
    req.app.state.engine_gate = EngineGate(slots=100)
    req.headers = {"x-api-key": "test-key"}
    return req


async def test_user_turn_is_on_disk_before_memory_is_asked(session_manager, monkeypatch):
    order: list[str] = []

    real_save = session_manager.save_session

    def spy_save(session):
        order.append("disk")
        return real_save(session)

    monkeypatch.setattr(session_manager, "save_session", spy_save)

    async def fake_rag(*args, **kwargs):
        order.append("memory")
        return "", []

    body = ChatCompletionRequest(
        messages=[Message(role="user", content="recorda que em dic Aran")],
        use_rag=True, stream=False, engine="ollama",
    )
    # C4.2: retrieval is the turn's `recall` step and it calls
    # `core.endpoints.chat_rag.build_rag_context` by module — patching the
    # re-export on `chat` would no longer be on the path this turn takes.
    with patch("core.endpoints.chat_rag.build_rag_context", new=fake_rag), \
         patch("core.endpoints.chat._forward_to_ollama",
               new=AsyncMock(return_value={"choices": [{"message": {"content": "Fet."}}]})):
        result = await chat_completions(body, _request(session_manager), BackgroundTasks())

    assert order[:2] == ["disk", "memory"], order
    assert result["choices"][0]["message"]["content"] == "Fet."
    assert result["nexe_engine"] == "ollama"          # emit still decorates
    assert result["nexe_rag_status"] == "inactive"    # nothing was retrieved


async def test_adapter_table_covers_every_step_with_a_coroutine():
    table = api_adapters(BackgroundTasks())
    assert set(table) == {step.id for step in TURN_STEPS}
    for step_id, adapter in table.items():
        assert inspect.iscoroutinefunction(adapter), step_id
        assert not inspect.isasyncgenfunction(adapter), step_id


# C3.1-C3.4 took `intent`, `postprocess`, `memory.write` and `compact` out of
# this list; C4.1 took `authorize` and `sanitize`; C4.2 took the last three —
# `recall`, `clock` and `system_prompt`, which lived inside
# `_build_rag_and_system_prompt`. Nothing is folded at this door any more, and
# `core/turn/folded.py` is the count.
FOLDED_AT_THIS_DOOR: tuple[str, ...] = ()


async def test_no_step_is_folded_at_this_door():
    """C4.2: every step of the table does its own work.

    Asserted by RUNNING each one with the little it needs to get going, not by
    looping over an empty list — an assertion about a loop that never runs is
    an assertion about nothing, and it would stay green the day a step is
    folded again. What each step needs is itself the point: a real step reads
    the turn (`authorize` the principal, `sanitize` the body, `recall` and
    `system_prompt` the language and the collections) where a folded one
    needed nothing at all.
    """
    assert len(FOLDED_AT_THIS_DOOR) == FOLDED_BASELINE["api"] == 0, (
        "this door's folded list and core/turn/folded.py disagree"
    )
    table = api_adapters(BackgroundTasks())
    body = ChatCompletionRequest(
        messages=[Message(role="user", content="hola")], use_rag=True, stream=False,
    )

    async def _no_rag(*_a, **_kw):
        return "", []

    with patch("core.endpoints.chat_rag.build_rag_context", new=_no_rag):
        for step_id in ("authorize", "sanitize", "recall", "clock", "system_prompt",
                        "intent", "postprocess", "memory.write", "compact"):
            probe = TurnContext(
                turn_id="t", entry="api", principal="a-real-key", lang="ca",
                body=ChatCompletionRequest(**body.model_dump()),
                app_state=SimpleNamespace(config={}),
            )
            probe.message = "hola"
            await table[step_id](probe)
            assert step_id not in probe.usage.get("folded", {}), (
                f"{step_id} is folded again at /v1"
            )
        assert "folded" not in TurnContext(turn_id="t", entry="api").usage


async def test_the_three_steps_c42_unfolded_do_their_work():
    """Not just "not folded": each of C4.2's three writes what its step is for.

    `recall` fills the turn's retrieval, `clock` its time line, `system_prompt`
    its prompt. A step that returned early would satisfy the test above and
    leave the turn exactly as empty as a folded one did.
    """
    table = api_adapters(BackgroundTasks())

    async def _found(*_a, **_kw):
        return "un fet recuperat", [("personal_memory", 0.9)]

    ctx = TurnContext(
        turn_id="t", entry="api", lang="ca",
        body=ChatCompletionRequest(
            messages=[Message(role="user", content="quina hora és?")], use_rag=True,
        ),
        app_state=SimpleNamespace(config={}),
    )
    ctx.message = "quina hora és?"
    with patch("core.endpoints.chat_rag.build_rag_context", new=_found):
        await table["recall"](ctx)
    await table["clock"](ctx)
    await table["system_prompt"](ctx)

    assert ctx.recall_text == "un fet recuperat"
    assert ctx.recall == [("personal_memory", 0.9)]
    assert "Hora actual del sistema" in ctx.clock_line
    assert ctx.system_prompt, "the system prompt step wrote nothing"
