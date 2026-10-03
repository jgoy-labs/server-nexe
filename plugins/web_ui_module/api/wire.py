"""
------------------------------------
Server Nexe
Location: plugins/web_ui_module/api/wire.py
Description: Most of the web door's alphabet: the NUL sentinels built
             outside the stream loop that `nexe-chat.js` and the CLI read
             (model, engine, RAG, loading, truncation, pending delete), the
             curated engine-error notices and the stats a saved answer
             carries. The stream's own markers (MODEL_READY in
             engine_call.py; COMPACT, MEM, WILL_COMPACT in turn_adapters.py)
             are written where they happen. Split out of routes_chat.py
             (2026-10-04).

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import logging
from typing import TYPE_CHECKING, Any

from core.turn.errors import is_oom_error

if TYPE_CHECKING:  # an annotation only: no import-time edge to core.memory_facts
    from core.memory_facts import intents as memory_intents

logger = logging.getLogger(__name__)


def _build_mem_stats(
    session: Any,
    rag_count: int,
    rag_items: list,
    model_name: "str | None",
    elapsed: float,
    full_response_len: int,
    mem_saved_count: int,
    mem_saves: list,
    engine_name: "str | None" = None,
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
        "engine": str(engine_name)[:30] if engine_name else None,
        "rag_count": rag_count if rag_count > 0 else None,
        "rag_avg": rag_avg_val,
        "rag_items": saved_rag_items,
        "mem_saved": mem_saved_count if mem_saved_count > 0 else None,
        "mem_facts": saved_facts,
    }


def model_token(model_name) -> str:
    """The MODEL token. The web client and the CLI keep the last one they
    read, so a turn answered by a fallback sends a second one (#1035)."""
    _safe_model = str(model_name).replace("\x00", "").replace("]", "")[:100]
    return f"\x00[MODEL:{_safe_model}]\x00"


def engine_token(engine_name) -> str:
    """The ENGINE token (#1146): which engine answers — sent when one claims
    the turn, so a fallback's is the last one the client reads, as with MODEL.
    Jordi, 03/10: «posa'm el motor al peu» (the footer only named the model)."""
    _safe = str(engine_name).replace("\x00", "").replace("]", "")[:30]
    return f"\x00[ENGINE:{_safe}]\x00"


async def _yield_response_headers(
    model_name: str,
    rag_count: int,
    rag_items: list,
    compacted: bool,
    compaction_count: int,
    doc_truncated_pct: int,
):
    """Yield the header tokens: MODEL, RAG*, COMPACT, DOC_TRUNCATED."""
    yield model_token(model_name)
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
    # Review 04/10: the text can echo what the user wrote (a fact, a «not
    # found» for their own words), and this path does not pass the stream's
    # guard. A stray NUL breaks the web's sentinel parity (#1139): nothing
    # after it would show. The sentinels are the only NULs on this wire.
    rendered = f"\x00[MODEL:nexe-system]\x00{(outcome.text or '').replace(chr(0), '')}"
    if outcome.deleted_facts:
        facts_pipe = "|".join(f.replace("\x00", "")[:80] for f in outcome.deleted_facts[:5])
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
    # never in the chat body; the user sees a curated message below. The
    # exception itself, not True: this runs from a `Failed` event, outside
    # any `except`, where True logs "NoneType: None" (#1117).
    logger.error("Streaming error: %s", err_msg, exc_info=exc)
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
