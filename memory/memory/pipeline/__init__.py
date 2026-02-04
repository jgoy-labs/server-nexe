"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/pipeline/__init__.py
Description: Pipeline d'ingesta per Memory Module (FASE 13 MVP).

www.jgoy.net
────────────────────────────────────
"""

from .deduplicator import Deduplicator
from .ingestion import IngestionPipeline

__all__ = [
  "Deduplicator",
  "IngestionPipeline",
]