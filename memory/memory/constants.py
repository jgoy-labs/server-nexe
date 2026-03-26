"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/constants.py
Description: Constants for the Memory module. Separated from manifest.py to avoid circular imports.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Any

# Dimensio dels vectors d'embeddings.
# Correspon al model paraphrase-multilingual-mpnet-base-v2 (768 dims).
# Si canvies el model d'embeddings, canvia nomes aquest valor.
DEFAULT_VECTOR_SIZE = 768

MODULE_ID = "memory"

MANIFEST: Dict[str, Any] = {
  "module_id": MODULE_ID,
  "name": "memory",
  "version": "0.8.2",
  "description": "Memory System - Flash, RAM Context and Persistence with lifecycle management",
  "author": "J.Goy",
  "category": "memory.core",

  "dependencies": [
    "rag",
    "memory",
    "embeddings"
  ],

  "capabilities": [
    "flash_memory",
    "ram_context",
    "persistence_manager",
    "lifecycle_management",
    "garbage_collection",
    "upload_pipeline"
  ],

  "health_check": "memory.memory.health:check",

  "workflow_nodes": [
    "memory.memory.workflow.nodes.upload_node",
    "memory.memory.workflow.nodes.commit_node"
  ],

  "specialists": [
    "memory.memory.specialists.memory_specialist"
  ],

  "languages": ["ca-ES", "en-US", "es-ES"],

  "default_config": {
    "flash_ttl_seconds": 1800,
    "gc_interval_seconds": 300,
    "max_upload_size_mb": 100,
    "transaction_ledger_enabled": True
  }
}

__all__ = [
  "MANIFEST",
  "MODULE_ID",
]