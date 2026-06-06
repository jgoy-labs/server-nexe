"""
Coverage tests for memory/shared/cache.py
Covers: l2_cache_dir property/setter, _init_l2 error, _serialize/_deserialize,
        get L2 hit/miss/ttl/decode error, put, _add_to_l1 eviction,
        clear, shutdown, L2 write error, L2 read error
"""

import asyncio
import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def run_async(coro):
    """Helper to run async functions with a fresh event loop."""
    return asyncio.run(coro)


class TestMultiLevelCacheSync:
    """Tests for synchronous methods - all wrapped in asyncio.run to ensure event loop."""

    def test_init(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "cache"))
            assert cache.l1_max_size == 1000
            assert cache.conn is not None
        run_async(run())

    def test_l2_cache_dir_property(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "cache"))
            assert cache.l2_cache_dir == cache.cache_dir
        run_async(run())

    def test_l2_cache_dir_setter(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "cache"))
            new_dir = tmp_path / "new_cache"
            cache.l2_cache_dir = str(new_dir)
            assert cache.cache_dir == new_dir
            assert cache.db_path == new_dir / "embeddings_l2.db"
        run_async(run())

    def test_init_l2_error(self, tmp_path):
        from memory.shared.cache import MultiLevelCache
        with patch("memory.shared.cache.sqlite3.connect", side_effect=Exception("db error")):
            async def run():
                cache = MultiLevelCache(cache_dir=str(tmp_path / "broken"))
                assert cache.conn is None
            run_async(run())

    def test_serialize_list(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "cache"))
            result = cache._serialize_embedding([1.0, 2.0, 3.0])
            assert json.loads(result) == [1.0, 2.0, 3.0]
        run_async(run())

    def test_serialize_numpy_like(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "cache"))
            mock_arr = MagicMock()
            mock_arr.tolist.return_value = [1.0, 2.0]
            result = cache._serialize_embedding(mock_arr)
            assert json.loads(result) == [1.0, 2.0]
        run_async(run())

    def test_deserialize_string(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "cache"))
            result = cache._deserialize_embedding("[1.0, 2.0]")
            assert result == [1.0, 2.0]
        run_async(run())

    def test_deserialize_bytes(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "cache"))
            result = cache._deserialize_embedding(b"[1.0, 2.0]")
            assert result == [1.0, 2.0]
        run_async(run())

    def test_generate_key(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "cache"))
            key = cache._generate_key("text", "model", "v1")
            assert isinstance(key, str)
            assert len(key) == 64
        run_async(run())

    def test_add_to_l1_eviction(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "cache"), l1_max_size=2)
            cache._add_to_l1("key1", [1.0])
            cache._add_to_l1("key2", [2.0])
            assert len(cache.l1_cache) == 2
            cache._add_to_l1("key3", [3.0])
            assert len(cache.l1_cache) == 2
            assert "key1" not in cache.l1_cache
        run_async(run())


