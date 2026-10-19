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
FILES = ("test_c48_p0_matrix.py", "test_c48_p0_rows.py", "_c48_p0_scenarios.py", "_c48_p0_lab.py",
         "test_c48_p0_api.py", "_c48_p0_api_lab.py")

APPLIED, KEPT, OPEN = "applied", "kept", "open"

REGISTER: dict[str, tuple[str, str]] = {
    "B1": (APPLIED, "one reply reserve for the fitted prompt at both doors and every engine: max_tokens, else 125 (662b5ec2)"),
    "B2": (APPLIED, "an engine in reserve answers with its own model at both doors, Ollama with its default (D1-x) (8633094d)"),
    "B3": (APPLIED, "which engines can resume: one filter for both doors (live_candidates), and N6 for what is said of it (26e69dcd)"),
    "B4": (APPLIED, "no engine answers: see Q and D3"),
    "B5": (APPLIED, "what is shown stays each door's; what is recorded is one: the engine name and the fall-back (C5 B), the metrics of every attempt (C5 E, MetricsSink)"),
    "B6": (KEPT, "the hold of the gate, the monitor and the deadline is one (C4.8-d): the doors agree from outside"),
    "B7": (KEPT, "no loading notice at /v1 (D4, nothing to build)"),
    "R1": (APPLIED, "the /v1 re-prompt goes to the engine that answered (9c8b18a4)"),
    "R2": (APPLIED, "Ollama's daemon down or failing at /v1 is an engine down, the next answers (N5); 404: D1-z (55942538)"),
    "R3": (KEPT, "an empty reply moves on only at the web JSON door: not unified, on purpose"),
    "R4": (APPLIED, "/v1 with no live engine is a 503 (daf8917a)"),
    "N1": (APPLIED, "the streaming /v1 forwarders hand the cascade the engine's own exception (TokenBridge) (55942538)"),
    "N2": (APPLIED, "an HTTP error of Ollama's daemon at /v1 is read for what it means: a 5xx moves on (55942538)"),
    "N3": (KEPT, "a failure after the first byte looks different at each door: not touched, on purpose"),
    "N4": (APPLIED, "a client that left is asked nothing more at every door; a deadline is not a client that left (17a7e1ff)"),
    "N5": (APPLIED, "the policy reads what a failure means (routing.classify), one reading for both doors (55942538)"),
    "N6": (APPLIED, "/v1 tells the switch against the first engine it asked, never one a Continue left out (26e69dcd)"),
    "N7": (APPLIED, "the re-prompt record names the engine it was asked of (R1 removed it)"),
    "N8": (KEPT, "the API engine answers at both doors, only when asked for by name and past the cloud gate; never a fallback, never in the chain"),
    "N9": (KEPT, "the consent for the API is the session's at the web door (remembered, a dialog) and the request's own at /v1 (nexe_cloud_consent): /v1 has no session"),
    "N10": (KEPT, "at /v1 the API answers with the model the request names: it has none loaded, unlike the engines D1 is about"),
    "D1": (APPLIED, "a flag per door for the first engine's model (6dbf519b)"),
    "D1-x": (APPLIED, "y: Ollama in reserve asks its own default, never the name picked for the engine in front (8633094d)"),
    "D1-z": (APPLIED, "a 404 from an engine in reserve is passed over, at both doors: the policy's in_reserve (N5) (a8955e25, 55942538)"),
    "D2": (APPLIED, "the web JSON 503 tells the first error curated (f8fec3a4)"),
    "D3": (APPLIED, "the first error, curated, at every door (f8fec3a4, 394cae0f, 9a95fba1)"),
    "D4": (KEPT, "no loading notice at /v1"),
    "Q": (APPLIED, "nobody answers: D2 and D3"),
}

