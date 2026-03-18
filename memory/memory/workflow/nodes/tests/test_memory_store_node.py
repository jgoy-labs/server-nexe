"""
Tests for memory/memory/workflow/nodes/memory_store_node.py.
"""

import sys
import types
import pytest
from dataclasses import dataclass, field
from typing import Any
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


class TestMemoryStoreNodeMetadata:
    """Test MemoryStoreNode metadata."""

    def test_get_metadata(self):
        """Test metadata structure."""
        from memory.memory.workflow.nodes.memory_store_node import MemoryStoreNode
        node = MemoryStoreNode()
        metadata = node.get_metadata()

        assert metadata.id == "memory.store"
        assert metadata.name == "Memory Store"
        assert metadata.category == "nexe_native"
        assert metadata.version == "1.0.0"

    def test_metadata_inputs(self):
        """Test input definitions."""
        from memory.memory.workflow.nodes.memory_store_node import MemoryStoreNode
        node = MemoryStoreNode()
        metadata = node.get_metadata()

        input_names = [inp.name for inp in metadata.inputs]
        assert "content" in input_names
        assert "entry_type" in input_names
        assert "source" in input_names
        assert "ttl_seconds" in input_names

        content_input = next(i for i in metadata.inputs if i.name == "content")
        assert content_input.required is True

    def test_metadata_outputs(self):
        """Test output definitions."""
        from memory.memory.workflow.nodes.memory_store_node import MemoryStoreNode
        node = MemoryStoreNode()
        metadata = node.get_metadata()

        output_names = [out.name for out in metadata.outputs]
        assert "entry_id" in output_names
        assert "success" in output_names


