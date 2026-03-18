"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/engines/flash_memory.py
Description: FlashMemory - Cache TTL with asyncio.Lock and backpressure control.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import heapq
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from ..models.memory_entry import MemoryEntry

logger = logging.getLogger(__name__)

def _normalize_expiry(expiry: datetime) -> datetime:
  if expiry.tzinfo is None:
    return expiry.replace(tzinfo=timezone.utc)
  return expiry

class FlashMemory:
  """
  Volatile cache with TTL and auto-cleanup.

  Features:
  - asyncio.Lock (NOT threading.Lock)
  - TTL per entry (default: 30 min)
  - Heap for efficient cleanup
  """

  def __init__(
    self,
    default_ttl_seconds: int = 1800
  ):
    self._store: Dict[str, MemoryEntry] = {}
    self._expiry_heap: List[tuple] = []
    self._lock = asyncio.Lock()
    self._default_ttl = default_ttl_seconds

    logger.info("FlashMemory initialized (TTL=%ss)", default_ttl_seconds)

  async def store(self, entry: MemoryEntry) -> str:
    """
    Store entry in Flash with TTL.

    Args:
      entry: MemoryEntry to store

    Returns:
      str: Entry ID
    """
    async with self._lock:
      ttl = entry.ttl_seconds or self._default_ttl
      expiry = datetime.now(timezone.utc) + timedelta(seconds=ttl)

      self._store[entry.id] = entry

      heapq.heappush(self._expiry_heap, (expiry.timestamp(), entry.id))

      logger.debug("Stored entry %s (TTL=%ss, expires=%s)", entry.id, ttl, expiry)

    return entry.id

  async def get(self, entry_id: str) -> Optional[MemoryEntry]:
    """
    Retrieve entry by ID.

    Args:
      entry_id: Entry ID

    Returns:
      MemoryEntry or None if not exists/expired
    """
    async with self._lock:
      entry = self._store.get(entry_id)

      if not entry:
        return None

      if self._is_expired(entry):
        del self._store[entry_id]
        logger.debug("Entry %s expired, removed", entry_id)
        return None

      return entry

  async def get_all(self, limit: int = 100) -> List[MemoryEntry]:
    """
    Retrieve all entries (not expired).

    Args:
      limit: Maximum number of entries to return

    Returns:
      List[MemoryEntry]
    """
    async with self._lock:
      await self._cleanup_expired()

      entries = sorted(self._store.values(), key=lambda e: e.timestamp, reverse=True)[:limit]
      return entries

  async def delete(self, entry_id: str) -> bool:
    """
    Delete entry by ID.

    Args:
      entry_id: Entry ID

    Returns:
      bool: True if deleted, False if not existed
    """
    async with self._lock:
      if entry_id in self._store:
        del self._store[entry_id]
        logger.debug("Deleted entry %s", entry_id)
        return True
      return False

  async def cleanup_expired(self) -> int:
    """
    Manual cleanup of expired entries.

    Returns:
      int: Number of deleted entries
    """
    async with self._lock:
      return await self._cleanup_expired()

  async def _cleanup_expired(self) -> int:
    """
    Internal cleanup of expired entries (NO lock, call within lock).

    Returns:
      int: Number of deleted entries
    """
    now = datetime.now(timezone.utc).timestamp()
    deleted_count = 0

    while self._expiry_heap:
      expiry_ts, entry_id = self._expiry_heap[0]

      if expiry_ts > now:
        break

      heapq.heappop(self._expiry_heap)

      if entry_id in self._store:
        del self._store[entry_id]
        deleted_count += 1

    if deleted_count > 0:
      logger.info("Cleaned up %s expired entries", deleted_count)

    return deleted_count

  def _is_expired(self, entry: MemoryEntry) -> bool:
    """
    Check if an entry has expired.

    Args:
      entry: MemoryEntry to verify

    Returns:
      bool: True if expired
    """
    ttl = entry.ttl_seconds or self._default_ttl
    expiry = entry.timestamp + timedelta(seconds=ttl)
    expiry = _normalize_expiry(expiry)
    return datetime.now(timezone.utc) > expiry

  async def get_stats(self) -> Dict[str, int]:
    """
    Get FlashMemory statistics.

    Returns:
      Dict with stats (total_entries, expired_pending)
    """
    async with self._lock:
      total_entries = len(self._store)
      heap_size = len(self._expiry_heap)

    return {
      "total_entries": total_entries,
      "expired_pending": heap_size
    }

__all__ = ["FlashMemory"]