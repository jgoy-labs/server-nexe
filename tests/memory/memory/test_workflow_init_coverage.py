"""Tests for memory/memory/workflow/ __init__ files — facade coverage."""


class TestWorkflowInit:
    def test_exports_store_node(self):
        from memory.memory.workflow import MemoryStoreNode
        assert MemoryStoreNode is not None

    def test_exports_recall_node(self):
        from memory.memory.workflow import MemoryRecallNode
        assert MemoryRecallNode is not None

    def test_all_exports(self):
        from memory.memory.workflow import __all__
        assert "MemoryStoreNode" in __all__
        assert "MemoryRecallNode" in __all__


class TestWorkflowNodesInit:
    def test_exports(self):
        from memory.memory.workflow.nodes import MemoryStoreNode, MemoryRecallNode, __all__
        assert MemoryStoreNode is not None
        assert MemoryRecallNode is not None
        assert "MemoryStoreNode" in __all__
        assert "MemoryRecallNode" in __all__
