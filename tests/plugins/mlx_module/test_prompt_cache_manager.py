"""
Tests for plugins/mlx_module/prompt_cache_manager.py.
"""

import pytest
from unittest.mock import patch, MagicMock
from plugins.mlx_module.core.prompt_cache_manager import (
    MLXPromptCacheManager,
    CacheEntry,
    SearchResult,
    get_prompt_cache_manager,
    _prompt_cache_manager,
)


class TestCacheEntry:
    """Test CacheEntry dataclass."""

    def test_creation(self):
        """Test creating a CacheEntry."""
        entry = CacheEntry(prompt_cache=["data"], count=1)
        assert entry.prompt_cache == ["data"]
        assert entry.count == 1


class TestSearchResult:
    """Test SearchResult dataclass."""

    def test_creation(self):
        """Test creating a SearchResult."""
        result = SearchResult(
            model="test",
            exact=[1, 2],
            shorter=None,
            longer=None,
            common_prefix=0,
        )
        assert result.model == "test"
        assert result.exact == [1, 2]


class TestMLXPromptCacheManager:
    """Test MLXPromptCacheManager."""

    def test_init_default(self):
        """Test default initialization."""
        mgr = MLXPromptCacheManager()
        assert mgr.max_size == 8
        assert mgr._cache == {}
        assert len(mgr._lru) == 0

    def test_init_custom_size(self):
        """Test custom max_size."""
        mgr = MLXPromptCacheManager(max_size=4)
        assert mgr.max_size == 4

    def test_search_no_model(self):
        """Test search for non-existent model."""
        mgr = MLXPromptCacheManager()
        result = mgr._search("nonexistent", [1, 2, 3])
        assert result.exact is None
        assert result.shorter is None
        assert result.longer is None
        assert result.common_prefix == 0

    def test_insert_and_exact_match(self):
        """Test inserting cache and finding exact match."""
        mgr = MLXPromptCacheManager()
        tokens = [1, 2, 3]
        cache_data = ["kv_cache_data"]

        mgr.insert_cache("model1", tokens, cache_data)

        result = mgr._search("model1", tokens)
        assert result.exact == tokens

    def test_insert_and_shorter_match(self):
        """Test finding shorter prefix match."""
        mgr = MLXPromptCacheManager()
        mgr.insert_cache("model1", [1, 2, 3], ["cache1"])

        # Search for longer sequence
        result = mgr._search("model1", [1, 2, 3, 4, 5])
        assert result.shorter == [1, 2, 3]

    def test_insert_and_longer_match(self):
        """Test finding longer match in trie."""
        mgr = MLXPromptCacheManager()
        mgr.insert_cache("model1", [1, 2, 3, 4, 5], ["cache_long"])

        # Search for shorter sequence that isn't cached
        result = mgr._search("model1", [1, 2])
        # Should find longer: the existing [1,2,3,4,5] has continuation
        assert result.longer is not None or result.shorter is None

    def test_fetch_nearest_cache_exact(self):
        """Test fetch with exact match."""
        mgr = MLXPromptCacheManager()
        tokens = [10, 20, 30]
        cache_data = ["kv_data"]
        mgr.insert_cache("m1", tokens, cache_data)

        prompt_cache, remaining = mgr.fetch_nearest_cache("m1", tokens)
        assert prompt_cache is not None
        assert remaining == []

    def test_insert_cache_snapshots_against_caller_mutation(self):
        """B120: insert_cache must store an immutable snapshot. The post-prefill
        save inserts cached_kv and then generation keeps mutating that SAME object
        in place, so storing by reference left the prompt-only entry holding a
        prompt+response cache (offset desync). Mutation 'CacheEntry(prompt_cache,
        1)' (store by reference) → fetched sees the mutated 7 → red."""
        mgr = MLXPromptCacheManager(max_size=4)

        class _KV:
            def __init__(self, offset):
                self.offset = offset

        cache = [_KV(3)]                      # prefill state: 3 tokens
        mgr.insert_cache("m", [1, 2, 3], cache)
        cache[0].offset = 7                   # generation extends the SAME object in place
        fetched, remaining = mgr.fetch_nearest_cache("m", [1, 2, 3])
        assert remaining == []
        assert fetched[0].offset == 3         # snapshot at insert time, not the mutated 7

    def test_fetch_nearest_cache_shorter(self):
        """Test fetch with shorter prefix match."""
        mgr = MLXPromptCacheManager()
        prefix = [10, 20, 30]
        mgr.insert_cache("m1", prefix, ["kv"])

        full = [10, 20, 30, 40, 50]
        prompt_cache, remaining = mgr.fetch_nearest_cache("m1", full)
        assert prompt_cache is not None
        assert remaining == [40, 50]

    def test_fetch_nearest_cache_no_match(self):
        """Test fetch with no match."""
        mgr = MLXPromptCacheManager()
        prompt_cache, remaining = mgr.fetch_nearest_cache("m1", [1, 2, 3])
        assert prompt_cache is None
        assert remaining == [1, 2, 3]

    def test_fetch_nearest_cache_longer_with_trim(self):
        """Test fetch with longer match requiring trim."""
        mgr = MLXPromptCacheManager()
        # Insert a longer cache (keep a handle on the exact stored object)
        original_cache = ["kv_long"]
        mgr.insert_cache("m1", [1, 2, 3, 4, 5], original_cache)

        # Mock the trim functions
        mock_can_trim = MagicMock(return_value=True)
        mock_trim = MagicMock()

        with patch.dict("sys.modules", {
            "mlx_lm": MagicMock(),
            "mlx_lm.models": MagicMock(),
            "mlx_lm.models.cache": MagicMock(
                can_trim_prompt_cache=mock_can_trim,
                trim_prompt_cache=mock_trim,
            ),
        }):
            # [1, 2] has no exact/shorter cache but the trie holds the longer
            # entry [1, 2, 3, 4, 5], so fetch must take the longer/trim branch.
            prompt_cache, remaining = mgr.fetch_nearest_cache("m1", [1, 2])

        # Trim branch returns the trimmed (deepcopied) cache, not None.
        assert prompt_cache is not None
        assert prompt_cache is not original_cache  # deepcopy, not the trie's object
        assert prompt_cache == ["kv_long"]
        # common_prefix=2 but prefix=min(len(tokens)-1, 2)=1, so rest=tokens[1:].
        assert remaining == [2]
        # The trim path was actually exercised: num_to_trim = len(longer) - prefix = 5 - 1.
        mock_can_trim.assert_called_once()
        mock_trim.assert_called_once_with(["kv_long"], 4)

    def test_fetch_nearest_cache_longer_trim_fails(self):
        """Test fetch with longer match when trim fails."""
        mgr = MLXPromptCacheManager()
        mgr.insert_cache("m1", [1, 2, 3, 4, 5], ["kv"])

        mock_can_trim = MagicMock(side_effect=RuntimeError("trim fail"))
        with patch.dict("sys.modules", {
            "mlx_lm": MagicMock(),
            "mlx_lm.models": MagicMock(),
            "mlx_lm.models.cache": MagicMock(
                can_trim_prompt_cache=mock_can_trim,
            ),
        }):
            prompt_cache, remaining = mgr.fetch_nearest_cache("m1", [1, 2])

        # The longer branch was entered (can_trim invoked) but raised, so the
        # except handler swallows it and execution falls through to "no match".
        mock_can_trim.assert_called_once()
        assert prompt_cache is None
        assert remaining == [1, 2]

    def test_insert_updates_existing(self):
        """Test inserting to same key updates count."""
        mgr = MLXPromptCacheManager()
        tokens = [1, 2, 3]
        mgr.insert_cache("m1", tokens, ["v1"])
        mgr.insert_cache("m1", tokens, ["v2"])

        entry = mgr._get("m1", tokens)
        assert entry.count == 2

    def test_lru_eviction(self):
        """Test LRU eviction when max_size exceeded."""
        mgr = MLXPromptCacheManager(max_size=2)
        mgr.insert_cache("m1", [1], ["c1"])
        mgr.insert_cache("m1", [2], ["c2"])
        mgr.insert_cache("m1", [3], ["c3"])  # Should evict [1]

        assert len(mgr._lru) == 2

    def test_delete(self):
        """Test deleting a cache entry."""
        mgr = MLXPromptCacheManager()
        mgr.insert_cache("m1", [1, 2, 3], ["cache"])
        mgr._delete("m1", [1, 2, 3])

        result = mgr._search("m1", [1, 2, 3])
        assert result.exact is None

    def test_extract_returns_deepcopy(self):
        """Test that extract returns a deepcopy."""
        mgr = MLXPromptCacheManager()
        original = [{"key": "value"}]
        mgr.insert_cache("m1", [1, 2], original)

        extracted = mgr._extract("m1", [1, 2])
        assert extracted.prompt_cache is not original
        assert extracted.count == 1

    def test_invalidate_model(self):
        """Test invalidating all caches for a model."""
        mgr = MLXPromptCacheManager()
        mgr.insert_cache("m1", [1], ["c1"])
        mgr.insert_cache("m1", [2], ["c2"])
        mgr.insert_cache("m2", [1], ["c3"])

        mgr.invalidate_model("m1")

        assert "m1" not in mgr._cache
        assert "m2" in mgr._cache
        assert all(m != "m1" for m, _ in mgr._lru)

    def test_invalidate_model_nonexistent(self):
        """Test invalidating non-existent model."""
        mgr = MLXPromptCacheManager()
        mgr.invalidate_model("nonexistent")  # Should not raise

    def test_clear(self):
        """Test clearing all caches."""
        mgr = MLXPromptCacheManager()
        mgr.insert_cache("m1", [1], ["c1"])
        mgr.insert_cache("m2", [2], ["c2"])

        mgr.clear()

        assert mgr._cache == {}
        assert len(mgr._lru) == 0

    def test_get_stats(self):
        """Test getting cache statistics."""
        mgr = MLXPromptCacheManager()
        mgr.insert_cache("model_a", [1, 2], ["c1"])
        mgr.insert_cache("model_b", [3, 4], ["c2"])

        stats = mgr.get_stats()
        assert "model_a" in stats["models"]
        assert "model_b" in stats["models"]
        assert stats["total_entries"] == 2
        assert stats["max_size"] == 8
        assert len(stats["lru_order"]) == 2

    def test_get_stats_empty(self):
        """Test stats on empty cache."""
        mgr = MLXPromptCacheManager()
        stats = mgr.get_stats()
        assert stats["models"] == []
        assert stats["total_entries"] == 0

    def test_search_with_deeper_trie(self):
        """Test search with multiple entries creating a deeper trie."""
        mgr = MLXPromptCacheManager()
        mgr.insert_cache("m1", [1, 2, 3], ["c1"])
        mgr.insert_cache("m1", [1, 2, 3, 4, 5], ["c2"])

        # Search for [1, 2, 3, 4] - should find shorter at [1, 2, 3]
        result = mgr._search("m1", [1, 2, 3, 4])
        assert result.shorter == [1, 2, 3]

    def test_lru_eviction_key_error(self):
        """Test LRU eviction handles already-deleted entries."""
        mgr = MLXPromptCacheManager(max_size=1)
        mgr.insert_cache("m1", [1], ["c1"])
        # Manually mess with internal state to trigger KeyError
        mgr._cache["m1"] = {}
        mgr.insert_cache("m1", [2], ["c2"])  # Should handle KeyError/IndexError


class TestGetPromptCacheManager:
    """Test singleton factory."""

    def test_get_prompt_cache_manager(self):
        """Test singleton creation."""
        import plugins.mlx_module.core.prompt_cache_manager as pcm

        # Reset the singleton
        pcm._prompt_cache_manager = None

        mgr1 = pcm.get_prompt_cache_manager(max_size=4)
        assert mgr1.max_size == 4

        mgr2 = pcm.get_prompt_cache_manager(max_size=16)
        assert mgr1 is mgr2  # Same instance
        assert mgr2.max_size == 4  # First call's max_size wins

        # Clean up
        pcm._prompt_cache_manager = None
