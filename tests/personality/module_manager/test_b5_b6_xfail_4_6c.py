"""
TDD xfail — Onada 4.6c: B5 (get_health hasattr guard) + B6 (stop_module state ERROR)
"""
import asyncio
import importlib
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from personality.data.models import ModuleInfo, ModuleState
from personality.module_manager.types import LifecycleConfig


# ────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ────────────────────────────────────────────────────────────────────────────

def _make_module_info(name, state=ModuleState.DISCOVERED, enabled=True):
    return ModuleInfo(
        name=name,
        path=Path(f"/fake/{name}"),
        manifest_path=Path(f"/fake/{name}/manifest.toml"),
        state=state,
        enabled=enabled,
    )


@pytest.fixture
def lm():
    from personality.module_manager.module_lifecycle import ModuleLifecycleManager
    modules = {}
    loader = MagicMock()
    loader.load_module = AsyncMock(return_value=MagicMock())
    loader.unload_module = AsyncMock()
    registry = MagicMock()
    events = MagicMock()
    events.emit_event = AsyncMock()
    metrics = MagicMock()
    return ModuleLifecycleManager(LifecycleConfig(
        modules=modules, loader=loader, registry=registry,
        events=events, metrics=metrics,
    ))


@pytest.fixture
def mm(tmp_path):
    config_file = tmp_path / "personality" / "server.toml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(
        '[meta]\nversion = "0.8"\n[personality]\n[personality.orchestrator]\nmodules_path = "plugins"\n'
    )
    with patch("personality.module_manager.module_manager.SECURITY_VALIDATION_AVAILABLE", False):
        from personality.module_manager.module_manager import ModuleManager
        return ModuleManager(config_path=config_file)


# ────────────────────────────────────────────────────────────────────────────
# B5 — get_health without hasattr guard
# ────────────────────────────────────────────────────────────────────────────

class TestB5GetHealthHashattrGuard:

    def test_b5_module_without_get_health_is_registered(self, mm, tmp_path):
        """xfail: module without get_health() should register with default health.

        Current bug: AttributeError is caught by except Exception → continue →
        module does not appear in loaded_modules. Post-fix with hasattr guard, the module
        registers with {"status": "ok", "note": "module without get_health()"}.
        """
        mem_path = tmp_path / "memory" / "embeddings"
        mem_path.mkdir(parents=True)
        (mem_path / "manifest.py").touch()

        class FakeEmbeddingsModule:
            """Module without get_health — simulates B5."""

            @classmethod
            def get_instance(cls):
                return cls()

            async def initialize(self, config=None):
                return True

            # get_health() deliberately absent

        fake_manifest = MagicMock()
        fake_manifest.MODULE_ID = "test_embeddings_id"

        fake_module_py = MagicMock()
        fake_module_py.EmbeddingsModule = FakeEmbeddingsModule

        def _fake_import(name):
            if name == "memory.embeddings.manifest":
                return fake_manifest
            if name == "memory.embeddings.module":
                return fake_module_py
            raise ImportError(name)

        mm.path_discovery.base_path = tmp_path
        with patch("importlib.import_module", side_effect=_fake_import):
            result = asyncio.run(mm.load_memory_modules())

        # Post-fix: module MUST be registered; currently FAILS (is discarded)
        assert "test_embeddings_id" in result

    def test_b5_antireg_module_with_get_health_is_registered(self, mm, tmp_path):
        """Anti-reg: module WITH get_health() still registers correctly."""
        mem_path = tmp_path / "memory" / "embeddings"
        mem_path.mkdir(parents=True)
        (mem_path / "manifest.py").touch()

        class FakeEmbeddingsModuleWithHealth:
            @classmethod
            def get_instance(cls):
                return cls()

            async def initialize(self, config=None):
                return True

            def get_health(self):
                return {"status": "ok"}

        fake_manifest = MagicMock()
        fake_manifest.MODULE_ID = "test_embeddings_with_health"

        fake_module_py = MagicMock()
        fake_module_py.EmbeddingsModule = FakeEmbeddingsModuleWithHealth

        def _fake_import(name):
            if name == "memory.embeddings.manifest":
                return fake_manifest
            if name == "memory.embeddings.module":
                return fake_module_py
            raise ImportError(name)

        mm.path_discovery.base_path = tmp_path
        with patch("importlib.import_module", side_effect=_fake_import):
            result = asyncio.run(mm.load_memory_modules())

        assert "test_embeddings_with_health" in result


# ────────────────────────────────────────────────────────────────────────────
# B6 — stop_module STOPPING leak (state no passa a ERROR)
# ────────────────────────────────────────────────────────────────────────────

class TestB6StopModuleStateErrorLeak:

    def test_b6_stop_module_error_sets_state_error(self, lm):
        """xfail: state should be ERROR when stop() raises an exception.

        Current bug (line ~308-314 module_lifecycle.py): the except block catches
        the error, returns False but does NOT update module_info.state. The module
        stays in state=STOPPING forever. Post-fix: state = ModuleState.ERROR.
        """
        mod = _make_module_info("test", state=ModuleState.RUNNING)
        mod.instance = MagicMock()
        mod.instance.stop = MagicMock(side_effect=RuntimeError("shutdown error"))
        lm.modules["test"] = mod

        result = asyncio.run(lm.stop_module("test"))

        assert result is False
        # Post-fix: state MUST be ERROR; currently FAILS (is STOPPING)
        assert mod.state == ModuleState.ERROR

    def test_b6_antireg_stop_module_success_sets_state_stopped(self, lm):
        """Anti-reg: stop_module without error keeps state=STOPPED."""
        mod = _make_module_info("test", state=ModuleState.RUNNING)
        mod.instance = MagicMock()
        mod.instance.stop = MagicMock(return_value=None)
        lm.modules["test"] = mod
        lm.loader.unload_module = AsyncMock()

        result = asyncio.run(lm.stop_module("test"))

        assert result is True
        assert mod.state == ModuleState.STOPPED
