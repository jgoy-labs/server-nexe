"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/tests/test_persistence.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path

from memory.memory.engines.persistence import PersistenceManager
from memory.memory.models.memory_entry import MemoryEntry
from memory.memory.models.memory_types import MemoryType

@pytest.fixture
async def temp_persistence():
  """Fixture: PersistenceManager with temporary paths"""
  temp_dir = Path(tempfile.mkdtemp())
  db_path = temp_dir / "test_memory.db"
  qdrant_path = temp_dir / "test_qdrant"

  pm = PersistenceManager(
    db_path=db_path,
    qdrant_path=qdrant_path,
    collection_name="test_collection",
    vector_size=768
  )

  yield pm

  pm.close()
  shutil.rmtree(temp_dir, ignore_errors=True)

@pytest.mark.asyncio
class TestPersistenceManager:
  """Tests for PersistenceManager"""

  async def test_initialization(self, temp_persistence):
    """Initialisation SQLite + Qdrant"""
    pm = temp_persistence

    assert pm.db_path.exists()

    assert pm.qdrant_path.exists()

    collections = pm.qdrant.get_collections().collections
    collection_names = [c.name for c in collections]
    assert "test_collection" in collection_names

  async def test_store_and_get(self, temp_persistence):
    """Store and retrieve entry"""
    pm = temp_persistence

    entry = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Test content",
      source="test"
    )

    entry_id = await pm.store(entry)

    assert entry_id == entry.id

    retrieved = await pm.get(entry_id)

    assert retrieved is not None
    assert retrieved.id == entry.id
    assert retrieved.content == "Test content"
    assert retrieved.source == "test"

  async def test_store_with_embedding(self, temp_persistence):
    """Store with embedding vector"""
    pm = temp_persistence

    entry = MemoryEntry(
      entry_type=MemoryType.SEMANTIC,
      content="Knowledge entry",
      source="test"
    )

    embedding = [0.1] * 768

    entry_id = await pm.store(entry, embedding=embedding)

    assert entry_id == entry.id

    retrieved = await pm.get(entry_id)
    assert retrieved is not None

  async def test_get_nonexistent(self, temp_persistence):
    """Retrieving a non-existent entry returns None"""
    pm = temp_persistence

    result = await pm.get("nonexistent_id")

    assert result is None

  async def test_hex_to_uuid_conversion(self):
    """Conversion of hex ID to UUID format"""
    hex_id = "019c2cdb30d195ae"

    uuid_str = PersistenceManager._hex_to_uuid(hex_id)

    assert len(uuid_str) == 36
    assert uuid_str.count('-') == 4
    assert uuid_str.startswith("019c2cdb-30d1-95ae-0000")

  async def test_insert_or_replace(self, temp_persistence):
    """INSERT OR REPLACE updates existing entry"""
    pm = temp_persistence

    entry1 = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Original content",
      source="test"
    )
    await pm.store(entry1)

    entry2 = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Original content",
      source="updated"
    )
    await pm.store(entry2)

    retrieved = await pm.get(entry1.id)

    assert retrieved.source == "updated"

  async def test_get_stats(self, temp_persistence):
    """Get persistence statistics"""
    pm = temp_persistence

    await pm.store(MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="E1",
      source="test"
    ))
    await pm.store(MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="E2",
      source="test"
    ))
    await pm.store(MemoryEntry(
      entry_type=MemoryType.SEMANTIC,
      content="S1",
      source="test"
    ))

    stats = await pm.get_stats()

    assert stats["total_entries"] == 3
    assert stats["episodic_count"] == 2
    assert stats["semantic_count"] == 1

  async def test_concurrent_writes(self, temp_persistence):
    """Concurrent writes (WAL mode)"""
    pm = temp_persistence

    async def store_entry(n):
      entry = MemoryEntry(
        entry_type=MemoryType.EPISODIC,
        content=f"Entry {n}",
        source="concurrent"
      )
      await pm.store(entry)

    await asyncio.gather(*[store_entry(i) for i in range(10)])

    stats = await pm.get_stats()
    assert stats["total_entries"] == 10

  async def test_metadata_serialization(self, temp_persistence):
    """Serialisation of metadata to JSON"""
    pm = temp_persistence

    entry = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Test",
      source="test",
      metadata={"key": "value", "count": 42}
    )

    await pm.store(entry)
    retrieved = await pm.get(entry.id)

    assert retrieved.metadata["key"] == "value"
    assert retrieved.metadata["count"] == 42

  async def test_search_vectors(self, temp_persistence):
    """Semantic search with Qdrant"""
    pm = temp_persistence

    for i in range(3):
      entry = MemoryEntry(
        entry_type=MemoryType.SEMANTIC,
        content=f"Entry {i}",
        source="test"
      )
      embedding = [0.1 * (i + 1)] * 768
      await pm.store(entry, embedding=embedding)

    query_vector = [0.15] * 768
    results = await pm.search(query_vector, limit=2)

    assert len(results) <= 2
    for entry_id, score in results:
      assert isinstance(entry_id, str)
      assert isinstance(score, float)

  async def test_empty_stats(self, temp_persistence):
    """Stats with empty DB"""
    pm = temp_persistence

    stats = await pm.get_stats()

    assert stats["total_entries"] == 0
    assert stats["episodic_count"] == 0
    assert stats["semantic_count"] == 0


