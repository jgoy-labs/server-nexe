"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/models/memory_entry.py
Description: Model principal MemoryEntry.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .memory_types import MemoryType, TrustLevel, ValidatorDecision

class MemoryEntry(BaseModel):
  """Memory entry with basic metadata support."""

  id: Optional[str] = Field(
    default=None,
    description="Deterministic unique ID (SHA256(content)[:16]) - auto-generated"
  )

  entry_type: MemoryType = Field(
    ...,
    description="Memory type: episodic or semantic"
  )

  content: str = Field(
    ...,
    min_length=1,
    max_length=100_000,
    description="Memory content (max 100KB)"
  )

  source: str = Field(
    default="unknown",
    description="Memory source (e.g., 'chat', 'pdf', 'api')"
  )

  timestamp: datetime = Field(
    default_factory=lambda: datetime.now(timezone.utc),
    description="UTC creation timestamp"
  )

  ttl_seconds: Optional[int] = Field(
    default=1800,
    ge=60,
    le=86400 * 30,
    description="Time-to-live en segons (default: 30 min)"
  )


  metadata: Dict[str, Any] = Field(
    default_factory=dict,
    description="Metadata lliure (tags, context, etc.)"
  )

  @field_validator('content')
  @classmethod
  def validate_content_not_empty(cls, v: str) -> str:
    """Validate that the content is not only whitespace."""
    if not v.strip():
      raise ValueError("Content cannot be empty or whitespace only")
    return v

  @model_validator(mode='after')
  def generate_deterministic_id(self):
    """
    Generar ID determinista si no existeix.

    Estratègia: SHA256(content)[:16]
    - Permet deduplicació per contingut
    - 16 chars = 64 bits = col·lisió improbable
    """
    if not self.id:
      content_hash = hashlib.sha256(self.content.encode('utf-8')).hexdigest()
      self.id = content_hash[:16]
    return self

  @property
  def should_encrypt(self) -> bool:
    """Check if entry should be encrypted (current MVP: False)."""
    return False

  def to_context_string(
    self,
    max_length: int = 300,
    safe_mode: bool = True
  ) -> str:
    """
    Converteix a string per LLM context amb safeguard info-leak.

    Args:
      max_length: Màxim chars
      safe_mode: IMPORTANT - trunca per defecte per evitar:
           - Credencials en PDFs
           - Dades personals
           - Claus PGP

    Returns:
      str: Context formatat
    """
    timestamp_str = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")

    content = self.content[:max_length] if safe_mode else self.content
    if len(self.content) > max_length and safe_mode:
      content += "..."

    if self.entry_type == MemoryType.EPISODIC:
      return f"[{timestamp_str}] {content}"
    else:
      return f"[{timestamp_str}] [DOC] {content}"

  model_config = ConfigDict(
    json_schema_extra={
      "example": {
        "entry_type": "episodic",
        "content": "Conversa sobre plans de futur",
        "source": "chat"
      }
    }
  )


class ExtractedFact(BaseModel):
  """Output from the extractor pipeline stage."""

  content: str = Field(..., description="Extracted fact text")
  entity: str = Field(default="user", description="Entity this fact refers to")
  attribute: Optional[str] = Field(default=None, description="Schema attribute if matched")
  value: Optional[str] = Field(default=None, description="Extracted value")
  tags: List[str] = Field(default_factory=list)
  importance: float = Field(default=0.6, ge=0.0, le=1.0)
  source: str = Field(default="heuristic")
  is_correction: bool = Field(default=False)


class ValidatorResult(BaseModel):
  """Output from the validator pipeline stage."""

  decision: ValidatorDecision
  scores: Dict[str, float] = Field(default_factory=dict)
  reason: str = Field(default="")
  trust_level: TrustLevel = Field(default=TrustLevel.UNTRUSTED)


class MemoryCard(BaseModel):
  """Formatted memory for LLM context injection."""

  content: str
  confidence: str = Field(default="moderate", description="high, moderate, low")
  source_store: str = Field(default="episodic")
  score: float = Field(default=0.0)
  entry_id: Optional[str] = Field(default=None)
  metadata: Dict[str, Any] = Field(default_factory=dict)


class MemoryStats(BaseModel):
  """Statistics for the memory system."""

  profile_count: int = 0
  episodic_count: int = 0
  staging_count: int = 0
  tombstone_count: int = 0
  working_memory_count: int = 0


__all__ = [
  "MemoryEntry",
  "ExtractedFact",
  "ValidatorResult",
  "MemoryCard",
  "MemoryStats",
]