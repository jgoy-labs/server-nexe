"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_embeddings_recall_ab.py
Description: Recall@N regression for embedding model.
             VectorStore-agnostic: InMemoryVectorStore (numpy cosine),
             zero qdrant_client dependency. Skip if fastembed not available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pytest

from memory.embeddings.core.vectorstore import VectorSearchHit, VectorSearchRequest


# ── skip guard ────────────────────────────────────────────────────────────────

_FASTEMBED_CACHE = os.environ.get(
    "FASTEMBED_CACHE_PATH", os.path.expanduser("~/.cache/fastembed")
)


def _fastembed_available() -> bool:
    cache = Path(_FASTEMBED_CACHE)
    if not cache.exists():
        return False
    for pattern in (
        "models--xenova--paraphrase-multilingual*",
        "paraphrase-multilingual*",
        "sentence-transformers--paraphrase-multilingual*",
    ):
        if list(cache.glob(pattern)):
            return True
    return False


pytestmark = pytest.mark.skipif(
    not _fastembed_available(),
    reason="fastembed model not in cache — run the installer or set FASTEMBED_CACHE_PATH",
)


# ── InMemoryVectorStore (protocol-compliant, zero Qdrant) ─────────────────────

class InMemoryVectorStore:
    """In-memory VectorStore for tests. Cosine similarity via numpy.

    Implements the VectorStore protocol with no external dependencies
    (qdrant_client, faiss, etc.). Suitable for unit and regression tests.
    """

    def __init__(self) -> None:
        self._vectors: List[np.ndarray] = []
        self._texts: List[str] = []
        self._metadatas: List[Dict[str, Any]] = []
        self._ids: List[str] = []

    def add_vectors(
        self,
        vectors: List[List[float]],
        texts: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> List[str]:
        ids = []
        for i, (vec, text, meta) in enumerate(zip(vectors, texts, metadatas)):
            uid = meta.get("id", f"doc-{len(self._ids) + i}")
            self._vectors.append(np.array(vec, dtype=np.float32))
            self._texts.append(text)
            self._metadatas.append(meta)
            self._ids.append(uid)
            ids.append(uid)
        return ids

    def search(self, request: VectorSearchRequest) -> List[VectorSearchHit]:
        if not self._vectors:
            return []
        q = np.array(request.query_vector, dtype=np.float32)
        q_norm = q / (np.linalg.norm(q) + 1e-9)
        matrix = np.stack(self._vectors)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9
        scores = (matrix / norms) @ q_norm
        top_k = min(request.top_k, len(scores))
        top_idx = np.argsort(scores)[::-1][:top_k]
        return [
            VectorSearchHit(
                id=self._ids[i],
                score=float(np.clip(scores[i], 0.0, 1.0)),
                text=self._texts[i],
                metadata=self._metadatas[i],
            )
            for i in top_idx
        ]

    def delete(self, ids: List[str]) -> int:
        before = len(self._ids)
        keep = [i for i, uid in enumerate(self._ids) if uid not in ids]
        self._ids = [self._ids[i] for i in keep]
        self._vectors = [self._vectors[i] for i in keep]
        self._texts = [self._texts[i] for i in keep]
        self._metadatas = [self._metadatas[i] for i in keep]
        return before - len(self._ids)

    def health(self) -> Dict[str, Any]:
        return {"status": "healthy", "num_vectors": len(self._ids)}


# ── Golden dataset (català / temàtica Nexe-IA) ────────────────────────────────

_GOLDEN_DOCS = [
    {"id": "d01", "text": "El servidor Nexe és un assistent local d'IA que funciona sense connexió a internet."},
    {"id": "d02", "text": "La memòria RAG permet que l'assistent recordi converses i fets importants de sessions anteriors."},
    {"id": "d03", "text": "MLX és un framework d'Apple per accelerar models d'IA en Apple Silicon M1, M2, M3 i M4."},
    {"id": "d04", "text": "Ollama permet executar models de llenguatge grans localment a l'ordinador sense GPU dedicada."},
    {"id": "d05", "text": "La privacitat és fonamental: amb Nexe les dades de l'usuari mai surten del dispositiu local."},
    {"id": "d06", "text": "Els models Qwen3 i Gemma3 suporten català de manera excel·lent i amb alta qualitat lingüística."},
    {"id": "d07", "text": "L'encriptació AES-GCM protegeix les sessions i les memories persistents de l'usuari al disc."},
    {"id": "d08", "text": "El sistema de plugins de Nexe permet afegir noves funcionalitats sense modificar el nucli."},
    {"id": "d09", "text": "FastEmbed utilitza models ONNX quantitzats per generar embeddings de text de forma eficient."},
    {"id": "d10", "text": "La instal·lació de Nexe requereix macOS 14 Sonoma o superior en màquines Apple Silicon."},
]

_GOLDEN_QUERIES: List[Dict[str, Any]] = [
    {"query": "assistent que funciona sense internet",          "relevant": {"d01"}},
    {"query": "recordar fets de converses anteriors",           "relevant": {"d02"}},
    {"query": "acceleració de models en Apple M1 M2",           "relevant": {"d03"}},
    {"query": "executar LLM localment sense connexió al núvol", "relevant": {"d04"}},
    {"query": "dades privades que no surten del dispositiu",    "relevant": {"d05"}},
    {"query": "models de llengua que parlen català",            "relevant": {"d06"}},
    {"query": "xifrat de sessions i memòries al disc",          "relevant": {"d07"}},
    {"query": "afegir noves funcionalitats al servidor",        "relevant": {"d08"}},
    {"query": "generar embeddings eficients amb ONNX",          "relevant": {"d09"}},
    {"query": "requisits sistema operatiu per instal·lar",      "relevant": {"d10"}},
]

# Conservative thresholds for a 10-doc dataset
_RECALL_AT_5_MIN = 0.5   # ≥5/10 queries must return the relevant doc in top-5
_RECALL_AT_10_MIN = 0.7  # ≥7/10 in top-10


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def embedder():
    from memory.embeddings.constants import DEFAULT_EMBEDDING_MODEL
    from memory.embeddings.simple_embedder import SimpleEmbedder
    return SimpleEmbedder(DEFAULT_EMBEDDING_MODEL)


@pytest.fixture(scope="module")
def populated_store(embedder):
    store = InMemoryVectorStore()
    texts = [d["text"] for d in _GOLDEN_DOCS]
    metadatas = [{"id": d["id"]} for d in _GOLDEN_DOCS]
    vectors = embedder.encode_batch(texts)
    store.add_vectors(vectors, texts, metadatas)
    return store


# ── helpers ───────────────────────────────────────────────────────────────────

def _recall_at_n(store: InMemoryVectorStore, embedder: Any, n: int) -> float:
    hits = 0
    for item in _GOLDEN_QUERIES:
        q_vec = embedder.encode(item["query"])
        results = store.search(VectorSearchRequest(query_vector=q_vec, top_k=n))
        returned_ids = {r.id for r in results}
        hits += len(returned_ids & item["relevant"])
    return hits / len(_GOLDEN_QUERIES)


# ── tests ─────────────────────────────────────────────────────────────────────

class TestRecallABRegression:
    """Recall@N regression — embedding model VectorStore-agnostic."""

    def test_in_memory_store_search_returns_ordered_results(self, populated_store, embedder):
        """InMemoryVectorStore returns results in descending score order."""
        q_vec = embedder.encode("assistent local sense internet")
        results = populated_store.search(
            VectorSearchRequest(query_vector=q_vec, top_k=3)
        )
        assert len(results) == 3
        assert all(0.0 <= r.score <= 1.0 for r in results)
        assert results[0].score >= results[-1].score

    def test_recall_at_5_above_threshold(self, populated_store, embedder):
        """Recall@5 ≥ 0.50. Detects degradation if the model changes.

        Conservative threshold: 5/10 queries must return the relevant doc
        in top-5. A well-initialised multilingual mpnet model exceeds 0.70.
        """
        recall = _recall_at_n(populated_store, embedder, n=5)
        assert recall >= _RECALL_AT_5_MIN, (
            f"Recall@5 = {recall:.2f} < {_RECALL_AT_5_MIN}. "
            "Possible embedding model degradation."
        )

    def test_recall_at_10_above_threshold(self, populated_store, embedder):
        """Recall@10 ≥ 0.70. With 10 docs the relevant one should always be present."""
        recall = _recall_at_n(populated_store, embedder, n=10)
        assert recall >= _RECALL_AT_10_MIN, (
            f"Recall@10 = {recall:.2f} < {_RECALL_AT_10_MIN}. "
            "Possible embedding model degradation."
        )

    def test_top1_hit_rate_nonzero(self, populated_store, embedder):
        """At least 3/10 queries must have the relevant doc in position 1."""
        top1_hits = sum(
            1
            for item in _GOLDEN_QUERIES
            if (
                res := populated_store.search(
                    VectorSearchRequest(
                        query_vector=embedder.encode(item["query"]), top_k=1
                    )
                )
            )
            and res[0].id in item["relevant"]
        )
        assert top1_hits >= 3, (
            f"Top-1 hits = {top1_hits}/10 < 3. "
            "The model does not return the relevant doc in first position for almost any query."
        )

    def test_store_delete_reduces_vectors(self, embedder):
        """delete() removes vectors correctly and does not affect future results."""
        store = InMemoryVectorStore()
        texts = [d["text"] for d in _GOLDEN_DOCS[:3]]
        metas = [{"id": d["id"]} for d in _GOLDEN_DOCS[:3]]
        store.add_vectors(embedder.encode_batch(texts), texts, metas)
        assert store.health()["num_vectors"] == 3
        assert store.delete(["d01"]) == 1
        assert store.health()["num_vectors"] == 2
        results = store.search(
            VectorSearchRequest(query_vector=embedder.encode("assistent local"), top_k=5)
        )
        assert all(r.id != "d01" for r in results)
