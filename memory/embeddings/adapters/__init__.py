"""
Adapters de vector stores per al Protocol VectorStore.

Importa QdrantAdapter per crear instàncies de vector store
que implementen el Protocol VectorStore definit a core/vectorstore.py.

Exemples:
    >>> from memory.embeddings.adapters import QdrantAdapter
    >>> store = QdrantAdapter(collection_name="nexe_docs", path="storage/vectors")
    >>> ids = store.add_vectors([[0.1, 0.2], [0.3, 0.4]], ["text1", "text2"], [{}, {}])
"""

from .qdrant_adapter import QdrantAdapter

__all__ = ["QdrantAdapter"]
