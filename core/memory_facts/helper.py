"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/memory_facts/helper.py
Description: Memory integration with intent detection for contextual memory storage.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio as _asyncio
import re
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple, List

from core.endpoints.chat_sanitization import _filter_rag_injection
from core.memory_access import KNOWLEDGE_COLLECTION, MEMORY_COLLECTION, get_memory_view
from core.memory_facts.intent_patterns import (  # noqa: F401 - re-exported for callers and tests
    CLEAR_ALL_CONFIRM_RE,
    CLEAR_ALL_CONFIRM_TRIGGERS,
    CLEAR_ALL_RE,
    CLEAR_ALL_TRIGGERS,
    DELETE_RE,
    DELETE_TRIGGERS,
    LIST_RE,
    LIST_TRIGGERS,
    RECALL_PATTERNS,
    RECALL_RE,
    SAVE_RE,
    SAVE_TRIGGERS,
)
from core.memory_facts.intent_patterns import (
    detect_delete_intent as detect_delete_intent_text,
    detect_intent as detect_intent_text,
    detect_save_intent as detect_save_intent_text,
    matches_clear_all_confirm as matches_clear_all_confirm_text,
)

logger = logging.getLogger(__name__)

# ============================================
# MEMORY MANAGEMENT CONFIG
# ============================================
MAX_MEMORY_ENTRIES = 500          # Maximum entries in personal_memory
SIMILARITY_THRESHOLD = 0.80       # Do not save if similarity > 80% (lowered from 0.85)
PRUNE_BATCH_SIZE = 30             # How many entries to remove when the limit is exceeded
TEMPORAL_DECAY_DAYS = 7           # Days to apply temporal decay (recent = bonus)
MIN_IMPORTANCE_SCORE = 0.3        # Minimum to save (filters out chatter)
DELETE_THRESHOLD = 0.20           # Threshold for delete search. History: 0.82 → 0.70 → 0.55 → 0.20 (bug #18 e2e 2026-04-15). Low threshold guarantees the fact is found even with paraphrase-multilingual scoring. IMPORTANT: only the top-1 result is deleted (see delete_from_memory), so a low threshold is safe — we find more candidates but only act on the best match.

# Memory types for structured storage
MEMORY_TYPES = {
    "fact": 1.0,           # Stable data (name, job) - maximum retention
    "preference": 0.9,     # User preferences
    "contextual": 0.6,     # Situational info ("I'm tired today")
    "conversation": 0.4,   # Pure conversation logs
}


