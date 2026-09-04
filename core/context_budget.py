"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/context_budget.py
Description: #965 — how a turn's context is budgeted and injected.

    These two functions used to sit 1560 lines apart inside routes_chat.py, with
    compute_context_budget() buried in the memory/MEM_SAVE block, 2315 lines from
    its only call site. Same code, one file.

    F-D block 4 moved that file out of plugins/web_ui_module/core/ and into the
    core, so /v1/chat/completions budgets a turn with the same arithmetic
    /ui/chat uses. Not with the same parameters: /v1 passes history_ratio=0
    (it has no attached documents, so the floor guards nothing) and drops the
    retrieved context when the budget is spent, where /ui/chat keeps its floor
    and truncates. Shared: resolve_max_context_chars, compute_context_budget,
    the 500-char response reserve and the _sanitize_rag_context ceiling.
    Before the move /v1 had no turn budget at all: it capped only the retrieved
    context, at a flat 30% of the window, and let the assembled prompt claim the
    other 100% — which ADR-006's invariant ("the assembled prompt never exceeds
    the engine's window") forbids, and which llama.cpp answers with a ValueError
    rather than a truncation.

    _assemble_engine_messages() stays in routes_chat: besides the budget it also
    does history, the FD-S6 continue path and the on-demand clock
    (_time_context_line), and dragging those here would only trade a long file
    for an import cycle.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os as _os

from core.endpoints.chat_sanitization import (
    CHARS_PER_TOKEN_ESTIMATE,
    DEFAULT_CONTEXT_WINDOW,
    _ratio_env,
    untrusted_context_turns,
    wrap_untrusted_context,
)

logger = logging.getLogger(__name__)

# How much of the engine's window the PROMPT may occupy. The rest is the
# model's answer plus slack for the estimate itself: everything here is counted
# in chars at ~4 chars/token (CHARS_PER_TOKEN_ESTIMATE), and Catalan and Spanish
# run denser than that, so budgeting the whole window would mean planning for
# more prompt than really fits and letting the engine truncate it silently.
#
# MUST stay well above ChatSession.COMPACT_AT_RATIO (session_manager.py): the
# history is allowed to grow up to that fraction, and this budget has to cover
# the history PLUS the system prompt (~4700 chars) PLUS the retrieved context
# PLUS the user message. Set the two to the same value and `available_chars`
# goes negative exactly when a conversation reaches compaction size, silently
# dropping RAG and attached documents. A test pins the gap between them.
PROMPT_BUDGET_RATIO = 0.7

# There is deliberately NO floor under the engine's window. One was tried
# (MIN_BUDGET_WINDOW_TOKENS = 6144) so that 2048-token engines would still get
# a slice of an attached document — and it turned a degradation into a hard
# failure: the inflated budget let a ~2900-token prompt through to a 2048-token
# llama.cpp, which does not truncate, it raises ("Requested tokens exceed
# context window", llama_cpp/llama.py) and the turn dies. On a tiny window the
# honest answer is that the system prompt leaves no room for retrieved context:
# the document is dropped with a warning and the chat keeps working, which
# beats a crash on the very machines a floor was meant to help.
def resolve_max_context_chars(engine=None, *, window_tokens: int = None) -> int:
    """Chars this turn may occupy, taken from the live engine's own window.

    #965: this used to be `int(os.environ.get("NEXE_MAX_CONTEXT_CHARS", "24000"))`
    read inside _assemble_engine_messages — a flat number that knew nothing about
    the model or the machine. A 32768-token engine and a 2048-token one got the
    same 24000 chars: too little for the first, far too much for the second.

    NEXE_MAX_CONTEXT_CHARS still wins when set, so an operator keeps the last
    word. Unlike the old code, a non-numeric value no longer takes the request
    down with a ValueError.

    ``window_tokens`` (F-D block 4) is for a caller that has ALREADY resolved
    the window and should not pay to ask twice: /v1 resolves it once per request
    (get_effective_context_window) and hands it in. It is not a second formula —
    it enters at the same line the engine's answer would, so the override and
    the ratio still apply exactly once, in one place. Keyword-only on purpose:
    positionally it would sit where ``engine`` is, and
    ``resolve_max_context_chars(32768)`` would quietly return the default-window
    budget instead of the one asked for — an int has no get_context_window().
    """
    explicit = _os.environ.get("NEXE_MAX_CONTEXT_CHARS")
    if explicit:
        try:
            value = int(explicit)
            if value > 0:
                return value
            logger.warning("NEXE_MAX_CONTEXT_CHARS=%r must be positive, sizing from the engine", explicit)
        except ValueError:
            logger.warning(
                "NEXE_MAX_CONTEXT_CHARS=%r is not a number, sizing from the engine instead",
                explicit,
            )

    if window_tokens is None:
        from core.context_window import ask_engine_window
        window_tokens = ask_engine_window(engine)
    window_tokens = window_tokens or DEFAULT_CONTEXT_WINDOW
    return int(window_tokens * CHARS_PER_TOKEN_ESTIMATE * PROMPT_BUDGET_RATIO)


