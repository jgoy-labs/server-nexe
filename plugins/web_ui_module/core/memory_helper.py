"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/memory_helper.py
Description: Memory integration with intent detection for contextual memory storage.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import re
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple, List

from memory.memory.constants import DEFAULT_VECTOR_SIZE

logger = logging.getLogger(__name__)

# ============================================
# MEMORY MANAGEMENT CONFIG
# ============================================
MAX_MEMORY_ENTRIES = 500          # Maximum entries in nexe_web_ui
SIMILARITY_THRESHOLD = 0.80       # No guardar si similaritat > 80% (baixat de 0.85)
PRUNE_BATCH_SIZE = 30             # How many entries to remove when the limit is exceeded
TEMPORAL_DECAY_DAYS = 7           # Dies per aplicar decay temporal (recent = bonus)
MIN_IMPORTANCE_SCORE = 0.3        # Minimum to save (filters out chatter)

# Memory types for structured storage
MEMORY_TYPES = {
    "fact": 1.0,           # Stable data (name, job) - maximum retention
    "preference": 0.9,     # User preferences
    "contextual": 0.6,     # Situational info ("I'm tired today")
    "conversation": 0.4,   # Pure conversation logs
}

# Intent patterns for memory operations (Catalan + Spanish + English)
# Patterns that indicate user wants to SAVE something
SAVE_TRIGGERS = [
    # Catalan — al final del missatge
    r',?\s*(ho\s+)?pots\s+guardar\??$',
    r',?\s*(ho\s+)?pots\s+recordar\??$',
    r',?\s*guarda[\-\']?ho\??$',
    r',?\s*desa[\-\']?ho\??$',
    # Catalan — al principi del missatge ("Recorda que X")
    r'^recorda\s+que\s+',
    r'^guarda\s+que\s+',
    r'^apunta\s+que\s+',
    # Catalan — with "memòria" anywhere in the message
    r'\bguardar?\b.*mem[oò]ria',
    r'\brecordar?\b.*mem[oò]ria',
    r'\bdesa\b.*mem[oò]ria',
    r'\bapunta\b.*mem[oò]ria',
    # Spanish — al final del missatge
    r',?\s*lo\s+puedes\s+guardar\??$',
    r',?\s*puedes\s+guardar(lo)?\??$',
    r',?\s*lo\s+puedes\s+recordar\??$',
    r',?\s*puedes\s+recordar(lo)?\??$',
    r',?\s*gu[aá]rda(lo)?\??$',
    r',?\s*recu[eé]rda(lo)?\??$',
    # Spanish — al principi del missatge ("Recuerda que X")
    r'^recuerda\s+que\s+',
    r'^guarda\s+que\s+',
    r'^apunta\s+que\s+',
    # Spanish — amb "memoria"
    r'\bguardar?\b.*memoria',
    r'\brecordar?\b.*memoria',
    # English — al final del missatge
    r',?\s*(can\s+you\s+)?(please\s+)?save\s+(it|this|that)\??$',
    r',?\s*(can\s+you\s+)?(please\s+)?remember\s+(it|this|that)\??$',
    r',?\s*save\s+it\??$',
    # English — al principi del missatge ("Remember that X")
    r'^remember\s+that\s+',
    r'^save\s+that\s+',
    # English — amb "memory"
    r'\bsave\b.*memory',
    r'\bremember\b.*memory',
]

RECALL_PATTERNS = [
    # Catalan
    r'\b(busca|cerca|recupera)\b',
    r'\bqu[eè]\s+saps\s+(sobre|de)\b',
    r'\b(recordes|et\s+recordes)\b',
    r'\bcom\s+(em\s+)?dic\b',
    r'\bquin\s+[eé]s\s+(el\s+)?(meu\s+)?nom\b',
    # Spanish
    r'\b(busca|recupera)\b',
    r'\bqu[eé]\s+sabes\s+(sobre|de|acerca)\b',
    r'\b(recuerdas|te\s+acuerdas)\b',
    r'\bc[oó]mo\s+me\s+llamo\b',
    r'\bcu[aá]l\s+es\s+(el\s+)?(mi\s+)?nombre\b',
    r'\bcu[aá]l\s+es\s+(el\s+)?nombre\s+del\s+(usuario|usurio)\b',
    # English
    r'\b(search|find|recall)\b',
    r'\bwhat\s+do\s+you\s+know\s+(about|on)\b',
    r'\b(do\s+you\s+remember)\b',
    r'\bwhat\s*(is|\'s)\s+my\s+name\b',
]

