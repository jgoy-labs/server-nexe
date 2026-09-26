"""
------------------------------------
Server Nexe
Location: plugins/web_ui_module/api/routes_chat.py
Description: POST /chat endpoint (~500 lines).
             Intent detection, RAG, compaction, multi-engine, streaming.
             Extracted from routes.py during tech debt refactoring.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass
import asyncio
import inspect
import logging
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Depends, Request as FastAPIRequest
from fastapi.responses import StreamingResponse
from core.dependencies import limiter
from core.turn.cancel import start_disconnect_monitor as _start_disconnect_monitor
from core.turn.context import TurnContext
from core.turn.post_commit import queue_for
from core.turn.run import run_turn, stream_turn
from core.turn.validate import parse_top_p
from plugins.web_ui_module.api.turn_adapters import ui_adapters

# C4.2: the prompt is assembled in the core now. The `continue` path below
# (FD-S6, decision §5 of the C1 plan) does not walk the turn map and calls
# these three itself; every other turn reaches them through the adapters.
from core.turn.assemble import _assemble_engine_messages, _build_turn_context
from core.turn.prompt import _build_turn_system_prompt

from core.chat_prompt import time_context_line
from core.context_budget import (  # noqa: F401 — re-exported for tests and callers
    compute_context_budget,
    _inject_context_into_messages,
)
import core.memory_facts as memory_facts
from core.memory_facts import intents as memory_intents
from core.memory_facts import deletes as memory_deletes
from core.memory_facts.write import will_write, write_facts
import core.turn.policy as policy
from core.endpoints.chat_engines._common import extract_engine_text as _engine_text
from plugins.web_ui_module.core.latex_sanitizer import LatexStreamBuffer, latex_to_unicode
# C4.4: the model's text format is the core's; this door keeps its alphabet.
from core.turn.text import clean as text_clean
from core.turn.errors import is_oom_error
from core.turn.persist import persist_assistant_turn, persist_partial_assistant
from core.turn.stream import Delta, Failed, Ready, StreamFlags, Whole, engine_events

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


async def _accumulate_nonstreaming_response(chat_result, response_chunks: list) -> None:
    """Accumulate chunks from a non-streaming chat_result into response_chunks."""
    if inspect.isasyncgen(chat_result) or hasattr(chat_result, '__aiter__'):
        async for chunk in chat_result:
            if isinstance(chunk, dict) and "message" in chunk and "content" in chunk["message"]:
                response_chunks.append(chunk["message"]["content"])
            elif isinstance(chunk, dict) and "content" in chunk:
                response_chunks.append(chunk["content"])
            elif isinstance(chunk, str):
                response_chunks.append(chunk)
    else:
        result = await chat_result if inspect.iscoroutine(chat_result) else chat_result
        content = _engine_text(result)
        if content:
            response_chunks.append(content)


@dataclass
class StreamingChatContext:
    """Request-scoped state for `_generate_streaming_response` (MC-027 F2).

    Carries the ~18 values the streaming body used to capture as closure free-vars.
    `session`, `messages` and `memory_helper` are LIVE references (mutated in place,
    never copied); `session_mgr` comes from the `register_chat_routes` factory scope,
    NOT a module global; `disconnect_monitor_task` is the live asyncio.Task whose
    ownership `_handle_chat_engine` hands off to the generator (INV-CRIT-01/02/06).
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
    # FD-S6: this stream RESUMES the session's last assistant message — the
    # tail must MERGE into it (never add_message: get_context_messages
    # dedupes consecutive roles keeping only the latest, which would erase
    # the first half of the answer).
    continue_mode: bool = False
    # C4.5: the `TurnContext` the core policy reads (gate, I8, language). The
    # adapters have the real one; the `continue` path, which never walks the
    # turn map, hands a bare one built in `_handle_chat_engine` (dies at C4.6).
    turn: Any = None


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


