"""Tests for memory/rag/workflow/ __init__ files — facade coverage."""


class TestRAGWorkflowInit:
    def test_import_succeeds(self):
        import memory.rag.workflow as wf
        assert hasattr(wf, '__all__')

    def test_nodes_init_import(self):
        import memory.rag.workflow.nodes as nodes
        assert hasattr(nodes, '__all__')


class TestRAGWorkflowRegistry:
    def test_registry_imported(self):
        from memory.rag.workflow import registry
        assert hasattr(registry, 'register_rag_nodes')