# Patterns that indicate user wants to DELETE/FORGET something
DELETE_TRIGGERS = [
    # Catalan — al principi ("Oblida que X", "Esborra que X")
    r'^oblida\s+(que\s+)?',
    r'^esborra\s+(que\s+)?',
    r'^elimina\s+(que\s+)?',
    # Catalan — al final ("..., oblida-ho", "..., esborra-ho")
    r',?\s*(ho\s+)?pots\s+oblidar\??$',
    r',?\s*(ho\s+)?pots\s+esborrar\??$',
    r',?\s*oblida[\-\']?ho\??$',
    r',?\s*esborra[\-\']?ho\??$',
    # Catalan — with "memòria"
    r'\boblidar?\b.*mem[oò]ria',
    r'\besborrar?\b.*mem[oò]ria',
    r'\beliminar?\b.*mem[oò]ria',
    # Spanish — al principi
    r'^olvida\s+(que\s+)?',
    r'^borra\s+(que\s+)?',
    r'^elimina\s+(que\s+)?',
    # Spanish — al final
    r',?\s*(lo\s+)?puedes\s+olvidar\??$',
    r',?\s*(lo\s+)?puedes\s+borrar\??$',
    r',?\s*olv[ií]da(lo)?\??$',
    r',?\s*b[oó]rra(lo)?\??$',
    # Spanish — amb "memoria"
    r'\bolvidar?\b.*memoria',
    r'\bborrar?\b.*memoria',
    # English — al principi
    r'^forget\s+(that\s+)?',
    r'^delete\s+(that\s+)?',
    r'^erase\s+(that\s+)?',
    # English — al final
    r',?\s*(can\s+you\s+)?(please\s+)?forget\s+(it|this|that)\??$',
    r',?\s*(can\s+you\s+)?(please\s+)?delete\s+(it|this|that)\??$',
    r',?\s*forget\s+it\??$',
    # English — amb "memory"
    r'\bforget\b.*memory',
    r'\bdelete\b.*memory',
    r'\berase\b.*memory',
]

