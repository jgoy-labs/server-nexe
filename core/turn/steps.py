"""The turn pipeline as a map, not an engine (ADR-007, C0).

TURN_STEPS is the frozen, ordered description of every step a chat turn goes
through. It does not execute anything: each Step just names what a step is
called, what road it belongs to, whether it is mandatory and substitutable,
what it reads and writes on a TurnContext, and where its behaviour lives
TODAY across the two doors (`/ui/chat` and `/v1/chat/completions`).

Building `run_turn()` on top of this (C1 of the pipeline plan, ADR-007) is
deliberately NOT part of this module. Until then, every door keeps its own
procedural orchestration; this table is the target shape they converge to,
and the single place that can now say, in code, "here is the whole turn".

Every `today` pointer below was first verified against the codebase on
2026-09-05, by two read-only audits of the turn as it stood then: one mapped
the sequence, the other the organs. #1085 (2026-09-24): the line numbers had
drifted (five pointed past the end of routes_chat.py), so pointers now cite
`path (symbol)` instead, and `tests/core/turn/test_turn_steps_pointers.py`
checks every one of them: the file exists, a cited line is inside it, a cited
symbol appears in it. `doors_today` is coarse on
purpose (per-door presence of an EQUIVALENT step, not a re-encoding of every
fine-grained divergence): the exhaustive 33-row divergence table lives in
those audits, not here.

See ADR-007 §4 for the source table this module implements, and its §2 for
why StepKind is a two-value label (COMPUTE | LLM) rather than two pipelines.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet, Mapping


class StepKind(Enum):
    """The road a step travels on. A label on the step, not a second pipeline
    (ADR-007 §7): the scheduler (C7) may run steps of different kinds
    concurrently, but there is one ordered sequence, not two."""

    COMPUTE = "compute"
    LLM = "llm"


@dataclass(frozen=True)
class Step:
    """One named, ordered step of the turn. Descriptive metadata only — no
    callable, no conducta (that is C1's `run_turn`). `reads`/`writes` name
    keys on a `core.turn.context.TurnContext`."""

    id: str
    kind: StepKind
    must_have: bool
    replaceable: bool
    idempotent: bool
    reads: FrozenSet[str] = field(default_factory=frozenset)
    writes: FrozenSet[str] = field(default_factory=frozenset)
    #: The subset of `writes` this step assigns on EVERY turn where it runs to
    #: completion — its signature of having done the work. The engine checks it
    #: after each step and records a step that wrote none of it as folded
    #: (`core/turn/run.py::_finish_ok`), which is what makes `FOLDED_BASELINE`
    #: a measurement rather than a decoration.
    #:
    #: Measured, not reasoned (19/09): the engine logged the fields every step
    #: really wrote across the turns driven through REAL adapter tables
    #: (`turn_lab`, `test_i1_one_sequence`, `test_api_turn_order`,
    #: `test_turn_adapters_ui`), and this is the intersection per step. It is
    #: deliberately NOT the intersection over the whole suite: a test that
    #: stubs a step with an empty double makes it write nothing, which is
    #: indistinguishable here from the step being folded — so the whole-suite
    #: figure collapses to empty and says nothing about production.
    #:
    #: Empty means "not observable this way", and for seven steps it is:
    #: `authorize`, `persist_user_turn`, `persist_assistant_turn`,
    #: `memory.write` and `compact` write no context field at all by design;
    #: `validate` writes `attachments` only when a turn carries an image; and
    #: `emit` leaves `ctx.wire` None on the streaming path, where the answer IS
    #: the chunk sequence. Those seven need a behavioural test to catch a fold,
    #: and today only some of them have one.
    writes_always: FrozenSet[str] = field(default_factory=frozenset)
    doors_today: FrozenSet[str] = field(default_factory=frozenset)
    today: Mapping[str, str] = field(default_factory=dict)
    note: str = ""


# Fields already on the TurnContext before step 1 runs: the door fills
# identity + payload (ADR-007 §3) and nothing else. Kept here, not imported
# from context.py, so this module stays free of any import beyond stdlib —
# it is data, and the layering gate has nothing to say about it.
GIVEN_BY_DOOR: FrozenSet[str] = frozenset({
    "turn_id", "session_id", "entry", "principal", "pipeline_version",
    "message", "attachments", "cancel_token", "deadline", "trace_id", "resume",
    # transitional plumbing the C1 adapters need (see context.py docstring)
    "body", "request", "app_state", "streaming",
})


TURN_STEPS: tuple[Step, ...] = (
    Step(
        id="validate", kind=StepKind.COMPUTE, must_have=True, replaceable=False,
        idempotent=True,
        reads=frozenset({"message", "attachments", "resume"}),
        # C4.1: `validate` decodes the turn's image attachment, so it writes
        # back into `attachments` the door handed it.
        writes=frozenset({"attachments"}),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "core/turn/validate.py (validate_turn)",
            "api": "core/turn/validate.py (validate_turn), after core/endpoints/chat.py (_validate_chat_request: routing params + non-user content)",
        },
        note="C4.1: one validate for both doors (it replaced the UI's own "
             "`_validate_chat_input`). The message-required 400 the "
             "UI has always answered now answers at /v1 too.",
    ),
    Step(
        id="authorize", kind=StepKind.COMPUTE, must_have=True, replaceable=False,
        idempotent=True,
        reads=frozenset({"principal"}), writes=frozenset(),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "core/turn/authorize.py (authorize_turn), on the principal require_ui_auth recorded",
            "api": "core/turn/authorize.py (authorize_turn), on the principal require_api_key recorded",
        },
        note="C4.1 / #1044: the two doors answered the same misconfiguration in "
             "opposite ways. The fail-closed one won (31/08 decision), and the "
             "chat door now refuses the `dev-mode-bypass` label at both entries. "
             "`_check_dev_mode` is untouched: the administration endpoints that "
             "hang off it are a separate decision.",
    ),
    Step(
        id="sanitize", kind=StepKind.COMPUTE, must_have=True, replaceable=False,
        idempotent=True,
        reads=frozenset({"message"}), writes=frozenset({"message"}),
        writes_always=frozenset({"message"}),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "core/turn/validate.py (sanitize_user_text) + jailbreak_speed_bump",
            "api": "core/turn/validate.py (sanitize_user_text), written back into body.messages",
        },
        note="C4.1 / #1043: one chain, allow_html=True at both doors (31/08 "
             "decision applied), check_xss untouched. The jailbreak speed-bump "
             "stays /ui/chat-only: #1021 measured that asymmetry and SECURITY.md "
             "documents it — converging it is its own decision.",
    ),
    Step(
        id="session", kind=StepKind.COMPUTE, must_have=True, replaceable=False,
        idempotent=False,
        reads=frozenset({"session_id", "entry", "message", "resume"}),
        # `history` was listed here and NO door has ever written it in this
        # step — measured 19/09 with the engine recording real writes: the
        # only production assignment to `ctx.history` in the whole codebase is
        # `turn_adapters.py:400`, inside `budget`, at the UI door. It moved to
        # the step that does it; `test_turn_steps.py` only ever checked this
        # table for internal consistency, so a field claimed by the wrong step
        # cost nothing and stayed for four sub-phases.
        writes=frozenset({"session_id", "session", "lang", "attachments", "message"}),
        writes_always=frozenset({"lang", "session", "session_id"}),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "plugins/web_ui_module/api/turn_adapters.py (get_or_create_session, id from body) + core/turn/prompt.py (_resolve_session_lang)",
            "api": "core/endpoints/chat_engines/_common.py (derive_session_id: X-Session-Id or hash of first message) + core/endpoints/chat.py (_resolve_request_lang)",
        },
        note="C4.2: `lang` is written HERE at both doors, which is what this "
             "table always said. The UI door used to resolve it three steps "
             "later, inside `system_prompt`, so `recall` labelled its sections "
             "with NEXE_LANG instead of the conversation's language.",
    ),
    Step(
        id="persist_user_turn", kind=StepKind.COMPUTE, must_have=True, replaceable=False,
        idempotent=False,
        reads=frozenset({"session_id", "message", "resume"}), writes=frozenset(),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "plugins/web_ui_module/api/turn_adapters.py (persist_user_turn: add_message + _save_session_to_disk)",
            "api": "core/endpoints/chat_engines/_common.py (mirror_v1_conversation: rewrites the mirror + save_session)",
        },
        note="The guarantee (I3 of ADR-007): nothing below this step may write "
             "memory before this one has written disk. Both doors assert it "
             "by behaviour (test_turn_adapters_ui.py, test_api_turn_order.py).",
    ),
    Step(
        id="intent", kind=StepKind.COMPUTE, must_have=False, replaceable=True,
        idempotent=True,
        reads=frozenset({"message"}), writes=frozenset({"intent"}),
        writes_always=frozenset({"intent"}),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "plugins/web_ui_module/api/turn_adapters.py (intent -> core.memory_facts.intents)",
            "api": "core/turn/adapters_api.py (intent -> core.memory_facts.intents)",
        },
        note="C3.1: both doors run the same resolver (core/memory_facts/intents.py). "
             "D6 — a 'save' intent persists the fact and lets the turn continue; only "
             "commands (forget/list/clear all/confirmations) short-circuit. A save here "
             "owns the turn's fact and says so in `usage.saved_by_intent`, which "
             "`memory.write` reads.",
    ),
    Step(
        id="recall", kind=StepKind.COMPUTE, must_have=False, replaceable=True,
        idempotent=True,
        reads=frozenset({"message", "intent", "lang", "attachments"}),
        writes=frozenset({"recall", "recall_text"}),
        writes_always=frozenset({"recall", "recall_text"}),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "core/turn/recall.py (_build_rag_context), collections chosen by core/turn/recall.py (collections_for_turn)",
            "api": "core/turn/recall.py (_build_rag_context), through core/endpoints/chat.py (_fetch_rag_context: the use_rag field), same collections_for_turn",
        },
        note="C4.2: one recall for both doors. The text comes back RAW — "
             "sizing it to the serving engine's window is `budget`'s, which is "
             "the first step that knows the window. Cost is embedding + vector "
             "search, not generation — COMPUTE per ADR-007 §2 ('EMBED is "
             "COMPUTE with cost=\"embed\"'). "
             "C4.3: `attachments` is READ here, and that is why it is declared: "
             "an attached document replaces its OWN collection for the turn and "
             "only that one (#1064), and the decision moved out of the web door "
             "into `collections_for_turn` so both doors answer the same. The "
             "step contract is what guarantees `session` wrote it first.",
    ),
    Step(
        id="clock", kind=StepKind.COMPUTE, must_have=False, replaceable=True,
        idempotent=True,
        reads=frozenset(), writes=frozenset({"clock_line"}),
        writes_always=frozenset({"clock_line"}),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "plugins/web_ui_module/api/turn_adapters.py (clock -> core.chat_prompt.turn_time_line)",
            "api": "core/turn/adapters_api.py (clock -> the same turn_time_line)",
        },
        note="C4.2: resolved once per turn and written down, at both doors — "
             "it used to be computed inside `_assemble_engine_messages` (ui) "
             "and `_build_rag_and_system_prompt` (api), which `budget` called. "
             "`budget` prefixes it to this turn's user message, never to the "
             "system prompt: that would poison the prefix cache for the whole "
             "conversation.",
    ),
    Step(
        id="system_prompt", kind=StepKind.COMPUTE, must_have=True, replaceable=True,
        idempotent=True,
        reads=frozenset({"clock_line", "intent", "lang", "resume"}), writes=frozenset({"system_prompt"}),
        writes_always=frozenset({"system_prompt"}),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "core/turn/prompt.py (turn_system_prompt), from plugins/web_ui_module/api/turn_adapters.py",
            "api": "core/turn/prompt.py (turn_system_prompt), through core/endpoints/chat.py (_system_prompt_for_turn: a client-supplied system message is the base)",
        },
        note="C4.2: one prompt for both doors, and the inverted import is gone "
             "— `_get_system_prompt` lives in core/turn/prompt.py now, so the "
             "plugin no longer reaches into the API's route module for it. "
             "Visible consequence: the collection-toggle notes (#851) reach "
             "/v1 for the first time. The sticky reply language is still "
             "stored per door (session object vs LRU, #850/#854) — the policy "
             "is one function, the store is not.",
    ),
    Step(
        id="engine", kind=StepKind.COMPUTE, must_have=True, replaceable=False,
        idempotent=False,
        reads=frozenset({"body", "app_state", "resume"}),
        writes=frozenset({"engine", "gpu_slot", "context_window", "engine_fallback_from", "engine_fallback_reason"}),
        writes_always=frozenset({"context_window", "engine"}),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "plugins/web_ui_module/api/turn_adapters.py (resolve_engine_cascade, iter_live_engines, _switch_model)",
            "api": "core/endpoints/chat_engines/routing.py (resolve_engine_cascade) + core/endpoints/chat.py (_dispatch_through_cascade)",
        },
        note="Contract today is duck typing (hasattr(module,'chat')): no Protocol "
             "in core/. The two competing fallback mechanisms (finding #1036) "
             "are one since 8d179a73 (C2.4): the forwarders no longer jump to "
             "Ollama on their own, every error propagates to the cascade.",
    ),
    Step(
        id="budget", kind=StepKind.COMPUTE, must_have=True, replaceable=False,
        idempotent=True,
        # `history` was in `reads` too, and no step has ever put it there for
        # this one to read: `budget` BUILDS it (`turn_adapters.py:400`) out of
        # the session. The pair `session writes history` + `budget reads
        # history` described a handover that never happened, and the gate that
        # checks reads are satisfied could not see it while both halves of the
        # fiction were present. Removing only the write half is what turned
        # that gate red — which is the gate doing its job.
        reads=frozenset({"system_prompt", "recall", "recall_text", "message", "lang", "engine", "context_window", "resume"}),
        # `history`: the UI door assembles the turn's context messages here and
        # keeps them on the context (`turn_adapters.py:400`). It is NOT in
        # `writes_always` because the API door does not write it at all — its
        # history comes from the client's own `messages` array, so there is
        # nothing to carry. That asymmetry is now visible in the map instead of
        # being attributed to a step that never touched the field.
        writes=frozenset({"prompt", "recall_text", "history"}),
        writes_always=frozenset({"prompt", "recall_text"}),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "core/turn/assemble.py (_assemble_engine_messages: compute_context_budget, history_ratio from resolve_history_ratio, 0.30 by default), called by plugins/web_ui_module/api/turn_adapters.py (_build_turn_context, _assemble_engine_messages)",
            "api": "core/endpoints/chat.py (_trim_rag_context: compute_context_budget, history_ratio=0.0)",
        },
        note="Same shared function (core/context_budget.py), different parameters "
             "by design (ADR-006) — not a bug, kept as one 'budget' step here. "
             "Runs AFTER `engine` (reordered 2026-09-06, C1.2): the budget is sized "
             "to the serving engine's window, at both doors.",
    ),
    Step(
        id="generate", kind=StepKind.LLM, must_have=True, replaceable=True,
        idempotent=False,
        reads=frozenset({"prompt", "engine", "cancel_token", "deadline", "context_window", "resume"}),
        writes=frozenset({"response", "wire", "engine", "engine_fallback_from", "engine_fallback_reason"}),
        writes_always=frozenset({"engine", "response"}),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "plugins/web_ui_module/api/turn_adapters.py (generate_json, generate_stream, _prepare_call: engine.chat, one GPU slot per turn)",
            "api": "core/endpoints/chat_engines/{mlx,llama_cpp,ollama}.py (module.chat / HTTP)",
        },
        note="C2.5 / #1041: both doors arm ctx.deadline "
             "(core/turn/deadline.py, NEXE_ENGINE_DEADLINE_S) on the same "
             "cancel event a client disconnect uses. 0 disables it.",
    ),
    Step(
        id="postprocess", kind=StepKind.COMPUTE, must_have=True, replaceable=False,
        idempotent=True,
        reads=frozenset({"response", "resume"}), writes=frozenset({"response", "facts"}),
        writes_always=frozenset({"facts", "response"}),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "core/turn/text/clean.py (clean_full_response: the model's format, then core.memory_facts.extract); "
                  "then core/memory_facts/deletes.py and core/turn/policy.py (C4.5: the pending delete and the re-prompt)",
            "api": "core/turn/adapters_api.py (postprocess -> core.turn.text.clean, JSON shape, then the same deletes.py "
                   "and policy.py the web door runs; a stream through core/turn/text/sse.py)",
        },
        note="C4.4: the model-format cleanup (<think>, harmony, <|…|>, ◁▷, echoed "
             "context headers, memory tags) is the core's, core/turn/text/ — one "
             "cleaner for both doors, the compactor and the /v1 history. A /v1 "
             "STREAM is cleaned on its way out (SseCleaner) and, since C4.6-b, its "
             "facts are read from the raw text in the same turn. ADR-010: the model's REASONING is not "
             "cleaned away — the engines return it apart, the UI shows it in "
             "its think block, /v1 sends it as `reasoning` when asked.",
    ),
    Step(
        id="persist_assistant_turn", kind=StepKind.COMPUTE, must_have=True, replaceable=False,
        idempotent=False,
        reads=frozenset({"session_id", "response", "resume"}), writes=frozenset(),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "plugins/web_ui_module/api/turn_adapters.py (persist_simple, persist_stream: core.turn.persist.persist_assistant_turn + _save_session_to_disk)",
            "api": "core/endpoints/chat_engines/_common.py (persist_v1_turn)",
        },
        note="This is the commit point (ADR-007 §8): everything after it is "
             "post-commit. #1040 (C2.4): an error after tokens are on the wire "
             "sets ctx.partial, and this step writes that text as an interrupted "
             "turn (persist_partial_assistant), never as a completed one.",
    ),
    Step(
        id="memory.write", kind=StepKind.LLM, must_have=False, replaceable=True,
        idempotent=False,
        reads=frozenset({"facts", "session_id", "resume"}), writes=frozenset(),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "plugins/web_ui_module/api/turn_adapters.py (memory_write -> core.memory_facts.write.write_facts)",
            "api": "core/turn/adapters_api.py (memory_write -> core.memory_facts.write.write_facts, no atomiser)",
        },
        note="C3.3: both doors write through core/memory_facts/write.py — one junk filter (the union of the two that used to disagree), one first-turn rule. 25/09 (ADR-007 §6 amended, Jordi): back INSIDE the turn, before `emit`, so the turn that saved tells what it kept (`usage.memory_kept` -> [MEM:n:facts]) — on the queue the news came one turn late and the UI badged the model's text instead (#1098). Measured: ~15 ms per fact, ~0.25 s when the atomiser runs. C3 review (08/09): a turn whose `intent` step already saved (`usage.saved_by_intent`) writes nothing here — what the model marks about that fact is its own paraphrase of it.",
    ),
    Step(
        id="emit", kind=StepKind.COMPUTE, must_have=True, replaceable=False,
        idempotent=False,
        reads=frozenset({"response", "entry", "wire", "engine", "recall_text", "engine_fallback_from", "engine_fallback_reason"}),
        writes=frozenset({"wire"}),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "plugins/web_ui_module/api/turn_adapters.py (emit_json, emit_stream: NUL sentinels \\x00[TAG]\\x00, two shapes, streaming and JSON)",
            "api": "core/endpoints/chat_engines/_streaming.py (format_sse_chunk: OpenAI SSE)",
        },
        note="The only door-specific step by design (ADR-007 §1): NUL sentinels "
             "at the web door, OpenAI SSE at /v1. #1039: before either door "
             "writes model text, core/turn/stream.py::StreamGuard strips "
             "control characters and stops the turn at NEXE_MAX_STREAM_MB.",
    ),
    Step(
        id="describe_image", kind=StepKind.LLM, must_have=False, replaceable=True,
        idempotent=True,
        reads=frozenset({"attachments", "engine", "lang", "session_id"}), writes=frozenset(),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "plugins/web_ui_module/api/turn_adapters.py (describe_image -> core.turn.image_memory.describe; kept on the message)",
            "api": "core/turn/adapters_api.py (describe_image -> core.turn.image_memory.describe; kept by image key)",
        },
        note="#1144 (Jordi 03/10): a turn that brought a new image has the model that served it "
             "write the image's own description, post-commit; later turns carry it as "
             "`[IMATGE ADJUNTA] …` in the history (core/turn/assemble.py, adapters_api). An image "
             "already described is not described again; skipped on a partial turn (core/turn/run.py) "
             "and on a resume.",
    ),
    Step(
        id="compact", kind=StepKind.LLM, must_have=False, replaceable=True,
        idempotent=False,
        reads=frozenset({"session_id"}), writes=frozenset(),
        doors_today=frozenset({"ui", "api"}),
        today={
            "ui": "core/sessions/compactor.py (compact_session), queued by turn_adapters",
            "api": "core/sessions/compactor.py (compact_session), queued by adapters_api",
        },
        note="C3.4: the compactor lives with the sessions it summarises, and both doors queue it post-commit. A long thread used to be compacted at one door and not at the other.",
    ),
)


#: The steps a RESUME turn does not run (C4.6, FD-S6 — the web door's
#: Continue): there is no new user message to read an intent in or to recall
#: for, and compacting would rewrite the history between the cut and the
#: resume, breaking the exact prefix the engine continues from. The engine
#: records them `skipped` — a decision the trace shows, not a step that ran
#: and found nothing (which is what writing `recall=[]` would have looked like).
#: `persist_user_turn` is NOT here: at /v1 a resume still mirrors the client's
#: turns (the client is the source of truth); at the web door there is simply
#: no new message, and its adapter says so.
SKIP_ON_RESUME: FrozenSet[str] = frozenset({"intent", "recall", "describe_image", "compact"})
