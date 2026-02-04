"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/models/memory_entry.py
Description: Model principal MemoryEntry (FASE 13 MVP).

www.jgoy.net
────────────────────────────────────
"""

import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .memory_types import MemoryType

class MemoryEntry(BaseModel):
  """Memory entry with basic metadata support."""

  id: Optional[str] = Field(
    default=None,
    description="ID únic determinista (SHA256(content)[:16]) - auto-generat"
  )

  entry_type: MemoryType = Field(
    ...,
    description="Tipus de memòria: episodic o semantic"
  )

  content: str = Field(
    ...,
    min_length=1,
    max_length=100_000,
    description="Contingut de la memòria (max 100KB)"
  )

  source: str = Field(
    default="unknown",
    description="Font de la memòria (e.g., 'chat', 'pdf', 'api')"
  )

  timestamp: datetime = Field(
    default_factory=lambda: datetime.now(timezone.utc),
    description="Timestamp UTC de creació"
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
    """Validar que el contingut no sigui només espais"""
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

__all__ = ["MemoryEntry"]