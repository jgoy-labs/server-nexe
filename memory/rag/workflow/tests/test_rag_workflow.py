"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: memory/rag/workflow/tests/test_rag_workflow.py
Description: Tests per memory/rag/workflow/ (registry i __init__).

www.jgoy.net
────────────────────────────────────
"""

import pytest
from unittest.mock import MagicMock


class TestRAGWorkflowRegistry:

    def test_registry_module_importable(self):
        from memory.rag.workflow import registry
        assert registry is not None

    def test_register_rag_nodes_callable(self):
        from memory.rag.workflow.registry import register_rag_nodes
        assert callable(register_rag_nodes)

    def test_register_rag_nodes_runs(self):
        # Already called at import time, calling again should not raise
        from memory.rag.workflow.registry import register_rag_nodes
        register_rag_nodes()

    def test_workflow_module_importable(self):
        import memory.rag.workflow
        assert memory.rag.workflow is not None


class TestRAGWorkflowNodesInit:

    def test_nodes_init_importable(self):
        import memory.rag.workflow.nodes
        assert memory.rag.workflow.nodes is not None

    def test_all_attribute_is_list(self):
        import memory.rag.workflow.nodes
        assert isinstance(memory.rag.workflow.nodes.__all__, list)
