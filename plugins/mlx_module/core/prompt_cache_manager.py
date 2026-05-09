# -*- coding: utf-8 -*-
"""
MLX Prompt Cache Manager with Prefix Matching.

Adapted from the LRUPromptCache pattern in mlx_lm/server.py to provide
real prefix matching in multi-turn conversations.

Features:
- Trie-based cache by tokens
- Searches for the longest matching prefix
- Returns only the new tokens to process
- LRU eviction when too many entries

"""
import copy
import logging
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cache entry with a reference counter."""
    prompt_cache: List[Any]
    count: int


@dataclass
class SearchResult:
    """Search result in the cache trie."""
    model: str
    exact: Optional[List[int]]
    shorter: Optional[List[int]]
    longer: Optional[List[int]]
    common_prefix: int


class MLXPromptCacheManager:
    """
    Cache manager with prefix matching for MLX.

    Uses a trie to store caches indexed by token sequence.
    When searching for a cache, returns the longest matching prefix
    and the remaining tokens that need to be processed.

    This allows reusing the KV cache of the system prompt + history
    and only processing new messages.

    Attributes:
        max_size: Maximum number of cache entries
        _cache: Dict model -> token trie -> CacheEntry
        _lru: Deque for LRU eviction
        _lock: Lock for thread-safety
    """

    def __init__(self, max_size: int = 8):
        """
        Initializes the cache manager.

        Args:
            max_size: Maximum number of entries (default 8)
        """
        self.max_size = max_size
        self._cache: Dict[str, Dict] = {}
        self._lru: deque = deque()
        self._lock = threading.Lock()

    def _trie_traverse(self, model: str, tokens: List[int]):
        """Walk the trie following tokens; return (node, last_cache_index, index)."""
        current = self._cache[model]
        last_cache_index = -1
        index = 0
        while index < len(tokens) and tokens[index] in current:
            current = current[tokens[index]]
            if "cache" in current:
                last_cache_index = index
            index += 1
        return current, last_cache_index, index

    def _find_longer_tokens(self, node, tokens: List[int], index: int) -> Optional[List[int]]:
        """BFS to find the shortest cached continuation beyond index."""
        best = None
        stack: list = [(node, [])]
        while stack:
            curr, extra = stack.pop()
            if "cache" in curr:
                if best is None or len(extra) < len(best):
                    best = extra
            else:
                for tok in curr:
                    if tok != "cache":
                        stack.append((curr[tok], extra + [tok]))
        return tokens[:index] + best if best else None

    def _search(self, model: str, tokens: List[int]) -> SearchResult:
        """
        Searches the cache for the longest matching prefix.

        Args:
            model: Model key
            tokens: Token sequence to search

        Returns:
            SearchResult with exact, shorter, longer or no match
        """
        if model not in self._cache:
            return SearchResult(model, None, None, None, 0)

        node, last_cache_index, index = self._trie_traverse(model, tokens)

        if last_cache_index == len(tokens) - 1:
            return SearchResult(model, tokens, None, None, 0)

        shorter = tokens[:last_cache_index + 1] if last_cache_index >= 0 else None

        longer = None
        common_prefix = index
        if index > 0 and last_cache_index < 0:
            longer = self._find_longer_tokens(node, tokens, index)

        return SearchResult(model, None, shorter, longer, common_prefix)

    def _get(self, model: str, tokens: List[int]) -> CacheEntry:
        """Get CacheEntry for exact tokens."""
        current = self._cache[model]
        for tok in tokens:
            current = current[tok]
        return current["cache"]

    def _delete(self, model: str, tokens: List[int]) -> None:
        """Delete cache and clean empty trie nodes."""
        path = [self._cache[model]]
        for tok in tokens:
            path.append(path[-1][tok])

        del path[-1]["cache"]

        # Clean empty nodes
        for i in reversed(range(len(tokens))):
            d_prev, d, t = path[i], path[i + 1], tokens[i]
            if len(d) > 0:
                break
            del d_prev[t]

    def _extract(self, model: str, tokens: List[int]) -> CacheEntry:
        """
        Extract cache for use.

        IMPORTANT: We do NOT remove the cache from the trie! We need it for
        prefix matching in subsequent turns. We always deepcopy and
        keep the original in the trie.

        This allows:
        - T1: tokens=[1..1600] → saves cache
        - T2: tokens=[1..1600, new] → finds prefix 1600, reuses cache
        - T3: tokens=[1..1600, new, more] → finds prefix 1600, reuses cache

        Previously (BUG): T2 deleted the cache, T3 could not find it.
        """
        cache_entry = self._get(model, tokens)

        # Always deepcopy and keep the original in the trie
        # to allow prefix matching in subsequent turns
        return CacheEntry(
            copy.deepcopy(cache_entry.prompt_cache),
            1
        )

    def fetch_nearest_cache(
        self,
        model: str,
        tokens: List[int]
    ) -> Tuple[Optional[List[Any]], List[int]]:
        """
        Finds the nearest cache and returns the remaining tokens.

        This is the main function. Finds the longest prefix
        that matches the given tokens and returns:
        - The KV cache for that prefix
        - The tokens that remain to be processed (new)

        Args:
            model: Model key (e.g. path or hash)
            tokens: Full token sequence of the prompt

        Returns:
            Tuple (prompt_cache, remaining_tokens):
            - prompt_cache: Reusable KV cache (or None if none)
            - remaining_tokens: New tokens to process
        """
        with self._lock:
            result = self._search(model, tokens)

            # Exact match
            if result.exact is not None:
                cache_entry = self._extract(result.model, result.exact)
                logger.debug(
                    "MLXPromptCacheManager: exact match, %d tokens cached",
                    len(result.exact)
                )
                return cache_entry.prompt_cache, []

            # Shorter prefix
            if result.shorter is not None:
                cache_entry = self._extract(result.model, result.shorter)
                prefix_len = len(result.shorter)
                rest = tokens[prefix_len:]
                logger.debug(
                    "MLXPromptCacheManager: shorter match, %d cached, %d new",
                    prefix_len, len(rest)
                )
                return cache_entry.prompt_cache, rest

            # Longer prefix (trim required)
            if result.longer is not None:
                try:
                    from mlx_lm.models.cache import (
                        can_trim_prompt_cache,
                        trim_prompt_cache
                    )

                    cache_entry = self._get(result.model, result.longer)
                    if can_trim_prompt_cache(cache_entry.prompt_cache):
                        trimmed_cache = copy.deepcopy(cache_entry.prompt_cache)
                        prefix = min(len(tokens) - 1, result.common_prefix)
                        num_to_trim = len(result.longer) - prefix
                        trim_prompt_cache(trimmed_cache, num_to_trim)
                        rest = tokens[prefix:]
                        logger.debug(
                            "MLXPromptCacheManager: longer match trimmed, %d new",
                            len(rest)
                        )
                        return trimmed_cache, rest
                except Exception as e:
                    logger.warning("MLXPromptCacheManager: trim failed: %s", e)

            # No match
            logger.debug("MLXPromptCacheManager: no match, %d tokens", len(tokens))
            return None, tokens

    def insert_cache(
        self,
        model: str,
        tokens: List[int],
        prompt_cache: List[Any]
    ) -> None:
        """
        Insert cache into the trie.

        Args:
            model: Model key
            tokens: Processed token sequence
            prompt_cache: KV cache to store
        """
        with self._lock:
            if model not in self._cache:
                self._cache[model] = {}

            # Navigate/create path in the trie
            current = self._cache[model]
            for tok in tokens:
                if tok not in current:
                    current[tok] = {}
                current = current[tok]

            # Update or create entry
            tokens_key = tuple(tokens)
            if "cache" in current:
                current["cache"].count += 1
                try:
                    self._lru.remove((model, tokens_key))
                except ValueError:
                    pass
            else:
                current["cache"] = CacheEntry(prompt_cache, 1)

            self._lru.append((model, tokens_key))

            # LRU eviction
            while len(self._lru) > self.max_size:
                old_model, old_tokens = self._lru.popleft()
                try:
                    self._delete(old_model, list(old_tokens))
                    logger.debug(
                        "MLXPromptCacheManager: evicted cache for %s",
                        old_model[:20]
                    )
                except (KeyError, IndexError):
                    pass

    def invalidate_model(self, model: str) -> None:
        """Invalidates all caches for a model."""
        with self._lock:
            if model in self._cache:
                del self._cache[model]
                self._lru = deque(
                    (m, t) for m, t in self._lru if m != model
                )
                logger.info(
                    "MLXPromptCacheManager: invalidated all caches for %s",
                    model[:20]
                )

    def clear(self) -> None:
        """Clears all cache."""
        with self._lock:
            self._cache.clear()
            self._lru.clear()
            logger.info("MLXPromptCacheManager: cleared all caches")

    def get_stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        with self._lock:
            return {
                "models": list(self._cache.keys()),
                "total_entries": len(self._lru),
                "max_size": self.max_size,
                "lru_order": [
                    (m[:20], len(t)) for m, t in list(self._lru)[-5:]
                ]
            }


# Global singleton (Bug 19: protected with double-checked locking)
_prompt_cache_manager: Optional[MLXPromptCacheManager] = None
_singleton_lock = threading.Lock()


def get_prompt_cache_manager(max_size: int = 8) -> MLXPromptCacheManager:
    """
    Get the cache manager singleton.

    Bug 19: thread-safe via double-checked locking. Without a lock, two
    concurrent calls could create two singleton instances —
    duplicating memory and losing shared cache.

    Args:
        max_size: Maximum size (only applied the first time)

    Returns:
        MLXPromptCacheManager singleton
    """
    global _prompt_cache_manager
    if _prompt_cache_manager is None:
        with _singleton_lock:
            if _prompt_cache_manager is None:  # double-check
                _prompt_cache_manager = MLXPromptCacheManager(max_size)
    return _prompt_cache_manager
