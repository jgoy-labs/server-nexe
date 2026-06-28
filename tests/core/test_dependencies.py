"""
Tests for core/dependencies.py

MC-103: the per-IP limiter is now defined IN core (no import from plugins). The
old try/except ImportError fallback (which made `core` depend on
`plugins.security.core.rate_limiting`) is gone, so the tests below assert the
NEW contract instead of the removed fallback behaviour.
"""
import ast
from pathlib import Path


class TestDependenciesContract:
    """MC-103: core defines the limiter itself; no plugins coupling."""

    def test_limiter_and_flag_exposed(self):
        from core.dependencies import ADVANCED_RATE_LIMITING, limiter
        from slowapi import Limiter
        assert isinstance(limiter, Limiter)
        assert isinstance(ADVANCED_RATE_LIMITING, bool)
        # advanced limiters were dead wiring (MC-123/124) → no advanced mode
        assert ADVANCED_RATE_LIMITING is False

    def test_no_module_level_plugins_import(self):
        """core/dependencies.py must not import from plugins at module scope.

        Mutation guard: re-add the old
        `from plugins.security.core.rate_limiting import (...)` at module level
        and this test goes RED.
        """
        import core.dependencies as deps

        tree = ast.parse(Path(deps.__file__).read_text())
        nodes = list(tree.body)
        for n in tree.body:
            if isinstance(n, (ast.Try, ast.If)):
                nodes.extend(n.body)
                for h in getattr(n, "handlers", []):
                    nodes.extend(h.body)
        offenders = [
            node.module
            for node in nodes
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("plugins")
        ]
        assert not offenders, f"core.dependencies imports plugins at module level: {offenders}"

    def test_all_exports_are_the_minimal_contract(self):
        """__all__ no longer advertises the removed advanced limiters."""
        from core.dependencies import __all__
        assert set(__all__) == {"get_i18n", "limiter", "ADVANCED_RATE_LIMITING"}
        for removed in ("limiter_global", "limiter_by_key", "limiter_composite",
                        "limiter_by_endpoint", "rate_limit_tracker",
                        "start_rate_limit_cleanup_task"):
            assert removed not in __all__
