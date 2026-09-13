"""The API door (`POST /v1/chat/completions`) on the turn engine (ADR-007, C1.2).

One adapter per step of `TURN_STEPS`, each a thin wrapper over a function that
ALREADY exists in `core/endpoints/chat.py` and `core/endpoints/chat_engines/`.
Nothing here re-implements a behaviour: the point of C1.2 is that the route
stops deciding the order by hand and lets `run_turn` walk the map, with no
change a client can see. Unbundling what today's functions fuse together is
later work (C3, C4), and the pass-through adapters below say so one by one.

Two facts about today's code shape the adapters, and both are deliberate:

* Every call into `chat.py` goes through the `core.endpoints.chat` MODULE
  object, looked up at call time. The API's tests patch
  `core.endpoints.chat._forward_to_ollama` and friends; an adapter that imported
  those names directly would silently escape the patches and the 20 test files
  that are C1.2's parity gate would be testing the old path. The two session
  helpers (`derive_session_id`, `mirror_v1_conversation`) are imported from
  their own module: nobody patches them through `chat`, and `chat.py` no longer
  needs them itself.
* `_dispatch_through_cascade` returns the finished response object — a dict for
  JSON, a `StreamingResponse` whose SSE generator (inside the engine forwarder)
  generates, formats and persists on its own. So at this door `generate` is
  opaque with respect to streaming and the route uses `run_turn` for BOTH
  `body.stream` values: `ctx.wire` carries the object the route returns, and
  `emit` decorates it exactly as before. Splitting the forwarders' SSE
  generators into `stream_turn` steps is a refactor of `mlx.py`/`llama_cpp.py`/
  `ollama.py` — the same files #1036 (the double fallback) lives in — and
  belongs to C2, not to a wiring commit.

Folded steps: **none, since C4.2**. `intent`, `postprocess`, `memory.write`
and `compact` became real at C3.1-C3.4; `authorize` and `sanitize` at C4.1;
and `recall`, `clock` and `system_prompt` here — the three that used to live
inside `_build_rag_and_system_prompt`, which `budget` called whole. That
function is gone: what is left of it is `_assemble_v1_messages`, the `budget`
step, and the other three run for themselves through
`core/turn/{recall,prompt}.py` — the same functions `/ui/chat` runs.
`core/turn/folded.py` records the count, and it is 0 at both doors now.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse

from core.endpoints.chat_engines._common import (
    build_openai_response,
    derive_session_id,
    mirror_v1_conversation,
)
from core.memory_facts import intents
from core.memory_facts.extract import extract_memory_tags
from core.memory_facts.write import write_facts
from core.turn import policy
from core.turn.budget import record_llm_call
from core.turn.cancel import start_disconnect_monitor
from core.turn.context import TurnContext
from core.turn.deadline import resolve_deadline_s
from core.turn.gate import GateBusy, Priority, _gate_wait_s, gate_for
from core.turn.post_commit import queue_for
from core.turn.authorize import authorize_turn
from core.turn.run import Adapters, TurnShortCircuit
from core.turn.validate import sanitize_user_text, validate_turn


def _chat():
    # Deferred, and by module: core.endpoints.chat imports this module, and the
    # API's tests patch attributes ON core.endpoints.chat.
    import core.endpoints.chat as chat_mod
    return chat_mod


def _content_of(response: Any) -> str:
    """The assistant text inside a JSON response; "" for a stream or nothing."""
    if not isinstance(response, dict):
        return ""
    choices = response.get("choices") or []
    if choices:
        content = (choices[0].get("message") or {}).get("content") or ""
        if content:
            return content
    return (response.get("message") or {}).get("content") or ""


def _memory_news(ctx: TurnContext) -> dict:
    """What the client is told about memory: this turn's intent (C3.1) and what
    the previous turn's background work finished doing (C3.3)."""
    last = ctx.usage.get("last_results") or {}
    return {
        "Memory-Action": ctx.usage.get("memory_action") or "",
        "Memory-Saved": ctx.usage.get("memory_saved", 0),
        "Memory-Saved-Last-Turn": (last.get("memory.write") or {}).get("saved") or 0,
        "Compacted-Last-Turn": (last.get("compact") or {}).get("compacted") or 0,
    }


def _write_memory_news(ctx: TurnContext) -> None:
    """Same news, in the shape each wire understands — headers for a stream,
    `nexe_*` fields for a dict, the shape `_inject_response_headers` set."""
    for name, value in _memory_news(ctx).items():
        if not value:
            continue
        if isinstance(ctx.wire, StreamingResponse):
            ctx.wire.headers[f"X-Nexe-{name}"] = str(value)
        elif isinstance(ctx.wire, dict):
            ctx.wire.setdefault("nexe_" + name.lower().replace("-", "_"), value)


