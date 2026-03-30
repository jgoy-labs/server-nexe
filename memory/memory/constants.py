"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/constants.py
Description: Constants for the Memory module. Separated from manifest.py to avoid circular imports.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Any

from memory.embeddings.constants import DEFAULT_VECTOR_SIZE  # noqa: F401 — canonical source

MODULE_ID = "memory"

# ── v1 Decisions (frozen) ──
# Trust: 2 levels only (trusted / untrusted). No 4-tier system.
# Episodic dedup: 2 bands (>0.92 refresh, <0.92 new). No link-on-write.
# Graph overlay: OFF. related_ids stored inline as JSON array in episodic.
# Exploratory mode: CLI/user only. No API endpoint.
# Retrieve threshold: floor=0.45, ceiling=0.65. No generic dynamic.
# Embedding model: paraphrase-multilingual-mpnet-base-v2, 768 dims.
# Storage: SQLite = source of truth. Qdrant embedded = rebuildable index.
# user_id: mandatory on ALL tables from day 1. No cross-user contamination.
V1_RETRIEVE_FLOOR = 0.45
V1_RETRIEVE_CEILING = 0.65
V1_DEDUP_REFRESH_THRESHOLD = 0.92
V1_STAGING_TTL_HOURS = 48
V1_TOMBSTONE_TTL_DAYS = 90

MANIFEST: Dict[str, Any] = {
  "module_id": MODULE_ID,
  "name": "memory",
  "version": "0.8.5",
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
  "DEFAULT_VECTOR_SIZE",
  "V1_RETRIEVE_FLOOR",
  "V1_RETRIEVE_CEILING",
  "V1_DEDUP_REFRESH_THRESHOLD",
  "V1_STAGING_TTL_HOURS",
  "V1_TOMBSTONE_TTL_DAYS",
]