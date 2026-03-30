"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/core/compactor.py
Description: Context compacting per sessions llargues.
             Extret de manifest.py durant normalitzacio.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os as _os
import re as _re

logger = logging.getLogger(__name__)

_SYSTEM_MSG = "Ets un assistent que fa resums breus i precisos de converses."


def _clean_for_compact(txt: str) -> str:
    """Neteja tags de thinking per compactar."""
    txt = _re.sub(r'<think>.*?</think>', '', txt, flags=_re.DOTALL)
    txt = _re.sub(r'<\|thinking\|>.*?<\|/thinking\|>', '', txt, flags=_re.DOTALL)
    return txt.strip()


def _is_ollama_engine(engine) -> bool:
    """Detecta si l'engine es OllamaModule (necessita model + messages, no system kwarg)."""
    cls_name = type(engine).__name__
    module_name = type(engine).__module__ or ""
    return "ollama" in cls_name.lower() or "ollama" in module_name.lower()


async def _call_engine(engine, messages, system_msg):
    """Crida engine.chat() adaptant-se al tipus d'engine (Ollama vs MLX/LlamaCpp)."""
    if _is_ollama_engine(engine):
        model_name = _os.getenv("NEXE_DEFAULT_MODEL", "llama3.2:3b")
        full_messages = [{"role": "system", "content": system_msg}] + messages
        result = engine.chat(model=model_name, messages=full_messages, stream=False)
        # OllamaModule.chat() es un async generator — consumir-lo
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
    else:
        # MLX/LlamaCpp accepten system= kwarg
        summary_result = await engine.chat(messages=messages, system=system_msg)
        if isinstance(summary_result, dict):
            if "message" in summary_result and isinstance(summary_result["message"], dict):
                return summary_result["message"].get("content", "")
            elif "response" in summary_result:
                return summary_result["response"]
            elif "content" in summary_result:
                return summary_result["content"]
            elif "choices" in summary_result:
                choices = summary_result["choices"]
                if choices:
                    return choices[0].get("message", {}).get("content", "")
        elif isinstance(summary_result, str):
            return summary_result
        return ""


async def compact_session(session, engine, session_manager):
    """
    Compacta una sessio amb massa missatges usant un resum LLM.

    Args:
        session: ChatSession instance
        engine: LLM engine amb metode chat()
        session_manager: SessionManager per save_to_disk
    """
    if not session.needs_compaction():
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

        if summary:
            session.apply_compaction(summary)
            session_manager._save_session_to_disk(session)
            logger.info("Session %s: compaction done (%d chars summary)", session.id[:8], len(summary))
        else:
            logger.warning("Session %s: compaction returned empty summary", session.id[:8])
    except Exception as e:
        logger.warning("Compaction failed: %s", e)