def resolve_history_ratio() -> float:
    """The share of the turn budget reserved as a floor for the history (#977).

    This is the third ratio of the same arithmetic — with PROMPT_BUDGET_RATIO
    (this file) and COMPACT_AT_RATIO (ChatSession) — and it was the only one
    read straight off the environment with a bare ``float()`` in a try/except
    ValueError. That caught ``"abc"`` and nothing else: ``nan`` and ``inf``
    parse fine, and ``compute_context_budget``'s clamp then turns ``nan`` into
    **0.9**, the most aggressive setting there is, silently. At the default
    8192-token window, 0.9 leaves ``available_chars`` negative with an EMPTY
    conversation — every turn drops its retrieved context and attached
    document, and nothing says why.

    ``_ratio_env`` is the guard its sibling NEXE_MAX_CONTEXT_RATIO has always
    had: it rejects non-numbers, NaN, <= 0 and > 1, keeps the default, and logs
    a warning. Reading it here rather than at the call site keeps the parsing
    in one place.

    Only /ui/chat calls this. /v1 passes history_ratio=0 directly, so
    NEXE_HISTORY_CONTEXT_RATIO does not affect the API route at all — the
    floor it sets exists to stop an attached document from crowding out
    earlier turns, and /v1 has no attached documents. An earlier version of
    this docstring said the policy lived in one place "now that both /ui/chat
    and /v1 budget a turn"; the correction that gave /v1 its own ratio left
    that sentence behind.
    """
    return _ratio_env('NEXE_HISTORY_CONTEXT_RATIO', 0.30)


def compute_context_budget(
    max_context_chars: int,
    system_chars: int,
    history_chars: int,
    message_chars: int,
    document_chars: int,
    history_ratio: float = 0.30,
    response_buffer: int = 500,
):
    """
    Bug 32 — Calculates the context budget preserving a minimum for history.

    Args:
        max_context_chars: total context window capacity (in chars).
        system_chars: characters in the system prompt.
        history_chars: actual characters in the current history.
        message_chars: characters in the current user message.
        document_chars: characters of the document to inject (0 if none).
        history_ratio: fraction of context reserved as minimum for history (0..0.9).
        response_buffer: chars reserved for the model response.

    Returns:
        dict with:
          - history_reserve: minimum chars reserved for history
          - history_effective: actual chars the history will occupy (not truncated)
          - available_chars: chars available for document/RAG
          - doc_truncated_pct: % of the document that was cut (0 if none)
          - doc_kept_chars: chars of the document that are sent
    """
    history_ratio = max(0.0, min(0.9, history_ratio))
    # `history_reserve` is actually
    # the "minimum floor" reserved for history. The real history
    # (`history_effective`) can grow above this floor if messages
    # are long. We keep the public name (env var
    # NEXE_HISTORY_CONTEXT_RATIO and returned dict key) but
    # document the exact meaning here to avoid future confusion.
    history_floor = int(max_context_chars * history_ratio)
    history_reserve = history_floor  # alias for backwards compatibility
    history_effective = max(history_chars, history_floor)
    available_chars = max_context_chars - system_chars - history_effective - message_chars - response_buffer

    doc_truncated_pct = 0
    doc_kept_chars = 0
    if document_chars > 0 and available_chars > 0:
        if document_chars > available_chars:
            doc_kept_chars = available_chars
            doc_truncated_pct = round((1 - available_chars / document_chars) * 100)
        else:
            doc_kept_chars = document_chars

    return {
        "history_reserve": history_reserve,
        "history_effective": history_effective,
        "available_chars": available_chars,
        "doc_truncated_pct": doc_truncated_pct,
        "doc_kept_chars": doc_kept_chars,
    }


