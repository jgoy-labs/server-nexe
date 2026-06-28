"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/memory/memory/workers/test_gc_daemon_behavior.py
Description: MC-064 — behavioral tests for GCDaemon with a real SQLiteStore.
    The GC logic archives user memories, so it must be exercised with real
    data: score-threshold archiving, the exact 0.15 boundary, budget
    enforcement (worst 15% purged), tombstone + vector-index deletion,
    dry_run immutability, and the "profile is NEVER auto-deleted" invariant.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from memory.memory.config import BudgetConfig, GCConfig, MemoryConfig
from memory.memory.storage.sqlite_store import SQLiteStore
from memory.memory.workers.gc_daemon import GCDaemon

USER = "gc-user"


class FakeVectorIndex:
    """Minimal VectorIndex double recording delete() calls."""

    def __init__(self):
        self.deleted_batches = []

    def delete(self, ids):
        self.deleted_batches.append(list(ids))


def _iso_days_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _future_iso() -> str:
    # created_at in the future clamps age_days to 0, so decay == 1.0 exactly
    # and score == importance * access_boost (deterministic, no clock drift).
    return (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    s = SQLiteStore(tmp_path / "gc_behavior.db")
    yield s
    s.close()


def _insert_episodic(
    store: SQLiteStore,
    content: str,
    importance: float,
    days_ago: float = 0.0,
    access_count: int = 0,
) -> str:
    """Insert an active episodic entry and backdate it to control its score."""
    entry_id = store.insert_episodic(
        user_id=USER, content=content, importance=importance
    )
    conn = store._connect()
    conn.execute(
        "UPDATE episodic SET created_at = ?, access_count = ? WHERE id = ?",
        (_iso_days_ago(days_ago), access_count, entry_id),
    )
    conn.commit()
    return entry_id


def _episodic_states(store: SQLiteStore) -> dict:
    conn = store._connect()
    rows = conn.execute(
        "SELECT id, state FROM episodic WHERE user_id = ?", (USER,)
    ).fetchall()
    return {row["id"]: row["state"] for row in rows}


def _count(store: SQLiteStore, table: str) -> int:
    conn = store._connect()
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # nosec B608: table name is a test-local literal


def _content_hash(store: SQLiteStore, entry_id: str) -> str:
    """The real content_hash stored for an episodic entry (SHA256, 64 hex)."""
    conn = store._connect()
    row = conn.execute(
        "SELECT content_hash FROM episodic WHERE id = ?", (entry_id,)
    ).fetchone()
    return row["content_hash"]


class TestRunGcScoreThreshold:
    """(1) run_gc archives entries with score < 0.15 and keeps the rest."""

    def test_low_score_archived_high_score_kept(self, store):
        # score = importance * exp(-age_days / 60) with access_count=0
        keep_fresh = _insert_episodic(store, "fresh important fact", 0.9, days_ago=0)
        # 0.8 * exp(-1) ~= 0.294 > 0.15 -> kept
        keep_aged = _insert_episodic(store, "aged but important", 0.8, days_ago=60)
        # 0.5 * exp(-5) ~= 0.0034 < 0.15 -> archived
        drop_old = _insert_episodic(store, "very old trivia", 0.5, days_ago=300)
        # 0.2 * exp(-1) ~= 0.074 < 0.15 -> archived
        drop_weak = _insert_episodic(store, "weak aged fact", 0.2, days_ago=60)

        daemon = GCDaemon(config=MemoryConfig(), sqlite_store=store)
        result = daemon.run_gc(USER)

        assert result["episodic_scanned"] == 4
        assert result["episodic_deleted"] == 2
        assert result["budget_enforced"] is False

        states = _episodic_states(store)
        assert states[keep_fresh] == "active"
        assert states[keep_aged] == "active"
        assert states[drop_old] == "archived"
        assert states[drop_weak] == "archived"

    def test_archived_entries_get_tombstones(self, store):
        dropped = _insert_episodic(store, "doomed memory", 0.3, days_ago=400)
        real_hash = _content_hash(store, dropped)
        daemon = GCDaemon(config=MemoryConfig(), sqlite_store=store)
        daemon.run_gc(USER)
        # B032: the tombstone must carry the real content_hash (so the dreaming
        # reinsertion guard, which looks up by content hash, can match it)...
        assert store.is_tombstoned(USER, real_hash) is True
        # ...and NOT be keyed by the entry id (the old inert behaviour).
        assert store.is_tombstoned(USER, dropped) is False

    def test_gc_log_row_written(self, store):
        _insert_episodic(store, "old entry to purge", 0.3, days_ago=400)
        daemon = GCDaemon(config=MemoryConfig(), sqlite_store=store)
        assert _count(store, "gc_log") == 0
        daemon.run_gc(USER)
        assert _count(store, "gc_log") == 1


class TestScoreBoundary:
    """(2) the deletion threshold is strict: score < 0.15, not <=."""

    def test_exact_boundary_score_is_kept(self):
        daemon = GCDaemon(config=MemoryConfig())
        # Future created_at -> age 0 -> decay 1.0 -> score == importance exactly.
        entries = [
            {"id": "at-boundary", "importance": 0.15, "created_at": _future_iso(),
             "access_count": 0, "last_accessed": None},
            {"id": "just-below", "importance": 0.1499, "created_at": _future_iso(),
             "access_count": 0, "last_accessed": None},
            {"id": "just-above", "importance": 0.1501, "created_at": _future_iso(),
             "access_count": 0, "last_accessed": None},
        ]
        to_delete = daemon._gc_score_entries(entries)
        assert "just-below" in to_delete
        assert "at-boundary" not in to_delete
        assert "just-above" not in to_delete


class TestBudgetEnforcement:
    """(3) over 90% budget -> purge max(1, int(N*0.15)) lowest-scored ids."""

    def _config(self, episodic_max: int) -> MemoryConfig:
        return MemoryConfig(budgets=BudgetConfig(episodic_max=episodic_max))

    def _entries(self, n: int):
        # Distinct importances, future created_at -> score == importance.
        return [
            {"id": f"e{i:02d}", "importance": 0.20 + i * 0.01,
             "created_at": _future_iso(), "access_count": 0,
             "last_accessed": None}
            for i in range(n)
        ]

    def test_under_budget_returns_unchanged(self):
        daemon = GCDaemon(config=self._config(episodic_max=10))
        entries = self._entries(9)  # 9 <= int(10*0.9) -> no enforcement
        assert daemon._gc_enforce_budget(entries, ["pre"]) == ["pre"]

    def test_purges_15_percent_lowest_scores(self):
        daemon = GCDaemon(config=self._config(episodic_max=10))
        entries = self._entries(20)  # 20 > 9 -> purge int(20*0.15) = 3
        merged = daemon._gc_enforce_budget(entries, [])
        assert sorted(merged) == ["e00", "e01", "e02"]

    def test_purges_at_least_one(self):
        daemon = GCDaemon(config=self._config(episodic_max=10))
        entries = self._entries(10)  # int(10*0.15) = 1 -> max(1, 1) = 1
        merged = daemon._gc_enforce_budget(entries, [])
        assert merged == ["e00"]

    def test_merges_with_existing_deletions_without_duplicates(self):
        daemon = GCDaemon(config=self._config(episodic_max=10))
        entries = self._entries(20)
        merged = daemon._gc_enforce_budget(entries, ["e01", "zz-external"])
        assert sorted(merged) == ["e00", "e01", "e02", "zz-external"]

    def test_run_gc_end_to_end_budget(self, store):
        # 10 fresh high-importance entries, none below the 0.15 threshold;
        # only the budget path can archive, and it must pick the lowest score.
        ids = [
            _insert_episodic(store, f"budget fact {i}", 0.50 + i * 0.04, days_ago=0)
            for i in range(10)
        ]
        config = self._config(episodic_max=10)
        daemon = GCDaemon(config=config, sqlite_store=store)
        result = daemon.run_gc(USER)

        assert result["budget_enforced"] is True
        assert result["episodic_deleted"] == 1
        states = _episodic_states(store)
        assert states[ids[0]] == "archived"  # lowest importance -> lowest score
        for eid in ids[1:]:
            assert states[eid] == "active"


class TestDeleteEntries:
    """(4) _gc_delete_entries archives, tombstones, and purges the vector index."""

    def test_archives_tombstones_and_deletes_vectors(self, store):
        e1 = _insert_episodic(store, "delete me one", 0.5)
        e2 = _insert_episodic(store, "delete me two", 0.5)
        h1, h2 = _content_hash(store, e1), _content_hash(store, e2)
        vector = FakeVectorIndex()
        daemon = GCDaemon(config=MemoryConfig(), sqlite_store=store, vector_index=vector)

        conn = store._connect()
        daemon._gc_delete_entries(conn, USER, [e1, e2])

        states = _episodic_states(store)
        assert states[e1] == "archived"
        assert states[e2] == "archived"
        assert vector.deleted_batches == [[e1, e2]]
        # B032: tombstones keyed by the real content_hash, not the entry id.
        assert store.is_tombstoned(USER, h1) is True
        assert store.is_tombstoned(USER, h2) is True
        assert store.is_tombstoned(USER, e1) is False
        assert store.is_tombstoned(USER, e2) is False

    def test_vector_delete_failure_does_not_abort_tombstones(self, store):
        e1 = _insert_episodic(store, "vector failure entry", 0.5)

        class ExplodingVector:
            def delete(self, ids):
                raise RuntimeError("qdrant down")

        real_hash = _content_hash(store, e1)
        daemon = GCDaemon(
            config=MemoryConfig(), sqlite_store=store, vector_index=ExplodingVector()
        )
        conn = store._connect()
        daemon._gc_delete_entries(conn, USER, [e1])

        assert _episodic_states(store)[e1] == "archived"
        assert store.is_tombstoned(USER, real_hash) is True


class TestDryRun:
    """(5) dry_run=True reports work but mutates NOTHING."""

    def test_dry_run_mutates_nothing(self, store):
        doomed = _insert_episodic(store, "would be purged", 0.3, days_ago=400)
        # Already-expired tombstone: dry run must count it but not delete it.
        store.add_tombstone(USER, "expired-hash", reason="user_forget", ttl_days=-1)
        tombstones_before = _count(store, "tombstones")
        vector = FakeVectorIndex()
        daemon = GCDaemon(config=MemoryConfig(), sqlite_store=store, vector_index=vector)

        result = daemon.run_gc(USER, dry_run=True)

        # Reported as deletable...
        assert result["dry_run"] is True
        assert result["episodic_deleted"] == 1
        assert result["tombstones_expired"] == 1
        # ...but nothing actually changed.
        assert _episodic_states(store)[doomed] == "active"
        assert vector.deleted_batches == []
        assert _count(store, "tombstones") == tombstones_before
        assert _count(store, "gc_log") == 0


class TestProfileNeverDeleted:
    """(6) critical/profile cards are NEVER touched by GC (v1 decision)."""

    def test_profile_survives_gc(self, store):
        store.upsert_profile(
            USER, "allergy", "peanuts", trust_level="trusted", is_critical=True
        )
        store.upsert_profile(USER, "favorite_color", "blue", is_critical=False)
        # Episodic garbage so the GC actually performs deletions.
        _insert_episodic(store, "ancient noise", 0.2, days_ago=500)

        daemon = GCDaemon(config=MemoryConfig(), sqlite_store=store)
        result = daemon.run_gc(USER)
        assert result["episodic_deleted"] == 1

        profile = store.get_profile(USER)  # only returns state='active' rows
        attrs = {p["attribute"] for p in profile}
        assert attrs == {"allergy", "favorite_color"}
        critical = next(p for p in profile if p["attribute"] == "allergy")
        assert critical["is_critical"]

    def test_run_gc_without_store_is_a_noop(self):
        daemon = GCDaemon(config=MemoryConfig(), sqlite_store=None)
        result = daemon.run_gc(USER)
        assert result["episodic_scanned"] == 0
        assert result["episodic_deleted"] == 0


class TestScoreModel:
    """Sanity checks of the decay model the GC decisions rest on."""

    def test_access_boost_rescues_old_entries(self):
        daemon = GCDaemon(config=MemoryConfig(gc=GCConfig()))
        created = _iso_days_ago(120)
        cold = daemon.calculate_entry_score(0.4, created, access_count=0)
        hot = daemon.calculate_entry_score(
            0.4, created, access_count=50, last_accessed=_iso_days_ago(1)
        )
        assert hot > cold
        # 0.4 * exp(-2) ~= 0.054 < 0.15: cold entry is GC fodder
        assert cold < 0.15


class TestB032TombstoneReinsertionGuard:
    """B032 — GC tombstones must match the dreaming reinsertion guard.

    DreamingCycle._process_episodic recomputes the content hash as
    sha256(content.lower().strip()) and calls is_tombstoned(user, hash).
    If the GC keyed the tombstone by entry id (a uuid4[:16]) it could never
    match the 64-hex content hash, leaving the anti-zombie guard dead weight.
    """

    def test_gc_tombstone_matches_dreaming_reinsertion_guard(self, store):
        import hashlib

        content = "Recurring trivia that decayed away"
        _insert_episodic(store, content, 0.3, days_ago=400)
        daemon = GCDaemon(config=MemoryConfig(), sqlite_store=store)
        daemon.run_gc(USER)

        # The exact hash DreamingCycle._process_episodic computes for this content.
        guard_hash = hashlib.sha256(content.lower().strip().encode()).hexdigest()
        assert store.is_tombstoned(USER, guard_hash) is True

    def test_missing_content_hash_skips_tombstone_loudly(self, store, caplog):
        import logging

        # An id with no matching episodic row (e.g. concurrently hard-deleted):
        # without the real hash a tombstone would be inert, so it must be skipped.
        with caplog.at_level(logging.WARNING, logger="memory.memory.workers.gc_daemon"):
            daemon = GCDaemon(config=MemoryConfig(), sqlite_store=store)
            conn = store._connect()
            daemon._gc_delete_entries(conn, USER, ["ghost-id-xyz"])

        assert _count(store, "tombstones") == 0
        assert any("no content_hash" in rec.message for rec in caplog.records)
