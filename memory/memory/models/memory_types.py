"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/models/memory_types.py
Description: Types and enums for Memory Module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from enum import Enum


class MemoryType(str, Enum):
  """
  Supported memory types.

  Supported types:
  - EPISODIC: Interactions (without Contextual Analysis yet)
  - SEMANTIC: Technical documents (without alignment)
  - PROFILE: Canonical identity facts (closed schema)
  - FACT: Facts extracted from the pipeline
  - NOTEBOOK: Project notebooks
  - SUMMARY: Consolidated summaries
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