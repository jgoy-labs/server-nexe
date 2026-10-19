"""pla-tokens-reals A/B — what an engine says a call cost, in one shape, in one place.

`None` is "the engine did not say". Never `0`, never an estimate: a zero would read
as "this cost nothing", and the footer is the only place allowed to estimate.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from core.endpoints.chat_engines import ollama as ollama_engine
from core.endpoints.chat_engines._streaming import NEXE_END, stream_end
from core.turn import usage
from core.turn.budget import note_usage, record_llm_call


class _Ctx:
    def __init__(self):
        self.usage: dict = {}
        self.engine = "mlx"


# ------------------------------------------------------------------ A: the shape


def test_nothing_said_is_none_not_zero():
    assert usage.make() is None
    assert usage.make(None, None, None) is None
    assert usage.make("7", True, -1) is None, "a string, a bool and a negative are not counts"


def test_a_cache_miss_is_a_real_zero():
    assert usage.make(10, 5, 0) == {"tokens_in": 10, "tokens_out": 5, "cached_in": 0}


def test_each_engine_shape_reads_into_the_same_dict():
    assert usage.from_engine_result({"prompt_tokens": 40, "tokens": 9, "cached_tokens": 30}) == \
        {"tokens_in": 40, "tokens_out": 9, "cached_in": 30}
    assert usage.from_engine_result({"prompt_tokens": 40, "tokens": 9}) == \
        {"tokens_in": 40, "tokens_out": 9, "cached_in": None}, "llama.cpp does not say what it reused"
    assert usage.from_ollama({"prompt_eval_count": 12, "eval_count": 3}) == \
        {"tokens_in": 12, "tokens_out": 3, "cached_in": None}
    assert usage.from_openai({"prompt_tokens": 8, "completion_tokens": 2}) == \
        {"tokens_in": 8, "tokens_out": 2, "cached_in": None}
    assert usage.from_openai({"input_tokens": 8, "output_tokens": 2, "cache_read_input_tokens": 6}) == \
        {"tokens_in": 8, "tokens_out": 2, "cached_in": 6}
    assert usage.from_openai({"prompt_tokens": 8, "completion_tokens": 2,
                              "prompt_tokens_details": {"cached_tokens": 4}})["cached_in"] == 4
    assert usage.from_engine_result("not a dict") is None
    assert usage.from_ollama(None) is None and usage.from_openai([]) is None


def test_a_json_body_with_zeros_is_not_a_count():
    assert usage.from_response({"usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}) is None
    assert usage.from_response({"usage": {"prompt_tokens": 931, "completion_tokens": 4}}) == \
        {"tokens_in": 931, "tokens_out": 4, "cached_in": None}
    assert usage.from_response({}) is None


# ------------------------------------------------------------------ A: where it is kept


def test_the_call_keeps_what_the_engine_said_and_none_when_it_said_nothing():
    ctx = _Ctx()
    record_llm_call(ctx, step="generate", engine="mlx", ms=5.0)
    call = ctx.usage["llm"]["calls"][0]
    assert (call["tokens_in"], call["tokens_out"], call["cached_in"]) == (None, None, None)
    record_llm_call(ctx, step="generate", engine="ollama", ms=5.0, tokens_in=3, tokens_out=2, cached_in=1)
    assert ctx.usage["llm"]["calls"][1]["cached_in"] == 1


def test_a_stream_says_it_at_the_end_and_it_lands_on_the_latest_generate_call():
    ctx = _Ctx()
    record_llm_call(ctx, step="generate", engine="mlx", ms=5.0)
    record_llm_call(ctx, step="memory.write", engine="mlx", ms=1.0)
    note_usage(ctx, {"tokens_in": 40, "tokens_out": 9, "cached_in": 30})
    calls = ctx.usage["llm"]["calls"]
    assert (calls[0]["tokens_in"], calls[0]["tokens_out"], calls[0]["cached_in"]) == (40, 9, 30)
    assert calls[1]["tokens_in"] is None, "another step's call is not the stream's"


def test_nothing_said_leaves_the_call_and_a_number_already_there_stands():
    ctx = _Ctx()
    record_llm_call(ctx, step="generate", engine="mlx", ms=5.0, tokens_in=7)
    note_usage(ctx, None)
    note_usage(ctx, {"tokens_in": 99, "tokens_out": 2, "cached_in": None})
    call = ctx.usage["llm"]["calls"][0]
    assert (call["tokens_in"], call["tokens_out"], call["cached_in"]) == (7, 2, None)


def test_the_stream_sentinel_carries_the_usage():
    said = {"tokens_in": 1, "tokens_out": 2, "cached_in": None}
    assert stream_end(usage=said)[NEXE_END]["usage"] == said
    assert stream_end()[NEXE_END]["usage"] is None


# ------------------------------------------------------------------ B: each engine says it


def test_ollama_says_it_on_its_last_line():
    _, events, status = ollama_engine._ollama_line_events(
        {"message": {"content": "hi"}, "done": True, "prompt_eval_count": 12, "eval_count": 3}, 0)
    assert status == "done"
    assert events[-1][NEXE_END]["usage"] == {"tokens_in": 12, "tokens_out": 3, "cached_in": None}
    _, events, _ = ollama_engine._ollama_line_events({"message": {"content": "hi"}, "done": True}, 0)
    assert events[-1][NEXE_END]["usage"] is None


class _Module:
    def __init__(self, result):
        self.result = result

    async def chat(self, *, stream_callback=None, **_kw):
        stream_callback("hola")
        return self.result


async def _end_of(make, module):
    out = [chunk async for chunk in make(module, [], "sys", "model")]
    return out[-1][NEXE_END]


@pytest.mark.parametrize("engine", ["mlx", "llama_cpp"])
async def test_an_in_process_engine_says_it_with_its_result(engine):
    import importlib

    mod = importlib.import_module(f"core.endpoints.chat_engines.{engine}")
    make = getattr(mod, "_mlx_stream_generator" if engine == "mlx" else "_llama_cpp_stream_generator")
    result = {"prompt_tokens": 40, "tokens": 9, "finish_reason": "stop"}
    if engine == "mlx":
        result["cached_tokens"] = 30
    end = await _end_of(make, _Module(result))
    assert end["usage"]["tokens_in"] == 40 and end["usage"]["tokens_out"] == 9
    assert end["usage"]["cached_in"] == (30 if engine == "mlx" else None)
    assert (await _end_of(make, _Module({"finish_reason": "stop"})))["usage"] is None


async def test_an_api_provider_says_it_in_its_closing_event():
    from core.endpoints.chat_engines import api as api_engine
    from plugins.api_module import chat as api_plugin

    events = [
        {"choices": [{"delta": {"content": "hi"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 8, "completion_tokens": 2}},
    ]

    async def chunks():
        for event in events:
            chunk = api_plugin.parse_stream_event(event, "p")
            if chunk is not None:
                yield chunk

    out = [c async for c in api_engine._api_stream_generator(chunks(), "m")]
    assert out[-1][NEXE_END]["usage"] == {"tokens_in": 8, "tokens_out": 2, "cached_in": None}

    async def whole():
        yield api_plugin.parse_whole_reply(
            {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 8, "completion_tokens": 2}}, "p")

    result = await api_engine._whole_reply(whole())
    assert (result["prompt_tokens"], result["tokens"]) == (8, 2)


# ------------------------------------------------------------------ the turn: /v1, through the real doors

import logging  # noqa: E402

from ._c48_p0_lab import CACHED_TOKENS, PROMPT_TOKENS, build_world, run_door  # noqa: E402
from .test_c5_p0_trace_matrix import LOGGER, _lines  # noqa: E402


@pytest.mark.parametrize("door", ["v1_stream", "v1_json", "ui_stream", "ui_json"])
@pytest.mark.parametrize("engine", ["mlx", "llama_cpp"])
async def test_the_turns_generate_call_carries_what_the_engine_said(turn_lab, caplog, door, engine):
    caplog.set_level(logging.INFO, logger=LOGGER)
    world = build_world({}, live=["mlx", "llama_cpp"])
    await run_door(turn_lab, world, door, backend=engine, sid=f"tok-{door}-{engine}")
    calls = [c for l in _lines(caplog) for c in l["llm"]["calls"] if c["step"] == "generate"]
    call = calls[-1]
    assert call["tokens_in"] == PROMPT_TOKENS and call["tokens_out"] and call["tokens_out"] > 0
    if engine == "mlx" and door != "v1_json":
        assert call["cached_in"] == CACHED_TOKENS
    else:
        # llama.cpp does not say what it reused, and the /v1 JSON body has no such field.
        assert call["cached_in"] is None, "said nowhere: None, never a 0"


# ------------------------------------------------------------------ D: the footer

from plugins.web_ui_module.api import wire  # noqa: E402


def test_the_footer_figure_is_exact_only_when_the_engine_said_it():
    said = {"tokens_in": 40, "tokens_out": 9, "cached_in": 30}
    assert wire.token_stats(said, 123) == {"tokens": 9, "tokens_exact": True, "tokens_in": 40, "cached_in": 30}
    assert wire.token_stats(None, 123) == {"tokens": 123}, "an estimate is not flagged exact and invents no counts"
    assert wire.token_stats({"tokens_in": 40, "tokens_out": None, "cached_in": None}, 123) == \
        {"tokens": 123, "tokens_in": 40}


def test_the_usage_token_leaves_a_blank_for_what_was_not_said():
    assert wire.usage_token({"tokens_in": 40, "tokens_out": 9, "cached_in": None}) == "\x00[USAGE:40|9|]\x00"
    assert wire.usage_token({"tokens_in": 40, "tokens_out": 9, "cached_in": 0}) == "\x00[USAGE:40|9|0]\x00"
    assert wire.usage_token(None) == "" and wire.usage_token({"tokens_in": 4, "tokens_out": None}) == ""


@pytest.mark.parametrize("engine,cached", [("mlx", str(CACHED_TOKENS)), ("llama_cpp", "")])
async def test_the_web_stream_sends_what_the_engine_said_after_the_answer(turn_lab, engine, cached):
    world = build_world({}, live=["mlx", "llama_cpp"])
    seen = await run_door(turn_lab, world, "ui_stream", backend=engine, sid=f"tok-wire-{engine}")
    assert len(seen.usage_tags) == 1
    tokens_in, tokens_out, cached_in = seen.usage_tags[0].split("|")
    assert tokens_in == str(PROMPT_TOKENS) and int(tokens_out) > 0
    assert cached_in == cached, "the cache is said by MLX only; a blank otherwise, never a 0"
    assert "USAGE" not in seen.text
    stats = seen.saved_stats
    assert stats.get("tokens_exact") is True and stats["tokens"] == int(tokens_out), "the saved footer is the exact count too"
    assert stats.get("tokens_in") == PROMPT_TOKENS


async def test_the_web_json_door_saves_the_exact_count_too(turn_lab):
    world = build_world({}, live=["mlx", "llama_cpp"])
    seen = await run_door(turn_lab, world, "ui_json", backend="mlx", sid="tok-wire-json")
    assert seen.saved_stats.get("tokens_exact") is True and seen.saved_stats.get("tokens_in") == PROMPT_TOKENS


# ------------------------------------------------------------------ review (14/10): zeros and guesses are not counts

def test_a_zero_in_or_out_is_not_said_but_a_cache_miss_is():
    assert usage.make(0, 0, None) is None
    assert usage.make(0, 0, 0) == {"tokens_in": None, "tokens_out": None, "cached_in": 0}
    assert usage.from_openai({"prompt_tokens": 0, "completion_tokens": 0}) is None


def test_a_closing_chunk_of_zeros_does_not_erase_a_real_count():
    real = usage.from_openai({"prompt_tokens": 8, "completion_tokens": 2})
    assert usage.merge(real, usage.from_openai({"prompt_tokens": 0, "completion_tokens": 0})) == real


def test_an_engine_that_could_only_guess_says_nothing():
    guessed = {"prompt_tokens": 0, "tokens": 12, "usage_estimated": True, "cached_tokens": 0}
    assert usage.from_engine_result(guessed) is None
    assert usage.from_engine_result({**guessed, "usage_estimated": False})["tokens_out"] == 12


def test_the_in_process_engines_flag_their_guesses():
    from plugins.llama_cpp_module.core.chat import LlamaCppChatNode
    from plugins.mlx_module.core import generate_helpers

    node = LlamaCppChatNode.__new__(LlamaCppChatNode)
    text_of = lambda choice: choice.get("text", "")  # noqa: E731
    silent = [{"choices": [{"text": "hola que tal"}]}]
    told = [{"choices": [{"text": "hola"}], "usage": {"prompt_tokens": 9, "completion_tokens": 2}}]
    assert node._consume_stream(iter(silent), None, None, text_of)["usage_estimated"] is True
    said = node._consume_stream(iter(told), None, None, text_of)
    assert said["usage_estimated"] is False and usage.from_engine_result(said)["tokens_in"] == 9
    assert usage.from_engine_result(node._consume_stream(iter(silent), None, None, text_of)) is None
    assert generate_helpers.__name__  # the MLX branch without a counter is pinned by the source test below


def test_mlx_without_a_counter_flags_its_result_in_the_source():
    import inspect

    from plugins.mlx_module.core import generate_helpers

    source = inspect.getsource(generate_helpers)
    branch = source[source.index('"tokens": len(text) // 4,'):][:200]
    assert '"usage_estimated": True' in branch


def test_the_v1_json_body_carries_the_cache_count_only_when_the_engine_said_it():
    from core.endpoints.chat_engines._common import build_openai_response

    said = build_openai_response({"response": "hi", "prompt_tokens": 40, "tokens": 9, "cached_tokens": 30}, "m", "mlx")
    assert said["usage"]["prompt_tokens_details"] == {"cached_tokens": 30}
    assert usage.from_response(said) == {"tokens_in": 40, "tokens_out": 9, "cached_in": 30}
    for result in ({"response": "hi", "prompt_tokens": 40, "tokens": 9},
                   {"response": "hi", "tokens": 3, "cached_tokens": 0, "usage_estimated": True}):
        assert "prompt_tokens_details" not in build_openai_response(result, "m", "mlx")["usage"]


def test_deepseeks_cache_field_is_read():
    assert usage.from_openai({"prompt_tokens": 8, "completion_tokens": 2, "prompt_cache_hit_tokens": 5})["cached_in"] == 5


def test_a_re_prompted_or_resumed_turn_estimates_its_footer_instead_of_borrowing_a_call():
    from core.turn.budget import footer_usage

    said = {"tokens_in": 40, "tokens_out": 9, "cached_in": None}
    ctx = _Ctx()
    ctx.resume = False
    record_llm_call(ctx, step="generate", engine="mlx", ms=1.0, tokens_out=9)
    assert footer_usage(ctx, said) == said
    record_llm_call(ctx, step="reprompt", engine="mlx", ms=1.0)
    assert footer_usage(ctx, said) is None, "the shown text is the re-prompt's, not the first call's"
    other = _Ctx()
    other.resume = True
    assert footer_usage(other, said) is None, "a Continue generates only the tail"


async def test_the_web_footer_of_a_re_prompted_turn_does_not_borrow_the_first_calls_count(turn_lab):
    """The first reply was only memory tags; the text shown is the re-prompt's, so the count
    of the first call is not its count (the footer estimates, the token is not sent)."""
    from core.turn.budget import footer_usage  # noqa: F401  (the guard under test)

    from ._c48_p0_lab import FakeOllamaDaemon, World
    from .test_c48_p0_rows import ANSWER, ONLY_TAG, _ScriptedOllama

    asked = _ScriptedOllama([ONLY_TAG, ANSWER])
    world = World(modules={"ollama_module": asked}, daemon=FakeOllamaDaemon(), engines={"ollama": asked})
    seen = await run_door(turn_lab, world, "ui_stream", backend="ollama", sid="tok-reprompt",
                          message="recorda que em dic Aran")
    assert ANSWER in seen.text and asked.calls == 2
    assert seen.usage_tags == (), "a count that belongs to another text is not sent"
    assert "tokens_exact" not in seen.saved_stats

    plain = _ScriptedOllama([ANSWER])
    world = World(modules={"ollama_module": plain}, daemon=FakeOllamaDaemon(), engines={"ollama": plain})
    seen = await run_door(turn_lab, world, "ui_stream", backend="ollama", sid="tok-plain", message="hola")
    assert len(seen.usage_tags) == 1 and seen.usage_tags[0].startswith(f"{PROMPT_TOKENS}|")


# ------------------------------------------------------------------ the step event reads the registry (15/10, live)

def test_the_step_event_carries_what_the_registry_holds_for_its_call():
    from core.turn.budget import record_llm_call
    from core.turn.context import TurnContext
    from core.turn.trace import step_event

    ctx = TurnContext(turn_id="t", entry="api")
    assert step_event(ctx, "generate", "llm", "ok", 5.0).tokens_in is None, "no call, nothing said"
    record_llm_call(ctx, step="generate", engine="ollama", ms=5.0, tokens_in=40, tokens_out=9, cached_in=None)
    record_llm_call(ctx, step="compact", engine="ollama", ms=5.0, tokens_in=7, tokens_out=3)
    event = step_event(ctx, "generate", "llm", "ok", 5.0)
    assert (event.tokens_in, event.tokens_out, event.cached_in) == (40, 9, None), "its own call, not another step's"
    assert step_event(ctx, "engine", "compute", "ok", 1.0).tokens_out is None, "a step without a call says nothing"
