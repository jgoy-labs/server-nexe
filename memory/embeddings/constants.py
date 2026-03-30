"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/embeddings/constants.py
Description: Constants for the Embeddings module. Separated from manifest.py to avoid circular imports.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Any

MODULE_ID = "embeddings"

# Embedding vector dimensionality.
# Model: paraphrase-multilingual-mpnet-base-v2 (768 dims).
# If you change the embedding model, change only this value.
DEFAULT_VECTOR_SIZE = 768

MANIFEST: Dict[str, Any] = {
  "module_id": MODULE_ID,
  "name": "embeddings",
  "version": "0.9.0",
  "description": "Multilingual embedding and vectorization system with multi-level caching",
  "author": "J.Goy",
  "category": "memory.core",

  "dependencies": [],

  "capabilities": [
    "text_embedding",
    "batch_embedding",
    "chunking",
    "vector_storage",
    "multi_level_cache"
  ],

  "health_check": "memory.embeddings.health:check",

  "workflow_nodes": [
    "memory.embeddings.workflow.nodes.embedding_node",
    "memory.embeddings.workflow.nodes.chunking_node"
  ],

  "specialists": [
    "memory.embeddings.specialists.embeddings_specialist"
  ],

  "languages": ["ca-ES", "en-US", "es-ES"],

  "default_config": {
    "model": "paraphrase-multilingual-mpnet-base-v2",
    "device": "cpu",
    "max_workers": 2,
    "cache_l1_size": 1000,
    "cache_l2_max_gb": 5.0,
    "cache_l2_ttl_hours": 72,
    "chunk_size": 512,
    "chunk_overlap": 50
  }
}

__all__ = [
  "MANIFEST",
  "MODULE_ID",
  "DEFAULT_VECTOR_SIZE",
]