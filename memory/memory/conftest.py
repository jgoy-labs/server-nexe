"""
Conftest for memory.memory tests.
Mocks nexe_flow and qdrant before modules try to import them.
"""

import sys
import types
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock


# Mock qdrant submodule for tools package
def _create_qdrant_mock():
    qdrant_key = "memory.memory.tools.qdrant"
    if qdrant_key not in sys.modules:
        mock_qdrant = types.ModuleType(qdrant_key)
        mock_qdrant.QdrantAdapter = type("QdrantAdapter", (), {})
        mock_qdrant.QdrantConfig = type("QdrantConfig", (), {})
        sys.modules[qdrant_key] = mock_qdrant

_create_qdrant_mock()


def _create_nexe_flow_mock():
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
        def __init__(self):
            pass
        def get_metadata(self):
            raise NotImplementedError
        async def execute(self, inputs):
            raise NotImplementedError
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


_create_nexe_flow_mock()