# Any B/R/N/D plus one or two digits is a label: an invented N11 must not slip through.
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
    """No row is open: every difference the matrix found is applied or kept, with the why."""
    assert sorted(label for label, (state, _why) in REGISTER.items() if state == OPEN) == []


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
    """A missing model moves on only from an engine in reserve, and the policy says so, not a door."""
    from fastapi import HTTPException

    from core.endpoints.chat_engines.routing import should_try_next_engine
    from core.turn import api_cascade
    missing = HTTPException(status_code=404, detail="no such model")
    return (should_try_next_engine(missing, in_reserve=True) is True
            and should_try_next_engine(missing) is False
            and "ModelNotOnFallback" not in _source(api_cascade))


def _probe_n5() -> bool:
    """One reading for both doors: the same event moves on, or ends the turn, whoever raised it."""
    import httpx
    from fastapi import HTTPException

    from core.endpoints.chat_engines.routing import should_try_next_engine as moves_on
    from core.turn.errors import BadRequest
    request = httpx.Request("POST", "http://127.0.0.1:11434/api/chat")
    down = (ConnectionError("x"), httpx.ConnectError("x"), TimeoutError("x"), httpx.ReadTimeout("x"),
            HTTPException(status_code=503), HTTPException(status_code=500), RuntimeError("oom"),
            HTTPException(status_code=401), ValueError("a ValueError nobody marked"),
            httpx.HTTPStatusError("x", request=request, response=httpx.Response(500, request=request)))
    final = (BadRequest("bad"), HTTPException(status_code=400), HTTPException(status_code=422),
             httpx.HTTPStatusError("x", request=request, response=httpx.Response(400, request=request)))
    return all(moves_on(e) for e in down) and not any(moves_on(e) for e in final)


def _probe_n1() -> bool:
    """The in-process /v1 streams raise the engine's own exception before a token, not its text."""
    from core.endpoints.chat_engines import llama_cpp, mlx
    from core.endpoints.chat_engines._streaming import TokenBridge
    return (callable(getattr(TokenBridge, "failure", None))
            and all("raise bridge.failure()" in _source(m) and "RuntimeError(bridge.error)" not in _source(m)
                    for m in (mlx, llama_cpp)))


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
    """One rule in the core, on why the event was set: no door carries a flag, a
    client that left stops the cascade and a deadline does not."""
    from core.turn.api_cascade import ApiDoor
    from core.turn.cancel import CLIENT_GONE, DEADLINE, TurnCancel
    from core.turn.engine_claim import CascadeDoor, _cancelled
    from plugins.web_ui_module.api.engine_doors import JsonDoor, StreamDoor
    gone, late = TurnCancel(), TurnCancel()
    gone.cancel(CLIENT_GONE)
    late.cancel(DEADLINE)
    return (not any(hasattr(door, "stop_when_cancelled") for door in (CascadeDoor, ApiDoor, JsonDoor, StreamDoor))
            and _cancelled(1, gone) and not _cancelled(1, late) and not _cancelled(0, gone))


def _probe_b1() -> bool:
    """Every fit of the prompt to a window asks the one rule for the reply reserve."""
    from core.endpoints import chat
    from core.turn import assemble
    from plugins.web_ui_module.api import engine_doors
    sources = (_source(chat._fit_v1_messages_to_window), _source(assemble._assemble_engine_messages),
               _source(engine_doors._refit_for))
    return all("reply_budget_tokens=reply_reserve_tokens(" in text for text in sources)


def _probe_b2() -> bool:
    """Both doors ask one rule for the model of an engine in reserve, and that rule gives Ollama its own."""
    import os

    from core.endpoints.chat_engines._common import model_in_reserve
    from core.turn.api_cascade import ApiDoor
    from plugins.web_ui_module.api import engine_doors
    saved = os.environ.get("NEXE_OLLAMA_MODEL")
    os.environ["NEXE_OLLAMA_MODEL"] = "probe-own:1b"
    try:
        own = model_in_reserve("ollama", object(), "Qwen3.5-9B-MLX-4bit", None)
    finally:
        if saved is None:
            os.environ.pop("NEXE_OLLAMA_MODEL", None)
        else:
            os.environ["NEXE_OLLAMA_MODEL"] = saved
    return (own == "probe-own:1b"
            and "model_in_reserve(" in _source(engine_doors._model_on_fallback)
            and "model_in_reserve(" in _source(ApiDoor._body_for))


