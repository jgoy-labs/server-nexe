"""
Conftest for ollama_module tests.
Mocks nexe_flow before workflow modules try to import it.
"""

import sys
import types
from dataclasses import dataclass, field
from typing import Any


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
    # Dynamic stub injection — ModuleType attributes are set at runtime.
    nfcn.Node = Node  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
    nfcn.NodeMetadata = NodeMetadata  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
    nfcn.NodeInput = NodeInput  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
    nfcn.NodeOutput = NodeOutput  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
    nf.core = nfc  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
    nfc.node = nfcn  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]

    sys.modules["nexe_flow"] = nf
    sys.modules["nexe_flow.core"] = nfc
    sys.modules["nexe_flow.core.node"] = nfcn


_create_nexe_flow_mock()
