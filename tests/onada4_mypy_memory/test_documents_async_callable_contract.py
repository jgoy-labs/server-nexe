"""Anti-regression Cluster 5 — `api/documents.py` callable contract.

Covers the 8 mypy findings at `memory/memory/api/__init__.py:308, 347, 359, 453` and
`memory/memory/api/documents.py:91, 180, 267`. Mechanics: the signatures of
`store_document`, `store_documents_batch`, `search_documents` declare
`generate_embedding: Callable[[str], List[float]]` (sync) but the body does
`await asyncio.wait_for(generate_embedding(text), ...)` and `await
generate_embeddings_batch(texts)`. Runtime works because callers pass
async methods (`_generate_embedding`, `_generate_embeddings_batch`) that return
Coroutines — `await` waits for them correctly. Mypy correctly warns: the signature
is a lie.

Director decision (Cluster 5): Dev#2 will update the signatures to
`Callable[[str], Awaitable[List[float]]]` (and batch variant). Runtime does NOT change.

PINNED CONTRACT (compatible pre and post-fix):
1. `store_document`, `store_documents_batch`, `search_documents` are `async def`
   (coroutine functions) — the mypy fix must NOT convert them to sync.
2. Called with a legitimate async callable, they complete without crash and return the
   expected type. Pins the `await callable(...)` semantics that the code executes.

Pre-fix (HEAD `30eb2a6`): runtime contract is fulfilled (even though mypy warns).
Post-fix: must continue to be fulfilled. If Dev#2 inadvertently changes the body to
`embedding = generate_embedding(text)` (sync) instead of await, this test detects
the regression empirically.
"""

from __future__ import annotations

import inspect
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

import pytest


def test_store_document_is_coroutine_function() -> None:
    """`store_document` is async — Cluster 5 fix must NOT change it to sync."""
    from memory.memory.api.documents import store_document

    assert inspect.iscoroutinefunction(store_document), (
        "store_document has lost the `async` — breaks all callers."
    )


def test_store_documents_batch_is_coroutine_function() -> None:
    from memory.memory.api.documents import store_documents_batch

    assert inspect.iscoroutinefunction(store_documents_batch)


def test_search_documents_is_coroutine_function() -> None:
    from memory.memory.api.documents import search_documents

    assert inspect.iscoroutinefunction(search_documents)


def test_store_document_signature_keeps_generate_embedding_param() -> None:
    """Pins the named parameter `generate_embedding`. If Dev#2 renames or
    removes the param (e.g., to simplify the mypy fix), callers in
    `api/__init__.py` lines 308/453 break."""
    from memory.memory.api.documents import store_document

    sig = inspect.signature(store_document)
    assert "generate_embedding" in sig.parameters


def test_store_documents_batch_signature_keeps_callable_param() -> None:
    from memory.memory.api.documents import store_documents_batch

    sig = inspect.signature(store_documents_batch)
    assert "generate_embeddings_batch" in sig.parameters


class _FakeQdrant:
    """Minimal mock of the Qdrant client for this contract test."""

    def __init__(self) -> None:
        self.upsert_calls: List[Dict[str, Any]] = []

    def upsert(self, *, collection_name: str, points: Any) -> None:
        self.upsert_calls.append({"collection_name": collection_name, "points": points})


@pytest.mark.asyncio
async def test_store_document_awaits_async_generate_embedding() -> None:
    """Runtime test: `store_document` must be able to receive an `async def` callable
    and obtain the embedding via `await`. If Dev#2 changes the body to sync, this
    test FAILS empirically (awaits are not executed).

    Pins the semantics of line 91 (`await asyncio.wait_for(generate_embedding(text), ...)`).
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
        f"doc_id format broken: {doc_id!r}. SHA256[:16] premise (documents.py:88)."
    )
    assert embedding_calls == ["contracte cluster 5"], (
        "The async embedder was not called exactly once — Cluster 5 fix has "
        "broken the `await generate_embedding(text)` semantics."
    )
    assert len(qdrant.upsert_calls) == 1, "qdrant.upsert was not invoked."


@pytest.mark.asyncio
async def test_store_documents_batch_awaits_async_callable() -> None:
    """Anti-regression L180: `await generate_embeddings_batch(texts)`."""
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
        "fake_async_batch was not awaited correctly — L180 semantics broken."
    )
