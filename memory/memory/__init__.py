"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/__init__.py
Description: Memory module - Flash Memory, RAM Context and Persistence Manager.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .module import MemoryModule
from .models.memory_entry import MemoryEntry
from .models.memory_types import MemoryType
from .constants import MANIFEST

from .api import (
  MemoryAPI,
  Document,
  SearchResult,
  CollectionInfo,
  MemoryAPIError,
  CollectionNotFoundError,
  InvalidCollectionNameError,
  DocumentNotFoundError,
  validate_collection_name,
)

__all__ = [
  "MemoryModule",
  "MemoryEntry",
  "MemoryType",
  "MANIFEST",
  "MemoryAPI",
  "Document",
  "SearchResult",
  "CollectionInfo",
  "MemoryAPIError",
  "CollectionNotFoundError",
  "InvalidCollectionNameError",
  "DocumentNotFoundError",
  "validate_collection_name",
]