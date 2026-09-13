"""#1041 (C2.5): a per-turn deadline, measured at C2.0, not guessed.

`resolve_deadline_s` is a pure function (its own tests, fast); the mechanism
end-to-end is exercised through `/v1`'s `generate` adapter with a fake MLX
module (same `_Engine` shape `test_fd_block5_engine_routing.py` uses, so it
carries a real `_node` and passes `_engine_available`) that hangs until
`cancel_event` fires. The UI's own `_arm_deadline` reuses the exact same
`cancel_event` the client-disconnect monitor already sets — a mechanism
`test_session_lease.py`/`test_turn_lease.py` and every MC-011 test already
exercise for the disconnect case — so it only needs its own timer verified,
not the whole HTTP harness again.

Mutation (exercised by hand before merging, see the diari): dropping the
`call_later` in `adapters_api.py::generate` (so `cancel_event` is never armed
by the deadline) turns `test_deadline_cuts_a_hanging_mlx_turn` red — the fake
engine's own `AssertionError("cancel_event was never set")` fires instead.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import BackgroundTasks
from unittest.mock import AsyncMock, MagicMock

from core.endpoints.chat import chat_completions  # noqa: F401 (breaks a circular import, see test_api_turn_order.py)
from core.turn.adapters_api import api_adapters
from core.turn.context import TurnContext
from core.turn.deadline import DEFAULT_DEADLINE_S, ENV_DEADLINE_S, resolve_deadline_s
from tests.core.test_fd_block5_engine_routing import _Engine, _state


class TestResolveDeadlineS:

    def test_default_is_the_measured_value(self, monkeypatch):
        monkeypatch.delenv(ENV_DEADLINE_S, raising=False)
        assert resolve_deadline_s() == DEFAULT_DEADLINE_S

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv(ENV_DEADLINE_S, "5")
        assert resolve_deadline_s() == 5.0

    def test_zero_disables_it(self, monkeypatch):
        monkeypatch.setenv(ENV_DEADLINE_S, "0")
        assert resolve_deadline_s() == 0.0

    def test_unparsable_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv(ENV_DEADLINE_S, "not-a-number")
        assert resolve_deadline_s() == DEFAULT_DEADLINE_S


class _HangingEngine(_Engine):
    """MLX-shaped (no 'model' param): hangs until cancel_event fires, exactly
    like a real generation loop stuck on a slow token — the deadline's whole
    reason to exist."""

    async def chat(self, messages, system="", session_id="default",
                    stream_callback=None, cancel_event=None, **kwargs):
        self.calls += 1
        start = time.monotonic()
        while time.monotonic() - start < 5.0:
            if cancel_event is not None and cancel_event.is_set():
                return {
                    "response": "cut short", "tokens": 1, "prompt_tokens": 0,
                    "context_used": 0, "tokens_per_second": 0.0, "system_tokens": 0,
                    "elapsed_ms": 1, "model_used": "fake", "session_id": session_id,
                    "cache_hit": False, "timing": {},
                }
            await asyncio.sleep(0.01)
        raise AssertionError("cancel_event was never set — the deadline did not fire")


def _v1_request(state) -> MagicMock:
    request = MagicMock()
    request.app.state = state
    request.is_disconnected = AsyncMock(return_value=False)
    request.headers.get = lambda key, default=None: default if default is not None else ""
    return request


def _v1_body(**overrides) -> MagicMock:
    fields = {
        "messages": [], "engine": "mlx", "force_lease": False, "stream": False,
        "max_tokens": None, "temperature": None, "top_p": None,
    }
    fields.update(overrides)
    return MagicMock(**fields)


@pytest.mark.asyncio
async def test_deadline_cuts_a_hanging_mlx_turn():
    engine = _HangingEngine()
    state = _state(mlx=engine)
    state.session_manager = None

    ctx = TurnContext(
        turn_id="deadline-t1", entry="api", session_id="sid", body=_v1_body(),
        request=_v1_request(state), app_state=state, message="hola", prompt=[],
        engine="mlx", engine_fallback_from=None, deadline=0.1,
    )
    await api_adapters(BackgroundTasks())["generate"](ctx)

    assert engine.calls == 1
    assert ctx.wire["choices"][0]["message"]["content"] == "cut short"


@pytest.mark.asyncio
async def test_zero_deadline_never_cancels():
    """0 disables the deadline (config contract) — a turn under the 5s the
    fake engine allows finishes on its own, cancel_event never set."""
    engine = _Engine(reply="finished normally")
    state = _state(mlx=engine)
    state.session_manager = None

    ctx = TurnContext(
        turn_id="deadline-t2", entry="api", session_id="sid", body=_v1_body(),
        request=_v1_request(state), app_state=state, message="hola", prompt=[],
        engine="mlx", engine_fallback_from=None, deadline=0.0,
    )
    await api_adapters(BackgroundTasks())["generate"](ctx)

    cancel_event, _monitor = ctx.cancel_token
    assert not cancel_event.is_set()
    assert ctx.wire["choices"][0]["message"]["content"] == "finished normally"
