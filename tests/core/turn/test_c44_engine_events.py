"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/test_c44_engine_events.py
Description: C4.4 — the engine loop is the core's and says WHAT happened;
             the door writes it in its own alphabet. Order and error channel
             are the old loop's (the web door's characterisation pins the
             bytes; this pins the events).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from core.turn.stream import Delta, Failed, Ready, StreamFlags, Whole, engine_events


async def _collect(chat_result, flags=None):
    flags = flags or StreamFlags()
    return [ev async for ev in engine_events(chat_result, "qwen3", flags)], flags


async def test_ready_comes_before_the_first_delta_and_a_flush_closes():
    async def gen():
        yield {"message": {"content": "Hola"}}
        yield {"message": {"content": " món"}}

    events, _ = await _collect(gen())
    assert isinstance(events[0], Ready)
    assert [e.full for e in events[1:]] == ["Hola", " món", ""]
    assert all(isinstance(e, Delta) for e in events[1:])


async def test_a_mid_stream_error_is_the_last_event_and_is_on_the_flags():
    boom = RuntimeError("engine died")

    async def gen():
        yield {"message": {"content": "Hola"}}
        raise boom

    events, flags = await _collect(gen())
    assert isinstance(events[-1], Failed) and events[-1].exc is boom
    assert flags.error is boom


async def test_the_trunc_sentinel_is_read_not_forwarded():
    async def gen():
        yield {"message": {"content": "Hola"}}
        yield {"__nexe_trunc__": True, "continuable": True}

    events, flags = await _collect(gen())
    assert flags.trunc and flags.trunc_continuable
    assert "".join(e.full for e in events if isinstance(e, Delta)) == "Hola"


async def test_a_non_streaming_engine_is_one_whole_reply():
    async def coro():
        return {"message": {"content": "Resposta"}}

    events, _ = await _collect(coro())
    assert isinstance(events[0], Ready)
    assert isinstance(events[1], Whole) and events[1].text == "Resposta"


async def test_a_split_engine_keeps_the_raw_text_as_the_turns_raw():
    """ADR-010: wire from the structured chunk, raw from `raw` — a Continue
    of a truncated turn needs the exact text the model generated."""
    from core.turn.reasoning import structured_chunk

    async def gen():
        yield structured_chunk("", "raona", raw="raona")
        yield structured_chunk("", "", raw="</think>\n")
        yield structured_chunk("Resposta", "", raw="Resposta")

    events, _ = await _collect(gen())
    deltas = [e for e in events if isinstance(e, Delta)]
    assert "".join(d.full for d in deltas) == "raona</think>\nResposta"
    assert "".join(w for d in deltas for w in d.wire) == "<think>raona</think>Resposta"
