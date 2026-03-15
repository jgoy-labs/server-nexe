"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/pipeline/deduplicator.py
Description: Deduplicator - Detecció de contingut duplicat amb SHA256.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import hashlib
import logging
from typing import Set

from ..models.memory_entry import MemoryEntry

logger = logging.getLogger(__name__)

class Deduplicator:
  """
  Deduplicador de contingut per pipeline d'ingesta.

  Features:
  - SHA256 hash per ID determinista
  - Cache in-memory de IDs processats
  - Check contra Persistence per duplicats existents
  """

  def __init__(self):
    self._seen_ids: Set[str] = set()
    logger.info("Deduplicator initialized")

  def is_duplicate(self, entry: MemoryEntry) -> bool:
    """
    Verificar si una entrada és duplicada.

    Args:
      entry: MemoryEntry a verificar

    Returns:
      bool: True si és duplicada
    """
    entry_id = entry.id

    if entry_id in self._seen_ids:
      logger.debug(f"Duplicate detected (in-memory): {entry_id}")
      return True

    self._seen_ids.add(entry_id)
    return False

  def mark_as_seen(self, entry_id: str):
    """
    Marcar un ID com processat (per duplicats de Persistence).

    Args:
      entry_id: ID de l'entrada
    """
    self._seen_ids.add(entry_id)

  def clear_cache(self):
    """Netejar cache in-memory (per testing o reset)"""
    self._seen_ids.clear()
    logger.info("Deduplicator cache cleared")

  def get_stats(self) -> dict:
    """Obtenir estadístiques del deduplicator"""
    return {
      "seen_ids_count": len(self._seen_ids)
    }

  @staticmethod
  def compute_content_hash(content: str) -> str:
    """
    Calcular hash determinista del contingut.

    Args:
      content: Text a hashejar

    Returns:
      str: SHA256 hash (16 primers chars)
    """
    return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]

__all__ = ["Deduplicator"]