class TestMultiLevelCacheAsync:
    """Tests for async methods - each creates a fresh cache in a single asyncio.run()."""

    def test_get_l1_hit(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "c1"))
            key = cache._generate_key("text", "model", "v1")
            cache.l1_cache[key] = [1.0, 2.0]
            result = await cache.get("text", "model", "v1")
            assert result == [1.0, 2.0]
        run_async(run())

    def test_put_and_get_l2(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "c2"))
            await cache.put("text", "model", [1.0, 2.0], "v1")
            cache.l1_cache.clear()
            result = await cache.get("text", "model", "v1")
            assert result == [1.0, 2.0]
        run_async(run())

    def test_get_l2_expired(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "c3"))
            cache.l2_ttl_seconds = 0
            await cache.put("text", "model", [1.0], "v1")
            cache.l1_cache.clear()
            import time
            time.sleep(0.01)
            result = await cache.get("text", "model", "v1")
            assert result is None
        run_async(run())

    def test_get_l2_decode_error(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "c4"))
            key = cache._generate_key("text", "model", "v1")
            cursor = cache.conn.cursor()
            cursor.execute(
                "INSERT INTO cache (key, data, created_at, last_accessed) VALUES (?, ?, ?, ?)",
                (key, "invalid json {{{", time.time(), time.time())
            )
            cache.conn.commit()
            cursor.close()
            result = await cache.get("text", "model", "v1")
            assert result is None
        run_async(run())

    def test_get_miss(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "c5"))
            result = await cache.get("nonexistent", "model", "v1")
            assert result is None
        run_async(run())

    def test_get_no_conn(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "c6"))
            cache.l1_cache.clear()
            cache.conn = None
            result = await cache.get("text", "model", "v1")
            assert result is None
        run_async(run())

    def test_put_no_conn(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "c7"))
            cache.conn = None
            await cache.put("text", "model", [1.0], "v1")
            key = cache._generate_key("text", "model", "v1")
            assert key in cache.l1_cache
        run_async(run())

    def test_clear(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "c8"))
            await cache.put("text", "model", [1.0], "v1")
            await cache.clear()
            assert len(cache.l1_cache) == 0
        run_async(run())

    def test_clear_no_conn(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "c9"))
            cache.conn = None
            await cache.clear()
            assert len(cache.l1_cache) == 0
        run_async(run())

    def test_shutdown(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "c10"))
            await cache.shutdown()
            assert cache.conn is None
        run_async(run())

    def test_shutdown_no_conn(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "c11"))
            cache.conn = None
            await cache.shutdown()
            assert cache.conn is None
        run_async(run())

    def test_get_l2_read_error(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "c12"))
            original_conn = cache.conn
            cache.conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.execute.side_effect = Exception("read error")
            mock_cursor.close = MagicMock()
            cache.conn.cursor.return_value = mock_cursor
            result = await cache.get("text", "model", "v1")
            assert result is None
            cache.conn = original_conn
        run_async(run())

    def test_put_l2_write_error(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache
            cache = MultiLevelCache(cache_dir=str(tmp_path / "c13"))
            original_conn = cache.conn
            cache.conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.execute.side_effect = Exception("write error")
            mock_cursor.close = MagicMock()
            cache.conn.cursor.return_value = mock_cursor
            await cache.put("text", "model", [1.0], "v1")
            cache.conn = original_conn
        run_async(run())


class TestL2SizeEviction:
    """MEM-010: the L2 SQLite store must be bounded by l2_max_size_bytes."""

    def test_put_evicts_oldest_when_over_budget(self, tmp_path):
        async def run():
            from memory.shared.cache import MultiLevelCache

            cache = MultiLevelCache(cache_dir=str(tmp_path / "evict"))
            cache._l2_eviction_interval = 4

            # Each embedding serialises to a few hundred bytes of JSON.
            big_vec = [0.123456789] * 64
            one_row_bytes = len(cache._serialize_embedding(big_vec))
            # Budget that should hold a small handful of rows, not all 40.
            cache.l2_max_size_bytes = one_row_bytes * 5

            for i in range(40):
                await cache.put(f"text-{i}", "model", big_vec, "v1")

            # Without eviction the DB would hold all 40 rows and far exceed the
            # budget. With eviction the stored payload stays bounded.
            cursor = cache.conn.cursor()
            row_count = cursor.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            stored = cursor.execute(
                "SELECT COALESCE(SUM(length(data)), 0) FROM cache"
            ).fetchone()[0]
            cursor.close()

            assert 0 < row_count < 40, f"unexpected row_count after eviction: {row_count}"
            assert stored <= cache.l2_max_size_bytes, (
                f"stored {stored} bytes exceeds budget {cache.l2_max_size_bytes}"
            )

            # A freshly written key survives eviction; older ones are dropped.
            cache.l1_cache.clear()
            assert await cache.get("text-0", "model", "v1") is None
            await cache.shutdown()

        run_async(run())
