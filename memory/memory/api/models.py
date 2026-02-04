"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/api/models.py
Description: Models i exceptions per Memory API.

www.jgoy.net
────────────────────────────────────
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

def _coerce_aware(dt: datetime) -> datetime:
  if dt.tzinfo is None:
    return dt.replace(tzinfo=timezone.utc)
  return dt

class MemoryAPIError(Exception):
  """Base exception per Memory API."""

class CollectionNotFoundError(MemoryAPIError):
  """Collection no existeix."""

class InvalidCollectionNameError(MemoryAPIError):
  """Nom de collection invàlid (no segueix naming convention)."""

class DocumentNotFoundError(MemoryAPIError):
  """Document no trobat."""

COLLECTION_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*_[a-z][a-z0-9_]*$")

def validate_collection_name(name: str) -> None:
  """
  Valida que el nom de collection segueix la naming convention.

  Format: {modul}_{tipus}
  - Només minúscules, números i underscore
  - Ha de tenir almenys un underscore separant modul i tipus
  - Ha de començar amb lletra

  Args:
    name: Nom de la collection

  Raises:
    InvalidCollectionNameError: Si el nom no és vàlid

  Examples:
    validate_collection_name("nexe_knowledge")
    validate_collection_name("memory_rag_sources")
    validate_collection_name("Nexe_Knowledge")
    validate_collection_name("memory")
  """
  if not COLLECTION_NAME_PATTERN.match(name):
    raise InvalidCollectionNameError(
      f"Invalid collection name '{name}'. "
      f"Must follow pattern '{{modul}}_{{tipus}}' with only lowercase, numbers and underscores. "
      f"Examples: 'nexe_knowledge', 'memory_sources', 'system_logs'"
    )

@dataclass
class Document:
  """
  Document retornat per l'API.

  Attributes:
    id: Identificador únic del document
    text: Contingut textual
    collection: Nom de la collection
    metadata: Metadades addicionals
    created_at: Timestamp de creació
    expires_at: Timestamp d'expiració (None = permanent)
  """

  id: str
  text: str
  collection: str
  metadata: Dict[str, Any] = field(default_factory=dict)
  created_at: Optional[datetime] = None
  expires_at: Optional[datetime] = None

  @property
  def is_expired(self) -> bool:
    """Comprova si el document ha expirat."""
    if self.expires_at is None:
      return False
    now = datetime.now(timezone.utc)
    expires_at = _coerce_aware(self.expires_at)
    return now > expires_at

  @property
  def ttl_remaining(self) -> Optional[int]:
    """Retorna segons restants fins expiració, o None si permanent."""
    if self.expires_at is None:
      return None
    now = datetime.now(timezone.utc)
    expires_at = _coerce_aware(self.expires_at)
    remaining = (expires_at - now).total_seconds()
    return max(0, int(remaining))

@dataclass
class SearchResult:
  """
  Resultat d'una cerca semàntica.

  Attributes:
    id: ID del document
    text: Contingut textual (si disponible)
    score: Puntuació de similitud (0-1, més alt = més similar)
    collection: Nom de la collection
    metadata: Metadades addicionals
  """

  id: str
  score: float
  collection: str
  text: Optional[str] = None
  metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class CollectionInfo:
  """
  Informació d'una collection.

  Attributes:
    name: Nom de la collection
    vector_size: Dimensió dels vectors
    points_count: Nombre de documents
    created_at: Timestamp de creació (si disponible)
  """

  name: str
  vector_size: int
  points_count: int
  created_at: Optional[datetime] = None

__all__ = [
  "MemoryAPIError",
  "CollectionNotFoundError",
  "InvalidCollectionNameError",
  "DocumentNotFoundError",
  "COLLECTION_NAME_PATTERN",
  "validate_collection_name",
  "Document",
  "SearchResult",
  "CollectionInfo",
]