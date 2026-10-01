"""I1 (ADR-007 §1): one turn, one sequence — and the door is a label (C4.0).

I1 is the invariant the whole canonada exists for: whichever entry a message
comes in through, it walks the SAME ordered `TURN_STEPS`. Until now nothing in
Python said so. The two per-door tests that look closest compare
`set(table)` — `test_api_turn_order.py:91-96` and
`test_turn_adapters_ui.py:101-109` — which is a statement about the adapter
table's KEYS, not about what a turn does, and a `set` has no order to check.

The tests below are the contract:

1. the three entries produce the same ordered sequence of step ids — and,
   since C4.2, the SAME TURN across the two doors, field by field, with a
   short list of exclusions each of which names a reason that is not "the
   pipeline behaved differently";
2. the folded map is EMPTY and the design degradations never grow (`== 0`
   since C4.2 — the thermometer of the whole C4 phase reached the bottom, see
   `core/turn/folded.py`);
3. flipping `ctx.entry` changes nothing about the turn — the mutation
   `if ctx.entry == "ui": return` inside a step keeps the sequence of ids
   identical, so only a behavioural comparison catches it.

The fakes are in `conftest.py`, and they are fakes only where a real thing
would cost an LLM call or a network hop: the adapter tables, the engine, the
session manager and the turn context are the production ones.
"""
from __future__ import annotations

import pytest

from core.turn.folded import DESIGN_DEGRADATIONS, FOLDED_BASELINE
from core.turn.steps import TURN_STEPS

pytestmark = pytest.mark.asyncio

#: The one sequence, in order. `run.py:_record` writes `usage["steps"]` as it
#: goes, so the dict's insertion order IS the execution order — nothing here
#: instruments the engine to find that out.
EXPECTED_SEQUENCE = tuple(step.id for step in TURN_STEPS)


def _sequence(ctx) -> tuple[str, ...]:
    return tuple(ctx.usage["steps"])


async def test_the_three_entries_run_the_same_sequence(turn_lab):
    """`/ui/chat` streaming, `/ui/chat` JSON and `/v1/chat/completions` walk
    TURN_STEPS in the same order — and therefore in the same order as each
    other, which is I1.

    Each turn gets its own session id: the doors take a per-session lease
    (`session` step), and reusing one id would make the second turn's outcome
    depend on the first turn's release rather than on the pipeline.

    C4.2 makes this STRICT: the sequence is compared as it always was, and
    then the two doors' TURNS are compared field by field
    (`_assert_same_turn`), which until now was only done between two runs of
    the SAME table. Everything excluded is named in `CROSS_DOOR_NOT_COMPARABLE`
    with the reason measured, so the list is an inventory of what C4 has left
    to converge and not a place to hide a divergence.
    """
    stream_ctx = await turn_lab.ui(streaming=True, session_id="i1-ui-stream")
    json_ctx = await turn_lab.ui(streaming=False, session_id="i1-ui-json")
    api_ctx = await turn_lab.api(session_id="i1-api")
    api_stream_ctx = await turn_lab.api(streaming=True, session_id="i1-api-stream")

    for door, ctx in (
        ("ui-stream", stream_ctx), ("ui-json", json_ctx),
        ("api", api_ctx), ("api-stream", api_stream_ctx),
    ):
        assert _sequence(ctx) == EXPECTED_SEQUENCE, (
            f"{door} does not walk TURN_STEPS in order: {_sequence(ctx)}"
        )
    # Said between the three as well, so a future change to TURN_STEPS that
    # somehow updated all three at once still has to keep them equal.
    assert _sequence(stream_ctx) == _sequence(json_ctx) == _sequence(api_ctx) == _sequence(api_stream_ctx)

    # C4.2: and the same TURN, not just the same order of ids.
    _assert_same_turn(json_ctx, api_ctx, also_skip=CROSS_DOOR_NOT_COMPARABLE)

    # T1 (finding 1057), 09/09 audit: `ctx.usage` has 14 possible buckets and,
    # until this commit, only two of them (`ui`, `folded`) had ever been
    # pulled out and compared — a door inventing a FIFTEENTH one, or silently
    # dropping one it always wrote, passed every test that only inspects the
    # buckets `_turn_state` already knows about. This does not open any
    # bucket's content; it only says the two doors agree on WHICH buckets
    # exist, modulo the one documented exception.
    json_keys = set(json_ctx.usage.keys()) - CROSS_DOOR_USAGE_ONLY_AT_UI
    api_keys = set(api_ctx.usage.keys()) - CROSS_DOOR_USAGE_ONLY_AT_UI
    assert json_keys == api_keys, (
        f"the two doors wrote a different set of usage buckets, unexplained: "
        f"{json_keys ^ api_keys}"
    )


