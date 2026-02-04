"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/tests/test_persistence.py
Description: No description available.

www.jgoy.net
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
  """Fixture: PersistenceManager amb paths temporals"""
  temp_dir = Path(tempfile.mkdtemp())
  db_path = temp_dir / "test_memory.db"
  qdrant_path = temp_dir / "test_qdrant"

  pm = PersistenceManager(
    db_path=db_path,
    qdrant_path=qdrant_path,
    collection_name="test_collection",
    vector_size=384
  )

  yield pm

  pm.close()
  shutil.rmtree(temp_dir, ignore_errors=True)

@pytest.mark.asyncio
class TestPersistenceManager:
  """Tests per PersistenceManager"""

  async def test_initialization(self, temp_persistence):
    """Inicialització SQLite + Qdrant"""
    pm = temp_persistence

    assert pm.db_path.exists()

    assert pm.qdrant_path.exists()

    collections = pm.qdrant.get_collections().collections
    collection_names = [c.name for c in collections]
    assert "test_collection" in collection_names

  async def test_store_and_get(self, temp_persistence):
    """Emmagatzemar i recuperar entry"""
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
    """Emmagatzemar amb embedding vector"""
    pm = temp_persistence

    entry = MemoryEntry(
      entry_type=MemoryType.SEMANTIC,
      content="Knowledge entry",
      source="test"
    )

    embedding = [0.1] * 384

    entry_id = await pm.store(entry, embedding=embedding)

    assert entry_id == entry.id

    retrieved = await pm.get(entry_id)
    assert retrieved is not None

  async def test_get_nonexistent(self, temp_persistence):
    """Recuperar entry inexistent retorna None"""
    pm = temp_persistence

    result = await pm.get("nonexistent_id")

    assert result is None

  async def test_hex_to_uuid_conversion(self):
    """Conversió hex ID a UUID format"""
    hex_id = "019c2cdb30d195ae"

    uuid_str = PersistenceManager._hex_to_uuid(hex_id)

    assert len(uuid_str) == 36
    assert uuid_str.count('-') == 4
    assert uuid_str.startswith("019c2cdb-30d1-95ae-0000")

  async def test_insert_or_replace(self, temp_persistence):
    """INSERT OR REPLACE actualitza entry existent"""
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
    """Obtenir estadístiques de persistència"""
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
    """Escriptures concurrents (WAL mode)"""
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
    """Serialització de metadata a JSON"""
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
    """Cerca semàntica amb Qdrant"""
    pm = temp_persistence

    for i in range(3):
      entry = MemoryEntry(
        entry_type=MemoryType.SEMANTIC,
        content=f"Entry {i}",
        source="test"
      )
      embedding = [0.1 * (i + 1)] * 384
      await pm.store(entry, embedding=embedding)

    query_vector = [0.15] * 384
    results = await pm.search(query_vector, limit=2)

    assert len(results) <= 2
    for entry_id, score in results:
      assert isinstance(entry_id, str)
      assert isinstance(score, float)

  async def test_empty_stats(self, temp_persistence):
    """Stats amb BD buida"""
    pm = temp_persistence

    stats = await pm.get_stats()

    assert stats["total_entries"] == 0
    assert stats["episodic_count"] == 0
    assert stats["semantic_count"] == 0