"""
Tests for memory/memory/workflow/nodes/memory_recall_node.py.
"""

import sys
import types
import pytest
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock


def _ensure_nexe_flow_mock():
    if "nexe_flow" in sys.modules:
        return
    @dataclass
    class NodeMetadata:
        node_type: str = ""
        id: str = ""
        name: str = ""
        version: str = "1.0.0"
        description: str = ""
        category: str = ""
        inputs: Any = field(default_factory=list)
        outputs: Any = field(default_factory=dict)
        icon: str = ""
        color: str = ""
    @dataclass
    class NodeInput:
        name: str = ""
        type: str = "string"
        required: bool = False
        description: str = ""
        default: Any = None
    @dataclass
    class NodeOutput:
        name: str = ""
        type: str = "string"
        description: str = ""
    class Node:
        def __init__(self): pass
        def get_metadata(self): raise NotImplementedError
        async def execute(self, inputs): raise NotImplementedError
        def validate_inputs(self, inputs):
            metadata = self.get_metadata()
            for inp in metadata.inputs:
                if inp.required and inp.name not in inputs:
                    raise ValueError(f"Missing required input: '{inp.name}'")

    nf = types.ModuleType("nexe_flow")
    nfc = types.ModuleType("nexe_flow.core")
    nfcn = types.ModuleType("nexe_flow.core.node")
    nfcn.Node = Node
    nfcn.NodeMetadata = NodeMetadata
    nfcn.NodeInput = NodeInput
    nfcn.NodeOutput = NodeOutput
    nf.core = nfc
    nfc.node = nfcn
    sys.modules["nexe_flow"] = nf
    sys.modules["nexe_flow.core"] = nfc
    sys.modules["nexe_flow.core.node"] = nfcn

_ensure_nexe_flow_mock()


