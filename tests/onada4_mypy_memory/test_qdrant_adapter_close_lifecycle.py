"""Anti-regressió Cluster 1 — `QdrantAdapter` use-after-close lifecycle.

Cobreix els 23 findings mypy `union-attr` a `memory/embeddings/adapters/qdrant_adapter.py`
(L123, 142, 150, 181, 198, 220, 224, 231, 235, 239, 251, 259, 269, 274, 281, 307, 311,
351, 360, 387, 421, 429, 451). Tots són `Item "None" of "Any | None" has no attribute X`.

Mecànica del bug latent (lifecycle): `__init__` sempre garanteix `self._client is not None`
en sortir, però `close()` (L324) seteja `self._client = None`. Tots 23 callsites assumeixen
client viu sense check; mypy correctament avisa.

Decisió Director (DUBTE 1, opció A): Dev#2 introdueix un helper privat
`_require_client(self) -> Any` que llança `RuntimeError("QdrantAdapter is closed")` si
`self._client is None`, i substitueix `self._client.X(...)` per `self._require_client().X(...)`
als 23 callsites.

CONTRACTE PINAT (post-fix): després de `close()`, qualsevol crida a un mètode que
necessiti el client ha de llançar `RuntimeError` (no `AttributeError` opaca).

Pre-fix (HEAD `30eb2a6`): comportament és `AttributeError: 'NoneType' has no attribute X`.
Per això el test es marca `xfail(strict=True)` — Dev#2 el desmarcarà al cirurgia
(commit Cluster 1 de l'ordre 13/13).
"""

from __future__ import annotations

import pytest


def test_qdrant_adapter_post_close_raises_runtime_error() -> None:
    """Pina contracte post-fix: `add_vectors` post-`close()` llança `RuntimeError`."""
    from memory.embeddings.adapters.qdrant_adapter import QdrantAdapter

    class _DummyClient:
        def close(self) -> None:
            pass

        def upsert(self, **_kwargs):  # pragma: no cover - defensive, no s'hauria d'invocar post-close
            return None

    adapter = QdrantAdapter(collection_name="test_close_lifecycle", client=_DummyClient())
    adapter.close()
    assert adapter._client is None, (
        "Invariant trencat: close() ha de deixar _client=None (precondició del bug)."
    )

    with pytest.raises(RuntimeError) as exc_info:
        adapter.add_vectors([[0.1, 0.2]], ["text"], [{"source": "test"}])

    assert "closed" in str(exc_info.value).lower(), (
        f"Missatge esperat conté 'closed', rebut: {exc_info.value!r}"
    )


def test_qdrant_adapter_close_method_exists() -> None:
    """Anti-regressió: el mètode `close()` existeix i continua sent l'únic punt
    que pot setar `_client=None` (premisa del bug i del fix)."""
    from memory.embeddings.adapters.qdrant_adapter import QdrantAdapter

    assert hasattr(QdrantAdapter, "close"), (
        "QdrantAdapter.close() ha desaparegut — trenca la premisa del cluster 1."
    )
    assert callable(QdrantAdapter.close)


def test_qdrant_adapter_protocol_methods_present() -> None:
    """Anti-regressió: mètodes del Protocol VectorStore segueixen presents.

    Si Dev#2 elimina/renomena qualsevol d'aquests, tots els callers extern del Protocol
    es trencarien — out-of-scope del cluster 1 (que només toca el guard intern)."""
    from memory.embeddings.adapters.qdrant_adapter import QdrantAdapter

    for method in ("add_vectors", "search", "delete", "health"):
        assert hasattr(QdrantAdapter, method), (
            f"QdrantAdapter.{method}() ha desaparegut — Dev#2 ha excedit l'scope del cluster."
        )
