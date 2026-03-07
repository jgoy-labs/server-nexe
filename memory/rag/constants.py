"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/rag/constants.py
Description: Constants for the RAG module. Separated from manifest.py to avoid circular imports.

www.jgoy.net
────────────────────────────────────
"""

from typing import Dict, Any

MODULE_ID = "rag"

MANIFEST: Dict[str, Any] = {
  "module_id": MODULE_ID,
  "name": "rag",
  "version": "0.8.0",
  "description": "RAG System (Retrieval-Augmented Generation) with multi-source and circuit breaker",
  "author": "J.Goy",
  "category": "memory.core",

  "dependencies": ["embeddings"],

  "capabilities": [
    "vector_search",
    "multi_rag_management",
    "personality_rag",
    "temp_upload_rag",
    "catalog_rag",
    "circuit_breaker"
  ],

  "health_check": "memory.rag.health:check",

  "workflow_nodes": [
    "memory.rag.workflow.nodes.search_node",
    "memory.rag.workflow.nodes.create_rag_node"
  ],

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