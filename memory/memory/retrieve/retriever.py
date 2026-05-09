"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/retrieve/retriever.py
Description: Multi-layer memory retriever with dynamic threshold and re-rank.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import statistics
from typing import Dict, List, Optional

from memory.memory.config import MemoryConfig
from memory.memory.models.memory_entry import MemoryCard

logger = logging.getLogger(__name__)


class Retriever:
    """
    Multi-layer retrieve: Working → Profile → Vector → re-rank → budget.

    Threshold dynamic: floor 0.45, ceiling 0.65 (v1 decision).
    Mode exploratory: CLI/user only, never API (v1 decision).
    """

    def __init__(
        self,
        config: MemoryConfig,
        sqlite_store=None,
        vector_index=None,
        working_memory=None,
        embedder=None,
    ):
        self._config = config
        self._store = sqlite_store
        self._vector = vector_index
        self._working = working_memory
        self._embedder = embedder

    def _retrieve_working_memory(self, user_id: str, session_id: str, query: str) -> "List[MemoryCard]":
        """Retrieve cards from working memory (RAM)."""
        cards = []
        if not self._working:
            return cards
        for r in self._working.search(user_id, session_id, query, limit=5):
            cards.append(MemoryCard(
                content=r["content"],
                confidence="high",
                source_store="working",
                score=r.get("score", 0.8),
                entry_id=r.get("id"),
                metadata=r.get("metadata", {}),
            ))
        return cards

    def _retrieve_profile(self, user_id: str, query: str) -> "List[MemoryCard]":
        """Retrieve relevant profile cards (RDBMS, deterministic)."""
        cards = []
        if not self._store:
            return cards
        query_lower = query.lower()
        query_words = query_lower.split()
        for p in self._store.get_profile(user_id):
            value_str = str(p.get("value_json", "")).lower()
            attr_str = str(p.get("attribute", "")).lower()
            is_relevant = (
                any(w in value_str for w in query_words)
                or any(w in attr_str for w in query_words)
            )
            is_critical = p.get("is_critical", False)
            if is_relevant or is_critical:
                confidence = "high" if p.get("trust_level") == "trusted" else "moderate"
                cards.append(MemoryCard(
                    content=f"{p['attribute']}: {p['value_json']}",
                    confidence=confidence,
                    source_store="profile",
                    score=0.9 if is_critical else 0.7,
                    entry_id=p.get("id"),
                    metadata={"is_critical": is_critical},
                ))
        return cards

    def _retrieve_vector(self, user_id: str, query: str, namespace: Optional[str], mode: str) -> "List[MemoryCard]":
        """Retrieve cards via semantic vector search with dynamic threshold."""
        cards = []
        if not (self._vector and self._vector.available and self._embedder):
            return cards
        try:
            embedding = self._embedder.encode(query)
            embedding_list = embedding if isinstance(embedding, list) else embedding.tolist()
            rc = self._config.retrieve
            threshold = rc.base_threshold
            candidates = self._vector.search(
                embedding=embedding_list, user_id=user_id,
                threshold=threshold, limit=20, namespace=namespace,
            )
            dyn_threshold = self._dynamic_threshold(candidates)
            if mode == "exploratory":
                dyn_threshold = rc.base_threshold
            for c in candidates:
                if c["score"] >= dyn_threshold:
                    cards.append(MemoryCard(
                        content=c["payload"].get("content", f"[episodic:{c['id']}]"),
                        confidence=self._score_to_confidence(c["score"]),
                        source_store="episodic",
                        score=c["score"],
                        entry_id=c["id"],
                        metadata=c.get("payload", {}),
                    ))
        except Exception as e:
            logger.warning("Vector search failed: %s", e)
        return cards

    def retrieve(
        self,
        user_id: str,
        session_id: str,
        query: str,
        namespace: Optional[str] = None,
        mode: str = "normal",
    ) -> List[MemoryCard]:
        """
        Retrieve relevant memories for a query.

        Args:
            user_id: User ID (mandatory)
            session_id: Session ID (mandatory for working memory)
            query: Search query
            namespace: Optional namespace filter
            mode: "normal" or "exploratory" (CLI only)

        Returns:
            List of MemoryCard, ordered by relevance, within token budget.
        """
        cards: List[MemoryCard] = []
        cards.extend(self._retrieve_working_memory(user_id, session_id, query))
        cards.extend(self._retrieve_profile(user_id, query))
        cards.extend(self._retrieve_vector(user_id, query, namespace, mode))
        cards = self._rerank(cards)
        cards = self._apply_budget(cards)
        return cards

    def _dynamic_threshold(self, candidates: List[Dict]) -> float:
        """Calculate dynamic threshold from candidates. Floor 0.45, ceiling 0.65."""
        rc = self._config.retrieve
        if len(candidates) < 3:
            return rc.fallback_threshold

        scores = [c["score"] for c in candidates]
        median = statistics.median(scores)
        std = statistics.stdev(scores) if len(scores) > 1 else 0
        dynamic = median + 0.5 * std
        return max(rc.floor_threshold, min(rc.ceiling_threshold, dynamic))

    def _rerank(self, cards: List[MemoryCard]) -> List[MemoryCard]:
        """Re-rank cards with additive scoring."""
        for card in cards:
            base = card.score
            type_bonus = 0.05 if card.source_store == "profile" else 0.0
            working_bonus = 0.1 if card.source_store == "working" else 0.0
            critical_bonus = 0.1 if card.metadata.get("is_critical") else 0.0
            card.score = min(1.0, base + type_bonus + working_bonus + critical_bonus)

        cards.sort(key=lambda c: c.score, reverse=True)
        return cards

    def _apply_budget(self, cards: List[MemoryCard]) -> List[MemoryCard]:
        """Apply token budget. Critical first, then best scored."""
        rc = self._config.retrieve
        total_budget = min(
            rc.max_tokens_cap,
            int(4096 * rc.max_tokens_ratio),
        )

        # Critical always included
        critical = [c for c in cards if c.metadata.get("is_critical")]
        normal = [c for c in cards if not c.metadata.get("is_critical")]

        critical_tokens = sum(len(c.content.split()) for c in critical)
        remaining = max(0, total_budget - critical_tokens)

        selected = list(critical)
        for card in normal:
            tokens = len(card.content.split())
            if tokens <= remaining:
                selected.append(card)
                remaining -= tokens

        return selected

    def _score_to_confidence(self, score: float) -> str:
        """Map score to confidence label."""
        if score >= 0.8:
            return "high"
        elif score >= 0.6:
            return "moderate"
        return "low"


__all__ = ["Retriever"]
