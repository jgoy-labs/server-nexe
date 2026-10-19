"""C4.8 part 0 — the matrix: what each door does TODAY when an engine fails.

Fake engines in the shape of the real MLX, llama.cpp and Ollama modules
(`_c48_p0_lab.py`, built on the fakes of #1117 and #1035) behind the two doors
the C4.8 puts on one cascade: `/v1/chat/completions` and the web UI's
`/ui/chat`, JSON and streamed. Every cell is a real turn through the real route
handler, and the line compared is what a client meets: the HTTP code, how the
stream ended, which engine's text it got, the notice written in the chat,
whether the answer was kept, the web labels `[ENGINE:]` / `[MODEL:]` / the
loading banner, the `X-Nexe-Fallback-*` pair, and which engines were asked.

**This pins the present, not the intention.** Where the doors differ, the cell
says so, and the comment above it names the row that explains it:

* B1–B7, R1–R4 and "Q" are rows of the review of 04/10
  (`revisio-pla-c4-8-contra-main-20261004.md`, §B);
* N1–N7 are differences the matrix found that the review did not list (they
  are in `diari/…/20261006-c4-8-part0-caracteritzacio.md`): N1 the streaming `/v1`
  forwarders lost the engine's error class (applied: they hand it over); N2 every HTTP
  error of Ollama's daemon was terminal at `/v1` (applied: read for what it means); N3
  what a failure after the first byte looks like; N4 a client that leaves (applied: no door
  asks another engine; a deadline is not a client that left); N5 the policy
  keyed on the exception CLASS (applied: it reads what the failure MEANS,
  `routing.classify`, the same for both doors); N6 `/v1` labelled an engine that was
  never asked as the one it fell back from (applied; rows file); N7 the `/v1` re-prompt was
  recorded under the engine of the first answer (gone since R1: it names the engine it was
  asked of).
* N8-N10 (the API providers, 06/10) the API engine is reachable at both doors, only when asked for by name
  and past the cloud gate. It is not in the chain these cells walk, so it has a column of its own:
  `test_c48_p0_api.py`.

A later part of C4.8 changes the cells whose row was decided, and only those;
any other cell turning red is a regression.

The notation of a cell: `200 by=llama_cpp saved fb=mlx/execution_failed
asked=mlx>llama_cpp` — `{X}` is the engine the client asked for, `{F}` the
healthy engine behind it (the first of mlx → llama_cpp → ollama that is not
`{X}`), `{FM}` the model `{F}` runs, `{DM}` the default model name the web door
sends when the body names none.
"""
from __future__ import annotations

import re

import pytest

from ._c48_p0_lab import DOORS, ENGINES, LLAMA_MODEL, MLX_MODEL
from ._c48_p0_scenarios import (
    EVERY_MODES, OLLAMA_BEHIND_MODES, PRIMARY_MODES, every_engine_fails, fallback_for, none_live,
    ollama_behind, primary_fails,
)

DEFAULT_MODEL = "llama3.2:3b"  # what conftest's `app_state` sets NEXE_DEFAULT_MODEL to
MODEL_OF = {"mlx": MLX_MODEL, "llama_cpp": LLAMA_MODEL}


