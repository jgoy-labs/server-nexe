"""The web UI door (`POST /ui/chat`) on the turn engine (ADR-007, C1.3).

One adapter per step of `core.turn.steps.TURN_STEPS`, each a thin wrapper over a
function that ALREADY exists in the core or in the door's other modules:
`wire.py` (the sentinels built outside the stream, the curated notices, the
saved stats) and `engine_call.py` (starting an engine and reading it), both
split out of `routes_chat.py` on 2026-10-04. The adapters live in the plugin,
not in `core/turn/`: the UI's behaviour is plugin code, and the layering gate
keeps `core → plugins` at zero. Calls into `wire`, `engine_call` and
`routes_chat` (`_rc()`, three names) are looked up on the module at call time;
the names this file imports from the core are bound here at import, and that
is where the UI's tests patch them (`turn_adapters.compact_session`,
`turn_adapters._build_rag_context`), with `core.lifespan` (`get_server_state`).
No test patches `routes_chat`, `wire` or `engine_call` (checked 2026-10-04).

Two tables, because four steps really differ between the UI's two wire formats
(measured 2026-09-05: different functions, different junk regexes, different
stats): `ui_adapters(session_mgr, streaming=False)` returns coroutine adapters
for the JSON reply; `streaming=True` swaps `generate`, `postprocess`, `emit` and
`memory.write` for async-generator adapters that yield the NUL-sentinel wire.
Everything else is one adapter for both.

Deliberate decisions of Jordi (06/09/2026), both visible below:
  * `compact` stays where it runs today — before generation, inside
    `_build_turn_context`, which `budget` calls — and is a pass-through here.
    Moving it after the commit, in the background, is the next block (C2).
  * Disk first: the assistant turn is persisted (`persist_assistant_turn`)
    BEFORE the turn's facts go to memory (`memory.write`). Today's streaming
    body did it the other way round (#1040). The wire order of `[SAVING]` /
    `[MEM:n]` moves after the turn is saved; the frontend handles those
    sentinels wherever they appear (`nexe-chat.js:720-736`).

Since C4.6 nothing bypasses these adapters: FD-S6's Continue is a turn with
`ctx.resume` set (the steps it does not need are skipped by the engine — see
`core/turn/steps.py::SKIP_ON_RESUME`), and the second path it used to have in
`routes_chat.py` is gone.
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from core.turn.authorize import authorize_turn
from core.turn.budget import record_llm_call
from core.turn.context import TurnContext
from core.turn.deadline import resolve_deadline_s
from core.turn.gate import GateBusy, Priority, _gate_wait_s, gate_for
import core.memory_facts as memory_facts
from core.memory_facts import intents
from core.memory_facts import deletes as memory_deletes
from core.memory_facts.write import needs_atomising, note_kept, write_facts
import core.turn.policy as policy
from core.sessions.compactor import compact_session
from core.turn.post_commit import queue_for
from core.turn.errors import StreamCapExceeded, classify_engine_error
from core.turn.persist import persist_assistant_turn, persist_partial_assistant
from core.turn.stream import Failed, StreamFlags, close_quietly
from core.turn.text import clean as text_clean
from core.turn.prompt import _fallback_lang, _resolve_session_lang, turn_system_prompt
from core.turn.recall import _build_rag_context, collections_for_turn
from core.turn.run import Adapters, TurnShortCircuit
from core.turn.validate import (
    jailbreak_notice,
    parse_top_p,
    sanitize_user_text,
    validate_turn,
)

# The web door's alphabet and its engine call, split out of routes_chat.py
# (2026-10-04): looked up on the module at call time, like `_rc()` below.
from plugins.web_ui_module.api import engine_call, wire

logger = logging.getLogger(__name__)

#: MC-133: an internal failure while preparing or running the turn is reported
#: to the client as this text (never str(e)), with a 200, as the route always did.
INTERNAL_ERROR_TEXT = "Error: an internal error occurred while generating the response."


def _rc():
    import plugins.web_ui_module.api.routes_chat as routes_chat
    return routes_chat


def _ui(ctx: TurnContext) -> dict:
    """The UI door's per-turn scratch (memory helper, engine candidates, the
    streaming context…): things today's functions pass around as locals."""
    return ctx.usage.setdefault("ui", {})


def _internal_error(ctx: TurnContext, exc: BaseException) -> TurnShortCircuit:
    """MC-133: log the detail (with traceback), never echo str(e) to the client.
    The turn is answered with the generic text, not persisted (B127), and sent."""
    logger.error("Error calling LLM: %s", exc, exc_info=True)
    return TurnShortCircuit(INTERNAL_ERROR_TEXT, reason="internal_error")


@dataclass
class _Claim:
    """One engine attempt of a streaming turn, its first event already read
    (#1117): the engine that claimed the stream, or the first one that failed
    before a byte when none did."""
    engine_name: str
    engine_obj: Any
    prepared: tuple
    primed: tuple
    flags: StreamFlags
    started: float


#: `_prepare_or_decide`'s answer when an engine fails to start in a way every
#: engine would repeat, and an earlier failure's notice is already in hand.
_KEEP_THE_NOTICE = object()


async def _switch_model(engine, engine_name: str, model_name: str) -> None:
    # Deferred: a plugin must not pull core at import time (layering gate, #471).
    from core.endpoints.chat_engines.model_switch import model_switch_lock, switch_engine_model
    async with model_switch_lock():
        await switch_engine_model(engine, engine_name, model_name)


def _model_on_fallback(engine, requested: str) -> str:
    """#1035: the model a fallback engine answers with — the one it has loaded.

    A model name belongs to one engine: an MLX directory is not a .gguf, and
    neither is an Ollama tag. The web doors used to ask the next engine in the
    cascade to load the name picked for another one; its validation raised
    ValueError("not found"), final for the cascade policy, so with a model
    selected in the UI (always) no fallback ever answered. `/v1` already runs
    a fallback with its loaded model; the web doors do the same now. An engine
    with no single loaded model (Ollama picks one per request) gets the
    requested name, as before.
    """
    # Deferred, as above.
    from core.endpoints.chat_engines._common import resolve_loaded_model_name
    return resolve_loaded_model_name(engine, requested)


class _CannotSeeTheImage(RuntimeError):
    """#1035: a fallback whose own model cannot read the turn's image. A
    RuntimeError, so the cascade moves on to the next engine; a ValueError
    would end the turn for every engine."""


def _reattach_mentioned_image(ctx: TurnContext) -> None:
    """#1144 (Jordi: «sí, posa la capa 2»): a message that talks about an image
    and brings none gets the conversation's latest one again, so the model
    looks at it instead of answering from memory — and so does any turn while
    that image has no description yet (the note cannot carry it). After
    `persist_user_turn` (stored once, not again with this turn) and before
    `budget` (the prompt is built knowing there is an image). Only for an
    engine that can see."""
    from core.endpoints.chat_engines.routing import engine_can_see_images  # deferred, as below
    from core.turn import image_memory

    if ctx.resume or ctx.attachments.get("image_b64"):
        return
    earlier = _latest_image(ctx.session.messages[:-1])  # the last one is this turn's own message
    if earlier is None:
        return
    key = image_memory.image_key(earlier["image_b64"])
    described = earlier.get("image_description") or image_memory.DESCRIPTIONS.get(key)
    # Live 03/10: asked right after the image, before its description existed,
    # the model had neither and guessed («el botó és verd»; it is blue). Until
    # the note can carry the image, the image itself goes again — unless no
    # description is coming (review 04/10: then every later turn re-sent it).
    if (described or image_memory.gave_up(key)) and not image_memory.mentions_image(ctx.message):
        return
    if engine_can_see_images(ctx.engine) is False:
        logger.info("Image not re-attached: the engine cannot see (#1144)")
        return
    ctx.attachments["image_b64"] = earlier["image_b64"]
    ctx.attachments["image_type"] = earlier.get("image_type")
    ctx.attachments["image_reattached"] = True
    logger.info("Image re-attached from an earlier message of the conversation (#1144)")


