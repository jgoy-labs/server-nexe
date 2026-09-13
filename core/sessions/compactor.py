"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/sessions/compactor.py
Description: Context compacting for long sessions.
             Lives with the sessions it summarises (ADR-007 C3.4): both
             doors compact, so this cannot be the UI plugin's.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import re as _re

logger = logging.getLogger(__name__)

_SYSTEM_MSG = "Ets un assistent que fa resums breus i precisos de converses."


def _clean_for_compact(txt: str) -> str:
    """Cleans thinking tags for compaction."""
    txt = _re.sub(r'<think>.*?</think>', '', txt, flags=_re.DOTALL)
    txt = _re.sub(r'<\|thinking\|>.*?<\|/thinking\|>', '', txt, flags=_re.DOTALL)
    return txt.strip()


def _is_ollama_engine(engine) -> bool:
    """Detects if the engine is OllamaModule (needs model + messages, no system kwarg)."""
    cls_name = type(engine).__name__
    module_name = type(engine).__module__ or ""
    return "ollama" in cls_name.lower() or "ollama" in module_name.lower()


async def _call_engine_ollama(engine, messages, system_msg) -> str:
    """Calls Ollama engine and consumes the async-generator response."""
    from core.runtime_state import get_with_env_fallback  # import for runtime fallback
    model_name = get_with_env_fallback("NEXE_DEFAULT_MODEL", "llama3.2:3b")
    full_messages = [{"role": "system", "content": system_msg}] + messages
    result = engine.chat(model=model_name, messages=full_messages, stream=False)
    summary = ""
    async for chunk in result:
        if isinstance(chunk, dict):
            msg = chunk.get("message", {})
            if isinstance(msg, dict):
                summary += msg.get("content", "")
            elif chunk.get("response"):
                summary += chunk["response"]
        elif isinstance(chunk, str):
            summary += chunk
    return summary


def _extract_mlx_content(summary_result) -> str:
    """Extracts content string from MLX/LlamaCpp chat() return value."""
    if isinstance(summary_result, dict):
        if "message" in summary_result and isinstance(summary_result["message"], dict):
            return summary_result["message"].get("content", "")
        if "response" in summary_result:
            return summary_result["response"]
        if "content" in summary_result:
            return summary_result["content"]
        if "choices" in summary_result:
            choices = summary_result["choices"]
            if choices:
                return choices[0].get("message", {}).get("content", "")
    if isinstance(summary_result, str):
        return summary_result
    return ""


async def _call_engine(engine, messages, system_msg):
    """Calls engine.chat() adapting to the engine type (Ollama vs MLX/LlamaCpp)."""
    if _is_ollama_engine(engine):
        return await _call_engine_ollama(engine, messages, system_msg)
    # MLX/LlamaCpp accept system= kwarg
    summary_result = await engine.chat(messages=messages, system=system_msg)
    return _extract_mlx_content(summary_result)


async def compact_session(session, engine, session_manager, *, cancel_event=None):
    """
    Compacts a session with too many messages using an LLM summary.

    Args:
        session: ChatSession instance
        engine: LLM engine with chat() method
        session_manager: SessionManager for save_to_disk
        cancel_event: (C2.2) set by the engine gate when a user turn has to
            wait for this background job's slot. Checked ONLY after the LLM
            call returns — the summary was already paid for, but a preempted
            compaction is never APPLIED: `apply_compaction` would otherwise
            race a user turn that appended new messages while this call was
            in flight, resumming a slice of the conversation that no longer
            matches `get_messages_to_compact()`'s current view.
    """
    # #965: ask the engine that is about to serve the turn how much it can hold,
    # so the same history compacts on a 4096-token model and does not on a 32768.
    from core.context_window import ask_engine_window

    if not session.needs_compaction(ask_engine_window(engine)):
        return

    to_compact = session.get_messages_to_compact()
    if not to_compact:
        return

    try:
        compact_text = "\n".join(
            f"{m['role']}: {_clean_for_compact(m['content'][:1500])}"
            for m in to_compact
        )
        prev_summary = f"Resum anterior: {session.context_summary}\n\n" if session.context_summary else ""
        compact_prompt = (
            f"{prev_summary}"
            f"Resumeix aquesta conversa en 2-3 frases curtes. "
            f"Inclou: tema principal, decisions preses, i informacio clau. "
            f"Respon NOMES amb el resum, res mes.\n\n{compact_text}"
        )

        summary = await _call_engine(
            engine,
            [{"role": "user", "content": compact_prompt}],
            _SYSTEM_MSG,
        )

        if cancel_event is not None and cancel_event.is_set():
            logger.info("Session %s: compaction preempted by a user turn, not applied", session.id[:8])
            return

        if summary:
            # The slice actually summarised, not "the last COMPACT_KEEP" at
            # apply time — a user turn queued between the LLM call above and
            # this line must not lose its own message (C2.2).
            session.apply_compaction(summary, compacted_count=len(to_compact))
            session_manager._save_session_to_disk(session)
            logger.info("Session %s: compaction done (%d chars summary)", session.id[:8], len(summary))
        else:
            logger.warning("Session %s: compaction returned empty summary", session.id[:8])
    except Exception as e:
        logger.warning("Compaction failed: %s", e)