#: (v1_json, v1_stream, ui_json, ui_stream) per failure mode, per group of engines.
PRIMARY: dict[str, dict[str, tuple[str, str, str, str]]] = {
    # Baseline: the engine asked for answers; nobody falls. The labels are the web
    # stream's ([ENGINE:], [MODEL:]); /v1 carries none (its headers: test_c48_p0_rows).
    "ok": {
        "mlx llama_cpp ollama": (
            "200 by={X} saved asked={X}",
            "200 by={X} finish=stop saved asked={X}",
            "200 by={X} saved asked={X}",
            "200 by={X} saved E={X} M={DM} asked={X}",
        ),
    },
    # Fails before its first byte: the engine is failing, and the next engine answers.
    # N2/N5 (applied): on /v1 Ollama's daemon answers its 500 as an HTTPException, and the
    #   policy reads what it MEANS (`routing.classify`): an engine failing, worth the next one,
    #   as on the web, where the module raises. It used to end the turn with a 500.
    # B5: /v1 names the switch (fb=); the web names it with its labels (E=, M=).
    # B2 (#1035): the web fallback answers under ITS model (M= has two: asked, then fallback).
    #   /v1 reports the loaded model of whoever answers in the body, not as a label.
    "pre_byte": {
        "mlx llama_cpp ollama": (
            "200 by={F} saved fb={X}/execution_failed asked={X}>{F}",
            "200 by={F} finish=stop saved fb={X}/execution_failed asked={X}>{F}",
            "200 by={F} saved asked={X}>{F}",
            "200 by={F} saved E={F} M={DM}>{FM} asked={X}>{F}",
        ),
    },
    # An out-of-memory in the engine is, for the cascade, an engine failing (it is retried),
    # Ollama's daemon 500 included (N2): same as pre_byte.
    "oom": {
        "mlx llama_cpp ollama": (
            "200 by={F} saved fb={X}/execution_failed asked={X}>{F}",
            "200 by={F} finish=stop saved fb={X}/execution_failed asked={X}>{F}",
            "200 by={F} saved asked={X}>{F}",
            "200 by={F} saved E={F} M={DM}>{FM} asked={X}>{F}",
        ),
    },
    # A bad request is bad for every engine: no other engine is asked, and the door shows it.
    # N1 (applied): the streaming /v1 forwarders of MLX and llama.cpp hand the cascade the
    #   engine's own exception (`TokenBridge.failure`), so a bad request is final streamed as
    #   in JSON; they used to turn it into `RuntimeError(bridge.error)` and the fallback answered.
    # N5 (applied): Ollama's 400 is a bad request at both doors — on the web the module's
    #   `OllamaSemanticError` carries the status, and it used to be retried (MLX answered).
    # The web stream says it with the generic notice (the notice is curated; D3).
    "bad_request": {
        "mlx llama_cpp ollama": (
            "400 not-saved asked={X}",
            "400 not-saved asked={X}",
            "400 not-saved asked={X}",
            "200 notice=error not-saved M={DM} asked={X}",
        ),
    },
    # An engine that cannot be reached is down: the next engine answers (N5, applied; a
    # builtin ConnectionError used to be a terminal 503). The /v1 stream already moved on
    # (N1 lost the class). R2 (applied): Ollama's daemon down at /v1 is the same — its chat
    # is never asked (the tag list fails first), the fallback answers and names the switch.
    "unreachable": {
        "mlx llama_cpp": (
            "200 by={F} saved fb={X}/execution_failed asked={X}>{F}",
            "200 by={F} finish=stop saved fb={X}/execution_failed asked={X}>{F}",
            "200 by={F} saved asked={X}>{F}",
            "200 by={F} saved E={F} M={DM}>{FM} asked={X}>{F}",
        ),
        "ollama": (
            "200 by={F} saved fb={X}/execution_failed asked={F}",
            "200 by={F} finish=stop saved fb={X}/execution_failed asked={F}",
            "200 by={F} saved asked={X}>{F}",
            "200 by={F} saved E={F} M={DM}>{FM} asked={X}>{F}",
        ),
    },
    # An engine too slow is down, whoever measured it (N5, applied): a builtin TimeoutError
    # used to be a terminal 504 and httpx's timeout a retry. Now both are the next engine's.
    "timeout": {
        "mlx llama_cpp ollama": (
            "200 by={F} saved fb={X}/execution_failed asked={X}>{F}",
            "200 by={F} finish=stop saved fb={X}/execution_failed asked={X}>{F}",
            "200 by={F} saved asked={X}>{F}",
            "200 by={F} saved E={F} M={DM}>{FM} asked={X}>{F}",
        ),
    },
    # Fails after its first token.
    # JSON (both doors): nothing was sent yet, so the whole answer is retried on the next engine.
    # Stream: the engine that gave a byte owns the turn.
    # N3: what the client is told differs. Web stream: the notice is written inside the chat and
    #   the partial answer is kept. /v1 stream of MLX/llama.cpp: the stream closes with
    #   `finish_reason: stop` — nothing says it was cut — and the partial is kept. /v1 stream of
    #   Ollama: the exception tears the connection down and nothing is kept.
    "mid_stream": {
        "mlx llama_cpp": (
            "200 by={F} saved fb={X}/execution_failed asked={X}>{F}",
            "200 by={X} finish=stop saved asked={X}",
            "200 by={F} saved asked={X}>{F}",
            "200 notice=error saved E={X} M={DM} asked={X}",
        ),
        "ollama": (
            "200 by={F} saved fb={X}/execution_failed asked={X}>{F}",
            "200 cut=ReadError by={X} not-saved asked={X}",
            "200 by={F} saved asked={X}>{F}",
            "200 notice=error saved E={X} M={DM} asked={X}",
        ),
    },
    # B7: the loading banner exists only on the web stream, once per turn. /v1 and the web JSON
    # answer without one (a client that cuts a long load is the review's open question). D4:
    # /v1 stays without a notice — there is nothing to build.
    "loading": {
        "mlx llama_cpp ollama": (
            "200 by={X} saved asked={X}",
            "200 by={X} finish=stop saved asked={X}",
            "200 by={X} saved asked={X}",
            "200 by={X} saved E={X} M={DM} loading=1 asked={X}",
        ),
    },
    # R3: an engine that answers with nothing. Web JSON treats it as a failure and tries the next
    # engine; /v1 (both shapes) returns the empty answer as a 200 and keeps nothing; the web stream
    # lets the first event claim the engine, labels it, and ends empty, not kept.
    "empty": {
        "mlx llama_cpp ollama": (
            "200 empty not-saved asked={X}",
            "200 finish=stop empty not-saved asked={X}",
            "200 by={F} saved asked={X}>{F}",
            "200 empty not-saved E={X} M={DM} asked={X}",
        ),
    },
    # A model that does not exist, asked of the engine the client named: final, at both doors
    #   (N5, applied: the web retried Ollama's `ModelNotFoundError` and MLX answered under its
    #   model; it carries 404, and a 404 is final for the engine asked for). MLX/llama.cpp never
    #   look at the name at /v1 (B2: /v1 answers with the loaded model).
    # #1141 (fixed): the web switches the model of candidate 0 in the `engine` step, outside the
    #   cascade, and MLX/llama.cpp refuse a name that is not theirs with a ValueError("not found").
    #   The step now gives the cascade's own verdict (`raise_if_terminal`): a terminal 404, not kept,
    #   and NO engine is asked. It used to be a generic 200 "Error: an internal error…".
    "not_found": {
        "mlx llama_cpp": (
            "200 by={X} saved asked={X}",
            "200 by={X} finish=stop saved asked={X}",
            "404 not-saved",
            "404 not-saved",
        ),
        "ollama": (
            "404 not-saved",
            "404 not-saved",
            "404 not-saved asked={X}",
            "200 notice=error not-saved M=model-que-no-existeix asked={X}",
        ),
    },
    # The client has left AND the engine dies with it (the worker stops because its cancel
    # event was set and raises — the case of #1117's own test; an engine that stops cleanly
    # and returns what it had is another event). N4 (applied): a client that left is asked
    # nothing more, at every door — the rule is the core's, on WHY the event was set
    # (`cancel.client_gone`), not a door's flag. Nobody claims: /v1 and the web JSON a 503
    # with the first failure, curated; the web stream its notice, as before. The JSON doors
    # and /v1 used to go on down the cascade for an answer nobody would read.
    "gone": {
        "mlx llama_cpp ollama": (
            "503 not-saved asked={X}",
            "503 not-saved asked={X}",
            "503 not-saved asked={X}",
            "200 notice=error not-saved M={DM} asked={X}",
        ),
    },
}