class MemoryHelper:
    """Helper class for memory operations with intent detection and smart extraction."""

    def __init__(self):
        self._memory_api = None
        self.save_triggers = SAVE_RE
        self.recall_regex = RECALL_RE
        self.delete_triggers = DELETE_RE
        self.list_triggers = LIST_RE
        self.clear_all_triggers = CLEAR_ALL_RE
        self.clear_all_confirm_triggers = CLEAR_ALL_CONFIRM_RE
        # Patterns to detect chatter (do not save)
        self.skip_patterns = [
            re.compile(r'^(hola|hey|ei|bon dia|bona tarda|bones|adéu|fins aviat)', re.IGNORECASE),
            re.compile(r'^(hi|hello|hey|good morning|bye|goodbye)', re.IGNORECASE),
            re.compile(r'^(gracias|gràcies|thanks|ok|vale|d\'acord|entendido)', re.IGNORECASE),
        ]

    def _is_trivial_message(self, message: str) -> bool:
        """Check if message is trivial (greeting, thanks, etc.) - don't save."""
        message = message.strip()
        if len(message) < 10:
            return True
        for pattern in self.skip_patterns:
            if pattern.match(message):
                return True
        return False

    @staticmethod
    def _retry_still_cooling() -> bool:
        """F3: Returns True if the failure cooldown has NOT elapsed yet (caller should return None)."""
        elapsed = time.monotonic() - _memory_api_last_failure_ts if _memory_api_last_failure_ts else None
        return elapsed is not None and elapsed < _MEMORY_API_RETRY_INTERVAL_S

    @staticmethod
    def _reset_failure_and_log() -> None:
        """Reset failure flags before a retry attempt and log the retry."""
        global _memory_api_init_failed, _memory_api_last_failure_ts
        elapsed = time.monotonic() - _memory_api_last_failure_ts if _memory_api_last_failure_ts else None
        logger.warning(
            "MemoryAPI: retrying initialization after %.0fs (previous failure %.0fs ago)",
            _MEMORY_API_RETRY_INTERVAL_S,
            elapsed if elapsed is not None else 0,
        )
        _memory_api_init_failed = False
        _memory_api_last_failure_ts = None

    @staticmethod
    async def _create_memory_api():
        """Obtain the filtered memory view and ensure this plugin's collections.

        Bug #19a — creates missing collections only; never deletes/recreates existing ones.
        D-M — never constructs a private API. If the porter fails, the caller sees None.
        """
        view = await get_memory_view("web_ui_module")
        logger.info("Memory view obtained from core.memory_access")
        for coll_name in view.filter_requested((MEMORY_COLLECTION, KNOWLEDGE_COLLECTION)):
            if not await view.collection_exists(coll_name):
                await view.create_collection(coll_name)
                logger.info("Created memory collection %s", coll_name)
        return view

    async def get_memory_api(self):
        """Get or initialize Memory API instance (module-level singleton, thread-safe)."""
        global _memory_api_instance, _memory_api_init_failed, _memory_api_last_failure_ts
        if _memory_api_instance is not None:
            self._memory_api = _memory_api_instance
            return _memory_api_instance
        if _memory_api_init_failed:
            # F3: check whether the retry interval has elapsed. If not, skip.
            # elapsed=None means no timestamp recorded (should not happen in production
            # since L317 always sets it, but treat as "eligible for retry" to avoid
            # permanent silence when the flag is set without a timestamp).
            if self._retry_still_cooling():
                return None
        async with _memory_init_lock:
            # Double-check after acquiring lock (handles concurrent callers and the
            # F3 retry case: reset the failure flags here so only one coroutine resets
            # them, avoiding a race where two callers both see elapsed>=60s and both
            # attempt a double-init in sequence).
            if _memory_api_instance is not None:
                self._memory_api = _memory_api_instance
                return _memory_api_instance
            if _memory_api_init_failed:
                # Still failed after acquiring lock — we are the retry caller.
                if self._retry_still_cooling():
                    return None
                self._reset_failure_and_log()
            try:
                api = await self._create_memory_api()
                _memory_api_instance = api
                logger.info("MemoryAPI singleton initialized and cached")
            except Exception as e:
                logger.error("Failed to initialize Memory API: %s", e)
                _memory_api_init_failed = True
                _memory_api_last_failure_ts = time.monotonic()
                return None
        self._memory_api = _memory_api_instance
        return _memory_api_instance

    def _detect_save_intent(self, message: str) -> Optional[str]:
        """Forwarder to core.memory_facts.intent_patterns (dies at C3.1)."""
        return detect_save_intent_text(message)

    def _detect_delete_intent(self, message: str) -> Optional[str]:
        """Forwarder to core.memory_facts.intent_patterns (dies at C3.1)."""
        return detect_delete_intent_text(message)

    def detect_intent(self, message: str) -> Tuple[str, Optional[str]]:
        """Forwarder to core.memory_facts.intent_patterns (dies at C3.1)."""
        return detect_intent_text(message)

    def matches_clear_all_confirm(self, message: str) -> bool:
        """Forwarder to core.memory_facts.intent_patterns (dies at C3.1)."""
        return matches_clear_all_confirm_text(message)

    async def _check_duplicate(self, content: str, memory) -> bool:
        """
        Check if similar content already exists in memory.

        Returns True if duplicate found (should skip saving).
        """
        try:
            results = await memory.search(
                query=content,
                collection=MEMORY_COLLECTION,
                top_k=1
            )
            if results and len(results) > 0:
                # If similarity > threshold, it is a duplicate
                if results[0].score >= SIMILARITY_THRESHOLD:
                    logger.debug(f"Duplicate detected (score={results[0].score:.2f}), skipping save")
                    return True
            return False
        except Exception as e:
            logger.warning(f"Duplicate check failed: {e}")
            return False  # When in doubt, save

    def _calculate_retention_score(self, entry) -> float:
        """
        Calculate retention score for an entry (higher = keep, lower = prune).

        Formula: type_weight * 0.4 + access_score * 0.3 + recency_score * 0.3
        """
        try:
            meta = entry.metadata or {}

            # 1. Type weight (facts more important than conversations)
            memory_type = meta.get("type", "conversation")
            type_weight = MEMORY_TYPES.get(memory_type, 0.4)

            # 2. Access count (frequently accessed = important)
            access_count = meta.get("access_count", 0)
            access_score = min(1.0, access_count / 10)  # Normalize to 0-1

            # 3. Recency score (recent = higher, but decays over time)
            saved_at = meta.get("saved_at", "")
            recency_score = 0.5  # Default middle score
            if saved_at:
                try:
                    saved_date = datetime.fromisoformat(saved_at)
                    if saved_date.tzinfo is None:
                        saved_date = saved_date.replace(tzinfo=timezone.utc)
                    days_old = (datetime.now(timezone.utc) - saved_date).days
                    # Decay: 1.0 at day 0, 0.5 at TEMPORAL_DECAY_DAYS, approaches 0.1 after
                    recency_score = max(0.1, 1.0 - (days_old / (TEMPORAL_DECAY_DAYS * 3)))
                except Exception as e:
                    logger.debug("Recency score calculation failed: %s", e)

            # Combined score
            retention = (type_weight * 0.4) + (access_score * 0.3) + (recency_score * 0.3)
            return retention

        except Exception as e:
            logger.debug(f"Retention score calc error: {e}")
            return 0.5  # Default mid-score

    async def _prune_old_entries(self, memory) -> int:
        """
        Smart pruning: Remove entries with LOWEST retention score.

        Retention score considers:
        - Memory type (facts > preferences > contextual > conversation)
        - Access frequency (more accessed = more important)
        - Recency (recent gets bonus, but old facts still preserved)

        Returns number of entries pruned.
        """
        try:
            if not await memory.collection_exists(MEMORY_COLLECTION):
                return 0

            # Check count first to avoid unnecessary search
            current_count = await memory.count(MEMORY_COLLECTION)
            if current_count <= MAX_MEMORY_ENTRIES:
                return 0

            # Retrieve entries for scoring — search with broad query
            # (Qdrant has no scroll/list API via this wrapper, so we use
            # a minimal query to retrieve all entries by vector similarity)
            all_entries = await memory.search(
                query=" ",
                collection=MEMORY_COLLECTION,
                top_k=current_count
            )

            current_count = len(all_entries)
            if current_count <= MAX_MEMORY_ENTRIES:
                return 0

            # Calculate retention score for each entry
            scored_entries = []
            for entry in all_entries:
                retention = self._calculate_retention_score(entry)
                scored_entries.append((entry, retention))

            # Sort by retention score (lowest first = candidates for deletion)
            scored_entries.sort(key=lambda x: x[1])

            # Delete entries with lowest retention scores
            entries_to_remove = current_count - MAX_MEMORY_ENTRIES + PRUNE_BATCH_SIZE
            to_delete = scored_entries[:entries_to_remove]

            deleted = 0
            for entry, score in to_delete:
                try:
                    if hasattr(entry, 'id') and entry.id:
                        await memory.delete(entry.id, collection=MEMORY_COLLECTION)
                        deleted += 1
                        # MC-112: log the entry id, never its text (user PII).
                        logger.debug("Pruned entry %s (retention=%.2f)", entry.id, score)
                except Exception as e:
                    logger.warning(f"Failed to delete entry: {e}")

            logger.info(f"Smart prune: {deleted} low-retention entries removed (was {current_count})")
            return deleted

        except Exception as e:
            logger.warning(f"Memory pruning failed: {e}")
            return 0

    async def save_to_memory(
        self,
        content: str,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        collections: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Save content to memory with deduplication and size management.

        Args:
            content: text to save.
            session_id: session id (metadata).
            metadata: extra metadata.
            collections: user-selected RAG collections filter (Bug #10). If
                non-None and does not include 'personal_memory', the save is rejected.
        """
        try:
            # Bug #10: respect user collection filter
            if collections is not None and MEMORY_COLLECTION not in collections:
                logger.info("Memory collection disabled by user — save_to_memory rejected")
                return {
                    "success": False,
                    "document_id": None,
                    "message": "Memory collection disabled",
                }

            # Legacy Qdrant path (MemoryService integration via pipeline is
            # handled at the endpoint level, not here — keep this path clean
            # for backwards compatibility with existing tests and callers)
            memory = await self.get_memory_api()
            if not memory:
                return {
                    "success": False,
                    "message": "Memory API not available"
                }

            # 1. Check for duplicates - skip if very similar content exists
            # Honest contract: success=False so callers don't show fake "saved" badges
            # (Bug #4 part 2). Use `duplicate=True` flag to distinguish from real errors.
            if await self._check_duplicate(content, memory):
                return {
                    "success": False,
                    "document_id": None,
                    "duplicate": True,
                    "message": "Contingut similar ja existeix, no guardat"
                }

            # 2. Prune old entries if needed
            await self._prune_old_entries(memory)

            # 3. Save new content
            meta = metadata or {}
            meta["source"] = "web_ui"
            meta["session_id"] = session_id
            meta["saved_at"] = datetime.now(timezone.utc).isoformat()

            doc_id = await memory.store(
                text=content,
                collection=MEMORY_COLLECTION,
                metadata=meta
            )

            return {
                "success": True,
                "document_id": doc_id,
                "message": "Saved to memory"
            }
        except Exception as e:
            logger.error(f"Memory store error: {e}")
            return {
                "success": False,
                "message": f"Error saving to memory: {str(e)}"
            }

    @staticmethod
    def _extract_fact_text(r) -> str:
        """Extract human-readable text from a search result entry."""
        if hasattr(r, 'payload') and r.payload:
            text = r.payload.get("text", "")
            if text:
                return text
        if hasattr(r, 'metadata') and r.metadata:
            text = r.metadata.get("text", "")
            if text:
                return text
        return r.text if hasattr(r, 'text') and r.text else ""

    async def _search_delete_candidates(
        self, memory, content: str, collections: List[str]
    ) -> List[Dict[str, Any]]:
        """Search collections for delete candidates. Returns top-1 per collection,
        sorted by score (best match first). NEVER deletes anything."""
        candidates: List[Dict[str, Any]] = []
        # MC-015: track per-collection outcome so an all-collections failure
        # (e.g. Qdrant down) is NOT mistaken for a legitimate 'nothing found'.
        n_responded = 0  # collections the service answered (exists check / search OK)
        n_errors = 0
        last_error: Optional[Exception] = None
        for collection in collections:
            try:
                if not await memory.collection_exists(collection):
                    n_responded += 1
                    continue
                results = await memory.search(
                    query=content, collection=collection, top_k=5, threshold=DELETE_THRESHOLD
                )
                n_responded += 1
                for r in results[:1]:
                    candidates.append({
                        "id": str(r.id),
                        "collection": collection,
                        "text": self._extract_fact_text(r),
                        "score": round(r.score, 2),
                        "metadata": getattr(r, "metadata", None) or {},
                    })
            except Exception as e:
                n_errors += 1
                last_error = e
                # MC-015: a failed search is not the legitimate 0-results case.
                logger.warning("Delete search in %s failed: %s", collection, e)
        # MC-015: if EVERY collection errored (none responded), propagate so the
        # caller reports an error instead of a false 'nothing found'. Partial
        # resilience is preserved: a single responding collection suppresses this.
        if not candidates and n_errors > 0 and n_responded == 0:
            raise last_error  # caught by delete_from_memory/preview → success:False
        candidates.sort(key=lambda c: c["score"], reverse=True)
        return candidates

    async def preview_delete_from_memory(
        self,
        content: str,
        collections: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """B028: dry-run of delete_from_memory — what WOULD be deleted, best first.

        Used by the 2-turn partial-delete confirmation: the pipeline shows the
        candidate to the user and only deletes (by exact id) after an explicit
        confirmation. Never mutates memory.
        """
        try:
            memory = await self.get_memory_api()
            if not memory:
                return {"success": False, "candidates": [], "message": "Memory API not available"}
            target_collections = collections if collections is not None else [MEMORY_COLLECTION, KNOWLEDGE_COLLECTION]
            candidates = await self._search_delete_candidates(memory, content, target_collections)
            return {"success": True, "candidates": candidates}
        except Exception as e:
            logger.error("Memory delete preview error: %s", e)
            return {"success": False, "candidates": [], "message": str(e)}

    async def delete_memory_entries(self, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """B028: delete previously-previewed entries by EXACT id+collection.

        No re-search between preview and delete — what the user confirmed is
        exactly what dies, even if memory changed in between.
        """
        try:
            memory = await self.get_memory_api()
            if not memory:
                return {"success": False, "deleted": 0, "deleted_facts": [], "message": "Memory API not available"}
            deleted = 0
            deleted_facts: list = []
            for entry in entries:
                try:
                    await memory.delete(entry["id"], entry["collection"])
                    deleted += 1
                    deleted_facts.append({"id": entry["id"], "text": entry.get("text", ""), "score": entry.get("score", 0)})
                    logger.info("Deleted memory entry %s from %s (confirmed)", entry["id"], entry["collection"])
                except Exception as e:
                    logger.warning("Failed to delete %s from %s: %s", entry.get("id"), entry.get("collection"), e)
            if deleted > 0:
                return {"success": True, "deleted": deleted, "deleted_facts": deleted_facts, "message": f"Esborrat {deleted} entrada(es) de la memoria"}
            return {"success": True, "deleted": 0, "deleted_facts": [], "message": "No s'ha trobat res similar a la memoria"}
        except Exception as e:
            logger.error("Memory delete error: %s", e)
            return {"success": False, "deleted": 0, "deleted_facts": [], "message": f"Error esborrant: {str(e)}"}

    async def delete_from_memory(
        self,
        content: str,
        collections: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Search for similar content in memory and delete the single best match.

        B028 (RT-04): this used to delete the top-1 of EVERY collection — with
        the default two collections, "oblida X" could kill X in personal_memory
        AND an unrelated 0.20-similarity document in user_knowledge. Restored
        to the original safety contract: at most ONE entry dies per call, the
        best match across all collections.

        Args:
            content: Text to search for and delete.
            collections: user-selected RAG collections filter (Bug #10). If None,
                defaults to ['personal_memory', 'user_knowledge'].

        Returns:
            Result dict with success status and count of deleted entries
        """
        try:
            memory = await self.get_memory_api()
            if not memory:
                return {"success": False, "deleted": 0, "deleted_facts": [], "message": "Memory API not available"}

            target_collections = collections if collections is not None else [MEMORY_COLLECTION, KNOWLEDGE_COLLECTION]
            candidates = await self._search_delete_candidates(memory, content, target_collections)
            if not candidates:
                return {"success": True, "deleted": 0, "deleted_facts": [], "message": "No s'ha trobat res similar a la memoria"}
            return await self.delete_memory_entries(candidates[:1])
        except Exception as e:
            logger.error("Memory delete error: %s", e)
            return {"success": False, "deleted": 0, "deleted_facts": [], "message": f"Error esborrant: {str(e)}"}

    async def list_memories(
        self,
        limit: int = 20,
        collections: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        List all stored memory facts using unbiased scroll (no semantic query).

        Args:
            limit: Maximum number of facts to return.
            collections: User-selected RAG collections filter (Bug #10).
                If non-None and does not include 'personal_memory', returns empty list.

        Returns:
            Dict with facts list, total count, and status.
        """
        try:
            # Bug #10: respect user collection filter — list is semantically personal
            if collections is not None and MEMORY_COLLECTION not in collections:
                logger.info("Memory collection disabled by user — list_memories returns empty")
                return {
                    "success": True,
                    "facts": [],
                    "total": 0,
                    "message": "Memory collection disabled",
                }

            memory = await self.get_memory_api()
            if not memory:
                return {"success": False, "facts": [], "total": 0, "message": "Memory not available"}

            collection = MEMORY_COLLECTION
            if not await memory.collection_exists(collection):
                return {"success": True, "facts": [], "total": 0, "message": "No memories stored"}

            total = await memory.count(collection)
            if total == 0:
                return {"success": True, "facts": [], "total": 0, "message": "No memories stored"}

            # F3: scroll instead of semantic search to avoid query-language bias.
            # Previously used `memory.search(query="user personal facts preferences", ...)`
            # which biased against Catalan/Spanish content.
            scroll_result = await memory.scroll(
                collection=collection,
                limit=min(limit, 50),
            )
            # qdrant scroll returns a (points, next_offset) tuple
            if isinstance(scroll_result, tuple):
                points = scroll_result[0]
            else:
                points = scroll_result

            facts = []
            for p in points:
                payload = getattr(p, "payload", None) or {}
                text = payload.get("text", "")
                if not text:
                    continue
                facts.append({
                    "id": str(getattr(p, "id", "")) or payload.get("original_id", ""),
                    "text": text,
                    "created_at": payload.get("created_at", payload.get("saved_at", "")),
                    "source": payload.get("source", "unknown"),
                    "type": payload.get("type", "unknown"),
                })

            return {
                "success": True,
                "facts": facts,
                "total": total,
                "message": f"{len(facts)} memories found (of {total} total)"
            }
        except Exception as e:
            logger.error("Memory list error: %s", e)
            return {"success": False, "facts": [], "total": 0, "message": str(e)}

    async def auto_save(
        self,
        user_message: str,
        session_id: str,
    ) -> Dict[str, Any]:
        """
        Save user message directly to memory (without LLM).

        Strategy: save the raw message. Semantic search will find
        'My name is Aran' when asked 'what's my name?'.

        Filters: greetings, questions, memory commands and trivial messages.
        Only saves user assertions/facts.
        """
        msg = user_message.strip()

        # Filter too short
        if len(msg) < 10:
            return {"success": True, "document_id": None, "message": "⏭️ Too short"}

        # Filter greetings
        for pat in self.skip_patterns:
            if pat.match(msg):
                return {"success": True, "document_id": None, "message": "⏭️ Greeting"}

        # Filter out questions (not facts, they pollute memory)
        if msg.rstrip('?').strip() != msg.rstrip() and '?' in msg:
            return {"success": True, "document_id": None, "message": "⏭️ Question"}

        # Filter out memory commands (save/delete/recall are handled via intent)
        intent, _ = self.detect_intent(msg)
        if intent in ('save', 'delete'):
            return {"success": True, "document_id": None, "message": "⏭️ Memory command"}

        return await self.save_to_memory(
            content=msg,
            session_id=session_id,
            metadata={"type": "user_message", "source": "auto_save"}
        )

    async def save_document_chunks(
        self,
        chunks: List[str],
        filename: str,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Save document chunks individually to user_knowledge.
        Each chunk gets its own embedding — enables semantic search within the document.

        Pattern: process_chunks — one embed+upsert per chunk, progress every 25.
        """
        import time
        memory = await self.get_memory_api()
        if not memory:
            return {"success": False, "chunks_saved": 0, "message": "Memory API not available"}

        # Documents go to user_knowledge (separate from personal_memory which is for personal memory)
        DOC_COLLECTION = KNOWLEDGE_COLLECTION
        if not await memory.collection_exists(DOC_COLLECTION):
            await memory.create_collection(DOC_COLLECTION)
            logger.info(f"Created {DOC_COLLECTION} collection")

        total = len(chunks)
        saved = 0
        base_meta = {
            **(metadata or {}),
            "source_document": filename,
            "total_chunks": total,
            "type": "document_chunk",
            "source": "web_ui_upload",
            "session_id": session_id,
        }

        logger.info(f"Ingesting '{filename}': {total} chunks → {DOC_COLLECTION}")
        t_total = time.time()
        # Bug #16: BATCH_SIZE was hardcoded to 50 here. Now sourced from
        # the IngestConfig SSOT via the defensive resolver (default still
        # 50 → behaviour-preserving). See memory/memory/config.py.
        cfg = getattr(memory, "ingest_config", None)
        raw_batch = getattr(cfg, "store_batch_size", None) if cfg is not None else None
        BATCH_SIZE = raw_batch if isinstance(raw_batch, int) and raw_batch > 0 else 50

        # Defense-in-depth — We apply `_filter_rag_injection` to each chunk
        # before indexing to `user_knowledge`. The same filter is already applied at
        # retrieval (`_sanitize_rag_context`), but a document with tags
        # `[MEM_SAVE:]`, `[MEMORIA:]` or `[CONTEXT ...]` should never reach
        # the vector index unneutralized. The filter does NOT truncate —
        # truncation only applies at RETRIEVAL.
        for batch_start in range(0, total, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, total)
            batch_chunks = chunks[batch_start:batch_end]
            batch_items = []
            for i, chunk in enumerate(batch_chunks, start=batch_start):
                clean_chunk = _filter_rag_injection(chunk)
                meta = {**base_meta, "chunk_index": i, "saved_at": datetime.now(timezone.utc).isoformat()}
                batch_items.append({"text": clean_chunk, "metadata": meta})
            try:
                t0 = time.time()
                await memory.store_batch(batch_items, collection=DOC_COLLECTION)
                saved += len(batch_items)
                elapsed_ms = (time.time() - t0) * 1000
                logger.info(f"  [{batch_end}/{total}] batch of {len(batch_items)} chunks, {elapsed_ms:.0f}ms")
            except Exception as e:
                logger.warning(f"  Batch [{batch_start}-{batch_end}] failed ({e}), falling back to single")
                for i, chunk in enumerate(batch_chunks, start=batch_start):
                    try:
                        clean_chunk = _filter_rag_injection(chunk)
                        meta = {**base_meta, "chunk_index": i, "saved_at": datetime.now(timezone.utc).isoformat()}
                        await memory.store(text=clean_chunk, collection=DOC_COLLECTION, metadata=meta)
                        saved += 1
                    except Exception as e2:
                        logger.warning(f"  [{i}/{total}] chunk failed: {e2}")

        total_s = time.time() - t_total
        logger.info(f"Ingestion '{filename}': {saved}/{total} chunks in {total_s:.1f}s")
        return {
            "success": True,
            "document_id": filename,
            "chunks_saved": saved,
            "message": f"✓ {saved}/{total} chunks indexats a {DOC_COLLECTION}",
        }

    def _apply_temporal_decay(self, score: float, metadata: Dict) -> float:
        """Apply temporal decay to score - recent memories get bonus."""
        saved_at = metadata.get("saved_at", "")
        if not saved_at:
            return score

        try:
            saved_date = datetime.fromisoformat(saved_at)
            if saved_date.tzinfo is None:
                saved_date = saved_date.replace(tzinfo=timezone.utc)
            days_old = (datetime.now(timezone.utc) - saved_date).days

            # Bonus for recent (within TEMPORAL_DECAY_DAYS)
            if days_old <= TEMPORAL_DECAY_DAYS:
                bonus = 0.15 * (1 - days_old / TEMPORAL_DECAY_DAYS)
                return min(1.0, score + bonus)
            # Small penalty for very old
            elif days_old > TEMPORAL_DECAY_DAYS * 4:
                return score * 0.9
        except Exception as e:
            logger.debug("Temporal decay calculation failed: %s", e)

        return score

    async def _search_collection_results(
        self, memory, query: str, collection: str, limit: int, session_id,
        query_embedding: "List[float] | None" = None,
    ) -> list:
        """Search one collection and return scored result dicts with temporal decay applied."""
        out: list[Dict[str, Any]] = []
        try:
            if not await memory.collection_exists(collection):
                return out
            _search_kwargs: Dict[str, Any] = dict(query=query, collection=collection, top_k=limit * 2)
            # MC-002: reuse the precomputed query embedding when available so the
            # vector store does not re-embed the identical query per collection.
            if query_embedding is not None:
                _search_kwargs["query_embedding"] = query_embedding
            results = await memory.search(**_search_kwargs)
            for r in results:
                meta = r.metadata or {}
                meta["source_collection"] = collection
                if meta.get("type") == "document_chunk" and session_id:
                    if meta.get("session_id") != session_id:
                        continue
                adjusted_score = self._apply_temporal_decay(r.score, meta)
                out.append({
                    "content": r.text or "",
                    "score": adjusted_score,
                    "original_score": r.score,
                    "metadata": meta,
                    "_id": r.id if hasattr(r, 'id') else None,
                })
        except Exception as e:
            logger.warning(f"Error searching collection {collection}: {e}")
        return out

    @staticmethod
    def _deduplicate_results(all_results: list, limit: int) -> list:
        """Sort by score descending and deduplicate by the whole content.

        #1091: the key used to be the first 200 chars ("chunks from same doc
        are similar"). A document with a RAG header carries the same
        `[Document]`/`[Abstract]` prefix on every chunk, so all its chunks
        shared those 200 chars and recall kept one per document (336 ca KB
        chunks → 35). Only exact duplicates collapse now.
        """
        all_results.sort(key=lambda x: x["score"], reverse=True)
        _seen_content: set = set()
        deduped = []
        for r in all_results:
            _key = r["content"].strip()
            if _key not in _seen_content:
                _seen_content.add(_key)
                deduped.append(r)
        return deduped[:limit]

    async def recall_from_memory(
        self,
        query: str,
        limit: int = 5,
        collections: list = None,  # type: ignore[assignment]  # no_implicit_optional
        session_id: str = None  # type: ignore[assignment]  # no_implicit_optional
    ) -> Dict[str, Any]:
        """
        Search memory with temporal decay and access tracking.

        Uses MemoryService.recall() if available, falls back to direct Qdrant.
        """
        try:
            # Legacy Qdrant path (MemoryService integration via pipeline is
            # handled at the endpoint level, not here — keep backwards compat)
            memory = await self.get_memory_api()
            if not memory:
                logger.warning("RAG recall: MemoryAPI not available (init failed or not ready)")
                return {"success": False, "results": [], "message": "Memory API not available"}

            if collections is not None:
                collections_to_search = memory.filter_requested(collections)
            else:
                collections_to_search = await memory.visible_names()

            # MC-002: embed the query ONCE and reuse it across collections instead
            # of recomputing the identical embedding per collection. Falls back to
            # per-search embedding (query_embedding=None) if precompute is unavailable.
            query_embedding = None
            try:
                query_embedding = await memory.embed_query(query)
            except Exception as emb_err:
                logger.debug("RAG recall: query embedding precompute unavailable: %s", emb_err)

            # MC-002: run the per-collection searches concurrently (was serial).
            # gather preserves argument order, so all_results keeps the original
            # collection ordering before dedup re-sorts by score.
            _per_collection = await _asyncio.gather(*(
                self._search_collection_results(memory, query, collection, limit, session_id, query_embedding)
                for collection in collections_to_search
            ))
            all_results = []
            for _results in _per_collection:
                all_results.extend(_results)

            final_results = self._deduplicate_results(all_results, limit)
            return {
                "success": True,
                "results": final_results,
                "total": len(final_results),
                "message": f"Found {len(final_results)} results"
            }
        except Exception as e:
            logger.error(f"Memory recall error: {e}")
            return {"success": False, "results": [], "message": f"Error searching memory: {str(e)}"}

    async def get_memory_stats(self) -> Dict[str, Any]:
        """
        Get memory collection statistics.

        Returns:
            Dict with entry count, config limits, etc.
        """
        try:
            memory = await self.get_memory_api()
            if not memory:
                return {"error": "Memory API not available"}

            count = 0
            if await memory.collection_exists(MEMORY_COLLECTION):
                count = await memory.count(MEMORY_COLLECTION)

            return {
                "collection": MEMORY_COLLECTION,
                "entry_count": count,
                "max_entries": MAX_MEMORY_ENTRIES,
                "similarity_threshold": SIMILARITY_THRESHOLD,
                "usage_percent": round((count / MAX_MEMORY_ENTRIES) * 100, 1) if MAX_MEMORY_ENTRIES > 0 else 0
            }
        except Exception as e:
            logger.error(f"Failed to get memory stats: {e}")
            return {"error": str(e)}

    async def clear_memory(self, confirm: bool = False) -> Dict[str, Any]:
        """
        Clear all entries from personal_memory collection.

        Args:
            confirm: Must be True to actually clear

        Returns:
            Result dict
        """
        if not confirm:
            return {
                "success": False,
                "message": "Pass confirm=True to clear memory"
            }

        try:
            memory = await self.get_memory_api()
            if not memory:
                return {"success": False, "message": "Memory API not available"}

            if await memory.collection_exists(MEMORY_COLLECTION):
                # Delete and recreate collection
                await memory.delete_collection(MEMORY_COLLECTION)
                await memory.create_collection(MEMORY_COLLECTION)
                logger.info("Memory collection cleared and recreated")

            # #897: the RAG collection is only half of what is stored.
            # Writes through MemoryService (CLI, /memory/store, workflow
            # nodes) live in memory_v1.db — facts, episodes and staging
            # rows — and they used to survive a wipe that reported success.
            view = await get_memory_view("web_ui_module")
            wiped = await view.forget_everything()
            # {} means the porter never reached MemoryService (service missing
            # / not initialized) — not "wiped zero rows". A non-empty dict,
            # even of zeros, is a real wipe. Treating {} as success is the
            # #897 lie on the service-down path: Qdrant is already gone,
            # memory_v1.db is intact, and the user hears "ja no recordo res".
            if not wiped:
                logger.warning(
                    "MemoryService did not run; personal facts were not wiped"
                )
                return {
                    "success": False,
                    "message": (
                        "Memory service is not running; personal facts were not wiped"
                    ),
                }
            logger.info("MemoryService stores wiped: %s", wiped)

            return {
                "success": True,
                "message": "✓ Memory cleared completely"
            }
        except Exception as e:
            logger.error(f"Failed to clear memory: {e}")
            return {"success": False, "message": str(e)}


# Retry interval for MemoryAPI initialization after a transient failure (F3).
# 60s balances recovery speed with request overhead: a failed retry costs one
# fastembed/Qdrant connect attempt per minute, acceptable vs permanent silence.
_MEMORY_API_RETRY_INTERVAL_S: float = 60.0

# Module-level state for the MemoryAPI view (shared by every helper instance;
# the helper itself is attached to server_state, see attach.py).
_memory_api_instance = None  # Singleton to avoid re-creating the model on each request
_memory_api_init_failed = False  # True after a failed init; reset by F3 retry logic
_memory_api_last_failure_ts: Optional[float] = None  # monotonic timestamp of last init failure

_memory_init_lock = _asyncio.Lock()  # Prevent concurrent double-init (race condition fix)