async def _yield_engine_chunks(ctx: "StreamingChatContext", flags: StreamFlags):
    """The engine's events in this door's alphabet: `(wire_token, full_delta)`.

    C4.4: the loop is the core's (`core.turn.stream.engine_events`); what is
    left here is the web door's presentation — the MODEL_READY sentinel, the
    LaTeX buffer, the localized error notice. The caller owns `full_response`:
    a pair whose token is None is accumulation only, and it comes before the
    wire tokens of its chunk, so a disconnect leaves the partial text where
    MC-116 expects it.
    """
    async for ev in engine_events(ctx.chat_result, ctx.model_name, flags,
                                  visible_buffer=LatexStreamBuffer()):
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


async def _arm_and_reprompt(
    ctx: StreamingChatContext, clean_response: str, mem_saves: list, mem_deletes: list, out: list,
):
    """The two moves `postprocess_stream` makes, for the `continue` path (C4.5):
    the core's delete rule and the core's second call. Yields the wire tokens;
    the final clean text is left in `out` (a generator cannot return a value
    while it yields). Dies with the path at C4.6."""
    armed = await memory_deletes.arm_pending_deletes(
        ctx.session, mem_deletes, ctx.memory_helper, ctx.rag_collections,
    )
    if armed is not None:
        yield pending_delete_sentinel(armed.pending_delete_fact)
    if clean_response or not mem_saves:
        out.append(clean_response)
        return
    parts: list[str] = []
    async for chunk in policy.reprompt_chunks(
        ctx.turn, mem_saves,
        call=reprompt_call_for(ctx.engine, ctx.sig, ctx.model_name, ctx.messages, ctx.thinking_enabled),
        engine_name=ctx.engine_name, model=ctx.model_name,
    ):
        parts.append(chunk)
        yield chunk
    text = policy.second_answer_text(parts)
    if not text:
        text = policy.empty_reply_text(ctx.lang)
        yield text
    out.append(text)


