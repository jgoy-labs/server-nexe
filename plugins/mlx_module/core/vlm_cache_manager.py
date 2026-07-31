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
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _key_digest(model_key: str) -> str:
    """Log-friendly form of a cache key that actually DISCRIMINATES (#843).

    The log printed ``model_key[:30]``, and a key looks like
    ``storage/models/Qwen3.5-9B-MLX-4bit:<identity_hash>:<session>`` — 30 chars
    never leave the model path, so every key logged identically. The 8 GB M1
    field capture of 23/07 was therefore read as "created and evicted the SAME key
    immediately"; measured 31/07, the keys differed and the eviction was key
    churn against ``max_sessions=1``. Keep the model name AND both
    discriminants, or the next field capture is just as unreadable.
    """
    parts = model_key.rsplit(":", 2)
    if len(parts) == 3:
        path, identity, session = parts
        return f"{Path(path).name}:{identity[:8]}:{session}"
    return model_key[-40:]

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
                    "VLMPromptCacheManager: new cache state (key=%s)",
                    _key_digest(model_key),
                )
            else:
                # #843: without this line a field log can only show creations
                # and evictions — the one thing it had to prove (that a turn
                # REUSED the state) was invisible.
                logger.info(
                    "VLMPromptCacheManager: reuse cache state (key=%s)",
                    _key_digest(model_key),
                )
            # Mark most-recently used.
            self._states.move_to_end(model_key)
            # LRU eviction — frees the KV memory of stale sessions.
            while len(self._states) > self.max_sessions:
                old_key, _ = self._states.popitem(last=False)
                logger.info(
                    "VLMPromptCacheManager: evicted cache state (key=%s)",
                    _key_digest(old_key),
                )
            return state

    def set_max_sessions(self, max_sessions: int) -> None:
        """Change the live-state ceiling and enforce it NOW.

        Lowering it has to free the KV memory immediately — on the machine this
        matters for (8 GB, #843) waiting until the next turn is waiting for the
        pressure that already exists.
        """
        with self._lock:
            self.max_sessions = max(1, max_sessions)
            while len(self._states) > self.max_sessions:
                old_key, _ = self._states.popitem(last=False)
                logger.info(
                    "VLMPromptCacheManager: evicted cache state (key=%s)",
                    _key_digest(old_key),
                )

    def invalidate(self, model_key: str) -> None:
        """Drop the cache state for a single ``model_key``."""
        with self._lock:
            if model_key in self._states:
                del self._states[model_key]
                logger.info(
                    "VLMPromptCacheManager: invalidated (key=%s)", _key_digest(model_key)
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
                "sessions": [_key_digest(k) for k in self._states.keys()],
                "total": len(self._states),
                "max_sessions": self.max_sessions,
            }


# Global singleton (double-checked locking, same pattern as the text manager).
_vlm_cache_manager: Optional[VLMPromptCacheManager] = None
_singleton_lock = threading.Lock()


def get_vlm_cache_manager(max_sessions: Optional[int] = None) -> VLMPromptCacheManager:
    """Get the VLM cache manager singleton, applying ``max_sessions`` for real.

    The argument used to land only on the very first call, and the VLM path
    called this bare — so the limit was frozen at 1 whatever anyone configured,
    while the text path honoured config.max_session_caches. Now a value passed
    here is applied to the existing singleton too (and enforced immediately).

    Args:
        max_sessions: Maximum live VLM cache states. ``None`` means "do not
            touch the current limit" — for call sites that only want the
            manager (e.g. ``clear()`` on model reload). Absent any configured
            value the ceiling stays 1: VLM KV caches are heavy and the 8 GB
            machine of #843 is the case that set that default.

    Returns:
        VLMPromptCacheManager singleton.
    """
    global _vlm_cache_manager
    if _vlm_cache_manager is None:
        with _singleton_lock:
            if _vlm_cache_manager is None:  # double-check
                _vlm_cache_manager = VLMPromptCacheManager(max_sessions or 1)
                return _vlm_cache_manager
    if max_sessions is not None and max_sessions != _vlm_cache_manager.max_sessions:
        _vlm_cache_manager.set_max_sessions(max_sessions)
    return _vlm_cache_manager
