"""
------------------------------------
Server Nexe
Location: plugins/web_ui_module/api/routes_chat.py
Description: POST /chat endpoint: the web door's alphabet (sentinels,
             localized errors) and the route that walks TURN_STEPS.
             Extracted from routes.py during tech debt refactoring.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

from typing import Dict, Any
from dataclasses import dataclass
import asyncio
import inspect
import logging
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Depends, Request as FastAPIRequest
from fastapi.responses import StreamingResponse
from core.dependencies import limiter
# The adapters (`turn_adapters.py`) reach these three through this module, at
# call time — which is where the web door's tests patch them.
from core.turn.cancel import start_disconnect_monitor as _start_disconnect_monitor  # noqa: F401
from core.turn.assemble import _assemble_engine_messages, _build_turn_context  # noqa: F401
from core.turn.context import TurnContext
from core.turn.lease import release_turn_lease, releasing
from core.turn.post_commit import queue_for
from core.turn.run import run_turn, stream_turn
from plugins.web_ui_module.api.turn_adapters import ui_adapters

from core.context_budget import (  # noqa: F401 — re-exported for tests and callers
    compute_context_budget,
    _inject_context_into_messages,
)
from core.memory_facts import intents as memory_intents
from core.endpoints.chat_engines._common import extract_engine_text as _engine_text
from plugins.web_ui_module.core.latex_sanitizer import LatexStreamBuffer, latex_to_unicode
from core.turn.errors import StreamCapExceeded, is_oom_error
from core.turn.stream import (
    Delta, Failed, Ready, StreamFlags, StreamGuard, Whole, close_quietly, engine_events,
)

logger = logging.getLogger(__name__)


# ─── Bug 17 — Hardened MEM_SAVE extractor ────────────────────────────────────
# The strict format we accept is: [MEM_SAVE: <text>]
# - <text> must be between 5 and MEM_SAVE_MAX_LEN characters
# - Must not contain newlines, tabs, brackets ([]), HTML brackets, or control chars
# - Only letters (including accents/cyrillic), digits, spaces, and safe punctuation
# - Explicitly rejected: <, >, [, ], {, }, |, `, \x00-\x1f
# - Nested MEM_SAVE rejected (one MEM_SAVE inside another)

def _build_mem_stats(
    session: Any,
    rag_count: int,
    rag_items: list,
    model_name: "str | None",
    elapsed: float,
    full_response_len: int,
    mem_saved_count: int,
    mem_saves: list,
) -> dict:
    """Build the stats dict for session.add_message."""
    est_tokens = max(1, full_response_len // 4)
    rag_avg_val = None
    if rag_count > 0 and rag_items:
        rag_avg_val = round(sum(s for _, s in rag_items) / len(rag_items), 2)
    saved_facts = [f.strip() for f in mem_saves if f.strip() and len(f.strip()) >= 5] if mem_saved_count > 0 else None
    saved_rag_items = [[str(c)[:30], round(s, 2)] for c, s in rag_items] if rag_items else None
    return {
        "tokens": est_tokens,
        "elapsed": elapsed,
        "model": str(model_name)[:100] if model_name else None,
        "rag_count": rag_count if rag_count > 0 else None,
        "rag_avg": rag_avg_val,
        "rag_items": saved_rag_items,
        "mem_saved": mem_saved_count if mem_saved_count > 0 else None,
        "mem_facts": saved_facts,
    }


async def _yield_response_headers(
    model_name: str,
    rag_count: int,
    rag_items: list,
    compacted: bool,
    compaction_count: int,
    doc_truncated_pct: int,
):
    """Yield the header tokens: MODEL, RAG*, COMPACT, DOC_TRUNCATED."""
    _safe_model = str(model_name).replace("\x00", "").replace("]", "")[:100]
    yield f"\x00[MODEL:{_safe_model}]\x00"
    if rag_count > 0:
        yield f"\x00[RAG:{int(rag_count)}]\x00"
        if rag_items:
            avg_score = sum(s for _, s in rag_items) / len(rag_items)
            yield f"\x00[RAG_AVG:{avg_score:.2f}]\x00"
            for _col, _score in rag_items:
                _safe_col = str(_col).replace("\x00", "").replace("|", "_")[:30]
                yield f"\x00[RAG_ITEM:{_safe_col}|{_score:.2f}]\x00"
    if compacted:
        yield f"\x00[COMPACT:{int(compaction_count)}]\x00"
    if doc_truncated_pct > 0:
        yield f"\x00[DOC_TRUNCATED:{doc_truncated_pct}]\x00"


def render_intent_for_ui(outcome: "memory_intents.IntentOutcome") -> str:
    """The web UI's alphabet for a memory command: the core answered with data,
    this adds the sentinels `nexe-chat.js` reads. The core stays wire-agnostic
    (ADR-007 C3.1); /v1 renders the same outcome as plain text plus headers."""
    rendered = f"\x00[MODEL:nexe-system]\x00{outcome.text}"
    if outcome.deleted_facts:
        facts_pipe = "|".join(f[:80] for f in outcome.deleted_facts[:5])
        rendered += f"\x00[DEL:{outcome.mem_deleted}:{facts_pipe}]\x00"
    if outcome.pending_delete_fact is not None:
        # PENDING_DELETE marker: the web UI shows its confirmation dialog. Text
        # confirmation ("si") works in parallel via session._pending_partial_delete.
        rendered += pending_delete_sentinel(outcome.pending_delete_fact)
    return rendered


def pending_delete_sentinel(fact: str) -> str:
    """The web UI's token for "confirm this forget?": `nexe-chat.js` opens its
    dialog on it and the CLI asks (`_report_memory`). Since C4.5 it carries the
    ENTRY's text on both wire shapes (the JSON path did; the stream carried the
    model's phrase), because that text is what the dialog sends back to
    `/ui/memory/confirm-delete` as the confirmed reference (B093)."""
    safe = (fact or "").replace("\x00", "").replace("|", "\\|")[:200]
    return f"\x00[PENDING_DELETE:{safe}]\x00"


@dataclass
class RepromptSetup:
    """This door's way of asking its engine once more — `policy.reprompt_chunks`'s
    `call` (C4.5): what `generate` had in hand when the engine started, kept as
    DATA so two turns that differ only in `ctx.entry` compare equal (the I1
    contract test reads the door's scratch). Ollama-shaped engines only, as it
    has always been: MLX and llama.cpp run through a queue and a worker thread
    (`_start_engine_call`) that was never wired for a second call. Returning
    None for them lets the core SAY it skipped, where `_yield_reprompt` used to
    skip in silence."""
    engine: Any
    sig: Any
    model_name: "str | None"
    messages: list
    thinking_enabled: bool

    def __call__(self, system_prompt: str):
        if "model" not in self.sig.parameters:
            return None
        full = [{"role": "system", "content": system_prompt}] + list(self.messages)
        return self.engine.chat(
            model=self.model_name, messages=full, stream=True, thinking_enabled=self.thinking_enabled,
        )


def reprompt_call_for(engine, sig, model_name, messages: list, thinking_enabled: bool) -> RepromptSetup:
    return RepromptSetup(engine, sig, model_name, messages, thinking_enabled)


async def _yield_model_loading_check(engine, model_name: str, engine_name: str):
    """Yield a MODEL_LOADING token if the engine reports the model is not yet loaded."""
    if not hasattr(engine, 'is_model_loaded'):
        return
    _safe_model = str(model_name).replace("\x00", "").replace("]", "")[:100]
    try:
        loaded = await engine.is_model_loaded(model_name)
        if not loaded:
            logger.info("Model %s not loaded — loading... [%s]", model_name, engine_name)
            yield f"\x00[MODEL_LOADING:{_safe_model}|{engine_name}]\x00"
    except Exception as e:
        logger.debug("Model loaded check failed for %s: %s", model_name, e)


def _json_chunk_text(chunk) -> "str | None":
    """The text of one chunk of a JSON-mode reply, whatever the engine's shape."""
    if isinstance(chunk, dict) and "message" in chunk and "content" in chunk["message"]:
        return chunk["message"]["content"]
    if isinstance(chunk, dict) and "content" in chunk:
        return chunk["content"]
    if isinstance(chunk, str):
        return chunk
    return None


async def _accumulate_nonstreaming_response(chat_result, response_chunks: list) -> bool:
    """Accumulate chunks from a non-streaming chat_result into response_chunks.

    #1039: through the core's `StreamGuard`, like the streaming shape — no
    control characters, and a reply that grows past `NEXE_MAX_STREAM_MB` stops
    there. Returns True when it did: the text so far is kept, and the caller
    ends the turn partial and stops the engine's worker.
    """
    guard = StreamGuard()
    try:
        if inspect.isasyncgen(chat_result) or hasattr(chat_result, '__aiter__'):
            async for chunk in chat_result:
                text = _json_chunk_text(chunk)
                if text is not None:
                    response_chunks.append(guard.take(text, "")[0])
        else:
            result = await chat_result if inspect.iscoroutine(chat_result) else chat_result
            content = _engine_text(result)
            if content:
                response_chunks.append(guard.take(content, "")[0])
    except StreamCapExceeded:
        await close_quietly(chat_result)
        return True
    return False


@dataclass
class StreamingChatContext:
    """Request-scoped state of one streamed answer (MC-027 F2), built by the
    `generate` adapter and read by the steps after it.

    `session`, `messages` and `memory_helper` are LIVE references (mutated in place,
    never copied); `disconnect_monitor_task` is the live asyncio.Task the turn's
    `generate` step started (INV-CRIT-01/02/06).
    """
    model_name: "str | None"
    rag_count: int
    rag_items: list
    compacted: bool
    doc_truncated_pct: int
    session: Any
    session_mgr: Any
    memory_helper: Any
    engine: Any
    engine_name: str
    chat_result: Any
    sig: Any
    system_prompt: str
    messages: list
    thinking_enabled: bool
    lang: "str | None"
    message: str
    disconnect_monitor_task: "asyncio.Task"
    # UI collection toggles for this request; None = all collections enabled
    # (old clients / bare API calls). Gates MEM_SAVE persistence.
    rag_collections: "list | None" = None


def _oom_notice(err_msg: str, lang: str) -> str:
    """Curated out-of-memory notice for the chat body, by originating engine.

    The MLX pre-load guard already raises a message telling the user to switch
    engines, but the streaming handler used to replace every OOM with a generic
    "close other applications" — and since the UI always streams, that advice
    never reached anyone. It is restored here, gated on the failure actually
    coming from MLX: this branch also catches OOM raised by other engines, and
    telling a user who is already on Ollama to switch to Ollama is nonsense.

    MC-133 still holds: the text is curated per language and never echoes the
    raw exception, which can carry internal paths or state.
    """
    mlx_specific = {
        "ca": "Memòria insuficient per carregar el model amb MLX. Canvia el motor a Ollama (fa servir molta menys memòria) o tanca altres aplicacions i torna-ho a provar.",
        "es": "Memoria insuficiente para cargar el modelo con MLX. Cambia el motor a Ollama (usa mucha menos memoria) o cierra otras aplicaciones e inténtalo de nuevo.",
        "en": "Not enough memory to load the model with MLX. Switch the engine to Ollama (it uses far less memory) or close other applications and try again.",
    }
    generic = {
        "ca": "Memòria insuficient. Tanca altres aplicacions per alliberar memòria i torna-ho a provar.",
        "es": "Memoria insuficiente. Cierra otras aplicaciones para liberar memoria e inténtalo de nuevo.",
        "en": "Not enough memory. Close other applications to free up memory and try again.",
    }
    table = mlx_specific if "MLX" in (err_msg or "") else generic
    return table.get(lang, table["en"])


def _stream_error_notice(exc: Exception, lang: "str | None") -> str:
    """Chat-body text for an exception raised mid-generation (MC-133).

    Logs the full detail (with traceback) locally and returns ONLY the curated,
    localized notice: the raw exception text can carry internal paths or state
    and must never reach the wire. OOM keeps its own message (`_oom_notice`).
    """
    err_msg = repr(exc) if not str(exc) else str(exc)
    # MC-133: the full detail (with traceback) belongs in the local log,
    # never in the chat body. exc_info=True keeps diagnostics; the user
    # sees a curated message below.
    logger.error("Streaming error: %s", err_msg, exc_info=True)
    _lk = lang[:2] if lang else "ca"
    if is_oom_error(err_msg):
        return f"\n⚠️ {_oom_notice(err_msg, _lk)}"
    # MC-133: do not echo the raw exception text (err_msg) — it can
    # carry internal paths/state. Surface a generic, localized notice.
    _err = {
        "ca": "S'ha produït un error en generar la resposta. Torna-ho a provar.",
        "es": "Se ha producido un error al generar la respuesta. Inténtalo de nuevo.",
        "en": "An error occurred while generating the response. Please try again.",
    }
    return f"\n⚠️ {_err.get(_lk, _err['en'])}"


def _gen_truncated_token(
    trunc: bool, trunc_continuable: bool, clean_response: str
) -> "str | None":
    """FD-S5 marker for an answer cut by the token ceiling, or None.

    A silent cut mid-sentence reads as the model going mute. The caller emits
    this as its OWN yield (a marker split across reads would not be parsed).
    Degrades to :0 (informative, no Continue) when the visible text is empty or
    the think-only placeholder — there is nothing to resume.
    """
    if not trunc:
        return None
    _cont_flag = 1 if (
        trunc_continuable and clean_response and clean_response != "…"
    ) else 0
    return f"\x00[GEN_TRUNCATED:{_cont_flag}]\x00"


async def claim_engine_start(chat_result, model_name: "str | None", flags: StreamFlags):
    """The engine's first event, or the exception that arrived before any byte.

    A streaming turn used to treat "the generator object exists" as the engine
    having started, yield the headers, and only then pull a chunk. llama.cpp
    refusing an image on a Continue, and Ollama answering 404 for a model,
    both happen on that first pull — the client already had a stream, and the
    next engine was never asked. `/v1` reads one byte before the response
    exists so the cascade can still move. This is that peek for the web door.
    Once a real event has arrived, this engine owns the stream.
    """
    events = engine_events(
        chat_result, model_name, flags, visible_buffer=LatexStreamBuffer(),
    )
    try:
        first = await events.__anext__()
    except StopAsyncIteration:
        await events.aclose()
        raise RuntimeError("engine ended before its first event")
    if isinstance(first, Failed):
        await events.aclose()
        raise first.exc
    return events, first


async def _event_source(ctx: "StreamingChatContext", flags: StreamFlags, primed):
    """Events already opened by `claim_engine_start`, or a fresh stream."""
    if primed is None:
        async for ev in engine_events(
            ctx.chat_result, ctx.model_name, flags, visible_buffer=LatexStreamBuffer(),
        ):
            yield ev
        return
    events, first = primed
    yield first
    async for ev in events:
        yield ev


async def _yield_engine_chunks(ctx: "StreamingChatContext", flags: StreamFlags, primed=None):
    """The engine's events in this door's alphabet: `(wire_token, full_delta)`.

    C4.4: the loop is the core's (`core.turn.stream.engine_events`); what is
    left here is the web door's presentation — the MODEL_READY sentinel, the
    LaTeX buffer, the localized error notice. The caller owns `full_response`:
    a pair whose token is None is accumulation only, and it comes before the
    wire tokens of its chunk, so a disconnect leaves the partial text where
    MC-116 expects it.

    `primed` is `(events, first)` from `claim_engine_start`: the cascade has
    already pulled the first event, and the same parser has to finish the turn.
    """
    async for ev in _event_source(ctx, flags, primed):
        if isinstance(ev, Ready):
            yield "\x00[MODEL_READY]\x00", ""
        elif isinstance(ev, Delta):
            yield None, ev.full
            for _tok in ev.wire:
                yield _tok, ""
        elif isinstance(ev, Whole):
            yield latex_to_unicode(ev.text), ev.text
        elif isinstance(ev, Failed):
            yield _stream_error_notice(ev.exc, ctx.lang), ""


def _start_engine_call(
    engine, engine_name: str, sig, model_name, system_prompt: str, messages: list, *,
    stream: bool, image_b64, thinking_enabled: bool, cancel_event, sampling_kwargs: dict,
    session_id: str, _continue: bool,
):
    """Start the engine's generation and return its `chat_result` (a dict, a
    coroutine or an async generator, depending on the engine's shape).

    Three shapes: Ollama-style `chat(model, messages, stream=…)`, the in-process
    engines (MLX, llama.cpp) driven through a queue + background task, and the
    generic `chat(messages, system=…)`. Extracted verbatim out of the old engine
    handler on 2026-09-06 (ADR-007 C1.3); since C4.6 the turn adapters are its
    only caller. `_continue` is the turn's `resume` (FD-S6). The `engine` step
    already drops a module that does not declare `can_continue`; both in-process
    engines that reach this branch (MLX and llama.cpp) honour `continue_final`.
    """
    # Ollama/MLX/LlamaCpp expect base64 strings, not bytes
    _images_arg = [image_b64] if image_b64 else None

    # cancel_event covers the in-process engines (MLX and
    # llama.cpp): both run a synchronous generation loop in a
    # worker thread that won't notice an HTTP disconnect on its
    # own, so the handler sets the event and the loop breaks
    # early instead of running to max_tokens (orphan worker
    # blocking the model — MC-011). Ollama cancels naturally via
    # its httpx async transport when the asyncio task is
    # cancelled, so it doesn't need the event.
    cancel_kwargs = (
        {"cancel_event": cancel_event}
        if engine_name in ("mlx", "llama_cpp")
        else {}
    )

    if 'model' in sig.parameters:
        # Ollama-style: chat(model, messages, stream=...)
        # We inject system prompt as first message for Ollama.
        # C4.6-a2: resume only when the engine declares `continue_final`.
        # One that does not would ignore the flag and start a new answer.
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        continue_kwargs = (
            {"continue_final": True}
            if _continue and "continue_final" in sig.parameters
            else {}
        )
        chat_result = engine.chat(model=model_name, messages=full_messages, stream=stream,
                                  images=_images_arg,
                                  thinking_enabled=thinking_enabled,
                                  **continue_kwargs, **cancel_kwargs, **sampling_kwargs)
    else:
        # MLX/LlamaCpp-style: chat(messages, system=...)
        if engine_name in ("mlx", "llama_cpp"):
            # MLX module requires a callback for streaming
            queue: asyncio.Queue = asyncio.Queue()

            _stream_chunk_count = [0]

            # B023: `stream_cb` and `queue_generator` below outlive the
            # iteration that built them — the engine task keeps
            # running while the cascade may already be on the next
            # engine, and a free name would then read THAT engine's
            # queue. The defaults pin each closure to the objects of
            # its own turn; the bodies are untouched on purpose (hot
            # streaming path).
            def stream_cb(token, *, _stream_chunk_count=_stream_chunk_count, queue=queue):
                # MLXChatNode already marshals this to the main loop, so we can just put in queue
                _stream_chunk_count[0] += 1
                if _stream_chunk_count[0] <= 3 or _stream_chunk_count[0] % 50 == 0:
                    logger.debug("stream_cb: chunk #%d (%d chars)", _stream_chunk_count[0], len(token))
                queue.put_nowait(token)

            # #1107: llama.cpp honours continue_final the same way MLX does.
            # An engine that arrived here without that support would ignore
            # the flag and start a new answer, so the raise stays for anyone
            # else that joins this branch.
            _continue_kwargs = {}
            if _continue:
                if engine_name not in ("mlx", "llama_cpp"):
                    raise ValueError(
                        "continue is only supported on the MLX and llama.cpp engines"
                    )
                _continue_kwargs = {"continue_final": True}
            # Launch chat in background task
            # B007 (1b): session_id scopes the prefix-cache key —
            # without it every conversation shares ":default".
            ml_task = asyncio.create_task(engine.chat(
                messages=messages, system=system_prompt, stream_callback=stream_cb,
                session_id=session_id,
                images=_images_arg, thinking_enabled=thinking_enabled,
                **_continue_kwargs, **cancel_kwargs, **sampling_kwargs,
            ))

            # Async generator that yields from queue until task is done
            async def queue_generator(*, queue=queue, ml_task=ml_task):
                while True:
                    # Check if queue has items first
                    if not queue.empty():
                        yield await queue.get()
                        continue

                    # If queue is empty, check if task is done
                    if ml_task.done():
                        # If task failed, re-raise exception
                        _exc = ml_task.exception()
                        if _exc is not None:
                            raise _exc
                        # FD-S5: the engine's result dict was
                        # discarded here — finish_reason died
                        # with it. Surface the truncation as
                        # an in-band sentinel. Defensive
                        # isinstance: llama_cpp shares this
                        # branch with its own result shape.
                        _res = ml_task.result()
                        if (
                            isinstance(_res, dict)
                            and _res.get("finish_reason") == "length"
                        ):
                            yield {
                                "__nexe_trunc__": True,
                                "continuable": bool(_res.get("continuable")),
                            }
                        break

                    # Wait for new tokens with short timeout
                    try:
                        token = await asyncio.wait_for(queue.get(), timeout=0.05)
                        yield token
                    except asyncio.TimeoutError:
                        continue

            chat_result = queue_generator()

        else:
            # Generic engine: only pass session_id if accepted.
            _sid_kwargs = (
                {"session_id": session_id}
                if "session_id" in sig.parameters else {}
            )
            chat_result = engine.chat(messages=messages, system=system_prompt,
                                      images=_images_arg,
                                      thinking_enabled=thinking_enabled,
                                      **_sid_kwargs,
                                      **cancel_kwargs, **sampling_kwargs)

    return chat_result


def register_chat_routes(router: APIRouter, *, session_mgr, require_ui_auth):
    """Registers endpoint: POST /chat"""

    # P0-3's lock around body.model singleton mutations now lives with the
    # switch it guards (core.endpoints.chat_engines.model_switch), because what
    # it protects — LlamaCppChatNode._pool / MLXChatNode._model — is
    # process-global while this function runs once per router. Its reasoning is
    # unchanged and is written there: server-nexe is architecturally mono-user
    # (workers=1, class-level singletons), so the race is a breadcrumb for a
    # future multi-user design rather than something seen in the field.

    # -- POST /chat --
    #    ~550 lines: intent detection, RAG, compaction,
    #    multi-engine, streaming

    @router.post("/chat", operation_id="webui_chat")
    @limiter.limit("20/minute")
    async def chat(request: FastAPIRequest, body: Dict[str, Any], _auth=Depends(require_ui_auth)):
        """Chat endpoint with streaming and memory intent detection.

        Concurrency is the engine gate's job now (ADR-007 §7, C2.1,
        core/turn/gate.py) — held by `generate_stream`/`generate_json` for as
        long as their body is being driven, not by this route for as long as
        it takes to get a `StreamingResponse` OBJECT back (that used to be the
        whole of the old `Semaphore(2)` here: it released before a single
        token was generated).
        """
        return await _chat_inner(request, body, _auth)

    async def _chat_inner(request: FastAPIRequest, body: Dict[str, Any], _auth):
        """Inner chat logic, called under semaphore."""
        session_id = body.get("session_id")
        # RT-10: clean 400 for malformed/traversal session ids (see routes_files).
        if session_id is not None and not session_mgr.is_valid_session_id(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id")
        stream = body.get("stream", False)

        # ADR-007 (C1.3): from here on this door no longer decides the order of
        # the turn. It builds a TurnContext and lets the engine walk TURN_STEPS;
        # every step is an adapter in `turn_adapters.py` wrapping the functions
        # this body used to call. Two tables, one per wire format, because four
        # steps really differ between them. C4.6: FD-S6's Continue is a turn
        # too — `resume` tells the steps; it no longer has a path of its own.
        ctx = TurnContext(
            turn_id=uuid4().hex,
            entry="ui",
            # C4.1 (#1044): WHO `require_ui_auth` authenticated, recorded on the
            # request by `auth_dependencies._remember_principal`. This door was
            # already fail-closed, so the turn's `authorize` step never fires
            # here — it is filled so there is ONE step, not a step and an
            # exception for the door that happened to be right.
            principal=getattr(getattr(request, "state", None), "principal", None),
            streaming=bool(stream),
            resume=body.get("continue") is True,
            body=body,
            request=request,
            app_state=request.app.state,
        )
        return await _walk_turn(ctx, bool(stream))

    async def _walk_turn(ctx: TurnContext, stream: bool):
        """The turn, walked through `TURN_STEPS` in this door's wire shape.

        #1105: a turn that fails after `session` gives the lease back — before
        this, only `emit`, the disconnect path and a short-circuit did, and the
        next message of the conversation got the 409 for the lease's whole TTL.
        In streaming the failure can come after the response is committed
        (`generate` runs inside the body), hence the wrapper on the body too.
        """
        adapters = ui_adapters(session_mgr, streaming=stream)
        # C2.2: memory.write/compact go to the post-commit queue when a real
        # one is attached (production always has one — the lifespan attaches
        # it next to the engine gate); None here makes them run inline,
        # exactly as before C2.2 — the fallback pre-C2.2 test harnesses need.
        post_commit = queue_for(ctx.app_state)
        try:
            if stream:
                body_iterator = await stream_turn(ctx, adapters, post_commit=post_commit)
            else:
                await run_turn(ctx, adapters, post_commit=post_commit)
        except BaseException:
            release_turn_lease(session_mgr, ctx)
            raise
        if stream:
            return StreamingResponse(
                releasing(body_iterator, session_mgr, ctx),
                media_type="text/plain",
                headers={
                    "Cache-Control": "no-cache, no-store",
                    "X-Accel-Buffering": "no",
                    "X-Content-Type-Options": "nosniff",
                    # The session this turn was stored in: a client that lost
                    # its id (or never learned the one the server minted for
                    # it) has a way back instead of starting a new conversation.
                    "X-Session-Id": ctx.session.id,
                    # C2.0: one id to grep for in `turn.trace` log lines.
                    "X-Nexe-Turn-Id": ctx.turn_id,
                },
            )
        return ctx.wire