async def _generate_streaming_response(ctx: StreamingChatContext):
    """Streaming response body, flattened out of `_handle_chat_engine` (MC-027 F2).

    All request-scoped state is carried explicitly on `ctx` instead of closure
    free-vars. `full_response` / `clean_response` / `_assistant_saved` stay BARE
    LOCALS (single-persist idempotency + the B125 getsource sentinel). The
    disconnect-monitor ownership handoff stays in `_handle_chat_engine` (which sets
    `_returning_stream` before returning the StreamingResponse); this generator only
    cancels the monitor on a clean finish (INV-CRIT-01). Behaviour is byte-equivalent
    to the inline closure it replaces.

    The phases live in `_yield_*` / `_persist_*` helpers (2026-08-20, CCN 66 -> 20);
    what stays here is the sequence, the three bare locals, and the accumulation of
    `full_response` at the yield site. The engine loop reports its truncation and
    thinking flags back on a `StreamFlags`, since a generator cannot return while
    it yields.
    """
    _assistant_saved = False  # MC-116
    try:
        full_response = ""
        _mem_saves = []  # init here so fallback extractor never hits UnboundLocalError
        async for _h in _yield_response_headers(
            ctx.model_name, ctx.rag_count, ctx.rag_items, ctx.compacted,
            ctx.session.compaction_count, ctx.doc_truncated_pct,
        ):
            yield _h

        # Check if model is loaded (Ollama, MLX, llama.cpp)
        async for _tok in _yield_model_loading_check(ctx.engine, ctx.model_name, ctx.engine_name):
            yield _tok

        import time as _time_mod
        _stream_start_t = _time_mod.time()
        _flags = StreamFlags()
        # The pairs are (wire token | None, text to accumulate). `full_response`
        # grows HERE, at the same point the inline loop grew it — before the
        # chunk's wire tokens go out — so a disconnect mid-stream leaves the
        # partial text for the MC-116 persist in the `finally`.
        async for _tok, _full_delta in _yield_engine_chunks(ctx, _flags):
            full_response += _full_delta
            if _tok is not None:
                yield _tok

        if not _flags.has_any_thinking:
            logger.info("Model did not produce thinking tokens (model decides when to think)")

        # Save clean response (no think/GPT-OSS tags) to session/disk
        clean_response, _mem_saves, _mem_deletes = text_clean.clean_full_response(full_response, ctx.message)

        # FD-S5: tell the client the answer was cut by the token ceiling.
        # Its OWN yield (a marker split across reads would not be parsed).
        _trunc_tok = _gen_truncated_token(
            _flags.trunc, _flags.trunc_continuable, clean_response,
        )
        if _trunc_tok:
            yield _trunc_tok

        # C4.5: the same core rule the adapters run (`core.memory_facts.deletes`,
        # `core.turn.policy`), so this path keeps no copy of its own.
        _tail: list = []
        async for _tok in _arm_and_reprompt(ctx, clean_response, _mem_saves, _mem_deletes, _tail):
            yield _tok
        clean_response = _tail[0] if _tail else clean_response

        # B125: persist a placeholder for a think-only turn so
        # the next user message is not dropped as a duplicate role.
        if not clean_response and full_response:
            logger.info("Think-only turn: persisting placeholder assistant message (B125)")
        clean_response = text_clean.think_only_placeholder(clean_response, full_response)

        if clean_response:
            # C3.3: the same core write both doors use. This path (the pre-C1.3
            # streaming body, kept for `continue`) still has a listener on the
            # wire, so it keeps emitting its own sentinels — unlike the queued
            # step, where nobody is there to read them.
            # The spinner is only honest when something can actually be saved:
            # `[SAVING]` is cleared by `[MEM:n]`, and a turn that stores nothing
            # never sends one — the user was left with a spinner forever.
            if will_write(_mem_saves, ctx.session, ctx.rag_collections):
                yield "\x00[SAVING]\x00"
            _write = await write_facts(
                _mem_saves, ctx.session, ctx.memory_helper,
                engine=ctx.engine, model_name=ctx.model_name, sig=ctx.sig,
                lang=ctx.lang, rag_collections=ctx.rag_collections,
            )
            _mem_saves[:] = _write.facts
            _mem_saved_count = _write.saved
            if _mem_saved_count:
                yield f"\x00[MEM:{_mem_saved_count}]\x00"

            # Save message with stats for persistence
            _elapsed = round(_time_mod.time() - _stream_start_t, 1)
            _stats = _build_mem_stats(
                ctx.session, ctx.rag_count, ctx.rag_items, ctx.model_name,
                _elapsed, len(full_response), _mem_saved_count, _mem_saves,
            )
            persist_assistant_turn(
                ctx.session, clean_response, full_response, _stats,
                _flags.trunc, _flags.trunc_continuable, resume=ctx.continue_mode,
            )
            ctx.session_mgr._save_session_to_disk(ctx.session)
            _assistant_saved = True  # MC-116

            # #859: the NEXT turn will compact before it generates anything, and
            # compaction is a full LLM summarisation inside the critical path
            # (~100 s measured on 8 GB) with an empty screen in front of it.
            # We cannot warn while it runs: it happens before that request has
            # even produced response headers, so there is no stream to speak on.
            # The turn that fills the window warns about the one after it, and
            # the client can say so the instant the user hits send.
            # #965: same window the next turn's compaction will measure against,
            # or the warning and the compaction could disagree. Deferred import:
            # a plugin must not pull core at import time (layering gate, #471).
            from core.context_window import ask_engine_window
            if ctx.session.needs_compaction(ask_engine_window(ctx.engine)):
                yield "\x00[WILL_COMPACT:1]\x00"

        # Stream finished cleanly — release the disconnect
        # monitor so it doesn't keep polling forever.
        if not ctx.disconnect_monitor_task.done():
            ctx.disconnect_monitor_task.cancel()

    finally:
        # MC-116: a client disconnect (Stop / closed tab) tears down this
        # async generator via aclose()->GeneratorExit at the current yield,
        # so the normal persist path above is skipped (esp. non-MLX engines
        # where cancel_event is not wired). Persist a best-effort assistant
        # turn so the session isn't left with an orphan 'user' message.
        if not _assistant_saved and full_response:
            persist_partial_assistant(
                ctx.session, ctx.session_mgr, full_response, ctx.message, resume=ctx.continue_mode,
            )