async def test_the_two_doors_build_the_same_prompt(turn_lab):
    """`prompt` is excluded above for its SHAPE, so its content is compared
    here — otherwise the exclusion would hide exactly what C4.2 converged.

    The two wires differ by construction: `/ui/chat` hands the engine the
    system prompt beside the turns (`engine.chat(messages, system=…)`) and
    `/v1` carries it as `messages[0]`, the OpenAI shape. Split that off and
    what is left has to match — the same system text, the same turns.
    """
    ui_ctx = await turn_lab.ui(streaming=False, session_id="prompt-ui")
    api_ctx = await turn_lab.api(session_id="prompt-api")

    assert api_ctx.prompt[0]["role"] == "system"
    assert api_ctx.prompt[0]["content"] == ui_ctx.system_prompt, (
        "the two doors no longer build the same system prompt"
    )
    api_turns = [(m["role"], m["content"]) for m in api_ctx.prompt[1:]]
    ui_turns = [(m["role"], m["content"]) for m in ui_ctx.prompt]
    assert api_turns == ui_turns, (
        f"the turns handed to the engine differ: ui={ui_turns} api={api_turns}"
    )


async def test_folded_never_grows(turn_lab):
    """The C4 thermometer, at the bottom. A healthy turn folds NO step, and
    degrades nothing beyond the two limits C3 declared.

    `== 0` since C4.2, not `<=`: while the number was coming down an equality
    would have gone red on the very commit doing the work, and now that it is
    zero `<=` would let a sub-fase fold a step again in silence. Both numbers
    live in `core/turn/folded.py`.
    """
    ui_ctx = await turn_lab.ui(streaming=False, session_id="folded-ui")
    api_ctx = await turn_lab.api(session_id="folded-api")
    api_stream_ctx = await turn_lab.api(streaming=True, session_id="folded-api-stream")

    for label, door, ctx in (
        ("ui", "ui", ui_ctx),
        ("api", "api", api_ctx),
        ("api-stream", "api", api_stream_ctx),
    ):
        folded = ctx.usage.get("folded", {})
        assert FOLDED_BASELINE[door] == 0, "core/turn/folded.py is no longer at zero"
        assert len(folded) == FOLDED_BASELINE[door], (
            f"the {label} door folded a step again "
            f"({len(folded)} != {FOLDED_BASELINE[door]}): {sorted(folded)}"
        )
        degraded = set(ctx.usage.get("degraded", {}))
        assert degraded <= DESIGN_DEGRADATIONS, (
            f"the {label} door degraded a step outside the declared C3 limits: "
            f"{sorted(degraded - DESIGN_DEGRADATIONS)}"
        )


#: Fields of the TurnContext that two runs of the same table cannot be
#: expected to share, each for a reason that is not "the turn behaved
#: differently". Everything else is compared, so a step that starts branching
#: on the door is caught wherever in the context it leaves its mark.
NOT_COMPARABLE = {
    # The two ids the plan names: these ARE two different turns of two
    # different sessions, by construction (see the test's docstring).
    "turn_id", "session_id",
    # `entry` is the very thing being flipped; `body` and `request` are the
    # door's raw input, which carries the session id.
    "entry", "body", "request",
    # `ChatSession` does not define `__eq__` (`type(s).__eq__ is
    # object.__eq__`), so two equivalent sessions never compare equal — the
    # object cannot be compared, but WHAT THE TURN PERSISTED INTO IT can, and
    # `_turn_state` pulls its messages out below. Audit 08/09, ALERT 1: the
    # earlier comment here blamed the session id, which is `None` in the lab —
    # a wrong reason that hid a real door-switch in `persist_user_turn`.
    "session",
    # Per-turn resources: a threading.Event, an asyncio.Task, a gate slot.
    # Object identity, not turn state.
    "cancel_token", "gpu_slot",
    # Shared mutable state of the process, not of the turn.
    "app_state",
    # C4.3-c: the engine's per-step write record. Reset at the start of every
    # step (`ctx.begin_step()`), so at the end of a turn it holds whatever the
    # LAST step wrote and nothing else — an artefact of the measurement, not
    # turn state. What the record is FOR is compared, and strictly:
    # `usage_folded` below is derived from it, and `FOLDED_BASELINE` pins it
    # to zero at both doors.
    "_written",
    # `usage` holds 14 buckets and most of them carry at least one clock
    # reading (a duration in ms, a `time.time()` stamp) that is never equal
    # twice — so the dict as a WHOLE is excluded here, and `_turn_state`
    # extracts back every bucket that IS turn state. Audit 08/09, ALERT 2:
    # excluding the whole dict once threw away `usage["ui"]` too, and a
    # door-switch that only touched it passed all 8907 tests. 09/09 audit
    # (finding 1057): `usage["llm"]` was excluded the exact same way and had
    # the exact same blind spot — of its per-call fields only `ms`/`at` are
    # clocks; `step`, `engine`, `tokens_in`, `tokens_out` and `model` are turn
    # state, and a door-switch that only marked `usage["llm"]` passed all
    # 8940 tests in green. `_turn_state` now extracts `usage_ui`,
    # `usage_folded`, `usage_llm` and `usage_llm_models` below; the ordered
    # step sequence is compared separately (`_sequence`), and `outcomes` — a
    # field of its own — says what each step did. What is STILL not
    # extracted (`degraded`, `memory_saved`, `saved_by_intent`,
    # `memory_action`, `mem_deletes`, `last_results`, `post_commit_result`,
    # `post_commit_cancel`, `prompt_tokens`, `completion_tokens`) is an
    # UNTESTED exclusion, not a verified one — the same class of gap #1057
    # closed for `llm`, left written down instead of hidden.
    "usage",
}

