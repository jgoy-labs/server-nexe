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

MODULE_ID = "rag"

MANIFEST: Dict[str, Any] = {
  "module_id": MODULE_ID,
  "name": "rag",
  "version": "0.9.1",
  "description": "RAG module: health/info introspection + PersonalityRAG source for the chat pipeline (the standalone /rag surface was retired, WS6-01/02)",
  "author": "J.Goy",
  "category": "memory.core",

  "dependencies": ["embeddings"],

  "capabilities": [
    "personality_rag"
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
    "circuit_breaker_threshold": 5,
    "circuit_breaker_timeout": 60,
    "max_concurrent_searches": 3
  }
}

__all__ = [
  "MANIFEST",
  "MODULE_ID",
]