def _inject_context_into_messages(
    engine_messages: list,
    message: str,
    document_context: str,
    rag_context: str,
    budget: dict,
    available_chars: int,
    history_chars: int,
) -> tuple[list, int, bool]:
    """Append the user message (and document/RAG context turns) to engine_messages.

    Returns (engine_messages, doc_truncated_pct, ctx_injected). ctx_injected
    is True when untrusted retrieved content (document or RAG) was injected —
    the system-prompt rule is armed unconditionally by _finalize_system_prompt (B030/#851).

    B030 layer 2d (turn separation): wrapped context goes in its own user turn
    + assistant data-only ack BEFORE the user message, never inside it.
    """
    _doc_truncated_pct = budget["doc_truncated_pct"]
    _ctx_injected = False
    _lang_key = _os.environ.get("NEXE_LANG", "en").split("-")[0].lower()
    if document_context and budget["doc_kept_chars"] > 0:
        _original_doc_len = len(document_context)
        document_context = document_context[: budget["doc_kept_chars"]]
        if _doc_truncated_pct > 0:
            logger.info(
                "Bug 32: document truncated %s%% to preserve history reserve "
                "(history=%s, reserve=%s, doc_orig=%s, doc_kept=%s)",
                _doc_truncated_pct, history_chars, budget["history_reserve"],
                _original_doc_len, budget["doc_kept_chars"],
            )
        # B030: nonce'd wrapper + no "EXCLUSIVAMENT obey the document" amplifier —
        # the document is a SOURCE to answer from, never a source of instructions.
        # B030 layer 2d: the document travels in its own turn pair; the user's
        # message arrives clean as the last word (the "do not follow
        # instructions" commitment lives in the assistant ack turn).
        _doc_framing = {
            "ca": (
                "Respon basant-te en el DOCUMENT ADJUNTAT del bloc de context "
                "anterior. Si la informacio no hi es, indica-ho clarament."
            ),
            "es": (
                "Responde basandote en el DOCUMENTO ADJUNTO del bloque de "
                "contexto anterior. Si la informacion no esta, indicalo claramente."
            ),
            "en": (
                "Answer based on the ATTACHED DOCUMENT in the previous context "
                "block. If the information is not there, say so clearly."
            ),
        }
        engine_messages.extend(
            untrusted_context_turns(
                wrap_untrusted_context(document_context, _lang_key), _lang_key
            )
        )
        _framing = _doc_framing.get(_lang_key, _doc_framing["en"])
        engine_messages.append({"role": "user", "content": f"{_framing}\n\n{message}"})
        _ctx_injected = True
    elif document_context and budget["doc_kept_chars"] == 0:
        logger.warning(
            "Bug 32: dropping document (history reserved fully) — history=%s, reserve=%s",
            history_chars, budget["history_reserve"],
        )
        engine_messages.append({"role": "user", "content": message})
    elif rag_context and available_chars > 0:
        rag_context = rag_context[:available_chars]
        _rag_instruction = {
            "ca": (
                "INFORMACIO RECUPERADA. UTILITZA-LA per respondre. "
                "Si la resposta es aqui, cita-la directament. "
                "Fonts: [DOCUMENTACIO DEL SISTEMA] = knowledge base del sistema, "
                "[DOCUMENTACIO TECNICA] = documents pujats per l'usuari, "
                "[MEMORIA DE L'USUARI] = coses que l'usuari t'ha dit abans. "
                "Quan et preguntin d'on saps algo, indica la font correcta. "
                "MAI diguis que ho saps pel teu entrenament si la info ve d'aqui:"
            ),
            "es": (
                "INFORMACION RECUPERADA. UTILIZALA para responder. "
                "Si la respuesta esta aqui, citala directamente. "
                "Fuentes: [DOCUMENTACION DEL SISTEMA] = knowledge base del sistema, "
                "[DOCUMENTACION TECNICA] = documentos subidos por el usuario, "
                "[MEMORIA DEL USUARIO] = cosas que el usuario te dijo antes. "
                "Cuando te pregunten de donde sabes algo, indica la fuente correcta. "
                "NUNCA digas que lo sabes por tu entrenamiento si la info viene de aqui:"
            ),
            "en": (
                "RETRIEVED INFORMATION. USE IT to answer. "
                "If the answer is here, cite it directly. "
                "Sources: [SYSTEM DOCUMENTATION] = system knowledge base, "
                "[TECHNICAL DOCUMENTATION] = documents uploaded by the user, "
                "[USER MEMORY] = things the user told you before. "
                "When asked where you know something from, indicate the correct source. "
                "NEVER say you know it from training if the info comes from here:"
            ),
        }
        _instr = _rag_instruction.get(_lang_key, _rag_instruction["en"])
        # B030 layer 2d: trusted source legend OUTSIDE the untrusted delimiters,
        # both in their own turn pair; the user's message arrives clean.
        context_block = f"{_instr}\n{wrap_untrusted_context(rag_context, _lang_key)}"
        engine_messages.extend(untrusted_context_turns(context_block, _lang_key))
        engine_messages.append({"role": "user", "content": message})
        _ctx_injected = True
    else:
        if rag_context:
            # The whole #965 story is that silent context loss is the bug: the
            # document drop above warns, this one did not — and it is how an
            # exhausted budget (negative available_chars) stayed invisible.
            logger.warning(
                "Dropping retrieved context: budget exhausted (available_chars=%d, history=%d)",
                available_chars, history_chars,
            )
        engine_messages.append({"role": "user", "content": message})
    return engine_messages, _doc_truncated_pct, _ctx_injected