#: The same four doors when EVERY engine fails the same way (`engine` is asked first).
EVERY: dict[str, dict[str, tuple[str, str, str, str]]] = {
    # Q — the same failure at every engine, asked from `{X}` down. An engine failing, so the cascade
    # goes all the way, at both doors and whoever is last (N2, applied: Ollama's daemon 500 at /v1 is
    # an engine failing too; it used to end the turn with a 500 where it stood, first or last).
    # Nobody answers: /v1 and the web JSON a 503 with the curated text of the FIRST error (D2/D3);
    # the web stream a 200 and the curated notice of the FIRST engine that failed (#1117; D3), unsaved.
    "pre_byte": {
        "mlx": (
            "503 not-saved asked={X}>llama_cpp>ollama",
            "503 not-saved asked={X}>llama_cpp>ollama",
            "503 not-saved asked={X}>llama_cpp>ollama",
            "200 notice=error not-saved M={DM} asked={X}>llama_cpp>ollama",
        ),
        "llama_cpp": (
            "503 not-saved asked={X}>mlx>ollama",
            "503 not-saved asked={X}>mlx>ollama",
            "503 not-saved asked={X}>mlx>ollama",
            "200 notice=error not-saved M={DM} asked={X}>mlx>ollama",
        ),
        "ollama": (
            "503 not-saved asked={X}>mlx>llama_cpp",
            "503 not-saved asked={X}>mlx>llama_cpp",
            "503 not-saved asked={X}>mlx>llama_cpp",
            "200 notice=error not-saved M={DM} asked={X}>mlx>llama_cpp",
        ),
    },
    # The web stream keeps the OOM notice of the first engine (mlx/llama.cpp) — but when the
    # first is Ollama, whose daemon text is not recognised as an OOM, the generic one.
    "oom": {
        "mlx": (
            "503 not-saved asked={X}>llama_cpp>ollama",
            "503 not-saved asked={X}>llama_cpp>ollama",
            "503 not-saved asked={X}>llama_cpp>ollama",
            "200 notice=oom not-saved M={DM} asked={X}>llama_cpp>ollama",
        ),
        "llama_cpp": (
            "503 not-saved asked={X}>mlx>ollama",
            "503 not-saved asked={X}>mlx>ollama",
            "503 not-saved asked={X}>mlx>ollama",
            "200 notice=oom not-saved M={DM} asked={X}>mlx>ollama",
        ),
        "ollama": (
            "503 not-saved asked={X}>mlx>llama_cpp",
            "503 not-saved asked={X}>mlx>llama_cpp",
            "503 not-saved asked={X}>mlx>llama_cpp",
            "200 notice=error not-saved M={DM} asked={X}>mlx>llama_cpp",
        ),
    },
    # The first engine that gave a byte owns the stream at both streams (N3 as above). The JSON
    # cascades through all and ends: both doors with a 503 (D3 made /v1's the curated first error;
    # it was the last engine's raw exception, a bare 500).
    "mid_stream": {
        "mlx": (
            "503 not-saved asked={X}>llama_cpp>ollama",
            "200 by={X} finish=stop saved asked={X}",
            "503 not-saved asked={X}>llama_cpp>ollama",
            "200 notice=error saved E={X} M={DM} asked={X}",
        ),
        "llama_cpp": (
            "503 not-saved asked={X}>mlx>ollama",
            "200 by={X} finish=stop saved asked={X}",
            "503 not-saved asked={X}>mlx>ollama",
            "200 notice=error saved E={X} M={DM} asked={X}",
        ),
        "ollama": (
            "503 not-saved asked={X}>mlx>llama_cpp",
            "200 cut=ReadError by={X} not-saved asked={X}",
            "503 not-saved asked={X}>mlx>llama_cpp",
            "200 notice=error saved E={X} M={DM} asked={X}",
        ),
    },
    # R3 again: /v1 returns an empty 200 from the first engine; web JSON asks all three, 503.
    "empty": {
        "mlx": (
            "200 empty not-saved asked={X}",
            "200 finish=stop empty not-saved asked={X}",
            "503 not-saved asked={X}>llama_cpp>ollama",
            "200 empty not-saved E={X} M={DM} asked={X}",
        ),
        "llama_cpp": (
            "200 empty not-saved asked={X}",
            "200 finish=stop empty not-saved asked={X}",
            "503 not-saved asked={X}>mlx>ollama",
            "200 empty not-saved E={X} M={DM} asked={X}",
        ),
        "ollama": (
            "200 empty not-saved asked={X}",
            "200 finish=stop empty not-saved asked={X}",
            "503 not-saved asked={X}>mlx>llama_cpp",
            "200 empty not-saved E={X} M={DM} asked={X}",
        ),
    },
    # A bad request is final at the first engine, at every door (N1 and N5, applied): 400 at both JSON
    # doors and at the /v1 stream, the generic notice in the web stream. The /v1 stream of MLX/llama.cpp
    # used to lose the class and ask every engine; the web retried Ollama's 400 and MLX gave it.
    "bad_request": {
        "mlx llama_cpp ollama": (
            "400 not-saved asked={X}",
            "400 not-saved asked={X}",
            "400 not-saved asked={X}",
            "200 notice=error not-saved M={DM} asked={X}",
        ),
    },
    # Every engine down (N5, applied): the cascade goes all the way and ends as Q, the first failure
    # curated. It used to stop at the first (a builtin ConnectionError was a terminal 503). Ollama's
    # daemon down is never asked its chat at /v1 (the tag list fails first); on the web it is.
    "unreachable": {
        "mlx": (
            "503 not-saved asked={X}>llama_cpp",
            "503 not-saved asked={X}>llama_cpp",
            "503 not-saved asked={X}>llama_cpp>ollama",
            "200 notice=error not-saved M={DM} asked={X}>llama_cpp>ollama",
        ),
        "llama_cpp": (
            "503 not-saved asked={X}>mlx",
            "503 not-saved asked={X}>mlx",
            "503 not-saved asked={X}>mlx>ollama",
            "200 notice=error not-saved M={DM} asked={X}>mlx>ollama",
        ),
        "ollama": (
            "503 not-saved asked=mlx>llama_cpp",
            "503 not-saved asked=mlx>llama_cpp",
            "503 not-saved asked={X}>mlx>llama_cpp",
            "200 notice=error not-saved M={DM} asked={X}>mlx>llama_cpp",
        ),
    },
    # Every engine too slow (N5, applied): the same as unreachable, and every door now agrees with the
    # /v1 stream, which already asked them all (N1 lost the class). A builtin TimeoutError was a 504.
    "timeout": {
        "mlx": (
            "503 not-saved asked={X}>llama_cpp>ollama",
            "503 not-saved asked={X}>llama_cpp>ollama",
            "503 not-saved asked={X}>llama_cpp>ollama",
            "200 notice=error not-saved M={DM} asked={X}>llama_cpp>ollama",
        ),
        "llama_cpp": (
            "503 not-saved asked={X}>mlx>ollama",
            "503 not-saved asked={X}>mlx>ollama",
            "503 not-saved asked={X}>mlx>ollama",
            "200 notice=error not-saved M={DM} asked={X}>mlx>ollama",
        ),
        "ollama": (
            "503 not-saved asked={X}>mlx>llama_cpp",
            "503 not-saved asked={X}>mlx>llama_cpp",
            "503 not-saved asked={X}>mlx>llama_cpp",
            "200 notice=error not-saved M={DM} asked={X}>mlx>llama_cpp",
        ),
    },
    # #1141 and R2 once more. (In-process engines answer here: /v1 ignores the model name and the web
    # fails before asking anything — same as PRIMARY. Ollama asked first: a 404, final, at both doors.)
    "not_found": {
        "mlx llama_cpp": (
            "200 by={X} saved asked={X}",
            "200 by={X} finish=stop saved asked={X}",
            "404 not-saved",
            "404 not-saved",
        ),
        "ollama": (
            "404 not-saved",
            "404 not-saved",
            "404 not-saved asked={X}",
            "200 notice=error not-saved M=model-que-no-existeix asked={X}",
        ),
    },
}

