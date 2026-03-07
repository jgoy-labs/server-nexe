# -*- coding: utf-8 -*-
"""
MLX Prompt Cache Manager amb Prefix Matching.

Adaptat del patró LRUPromptCache de mlx_lm/server.py per oferir
prefix matching real en converses multi-torn.

Característiques:
- Trie-based cache per tokens
- Cerca el prefix més llarg que coincideix
- Retorna només els tokens nous per processar
- LRU eviction quan massa entrades

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
    """Entrada de cache amb comptador de referències."""
    prompt_cache: List[Any]
    count: int


@dataclass
class SearchResult:
    """Resultat de cerca al trie de cache."""
    model: str
    exact: Optional[List[int]]
    shorter: Optional[List[int]]
    longer: Optional[List[int]]
    common_prefix: int


class MLXPromptCacheManager:
    """
    Gestor de cache amb prefix matching per MLX.

    Usa un trie per emmagatzemar caches indexats per seqüència de tokens.
    Quan es busca un cache, retorna el prefix més llarg que coincideix
    i els tokens restants que cal processar.

    Això permet reutilitzar el KV cache del system prompt + historial
    i només processar els missatges nous.

    Attributes:
        max_size: Màxim nombre d'entrades al cache
        _cache: Dict model -> trie de tokens -> CacheEntry
        _lru: Deque per LRU eviction
        _lock: Lock per thread-safety
    """

    def __init__(self, max_size: int = 8):
        """
        Inicialitza el gestor de cache.

        Args:
            max_size: Màxim nombre d'entrades (default 8)
        """
        self.max_size = max_size
        self._cache: Dict[str, Dict] = {}
        self._lru: deque = deque()
        self._lock = threading.Lock()

    def _search(self, model: str, tokens: List[int]) -> SearchResult:
        """
        Cerca al cache el prefix més llarg que coincideix.

        Args:
            model: Clau del model
            tokens: Seqüència de tokens a buscar

        Returns:
            SearchResult amb exact, shorter, longer o cap coincidència
        """
        if model not in self._cache:
            return SearchResult(model, None, None, None, 0)

        current = self._cache[model]
        last_cache_index = -1
        index = 0

        # Recórrer el trie seguint els tokens
        while index < len(tokens) and tokens[index] in current:
            current = current[tokens[index]]
            if "cache" in current:
                last_cache_index = index
            index += 1

        # Coincidència exacta
        if last_cache_index == len(tokens) - 1:
            return SearchResult(model, tokens, None, None, 0)

        # Cerca cache més curt (prefix vàlid)
        shorter = None
        if last_cache_index >= 0:
            shorter = tokens[:last_cache_index + 1]

        # Cerca cache més llarg (si hi ha continuació)
        longer = None
        common_prefix = index
        if index > 0 and last_cache_index < 0:
            best = None
            stack = [(current, [])]
            while stack:
                curr, extra = stack.pop()
                if "cache" in curr:
                    if best is None or len(extra) < len(best):
                        best = extra
                else:
                    for tok in curr:
                        if tok != "cache":
                            stack.append((curr[tok], extra + [tok]))
            if best:
                longer = tokens[:index] + best

        return SearchResult(model, None, shorter, longer, common_prefix)

    def _get(self, model: str, tokens: List[int]) -> CacheEntry:
        """Obtenir CacheEntry per tokens exactes."""
        current = self._cache[model]
        for tok in tokens:
            current = current[tok]
        return current["cache"]

    def _delete(self, model: str, tokens: List[int]) -> None:
        """Eliminar cache i netejar nodes buits del trie."""
        path = [self._cache[model]]
        for tok in tokens:
            path.append(path[-1][tok])

        del path[-1]["cache"]

        # Netejar nodes buits
        for i in reversed(range(len(tokens))):
            d_prev, d, t = path[i], path[i + 1], tokens[i]
            if len(d) > 0:
                break
            del d_prev[t]

    def _extract(self, model: str, tokens: List[int]) -> CacheEntry:
        """
        Extreure cache per ús.

        IMPORTANT: NO eliminem el cache del trie! El necessitem per
        prefix matching en torns següents. Sempre fem deepcopy i
        mantenim l'original al trie.

        Això permet:
        - T1: tokens=[1..1600] → guarda cache
        - T2: tokens=[1..1600, nous] → troba prefix 1600, reutilitza cache
        - T3: tokens=[1..1600, nous, més] → troba prefix 1600, reutilitza cache

        Abans (BUG): T2 eliminava el cache, T3 no el trobava.
        """
        cache_entry = self._get(model, tokens)

        # Sempre fem deepcopy i mantenim l'original al trie
        # per permetre prefix matching en torns següents
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
        Busca el cache més proper i retorna els tokens restants.

        Aquesta és la funció principal. Busca el prefix més llarg
        que coincideix amb els tokens donats i retorna:
        - El cache KV per aquell prefix
        - Els tokens que queden per processar (nous)

        Args:
            model: Clau del model (p.ex. path o hash)
            tokens: Seqüència completa de tokens del prompt

        Returns:
            Tuple (prompt_cache, remaining_tokens):
            - prompt_cache: Cache KV reutilitzable (o None si no hi ha)
            - remaining_tokens: Tokens nous a processar
        """
        with self._lock:
            result = self._search(model, tokens)

            # Coincidència exacta
            if result.exact is not None:
                cache_entry = self._extract(result.model, result.exact)
                logger.debug(
                    "MLXPromptCacheManager: exact match, %d tokens cached",
                    len(result.exact)
                )
                return cache_entry.prompt_cache, []

            # Prefix més curt
            if result.shorter is not None:
                cache_entry = self._extract(result.model, result.shorter)
                prefix_len = len(result.shorter)
                rest = tokens[prefix_len:]
                logger.debug(
                    "MLXPromptCacheManager: shorter match, %d cached, %d new",
                    prefix_len, len(rest)
                )
                return cache_entry.prompt_cache, rest

            # Prefix més llarg (cal trim)
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

            # Cap coincidència
            logger.debug("MLXPromptCacheManager: no match, %d tokens", len(tokens))
            return None, tokens

    def insert_cache(
        self,
        model: str,
        tokens: List[int],
        prompt_cache: List[Any]
    ) -> None:
        """
        Inserir cache al trie.

        Args:
            model: Clau del model
            tokens: Seqüència de tokens processats
            prompt_cache: Cache KV a emmagatzemar
        """
        with self._lock:
            if model not in self._cache:
                self._cache[model] = {}

            # Navegar/crear path al trie
            current = self._cache[model]
            for tok in tokens:
                if tok not in current:
                    current[tok] = {}
                current = current[tok]

            # Actualitzar o crear entrada
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
        """Invalida tots els caches per un model."""
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
        """Neteja tot el cache."""
        with self._lock:
            self._cache.clear()
            self._lru.clear()
            logger.info("MLXPromptCacheManager: cleared all caches")

    def get_stats(self) -> Dict[str, Any]:
        """Retorna estadístiques del cache."""
        with self._lock:
            return {
                "models": list(self._cache.keys()),
                "total_entries": len(self._lru),
                "max_size": self.max_size,
                "lru_order": [
                    (m[:20], len(t)) for m, t in list(self._lru)[-5:]
                ]
            }


# Singleton global
_prompt_cache_manager: Optional[MLXPromptCacheManager] = None


def get_prompt_cache_manager(max_size: int = 8) -> MLXPromptCacheManager:
    """
    Obtenir el singleton del gestor de cache.

    Args:
        max_size: Mida màxima (només s'aplica la primera vegada)

    Returns:
        MLXPromptCacheManager singleton
    """
    global _prompt_cache_manager
    if _prompt_cache_manager is None:
        _prompt_cache_manager = MLXPromptCacheManager(max_size)
    return _prompt_cache_manager
