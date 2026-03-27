"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/rag_sources/__init__.py
Description: Base module for RAG sources.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .base import AddDocumentRequest, SearchRequest, SearchHit

__all__ = [
  "AddDocumentRequest",
  "SearchRequest",
  "SearchHit",
]
