"""
Vector store adapters for the VectorStore Protocol.

Imports QdrantAdapter to create vector store instances
that implement the VectorStore Protocol defined in core/vectorstore.py.

Examples:
    >>> from memory.embeddings.adapters import QdrantAdapter
    >>> store = QdrantAdapter(collection_name="nexe_docs", path="storage/vectors")
    >>> ids = store.add_vectors([[0.1, 0.2], [0.3, 0.4]], ["text1", "text2"], [{}, {}])
"""

from .qdrant_adapter import QdrantAdapter

__all__ = ["QdrantAdapter"]