#: An in-process engine (`mlx`, `llama_cpp`) fails and Ollama is the only engine behind it.
OLLAMA_BEHIND: dict[str, dict[str, tuple[str, str, str, str]]] = {
    # Ollama is the only engine behind. It answers at both doors; on /v1 through the daemon, and the
    # fallback pair names the engine that failed. In reserve it is asked for its own model (B2/D1-x),
    # here the lab's default, and the web stream shows ITS label ([ENGINE:ollama]) with a single
    # [MODEL:] (the default name: no body model).
    "pre_byte": {
        "mlx llama_cpp": (
            "200 by=ollama saved fb={X}/execution_failed asked={X}>ollama",
            "200 by=ollama finish=stop saved fb={X}/execution_failed asked={X}>ollama",
            "200 by=ollama saved asked={X}>ollama",
            "200 by=ollama saved E=ollama M={DM} asked={X}>ollama",
        ),
    },
    "oom": {
        "mlx llama_cpp": (
            "200 by=ollama saved fb={X}/execution_failed asked={X}>ollama",
            "200 by=ollama finish=stop saved fb={X}/execution_failed asked={X}>ollama",
            "200 by=ollama saved asked={X}>ollama",
            "200 by=ollama saved E=ollama M={DM} asked={X}>ollama",
        ),
    },
    # A bad request, final at every door (N1, applied: the /v1 stream of an in-process forwarder used
    # to lose the class, and Ollama answered). An engine down or too slow: Ollama answers (N5, applied).
    "bad_request": {
        "mlx llama_cpp": (
            "400 not-saved asked={X}",
            "400 not-saved asked={X}",
            "400 not-saved asked={X}",
            "200 notice=error not-saved M={DM} asked={X}",
        ),
    },
    "unreachable": {
        "mlx llama_cpp": (
            "200 by=ollama saved fb={X}/execution_failed asked={X}>ollama",
            "200 by=ollama finish=stop saved fb={X}/execution_failed asked={X}>ollama",
            "200 by=ollama saved asked={X}>ollama",
            "200 by=ollama saved E=ollama M={DM} asked={X}>ollama",
        ),
    },
    "timeout": {
        "mlx llama_cpp": (
            "200 by=ollama saved fb={X}/execution_failed asked={X}>ollama",
            "200 by=ollama finish=stop saved fb={X}/execution_failed asked={X}>ollama",
            "200 by=ollama saved asked={X}>ollama",
            "200 by=ollama saved E=ollama M={DM} asked={X}>ollama",
        ),
    },
    # Ollama is not asked after a first byte (the engine that streamed it owns the answer).
    "mid_stream": {
        "mlx llama_cpp": (
            "200 by=ollama saved fb={X}/execution_failed asked={X}>ollama",
            "200 by={X} finish=stop saved asked={X}",
            "200 by=ollama saved asked={X}>ollama",
            "200 notice=error saved E={X} M={DM} asked={X}",
        ),
    },
    # R3 with Ollama behind: only the web JSON moves on to it.
    "empty": {
        "mlx llama_cpp": (
            "200 empty not-saved asked={X}",
            "200 finish=stop empty not-saved asked={X}",
            "200 by=ollama saved asked={X}>ollama",
            "200 empty not-saved E={X} M={DM} asked={X}",
        ),
    },
}

