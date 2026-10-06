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
  forwarders lose the engine's error class; N2 every HTTP error of Ollama's daemon is
  terminal at `/v1`; N3 what a failure after the first byte looks like; N4 a client that
  leaves; N5 the policy keys on the exception CLASS; N6 `/v1` labels an engine that was
  never asked as the one it fell back from (rows file); N7 the `/v1` re-prompt was recorded
  under the engine of the first answer (gone since R1: it names the engine it was asked of).

A later part of C4.8 changes the cells whose row was decided, and only those;
any other cell turning red is a regression.

The notation of a cell: `200 by=llama_cpp saved fb=mlx/execution_failed
asked=mlx>llama_cpp` — `{X}` is the engine the client asked for, `{F}` the
healthy engine behind it (the first of mlx → llama_cpp → ollama that is not
`{X}`), `{FM}` the model `{F}` runs, `{DM}` the default model name the web door
sends when the body names none.
"""
from __future__ import annotations

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
    # Fails before its first byte, in a way the cascade retries: the next engine answers.
    # N2 (R2 generalised): on /v1 Ollama is a daemon over HTTP, and every HTTP error it
    #   answers is an HTTPException, terminal for the cascade: a 500 and nobody else is asked,
    #   with a healthy engine waiting. On the web the module raises and the cascade moves on.
    # B5: /v1 names the switch (fb=); the web names it with its labels (E=, M=).
    # B2 (#1035): the web fallback answers under ITS model (M= has two: asked, then fallback).
    #   /v1 reports the loaded model of whoever answers in the body, not as a label.
    "pre_byte": {
        "mlx llama_cpp": (
            "200 by={F} saved fb={X}/execution_failed asked={X}>{F}",
            "200 by={F} finish=stop saved fb={X}/execution_failed asked={X}>{F}",
            "200 by={F} saved asked={X}>{F}",
            "200 by={F} saved E={F} M={DM}>{FM} asked={X}>{F}",
        ),
        "ollama": (
            "500 not-saved asked={X}",
            "500 not-saved asked={X}",
            "200 by={F} saved asked={X}>{F}",
            "200 by={F} saved E={F} M={DM}>{FM} asked={X}>{F}",
        ),
    },
    # An out-of-memory in the engine is, for the cascade, a failure like any other (it is
    # retried). Same differences as pre_byte, and N2 for Ollama: the daemon's 500.
    "oom": {
        "mlx llama_cpp": (
            "200 by={F} saved fb={X}/execution_failed asked={X}>{F}",
            "200 by={F} finish=stop saved fb={X}/execution_failed asked={X}>{F}",
            "200 by={F} saved asked={X}>{F}",
            "200 by={F} saved E={F} M={DM}>{FM} asked={X}>{F}",
        ),
        "ollama": (
            "500 not-saved asked={X}",
            "500 not-saved asked={X}",
            "200 by={F} saved asked={X}>{F}",
            "200 by={F} saved E={F} M={DM}>{FM} asked={X}>{F}",
        ),
    },
    # A ValueError is bad for every engine (`should_try_next_engine`): no other engine is
    # asked, and the door shows it.
    # N1: the streaming /v1 forwarders of MLX and llama.cpp turn the engine's error into
    #   `RuntimeError(bridge.error)` (the class is lost), so what is terminal in JSON is
    #   retried when streamed: the fallback answers. The web streams and JSON agree on
    #   the policy but differ in what they show: JSON 400 with the engine's text, the
    #   stream a 200 with the generic notice (the notice is curated; D3).
    # Ollama on /v1: the daemon's 400 is an HTTPException: terminal in both shapes (N2).
    # Ollama on the web: the module turns the daemon's 400 into `OllamaSemanticError`, a plain
    #   Exception, so the cascade RETRIES it and MLX answers — a ValueError is what is final.
    "bad_request": {
        "mlx llama_cpp": (
            "400 not-saved asked={X}",
            "200 by={F} finish=stop saved fb={X}/execution_failed asked={X}>{F}",
            "400 not-saved asked={X}",
            "200 notice=error not-saved M={DM} asked={X}",
        ),
        "ollama": (
            "400 not-saved asked={X}",
            "400 not-saved asked={X}",
            "200 by={F} saved asked={X}>{F}",
            "200 by={F} saved E={F} M={DM}>{FM} asked={X}>{F}",
        ),
    },
    # A ConnectionError is terminal (`engine_error_to_http`: 503), as the user asked for a
    # machine that is down. Same N1 as above for the streaming /v1 forwarders.
    # R2: Ollama's daemon down is a 503 terminal on /v1 (no engine asked, not even its
    #   own chat); on the web the module's `httpx.ConnectError` is not a builtin
    #   ConnectionError, so it is retried and MLX answers.
    "unreachable": {
        "mlx llama_cpp": (
            "503 not-saved asked={X}",
            "200 by={F} finish=stop saved fb={X}/execution_failed asked={X}>{F}",
            "503 not-saved asked={X}",
            "200 notice=error not-saved M={DM} asked={X}",
        ),
        "ollama": (
            "503 not-saved",
            "503 not-saved",
            "200 by={F} saved asked={X}>{F}",
            "200 by={F} saved E={F} M={DM}>{FM} asked={X}>{F}",
        ),
    },
    # A builtin TimeoutError is terminal (504); httpx's timeout is not (N5: the policy
    # keys on the CLASS, so the same event is final or retried by who raised it). Same N1.
    "timeout": {
        "mlx llama_cpp": (
            "504 not-saved asked={X}",
            "200 by={F} finish=stop saved fb={X}/execution_failed asked={X}>{F}",
            "504 not-saved asked={X}",
            "200 notice=error not-saved M={DM} asked={X}",
        ),
        "ollama": (
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
    # answer without one (a client that cuts a long load is the review's open question). D4
    # (provisional 06/10): /v1 stays without a notice — there is nothing to build.
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
    # A model that does not exist. R2: on /v1 Ollama's 404 is terminal; MLX/llama.cpp never look
    #   at the name (B2: /v1 answers with the loaded model).
    # On the web, Ollama's `ModelNotFoundError` is retried (#1035): MLX answers under its model.
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
            "200 by={F} saved asked={X}>{F}",
            "200 by={F} saved E={F} M=model-que-no-existeix>{FM} asked={X}>{F}",
        ),
    },
    # The client has left AND the engine dies with it (the worker stops because its cancel
    # event was set and raises — the case of #1117's own test; an engine that stops cleanly
    # and returns what it had is another event). N4: only the web STREAM then stops asking
    # engines (its cascade checks the cancel event); the web JSON and /v1 keep asking down the
    # cascade for an answer nobody will read. (Ollama on /v1: its 500 ends the turn, as in pre_byte.)
    "gone": {
        "mlx llama_cpp": (
            "200 by={F} saved fb={X}/execution_failed asked={X}>{F}",
            "200 by={F} finish=stop saved fb={X}/execution_failed asked={X}>{F}",
            "200 by={F} saved asked={X}>{F}",
            "200 notice=error not-saved M={DM} asked={X}",
        ),
        "ollama": (
            "500 not-saved asked={X}",
            "500 not-saved asked={X}",
            "200 by={F} saved asked={X}>{F}",
            "200 notice=error not-saved M={DM} asked={X}",
        ),
    },
}

#: The same four doors when EVERY engine fails the same way (`engine` is asked first).
EVERY: dict[str, dict[str, tuple[str, str, str, str]]] = {
    # Q — the same failure at every engine, asked from `{X}` down. Retryable, so the cascade goes
    # all the way. /v1 JSON and stream: Ollama is last, and its daemon error is an HTTPException,
    # terminal: a 500 with the daemon's text (JSON) or the generic "Ollama returned HTTP 500" (stream).
    # (When the last engine fails with something retryable — in-process engines last, the mid_stream
    # and timeout modes below — D3 [IA, provisional 06/10] makes /v1 answer a 503 with the curated text
    # of the FIRST error; it used to be `raise last_exc`, the framework's bare 500.
    # test_c48_p0_rows, test_q_v1_with_every...)
    # Web JSON: 503 with the curated text of the first error (D2); web stream: 200 and the
    # curated notice of the FIRST engine that failed (#1117; D3), unsaved.
    "pre_byte": {
        "mlx": (
            "500 not-saved asked={X}>llama_cpp>ollama",
            "500 not-saved asked={X}>llama_cpp>ollama",
            "503 not-saved asked={X}>llama_cpp>ollama",
            "200 notice=error not-saved M={DM} asked={X}>llama_cpp>ollama",
        ),
        "llama_cpp": (
            "500 not-saved asked={X}>mlx>ollama",
            "500 not-saved asked={X}>mlx>ollama",
            "503 not-saved asked={X}>mlx>ollama",
            "200 notice=error not-saved M={DM} asked={X}>mlx>ollama",
        ),
        "ollama": (
            "500 not-saved asked={X}",
            "500 not-saved asked={X}",
            "503 not-saved asked={X}>mlx>llama_cpp",
            "200 notice=error not-saved M={DM} asked={X}>mlx>llama_cpp",
        ),
    },
    # The web stream keeps the OOM notice of the first engine (mlx/llama.cpp) — but when the
    # first is Ollama, whose daemon text is not recognised as an OOM, the generic one.
    "oom": {
        "mlx": (
            "500 not-saved asked={X}>llama_cpp>ollama",
            "500 not-saved asked={X}>llama_cpp>ollama",
            "503 not-saved asked={X}>llama_cpp>ollama",
            "200 notice=oom not-saved M={DM} asked={X}>llama_cpp>ollama",
        ),
        "llama_cpp": (
            "500 not-saved asked={X}>mlx>ollama",
            "500 not-saved asked={X}>mlx>ollama",
            "503 not-saved asked={X}>mlx>ollama",
            "200 notice=oom not-saved M={DM} asked={X}>mlx>ollama",
        ),
        "ollama": (
            "500 not-saved asked={X}",
            "500 not-saved asked={X}",
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
    # Terminal at the first in-process engine: 400 at both JSON doors and at /v1 stream, the web
    # stream says it with the generic notice. When Ollama is asked first its error is retried on the
    # web (it is not a ValueError) and the next engine gives the terminal 400; /v1 stops at Ollama.
    "bad_request": {
        "mlx": (
            "400 not-saved asked={X}",
            "400 not-saved asked={X}>llama_cpp>ollama",
            "400 not-saved asked={X}",
            "200 notice=error not-saved M={DM} asked={X}",
        ),
        "llama_cpp": (
            "400 not-saved asked={X}",
            "400 not-saved asked={X}>mlx>ollama",
            "400 not-saved asked={X}",
            "200 notice=error not-saved M={DM} asked={X}",
        ),
        "ollama": (
            "400 not-saved asked={X}",
            "400 not-saved asked={X}",
            "400 not-saved asked={X}>mlx",
            "200 notice=error not-saved M={DM} asked={X}>mlx",
        ),
    },
    # Terminal 503, same shape. (Ollama first on /v1: the daemon's own text, no engine asked.)
    "unreachable": {
        "mlx": (
            "503 not-saved asked={X}",
            "503 not-saved asked={X}>llama_cpp",
            "503 not-saved asked={X}",
            "200 notice=error not-saved M={DM} asked={X}",
        ),
        "llama_cpp": (
            "503 not-saved asked={X}",
            "503 not-saved asked={X}>mlx",
            "503 not-saved asked={X}",
            "200 notice=error not-saved M={DM} asked={X}",
        ),
        "ollama": (
            "503 not-saved",
            "503 not-saved",
            "503 not-saved asked={X}>mlx",
            "200 notice=error not-saved M={DM} asked={X}>mlx",
        ),
    },
    # N5 and N1: the in-process 504 is terminal in JSON; in /v1 stream the class is lost and every
    # engine is asked, ending (D3) with a 503 (it was the last one's exception, a bare 500).
    "timeout": {
        "mlx": (
            "504 not-saved asked={X}",
            "503 not-saved asked={X}>llama_cpp>ollama",
            "504 not-saved asked={X}",
            "200 notice=error not-saved M={DM} asked={X}",
        ),
        "llama_cpp": (
            "504 not-saved asked={X}",
            "503 not-saved asked={X}>mlx>ollama",
            "504 not-saved asked={X}",
            "200 notice=error not-saved M={DM} asked={X}",
        ),
        "ollama": (
            "504 not-saved asked={X}>mlx",
            "503 not-saved asked={X}>mlx>llama_cpp",
            "504 not-saved asked={X}>mlx",
            "200 notice=error not-saved M={DM} asked={X}>mlx",
        ),
    },
    # #1141 and R2 once more. (In-process engines answer here: /v1 ignores the model name and the web
    # fails before asking anything — same as PRIMARY. Ollama asked first: /v1 404 terminal, web MLX.)
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
            "200 by=mlx saved asked={X}>mlx",
            "200 by=mlx saved E=mlx M=model-que-no-existeix>Qwen3.5-4B-MLX-4bit asked={X}>mlx",
        ),
    },
}

#: An in-process engine (`mlx`, `llama_cpp`) fails and Ollama is the only engine behind it.
OLLAMA_BEHIND: dict[str, dict[str, tuple[str, str, str, str]]] = {
    # Ollama is the only engine behind. It answers at both doors; on /v1 through the daemon, and the
    # fallback pair names the engine that failed. On the web it is asked for the requested name, and the
    # stream shows ITS label ([ENGINE:ollama]) with a single [MODEL:] (the default name: no body model).
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
    # N1 and the terminal classes once more, now with Ollama as the healthy engine behind: it answers
    # only when the stream of an in-process /v1 forwarder lost the error class.
    "bad_request": {
        "mlx llama_cpp": (
            "400 not-saved asked={X}",
            "200 by=ollama finish=stop saved fb={X}/execution_failed asked={X}>ollama",
            "400 not-saved asked={X}",
            "200 notice=error not-saved M={DM} asked={X}",
        ),
    },
    "unreachable": {
        "mlx llama_cpp": (
            "503 not-saved asked={X}",
            "200 by=ollama finish=stop saved fb={X}/execution_failed asked={X}>ollama",
            "503 not-saved asked={X}",
            "200 notice=error not-saved M={DM} asked={X}",
        ),
    },
    "timeout": {
        "mlx llama_cpp": (
            "504 not-saved asked={X}",
            "200 by=ollama finish=stop saved fb={X}/execution_failed asked={X}>ollama",
            "504 not-saved asked={X}",
            "200 notice=error not-saved M={DM} asked={X}",
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
    # Q (R4), decided provisionally 06/10 («/v1 with no live engine -> 503, as the web»): nothing
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
