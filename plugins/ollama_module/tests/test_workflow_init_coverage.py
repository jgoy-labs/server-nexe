"""Tests for plugins/ollama_module/workflow/ __init__ files — coverage."""


class TestOllamaWorkflowInit:
    def test_exports_ollama_node(self):
        from plugins.ollama_module.workflow import OllamaNode, __all__
        assert "OllamaNode" in __all__
        assert OllamaNode is not None


class TestOllamaWorkflowNodesInit:
    def test_exports_ollama_node(self):
        from plugins.ollama_module.workflow.nodes import OllamaNode, __all__
        assert "OllamaNode" in __all__
