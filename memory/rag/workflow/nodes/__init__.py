"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/rag/workflow/nodes/__init__.py
Description: Exporta nodes de workflow del mòdul RAG.

www.jgoy.net
────────────────────────────────────
"""

try:
  from .rag_search_node import RAG_AVAILABLE, RAGSearchNode

  if RAG_AVAILABLE:
    __all__ = ["RAGSearchNode"]
  else:
    __all__ = []
except ImportError:
  __all__ = []