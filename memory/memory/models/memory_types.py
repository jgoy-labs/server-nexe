"""
────────────────────────────────────
Server Nexe
Version: 0.8
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

  Planned:
  - SEMANTIC_INTIMATE: Diaris amb Anàlisi Contextual opcional
  """

  EPISODIC = "episodic"
  """Interaccions directes amb l'usuari (converses, decisions)"""

  SEMANTIC = "semantic"
  """Documents tècnics, facts, coneixement estructurat"""

__all__ = ["MemoryType"]