# Slack the fit guard keeps between the estimated prompt and the engine's real
# window. The floor is _TRUNCATION_MARGIN_TOKENS from the MLX plugin, for the
# same reason: the chat template adds tokens nobody counted here (role headers,
# BOS, the assistant's opening turn).
#
# The 5% is the OTHER error, and it does not scale with a flat number: this file
# measures in chars at 4 chars/token, and the note above PROMPT_BUDGET_RATIO
# says why that runs optimistic — Catalan and Spanish are denser, so a prompt
# estimated at 8000 tokens can really be 8400. With a flat 256, a 32768-token
# window was guarded to 99.2% of itself by an estimate known to undercount, and
# the guard would have declared a prompt that fits one that does not.
PROMPT_FIT_MARGIN_TOKENS = 256
PROMPT_FIT_MARGIN_RATIO = 0.05


_ELISION = "\n\n[…]\n\n"


def _trim_turn_content(message: dict, budget_chars: int) -> str:
    """Cut one turn's text down to ``budget_chars``, losing the least useful part.

    Taking the first N chars is the obvious move and it is wrong for the shape
    this path actually sees: someone pastes a long text and asks the question
    UNDERNEATH it. Cutting the tail throws away the question and leaves the
    model answering nothing in particular — silent, and the user cannot tell.
    So a user turn keeps its head AND its tail with the cut marked in between.

    An assistant turn is the continue path (FD-S6): the generation has to resume
    from where it stopped, so what matters there is the END. Its head is what
    goes.
    """
    text = message.get("content") or ""
    if budget_chars <= 0 or len(text) <= budget_chars:
        return text[:budget_chars] if budget_chars > 0 else ""
    if message.get("role") == "assistant":
        return text[-budget_chars:]
    room = budget_chars - len(_ELISION)
    if room <= 0:
        return text[:budget_chars]
    head = (room * 7) // 10
    return text[:head] + _ELISION + text[-(room - head):]


