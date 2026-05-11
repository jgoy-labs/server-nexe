"""
Tests for plugins/ollama_module/workflow/nodes/__init__.py.
Must mock nexe_flow before importing.
"""

import sys
import types
import pytest
from dataclasses import dataclass, field
from typing import Any


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
