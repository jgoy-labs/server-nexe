"""Anti-regressió Cluster 5 — `api/documents.py` callable contract.

Cobreix els 8 findings mypy a `memory/memory/api/__init__.py:308, 347, 359, 453` i
`memory/memory/api/documents.py:91, 180, 267`. Mecànica: les firmes de
`store_document`, `store_documents_batch`, `search_documents` declaren
`generate_embedding: Callable[[str], List[float]]` (sync) però el cos fa
`await asyncio.wait_for(generate_embedding(text), ...)` i `await
generate_embeddings_batch(texts)`. Runtime funciona perquè els callers passen
mètodes async (`_generate_embedding`, `_generate_embeddings_batch`) que retornen
Coroutines — `await` les espera correctament. Mypy correctament avisa: la firma
és mentida.

Decisió Director (Cluster 5): Dev#2 actualitzarà les firmes a
`Callable[[str], Awaitable[List[float]]]` (i variant batch). El runtime NO canvia.

CONTRACTE PINAT (compatible pre i post-fix):
1. `store_document`, `store_documents_batch`, `search_documents` són `async def`
   (coroutine functions) — fix mypy NO ha de convertir-les en sync.
2. Cridades amb un callable async legítim, completen sense crash i retornen el
   tipus esperat. Pina la semàntica `await callable(...)` que el codi executa.

Pre-fix (HEAD `30eb2a6`): contracte compleix runtime (encara que mypy avisa).
Post-fix: ha de seguir complint-se. Si Dev#2 inadvertidament canvia el cos a
`embedding = generate_embedding(text)` (sync) en lloc d'await, aquest test detecta
la regressió empíricament.
"""

from __future__ import annotations

import inspect
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

import pytest


def test_store_document_is_coroutine_function() -> None:
    """`store_document` és async — fix Cluster 5 NO ha de canviar a sync."""
    from memory.memory.api.documents import store_document

    assert inspect.iscoroutinefunction(store_document), (
        "store_document ha perdut el `async` — trenca tots els callers."
    )


def test_store_documents_batch_is_coroutine_function() -> None:
    from memory.memory.api.documents import store_documents_batch

    assert inspect.iscoroutinefunction(store_documents_batch)


def test_search_documents_is_coroutine_function() -> None:
    from memory.memory.api.documents import search_documents

    assert inspect.iscoroutinefunction(search_documents)


def test_store_document_signature_keeps_generate_embedding_param() -> None:
    """Pina paràmetre nominat `generate_embedding`. Si Dev#2 renomena o
    elimina el param (e.g., per simplificar la fix mypy), els callers de
    `api/__init__.py` línies 308/453 es trenquen."""
    from memory.memory.api.documents import store_document

    sig = inspect.signature(store_document)
    assert "generate_embedding" in sig.parameters


def test_store_documents_batch_signature_keeps_callable_param() -> None:
    from memory.memory.api.documents import store_documents_batch

    sig = inspect.signature(store_documents_batch)
    assert "generate_embeddings_batch" in sig.parameters


class _FakeQdrant:
    """Mock minimal del client Qdrant per aquesta prova de contracte."""

    def __init__(self) -> None:
        self.upsert_calls: List[Dict[str, Any]] = []

    def upsert(self, *, collection_name: str, points: Any) -> None:
        self.upsert_calls.append({"collection_name": collection_name, "points": points})


@pytest.mark.asyncio
async def test_store_document_awaits_async_generate_embedding() -> None:
    """Test runtime: `store_document` ha de poder rebre un `async def` callable
    i obtenir l'embedding via `await`. Si Dev#2 canvia el cos a sync, aquest
    test FALLA empíricament (no executa awaits).

    Pina la semàntica de la línia 91 (`await asyncio.wait_for(generate_embedding(text), ...)`).
    """
    from memory.memory.api.documents import store_document

    embedding_calls: List[str] = []

    async def fake_async_embedder(text: str) -> List[float]:
        embedding_calls.append(text)
        return [0.1, 0.2, 0.3, 0.4]

    qdrant = _FakeQdrant()
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        doc_id = await store_document(
            qdrant=qdrant,
            executor=executor,
            generate_embedding=fake_async_embedder,
            text="contracte cluster 5",
            collection="test_async_callable",
            metadata={"src": "anti-regressio"},
        )
    finally:
        executor.shutdown(wait=True)

    assert isinstance(doc_id, str) and len(doc_id) == 16, (
        f"doc_id format trencat: {doc_id!r}. Premisa SHA256[:16] (documents.py:88)."
    )
    assert embedding_calls == ["contracte cluster 5"], (
        "L'embedder async no s'ha cridat exactament una vegada — fix Cluster 5 ha "
        "trencat la semàntica `await generate_embedding(text)`."
    )
    assert len(qdrant.upsert_calls) == 1, "qdrant.upsert no ha estat invocat."


@pytest.mark.asyncio
async def test_store_documents_batch_awaits_async_callable() -> None:
    """Anti-regressió L180: `await generate_embeddings_batch(texts)`."""
    from memory.memory.api.documents import store_documents_batch

    batch_calls: List[List[str]] = []

    async def fake_async_batch(texts: List[str]) -> List[List[float]]:
        batch_calls.append(texts)
        return [[0.1, 0.2] for _ in texts]

    qdrant = _FakeQdrant()
    executor = ThreadPoolExecutor(max_workers=1)
    items = [{"text": "a"}, {"text": "b"}]
    try:
        doc_ids = await store_documents_batch(
            qdrant=qdrant,
            executor=executor,
            generate_embeddings_batch=fake_async_batch,
            items=items,
            collection="test_batch_async",
        )
    finally:
        executor.shutdown(wait=True)

    assert len(doc_ids) == 2
    assert batch_calls == [["a", "b"]], (
        "fake_async_batch no s'ha awaited correctament — semantica L180 trencada."
    )
