"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/test_gen_truncated_marker_stream.py
Description: FD-S5 — a max_tokens cut reaches the web client as
             \\x00[GEN_TRUNCATED:{1|0}]\\x00, its OWN yield after the last text.

Driven through real web turns (`turn_lab`). Until C4.6 these drove the legacy
streaming body (`_generate_streaming_response`) directly — the one the
Continue path kept, gone now; the adapters are what every turn walks.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""


async def _drive(turn_lab, fake_engine, chunks, session_id):
    fake_engine.chunks = tuple(chunks)
    ctx = await turn_lab.ui(streaming=True, session_id=session_id)
    yields = [c for c in ctx.lab_wire_chunks if isinstance(c, str)]
    return "".join(yields), yields


async def test_marker_emitted_after_text_on_length(turn_lab, fake_engine):
    body, yields = await _drive(
        turn_lab, fake_engine,
        ["Hola ", "món", {"__nexe_trunc__": True, "continuable": True}], "gt-length",
    )
    assert "\x00[GEN_TRUNCATED:1]\x00" in body
    # own yield, never mixed with text
    assert [y for y in yields if "GEN_TRUNCATED" in y] == ["\x00[GEN_TRUNCATED:1]\x00"]
    # after the last text chunk
    assert body.index("món") < body.index("GEN_TRUNCATED")


async def test_not_continuable_marks_zero(turn_lab, fake_engine):
    body, _ = await _drive(
        turn_lab, fake_engine, ["text", {"__nexe_trunc__": True, "continuable": False}], "gt-zero",
    )
    assert "\x00[GEN_TRUNCATED:0]\x00" in body


async def test_no_marker_without_truncation(turn_lab, fake_engine):
    body, _ = await _drive(turn_lab, fake_engine, ["Hola ", "món"], "gt-none")
    assert "GEN_TRUNCATED" not in body


async def test_ollama_done_reason_length_marks_zero(turn_lab, fake_engine):
    """Length without a `continuable` field stays :0. The engine, not the
    door, decides whether Continue is honest (C4.6-a2)."""
    body, _ = await _drive(
        turn_lab, fake_engine,
        [{"message": {"content": "hola"}}, {"done": True, "done_reason": "length"}], "gt-ollama",
    )
    assert "\x00[GEN_TRUNCATED:0]\x00" in body


async def test_ollama_length_continuable_marks_one(turn_lab, fake_engine):
    body, yields = await _drive(
        turn_lab, fake_engine,
        [
            {"message": {"content": "hola"}},
            {"done": True, "done_reason": "length", "continuable": True},
        ],
        "gt-ollama-1",
    )
    assert "\x00[GEN_TRUNCATED:1]\x00" in body
    assert [y for y in yields if "GEN_TRUNCATED" in y] == ["\x00[GEN_TRUNCATED:1]\x00"]
    assert body.index("hola") < body.index("GEN_TRUNCATED")


async def test_ollama_length_not_continuable_marks_zero(turn_lab, fake_engine):
    body, _ = await _drive(
        turn_lab, fake_engine,
        [
            {"message": {"content": "hola"}},
            {"done": True, "done_reason": "length", "continuable": False},
        ],
        "gt-ollama-0",
    )
    assert "\x00[GEN_TRUNCATED:0]\x00" in body


async def test_think_only_degrades_to_zero(turn_lab, fake_engine):
    """A turn whose visible text cleans to EMPTY has nothing resumable — the
    marker degrades to :0 even when the engine said continuable (the cut
    landed inside the reasoning)."""
    body, _ = await _drive(
        turn_lab, fake_engine,
        ["<think>reasoning, then the cut</think>", {"__nexe_trunc__": True, "continuable": True}],
        "gt-think",
    )
    assert "\x00[GEN_TRUNCATED:0]\x00" in body
    assert "GEN_TRUNCATED:1" not in body
