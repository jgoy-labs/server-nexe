"""MC-003: the RAG recall limit was recomputed via psutil.virtual_memory() on
every chat request, even though .total is invariant at runtime. It is now
cached at module level.

F-D block 3 (2026-08-31): the function moved to core.endpoints.chat_rag
(system_rag_limit, public) — /v1 shares it now too, not just the UI route.
"""
from core.endpoints.chat_rag import system_rag_limit


def test_system_rag_limit_is_cached(monkeypatch):
    system_rag_limit.cache_clear()
    import psutil

    calls = {"n": 0}
    real = psutil.virtual_memory

    def counting():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(psutil, "virtual_memory", counting)
    try:
        first = system_rag_limit()
        second = system_rag_limit()
        assert first == second
        assert first in (3, 5)
        assert calls["n"] == 1, f"virtual_memory should be read once, got {calls['n']}"
    finally:
        system_rag_limit.cache_clear()
