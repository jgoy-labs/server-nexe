"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/test_1039_web_stream_hardening.py
Description: #1039 / #1104 — the model's text passes the same guard at every
             door: no control characters (a model must not forge the web
             door's \\x00[…]\\x00 sentinels) and a byte ceiling that ends the
             turn partial and stops the engine.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import threading

import pytest

from core.endpoints.chat_engines import _streaming
from core.turn.errors import StreamCapExceeded
from core.turn.stream import Delta, Failed, Ready, StreamFlags, Whole, engine_events

#: What a model would have to write to make the web client paint a "saved"
#: badge for a fact the server never stored (nexe-chat.js reads the NUL-framed
#: sentinel off the raw stream; the CLI's reader does the same).
FORGED = "\x00[MEM:9:fals]\x00"


async def _events(chat_result, flags=None):
    flags = flags or StreamFlags()
    return [ev async for ev in engine_events(chat_result, "qwen3", flags)], flags


def _text_of(events) -> tuple[str, str]:
    wire = "".join(w for e in events if isinstance(e, Delta) for w in e.wire)
    full = "".join(e.full for e in events if isinstance(e, Delta))
    return wire, full


# ── the engine loop ─────────────────────────────────────────────────────────


async def test_a_forged_sentinel_leaves_no_control_character_on_the_wire_or_in_the_turn():
    async def gen():
        yield f"Hola {FORGED}"
        yield {"message": {"content": " món", "thinking": "pensa\x07"}}

    events, _ = await _events(gen())
    wire, full = _text_of(events)
    assert "\x00" not in wire and "\x00" not in full
    assert "\x07" not in full
    # The words stay: only the bytes that make them a sentinel go.
    assert "[MEM:9:fals]" in wire


async def test_the_raw_text_of_a_split_engine_is_cleaned_too():
    from core.turn.reasoning import structured_chunk

    async def gen():
        yield structured_chunk("Resposta", "", raw=f"Resposta{FORGED}")

    events, _ = await _events(gen())
    _, full = _text_of(events)
    assert "\x00" not in full


async def test_a_whole_reply_is_cleaned():
    async def coro():
        return {"message": {"content": f"Resposta{FORGED}"}}

    events, _ = await _events(coro())
    whole = [e for e in events if isinstance(e, Whole)]
    assert whole and "\x00" not in whole[0].text


async def test_the_ceiling_ends_the_stream_as_a_failure_and_closes_the_engines_generator(monkeypatch):
    monkeypatch.setattr(_streaming, "MAX_STREAM_BYTES", 10)
    closed = []

    async def gen():
        try:
            yield "12345"
            yield "67890"
            yield "abc"  # 13 bytes > 10
            yield "never read"
        finally:
            closed.append(True)

    events, flags = await _events(gen())
    assert isinstance(events[0], Ready)
    assert isinstance(events[-1], Failed) and isinstance(events[-1].exc, StreamCapExceeded)
    assert isinstance(flags.error, StreamCapExceeded)
    _, full = _text_of(events)
    assert full == "1234567890"
    assert closed == [True]


async def test_reasoning_counts_against_the_ceiling(monkeypatch):
    monkeypatch.setattr(_streaming, "MAX_STREAM_BYTES", 10)

    async def gen():
        yield {"message": {"content": "", "thinking": "x" * 11}}

    events, flags = await _events(gen())
    assert isinstance(flags.error, StreamCapExceeded)


# ── the web door's JSON shape (never passes through engine_events) ────────


async def test_the_json_accumulation_is_cleaned():
    from plugins.web_ui_module.api import engine_call

    async def gen():
        yield f"Hola {FORGED}"
        yield {"message": {"content": " món"}}

    chunks: list = []
    capped = await engine_call._accumulate_nonstreaming_response(gen(), chunks)
    assert capped is False
    assert "\x00" not in "".join(chunks)


async def test_the_json_accumulation_stops_at_the_ceiling(monkeypatch):
    from plugins.web_ui_module.api import engine_call

    monkeypatch.setattr(_streaming, "MAX_STREAM_BYTES", 10)
    closed = []

    async def gen():
        try:
            yield "12345"
            yield "678901"
            yield "never read"
        finally:
            closed.append(True)

    chunks: list = []
    capped = await engine_call._accumulate_nonstreaming_response(gen(), chunks)
    assert capped is True
    assert chunks == ["12345"]
    assert closed == [True]


# ── the re-prompt's second answer (never passes through engine_events) ────


async def test_the_second_answer_is_cleaned():
    from core.turn.policy import _visible_text

    async def stream():
        yield f"D'acord {FORGED}"
        yield {"message": {"content": " fet"}}

    parts = [p async for p in _visible_text(stream())]
    assert parts and "\x00" not in "".join(parts)


async def test_the_second_answer_stops_at_the_ceiling(monkeypatch):
    from core.turn.policy import _visible_text

    monkeypatch.setattr(_streaming, "MAX_STREAM_BYTES", 10)

    async def stream():
        yield "x" * 11

    with pytest.raises(StreamCapExceeded):
        _ = [p async for p in _visible_text(stream())]


# ── /v1's bridge (#1104) ───────────────────────────────────────────────────


async def test_the_bridge_keeps_the_cap_error_when_the_engine_finishes_normally(monkeypatch):
    monkeypatch.setattr(_streaming, "MAX_STREAM_BYTES", 10)
    stop = threading.Event()
    bridge = _streaming.TokenBridge(cancel_event=stop)

    bridge.on_token("x" * 11)
    assert bridge.error == "stream_cap_exceeded"
    assert stop.is_set(), "the engine must be told to stop, or it runs to max_tokens"

    # The engine's worker notices the event and returns normally: before
    # #1104 this second call wiped the error and the stream closed as "stop".
    bridge.set_done(result={"finish_reason": "stop"})
    assert bridge.error == "stream_cap_exceeded"


# ── the web door, end to end ───────────────────────────────────────────────


async def test_the_web_door_never_puts_a_forged_sentinel_on_its_wire(turn_lab, fake_engine):
    fake_engine.chunks = (f"Hola {FORGED}", " Aran.")
    ctx = await turn_lab.ui(streaming=True, session_id="f1039-stream")
    wire = "".join(c for c in ctx.lab_wire_chunks if isinstance(c, str))
    assert FORGED not in wire
    assert "\x00" not in ctx.response
    saved = turn_lab.session_manager.get_or_create_session("f1039-stream").messages[-1]["content"]
    assert "\x00" not in saved


async def test_the_web_door_json_reply_carries_no_forged_sentinel(turn_lab, fake_engine):
    fake_engine.chunks = (f"Hola {FORGED}", " Aran.")
    ctx = await turn_lab.ui(streaming=False, session_id="f1039-json")
    assert "\x00" not in ctx.wire["response"]


async def test_a_runaway_web_stream_ends_partial_and_stops_the_engine(turn_lab, monkeypatch):
    monkeypatch.setattr(_streaming, "MAX_STREAM_BYTES", 8)  # "Hola, " + "Aran." = 11
    ctx = await turn_lab.ui(streaming=True, session_id="f1039-cap-stream")
    assert ctx.partial is True
    assert ctx.error["message"] == "stream_cap_exceeded"
    assert ctx.cancel_token[0].is_set(), "the engine's worker must be told to stop"
    assert ctx.outcomes["memory.write"] == "skipped"


async def test_a_runaway_web_json_reply_ends_partial_and_stops_the_engine(turn_lab, monkeypatch):
    monkeypatch.setattr(_streaming, "MAX_STREAM_BYTES", 8)
    ctx = await turn_lab.ui(streaming=False, session_id="f1039-cap-json")
    assert ctx.partial is True
    assert ctx.cancel_token[0].is_set()
    assert ctx.wire["response"] == "Hola,"
    assert ctx.outcomes["memory.write"] == "skipped"
