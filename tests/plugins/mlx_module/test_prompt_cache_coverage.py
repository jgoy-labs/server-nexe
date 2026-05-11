"""Tests for plugins/mlx_module/core/prompt_cache_manager.py — coverage gaps."""


class TestCacheEntry:
    def test_dataclass_fields(self):
        from plugins.mlx_module.core.prompt_cache_manager import CacheEntry
        entry = CacheEntry(prompt_cache=[1, 2, 3], count=1)
        assert entry.prompt_cache == [1, 2, 3]
        assert entry.count == 1


class TestSearchResult:
    def test_dataclass_fields(self):
        from plugins.mlx_module.core.prompt_cache_manager import SearchResult
        sr = SearchResult(model="test", exact=None, shorter=None, longer=None, common_prefix=0)
        assert sr.model == "test"
        assert sr.exact is None


class TestMLXPromptCacheManager:
    def test_init(self):
        from plugins.mlx_module.core.prompt_cache_manager import MLXPromptCacheManager
        mgr = MLXPromptCacheManager(max_size=4)
        assert mgr.max_size == 4

    def test_insert_and_fetch(self):
        from plugins.mlx_module.core.prompt_cache_manager import MLXPromptCacheManager, CacheEntry
        mgr = MLXPromptCacheManager()
        mgr.insert_cache("model1", [1, 2, 3], CacheEntry(prompt_cache=["data"], count=1))
        cache, remaining = mgr.fetch_nearest_cache("model1", [1, 2, 3, 4])
        assert cache is not None
        assert remaining == [4]

    def test_fetch_no_cache(self):
        from plugins.mlx_module.core.prompt_cache_manager import MLXPromptCacheManager
        mgr = MLXPromptCacheManager()
        cache, remaining = mgr.fetch_nearest_cache("model1", [1, 2, 3])
        assert cache is None
        assert remaining == [1, 2, 3]

    def test_invalidate_model(self):
        from plugins.mlx_module.core.prompt_cache_manager import MLXPromptCacheManager, CacheEntry
        mgr = MLXPromptCacheManager()
        mgr.insert_cache("model1", [1, 2], CacheEntry(prompt_cache=["d"], count=1))
        mgr.invalidate_model("model1")
        cache, remaining = mgr.fetch_nearest_cache("model1", [1, 2])
        assert cache is None

    def test_clear(self):
        from plugins.mlx_module.core.prompt_cache_manager import MLXPromptCacheManager, CacheEntry
        mgr = MLXPromptCacheManager()
        mgr.insert_cache("m1", [1], CacheEntry(prompt_cache=["x"], count=1))
        mgr.clear()
        stats = mgr.get_stats()
        assert stats["total_entries"] == 0

    def test_get_stats_empty(self):
        from plugins.mlx_module.core.prompt_cache_manager import MLXPromptCacheManager
        mgr = MLXPromptCacheManager()
        stats = mgr.get_stats()
        assert stats["total_entries"] == 0
        assert stats["max_size"] == 8

    def test_get_stats_with_entries(self):
        from plugins.mlx_module.core.prompt_cache_manager import MLXPromptCacheManager, CacheEntry
        mgr = MLXPromptCacheManager()
        mgr.insert_cache("m1", [1, 2], CacheEntry(prompt_cache=["a"], count=1))
        mgr.insert_cache("m1", [3, 4], CacheEntry(prompt_cache=["b"], count=1))
        stats = mgr.get_stats()
        assert stats["total_entries"] == 2


class TestGetPromptCacheManagerSingleton:
    def test_returns_instance(self):
        from plugins.mlx_module.core.prompt_cache_manager import get_prompt_cache_manager, MLXPromptCacheManager
        mgr = get_prompt_cache_manager()
        assert isinstance(mgr, MLXPromptCacheManager)

    def test_singleton(self):
        from plugins.mlx_module.core.prompt_cache_manager import get_prompt_cache_manager
        m1 = get_prompt_cache_manager()
        m2 = get_prompt_cache_manager()
        assert m1 is m2
