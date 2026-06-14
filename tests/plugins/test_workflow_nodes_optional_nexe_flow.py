"""
────────────────────────────────────
Server Nexe
Location: tests/plugins/test_workflow_nodes_optional_nexe_flow.py
Description: A-003 / A-004 regression — workflow node modules must import
cleanly on a real install where the (not-yet-shipped) nexe_flow package is
absent, degrading the node classes to None instead of raising ImportError.

The project conftest installs a mock nexe_flow in sys.modules so the normal
suite exercises the happy path. These tests simulate the *real install* by
temporarily removing the mock and blocking any (re)import of nexe_flow, then
re-importing the node module from scratch.
────────────────────────────────────
"""

import builtins
import importlib
import sys

import pytest


class _BlockNexeFlow:
    """Context manager: remove the nexe_flow mock and make importing it fail.

    Mirrors a real installation that never shipped nexe_flow. Restores the
    previous module-cache + import hook on exit so other tests keep their mock.
    """

    def __init__(self, *target_modules: str):
        self._target_modules = target_modules
        self._saved_modules: dict = {}
        self._real_import = builtins.__import__

    def __enter__(self):
        # Snapshot + drop any nexe_flow.* and the target node modules so they
        # are re-imported fresh under the blocked import hook.
        for name in list(sys.modules):
            if name == "nexe_flow" or name.startswith("nexe_flow."):
                self._saved_modules[name] = sys.modules.pop(name)
        for name in self._target_modules:
            if name in sys.modules:
                self._saved_modules[name] = sys.modules.pop(name)

        real_import = self._real_import

        def _guarded_import(name, *args, **kwargs):
            if name == "nexe_flow" or name.startswith("nexe_flow."):
                raise ImportError("nexe_flow is not installed (simulated)")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = _guarded_import
        return self

    def __exit__(self, *exc):
        builtins.__import__ = self._real_import
        # Drop anything imported while the block was active, then restore the
        # original (mocked) modules so the rest of the suite is unaffected.
        for name in self._target_modules:
            sys.modules.pop(name, None)
        for name in list(sys.modules):
            if name == "nexe_flow" or name.startswith("nexe_flow."):
                sys.modules.pop(name, None)
        sys.modules.update(self._saved_modules)
        return False


def test_ollama_node_imports_without_nexe_flow():
    """A-003: ollama_node imports and OllamaNode degrades to None when nexe_flow
    is absent (instead of raising ImportError)."""
    mod_name = "plugins.ollama_module.workflow.nodes.ollama_node"
    with _BlockNexeFlow(mod_name):
        mod = importlib.import_module(mod_name)
        assert mod.NEXE_FLOW_AVAILABLE is False
        assert mod.OllamaNode is None
        # nexe_flow-independent helpers must still be usable.
        with pytest.raises(ValueError):
            mod.validate_ollama_model("definitely-not-allowed-model")


def test_ollama_workflow_package_imports_without_nexe_flow():
    """A-003: importing the workflow subpackage must not crash when nexe_flow
    is absent (the __init__ re-export of OllamaNode must tolerate None)."""
    targets = (
        "plugins.ollama_module.workflow",
        "plugins.ollama_module.workflow.nodes",
        "plugins.ollama_module.workflow.nodes.ollama_node",
    )
    with _BlockNexeFlow(*targets):
        pkg = importlib.import_module("plugins.ollama_module.workflow")
        assert pkg.OllamaNode is None


def test_sanitizer_node_imports_without_nexe_flow():
    """A-004: sanitizer_node imports and SanitizerNode degrades to None when
    nexe_flow is absent (instead of raising ImportError)."""
    mod_name = "plugins.security.sanitizer.workflow.nodes.sanitizer_node"
    with _BlockNexeFlow(mod_name):
        mod = importlib.import_module(mod_name)
        assert mod.NEXE_FLOW_AVAILABLE is False
        assert mod.SanitizerNode is None
        # The config dataclass does not depend on nexe_flow.
        assert mod.SanitizerNodeConfig().fail_on_critical is False


def test_intervention_node_imports_without_nexe_flow():
    """B130: intervention_node imports and InterventionNode degrades to a None
    sentinel when nexe_flow is absent (instead of raising ModuleNotFoundError).
    RESISTANCE_RESPONSE is nexe_flow-independent and must stay importable."""
    mod_name = "plugins.security.sanitizer.workflow.nodes.intervention_node"
    with _BlockNexeFlow(mod_name):
        mod = importlib.import_module(mod_name)
        assert mod.NEXE_FLOW_AVAILABLE is False
        assert mod.InterventionNode is None
        assert isinstance(mod.RESISTANCE_RESPONSE, str)
