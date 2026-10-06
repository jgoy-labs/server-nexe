"""The scenarios of the C4.8 part 0 matrix, as functions of (engine, mode, door).

Kept apart from the tests so the expected tables and the code that fills them
share one definition of "the primary engine fails like this".
"""
from __future__ import annotations

from ._c48_p0_lab import ENGINES, Seen, build_world, run_door

#: Failure modes of the first engine of the cascade (the one the client asked
#: for), with a healthy engine behind it. `ok` is the baseline.
PRIMARY_MODES = (
    "ok", "pre_byte", "oom", "bad_request", "unreachable", "timeout",
    "mid_stream", "loading", "empty", "not_found", "gone",
)

#: Failure modes of an in-process engine with ONLY Ollama behind it: Ollama as
#: the healthy fallback (it answers over HTTP at /v1 and through its module on
#: the web).
OLLAMA_BEHIND_MODES = ("pre_byte", "oom", "bad_request", "unreachable", "timeout", "mid_stream", "empty")

#: Failure modes every engine shares: nobody answers.
EVERY_MODES = (
    "pre_byte", "oom", "mid_stream", "empty", "bad_request", "unreachable", "timeout", "not_found",
)

#: A model name no engine has: the web door sends it (the dropdown always
#: does), `/v1` carries it in `model`.
MISSING_MODEL = "model-que-no-existeix"


def _extra(mode: str) -> dict | None:
    return {"model": MISSING_MODEL} if mode == "not_found" else None


def fallback_for(engine: str) -> str:
    """The healthy engine behind `engine`: the first of the cascade that is not it."""
    return next(name for name in ENGINES if name != engine)


async def primary_fails(lab, engine: str, mode: str, door: str) -> Seen:
    """`engine` is asked for and fails as `mode` says; the next one is healthy."""
    world = build_world({engine: mode}, live=[engine, fallback_for(engine)],
                        delay=0.05 if mode == "gone" else 0.0)
    return await run_door(
        lab, world, door, backend=engine, sid=f"p-{engine}-{mode}-{door}",
        extra=_extra(mode), gone=mode == "gone",
    )


async def ollama_behind(lab, engine: str, mode: str, door: str) -> Seen:
    """`engine` (mlx or llama.cpp) fails as `mode` says; Ollama is the only one behind it."""
    world = build_world({engine: mode}, live=[engine, "ollama"])
    return await run_door(
        lab, world, door, backend=engine, sid=f"o-{engine}-{mode}-{door}",
    )


async def every_engine_fails(lab, engine: str, mode: str, door: str) -> Seen:
    """Every engine fails the same way; `engine` is the one asked for first."""
    world = build_world({name: mode for name in ENGINES})
    return await run_door(
        lab, world, door, backend=engine, sid=f"e-{engine}-{mode}-{door}", extra=_extra(mode),
    )


async def none_live(lab, door: str, daemon_up: bool) -> Seen:
    """No engine registered at all; Ollama's daemon answers or is down."""
    world = build_world(live=[])
    if not daemon_up:
        world.daemon.mode, world.daemon.down = "unreachable", True
    return await run_door(lab, world, door, backend="mlx", sid=f"n-{daemon_up}-{door}")
