"""
Tests for plugins/ollama_module/workflow/__init__.py.
Must mock nexe_flow before importing.
"""

import pytest


class TestOllamaWorkflowInit:
    """Test ollama workflow __init__ module."""

    def test_import_module(self):
        """Test workflow module can be imported."""
        import plugins.ollama_module.workflow as wf_mod
        assert wf_mod is not None

    def test_ollama_node_exported(self):
        """Test OllamaNode is exported."""
        from plugins.ollama_module.workflow import OllamaNode
        assert OllamaNode is not None

    def test_all_exports(self):
        """Test __all__ contains OllamaNode."""
        from plugins.ollama_module.workflow import __all__
        assert "OllamaNode" in __all__
