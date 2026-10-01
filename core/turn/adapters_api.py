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
* `run_turn` is the JSON shape. `stream_turn` (C4.6-b) is the streaming one:
  `api_adapters(..., streaming=True)` swaps `generate`, `postprocess`,
  `persist_assistant_turn` and `emit` for async generators. The engines yield
  tokens and one sentinel; this table cleans, reads the facts, persists and
  writes `[DONE]`. The default stays the coroutine table every JSON caller
  walks. A stream is no longer opaque at this door.

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
import json
import logging
import time
from typing import Any, Optional

from fastapi import BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse

from core.endpoints.chat_engines._common import (
    build_openai_response,
    derive_session_id,
    mirror_v1_conversation,
    persist_v1_turn,
    served_model_of,
)
from core.endpoints.chat_engines._streaming import (
    NEXE_END,
    SSE_DONE,
    format_sse_chunk,
    format_sse_done,
    format_sse_role,
)
from core.memory_facts import intents
from core.memory_facts.deletes import arm_pending_deletes
from core.memory_facts.write import note_kept, write_facts
from core.turn import policy
from core.turn.budget import record_llm_call
from core.turn.cancel import start_disconnect_monitor
from core.turn.context import TurnContext
from core.turn.deadline import resolve_deadline_s
from core.turn.gate import GateBusy, Priority, _gate_wait_s, gate_for
from core.turn.post_commit import queue_for
from core.turn.authorize import authorize_turn
from core.turn.run import Adapters, TurnShortCircuit
from core.turn.reasoning import split_text
from core.turn.text.clean import clean_full_response
from core.turn.text.sse import SseCleaner
from core.turn.validate import parse_content_parts, sanitize_user_text, validate_turn


logger = logging.getLogger(__name__)


def _chat():
    # Deferred, and by module: core.endpoints.chat imports this module, and the
    # API's tests patch attributes ON core.endpoints.chat.
    import core.endpoints.chat as chat_mod
    return chat_mod


def _wants_reasoning(ctx: TurnContext) -> bool:
    """ADR-010: /v1 reasons only when the request asks (`reasoning_effort`)."""
    wants = getattr(ctx.body, "wants_reasoning", None)
    return callable(wants) and wants() is True


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


async def _text_of_reprompt_stream(body):
    """Answer text from a second call that came back as SSE.

    Production asks with `stream=False` and gets a dict. The turn lab's
    engine fake always speaks SSE, so the same drain has to read both.
    Sentinels carry no answer.
    """
    async for chunk in body:
        if _end_of(chunk) is not None:
            continue
        text = _raw_of(chunk)
        if text:
            yield text


def _reasoning_apart(response: Any) -> str:
    """Reasoning a JSON engine already split out of the answer (ADR-010)."""
    if not isinstance(response, dict):
        return ""
    first = (response.get("choices") or [{}])[0] or {}
    return (first.get("message") or {}).get("reasoning") or ""


def _note_reprompt_reasoning(ctx: TurnContext, reasoning: str) -> None:
    """Keep the second call's reasoning on the JSON wire, only if asked."""
    if not reasoning or not _wants_reasoning(ctx) or not isinstance(ctx.wire, dict):
        return
    message = ctx.wire["choices"][0]["message"]
    message["reasoning"] = (message.get("reasoning") or "") + reasoning


def _v1_reprompt_call(ctx: TurnContext):
    """This door's way of asking its engine once more — `policy.reprompt_chunks`'s
    `call` (C4.5). The same cascade `generate` walked, non-streaming, with the
    turn's prompt under the override; the reply's reasoning is set apart as
    `postprocess` does with the first one (ADR-010), kept only if asked for."""
    chat = _chat()

    def call(system_prompt: str):
        prompt = list(ctx.prompt)
        if prompt and isinstance(prompt[0], dict) and prompt[0].get("role") == "system":
            prompt[0] = {**prompt[0], "content": system_prompt}
        else:
            prompt.insert(0, {"role": "system", "content": system_prompt})

        async def chunks():
            response, _served_by, _fallback_from, _reason, _model = await chat._dispatch_through_cascade(
                ctx.body, ctx.request, prompt, ctx.message or None,
                ctx.session_id, ctx.engine, ctx.engine_fallback_from,
                resume=False,
            )
            if isinstance(response, StreamingResponse):
                async for text in _text_of_reprompt_stream(response.body_iterator):
                    yield text
                return
            inline_reasoning, answer = split_text(_content_of(response))
            _note_reprompt_reasoning(ctx, _reasoning_apart(response) + inline_reasoning)
            if answer:
                yield answer

        return chunks()

    return call


