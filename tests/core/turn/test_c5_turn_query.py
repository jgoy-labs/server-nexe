"""C5 part F (D2, D3) — what a recent turn did, asked by its id.

`TurnStore` is a sink of the TraceSink port: a turn is in it from its first event,
its post-commit jobs join the same record, and it is `final` when nothing is
pending. `GET /v1/turns/{turn_id}/trace` serves it behind the API key. The id is
`X-Nexe-Turn-Id`, now on JSON answers too. The user's text is never in it.
"""
from __future__ import annotations

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.turn.context import TurnContext
from core.turn.gate import EngineGate
from core.turn.post_commit import PostCommitQueue
from core.turn.run import run_turn
from core.turn.steps import TURN_STEPS
from core.turn.trace import LogSink, StepEvent
from core.turn.turn_store import TurnStore

from ._c48_p0_lab import DOORS, build_world, run_door

ALL_IDS = tuple(s.id for s in TURN_STEPS)
KEY = "turn-query-key-1"


def _event(turn_id: str, step: str, **kw) -> StepEvent:
    base = dict(turn_id=turn_id, entry="api", streaming=False, step=step, kind="compute",
                started_at=0.0, duration_ms=1.0, outcome="ok")
    base.update(kw)
    return StepEvent(**base)


@pytest.mark.parametrize("door", DOORS)
async def test_the_id_of_each_shape_of_turn_finds_its_trace(turn_lab, door):
    store = TurnStore()
    turn_lab.app_state.trace_sinks = (store, LogSink())
    world = build_world({}, live=["mlx"])
    seen = await run_door(turn_lab, world, door, backend="mlx", sid=f"c5f-{door}")
    record = store.get(seen.ctx.turn_id)
    assert record is not None and record["final"] is True
    assert sorted(s["step"] for s in record["steps"]) == sorted(ALL_IDS)
    assert record["entry"] == ("api" if door.startswith("v1") else "ui")
    assert record["engine"] == "mlx"


def test_a_turn_in_progress_is_there_from_its_first_event_and_not_final():
    store = TurnStore()
    store.on_step(_event("t1", "validate"))
    store.on_step(_event("t1", "authorize"))
    record = store.get("t1")
    assert [s["step"] for s in record["steps"]] == ["validate", "authorize"]
    assert record["final"] is False


async def test_the_post_commit_jobs_join_the_same_record_and_it_ends_when_they_do():
    store = TurnStore()
    queue = PostCommitQueue(EngineGate(slots=1))
    ctx = TurnContext(turn_id="t-pc", entry="api", message="hola", app_state=_State(store))

    async def noop(c):
        return None

    await run_turn(ctx, {s: noop for s in ALL_IDS}, post_commit=queue)
    mid = store.get("t-pc")
    assert mid["final"] is False and sorted(mid["pending"]) == ["compact", "describe_image"]
    queue.start()
    try:
        await queue.drain()
    finally:
        await queue.stop()
    end = store.get("t-pc")
    assert end["final"] is True and end["pending"] == []
    assert sorted(s["step"] for s in end["steps"]) == sorted(ALL_IDS)


class _State:
    def __init__(self, *sinks) -> None:
        self.trace_sinks = tuple(sinks)


async def test_a_superseded_job_does_not_keep_its_turn_pending_for_ever():
    store = TurnStore()
    queue = PostCommitQueue(EngineGate(slots=1))

    async def noop(c):
        return None

    for turn in ("t-old", "t-new"):
        ctx = TurnContext(turn_id=turn, entry="api", session_id="s", app_state=_State(store))
        await run_turn(ctx, {s: noop for s in ALL_IDS}, post_commit=queue)
    queue.start()
    try:
        await queue.drain()
    finally:
        await queue.stop()
    assert store.get("t-old")["final"] is True and store.get("t-new")["final"] is True


def test_the_oldest_turn_leaves_the_ring_first():
    store = TurnStore(capacity=3)
    for i in range(5):
        store.on_step(_event(f"t{i}", "validate"))
    assert [store.get(f"t{i}") is not None for i in range(5)] == [False, False, True, True, True]


async def test_what_the_user_wrote_is_in_neither_the_trace_nor_the_line(turn_lab, caplog):
    caplog.set_level(logging.INFO)
    store = TurnStore()
    turn_lab.app_state.trace_sinks = (store, LogSink())
    world = build_world({}, live=["mlx"])
    seen = await run_door(turn_lab, world, "v1_json", backend="mlx", sid="c5f-secret",
                          message="LA-CONTRASENYA-ES-PINYA-COLADA-42")
    assert "PINYA-COLADA" not in json.dumps(store.get(seen.ctx.turn_id))
    assert not [r for r in caplog.records if r.name == "nexe.turn.trace" and "PINYA-COLADA" in r.getMessage()]