class TestMemoryStoreNodeExecute:
    """Test MemoryStoreNode execution."""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Test successful store."""
        from memory.memory.workflow.nodes.memory_store_node import MemoryStoreNode

        node = MemoryStoreNode()
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._pipeline = MagicMock()
        mock_module._pipeline.ingest = AsyncMock(return_value=True)

        with patch("memory.memory.workflow.nodes.memory_store_node.MemoryModule") as MockMM:
            MockMM.get_instance.return_value = mock_module
            with patch("memory.memory.workflow.nodes.memory_store_node.MemoryEntry") as MockEntry:
                mock_entry = MagicMock()
                mock_entry.id = "entry-123"
                MockEntry.return_value = mock_entry
                result = await node.execute({"content": "test content"})

        assert result["success"] is True
        assert result["entry_id"] == "entry-123"

    @pytest.mark.asyncio
    async def test_execute_empty_content(self):
        """Test with empty content."""
        from memory.memory.workflow.nodes.memory_store_node import MemoryStoreNode

        node = MemoryStoreNode()
        result = await node.execute({"content": ""})
        assert result["success"] is False
        assert result["entry_id"] is None

    @pytest.mark.asyncio
    async def test_execute_whitespace_content(self):
        """Test with whitespace-only content."""
        from memory.memory.workflow.nodes.memory_store_node import MemoryStoreNode

        node = MemoryStoreNode()
        result = await node.execute({"content": "   "})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_execute_none_content(self):
        """Test with None content."""
        from memory.memory.workflow.nodes.memory_store_node import MemoryStoreNode

        node = MemoryStoreNode()
        result = await node.execute({})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_execute_invalid_entry_type(self):
        """Test with invalid entry type falls back to EPISODIC."""
        from memory.memory.workflow.nodes.memory_store_node import MemoryStoreNode

        node = MemoryStoreNode()
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._pipeline = MagicMock()
        mock_module._pipeline.ingest = AsyncMock(return_value=True)

        with patch("memory.memory.workflow.nodes.memory_store_node.MemoryModule") as MockMM:
            MockMM.get_instance.return_value = mock_module
            with patch("memory.memory.workflow.nodes.memory_store_node.MemoryEntry") as MockEntry:
                mock_entry = MagicMock()
                mock_entry.id = "entry-456"
                MockEntry.return_value = mock_entry
                result = await node.execute({
                    "content": "test",
                    "entry_type": "invalid_type"
                })

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_auto_initialize(self):
        """Test auto-initialization."""
        from memory.memory.workflow.nodes.memory_store_node import MemoryStoreNode

        node = MemoryStoreNode()
        mock_module = MagicMock()
        mock_module._initialized = False
        mock_module.initialize = AsyncMock()
        mock_module._pipeline = MagicMock()
        mock_module._pipeline.ingest = AsyncMock(return_value=True)

        with patch("memory.memory.workflow.nodes.memory_store_node.MemoryModule") as MockMM:
            MockMM.get_instance.return_value = mock_module
            with patch("memory.memory.workflow.nodes.memory_store_node.MemoryEntry") as MockEntry:
                mock_entry = MagicMock()
                mock_entry.id = "entry-789"
                MockEntry.return_value = mock_entry
                result = await node.execute({"content": "test"})

        mock_module.initialize.assert_awaited_once()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_no_pipeline(self):
        """Test when pipeline is None after init."""
        from memory.memory.workflow.nodes.memory_store_node import MemoryStoreNode

        node = MemoryStoreNode()
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._pipeline = None

        with patch("memory.memory.workflow.nodes.memory_store_node.MemoryModule") as MockMM:
            MockMM.get_instance.return_value = mock_module
            with patch("memory.memory.workflow.nodes.memory_store_node.MemoryEntry") as MockEntry:
                MockEntry.return_value = MagicMock(id="x")
                result = await node.execute({"content": "test"})

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_execute_ingest_fails(self):
        """Test when ingest returns False."""
        from memory.memory.workflow.nodes.memory_store_node import MemoryStoreNode

        node = MemoryStoreNode()
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._pipeline = MagicMock()
        mock_module._pipeline.ingest = AsyncMock(return_value=False)

        with patch("memory.memory.workflow.nodes.memory_store_node.MemoryModule") as MockMM:
            MockMM.get_instance.return_value = mock_module
            with patch("memory.memory.workflow.nodes.memory_store_node.MemoryEntry") as MockEntry:
                mock_entry = MagicMock()
                mock_entry.id = "entry-dup"
                MockEntry.return_value = mock_entry
                result = await node.execute({"content": "test"})

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_execute_exception(self):
        """Test general exception handling."""
        from memory.memory.workflow.nodes.memory_store_node import MemoryStoreNode

        node = MemoryStoreNode()

        with patch("memory.memory.workflow.nodes.memory_store_node.MemoryModule") as MockMM:
            MockMM.get_instance.side_effect = RuntimeError("crash")
            with patch("memory.memory.workflow.nodes.memory_store_node.MemoryEntry") as MockEntry:
                MockEntry.return_value = MagicMock(id="x")
                result = await node.execute({"content": "test"})

        assert result["success"] is False
        assert result["entry_id"] is None

    @pytest.mark.asyncio
    async def test_execute_with_custom_params(self):
        """Test with custom source and ttl."""
        from memory.memory.workflow.nodes.memory_store_node import MemoryStoreNode

        node = MemoryStoreNode()
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._pipeline = MagicMock()
        mock_module._pipeline.ingest = AsyncMock(return_value=True)

        with patch("memory.memory.workflow.nodes.memory_store_node.MemoryModule") as MockMM:
            MockMM.get_instance.return_value = mock_module
            with patch("memory.memory.workflow.nodes.memory_store_node.MemoryEntry") as MockEntry:
                mock_entry = MagicMock()
                mock_entry.id = "entry-custom"
                MockEntry.return_value = mock_entry

                result = await node.execute({
                    "content": "data",
                    "entry_type": "semantic",
                    "source": "api",
                    "ttl_seconds": 7200
                })

        assert result["success"] is True