def _probe_b3() -> bool:
    """Both doors narrow the candidates with the one filter that knows who can resume."""
    from core.turn import api_cascade, engine_claim
    from plugins.web_ui_module.api import turn_adapters
    return ("able_to_continue" in _source(engine_claim.live_candidates)
            and all("live_candidates(" in _source(module) for module in (api_cascade, turn_adapters)))


def _probe_n6() -> bool:
    """/v1 tells the switch against the first engine it asked, not the one the engine step resolved."""
    from core.turn import api_cascade
    text = _source(api_cascade.dispatch_v1)
    return "candidates[0][0]" in text and "preferred_fallback = engine" not in text


def _probe_n8() -> bool:
    """/v1 answers the API by itself behind the gate, refuses it without, and the chain never holds it."""
    import inspect
    from types import SimpleNamespace

    from fastapi import HTTPException

    from core.endpoints import chat
    from core.endpoints.chat_engines import routing
    state = SimpleNamespace(modules={"ollama_module": SimpleNamespace(chat=lambda *a, **k: None),
                                     "api_module": SimpleNamespace(chat=lambda *a, **k: None)}, config={})
    try:
        routing._resolve_engine("api", state)
        return False
    except HTTPException as refused:
        if refused.status_code != 400:
            return False
    dispatch = inspect.getsource(chat._dispatch_to_engine)
    return (routing._resolve_engine("api", state, cloud_ok=True) == ("api", None)
            and "api" not in routing.ENGINE_CASCADE
            and dispatch.index("_forward_to_api") < dispatch.rindex("_forward_to_ollama"))


def _probe_n9() -> bool:
    """The web door reads the session's consent; /v1 has none to read, and the request carries its own."""
    import inspect

    from core.endpoints.chat_schemas import ChatCompletionRequest
    from core.providers import cloud
    from plugins.web_ui_module.api import turn_adapters
    return ("nexe_cloud_consent" in ChatCompletionRequest.model_fields
            and "session_consent=None" in inspect.getsource(cloud.require_cloud_request)
            and "session_consent=getattr(ctx.session" in inspect.getsource(turn_adapters._cloud_gate))


def _probe_n10() -> bool:
    """/v1 gives the API the request's model; it asks no engine which one it has loaded."""
    import inspect

    from core.endpoints.chat_engines import api
    source = inspect.getsource(api)
    return "model=request.model" in source and "resolve_loaded_model_name" not in source


PROBES = {
    "R1": _probe_r1, "N7": _probe_r1, "R4": _probe_r4, "D1": _probe_d1, "D1-z": _probe_d1z,
    "D2": _probe_d2, "D3": _probe_d3, "Q": _probe_d3, "R3": _probe_r3, "D4": _probe_d4,
    "B7": _probe_d4, "B6": _probe_b6, "N4": _probe_n4, "N8": _probe_n8, "N9": _probe_n9, "N10": _probe_n10,
    "B3": _probe_b3, "N6": _probe_n6, "B1": _probe_b1, "B2": _probe_b2, "D1-x": _probe_b2,
    "N5": _probe_n5, "N2": _probe_n5, "R2": _probe_n5, "N1": _probe_n1,
}


def test_what_the_register_says_of_the_applied_and_the_kept_is_true_of_the_code():
    wrong = [label for label, probe in PROBES.items() if probe() is not True]
    assert not wrong, f"the register says something the code no longer does: {wrong}"
    assert set(PROBES) <= set(REGISTER)


def test_every_applied_or_kept_label_with_a_probe_is_probed_and_the_rest_are_said_not_to_be():
    """The labels whose state is a decision about behaviour a cell pins (N3, B4, B5) have no
    probe here: the matrix is their test. Listing them keeps that a choice, not an omission."""
    unprobed = sorted(label for label, (state, _why) in REGISTER.items() if state != OPEN and label not in PROBES)
    assert unprobed == ["B4", "B5", "N3"]
