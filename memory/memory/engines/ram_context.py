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
  Vista immutable sobre FlashMemory per context window LLM.

  Features:
  - FIFO: max 100 entries més recents
  - Read-only (no modifica Flash)
  - to_context_string() amb safeguards
  - Refresh automàtic des de Flash
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
    Recuperar últimes N entries per context window.

    Args:
      limit: Màxim entries (default: self._max_entries)
      safe_mode: Truncar content per seguretat

    Returns:
      List[MemoryEntry] ordenades per timestamp DESC
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
    Generar string de context per LLM amb safeguards.

    Args:
      limit: Màxim entries a incloure
      max_length_per_entry: Màxim chars per entrada
      safe_mode: Activar truncació anti-info-leak

    Returns:
      str: Context formatat per LLM
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
    Recuperar últimes N entries d'un tipus específic.

    Args:
      entry_type: Tipus de memòria (MemoryType.EPISODIC/SEMANTIC)
      limit: Màxim entries

    Returns:
      List[MemoryEntry] filtrades per tipus
    """
    all_entries = await self.get_context_window(limit=self._max_entries)

    filtered = [e for e in all_entries if e.entry_type == entry_type]

    logger.debug(f"Filtered {len(filtered)} entries of type '{entry_type.value}'")

    return filtered[:limit]

  async def get_stats(self) -> dict:
    """
    Obtenir estadístiques de RAMContext.

    Returns:
      Dict amb stats (total_available, episodic_count, semantic_count)
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