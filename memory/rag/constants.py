"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/rag/constants.py
Description: Constants for the RAG module. Separated from manifest.py to avoid circular imports.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Any

from core.version import __version__

MODULE_ID = "rag"

MANIFEST: Dict[str, Any] = {
  "module_id": MODULE_ID,
  "name": "rag",
  "version": __version__,
  "description": "RAG module: health/info introspection and a CLI search over the chat's retrieval sources in core/rag/ (ADR-008 E2)",
  "author": "J.Goy",
  "category": "memory.core",

  "dependencies": ["embeddings"],

  # ADR-008 E2: "personality_rag" went with PersonalityRAG. The module owns
  # no source any more; it lists and searches the ones in core/rag/.
  "capabilities": [
    "source_introspection"
  ],

  "health_check": "memory.rag.health:check",

  "specialists": [
    "memory.rag.specialists.rag_specialist"
  ],

  "languages": ["ca-ES", "en-US", "es-ES"],

  "module": {
    "enabled": True,
    "priority": 10,
    "auto_start": True
  },

  "default_config": {
    "top_k": 5,
    "similarity_threshold": 0.7,
    "max_concurrent_searches": 3
  }
}

__all__ = [
  "MANIFEST",
  "MODULE_ID",
]