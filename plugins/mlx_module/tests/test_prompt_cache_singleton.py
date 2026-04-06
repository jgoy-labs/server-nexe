"""
Bug 19 — get_prompt_cache_manager() singleton sense lock.
N threads que el criden simultaniament han de rebre la MATEIXA instancia.
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
    """Reset el singleton abans/despres de cada test."""
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
            # Sincronitzar tots els threads perque arribin alhora a la
            # crida — maximitza la probabilitat de race condition.
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
        # Tots els threads han de tenir EXACTAMENT la mateixa instancia
        for inst in results:
            assert inst is first, "Race condition: dues instancies del singleton"

    def test_repeated_calls_return_same_instance(self):
        a = get_prompt_cache_manager()
        b = get_prompt_cache_manager()
        c = get_prompt_cache_manager(max_size=99)  # max_size ignorat el 2on cop
        assert a is b is c

    def test_singleton_lock_exists(self):
        """Sanity: el module ha d'exposar _singleton_lock (Bug 19 fix)."""
        assert hasattr(pcm_mod, "_singleton_lock")
        assert isinstance(pcm_mod._singleton_lock, type(threading.Lock()))
