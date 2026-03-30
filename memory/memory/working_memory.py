"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/working_memory.py
Description: In-RAM working memory for current session. Volatile — dies on shutdown.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import atexit
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class WorkingMemory:
    """
    In-RAM working memory per session.

    Holds recent facts and context for fast retrieval.
    Flushes to staging every N turns or on shutdown.
    Isolated by (user_id, session_id) — zero cross-contamination.
    """

    def __init__(
        self,
        flush_callback: Optional[Callable] = None,
        flush_interval: int = 5,
    ):
        """
        Args:
            flush_callback: Called with entries list when flush triggers.
                            Signature: (entries: List[Dict]) -> None
            flush_interval: Flush every N add() calls (default 5).
        """
        self._entries: Dict[str, List[Dict[str, Any]]] = {}
        self._turn_counts: Dict[str, int] = {}
        self._flush_callback = flush_callback
        self._flush_interval = flush_interval
        self._lock = threading.Lock()
        self._shutdown_registered = False

    def _session_key(self, user_id: str, session_id: str) -> str:
        return f"{user_id}:{session_id}"

    def add(
        self,
        user_id: str,
        session_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Add a fact to working memory.

        Returns entry ID. Auto-flushes every flush_interval adds.
        """
        key = self._session_key(user_id, session_id)
        entry = {
            "id": f"wm-{len(self._entries.get(key, []))}",
            "user_id": user_id,
            "session_id": session_id,
            "content": content,
            "metadata": metadata or {},
            "added_at": datetime.now(timezone.utc).isoformat(),
        }

        with self._lock:
            if key not in self._entries:
                self._entries[key] = []
                self._turn_counts[key] = 0
            self._entries[key].append(entry)
            self._turn_counts[key] += 1

            if not self._shutdown_registered:
                atexit.register(self._atexit_flush)
                self._shutdown_registered = True

            if self._turn_counts[key] >= self._flush_interval:
                self._do_flush(key)

        return entry["id"]

    def search(
        self,
        user_id: str,
        session_id: str,
        query: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search working memory with basic keyword matching.

        Returns entries sorted by relevance (simple keyword overlap).
        """
        key = self._session_key(user_id, session_id)

        with self._lock:
            entries = self._entries.get(key, [])

        if not entries:
            return []

        query_lower = query.lower()
        query_words = set(query_lower.split())

        scored = []
        for entry in entries:
            content_lower = entry["content"].lower()
            content_words = set(content_lower.split())

            # Keyword overlap scoring
            if not query_words:
                score = 0.0
            else:
                overlap = len(query_words & content_words)
                score = overlap / len(query_words)

            # Substring bonus
            if query_lower in content_lower:
                score += 0.3

            if score > 0:
                scored.append({**entry, "score": min(1.0, score)})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    def get_all(
        self,
        user_id: str,
        session_id: str,
    ) -> List[Dict[str, Any]]:
        """Get all entries for a session."""
        key = self._session_key(user_id, session_id)
        with self._lock:
            return list(self._entries.get(key, []))

    def count(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> int:
        """Count entries. If user_id+session_id given, count that session only."""
        with self._lock:
            if user_id and session_id:
                key = self._session_key(user_id, session_id)
                return len(self._entries.get(key, []))
            return sum(len(v) for v in self._entries.values())

    def flush_to_staging(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> int:
        """
        Flush entries to staging via callback.

        If user_id + session_id given, flush only that session.
        Otherwise flush all.
        Returns number of entries flushed.
        """
        total = 0
        with self._lock:
            if user_id and session_id:
                key = self._session_key(user_id, session_id)
                total = self._do_flush(key)
            else:
                keys = list(self._entries.keys())
                for key in keys:
                    total += self._do_flush(key)
        return total

    def _do_flush(self, key: str) -> int:
        """Flush a single session's entries. Must be called under lock."""
        entries = self._entries.get(key, [])
        if not entries:
            return 0

        count = len(entries)
        if self._flush_callback:
            try:
                self._flush_callback(list(entries))
            except Exception as e:
                logger.error("Working memory flush failed: %s", e)
                return 0

        self._entries[key] = []
        self._turn_counts[key] = 0
        logger.debug("Flushed %d entries from working memory (%s)", count, key)
        return count

    def clear(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> int:
        """Clear entries without flushing. Returns count cleared."""
        with self._lock:
            if user_id and session_id:
                key = self._session_key(user_id, session_id)
                count = len(self._entries.get(key, []))
                self._entries.pop(key, None)
                self._turn_counts.pop(key, None)
                return count
            count = sum(len(v) for v in self._entries.values())
            self._entries.clear()
            self._turn_counts.clear()
            return count

    def _atexit_flush(self):
        """Safety net: flush all on interpreter shutdown."""
        try:
            self.flush_to_staging()
        except Exception as e:
            logger.error("atexit flush failed: %s", e)


__all__ = ["WorkingMemory"]
