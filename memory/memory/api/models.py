"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/api/models.py
Description: Models and exceptions for Memory API.

www.jgoy.net · https://server-nexe.org
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
  """Base exception for Memory API."""

class CollectionNotFoundError(MemoryAPIError):
  """Collection does not exist."""

class InvalidCollectionNameError(MemoryAPIError):
  """Invalid collection name (does not follow naming convention)."""

class DocumentNotFoundError(MemoryAPIError):
  """Document not found."""

COLLECTION_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*_[a-z][a-z0-9_]*$")

def validate_collection_name(name: str) -> None:
  """
  Validate that the collection name follows the naming convention.

  Format: {module}_{type}
  - Only lowercase, numbers and underscores
  - Must have at least one underscore separating module and type
  - Must start with a letter

  Args:
    name: Collection name

  Raises:
    InvalidCollectionNameError: If the name is not valid

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
  Document returned by the API.

  Attributes:
    id: Unique document identifier
    text: Textual content
    collection: Collection name
    metadata: Additional metadata
    created_at: Creation timestamp
    expires_at: Expiry timestamp (None = permanent)
  """

  id: str
  text: str
  collection: str
  metadata: Dict[str, Any] = field(default_factory=dict)
  created_at: Optional[datetime] = None
  expires_at: Optional[datetime] = None

  @property
  def is_expired(self) -> bool:
    """Check if the document has expired."""
    if self.expires_at is None:
      return False
    now = datetime.now(timezone.utc)
    expires_at = _coerce_aware(self.expires_at)
    return now > expires_at

  @property
  def ttl_remaining(self) -> Optional[int]:
    """Return seconds remaining until expiry, or None if permanent."""
    if self.expires_at is None:
      return None
    now = datetime.now(timezone.utc)
    expires_at = _coerce_aware(self.expires_at)
    remaining = (expires_at - now).total_seconds()
    return max(0, int(remaining))

@dataclass
class SearchResult:
  """
  Result of a semantic search.

  Attributes:
    id: Document ID
    text: Textual content (if available)
    score: Similarity score (0-1, higher = more similar)
    collection: Collection name
    metadata: Additional metadata
  """

  id: str
  score: float
  collection: str
  text: Optional[str] = None
  metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class CollectionInfo:
  """
  Information about a collection.

  Attributes:
    name: Collection name
    vector_size: Vector dimension
    points_count: Number of documents
    created_at: Creation timestamp (if available)
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