async def _arm_pending_delete(ctx: TurnContext, deletes: list, clean: str) -> str:
    """C4.5: the model's [MEM_DELETE:] tags arm the same confirmation the web
    door arms (`core.memory_facts.deletes`), instead of landing in a usage field
    nobody read. The question rides in the content; the entry to confirm, in
    `nexe_pending_delete` / `X-Nexe-Pending-Delete`. The "sí" of the next turn
    is the `intent` step's job (C3.1). Returns the content to send."""
    helper = getattr(ctx.app_state, "memory_helper", None)
    if ctx.session is None or helper is None:
        return clean
    armed = await arm_pending_deletes(
        ctx.session, deletes, helper, getattr(ctx.body, "rag_collections", None),
    )
    if armed is None:
        return clean
    ctx.usage["memory_action"] = armed.memory_action
    ctx.usage["pending_delete"] = armed.pending_delete_fact
    return f"{clean}\n\n{armed.text}" if clean else armed.text


async def _second_reply(ctx: TurnContext, facts: list) -> str:
    """D3, whole (C4.5): a turn whose whole answer was [MEM_SAVE:] tags gets the
    second generation the web door has spent since #856 — through the one core
    policy, inside the gate, counted once. Until now this door wrote it down as
    `degraded["reprompt"]` and answered with a confirmation built from the
    model's tags. Nothing back → the neutral stand-in, in the turn's language."""
    parts: list[str] = []
    async for chunk in policy.reprompt_chunks(
        ctx, facts, call=_v1_reprompt_call(ctx),
        # I8 names the model: the one the JSON reply says answered — the same
        # source `generate` read (`served_model_of`), not a new usage bucket.
        engine_name=ctx.engine or "", model=served_model_of(ctx.wire),
    ):
        parts.append(chunk)
    return policy.second_answer_text(parts) or policy.empty_reply_text(ctx.lang)