#: Inside `usage["ui"]` (`_ui(ctx)`, `turn_adapters.py:60-63`), the ONLY entries
#: two runs of the same table cannot share. Every key of that scratch was
#: measured on BOTH paths (audit 08/09), not reasoned about — and everything not
#: listed here, `candidates`, `reprompt_ctx` and `memory_helper` included,
#: compares EQUAL between two turns. That makes them turn state, and they are
#: compared: an exclusion nobody earned is a blind spot, which is how a door
#: that hands one door a different engine cascade than the other went unnoticed
#: by all 8907 tests.
#:
#: * `stream_ctx` — a `StreamingChatContext` (`turn_adapters.py:546`). It is a
#:   dataclass and DOES compare by value; what makes it unusable is what it
#:   holds: `session` (a `ChatSession`, no `__eq__`), `chat_result` (the
#:   engine's live async generator) and `disconnect_monitor_task` (an
#:   `asyncio.Task`) — three per-turn handles, measured one by one.
#: * `start_t`, `stream_start_t` — `time.time()` readings (`:189`, `:554`),
#:   different on every run by definition.
#:
#: `stream_ctx` and `stream_start_t` exist only on the STREAMING path; this set
#: describes the scratch, not what any one assertion happens to reach.
UI_SCRATCH_NOT_COMPARABLE = {"stream_ctx", "start_t", "stream_start_t"}


def _turn_state(ctx) -> dict:
    """Everything the pipeline built during the turn, minus what cannot match."""
    state = {
        name: value for name, value in vars(ctx).items()
        if name not in NOT_COMPARABLE
    }
    # `usage` as a whole cannot be compared (per-step ms), but the parts of it
    # that ARE turn state can: the UI door's scratch and the folded map.
    state["usage_ui"] = {
        k: v for k, v in ctx.usage.get("ui", {}).items()
        if k not in UI_SCRATCH_NOT_COMPARABLE
    }
    state["usage_folded"] = ctx.usage.get("folded")
    # I8, recovered (T1, finding 1057): of `usage["llm"]`'s per-call fields
    # only `ms`/`at` are clocks — `step`, `engine`, `tokens_in`, `tokens_out`
    # are turn state and are compared UNCONDITIONALLY, cross-door included: a
    # step billing an LLM call to the wrong engine, or a door making a call
    # the other one doesn't, now shows up here. `model` is split into its own
    # key below because it does NOT mean the same thing at the two doors.
    llm_calls = ctx.usage.get("llm", {}).get("calls", [])
    state["usage_llm"] = {
        "total_calls": ctx.usage.get("llm", {}).get("total_calls", 0),
        "calls": [
            {k: v for k, v in call.items() if k not in ("model", "ms", "at")}
            for call in llm_calls
        ],
    }
    # `model` at `/ui/chat` is the REQUESTED model (`ui["model_name"]`,
    # `turn_adapters.py:347`: the body's `model` or `NEXE_DEFAULT_MODEL`);
    # at `/v1` it is (or, until #1054 is fixed, would be) the model that
    # ACTUALLY SERVED the turn (`resolve_loaded_model_name`,
    # `_common.py:316-334` — echoing `request.model` back "would lie about
    # which model answered", B075-C3). Converging them is not a rename: `/v1`
    # is explicitly forbidden from switching models to match a request
    # (`test_fd_block5_engine_routing.py:503-505`), so the two doors serve
    # DIFFERENT models given the same input, by design. Same family as
    # `engine`/`context_window` below (EnginePort work) — excluded cross-door
    # only; the label-flip tests, which run the same door twice, still
    # compare it.
    state["usage_llm_models"] = [call.get("model") for call in llm_calls]
    # The session object has no `__eq__`, but the turn it persisted has.
    messages = getattr(ctx.session, "messages", None) or []
    state["session_messages"] = [
        (m.get("role"), m.get("content")) if isinstance(m, dict)
        else (getattr(m, "role", None), getattr(m, "content", None))
        for m in messages
    ]
    return state


