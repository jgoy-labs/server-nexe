"""G7 (#895) — the pool owns the client; nobody else gets to close it.

core/qdrant_pool.py hands out ONE QdrantClient per path/url, shared by every
consumer. Two of them closed it anyway: QdrantAdapter.close() and, through it,
VectorIndex.close() (fired from MemoryService.shutdown()). After that call the
other consumers got `RuntimeError: QdrantLocal instance is closed` and the pool
kept handing out the dead client, with no recovery — a subsystem shutting itself
down took memory and RAG with it for everyone.

The project had already written the policy down in memory/memory/api/__init__.py
("Do NOT close the Qdrant client here ... lifecycle via close_qdrant_client() at
shutdown"). What was missing was the code obeying it instead of contradicting it.

Note that EVERY adapter's client comes from the pool: `from_pool()` asks for it
explicitly, and the plain constructor falls through to `_create_client()`, which
asks for it too. So "do not close if it came from the pool" was never a case to
distinguish — it is all of them.
"""
from __future__ import annotations

import pytest

from core.qdrant_pool import close_qdrant_client, get_qdrant_client
from memory.embeddings.adapters import QdrantAdapter


@pytest.fixture()
def pool_path(tmp_path):
    """A clean pool around each test: this is process-global state."""
    import core.qdrant_pool as pool

    pool._instances.clear()
    try:
        yield str(tmp_path / "g7-vectors")
    finally:
        close_qdrant_client()


def test_closing_one_adapter_leaves_the_others_working(pool_path):
    """The whole point: one consumer leaving must not blind the rest."""
    first = QdrantAdapter.from_pool(collection_name="alpha", path=pool_path)
    second = QdrantAdapter.from_pool(collection_name="beta", path=pool_path)
    assert first._client is second._client, "precondition: the pool shares one client"

    first.close()

    # The surviving consumer must still be able to talk to the store.
    second.get_collections()


def test_the_pool_keeps_serving_a_live_client_after_a_close(pool_path):
    """A dead client cached in the pool is worse than no client: every later
    caller receives it and fails, with no recovery path."""
    adapter = QdrantAdapter.from_pool(collection_name="alpha", path=pool_path)
    adapter.close()

    client = get_qdrant_client(path=pool_path)
    client.get_collections()  # raises RuntimeError("...is closed") if it was killed


def test_close_still_releases_the_adapter(pool_path):
    """close() keeps meaning "this adapter is done": it drops its reference and
    later use is a clean RuntimeError, not an AttributeError."""
    adapter = QdrantAdapter.from_pool(collection_name="alpha", path=pool_path)
    adapter.close()

    assert adapter._client is None
    with pytest.raises(RuntimeError, match="closed"):
        adapter.get_collections()


def test_the_pool_can_still_close_everything(pool_path):
    """Calibration: the client is not immortal — the owner can end it.

    Without this, a close() that never closes anything would look identical to
    a correct one, and the shutdown path would silently leak the store.
    """
    client = get_qdrant_client(path=pool_path)
    close_qdrant_client()

    with pytest.raises(RuntimeError, match="closed"):
        client.get_collections()
