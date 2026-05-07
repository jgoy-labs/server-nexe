"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/engines/ram_context.py
Description: RAMContext - Vista immutable sobre FlashMemory (FIFO, max 100 entries).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from typing import List, Optional

from .flash_memory import FlashMemory
from ..models.memory_entry import MemoryEntry
from ..models.memory_types import MemoryType

logger = logging.getLogger(__name__)

class RAMContext:
  """
  Immutable view over FlashMemory for LLM context window.

  Features:
  - FIFO: max 100 most recent entries
  - Read-only (does not modify Flash)
  - to_context_string() with safeguards
  - Automatic refresh from Flash
  """

  def __init__(
    self,
    flash_memory: FlashMemory,
    max_entries: int = 100
  ):
    self._flash = flash_memory
    self._max_entries = max_entries

    logger.info(f"RAMContext initialized (max_entries={max_entries})")

  async def get_context_window(
    self,
    limit: Optional[int] = None,
    safe_mode: bool = True
  ) -> List[MemoryEntry]:
    """
    Retrieve last N entries for context window.

    Args:
      limit: Maximum entries (default: self._max_entries)
      safe_mode: Truncate content for safety

    Returns:
      List[MemoryEntry] sorted by timestamp DESC
    """
    effective_limit = min(limit or self._max_entries, self._max_entries)

    # flash.get_all() now returns sorted by timestamp (SC1 fix)
    entries = await self._flash.get_all(limit=effective_limit)

    logger.debug(f"RAMContext returned {len(entries)} entries")

    return entries

  async def to_context_string(
    self,
    limit: Optional[int] = None,
    max_length_per_entry: int = 300,
    safe_mode: bool = True
  ) -> str:
    """
    Generate context string for LLM with safeguards.

    Args:
      limit: Maximum entries to include
      max_length_per_entry: Maximum chars per entry
      safe_mode: Enable anti-info-leak truncation

    Returns:
      str: Context formatted for LLM
    """
    entries = await self.get_context_window(limit=limit, safe_mode=safe_mode)

    context_lines = []
    for entry in entries:
      line = entry.to_context_string(
        max_length=max_length_per_entry,
        safe_mode=safe_mode
      )
      context_lines.append(line)

    context = "\n".join(context_lines)

    logger.debug(f"Generated context string ({len(context)} chars, {len(entries)} entries)")

    return context

  async def get_recent_by_type(
    self,
    entry_type: MemoryType,
    limit: int = 20
  ) -> List[MemoryEntry]:
    """
    Retrieve last N entries of a specific type.

    Args:
      entry_type: Memory type (MemoryType.EPISODIC/SEMANTIC)
      limit: Maximum entries

    Returns:
      List[MemoryEntry] filtered by type
    """
    all_entries = await self.get_context_window(limit=self._max_entries)

    filtered = [e for e in all_entries if e.entry_type == entry_type]

    logger.debug(f"Filtered {len(filtered)} entries of type '{entry_type.value}'")

    return filtered[:limit]

  async def get_stats(self) -> dict:
    """
    Get RAMContext statistics.

    Returns:
      Dict with stats (total_available, episodic_count, semantic_count)
    """
    entries = await self.get_context_window(limit=self._max_entries)

    episodic_count = sum(1 for e in entries if e.entry_type == MemoryType.EPISODIC)
    semantic_count = sum(1 for e in entries if e.entry_type == MemoryType.SEMANTIC)

    return {
      "total_available": len(entries),
      "max_entries": self._max_entries,
      "episodic_count": episodic_count,
      "semantic_count": semantic_count,
    }

__all__ = ["RAMContext"]