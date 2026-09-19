"""The web UI door (`POST /ui/chat`) on the turn engine (ADR-007, C1.3).

One adapter per step of `core.turn.steps.TURN_STEPS`, each a thin wrapper over a
function that ALREADY exists in `routes_chat.py`. The adapters live in the
plugin, not in `core/turn/`: the UI's behaviour is plugin code, and the layering
gate keeps `core → plugins` at zero. Every call into `routes_chat` goes through
the module object, looked up at call time — the UI's tests patch attributes on
`plugins.web_ui_module.api.routes_chat` (`helper_for` from the core,
the core's `compact_session`) and on `core.lifespan` (`get_server_state`).

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

What does NOT go through these adapters (decision §5 of the C1 plan): the FD-S6
`continue` flow, which keeps its own path in `_chat_inner` and still calls
`_handle_chat_engine` — hence that function stays, sharing `_start_engine_call`
and `_start_disconnect_monitor` with the adapters instead of a second copy.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
from typing import Any

from fastapi import HTTPException

from core.turn.authorize import authorize_turn
from core.turn.budget import record_llm_call
from core.turn.context import TurnContext
from core.turn.deadline import resolve_deadline_s
from core.turn.gate import GateBusy, Priority, _gate_wait_s, gate_for
import core.memory_facts as memory_facts
from core.memory_facts import intents
from core.memory_facts.write import write_facts
from core.sessions.compactor import compact_session
from core.turn.post_commit import queue_for
from core.turn.prompt import _resolve_session_lang, turn_system_prompt
from core.turn.recall import _build_rag_context, collections_for_turn
from core.turn.run import Adapters, TurnShortCircuit
from core.turn.validate import (
    jailbreak_speed_bump,
    parse_top_p,
    sanitize_user_text,
    validate_turn,
)

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


async def _switch_model(engine, engine_name: str, model_name: str) -> None:
    # Deferred: a plugin must not pull core at import time (layering gate, #471).
    from core.endpoints.chat_engines.model_switch import model_switch_lock, switch_engine_model
    async with model_switch_lock():
        await switch_engine_model(engine, engine_name, model_name)


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
    paints (:643 COMPACT, :762 MEM). They ride in `emit`, which is the last step
    of the turn — so they reach the client at the END of the next answer's
    stream, not before it. The frontend clears them wherever they land."""
    out = []
    results = _last_results(ctx)
    saved = (results.get("memory.write") or {}).get("saved") or 0
    compacted = (results.get("compact") or {}).get("compacted") or 0
    if saved:
        out.append(f"\x00[MEM:{saved}]\x00")
    if compacted:
        out.append(f"\x00[COMPACT:{compacted}]\x00")
    return out


def _last_results_fields(ctx: TurnContext) -> dict:
    """The same news for a JSON reply."""
    results = _last_results(ctx)
    fields = {}
    saved = (results.get("memory.write") or {}).get("saved") or 0
    compacted = (results.get("compact") or {}).get("compacted") or 0
    if saved:
        fields["memory_saved_last_turn"] = saved
    if compacted:
        fields["compacted_last_turn"] = compacted
    return fields


