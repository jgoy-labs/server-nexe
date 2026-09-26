"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/test_reprompt_chunks.py
Description: The second LLM call of a tags-only turn, in the core (ADR-007
             C4.5, D3). What `_yield_reprompt` used to be tested for at the
             web door (tests/test_response_generator_helpers.py, until 26/09)
             plus the two things the doors got wrong: the call takes an
             engine slot, and I8 counts it only when an engine was asked.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest
from starlette.datastructures import State

from core.turn import policy
from core.turn.context import TurnContext
from core.turn.gate import ENV_GATE_WAIT_S, EngineGate, Priority


def _ctx(gate: EngineGate | None = None, lang: str | None = "ca") -> TurnContext:
    state = State()
    state.engine_gate = gate or EngineGate(slots=1)
    return TurnContext(turn_id="t-rp", entry="ui", app_state=state, system_prompt="sys", lang=lang)


def _call_yielding(*chunks):
    """A door's `call`: records the system prompt it was handed, streams `chunks`."""
    async def gen():
        for c in chunks:
            yield c

    def call(system_prompt: str):
        call.systems.append(system_prompt)
        return gen()

    call.systems = []
    return call


async def _collect(agen) -> list:
    return [c async for c in agen]


def _llm(ctx: TurnContext) -> list:
    return (ctx.usage.get("llm") or {}).get("calls", [])


async def test_it_yields_the_clean_second_answer_and_counts_one_call():
    ctx = _ctx()
    call = _call_yielding("hola", " món")
    out = await _collect(policy.reprompt_chunks(
        ctx, ["l'usuari es diu Joan"], call=call, engine_name="ollama", model="llama3",
    ))
    assert "".join(out) == "hola món"
    assert [c["step"] for c in _llm(ctx)] == ["reprompt"]
    assert _llm(ctx)[0]["engine"] == "ollama" and _llm(ctx)[0]["model"] == "llama3"
    assert _llm(ctx)[0]["ms"] >= 0


async def test_the_model_is_asked_under_the_override_in_the_turns_language():
    for lang, key in (("ca", "ca"), ("es", "es"), ("en", "en"), ("fr", "en"), (None, "ca")):
        call = _call_yielding("x")
        await _collect(policy.reprompt_chunks(_ctx(lang=lang), ["f"], call=call, engine_name="e", model=None))
        assert call.systems == ["sys" + policy.REPROMPT_OVERRIDE[key]], lang


async def test_nothing_to_confirm_asks_nothing():
    ctx = _ctx()
    call = _call_yielding("hola")
    assert await _collect(policy.reprompt_chunks(ctx, [], call=call, engine_name="e", model=None)) == []
    assert await _collect(policy.reprompt_chunks(ctx, ["", "  "], call=call, engine_name="e", model=None)) == []
    assert call.systems == [] and "llm" not in ctx.usage


async def test_the_flag_off_asks_nothing_and_counts_nothing(monkeypatch):
    monkeypatch.setenv(policy.ENV_REPROMPT_IF_ONLY_MEMSAVE, "false")
    ctx = _ctx()
    call = _call_yielding("hola")
    assert await _collect(policy.reprompt_chunks(ctx, ["fact"], call=call, engine_name="e", model=None)) == []
    assert call.systems == [] and "llm" not in ctx.usage


async def test_a_door_without_a_call_is_a_skip_not_an_inference():
    """The `continue` path before an engine started, a short-circuited turn."""
    ctx = _ctx()
    assert await _collect(policy.reprompt_chunks(ctx, ["fact"], call=None, engine_name="e", model=None)) == []
    assert "llm" not in ctx.usage


async def test_an_engine_shape_the_door_cannot_call_again_is_said_not_counted():
    """What `_yield_reprompt` did in silence for MLX/llama.cpp (`'model' not in sig`)."""
    ctx = _ctx()
    out = await _collect(policy.reprompt_chunks(
        ctx, ["fact"], call=lambda system: None, engine_name="mlx", model="Qwen",
    ))
    assert out == [] and "llm" not in ctx.usage


