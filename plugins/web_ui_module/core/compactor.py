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
import re as _re

logger = logging.getLogger(__name__)


def _clean_for_compact(txt: str) -> str:
    """Neteja tags de thinking per compactar."""
    txt = _re.sub(r'<think>.*?</think>', '', txt, flags=_re.DOTALL)
    txt = _re.sub(r'<\|thinking\|>.*?<\|/thinking\|>', '', txt, flags=_re.DOTALL)
    return txt.strip()


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

        summary_result = await engine.chat(
            messages=[{"role": "user", "content": compact_prompt}],
            system="Ets un assistent que fa resums breus i precisos de converses."
        )

        summary = ""
        if isinstance(summary_result, dict):
            if "message" in summary_result and isinstance(summary_result["message"], dict):
                summary = summary_result["message"].get("content", "")
            elif "response" in summary_result:
                summary = summary_result["response"]
            elif "content" in summary_result:
                summary = summary_result["content"]
            elif "choices" in summary_result:
                choices = summary_result["choices"]
                if choices:
                    summary = choices[0].get("message", {}).get("content", "")
        elif isinstance(summary_result, str):
            summary = summary_result

        if summary:
            session.apply_compaction(summary)
            session_manager._save_session_to_disk(session)
            logger.info("Session %s: compaction done (%d chars summary)", session.id[:8], len(summary))
        else:
            logger.warning("Session %s: compaction returned empty summary", session.id[:8])
    except Exception as e:
        logger.warning("Compaction failed: %s", e)
