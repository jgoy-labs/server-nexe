"""Tests for memory/memory/cli/__init__.py — facade coverage."""


class TestCLIInit:
    def test_exports_rag_main(self):
        from memory.memory.cli import rag_main, __all__
        assert "rag_main" in __all__
        assert callable(rag_main)
