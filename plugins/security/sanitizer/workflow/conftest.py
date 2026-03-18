"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/security/sanitizer/workflow/conftest.py
Description: Conftest per mockejar nexe_flow (no instal·lat) a nivell de workflow.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
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

    nexe_flow = types.ModuleType("nexe_flow")
    nexe_flow_core = types.ModuleType("nexe_flow.core")
    nexe_flow_core_node = types.ModuleType("nexe_flow.core.node")
    nexe_flow_core_node.Node = Node
    nexe_flow_core_node.NodeMetadata = NodeMetadata
    nexe_flow_core_node.NodeInput = NodeInput
    nexe_flow_core_node.NodeOutput = NodeOutput
    nexe_flow.core = nexe_flow_core
    nexe_flow_core.node = nexe_flow_core_node

    sys.modules["nexe_flow"] = nexe_flow
    sys.modules["nexe_flow.core"] = nexe_flow_core
    sys.modules["nexe_flow.core.node"] = nexe_flow_core_node


_create_nexe_flow_mock()
