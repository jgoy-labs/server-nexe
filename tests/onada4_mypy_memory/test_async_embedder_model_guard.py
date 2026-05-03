"""Anti-regressió Cluster 8 — `AsyncEmbedder._model` lazy-load guard.

Cobreix els 2 findings mypy `union-attr` a
`memory/embeddings/core/async_encoder.py:207` (`_encode_sync` cridant
`self._model.embed([text])`) i L283 (`_encode_batch_sync` cridant
`self._model.embed(texts, ...)`). Causa: `_model: Optional[object] = None`
(L94) i només es carrega via `await self._ensure_loaded()` (L105-122).
Mypy no infereix l'invariant cross-await que `_encode_sync` només s'invoca
post-`_ensure_loaded`.

Decisió Director (Cluster 8): Dev#2 introdueix un guard `assert self._model
is not None` o `if self._model is None: raise RuntimeError(...)` als helpers
síncrons.

CONTRACTE PINAT:
1. `_encode_sync` i `_encode_batch_sync` segueixen sent mètodes d'instància
   amb signatures (text, normalize) i (texts, normalize, batch_size). Fix
   mypy NO ha de canviar les signatures externes.
2. **TDD post-fix:** quan `_model is None` i s'invoca `_encode_sync`, ha de
   llançar `RuntimeError` (no `AttributeError` opaca). Aquest test pina el
   contracte explícit del fix Cluster 8 — pre-fix és AttributeError.

Pre-fix (HEAD `30eb2a6`): `AttributeError: 'NoneType' object has no attribute
'embed'`. Per això el TDD es marca `xfail(strict=True)`.
"""

from __future__ import annotations

import inspect
import uuid

import pytest


def _fresh_embedder():
    """Crea instància `AsyncEmbedder` amb model_name únic per evitar singleton hits.

    El singleton de `AsyncEmbedder.__new__` reusa instàncies per `model_name`. Usant
    un `uuid` garantim que `_initialized=False` al `__new__` i el `__init__` corre
    íntegrament (i deixa `self._model = None` segons L94).
    """
    from memory.embeddings.core.async_encoder import AsyncEmbedder

    fake_name = f"__test_cluster8_{uuid.uuid4().hex}__"
    return AsyncEmbedder(fake_name)


def test_encode_sync_signature_pinned() -> None:
    """Anti-regressió: `_encode_sync(self, text: str, normalize: bool)` pin."""
    from memory.embeddings.core.async_encoder import AsyncEmbedder

    sig = inspect.signature(AsyncEmbedder._encode_sync)
    assert list(sig.parameters.keys()) == ["self", "text", "normalize"], (
        f"Signatura _encode_sync canviada: {list(sig.parameters.keys())}. "
        "Fix Cluster 8 ha de mantenir la signatura externa."
    )


def test_encode_batch_sync_signature_pinned() -> None:
    from memory.embeddings.core.async_encoder import AsyncEmbedder

    sig = inspect.signature(AsyncEmbedder._encode_batch_sync)
    assert list(sig.parameters.keys()) == ["self", "texts", "normalize", "batch_size"], (
        f"Signatura _encode_batch_sync canviada: {list(sig.parameters.keys())}."
    )


def test_async_embedder_model_starts_none() -> None:
    """Pina la premisa del bug: `__init__` deixa `_model = None` (línia 94)."""
    embedder = _fresh_embedder()
    try:
        assert embedder._model is None, (
            "AsyncEmbedder.__init__ ja no inicialitza _model a None — invariant "
            "lazy-load trencat (cluster 8 perd sentit)."
        )
    finally:
        # Singleton cleanup per no contaminar altres tests
        from memory.embeddings.core.async_encoder import AsyncEmbedder
        AsyncEmbedder._instances.pop(embedder.model_name, None)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Bug bloquejat pre-Dev#2 (Cluster 8). Pre-fix _encode_sync amb _model=None "
        "llança AttributeError opaca; post-fix ha de llançar RuntimeError explícit. "
        "Dev#2 treurà aquesta marca al commit cluster 8."
    ),
)
def test_encode_sync_raises_runtime_error_when_model_none() -> None:
    """TDD post-fix: `_encode_sync` amb `_model=None` llança `RuntimeError`."""
    embedder = _fresh_embedder()
    try:
        assert embedder._model is None  # premisa explícita

        with pytest.raises(RuntimeError) as exc_info:
            embedder._encode_sync("text", True)

        msg = str(exc_info.value).lower()
        assert "model" in msg or "loaded" in msg or "ensure" in msg, (
            f"Missatge esperat menciona model/loaded/ensure, rebut: {exc_info.value!r}"
        )
    finally:
        from memory.embeddings.core.async_encoder import AsyncEmbedder
        AsyncEmbedder._instances.pop(embedder.model_name, None)
