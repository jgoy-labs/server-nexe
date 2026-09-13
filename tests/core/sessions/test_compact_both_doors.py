"""Compaction belongs to the sessions, not to one door (ADR-007 C3.4).

The compactor lived inside the web UI plugin, so a long conversation was
summarised when the user talked through the browser and never when the same
thread was continued through /v1 — the window filled and the oldest turns were
simply lost.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import BackgroundTasks

from core.endpoints.chat import chat_completions  # noqa: F401 — breaks a circular import
from core.turn.adapters_api import api_adapters
from core.turn.context import TurnContext


def _session(compaction_count=0):
    s = MagicMock()
    s.id = "s-1"
    s.compaction_count = compaction_count
    return s


def _ctx_with(session):
    state = MagicMock()
    state.session_manager.get_or_create_session.return_value = session
    ctx = TurnContext(turn_id="t", entry="api")
    ctx.app_state = state
    ctx.session_id = "s-1"
    return ctx


async def test_v1_compacts_for_real_without_mocking_the_compactor():
    """The compactor is NOT mocked here, on purpose.

    The first version of this test mocked `compact_session` with a fake that
    accepted any `engine`, and it passed while /v1 could not compact at all:
    `ctx.engine` is the engine's NAME at this door, the compactor calls
    `.chat()` on what it receives, and the AttributeError was swallowed by the
    compactor's own `except Exception` and logged as a warning. Green test,
    zero compactions, and a CHANGELOG promising the opposite.
    """
    engine_module = MagicMock()

    async def _chat(**_kwargs):
        return {"response": "resum de la conversa"}

    engine_module.chat = _chat

    session = MagicMock()
    session.id = "s-1"
    session.compaction_count = 0
    session.needs_compaction.return_value = True
    session.get_messages_to_compact.return_value = [
        {"role": "user", "content": "hola " * 50},
        {"role": "assistant", "content": "ep " * 50},
    ]
    session.context_summary = ""

    def _apply(summary, compacted_count=0):
        # What the real ChatSession does: the counter is the evidence that a
        # summary was produced AND applied, not merely that a call was made.
        session.compaction_count += 1

    session.apply_compaction.side_effect = _apply

    state = MagicMock()
    state.session_manager.get_or_create_session.return_value = session
    # What the real door has: a name, and the module registry it resolves through.
    state.modules = {"ollama_module": engine_module}

    ctx = TurnContext(turn_id="t", entry="api")
    ctx.app_state = state
    ctx.session_id = "s-1"
    ctx.engine = "ollama"

    await api_adapters(BackgroundTasks())["compact"](ctx)

    session.apply_compaction.assert_called_once()
    assert session.compaction_count == 1, (
        "/v1 did not compact: the engine name never resolved to a module"
    )
    assert ctx.usage["post_commit_result"]["compact"] == {"compacted": 1}


async def test_an_engine_that_cannot_be_resolved_is_declared():
    ctx = TurnContext(turn_id="t", entry="api")
    state = MagicMock()
    state.session_manager.get_or_create_session.return_value = _session()
    state.modules = {}
    ctx.app_state = state
    ctx.session_id = "s-1"
    ctx.engine = "mlx"

    await api_adapters(BackgroundTasks())["compact"](ctx)

    assert "compact" in ctx.usage.get("degraded", {})


async def test_a_compaction_that_did_nothing_announces_nothing():
    """compact_session decides internally whether there is anything to
    summarise; a no-op must not tell the next turn a conversation was cut."""
    ctx = _ctx_with(_session())

    with patch("core.sessions.compactor.compact_session", new=AsyncMock()):
        await api_adapters(BackgroundTasks())["compact"](ctx)

    assert "compact" not in ctx.usage.get("post_commit_result", {})


async def test_without_a_session_manager_it_says_so():
    ctx = TurnContext(turn_id="t", entry="api")
    ctx.app_state = MagicMock(spec=[])  # nothing on it
    await api_adapters(BackgroundTasks())["compact"](ctx)
    assert "compact" in ctx.usage.get("degraded", {})


def test_the_step_map_says_both_doors():
    from core.turn.steps import TURN_STEPS

    step = next(s for s in TURN_STEPS if s.id == "compact")
    assert step.doors_today == frozenset({"ui", "api"})


def test_the_compactor_no_longer_lives_in_the_plugin():
    import pathlib

    import core.sessions.compactor as compactor

    path = pathlib.Path(compactor.__file__)
    assert path.parts[-2:] == ("sessions", "compactor.py")
    repo = path.parents[2]
    assert not (repo / "plugins" / "web_ui_module" / "core" / "compactor.py").exists()
