"""
Tests for memory/rag/workflow/nodes/rag_search_node.py
Covers: __init__, _init_rag_source, execute, validate_config, get_metadata
"""

import asyncio
import sys
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestRAGSearchNodeInit:
    """Tests for RAGSearchNode construction."""

    def test_create_node(self):
        from memory.rag.workflow.nodes.rag_search_node import RAGSearchNode
        node = RAGSearchNode()
        assert node._rag_source is None
        assert node.config == {}

    def test_get_metadata(self):
        from memory.rag.workflow.nodes.rag_search_node import RAGSearchNode
        node = RAGSearchNode()
        meta = node.get_metadata()
        assert meta.id == "rag.search"
        assert meta.name == "RAG Search"
        assert meta.version == "1.0.0"
        assert meta.category == "llm"
        assert len(meta.inputs) == 1
        assert meta.inputs[0].name == "query"
        assert meta.inputs[0].required is True
        assert len(meta.outputs) == 4
        output_names = [o.name for o in meta.outputs]
        assert "prompt" in output_names
        assert "context" in output_names
        assert "results" in output_names
        assert "num_results" in output_names


class TestInitRagSource:
    """Tests for _init_rag_source method."""

    def test_rag_not_available_raises(self):
        from memory.rag.workflow.nodes.rag_search_node import RAGSearchNode
        node = RAGSearchNode()
        with patch("memory.rag.workflow.nodes.rag_search_node.RAG_AVAILABLE", False):
            with pytest.raises(RuntimeError):
                node._init_rag_source()

    def test_rag_source_init_success(self):
        from memory.rag.workflow.nodes import rag_search_node
        node = rag_search_node.RAGSearchNode()
        node.config = {"source": "my-docs", "index_name": "documents"}
        mock_source = MagicMock()
        original_frs = getattr(rag_search_node, 'FileRAGSource', None)
        try:
            rag_search_node.FileRAGSource = MagicMock(return_value=mock_source)
            with patch.object(rag_search_node, "RAG_AVAILABLE", True):
                result = node._init_rag_source()
                assert result is mock_source
                assert node._rag_source is mock_source
        finally:
            if original_frs is not None:
                rag_search_node.FileRAGSource = original_frs

    def test_rag_source_init_failure(self):
        from memory.rag.workflow.nodes import rag_search_node
        node = rag_search_node.RAGSearchNode()
        original_frs = getattr(rag_search_node, 'FileRAGSource', None)
        try:
            rag_search_node.FileRAGSource = MagicMock(side_effect=Exception("init failed"))
            with patch.object(rag_search_node, "RAG_AVAILABLE", True):
                with pytest.raises(RuntimeError):
                    node._init_rag_source()
        finally:
            if original_frs is not None:
                rag_search_node.FileRAGSource = original_frs

    def test_rag_source_reused_if_already_set(self):
        from memory.rag.workflow.nodes.rag_search_node import RAGSearchNode
        node = RAGSearchNode()
        existing = MagicMock()
        node._rag_source = existing
        with patch("memory.rag.workflow.nodes.rag_search_node.RAG_AVAILABLE", True):
            result = node._init_rag_source()
            assert result is existing