async def test_entry_is_a_label_not_a_switch(turn_lab):
    """The one that catches the mutation.

    `ctx.entry` names the DOOR, never a branch: the same adapter table, given
    the same input, must produce the same turn whatever the label says. A
    mutation like `if ctx.entry == "ui": return` at the top of a step keeps the
    sequence of step ids intact — a step that returns early is still recorded
    as "ok" — so a sequence comparison alone stays green. So does a comparison
    of the ANSWER alone: a fake engine ignores the prompt it is handed, so a
    step that silently stops building the system prompt still produces the same
    reply. What catches it is the state the pipeline leaves on the context, and
    that is what this compares — every field of the `TurnContext` except the
    ones listed in `NOT_COMPARABLE`, each excluded for a stated reason.

    `ctx.entry` itself DOES travel, on purpose: it is the lease `holder`
    (`turn_adapters.py:216`, `adapters_api.py:150`) and it is written to the
    trace. That is the door identifying itself as the writer of a session,
    which is what I9 asks for — not the turn behaving differently. So `entry`
    is excluded as the flipped variable itself, never because a step is allowed
    to read it.
    """
    labelled_ui = await turn_lab.ui(streaming=False, session_id="label-a", entry="ui")
    # Same table, same input — only the label flipped.
    labelled_api = await turn_lab.ui(streaming=False, session_id="label-b", entry="api")
    _assert_same_turn(labelled_ui, labelled_api)


async def test_entry_is_a_label_not_a_switch_when_streaming(turn_lab):
    """The same contract on the streaming path, which has four adapters of its
    own (`generate_stream`, `postprocess_stream`, `persist_stream`,
    `emit_stream`) — three of which exist NOWHERE else. Until this test they
    were outside the thermometer entirely: the JSON twin above never runs them.

    It costs nothing to hold: two streaming turns with `entry` flipped diverge
    in no field at all (measured before writing this). And it is where the
    wire comparison earns its keep — on this path `ctx.wire` stays None, so
    `emit_stream`'s only observable output is the chunk sequence the lab
    collected. A door-switch inside it changes nothing else about the turn.
    """
    labelled_ui = await turn_lab.ui(streaming=True, session_id="stream-a", entry="ui")
    labelled_api = await turn_lab.ui(streaming=True, session_id="stream-b", entry="api")
    _assert_same_turn(labelled_ui, labelled_api)
    # The turn really did stream: an empty wire would make the comparison above
    # vacuous for exactly the step this test exists to cover.
    assert labelled_ui.lab_wire_chunks, "no chunks reached the wire — emit_stream never ran"