def _latest_image(messages: list) -> "dict | None":
    """The last user message in `messages` that brought an image."""
    return next((m for m in reversed(messages) if m.get("role") == "user" and m.get("image_b64")), None)


def _latest_undescribed_image(messages: list) -> "dict | None":
    """The last user message whose image still needs its description — not
    simply the last image (review 04/10: two images in a row, the second
    turn's job replaced the first's, and the first was never described)."""
    from core.turn import image_memory

    return next((m for m in reversed(messages)
                 if m.get("role") == "user" and m.get("image_b64") and not m.get("image_description")
                 and not image_memory.gave_up(image_memory.image_key(m["image_b64"]))), None)


def _require_sight(engine, engine_name: str, model_name: str) -> None:
    """A fallback answers with its own model (#1035), and a text model given a
    turn with an image would answer as if it saw it. An engine that says it
    cannot see is skipped; one that does not say (it takes the requested
    model, Ollama) is left as before."""
    from core.endpoints.chat_engines.routing import engine_can_see_images  # deferred, as above
    if engine_can_see_images(engine) is False:
        raise _CannotSeeTheImage(f"{engine_name} runs {model_name}, which cannot see the image")


def _serve_with(ctx: TurnContext, engine_obj, ui: dict) -> None:
    """The engine that answers becomes the turn's — and so does its window.

    C4.4: `ctx.context_window` is set at `engine` against the first candidate
    and is documented as the SERVING engine's window. On a fallback the
    prompt was already refitted to the new one (`_refit_for`); the field was
    not, and anything reading it after `generate` got the wrong engine's.
    """
    if ui["candidates"] and engine_obj is not ui["candidates"][0][1]:
        from core.context_window import ask_engine_window  # deferred, as above
        ctx.context_window = ask_engine_window(engine_obj)
    ctx.engine = engine_obj


def _refit_for(engine, system_prompt: str, messages: list) -> list:
    """#976 on a fallback engine: the prompt was fitted to the window of the
    engine that was resolved; another one may hold less."""
    from core.context_window import ask_engine_window
    from core.context_budget import fit_prompt_to_window
    from core.endpoints.chat_sanitization import CHARS_PER_TOKEN_ESTIMATE, DEFAULT_CONTEXT_WINDOW
    window = ask_engine_window(engine) or DEFAULT_CONTEXT_WINDOW
    fitted, _ = fit_prompt_to_window(
        system_prompt, messages, window, reply_budget_tokens=500 // CHARS_PER_TOKEN_ESTIMATE,
    )
    return fitted


def _last_results(ctx: TurnContext) -> dict:
    """What the previous turn's post-commit work reported (C3.3).

    The queue records each job's result and `take_last_results` pops it in the
    next turn's `session` step; this is only the reading. Empty for the first
    turn of a session, and never repeated: the pop already happened.
    """
    return ctx.usage.get("last_results") or {}


def _last_results_sentinels(ctx: TurnContext) -> list[str]:
    """The UI's alphabet for that news: the sentinels `nexe-chat.js` already
    paints (:643 COMPACT; MEM left the queue on 25/09, see `_mem_sentinel`). They ride in `emit`, which is the last step
    of the turn — so they reach the client at the END of the next answer's
    stream, not before it. The frontend clears them wherever they land."""
    out = []
    results = _last_results(ctx)
    compacted = (results.get("compact") or {}).get("compacted") or 0
    if compacted:
        out.append(f"\x00[COMPACT:{compacted}]\x00")
    return out


def _mem_sentinel(ctx: TurnContext) -> str:
    """`\x00[MEM:n:fact1|fact2]\x00` for what this turn left in memory, or "".

    n = facts stored new; the list = every fact in memory because of this turn
    (a duplicate is remembered too). `|` separates facts, so it is folded out
    of each one; NUL never reaches a sentinel. The badge and the CLI read ONLY
    this — a model's `[MEM_SAVE:]` is a request, not a confirmation (#1098).
    """
    kept = [
        str(f).replace("|", "/").replace("\x00", "").strip()
        for f in (ctx.usage.get("memory_kept") or [])
    ]
    kept = [f for f in kept if f]
    saved = ctx.usage.get("memory_saved", 0) or 0
    if not kept and not saved:
        return ""
    return f"\x00[MEM:{saved}:{'|'.join(kept)}]\x00" if kept else f"\x00[MEM:{saved}]\x00"


async def _atomiser_slot(ctx: TurnContext, engine):
    """(engine, gate, slot) for `memory.write`'s atomiser.

    The atomiser costs an LLM call, so it only runs where an engine is already
    in hand — the streaming path, exactly as before C3.3. Inline since 25/09,
    after `generate` gave its slot back: take it again, and only when a fact
    will reach the engine. Busy -> no engine, the fact is stored whole — what
    the atomiser's own failure does. The caller releases a non-None slot.
    """
    if engine is None or not any(needs_atomising(f) for f in ctx.facts):
        return None, None, None
    gate = gate_for(ctx.app_state)
    try:
        slot = await gate.acquire(Priority.USER_TURN, holder=ctx.turn_id, timeout=_gate_wait_s())
    except GateBusy:
        return None, None, None
    return engine, gate, slot


def _last_results_fields(ctx: TurnContext) -> dict:
    """The same news for a JSON reply."""
    results = _last_results(ctx)
    fields = {}
    compacted = (results.get("compact") or {}).get("compacted") or 0
    if compacted:
        fields["compacted_last_turn"] = compacted
    return fields


def _record_saved_facts(session, outcome, session_mgr, *, accumulate: bool = False) -> None:
    """Complete the assistant turn's stats with what memory ended up keeping.

    Disk first: the turn was committed before the facts existed in memory; now
    that they do, the stats say so (same fields as before C3.3).

    `accumulate` (C4.6): a resumed answer is the SAME message as the one it
    continues — what its tail kept adds to what the first part kept.
    """
    if not (session.messages and session.messages[-1].get("role") == "assistant"):
        return
    stats = session.messages[-1].setdefault("stats", {})
    facts = [f.strip() for f in outcome.facts if f.strip() and len(f.strip()) >= 5]
    if accumulate:
        stats["mem_saved"] = (stats.get("mem_saved") or 0) + outcome.saved
        stats["mem_facts"] = list(stats.get("mem_facts") or []) + facts
    else:
        stats["mem_saved"] = outcome.saved
        stats["mem_facts"] = facts
    session_mgr._save_session_to_disk(session)


def _end_partial(ctx: TurnContext, exc: Exception) -> None:
    """#1040 (C2.4): an error after tokens reached the wire cannot be retried,
    only recorded — the turn is PARTIAL (persisted as such, no memory.write).

    #1039: when the error is the byte ceiling, the engine is also told to stop.
    Closing its generator does not reach the MLX/llama.cpp worker thread, which
    would otherwise keep generating to max_tokens; the turn's cancel event does.
    """
    ctx.partial = True
    ctx.error = {
        "step": "generate",
        "class": classify_engine_error(exc),
        "message": str(exc),
    }
    if isinstance(exc, StreamCapExceeded) and ctx.cancel_token is not None:
        ctx.cancel_token[0].set()


def _cancel_monitor(ctx: TurnContext) -> None:
    token = ctx.cancel_token
    if token is None:
        return
    _event, task = token
    if task is not None and not task.done():
        task.cancel()


