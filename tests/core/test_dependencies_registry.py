"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/tests/test_dependencies_registry.py
Description: Tests per core/dependencies.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest


# ─── Tests dependencies.py ────────────────────────────────────────────────────

class TestDependencies:

    def test_limiter_is_importable(self):
        from core.dependencies import limiter
        assert limiter is not None

    def test_limiter_is_a_slowapi_limiter(self):
        """MC-103: the per-IP limiter is a real slowapi Limiter defined in core."""
        from core.dependencies import limiter
        from slowapi import Limiter
        assert isinstance(limiter, Limiter)

    def test_advanced_rate_limiting_flag(self):
        from core.dependencies import ADVANCED_RATE_LIMITING
        assert isinstance(ADVANCED_RATE_LIMITING, bool)

    def test_all_exports_present(self):
        import core.dependencies as dep
        for name in dep.__all__:
            assert hasattr(dep, name), f"Missing export: {name}"

    def test_dependencies_does_not_import_plugins_at_module_level(self):
        """MC-103: core/dependencies.py must NOT import from plugins at module level
        (that was the core→plugins wrong-direction edge / latent cycle). The per-IP
        limiter is now defined locally in core.

        Mutation guard: re-add `from core.security.rate_limiting import ...`
        at module scope and this test goes RED.
        """
        import ast
        from pathlib import Path
        import core.dependencies as deps

        tree = ast.parse(Path(deps.__file__).read_text())
        offenders = []
        # module-level imports = direct children of the module body, plus those
        # inside a top-level try/if (where the old offending import lived).
        nodes = list(tree.body)
        for n in tree.body:
            if isinstance(n, (ast.Try, ast.If)):
                nodes.extend(n.body)
                for h in getattr(n, "handlers", []):
                    nodes.extend(h.body)
        for node in nodes:
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("plugins"):
                offenders.append(node.module)
        assert not offenders, (
            f"core.dependencies imports plugins at module level: {offenders} (MC-103 cycle)"
        )
