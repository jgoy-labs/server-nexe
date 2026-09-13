"""One `recall` for both chat doors (ADR-007, C4.2).

Retrieval was the last step both doors ran *inside another step's function*:
`/ui/chat` did it in `_build_rag_context`, which `_build_turn_context` called
from the `budget` adapter, and `/v1` did it in `_fetch_rag_context`, which
`_build_rag_and_system_prompt` called from the same place. Both were folded,
and `core/turn/folded.py` counted them. Here the step is one function, and the
adapters call it as the step it is.

**What each door still decides for itself**, because it is the door's own
field and not the turn's behaviour: `/v1` asks only when `use_rag` is set,
`/ui/chat` skips retrieval when the session has an attached document (the
document is the context that turn already has). Everything below that — which
collections, which threshold, the log line, and the fact that a retrieval
failure is a turn without context and never a failed turn — is the same.

**What moved, deliberately, to `budget`.** The UI door used to sanitize the
retrieved text here (`_sanitize_rag_context`) with the serving engine's
window; the API door does it when it injects. That is the order the map
already has: `recall` runs BEFORE `engine`, so no window is known yet, and
the ceiling belongs where the text is fitted. So this returns the text as
retrieved, and both doors sanitize + trim it in `budget`, as `/v1` always did.

`app_state` is threaded through unused-but-declared: `build_rag_context` takes
it (it is FastAPI's app state in the signature) and never reads it — measured
on `core/endpoints/chat_rag.py`, where the only uses of the name are the
parameter and its docstring line. It stays in the call so the day it does read
it, the doors are already handing over the same thing.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def _build_rag_context(
    message: str,
    *,
    app_state: Any = None,
    lang: str = "en",
    collections: Optional[list] = None,
    threshold_override: Optional[float] = None,
) -> tuple[str, int, list]:
    """Recall from memory for this turn. Returns (text, count, items).

    F-D block 3: retrieval is `core.endpoints.chat_rag.build_rag_context` —
    the same per-collection thresholds, dedup and RAM-derived limit at both
    doors, instead of a second implementation with one flat threshold and no
    dedup.

    A retrieval that fails is a turn WITHOUT context, never a failed turn: the
    warning is the signal (#899), the empty tuple is the answer.
    """
    try:
        # Deferred, by module: `core.endpoints.chat_rag` executes
        # `core/endpoints/__init__.py` (which eagerly imports `.v1` -> `.chat`),
        # and both doors' tests patch `build_rag_context` ON that module — an
        # imported name would escape the patch.
        from core.endpoints import chat_rag

        logger.info("RAG: attempting recall (collections=%s)", collections or "all")
        rag_context, rag_items = await chat_rag.build_rag_context(
            message, app_state, lang,
            collections=collections,
            threshold_override=float(threshold_override) if threshold_override is not None else None,
        )
        rag_count = len(rag_items)
        if rag_count:
            logger.info("RAG: %s relevant memories", rag_count)
            for col, score in rag_items:
                logger.info("  RAG [%s] score=%.2f", col, score)
        return rag_context, rag_count, rag_items
    except Exception as e:
        logger.warning("RAG lookup failed: %s", e)
        return "", 0, []