def _arm_deadline(ctx: TurnContext, cancel_event) -> "asyncio.TimerHandle | None":
    """#1041 (C2.5): fire the SAME cancel_event a client disconnect would set,
    after ctx.deadline seconds — the engine cannot tell the two apart, and
    does not need to. Returns the handle so the caller can cancel it once the
    turn is done (a stray timer firing after the turn has no effect, but
    leaving it armed is untidy and it is cheap to cancel)."""
    if not ctx.deadline:
        return None
    return asyncio.get_running_loop().call_later(ctx.deadline, cancel_event.set)


def _resume_from(ctx: TurnContext) -> None:
    """C4.6 (FD-S6): what a Continue takes from its session, read-only.

    The answer to resume must be the session's last message — checked here,
    BEFORE the lease, so a refused Continue never holds the session. The last
    real user message is the turn's `message` (what the memory rules read and
    the budget counts), the language is the session's sticky one and is NOT
    re-detected (a flip mid-answer would leave the prefix the engine resumes
    from), and no document is injected between the cut and the resume.
    """
    messages = ctx.session.messages
    if not messages or messages[-1].get("role") != "assistant":
        raise HTTPException(
            status_code=400, detail="continue requires the last message to be an assistant turn",
        )
    answered = next((m for m in reversed(messages) if m.get("role") == "user"), {})
    ctx.message = answered.get("content", "")
    ctx.lang = getattr(ctx.session, "lang", None) or _fallback_lang()
    ctx.attachments["document"] = None
    # C4.6-a-vlm: an answer about an image is resumed WITH that image — a
    # vision model continuing without it would be describing from memory,
    # and its prompt would no longer be the one the answer was cut from.
    if answered.get("image_b64"):
        ctx.attachments["image_b64"] = answered["image_b64"]
        ctx.attachments["image_type"] = answered.get("image_type")
    else:
        # #1144: a turn that got the conversation's image re-attached was
        # answered WITH it, though the message does not store it again.
        from core.turn import image_memory

        if image_memory.mentions_image(ctx.message):
            asked_at = max(i for i, m in enumerate(messages) if m is answered) if answered else len(messages)
            earlier = _latest_image(messages[:asked_at])
            if earlier is not None:
                ctx.attachments["image_b64"] = earlier.get("image_b64")
                ctx.attachments["image_type"] = earlier.get("image_type")
                ctx.attachments["image_reattached"] = True


def _memory_port(ctx: TurnContext):
    """The memory port and the door's memory bookkeeping, set up once per turn.

    `intent` sets it up. On a resume `intent` does not run, so `session` does —
    four later steps read these without a guard. The bookkeeping goes first:
    a missing port raises, and the counters must exist either way.
    """
    ui = _ui(ctx)
    if "memory_helper" not in ui:
        ui.setdefault("memory_action", None)
        ui.setdefault("mem_deleted", 0)
        ui["memory_helper"] = memory_facts.helper_for(ctx.app_state)
    return ui["memory_helper"]


def _rag_collections(ctx: TurnContext):
    """The turn's collection toggles. A Continue's body carries none: it reuses
    the ones the session remembers from the answer it resumes (#851 — same
    prompt prefix, and the same collections memory may write to)."""
    if ctx.resume:
        return getattr(ctx.session, "rag_collections", None)
    return ctx.body.get("rag_collections")


def _able_to_continue(candidates: list, model_name: str) -> list:
    """C4.6: on a resume, only the engines that can end their prompt inside the
    last assistant message. None → a clear 400: before this, a Continue that
    reached another engine either raised mid-stream or started a new answer
    that was glued onto the cut one."""
    from core.endpoints.chat_engines.routing import engine_can_continue

    able = [(name, eng) for name, eng in candidates if engine_can_continue(eng, model_name)]
    if not able:
        raise HTTPException(status_code=400, detail="continue is not supported by the available engines")
    return able


