"""
Bug 19 — get_prompt_cache_manager() singleton without a lock.
N threads calling it simultaneously must receive the SAME instance.
"""
import threading
import pytest

import plugins.mlx_module.core.prompt_cache_manager as pcm_mod
from plugins.mlx_module.core.prompt_cache_manager import (
    get_prompt_cache_manager,
    MLXPromptCacheManager,
)


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the singleton before/after each test."""
    pcm_mod._prompt_cache_manager = None
    yield
    pcm_mod._prompt_cache_manager = None


class TestSingletonThreadSafety:

    def test_concurrent_threads_get_same_instance(self):
        N = 50
        results = []
        lock = threading.Lock()
        barrier = threading.Barrier(N)

        def worker():
            # Synchronize all threads so they arrive at the call at the same time
            # — maximizes the probability of a race condition.
            barrier.wait()
            instance = get_prompt_cache_manager()
            with lock:
                results.append(instance)

        threads = [threading.Thread(target=worker) for _ in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == N
        first = results[0]
        assert isinstance(first, MLXPromptCacheManager)
        # All threads must have EXACTLY the same instance
        for inst in results:
            assert inst is first, "Race condition: two singleton instances"

    def test_repeated_calls_return_same_instance(self):
        a = get_prompt_cache_manager()
        b = get_prompt_cache_manager()
        c = get_prompt_cache_manager(max_size=99)  # max_size ignored on the 2nd call
        assert a is b is c

    def test_singleton_lock_exists(self):
        """Sanity: the module must expose _singleton_lock (Bug 19 fix)."""
        assert hasattr(pcm_mod, "_singleton_lock")
        assert isinstance(pcm_mod._singleton_lock, type(threading.Lock()))
