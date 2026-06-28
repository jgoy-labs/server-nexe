"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_mc102_103_layering.py
Description: Dedicated guards for the MC-102 / MC-103 de-coupling work.

MC-102: ServerState was extracted to the dependency-free leaf core/server_state.py
        so memory/plugins no longer import the heavy startup module to read state.
MC-103: the per-IP limiter is defined IN core (no import from plugins).
Gate fix: check_layering ignores `if TYPE_CHECKING:` blocks (type-only imports are
          not runtime coupling).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import ast
import importlib.util
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


class TestMC102ServerStateLeaf:

    def test_singleton_is_shared_with_lifespan(self):
        """core.lifespan re-exports the SAME singleton (identity preserved)."""
        import core.server_state as ss
        import core.lifespan as lf
        assert lf.server_state is ss.server_state
        assert lf.ServerState is ss.ServerState
        assert lf.get_server_state() is ss.get_server_state()
        assert ss.get_server_state() is ss.server_state

    def test_server_state_is_a_runtime_leaf(self):
        """core/server_state.py must not import memory/plugins/personality at
        RUNTIME (module scope). The APIIntegrator type lives under TYPE_CHECKING,
        which never executes — so it must NOT appear as a runtime import.

        Mutation guard: move the APIIntegrator import out of the TYPE_CHECKING
        block (to module scope) and this goes RED.
        """
        import core.server_state as ss
        tree = ast.parse(Path(ss.__file__).read_text())
        runtime_modules: list[str] = []
        for node in tree.body:  # module body only; if TYPE_CHECKING is an ast.If, skipped
            if isinstance(node, ast.ImportFrom) and node.module:
                runtime_modules.append(node.module)
            elif isinstance(node, ast.Import):
                runtime_modules.extend(a.name for a in node.names)
        leaked = [m for m in runtime_modules if m.split(".")[0] in ("memory", "plugins", "personality")]
        assert not leaked, f"core/server_state.py is not a leaf — leaks runtime imports: {leaked}"

    def test_memory_module_imports_leaf_not_lifespan(self):
        """memory/memory/module.py must pull get_server_state from the leaf
        (core.server_state), NOT from core.lifespan (the latent-cycle edge).

        Mutation guard: repoint the import back to core.lifespan → RED.
        """
        src = (_REPO / "memory" / "memory" / "module.py").read_text()
        tree = ast.parse(src)
        targets = [n.module for n in ast.walk(tree)
                   if isinstance(n, ast.ImportFrom) and n.module]
        assert "core.server_state" in targets
        assert "core.lifespan" not in targets, (
            "memory.module must not import core.lifespan (MC-102 latent cycle)"
        )


class TestLayeringGateIgnoresTypeChecking:
    """The check_layering gate must not count `if TYPE_CHECKING:` imports as
    runtime cross-package edges (MC-102 gate fix), while still counting a real
    top-level conditional import."""

    def _collector(self):
        spec = importlib.util.spec_from_file_location(
            "_check_layering", _REPO / "scripts" / "check_layering.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._ImportTimeCollector

    def test_type_checking_import_not_counted(self):
        Collector = self._collector()
        src = (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from personality.integration import APIIntegrator\n"
            "import os\n"
        )
        c = Collector()
        c.visit(ast.parse(src))
        assert "personality.integration" not in c.modules
        assert "os" in c.modules  # real runtime import is still counted

    def test_real_conditional_import_still_counted(self):
        """A non-TYPE_CHECKING top-level `if` import IS runtime coupling → counted."""
        Collector = self._collector()
        src = (
            "import sys\n"
            "if sys.platform == 'darwin':\n"
            "    import json\n"
        )
        c = Collector()
        c.visit(ast.parse(src))
        assert "json" in c.modules