@pytest.mark.parametrize("door", ["v1_json", "ui_json"])
async def test_a_json_answer_carries_the_turn_id_in_its_headers(turn_lab, door):
    world = build_world({}, live=["mlx"])
    seen = await run_door(turn_lab, world, door, backend="mlx", sid=f"c5f-h-{door}")
    assert seen.json_headers.get("x-nexe-turn-id") == seen.ctx.turn_id


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", KEY)
    from slowapi import Limiter
    from slowapi.util import get_remote_address

    from core.endpoints.v1 import router_v1

    app = FastAPI()
    app.state.limiter = Limiter(key_func=get_remote_address)
    app.include_router(router_v1)
    store = TurnStore()
    store.on_step(_event("abc123", "validate"))
    app.state.trace_sinks = (store,)
    return TestClient(app, raise_server_exceptions=False)


def test_the_route_needs_the_key(client):
    assert client.get("/v1/turns/abc123/trace").status_code == 401


def test_the_route_answers_a_known_turn_and_404s_an_unknown_or_malformed_one(client):
    headers = {"X-Api-Key": KEY}
    ok = client.get("/v1/turns/abc123/trace", headers=headers)
    assert ok.status_code == 200 and ok.json()["turn_id"] == "abc123"
    assert client.get("/v1/turns/nope/trace", headers=headers).status_code == 404
    assert client.get("/v1/turns/..%2Fetc/trace", headers=headers).status_code == 404


def test_without_a_store_there_is_a_404_not_a_500(client):
    client.app.state.trace_sinks = (LogSink(),)
    assert client.get("/v1/turns/abc123/trace", headers={"X-Api-Key": KEY}).status_code == 404


def test_the_lifespan_wires_the_log_the_metrics_and_the_store():
    from types import SimpleNamespace

    from core.lifespan_sessions import _expose_trace_sinks
    from core.turn.metrics_sink import MetricsSink

    app = SimpleNamespace(state=SimpleNamespace())
    _expose_trace_sinks(app)
    assert [type(s) for s in app.state.trace_sinks] == [LogSink, MetricsSink, TurnStore]


# ---- review of 13/10 (independent pass) ------------------------------------------------------

def test_the_trace_names_what_degraded_and_never_the_exceptions_words():
    store = TurnStore()
    store.on_step(_event("t-r1", "memory.write", outcome="degraded",
                         degraded_reason="ValidationError: input_value='LA-CONTRASENYA-42'"))
    shown = store.get("t-r1")["steps"][0]
    assert shown["degraded_reason"] == "ValidationError"
    assert "CONTRASENYA" not in json.dumps(store.get("t-r1"))


def test_a_job_of_a_turn_that_left_the_ring_does_not_bring_it_back():
    store = TurnStore(capacity=2)
    store.on_step(_event("old", "validate"))
    store.on_step(_event("a", "validate"))
    store.on_step(_event("b", "validate"))  # `old` leaves
    store.on_step(_event("old", "compact", late=True))
    assert store.get("old") is None and store.get("a") is not None and store.get("b") is not None


def test_a_call_the_turns_line_already_carries_is_not_counted_again_when_its_job_ends():
    store = TurnStore()
    call = {"step": "compact", "engine": "mlx", "ms": 5.0, "at": 123.0}
    store.on_step(_event("t-r2", "validate"))
    store.on_turn(None, {"turn_id": "t-r2", "entry": "api", "streaming": False, "engine": "mlx",
                         "engine_fallback_from": None, "left_machine": False, "partial": False,
                         "llm": {"calls": [call], "total_calls": 1, "total_ms": 5.0},
                         "post_commit_pending": ["compact"]})
    store.on_step(_event("t-r2", "compact", late=True, calls=(call,)))
    assert store.get("t-r2")["llm"]["total_calls"] == 1


def test_a_turn_that_fell_at_a_step_it_could_not_do_without_is_final():
    store = TurnStore()
    store.on_step(_event("t-r3", "validate", outcome="failed", error_code="http_400"))
    assert store.get("t-r3")["final"] is True


async def test_a_re_prompt_that_was_cut_is_not_counted_as_a_success():
    import asyncio

    from starlette.datastructures import State

    from core.turn import policy

    async def slow():
        yield "a"
        raise asyncio.CancelledError

    state = State()
    state.engine_gate = EngineGate(slots=1)
    ctx = TurnContext(turn_id="t-r4", entry="ui", app_state=state, system_prompt="s", lang="ca")
    with pytest.raises(asyncio.CancelledError):
        _ = [c async for c in policy.reprompt_chunks(ctx, ["f"], call=lambda s: slow(), engine_name="mlx", model=None)]
    assert [a["ok"] for a in ctx.usage["engine_attempts"]] == [False]