#: What two turns of DIFFERENT doors cannot be expected to share, measured on
#: this lab (08-09/09/2026) and each one for a reason that is not "the pipeline
#: behaved differently". This is the inventory of what C4 has left to converge;
#: `system_prompt`, `usage_folded`, `recall` and `recall_text` were on it
#: before C4.2 and are not any more.
#:
#: * `prompt` — SHAPE, not content: `/v1` carries the system prompt as
#:   `messages[0]` (OpenAI) and `/ui/chat` hands it to the engine beside the
#:   turns. Compared, split apart, in `test_the_two_doors_build_the_same_prompt`.
#: * `wire`, `lab_wire_chunks` — the door's payload is the one step that is
#:   door-specific BY DESIGN (ADR-007 §1, `emit`).
#: * `engine` — `ctx.engine` is the engine's NAME at `/v1` (`served_by`, a str)
#:   and the live MODULE at `/ui/chat`; `steps.py` says so, and unifying it is
#:   the EnginePort work, not C4.2.
#: * `context_window` — follows from the above, and the reason is STRUCTURAL,
#:   not the lab's: the two doors resolve the window by different mechanisms —
#:   the UI door asks the engine module it is holding (`ask_engine_window`),
#:   `/v1` resolves it from the engine's NAME (`get_effective_context_window`).
#:   One is a question to an object, the other a lookup by string, and making
#:   them one is the same EnginePort work `engine` above is waiting for. (The
#:   concrete values here — `None` at the UI, 8192 at `/v1` — are the lab's
#:   fake answering nothing; the divergence would survive a fake that did.)
#: * `attachments` — `/ui/chat` declares the image keys it accepts and `/v1`
#:   has no attachment channel at all until C4.3, which is the sub-fase that
#:   gives the two doors one.
#: * `usage_ui` — the UI door's per-turn scratch (`_ui(ctx)`), by definition
#:   only written at that door.
#: * `usage_llm_models` — T1 (finding 1057), 09/09 audit. `/ui/chat` registers
#:   the model the CLIENT asked for; `/v1` registers (or would, once #1054 is
#:   fixed) the model that actually served — two different questions, not two
#:   spellings of one answer, and `/v1` is contractually forbidden from
#:   loading a different model to converge them
#:   (`test_fd_block5_engine_routing.py:503-505`). `usage_llm` above (the
#:   non-model fields of the same bucket) is compared, so this is the one
#:   field of it that is not — same shape as `engine`/`context_window` below.
#: * `session_messages` — `/v1` never puts the live session ON THE CONTEXT:
#:   `ctx.session` stays `None` at that door (`adapters_api.py` calls
#:   `get_or_create_session` in the `session` step without keeping the object;
#:   the UI's `session` step assigns it), and `_turn_state` reads the messages
#:   off `ctx.session`. So this compares "the UI's session" against nothing.
#:   The turn DOES persist: the user mirror is written INLINE by
#:   `persist_user_turn` (`mirror_v1_conversation`, `adapters_api.py:185`) —
#:   only `persist_assistant_turn` goes through the request's `BackgroundTasks`,
#:   which the lab never runs. Measured, not reasoned (T2, finding 1058: the
#:   09/09 audit re-exercised this and got 14, not the 10 this comment used to
#:   claim): with that write removed, **14** tests go red —
#:   `test_user_turn_is_on_disk_before_memory_is_asked` and **13** of
#:   `test_fc_thread_mirror.py`, not 9 — so nothing is hidden here. Reproduce
#:   with `return` as the first line of `mirror_v1_conversation`
#:   (`_common.py:237`) and:
#:   `pytest tests/core/endpoints/test_fc_thread_mirror.py tests/core/turn/test_api_turn_order.py`
#:   → 14 failed, 24 passed. Putting the live session on the context at `/v1`
#:   is EnginePort/C4.3 work.
CROSS_DOOR_NOT_COMPARABLE = {
    "prompt", "wire", "lab_wire_chunks", "engine", "context_window",
    "attachments", "usage_ui", "usage_llm_models", "session_messages",
}

#: Buckets of `ctx.usage` known and DOCUMENTED to live at only one door — the
#: one bucket allowed to make the two doors' key sets differ, because its
#: content (not just its presence) is already compared field by field
#: (`usage_ui` above). Anything else that only one door writes is an
#: uninspected divergence, which is exactly the class of gap #1057 closed for
#: `llm` — see the assertion in `test_the_three_entries_run_the_same_sequence`.
CROSS_DOOR_USAGE_ONLY_AT_UI = {"ui"}


def _assert_same_turn(one, other, *, also_skip: set[str] = frozenset()) -> None:
    """Two turns that must match: same table with `entry` flipped, or — since
    C4.2 — the two doors, minus `also_skip`."""
    assert _sequence(one) == _sequence(other), (
        "the same adapter table walked a different sequence when the door's "
        "label changed — `entry` is being used as a switch"
    )

    one_state, other_state = _turn_state(one), _turn_state(other)
    # `wire` is the one compared field that carries the ids on purpose (the
    # door puts them there for the client), so it is compared without them.
    # It is None on the streaming path, where the wire is `lab_wire_chunks`.
    for state in (one_state, other_state):
        if isinstance(state.get("wire"), dict):
            state["wire"] = {
                k: v for k, v in state["wire"].items() if k not in ("turn_id", "session_id")
            }

    # Union of both key sets, read with `.get`: iterating only the first state
    # and indexing the second raises `KeyError` instead of asserting when a key
    # exists on one side only (measured by the auditor 08/09:
    # `_assert_same_turn(ui, api)` → `KeyError: 'lab_wire_chunks'`, which only
    # `TurnLab.ui()` writes). C4.1 lowers the folded map, and comparing a UI
    # turn against an API one is the natural next step.
    keys = (set(one_state) | set(other_state)) - set(also_skip)
    differing = sorted(k for k in keys if one_state.get(k) != other_state.get(k))
    assert not differing, (
        "flipping ctx.entry changed the turn — `entry` is being used as a "
        f"switch, and these fields diverged: {differing}"
    )