#: Q (R4): no engine registered; `True` = Ollama's daemon is up.
NONE: dict[bool, tuple[str, str, str, str]] = {
    # Q (R4), rule: /v1 with no live engine answers a 503, as the web: nothing
    # registered, so /v1 refuses before it asks anybody, whether the Ollama daemon is up or not.
    # It used to go to the daemon anyway (`or [engine]`) and answer 200 when it was up (the
    # fallback header naming the engine asked for) or its own 503 when it was not.
    # The web refuses at its `engine` step: a 503 whether or not the daemon is up.
    True: (
        "503 not-saved",
        "503 not-saved",
        "503 not-saved",
        "503 not-saved",
    ),
    False: (
        "503 not-saved",
        "503 not-saved",
        "503 not-saved",
        "503 not-saved",
    ),
}


def _row(table: dict, mode: str, engine: str) -> tuple:
    for engines, cells in table[mode].items():
        if engine in engines.split():
            return cells
    raise KeyError((mode, engine))


def _expand(cell: str, engine: str) -> str:
    fallback = fallback_for(engine)
    return cell.format(
        X=engine, F=fallback, FM=MODEL_OF.get(fallback, "<no fixed model>"), DM=DEFAULT_MODEL,
    )


def test_the_tables_name_every_mode_and_every_engine():
    assert set(PRIMARY) == set(PRIMARY_MODES)
    assert set(EVERY) == set(EVERY_MODES)
    assert set(OLLAMA_BEHIND) == set(OLLAMA_BEHIND_MODES)
    for mode in PRIMARY_MODES:
        for engine in ENGINES:
            assert len(_row(PRIMARY, mode, engine)) == len(DOORS)
    for mode in EVERY_MODES:
        for engine in ENGINES:
            assert len(_row(EVERY, mode, engine)) == len(DOORS)
    for mode in OLLAMA_BEHIND_MODES:
        for engine in ("mlx", "llama_cpp"):
            assert len(_row(OLLAMA_BEHIND, mode, engine)) == len(DOORS)


