"""Anti-regressió Cluster 2 — `VectorIndex` post-init failure defaults.

Cobreix els 4 findings mypy `attr-defined` a `memory/memory/storage/vector_index.py`
(L110, 148, 171, 180). Tots són `"None" has no attribute X` perquè `self._client`
declara None com estat inicial fins a `_init_client()`.

Mecànica del bug latent: si `_init_client()` falla, `self._client` queda None i
`self._available = False`. Cada operació pública (`index`, `search`, `delete`,
`count`) té un guard `if not self._available: return <default>` ABANS de tocar
`self._client`. Mypy no narrows i marca els callsites.

Decisió Director: Dev#2 farà un fix del tipus `assert self._client is not None`
post-guard `_available` o convertirà el guard a `if self._client is None: return
<default>`. **Aquest test pina el contracte runtime sense suposar quina opció
escull Dev#2:** post-init failure → operacions públiques retornen defaults sense
crash, MAI raise.

Pre-fix (HEAD `30eb2a6`): contracte ja es compleix gràcies al guard `_available`.
Post-fix: ha de seguir complint-se. Si Dev#2 trenca el guard (e.g., elimina
`if not self._available: return 0` confiant en assert), aquest test detecta la
regressió.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def broken_vector_index(monkeypatch: pytest.MonkeyPatch, tmp_path: Any):
    """Crea un VectorIndex amb _init_client forçat a fallar.

    L'estat resultant és `_available=False` i `_client=None` — la condició exacta
    que dispara els 4 findings mypy. Forcing-`from_pool` a llançar simula qualsevol
    error d'init (Qdrant lock contention, permisos, disc ple…)."""
    from memory.embeddings.adapters import QdrantAdapter
    from memory.memory.storage.vector_index import VectorIndex

    def _explode(*_args, **_kwargs):
        raise RuntimeError("simulated init failure")

    monkeypatch.setattr(QdrantAdapter, "from_pool", classmethod(lambda cls, **kw: _explode()))

    vi = VectorIndex(qdrant_path=str(tmp_path / "vectors"))
    assert vi._available is False, (
        "Setup invalid: _init_client no ha caigut a la branca except (revisa monkeypatch)."
    )
    assert vi._client is None
    return vi


def test_vector_index_index_returns_zero_when_unavailable(broken_vector_index: Any) -> None:
    """`index()` amb `_available=False` retorna 0 sense crash (cobreix L110)."""
    result = broken_vector_index.index(
        entries=[{"id": "x", "user_id": "u", "namespace": "default"}],
        embeddings=[[0.0, 0.1]],
    )
    assert result == 0


def test_vector_index_search_returns_empty_when_unavailable(broken_vector_index: Any) -> None:
    """`search()` amb `_available=False` retorna llista buida sense crash (cobreix L148)."""
    result = broken_vector_index.search(
        embedding=[0.0, 0.1],
        user_id="u",
    )
    assert result == []


def test_vector_index_delete_returns_zero_when_unavailable(broken_vector_index: Any) -> None:
    """`delete()` amb `_available=False` retorna 0 sense crash (cobreix L171)."""
    result = broken_vector_index.delete(ids=["a", "b"])
    assert result == 0


def test_vector_index_count_returns_zero_when_unavailable(broken_vector_index: Any) -> None:
    """`count()` amb `_available=False` retorna 0 sense crash (cobreix L180)."""
    result = broken_vector_index.count()
    assert result == 0


def test_vector_index_index_empty_entries_returns_zero(tmp_path: Any) -> None:
    """Anti-regressió segon guard: entries buides retornen 0 sense tocar `_client`.

    Aquest path és independent de `_available`; pina la branca short-circuit dels
    23 callsites. Si Dev#2 simplifica el guard `if not self._available or not entries`
    incorrectament, el test detecta la regressió."""
    from memory.memory.storage.vector_index import VectorIndex

    vi = VectorIndex(qdrant_path=str(tmp_path / "vectors_ok"))
    if vi._available:
        result = vi.index(entries=[], embeddings=[])
        assert result == 0
    else:
        pytest.skip("VectorIndex no disponible al sandbox; cobert pel test broken")