def _start_engine_call(
    engine, engine_name: str, sig, model_name, system_prompt: str, messages: list, *,
    stream: bool, image_b64, thinking_enabled: bool, cancel_event, sampling_kwargs: dict,
    session_id: str, _continue: bool,
):
    """Start the engine's generation and return its `chat_result` (a dict, a
    coroutine or an async generator, depending on the engine's shape).

    Three shapes: Ollama-style `chat(model, messages, stream=…)`, the in-process
    engines (MLX, llama.cpp) driven through a queue + background task, and the
    generic `chat(messages, system=…)`. Extracted verbatim out of
    `_handle_chat_engine` on 2026-09-06 (ADR-007 C1.3) so the turn adapters and
    the `continue` path share one copy; the bodies are untouched (hot streaming
    path).
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
        # We inject system prompt as first message for Ollama
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        chat_result = engine.chat(model=model_name, messages=full_messages, stream=stream,
                                  images=_images_arg,
                                  thinking_enabled=thinking_enabled,
                                  **cancel_kwargs, **sampling_kwargs)
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

            # FD-S6: continue only reaches the MLX text path
            # (the marker is only :1 there). llama_cpp would
            # silently ignore the kwarg and REPEAT — hard gate.
            _continue_kwargs = {}
            if _continue:
                if engine_name != "mlx":
                    raise ValueError(
                        "continue is only supported on the MLX engine"
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

    async def _handle_chat_engine(
        body: dict,
        session,
        memory_helper,
        message: str,
        request: FastAPIRequest,
    ) -> tuple[str, Optional[str], Any]:
        """Returns (response_text, model_name, streaming_response_or_None).

        Only the `continue` path calls this since C1.3; the re-prompt context
        it used to return as a 4th element (#856) left with C4.5 — the second
        call is the core's now (`policy.reprompt_chunks`).
        """
        model_name = None
        image_b64 = body.get("image_b64")
        stream = body.get("stream", False)
        # FD-S6: continue mode — resume the last assistant turn.
        _continue = body.get("continue") is True
        # Opt-in nucleus sampling from the UI body → forwarded to every engine.
        # Empty dict when absent so the engine keeps its current default.
        _top_p = parse_top_p(body)
        sampling_kwargs = {"top_p": _top_p} if _top_p is not None else {}

        # Cancellation propagation (Bug C handoff, fix 2026-05-14): when the
        # HTTP client disconnects (UI Stop button → AbortController) we set
        # this event so the MLX worker thread can break out of its streaming
        # loop instead of running to max_tokens. Without this, the
        # single-worker MLX executor stays busy ~100s after the user clicks
        # Stop, blocking every subsequent request.
        cancel_event, _disconnect_monitor_task = _start_disconnect_monitor(request)
        # When we return a StreamingResponse, ownership of the monitor task
        # transfers to response_generator (which cancels it after the
        # generator finishes). The non-streaming path cancels it from the
        # finally block.
        # The flag prevents premature cancel between `return StreamingResponse`
        # and the first client read.
        _returning_stream = False
        # Normal chat - Auto-detect and use available LLM engine
        try:
            from core.lifespan import get_server_state
            import os

            # Deferred, like the ask_engine_window import above: a plugin must
            # not pull core at import time (layering gate, #471).
            from core.endpoints.chat_engines.model_switch import (
                model_switch_lock,
                switch_engine_model,
            )
            from core.endpoints.chat_engines.routing import (
                iter_live_engines,
                raise_if_terminal,
                resolve_engine_cascade,
            )

            module_manager = get_server_state().module_manager
            if module_manager is None:
                raise HTTPException(status_code=503, detail="Service unavailable: module manager not initialized")
            # Prioritize model/backend from request (UI selector) over env vars
            model_name = body.get("model") or os.getenv("NEXE_DEFAULT_MODEL", "llama3.2:3b")
            if len(model_name) > 100:  # type: ignore[arg-type]  # model_name: Any|str|None; os.getenv default prevents None in practice
                raise HTTPException(status_code=400, detail="Model name too long (max 100 chars)")
            preferred_engine = (body.get("backend") or os.getenv("NEXE_MODEL_ENGINE", "auto")).lower()  # type: ignore[union-attr]  # Any|str|None .lower(); os.getenv default "auto" prevents None

            # Log available modules
            available_modules = [m.name for m in module_manager.registry.list_modules()]
            logger.info(f"Available modules: {available_modules}")

            # F-D block 5: which engines to try, and which of them are live,
            # both come from the core resolver. What was here was a second
            # engine table with its own alias map ("llamacpp" and nothing else)
            # and its own five-deep walk (registry → .instance →
            # get_module_instance() → .chat) — a walk the loader had already
            # done once at startup, whose result is exactly what
            # get_engine_module reads. Neither copy was node-aware, so a module
            # registered with a dead node was dispatched to here while /status
            # reported it down.
            #
            # The names in this loop are the core's canonical ones now ("mlx",
            # not "mlx_module"). What the user sees does not change: the UI
            # strips "_module" before upper-casing the MODEL_LOADING label, so
            # both spellings render "MLX".
            _cascade = resolve_engine_cascade(preferred_engine, request.app.state)
            logger.info("Engine cascade for this turn: %s", _cascade)

            response_text = None  # type: ignore[assignment]  # Optional[str] by design, initialized None and assigned post-engine
            for engine_name, engine in iter_live_engines(_cascade, request.app.state):
                logger.info(f"Trying engine: {engine_name}")
                try:
                    # Resolve local model path if coming from the UI selector.
                    # The lock serialises concurrent swaps of class-level
                    # singletons; the env dance that builds the new config
                    # (mutated for the minimum time and always restored — P0-3
                    # env leak) now lives inside each engine module, which is
                    # the only place that knows its own config.
                    if body.get("model"):
                        async with model_switch_lock():
                            await switch_engine_model(engine, engine_name, model_name)

                    # Per-session thinking toggle
                    thinking_enabled = getattr(session, "thinking_enabled", False)

                    logger.info(f"Calling {engine_name}.chat with model={model_name} thinking={thinking_enabled}")

                    # --- Context Compacting + Build Context ---
                    # Three helpers (MC-026/MC-027). Still inside the engine
                    # loop, exactly as before — what moved out of this function
                    # is ~130 lines of pure data preparation with no response
                    # I/O in them, which is what took it to CCN 58.
                    _turn = await _build_turn_context(
                        body, session, session_mgr, engine, message, _continue,
                    )
                    system_prompt, _lang = _build_turn_system_prompt(
                        body, session, message, _continue,
                        # C4.2: the same state the turn's `system_prompt` step
                        # hands over (`ctx.app_state`), so a `continue` resolves
                        # the base prompt from where the turn it resumes did —
                        # the two must land in the same prefix-cache namespace.
                        app_state=request.app.state,
                    )
                    # C4.2: the clock is a step of the turn now, and this path
                    # does not walk the map — it resolves the same line itself
                    # instead of the assembler doing it behind its back.
                    _clock_line = time_context_line(message, _lang)
                    messages, _doc_truncated_pct = _assemble_engine_messages(
                        _turn, system_prompt, _lang, message, session, _continue,
                        engine, clock_line=_clock_line, app_state=request.app.state,
                        has_image=bool(image_b64),
                    )
                    response_chunks: list[str] = []

                    # Adapt to different chat signatures
                    import inspect
                    sig = inspect.signature(engine.chat)

                    chat_result = _start_engine_call(
                        engine, engine_name, sig, model_name, system_prompt, messages,
                        stream=stream, image_b64=image_b64, thinking_enabled=thinking_enabled,
                        cancel_event=cancel_event, sampling_kwargs=sampling_kwargs,
                        session_id=session.id, _continue=_continue,
                    )

                    # Flag if compacted to notify the client
                    _compacted = session.compaction_count > 0 and session.context_summary is not None

                    if stream:
                        _stream_ctx = StreamingChatContext(
                            model_name=model_name,
                            rag_count=_turn.rag_count,
                            rag_items=_turn.rag_items,
                            compacted=_compacted,
                            doc_truncated_pct=_doc_truncated_pct,
                            session=session,
                            session_mgr=session_mgr,
                            memory_helper=memory_helper,
                            engine=engine,
                            engine_name=engine_name,
                            chat_result=chat_result,
                            sig=sig,
                            system_prompt=system_prompt,
                            messages=messages,
                            thinking_enabled=thinking_enabled,
                            lang=_lang,
                            message=message,
                            disconnect_monitor_task=_disconnect_monitor_task,
                            rag_collections=body.get("rag_collections"),
                            continue_mode=_continue,
                            # C4.5: what the core policy reads. This path has no
                            # turn of its own (it never walks TURN_STEPS), so the
                            # re-prompt's gate slot and I8 entry land on this one.
                            turn=TurnContext(
                                turn_id=uuid4().hex, entry="ui", streaming=True,
                                app_state=request.app.state, session_id=session.id,
                                session=session, message=message, lang=_lang,
                                system_prompt=system_prompt,
                            ),
                        )
                        _returning_stream = True
                        return "", model_name, StreamingResponse(
                            _generate_streaming_response(_stream_ctx),
                            media_type="text/plain",
                            headers={
                                "Cache-Control": "no-cache, no-store",
                                "X-Accel-Buffering": "no",
                                "X-Content-Type-Options": "nosniff",
                                # The session this turn was stored in. The JSON
                                # path already returns it; streaming did not, so
                                # a client that lost its id (or never learned the
                                # one the server minted for it) had no way back
                                # and silently started a new conversation on the
                                # next message, orphaning everything before it.
                                "X-Session-Id": session.id,
                            }
                        )

                    # Handle non-streaming response accumulation
                    await _accumulate_nonstreaming_response(chat_result, response_chunks)

                    response_text = "".join(response_chunks)
                    if response_text:
                        logger.info(f"{engine_name} succeeded!")
                        break
                except Exception as e:
                    # F-D block 5: which errors end the turn and which are worth
                    # another engine is one decision, and it lives in the core
                    # (engine_error_to_http) instead of four except clauses here
                    # — /v1 had none of them and turned every engine failure
                    # into a 500.
                    raise_if_terminal(e, engine_name)
                    logger.warning(f"{engine_name} failed: {e}")
                    logger.debug("Engine error details:", exc_info=True)
                    continue

            if not response_text:
                # D-I phase 2 / #884: this is a failed request, not an
                # assistant turn. 200 + error-string painted the phrase
                # inside the chat bubble (app.js only errors when not ok).
                raise HTTPException(
                    status_code=503,
                    detail="No AI engine available",
                )
        except HTTPException:
            # Make sure the disconnect monitor doesn't outlive a 4xx/5xx exit.
            if not _disconnect_monitor_task.done():
                _disconnect_monitor_task.cancel()
            raise
        except Exception as e:
            # MC-133: log the detail (with traceback) but never echo str(e) to the
            # response body — it can carry internal paths/state. The user-facing
            # text stays generic (kept English to match the sibling fallback above,
            # since _lang may be unset this early in the catch-all).
            logger.error("Error calling LLM: %s", e, exc_info=True)
            response_text = "Error: an internal error occurred while generating the response."
        finally:
            # Only cancel monitor if NOT returning a stream. For streams the
            # response_generator owns the monitor and cancels it after [DONE];
            # cancelling here would kill the monitor before the client even
            # starts reading the response.
            if not _returning_stream and not _disconnect_monitor_task.done():
                _disconnect_monitor_task.cancel()

        return response_text or "", model_name, None


    async def _chat_inner(request: FastAPIRequest, body: Dict[str, Any], _auth):
        """Inner chat logic, called under semaphore."""
        session_id = body.get("session_id")
        # RT-10: clean 400 for malformed/traversal session ids (see routes_files).
        if session_id is not None and not session_mgr.is_valid_session_id(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id")
        stream = body.get("stream", False)

        # ── FD-S6: Continue — resume the last (truncated) assistant turn ──
        # Dedicated branch BEFORE the turn's `validate` step (which 400s an empty
        # message). No new user message is persisted, no intent detection, no
        # compaction, no doc/RAG injection: the engine re-enters the last
        # assistant message with continue_final=True and the tail merges
        # in-place. Server-side stateless: everything derives from the
        # session history at click time.
        if body.get("continue") is True:
            if not session_id:
                raise HTTPException(
                    status_code=400, detail="continue requires session_id"
                )
            _c_session = session_mgr.get_or_create_session(session_id)
            if (
                not _c_session.messages
                or _c_session.messages[-1].get("role") != "assistant"
            ):
                raise HTTPException(
                    status_code=400,
                    detail="continue requires the last message to be an assistant turn",
                )
            # The last REAL user message drives language detection + system.
            _last_user = next(
                (m.get("content", "") for m in reversed(_c_session.messages)
                 if m.get("role") == "user"),
                "",
            )
            response_text, model_name, _streaming_resp = await _handle_chat_engine(
                body, _c_session, memory_facts.helper_for(request.app.state), _last_user, request
            )
            if _streaming_resp is not None:
                return _streaming_resp
            # Non-streaming continue: merge the tail in-place (same contract
            # as the streaming finally).
            if response_text and not response_text.startswith("Error:"):
                _c_session.messages[-1]["content"] += response_text
                _c_session.messages[-1].pop("gen_raw", None)
                session_mgr._save_session_to_disk(_c_session)
            return {
                "response": response_text,
                "session_id": _c_session.id,
                "intent": "chat",
                "memory_action": None,
            }

        # ADR-007 (C1.3): from here on this door no longer decides the order of
        # the turn. It builds a TurnContext and lets the engine walk TURN_STEPS;
        # every step is an adapter in `turn_adapters.py` wrapping the functions
        # this body used to call. Two tables, one per wire format, because four
        # steps really differ between them. The `continue` branch above keeps
        # its own path on purpose (C1 plan, decision §5).
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
            body=body,
            request=request,
            app_state=request.app.state,
        )
        adapters = ui_adapters(session_mgr, streaming=bool(stream))
        # C2.2: memory.write/compact go to the post-commit queue when a real
        # one is attached (production always has one — the lifespan attaches
        # it next to the engine gate); None here makes them run inline,
        # exactly as before C2.2 — the fallback pre-C2.2 test harnesses need.
        post_commit = queue_for(ctx.app_state)
        if stream:
            body_iterator = await stream_turn(ctx, adapters, post_commit=post_commit)
            return StreamingResponse(
                body_iterator,
                media_type="text/plain",
                headers={
                    "Cache-Control": "no-cache, no-store",
                    "X-Accel-Buffering": "no",
                    "X-Content-Type-Options": "nosniff",
                    # The session this turn was stored in (see the note in
                    # `_handle_chat_engine`): a client that lost its id has
                    # a way back.
                    "X-Session-Id": ctx.session.id,
                    # C2.0: one id to grep for in `turn.trace` log lines.
                    "X-Nexe-Turn-Id": ctx.turn_id,
                },
            )
        await run_turn(ctx, adapters, post_commit=post_commit)
        return ctx.wire
