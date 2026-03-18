"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: memory/rag_sources/base.py
Description: Base models for RAG sources (requests and hits).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Any
from pydantic import BaseModel, Field


class AddDocumentRequest(BaseModel):
  """Request to add a document to a RAG source."""
  text: str
  metadata: Dict[str, Any] = Field(default_factory=dict)
  chunk_size: int = 800
  chunk_overlap: int = 100


class SearchRequest(BaseModel):
  """Request to search documents in a RAG source."""
  query: str
  top_k: int = 5
  filters: Dict[str, Any] = Field(default_factory=dict)


class SearchHit(BaseModel):
  """Single RAG search result."""
  doc_id: str
  chunk_id: str
  score: float
  text: str
  metadata: Dict[str, Any] = Field(default_factory=dict)


__all__ = [
  "AddDocumentRequest",
  "SearchRequest",
  "SearchHit",
]
