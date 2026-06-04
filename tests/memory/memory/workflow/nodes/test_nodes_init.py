"""
Tests for memory/memory/workflow/nodes/__init__.py.
Must mock nexe_flow before importing.
"""

import pytest


class TestNodesInit:
    """Test workflow nodes __init__ module."""

    def test_import_module(self):
        """Test nodes module can be imported."""
        import memory.memory.workflow.nodes as nodes_mod
        assert nodes_mod is not None

    def test_memory_store_node_exported(self):
        """Test MemoryStoreNode is exported."""
        from memory.memory.workflow.nodes import MemoryStoreNode
        assert MemoryStoreNode is not None

    def test_memory_recall_node_exported(self):
        """Test MemoryRecallNode is exported."""
        from memory.memory.workflow.nodes import MemoryRecallNode
        assert MemoryRecallNode is not None

    def test_all_exports(self):
        """Test __all__ contains expected symbols."""
        from memory.memory.workflow.nodes import __all__
        assert "MemoryStoreNode" in __all__
        assert "MemoryRecallNode" in __all__