def _keep_newest_that_fit(messages: list, remaining: int) -> tuple:
    """The newest turns that fit in ``remaining`` chars, and what they weigh.

    Walks from the most recent backwards, keeping whole messages while they fit;
    one that does not is dropped, never cut in half (that would break role
    alternation and the chat template). The most recent message is evaluated
    first and always kept — even alone, and even if it alone exceeds the budget,
    so this never emits zero turns and the caller trims that one turn instead.
    """
    kept: list = []
    running = 0
    for msg in reversed(messages):
        cost = len(msg.get("content") or "")
        if kept and running + cost > remaining:
            break
        kept.append(msg)
        running += cost
    kept.reverse()
    return kept, running


def fit_prompt_to_window(
    system: str,
    messages: list,
    window_tokens: int,
    reply_budget_tokens: int = 0,
) -> tuple:
    """Drop whole turns, oldest first, until the assembled prompt fits the window.

    #976 / ADR-006's invariant ("the assembled prompt never exceeds the engine's
    window"), enforced where the prompt is actually assembled instead of trusted
    to the arithmetic upstream. llama.cpp does not truncate an oversized prompt:
    it raises ("Requested tokens exceed context window", llama_cpp/llama.py) and
    the turn dies. MLX truncates inside its plugin (truncate_messages_to_budget)
    and Ollama truncates server-side; llama.cpp has no enforcement of its own.

    compute_context_budget decides what the turn may KEEP; this checks what was
    actually ASSEMBLED — for every engine, at both doors. The two can disagree:
    the budget reasons about the document and the retrieved context, and knows
    nothing about the history the caller then prepends, the clock line, or the
    untrusted-context wrapper.

    Contract copied from the MLX helper, and carried out by
    _keep_newest_that_fit: whole turns go, oldest first, and it never returns
    zero turns.

    Estimation is by chars (CHARS_PER_TOKEN_ESTIMATE). The core cannot reach a
    plugin's tokenizer — the layering gate keeps core → plugins at zero — so the
    margin above is what covers the difference between the estimate and the
    tokens the engine really counts.

    Returns (messages, trimmed): `trimmed` is True when anything was dropped or
    cut, so the caller can say so rather than shrinking the prompt in silence.
    """
    if not messages:
        return messages, False

    # A reply reserve bigger than the window is a caller mistake (a client
    # asking /v1 for max_tokens=8192 on a 2048-token engine); clamp it rather
    # than letting it drive the budget negative and empty the prompt.
    reply_reserve = max(0, min(int(reply_budget_tokens or 0), window_tokens // 2))
    margin = max(PROMPT_FIT_MARGIN_TOKENS, int(window_tokens * PROMPT_FIT_MARGIN_RATIO))
    budget_chars = (window_tokens - reply_reserve - margin) * CHARS_PER_TOKEN_ESTIMATE
    remaining = budget_chars - len(system or "")

    if remaining <= 0:
        # The system prompt alone fills the window. There is no honest trim
        # here: an empty prompt is useless and a floor would be the same lie
        # MIN_BUDGET_WINDOW_TOKENS was (see the note above
        # resolve_max_context_chars). Say it loudly and let the newest turn go
        # through as it is — the estimate is conservative, so it may still fit.
        logger.error(
            "System prompt (%d chars) leaves no room in a %d-token window: "
            "the turn is sent unfitted and the engine may reject it",
            len(system or ""), window_tokens,
        )
        return messages[-1:], len(messages) > 1

    kept, running = _keep_newest_that_fit(messages, remaining)
    trimmed = len(kept) < len(messages)

    # The newest turn on its own can still overflow (a document pasted into the
    # message itself). Cutting its content is the last resort: dropping it would
    # send no user turn at all, and keeping it whole is the dead turn #976 is
    # about.
    if len(kept) == 1 and running > remaining:
        kept = [dict(kept[0], content=_trim_turn_content(kept[0], remaining))]
        trimmed = True

    if trimmed:
        # `running` is what the kept turns weighed BEFORE the last-resort trim;
        # reporting it would claim 30000 chars were kept when 2468 were.
        logger.warning(
            "Prompt did not fit the engine window (%d tok): kept %d of %d turns "
            "(%d chars of the %d available)",
            window_tokens, len(kept), len(messages),
            sum(len(m.get("content") or "") for m in kept), remaining,
        )
    return kept, trimmed
