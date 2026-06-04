"""
Tests for plugins/ollama_module/workflow/nodes/__init__.py.
Must mock nexe_flow before importing.
"""

import pytest


class TestOllamaNodesInit:
    """Test ollama workflow nodes __init__ module."""

    def test_import_module(self):
        """Test nodes module can be imported."""
        import plugins.ollama_module.workflow.nodes as nodes_mod
        assert nodes_mod is not None

    def test_ollama_node_exported(self):
        """Test OllamaNode is exported."""
        from plugins.ollama_module.workflow.nodes import OllamaNode
        assert OllamaNode is not None

    def test_all_exports(self):
        """Test __all__ contains OllamaNode."""
        from plugins.ollama_module.workflow.nodes import __all__
        assert "OllamaNode" in __all__