class TestMemoryRecallNodeMetadata:
    """Test MemoryRecallNode metadata."""

    def test_get_metadata(self):
        """Test metadata structure."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode
        node = MemoryRecallNode()
        metadata = node.get_metadata()

        assert metadata.id == "memory.recall"
        assert metadata.name == "Memory Recall"
        assert metadata.category == "nexe_native"
        assert metadata.version == "1.1.0"

    def test_metadata_inputs(self):
        """Test input definitions."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode
        node = MemoryRecallNode()
        metadata = node.get_metadata()

        input_names = [inp.name for inp in metadata.inputs]
        assert "limit" in input_names
        assert "entry_type" in input_names
        assert "query" in input_names
        assert "person_id" in input_names

    def test_metadata_outputs(self):
        """Test output definitions."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode
        node = MemoryRecallNode()
        metadata = node.get_metadata()

        output_names = [out.name for out in metadata.outputs]
        assert "context" in output_names
        assert "entries" in output_names
        assert "entry_count" in output_names
        assert "source" in output_names


class TestMemoryRecallNodeExecute:
    """Test MemoryRecallNode execution."""

    def _make_entry(self, content="test content", source="test"):
        entry = MagicMock()
        entry.content = content
        entry.source = source
        entry.id = "test-id-123"
        entry.timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        entry.entry_type = "episodic"
        return entry

    @pytest.mark.asyncio
    async def test_execute_from_flash_memory(self):
        """Test recall from FlashMemory."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode

        node = MemoryRecallNode()
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._flash_memory = MagicMock()
        mock_module._flash_memory.get_all = AsyncMock(return_value=[self._make_entry()])
        mock_module._persistence = None

        mock_rag_log = MagicMock()

        with patch("memory.memory.workflow.nodes.memory_recall_node.MemoryModule") as MockMM:
            MockMM.get_instance.return_value = mock_module
            with patch("memory.memory.workflow.nodes.memory_recall_node.get_rag_logger", return_value=mock_rag_log):
                result = await node.execute({"limit": 10, "entry_type": "episodic"})

        assert result["source"] == "flash"
        assert result["entry_count"] == 1
        assert len(result["entries"]) == 1
        assert result["context"] != ""

    @pytest.mark.asyncio
    async def test_execute_auto_initialize(self):
        """Test auto-initialization when module not initialized."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode

        node = MemoryRecallNode()
        mock_module = MagicMock()
        mock_module._initialized = False
        mock_module.initialize = AsyncMock()
        mock_module._flash_memory = MagicMock()
        mock_module._flash_memory.get_all = AsyncMock(return_value=[self._make_entry()])
        mock_module._persistence = None

        mock_rag_log = MagicMock()

        with patch("memory.memory.workflow.nodes.memory_recall_node.MemoryModule") as MockMM:
            MockMM.get_instance.return_value = mock_module
            with patch("memory.memory.workflow.nodes.memory_recall_node.get_rag_logger", return_value=mock_rag_log):
                result = await node.execute({"limit": 5})

        mock_module.initialize.assert_awaited_once()
        assert result["source"] == "flash"

    @pytest.mark.asyncio
    async def test_execute_flash_empty_falls_to_sqlite(self):
        """Test fallback from flash to SQLite."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode

        node = MemoryRecallNode()
        entry = self._make_entry()
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._flash_memory = MagicMock()
        mock_module._flash_memory.get_all = AsyncMock(return_value=[])
        mock_module._flash_memory.store = AsyncMock()
        mock_module._persistence = MagicMock()
        mock_module._persistence.get_recent = AsyncMock(return_value=[entry])

        mock_rag_log = MagicMock()

        with patch("memory.memory.workflow.nodes.memory_recall_node.MemoryModule") as MockMM:
            MockMM.get_instance.return_value = mock_module
            with patch("memory.memory.workflow.nodes.memory_recall_node.get_rag_logger", return_value=mock_rag_log):
                result = await node.execute({"limit": 10, "entry_type": "episodic"})

        assert result["source"] == "sqlite"
        assert result["entry_count"] == 1
        # Should have cached to flash
        mock_module._flash_memory.store.assert_awaited()

    @pytest.mark.asyncio
    async def test_execute_sqlite_no_flash_cache(self):
        """Test SQLite fallback without flash memory available."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode

        node = MemoryRecallNode()
        entry = self._make_entry()
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._flash_memory = None
        mock_module._persistence = MagicMock()
        mock_module._persistence.get_recent = AsyncMock(return_value=[entry])

        mock_rag_log = MagicMock()

        with patch("memory.memory.workflow.nodes.memory_recall_node.MemoryModule") as MockMM:
            MockMM.get_instance.return_value = mock_module
            with patch("memory.memory.workflow.nodes.memory_recall_node.get_rag_logger", return_value=mock_rag_log):
                result = await node.execute({"limit": 10})

        assert result["source"] == "sqlite"

    @pytest.mark.asyncio
    async def test_execute_sqlite_error(self):
        """Test SQLite error handling."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode

        node = MemoryRecallNode()
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._flash_memory = MagicMock()
        mock_module._flash_memory.get_all = AsyncMock(return_value=[])
        mock_module._persistence = MagicMock()
        mock_module._persistence.get_recent = AsyncMock(side_effect=RuntimeError("db error"))

        mock_rag_log = MagicMock()

        with patch("memory.memory.workflow.nodes.memory_recall_node.MemoryModule") as MockMM:
            MockMM.get_instance.return_value = mock_module
            with patch("memory.memory.workflow.nodes.memory_recall_node.get_rag_logger", return_value=mock_rag_log):
                result = await node.execute({"limit": 10, "query": None})

        assert result["source"] == "none"

    @pytest.mark.asyncio
    async def test_execute_qdrant_semantic_search(self):
        """Test Qdrant semantic search path."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode

        node = MemoryRecallNode()
        entry = self._make_entry()
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._flash_memory = MagicMock()
        mock_module._flash_memory.get_all = AsyncMock(return_value=[])
        mock_module._persistence = MagicMock()
        mock_module._persistence.get_recent = AsyncMock(return_value=[])
        mock_module._persistence.search = AsyncMock(return_value=[("id1", 0.9)])
        mock_module._persistence.get = AsyncMock(return_value=entry)

        mock_rag_log = MagicMock()

        with patch("memory.memory.workflow.nodes.memory_recall_node.MemoryModule") as MockMM:
            MockMM.get_instance.return_value = mock_module
            with patch("memory.memory.workflow.nodes.memory_recall_node.get_rag_logger", return_value=mock_rag_log):
                with patch.object(node, "_get_embedding", new_callable=AsyncMock, return_value=[0.1] * 768):
                    result = await node.execute({"limit": 10, "query": "test query"})

        assert result["source"] == "qdrant"
        assert result["entry_count"] == 1

    @pytest.mark.asyncio
    async def test_execute_qdrant_no_embedding(self):
        """Test Qdrant path when embedding fails."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode

        node = MemoryRecallNode()
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._flash_memory = MagicMock()
        mock_module._flash_memory.get_all = AsyncMock(return_value=[])
        mock_module._persistence = MagicMock()
        mock_module._persistence.get_recent = AsyncMock(return_value=[])

        mock_rag_log = MagicMock()

        with patch("memory.memory.workflow.nodes.memory_recall_node.MemoryModule") as MockMM:
            MockMM.get_instance.return_value = mock_module
            with patch("memory.memory.workflow.nodes.memory_recall_node.get_rag_logger", return_value=mock_rag_log):
                with patch.object(node, "_get_embedding", new_callable=AsyncMock, return_value=None):
                    result = await node.execute({"limit": 10, "query": "test"})

        assert result["source"] == "none"

    @pytest.mark.asyncio
    async def test_execute_qdrant_error(self):
        """Test Qdrant error handling."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode

        node = MemoryRecallNode()
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._flash_memory = MagicMock()
        mock_module._flash_memory.get_all = AsyncMock(return_value=[])
        mock_module._persistence = MagicMock()
        mock_module._persistence.get_recent = AsyncMock(return_value=[])

        mock_rag_log = MagicMock()

        with patch("memory.memory.workflow.nodes.memory_recall_node.MemoryModule") as MockMM:
            MockMM.get_instance.return_value = mock_module
            with patch("memory.memory.workflow.nodes.memory_recall_node.get_rag_logger", return_value=mock_rag_log):
                with patch.object(node, "_get_embedding", new_callable=AsyncMock, side_effect=RuntimeError("embed err")):
                    result = await node.execute({"limit": 10, "query": "test"})

        assert result["source"] == "none"

    @pytest.mark.asyncio
    async def test_execute_no_entries_anywhere(self):
        """Test when no entries found in any source."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode

        node = MemoryRecallNode()
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._flash_memory = MagicMock()
        mock_module._flash_memory.get_all = AsyncMock(return_value=[])
        mock_module._persistence = MagicMock()
        mock_module._persistence.get_recent = AsyncMock(return_value=[])

        mock_rag_log = MagicMock()

        with patch("memory.memory.workflow.nodes.memory_recall_node.MemoryModule") as MockMM:
            MockMM.get_instance.return_value = mock_module
            with patch("memory.memory.workflow.nodes.memory_recall_node.get_rag_logger", return_value=mock_rag_log):
                result = await node.execute({})

        assert result["context"] == ""
        assert result["entries"] == []
        assert result["entry_count"] == 0
        assert result["source"] == "none"

    @pytest.mark.asyncio
    async def test_execute_general_exception(self):
        """Test general exception handling."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode

        node = MemoryRecallNode()
        mock_rag_log = MagicMock()

        with patch("memory.memory.workflow.nodes.memory_recall_node.MemoryModule") as MockMM:
            MockMM.get_instance.side_effect = RuntimeError("boom")
            with patch("memory.memory.workflow.nodes.memory_recall_node.get_rag_logger", return_value=mock_rag_log):
                result = await node.execute({})

        assert result["source"] == "error"
        assert result["context"] == ""
        mock_rag_log.recall_error.assert_called_once()


class TestMemoryRecallNodeHelpers:
    """Test helper methods."""

    def test_format_context_empty(self):
        """Test formatting empty entries."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode
        node = MemoryRecallNode()
        assert node._format_context([]) == ""

    def test_format_context_with_entries(self):
        """Test formatting entries."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode
        node = MemoryRecallNode()

        entry = MagicMock()
        entry.timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        entry.content = "short content"

        result = node._format_context([entry])
        assert "[Recent memories]" in result
        assert "short content" in result

    def test_format_context_long_content_truncated(self):
        """Test that long content is truncated."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode
        node = MemoryRecallNode()

        entry = MagicMock()
        entry.timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        entry.content = "x" * 400

        result = node._format_context([entry])
        assert "..." in result

    def test_format_context_no_timestamp(self):
        """Test formatting entry without timestamp."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode
        node = MemoryRecallNode()

        entry = MagicMock()
        entry.timestamp = None
        entry.content = "content"

        result = node._format_context([entry])
        assert "[?]" in result

    def test_entry_to_dict(self):
        """Test entry to dict conversion."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode
        node = MemoryRecallNode()

        entry = MagicMock()
        entry.id = "test-id"
        entry.content = "x" * 300
        entry.source = "test"
        entry.timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        entry.entry_type = "episodic"

        result = node._entry_to_dict(entry)
        assert result["id"] == "test-id"
        assert len(result["content"]) == 200
        assert result["source"] == "test"
        assert result["entry_type"] == "episodic"
        assert result["timestamp"] is not None

    def test_entry_to_dict_no_timestamp(self):
        """Test entry to dict with no timestamp."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode
        node = MemoryRecallNode()

        entry = MagicMock()
        entry.id = "test-id"
        entry.content = "short"
        entry.source = "test"
        entry.timestamp = None
        entry.entry_type = "semantic"

        result = node._entry_to_dict(entry)
        assert result["timestamp"] is None


class TestGetEmbedding:
    """Test _get_embedding method."""

    @pytest.mark.asyncio
    async def test_get_embedding_success(self):
        """Test successful embedding retrieval."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode
        node = MemoryRecallNode()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node._get_embedding("test text")
            assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_get_embedding_non_200(self):
        """Test embedding with non-200 response."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode
        node = MemoryRecallNode()

        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node._get_embedding("test")
            assert result is None

    @pytest.mark.asyncio
    async def test_get_embedding_exception(self):
        """Test embedding with exception."""
        from memory.memory.workflow.nodes.memory_recall_node import MemoryRecallNode
        node = MemoryRecallNode()

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=RuntimeError("network error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node._get_embedding("test")
            assert result is None
