"""C5 part 0 — the trace line as it is TODAY, at the four shapes of a turn.

A photo, not an intention (same rule as the C4.8 matrix): every cell is a real
turn through a real door (`_c48_p0_lab.py`) and the line compared is what
`emit_turn_trace` logs for it — how many lines the turn left, which engine the
line names, the fallback it records, how many LLM calls it bills, how many
steps carry an outcome, whether it is partial, and what `generate` ended as.

The parts of the C5 turn cells over, each under the label of the part that does
it; any cell turning red without its label is a regression:

* **#1160-a** (part B, applied): until B the web door logged the engine MODULE's
  class name (`InProc`) and never a fallback; `/v1` logged the engine's name and the
  fallback. Since B both name the engine that answered and the one they fell back
  from — which shows what the old name hid: a JSON web turn whose engine answers
  NOTHING moves on to the next engine (the `empty` row), the streamed one and `/v1` do not.
* **#1160-b** (part C): a stream cut short bills no call (`calls=0` at `/v1`).
* **C5-0** (found by this part, applied by part A): a JSON turn that ended in an
  exception (here a 503, `generate` fell) left NO line at all — `run_turn` logged
  on return. Both cells below said `n=0` until A, and say `n=1` since.
"""
from __future__ import annotations

import json
import logging

import pytest

from ._c48_p0_lab import DOORS, build_world, run_door

LOGGER = "nexe.turn.trace"


def _lines(caplog) -> list[dict]:
    return [
        json.loads(r.message[len("turn.trace "):])
        for r in caplog.records if r.name == LOGGER and r.message.startswith("turn.trace ")
    ]


def _sig(lines: list[dict]) -> str:
    if not lines:
        return "n=0"
    last = lines[-1]
    return " ".join([
        f"n={len(lines)}", f"engine={last['engine']}", f"fb={last['engine_fallback_from'] or '-'}",
        f"calls={len(last['llm'].get('calls', []))}", f"outcomes={len(last['outcomes'])}",
        f"partial={last['partial']}", f"generate={last['outcomes'].get('generate')}",
    ])


_OK = {
    "v1_json": "n=1 engine=mlx fb=- calls=1 outcomes=18 partial=False generate=ok",
    "v1_stream": "n=1 engine=mlx fb=- calls=1 outcomes=18 partial=False generate=ok",
    "ui_json": "n=1 engine=mlx fb=- calls=1 outcomes=18 partial=False generate=ok",
    "ui_stream": "n=1 engine=mlx fb=- calls=1 outcomes=18 partial=False generate=ok",
}
_FELL_ALL = "n=1 engine=llama_cpp fb=mlx calls=1 outcomes=18 partial=False generate=ok"
_FELL = {door: _FELL_ALL for door in DOORS}  # the first engine fails before a byte (or is unreachable)

#: (mode) -> {door: signature}
EXPECTED = {
    "ok": _OK,
    "empty": {**_OK, "ui_json": _FELL_ALL},
    "pre_byte": _FELL,
    "unreachable": _FELL,
    "mid_stream": {
        "v1_json": _FELL_ALL,
        "v1_stream": "n=1 engine=mlx fb=- calls=1 outcomes=18 partial=True generate=degraded",
        "ui_json": _FELL_ALL,
        "ui_stream": "n=1 engine=mlx fb=- calls=1 outcomes=18 partial=True generate=degraded",
    },
    "gone": {
        "v1_json": "n=1 engine=mlx fb=- calls=0 outcomes=12 partial=False generate=failed",
        "v1_stream": "n=1 engine=mlx fb=- calls=0 outcomes=12 partial=False generate=failed",
        "ui_json": "n=1 engine=mlx fb=- calls=0 outcomes=12 partial=False generate=failed",
        "ui_stream": "n=1 engine=mlx fb=- calls=1 outcomes=18 partial=True generate=degraded",
    },
}


@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("mode", list(EXPECTED))
async def test_the_trace_line_of_each_shape_of_turn(turn_lab, caplog, door, mode):
    caplog.set_level(logging.INFO, logger=LOGGER)
    gone = mode == "gone"
    world = build_world({"mlx": mode}, live=["mlx", "llama_cpp"], delay=0.05 if gone else 0.0)
    await run_door(turn_lab, world, door, backend="mlx", sid=f"c5p0-{door}-{mode}", gone=gone)
    assert _sig(_lines(caplog)) == EXPECTED[mode][door]
