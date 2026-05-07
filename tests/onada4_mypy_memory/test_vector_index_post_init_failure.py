"""Anti-regression Cluster 2 — `VectorIndex` post-init failure defaults.

Covers the 4 mypy `attr-defined` findings at `memory/memory/storage/vector_index.py`
(L110, 148, 171, 180). All are `"None" has no attribute X` because `self._client`
declares None as its initial state until `_init_client()`.

Latent bug mechanics: if `_init_client()` fails, `self._client` remains None and
`self._available = False`. Each public operation (`index`, `search`, `delete`,
`count`) has a guard `if not self._available: return <default>` BEFORE touching
`self._client`. Mypy does not narrow and flags the callsites.

Director decision: Dev#2 will do a fix of the type `assert self._client is not None`
post-`_available` guard or will convert the guard to `if self._client is None: return
<default>`. **This test pins the runtime contract without assuming which option
Dev#2 chooses:** post-init failure → public operations return defaults without
crash, NEVER raise.

Pre-fix (HEAD `30eb2a6`): contract is already fulfilled thanks to the `_available` guard.
Post-fix: must continue to be fulfilled. If Dev#2 breaks the guard (e.g., removes
`if not self._available: return 0` relying on assert), this test detects the
regression.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def broken_vector_index(monkeypatch: pytest.MonkeyPatch, tmp_path: Any):
    """Creates a VectorIndex with _init_client forced to fail.

    The resulting state is `_available=False` and `_client=None` — the exact condition
    that triggers the 4 mypy findings. Forcing `from_pool` to raise simulates any
    init error (Qdrant lock contention, permissions, disk full…)."""
    from memory.embeddings.adapters import QdrantAdapter
    from memory.memory.storage.vector_index import VectorIndex

    def _explode(*_args, **_kwargs):
        raise RuntimeError("simulated init failure")

    monkeypatch.setattr(QdrantAdapter, "from_pool", classmethod(lambda cls, **kw: _explode()))

    vi = VectorIndex(qdrant_path=str(tmp_path / "vectors"))
    assert vi._available is False, (
        "Invalid setup: _init_client did not fall into the except branch (check monkeypatch)."
    )
    assert vi._client is None
    return vi


def test_vector_index_index_returns_zero_when_unavailable(broken_vector_index: Any) -> None:
    """`index()` with `_available=False` returns 0 without crash (covers L110)."""
    result = broken_vector_index.index(
        entries=[{"id": "x", "user_id": "u", "namespace": "default"}],
        embeddings=[[0.0, 0.1]],
    )
    assert result == 0


def test_vector_index_search_returns_empty_when_unavailable(broken_vector_index: Any) -> None:
    """`search()` with `_available=False` returns empty list without crash (covers L148)."""
    result = broken_vector_index.search(
        embedding=[0.0, 0.1],
        user_id="u",
    )
    assert result == []


def test_vector_index_delete_returns_zero_when_unavailable(broken_vector_index: Any) -> None:
    """`delete()` with `_available=False` returns 0 without crash (covers L171)."""
    result = broken_vector_index.delete(ids=["a", "b"])
    assert result == 0


def test_vector_index_count_returns_zero_when_unavailable(broken_vector_index: Any) -> None:
    """`count()` with `_available=False` returns 0 without crash (covers L180)."""
    result = broken_vector_index.count()
    assert result == 0


def test_vector_index_index_empty_entries_returns_zero(tmp_path: Any) -> None:
    """Anti-regression second guard: empty entries return 0 without touching `_client`.

    This path is independent of `_available`; pins the short-circuit branch of the
    23 callsites. If Dev#2 simplifies the guard `if not self._available or not entries`
    incorrectly, the test detects the regression."""
    from memory.memory.storage.vector_index import VectorIndex

    vi = VectorIndex(qdrant_path=str(tmp_path / "vectors_ok"))
    if vi._available:
        result = vi.index(entries=[], embeddings=[])
        assert result == 0
    else:
        pytest.skip("VectorIndex no disponible al sandbox; cobert pel test broken")
