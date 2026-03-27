"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/api/operations.py
Description: Facade for Memory API operations.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .collections import (
  create_collection,
  delete_collection,
  list_collections,
  collection_exists,
)

from .documents import (
  store_document,
  search_documents,
  get_document,
  delete_document,
  count_documents,
  cleanup_expired,
  hex_to_uuid,
)

__all__ = [
  "create_collection",
  "delete_collection",
  "list_collections",
  "collection_exists",
  "store_document",
  "search_documents",
  "get_document",
  "delete_document",
  "count_documents",
  "cleanup_expired",
  "hex_to_uuid",
]