@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("mode", PRIMARY_MODES)
async def test_the_engine_asked_for_fails(turn_lab, mode, engine, door):
    """The first engine fails as `mode` says, a healthy one waits behind it."""
    seen = await primary_fails(turn_lab, engine, mode, door)
    expected = _expand(_row(PRIMARY, mode, engine)[DOORS.index(door)], engine)
    assert seen.sig() == expected


@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("mode", EVERY_MODES)
async def test_every_engine_fails(turn_lab, mode, engine, door):
    """Q: the same failure at every engine. What each door tells the client."""
    seen = await every_engine_fails(turn_lab, engine, mode, door)
    expected = _expand(_row(EVERY, mode, engine)[DOORS.index(door)], engine)
    assert seen.sig() == expected


@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("engine", ["mlx", "llama_cpp"])
@pytest.mark.parametrize("mode", OLLAMA_BEHIND_MODES)
async def test_ollama_is_the_healthy_engine_behind(turn_lab, mode, engine, door):
    """Ollama answers as the fallback: over HTTP at /v1, through its module on the web."""
    seen = await ollama_behind(turn_lab, engine, mode, door)
    expected = _expand(_row(OLLAMA_BEHIND, mode, engine)[DOORS.index(door)], engine)
    assert seen.sig() == expected


