"""Tests for memory/memory/tools/__init__.py — facade coverage."""


class TestToolsInit:
    def test_exports_qdrant_adapter(self):
        from memory.memory.tools import QdrantAdapter
        assert QdrantAdapter is not None

    def test_exports_qdrant_config(self):
        from memory.memory.tools import QdrantConfig
        assert QdrantConfig is not None

    def test_all_exports(self):
        from memory.memory.tools import __all__
        assert "QdrantAdapter" in __all__
        assert "QdrantConfig" in __all__
