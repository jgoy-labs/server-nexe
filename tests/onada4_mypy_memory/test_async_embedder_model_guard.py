"""Anti-regression Cluster 8 — `AsyncEmbedder._model` lazy-load guard.

Covers the 2 mypy `union-attr` findings at
`memory/embeddings/core/async_encoder.py:207` (`_encode_sync` calling
`self._model.embed([text])`) and L283 (`_encode_batch_sync` calling
`self._model.embed(texts, ...)`). Cause: `_model: Optional[object] = None`
(L94) and it is only loaded via `await self._ensure_loaded()` (L105-122).
Mypy does not infer the cross-await invariant that `_encode_sync` is only
invoked post-`_ensure_loaded`.

Director decision (Cluster 8): Dev#2 introduces a guard `assert self._model
is not None` or `if self._model is None: raise RuntimeError(...)` in the
sync helpers.

PINNED CONTRACT:
1. `_encode_sync` and `_encode_batch_sync` remain instance methods
   with signatures (text, normalize) and (texts, normalize, batch_size). The
   mypy fix must NOT change the external signatures.
2. **TDD post-fix:** when `_model is None` and `_encode_sync` is invoked, it must
   raise `RuntimeError` (not an opaque `AttributeError`). This test pins the
   explicit contract of the Cluster 8 fix — pre-fix is AttributeError.

Pre-fix (HEAD `30eb2a6`): `AttributeError: 'NoneType' object has no attribute
'embed'`. That is why the TDD is marked `xfail(strict=True)`.
"""

from __future__ import annotations

import inspect
import uuid

import pytest


def _fresh_embedder():
    """Creates an `AsyncEmbedder` instance with a unique model_name to avoid singleton hits.

    The `AsyncEmbedder.__new__` singleton reuses instances per `model_name`. Using
    a `uuid` ensures `_initialized=False` in `__new__` and `__init__` runs
    fully (leaving `self._model = None` as per L94).
    """
    from memory.embeddings.core.async_encoder import AsyncEmbedder

    fake_name = f"__test_cluster8_{uuid.uuid4().hex}__"
    return AsyncEmbedder(fake_name)


def test_encode_sync_signature_pinned() -> None:
    """Anti-regression: `_encode_sync(self, text: str, normalize: bool)` pin."""
    from memory.embeddings.core.async_encoder import AsyncEmbedder

    sig = inspect.signature(AsyncEmbedder._encode_sync)
    assert list(sig.parameters.keys()) == ["self", "text", "normalize"], (
        f"Signature _encode_sync changed: {list(sig.parameters.keys())}. "
        "Cluster 8 fix must maintain the external signature."
    )


def test_encode_batch_sync_signature_pinned() -> None:
    from memory.embeddings.core.async_encoder import AsyncEmbedder

    sig = inspect.signature(AsyncEmbedder._encode_batch_sync)
    assert list(sig.parameters.keys()) == ["self", "texts", "normalize", "batch_size"], (
        f"Signature _encode_batch_sync changed: {list(sig.parameters.keys())}."
    )


def test_async_embedder_model_starts_none() -> None:
    """Pins the bug premise: `__init__` leaves `_model = None` (line 94)."""
    embedder = _fresh_embedder()
    try:
        assert embedder._model is None, (
            "AsyncEmbedder.__init__ no longer initialises _model to None — "
            "lazy-load invariant broken (cluster 8 loses its rationale)."
        )
    finally:
        # Singleton cleanup to avoid contaminating other tests
        from memory.embeddings.core.async_encoder import AsyncEmbedder
        AsyncEmbedder._instances.pop(embedder.model_name, None)


def test_encode_sync_raises_runtime_error_when_model_none() -> None:
    """TDD post-fix: `_encode_sync` with `_model=None` raises `RuntimeError`."""
    embedder = _fresh_embedder()
    try:
        assert embedder._model is None  # explicit premise

        with pytest.raises(RuntimeError) as exc_info:
            embedder._encode_sync("text", True)

        msg = str(exc_info.value).lower()
        assert "model" in msg or "loaded" in msg or "ensure" in msg, (
            f"Expected message to mention model/loaded/ensure, received: {exc_info.value!r}"
        )
    finally:
        from memory.embeddings.core.async_encoder import AsyncEmbedder
        AsyncEmbedder._instances.pop(embedder.model_name, None)
