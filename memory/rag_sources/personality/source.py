"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/rag_sources/personality/source.py
Description: PersonalityRAG implementation.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import logging
import uuid
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class PersonalityRAG:
    """Font de coneixement basada en la identitat del sistema."""
    
    def __init__(self):
        self.name = "personality_core"
        self._documents: List[Dict[str, Any]] = []
        logger.info("PersonalityRAG source initialized")

    async def add_document(self, request) -> str:
        """Afegeix un document a la font."""
        doc_id = f"personality-{uuid.uuid4().hex}"
        self._documents.append({
            "doc_id": doc_id,
            "text": request.text,
            "metadata": request.metadata,
        })
        return doc_id

    async def search(self, request, limit: int = 5):
        """Simple token-matching search."""
        from memory.rag_sources.base import SearchRequest, SearchHit

        if isinstance(request, SearchRequest):
            query = request.query
            top_k = request.top_k
        else:
            query = request
            top_k = limit

        tokens = [t for t in query.lower().split() if t]
        if not tokens:
            return []

        hits = []
        for doc in self._documents:
            text = doc["text"]
            text_lower = text.lower()
            match_count = sum(1 for t in tokens if t in text_lower)
            if match_count == 0:
                continue
            score = match_count / max(len(tokens), 1)
            hits.append(SearchHit(
                doc_id=doc["doc_id"],
                chunk_id="0",
                score=score,
                text=text,
                metadata=doc.get("metadata", {})
            ))

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def health(self) -> Dict[str, Any]:
        """Basic health check for the source."""
        return {
            "status": "healthy",
            "num_documents": len(self._documents),
            "num_chunks": len(self._documents),
        }
