"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/models/memory_types.py
Description: Tipus i enums per Memory Module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from enum import Enum


class MemoryType(str, Enum):
  """
  Tipus de memòria suportats.

  Supported types:
  - EPISODIC: Interaccions (sense Anàlisi Contextual encara)
  - SEMANTIC: Documents tècnics (sense alignment)
  - PROFILE: Fets canònics d'identitat (schema tancat)
  - FACT: Fets extrets del pipeline
  - NOTEBOOK: Project notebooks
  - SUMMARY: Resums consolidats
  """

  EPISODIC = "episodic"
  """Direct interactions with the user (conversations, decisions)."""

  SEMANTIC = "semantic"
  """Technical documents, facts, structured knowledge."""

  PROFILE = "profile"
  """Canonical identity facts (closed schema)."""

  FACT = "fact"
  """Extracted facts from pipeline."""

  NOTEBOOK = "notebook"
  """Project notebooks."""

  SUMMARY = "summary"
  """Consolidated summaries."""


class TrustLevel(str, Enum):
  """Trust levels for memory entries. v1: 2 levels only."""

  TRUSTED = "trusted"
  """Explicitly confirmed by user or trusted plugin."""

  UNTRUSTED = "untrusted"
  """Inferred by model or unconfirmed source."""


class MemoryState(str, Enum):
  """Lifecycle states for memory entries."""

  ACTIVE = "active"
  STALE = "stale"
  ARCHIVED = "archived"
  COMPRESSED = "compressed"
  SUPERSEDED = "superseded"


class ValidatorDecision(str, Enum):
  """Decisions from the validator pipeline stage."""

  REJECT = "reject"
  STAGE_ONLY = "stage_only"
  PROMOTE_EPISODIC = "promote_episodic"
  UPSERT_PROFILE = "upsert_profile"


class StagingStatus(str, Enum):
  """Status for staging buffer entries."""

  PENDING = "pending"
  LEASED = "leased"
  PROCESSED = "processed"
  FAILED = "failed"
  PARKED = "parked"


__all__ = [
  "MemoryType",
  "TrustLevel",
  "MemoryState",
  "ValidatorDecision",
  "StagingStatus",
]