@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("daemon_up", [True, False])
async def test_no_engine_is_live(turn_lab, daemon_up, door):
    seen = await none_live(turn_lab, door, daemon_up)
    assert seen.sig() == NONE[daemon_up][DOORS.index(door)]


# ── P2-7: no cell tells the client raw text; what nexe wrote for the user arrives ──

def _curated_words() -> set:
    """The curated sentences a failed turn may say, by what it means, in every
    language, and the core's own for no engine at all."""
    from core.turn import errors
    from core.turn.engine_claim import NO_ENGINE_DETAIL
    tables = (errors._FAILED, errors._OOM_MLX, errors._OOM_GENERIC, errors._NOT_FOUND, errors._BAD_REQUEST,
              *errors._NO_ENGINE_CAN_ANSWER.values())
    return {text for table in tables for text in table.values()} | {NO_ENGINE_DETAIL}


#: Messages nexe writes for the user, handed on as they are (`user_text`): the model
#: switches («Model 'X' not found: …», #1154's «it has no weights»), the Ollama
#: forwarder's 404 with the models that are there, the Ollama plugin's, and a bad
#: request an engine refuses on purpose (`BadRequest`; the lab's stands for one).
_WRITTEN_FOR_THE_USER = (
    re.compile(r"^Model '.+' not found: .+$"),
    re.compile(r"^Model '.+' not found\. Available chat models: .+$"),
    re.compile(r"^Ollama model not found: .+$"),
    re.compile(r"^bad request: this engine cannot take it$"),
)

#: What the lab's engines and daemon say raw: none of it may reach a client.
_RAW = ("worker died", "internal error", "Internal Server Error", "connection refused", "took too long",
        "timed out", "requires more system memory", "[METAL]", "Client error", "Ollama returned HTTP",
        "http://", "11434", "Traceback")


def _said_for_the_user(detail: str) -> bool:
    return detail in _curated_words() or any(p.match(detail) for p in _WRITTEN_FOR_THE_USER)


def test_the_two_kinds_are_told_apart():
    assert _said_for_the_user("The engine could not accept this request.")
    assert _said_for_the_user("Model 'x' not found: it has no weights (*.safetensors) under the models directory")
    assert not _said_for_the_user("bad request")  # the daemon's own body
    assert not _said_for_the_user("Client error '401 Unauthorized' for url 'http://127.0.0.1:11434/api/chat'")


_EVERY_CELL = (
    [("primary", mode, engine, door) for mode in PRIMARY_MODES for engine in ENGINES for door in DOORS]
    + [("every", mode, engine, door) for mode in EVERY_MODES for engine in ENGINES for door in DOORS]
    + [("behind", mode, engine, door) for mode in OLLAMA_BEHIND_MODES for engine in ("mlx", "llama_cpp")
       for door in DOORS]
)


@pytest.mark.parametrize("table,mode,engine,door", _EVERY_CELL)
async def test_no_cell_tells_the_client_raw_text(turn_lab, table, mode, engine, door):
    """P2-7: whatever a cell answers with an HTTP error is either a curated sentence
    or a message nexe wrote for the user — never an engine's or an exception's own
    words (an internal URL, a reshape, a pydantic dump, the daemon's error body)."""
    run = {"primary": primary_fails, "every": every_engine_fails, "behind": ollama_behind}[table]
    seen = await run(turn_lab, engine, mode, door)
    if seen.status >= 400:
        assert _said_for_the_user(seen.detail), (table, mode, engine, door, seen.detail)
        assert not any(raw in seen.detail for raw in _RAW), (table, mode, engine, door, seen.detail)


@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("daemon_up", [True, False])
async def test_no_cell_without_engines_tells_anything_else(turn_lab, daemon_up, door):
    seen = await none_live(turn_lab, door, daemon_up)
    if seen.status >= 400:
        assert _said_for_the_user(seen.detail), seen.detail
