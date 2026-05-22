"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/memory_service.py
Description: MemoryService — single facade for the memory system.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import hashlib
import json
import logging
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import MemoryConfig, get_config
from .models.memory_entry import ExtractedFact, MemoryCard, MemoryStats
from .models.memory_types import TrustLevel, ValidatorDecision
from .pipeline.extractor import Extractor
from .pipeline.gate import Gate
from .pipeline.schema_enforcer import SchemaEnforcer
from .pipeline.validator import Validator
from .storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


class MemoryService:
    """
    Single facade for all memory operations.

    All consumers go through this service. Orchestrates:
    pipeline (gate → extractor → validator) + storage (SQLite + Vector Index).
    """

    def __init__(
        self,
        config: Optional[MemoryConfig] = None,
        db_path: Optional[Path] = None,
        qdrant_path: Optional[str] = None,
    ):
        """Initialize pipeline components and storage backends."""
        # F2.2: resol path via SidecarConfig en sidecar mode
        from memory.memory._paths import resolve_qdrant_path
        self._config = config or get_config()
        _default_vectors = resolve_qdrant_path()
        self._db_path = db_path or Path(
            self._config.db_path or str(_default_vectors / "memory_v1.db")
        )
        self._qdrant_path = qdrant_path or self._config.qdrant_path or str(_default_vectors)

        # Pipeline components
        self._gate = Gate()
        self._extractor = Extractor()
        self._schema_enforcer = SchemaEnforcer()
        self._validator = Validator(schema_enforcer=self._schema_enforcer)

        # Storage. The SQLiteStore guards its cached sqlite3.Connection with
        # an RLock — that lock only coordinates within a single store
        # instance. The lifespan contract (see core/lifespan_modules.py:295
        # and memory/memory/module.py) keeps MemoryService a process-wide
        # singleton (MemoryModule creates one; lifespan_modules reuses it),
        # so all callers share the same RLock-protected SQLiteStore. Any
        # future refactor that drops the singleton must also coordinate
        # SQLiteStore access across instances (file lock or per-call conn).
        self._store = SQLiteStore(self._db_path)
        self._vector_index = None  # Lazy init to avoid Qdrant dependency in tests
        self._initialized = False

    def _ensure_vector_index(self):
        """Lazy-init vector index."""
        if self._vector_index is None:
            try:
                from .storage.vector_index import VectorIndex
                self._vector_index = VectorIndex(self._qdrant_path)
            except Exception as e:
                logger.warning("VectorIndex init failed: %s", e)

    @property
    def initialized(self) -> bool:
        """Whether the service has been initialized (store + vector index ready)."""
        return self._initialized

    async def initialize(self) -> bool:
        """Initialize the memory service."""
        if self._initialized:
            return True
        self._ensure_vector_index()
        self._initialized = True
        logger.info("MemoryService initialized (db=%s)", self._db_path)
        return True

    # ── Write path ──

    def _remember_gate(self, text: str, source: str, is_mem_save: bool, force: bool):
        """Run the gate check. Returns GateResult (always passed if force=True)."""
        if force:
            from .pipeline.gate import GateResult
            return GateResult(passed=True, reason="forced", score=1.0)
        is_user = source in ("user_message", "cli", "web_ui")
        return self._gate.evaluate(text, is_user_message=is_user, is_mem_save=is_mem_save)

    def _remember_extract_facts(self, text: str, entity: str, importance_hint: Optional[float]) -> list:
        """Extract facts from text, falling back to a generic fact if none found."""
        facts = self._extractor.extract(text)
        if not facts:
            facts = [ExtractedFact(
                content=text,
                entity=entity,
                importance=importance_hint or 0.5,
                source="heuristic",
            )]
        return facts

    def _remember_get_existing_value(self, user_id: str, fact: "ExtractedFact") -> Optional[str]:
        """Return the current profile value for fact.attribute, or None."""
        if not fact.attribute:
            return None
        canonical, _ = self._schema_enforcer.resolve(fact.attribute)
        if not canonical:
            return None
        profiles = self._store.get_profile(user_id, canonical)
        if not profiles:
            return None
        existing = json.loads(profiles[0]["value_json"])
        if isinstance(existing, list):
            existing = ", ".join(str(v) for v in existing)
        return existing

    def _remember_store_fact(self, user_id: str, fact: "ExtractedFact", result, entity: str, source: str, trust_level: str, namespace: str) -> Optional[str]:
        """Write fact to profile or episodic based on validator decision. Returns target_store name."""
        if result.decision == ValidatorDecision.UPSERT_PROFILE:
            if fact.attribute:
                canonical, _ = self._schema_enforcer.resolve(fact.attribute)
                if canonical and fact.value:
                    is_critical = self._schema_enforcer.is_critical(canonical)
                    self._store.upsert_profile(
                        user_id=user_id,
                        attribute=canonical,
                        value=fact.value,
                        entity=entity,
                        source=source,
                        trust_level=trust_level,
                        is_critical=is_critical,
                    )
            return "profile"
        if result.decision == ValidatorDecision.PROMOTE_EPISODIC:
            self._store.insert_episodic(
                user_id=user_id,
                content=fact.content,
                memory_type="fact",
                importance=fact.importance,
                source=source,
                trust_level=trust_level,
                namespace=namespace,
            )
            return "episodic"
        return None

    async def remember(
        self,
        user_id: str,
        text: str,
        entity: str = "user",
        namespace: str = "default",
        importance_hint: Optional[float] = None,
        trust_level: str = "untrusted",
        source: str = "user_message",
        is_mem_save: bool = False,
        force: bool = False,
    ) -> Optional[str]:
        """
        Process text through the pipeline and store if worthy.

        Returns staging entry ID if accepted, None if rejected.
        If force=True, bypass the Gate heuristic.
        """
        text = unicodedata.normalize("NFKC", text)

        gate_result = self._remember_gate(text, source, is_mem_save, force)
        if not gate_result.passed:
            logger.debug("Gate rejected: %s (reason=%s)", text[:50], gate_result.reason)
            return None

        facts = self._remember_extract_facts(text, entity, importance_hint)
        tl = TrustLevel(trust_level)
        entry_id = None

        for fact in facts:
            if importance_hint is not None:
                fact.importance = importance_hint

            existing_value = self._remember_get_existing_value(user_id, fact)
            result = self._validator.validate(fact, tl, existing_value)

            if result.decision == ValidatorDecision.REJECT:
                logger.debug("Validator rejected: %s", fact.content[:50])
                continue

            target_store = self._remember_store_fact(user_id, fact, result, entity, source, trust_level, namespace)

            # Always create staging entry for traceability
            entry_id = self._store.insert_staging(
                user_id=user_id,
                raw_text=text,
                extractor_output=fact.model_dump() if fact else None,
                gate_score=gate_result.score,
                validator_score=sum(result.scores.values()) / max(len(result.scores), 1),
                validator_decision=result.decision.value,
                decision_reason=result.reason,
                source=source,
                trust_level=trust_level,
                namespace=namespace,
                target_store=target_store,
            )

        return entry_id

    # ── Read path ──

    async def recall(
        self,
        user_id: str,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 5,
        mode: str = "normal",
    ) -> List[MemoryCard]:
        """
        Retrieve relevant memories as MemoryCards.

        Layers: profile → episodic → (vector search if available).
        """
        cards: List[MemoryCard] = []

        # 1. Profile facts (high confidence)
        profiles = self._store.get_profile(user_id)
        for p in profiles:
            value = json.loads(p["value_json"])
            card = MemoryCard(
                content=f"{p['attribute']}: {value}",
                confidence="high",
                source_store="profile",
                score=1.0,
                entry_id=p["id"],
                metadata={"entity": p["entity"], "attribute": p["attribute"]},
            )
            cards.append(card)

        # 2. Recent episodic (moderate confidence)
        episodes = self._store.get_episodic(user_id, limit=limit * 2)
        for ep in episodes[:limit]:
            card = MemoryCard(
                content=ep["content"],
                confidence="moderate",
                source_store="episodic",
                score=ep.get("importance", 0.5),
                entry_id=ep["id"],
            )
            cards.append(card)

        # 3. Token budget — trim to limit
        cards = cards[:limit]

        return cards

    async def get_profile(
        self, user_id: str, entity: str = "user"
    ) -> Dict[str, Any]:
        """Get full profile for a user."""
        profiles = self._store.get_profile(user_id)
        result = {}
        for p in profiles:
            if p.get("entity", "user") == entity:
                result[p["attribute"]] = {
                    "value": json.loads(p["value_json"]),
                    "trust_level": p["trust_level"],
                    "is_critical": bool(p["is_critical"]),
                    "last_seen_at": p["last_seen_at"],
                    "evidence_count": p["evidence_count"],
                }
        return result

    async def update_profile(
        self,
        user_id: str,
        attribute: str,
        value: Any,
        entity: str = "user",
    ) -> bool:
        """
        Administrative profile update (bypasses pipeline, not schema enforcer).
        """
        canonical, method = self._schema_enforcer.resolve(attribute)
        if not canonical:
            logger.warning("update_profile: attribute '%s' not in schema", attribute)
            return False

        is_critical = self._schema_enforcer.is_critical(canonical)
        self._store.upsert_profile(
            user_id=user_id,
            attribute=canonical,
            value=value,
            entity=entity,
            source="admin",
            trust_level="trusted",
            is_critical=is_critical,
        )
        return True

    # ── Delete path ──

    async def forget(self, user_id: str, entry_id: str) -> bool:
        """Real forget: delete from stores + tombstone + redact history."""
        conn = self._store._connect()
        # Try profile first
        row = conn.execute(
            "SELECT id, value_json FROM profile WHERE id = ? AND user_id = ?",
            (entry_id, user_id),
        ).fetchone()
        if row:
            ch = hashlib.sha256(str(row["value_json"]).lower().strip().encode()).hexdigest()
            conn.execute("DELETE FROM profile WHERE id = ?", (entry_id,))
            conn.execute(
                "UPDATE profile_history SET old_value_json = ?, new_value_json = ? WHERE profile_id = ?",
                ("[REDACTED]", "[REDACTED]", entry_id))
            conn.commit()
            self._store.add_tombstone(user_id, ch, "user_forget")
            return True
        # Try episodic
        row = conn.execute(
            "SELECT id, content_hash FROM episodic WHERE id = ? AND user_id = ?",
            (entry_id, user_id),
        ).fetchone()
        if row:
            conn.execute("DELETE FROM episodic WHERE id = ?", (entry_id,))
            conn.commit()
            if row["content_hash"]:
                self._store.add_tombstone(user_id, row["content_hash"], "user_forget")
            return True
        return False

    async def forget_about(self, user_id: str, entity: str, attribute: Optional[str] = None) -> int:
        """Forget all data for entity/attribute."""
        conn = self._store._connect()
        if attribute:
            rows = conn.execute("SELECT id FROM profile WHERE user_id = ? AND entity = ? AND attribute = ?",
                                (user_id, entity, attribute)).fetchall()
        else:
            rows = conn.execute("SELECT id FROM profile WHERE user_id = ? AND entity = ?",
                                (user_id, entity)).fetchall()
        count = 0
        for row in rows:
            if await self.forget(user_id, row["id"]):
                count += 1
        return count

    # ── Stats ──

    async def stats(self, user_id: str) -> MemoryStats:
        """Get memory statistics."""
        raw = self._store.get_stats(user_id)
        return MemoryStats(
            profile_count=raw["profile_count"],
            episodic_count=raw["episodic_count"],
            staging_count=raw["staging_count"],
            tombstone_count=raw["tombstone_count"],
        )

    # ── Export/Import ──

    async def export_memory(self, user_id: str) -> Dict[str, Any]:
        """Export all memory data for a user."""
        profile = await self.get_profile(user_id)
        episodes = self._store.get_episodic(user_id, limit=10000)
        return {
            "user_id": user_id, "exported_at": datetime.now(timezone.utc).isoformat(),
            "profile": profile, "episodic_count": len(episodes),
            "episodic": [{"id": e["id"], "content": e["content"], "importance": e["importance"]} for e in episodes],
        }

    async def export_mirror(self, user_id: str) -> str:
        """Export memory as human-readable text."""
        profile = await self.get_profile(user_id)
        lines = ["# Memory Mirror", ""]
        if profile:
            lines.append("## Profile")
            for attr, info in profile.items():
                lines.append(f"- {attr}: {info['value']}")
            lines.append("")
        episodes = self._store.get_episodic(user_id, limit=100)
        if episodes:
            lines.append("## Recent Facts")
            for ep in episodes:
                lines.append(f"- {ep['content']}")
        return "\n".join(lines)

    async def import_corrections(self, user_id: str, corrections: Dict[str, Any]) -> int:
        """Import profile corrections from user."""
        count = 0
        for attr, value in corrections.items():
            if await self.update_profile(user_id, attr, value):
                count += 1
        return count

    # ── Lifecycle ──

    async def shutdown(self):
        """Graceful shutdown."""
        if self._store:
            self._store.close()
        if self._vector_index:
            self._vector_index.close()
        self._initialized = False
        logger.info("MemoryService shut down")


__all__ = ["MemoryService"]
