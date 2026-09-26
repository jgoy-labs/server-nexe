"""#1068: every `workflow_nodes` path a memory MANIFEST declares is a real file.

`memory/memory/constants.py` declared `upload_node` and `commit_node`, which
never existed, while the module's two real nodes went undeclared. Nothing
loads these paths today, so nothing noticed. This checks the declaration
against the tree — reading the constants with `ast`, importing nothing — for
every `memory/*/constants.py`. Whether the manifest should carry the field at
all is a separate question; this only keeps what it says true.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _workflow_nodes(constants: Path) -> list[str] | None:
    tree = ast.parse(constants.read_text(encoding="utf-8"))
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else (
            node.targets[0] if isinstance(node, ast.Assign) else None
        )
        if not (isinstance(target, ast.Name) and target.id == "MANIFEST"):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            if isinstance(key, ast.Constant) and key.value == "workflow_nodes":
                return ast.literal_eval(value)
    return None


def _missing(dotted: str) -> bool:
    rel = Path(*dotted.split("."))
    return not ((ROOT / rel).with_suffix(".py").is_file() or (ROOT / rel / "__init__.py").is_file())


def test_every_declared_workflow_node_exists():
    manifests = sorted(ROOT.glob("memory/*/constants.py"))
    declared = {m: _workflow_nodes(m) for m in manifests}
    declared = {m: nodes for m, nodes in declared.items() if nodes}
    # Not vacuous: today two manifests declare nodes.
    assert len(declared) >= 2, declared
    missing = [
        f"{m.relative_to(ROOT)}: {dotted}"
        for m, nodes in declared.items()
        for dotted in nodes
        if _missing(dotted)
    ]
    assert not missing, "\n".join(missing)