class TestExecute:
    """Tests for RAGSearchNode.execute()."""

    def test_execute_missing_query_raises(self):
        from memory.rag.workflow.nodes.rag_search_node import RAGSearchNode
        node = RAGSearchNode()

        async def run():
            with pytest.raises(ValueError):
                await node.execute({"query": ""})

        asyncio.run(run())

    def test_execute_missing_query_key_raises(self):
        from memory.rag.workflow.nodes.rag_search_node import RAGSearchNode
        node = RAGSearchNode()

        async def run():
            with pytest.raises(ValueError):
                await node.execute({})

        asyncio.run(run())

    def test_execute_success_with_results(self):
        from memory.rag.workflow.nodes.rag_search_node import RAGSearchNode
        node = RAGSearchNode()
        node.config = {"top_k": 3, "score_threshold": 0.5, "prompt_template": "Context:\n{context}\n\nQuestion: {query}"}

        mock_source = MagicMock()
        mock_source.search = AsyncMock(return_value=[
            {"text": "Document text 1", "score": 0.9, "metadata": {"file_path": "file1.md"}},
            {"text": "Document text 2", "score": 0.7, "metadata": {"file_path": "file2.md"}},
        ])

        mock_search_request_cls = MagicMock()

        async def run():
            with patch.object(node, "_init_rag_source", return_value=mock_source), \
                 patch.dict("sys.modules", {"memory.rag_sources.base": MagicMock(SearchRequest=mock_search_request_cls)}):
                result = await node.execute({"query": "test query"})
                assert "prompt" in result
                assert "context" in result
                assert "results" in result
                assert result["num_results"] == 2
                assert "test query" in result["prompt"]
                assert "Document text 1" in result["context"]

        asyncio.run(run())

    def test_execute_no_results(self):
        from memory.rag.workflow.nodes.rag_search_node import RAGSearchNode
        node = RAGSearchNode()
        node.config = {}

        mock_source = MagicMock()
        mock_source.search = AsyncMock(return_value=[])
        mock_search_request_cls = MagicMock()

        async def run():
            with patch.object(node, "_init_rag_source", return_value=mock_source), \
                 patch.dict("sys.modules", {"memory.rag_sources.base": MagicMock(SearchRequest=mock_search_request_cls)}):
                result = await node.execute({"query": "no results query"})
                assert result["num_results"] == 0
                assert isinstance(result["context"], str)

        asyncio.run(run())

    def test_execute_search_failure(self):
        from memory.rag.workflow.nodes.rag_search_node import RAGSearchNode
        node = RAGSearchNode()
        node.config = {}

        async def run():
            with patch.object(node, "_init_rag_source", side_effect=RuntimeError("Search failed")):
                with pytest.raises(RuntimeError):
                    await node.execute({"query": "failing query"})

        asyncio.run(run())


class TestValidateConfig:
    """Tests for RAGSearchNode.validate_config()."""

    def test_valid_config(self):
        from memory.rag.workflow.nodes.rag_search_node import RAGSearchNode
        node = RAGSearchNode()
        node.config = {"top_k": 5, "score_threshold": 0.7, "prompt_template": "Context:\n{context}\n\nQuestion: {query}"}
        assert node.validate_config() is True

    def test_top_k_too_low(self):
        from memory.rag.workflow.nodes.rag_search_node import RAGSearchNode
        node = RAGSearchNode()
        node.config = {"top_k": 0}
        with pytest.raises(ValueError):
            node.validate_config()

    def test_score_threshold_out_of_range(self):
        from memory.rag.workflow.nodes.rag_search_node import RAGSearchNode
        node = RAGSearchNode()
        node.config = {"top_k": 5, "score_threshold": 1.5}
        with pytest.raises(ValueError):
            node.validate_config()

    def test_score_threshold_negative(self):
        from memory.rag.workflow.nodes.rag_search_node import RAGSearchNode
        node = RAGSearchNode()
        node.config = {"top_k": 5, "score_threshold": -0.1}
        with pytest.raises(ValueError):
            node.validate_config()

    def test_missing_context_placeholder(self):
        from memory.rag.workflow.nodes.rag_search_node import RAGSearchNode
        node = RAGSearchNode()
        node.config = {"top_k": 5, "score_threshold": 0.7, "prompt_template": "No context here {query}"}
        with pytest.raises(ValueError):
            node.validate_config()

    def test_missing_query_placeholder(self):
        from memory.rag.workflow.nodes.rag_search_node import RAGSearchNode
        node = RAGSearchNode()
        node.config = {"top_k": 5, "score_threshold": 0.7, "prompt_template": "Context:\n{context}\n\nNo query"}
        with pytest.raises(ValueError):
            node.validate_config()

    def test_default_config_valid(self):
        from memory.rag.workflow.nodes.rag_search_node import RAGSearchNode
        node = RAGSearchNode()
        node.config = {}
        assert node.validate_config() is True
