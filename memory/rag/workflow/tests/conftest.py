"""
Conftest for memory/rag/workflow tests.
Ensures nexe_flow mock supports json_schema parameter needed by RAGSearchNode.
"""

import sys
import types
from dataclasses import dataclass, field
from typing import Any


def _ensure_nexe_flow_with_json_schema():
    """Create or update nexe_flow mock to support json_schema on NodeInput/NodeOutput."""

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
        config_schema: Any = field(default_factory=dict)

    @dataclass
    class NodeInput:
        name: str = ""
        type: str = "string"
        required: bool = False
        description: str = ""
        default: Any = None
        json_schema: Any = field(default_factory=dict)

    @dataclass
    class NodeOutput:
        name: str = ""
        type: str = "string"
        description: str = ""
        json_schema: Any = field(default_factory=dict)

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

    # Always replace to ensure json_schema support
    nf = sys.modules.get("nexe_flow") or types.ModuleType("nexe_flow")
    nfc = sys.modules.get("nexe_flow.core") or types.ModuleType("nexe_flow.core")
    nfcn = sys.modules.get("nexe_flow.core.node") or types.ModuleType("nexe_flow.core.node")

    nfcn.Node = Node
    nfcn.NodeMetadata = NodeMetadata
    nfcn.NodeInput = NodeInput
    nfcn.NodeOutput = NodeOutput
    nf.core = nfc
    nfc.node = nfcn

    sys.modules["nexe_flow"] = nf
    sys.modules["nexe_flow.core"] = nfc
    sys.modules["nexe_flow.core.node"] = nfcn

    # Force reimport of rag_search_node to pick up updated mock
    rag_mod_key = "memory.rag.workflow.nodes.rag_search_node"
    if rag_mod_key in sys.modules:
        del sys.modules[rag_mod_key]
    # Also clear parent init modules that cache the old import
    for key in list(sys.modules.keys()):
        if key.startswith("memory.rag.workflow.nodes") and key != rag_mod_key:
            if key in sys.modules:
                del sys.modules[key]


_ensure_nexe_flow_with_json_schema()