class MemoryHelper:
    """Helper class for memory operations with intent detection and smart extraction."""

    def __init__(self):
        self._memory_api = None
        self.save_triggers = [re.compile(p, re.IGNORECASE) for p in SAVE_TRIGGERS]
        self.recall_regex = [re.compile(p, re.IGNORECASE) for p in RECALL_PATTERNS]
        self.delete_triggers = [re.compile(p, re.IGNORECASE) for p in DELETE_TRIGGERS]
        # Patterns per detectar xerrameca (no guardar)
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

    async def get_memory_api(self):
        """Get or initialize Memory API instance (module-level singleton)."""
        global _memory_api_instance
        if _memory_api_instance is None:
            try:
                from memory.memory.api import MemoryAPI
                api = MemoryAPI()
                await api.initialize()

                # Ensure collections exist with correct dimensions (768)
                for coll_name in ("nexe_web_ui", "user_knowledge"):
                    if await api.collection_exists(coll_name):
                        try:
                            info = api._qdrant.get_collection(coll_name)
                            vec_cfg = info.config.params.vectors
                            dim = vec_cfg.size if hasattr(vec_cfg, 'size') else None
                            if dim and dim != DEFAULT_VECTOR_SIZE:
                                logger.warning("Collection %s has %d dims, expected %d — recreating", coll_name, dim, DEFAULT_VECTOR_SIZE)
                                await api.delete_collection(coll_name)
                                await api.create_collection(coll_name, vector_size=DEFAULT_VECTOR_SIZE)
                                logger.info("Recreated %s with %d dims", coll_name, DEFAULT_VECTOR_SIZE)
                        except Exception as dim_err:
                            logger.debug("Could not verify dims for %s: %s", coll_name, dim_err)
                    else:
                        await api.create_collection(coll_name, vector_size=DEFAULT_VECTOR_SIZE)
                        logger.info("Created memory collection %s", coll_name)

                _memory_api_instance = api
                logger.info("MemoryAPI singleton initialized and cached")
            except Exception as e:
                logger.error(f"Failed to initialize Memory API: {e}")
                _memory_api_instance = None
        self._memory_api = _memory_api_instance
        return _memory_api_instance

    def detect_intent(self, message: str) -> Tuple[str, Optional[str]]:
        """
        Detect user intent in message.

        Args:
            message: User message text

        Returns:
            Tuple of (intent, extracted_content)
            intent can be: 'save', 'recall', 'chat'
        """
        # Check for save intent
        # Triggers at END: "Em dic Claude, guarda-ho" → content = before trigger
        # Triggers at START: "Recorda que em dic Claude" → content = after trigger
        for pattern in self.save_triggers:
            match = pattern.search(message)
            if match:
                if match.start() == 0:
                    content = message[match.end():].strip()
                else:
                    content = message[:match.start()].strip()
                    content = content.rstrip(',').strip()
                if content:
                    return ('save', content)

        # Check for delete intent
        # "Oblida que em dic Claude" → delete, content = "em dic Claude"
        for pattern in self.delete_triggers:
            match = pattern.search(message)
            if match:
                if match.start() == 0:
                    content = message[match.end():].strip()
                else:
                    content = message[:match.start()].strip()
                    content = content.rstrip(',').strip()
                if content:
                    return ('delete', content)

        # Check for recall intent
        for pattern in self.recall_regex:
            if pattern.search(message):
                return ('recall', message)

        # Default: normal chat
        return ('chat', None)

    async def _check_duplicate(self, content: str, memory) -> bool:
        """
        Check if similar content already exists in memory.

        Returns True if duplicate found (should skip saving).
        """
        try:
            results = await memory.search(
                query=content,
                collection="nexe_web_ui",
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
            return False  # En cas de dubte, guardar

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
            if not await memory.collection_exists("nexe_web_ui"):
                return 0

            # Check count first to avoid unnecessary search
            current_count = await memory.count("nexe_web_ui")
            if current_count <= MAX_MEMORY_ENTRIES:
                return 0

            # Retrieve entries for scoring — search with broad query
            # (Qdrant has no scroll/list API via this wrapper, so we use
            # a minimal query to retrieve all entries by vector similarity)
            all_entries = await memory.search(
                query=" ",
                collection="nexe_web_ui",
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
                        await memory.delete(entry.id, collection="nexe_web_ui")
                        deleted += 1
                        logger.debug(f"Pruned entry (retention={score:.2f}): {entry.text[:50] if entry.text else 'N/A'}...")
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
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Save content to memory with deduplication and size management.

        Args:
            content: Text to save
            session_id: Session identifier
            metadata: Optional metadata

        Returns:
            Result dict with success status and message
        """
        try:
            memory = await self.get_memory_api()
            if not memory:
                return {
                    "success": False,
                    "message": "Memory API not available"
                }

            # 1. Check for duplicates - skip if very similar content exists
            if await self._check_duplicate(content, memory):
                return {
                    "success": True,
                    "document_id": None,
                    "message": "⏭️ Contingut similar ja existeix, no guardat"
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
                collection="nexe_web_ui",
                metadata=meta
            )

            return {
                "success": True,
                "document_id": doc_id,
                "message": "✓ Saved to memory"
            }
        except Exception as e:
            logger.error(f"Memory store error: {e}")
            return {
                "success": False,
                "message": f"Error saving to memory: {str(e)}"
            }

    async def delete_from_memory(self, content: str) -> Dict[str, Any]:
        """
        Search for similar content in memory and delete matching entries.

        Args:
            content: Text to search for and delete

        Returns:
            Result dict with success status and count of deleted entries
        """
        try:
            memory = await self.get_memory_api()
            if not memory:
                return {"success": False, "message": "Memory API not available"}

            deleted = 0
            for collection in ["nexe_web_ui", "user_knowledge"]:
                try:
                    if not await memory.collection_exists(collection):
                        continue
                    results = await memory.search(
                        query=content, collection=collection, top_k=5, threshold=0.6
                    )
                    for r in results:
                        try:
                            await memory.delete(r.id, collection)
                            deleted += 1
                            logger.info("Deleted memory entry %s from %s (score=%.2f)", r.id, collection, r.score)
                        except Exception as e:
                            logger.warning("Failed to delete %s from %s: %s", r.id, collection, e)
                except Exception as e:
                    logger.debug("Delete search in %s failed: %s", collection, e)

            if deleted > 0:
                return {"success": True, "deleted": deleted, "message": f"Esborrat {deleted} entrada(es) de la memoria"}
            else:
                return {"success": True, "deleted": 0, "message": "No s'ha trobat res similar a la memoria"}
        except Exception as e:
            logger.error("Memory delete error: %s", e)
            return {"success": False, "message": f"Error esborrant: {str(e)}"}

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

        Pattern: NAT UBIK process_chunks — un embed+upsert per chunk, progress cada 25.
        """
        import time
        memory = await self.get_memory_api()
        if not memory:
            return {"success": False, "chunks_saved": 0, "message": "Memory API not available"}

        # Documents van a user_knowledge (separat de nexe_web_ui que es per memoria personal)
        DOC_COLLECTION = "user_knowledge"
        if not await memory.collection_exists(DOC_COLLECTION):
            await memory.create_collection(DOC_COLLECTION, vector_size=DEFAULT_VECTOR_SIZE)
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

        for i, chunk in enumerate(chunks):
            t0 = time.time()
            try:
                meta = {**base_meta, "chunk_index": i, "saved_at": datetime.now(timezone.utc).isoformat()}
                await memory.store(
                    text=chunk,
                    collection=DOC_COLLECTION,
                    metadata=meta,
                )
                saved += 1
                elapsed_ms = (time.time() - t0) * 1000
                if i % 25 == 0 or i == total - 1:
                    logger.info(f"  [{i+1}/{total}] {len(chunk)} chars, {elapsed_ms:.0f}ms")
            except Exception as e:
                logger.warning(f"  [{i}/{total}] chunk failed: {e}")

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

    async def recall_from_memory(
        self,
        query: str,
        limit: int = 5,
        collections: list = None,
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        Search memory with temporal decay and access tracking.

        Args:
            query: Search query
            limit: Max results to return per collection
            collections: Optional list of collection names to search (default: all 3)
            session_id: If set, document_chunks from other sessions are filtered out

        Returns:
            Result dict with search results (scores adjusted for recency)
        """
        try:
            memory = await self.get_memory_api()
            if not memory:
                return {
                    "success": False,
                    "results": [],
                    "message": "Memory API not available"
                }

            _all_collections = ["nexe_documentation", "nexe_web_ui", "user_knowledge"]
            collections_to_search = [c for c in _all_collections if c in collections] if collections else _all_collections
            all_results = []

            for collection in collections_to_search:
                try:
                    if await memory.collection_exists(collection):
                        results = await memory.search(
                            query=query,
                            collection=collection,
                            top_k=limit * 2  # Get more, then filter
                        )
                        for r in results:
                            meta = r.metadata or {}
                            meta["source_collection"] = collection

                            # Document chunks: nomes mostrar si son de la sessio actual
                            if meta.get("type") == "document_chunk" and session_id:
                                if meta.get("session_id") != session_id:
                                    continue

                            # Apply temporal decay to score
                            adjusted_score = self._apply_temporal_decay(r.score, meta)

                            all_results.append({
                                "content": r.text or "",
                                "score": adjusted_score,
                                "original_score": r.score,
                                "metadata": meta,
                                "_id": r.id if hasattr(r, 'id') else None
                            })

                except Exception as e:
                    logger.warning(f"Error searching collection {collection}: {e}")

            # Sort by score descending
            all_results.sort(key=lambda x: x["score"], reverse=True)
            
            # Global limit
            final_results = all_results[:limit]

            return {
                "success": True,
                "results": final_results,
                "total": len(final_results),
                "message": f"Found {len(final_results)} results"
            }
        except Exception as e:
            logger.error(f"Memory recall error: {e}")
            return {
                "success": False,
                "results": [],
                "message": f"Error searching memory: {str(e)}"
            }

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
            if await memory.collection_exists("nexe_web_ui"):
                count = await memory.count("nexe_web_ui")

            return {
                "collection": "nexe_web_ui",
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
        Clear all entries from nexe_web_ui collection.

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

            if await memory.collection_exists("nexe_web_ui"):
                # Delete and recreate collection
                await memory.delete_collection("nexe_web_ui")
                await memory.create_collection("nexe_web_ui", vector_size=DEFAULT_VECTOR_SIZE)
                logger.info("Memory collection cleared and recreated")

            return {
                "success": True,
                "message": "✓ Memory cleared completely"
            }
        except Exception as e:
            logger.error(f"Failed to clear memory: {e}")
            return {"success": False, "message": str(e)}


# Global instances (module-level singletons)
_memory_helper = MemoryHelper()
_memory_api_instance = None  # Singleton to avoid re-creating the model on each request

def get_memory_helper() -> MemoryHelper:
    """Get global memory helper instance."""
    return _memory_helper
