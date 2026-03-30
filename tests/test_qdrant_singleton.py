"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_qdrant_singleton.py
Description: Verify singleton prevents concurrent access errors.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import threading
import pytest
from core.qdrant_pool import get_qdrant_client, close_qdrant_client, _lock


def test_singleton_returns_same_instance(tmp_path):
    """Dues crides amb el mateix path retornen el mateix objecte."""
    import core.qdrant_pool as pool
    pool._instances.clear()  # Reset
    try:
        p = str(tmp_path / "qdrant-test")
        c1 = get_qdrant_client(path=p)
        c2 = get_qdrant_client(path=p)
        assert c1 is c2
    finally:
        close_qdrant_client()


def test_singleton_thread_safe(tmp_path):
    """10 threads concurrents obtenen el mateix objecte."""
    import core.qdrant_pool as pool
    pool._instances.clear()  # Reset
    try:
        p = str(tmp_path / "qdrant-thread")
        results = []
        def get_client():
            c = get_qdrant_client(path=p)
            results.append(id(c))
        threads = [threading.Thread(target=get_client) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert len(set(results)) == 1  # Tots el mateix objecte
    finally:
        close_qdrant_client()
