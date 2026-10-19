"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/rag/profile.py
Description: What the user told the assistant about themselves, listed — not
             searched — so it reaches every turn.

Live 13/10/2026: the model greeted "Jordi" and said "tens 45 anys" on one turn
and took it back two turns later («no tinc cap font visible»). Both facts were
in `personal_memory`. The recall is by similarity to the question (threshold
0.3, top_k 2) and, after that, a limit of 3-5 hits across ALL collections in
which memory comes last: "com que no tens dades?" resembled none of them, and
three documents filled the limit anyway. ADR-002 §3 had decided "the chat
injects the exact facts first, then the vector top-k"; that step was never
wired (the history shows `("personal_memory", 0.3, 2)` identical on 20/06 and
25/08, before the turn pipeline existed).

So the facts the user stated are not retrieved: they are listed, newest first,
up to a ceiling, and travel outside the hit limit.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from core.memory_access import MEMORY_COLLECTION

logger = logging.getLogger(__name__)

#: Facts that go to every turn. ~15 short lines are ~300 tokens: a small local
#: model can carry them, and a user with more gets the newest (a warning says so).
PROFILE_MAX_FACTS = 15

#: Points read per page, and the most pages read. `scroll` has no ordering and
#: no filter of its own, so the whole collection is walked (it holds a person's
#: stated facts, not documents) up to a ceiling; the newest PROFILE_MAX_FACTS
#: of the user facts found are kept.
_SCROLL_PAGE = 200
_SCROLL_MAX_PAGES = 10

#: A fact longer than this is cut: the "~300 tokens" of PROFILE_MAX_FACTS holds
#: for short lines, and a long one must not decide the size of every turn.
_MAX_FACT_CHARS = 300

#: `type` of what the user stated (and the model saved with [MEM_SAVE:]).
#: Not `fact`: that is what the memory API stores for anything else (tests,
#: documents that call themselves memory).
PROFILE_TYPES = frozenset({"user_fact"})


@dataclass
class ProfileHit:
    """A stated fact in the shape the context builder reads from a search hit."""

    id: str
    text: str
    collection: str = MEMORY_COLLECTION
    score: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


def _created_at(payload: Dict[str, Any]) -> str:
    value = payload.get("created_at") or payload.get("saved_at") or ""
    return value if isinstance(value, str) else ""


async def _list_points(memory: Any) -> list:
    """Every point of the memory collection, page by page (ceiling: _SCROLL_MAX_PAGES)."""
    points: list = []
    offset = None
    for _ in range(_SCROLL_MAX_PAGES):
        scroll_result = await memory.scroll(collection=MEMORY_COLLECTION, limit=_SCROLL_PAGE, offset=offset)
        page, offset = scroll_result if isinstance(scroll_result, tuple) else (scroll_result, None)
        points.extend(page or [])
        if offset is None:
            break
    return points


def _fact_of(point: Any, now: datetime) -> "ProfileHit | None":
    """The stated fact a point holds, or None (empty, another type, expired)."""
    payload = getattr(point, "payload", None) or {}
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    if payload.get("type") not in PROFILE_TYPES or _expired(payload, now):
        return None
    text = text.strip()
    if len(text) > _MAX_FACT_CHARS:
        text = text[:_MAX_FACT_CHARS].rstrip() + "…"
    return ProfileHit(id=str(getattr(point, "id", "") or payload.get("original_id", "")),
                      text=text, metadata=dict(payload))


async def profile_hits(memory: Any, limit: int = PROFILE_MAX_FACTS) -> List[ProfileHit]:
    """The user's stated facts, newest first, at most `limit`. [] on any failure.

    A failure here must not cost the turn its other context, so it is logged
    and swallowed; the similarity search still runs.
    """
    try:
        if not await memory.collection_exists(MEMORY_COLLECTION):
            return []
        points = await _list_points(memory)
    except Exception as e:
        logger.warning("RAG profile: could not list the user's facts: %s", e)
        return []

    now = datetime.now(timezone.utc)
    facts: List[ProfileHit] = []
    seen: set = set()
    for point in points:
        fact = _fact_of(point, now)
        if fact is not None and fact.text not in seen:
            seen.add(fact.text)
            facts.append(fact)
    facts.sort(key=lambda h: _created_at(h.metadata), reverse=True)
    if len(facts) > limit:
        logger.info("RAG profile: %d stated facts, only the newest %d travel with the turn", len(facts), limit)
    return facts[:limit]


def _expired(payload: Dict[str, Any], now: datetime) -> bool:
    """True for a fact whose `expires_at` has passed. The similarity search drops
    these (documents.py); a listing has to as well, or `cleanup_expired` being
    late would put a dead fact back into every turn. No/unreadable date = alive."""
    raw = payload.get("expires_at")
    if not isinstance(raw, str) or not raw:
        return False
    try:
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when <= now
