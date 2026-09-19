"""One `recall` for both chat doors (ADR-007, C4.2).

Retrieval was the last step both doors ran *inside another step's function*:
`/ui/chat` did it in `_build_rag_context`, which `_build_turn_context` called
from the `budget` adapter, and `/v1` did it in `_fetch_rag_context`, which
`_build_rag_and_system_prompt` called from the same place. Both were folded,
and `core/turn/folded.py` counted them. Here the step is one function, and the
adapters call it as the step it is.

**What each door still decides for itself**, because it is the door's own
field and not the turn's behaviour: `/v1` asks only when `use_rag` is set,
and `/ui/chat` narrows WHICH collections it asks for when the session has an
attached document — it drops the uploaded-documents one, because the document
IS that turn's knowledge, and keeps the rest. Until #1064 this paragraph said
it skipped retrieval altogether, and the adapter did exactly that: one
retrieval covers three collections, so personal memory went silent too on
every turn with a document open. The narrowing lives in
`plugins/web_ui_module/api/turn_adapters.py` (`recall`). Everything below that
— which threshold, the log line, and the fact that a retrieval failure is a
turn without context and never a failed turn — is the same.

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

from core.memory_access import KNOWLEDGE_COLLECTION, SYSTEM_COLLECTIONS

logger = logging.getLogger(__name__)


def collections_for_turn(
    toggled: Optional[list], *, has_document: bool,
) -> Optional[list]:
    """Which sources this turn asks, given the client's toggle and whether the
    session has a document attached. **The same answer at both doors** (C4.3).

    A session with an attached document already has ITS OWN knowledge for the
    turn, so searching the uploaded-documents collection again adds nothing —
    but only that one is dropped. Until #1064 the web door skipped retrieval
    whole, which also silenced personal memory on every turn with a document
    open; the rule was right and its width was not.

    This lived at the web door, and it could not stay there. The moment `/v1`
    accepts an attachment, a rule that hangs off one door's session means the
    two doors answer the same turn differently, and the I1 contract — one
    sequence, the door is a label and not a switch — stops being true. So the
    decision is the turn's, not the door's.

    `None` means "no toggle from the client": the baseline is the known system
    collections. An explicit list is honoured as given, INCLUDING an empty one
    — `[]` is "the user switched every source off", and turning it into a full
    list here would answer from personal memory against an opt-out, the
    privacy regression `chat_rag` warns about in its own comment.

    Collections a plugin registers at runtime stay out of these turns, exactly
    as they were when the step was skipped whole: narrowing to an explicit
    list is what makes dropping one possible, and widening past that is a
    separate question.
    """
    if not has_document:
        return toggled
    base = list(SYSTEM_COLLECTIONS) if toggled is None else list(toggled)
    return [c for c in base if c != KNOWLEDGE_COLLECTION]


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
