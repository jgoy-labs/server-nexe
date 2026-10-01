"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/turn/persist.py
Description: The assistant turn, written into the session (C4.4, moved from routes_chat.py).

`resume` is the web door's `continue` (FD-S6): the tail merges into the
truncated turn. It dies as a separate path at C4.6.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from typing import Any

from core.turn.text import clean as text_clean

logger = logging.getLogger(__name__)


def persist_assistant_turn(
    session: Any,
    clean_response: str,
    full_response: str,
    stats: dict,
    trunc: bool,
    trunc_continuable: bool,
    *,
    resume: bool = False,
) -> None:
    """Write the assistant turn into the session (FD-S6 merge or add_message).

    Sync on purpose: it is called from the streaming body between
    `_save_session_to_disk` and the `_assistant_saved` flag, and that ordering
    is what keeps the single-persist contract (INV-CRIT-03) intact — an `await`
    here would open a cancellation point in the middle of it.
    """
    if resume and session.messages \
            and session.messages[-1].get("role") == "assistant":
        # FD-S6: MERGE the tail into the truncated turn — direct
        # concatenation, no separator (the tail resumes mid-sentence).
        # Never add_message: get_context_messages dedupes consecutive
        # assistant turns keeping only the LATEST, which would erase
        # the first half of the answer.
        _last = session.messages[-1]
        _last["content"] += clean_response
        if trunc and trunc_continuable:
            # Chained continue (truncated again): extend the raw so
            # the NEXT continue prompt stays an exact token prefix.
            if _last.get("gen_raw"):
                _last["gen_raw"] += full_response
            else:
                _last["gen_raw"] = _last["content"]
        else:
            _last.pop("gen_raw", None)  # completed: drop the raw
    else:
        session.add_message("assistant", clean_response, stats=stats)
        if trunc and trunc_continuable and session.messages:
            # FD-S6: persist the RAW generation next to the clean
            # content. With thinking ON the clean text's re-render
            # diverges token-wise from the KV cache entry — gen_raw is
            # what makes the future continue prompt an exact prefix.
            session.messages[-1]["gen_raw"] = full_response


def persist_partial_assistant(
    session: Any, session_mgr: Any, full_response: str, message: str, *, resume: bool = False,
) -> None:
    """Best-effort persist of an interrupted turn (MC-116), for the `finally`.

    Sync on purpose: the caller runs this while unwinding a GeneratorExit, where
    awaiting is not an option. Never raises — a failure to save a partial turn
    must not replace the original teardown.
    """
    try:
        _partial_clean, _, _ = text_clean.clean_full_response(full_response, message)
        _partial_clean = text_clean.think_only_placeholder(_partial_clean, full_response)
        if _partial_clean and resume and session.messages \
                and session.messages[-1].get("role") == "assistant":
            # FD-S6 (MC-116): interrupted continue → merge the partial
            # tail in-place, same no-separator contract as the clean
            # path (add_message would trip the consecutive-role dedupe).
            _last = session.messages[-1]
            _last["content"] += _partial_clean
            # The answer is still cut. Keep the raw prefix so the NEXT
            # Continue stays an exact token prefix — the same rule as a
            # truncated merge. Dropping gen_raw here made that next resume
            # render the cleaned text and miss the cache when thinking was on.
            if _last.get("gen_raw"):
                _last["gen_raw"] += full_response
            # #1106: merged in memory only, until now — the tail was lost if
            # nothing else saved the session before a restart.
            session_mgr._save_session_to_disk(session)
        elif _partial_clean:
            session.add_message("assistant", _partial_clean, stats={"interrupted": True})
            session_mgr._save_session_to_disk(session)
    except Exception:
        logger.warning("MC-116: could not persist partial assistant on stream interruption", exc_info=True)