def _memory_news(ctx: TurnContext) -> dict:
    """What the client is told about memory: this turn's intent (C3.1), what
    THIS turn stored (D6 and `memory.write`, inline before `emit` since 25/09)
    and what the previous turn's background work finished doing (C3.3).
    `Memory-Saved-Last-Turn` stays for clients that read it; memory no longer
    runs in the background, so it is never sent (0 is skipped)."""
    last = ctx.usage.get("last_results") or {}
    return {
        "Memory-Action": ctx.usage.get("memory_action") or "",
        "Memory-Saved": ctx.usage.get("memory_saved", 0),
        "Memory-Saved-Last-Turn": (last.get("memory.write") or {}).get("saved") or 0,
        "Compacted-Last-Turn": (last.get("compact") or {}).get("compacted") or 0,
        # C4.5: the entry a model's [MEM_DELETE:] left waiting for the user's
        # "sí" — what the web UI's dialog shows, said in this door's alphabet.
        "Pending-Delete": ctx.usage.get("pending_delete") or "",
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
    kept = ctx.usage.get("memory_kept") or []
    if kept and isinstance(ctx.wire, dict):
        # The facts themselves only in a body: a header is no place for them.
        ctx.wire.setdefault("nexe_memory_facts", list(kept))


def _peel_content_parts(ctx: TurnContext) -> None:
    """Turn every multi-part `content` into plain text, keeping ONE image.

    The image kept is the most RECENT one in the conversation, not the one
    on the last message (#1081 review). A vision client re-sends its whole
    history: the image rides on turn 1 and the follow-up question ("and what
    colour is the one on the left?") arrives on turn 3 with no parts at all.
    Reading only the last user message dropped that image on the floor — no
    log, no header, `has_image` False, and an answer about nothing.

    One image per turn is still the premise the engines are built on
    (`_images_arg = [image_b64]`), so older images are dropped — but counted
    and said out loud, which is the half that was missing.
    """
    image_b64 = image_type = None
    older_images = 0
    # Backwards: the first image found walking from the newest message is the
    # one this turn should carry.
    for msg in reversed(ctx.body.messages):
        if isinstance(msg.content, str):
            continue
        text, msg_image, msg_image_type = parse_content_parts(msg.content)
        if msg_image:
            if image_b64 is None:
                image_b64, image_type = msg_image, msg_image_type
            else:
                older_images += 1
        msg.content = text
    if image_b64:
        ctx.attachments["image_b64"] = image_b64
        ctx.attachments["image_type"] = image_type
    if older_images:
        logger.warning(
            "%d older image(s) in the request history dropped — /v1 carries "
            "one image per turn, the most recent one",
            older_images,
        )
    last_user = next(
        (m for m in reversed(ctx.body.messages) if m.role == "user"), None
    )
    ctx.message = (last_user.content if last_user else None) or ""


def _engine_prefix(engine: Optional[str]) -> str:
    """The SSE id prefix the three forwarders already use."""
    name = (engine or "").lower().replace(".", "").replace("_", "")
    if "llamacpp" in name:
        return "llamacpp"
    if name == "mlx":
        return "mlx"
    return "ollama"


def _served_model(ctx: TurnContext) -> str:
    return ctx.usage.get("served_model") or ctx.engine or "nexe"


def _end_of(chunk: Any) -> Optional[dict]:
    """The engine's closing sentinel, if this chunk is one."""
    if isinstance(chunk, dict):
        end = chunk.get(NEXE_END)
        if isinstance(end, dict):
            return end
    return None


def _raw_of(chunk: Any) -> str:
    """The answer text inside one SSE chunk, before `SseCleaner` touches it.

    Facts live in that text. Accumulating the cleaned chunk would drop them
    before `postprocess` can read them, which is the hole C4.6-b closes.
    """
    text = chunk.decode("utf-8") if isinstance(chunk, (bytes, bytearray)) else chunk
    if not isinstance(text, str):
        return ""
    parts: list[str] = []
    for event in text.split("\n\n"):
        event = event.strip()
        if not event.startswith("data:"):
            continue
        payload = event[len("data:"):].strip()
        if payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
            delta = (obj.get("choices") or [{}])[0].get("delta") or {}
        except (ValueError, IndexError, AttributeError, TypeError):
            continue
        content = delta.get("content")
        if isinstance(content, str):
            parts.append(content)
    return "".join(parts)


def _note_end(ctx: TurnContext, end: dict) -> None:
    """Remember why the engine stopped. A failure after tokens is a partial."""
    ctx.usage["stream_end"] = end
    failure = end.get("failure")
    if not failure:
        return
    ctx.partial = True
    ctx.error = {"step": "generate", "class": "engine", "message": str(failure)}


def _memory_fields(ctx: TurnContext) -> dict:
    """The three names the JSON body already uses, for the last SSE chunk."""
    fields: dict = {}
    saved = ctx.usage.get("memory_saved") or 0
    if saved:
        fields["nexe_memory_saved"] = saved
    kept = ctx.usage.get("memory_kept") or []
    if kept:
        fields["nexe_memory_facts"] = list(kept)
    pending = ctx.usage.get("pending_delete") or ""
    if pending:
        fields["nexe_pending_delete"] = pending
    return fields


def _release(ctx: TurnContext) -> None:
    session_mgr = getattr(ctx.app_state, "session_manager", None)
    if session_mgr is not None and ctx.session_id:
        session_mgr.release_lease(ctx.session_id, ctx.turn_id)


async def _open_stream_call(ctx: TurnContext):
    """Gate, deadline, cascade. The slot stays held: the caller releases it
    when the generator ends, including when the client leaves."""
    chat = _chat()
    gate = gate_for(ctx.app_state)
    cancel_event, monitor = start_disconnect_monitor(ctx.request)
    ctx.cancel_token = (cancel_event, monitor)
    deadline_handle = None
    if ctx.deadline:
        deadline_handle = asyncio.get_running_loop().call_later(ctx.deadline, cancel_event.set)

    def stop() -> None:
        if deadline_handle is not None:
            deadline_handle.cancel()
        if not monitor.done():
            monitor.cancel()

    try:
        slot = await gate.acquire(
            Priority.USER_TURN, holder=ctx.turn_id, cancel_event=cancel_event, timeout=_gate_wait_s(),
        )
    except GateBusy:
        stop()
        raise HTTPException(status_code=429, detail="Server busy, try again in a moment")
    ctx.gpu_slot = slot
    started = time.monotonic()
    try:
        image = ctx.attachments.get("image_b64")
        response, served_by, fallback_from, reason, served_model = await chat._dispatch_through_cascade(
            ctx.body, ctx.request, ctx.prompt, ctx.message or None,
            ctx.session_id, ctx.engine, ctx.engine_fallback_from,
            cancel_event=cancel_event,
            images=[image] if image else None,
            resume=ctx.resume,
        )
    except BaseException:
        await gate.release(slot)
        stop()
        raise
    ctx.usage["served_model"] = served_model or ""
    if served_by != ctx.engine:
        ctx.context_window = chat.get_effective_context_window(served_by, ctx.app_state)
    ctx.engine = served_by
    ctx.engine_fallback_from = fallback_from
    ctx.engine_fallback_reason = reason
    return response, served_by, served_model, slot, gate, stop, started


async def _drain_engine(ctx: TurnContext, response: Any, cleaner: SseCleaner):
    """Forward the engine's chunks, keeping the raw answer on `ctx.response`."""
    if not isinstance(response, StreamingResponse):
        ctx.response = _content_of(response)
        return
    async for chunk in response.body_iterator:
        end = _end_of(chunk)
        if end is not None:
            _note_end(ctx, end)
            continue
        ctx.response += _raw_of(chunk)
        for out in cleaner.rewrite(chunk):
            yield out
    for out in cleaner.close():
        yield out


def _text_appended(before: str, after: str) -> str:
    """What `after` added past `before`. Empty when the text was replaced."""
    if not after.startswith(before):
        return ""
    return after[len(before):].strip("\n")


async def _stream_facts_only_reprompt(ctx: TurnContext, facts: list, finished: list):
    """The second ask, as SSE chunks. The finished answer lands in `finished`.

    The cascade sees `stream=False`. The lab's fake still speaks SSE, and
    `_v1_reprompt_call` drains whichever shape comes back. An empty second
    ask yields the neutral stand-in so the client is not left with nothing.
    """
    saved_body = ctx.body
    ctx.body = saved_body.model_copy(update={"stream": False})
    parts: list[str] = []
    try:
        async for chunk in policy.reprompt_chunks(
            ctx, facts, call=_v1_reprompt_call(ctx),
            engine_name=ctx.engine or "", model=_served_model(ctx),
        ):
            parts.append(chunk)
            if chunk:
                yield format_sse_chunk(chunk, _served_model(ctx), _engine_prefix(ctx.engine))
    finally:
        ctx.body = saved_body
    clean = policy.second_answer_text(parts) or policy.empty_reply_text(ctx.lang)
    finished.append(clean)
    if not parts and clean:
        yield format_sse_chunk(clean, _served_model(ctx), _engine_prefix(ctx.engine))


def api_adapters(background_tasks: BackgroundTasks, streaming: bool = False) -> Adapters:
    """The adapter table for one request. Built per request because
    `persist_assistant_turn` needs this request's `BackgroundTasks`.

    `streaming=True` swaps the four steps whose wire shape differs
    (`generate`, `postprocess`, `persist_assistant_turn`, `emit`) for async
    generators, the same split the web door has had since C1. The default
    stays the coroutine table: `run_turn` rejects a generator, and every
    existing caller of this function is a JSON turn.
    """

    async def validate(ctx: TurnContext) -> None:
        chat = _chat()
        # #1081: a message's `content` can be a list of OpenAI content
        # parts (text + inline image) instead of a plain string. Every
        # consumer downstream (mirror, sanitize, memory extraction) expects a
        # string — the UI door has always kept `image_b64` OUT of the message
        # text the same way — so parts are peeled apart HERE, once, and
        # `ctx.body.messages` never carries anything but text again.
        #
        # BEFORE `_validate_chat_request`, not after: that function runs
        # `validate_string_input` over every non-user message, which answers
        # 400 "Input must be a string" for a list. The schema accepts parts
        # on any role, and the OpenAI SDKs really do send a `system` that
        # way — so the door that accepts the shape has to normalise it first.
        _peel_content_parts(ctx)
        if getattr(ctx.body, "resume", False) is True and ctx.attachments.get("image_b64"):
            # The web door's rule: a Continue does not take a new attachment.
            # The image, if the history carried one, is already on the session
            # at that door. Here the request IS the history, so an image part
            # is the attachment and it is refused the same way.
            raise HTTPException(status_code=400, detail="continue does not take an attachment")
        chat._validate_chat_request(ctx.body)
        # C4.1: the shared `validate` (core/turn/validate.py) — including the
        # image check, now that this door can carry one: `attachments` above
        # is what `validate_turn` decodes and size-checks.
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
        if ctx.resume:
            # The language stays the one the cut answer was written in. Detecting
            # it again from the partial would flip the prefix the engine resumes.
            from core.lang_detect import fallback_lang
            remembered = chat._SESSION_LANG.get(ctx.session_id) or {}
            ctx.lang = remembered.get("lang") or fallback_lang()
        else:
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
            # C4.3 (D4): the object was already being asked for and thrown
            # away. Keeping it is what lets an attachment be the SESSION's and
            # not the web door's — `TURN_STEPS` has always said this step
            # writes `session`, and until now only one door did.
            ctx.session = session_mgr.get_or_create_session(ctx.session_id)
            # A resume does not inject the session's document between the cut
            # and the continuation: that text was not part of the prefix.
            if ctx.resume:
                ctx.attachments["document"] = None
                if getattr(ctx.session, "lang", None):
                    ctx.lang = ctx.session.lang
            else:
                ctx.attachments["document"] = ctx.session.get_attached_document()
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
            ctx.body, ctx.app_state, ctx.lang,
            has_document=ctx.attachments.get("document") is not None,
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
        # #1078: `session` already read the attached document into
        # `ctx.attachments` and `recall` already narrowed the collections for
        # it (C4.3-a) — but nobody at this door ever turned the document into
        # text and put it in front of the model. `_build_document_context` is
        # the one place that does that; the UI door's `budget` has called it
        # (via `_build_turn_context`) since C4.3. `context_text` folds it in
        # ahead of whatever `recall` found — narrowing only ever removes
        # `user_knowledge`, so `ctx.recall_text` can still carry
        # nexe_documentation/personal_memory results alongside a document.
        # The SAME block the UI builds, since the framing moved behind the
        # presentation port. Both halves of the old divergence are closed, and
        # the reason each one existed is worth keeping:
        #   * the sentence citing the document was missing here because adding
        #     it meant appending to the user's message, which an
        #     OpenAI-compatible API has no business doing. It does not mean
        #     that any more: the prose travels inside the context turn pair
        #     this door ALREADY inserts, so the client's `messages` array is
        #     still never edited — only added to, as it always was.
        #   * the document used to ride this door's RAG budget with
        #     `document_chars=0`, so a long client history dropped it whole
        #     (#1079, measured: gone at ~30k chars with only a WARNING).
        # A Continue keeps the prefix the answer was cut from: no document
        # and no retrieved text between the cut and the resume. `recall` is
        # already skipped; this is the belt, and the document is not.
        context_text = "" if ctx.resume else ctx.recall_text
        document_chars = 0
        attached_doc = None if ctx.resume else ctx.attachments.get("document")
        if attached_doc:
            from core.turn.assemble import _build_document_context
            document_context, _shown, _total = _build_document_context(
                attached_doc, context_window=ctx.context_window, lang=ctx.lang,
            )
            context_text = document_context + context_text
            # C4.4: how much of this block is the user's own upload. Without
            # it the budget treats the document as more retrieved text and a
            # long client history drops it whole — for turns the window fit
            # was about to drop anyway (see `_trim_rag_context`).
            document_chars = len(document_context)
        ctx.prompt, ctx.recall_text = chat._assemble_v1_messages(
            ctx.body, ctx.system_prompt, context_text, ctx.clock_line,
            ctx.lang, ctx.context_window, document_chars,
            bool(ctx.recall_text), ctx.app_state,
            # #1081: the `validate` step above writes `image_b64` when the
            # client sent content parts, so this is live at this door since
            # this step — the port carried the shape one commit before the door
            # could fill it.
            has_image=bool(ctx.attachments.get("image_b64")),
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
            _image_b64 = ctx.attachments.get("image_b64")
            response, served_by, fallback_from, reason, served_model = await chat._dispatch_through_cascade(
                ctx.body, ctx.request, ctx.prompt, ctx.message or None,
                ctx.session_id, ctx.engine, ctx.engine_fallback_from,
                cancel_event=cancel_event,
                # #1081: same shape as the UI door's `_images_arg`.
                images=[_image_b64] if _image_b64 else None,
                resume=ctx.resume,
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
            if served_by != ctx.engine:
                # C4.4: a fallback engine answered — its window is the turn's
                # now (`context_window` is the SERVING engine's, context.py).
                ctx.context_window = chat.get_effective_context_window(served_by, ctx.app_state)
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
                # C4.4-b: the model's format is cleaned here, on the one seam
                # the three engine forwarders share — /v1 no longer streams
                # <think>, harmony channels or memory tags to its client.
                cleaner = SseCleaner(served_model, keep_reasoning=_wants_reasoning(ctx))

                async def _release_after(inner=inner):
                    try:
                        async for chunk in inner:
                            for out in cleaner.rewrite(chunk):
                                yield out
                        for out in cleaner.close():
                            yield out
                    finally:
                        await gate.release(slot)
                        _stop_cancellation()

                response.body_iterator = _release_after()
        finally:
            if not released:
                await gate.release(slot)
                _stop_cancellation()

    async def persist_assistant_turn(ctx: TurnContext) -> None:
        # JSON only. A stream writes the answer in `persist_stream`, once the
        # text is known — the forwarders no longer persist (C4.6-b).
        _chat()._persist_v1_turn_from_response(
            ctx.wire, background_tasks, ctx.app_state, ctx.session_id,
            resume=ctx.resume,
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
        note_kept(ctx.usage, outcome.mem_saved, outcome.kept_facts)
        ctx.usage["memory_action"] = outcome.memory_action
        if outcome.pending_delete_fact is not None:
            # C4.5: the entry a typed "oblida" left pending, in this door's
            # alphabet (nexe_pending_delete / X-Nexe-Pending-Delete) — the same
            # field a model's [MEM_DELETE:] fills at `postprocess`.
            ctx.usage["pending_delete"] = outcome.pending_delete_fact
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

        C4.4: the JSON reply is cleaned with the core's one cleaner first
        (<think>, harmony, <|…|>) — the web door's. A stream is the other
        table (`postprocess_stream`, C4.6-b): its facts are read from the raw
        text in the same turn. This coroutine only sees dicts.
        """
        if not isinstance(ctx.wire, dict):
            # A stream is the other table (`streaming=True`). This one only
            # sees dicts; writing the old C4.6 degradation here would keep a
            # limit the stream walk has closed.
            ctx.response = ctx.response or ""
            ctx.facts = []
            return
        try:
            message = ctx.wire["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            return
        # ADR-010: reasoning a model still wrote INTO the text joins the
        # reasoning the engine already set apart; the client keeps it only if
        # it asked. The answer goes through the one cleaner, as in C4.4.
        inline_reasoning, content = split_text(message.get("content") or "")
        reasoning = (message.get("reasoning") or "") + inline_reasoning
        if reasoning and _wants_reasoning(ctx):
            message["reasoning"] = reasoning
        else:
            message.pop("reasoning", None)
        clean, facts, deletes = clean_full_response(content, user_input=ctx.message)
        if deletes:
            clean = await _arm_pending_delete(ctx, deletes, clean)
        if not clean and facts and not ctx.resume:
            clean = await _second_reply(ctx, facts)
        message["content"] = clean
        ctx.response = clean
        ctx.facts = facts

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
        # 25/09: inline, before `emit` — this turn's own note (#1098).
        note_kept(ctx.usage, outcome.saved, outcome.kept)

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

    async def generate_stream(ctx: TurnContext):
        """The engine call, as a generator. The first yield is the assistant
        role, once the cascade has accepted an engine — a reasoning-first
        model does not hold the headers until the answer starts. I8's time is
        the whole generation, not the wait for that first token."""
        ctx.response = ""
        response, served_by, served_model, slot, gate, stop, started = await _open_stream_call(ctx)
        try:
            yield format_sse_role(served_model or served_by, _engine_prefix(served_by))
            cleaner = SseCleaner(served_model, keep_reasoning=_wants_reasoning(ctx))
            async for out in _drain_engine(ctx, response, cleaner):
                yield out
            record_llm_call(
                ctx, step="generate", engine=served_by, model=served_model or "",
                ms=(time.monotonic() - started) * 1000.0,
            )
        finally:
            await gate.release(slot)
            stop()

    async def postprocess_stream(ctx: TurnContext):
        """Clean the raw answer, arm a delete, and ask again when the reply
        was only memory tags. A partial turn is cleaned and not asked again."""
        clean, facts, deletes = clean_full_response(ctx.response or "", user_input=ctx.message)
        if not ctx.partial and deletes:
            before = clean
            clean = await _arm_pending_delete(ctx, deletes, clean)
            extra = _text_appended(before, clean)
            if extra:
                yield format_sse_chunk(extra, _served_model(ctx), _engine_prefix(ctx.engine))
        if not ctx.resume and not ctx.partial and not clean and facts:
            finished: list[str] = []
            async for sse in _stream_facts_only_reprompt(ctx, facts, finished):
                yield sse
            if finished:
                clean = finished[0]
        ctx.response = clean
        ctx.facts = facts

    async def persist_stream(ctx: TurnContext) -> None:
        """The answer is known here, so it is written now. A disconnect
        (`generate` cancelled) is a partial and lets the lease go, because
        `emit` will not run. An engine error keeps the lease until `[DONE]`."""
        text = ctx.response or ""
        cancelled = ctx.outcomes.get("generate") == "cancelled"
        if str(text).strip():
            end = ctx.usage.get("stream_end") or {}
            persist_v1_turn(
                ctx.app_state, ctx.session_id, text,
                partial=bool(ctx.partial) or cancelled,
                resume=ctx.resume,
                truncated=end.get("finish_reason") == "length",
            )
        if cancelled:
            _release(ctx)

    async def emit_stream(ctx: TurnContext):
        """The final chunk, then `[DONE]`, then the lease. A memory command
        never ran `generate`, so its text leaves from here, as SSE."""
        # `skipped`: a memory command answered before `generate`, so this is
        # the first thing on the wire. `ok` and `degraded` already yielded
        # the role from `generate`.
        if ctx.outcomes.get("generate") == "skipped":
            model = getattr(ctx.body, "model", None) or "nexe-memory"
            prefix = "nexe"
            yield format_sse_role(model, prefix)
            if ctx.response:
                yield format_sse_chunk(ctx.response, model, prefix)
        else:
            model = _served_model(ctx)
            prefix = _engine_prefix(ctx.engine)
        end = ctx.usage.get("stream_end") or {}
        yield format_sse_done(
            model, prefix,
            truncated=bool(end.get("truncated")),
            finish_reason=end.get("finish_reason"),
            fields=_memory_fields(ctx),
        )
        yield SSE_DONE
        _release(ctx)

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
        # JSON: the lease ends here, with the body. A stream releases in
        # `emit_stream`, after `[DONE]` (C4.6-b).
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
        "generate": generate_stream if streaming else generate,
        "postprocess": postprocess_stream if streaming else postprocess,
        "persist_assistant_turn": persist_stream if streaming else persist_assistant_turn,
        "emit": emit_stream if streaming else emit,
        "memory.write": memory_write,
        "compact": compact,
    }