async def test_an_engine_that_refuses_to_start_is_not_counted():
    ctx = _ctx()

    def call(system_prompt: str):
        raise RuntimeError("engine down")

    assert await _collect(policy.reprompt_chunks(ctx, ["fact"], call=call, engine_name="e", model=None)) == []
    assert "llm" not in ctx.usage


async def test_an_engine_that_dies_mid_stream_keeps_what_came_and_is_counted():
    ctx = _ctx()

    async def gen():
        yield "primera"
        raise RuntimeError("engine died")

    out = await _collect(policy.reprompt_chunks(ctx, ["fact"], call=lambda s: gen(), engine_name="e", model="m"))
    assert out == ["primera"]
    assert [c["step"] for c in _llm(ctx)] == ["reprompt"]


async def test_reasoning_and_tags_never_reach_the_second_answer():
    """B124: a chunk with a complete <think>…</think> plus trailing text keeps
    the text; a thinking-only dict chunk is dropped; a repeated tag is noise."""
    ctx = _ctx()
    out = await _collect(policy.reprompt_chunks(
        ctx, ["fact"],
        call=_call_yielding(
            {"message": {"thinking": "pensa", "content": ""}},
            "<think>reasoning</think>Hola Joan",
            {"message": {"content": " text [MEM_SAVE: fake] fi"}},
        ),
        engine_name="e", model=None,
    ))
    joined = "".join(out)
    assert joined == "Hola Joan text  fi"
    assert "<think>" not in joined and "[MEM_SAVE:" not in joined


async def test_the_call_holds_an_engine_slot_and_gives_it_back():
    gate = EngineGate(slots=1)
    ctx = _ctx(gate)
    seen = {}

    async def gen():
        seen["free_during"] = gate._free()
        yield "hola"

    await _collect(policy.reprompt_chunks(ctx, ["fact"], call=lambda s: gen(), engine_name="e", model=None))
    assert seen["free_during"] == 0, "the second call ran outside the engine gate"
    assert gate._free() == 1, "the slot was not given back"


async def test_the_slot_is_given_back_when_the_engine_dies():
    gate = EngineGate(slots=1)

    async def gen():
        raise RuntimeError("boom")
        yield  # pragma: no cover — makes this an async generator

    await _collect(policy.reprompt_chunks(_ctx(gate), ["fact"], call=lambda s: gen(), engine_name="e", model=None))
    assert gate._free() == 1


async def test_a_busy_gate_means_no_second_call_and_nothing_counted(monkeypatch):
    monkeypatch.setenv(ENV_GATE_WAIT_S, "0.05")
    gate = EngineGate(slots=1)
    held = await gate.acquire(Priority.USER_TURN, holder="another-turn")
    ctx = _ctx(gate)
    call = _call_yielding("hola")
    try:
        out = await _collect(policy.reprompt_chunks(ctx, ["fact"], call=call, engine_name="e", model=None))
    finally:
        await gate.release(held)
    assert out == [] and call.systems == [] and "llm" not in ctx.usage


def test_a_tag_split_across_chunks_is_gone_from_the_joined_second_answer():
    """Live 26/09 (gemma4:e4b): the second answer was the tag again, in pieces
    the per-chunk strip cannot see. Joined, it is nothing — the caller falls
    back to the neutral phrase instead of showing the tag."""
    assert policy.second_answer_text(["[MEM_SAVE: el color", " preferit de l'usuari és el blau]"]) == ""
    assert policy.second_answer_text(["Molt bé. ", "[MEM_DEL", "ETE: x] i ja està."]) == "Molt bé.  i ja està."
    assert policy.second_answer_text(["D'acord, ", "ho recordo."]) == "D'acord, ho recordo."
    assert policy.second_answer_text([]) == ""
