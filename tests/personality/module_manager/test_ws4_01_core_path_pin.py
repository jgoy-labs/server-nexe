"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/personality/module_manager/test_ws4_01_core_path_pin.py
Description: WS4-01 — core-module trust is (name, canonical path), not name
alone. A plugin directory merely named like a core module must not be
auto-approved by the allowlist.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from personality.module_manager.core_modules import (
    get_core_modules,
    is_core_module_at,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class TestIsCoreModuleAt:
    def test_canonical_paths_pass(self):
        for name, rel in [
            ("security", "plugins/security"),
            ("ollama_module", "plugins/ollama_module"),
            ("rag", "memory/rag"),
            ("embeddings", "memory/embeddings"),
            ("memory", "memory/memory"),
            ("cli", "core/cli"),
        ]:
            assert is_core_module_at(name, PROJECT_ROOT / rel, PROJECT_ROOT), name

    def test_impersonator_path_rejected(self):
        # A directory NAMED like a core module but living elsewhere
        assert not is_core_module_at("memory", PROJECT_ROOT / "plugins" / "memory", PROJECT_ROOT)
        assert not is_core_module_at("security", PROJECT_ROOT / "plugins" / "core" / "security", PROJECT_ROOT)
        assert not is_core_module_at("cli", PROJECT_ROOT / "storage" / "cli", PROJECT_ROOT)

    def test_unknown_name_rejected(self):
        assert not is_core_module_at("mlx_module", PROJECT_ROOT / "plugins" / "mlx_module", PROJECT_ROOT)

    def test_fails_closed_on_missing_inputs(self):
        assert not is_core_module_at("memory", None, PROJECT_ROOT)
        assert not is_core_module_at("memory", PROJECT_ROOT / "memory" / "memory", None)

    def test_path_outside_root_rejected(self):
        assert not is_core_module_at("memory", "/tmp/evil/memory", PROJECT_ROOT)

    def test_ghost_modules_pruned(self):
        # B041: names that do not ship with the repo carry no core trust
        ghosts = {
            "observability", "workflow_engine", "ui_control_center",
            "demo_module", "system_testing", "auto_clean",
            "tool_manager", "monitor_system",
        }
        assert ghosts.isdisjoint(get_core_modules())
        assert get_core_modules() == {
            "security", "ollama_module", "rag", "embeddings", "memory", "cli",
        }


class TestCheckPluginSecurityPathPin:
    """Exercise _check_plugin_security end to end with a fake context."""

    def _run_check(self, module_name, module_path, approved=frozenset()):
        from personality.module_manager.plugin_loader import PluginLoaderMixin

        loader = PluginLoaderMixin()
        internal = get_core_modules()
        ctx = SimpleNamespace(
            app=MagicMock(),
            module_name=module_name,
            module_info=SimpleNamespace(
                path=module_path, enabled=True, state=None,
            ),
            allowlist_config={
                'approved_modules': set(approved),
                'internal_modules': internal,
                'effective_allowlist': set(approved) | internal,
                'core_env': 'production',
                'project_root': PROJECT_ROOT,
            },
        )
        return loader._check_plugin_security(ctx), ctx

    def test_core_module_at_canonical_path_passes(self):
        ok, _ = self._run_check("memory", PROJECT_ROOT / "memory" / "memory")
        assert ok

    def test_impersonator_named_like_core_is_rejected(self):
        ok, ctx = self._run_check("memory", PROJECT_ROOT / "plugins" / "memory")
        assert not ok
        assert ctx.module_info.enabled is False

    def test_operator_approved_module_passes_regardless_of_path(self):
        ok, _ = self._run_check(
            "mlx_module", PROJECT_ROOT / "plugins" / "mlx_module",
            approved={"mlx_module"},
        )
        assert ok

    def test_unapproved_non_core_rejected(self):
        ok, ctx = self._run_check("hacker_module", PROJECT_ROOT / "plugins" / "hacker_module")
        assert not ok
        assert ctx.module_info.enabled is False
