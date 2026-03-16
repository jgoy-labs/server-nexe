"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: memory/rag_sources/file/source.py
Description: Implementació de FileRAGSource per a fitxers locals i Qdrant.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import uuid
from typing import List, Dict, Any, Optional

from memory.rag_sources.base import AddDocumentRequest, SearchRequest, SearchHit

logger = logging.getLogger(__name__)

class FileRAGSource:
  """
  Font de coneixement basada en fitxers pujats per l'usuari.
  Implementació inicial amb cerca per paraules clau i emmagatzematge en memòria.

  NOTE: Aquesta versió v0.8.0 és una implementació de referència/mock.
  No integra encara semantic search real via embeddings amb Qdrant,
  però permet mantenir la compatibilitat amb el workflow i l'API.
  """

  def __init__(self, qdrant_url: Optional[str] = None, table_name: str = "documents"):
    """
    Inicialitza la font RAG de fitxers.

    Args:
      qdrant_url: URL del servidor Qdrant (opcional)
      table_name: Nom de la col·lecció/taula
    """
    self.name = f"file_rag_{table_name}"
    self.qdrant_url = qdrant_url
    self.table_name = table_name
    self._documents: List[Dict[str, Any]] = []

    logger.info(f"FileRAGSource initialized (table: {table_name}, url: {qdrant_url})")

  async def add_document(self, request: AddDocumentRequest) -> str:
    """
    Afegeix un document a la font.

    Args:
      request: AddDocumentRequest amb el text i metadata

    Returns:
      doc_id: ID únic del document
    """
    doc_id = request.metadata.get("doc_id") or f"file-{uuid.uuid4().hex}"

    self._documents.append({
      "doc_id": doc_id,
      "text": request.text,
      "metadata": request.metadata,
    })

    logger.debug(f"Document added to FileRAGSource: {doc_id}")
    return doc_id

  async def search(self, request: SearchRequest) -> List[SearchHit]:
    """
    Cerca documents rellevants mitjançant coincidència de paraules clau.

    Implementació simplificada per a v0.8:
    - Tokenització bàsica
    - Coincidència de paraules completes (no parcials) per evitar falsos positius
    - Score normalitzat per la longitud de la query

    Args:
      request: SearchRequest amb la query i paràmetres

    Returns:
      Llista de SearchHit ordenats per score
    """
    import re
    query = request.query
    top_k = request.top_k

    # Tokenització: només paraules alfanumèriques > 2 caràcters
    tokens = [t.lower() for t in re.findall(r'\w+', query) if len(t) > 2]
    if not tokens:
      return []

    hits = []
    for doc in self._documents:
      text = doc["text"].lower()
      # Use word boundaries for better matching
      matches = sum(1 for token in tokens if re.search(rf'\b{re.escape(token)}\b', text))

      if matches > 0:
        score = matches / len(tokens)
        hits.append(SearchHit(
          doc_id=doc["doc_id"],
          chunk_id="0",
          score=score,
          text=doc["text"],
          metadata=doc.get("metadata", {})
        ))

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:top_k]

  def health(self) -> Dict[str, Any]:
    """
    Health check de la font.

    Returns:
      Dict amb l'estat i estadístiques
    """
    return {
      "status": "healthy",
      "source_type": "file",
      "table_name": self.table_name,
      "num_documents": len(self._documents),
      "num_chunks": len(self._documents),
      "qdrant_connected": self.qdrant_url is not None
    }

__all__ = ['FileRAGSource']
