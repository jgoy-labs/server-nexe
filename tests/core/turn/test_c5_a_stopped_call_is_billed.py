"""C5 part C (#1160-b, D6) — a call the client stops is still on the bill.

Until C, `generate` billed its LLM call after the token loop: a Stop (or a dropped
connection) skipped it, and the turn's line said `calls=0` for an engine that had
been asked and had run. Now the call is billed `cancelled`, with the time it ran;
a call that finished is billed once, `ok`.
"""
from __future__ import annotations

import json
import logging

import pytest

from ._c48_p0_lab import STOP_AFTER, build_world, run_door
from .test_c5_p0_trace_matrix import LOGGER, _lines

#: Chunks read before the client leaves, per door: after the engine started, before it ended.
CUT_AT = {"v1_stream": 1, "ui_stream": 4}


async def _cut(turn_lab, caplog, door: str, *, engine: str = "mlx") -> list[dict]:
    caplog.set_level(logging.INFO, logger=LOGGER)
    STOP_AFTER["chunks"] = CUT_AT[door]
    try:
        world = build_world({}, live=["mlx", "llama_cpp"])
        await run_door(turn_lab, world, door, backend=engine, sid=f"c5c-{door}")
    finally:
        STOP_AFTER["chunks"] = None
    return _lines(caplog)


@pytest.mark.parametrize("door", list(CUT_AT))
async def test_a_stopped_stream_bills_one_cancelled_call(turn_lab, caplog, door):
    lines = await _cut(turn_lab, caplog, door)
    assert len(lines) == 1
    calls = [c for c in lines[0]["llm"]["calls"] if c["step"] == "generate"]
    assert [(c["engine"], c["outcome"]) for c in calls] == [("mlx", "cancelled")]
    assert calls[0]["ms"] > 0
    assert lines[0]["llm"]["total_calls"] == 1


@pytest.mark.parametrize("door", list(CUT_AT))
async def test_a_stream_read_to_the_end_bills_one_ok_call(turn_lab, caplog, door):
    caplog.set_level(logging.INFO, logger=LOGGER)
    world = build_world({}, live=["mlx", "llama_cpp"])
    await run_door(turn_lab, world, door, backend="mlx", sid=f"c5c-ok-{door}")
    calls = [c for l in _lines(caplog) for c in l["llm"]["calls"] if c["step"] == "generate"]
    assert [(c["engine"], c["outcome"]) for c in calls[-1:]] == [("mlx", "ok")]
    assert lines_total(caplog) == 1


def lines_total(caplog) -> int:
    return _lines(caplog)[-1]["llm"]["total_calls"]


@pytest.mark.parametrize("door", list(CUT_AT))
async def test_the_turns_left_machine_and_its_calls_agree(turn_lab, caplog, door):
    """9fd4ebbc: a line that said the turn left the machine while no call did (or the
    other way round) was a line nobody could trust."""
    line = (await _cut(turn_lab, caplog, door))[0]
    assert line["left_machine"] == any(c["left_machine"] for c in line["llm"]["calls"])


@pytest.mark.parametrize("door", ["ui_json", "v1_json"])
async def test_a_json_turn_cancelled_while_the_engine_answers_bills_the_call(turn_lab, caplog, door):
    """No stream, so nothing is read and cut: the request's task is cancelled while
    the engine is still working — the line is left, and the call is on it."""
    import asyncio

    caplog.set_level(logging.INFO, logger=LOGGER)
    world = build_world({}, live=["mlx"], delay=5.0)
    task = asyncio.create_task(run_door(turn_lab, world, door, backend="mlx", sid=f"c5c-json-{door}"))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    lines = _lines(caplog)
    assert len(lines) == 1
    calls = [c for c in lines[0]["llm"].get("calls", []) if c["step"] == "generate"]
    assert [(c["engine"], c["outcome"]) for c in calls] == [("mlx", "cancelled")]
    assert calls[0]["ms"] > 0


async def test_an_engine_that_breaks_mid_stream_is_billed_failed_not_cancelled(turn_lab, caplog, monkeypatch):
    """Review 13/10: the bill said `cancelled` for any way out of the loop but a good one."""
    import core.turn.adapters_api as api

    async def broken(ctx, response, cleaner):
        raise RuntimeError("engine died")
        yield  # pragma: no cover

    monkeypatch.setattr(api, "_drain_engine", broken)
    caplog.set_level(logging.INFO, logger=LOGGER)
    world = build_world({}, live=["mlx", "llama_cpp"])
    await run_door(turn_lab, world, "v1_stream", backend="mlx", sid="c5c-broken")
    calls = [c for l in _lines(caplog) for c in l["llm"].get("calls", []) if c["step"] == "generate"]
    assert [c["outcome"] for c in calls] == ["failed"]


@pytest.mark.parametrize("chunks, billed", [(1, []), (2, ["cancelled"]), (3, ["cancelled"]), (4, ["cancelled"])])
async def test_a_web_client_that_leaves_before_the_first_token_is_billed_once_the_engine_took_the_call(
        turn_lab, caplog, chunks, billed):
    """Review 13/10, P3: the engine/model labels go out before the token loop; leaving there billed
    nothing. Chunk 1 is the headers, sent before any engine is asked: no call, no bill."""
    caplog.set_level(logging.INFO, logger=LOGGER)
    STOP_AFTER["chunks"] = chunks
    try:
        world = build_world({}, live=["mlx"])
        await run_door(turn_lab, world, "ui_stream", backend="mlx", sid=f"c5c-any-{chunks}")
    finally:
        STOP_AFTER["chunks"] = None
    line = _lines(caplog)[0]
    assert [c["outcome"] for c in line["llm"].get("calls", []) if c["step"] == "generate"] == billed
