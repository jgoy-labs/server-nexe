"""C5 part B (#1160-a, B5) — one name for the engine, one record of the fall-back.

`ctx.engine` holds the engine MODULE at the web door and its NAME at `/v1`; the
trace and the metrics need the name, and the fall-back, which only `/v1` kept.
Both doors now write `ctx.engine_name` and the engine the turn fell back from,
by the one rule in `core/turn/engine_claim.py::fallback_of`.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.turn.engine_claim import fallback_of

from ._c48_p0_lab import DOORS, build_world, run_door


@pytest.mark.parametrize("door", DOORS)
async def test_a_fall_back_is_on_the_turn_at_every_door(turn_lab, door):
    world = build_world({"mlx": "pre_byte"}, live=["mlx", "llama_cpp"])
    seen = await run_door(turn_lab, world, door, backend="mlx", sid=f"c5b-{door}")
    assert (seen.ctx.engine_name, seen.ctx.engine_fallback_from, seen.ctx.engine_fallback_reason) == (
        "llama_cpp", "mlx", "execution_failed")


@pytest.mark.parametrize("door", DOORS)
async def test_an_engine_that_answers_first_time_is_no_fall_back(turn_lab, door):
    world = build_world({}, live=["mlx", "llama_cpp"])
    seen = await run_door(turn_lab, world, door, backend="mlx", sid=f"c5b-ok-{door}")
    assert (seen.ctx.engine_name, seen.ctx.engine_fallback_from) == ("mlx", None)


async def test_the_engine_asked_for_that_is_not_live_reads_the_same_at_every_door(turn_lab):
    """The four shapes record the same thing on the turn when the engine named is not
    live: it answered by `llama_cpp`, instead of `mlx`. What the CLIENT is told is
    another matter and is not touched (`/v1` says it in headers, the web does not)."""
    cells = set()
    for door in DOORS:
        world = build_world({}, live=["llama_cpp"])
        seen = await run_door(turn_lab, world, door, backend="mlx", sid=f"c5b-nl-{door}")
        cells.add((seen.ctx.engine_name, seen.ctx.engine_fallback_from))
    assert cells == {("llama_cpp", "mlx")}


def test_the_rule_is_against_the_first_engine_asked_and_keeps_what_was_there():
    claim = SimpleNamespace(engine_name="b")
    assert fallback_of(claim, "a") == "a"
    assert fallback_of(claim, "b") is None
    assert fallback_of(SimpleNamespace(engine_name="b"), "a", already="z") == "z"
    assert fallback_of(SimpleNamespace(engine_name="a"), "a", already=None) is None
