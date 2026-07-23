# -*- coding: utf-8 -*-
"""Process-wide cache of fastembed TextEmbedding instances.

Every ``TextEmbedding(...)`` call builds its own ONNX InferenceSession, and each
session holds its own copy of the model weights. With the multilingual mpnet
model that is ~1.4 GB resident per session in FP32 — and the sidecar was
creating one in ``MemoryAPI._init_embedder`` and another in the ingestion
pipeline, so a machine that had barely enough RAM for the LLM was paying for the
embedder twice (three times while an auto-ingest was running).

The instances are functionally interchangeable: same model, same cache dir, same
normalisation downstream. Sharing one per (model, cache_dir, threads) removes the
duplication without changing any embedding output.

Thread safety: ONNX Runtime sessions are safe for concurrent inference, which is
what fastembed does under ``embed()``. Construction is serialised by a lock so a
race at startup cannot build two sessions and defeat the point.

Escape hatch: ``NEXE_SHARED_EMBEDDER=0`` restores the previous behaviour (a fresh
instance per call site) without a rebuild, in case sharing ever turns out to
misbehave in the field.
"""

import logging
import os
import threading
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_instances: Dict[Tuple[str, str, Optional[int]], Any] = {}
_lock = threading.Lock()


def sharing_enabled() -> bool:
    """False when NEXE_SHARED_EMBEDDER is explicitly disabled."""
    return os.environ.get("NEXE_SHARED_EMBEDDER", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def get_text_embedding(model_name: str, threads: Optional[int] = None) -> Any:
    """Return a shared TextEmbedding for ``model_name`` (built on first use).

    Raises whatever fastembed raises when the model is not available locally —
    callers already translate that into their own installer-facing message, and
    a failed construction is deliberately NOT cached so a later retry (e.g.
    after the installer finishes downloading) can still succeed.
    """
    from fastembed import TextEmbedding

    from memory.embeddings.paths import default_fastembed_cache_dir

    cache_dir = str(default_fastembed_cache_dir())
    kwargs: Dict[str, Any] = {"cache_dir": cache_dir}
    if threads is not None:
        kwargs["threads"] = threads

    if not sharing_enabled():
        return TextEmbedding(model_name, **kwargs)

    key = (model_name, cache_dir, threads)
    instance = _instances.get(key)
    if instance is not None:
        return instance

    with _lock:
        # Re-check inside the lock: two callers can arrive together at startup.
        instance = _instances.get(key)
        if instance is not None:
            return instance
        instance = TextEmbedding(model_name, **kwargs)
        _instances[key] = instance
        logger.info(
            "Shared TextEmbedding created (model=%s, threads=%s, live sessions=%d)",
            model_name, threads, len(_instances),
        )
        return instance


def reset_shared_embedders() -> None:
    """Drop the cached instances. For tests and for teardown paths only."""
    with _lock:
        _instances.clear()
