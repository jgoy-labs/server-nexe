"""C4.8-e: the vocabulary of the differences between the two doors is closed, and
what the register says about the applied and kept ones is true of the code.

The part 0 matrix pins what each door does when an engine fails, and every place
where the doors differ names the row that explains it (B1-B7, R1-R4, N1-N7, Q, the
decisions D1-D4 and their sub-decisions D1-x/y/z). This file is the register. It
enforces two things, and only two: every label the matrix files use is here with a
state, and every label here is still used there (a label is found anywhere in the
file, so a cell without a label is NOT caught: the cells themselves are pinned by
the matrix); and each applied/kept label that can be probed in the code says
something that is true of it (PROBES), so a revert that leaves the register
untouched turns a test red.

The states are the honest ones. `applied` is a decision that was taken and is now
in the code (each one is a commit of its own, so it can be reverted on its own).
`kept` is a difference left on purpose, with the decision to leave it. `open` is a
difference nobody has decided: it stays written in the cells and is a candidate for
a decision, not a finished row. Moving a label to another state is a decision and
belongs in a commit of its own.
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = ("test_c48_p0_matrix.py", "test_c48_p0_rows.py", "_c48_p0_scenarios.py", "_c48_p0_lab.py")

APPLIED, KEPT, OPEN = "applied", "kept", "open"

REGISTER: dict[str, tuple[str, str]] = {
    "B1": (OPEN, "the reply reserve the prompt is fitted with: the web 125 tokens (fallbacks only), /v1 max_tokens (every engine)"),
    "B2": (OPEN, "Ollama in reserve is asked for the requested name (D1-x/y open); the not-found half is D1-z"),
    "B3": (OPEN, "which engines can resume; N6, /v1 names a fallback_from it never asked"),
    "B4": (APPLIED, "no engine answers: see Q and D3"),
    "B5": (OPEN, "what each door records about the engine that answered (counters and headers at /v1, stats at the web)"),
    "B6": (KEPT, "the hold of the gate, the monitor and the deadline is one (C4.8-d): the doors agree from outside"),
    "B7": (KEPT, "no loading notice at /v1 (D4 provisional, nothing to build)"),
    "R1": (APPLIED, "the /v1 re-prompt goes to the engine that answered (9c8b18a4)"),
    "R2": (OPEN, "every HTTP error of Ollama's daemon ends the cascade at /v1 (N2); the not-found half is D1-z"),
    "R3": (KEPT, "an empty reply moves on only at the web JSON door: not unified, on purpose"),
    "R4": (APPLIED, "/v1 with no live engine is a 503 (daf8917a)"),
    "N1": (KEPT, "the streaming /v1 forwarders lose the error class: not touched, on purpose"),
    "N2": (KEPT, "every HTTP error of the daemon is terminal at /v1: not touched, on purpose"),
    "N3": (KEPT, "a failure after the first byte looks different at each door: not touched, on purpose"),
    "N4": (OPEN, "only the web stream stops asking engines once the client left"),
    "N5": (OPEN, "the policy keys on the exception class, so the same event is final or retried by who raised it"),
    "N6": (OPEN, "/v1 labels an engine it never asked as the one it fell back from"),
    "N7": (APPLIED, "the re-prompt record names the engine it was asked of (R1 removed it)"),
    "D1": (APPLIED, "a flag per door for the first engine's model (6dbf519b)"),
    "D1-x": (OPEN, "Ollama in reserve is asked for the name the client sent, as before (D1 residual x/y not decided)"),
    "D1-z": (APPLIED, "at /v1 a 404 from an engine in reserve is passed over (a8955e25); the web's first engine is untouched"),
    "D2": (APPLIED, "the web JSON 503 tells the first error curated (f8fec3a4)"),
    "D3": (APPLIED, "the first error, curated, at every door (f8fec3a4, 394cae0f, 9a95fba1)"),
    "D4": (KEPT, "no loading notice at /v1"),
    "Q": (APPLIED, "nobody answers: D2 and D3"),
}

# Any B/R/N/D plus one or two digits is a label: an invented N8 must not slip through.
_LABEL = re.compile(r"\b([BRND]\d{1,2}(?:-[a-z])?|Q)\b")


def _used() -> set[str]:
    return {m for name in FILES for m in _LABEL.findall((HERE / name).read_text(encoding="utf-8"))}


def test_every_label_the_matrix_uses_is_in_the_register():
    unclassified = _used() - set(REGISTER)
    assert not unclassified, f"differences nobody classified: {sorted(unclassified)}"


def test_every_label_in_the_register_is_still_used_by_the_matrix():
    stale = set(REGISTER) - _used()
    assert not stale, f"labels the matrix no longer mentions: {sorted(stale)}"


def test_the_states_are_the_three_honest_ones_and_each_says_why():
    for label, (state, why) in REGISTER.items():
        assert state in {APPLIED, KEPT, OPEN}, label
        assert len(why) > 20, label


def test_what_is_still_open_is_counted_not_hidden():
    """Nine rows are open on 06/10; this list moves when somebody decides one."""
    assert sorted(label for label, (state, _why) in REGISTER.items() if state == OPEN) == [
        "B1", "B2", "B3", "B5", "D1-x", "N4", "N5", "N6", "R2",
    ]


# ── the applied and the kept are true of the code ────────────────────────────

import core.endpoints.chat  # noqa: F401,E402  (breaks a circular import: core.turn.adapters_api cannot be imported first)


def _source(obj) -> str:
    import inspect
    return inspect.getsource(obj)


def _probe_r1() -> bool:
    from core.turn import adapters_api
    text = _source(adapters_api._v1_reprompt_call)
    return "ask_again" in text and "dispatch_v1" not in text


def _probe_r4() -> bool:
    from core.turn import api_cascade
    return "live_candidates" in _source(api_cascade.dispatch_v1)


def _probe_d1() -> bool:
    from core.turn.context import TurnContext
    return "model_follows_request" in TurnContext.__dataclass_fields__


def _probe_d1z() -> bool:
    from core.turn.api_cascade import ApiDoor, ModelNotOnFallback
    return issubclass(ModelNotOnFallback, RuntimeError) and "ModelNotOnFallback" in _source(ApiDoor.read_first)


def _probe_d2() -> bool:
    """The default end of a cascade is the curated 503, and the web JSON door does not override it."""
    from core.turn.engine_claim import CascadeDoor
    from plugins.web_ui_module.api.engine_doors import JsonDoor
    ended = CascadeDoor().exhausted(RuntimeError("x"), None)
    return getattr(ended, "status_code", None) == 503 and "exhausted" not in vars(JsonDoor)


def _probe_d3() -> bool:
    """The web stream stands the first failure in, and /v1 ends like the default (no override)."""
    from core.turn.api_cascade import ApiDoor
    from core.turn.engine_claim import CascadeDoor
    from plugins.web_ui_module.api.engine_doors import StreamDoor
    return StreamDoor.stand_in is not CascadeDoor.stand_in and "exhausted" not in vars(ApiDoor)


def _probe_r3() -> bool:
    """An empty reply is passed over at the web JSON door only."""
    from core.turn.api_cascade import ApiDoor
    from plugins.web_ui_module.api.engine_doors import JsonDoor
    return "EmptyReply" in _source(JsonDoor.read_first) and "EmptyReply" not in _source(ApiDoor.read_first)


def _probe_d4() -> bool:
    """/v1 never announces a loading model: nothing of its door speaks of one."""
    from core.turn import api_cascade
    return "announce" not in vars(api_cascade.ApiDoor) and "loading" not in _source(api_cascade).lower()


def _probe_b6() -> bool:
    """The four doors hold the gate, the monitor and the deadline through one class."""
    from core.turn import adapters_api
    from plugins.web_ui_module.api import turn_adapters
    return all("EngineHold" in _source(module) for module in (adapters_api, turn_adapters))


def _probe_n4() -> bool:
    """Only the web stream stops asking engines once the client left."""
    from core.turn.api_cascade import ApiDoor
    from plugins.web_ui_module.api.engine_doors import JsonDoor, StreamDoor
    return StreamDoor.stop_when_cancelled is True and not JsonDoor.stop_when_cancelled and not ApiDoor.stop_when_cancelled


PROBES = {
    "R1": _probe_r1, "N7": _probe_r1, "R4": _probe_r4, "D1": _probe_d1, "D1-z": _probe_d1z,
    "D2": _probe_d2, "D3": _probe_d3, "Q": _probe_d3, "R3": _probe_r3, "D4": _probe_d4,
    "B7": _probe_d4, "B6": _probe_b6, "N4": _probe_n4,
}


def test_what_the_register_says_of_the_applied_and_the_kept_is_true_of_the_code():
    wrong = [label for label, probe in PROBES.items() if probe() is not True]
    assert not wrong, f"the register says something the code no longer does: {wrong}"
    assert set(PROBES) <= set(REGISTER)


def test_every_applied_or_kept_label_with_a_probe_is_probed_and_the_rest_are_said_not_to_be():
    """The labels whose state is a decision about behaviour a cell pins (N1-N3, B4, B5…) have no
    probe here: the matrix is their test. Listing them keeps that a choice, not an omission."""
    unprobed = sorted(label for label, (state, _why) in REGISTER.items() if state != OPEN and label not in PROBES)
    assert unprobed == ["B4", "N1", "N2", "N3"]
