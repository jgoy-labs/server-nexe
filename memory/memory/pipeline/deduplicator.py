"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/pipeline/deduplicator.py
Description: Deduplicator - Duplicate content detection using SHA256.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import hashlib
import logging
import re
from typing import Dict, Optional, Set

from ..models.memory_entry import MemoryEntry

logger = logging.getLogger(__name__)

# Normalized city/location aliases for semantic dedup
_LOCATION_ALIASES: Dict[str, str] = {
    "bcn": "barcelona",
    "barna": "barcelona",
    "mad": "madrid",
    "vlc": "valencia",
    "nyc": "new york",
    "sf": "san francisco",
    "la": "los angeles",
    "ldn": "london",
}

# Patterns to extract attribute+value for semantic dedup (lightweight, no Extractor dependency)
_SEMANTIC_PATTERNS = [
    # Location: "visc a X", "soc de X", "la meva ciutat és X", "X és on visc"
    (
        "location",
        [
            re.compile(r"(?:visc\s+a|vivo\s+en|i\s+live\s+in)\s+(.+?)(?:\.|,|$)", re.IGNORECASE),
            re.compile(r"(?:soc\s+de|soy\s+de|i(?:'m|\s+am)\s+from)\s+(.+?)(?:\.|,|$)", re.IGNORECASE),
            re.compile(r"(?:la\s+meva\s+ciutat\s+[eé]s|mi\s+ciudad\s+es|my\s+city\s+is)\s+(.+?)(?:\.|,|$)", re.IGNORECASE),
            re.compile(r"(.+?)\s+[eé]s\s+on\s+visc", re.IGNORECASE),
        ],
    ),
    # Name: "em dic X", "me llamo X", "my name is X"
    (
        "name",
        [
            re.compile(r"(?:em\s+dic|me\s+llamo|my\s+name\s+is)\s+([A-Za-zÀ-ÿ]+)", re.IGNORECASE),
        ],
    ),
    # Occupation: "soc X" (when followed by occupation-like words)
    (
        "occupation",
        [
            re.compile(r"(?:soc\s+(?:un\s+|una\s+)?|soy\s+(?:un\s+|una\s+)?|i\s+am\s+(?:a\s+|an\s+)?)(\w[\w\s]{2,30}?)(?:\.|,|$)", re.IGNORECASE),
        ],
    ),
]


class Deduplicator:
  """
  Content deduplicator for the ingestion pipeline.

  Features:
  - SHA256 hash for deterministic ID (exact dedup)
  - Semantic dedup by normalised attribute+value (semantic dedup)
  - In-memory cache of processed IDs
  - Check against Persistence for existing duplicates
  """

  def __init__(self) -> None:
    self._seen_ids: Set[str] = set()
    self._seen_semantic: Dict[str, str] = {}  # "attr:normalized_value" -> first entry_id
    logger.info("Deduplicator initialized")

  def is_duplicate(self, entry: MemoryEntry) -> bool:
    """
    Check whether an entry is a duplicate (exact or semantic).

    Args:
      entry: MemoryEntry to check

    Returns:
      bool: True if it is a duplicate
    """
    entry_id = entry.id

    # 1. Exact hash dedup
    if entry_id in self._seen_ids:
      logger.debug("Duplicate detected (exact hash): %s", entry_id)
      return True

    # 2. Semantic dedup: same attribute+value expressed differently
    semantic_key = self._extract_semantic_key(entry.content)
    if semantic_key:
      if semantic_key in self._seen_semantic:
        original_id = self._seen_semantic[semantic_key]
        logger.debug(
            "Duplicate detected (semantic): %s matches %s via key '%s'",
            entry_id, original_id, semantic_key,
        )
        return True
      self._seen_semantic[semantic_key] = entry_id

    self._seen_ids.add(entry_id)
    return False

  def _extract_semantic_key(self, content: str) -> Optional[str]:
    """
    Extract a normalized semantic key from content.

    Returns:
      "attribute:normalized_value" or None if no pattern matched
    """
    for attribute, patterns in _SEMANTIC_PATTERNS:
      for pattern in patterns:
        match = pattern.search(content)
        if match:
          raw_value = match.group(1).strip().rstrip(".")
          normalized = self._normalize_value(raw_value)
          if normalized:
            return f"{attribute}:{normalized}"
    return None

  @staticmethod
  def _normalize_value(value: str) -> str:
    """Normalize a value for comparison (lowercase, resolve aliases)."""
    lower = value.lower().strip()
    # Check location aliases
    if lower in _LOCATION_ALIASES:
      return _LOCATION_ALIASES[lower]
    return lower

  def mark_as_seen(self, entry_id: str):
    """
    Mark an ID as processed (for duplicates from Persistence).

    Args:
      entry_id: Entry ID
    """
    self._seen_ids.add(entry_id)

  def clear_cache(self):
    """Clear in-memory cache (for testing or reset)"""
    self._seen_ids.clear()
    logger.info("Deduplicator cache cleared")

  def get_stats(self) -> dict:
    """Get deduplicator statistics."""
    return {
      "seen_ids_count": len(self._seen_ids)
    }

  @staticmethod
  def compute_content_hash(content: str) -> str:
    """
    Calculate deterministic hash of the content.

    Args:
      content: Text to hash

    Returns:
      str: SHA256 hash (first 16 chars)
    """
    return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]

__all__ = ["Deduplicator"]