def _record_saved_facts(session, outcome, session_mgr) -> None:
    """Complete the assistant turn's stats with what memory ended up keeping.

    Disk first: the turn was committed before the facts existed in memory; now
    that they do, the stats say so (same fields as before C3.3).
    """
    if not (session.messages and session.messages[-1].get("role") == "assistant"):
        return
    stats = session.messages[-1].setdefault("stats", {})
    stats["mem_saved"] = outcome.saved
    stats["mem_facts"] = [f.strip() for f in outcome.facts if f.strip() and len(f.strip()) >= 5]
    session_mgr._save_session_to_disk(session)


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
        ctx.message = jailbreak_speed_bump(ctx.message)

    async def session(ctx: TurnContext) -> None:
        ctx.session = session_mgr.get_or_create_session(ctx.body.get("session_id"))
        ctx.session_id = ctx.session.id
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
        ctx.session.add_message(
            "user", ctx.message,
            image_b64=ctx.attachments.get("image_b64"),
            image_type=ctx.attachments.get("image_type"),
        )
        session_mgr._save_session_to_disk(ctx.session)

    async def intent(ctx: TurnContext) -> None:
        ui = _ui(ctx)
        port = memory_facts.helper_for(ctx.app_state)
        ui["memory_helper"] = port
        ui.setdefault("memory_action", None)
        ui.setdefault("mem_deleted", 0)
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
        ctx.usage["memory_saved"] = ctx.usage.get("memory_saved", 0) + outcome.mem_saved
        # C3 review (08/09): `memory.write` needs to know D6 already owns this
        # turn's fact. Not derived from `memory_action` — postprocess can
        # overwrite that to "delete_pending" in the same turn, and a `recall`
        # sets it without any save having happened.
        ctx.usage["saved_by_intent"] = outcome.saved_by_intent
        ctx.intent = intents.outcome_for(detected, outcome)
        if outcome.continue_turn:
            # D6: the fact is already saved; the model answers the user normally.
            return
        raise TurnShortCircuit(rc.render_intent_for_ui(outcome), reason=f"memory_intent:{outcome.kind}")

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
        """C4.2: B007's on-demand clock, resolved once and written down.

        It used to be computed inside `_assemble_engine_messages`, which
        `budget` calls — the last thing this door had folded. `budget` still
        prefixes it to this turn's user message and never to the system
        prompt, which would poison the prefix cache for the whole conversation.
        """
        from core.chat_prompt import time_context_line

        ctx.clock_line = time_context_line(ctx.message, ctx.lang)

    async def system_prompt(ctx: TurnContext) -> None:
        """C4.2: the same `turn_system_prompt` /v1 runs.

        The language is already resolved (the `session` step) and the
        collection toggles are this door's field: the body carries them, and
        the session remembers them so a `continue` stays inside the prefix the
        turn just built.
        """
        _rag_cols = ctx.body.get("rag_collections")
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
            ui["model_name"] = model_name
            ui["candidates"] = candidates
            ui["engine_name"], ctx.engine = candidates[0]
            if ctx.body.get("model"):
                await _switch_model(ctx.engine, ui["engine_name"], model_name)
            ctx.context_window = ask_engine_window(ctx.engine)
            ctx.deadline = resolve_deadline_s() or None
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
                ctx.body, ctx.session, session_mgr, ctx.engine, ctx.message, False,
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
                turn, ctx.system_prompt, ctx.lang, ctx.message, ctx.session, False, ctx.engine,
                clock_line=ctx.clock_line,
            )
            if ctx.attachments.get("image_b64"):
                messages = rc._inject_image_block(messages)
            ctx.prompt = messages
            ui["doc_truncated_pct"] = doc_truncated_pct
            ui["compacted"] = ctx.session.compaction_count > 0 and ctx.session.context_summary is not None
        except HTTPException:
            raise
        except Exception as exc:
            raise _internal_error(ctx, exc) from exc

    async def _prepare_call(ctx: TurnContext, index: int, engine_name: str, engine_obj, cancel_event, *, stream: bool):
        """One engine attempt's setup: model switch (fallbacks only — the first
        candidate was switched in `engine`), signature, prompt refit, start."""
        ui = _ui(ctx)
        if index > 0 and ctx.body.get("model"):
            await _switch_model(engine_obj, engine_name, ui["model_name"])
        thinking_enabled = getattr(ctx.session, "thinking_enabled", False)
        sig = inspect.signature(engine_obj.chat)
        messages = ctx.prompt if index == 0 else _refit_for(engine_obj, ctx.system_prompt, ctx.prompt)
        top_p = parse_top_p(ctx.body)
        sampling_kwargs = {"top_p": top_p} if top_p is not None else {}
        chat_result = rc._start_engine_call(
            engine_obj, engine_name, sig, ui["model_name"], ctx.system_prompt, messages,
            stream=stream, image_b64=ctx.attachments.get("image_b64"),
            thinking_enabled=thinking_enabled, cancel_event=cancel_event,
            sampling_kwargs=sampling_kwargs, session_id=ctx.session.id, _continue=False,
        )
        return chat_result, sig, messages, thinking_enabled

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
                    chat_result, sig, messages, thinking_enabled = await _prepare_call(
                        ctx, index, engine_name, engine_obj, cancel_event, stream=False,
                    )
                    # #856: what the non-streaming re-prompt needs, captured live.
                    ui["reprompt_ctx"] = rc.NonStreamRepromptContext(
                        engine=engine_obj, model_name=ui["model_name"], sig=sig, lang=ctx.lang,
                        system_prompt=ctx.system_prompt, messages=messages,
                        thinking_enabled=thinking_enabled,
                    )
                    chunks: list[str] = []
                    await rc._accumulate_nonstreaming_response(chat_result, chunks)
                    text = "".join(chunks)
                    if text:
                        logger.info("%s succeeded!", engine_name)
                        record_llm_call(
                            ctx, step="generate", engine=engine_name, model=ui["model_name"],
                            ms=(time.monotonic() - _call_started) * 1000.0,
                        )
                        ctx.response = text
                        ctx.engine = engine_obj
                        ui["engine_name"] = engine_name
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
        ui = _ui(ctx)
        if not ctx.response or ctx.response.startswith("Error:"):
            return
        text, memory_action, mem_deleted_delta, mem_saves = await rc._postprocess_nonstreaming(
            ctx.response, ctx.session, ui["memory_helper"], ctx.message, ui["memory_action"],
            ctx.body.get("rag_collections"), ui.get("reprompt_ctx"),
        )
        ctx.response = text
        ui["memory_action"] = memory_action
        ui["mem_deleted"] += mem_deleted_delta
        ctx.facts = mem_saves

    async def persist_simple(ctx: TurnContext) -> None:
        """The JSON reply and every short-circuited turn (a memory command's
        answer): one assistant message with the route's small stats. `elapsed`
        is measured now — the old body wrote a literal 0 (routes_chat.py:3039)."""
        ui = _ui(ctx)
        # B127: never persist an engine error ("Error: ...") as an assistant turn.
        if ctx.response.startswith("Error:"):
            return
        model_name = ui.get("model_name")
        ctx.session.add_message("assistant", ctx.response, stats={
            "tokens": max(1, len(ctx.response) // 4),
            "elapsed": round(time.time() - ui.get("start_t", time.time()), 1),
            "model": str(model_name)[:100] if model_name else None,
            "mem_deleted": ui.get("mem_deleted") or None,
        })
        session_mgr._save_session_to_disk(ctx.session)

    async def emit_json(ctx: TurnContext) -> None:
        ctx.wire = {
            "response": ctx.response,
            "session_id": ctx.session.id,
            "intent": ctx.intent,
            "memory_action": _ui(ctx).get("memory_action"),
            # D6: how many facts the intent step saved in THIS turn (0 normally).
            "memory_saved": ctx.usage.get("memory_saved", 0),
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
            # #1040 (C2.4): the error is already on the wire (as text, via
            # _stream_error_notice) — it cannot be retried, only recorded.
            # A partial turn is persisted as such downstream (persist_stream)
            # and queues no memory.write (run.py): facts extracted from a
            # broken reply are not trustworthy.
            ctx.partial = True
            ctx.error = {
                "step": "generate",
                "class": rc._classify_engine_error(flags.error),
                "message": str(flags.error),
            }

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
            try:
                from core.endpoints.chat_engines.routing import raise_if_terminal
                started = None
                for index, (engine_name, engine_obj) in enumerate(ui["candidates"]):
                    logger.info("Trying engine: %s", engine_name)
                    try:
                        started = await _prepare_call(ctx, index, engine_name, engine_obj, cancel_event, stream=True)
                        break  # the first engine that starts owns the stream (as before)
                    except Exception as exc:
                        raise_if_terminal(exc, engine_name)
                        logger.warning("%s failed: %s", engine_name, exc)
                        logger.debug("Engine error details:", exc_info=True)
                        continue
                if started is None:
                    raise HTTPException(status_code=503, detail="No AI engine available")
            except HTTPException:
                _cancel_monitor(ctx)
                raise
            except Exception as exc:
                _cancel_monitor(ctx)
                raise _internal_error(ctx, exc) from exc

            chat_result, sig, messages, thinking_enabled = started
            ctx.engine = engine_obj
            ui["engine_name"] = engine_name
            stream_ctx = rc.StreamingChatContext(
                model_name=ui["model_name"], rag_count=ui["rag_count"], rag_items=ctx.recall,
                compacted=ui["compacted"], doc_truncated_pct=ui["doc_truncated_pct"],
                session=ctx.session, session_mgr=session_mgr, memory_helper=ui["memory_helper"],
                engine=engine_obj, engine_name=engine_name, chat_result=chat_result, sig=sig,
                system_prompt=ctx.system_prompt, messages=messages, thinking_enabled=thinking_enabled,
                lang=ctx.lang, message=ctx.message, disconnect_monitor_task=monitor,
                rag_collections=ctx.body.get("rag_collections"), continue_mode=False,
            )
            ui["stream_ctx"] = stream_ctx
            async for header in rc._yield_response_headers(
                stream_ctx.model_name, stream_ctx.rag_count, stream_ctx.rag_items, stream_ctx.compacted,
                stream_ctx.session.compaction_count, stream_ctx.doc_truncated_pct,
            ):
                yield header
            async for token in rc._yield_model_loading_check(engine_obj, stream_ctx.model_name, engine_name):
                yield token
            ui["stream_start_t"] = time.time()
            flags = rc._StreamFlags()
            ui["flags"] = flags
            # `ctx.response` holds the RAW text while generating (what the old
            # body called full_response); `postprocess` turns it into the clean
            # answer.
            async for token, full_delta in rc._yield_engine_chunks(stream_ctx, flags):
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
        clean_response, mem_saves, mem_deletes = rc._clean_full_response(full_response, ctx.message)
        # FD-S5: its OWN yield (a marker split across reads would not be parsed).
        trunc_token = rc._gen_truncated_token(flags.trunc, flags.trunc_continuable, clean_response)
        if trunc_token:
            yield trunc_token
        async for token in rc._yield_mem_delete_prompts(stream_ctx, mem_deletes):
            yield token
        reprompt_out: list = []
        # I8 (C2.5): _yield_reprompt_when_only_mem_saves is a no-op unless
        # clean_response is empty AND there are facts — same condition it
        # checks internally, so a turn that never re-prompts adds no entry.
        _will_reprompt = not clean_response and bool(mem_saves)
        _rp_started = time.monotonic()
        async for chunk in rc._yield_reprompt_when_only_mem_saves(stream_ctx, clean_response, mem_saves, reprompt_out):
            yield chunk
        if _will_reprompt:
            record_llm_call(
                ctx, step="reprompt", engine=ui.get("engine_name") or "",
                ms=(time.monotonic() - _rp_started) * 1000.0,
            )
        if reprompt_out:
            clean_response = reprompt_out[0]
        if not clean_response and full_response:
            logger.info("Think-only turn: persisting placeholder assistant message (B125)")
        ctx.response = rc._think_only_placeholder(clean_response, full_response)
        ctx.facts = mem_saves

    async def persist_stream(ctx: TurnContext) -> None:
        ui = _ui(ctx)
        stream_ctx = ui.get("stream_ctx")
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
                rc._persist_partial_assistant(stream_ctx, full_response)
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
        stats = rc._build_mem_stats(
            stream_ctx.session, stream_ctx.rag_count, stream_ctx.rag_items, stream_ctx.model_name,
            elapsed, len(full_response), 0, ctx.facts,
        )
        rc._persist_assistant_turn(stream_ctx, clean_response, full_response, stats, flags.trunc, flags.trunc_continuable)
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
        saved = ctx.usage.get("memory_saved", 0)
        if saved:
            # D6: "remember that ..." no longer answers instead of the model —
            # the note that it was saved rides after the answer, as a sentinel
            # `nexe-chat.js` already paints (:762).
            yield f"\x00[MEM:{saved}]\x00"
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

        The two async generators this replaces yielded `[SAVING]`/`[MEM:n]` into
        the stream. Since C2.2 this step runs on the post-commit queue, where
        `_enqueue_post_commit` drains a generator without forwarding a single
        chunk: those sentinels reached nobody in production. What the user sees
        now is published for the NEXT turn (`post_commit_result` ->
        `take_last_results`), which is the decision of 06/09 finally wired.
        """
        if not ctx.facts:
            return
        ui = _ui(ctx)
        stream_ctx = ui.get("stream_ctx")
        session = stream_ctx.session if stream_ctx is not None else ctx.session
        started = time.monotonic()
        outcome = await write_facts(
            ctx.facts, session, ui["memory_helper"],
            # The atomiser costs an LLM call, so it only runs where an engine is
            # already in hand — the streaming path, exactly as before C3.3.
            engine=(stream_ctx.engine if stream_ctx is not None else None),
            model_name=ui.get("model_name") or "",
            sig=(getattr(stream_ctx, "sig", None) if stream_ctx is not None else None),
            lang=ctx.lang or "ca",
            rag_collections=ctx.body.get("rag_collections"),
            saved_by_intent=bool(ctx.usage.get("saved_by_intent")),
        )
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
        if outcome.saved:
            ctx.usage.setdefault("post_commit_result", {})["memory.write"] = {"saved": outcome.saved}
            _record_saved_facts(session, outcome, session_mgr)

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
