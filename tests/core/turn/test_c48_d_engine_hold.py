"""C4.8-d: the engine hold (gate slot + disconnect monitor + deadline), on its own.

Four `generate` bodies used to repeat the same acquire-and-release; the part 0
matrix (rows B6) pins what a client sees of it at each door, and this file pins
the hold itself: what it starts, what it stops, and who stops it.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from core.turn.context import TurnContext
from core.turn.engine_hold import EngineHold, cancel_monitor
from core.turn.gate import EngineGate


class _Request:
    """Never disconnects, unless told to."""

    def __init__(self) -> None:
        self.gone = False

    async def is_disconnected(self) -> bool:
        return self.gone


class _State:
    def __init__(self, gate: EngineGate) -> None:
        self.engine_gate = gate


def _ctx(gate: EngineGate, *, deadline=None, request=None) -> TurnContext:
    return TurnContext(
        turn_id="t1", request=request or _Request(), app_state=_State(gate), deadline=deadline,
    )


async def test_it_takes_the_slot_and_publishes_what_the_turn_needs():
    gate = EngineGate(slots=1)
    ctx = _ctx(gate)
    async with EngineHold(ctx) as hold:
        assert len(gate._holders) == 1
        assert ctx.gpu_slot is next(iter(gate._holders.values()))
        assert ctx.cancel_token == (hold.cancel_event, hold.monitor)
        assert not hold.cancel_event.is_set()
        assert ctx.gpu_slot.holder == "t1" and ctx.gpu_slot.cancel is hold.cancel_event
    assert len(gate._holders) == 0


async def test_leaving_the_block_stops_the_monitor_and_gives_the_slot_back():
    gate = EngineGate(slots=1)
    ctx = _ctx(gate)
    async with EngineHold(ctx) as hold:
        monitor = hold.monitor
    await asyncio.sleep(0)
    assert monitor.done()
    assert len(gate._holders) == 0


async def test_an_error_inside_the_block_still_releases_everything():
    gate = EngineGate(slots=1)
    ctx = _ctx(gate)
    with pytest.raises(RuntimeError, match="boom"):
        async with EngineHold(ctx) as hold:
            monitor = hold.monitor
            raise RuntimeError("boom")
    await asyncio.sleep(0)
    assert monitor.done() and len(gate._holders) == 0


async def test_keep_monitor_leaves_it_running_for_the_persistence_step():
    gate = EngineGate(slots=1)
    ctx = _ctx(gate)
    async with EngineHold(ctx, keep_monitor=True) as hold:
        monitor = hold.monitor
    await asyncio.sleep(0)
    assert not monitor.done()
    assert len(gate._holders) == 0  # the slot is given back all the same
    cancel_monitor(ctx)
    await asyncio.sleep(0)
    assert monitor.done()


async def test_the_deadline_sets_the_same_event_a_client_leaving_would():
    gate = EngineGate(slots=1)
    ctx = _ctx(gate, deadline=0.05)
    async with EngineHold(ctx) as hold:
        assert not hold.cancel_event.is_set()
        await asyncio.sleep(0.2)
        assert hold.cancel_event.is_set()


async def test_without_a_deadline_the_event_stays_clear():
    gate = EngineGate(slots=1)
    ctx = _ctx(gate, deadline=None)
    async with EngineHold(ctx) as hold:
        await asyncio.sleep(0.05)
        assert not hold.cancel_event.is_set()


async def test_leaving_the_block_cancels_a_deadline_that_has_not_fired():
    gate = EngineGate(slots=1)
    ctx = _ctx(gate, deadline=0.1)
    async with EngineHold(ctx) as hold:
        event = hold.cancel_event
    await asyncio.sleep(0.25)
    assert not event.is_set()


async def test_a_client_that_leaves_sets_the_event():
    gate = EngineGate(slots=1)
    request = _Request()
    ctx = _ctx(gate, request=request)
    async with EngineHold(ctx) as hold:
        request.gone = True
        for _ in range(40):
            if hold.cancel_event.is_set():
                break
            await asyncio.sleep(0.05)
        assert hold.cancel_event.is_set()


async def test_a_busy_gate_is_a_429_and_nothing_is_left_running(monkeypatch):
    monkeypatch.setenv("NEXE_ENGINE_GATE_WAIT_S", "0.05")
    gate = EngineGate(slots=1)
    first = _ctx(gate)
    async with EngineHold(first):
        second = _ctx(gate, deadline=30)
        hold = EngineHold(second)
        with pytest.raises(HTTPException) as caught:
            await hold.open()
        assert caught.value.status_code == 429
        assert caught.value.detail == "Server busy, try again in a moment"  # the wording clients see
        await asyncio.sleep(0)
        assert hold.monitor.done()
        assert hold._deadline.cancelled()
        assert second.gpu_slot is None
    assert len(gate._holders) == 0


async def test_a_busy_gate_stops_the_monitor_even_when_it_would_be_kept(monkeypatch):
    monkeypatch.setenv("NEXE_ENGINE_GATE_WAIT_S", "0.05")
    gate = EngineGate(slots=1)
    async with EngineHold(_ctx(gate)):
        hold = EngineHold(_ctx(gate), keep_monitor=True)
        with pytest.raises(HTTPException):
            await hold.open()
        await asyncio.sleep(0)
        assert hold.monitor.done()


async def test_release_is_idempotent():
    gate = EngineGate(slots=1)
    hold = await EngineHold(_ctx(gate)).open()
    calls = []
    real = gate.release

    async def counting(slot):
        calls.append(slot)
        await real(slot)

    gate.release = counting
    await hold.release()
    await hold.release()
    assert len(calls) == 1
    assert len(gate._holders) == 0
    other = _ctx(gate)
    async with EngineHold(other):  # the slot really is free again
        assert len(gate._holders) == 1


async def test_a_hold_handed_over_is_not_released_by_the_block():
    gate = EngineGate(slots=1)
    ctx = _ctx(gate)
    async with EngineHold(ctx) as hold:
        release = hold.hand_over()
        monitor = hold.monitor
    assert len(gate._holders) == 1 and not monitor.done()
    await release()
    await asyncio.sleep(0)
    assert len(gate._holders) == 0 and monitor.done()


async def test_cancel_monitor_without_a_token_does_nothing():
    cancel_monitor(TurnContext(turn_id="t"))


async def test_cancel_monitor_leaves_a_finished_task_alone():
    ctx = TurnContext(turn_id="t")

    async def quick():
        return None

    task = asyncio.create_task(quick())
    await task
    ctx.cancel_token = (None, task)
    cancel_monitor(ctx)
    assert not task.cancelled()
    ctx.cancel_token = (None, None)
    cancel_monitor(ctx)


async def test_it_asks_for_the_user_turn_priority_and_preempts_a_background_job():
    from core.turn.gate import Priority
    import threading

    gate = EngineGate(slots=1)
    background_cancel = threading.Event()
    slot = await gate.acquire(Priority.COMPACT, holder="job", cancel_event=background_cancel, timeout=1)

    async def free_it_when_asked():
        for _ in range(100):
            if background_cancel.is_set():
                await gate.release(slot)
                return
            await asyncio.sleep(0.01)

    task = asyncio.create_task(free_it_when_asked())
    ctx = _ctx(gate)
    async with EngineHold(ctx):
        assert background_cancel.is_set()
        assert ctx.gpu_slot.priority is Priority.USER_TURN
    await task


# ───────────────────────── how the doors use it (what a hold's owner must keep) ──


async def test_the_web_stream_keeps_its_monitor_alive_until_the_turn_persists(turn_lab, monkeypatch):
    """The monitor outlives `generate` (`keep_monitor`): `postprocess` and the
    re-prompt still need to know whether the client is there, and
    `persist_stream` is what stops it.

    Observed from inside `postprocess` through the one call it makes first
    (`wire._gen_truncated_token`), not by replacing a step in the adapter
    table: the table's first build imports `routes_chat`, which would then keep
    the replacement for every later test of the session."""
    from plugins.web_ui_module.api import wire

    seen: dict = {}
    real = wire._gen_truncated_token

    def spy(*args, **kwargs):
        monitors = [t for t in asyncio.all_tasks() if "_monitor_disconnect" in repr(t.get_coro())]
        seen["alive"] = [not t.done() and t.cancelling() == 0 for t in monitors]
        return real(*args, **kwargs)

    monkeypatch.setattr(wire, "_gen_truncated_token", spy)
    ctx = await turn_lab.ui(streaming=True, session_id="c48d-keep")
    assert seen["alive"] == [True]
    await asyncio.sleep(0)
    assert ctx.cancel_token[1].done()  # and `persist_stream` did stop it
    stream_ctx = ctx.usage["ui"]["stream_ctx"]
    assert stream_ctx.disconnect_monitor_task is ctx.cancel_token[1]


def _v1_ctx(gate, request=None, *, stream: bool):
    from core.endpoints.chat_schemas import ChatCompletionRequest, Message

    body = ChatCompletionRequest(messages=[Message(role="user", content="hi")], stream=stream)
    ctx = TurnContext(turn_id="t-v1", body=body, request=request or _Request(), app_state=_State(gate))
    ctx.prompt = [{"role": "user", "content": "hi"}]
    ctx.engine = "ollama"
    ctx.session_id = "s1"
    return ctx


async def test_v1_json_that_got_a_stream_hands_the_slot_to_the_wrapped_body():
    """A streaming response coming out of the non-streaming `generate`: the slot
    outlives the step and is given back when the body ends — not before."""
    from unittest.mock import AsyncMock, patch

    from fastapi import BackgroundTasks
    from fastapi.responses import StreamingResponse

    from core.turn.adapters_api import api_adapters

    async def body():
        yield "data: {}\n\n"

    response = StreamingResponse(body(), media_type="text/event-stream")
    cascade = AsyncMock(return_value=(response, "ollama", None, "preferred_unavailable", "m"))
    gate = EngineGate(slots=1)
    ctx = _v1_ctx(gate, stream=True)
    with patch("core.turn.api_cascade.dispatch_v1", new=cascade):
        await api_adapters(BackgroundTasks())["generate"](ctx)
    assert len(gate._holders) == 1  # still held: the body has not been read
    assert not ctx.cancel_token[1].done()
    async for _ in ctx.wire.body_iterator:
        pass
    await asyncio.sleep(0)
    assert len(gate._holders) == 0 and ctx.cancel_token[1].done()


async def test_v1_json_that_got_a_stream_releases_when_the_client_leaves_mid_body():
    from unittest.mock import AsyncMock, patch

    from fastapi import BackgroundTasks
    from fastapi.responses import StreamingResponse

    from core.turn.adapters_api import api_adapters

    async def body():
        yield "data: {}\n\n"
        yield "data: {}\n\n"

    response = StreamingResponse(body(), media_type="text/event-stream")
    cascade = AsyncMock(return_value=(response, "ollama", None, "preferred_unavailable", "m"))
    gate = EngineGate(slots=1)
    ctx = _v1_ctx(gate, stream=True)
    with patch("core.turn.api_cascade.dispatch_v1", new=cascade):
        await api_adapters(BackgroundTasks())["generate"](ctx)
    iterator = ctx.wire.body_iterator
    await iterator.__anext__()
    await iterator.aclose()
    assert len(gate._holders) == 0


async def test_v1_stream_gives_the_slot_back_when_the_cascade_fails():
    from unittest.mock import AsyncMock, patch

    from fastapi import BackgroundTasks

    from core.turn.adapters_api import api_adapters

    cascade = AsyncMock(side_effect=RuntimeError("every engine failed"))
    gate = EngineGate(slots=1)
    ctx = _v1_ctx(gate, stream=True)
    with patch("core.turn.api_cascade.dispatch_v1", new=cascade):
        with pytest.raises(RuntimeError, match="every engine failed"):
            async for _ in api_adapters(BackgroundTasks(), streaming=True)["generate"](ctx):
                pass
    await asyncio.sleep(0)
    assert len(gate._holders) == 0 and ctx.cancel_token[1].done()


async def test_v1_json_gives_the_slot_back_when_the_cascade_fails():
    from unittest.mock import AsyncMock, patch

    from fastapi import BackgroundTasks

    from core.turn.adapters_api import api_adapters

    cascade = AsyncMock(side_effect=RuntimeError("every engine failed"))
    gate = EngineGate(slots=1)
    ctx = _v1_ctx(gate, stream=False)
    with patch("core.turn.api_cascade.dispatch_v1", new=cascade):
        with pytest.raises(RuntimeError, match="every engine failed"):
            await api_adapters(BackgroundTasks())["generate"](ctx)
    await asyncio.sleep(0)
    assert len(gate._holders) == 0 and ctx.cancel_token[1].done()


async def test_v1_stream_gives_the_slot_back_when_it_ends_cleanly_and_when_the_client_leaves():
    from unittest.mock import AsyncMock, patch

    from fastapi import BackgroundTasks
    from fastapi.responses import StreamingResponse

    from core.endpoints.chat_engines._streaming import format_sse_chunk, stream_end
    from core.turn.adapters_api import api_adapters

    async def body():
        yield format_sse_chunk("hola", "m", "ollama")
        yield format_sse_chunk("mon", "m", "ollama")
        yield stream_end()

    for leave_early in (False, True):
        response = StreamingResponse(body(), media_type="text/event-stream")
        cascade = AsyncMock(return_value=(response, "ollama", None, "preferred_unavailable", "m"))
        gate = EngineGate(slots=1)
        ctx = _v1_ctx(gate, stream=True)
        with patch("core.turn.api_cascade.dispatch_v1", new=cascade):
            generator = api_adapters(BackgroundTasks(), streaming=True)["generate"](ctx)
            await generator.__anext__()  # the role chunk: the slot is held while the answer runs
            assert len(gate._holders) == 1
            if leave_early:
                await generator.aclose()
            else:
                async for _ in generator:
                    pass
        await asyncio.sleep(0)
        assert len(gate._holders) == 0 and ctx.cancel_token[1].done()


async def test_web_json_ends_with_its_monitor_stopped_and_the_slot_free(turn_lab):
    ctx = await turn_lab.ui(streaming=False, session_id="c48d-json-end")
    await asyncio.sleep(0)
    assert ctx.cancel_token[1].done()
    assert len(turn_lab.app_state.engine_gate._holders) == 0


async def test_a_cancel_while_waiting_for_the_slot_leaves_nothing_running(monkeypatch):
    monkeypatch.setenv("NEXE_ENGINE_GATE_WAIT_S", "30")
    gate = EngineGate(slots=1)
    async with EngineHold(_ctx(gate)):
        second = _ctx(gate, deadline=30)
        hold = EngineHold(second)
        waiting = asyncio.create_task(hold.open())
        await asyncio.sleep(0.05)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        await asyncio.sleep(0)
        assert hold.monitor.done()
        assert hold._deadline.cancelled()
    assert len(gate._holders) == 0


async def test_a_cancel_while_giving_the_slot_back_can_be_retried():
    gate = EngineGate(slots=1)
    hold = await EngineHold(_ctx(gate)).open()
    real = gate.release
    gate_calls = []

    async def cancelled_once(slot):
        gate_calls.append(slot)
        if len(gate_calls) == 1:
            raise asyncio.CancelledError()
        await real(slot)

    gate.release = cancelled_once
    with pytest.raises(asyncio.CancelledError):
        await hold.release()
    assert len(gate._holders) == 1  # the slot was not given back
    await hold.release()            # and a second try does
    assert len(gate._holders) == 0 and len(gate_calls) == 2


async def test_a_failure_before_the_body_takes_over_still_releases_the_slot():
    """`hand_over()` comes last: if building the cleaner fails, the block is
    still the owner and gives the slot back."""
    from unittest.mock import AsyncMock, patch

    from fastapi import BackgroundTasks
    from fastapi.responses import StreamingResponse

    from core.turn.adapters_api import api_adapters

    async def body():
        yield "data: {}\n\n"

    response = StreamingResponse(body(), media_type="text/event-stream")
    cascade = AsyncMock(return_value=(response, "ollama", None, "preferred_unavailable", "m"))
    gate = EngineGate(slots=1)
    ctx = _v1_ctx(gate, stream=True)
    with patch("core.turn.api_cascade.dispatch_v1", new=cascade), \
            patch("core.turn.adapters_api.SseCleaner", side_effect=RuntimeError("cleaner broke")):
        with pytest.raises(RuntimeError, match="cleaner broke"):
            await api_adapters(BackgroundTasks())["generate"](ctx)
    await asyncio.sleep(0)
    assert len(gate._holders) == 0 and ctx.cancel_token[1].done()
