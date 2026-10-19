"""API providers, phase 3 — the trace says when a turn LEFT the machine.

C5's `TraceSink` will read `TurnContext`; the trace line is its precursor. The `engine` step writes
`ctx.left_machine` from what the engine declares (never from a name alone), every counted call
carries its own flag (the internal steps — compaction, re-prompt, description — are calls to the
provider too), and a message saved from a hosted engine says so in its stats. A local turn says
nothing new: its stats are the ones they always were.
"""
from __future__ import annotations

import json
import logging

import pytest

from core import runtime_state
from core.providers.cloud import ALLOW_CLOUD_ENV
from core.turn.budget import record_llm_call
from core.turn.context import TurnContext
from core.turn.steps import TURN_STEPS
from core.turn.trace import emit_turn_trace

from ._c48_p0_api_lab import FAKE_KEY, FakeProvider, ask_api, consent_for
from ._c48_p0_lab import DOORS, build_world, run_door

TRACE_LOGGER = "nexe.turn.trace"


@pytest.fixture
def cloud(monkeypatch):
    runtime_state.reset()
    monkeypatch.setenv(ALLOW_CLOUD_ENV, "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
    yield
    runtime_state.reset()


# ------------------------------------------------------------------------ the pieces

def test_the_turn_context_starts_inside_the_machine():
    assert TurnContext(turn_id="t").left_machine is False


def test_the_engine_step_declares_it_writes_and_always_writes_the_field():
    step = next(s for s in TURN_STEPS if s.id == "engine")
    assert "left_machine" in step.writes and "left_machine" in step.writes_always


@pytest.mark.parametrize("engine, left", [("api", True), ("API", True), ("mlx", False), ("llama_cpp", False), ("ollama", False),
                                          ("", False), (None, False)])
def test_every_counted_call_carries_whether_it_left(engine, left):
    ctx = TurnContext(turn_id="t")
    record_llm_call(ctx, step="compact", engine=engine, model="m", ms=1.0)
    (call,) = ctx.usage["llm"]["calls"]
    assert call["left_machine"] is left


def test_the_trace_line_says_it_from_the_step_alone_or_from_any_call(caplog):
    caplog.set_level(logging.INFO, logger=TRACE_LOGGER)
    by_step = TurnContext(turn_id="a", left_machine=True)
    assert emit_turn_trace(by_step)["left_machine"] is True
    by_call = TurnContext(turn_id="b")
    record_llm_call(by_call, step="describe_image", engine="api", model="gpt-4o", ms=1.0)
    assert emit_turn_trace(by_call)["left_machine"] is True, "an internal step on the provider counts for the turn"
    inside = TurnContext(turn_id="c")
    record_llm_call(inside, step="generate", engine="ollama", model="m", ms=1.0)
    assert emit_turn_trace(inside)["left_machine"] is False
    assert emit_turn_trace(TurnContext(turn_id="d"))["left_machine"] is False
    logged = [json.loads(r.message.split("turn.trace ", 1)[1]) for r in caplog.records if r.name == TRACE_LOGGER]
    assert [line["left_machine"] for line in logged] == [True, True, False, False]


def test_a_stats_record_names_a_hosted_engine_and_only_that():
    from plugins.web_ui_module.api.wire import _build_mem_stats

    def stats(engine):
        return _build_mem_stats(None, 0, [], "m", 1.0, 100, 0, [], engine)

    assert stats("api")["left_machine"] is True
    for local in ("ollama", "mlx", "llama_cpp", None, ""):
        assert "left_machine" not in stats(local), "a local message keeps the stats it always had"


# --------------------------------------------------------------- a real turn, both doors

@pytest.mark.parametrize("door", DOORS)
async def test_an_api_turn_left_the_machine_and_every_trace_of_it_says_so(turn_lab, cloud, door, caplog):
    caplog.set_level(logging.INFO, logger=TRACE_LOGGER)
    seen, _world = await ask_api(turn_lab, door, FakeProvider("ok"))
    ctx = seen.ctx
    assert ctx.left_machine is True
    assert {c["left_machine"] for c in ctx.usage["llm"]["calls"]} == {True}
    line = [json.loads(r.message.split("turn.trace ", 1)[1]) for r in caplog.records if r.name == TRACE_LOGGER][-1]
    assert line["left_machine"] is True and line["engine"] in ("api", "ApiTurnEngine")
    assert seen.saved_stats.get("left_machine") is (True if door.startswith("ui") else None), "the web stats; /v1 saves none"


@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("engine", ["mlx", "ollama"])
async def test_a_local_turn_never_says_it_left(turn_lab, cloud, door, engine, caplog):
    caplog.set_level(logging.INFO, logger=TRACE_LOGGER)
    world = build_world(live=["mlx", "ollama"])
    world.modules["api_module"] = FakeProvider("ok").module()  # loaded, switch on, key in place: and not asked
    seen = await run_door(turn_lab, world, door, backend=engine, sid=f"inside-{engine}-{door}",
                          extra=consent_for(door))
    assert seen.ctx.left_machine is False
    assert {c["left_machine"] for c in seen.ctx.usage["llm"]["calls"]} == {False}
    line = [json.loads(r.message.split("turn.trace ", 1)[1]) for r in caplog.records if r.name == TRACE_LOGGER][-1]
    assert line["left_machine"] is False
    assert "left_machine" not in seen.saved_stats


async def test_a_refused_turn_did_not_leave_and_has_no_trace_of_having_tried(turn_lab, cloud):
    seen, _world = await ask_api(turn_lab, "v1_json", FakeProvider("ok"), consent=False)
    assert seen.status == 403
    assert seen.ctx is None or seen.ctx.left_machine is False
