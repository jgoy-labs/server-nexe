"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/tests/test_flash_memory.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta

from memory.memory.engines.flash_memory import FlashMemory
from memory.memory.models.memory_entry import MemoryEntry
from memory.memory.models.memory_types import MemoryType

@pytest.mark.asyncio
class TestFlashMemory:
  """Tests for FlashMemory TTL cache"""

  async def test_initialization(self):
    """Initialisation with default TTL"""
    flash = FlashMemory(default_ttl_seconds=1800)
    assert flash._default_ttl == 1800
    assert len(flash._store) == 0
    assert len(flash._expiry_heap) == 0

  async def test_store_and_get(self):
    """Store and retrieve entry"""
    flash = FlashMemory()
    entry = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Test content",
      source="test"
    )

    await flash.store(entry)
    retrieved = await flash.get(entry.id)

    assert retrieved is not None
    assert retrieved.id == entry.id
    assert retrieved.content == "Test content"

  async def test_get_nonexistent(self):
    """Retrieving a non-existent entry returns None"""
    flash = FlashMemory()
    result = await flash.get("nonexistent_id")
    assert result is None

  async def test_restore_does_not_evict_refreshed_entry_mem001(self):
    """MEM-001 regression: a stale (expiry, id) tuple left behind by an earlier
    store() must NOT evict the live, refreshed entry. _cleanup_expired now
    re-validates the entry's current expiry before deleting (lazy-delete)."""
    import heapq
    flash = FlashMemory(default_ttl_seconds=3600)  # long TTL → not expired
    entry = MemoryEntry(entry_type=MemoryType.EPISODIC, content="x", source="t")
    await flash.store(entry)  # pushes a fresh, far-future tuple
    # Simulate the leftover tuple from a prior, shorter-lived store of the same id.
    heapq.heappush(flash._expiry_heap, (0.0, entry.id))  # epoch → "expired" tuple
    removed = await flash.cleanup_expired()
    assert removed == 0                                # stale tuple ignored
    assert await flash.get(entry.id) is not None       # live entry survives

  async def test_ttl_expiration(self):
    """Entry with a real TTL whose creation timestamp is older than the TTL is
    expired and evicted on get() (no time.sleep — drive it via the timestamp)."""
    flash = FlashMemory(default_ttl_seconds=60)
    old = datetime.now(timezone.utc) - timedelta(seconds=120)
    entry = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Will expire",
      source="test",
      ttl_seconds=60,
      timestamp=old,
    )

    await flash.store(entry)

    assert flash._is_expired(entry) is True
    assert await flash.get(entry.id) is None  # expired → evicted on read

  async def test_none_ttl_is_permanent(self):
    """B113: ttl_seconds=None means permanent — even an entry with a very old
    creation timestamp never expires (consistent with the SQLite / Document
    layers). Mutation gate: under the old `ttl or default` fallback the default
    would expire this entry over its old timestamp."""
    flash = FlashMemory(default_ttl_seconds=60)
    old = datetime.now(timezone.utc) - timedelta(days=3650)
    entry = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Permanent fact",
      source="test",
      ttl_seconds=None,
      timestamp=old,
    )

    await flash.store(entry)

    assert flash._is_expired(entry) is False
    assert await flash.get(entry.id) is not None  # survives despite old timestamp
    # Permanent entries push no expiry tuple onto the heap.
    assert len(flash._expiry_heap) == 0

  async def test_permanent_survives_alongside_expired_entry(self):
    """B113: a permanent (None) entry coexists with a real-TTL entry. Only the
    TTL entry occupies the expiry heap; on read the expired one is lazily
    evicted while the permanent one survives — the heap carries no dead
    reference to the permanent entry."""
    flash = FlashMemory(default_ttl_seconds=60)
    old = datetime.now(timezone.utc) - timedelta(seconds=120)
    permanent = MemoryEntry(
      entry_type=MemoryType.EPISODIC, content="permanent fact",
      source="test", ttl_seconds=None, timestamp=old,
    )
    expired = MemoryEntry(
      entry_type=MemoryType.EPISODIC, content="will expire",
      source="test", ttl_seconds=60, timestamp=old,  # timestamp+ttl already past
    )

    await flash.store(permanent)
    await flash.store(expired)

    # only the TTL entry scheduled an expiry tuple; the permanent one did not
    assert len(flash._expiry_heap) == 1
    # lazy eviction on read: expired gone, permanent stays
    assert await flash.get(expired.id) is None
    assert await flash.get(permanent.id) is not None

  async def test_cleanup_expired(self):
    """Cleanup removes expired entries"""
    flash = FlashMemory(default_ttl_seconds=60)

    entry1 = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Expires soon",
      source="test",
      ttl_seconds=60
    )

    entry2 = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Stays longer",
      source="test",
      ttl_seconds=3600
    )

    await flash.store(entry1)
    await flash.store(entry2)

    assert len(flash._store) == 2

    removed = await flash.cleanup_expired()

    assert removed == 0
    assert len(flash._store) == 2

  async def test_get_all(self):
    """Retrieve all entries"""
    flash = FlashMemory()

    entry1 = MemoryEntry(entry_type=MemoryType.EPISODIC, content="One", source="test")
    entry2 = MemoryEntry(entry_type=MemoryType.SEMANTIC, content="Two", source="test")

    await flash.store(entry1)
    await flash.store(entry2)

    all_entries = await flash.get_all()

    assert len(all_entries) == 2
    assert any(e.content == "One" for e in all_entries)
    assert any(e.content == "Two" for e in all_entries)

  async def test_concurrent_access(self):
    """Concurrent access with asyncio.Lock"""
    flash = FlashMemory()

    async def store_entry(n):
      entry = MemoryEntry(
        entry_type=MemoryType.EPISODIC,
        content=f"Entry {n}",
        source="concurrent"
      )
      await flash.store(entry)

    await asyncio.gather(*[store_entry(i) for i in range(10)])

    all_entries = await flash.get_all()
    assert len(all_entries) == 10

  async def test_overwrite_same_id(self):
    """Storing same ID updates entry"""
    flash = FlashMemory()

    entry1 = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Original",
      source="test"
    )

    await flash.store(entry1)

    entry2 = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Original",
      source="updated"
    )

    await flash.store(entry2)

    all_entries = await flash.get_all()
    assert len(all_entries) == 1
    assert all_entries[0].source == "updated"