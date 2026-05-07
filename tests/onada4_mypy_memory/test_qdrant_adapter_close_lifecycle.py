"""Anti-regression Cluster 1 — `QdrantAdapter` use-after-close lifecycle.

Covers the 23 mypy `union-attr` findings in `memory/embeddings/adapters/qdrant_adapter.py`
(L123, 142, 150, 181, 198, 220, 224, 231, 235, 239, 251, 259, 269, 274, 281, 307, 311,
351, 360, 387, 421, 429, 451). All are `Item "None" of "Any | None" has no attribute X`.

Latent bug mechanics (lifecycle): `__init__` always guarantees `self._client is not None`
on exit, but `close()` (L324) sets `self._client = None`. All 23 callsites assume
a live client without a check; mypy correctly warns.

Director decision (DUBTE 1, option A): Dev#2 introduces a private helper
`_require_client(self) -> Any` that raises `RuntimeError("QdrantAdapter is closed")` if
`self._client is None`, and replaces `self._client.X(...)` with `self._require_client().X(...)`
at the 23 callsites.

PINNED CONTRACT (post-fix): after `close()`, any call to a method that
requires the client must raise `RuntimeError` (not an opaque `AttributeError`).

Pre-fix (HEAD `30eb2a6`): behaviour is `AttributeError: 'NoneType' has no attribute X`.
That is why the test is marked `xfail(strict=True)` — Dev#2 will remove it at surgery
(Cluster 1 commit, position 13/13).
"""

from __future__ import annotations

import pytest


def test_qdrant_adapter_post_close_raises_runtime_error() -> None:
    """Pins post-fix contract: `add_vectors` post-`close()` raises `RuntimeError`."""
    from memory.embeddings.adapters.qdrant_adapter import QdrantAdapter

    class _DummyClient:
        def close(self) -> None:
            pass

        def upsert(self, **_kwargs):  # pragma: no cover - defensive, should not be invoked post-close
            return None

    adapter = QdrantAdapter(collection_name="test_close_lifecycle", client=_DummyClient())
    adapter.close()
    assert adapter._client is None, (
        "Invariant broken: close() must leave _client=None (bug precondition)."
    )

    with pytest.raises(RuntimeError) as exc_info:
        adapter.add_vectors([[0.1, 0.2]], ["text"], [{"source": "test"}])

    assert "closed" in str(exc_info.value).lower(), (
        f"Expected message to contain 'closed', received: {exc_info.value!r}"
    )


def test_qdrant_adapter_close_method_exists() -> None:
    """Anti-regression: the `close()` method exists and remains the only point
    that can set `_client=None` (premise of the bug and the fix)."""
    from memory.embeddings.adapters.qdrant_adapter import QdrantAdapter

    assert hasattr(QdrantAdapter, "close"), (
        "QdrantAdapter.close() has disappeared — breaks the cluster 1 premise."
    )
    assert callable(QdrantAdapter.close)


def test_qdrant_adapter_protocol_methods_present() -> None:
    """Anti-regression: VectorStore Protocol methods remain present.

    If Dev#2 removes/renames any of these, all external callers of the Protocol
    would break — out-of-scope for cluster 1 (which only touches the internal guard)."""
    from memory.embeddings.adapters.qdrant_adapter import QdrantAdapter

    for method in ("add_vectors", "search", "delete", "health"):
        assert hasattr(QdrantAdapter, method), (
            f"QdrantAdapter.{method}() has disappeared — Dev#2 has exceeded the cluster scope."
        )