def ui_adapters(session_mgr, *, streaming: bool) -> Adapters:
    """The adapter table for one request of the web UI door."""
    rc = _rc()

    # ------------------------------------------------------------ shared

    async def validate(ctx: TurnContext) -> None:
        _ui(ctx)["start_t"] = time.time()
        session_id = ctx.body.get("session_id")
        # RT-10: clean 400 for malformed/traversal session ids (see routes_files).
        if session_id is not None and not session_mgr.is_valid_session_id(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id")
        if ctx.resume and not session_id:
            raise HTTPException(status_code=400, detail="continue requires session_id")
        if ctx.resume and ctx.body.get("image_b64"):
            raise HTTPException(status_code=400, detail="continue does not take an attachment")
        # C4.1: the door hands over identity + payload (ADR-007 §3) and the
        # shared `validate` (core/turn/validate.py) judges it — allowed MIME,
        # real base64, under 10 MB, and a message that is actually there. It
        # was `rc._validate_chat_input`, which also sanitized: that half is the
        # `sanitize` step now, two steps down, and no longer folded.
        ctx.message = ctx.body.get("message", "")
        image_b64 = ctx.body.get("image_b64")
        ctx.attachments = {
            "image_b64": image_b64,
            # Bug #19c / fix 2026-04-22: persist the MIME with the image so the
            # frontend can rebuild `data:<mime>;…` exactly.
            "image_type": ctx.body.get("image_type") if image_b64 else None,
            "image_bytes": None,
        }
        await validate_turn(ctx)

    async def sanitize(ctx: TurnContext) -> None:
        """C4.1: no longer folded inside `_validate_chat_input`.

        `sanitize_user_text` is the chain both doors run. The jailbreak
        speed-bump after it is this door's, and stays this door's: #1021
        measured the asymmetry and SECURITY.md documents it — see the note in
        `core/turn/validate.py` for why C4.1 does not converge it.
        """
        ctx.message = sanitize_user_text(ctx.message)
        # The notice is for this turn's prompt, never the user's stored text:
        # glued to ctx.message it was saved to the history and repeated on
        # every later turn (26/09). `budget` adds it.
        notice = jailbreak_notice(ctx.message)
        if notice:
            ctx.usage["security_notice"] = notice

    async def session(ctx: TurnContext) -> None:
        ctx.session = session_mgr.get_or_create_session(ctx.body.get("session_id"))
        ctx.session_id = ctx.session.id
        if ctx.resume:
            _resume_from(ctx)
            # `intent`, which sets the memory port up, does not run on a resume.
            _memory_port(ctx)
        else:
            # C4.2: the sticky reply language (#850) is resolved HERE, once per
            # turn, which is what `TURN_STEPS` has always said (`session` writes
            # `lang`). It used to be resolved inside `system_prompt`, three steps
            # later — so `recall` labelled its sections with NEXE_LANG instead of
            # the conversation's language, and said so in a comment. The other
            # door has resolved it in this step since C1.2.
            ctx.lang = _resolve_session_lang(ctx.session, ctx.message)
            # C4.3 (D4): the document attached to this session is turn state, read
            # once here like everything else the session gives. It used to be read
            # deep inside `budget` (`_build_turn_context`), which is why only this
            # door could ever see it.
            ctx.attachments["document"] = ctx.session.get_attached_document()
        # C2.3 (ADR-007 §9/I9): one live writer per session — refused with the
        # current lease unless the client explicitly asks to take over (the
        # 409 dialog on the frontend). A background job for this session is a
        # separate question, answered by the queue directly: it is already
        # serialised against this turn by the engine gate, so it only needs
        # preempting, never a lease check of its own.
        result = session_mgr.acquire_lease(
            ctx.session_id, holder=ctx.entry, turn_id=ctx.turn_id, where="web UI",
            force=bool(ctx.body.get("force_lease")),
        )
        if not result.granted:
            raise HTTPException(status_code=409, detail={"code": "session_leased", "lease": result.lease})
        queue = queue_for(ctx.app_state)
        if queue is not None:
            # C3.3: what the previous turn's background work finished doing.
            # Popped, so the same news is never told twice.
            ctx.usage["last_results"] = queue.take_last_results(ctx.session_id)
            if queue.running(ctx.session_id):
                queue.preempt(ctx.session_id)

    async def persist_user_turn(ctx: TurnContext) -> None:
        if ctx.resume:
            # C4.6: a Continue has no new message — the user's turn it answers
            # is already in the session. (Not a policy skip: at /v1 this step
            # still has work to do on a resume.)
            return
        ctx.session.add_message(
            "user", ctx.message,
            image_b64=ctx.attachments.get("image_b64"),
            image_type=ctx.attachments.get("image_type"),
        )
        session_mgr._save_session_to_disk(ctx.session)

    async def intent(ctx: TurnContext) -> None:
        ui = _ui(ctx)
        port = _memory_port(ctx)
        if not intents.intent_enabled():
            ctx.intent = "chat"
            return
        detected, extracted_content = intents.detect_with_pending(ctx.session, ctx.message, port)
        ctx.intent = detected
        if detected == "chat":
            return
        outcome = await intents.resolve(
            detected, extracted_content or "", ctx.session, port, ctx.message,
            rag_collections=ctx.body.get("rag_collections"),
        )
        ui["memory_action"] = outcome.memory_action
        ui["mem_deleted"] += outcome.mem_deleted
        note_kept(ctx.usage, outcome.mem_saved, outcome.kept_facts)
        # C3 review (08/09): `memory.write` needs to know D6 already owns this
        # turn's fact. Not derived from `memory_action` — postprocess can
        # overwrite that to "delete_pending" in the same turn, and a `recall`
        # sets it without any save having happened.
        ctx.usage["saved_by_intent"] = outcome.saved_by_intent
        ctx.intent = intents.outcome_for(detected, outcome)
        if outcome.continue_turn:
            # D6: the fact is already saved; the model answers the user normally.
            return
        raise TurnShortCircuit(wire.render_intent_for_ui(outcome), reason=f"memory_intent:{outcome.kind}")

    async def recall(ctx: TurnContext) -> None:
        """C4.2: retrieval is a step of the turn, not a line inside
        `_build_turn_context`.

        The retrieval under it is `core/turn/recall.py`, shared with /v1. The
        text comes back RAW — `budget` sizes it to the engine's window, which
        is the first step that knows what it is.

        WHICH sources a turn asks is no longer this door's call either (C4.3):
        `collections_for_turn` decides it in the core, from the document the
        `session` step already wrote to `ctx.attachments`. It used to hang off
        `ctx.session.has_attached_document()` right here, and a rule that
        hangs off one door's session is a rule the other door cannot obey —
        which is exactly what would break the day `/v1` accepts an attachment.
        """
        ctx.recall_text, _count, ctx.recall = await _build_rag_context(
            ctx.message, app_state=ctx.app_state, lang=ctx.lang,
            collections=collections_for_turn(
                ctx.body.get("rag_collections"),
                has_document=ctx.attachments.get("document") is not None,
            ),
            threshold_override=ctx.body.get("rag_threshold"),
        )
        _ui(ctx)["rag_count"] = _count

    async def clock(ctx: TurnContext) -> None:
        """C4.2: the clock, resolved once and written down. `budget` prefixes it
        to this turn's user message and never to the system prompt, which
        would poison the prefix cache for the whole conversation.

        #1125: every turn, not only when a phrase asked for the time — the
        model said it had no clock to "quin dia i hora es avui?" (02/10). It
        is the same line every earlier message carries from its stored
        `timestamp` (`core/turn/assemble.py`), so the history renders the same
        next turn. /v1 runs the same function; its history is the client's,
        and carries what the client sends.
        """
        from core.chat_prompt import turn_time_line

        ctx.clock_line = turn_time_line(ctx.lang)

    async def system_prompt(ctx: TurnContext) -> None:
        """C4.2: the same `turn_system_prompt` /v1 runs.

        The language is already resolved (the `session` step) and the
        collection toggles are this door's field: the body carries them, and
        the session remembers them so a `continue` stays inside the prefix the
        turn just built.
        """
        _rag_cols = _rag_collections(ctx)
        if not ctx.resume:
            ctx.session.rag_collections = _rag_cols
        ctx.system_prompt = turn_system_prompt(
            lang=ctx.lang, rag_collections=_rag_cols,
            message=ctx.message, app_state=ctx.app_state,
        )

    async def engine(ctx: TurnContext) -> None:
        ui = _ui(ctx)
        try:
            from core.lifespan import get_server_state
            from core.endpoints.chat_engines.routing import iter_live_engines, resolve_engine_cascade
            from core.context_window import ask_engine_window

            module_manager = get_server_state().module_manager
            if module_manager is None:
                raise HTTPException(status_code=503, detail="Service unavailable: module manager not initialized")
            # Prioritize model/backend from request (UI selector) over env vars.
            model_name = ctx.body.get("model") or os.getenv("NEXE_DEFAULT_MODEL", "llama3.2:3b")
            if len(model_name) > 100:
                raise HTTPException(status_code=400, detail="Model name too long (max 100 chars)")
            preferred_engine = (ctx.body.get("backend") or os.getenv("NEXE_MODEL_ENGINE", "auto")).lower()
            logger.info("Available modules: %s", [m.name for m in module_manager.registry.list_modules()])
            cascade = resolve_engine_cascade(preferred_engine, ctx.app_state)
            logger.info("Engine cascade for this turn: %s", cascade)
            candidates = list(iter_live_engines(cascade, ctx.app_state))
            if not candidates:
                # D-I phase 2 / #884: a failed request, not an assistant turn.
                raise HTTPException(status_code=503, detail="No AI engine available")
            if ctx.resume:
                candidates = _able_to_continue(candidates, model_name)
            ui["model_name"] = model_name
            ui["candidates"] = candidates
            ui["engine_name"], ctx.engine = candidates[0]
            if ctx.body.get("model"):
                await _switch_model(ctx.engine, ui["engine_name"], model_name)
            ctx.context_window = ask_engine_window(ctx.engine)
            ctx.deadline = resolve_deadline_s() or None
            _reattach_mentioned_image(ctx)
        except HTTPException:
            raise
        except Exception as exc:
            raise _internal_error(ctx, exc) from exc

    async def budget(ctx: TurnContext) -> None:
        ui = _ui(ctx)
        try:
            # compact=False (C2.2): `compact` is its own post-commit step now
            # (table below) — running it here too would compact twice.
            turn = await rc._build_turn_context(
                ctx.body, ctx.session, session_mgr, ctx.engine, ctx.message, ctx.resume,
                compact=False,
                # C4.3: the attached document arrives as turn state (the
                # `session` step read it), not fetched from the session here.
                attachments=ctx.attachments,
                # #1063: the document header agrees with the turn's reply
                # language, not always Catalan.
                lang=ctx.lang,
                # C4.2: what the `recall` step retrieved. `_build_turn_context`
                # used to do the retrieval itself — that is what made `recall`
                # folded at this door — and now only sizes it to the window.
                recall=(ctx.recall_text, ui.get("rag_count", 0), ctx.recall),
            )
            ctx.history = turn.context_messages
            ctx.recall = turn.rag_items
            ctx.recall_text = turn.rag_context
            ui["rag_count"] = turn.rag_count
            messages, doc_truncated_pct = rc._assemble_engine_messages(
                turn, ctx.system_prompt, ctx.lang,
                ctx.usage.get("security_notice", "") + ctx.message,
                ctx.session, ctx.resume, ctx.engine,
                clock_line=ctx.clock_line, app_state=ctx.app_state,
                # #1081: the image note now travels through the same
                # ContextShape/ContextFraming port as the document's, instead
                # of mutating `messages[-1]` after assembly.
                has_image=bool(ctx.attachments.get("image_b64")),
            )
            ctx.prompt = messages
            ui["doc_truncated_pct"] = doc_truncated_pct
            ui["compacted"] = ctx.session.compaction_count > 0 and ctx.session.context_summary is not None
        except HTTPException:
            raise
        except Exception as exc:
            raise _internal_error(ctx, exc) from exc

    async def _prepare_call(ctx: TurnContext, index: int, engine_name: str, engine_obj, cancel_event, *, stream: bool):
        """One engine attempt's setup: its model, signature, prompt refit, start.

        The first candidate was switched to the requested model in `engine`; a
        fallback answers with the model it has loaded (#1035), and only if
        that model can see the turn's image when there is one. The model comes
        back last: this attempt's text is parsed, recorded and stored as its."""
        ui = _ui(ctx)
        model_name = ui["model_name"] if index == 0 else _model_on_fallback(engine_obj, ui["model_name"])
        image_b64 = ctx.attachments.get("image_b64")
        if image_b64 and ctx.attachments.get("image_reattached"):
            # #1144: a re-attached image is a help, never a reason to pass an
            # engine over — one that cannot see answers from the image's note.
            from core.endpoints.chat_engines.routing import engine_can_see_images  # deferred, as in _require_sight
            if engine_can_see_images(engine_obj) is False:
                image_b64 = None
        elif index > 0 and image_b64:
            _require_sight(engine_obj, engine_name, model_name)
        thinking_enabled = getattr(ctx.session, "thinking_enabled", False)
        sig = inspect.signature(engine_obj.chat)
        messages = ctx.prompt if index == 0 else _refit_for(engine_obj, ctx.system_prompt, ctx.prompt)
        top_p = parse_top_p(ctx.body)
        sampling_kwargs = {"top_p": top_p} if top_p is not None else {}
        chat_result = engine_call._start_engine_call(
            engine_obj, engine_name, sig, model_name, ctx.system_prompt, messages,
            stream=stream, image_b64=image_b64,
            thinking_enabled=thinking_enabled, cancel_event=cancel_event,
            sampling_kwargs=sampling_kwargs, session_id=ctx.session.id, _continue=ctx.resume,
        )
        return chat_result, sig, messages, thinking_enabled, model_name

    # ---------------------------------------------------------- JSON mode

    async def generate_json(ctx: TurnContext) -> None:
        ui = _ui(ctx)
        cancel_event, monitor = rc._start_disconnect_monitor(ctx.request)
        ctx.cancel_token = (cancel_event, monitor)
        deadline_handle = _arm_deadline(ctx, cancel_event)
        gate = gate_for(ctx.app_state)
        try:
            slot = await gate.acquire(
                Priority.USER_TURN, holder=ctx.turn_id, cancel_event=cancel_event, timeout=_gate_wait_s(),
            )
        except GateBusy:
            _cancel_monitor(ctx)
            if deadline_handle is not None:
                deadline_handle.cancel()
            raise HTTPException(status_code=429, detail="Server busy, try again in a moment")
        ctx.gpu_slot = slot
        try:
            from core.endpoints.chat_engines.routing import raise_if_terminal
            for index, (engine_name, engine_obj) in enumerate(ui["candidates"]):
                logger.info("Trying engine: %s", engine_name)
                _call_started = time.monotonic()
                try:
                    chat_result, sig, messages, thinking_enabled, model_name = await _prepare_call(
                        ctx, index, engine_name, engine_obj, cancel_event, stream=False,
                    )
                    # C4.5: how this door asks the engine once more, if the
                    # turn cleans down to nothing but tags (`postprocess`).
                    ui["reprompt_call"] = engine_call.reprompt_call_for(
                        engine_obj, sig, model_name, messages, thinking_enabled,
                    )
                    chunks: list[str] = []
                    if await engine_call._accumulate_nonstreaming_response(chat_result, chunks):
                        _end_partial(ctx, StreamCapExceeded())
                    text = "".join(chunks)
                    if text:
                        logger.info("%s succeeded!", engine_name)
                        record_llm_call(
                            ctx, step="generate", engine=engine_name, model=model_name,
                            ms=(time.monotonic() - _call_started) * 1000.0,
                        )
                        ctx.response = text
                        _serve_with(ctx, engine_obj, ui)
                        ui["engine_name"] = engine_name
                        ui["model_name"] = model_name  # #1035: the one that answered
                        return
                except Exception as exc:
                    # F-D block 5: which errors end the turn and which are worth
                    # another engine is one decision, and it lives in the core.
                    raise_if_terminal(exc, engine_name)
                    logger.warning("%s failed: %s", engine_name, exc)
                    logger.debug("Engine error details:", exc_info=True)
                    continue
            raise HTTPException(status_code=503, detail="No AI engine available")
        except HTTPException:
            raise
        except Exception as exc:
            raise _internal_error(ctx, exc) from exc
        finally:
            _cancel_monitor(ctx)
            if deadline_handle is not None:
                deadline_handle.cancel()
            await gate.release(slot)

    async def postprocess_json(ctx: TurnContext) -> None:
        """C4.5: the same three moves the streaming shape makes — the core's
        cleaner, the core's delete rule, the core's re-prompt — instead of the
        plugin's own copy of them (`_postprocess_nonstreaming`, gone)."""
        ui = _ui(ctx)
        if not ctx.response or ctx.response.startswith("Error:"):
            return
        clean, facts, deletes = text_clean.clean_full_response(ctx.response, ctx.message)
        # C3 review (08/09): inline tags label the turn only when no
        # memory_action exists yet. A D6 "save" already ran deterministically at
        # `intent`; the model parroting its own confirmation back as another
        # tag (common on small models) must not relabel that real, counted save
        # as the unreliable "mem_save_inline" bucket. /v1 never overwrote it.
        if facts and not ui["memory_action"]:
            ui["memory_action"] = "mem_save_inline"
        armed = await memory_deletes.arm_pending_deletes(
            ctx.session, deletes, ui["memory_helper"], _rag_collections(ctx), user_message=ctx.message,
        )
        if armed is not None:
            question = wire.render_intent_for_ui(armed)
            clean = f"{clean}\n\n{question}" if clean else question
            ui["memory_action"] = armed.memory_action
        if not clean and facts and not ctx.resume:
            parts: list[str] = []
            async for chunk in policy.reprompt_chunks(
                ctx, facts, call=ui.get("reprompt_call"),
                engine_name=ui.get("engine_name") or "", model=ui.get("model_name"),
            ):
                parts.append(chunk)
            clean = policy.second_answer_text(parts) or policy.empty_reply_text(ctx.lang)
        ctx.response = clean
        ctx.facts = facts

    async def persist_simple(ctx: TurnContext) -> None:
        """The JSON reply and every short-circuited turn (a memory command's
        answer): one assistant message with the route's small stats. `elapsed`
        is measured now — the old body wrote a literal 0 (routes_chat.py:3039)."""
        ui = _ui(ctx)
        # B127: never persist an engine error ("Error: ...") as an assistant turn.
        if ctx.response.startswith("Error:"):
            return
        model_name = ui.get("model_name")
        if ctx.resume:
            # C4.6: the tail MERGES into the answer it continues (FD-S6) — the
            # legacy JSON Continue did it raw; this is the cleaned text.
            persist_assistant_turn(ctx.session, ctx.response, ctx.response, {}, False, False, resume=True)
        else:
            ctx.session.add_message("assistant", ctx.response, stats={
                "tokens": max(1, len(ctx.response) // 4),
                "elapsed": round(time.time() - ui.get("start_t", time.time()), 1),
                "model": str(model_name)[:100] if model_name else None,
                "engine": ui.get("engine_name") or None,
                "mem_deleted": ui.get("mem_deleted") or None,
            })
        session_mgr._save_session_to_disk(ctx.session)

    async def emit_json(ctx: TurnContext) -> None:
        ctx.wire = {
            "response": ctx.response,
            "session_id": ctx.session.id,
            "intent": ctx.intent,
            "memory_action": _ui(ctx).get("memory_action"),
            # #1098: what THIS turn stored new (D6 or memory.write), and every
            # fact it left in memory — the only list a client may call saved.
            "memory_saved": ctx.usage.get("memory_saved", 0),
            "memory_facts": list(ctx.usage.get("memory_kept") or []),
            # C3.3: what the PREVIOUS turn's background work finished doing.
            **_last_results_fields(ctx),
            # C2.0: one id to grep for in `turn.trace` log lines. `ctx.wire`
            # is a plain dict here (no Response object to hang a header on).
            "turn_id": ctx.turn_id,
        }
        # C2.3: the turn is answered — release the lease so the next request
        # (this session's own, or another device taking over) is never stuck
        # waiting out the TTL.
        session_mgr.release_lease(ctx.session_id, ctx.turn_id)

    # ----------------------------------------------------- streaming mode

    def _finish_generation(ctx: TurnContext, ui: dict, flags, engine_name: str, gen_started: float) -> None:
        """The bookkeeping after `generate_stream`'s token loop: I8's call
        record, the thinking-tokens log, and #1040's partial-turn signal.
        Split out to keep `generate_stream` under the complexity gate — no
        behaviour of its own beyond what it replaces inline."""
        record_llm_call(
            ctx, step="generate", engine=engine_name, model=ui["model_name"],
            ms=(time.time() - gen_started) * 1000.0,
        )
        if not flags.has_any_thinking:
            logger.info("Model did not produce thinking tokens (model decides when to think)")
        if flags.error is not None:
            # The error is already on the wire (as text, via _stream_error_notice).
            _end_partial(ctx, flags.error)

    async def _prepare_or_decide(ctx: TurnContext, index: int, engine_name: str, engine_obj, cancel_event,
                                 *, have_notice: bool):
        """`_prepare_call` for the streaming claim, and what a failure there
        means: `None` tries the next engine; an error the cascade policy treats
        as final (`should_try_next_engine`) is raised as its HTTP answer —
        unless a notice is already in hand (`have_notice`, #1117), and then
        `_KEEP_THE_NOTICE` writes it instead of cutting a stream whose 200 is
        already out. Either way the error is logged here: the notice the user
        sees is the earlier engine's, and this one would otherwise leave no trace."""
        from core.endpoints.chat_engines.routing import raise_if_terminal, should_try_next_engine
        try:
            return await _prepare_call(ctx, index, engine_name, engine_obj, cancel_event, stream=True)
        except Exception as exc:
            logger.warning("%s failed: %s", engine_name, exc)
            logger.debug("Engine error details:", exc_info=True)
            if have_notice and not should_try_next_engine(exc):
                return _KEEP_THE_NOTICE
            raise_if_terminal(exc, engine_name)
            return None

    async def _claim_stream_engine(ctx: TurnContext, ui: dict, cancel_event, holder: list):
        """The engine that owns this stream, chosen before any of its bytes.

        Each candidate is started (`_prepare_call`, which also says the model
        it runs: a fallback's is the one it has loaded, #1035), the loading
        banner goes out if that model is not in memory, and its first event is
        read (`engine_call.claim_engine_start`). A
        real event claims the stream. A failure tries the next engine, unless
        the cascade policy treats it as final (`should_try_next_engine`).

        #1117: the response is committed by now, so when no engine claims the
        stream the FIRST one that failed on its first event keeps the turn,
        that event already read, and the normal path writes its notice (the
        out-of-memory one included) — usually the engine the user picked, and
        the wire 32f9cbd0 sent. A raise cuts the connection, so it is left for
        the two cases 32f9cbd0 already raised in: no engine got as far as its
        first event, or one failed to start with a final error before any
        notice was in hand.

        The loading banner names the first engine that needed a load. When it
        fails and another one loads, nexe-chat.js keeps that first label (a
        second banner would spin for ever there).

        Only wire strings come out. The claim goes into `holder`: Starlette
        encodes every chunk, so nothing else may reach the wire.
        """
        from core.endpoints.chat_engines.routing import should_try_next_engine
        announced = False
        first_failure = None
        pending = None
        try:
            for index, (engine_name, engine_obj) in enumerate(ui["candidates"]):
                if index > 0 and cancel_event.is_set():
                    break  # the turn is cancelled (client gone, deadline): no other engine is asked
                logger.info("Trying engine: %s", engine_name)
                prepared = await _prepare_or_decide(
                    ctx, index, engine_name, engine_obj, cancel_event, have_notice=first_failure is not None,
                )
                if prepared is _KEEP_THE_NOTICE:
                    break
                if prepared is None:
                    continue
                pending = prepared[0]
                if not announced:
                    # After `_prepare_call`: it says which model this attempt
                    # runs (a fallback's own, #1035), and that is the one the
                    # banner asks about and names.
                    # Once per turn: nexe-chat.js keeps a second banner spinning.
                    async for token in wire._yield_model_loading_check(engine_obj, prepared[-1], engine_name):
                        announced = True
                        yield token
                flags = StreamFlags()
                started = time.time()  # the load and the first token are this call's time
                events, first = await engine_call.claim_engine_start(prepared[0], prepared[-1], flags)
                pending = None
                attempt = _Claim(engine_name, engine_obj, prepared, (events, first), flags, started)
                if not isinstance(first, Failed):
                    holder.append(attempt)
                    return
                logger.warning("%s failed before its first byte: %s", engine_name, first.exc)
                logger.debug("Engine error details:", exc_info=first.exc)
                if first_failure is None:
                    # Replayed, its `started` also covers the engines tried after it.
                    first_failure = attempt
                if not should_try_next_engine(first.exc):
                    break  # final for the cascade policy: no other engine is asked
            if first_failure is None:
                raise HTTPException(status_code=503, detail="No AI engine available")
            holder.append(first_failure)
        finally:
            if pending is not None:
                await close_quietly(pending)

    async def generate_stream(ctx: TurnContext):
        ui = _ui(ctx)
        cancel_event, monitor = rc._start_disconnect_monitor(ctx.request)
        ctx.cancel_token = (cancel_event, monitor)
        deadline_handle = _arm_deadline(ctx, cancel_event)
        gate = gate_for(ctx.app_state)
        try:
            slot = await gate.acquire(
                Priority.USER_TURN, holder=ctx.turn_id, cancel_event=cancel_event, timeout=_gate_wait_s(),
            )
        except GateBusy:
            _cancel_monitor(ctx)
            if deadline_handle is not None:
                deadline_handle.cancel()
            raise HTTPException(status_code=429, detail="Server busy, try again in a moment")
        ctx.gpu_slot = slot
        # The slot is held for as long as THIS GENERATOR is alive — released in
        # the `finally` below, which PEP 525's `aclose()` reaches even if the
        # client disconnects mid-stream (run.py's `_drive_generator` always
        # closes it). Before C2.1 the UI's `Semaphore(2)` released when
        # `_chat_inner` returned the `StreamingResponse` OBJECT, before a single
        # token was generated — this is the fix.
        try:
            # #1117: the headers first — none of them depends on the engine
            # that will answer. The loading banner goes out inside the claim,
            # with the engine that is about to load.
            async for header in wire._yield_response_headers(
                ui["model_name"], ui["rag_count"], ctx.recall, ui["compacted"],
                ctx.session.compaction_count, ui["doc_truncated_pct"],
            ):
                yield header
            holder: list = []
            try:
                async with contextlib.aclosing(_claim_stream_engine(ctx, ui, cancel_event, holder)) as claiming:
                    async for token in claiming:
                        yield token
            except HTTPException:
                _cancel_monitor(ctx)
                raise
            except Exception as exc:
                _cancel_monitor(ctx)
                raise _internal_error(ctx, exc) from exc

            claim = holder[0]
            engine_name, engine_obj, flags = claim.engine_name, claim.engine_obj, claim.flags
            chat_result, sig, messages, thinking_enabled, model_name = claim.prepared
            _serve_with(ctx, engine_obj, ui)
            ui["engine_name"] = engine_name
            # #1035: from here on the turn's model is the one that answers. The
            # `[MODEL:]` header above went out with the requested one; the
            # client keeps the last it reads, so a fallback's goes out now —
            # when it answers, not when its failure is the notice replayed.
            if not isinstance(claim.primed[1], Failed):
                if model_name != ui["model_name"]:
                    yield wire.model_token(model_name)
                yield wire.engine_token(engine_name)  # #1146: the footer names the engine
            ui["model_name"] = model_name
            ui["reprompt_call"] = engine_call.reprompt_call_for(
                engine_obj, sig, model_name, messages, thinking_enabled,
            )
            stream_ctx = engine_call.StreamingChatContext(
                model_name=model_name, rag_count=ui["rag_count"], rag_items=ctx.recall,
                compacted=ui["compacted"], doc_truncated_pct=ui["doc_truncated_pct"],
                session=ctx.session, session_mgr=session_mgr, memory_helper=ui["memory_helper"],
                engine=engine_obj, engine_name=engine_name, chat_result=chat_result, sig=sig,
                system_prompt=ctx.system_prompt, messages=messages, thinking_enabled=thinking_enabled,
                lang=ctx.lang, message=ctx.message, disconnect_monitor_task=monitor,
                rag_collections=_rag_collections(ctx),
            )
            ui["stream_ctx"] = stream_ctx
            ui["stream_start_t"] = claim.started
            ui["flags"] = flags
            # `ctx.response` holds the RAW text while generating (what the old
            # body called full_response); `postprocess` turns it into the clean
            # answer.
            async for token, full_delta in engine_call._yield_engine_chunks(stream_ctx, claim.primed):
                ctx.response += full_delta
                if token is not None:
                    yield token
            _finish_generation(ctx, ui, flags, engine_name, ui["stream_start_t"])
        finally:
            if deadline_handle is not None:
                deadline_handle.cancel()
            await gate.release(slot)

    async def postprocess_stream(ctx: TurnContext):
        ui = _ui(ctx)
        stream_ctx, flags = ui["stream_ctx"], ui["flags"]
        full_response = ctx.response
        ui["full_response"] = full_response
        clean_response, mem_saves, mem_deletes = text_clean.clean_full_response(full_response, ctx.message)
        # FD-S5: its OWN yield (a marker split across reads would not be parsed).
        trunc_token = wire._gen_truncated_token(flags.trunc, flags.trunc_continuable, clean_response)
        if trunc_token:
            yield trunc_token
        # C4.5: one delete rule and one re-prompt for every door, in the core.
        # The I8 entry for the second call is the core's too — counted only
        # when an engine was really asked (this path used to count it whenever
        # the reply was empty, flag off or engine skipped alike).
        armed = await memory_deletes.arm_pending_deletes(
            stream_ctx.session, mem_deletes, stream_ctx.memory_helper, stream_ctx.rag_collections,
            user_message=ctx.message,
        )
        if armed is not None:
            yield wire.pending_delete_sentinel(armed.pending_delete_fact)
        if not clean_response and mem_saves and not ctx.resume:
            parts: list[str] = []
            async for chunk in policy.reprompt_chunks(
                ctx, mem_saves, call=ui.get("reprompt_call"),
                engine_name=ui.get("engine_name") or "", model=stream_ctx.model_name,
            ):
                parts.append(chunk)
                yield chunk
            # The wire got the chunks as they came (the web client strips a tag
            # itself); what is persisted and shown on reload is the joined,
            # clean text — or the neutral stand-in when nothing is left.
            clean_response = policy.second_answer_text(parts)
            if not clean_response:
                clean_response = policy.empty_reply_text(ctx.lang)
                yield clean_response
        if ctx.resume:
            # C4.6: the tail merges into a sentence already on screen — no
            # stand-in text (B125's placeholder or the neutral reply) is glued
            # onto it. An empty tail leaves the answer as it was.
            ctx.response = clean_response
        else:
            if not clean_response and full_response:
                logger.info("Think-only turn: persisting placeholder assistant message (B125)")
            ctx.response = text_clean.think_only_placeholder(clean_response, full_response)
        ctx.facts = mem_saves

    async def persist_stream(ctx: TurnContext) -> None:
        ui = _ui(ctx)
        stream_ctx = ui.get("stream_ctx")
        if stream_ctx is None and ctx.outcomes.get("generate") == "cancelled":
            # #1117: cancelled while the engine was still being claimed (Stop on
            # the loading banner). It has not said a word, so there is no answer
            # to store — the same as a cancel before the first token, below. The
            # stream context only exists once an engine owns the stream.
            _cancel_monitor(ctx)
            session_mgr.release_lease(ctx.session_id, ctx.turn_id)
            return
        if stream_ctx is None:
            # A short-circuited turn (memory command, internal error): no stream
            # ever started, the route's small stats apply.
            await persist_simple(ctx)
            return
        flags = ui["flags"]
        full_response = ui.get("full_response", ctx.response)
        if ctx.outcomes.get("generate") == "cancelled" or ctx.outcomes.get("postprocess") != "ok" or ctx.partial:
            # MC-116: the client went away mid-stream — keep what was generated.
            # #1040 (C2.4): `ctx.partial` covers the other broken-turn case —
            # the client is still there, but the engine errored mid-stream and
            # the error text is already on the wire. Same treatment either way:
            # persist what was generated as a partial turn, never as complete.
            if not ui.get("assistant_saved") and full_response:
                persist_partial_assistant(
                    stream_ctx.session, stream_ctx.session_mgr, full_response, stream_ctx.message,
                    resume=ctx.resume,
                )
                ui["assistant_saved"] = True
            _cancel_monitor(ctx)
            # C2.3: `emit` never runs on this path (AFTER_CANCEL is only
            # persist_assistant_turn) — this is the only chance to release
            # the lease so the session is not stuck until the TTL expires.
            session_mgr.release_lease(ctx.session_id, ctx.turn_id)
            return
        clean_response = ctx.response
        if not clean_response:
            return
        elapsed = round(time.time() - ui["stream_start_t"], 1)
        # Disk first (decision 06/09): the facts' count lands in these stats
        # AFTER `memory.write` runs — see `memory_write_stream`.
        stats = wire._build_mem_stats(
            stream_ctx.session, stream_ctx.rag_count, stream_ctx.rag_items, stream_ctx.model_name,
            elapsed, len(full_response), 0, ctx.facts, engine_name=ui.get("engine_name"),
        )
        persist_assistant_turn(
            stream_ctx.session, clean_response, full_response, stats, flags.trunc, flags.trunc_continuable,
            resume=ctx.resume,
        )
        session_mgr._save_session_to_disk(stream_ctx.session)
        ui["assistant_saved"] = True

    async def emit_stream(ctx: TurnContext):
        ui = _ui(ctx)
        stream_ctx = ui.get("stream_ctx")
        # C3.3: the news of what the PREVIOUS turn's background work did (the
        # decision of 06/09, finally wired). `emit` runs after `generate`, so
        # this lands at the end of this answer's stream.
        for chunk in _last_results_sentinels(ctx):
            yield chunk
        if stream_ctx is None:
            # A short-circuited turn: the pre-built text, one character at a
            # time, exactly as `_chat_inner` always did for memory commands.
            for char in ctx.response:
                yield char
            session_mgr.release_lease(ctx.session_id, ctx.turn_id)  # C2.3
            return
        note = _mem_sentinel(ctx)
        if note:
            # #1098: what THIS turn kept (D6 and/or memory.write, which now runs
            # before emit) rides after the answer — the facts the server
            # confirms, never the model's own tags.
            yield note
        if ctx.response:
            # #859/#965: the turn that fills the window warns about the one after
            # it. Deferred import: a plugin must not pull core at import time.
            from core.context_window import ask_engine_window
            if stream_ctx.session.needs_compaction(ask_engine_window(stream_ctx.engine)):
                yield "\x00[WILL_COMPACT:1]\x00"
        _cancel_monitor(ctx)  # stream finished cleanly — release the monitor
        session_mgr.release_lease(ctx.session_id, ctx.turn_id)  # C2.3: turn answered

    async def memory_write(ctx: TurnContext) -> None:
        """C3.3: one coroutine for both wire formats, and the same code /v1 runs.

        25/09 (ADR-007 §6 amended): inline again, before `emit`. On the queue
        (C2.2 → 25/09) what it saved was told one turn late, and the UI badged
        the model's own tags instead (#1098). It notes what it kept on the turn
        (`note_kept`) and `emit` sends it as `[MEM:n:facts]`.
        """
        if not ctx.facts:
            return
        ui = _ui(ctx)
        stream_ctx = ui.get("stream_ctx")
        session = stream_ctx.session if stream_ctx is not None else ctx.session
        started = time.monotonic()
        engine, gate, slot = await _atomiser_slot(
            ctx, stream_ctx.engine if stream_ctx is not None else None,
        )
        try:
            outcome = await write_facts(
                ctx.facts, session, ui["memory_helper"],
                engine=engine,
                model_name=ui.get("model_name") or "",
                sig=(getattr(stream_ctx, "sig", None) if stream_ctx is not None else None),
                lang=ctx.lang or "ca",
                rag_collections=_rag_collections(ctx),
                saved_by_intent=bool(ctx.usage.get("saved_by_intent")),
            )
        finally:
            if slot is not None:
                await gate.release(slot)
        ctx.facts = outcome.facts
        if outcome.engine_called:
            # I8 (C2.5): one bucket entry for the whole atomisation pass.
            # #1061: gated on the atomiser having reached the engine, not on
            # facts surviving. The JSON path has no `stream_ctx` and therefore
            # no engine, and a fact without a conjunction costs nothing even in
            # streaming — both used to be billed as an inference.
            record_llm_call(
                ctx, step="memory.write", engine=ui.get("engine_name") or "",
                ms=(time.monotonic() - started) * 1000.0,
            )
        note_kept(ctx.usage, outcome.saved, outcome.kept)
        if outcome.saved:
            _record_saved_facts(session, outcome, session_mgr, accumulate=ctx.resume)

    async def describe_image(ctx: TurnContext) -> None:
        """#1144, post-commit: the conversation's latest image, if it has no
        description yet, gets its own from the model that served this turn —
        kept with the message it came on (the encrypted session) and by image
        key. Later turns carry it as the image's note in the history
        (core/turn/assemble.py). An image already described is not described
        again; one whose description was preempted gets it on a later turn,
        and one that came back empty is tried `MAX_DESCRIBE_ATTEMPTS` times. A
        conversation deleted while this ran is not written back."""
        from core.turn import image_memory

        # The conversation's latest image still to be described, not only this
        # turn's: the queue keeps one job per (session, step), so a later
        # turn's job replaces a preempted one — live 03/10 that lost the
        # description of the image whose job a quick follow-up had interrupted.
        message = _latest_undescribed_image(ctx.session.messages)
        if message is None or ctx.engine is None:
            return
        image_b64 = message["image_b64"]
        key = image_memory.image_key(image_b64)
        description = image_memory.DESCRIPTIONS.get(key) or await _describe_now(ctx, image_b64, key)
        if not description:
            return
        message["image_description"] = description
        if session_mgr.save_session_if_live(ctx.session):
            logger.info("Image described for later turns (#1144): %d chars", len(description))

    async def _describe_now(ctx: TurnContext, image_b64: str, key: str) -> str:
        """One description call, counted only when the engine was asked; an
        empty answer that was not a cancellation is a failed attempt."""
        from core.endpoints.chat_engines.routing import engine_can_see_images  # deferred, as above
        from core.turn import image_memory

        if engine_can_see_images(ctx.engine) is False:
            image_memory.note_failed_attempt(key)
            logger.info("Image not described: the engine cannot see (#1144)")
            return ""
        cancel = ctx.usage.get("post_commit_cancel", {}).get("describe_image")
        started = time.monotonic()
        description = await image_memory.describe(
            ctx.engine, _ui(ctx).get("model_name") or "", image_b64, ctx.lang, cancel_event=cancel)
        record_llm_call(ctx, step="describe_image", engine=_ui(ctx).get("engine_name") or "",
                        ms=(time.monotonic() - started) * 1000.0)
        if description:
            image_memory.DESCRIPTIONS.put(key, description)
        elif cancel is None or not cancel.is_set():
            image_memory.note_failed_attempt(key)
            logger.info("Image description: none usable (#1144)")
        return description

    async def compact(ctx: TurnContext) -> None:
        """Post-commit (C2.2): used to run inline, before generation, inside
        `_build_turn_context` (#1042, closed at C1) — `budget` now passes
        `compact=False` there and this is the real thing, queued."""
        # I8 (C2.5): compact_session decides INTERNALLY whether there is
        # anything to summarise (session.needs_compaction()) and is a no-op
        # otherwise — comparing compaction_count before/after is the only way
        # to tell "ran and did nothing" from "actually spent an LLM call".
        _compacted_before = ctx.session.compaction_count
        _compact_started = time.monotonic()
        cancel = ctx.usage.get("post_commit_cancel", {}).get("compact")
        await compact_session(ctx.session, ctx.engine, session_mgr, cancel_event=cancel)
        if ctx.session.compaction_count > _compacted_before:
            record_llm_call(
                ctx, step="compact", engine=_ui(ctx).get("engine_name") or "",
                ms=(time.monotonic() - _compact_started) * 1000.0,
            )
            # C3.3: the next turn tells the user the conversation was summarised.
            ctx.usage.setdefault("post_commit_result", {})["compact"] = {
                "compacted": ctx.session.compaction_count - _compacted_before,
            }

    table: dict[str, Any] = {
        "validate": validate,
        "authorize": authorize_turn,
        "sanitize": sanitize,
        "session": session,
        "persist_user_turn": persist_user_turn,
        "intent": intent,
        "recall": recall,
        "clock": clock,
        "system_prompt": system_prompt,
        "engine": engine,
        "budget": budget,
        # C2.2: real now, queued by run.py's POST_COMMIT when a real queue is
        # attached — was folded (inline inside _build_turn_context, before
        # generation) until here. Same adapter for both wire shapes: compact
        # never touched the wire, streaming or not.
        "describe_image": describe_image,
        "compact": compact,
    }
    if streaming:
        table.update({
            "generate": generate_stream,
            "postprocess": postprocess_stream,
            "persist_assistant_turn": persist_stream,
            "emit": emit_stream,
            # C2.2: queued by run.py's POST_COMMIT when a real queue is
            # attached (production always has one); run.py's
            # _enqueue_post_commit already knows to drain a generator adapter
            # without forwarding its chunks — see the adapter's own docstring
            # for why it kept its yields instead of losing them for every
            # `post_commit=None` caller too.
            "memory.write": memory_write,
        })
    else:
        table.update({
            "generate": generate_json,
            "postprocess": postprocess_json,
            "persist_assistant_turn": persist_simple,
            "emit": emit_json,
            "memory.write": memory_write,
        })
    return table
