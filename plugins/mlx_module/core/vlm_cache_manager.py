# -*- coding: utf-8 -*-
"""
VLM Prompt Cache Manager.

Keeps one ``mlx_vlm`` ``PromptCacheState`` per session so the VLM generation
path reuses the KV cache across conversation turns (prefix matching), the same
way :class:`MLXPromptCacheManager` already does for the text path.

Why this exists
---------------
The text path (``_generate_blocking``) reuses the KV cache via
``MLXPromptCacheManager`` (trie + prefix matching). The VLM path
(``_generate_vlm``) historically wired NO cache at all: every turn re-prefilled
the whole context (the ``cached=0`` seen in production logs), so latency and
memory grew with the conversation. Any model detected as VLM
(``_detect_vlm_capability`` → True, e.g. the Qwen3.5 family — which is VL at
every tier) paid the full re-prefill on each turn.

``mlx_vlm`` >= 0.4 ships a native ``PromptCacheState`` (``find_prefix_length`` +
``update``). ``stream_generate`` accepts it via the ``prompt_cache_state``
kwarg, reuses the common prefix, and only prefills the new tokens. This manager
holds one such state per ``model_key`` and hands it to the runner.

Memory note
-----------
VLM KV caches are large. On low-RAM machines (the 8 GB case that surfaced this
bug) we keep a very small number of sessions (default 1) and evict LRU, so we
never hold a stale cache while a fresh conversation runs.
"""
import logging
import threading
from collections import OrderedDict
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# mlx_vlm >= 0.4 exposes PromptCacheState. Import defensively so an older
# mlx_vlm (without it) degrades to "no prefix reuse" instead of crashing —
# i.e. exactly today's behaviour, zero regression.
try:
    from mlx_vlm.generate import PromptCacheState  # type: ignore

    _VLM_CACHE_AVAILABLE = True
except Exception:  # pragma: no cover - depends on installed mlx_vlm version
    PromptCacheState = None  # type: ignore
    _VLM_CACHE_AVAILABLE = False


class VLMPromptCacheManager:
    """Holds one ``PromptCacheState`` per ``model_key`` with LRU eviction.

    The ``model_key`` is built by the caller exactly like the text path
    (``model_path:identity_hash:session``). Because ``identity_hash`` is part of
    the key, a change in the system prompt naturally yields a new key — the old
    state is evicted (LRU), which doubles as cache invalidation.
    """

    def __init__(self, max_sessions: int = 1):
        # At least 1; on 8 GB we keep exactly one live VLM KV cache.
        self.max_sessions = max(1, max_sessions)
        self._states: "OrderedDict[str, Any]" = OrderedDict()
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        """True if the installed mlx_vlm exposes PromptCacheState."""
        return _VLM_CACHE_AVAILABLE

    def get_or_create(self, model_key: str) -> Optional[Any]:
        """Return the ``PromptCacheState`` for ``model_key`` (create if missing).

        Returns ``None`` when mlx_vlm has no ``PromptCacheState`` (older
        version); the caller then runs without prefix reuse — same as today, no
        regression.
        """
        if not _VLM_CACHE_AVAILABLE:
            return None
        with self._lock:
            state = self._states.get(model_key)
            if state is None:
                state = PromptCacheState()
                self._states[model_key] = state
                logger.info(
                    "VLMPromptCacheManager: new cache state (key=%s)", model_key[:30]
                )
            # Mark most-recently used.
            self._states.move_to_end(model_key)
            # LRU eviction — frees the KV memory of stale sessions.
            while len(self._states) > self.max_sessions:
                old_key, _ = self._states.popitem(last=False)
                logger.info(
                    "VLMPromptCacheManager: evicted cache state (key=%s)", old_key[:30]
                )
            return state

    def invalidate(self, model_key: str) -> None:
        """Drop the cache state for a single ``model_key``."""
        with self._lock:
            if model_key in self._states:
                del self._states[model_key]
                logger.info(
                    "VLMPromptCacheManager: invalidated (key=%s)", model_key[:30]
                )

    def clear(self) -> None:
        """Drop all cache states (e.g. on model reload)."""
        with self._lock:
            self._states.clear()
            logger.info("VLMPromptCacheManager: cleared all VLM cache states")

    def get_stats(self) -> Dict[str, Any]:
        """Return cache statistics (for the MLX status endpoint)."""
        with self._lock:
            return {
                "available": _VLM_CACHE_AVAILABLE,
                "sessions": [k[:20] for k in self._states.keys()],
                "total": len(self._states),
                "max_sessions": self.max_sessions,
            }


# Global singleton (double-checked locking, same pattern as the text manager).
_vlm_cache_manager: Optional[VLMPromptCacheManager] = None
_singleton_lock = threading.Lock()


def get_vlm_cache_manager(max_sessions: int = 1) -> VLMPromptCacheManager:
    """Get the VLM cache manager singleton.

    Args:
        max_sessions: Maximum live VLM cache states (only applied on first call).

    Returns:
        VLMPromptCacheManager singleton.
    """
    global _vlm_cache_manager
    if _vlm_cache_manager is None:
        with _singleton_lock:
            if _vlm_cache_manager is None:  # double-check
                _vlm_cache_manager = VLMPromptCacheManager(max_sessions)
    return _vlm_cache_manager