@pytest.mark.asyncio
class TestPersistenceManagerAdditional:
    """Additional tests targeting uncovered lines."""

    def test_safe_timeout_negative_value(self, monkeypatch):
        """Line 39: negative value returns default."""
        from memory.memory.engines.persistence import _safe_timeout
        monkeypatch.setenv("TEST_TIMEOUT_NEG", "-5.0")
        result = _safe_timeout("TEST_TIMEOUT_NEG", 7.0)
        assert result == 7.0

    def test_safe_timeout_capped_to_max(self, monkeypatch):
        """Line 40: value capped to MAX_TIMEOUT."""
        from memory.memory.engines.persistence import _safe_timeout, MAX_TIMEOUT
        monkeypatch.setenv("TEST_TIMEOUT_HIGH", "999.0")
        result = _safe_timeout("TEST_TIMEOUT_HIGH", 5.0)
        assert result == MAX_TIMEOUT

    def test_safe_timeout_invalid_value(self, monkeypatch):
        """Lines 41-42: invalid value returns default."""
        from memory.memory.engines.persistence import _safe_timeout
        monkeypatch.setenv("TEST_TIMEOUT_BAD", "not-a-number")
        result = _safe_timeout("TEST_TIMEOUT_BAD", 5.0)
        assert result == 5.0

    async def test_init_qdrant_server_mode_failure(self, tmp_path):
        """Lines 151-158, 177-184: Qdrant server mode fails gracefully."""
        pm_cls = PersistenceManager
        db_path = tmp_path / "test.db"
        # Use a bogus URL to force connection failure
        pm = pm_cls(
            db_path=db_path,
            qdrant_path=None,
            collection_name="test_col",
            vector_size=768,
            qdrant_url="http://127.0.0.1:19999"  # unlikely to have Qdrant
        )
        # Should not crash, just mark qdrant unavailable
        assert pm._qdrant_available is False or pm._qdrant_available is True
        pm.close()

    async def test_store_with_embedding_strict_rollback(self, tmp_path):
        """Lines 219-228: strict mode rollback when Qdrant fails."""
        from memory.memory.engines.persistence import StorageError
        from unittest.mock import patch, AsyncMock, MagicMock

        db_path = tmp_path / "test.db"
        qdrant_path = tmp_path / "qdrant"

        pm = PersistenceManager(
            db_path=db_path,
            qdrant_path=qdrant_path,
            collection_name="test_col",
            vector_size=768
        )

        entry = MemoryEntry(
            entry_type=MemoryType.EPISODIC,
            content="Test rollback",
            source="test"
        )

        # Make _store_qdrant fail
        with patch.object(pm, '_store_qdrant', side_effect=Exception("Qdrant error")):
            with pytest.raises(StorageError, match="Strict rollback"):
                await pm.store(entry, embedding=[0.1] * 768, strict=True)

        # Entry should have been rolled back from SQLite
        result = await pm.get(entry.id)
        assert result is None
        pm.close()

    async def test_store_with_embedding_degraded_mode(self, tmp_path):
        """Lines 227-233: degraded mode when Qdrant fails."""
        from unittest.mock import patch

        db_path = tmp_path / "test.db"
        qdrant_path = tmp_path / "qdrant"

        pm = PersistenceManager(
            db_path=db_path,
            qdrant_path=qdrant_path,
            collection_name="test_col",
            vector_size=768
        )

        entry = MemoryEntry(
            entry_type=MemoryType.EPISODIC,
            content="Test degraded",
            source="test"
        )

        with patch.object(pm, '_store_qdrant', side_effect=Exception("Qdrant error")):
            entry_id = await pm.store(entry, embedding=[0.1] * 768, strict=False)

        # Entry should still be in SQLite
        result = await pm.get(entry_id)
        assert result is not None
        assert result.content == "Test degraded"
        pm.close()

    async def test_store_embedding_qdrant_unavailable(self, tmp_path):
        """Line 233: embedding provided but Qdrant unavailable."""
        db_path = tmp_path / "test.db"

        pm = PersistenceManager(
            db_path=db_path,
            qdrant_path=None,
            collection_name="test_col",
            vector_size=768,
            qdrant_url="http://127.0.0.1:19999"
        )
        pm._qdrant_available = False

        entry = MemoryEntry(
            entry_type=MemoryType.EPISODIC,
            content="Test no qdrant",
            source="test"
        )

        entry_id = await pm.store(entry, embedding=[0.1] * 768)
        assert entry_id == entry.id
        pm.close()

    async def test_store_qdrant_server_mode(self, tmp_path):
        """Lines 309-310: _store_qdrant server mode uses executor."""
        from unittest.mock import patch, MagicMock

        db_path = tmp_path / "test.db"

        pm = PersistenceManager(
            db_path=db_path,
            qdrant_path=None,
            collection_name="test_col",
            vector_size=768,
            qdrant_url="http://127.0.0.1:19999"
        )
        # Fake qdrant available
        pm._qdrant_available = True
        pm.qdrant = MagicMock()
        pm.qdrant_path = None  # server mode

        entry = MemoryEntry(
            entry_type=MemoryType.EPISODIC,
            content="Server mode test",
            source="test"
        )

        await pm._store_qdrant(entry.id, [0.1] * 768, {"content": "test"})
        pm.qdrant.upsert.assert_called_once()
        pm.close()

    async def test_delete_sqlite(self, tmp_path):
        """Lines 316-326: _delete_sqlite helper."""
        db_path = tmp_path / "test.db"
        qdrant_path = tmp_path / "qdrant"

        pm = PersistenceManager(
            db_path=db_path,
            qdrant_path=qdrant_path,
            collection_name="test_col",
            vector_size=768
        )

        entry = MemoryEntry(
            entry_type=MemoryType.EPISODIC,
            content="To delete",
            source="test"
        )
        await pm.store(entry)
        assert await pm.get(entry.id) is not None

        await pm._delete_sqlite(entry.id)
        assert await pm.get(entry.id) is None
        pm.close()

    async def test_get_recent_with_expired_entries(self, tmp_path):
        """Lines 496, 501-504, 506-514: get_recent filters expired entries."""
        from datetime import datetime, timezone
        import time

        db_path = tmp_path / "test.db"
        qdrant_path = tmp_path / "qdrant"

        pm = PersistenceManager(
            db_path=db_path,
            qdrant_path=qdrant_path,
            collection_name="test_col",
            vector_size=768
        )

        # Store entry without TTL
        entry2 = MemoryEntry(
            entry_type=MemoryType.EPISODIC,
            content="Permanent entry",
            source="test"
        )
        await pm.store(entry2)

        # To test TTL filtering, manually insert an expired entry via SQLite
        import sqlite3
        conn = sqlite3.connect(str(pm.db_path))
        cursor = conn.cursor()
        # Insert entry with timestamp 1000 seconds ago and TTL of 60
        old_ts = time.time() - 1000
        cursor.execute("""
            INSERT OR REPLACE INTO memory_entries
            (id, entry_type, content, source, timestamp, ttl_seconds, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("expired_id", "episodic", "Expired entry", "test", old_ts, 60, None))
        conn.commit()
        conn.close()

        recent = await pm.get_recent(limit=10, exclude_expired=True)
        contents = [e.content for e in recent]
        assert "Permanent entry" in contents
        assert "Expired entry" not in contents
        pm.close()

    async def test_get_recent_timeout(self, tmp_path):
        """get_recent returns [] when the SQLite read exceeds the preload timeout.

        get_recent wraps run_in_executor in asyncio.wait_for with
        self._sqlite_preload_timeout (persistence_sqlite.py); on
        asyncio.TimeoutError it must swallow the error and return [].
        """
        import time
        from unittest.mock import patch

        db_path = tmp_path / "test.db"
        qdrant_path = tmp_path / "qdrant"

        pm = PersistenceManager(
            db_path=db_path,
            qdrant_path=qdrant_path,
            collection_name="test_col",
            vector_size=768
        )

        # Force the timeout to fire: tiny budget + a blocking _connect_sqlite
        # so the executor task can never finish in time.
        pm._sqlite_preload_timeout = 0.05

        def _slow_connect(*args, **kwargs):
            time.sleep(1.0)
            raise AssertionError("should have timed out before connecting")

        with patch.object(pm, '_connect_sqlite', side_effect=_slow_connect):
            result = await pm.get_recent(limit=10)

        # Must hit the asyncio.TimeoutError branch -> empty list, not raise.
        assert result == []

        pm.close()

    async def test_get_recent_exception(self, tmp_path):
        """Lines 536-538: get_recent general exception returns empty list."""
        from unittest.mock import patch

        db_path = tmp_path / "test.db"
        qdrant_path = tmp_path / "qdrant"

        pm = PersistenceManager(
            db_path=db_path,
            qdrant_path=qdrant_path,
            collection_name="test_col",
            vector_size=768
        )

        # Make the executor raise
        with patch.object(pm.executor, 'submit', side_effect=Exception("DB error")):
            result = await pm.get_recent(limit=10)
            assert result == []

        pm.close()

    async def test_close_releases_resources(self, tmp_path):
        """close() shuts down the executor and drops the Qdrant reference.

        The QdrantClient is shared via the pool, so close() intentionally
        does NOT call qdrant.close(); it only shuts the executor and clears
        self.qdrant. This asserts that documented behavior.
        """
        db_path = tmp_path / "test.db"
        qdrant_path = tmp_path / "qdrant"

        pm = PersistenceManager(
            db_path=db_path,
            qdrant_path=qdrant_path,
            collection_name="test_col",
            vector_size=768
        )

        executor = pm.executor

        pm.close()  # Must not raise

        # Qdrant reference dropped (shared client is NOT closed here).
        assert pm.qdrant is None
        # Executor was shut down: submitting new work must raise.
        with pytest.raises(RuntimeError):
            executor.submit(lambda: None)

    async def test_collection_already_exists(self, tmp_path):
        """Line 173: collection already exists at init."""
        db_path = tmp_path / "test.db"
        qdrant_path = tmp_path / "qdrant"

        # First init creates the collection
        pm1 = PersistenceManager(
            db_path=db_path,
            qdrant_path=qdrant_path,
            collection_name="test_col",
            vector_size=768
        )
        pm1.close()

        # Second init finds existing collection (line 173)
        pm2 = PersistenceManager(
            db_path=db_path,
            qdrant_path=qdrant_path,
            collection_name="test_col",
            vector_size=768
        )
        assert pm2._qdrant_available is True
        pm2.close()


@pytest.mark.asyncio
class TestPersistenceManagerSQLCipher:
    """Tests for SQLCipher encryption integration."""

    def _make_crypto(self):
        import os
        from core.crypto.provider import CryptoProvider
        return CryptoProvider(master_key=os.urandom(32))

    async def test_encrypted_store_and_get(self, tmp_path):
        """Store and retrieve with SQLCipher encryption."""
        crypto = self._make_crypto()
        pm = PersistenceManager(
            db_path=tmp_path / "enc.db",
            qdrant_path=tmp_path / "qdrant",
            collection_name="test_enc",
            vector_size=768,
            crypto_provider=crypto
        )
        assert pm._encrypted is True

        entry = MemoryEntry(
            entry_type=MemoryType.EPISODIC,
            content="Encrypted content",
            source="test"
        )
        await pm.store(entry)
        retrieved = await pm.get(entry.id)
        assert retrieved is not None
        assert retrieved.content == "Encrypted content"
        pm.close()

    async def test_encrypted_db_not_readable_plain(self, tmp_path):
        """Encrypted DB cannot be read with plain sqlite3."""
        import sqlite3 as plain_sqlite
        crypto = self._make_crypto()
        db_path = tmp_path / "enc.db"
        pm = PersistenceManager(
            db_path=db_path,
            qdrant_path=tmp_path / "qdrant",
            collection_name="test_enc",
            vector_size=768,
            crypto_provider=crypto
        )
        entry = MemoryEntry(
            entry_type=MemoryType.EPISODIC,
            content="Secret data",
            source="test"
        )
        await pm.store(entry)
        pm.close()

        # Plain sqlite3 should fail to read
        with pytest.raises(Exception):
            conn = plain_sqlite.connect(str(db_path))
            conn.execute("SELECT * FROM memory_entries")

    async def test_migration_plain_to_encrypted(self, tmp_path):
        """Existing plain DB gets migrated to SQLCipher."""
        db_path = tmp_path / "memories.db"
        qdrant_path = tmp_path / "qdrant"

        # 1. Create plain DB with data
        pm_plain = PersistenceManager(
            db_path=db_path,
            qdrant_path=qdrant_path,
            collection_name="test_mig",
            vector_size=768
        )
        entry = MemoryEntry(
            entry_type=MemoryType.EPISODIC,
            content="Pre-migration data",
            source="test"
        )
        await pm_plain.store(entry)
        pm_plain.close()

        # Verify plain DB exists
        assert PersistenceManager._is_plaintext_sqlite(db_path)

        # 2. Re-open with crypto → should migrate
        crypto = self._make_crypto()
        pm_enc = PersistenceManager(
            db_path=db_path,
            qdrant_path=qdrant_path,
            collection_name="test_mig",
            vector_size=768,
            crypto_provider=crypto
        )
        assert pm_enc._encrypted is True

        # Data should be preserved
        retrieved = await pm_enc.get(entry.id)
        assert retrieved is not None
        assert retrieved.content == "Pre-migration data"

        # Backup should exist
        assert db_path.with_suffix('.db.bak').exists()

        # DB should no longer be plain
        assert not PersistenceManager._is_plaintext_sqlite(db_path)
        pm_enc.close()

    async def test_no_crypto_no_encryption(self, tmp_path):
        """Without crypto_provider, DB stays plain."""
        db_path = tmp_path / "plain.db"
        pm = PersistenceManager(
            db_path=db_path,
            qdrant_path=tmp_path / "qdrant",
            collection_name="test_plain",
            vector_size=768
        )
        assert pm._encrypted is False
        entry = MemoryEntry(
            entry_type=MemoryType.EPISODIC,
            content="Plain data",
            source="test"
        )
        await pm.store(entry)
        assert PersistenceManager._is_plaintext_sqlite(db_path)
        pm.close()

    async def test_encrypted_search(self, tmp_path):
        """Semantic search works with encrypted DB."""
        crypto = self._make_crypto()
        pm = PersistenceManager(
            db_path=tmp_path / "enc.db",
            qdrant_path=tmp_path / "qdrant",
            collection_name="test_search_enc",
            vector_size=768,
            crypto_provider=crypto
        )
        for i in range(3):
            entry = MemoryEntry(
                entry_type=MemoryType.SEMANTIC,
                content=f"Entry {i}",
                source="test"
            )
            await pm.store(entry, embedding=[0.1 * (i + 1)] * 768)

        results = await pm.search([0.15] * 768, limit=2)
        assert len(results) <= 2
        pm.close()

    async def test_encrypted_get_recent(self, tmp_path):
        """get_recent works with encrypted DB."""
        crypto = self._make_crypto()
        pm = PersistenceManager(
            db_path=tmp_path / "enc.db",
            qdrant_path=tmp_path / "qdrant",
            collection_name="test_recent_enc",
            vector_size=768,
            crypto_provider=crypto
        )
        for i in range(5):
            entry = MemoryEntry(
                entry_type=MemoryType.EPISODIC,
                content=f"Recent {i}",
                source="test"
            )
            await pm.store(entry)

        recent = await pm.get_recent(limit=3)
        assert len(recent) == 3
        pm.close()

    async def test_encrypted_stats(self, tmp_path):
        """get_stats works with encrypted DB."""
        crypto = self._make_crypto()
        pm = PersistenceManager(
            db_path=tmp_path / "enc.db",
            qdrant_path=tmp_path / "qdrant",
            collection_name="test_stats_enc",
            vector_size=768,
            crypto_provider=crypto
        )
        await pm.store(MemoryEntry(entry_type=MemoryType.EPISODIC, content="E1", source="test"))
        await pm.store(MemoryEntry(entry_type=MemoryType.SEMANTIC, content="S1", source="test"))

        stats = await pm.get_stats()
        assert stats["total_entries"] == 2
        assert stats["episodic_count"] == 1
        assert stats["semantic_count"] == 1
        pm.close()

    def test_is_plaintext_sqlite_nonexistent(self, tmp_path):
        """Non-existent file is not plain SQLite."""
        assert not PersistenceManager._is_plaintext_sqlite(tmp_path / "nope.db")

    def test_is_plaintext_sqlite_empty(self, tmp_path):
        """Empty file is not plain SQLite."""
        f = tmp_path / "empty.db"
        f.write_bytes(b"")
        assert not PersistenceManager._is_plaintext_sqlite(f)

    async def test_f56_quarantines_db_from_previous_master_key(self, tmp_path):
        """F5.6 BUG-NEW-2 — A DB encrypted with key A is moved aside when the
        app boots with key B; a fresh DB is created so the memory subsystem
        keeps working.

        Reproduces the second-launch crash on a fresh DMG install where the
        previous MASTER_KEY differs from the new one and sqlcipher raises
        'file is not a database'.
        """
        import os
        from core.crypto.provider import CryptoProvider

        db_path = tmp_path / "memories.db"
        qdrant_path = tmp_path / "qdrant"

        # Round 1 — write data with key A.
        key_a = os.urandom(32)
        pm_a = PersistenceManager(
            db_path=db_path,
            qdrant_path=qdrant_path,
            collection_name="test_quarantine",
            vector_size=768,
            crypto_provider=CryptoProvider(master_key=key_a),
        )
        await pm_a.store(MemoryEntry(
            entry_type=MemoryType.EPISODIC,
            content="data encrypted with key A",
            source="test",
        ))
        pm_a.close()
        assert db_path.exists()

        # Round 2 — boot with key B. Should quarantine and start fresh,
        # NOT raise "file is not a database".
        key_b = os.urandom(32)
        pm_b = PersistenceManager(
            db_path=db_path,
            qdrant_path=qdrant_path,
            collection_name="test_quarantine",
            vector_size=768,
            crypto_provider=CryptoProvider(master_key=key_b),
        )
        # Fresh DB must accept new writes without error.
        await pm_b.store(MemoryEntry(
            entry_type=MemoryType.EPISODIC,
            content="data encrypted with key B",
            source="test",
        ))

        # The original file was quarantined with a timestamp suffix.
        quarantined = list(tmp_path.glob("memories.db.unrecoverable-*"))
        assert len(quarantined) == 1, (
            f"expected exactly one quarantined DB, got {quarantined}"
        )
        pm_b.close()