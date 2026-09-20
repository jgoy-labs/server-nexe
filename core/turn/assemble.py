"""One prompt assembly for the web UI door, in the core (ADR-007, C4.2).

`PromptParts` (the `TurnContext` SHADOW that used to sit in
`routes_chat.py`, forcing the turn's real envelope to be imported there as
`CoreTurnContext` — the name is one again), the turn's context assembly and
the engine payload, moved out of the plugin whole. What used to be
`_build_turn_context` + `_assemble_engine_messages` is here, unchanged except
for the one thing C4.2 is about: **retrieval is no longer done in here**. It
arrives as `recall`, from the `recall` step that now runs at both doors
(`core/turn/recall.py`), instead of being folded inside this function.

The `continue` path (FD-S6, decision §5 of the C1 plan) keeps calling these
from `routes_chat._handle_chat_engine` — it does not walk the turn map, and
it never retrieves anything, so it passes the empty recall this signature
defaults to.

Every import is from `core/`. Two are function-local and say why: pulling
`core.context_budget` or `core.endpoints.chat_sanitization` at module level
executes `core/endpoints/__init__.py`, which eagerly imports `.v1` -> `.chat`
-> `core.turn.*` — the cycle `_trim_rag_context` documents in
`core/endpoints/chat.py` for the same package.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from core.context_window import ask_engine_window
from core.sessions.compactor import compact_session

logger = logging.getLogger(__name__)


#: #1063: the header used to be Catalan no matter what. The sentence that
#: CITES it — `context_budget._doc_framing` — must answer in the SAME
#: language; with `NEXE_LANG=en` (the default) a model reading "Answer based
#: on the ATTACHED DOCUMENT" would find a block titled "DOCUMENT ADJUNTAT"
#: right after it. `core/endpoints/chat_rag.py` treats that correspondence as
#: a deliberate invariant ("labels per language — must match system prompt
#: references"); this was the one label that broke it.
#:
#: ⚠️ #1072: this comment used to say the citing sentence "already answers in
#: the turn's language", and that was NOT true — `_doc_framing` resolved out
#: of `NEXE_LANG`, so fixing the header alone left the pair split the OTHER
#: way (English header, Catalan sentence, with this repo's own `.env`). The
#: sentence follows the turn now too: `_assemble_engine_messages` passes its
#: `lang` down to `_inject_context_into_messages`. Fixing one half of a
#: correspondence on the assumption that the other half was already right is
#: what made this survive a fix that went looking straight at it.
#:
#: Same shape as `_doc_framing` (`core/context_budget.py`) and
#: `_COLLECTIONS_OFF_NOTES` (`core/turn/prompt.py`): a module dict keyed by
#: the two-letter code, resolved by the caller's `lang`, `en` as the fallback
#: — never read from `NEXE_LANG` here, unlike its neighbour, because this one
#: has `ctx.lang` in scope at its only production call site (`budget` in
#: `turn_adapters.py`) and the turn's reply language is what the surrounding
#: prompt is already written in.
_DOC_HEADER = {
    "ca": "DOCUMENT ADJUNTAT ({filename}):",
    "es": "DOCUMENTO ADJUNTO ({filename}):",
    "en": "ATTACHED DOCUMENT ({filename}):",
}
_DOC_PARTIAL_NOTE = {
    "ca": (
        "[Mostrant les primeres ~{shown_pages} pagines de ~{total_pages} "
        "({shown}/{total} parts, {pct}% del document). "
        "La resta del document esta indexada — l'usuari pot fer preguntes "
        "sobre qualsevol part i el sistema les recuperara.]\n\n"
    ),
    "es": (
        "[Mostrando las primeras ~{shown_pages} paginas de ~{total_pages} "
        "({shown}/{total} partes, {pct}% del documento). "
        "El resto del documento esta indexado — el usuario puede hacer preguntas "
        "sobre cualquier parte y el sistema las recuperara.]\n\n"
    ),
    "en": (
        "[Showing the first ~{shown_pages} pages of ~{total_pages} "
        "({shown}/{total} parts, {pct}% of the document). "
        "The rest of the document is indexed — the user can ask about "
        "any part and the system will retrieve it.]\n\n"
    ),
}
_DOC_COMPLETE_NOTE = {
    "ca": "[Document complet: ~{total_pages} pagines]\n\n",
    "es": "[Documento completo: ~{total_pages} paginas]\n\n",
    "en": "[Complete document: ~{total_pages} pages]\n\n",
}


def _doc_lang_key(lang) -> str:
    """Two-letter code restricted to ca/es/en, `en` as the fallback.

    Same normalisation `core/turn/prompt.py::_collections_prompt_overrides`
    already applies — this does not invent a second convention.
    """
    _lk = (lang or "en")[:2]
    return _lk if _lk in _DOC_HEADER else "en"


def _build_document_context(
    attached_doc: dict, context_window=None, lang=None,
) -> tuple[str, int, int]:
    """Build document_context string from an attached_doc dict.

    `lang` (#1063) is the turn's reply language — the caller's `ctx.lang` —
    so the header agrees with `_doc_framing`, the sentence in the same
    prompt that cites it by name. `None` (a caller with no turn language in
    scope) falls back to `en`, never to `NEXE_LANG`: this is turn content,
    not the server's voice.

    Returns (document_context, shown, total_chunks).
    """
    from core.endpoints.chat_sanitization import _sanitize_rag_context

    _lk = _doc_lang_key(lang)
    # Every other field here is read with `.get` and a default; `filename` was
    # the one read by subscript, so a session holding a document without it
    # raised KeyError from inside `budget`. At the UI that surfaced as the
    # door's internal-error wrapper; at `/v1`, where C4.3-b's `budget` has no
    # wrapper of its own, it became an uncaught 500 on a turn that had
    # answered fine the day before. A document is session state that may have
    # been written by an older build, so the shape is not guaranteed: an
    # unusable one costs the turn its document, never the turn itself.
    if not attached_doc.get('filename'):
        logger.warning(
            "Attached document has no filename (%s) — answering without it",
            sorted(attached_doc) or "empty dict",
        )
        return "", 0, 0
    chunks = attached_doc.get('chunks', [attached_doc.get('content', '')])
    total_chunks = attached_doc.get('total_chunks', len(chunks))
    total_chars = attached_doc.get('total_chars', 0)
    shown = len(chunks)
    doc_content = "\n\n---\n\n".join(chunks)
    header = _DOC_HEADER[_lk].format(filename=attached_doc['filename'])
    if total_chunks == 1:
        document_context = f"\n\n{header}\n\n{doc_content}\n"
    else:
        est_pages_total = round(total_chars / 3000)
        est_pages_shown = round(len(doc_content) / 3000)
        pct = round(shown * 100 / total_chunks)
        document_context = f"\n\n{header}\n"
        if shown < total_chunks:
            document_context += _DOC_PARTIAL_NOTE[_lk].format(
                shown_pages=est_pages_shown, total_pages=est_pages_total,
                shown=shown, total=total_chunks, pct=pct,
            )
        else:
            document_context += _DOC_COMPLETE_NOTE[_lk].format(total_pages=est_pages_total)
        document_context += f"{doc_content}\n"
    document_context = _sanitize_rag_context(document_context, context_window)
    logger.info(
        "Using attached document: %s (parts %d/%d, %d chars)",
        attached_doc['filename'], shown, total_chunks, len(doc_content),
    )
    return document_context, shown, total_chunks


@dataclass
class PromptParts:
    """What a turn takes from the session before the prompt exists.

    Split out of `_handle_chat_engine` on 2026-08-20 (see MC-026/MC-027): the
    handler had grown to CCN 58 with ~130 lines of pure data assembly sitting
    in the middle of the engine loop. The bodies below are unchanged — only
    their indentation and the way the values travel.

    Named `TurnContext` until C4.2, which is why `routes_chat.py` had to import
    the turn's real envelope as `CoreTurnContext`: two different objects with
    one name, in the same module. This one is the prompt's parts; the other is
    the turn (`core/turn/context.py`).
    """

    context_messages: list
    document_context: str
    rag_context: str
    rag_count: int
    rag_items: list


async def _build_turn_context(
    body: dict, session, session_mgr, engine, message: str, _continue: bool,
    *, compact: bool = True, recall: tuple = ("", 0, ()),
    attachments: dict | None = None, lang: str | None = None,
) -> PromptParts:
    """Compaction + conversation history + attached document + RAG.

    `_continue` keeps the name it has in the caller on purpose: this code moved
    here verbatim, and every FD-S6 branch below reads the way it always did.

    `recall` (C4.2) is what the turn's `recall` step retrieved, as
    (text, count, items). This function used to retrieve it itself, which is
    what made `recall` a folded step at this door; `memory_helper` was its
    only reason to be in the signature and left with it. The `continue` path
    passes nothing and gets the empty default, exactly as before: FD-S6 never
    retrieved on a resume.

    `compact` (C2.2): the turn columns's `budget` adapter passes `False` — its
    door queues `compact` as its own post-commit step (core/turn/run.py's
    POST_COMMIT) instead, so it must not ALSO run here inline. The `continue`
    path (which never reaches the column, §5 of the C1 plan) keeps the
    default and compacts exactly as it always did.

    `lang` (#1063) is the turn's reply language, forwarded to
    `_build_document_context` so its header agrees with `_doc_framing`
    (`core/context_budget.py`), the sentence in the same prompt that names it.
    The `continue` path never reaches this: `_continue=True` forces
    `attached_doc = None` two lines below, so passing nothing here (the
    default) is correct, not an oversight. The API door (`/v1`) does not call
    this function at all yet — D4 (C4.3) is what would make it — so today's
    only production caller is the `budget` adapter, which already has
    `ctx.lang` in scope.
    """
    # --- Context Compacting ---
    # If the session has too many messages, compact with LLM summary.
    # FD-S6: skipped on continue — compaction rewrites the
    # history (an extra LLM generation between cut and resume)
    # and would invalidate the prefix the resume relies on.
    if compact and not _continue:
        await compact_session(session, engine, session_mgr)

    # --- Build Context ---
    # 1. Get recent conversation history with summary context
    context_messages_full = session.get_context_messages()
    # Exclude the very last message (just added) to avoid duplication.
    # FD-S6: on continue there is NO just-added user message —
    # the last message is the truncated assistant turn we are
    # about to resume, and it must stay.
    if _continue:
        context_messages = list(context_messages_full)
    else:
        context_messages = context_messages_full[:-1] if context_messages_full else []

    # 2. Check for attached document (takes priority over RAG)
    # FD-S6: none of this on continue — a doc/RAG turn injected
    # between the cut and the resume would both derail the
    # answer and shatter the prefix the resume reuses.
    if _continue:
        attached_doc = None
        document_context = ""
        rag_context, rag_count, _rag_items = "", 0, []
    else:
        # C4.3: the `session` step read it into `ctx.attachments`; this no
        # longer reaches into the session for it. The disk write stays exactly
        # where it was — the read it sat next to never mutated anything, so
        # what it persists is whatever the steps before it did, and moving it
        # is a separate question from moving the read.
        attached_doc = (attachments or {}).get("document")
        session_mgr._save_session_to_disk(session)

        # #972: the sanitizer sizes against the window the serving engine
        # really has, not DEFAULT_CONTEXT_WINDOW (8192).
        from core.endpoints.chat_sanitization import _sanitize_rag_context

        _window = ask_engine_window(engine)

        document_context = ""
        if attached_doc:
            document_context, _shown, _total_chunks = _build_document_context(
                attached_doc, context_window=_window, lang=lang,
            )

        # 3. The memory context (RAG) the `recall` step retrieved, sized to the
        # window here — the step runs before `engine`, so this is the first
        # point in the turn that knows how big the window is. An attached
        # document is the turn's context and the door does not recall at all.
        rag_context, rag_count, _rag_items = recall
        rag_context = _sanitize_rag_context(rag_context, _window) if rag_context else ""
        _rag_items = list(_rag_items)

    return PromptParts(
        context_messages=context_messages,
        document_context=document_context,
        rag_context=rag_context,
        rag_count=rag_count,
        rag_items=_rag_items,
    )


def _assemble_engine_messages(
    turn: PromptParts, system_prompt: str, lang: str, message: str, session, _continue: bool,
    engine=None, *, clock_line: str = "", app_state=None, has_image: bool = False,
) -> tuple[list, int]:
    """Engine payload: history, context budget, injection, on-demand clock.

    `engine` (#965) is the live engine module, asked how many tokens it can hold
    so the budget follows the model and the machine instead of a flat 24000
    chars. Optional: without it the documented default window is used.

    `clock_line` (C4.2) is what the turn's `clock` step resolved. It used to be
    computed here, which is what made `clock` a folded step at this door; both
    callers pass it now — the `budget` adapter from `ctx.clock_line`, and the
    `continue` path from the same `time_context_line` it always called.

    Returns (messages, doc_truncated_pct).
    """
    from core.context_budget import (
        _inject_context_into_messages,
        compute_context_budget,
        fit_prompt_to_window,
        resolve_history_ratio,
        resolve_max_context_chars,
    )
    from core.endpoints.chat_sanitization import (
        CHARS_PER_TOKEN_ESTIMATE,
        DEFAULT_CONTEXT_WINDOW,
    )

    context_messages = turn.context_messages
    document_context = turn.document_context
    rag_context = turn.rag_context
    # 4. Prepare messages payload for engine
    engine_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in context_messages
    ]

    # ── Bug 32: Dynamic context budget ─────────────────────────────────
    # Reserve a minimum slice of the model context for conversation history
    # so that a huge attached document never wipes out previous turns.
    # Configurable via NEXE_HISTORY_CONTEXT_RATIO (default 0.30 = 30%).
    # #965: the total no longer comes from a flat env default — it is sized from
    # the window the serving engine actually has.
    MAX_CONTEXT_CHARS = resolve_max_context_chars(engine)
    # #977: read through core's _ratio_env like its two sibling ratios, instead
    # of a bare float() that let nan/inf through to become the 0.9 clamp.
    _history_ratio = resolve_history_ratio()

    system_chars = len(system_prompt)
    history_chars = sum(len(m.get("content", "")) for m in context_messages)
    message_chars = len(message)

    _budget = compute_context_budget(
        max_context_chars=MAX_CONTEXT_CHARS,
        system_chars=system_chars,
        history_chars=history_chars,
        message_chars=message_chars,
        document_chars=len(document_context) if document_context else 0,
        history_ratio=_history_ratio,
        response_buffer=500,
    )
    available_chars = _budget["available_chars"]

    # Inject context into messages (not system prompt -> MLX can cache the prefix)
    if _continue:
        # FD-S6: no new user turn — the prompt must END at the
        # truncated assistant message. Swap its content for the
        # RAW generation (gen_raw) when present: with thinking
        # ON the persisted content is CLEAN (think stripped)
        # and its re-render diverges token-wise from the KV
        # that was just built — gen_raw makes the continue
        # prompt an exact token prefix of the cache entry
        # (prefill ~0 instead of the full 50s re-prefill).
        _doc_truncated_pct, _ctx_injected = 0, False
        _raw = (
            session.messages[-1].get("gen_raw")
            if session.messages else None
        )
        if _raw and engine_messages and engine_messages[-1]["role"] == "assistant":
            engine_messages[-1]["content"] = _raw
    else:
        engine_messages, _doc_truncated_pct, _ctx_injected = _inject_context_into_messages(
            engine_messages, message, document_context, rag_context,
            _budget, available_chars, history_chars, lang, app_state,
            has_image=has_image,
        )
    # B030/#851: the data-not-instructions rule is armed
    # UNCONDITIONALLY by _finalize_system_prompt, which runs in
    # _build_turn_system_prompt before this — a conditional suffix
    # here split the prefix-cache namespace between RAG and
    # non-RAG turns of the same session.

    # B007/D-A: clock on demand — if the user asks the time,
    # prefix THIS turn's user message with the system clock.
    # Never the system prompt (it would poison the prefix cache
    # for the whole conversation); the session keeps the raw
    # message, so only this turn diverges in the cache.
    if clock_line and engine_messages and engine_messages[-1]["role"] == "user":
        engine_messages[-1]["content"] = (
            f"{clock_line}\n\n{engine_messages[-1]['content']}"
        )

    # #976: the last line of defence. The budget above decides what the turn may
    # KEEP; this checks what was actually ASSEMBLED against the window the engine
    # reported — history, the clock line and the untrusted-context wrapper all
    # land after the arithmetic. MLX truncates inside its plugin and Ollama
    # truncates server-side, but llama.cpp raises and the turn dies, so the
    # guarantee has to live here, where both doors pass.
    _window_tokens = ask_engine_window(engine) or DEFAULT_CONTEXT_WINDOW
    messages, _ = fit_prompt_to_window(
        system_prompt, engine_messages, _window_tokens,
        # The same 500-char reply reserve compute_context_budget was given above.
        reply_budget_tokens=500 // CHARS_PER_TOKEN_ESTIMATE,
    )
    return messages, _doc_truncated_pct
