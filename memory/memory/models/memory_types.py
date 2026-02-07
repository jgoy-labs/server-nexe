"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/models/memory_types.py
Description: Tipus i enums per Memory Module MVP (FASE 13).

www.jgoy.net
────────────────────────────────────
"""

from enum import Enum

class MemoryType(str, Enum):
  """
  Tipus de memòria suportats.

  FASE 13 MVP:
  - EPISODIC: Interaccions (sense Anàlisi Contextual encara)
  - SEMANTIC: Documents tècnics (sense alignment)

  FASE 19:
  - SEMANTIC_INTIMATE: Diaris amb Anàlisi Contextual opcional
  """

  EPISODIC = "episodic"
  """Direct interactions with the user (conversations, decisions)"""

  SEMANTIC = "semantic"
  """Technical documents, facts, structured knowledge"""

__all__ = ["MemoryType"]
