"""MC-003: the RAG recall limit was recomputed via psutil.virtual_memory() on
every chat request, even though .total is invariant at runtime. It is now
cached at module level.
"""
import plugins.web_ui_module.api.routes_chat as rc


def test_system_rag_limit_is_cached(monkeypatch):
    rc._system_rag_limit.cache_clear()
    import psutil

    calls = {"n": 0}
    real = psutil.virtual_memory

    def counting():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(psutil, "virtual_memory", counting)
    try:
        first = rc._system_rag_limit()
        second = rc._system_rag_limit()
        assert first == second
        assert first in (3, 5)
        assert calls["n"] == 1, f"virtual_memory should be read once, got {calls['n']}"
    finally:
        rc._system_rag_limit.cache_clear()
