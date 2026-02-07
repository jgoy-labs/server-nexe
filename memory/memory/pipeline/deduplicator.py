"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/pipeline/deduplicator.py
Description: Deduplicator - Duplicate content detection with SHA256.

www.jgoy.net
────────────────────────────────────
"""

import hashlib
import logging
from typing import Set

from ..models.memory_entry import MemoryEntry
from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)

def _t(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"memory.deduplicator.{key}", fallback, **kwargs)

class Deduplicator:
  """
  Content deduplicator for the ingestion pipeline.

  Features:
  - SHA256 hash for deterministic IDs
  - In-memory cache of processed IDs
  - Check against Persistence for existing duplicates
  """

  def __init__(self):
    self._seen_ids: Set[str] = set()
    logger.info(_t("initialized", "Deduplicator initialized"))

  def is_duplicate(self, entry: MemoryEntry) -> bool:
    """
    Check whether an entry is a duplicate.

    Args:
      entry: MemoryEntry to check

    Returns:
      bool: True if duplicate
    """
    entry_id = entry.id

    if entry_id in self._seen_ids:
      logger.debug(_t(
        "duplicate_detected",
        "Duplicate detected (in-memory): {id}",
        id=entry_id
      ))
      return True

    self._seen_ids.add(entry_id)
    return False

  def mark_as_seen(self, entry_id: str):
    """
    Mark an ID as processed (for Persistence duplicates).

    Args:
      entry_id: Entry ID
    """
    self._seen_ids.add(entry_id)

  def clear_cache(self):
    """Clear the in-memory cache (for testing or reset)."""
    self._seen_ids.clear()
    logger.info(_t("cache_cleared", "Deduplicator cache cleared"))

  def get_stats(self) -> dict:
    """Get deduplicator statistics."""
    return {
      "seen_ids_count": len(self._seen_ids)
    }

  @staticmethod
  def compute_content_hash(content: str) -> str:
    """
    Compute deterministic hash of the content.

    Args:
      content: Text to hash

    Returns:
      str: SHA256 hash (first 16 chars)
    """
    return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]

__all__ = ["Deduplicator"]