def api_adapters(background_tasks: BackgroundTasks) -> Adapters:
    """The adapter table for one request. Built per request because
    `persist_assistant_turn` needs this request's `BackgroundTasks`."""

    async def validate(ctx: TurnContext) -> None:
        chat = _chat()
        chat._validate_chat_request(ctx.body)
        ctx.message = next(
            (m.content for m in reversed(ctx.body.messages) if m.role == "user"), None
        ) or ""
        # C4.1: the shared `validate` (core/turn/validate.py). This door carries
        # no attachments, so all it adds today is the empty-message 400 the UI
        # door has always answered — one validate means one answer to "there is
        # no turn here", not two.
        await validate_turn(ctx)

    async def sanitize(ctx: TurnContext) -> None:
        """C4.1: no longer folded inside `_validate_chat_request`.

        The chain is `core.turn.validate.sanitize_user_text`, the same function
        `/ui/chat` runs. What is this door's own is WHERE the text lives: /v1
        carries the turn in `body.messages` and everything downstream reads it
        from there (`mirror_v1_conversation`, `_assemble_v1_messages`),
        so every user-role message goes through the chain and is written back,
        exactly as `_validate_chat_request` did until here — not just the last
        one, which would have left the earlier turns of a multi-turn request
        unsanitized.
        """
        last_user = ""
        for msg in ctx.body.messages:
            if msg.role == "user" and msg.content is not None:
                msg.content = sanitize_user_text(msg.content)
                last_user = msg.content
        ctx.message = last_user or ctx.message

    async def session(ctx: TurnContext) -> None:
        chat = _chat()
        ctx.session_id = derive_session_id(ctx.request, ctx.body.messages)
        ctx.lang = chat._resolve_request_lang(ctx.session_id, ctx.message)
        # C2.3 (ADR-007 §9/I9): same lease the UI door takes — one live
        # writer per session, whichever door it is (tanka #997: this is
        # exactly "the /v1 mirror wipes a UI thread's images/stats when a
        # client reuses its X-Session-Id" made impossible instead of fixed
        # per-symptom).
        #
        # get_or_create_session here, not just derive the id: the ChatSession
        # object this session_id names does not exist in the SessionManager
        # yet on a brand-new thread's first turn — mirror_v1_conversation
        # (persist_user_turn, the NEXT step) is what has always created it.
        # Without this, acquire_lease would find `session is None` every
        # time on that first turn and grant trivially, with nowhere to write
        # the lease — exactly the race this step exists to close. Idempotent:
        # persist_user_turn's own get_or_create_session finds the same object.
        session_mgr = getattr(ctx.app_state, "session_manager", None)
        if session_mgr is not None:
            session_mgr.get_or_create_session(ctx.session_id)
            result = session_mgr.acquire_lease(
                ctx.session_id, holder=ctx.entry, turn_id=ctx.turn_id, where="API",
                force=bool(getattr(ctx.body, "force_lease", False)),
            )
            if not result.granted:
                raise HTTPException(status_code=409, detail={"code": "session_leased", "lease": result.lease})
            queue = queue_for(ctx.app_state)
            if queue is not None:
                # C3.3: what the previous turn's background work finished doing.
                # AFTER the lease on purpose: reading it is popping it, and a
                # refused turn (409) would otherwise swallow the news for good.
                ctx.usage["last_results"] = queue.take_last_results(ctx.session_id)
                if queue.running(ctx.session_id):
                    queue.preempt(ctx.session_id)

    async def persist_user_turn(ctx: TurnContext) -> None:
        # F-C: the client's messages become the session mirror, saved to disk
        # here — BEFORE anything downstream touches memory (ADR-007 I3).
        mirror_v1_conversation(ctx.app_state, ctx.session_id, ctx.body.messages)

    async def engine(ctx: TurnContext) -> None:
        chat = _chat()
        ctx.engine, ctx.engine_fallback_from = chat._resolve_engine(ctx.body.engine, ctx.app_state)
        ctx.context_window = chat.get_effective_context_window(ctx.engine, ctx.app_state)
        ctx.deadline = resolve_deadline_s() or None

    async def recall(ctx: TurnContext) -> None:
        """C4.2: retrieval is a step of the turn, not a line inside `budget`.

        `_fetch_rag_context` is this door's question — `use_rag` is a field of
        this schema alone — and the retrieval under it is
        `core/turn/recall.py`, shared with the other door. What comes back is
        the RAW text: sizing it to the engine's window happens in `budget`,
        which is the first step that knows what the window is.
        """
        ctx.recall_text, ctx.recall = await _chat()._fetch_rag_context(
            ctx.body, ctx.app_state, ctx.lang
        )

    async def clock(ctx: TurnContext) -> None:
        """C4.2: B007's on-demand clock, resolved once and written down.

        `budget` prefixes it to this turn's user message (never the system
        prompt, which would poison the prefix cache for the whole
        conversation). Resolved from `ctx.message` — the last user message,
        which is the one the line is prefixed to.
        """
        # Deferred: `core.chat_prompt` is cheap, but this module is imported
        # while `core.endpoints.chat` is still initialising and the import
        # graph there is the cycle `_trim_rag_context` documents.
        from core.chat_prompt import time_context_line

        ctx.clock_line = time_context_line(ctx.message, ctx.lang)

    async def system_prompt(ctx: TurnContext) -> None:
        """C4.2: the same `turn_system_prompt` the web UI door runs.

        Visible consequence, declared: the collection-toggle notes (#851) reach
        this door for the first time. `rag_collections` has always been a field
        of this schema, retrieval has always honoured it, and the prompt kept
        promising sources the turn had switched off.
        """
        ctx.system_prompt = _chat()._system_prompt_for_turn(
            ctx.body, ctx.app_state, ctx.lang
        )

    async def budget(ctx: TurnContext) -> None:
        chat = _chat()
        ctx.prompt, ctx.recall_text = chat._assemble_v1_messages(
            ctx.body, ctx.system_prompt, ctx.recall_text, ctx.clock_line,
            ctx.lang, ctx.context_window,
        )
        # #976: what the budget planned and what got assembled are not the same
        # thing — the cascade fits again per candidate, this is the first pass.
        ctx.prompt = chat._fit_v1_messages_to_window(ctx.prompt, ctx.context_window, ctx.body)

    async def generate(ctx: TurnContext) -> None:
        chat = _chat()
        gate = gate_for(ctx.app_state)
        # #1041 (C2.5): /v1 had no cancellation channel at all before this —
        # neither a client-disconnect monitor nor a deadline. One event now
        # covers both: the same monitor the UI has always used, shared with a
        # timer armed below when ctx.deadline is set (`engine` adapter).
        cancel_event, monitor = start_disconnect_monitor(ctx.request)
        ctx.cancel_token = (cancel_event, monitor)
        deadline_handle = None
        if ctx.deadline:
            deadline_handle = asyncio.get_running_loop().call_later(ctx.deadline, cancel_event.set)

        def _stop_cancellation() -> None:
            if deadline_handle is not None:
                deadline_handle.cancel()
            if not monitor.done():
                monitor.cancel()

        try:
            slot = await gate.acquire(
                Priority.USER_TURN, holder=ctx.turn_id, cancel_event=cancel_event, timeout=_gate_wait_s(),
            )
        except GateBusy:
            _stop_cancellation()
            raise HTTPException(status_code=429, detail="Server busy, try again in a moment")
        ctx.gpu_slot = slot
        released = False
        _gen_started = time.monotonic()
        try:
            response, served_by, fallback_from, reason, served_model = await chat._dispatch_through_cascade(
                ctx.body, ctx.request, ctx.prompt, ctx.message or None,
                ctx.session_id, ctx.engine, ctx.engine_fallback_from,
                cancel_event=cancel_event,
            )
            # I8 (C2.5): the cascade may have tried more than one engine, but
            # `served_by` is the one that actually generated — a retry that
            # failed before any token spent no inference worth counting here.
            # #1054: `served_by` names the ENGINE; `served_model` names what it
            # loaded, which is what the UI door has always recorded here.
            record_llm_call(
                ctx, step="generate", engine=served_by, model=served_model,
                ms=(time.monotonic() - _gen_started) * 1000.0,
            )
            ctx.wire = response
            ctx.engine = served_by
            ctx.engine_fallback_from = fallback_from
            ctx.engine_fallback_reason = reason
            ctx.response = _content_of(response)
            if isinstance(response, StreamingResponse):
                # Ownership of the slot moves to the wrapped body: a streaming
                # response's generator/formatting/persistence all run inside
                # the engine forwarder, well after this adapter returns — the
                # slot must outlive `generate`, not end with it (C2.4 splits
                # this forwarder up; until then the slot follows the object).
                released = True
                inner = response.body_iterator

                async def _release_after(inner=inner):
                    try:
                        async for chunk in inner:
                            yield chunk
                    finally:
                        await gate.release(slot)
                        _stop_cancellation()

                response.body_iterator = _release_after()
        finally:
            if not released:
                await gate.release(slot)
                _stop_cancellation()

    async def persist_assistant_turn(ctx: TurnContext) -> None:
        # JSON: queued as a background task. Stream: a no-op here — the SSE
        # generator inside the forwarder persists when the text is complete.
        _chat()._persist_v1_turn_from_response(
            ctx.wire, background_tasks, ctx.app_state, ctx.session_id
        )

    async def intent(ctx: TurnContext) -> None:
        """D7 (C3.1): /v1 runs the same memory brain the web UI does.

        A memory command answers here, without a generation, exactly as it does
        at the other door; the difference is only how it is written down — plain
        text in the completion, plus `nexe_memory_*` fields (the shape
        `_inject_response_headers` already uses for engine and RAG status).
        """
        if not intents.intent_enabled():
            ctx.intent = "chat"
            return
        session_mgr = getattr(ctx.app_state, "session_manager", None)
        helper = getattr(ctx.app_state, "memory_helper", None)
        if session_mgr is None or helper is None:
            # Declared, not silent — but NOT as "folded": the step exists here
            # now (C3.1); it is degraded, which is a different thing, and
            # writing it to `folded` would tell the step map a lie the
            # baseline test would happily swallow.
            ctx.usage.setdefault("degraded", {})["intent"] = "no session_manager/memory_helper on app_state"
            ctx.intent = "chat"
            return
        session_obj = session_mgr.get_or_create_session(ctx.session_id)
        detected, extracted = intents.detect_with_pending(session_obj, ctx.message, helper)
        ctx.intent = detected
        if detected == "chat":
            return
        outcome = await intents.resolve(
            detected, extracted or "", session_obj, helper, ctx.message,
            # The field exists in the /v1 schema too; not passing it made the
            # memory-off switch structurally dead at this door.
            rag_collections=getattr(ctx.body, "rag_collections", None),
        )
        ctx.usage["memory_saved"] = ctx.usage.get("memory_saved", 0) + outcome.mem_saved
        ctx.usage["memory_action"] = outcome.memory_action
        # C3 review (08/09): same signal as the other door — D6 already owns
        # this turn's fact, so `memory.write` drops what the model repeats.
        ctx.usage["saved_by_intent"] = outcome.saved_by_intent
        ctx.intent = intents.outcome_for(detected, outcome)
        if outcome.continue_turn:
            # D6: the fact is saved; the model still answers the user.
            return
        model_name = getattr(ctx.body, "model", None) or "nexe-memory"
        ctx.wire = build_openai_response({"response": outcome.text}, model_name, "nexe-memory")
        raise TurnShortCircuit(outcome.text, reason=f"memory_intent:{outcome.kind}")

    async def postprocess(ctx: TurnContext) -> None:
        """C3.2: the model's memory tags are read at this door too.

        JSON only: in streaming the text has already left through the SSE
        forwarder by the time this runs, so a tag the model emitted mid-stream
        is already at the client. The sentinel FSM that lets the UI door strip
        them from a live stream is unified for both in C4 — until then this is
        a written limit, not a silent one.
        """
        if not isinstance(ctx.wire, dict):
            ctx.usage.setdefault("degraded", {})["postprocess"] = (
                "streaming: tags already forwarded to the client (C4)"
            )
            return
        try:
            message = ctx.wire["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            return
        clean, facts, deletes = extract_memory_tags(message.get("content") or "", user_input=ctx.message)
        if not clean and facts:
            # C3.5 (D3, partly): a turn whose whole answer was [MEM_SAVE:] tags
            # used to leave /v1 with a 200 and an EMPTY body — the UI door has
            # answered with this confirmation since #856. What is NOT done here
            # is the other half of D3: re-entering `generate` for a second, real
            # reply. That costs an LLM call from inside postprocess and is
            # written down as pending rather than improvised.
            clean = policy.mem_save_fallback_text(facts)
            ctx.usage.setdefault("degraded", {})["reprompt"] = "no second generation at /v1 yet (D3)"
        message["content"] = clean
        ctx.response = clean
        ctx.facts = facts
        if deletes:
            ctx.usage["mem_deletes"] = deletes

    async def memory_write(ctx: TurnContext) -> None:
        """C3.3: /v1 stores the facts its model marked, like the other door.

        Until now this step was folded here and the tags were shipped raw
        (C3.2 stopped that); reading them without ever storing them would have
        been the same silence with better manners.
        """
        if not ctx.facts:
            return
        session_mgr = getattr(ctx.app_state, "session_manager", None)
        helper = getattr(ctx.app_state, "memory_helper", None)
        if session_mgr is None or helper is None:
            ctx.usage.setdefault("degraded", {})["memory.write"] = "no session_manager/memory_helper on app_state"
            return
        session = session_mgr.get_or_create_session(ctx.session_id)
        started = time.monotonic()
        # No engine: /v1 does not spend an extra LLM call to atomise a fact.
        outcome = await write_facts(
            ctx.facts, session, helper, lang=ctx.lang or "ca",
            rag_collections=getattr(ctx.body, "rag_collections", None),
            saved_by_intent=bool(ctx.usage.get("saved_by_intent")),
        )
        ctx.facts = outcome.facts
        # #1061: this door passes no engine, so the atomiser never runs here —
        # the call was billed anyway. `engine_called` is the only thing that
        # knows an inference happened; `outcome.facts` only means facts survived.
        if outcome.engine_called:
            record_llm_call(ctx, step="memory.write", engine=ctx.engine or "",
                            ms=(time.monotonic() - started) * 1000.0)
        if outcome.saved:
            ctx.usage.setdefault("post_commit_result", {})["memory.write"] = {"saved": outcome.saved}

    async def compact(ctx: TurnContext) -> None:
        """C3.4: /v1 summarises a long conversation too.

        Same function the UI door calls, on the same post-commit queue: a
        conversation that overran its window was compacted at one door and not
        at the other, so the same thread behaved differently depending on which
        client had been talking to it.
        """
        session_mgr = getattr(ctx.app_state, "session_manager", None)
        if session_mgr is None:
            ctx.usage.setdefault("degraded", {})["compact"] = "no session_manager on app_state"
            return
        # Deferred: core.sessions imports back into core.turn, and this module
        # is imported while core.turn is still initialising.
        from core.endpoints.chat_engines.routing import get_engine_module
        from core.sessions.compactor import compact_session

        # `ctx.engine` is the engine's NAME at this door (`served_by`, a str),
        # while the compactor needs the module to call `.chat()` on. Passing the
        # name straight through raised AttributeError inside compact_session,
        # where a broad `except Exception` turned it into a warning: /v1 looked
        # like it compacted and never did.
        engine_module = get_engine_module(ctx.engine, ctx.app_state) if isinstance(ctx.engine, str) else ctx.engine
        if engine_module is None or not hasattr(engine_module, "chat"):
            ctx.usage.setdefault("degraded", {})["compact"] = f"no live module for engine {ctx.engine!r}"
            return

        session = session_mgr.get_or_create_session(ctx.session_id)
        before = getattr(session, "compaction_count", 0)
        started = time.monotonic()
        cancel = ctx.usage.get("post_commit_cancel", {}).get("compact")
        await compact_session(session, engine_module, session_mgr, cancel_event=cancel)
        if getattr(session, "compaction_count", 0) > before:
            record_llm_call(ctx, step="compact", engine=str(ctx.engine or ""),
                            ms=(time.monotonic() - started) * 1000.0)
            ctx.usage.setdefault("post_commit_result", {})["compact"] = {
                "compacted": session.compaction_count - before,
            }

    async def emit(ctx: TurnContext) -> None:
        ctx.wire = _chat()._inject_response_headers(
            ctx.wire, ctx.engine, ctx.recall_text, ctx.engine_fallback_from, ctx.engine_fallback_reason
        )
        # C2.0: one id to grep for in `turn.trace` log lines, on both wire shapes.
        if isinstance(ctx.wire, StreamingResponse):
            ctx.wire.headers["X-Nexe-Turn-Id"] = ctx.turn_id
        elif isinstance(ctx.wire, dict):
            ctx.wire.setdefault("turn_id", ctx.turn_id)
        _write_memory_news(ctx)
        # C2.3: release the lease taken in `session`. Known gap for the
        # streaming shape (docstring above: this door's `generate` is opaque
        # to streaming — the forwarder still sends tokens after this adapter
        # returns), so this releases a moment before the stream truly ends,
        # same trade-off #1036/C2.4's forwarder split will also have to
        # revisit. The JSON shape is exact: nothing sends after this.
        session_mgr = getattr(ctx.app_state, "session_manager", None)
        if session_mgr is not None:
            session_mgr.release_lease(ctx.session_id, ctx.turn_id)

    return {
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
        "generate": generate,
        "postprocess": postprocess,
        "persist_assistant_turn": persist_assistant_turn,
        "emit": emit,
        "memory.write": memory_write,
        "compact": compact,
    }
