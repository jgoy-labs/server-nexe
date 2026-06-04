"""
Tests for memory/memory/workflow/__init__.py.
Must mock nexe_flow before importing workflow modules.
"""

import pytest


class TestWorkflowInit:
    """Test workflow __init__ module."""

    def test_import_module(self):
        """Test workflow module can be imported."""
        import memory.memory.workflow as wf_mod
        assert wf_mod is not None

    def test_memory_store_node_exported(self):
        """Test MemoryStoreNode is exported."""
        from memory.memory.workflow import MemoryStoreNode
        assert MemoryStoreNode is not None

    def test_memory_recall_node_exported(self):
        """Test MemoryRecallNode is exported."""
        from memory.memory.workflow import MemoryRecallNode
        assert MemoryRecallNode is not None

    def test_all_exports(self):
        """Test __all__ contains expected symbols."""
        from memory.memory.workflow import __all__
        assert "MemoryStoreNode" in __all__
        assert "MemoryRecallNode" in __all__
